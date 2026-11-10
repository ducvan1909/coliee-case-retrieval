"""Compare mmap sparse ranking against an independent scalar SQL oracle."""

from collections import defaultdict
import argparse
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics
import time


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUN = ROOT / 'pipeline_v2/artifacts/m3_full_train_20261108_v1'


def oracle(db, metadata, query, kind, excluded):
    n, avg, k1, b = db.execute('SELECT n,avg,k1,b FROM stats WHERE kind=?', (kind,)).fetchone()
    scores = defaultdict(float)
    for term in sorted(set(re.findall(r'\w+', query.casefold(), re.UNICODE))):
        row = db.execute('SELECT df FROM terms WHERE kind=? AND term=?', (kind, term)).fetchone()
        if row is None:
            continue
        idf = math.log(1 + (n - row[0] + .5) / (row[0] + .5))
        for ident, tf in db.execute('SELECT id,tf FROM postings WHERE kind=? AND term=?', (kind, term)):
            case, length = metadata[kind][ident]
            if case == excluded:
                continue
            scores[ident] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (avg or 1)))
    return sorted(scores.items(), key=lambda row: (-row[1], row[0]))


def assert_hits(actual, expected):
    pairs = [(hit.get('passage_id', hit['case_id']), hit['score']) for hit in actual]
    assert [r[0] for r in pairs] == [r[0] for r in expected], 'Ranked IDs differ'
    assert all(math.isclose(a[1], b[1], abs_tol=1e-10, rel_tol=1e-10)
               for a, b in zip(pairs, expected)), 'Score drift'
    return max((abs(a[1] - b[1]) for a, b in zip(pairs, expected)), default=0)


def main():
    from pipeline_v2.sparse_bm25.index import SparseSession

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index-dir', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workload = json.loads((ROOT / 'pipeline_v2/reviews/m3_search_latency_diagnostic_v1/workload_manifest.json').read_bytes())
    started = time.perf_counter()
    session = SparseSession(ROOT, args.index_dir)
    startup = time.perf_counter() - started
    db = sqlite3.connect((RUN / 'lexical.sqlite3').as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA mmap_size=536870912')
    db.execute('PRAGMA cache_size=-131072')
    metadata = {kind: {ident: (case, length) for ident, case, length in db.execute(
        'SELECT id,case_id,length FROM documents WHERE kind=?', (kind,))} for kind in ('case', 'passage')}
    rows = []
    result = {'status': 'running', 'startup_seconds': startup, 'rows': rows, 'model_requests': 0}
    try:
        for query in workload['queries']:
            for kind in ('case', 'passage'):
                t = time.perf_counter()
                response = session.search(query['text'], kind, 4096, query['query_case'])
                first_seconds = time.perf_counter() - t
                t = time.perf_counter()
                expected = oracle(db, metadata, query['text'], kind, query['query_case'])
                oracle_seconds = time.perf_counter() - t
                deviation = assert_hits(response['hits'], expected[:4096])
                unique = []
                seen = set()
                for pair in expected:
                    case = metadata[kind][pair[0]][0]
                    if case not in seen:
                        seen.add(case)
                        unique.append(pair)
                        if len(unique) == 100:
                            break
                t = time.perf_counter()
                unique_response = session.search(query['text'], kind, 100, query['query_case'], unique_cases=True)
                unique_seconds = time.perf_counter() - t
                deviation = max(deviation, assert_hits(unique_response['hits'], unique))
                repeats = []
                for _ in range(2):
                    t = time.perf_counter()
                    repeated = session.search(query['text'], kind, 100, query['query_case'], unique_cases=True)
                    repeats.append(time.perf_counter() - t)
                    assert_hits(repeated['hits'], unique)
                row = {'query_id': query['query_id'], 'kind': kind, 'status': 'PASS',
                       'raw_4096_seconds': first_seconds, 'scalar_oracle_seconds': oracle_seconds,
                       'unique_100_seconds': unique_seconds, 'unique_100_repeats_seconds': repeats,
                       'max_abs_score_diff': deviation}
                rows.append(row)
                (HERE / 'benchmark_progress.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                print(json.dumps(row), flush=True)
        result['status'] = 'PASS_full_workload_raw_and_unique_parity'
        result['summary'] = {kind: {
            'raw_4096_median_seconds': statistics.median(r['raw_4096_seconds'] for r in rows if r['kind'] == kind),
            'unique_100_median_seconds': statistics.median(r['unique_100_seconds'] for r in rows if r['kind'] == kind),
            'repeated_unique_100_median_seconds': statistics.median(v for r in rows if r['kind'] == kind for v in r['unique_100_repeats_seconds']),
        } for kind in ('case', 'passage')}
    finally:
        session.close()
        db.close()
        result['elapsed_seconds'] = time.perf_counter() - started
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)


if __name__ == '__main__':
    main()
