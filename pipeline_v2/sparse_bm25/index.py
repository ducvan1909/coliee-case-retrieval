"""Read-only eager BM25 arrays with bounded-memory construction and retrieval."""

import json
import math
from pathlib import Path
import re
import sqlite3
import time

import numpy as np

from ..full_corpus.runner import load_plan
from ..optimization_v2.common import artifact, file_digest, read
from ..retrieval.bm25 import analyze
from ..retrieval.common import M3Error, write_json
from ..source.core import canonical, digest
from ..full_search.lexical import FastBM25


PROFILE = 'pipeline_v2/configs/m3_sparse.json'
KINDS = ('case', 'passage')


def implementation():
    root = Path(__file__).resolve().parents[2]
    from ..full_corpus.common import implementation as full_code
    from ..full_search.lexical import implementation as lexical_code
    from ..full_search.hybrid import implementation as hybrid_code
    result = {**full_code(), **lexical_code(), **hybrid_code()}
    names = ['pipeline_v2/m3_sparse.py', 'pipeline_v2/sparse_bm25/__init__.py',
             'pipeline_v2/sparse_bm25/index.py']
    result.update({name: file_digest(root / name) for name in names})
    return result


def load_profile(root):
    profile = read(Path(root) / PROFILE)
    expected = {'schema_version': 'pipeline-v2-m3-sparse-1',
                'full_run': 'pipeline_v2/artifacts/m3_full_train_20261108_v1',
                'analyzer': 'unicode_word_casefold_no_stopwords_v1',
                'score_dtype': 'float64', 'doc_index_dtype': 'uint32',
                'offset_dtype': 'uint64'}
    if any(profile.get(key) != value for key, value in expected.items()):
        raise M3Error('Unsupported sparse profile')
    for key, low, high in [('fetch_size', 64, 65536), ('score_block_size', 64, 1048576),
                           ('metadata_cache_mib', 1, 128), ('max_limit', 1, 16384)]:
        if type(profile.get(key)) is not int or not low <= profile[key] <= high:
            raise M3Error('Invalid sparse profile setting: ' + key)
    artifact(root, profile['index_dir'])
    return profile


def _close_arrays(channels):
    for channel in channels.values():
        for value in channel.values():
            if isinstance(value, np.memmap):
                value.flush()
                value._mmap.close()


def _open_database(database):
    db = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA cache_size=-32768')
    return db


def _prepare_channel(db, target, kind):
    stats = db.execute('SELECT n,avg,k1,b FROM stats WHERE kind=?', (kind,)).fetchone()
    if stats is None:
        raise M3Error('Missing channel statistics')
    n, avg, k1, b = stats
    if (type(n) is not int or not 0 <= n <= np.iinfo(np.uint32).max
            or not all(math.isfinite(x) for x in (avg, k1, b))
            or avg < 0 or k1 <= 0 or not 0 <= b <= 1):
        raise M3Error('Invalid sparse statistics')
    documents = list(db.execute('SELECT id,case_id,length FROM documents WHERE kind=? ORDER BY id', (kind,)))
    if len(documents) != n or len({row[0] for row in documents}) != n:
        raise M3Error('Sparse document count mismatch')
    if any(not isinstance(i, str) or not i or not isinstance(c, str)
           or re.fullmatch(r'[0-9]{6}\.txt', c) is None or type(length) is not int or length < 0
           for i, c, length in documents):
        raise M3Error('Invalid sparse document fields')
    lengths = np.asarray([row[2] for row in documents], dtype=np.float64)
    if n and not math.isclose(float(lengths.mean()), avg, rel_tol=1e-12, abs_tol=1e-12):
        raise M3Error('Sparse average length mismatch')
    ids = [row[0] for row in documents]
    cases = sorted({row[1] for row in documents})
    case_codes = {case: i for i, case in enumerate(cases)}
    document_cases = np.asarray([case_codes[row[1]] for row in documents], dtype=np.uint32)
    terms = list(db.execute('SELECT term,df FROM terms WHERE kind=? ORDER BY term', (kind,)))
    if any(not isinstance(term, str) or not term or type(df) is not int or not 0 < df <= n for term, df in terms):
        raise M3Error('Invalid sparse term frequency')
    offsets = np.zeros(len(terms) + 1, dtype=np.uint64)
    offsets[1:] = np.cumsum([df for _, df in terms], dtype=np.uint64)
    total = int(offsets[-1])
    np.save(target / f'{kind}.indptr.npy', offsets, allow_pickle=False)
    np.save(target / f'{kind}.cases.npy', document_cases, allow_pickle=False)
    write_json(target / f'{kind}.catalog.json', {'ids': ids, 'cases': cases, 'terms': [term for term, _ in terms]})
    return {
        'n': n, 'avg': avg, 'k1': k1, 'b': b, 'postings': total, 'terms': len(terms),
        'indices': np.lib.format.open_memmap(target / f'{kind}.indices.npy', mode='w+', dtype=np.uint32, shape=(total,)),
        'values': np.lib.format.open_memmap(target / f'{kind}.values.npy', mode='w+', dtype=np.float64, shape=(total,)),
        'ordinals': {ident: i for i, ident in enumerate(ids)},
        'term_ids': {term: i for i, (term, _) in enumerate(terms)},
        'offsets': offsets, 'next': offsets[:-1].copy(),
        'idf': np.asarray([math.log(1 + (n - df + .5) / (df + .5)) for _, df in terms], dtype=np.float64),
        'norm': k1 * (1 - b + b * lengths / (avg or 1)),
    }


