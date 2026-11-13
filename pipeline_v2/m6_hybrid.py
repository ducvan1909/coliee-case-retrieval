"""Durable M6 admission around the accepted M3 arbitrary-query hybrid runtime."""
from dataclasses import asdict, dataclass
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import perf_counter

from .agent_harness import ToolResult
from .agent_harness.contracts import HarnessError, encode, fingerprint, source_hash
from .full_search.hybrid import RUNTIME_DIR, POLICY, CHANNEL_BUDGET, DENSE_CAP, RRF_K, OUTPUT_CAP
from .m4 import _lead
from .sparse_bm25.index import SparseHybridSession

VERSION = 'm6-live-hybrid-v1'
CHANNELS = ('case_bm25', 'passage_bm25', 'dense_passage')


class EmbeddingBudgetExceeded(HarnessError):
    pass


@dataclass(frozen=True)
class EmbeddingBudget:
    max_requests: int
    max_input_tokens: int

    def __post_init__(self):
        if any(type(value) is not int or value < 0 for value in asdict(self).values()):
            raise HarnessError('Embedding caps must be explicit nonnegative integers')


def implementation_binding():
    root = Path(__file__).resolve().parents[1]
    names = ('pipeline_v2/m6_hybrid.py', 'pipeline_v2/full_search/hybrid.py',
             'pipeline_v2/sparse_bm25/index.py', 'pipeline_v2/optimization_v2/runtime.py',
             'pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json')
    return {'version': VERSION, 'files': {name: sha256((root / name).read_bytes()).hexdigest() for name in names},
            'policy': POLICY, 'channel_budget': CHANNEL_BUDGET, 'dense_cap': DENSE_CAP,
            'rrf_k': RRF_K, 'output_cap': OUTPUT_CAP}


