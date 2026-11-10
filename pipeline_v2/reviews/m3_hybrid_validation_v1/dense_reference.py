"""Independent full-corpus cosine reference over committed cache shards."""

import argparse
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

from pipeline_v2.full_corpus.storage import ReadonlyCache


ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / 'pipeline_v2/artifacts/m3_full_train_20261108_v1'
WORKLOAD = ROOT / 'pipeline_v2/reviews/m3_search_latency_diagnostic_v1/workload_manifest.json'


def batch_rows(db, batch):
    return db.execute(
        "SELECT s.passage_id, json_extract(d.metadata,'$.exact_input_sha256'), d.case_id "
        "FROM schedule s JOIN documents d ON d.kind='passage' AND d.id=s.passage_id "
        'WHERE s.batch=? ORDER BY s.ordinal', (batch,)
    ).fetchall()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((RUN / 'manifest.json').read_bytes())
    fixtures = json.loads(WORKLOAD.read_bytes())['diagnostic_dense_vectors']
    cache = ReadonlyCache(RUN, manifest['embedding_fingerprint'], manifest['profile']['embedding']['dimensions'])
    db = sqlite3.connect((RUN / 'lexical.sqlite3').as_uri() + '?mode=ro', uri=True)
    started = time.perf_counter()
    try:
        queries = []
        for fixture in fixtures:
            rows = batch_rows(db, fixture['schedule_batch'])
            i = fixture['batch_row_index']
            assert rows[i][0] == fixture['passage_id']
            queries.append(cache.get_batch([r[0] for r in rows], [r[1] for r in rows])[i])
        queries = np.asarray(queries, dtype=np.float64)
        queries /= np.linalg.norm(queries, axis=1, keepdims=True)
        all_ids = []
        scores = np.empty((manifest['passages'], len(fixtures)), dtype=np.float64)
        for batch in range(manifest['batches']):
            rows = batch_rows(db, batch)
            ids = [r[0] for r in rows]
            vectors = cache.get_batch(ids, [r[1] for r in rows]).astype(np.float64)
            vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
            block = vectors @ queries.T
            for j, fixture in enumerate(fixtures):
                exclude = fixture['query_case_excluded']
                block[[r[2] == exclude for r in rows], j] = -np.inf
            scores[len(all_ids):len(all_ids) + len(ids)] = block
            all_ids.extend(ids)
        assert len(all_ids) == manifest['passages']
        id_array = np.asarray(all_ids)
        results = {}
        for j, fixture in enumerate(fixtures):
            best = np.lexsort((id_array, -scores[:, j]))[:4097]
            results[fixture['vector_id']] = [{'passage_id': all_ids[i], 'score': float(scores[i, j])} for i in best]
        out = {'mode': 'offline_exact_cache_reference_not_qdrant',
               'points_scanned': len(all_ids), 'elapsed_seconds': time.perf_counter() - started,
               'results': results}
        with args.output.open('x', encoding='utf-8') as f:
            json.dump(out, f)
        print(f"Offline exact reference scanned {len(all_ids)} points in {out['elapsed_seconds']:.2f}s")
    finally:
        db.close()


if __name__ == '__main__':
    main()