def build_from_database(database, output, bindings=None, fetch_size=8192):
    """Fixture-capable builder. Output must be new and source is always read-only."""
    if type(fetch_size) is not int or not 64 <= fetch_size <= 65536:
        raise M3Error('Invalid sparse builder fetch size')
    database, target = Path(database).resolve(), Path(output).resolve()
    if target.exists():
        raise M3Error('Sparse output already exists')
    started = time.perf_counter()
    source_hash = file_digest(database)
    db = _open_database(database)
    channels = {}
    target.mkdir(parents=True, exist_ok=False)
    try:
        for kind in KINDS:
            channels[kind] = _prepare_channel(db, target, kind)
        total = sum(channel['postings'] for channel in channels.values())
        completed = 0
        last_checkpoint = started
        # Sequential source-table scan avoids term-index lookups followed by rowid reads.
        cursor = db.execute('SELECT kind,term,id,tf FROM postings NOT INDEXED ORDER BY rowid')
        while True:
            block = cursor.fetchmany(fetch_size)
            if not block:
                break
            grouped = {kind: [] for kind in KINDS}
            for kind, term, ident, frequency in block:
                if kind not in channels or type(frequency) is not int or frequency <= 0:
                    raise M3Error('Invalid sparse posting')
                channel = channels[kind]
                try:
                    term_id = channel['term_ids'][term]
                    ordinal = channel['ordinals'][ident]
                except KeyError as exc:
                    raise M3Error('Posting outside sparse universe') from exc
                position = int(channel['next'][term_id])
                if position >= int(channel['offsets'][term_id + 1]):
                    raise M3Error('Posting count exceeds document frequency')
                channel['next'][term_id] += 1
                grouped[kind].append((position, term_id, ordinal, frequency))
            for kind, records in grouped.items():
                if not records:
                    continue
                channel = channels[kind]
                positions, terms, ordinals, frequencies = np.asarray(records, dtype=np.int64).T
                tf = frequencies.astype(np.float64)
                values = (channel['idf'][terms] * tf * (channel['k1'] + 1)
                          / (tf + channel['norm'][ordinals]))
                channel['indices'][positions] = ordinals
                channel['values'][positions] = values
            completed += len(block)
            if time.perf_counter() - last_checkpoint >= 5:
                write_json(target / 'build_progress.json', {'phase': 'postings', 'completed': completed,
                           'total': total, 'elapsed_seconds': time.perf_counter() - started}, replace=True)
                last_checkpoint = time.perf_counter()
        if completed != total:
            raise M3Error('Sparse total posting count mismatch')
        for kind, channel in channels.items():
            if not np.array_equal(channel['next'], channel['offsets'][1:]):
                raise M3Error('Incomplete sparse term postings')
            write_json(target / 'build_progress.json', {'phase': 'sort_and_validate', 'channel': kind,
                       'completed': completed, 'total': total}, replace=True)
            for start, end in zip(channel['offsets'][:-1], channel['offsets'][1:]):
                start, end = int(start), int(end)
                indices = channel['indices'][start:end]
                order = np.argsort(indices, kind='stable')
                sorted_ids = np.asarray(indices[order])
                if len(sorted_ids) > 1 and np.any(sorted_ids[1:] <= sorted_ids[:-1]):
                    raise M3Error('Duplicate document in sparse term postings')
                values = np.asarray(channel['values'][start:end][order])
                if not np.isfinite(values).all() or np.any(values <= 0):
                    raise M3Error('Invalid precomputed BM25 contribution')
                channel['indices'][start:end] = sorted_ids
                channel['values'][start:end] = values
        _close_arrays(channels)
        if file_digest(database) != source_hash:
            raise M3Error('Source database changed while building sparse index')
        manifest = {'schema_version': 'pipeline-v2-sparse-bm25-index-1',
                    'database_sha256': source_hash, 'bindings': bindings or {},
                    'analyzer': 'unicode_word_casefold_no_stopwords_v1',
                    'channels': {kind: {key: channel[key] for key in ('n', 'avg', 'k1', 'b', 'postings', 'terms')}
                                 for kind, channel in channels.items()},
                    'elapsed_seconds': time.perf_counter() - started,
                    'format': {'indices': 'uint32', 'values': 'float64', 'indptr': 'uint64'}}
        write_json(target / 'manifest.json', manifest)
        names = ['manifest.json'] + [f'{kind}.{suffix}' for kind in KINDS for suffix in
                                    ('catalog.json', 'cases.npy', 'indptr.npy', 'indices.npy', 'values.npy')]
        seal = {name: {'sha256': file_digest(target / name), 'bytes': (target / name).stat().st_size} for name in names}
        write_json(target / 'seal.json', seal)
        return {'status': 'sparse_index_built', 'index_dir': str(target),
                'postings': completed, 'bytes': sum(entry['bytes'] for entry in seal.values()),
                'seconds': time.perf_counter() - started, 'model_requests': 0}
    finally:
        db.close()
        for channel in channels.values():
            for value in channel.values():
                if isinstance(value, np.memmap) and not value._mmap.closed:
                    value._mmap.close()