class EmbeddingJournal:
    """Append-only reservations and M3 ledger links; never infer known usage from missing receipts."""
    def __init__(self, run_dir, root, budget):
        if not isinstance(budget, EmbeddingBudget):
            raise HarnessError('Explicit EmbeddingBudget required')
        self.root, self.directory, self.budget = Path(root).resolve(), Path(run_dir), budget
        self.path = self.directory / 'embedding_events.sqlite3'
        self.context = None

    def _db(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA synchronous=FULL')
        db.executescript("""CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, body BLOB NOT NULL);
            CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append only'); END;
            CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append only'); END;""")
        return db

    def events(self):
        if not self.path.exists(): return []
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            return [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]

    def append(self, kind, **fields):
        row = {'kind': kind, **fields}
        with closing(self._db()) as db, db:
            db.execute('INSERT INTO events(body) VALUES(?)', (encode(row),))
        return row

    def start_operation(self, action_id, query, case, limit):
        if not source_hash(action_id):
            raise HarnessError('Hybrid search requires a durable M6 action ID')
        operation = fingerprint([action_id, query, case, limit])
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            events = [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]
            if any(row.get('action_id') == action_id for row in events):
                raise HarnessError('Hybrid operation already admitted; never resend an uncertain/completed action')
            row = {'kind': 'search_admitted', 'operation': operation, 'action_id': action_id,
                   'query_sha256': sha256(query.encode('utf-8')).hexdigest(), 'query_case': case, 'limit': limit}
            db.execute('INSERT INTO events(body) VALUES(?)', (encode(row),))
        self.context = operation
        return operation

    def reserve(self, request_id, input_tokens):
        if type(input_tokens) is not int or input_tokens < 1:
            raise HarnessError('Invalid pinned embedding token count')
        ledger = (RUNTIME_DIR / request_id / 'ledger.sqlite3').as_posix()
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            events = [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]
            reservations = [row for row in events if row['kind'] == 'embedding_admitted']
            if self.context is None or any(row['operation'] == self.context for row in reservations):
                raise HarnessError('Expected one embedding reservation per admitted search')
            if len(reservations) >= self.budget.max_requests:
                raise EmbeddingBudgetExceeded('embedding_budget:request_cap')
            if sum(row['reserved_input_tokens'] for row in reservations) + input_tokens > self.budget.max_input_tokens:
                raise EmbeddingBudgetExceeded('embedding_budget:input_token_cap')
            row = {'kind': 'embedding_admitted', 'operation': self.context, 'm3_request_id': request_id,
                   'm3_ledger': ledger, 'reserved_input_tokens': input_tokens}
            db.execute('INSERT INTO events(body) VALUES(?)', (encode(row),))

    def remaining(self):
        reservations = [row for row in self.events() if row['kind'] == 'embedding_admitted']
        return {'requests': self.budget.max_requests - len(reservations),
                'input_tokens': self.budget.max_input_tokens - sum(row['reserved_input_tokens'] for row in reservations)}

    def usage(self):
        events = self.events()
        admissions = [row for row in events if row['kind'] == 'embedding_admitted']
        attempts, links, unknown_reservations = [], [], 0
        for row in admissions:
            path = self.root / row['m3_ledger']
            rows = None
            if path.is_file():
                with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone()
                    if exists:
                        db.row_factory = sqlite3.Row
                        rows = [dict(item) for item in db.execute('SELECT * FROM attempts ORDER BY id')]
            receipt = next((event for event in reversed(events) if event['kind'] == 'embedding_returned'
                            and event.get('m3_request_id') == row['m3_request_id']), None)
            # A returned exception and no M3 attempt means constructor/pre-admission failure, zero inference.
            zero = rows == [] and receipt is not None
            if rows is None or (not rows and not zero):
                unknown_reservations += 1
            for attempt in rows or []:
                if attempt.get('receipt'):
                    attempt['receipt'] = json.loads(attempt['receipt'])
                attempts.append({**attempt, 'm3_request_id': row['m3_request_id'],
                                 'operation': row['operation'], 'm3_ledger': row['m3_ledger']})
            links.append({**row, 'receipt_status': 'known_zero_inference' if zero else
                          'attempts_recorded' if rows else 'unknown', 'attempt_count': len(rows) if rows is not None else None})
        unknown_tokens = sum(row.get('tokens') is None for row in attempts) + unknown_reservations
        known_tokens = sum(row.get('tokens') or 0 for row in attempts)
        known_requests = sum(bool(row.get('receipt')) for row in attempts)
        unknown_attempts = sum(not row.get('receipt') for row in attempts) + unknown_reservations
        latencies = [row.get('elapsed') for row in attempts]
        search_receipts = [row for row in events if row['kind'] == 'search_returned']
        return {'embedding_reservations': len(admissions),
                'reserved_input_tokens': sum(row['reserved_input_tokens'] for row in admissions),
                'known_model_requests': known_requests, 'model_requests': None if unknown_attempts else known_requests,
                'recorded_provider_attempts': len(attempts),
                'known_input_tokens': known_tokens, 'input_tokens': None if unknown_tokens else known_tokens,
                'unknown_token_attempts': unknown_tokens, 'unknown_receipt_attempts': unknown_attempts,
                'provider_attempts': attempts, 'ledger_links': links,
                'reported_client_rpc_seconds': None if unknown_reservations or any(value is None for value in latencies) else sum(latencies),
                'search_operations': sum(row['kind'] == 'search_admitted' for row in events),
                'search_failures': sum(row['status'] == 'error' for row in search_receipts),
                'search_budget_stops': sum(row['status'] == 'budget' for row in search_receipts),
                'search_receipts': search_receipts,
                'unknown_search_operations': sum(row['kind'] == 'search_admitted' for row in events) - len(search_receipts),
                'observed_search_seconds': sum(row['elapsed_seconds'] for row in search_receipts)}


class AccountedSparseHybridSession(SparseHybridSession):
    def __init__(self, root, journal):
        self.m6_journal = journal
        super().__init__(root)

    def _query_embedding(self, query, query_case, request_id):
        from .passages import PinnedTokenizer
        from .retrieval.runtime import render_query
        tokenizer = PinnedTokenizer(self.root, 'pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json')
        tokens = tokenizer.backend.encode(render_query(query, self.profile), add_special_tokens=True).ids
        if not tokens or tokens[-1] != 151643 or len(tokens) > self.profile['embedding']['max_tokens']:
            raise HarnessError('Embedding query token/EOS cap rejected before inference')
        self.m6_journal.reserve(request_id, len(tokens))
        started = perf_counter()
        try:
            result = super()._query_embedding(query, query_case, request_id)
        except Exception as exc:
            self.m6_journal.append('embedding_returned', operation=self.m6_journal.context,
                                   m3_request_id=request_id, status='error', error_type=type(exc).__name__,
                                   observed_elapsed_seconds=perf_counter() - started)
            raise
        self.m6_journal.append('embedding_returned', operation=self.m6_journal.context,
                               m3_request_id=request_id, status='success', provenance=result[1],
                               observed_elapsed_seconds=perf_counter() - started)
        return result


class HybridSearch:
    """Lazy reusable accepted M3 session. Constructing/preparing this object is inference-free."""
    def __init__(self, root, run_dir, budget, *, session_factory=None, execution_mode='real_query',
                 expected_snapshot=None):
        if execution_mode not in ('real_query', 'cached_vector_diagnostic') or (
                execution_mode == 'cached_vector_diagnostic' and session_factory is None):
            raise HarnessError('Cached hybrid diagnostics require an explicit diagnostic session')
        self.root = Path(root).resolve()
        self.journal = EmbeddingJournal(run_dir, self.root, budget)
        self.factory = session_factory or AccountedSparseHybridSession
        self.session = None
        self.execution_mode = execution_mode
        self.expected_snapshot = expected_snapshot
        self.fingerprint = fingerprint([implementation_binding(), asdict(budget), execution_mode, expected_snapshot])

    def search(self, query, query_case, limit, action_id):
        operation = self.journal.start_operation(action_id, query, query_case, limit)
        started = perf_counter()
        try:
            if self.session is None:
                self.session = self.factory(self.root, self.journal)
                if self.expected_snapshot:
                    actual = {
                        'full_manifest_sha256': self.session.lexical.binding['manifest.json'],
                        'sparse_manifest_sha256': self.session.lexical.index_binding['manifest.json'],
                        'embedding_fingerprint': self.session.fingerprint,
                        'collection': self.session.manifest['collection'],
                    }
                    if actual != self.expected_snapshot:
                        self.close()
                        raise HarnessError('Hybrid session snapshot differs from source tools')
            self.session.last_request_id = None
            result = self.session.search(query, query_case, limit)
            if result.get('query_case') != query_case or result.get('query_sha256') != sha256(query.encode('utf-8')).hexdigest():
                raise HarnessError('Hybrid response is not bound to the adaptive issue/query')
            if (result.get('status') != 'ok' or result.get('execution_mode') != self.execution_mode
                    or result.get('policy') != POLICY or set(result.get('channels', {})) != set(CHANNELS)
                    or result.get('model_requests') != int(self.execution_mode == 'real_query')):
                raise HarnessError('Unexpected M3 hybrid result policy or execution mode')
            if self.expected_snapshot and any(result.get(key) != value for key, value in self.expected_snapshot.items()):
                raise HarnessError('Hybrid response snapshot differs from source tools')
            if not isinstance(result.get('hits'), list) or len(result['hits']) > limit:
                raise HarnessError('Hybrid response exceeded the host result cap')
            cases = [hit['case_id'] for hit in result['hits']]
            if query_case in cases or len(cases) != len(set(cases)):
                raise HarnessError('Hybrid response contains query case or duplicate cases')
            self.journal.append('search_returned', operation=operation, status='success',
                                m3_request_id=result.get('request_id'), elapsed_seconds=perf_counter()-started)
            return result
        except Exception as exc:
            status = 'budget' if isinstance(exc, EmbeddingBudgetExceeded) else 'error'
            self.journal.append('search_returned', operation=operation, status=status, error_type=type(exc).__name__,
                                m3_request_id=getattr(self.session, 'last_request_id', None), elapsed_seconds=perf_counter()-started)
            raise
        finally:
            self.journal.context = None

    def usage(self): return self.journal.usage()

    def remaining(self):
        if self.execution_mode == 'cached_vector_diagnostic':
            return None
        return self.journal.remaining()

    def close(self):
        if self.session is not None:
            self.session.close()
            self.session = None


def observation(result, need):
    """Keep fused case order and the supporting passage leads for source reading."""
    hits = []
    for rank, hit in enumerate(result['hits'], 1):
        case = hit['case_id']
        channels = {name: _lead(lead) for name, lead in hit['channels'].items()}
        if any(name not in CHANNELS or lead['case_id'] != case for name, lead in channels.items()):
            raise HarnessError('M3 hybrid channel lead belongs to a different candidate')
        representative = next((channels[name] for name in ('passage_bm25', 'dense_passage')
                               if name in channels and 'open_ref' in channels[name]), {})
        hits.append({**representative, 'case_id': case, 'rank': rank, 'score': hit['score'],
                     'discovery_channel': 'hybrid', 'channels': channels,
                     'channel_ranks': {name: lead['rank'] for name, lead in channels.items()}})
    fields = ('request_id', 'policy', 'execution_mode', 'query_case', 'query_sha256', 'query_vector',
              'embedding_fingerprint', 'full_manifest_sha256', 'sparse_manifest_sha256',
              'collection', 'coverage', 'timings', 'model_requests')
    return ToolResult({**{key: result[key] for key in fields if key in result}, 'hits': hits,
                       'm6_source_need': need}, candidates=tuple(hit['case_id'] for hit in hits))
