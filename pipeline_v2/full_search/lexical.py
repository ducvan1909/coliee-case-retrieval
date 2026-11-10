"""Join-free, vectorized BM25 with the frozen analyzer and exact ranking policy."""
import json
import math
from pathlib import Path
import re
import sqlite3
import time

import numpy as np

from ..optimization_v2.common import M3Error, file_digest, read
from ..retrieval.bm25 import analyze
from ..source.core import canonical, digest


PROFILE = 'pipeline_v2/configs/m3_lexical.json'
DEFAULT_RUN = 'pipeline_v2/artifacts/m3_full_train_20261108_v1'


def implementation():
    root = Path(__file__).resolve().parents[2]
    names = ['pipeline_v2/full_search/__init__.py',
             'pipeline_v2/full_search/lexical.py', 'pipeline_v2/m3_lexical.py']
    return {name: file_digest(root / name) for name in names}


def load_profile(root):
    p = read(Path(root) / PROFILE)
    if p.get('schema_version') != 'pipeline-v2-m3-lexical-1' or p.get('full_run') != DEFAULT_RUN:
        raise M3Error('Unsupported lexical profile')
    if p.get('analyzer') != 'unicode_word_casefold_no_stopwords_v1':
        raise M3Error('Unsupported lexical analyzer')
    for field, low, high in [('cache_mib', 1, 512), ('mmap_mib', 0, 2048),
                             ('fetch_size', 64, 16384), ('max_limit', 1, 16384)]:
        if type(p.get(field)) is not int or not low <= p[field] <= high:
            raise M3Error('Invalid lexical profile field: ' + field)
    return p


