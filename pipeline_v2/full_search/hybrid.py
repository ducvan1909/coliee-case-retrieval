"""Full-corpus lexical and exact dense retrieval with case-level fusion."""

from collections import OrderedDict, defaultdict
import math
from pathlib import Path
import re
import time
from uuid import uuid4

import numpy as np

from ..full_corpus.runner import execution_state
from ..full_corpus.storage import FullQdrant, PAYLOAD, ReadonlyCache
from ..optimization_v2.common import file_digest, implementation as v2_implementation, read
from ..optimization_v2.runtime import OptModalEmbedder, request_embedding
from ..passages import PinnedTokenizer
from ..retrieval.cache import Cache, validate_vectors
from ..retrieval.common import M3Error
from ..retrieval.qdrant import point_id
from ..retrieval.runtime import render_query
from ..source.core import canonical, digest
from .lexical import LexicalSession


CHANNEL_BUDGET = 100
DENSE_CAP = 4096
OUTPUT_CAP = 20
RRF_K = 60
SERVER_TIMEOUT_SECONDS = 120
HTTP_TIMEOUT_SECONDS = 135
SCORE_ATOL = 1e-5
TIE_ATOL = 1e-6
SHARD_CACHE_SIZE = 32
POLICY = 'm3-full-hybrid-exact-rrf-v1'
RUNTIME_DIR = Path('pipeline_v2/artifacts/m3_full_search_runtime_v1')
VERIFY_RECEIPT = Path('pipeline_v2/reviews/m3_full_ag_review_v1/step5_verify_stdout.json')
VERIFY_RECEIPT_SHA256 = 'b841927b07e001435779a3575e3abccfd0f564e81680e63b801f39049b0ccd08'
VERIFIED_MANIFEST_SHA256 = '7bdf2bb5dda4b324147f5332f4c4a0ed95b15a953b2d3c40fe9f184ca74d45b0'


def implementation():
    root = Path(__file__).resolve().parents[2]
    return {name: file_digest(root / name) for name in (
        'pipeline_v2/full_search/hybrid.py', 'pipeline_v2/m3_hybrid.py')}


def _check_limit(limit):
    if type(limit) is not int or not 1 <= limit <= OUTPUT_CAP:
        raise M3Error(f'Hybrid limit must be between 1 and {OUTPUT_CAP}')


def _best_cases(hits):
    best = []
    seen = set()
    for hit in hits:
        case = hit['case_id']
        if case not in seen:
            seen.add(case)
            best.append({**hit, 'rank': len(best) + 1})
            if len(best) == CHANNEL_BUDGET:
                break
    return best


def fuse_channels(channels, limit=OUTPUT_CAP):
    """RRF over case ranks with one vote per case and channel."""
    _check_limit(limit)
    leads = defaultdict(dict)
    for channel, hits in channels.items():
        for hit in _best_cases(hits):
            leads[hit['case_id']][channel] = hit
    rows = [{'case_id': case, 'channels': matches,
             'score': math.fsum(1 / (RRF_K + hit['rank']) for hit in matches.values())}
            for case, matches in leads.items()]
    return sorted(rows, key=lambda row: (-row['score'], row['case_id']))[:limit]


def validate_dense_hits(points, reader, fingerprint, query_case):
    """Check the returned order and bind every dense hit to sealed metadata."""
    ids = []
    seen = set()
    previous = math.inf
    for point in points:
        if not isinstance(point, dict):
            raise M3Error('Malformed dense point')
        payload = point.get('payload')
        score = point.get('score')
        if not isinstance(payload, dict) or payload.get('embedding_fingerprint') != fingerprint:
            raise M3Error('Missing or foreign dense payload')
        ident = payload.get('passage_id')
        if not isinstance(ident, str) or ident in seen or point.get('id') != point_id(ident, fingerprint):
            raise M3Error('Duplicate or invalid dense point ID')
        if payload.get('case_id') == query_case:
            raise M3Error('Dense search returned the excluded query case')
        if (type(score) not in (int, float) or not math.isfinite(score)
                or not -1 - SCORE_ATOL <= score <= 1 + SCORE_ATOL or score > previous):
            raise M3Error('Invalid dense score or non-descending score order')
        ids.append(ident)
        seen.add(ident)
        previous = score
    metadata = reader.get_many('passage', ids)
    rows = []
    for point, passage in zip(points, metadata, strict=True):
        payload = point['payload']
        if any(key not in payload or key not in passage or payload[key] != passage[key] for key in PAYLOAD):
            raise M3Error('Dense payload differs from sealed lexical metadata')
        rows.append({**passage, 'score': point['score']})
    # Stable ordering of ties within the returned set. A capped reply may omit ties.
    return sorted(rows, key=lambda row: (-row['score'], row['passage_id']))


