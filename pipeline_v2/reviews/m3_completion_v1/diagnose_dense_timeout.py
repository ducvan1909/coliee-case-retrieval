"""Isolate Qdrant search using the same checked cached vector as M3."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from pipeline_v2.full_corpus.storage import ReadonlyCache
from pipeline_v2.full_search.hybrid import _ScheduleVectors
from pipeline_v2.optimization_v2.index import PersistentBM25


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unfiltered-control', action='store_true')
    args = parser.parse_args()
    run = ROOT / 'pipeline_v2/artifacts/m3_full_train_20261108_v1'
    manifest = json.loads((run / 'manifest.json').read_bytes())
    fingerprint = manifest['embedding_fingerprint']
    with requests.Session() as session:
        session.trust_env = False
        lexical = PersistentBM25(run / 'lexical.sqlite3')
        try:
            passage = '095448:88b488d43fde1389756a8dd7'
            cache = ReadonlyCache(run, fingerprint, 2560)
            vector = _ScheduleVectors(lexical, cache).select([passage])[passage].tolist()
        finally:
            lexical.close()
        collection = manifest['collection']
        base = f'http://127.0.0.1:6333/collections/{collection}'
        fingerprint_filter = {'key': 'embedding_fingerprint', 'match': {'value': fingerprint}}
        query_case_filter = {'key': 'case_id', 'match': {'value': '095448.txt'}}
        full = {'must': [fingerprint_filter], 'must_not': [query_case_filter]}
        narrow = {'must': [fingerprint_filter, query_case_filter]}
        variants = (
            ('narrow_exact', narrow, 20, False, 15),
            ('m3_exact', full, 4096, True, 120),
            ('full_exact_without_payload', full, 1, False, 60),
        )
        if args.unfiltered_control:
            variants = (('unfiltered_exact_without_payload', None, 1, False, 90),)
        path = Path(__file__).with_name(f'dense_timeout_requests_{time.time_ns()}.jsonl')
        with path.open('x', encoding='utf-8') as stream:
            for name, condition, limit, payload, deadline in variants:
                row = {'probe': name, 'started_utc': datetime.now(timezone.utc).isoformat(),
                       'server_timeout_seconds': deadline, 'limit': limit,
                       'with_payload': payload, 'exact': True, 'model_requests': 0}
                print(json.dumps(row), flush=True)
                start = time.perf_counter()
                try:
                    request = {'query': vector, 'limit': limit, 'with_payload': payload,
                               'with_vector': False, 'params': {'exact': True}}
                    if condition is not None:
                        request['filter'] = condition
                    response = session.post(base + '/points/query', params={'timeout': deadline},
                                            json=request, timeout=deadline + 15)
                    body = response.json()
                    row.update(http_status=response.status_code, server_seconds=body.get('time'),
                               usage=body.get('usage'), result_count=len(body.get('result', {}).get('points', [])),
                               qdrant_status=body.get('status'))
                except (requests.RequestException, ValueError) as exc:
                    row.update(error_type=type(exc).__name__, error=str(exc))
                row.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                           wall_seconds=time.perf_counter() - start)
                line = json.dumps(row)
                stream.write(line + '\n')
                stream.flush()
                print(line, flush=True)
        print(path, flush=True)


if __name__ == '__main__':
    main()