def build_sparse(root, output):
    root = Path(root).resolve()
    target = artifact(root, output)
    profile, code = load_profile(root), implementation()
    _, run, manifest, lexical = load_plan(root, profile['full_run'])
    lexical.close()
    bindings = {'profile': profile, 'implementation': code,
                'full_manifest_sha256': file_digest(run / 'manifest.json'),
                'full_seal_sha256': file_digest(run / 'seal.json')}
    result = build_from_database(run / 'lexical.sqlite3', target, bindings, profile['fetch_size'])
    if profile != load_profile(root) or code != implementation():
        # Remove the completion marker, preserving partial artifacts for diagnosis.
        (target / 'seal.json').unlink()
        raise M3Error('Sparse builder code or profile changed')
    return result


class SparseBM25:
    """Term-contiguous mmap arrays, with metadata fetched only for retained hits."""

    def __init__(self, database, index_dir, validate_database=True, score_block_size=65536, metadata_cache_mib=32):
        self.directory = Path(index_dir).resolve()
        self.database = Path(database).resolve()
        self.db = None
        self.channels = {}
        self.score_block_size = score_block_size
        if type(score_block_size) is not int or not 64 <= score_block_size <= 1048576:
            raise M3Error('Invalid sparse score block size')
        if type(metadata_cache_mib) is not int or not 1 <= metadata_cache_mib <= 128:
            raise M3Error('Invalid sparse metadata cache size')
        started = time.perf_counter()
        try:
            self.manifest = read(self.directory / 'manifest.json')
            sealed = read(self.directory / 'seal.json')
            expected = {'manifest.json'} | {f'{kind}.{suffix}' for kind in KINDS for suffix in
                                           ('catalog.json', 'cases.npy', 'indptr.npy', 'indices.npy', 'values.npy')}
            if set(sealed) != expected:
                raise M3Error('Incomplete sparse index seal')
            for name, entry in sealed.items():
                path = self.directory / name
                if path.is_symlink() or entry != {'sha256': file_digest(path), 'bytes': path.stat().st_size}:
                    raise M3Error('Sparse index seal drift')
            if self.manifest.get('schema_version') != 'pipeline-v2-sparse-bm25-index-1':
                raise M3Error('Unsupported sparse index schema')
            if validate_database and file_digest(self.database) != self.manifest['database_sha256']:
                raise M3Error('Sparse source database drift')
            self.db = _open_database(self.database)
            self.db.execute('PRAGMA cache_size=' + str(-metadata_cache_mib * 1024))
            for kind in KINDS:
                catalog = read(self.directory / f'{kind}.catalog.json')
                channel = {key: np.load(self.directory / f'{kind}.{suffix}.npy', mmap_mode='r', allow_pickle=False)
                           for key, suffix in [('indices', 'indices'), ('values', 'values'), ('offsets', 'indptr'), ('cases', 'cases')]}
                self.channels[kind] = channel
                channel['ids'] = catalog['ids']
                channel['terms'] = catalog['terms']
                channel['case_names'] = catalog['cases']
                channel['term_ids'] = {term: i for i, term in enumerate(catalog['terms'])}
                channel['ordinals'] = {ident: i for i, ident in enumerate(catalog['ids'])}
                channel['case_codes'] = {case: i for i, case in enumerate(catalog['cases'])}
                channel['n'] = self.manifest['channels'][kind]['n']
                if (channel['indices'].dtype != np.uint32 or channel['values'].dtype != np.float64
                        or channel['offsets'].dtype != np.uint64 or channel['cases'].dtype != np.uint32
                        or channel['indices'].shape != channel['values'].shape
                        or channel['indices'].shape != (self.manifest['channels'][kind]['postings'],)
                        or channel['offsets'].shape != (len(catalog['terms']) + 1,)
                        or channel['cases'].shape != (channel['n'],)
                        or len(catalog['ids']) != channel['n']
                        or catalog['ids'] != sorted(set(catalog['ids']))
                        or catalog['terms'] != sorted(set(catalog['terms']))
                        or catalog['cases'] != sorted(set(catalog['cases']))
                        or len(catalog['terms']) != self.manifest['channels'][kind]['terms']
                        or (len(channel['cases']) and int(channel['cases'].max()) >= len(catalog['cases']))
                        or int(channel['offsets'][0]) != 0
                        or int(channel['offsets'][-1]) != len(channel['indices'])
                        or np.any(channel['offsets'][1:] < channel['offsets'][:-1])):
                    raise M3Error('Sparse array schema mismatch')
                for start, end in zip(channel['offsets'][:-1], channel['offsets'][1:]):
                    start, end = int(start), int(end)
                    indices = channel['indices'][start:end]
                    values = channel['values'][start:end]
                    if (start == end or int(indices[-1]) >= channel['n']
                            or np.any(indices[1:] <= indices[:-1])
                            or not np.isfinite(values).all() or np.any(values <= 0)):
                        raise M3Error('Invalid sparse term arrays')
            self.preload_seconds = time.perf_counter() - started
        except BaseException:
            self.close()
            raise

    get_many = FastBM25.get_many
    _top = staticmethod(FastBM25._top)

    def search_detailed(self, query, kind, limit=1024, exclude_case=None, unique_cases=False):
        if (not isinstance(query, str) or kind not in self.channels or type(limit) is not int
                or not 1 <= limit <= 16384 or type(unique_cases) is not bool):
            raise M3Error('Invalid sparse query/channel/limit/mode')
        if exclude_case is not None and (not isinstance(exclude_case, str) or re.fullmatch(r'[0-9]{6}\.txt', exclude_case) is None):
            raise M3Error('Invalid excluded case ID')
        started = time.perf_counter()
        channel = self.channels[kind]
        scores = np.zeros(channel['n'], dtype=np.float64)
        terms_matched = postings = 0
        for term in sorted(set(analyze(query))):
            term_id = channel['term_ids'].get(term)
            if term_id is None:
                continue
            terms_matched += 1
            start, end = map(int, channel['offsets'][term_id:term_id + 2])
            postings += end - start
            for offset in range(start, end, self.score_block_size):
                stop = min(end, offset + self.score_block_size)
                indices = channel['indices'][offset:stop]
                scores[indices] += channel['values'][offset:stop]
        excluded = channel['case_codes'].get(exclude_case)
        if excluded is not None:
            scores[channel['cases'] == excluded] = 0
        scoring_seconds = time.perf_counter() - started
        positive_count = int(np.count_nonzero(scores > 0))
        selection_start = time.perf_counter()
        if unique_cases:
            best = np.zeros(len(channel['case_codes']), dtype=np.float64)
            np.maximum.at(best, channel['cases'], scores)
            representatives = np.full(len(best), channel['n'], dtype=np.uint32)
            candidates = np.flatnonzero((scores > 0) & (scores == best[channel['cases']]))
            np.minimum.at(representatives, channel['cases'][candidates], candidates.astype(np.uint32))
            ranked_cases = sorted(np.flatnonzero(best > 0), key=lambda code: (-best[code], int(representatives[code])))[:limit]
            chosen = np.asarray([representatives[code] for code in ranked_cases], dtype=np.intp)
        else:
            chosen = self._top(scores, limit)
        top_seconds = time.perf_counter() - selection_start
        ids = [channel['ids'][i] for i in chosen]
        meta_start = time.perf_counter()
        hits = [{**doc, 'score': float(scores[i])} for i, doc in zip(chosen, self.get_many(kind, ids))]
        return {'hits': hits, 'channel': kind, 'unique_cases': unique_cases,
                'query_case_excluded': exclude_case, 'terms_matched': terms_matched,
                'postings_rows': postings, 'matched_documents': positive_count,
                'model_requests': 0, 'timings': {'total_seconds': time.perf_counter() - started,
                'array_scoring_seconds': scoring_seconds, 'top_selection_seconds': top_seconds,
                'metadata_seconds': time.perf_counter() - meta_start}}

    def search(self, query, kind, limit=1024, exclude_case=None, unique_cases=False):
        return self.search_detailed(query, kind, limit, exclude_case, unique_cases)['hits']

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        for channel in self.channels.values():
            for value in channel.values():
                if isinstance(value, np.memmap) and not value._mmap.closed:
                    value._mmap.close()