class FastBM25:
    """Preload small columns, stream postings, score float64 vectors per block.

    The database is always read-only. The caller owns snapshot validation; use
    LexicalSession for production full-run access. No raw text/vector preload.
    """
    def __init__(self, path, cache_mib=128, mmap_mib=512, fetch_size=4096):
        for name, value, low, high in [('cache_mib', cache_mib, 1, 512),
                                       ('mmap_mib', mmap_mib, 0, 2048),
                                       ('fetch_size', fetch_size, 64, 16384)]:
            if type(value) is not int or not low <= value <= high:
                raise M3Error('Invalid ' + name)
        started = time.perf_counter()
        self.path = Path(path).resolve()
        self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        self.fetch_size = fetch_size
        self.channels = {}
        try:
            self.db.execute('PRAGMA query_only=ON')
            self.db.execute('PRAGMA cache_size=' + str(-cache_mib * 1024))
            self.db.execute('PRAGMA mmap_size=' + str(mmap_mib * 1024 * 1024))
            self.pragmas = {key: self.db.execute('PRAGMA ' + key).fetchone()[0]
                            for key in ('query_only', 'cache_size', 'mmap_size')}
            for kind in ('case', 'passage'):
                stats = self.db.execute('SELECT n,avg,k1,b FROM stats WHERE kind=?', (kind,)).fetchone()
                if stats is None:
                    raise M3Error('Missing lexical channel: ' + kind)
                n, avg, k1, b = stats
                if (type(n) is not int or n < 0 or not all(math.isfinite(x) for x in (avg, k1, b))
                        or avg < 0 or k1 <= 0 or not 0 <= b <= 1):
                    raise M3Error('Invalid BM25 statistics')
                ids, cases, lengths = [], [], []
                case_codes = {}
                for ident, case, length in self.db.execute(
                        'SELECT id,case_id,length FROM documents WHERE kind=? ORDER BY id', (kind,)):
                    if (not isinstance(ident, str) or not ident or not isinstance(case, str)
                            or re.fullmatch(r'[0-9]{6}\.txt', case) is None
                            or type(length) is not int or length < 0):
                        raise M3Error('Invalid lexical document columns')
                    ids.append(ident)
                    cases.append(case_codes.setdefault(case, len(case_codes)))
                    lengths.append(length)
                if len(ids) != n or len(set(ids)) != n:
                    raise M3Error('Lexical statistics/document count mismatch')
                array = np.asarray(lengths, dtype=np.float64)
                if n and not math.isclose(float(array.mean()), avg, rel_tol=1e-12, abs_tol=1e-12):
                    raise M3Error('Lexical average length mismatch')
                self.channels[kind] = {
                    'ids': ids, 'ordinals': {ident: i for i, ident in enumerate(ids)},
                    'case_codes': case_codes, 'cases': np.asarray(cases, dtype=np.int32),
                    'norm': k1 * (1 - b + b * array / (avg or 1)),
                    'n': n, 'avg': avg, 'k1': k1, 'b': b,
                }
            self.preload_seconds = time.perf_counter() - started
        except BaseException:
            self.db.close()
            raise

    def get_many(self, kind, ids):
        found = {}
        for offset in range(0, len(ids), 256):
            block = ids[offset:offset + 256]
            sql = 'SELECT id,metadata FROM documents WHERE kind=? AND id IN (' + ','.join('?' for _ in block) + ')'
            for ident, body in self.db.execute(sql, [kind, *block]):
                found[ident] = json.loads(body)
        if set(found) != set(ids):
            raise M3Error('Missing lexical hit metadata')
        result = [found[ident] for ident in ids]
        for ident, doc in zip(ids, result):
            channel = self.channels[kind]
            if ('text' in doc or doc.get('passage_id', doc.get('case_id')) != ident
                    or channel['case_codes'].get(doc.get('case_id'))
                    != channel['cases'][channel['ordinals'][ident]]):
                raise M3Error('Lexical hit metadata differs from immutable columns')
        return result

    @staticmethod
    def _top(scores, limit):
        """Select exact top-K; all boundary ties resolve by sorted ID ordinal."""
        positive = np.flatnonzero(scores > 0)
        if len(positive) > limit:
            threshold = np.partition(scores[positive], len(positive) - limit)[len(positive) - limit]
            above = positive[scores[positive] > threshold]
            equal = positive[scores[positive] == threshold]
            positive = np.concatenate((above, equal[:limit - len(above)]))
        return positive[np.lexsort((positive, -scores[positive]))]

    def search_detailed(self, query, kind, limit=1024, exclude_case=None, unique_cases=False):
        if (not isinstance(query, str) or kind not in self.channels or type(limit) is not int
                or not 1 <= limit <= 16384 or type(unique_cases) is not bool):
            raise M3Error('Invalid lexical query/channel/limit/mode')
        if exclude_case is not None and (not isinstance(exclude_case, str)
                or re.fullmatch(r'[0-9]{6}\.txt', exclude_case) is None):
            raise M3Error('Invalid query case ID')
        started = time.perf_counter()
        channel = self.channels[kind]
        scores = np.zeros(channel['n'], dtype=np.float64)
        excluded = channel['case_codes'].get(exclude_case)
        rows_seen = terms_seen = 0
        fetch_seconds = score_seconds = 0.0
        for term in sorted(set(analyze(query))):
            row = self.db.execute('SELECT df FROM terms WHERE kind=? AND term=?', (kind, term)).fetchone()
            if row is None:
                continue
            df = row[0]
            if type(df) is not int or not 0 <= df <= channel['n']:
                raise M3Error('Invalid lexical document frequency')
            terms_seen += 1
            idf = math.log(1 + (channel['n'] - df + .5) / (df + .5))
            fetched = 0
            t = time.perf_counter()
            cursor = self.db.execute('SELECT id,tf FROM postings WHERE kind=? AND term=?', (kind, term))
            fetch_seconds += time.perf_counter() - t
            while True:
                t = time.perf_counter()
                block = cursor.fetchmany(self.fetch_size)
                fetch_seconds += time.perf_counter() - t
                if not block:
                    break
                t = time.perf_counter()
                try:
                    indices = np.fromiter((channel['ordinals'][p[0]] for p in block), dtype=np.intp, count=len(block))
                except KeyError as exc:
                    raise M3Error('Posting points outside immutable document universe') from exc
                if any(type(p[1]) is not int or p[1] <= 0 for p in block):
                    raise M3Error('Invalid posting frequency')
                tf = np.fromiter((p[1] for p in block), dtype=np.float64, count=len(block))
                fetched += len(block)
                if excluded is not None:
                    keep = channel['cases'][indices] != excluded
                    indices, tf = indices[keep], tf[keep]
                # PRIMARY KEY(kind,term,id) ensures unique indices per term.
                scores[indices] += idf * tf * (channel['k1'] + 1) / (tf + channel['norm'][indices])
                score_seconds += time.perf_counter() - t
            rows_seen += fetched
            if fetched != df:
                raise M3Error('Posting count differs from frozen document frequency')
        t = time.perf_counter()
        if unique_cases:
            all_hits = self._top(scores, max(1, channel['n']))
            seen, selected = set(), []
            for i in all_hits:
                case = int(channel['cases'][i])
                if case not in seen:
                    seen.add(case); selected.append(i)
                    if len(selected) == limit:
                        break
            chosen = np.asarray(selected, dtype=np.intp)
        else:
            chosen = self._top(scores, limit)
        top_seconds = time.perf_counter() - t
        ids = [channel['ids'][i] for i in chosen]
        t = time.perf_counter()
        hits = [{**doc, 'score': float(scores[i])} for i, doc in zip(chosen, self.get_many(kind, ids))]
        meta_seconds = time.perf_counter() - t
        return {'hits': hits, 'channel': kind, 'unique_cases': unique_cases,
                'query_case_excluded': exclude_case, 'terms_matched': terms_seen,
                'postings_rows': rows_seen, 'matched_documents': int(np.count_nonzero(scores > 0)),
                'timings': {'total_seconds': time.perf_counter() - started,
                            'postings_fetch_seconds': fetch_seconds, 'mapping_and_scoring_seconds': score_seconds,
                            'top_selection_seconds': top_seconds, 'metadata_seconds': meta_seconds},
                'model_requests': 0}

    def search(self, query, kind, limit=1024, exclude_case=None, unique_cases=False):
        return self.search_detailed(query, kind, limit, exclude_case, unique_cases)['hits']

    def close(self):
        self.db.close()