def _readiness(session):
    lexical = session.lexical
    verify = session.root / VERIFY_RECEIPT
    if (lexical.binding['manifest.json'] != VERIFIED_MANIFEST_SHA256
            or file_digest(verify) != VERIFY_RECEIPT_SHA256):
        raise M3Error('Full verification receipt or manifest binding changed')
    receipt = read(verify)
    required = {
        'status': 'PASS', 'execution_mode': 'real_local_DB',
        'method': 'all_expected_unique_ids_payload_vectors_plus_exact_count_batched64',
        'collection': session.manifest['collection'], 'points': session.manifest['passages'],
    }
    if any(receipt.get(key) != value for key, value in required.items()):
        raise M3Error('Full verification receipt does not cover this collection')
    expected_state = execution_state(lexical.directory, session.manifest, 'real_modal')
    if read(lexical.directory / 'execution_state.json') != expected_state:
        raise M3Error('Full collection lacks matching real ingestion state')


class _ScheduleVectors:
    """Look up passage vectors by batch with a bounded cache of checked shards."""

    def __init__(self, reader, cache):
        self.reader = reader
        self.cache = cache
        self.shards = OrderedDict()

    def _shard(self, batch):
        if batch not in self.shards:
            ids = [row[0] for row in self.reader.db.execute(
                'SELECT passage_id FROM schedule WHERE batch=? ORDER BY ordinal', (batch,))]
            docs = self.reader.get_many('passage', ids)
            vectors = self.cache.get_batch(ids, [doc['exact_input_sha256'] for doc in docs])
            if vectors is None:
                raise M3Error('Missing checked vector shard')
            self.shards[batch] = ({ident: row for row, ident in enumerate(ids)}, vectors)
            if len(self.shards) > SHARD_CACHE_SIZE:
                self.shards.popitem(last=False)
        self.shards.move_to_end(batch)
        return self.shards[batch]

    def select(self, ids):
        groups = defaultdict(list)
        for offset in range(0, len(ids), 256):
            block = ids[offset:offset + 256]
            placeholders = ','.join('?' for _ in block)
            for ident, batch in self.reader.db.execute(
                    f'SELECT passage_id,batch FROM schedule WHERE passage_id IN ({placeholders})', block):
                groups[batch].append(ident)
        if sum(map(len, groups.values())) != len(ids):
            raise M3Error('Passage missing from sealed vector schedule')
        selected = {}
        for batch, members in groups.items():
            offsets, vectors = self._shard(batch)
            for ident in members:
                selected[ident] = vectors[offsets[ident]].copy()
        return selected