class SparseSession:
    """Full-plan validation at open, with an immutable sparse search snapshot."""

    def __init__(self, root, index_dir=None):
        self.root = Path(root).resolve()
        self.profile = load_profile(self.root)
        self.directory = artifact(self.root, self.profile['full_run'])
        self.index_dir = artifact(self.root, index_dir or self.profile['index_dir'])
        self.code = implementation()
        self.invalidated = False
        self.reader = None
        started = time.perf_counter()
        try:
            _, _, self.manifest, lexical = load_plan(self.root, self.profile['full_run'])
            lexical.close()
            self.binding = {name: file_digest(self.directory / name) for name in ('manifest.json', 'seal.json')}
            # load_plan already checked this database's entire content hash.
            index_manifest = read(self.index_dir / 'manifest.json')
            database_hash = read(self.directory / 'seal.json')['lexical.sqlite3']['sha256']
            if index_manifest['database_sha256'] != database_hash:
                raise M3Error('Sparse source database binding differs')
            self.reader = SparseBM25(self.directory / 'lexical.sqlite3', self.index_dir, validate_database=False,
                                    score_block_size=self.profile['score_block_size'],
                                    metadata_cache_mib=self.profile['metadata_cache_mib'])
            expected = {'profile': self.profile, 'implementation': self.code,
                        'full_manifest_sha256': self.binding['manifest.json'],
                        'full_seal_sha256': self.binding['seal.json']}
            if self.reader.manifest['bindings'] != expected:
                raise M3Error('Sparse artifact dependencies differ')
            self.index_binding = {name: file_digest(self.index_dir / name) for name in ('manifest.json', 'seal.json')}
            self.initialization_seconds = time.perf_counter() - started
            self.guard()
        except BaseException:
            self.close()
            raise

    def guard(self):
        from ..full_corpus.common import load_profile as full_profile
        try:
            if (self.invalidated or self.profile != load_profile(self.root) or self.code != implementation()
                    or self.manifest['profile'] != full_profile(self.root)
                    or any(file_digest(self.directory / name) != value for name, value in self.binding.items())
                    or any(file_digest(self.index_dir / name) != value for name, value in self.index_binding.items())):
                raise M3Error('Sparse snapshot invalidated')
        except BaseException:
            self.invalidated = True
            raise

    def revalidate(self):
        self.guard()
        # Construct and close a fresh session so every seal and raw source is checked again.
        try:
            fresh = SparseSession(self.root, self.index_dir)
            fresh.close()
        except BaseException:
            self.invalidated = True
            raise
        return {'status': 'sparse_snapshot_revalidated', 'model_requests': 0}

    def search(self, query, kind, limit=1024, exclude_case=None, unique_cases=False):
        self.guard()
        if type(limit) is not int or not 1 <= limit <= self.profile['max_limit']:
            raise M3Error('Sparse search limit exceeds profile')
        result = self.reader.search_detailed(query, kind, limit, exclude_case, unique_cases)
        self.guard()
        result.update(scope='all_train_cases_and_passages', implementation_sha256=digest(canonical(self.code)),
                      session_initialization_seconds=self.initialization_seconds,
                      full_manifest_sha256=self.binding['manifest.json'])
        return result

    def close(self):
        if self.reader is not None:
            self.reader.close()