class LexicalSession:
    """Validated immutable full snapshot; revalidate explicitly after changes."""
    def __init__(self, root, run_dir=None):
        self.root = Path(root).resolve()
        self.profile = load_profile(self.root)
        self.run_dir = run_dir or self.profile['full_run']
        if self.run_dir != self.profile['full_run']:
            raise M3Error('Lexical session requires the frozen full run')
        self.code = implementation()
        self.invalidated = False
        self.reader = None
        try:
            self._open()
        except BaseException:
            self.close()
            raise

    def _open(self):
        started = time.perf_counter()
        from ..full_corpus.runner import load_plan
        _, self.directory, self.manifest, lexical = load_plan(self.root, self.run_dir)
        lexical.close()
        self.binding = {name: file_digest(self.directory / name) for name in ('manifest.json', 'seal.json')}
        self.reader = FastBM25(self.directory / 'lexical.sqlite3', self.profile['cache_mib'],
                              self.profile['mmap_mib'], self.profile['fetch_size'])
        self.initialization_seconds = time.perf_counter() - started
        self.guard()

    def guard(self):
        from ..full_corpus.common import implementation as full_code, load_profile as full_profile
        try:
            if (self.invalidated or self.profile != load_profile(self.root) or self.code != implementation()
                    or self.manifest['implementation'] != full_code()
                    or self.manifest['profile'] != full_profile(self.root)
                    or any(file_digest(self.directory / name) != sha for name, sha in self.binding.items())):
                raise M3Error('Lexical snapshot invalidated; reopen after verifying dependencies')
        except BaseException:
            self.invalidated = True
            raise

    def revalidate(self):
        self.guard()
        from ..full_corpus.runner import load_plan
        try:
            _, _, manifest, lexical = load_plan(self.root, self.run_dir)
            lexical.close()
            if manifest != self.manifest:
                raise M3Error('Full manifest changed')
        except BaseException:
            self.invalidated = True
            raise
        return {'status': 'immutable_snapshot_revalidated', 'model_requests': 0}

    def search(self, query, kind, limit=1024, exclude_case=None, unique_cases=False):
        self.guard()
        if type(limit) is not int or not 1 <= limit <= self.profile['max_limit']:
            raise M3Error('Limit exceeds lexical profile')
        result = self.reader.search_detailed(query, kind, limit, exclude_case, unique_cases)
        self.guard()
        result.update(scope='all_train_cases_and_passages',
                      implementation_sha256=digest(canonical(self.code)),
                      full_manifest_sha256=self.binding['manifest.json'],
                      snapshot_contract='validated_at_open_explicit_revalidate_after_changes',
                      session_initialization_seconds=self.initialization_seconds,
                      preload_seconds=self.reader.preload_seconds, sqlite_pragmas=self.reader.pragmas)
        return result

    def close(self):
        if self.reader is not None:
            self.reader.close()
