"""Replay the three fixed M3 diagnostic vectors through a single hybrid session."""

import argparse
from contextlib import nullcontext
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch

from pipeline_v2.full_corpus.runner import source_path
from pipeline_v2.full_corpus.storage import PAYLOAD
from pipeline_v2.full_search.hybrid import HybridSession
from pipeline_v2.retrieval.qdrant import point_id


ROOT = Path(__file__).resolve().parents[3]
WORKLOAD = ROOT / 'pipeline_v2/reviews/m3_search_latency_diagnostic_v1/workload_manifest.json'
RUN = ROOT / 'pipeline_v2/artifacts/m3_full_train_20261108_v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_response(response, excluded):
    assert response['status'] == 'ok' and response['model_requests'] == 0
    assert response['eligible_case_universe'] == 7707
    assert set(response['channels']) == {'case_bm25', 'passage_bm25', 'dense_passage'}
    votes = {}
    for channel, leads in response['channels'].items():
        cases = [lead['case_id'] for lead in leads]
        assert excluded not in cases and len(set(cases)) == len(cases) <= 100
        assert response['coverage'][channel]['returned_unique_cases'] == len(cases)
        for rank, case in enumerate(cases, 1):
            votes.setdefault(case, []).append(1 / (60 + rank))
    scores = {case: math.fsum(values) for case, values in votes.items()}
    expected = sorted(scores, key=lambda case: (-scores[case], case))[:20]
    assert [hit['case_id'] for hit in response['hits']] == expected
    assert all(hit['score'] == scores[hit['case_id']] for hit in response['hits'])


class OfflineDenseReplay:
    """Replay offline exact results through the hybrid adapter's response checks."""

    path = '/offline_reference'

    def __init__(self, _url, collection, fingerprint, _dimensions, *, timeout, reference, fixtures):
        manifest = json.loads((RUN / 'manifest.json').read_bytes())
        assert (collection, fingerprint) == (manifest['collection'], manifest['embedding_fingerprint'])
        assert reference['mode'] == 'offline_exact_cache_reference_not_qdrant'
        assert reference['points_scanned'] == manifest['passages']
        self.points = manifest['passages']
        self.fp = fingerprint
        self.by_case = {f['query_case_excluded']: reference['results'][f['vector_id']] for f in fixtures}
        self.session = sqlite3.connect((RUN / 'lexical.sqlite3').as_uri() + '?mode=ro', uri=True)

    def check_schema(self):
        pass  # This replay has no Qdrant schema.

    def count(self):
        return self.points

    def _request(self, method, path, body):
        assert method == 'POST' and '/points/query?timeout=' in path
        assert body['params'] == {'exact': True} and body['with_vector'] is False
        assert body['filter']['must'] == [{'key': 'embedding_fingerprint', 'match': {'value': self.fp}}]
        case = body['filter']['must_not'][0]['match']['value']
        points = []
        for hit in self.by_case[case][:body['limit']]:
            passage_id = hit['passage_id']
            row = self.session.execute("SELECT metadata FROM documents WHERE kind='passage' AND id=?",
                                       (passage_id,)).fetchone()
            meta = json.loads(row[0])
            payload = {key: meta[key] for key in PAYLOAD}
            payload['embedding_fingerprint'] = self.fp
            points.append({'id': point_id(passage_id, self.fp), 'score': hit['score'], 'payload': payload})
        return {'points': points}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--offline-reference', type=Path)
    args = parser.parse_args()
    workload_bytes = WORKLOAD.read_bytes()
    fixtures = json.loads(workload_bytes)['diagnostic_dense_vectors']
    backend = 'offline_cache_replay' if args.offline_reference else 'qdrant_exact_local'
    db_override = nullcontext()
    if args.offline_reference:
        reference = json.loads(args.offline_reference.read_bytes())
        db_override = patch('pipeline_v2.full_search.hybrid.FullQdrant',
                            lambda *a, **kw: OfflineDenseReplay(*a, **kw, reference=reference, fixtures=fixtures))
    with args.output.open('x', encoding='utf-8') as evidence:
        def record(row):
            evidence.write(json.dumps(row, ensure_ascii=True) + '\n')
            evidence.flush()

        record({'event': 'started', 'workload_sha256': sha(workload_bytes),
                'vector_ids': [row['vector_id'] for row in fixtures],
                'mode': 'cached_document_vector_diagnostic', 'dense_backend': backend})
        session = None
        started = time.perf_counter()
        try:
            with db_override:
                session = HybridSession(ROOT)
                record({'event': 'session_opened', 'seconds': time.perf_counter() - started})
                for fixture in fixtures:
                    case_id = fixture['query_case_excluded']
                    raw = source_path(ROOT, case_id).read_bytes()
                    span = raw[slice(*fixture['span_bytes'])]
                    if sha(raw) != fixture['source_hash'] or sha(span) != fixture['exact_input_sha256']:
                        raise ValueError('Diagnostic fixture source or span drift')
                    request_start = time.perf_counter()
                    response = session.search_cached(span.decode('utf-8'), case_id, fixture['passage_id'])
                    seconds = time.perf_counter() - request_start
                    check_response(response, case_id)
                    record({'event': 'query_complete', 'vector_id': fixture['vector_id'],
                            'dense_backend': backend, 'case_id': case_id, 'seconds': seconds, 'response': response})
                    print(f"{fixture['vector_id']} {seconds:.3f}s", flush=True)
        except BaseException as exc:
            record({'event': 'failed', 'error_type': type(exc).__name__,
                    'seconds': time.perf_counter() - started})
            raise
        finally:
            if session is not None:
                session.close()
        record({'event': 'complete', 'seconds': time.perf_counter() - started})


if __name__ == '__main__':
    main()