class HybridSession:
    """Reuse one validated lexical snapshot and local dense connection."""

    def __init__(self, root):
        started = time.perf_counter()
        self.root = Path(root).resolve()
        self.last_request_id = None
        self.lexical = LexicalSession(self.root)
        self.db = None
        try:
            self.manifest = self.lexical.manifest
            self.profile = self.manifest['profile']
            self.fingerprint = self.manifest['embedding_fingerprint']
            self.dimensions = self.profile['embedding']['dimensions']
            self.code = implementation()
            self.code_sha256 = digest(canonical(self.code))
            _readiness(self)
            self.db = FullQdrant(self.profile['qdrant']['url'], self.manifest['collection'],
                                 self.fingerprint, self.dimensions, timeout=HTTP_TIMEOUT_SECONDS)
            self.vectors = _ScheduleVectors(
                self.lexical.reader, ReadonlyCache(self.lexical.directory, self.fingerprint, self.dimensions))
            self.initialization_seconds = time.perf_counter() - started
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def close(self):
        try:
            if self.db is not None:
                self.db.session.close()
        finally:
            self.lexical.close()

    def _guard(self):
        self.lexical.guard()
        if self.code != implementation():
            raise M3Error('Hybrid implementation changed during session')
        _readiness(self)

    def _compatibility(self):
        binding = self.manifest['compatibility']
        receipt = self.root / binding['receipt']
        index = self.root / self.profile['compatibility_index']
        pointer = index.parent / (index.name + '_runtime') / 'compatibility_current.json'
        if (file_digest(receipt) != binding['sha256']
                or read(receipt.with_name('compatibility.sha256.json')) != {'sha256': binding['sha256']}
                or read(pointer) != {'status': 'PASS', 'receipt': binding['receipt'],
                                     'receipt_sha256': binding['sha256']}):
            raise M3Error('V2 query compatibility changed during hybrid session')

    def _check_db(self):
        self.db.check_schema()
        if self.db.count() != self.manifest['passages']:
            raise M3Error('Full DB count differs from the verified manifest')

    def _validate_input(self, query, query_case, limit):
        _check_limit(limit)
        if (not isinstance(query_case, str) or re.fullmatch(r'[0-9]{6}\.txt', query_case) is None
                or query_case not in self.manifest['source_hashes']):
            raise M3Error('Hybrid search requires a query case in the sealed train corpus')
        if not isinstance(query, str) or not query.strip():
            raise M3Error('Hybrid query must be a nonempty string')

    def _dense(self, vector, query_case):
        vector = validate_vectors([vector], 1, self.dimensions)[0]
        channel = self.lexical.reader.channels['passage']
        excluded = channel['case_codes'].get(query_case)
        excluded_points = 0 if excluded is None else int(np.count_nonzero(channel['cases'] == excluded))
        eligible = self.manifest['passages'] - excluded_points
        scan_limit = min(DENSE_CAP, eligible)
        condition = {
            'must': [{'key': 'embedding_fingerprint', 'match': {'value': self.fingerprint}}],
            'must_not': [{'key': 'case_id', 'match': {'value': query_case}}],
        }
        started = time.perf_counter()
        response = self.db._request('POST', self.db.path + f'/points/query?timeout={SERVER_TIMEOUT_SECONDS}', {
            'query': vector.tolist(), 'limit': scan_limit, 'filter': condition,
            'with_payload': True, 'with_vector': False, 'params': {'exact': True},
        }) if scan_limit else {'points': []}
        query_seconds = time.perf_counter() - started
        points = response['points']
        if len(points) != scan_limit:
            raise M3Error('Dense exact search returned an unexpected number of eligible points')
        started = time.perf_counter()
        hits = validate_dense_hits(points, self.lexical.reader, self.fingerprint, query_case)
        best = _best_cases(hits)
        check = {hit['passage_id']: hit for hit in best}
        if hits:
            check[hits[-1]['passage_id']] = hits[-1]
        vectors = self.vectors.select(list(check))
        query_vector = np.asarray(vector, dtype=np.float64)
        query_vector /= np.linalg.norm(query_vector)
        for ident, hit in check.items():
            candidate = np.asarray(vectors[ident], dtype=np.float64)
            cosine = float(query_vector @ candidate / np.linalg.norm(candidate))
            if not math.isclose(cosine, hit['score'], abs_tol=SCORE_ATOL, rel_tol=0):
                raise M3Error('Dense hit score differs from the checked cached vector')
        verify_seconds = time.perf_counter() - started
        capped = len(hits) < eligible
        tie_near_boundary = bool(capped and best and math.isclose(
            best[-1]['score'], hits[-1]['score'], abs_tol=TIE_ATOL, rel_tol=0))
        coverage = {
            'requested_unique_cases': CHANNEL_BUDGET, 'returned_unique_cases': len(best),
            'raw_hits': len(hits), 'eligible_points': eligible, 'scan_limit': scan_limit,
            'universe_exhausted': not capped, 'scan_capped': capped,
            'budget_shortfall': len(best) < CHANNEL_BUDGET,
            'complete_for_requested_budget': len(best) == CHANNEL_BUDGET and not tie_near_boundary,
            'raw_boundary_tie': 'unknown_at_scan_cap' if capped else 'no_omitted_points',
            'retained_case_boundary_tie_possible': tie_near_boundary,
            'validated_payload_hits': len(hits), 'validated_cached_scores': len(check),
            'score_validation_scope': 'retained_best_case_leads_and_last_raw_hit',
        }
        return best, coverage, {'dense_query_seconds': query_seconds, 'dense_validation_seconds': verify_seconds}

    def _lexical(self, query, query_case):
        channels, coverage, timings = {}, {}, {}
        for kind in ('case', 'passage'):
            name = f'{kind}_bm25'
            started = time.perf_counter()
            response = self.lexical.search(query, kind, CHANNEL_BUDGET, query_case, unique_cases=True)
            timings[f'{name}_seconds'] = time.perf_counter() - started
            hits = _best_cases(response['hits'])
            channels[name] = hits
            coverage[name] = {
                'requested_unique_cases': CHANNEL_BUDGET, 'returned_unique_cases': len(hits),
                'positive_documents_scored': response['matched_documents'],
                'scan_capped': False, 'universe_exhausted': True,
                'budget_shortfall': len(hits) < CHANNEL_BUDGET,
                'complete_for_requested_budget': len(hits) == CHANNEL_BUDGET,
            }
        return channels, coverage, timings

    def _query_embedding(self, query, query_case, request_id):
        self._compatibility()
        tokenizer = PinnedTokenizer(self.root, 'pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json')
        rendered = render_query(query, self.profile)
        tokens = tokenizer.backend.encode(rendered, add_special_tokens=True).ids
        if not tokens or tokens[-1] != 151643 or len(tokens) > self.profile['embedding']['max_tokens']:
            raise M3Error('Query with instruction exceeds the token cap or has invalid EOS')
        directory = self.root / RUNTIME_DIR / request_id
        if directory.resolve() != directory:
            raise M3Error('Hybrid runtime ledger must stay in its dedicated artifact directory')
        directory.mkdir(parents=True, exist_ok=False)
        ledger = Cache(directory, self.fingerprint, self.dimensions)
        try:
            vectors, response = request_embedding(
                OptModalEmbedder(self.profile), [query], 'query', self.profile, tokenizer,
                v2_implementation(), ledger, f'{query_case}:{digest(rendered.encode("utf-8"))}')
            return vectors[0], {
                'kind': 'attested_v2_query_embedding', 'input_tokens': response['input_tokens'],
                'padded_tokens': response['padded_tokens'], 'rendered_input_sha256': response['input_hashes'][0],
                'client_rpc_seconds': response['client_elapsed_seconds'],
                'remote_seconds': response['remote_elapsed_seconds'],
                'ledger': (RUNTIME_DIR / request_id / 'ledger.sqlite3').as_posix(),
            }
        finally:
            ledger.db.close()

    def _search(self, query, query_case, limit, passage_id):
        started = time.perf_counter()
        self._validate_input(query, query_case, limit)
        request_id = uuid4().hex
        self.last_request_id = request_id
        self._guard()
        if passage_id is not None:
            if not isinstance(passage_id, str) or not passage_id:
                raise M3Error('Invalid diagnostic passage ID')
            passage, = self.lexical.reader.get_many('passage', [passage_id])
            if passage['case_id'] != query_case:
                raise M3Error('Diagnostic passage must belong to the query case')
        channels, coverage, timings = self._lexical(query, query_case)
        self._guard()
        check_started = time.perf_counter()
        self._check_db()
        timings['dense_readiness_seconds'] = time.perf_counter() - check_started
        embed_started = time.perf_counter()
        if passage_id is None:
            vector, provenance = self._query_embedding(query, query_case, request_id)
        else:
            vector = self.vectors.select([passage_id])[passage_id]
            provenance = {'kind': 'cached_document_vector_diagnostic', 'passage_id': passage_id,
                          'source_hash': passage['source_hash'], 'span_bytes': passage['span_bytes'],
                          'input_sha256': passage['exact_input_sha256']}
        timings['query_vector_seconds'] = time.perf_counter() - embed_started
        channels['dense_passage'], coverage['dense_passage'], dense_timings = self._dense(vector, query_case)
        timings.update(dense_timings)
        self._guard()
        if passage_id is None:
            self._compatibility()
        hits = fuse_channels(channels, limit)
        timings['total_seconds'] = time.perf_counter() - started
        return {
            'status': 'ok', 'request_id': request_id, 'policy': POLICY,
            'execution_mode': 'real_query' if passage_id is None else 'cached_vector_diagnostic',
            'query_case': query_case, 'query_sha256': digest(query.encode('utf-8')),
            'query_vector': provenance, 'model_requests': int(passage_id is None),
            'eligible_case_universe': self.manifest['cases'] - 1,
            'full_manifest_sha256': self.lexical.binding['manifest.json'],
            'full_verification_receipt_sha256': VERIFY_RECEIPT_SHA256,
            'embedding_fingerprint': self.fingerprint, 'collection': self.manifest['collection'],
            'implementation_sha256': self.code_sha256,
            'readiness_scope': 'historical_full_verify_plus_live_schema_count_and_returned_hit_checks',
            'session_initialization_seconds': self.initialization_seconds,
            'hits': hits, 'channels': channels, 'coverage': coverage, 'timings': timings,
        }

    def search(self, query, query_case, limit=OUTPUT_CAP):
        return self._search(query, query_case, limit, None)

    def search_cached(self, query, query_case, passage_id, limit=OUTPUT_CAP):
        if passage_id is None:
            raise M3Error('Cached diagnostic requires a passage ID')
        return self._search(query, query_case, limit, passage_id)