from ..full_search.hybrid import HybridSession, FullQdrant, _readiness, _ScheduleVectors, HTTP_TIMEOUT_SECONDS
from ..full_corpus.storage import ReadonlyCache


class SparseHybridSession(HybridSession):
    """Use the accepted dense/fusion adapter with sparse lexical arrays."""

    def __init__(self, root, index_dir=None):
        started = time.perf_counter()
        self.root = Path(root).resolve()
        self.last_request_id = None
        self.lexical = SparseSession(self.root, index_dir)
        self.db = None
        try:
            self.manifest = self.lexical.manifest
            self.profile = self.manifest['profile']
            self.fingerprint = self.manifest['embedding_fingerprint']
            self.dimensions = self.profile['embedding']['dimensions']
            self.code = implementation()
            self.code_sha256 = digest(canonical(self.code))
            _readiness(self)
            self.db = FullQdrant(self.profile['qdrant']['url'], self.manifest['collection'], self.fingerprint,
                                 self.dimensions, timeout=HTTP_TIMEOUT_SECONDS)
            self.vectors = _ScheduleVectors(self.lexical.reader, ReadonlyCache(self.lexical.directory, self.fingerprint, self.dimensions))
            self.initialization_seconds = time.perf_counter() - started
        except BaseException:
            self.close()
            raise

    def _guard(self):
        self.lexical.guard()
        if self.code != implementation():
            raise M3Error('Sparse hybrid implementation drift')
        _readiness(self)

    def _search(self, query, query_case, limit, passage_id):
        result = super()._search(query, query_case, limit, passage_id)
        result['lexical_backend'] = 'eager_sparse_float64_mmap_v1'
        result['sparse_manifest_sha256'] = self.lexical.index_binding['manifest.json']
        return result
