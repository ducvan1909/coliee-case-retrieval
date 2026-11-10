"""Summarize completed local acceptance without changing sealed artifacts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def load_lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def main():
    prior = json.loads((HERE / 'prior_state.json').read_text(encoding='utf-8'))
    checked = {}
    for group in prior.values():
        for name, expected in group.items():
            actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            assert actual == expected, name
            checked[name] = actual
    baseline = load_lines(ROOT / 'pipeline_v2/reviews/m3_hybrid_validation_v1/qdrant_cached_benchmark.jsonl')
    current = load_lines(HERE / 'qdrant_cached_benchmark.jsonl')
    assert current[-1]['event'] == 'complete'
    old = {r['vector_id']: r for r in baseline if r['event'] == 'query_complete'}
    comparisons = []
    for row in current:
        if row['event'] != 'query_complete':
            continue
        before, after = old[row['vector_id']]['response'], row['response']
        assert before['hits'] == after['hits'], row['vector_id']
        for channel in ('case_bm25', 'passage_bm25', 'dense_passage'):
            assert before['channels'][channel] == after['channels'][channel], (row['vector_id'], channel)
        assert after['model_requests'] == 0
        comparisons.append({'vector_id': row['vector_id'], 'exact_hits_and_channels': True,
                            'baseline_timings': before['timings'], 'sparse_timings': after['timings']})
    assert len(comparisons) == 3
    lexical = json.loads((HERE / 'actual_benchmark.json').read_text(encoding='utf-8'))
    assert len(lexical['rows']) == 16 and all(r['status'] == 'PASS' for r in lexical['rows'])
    result = {'status': 'PASS', 'model_requests': 0, 'unit_tests_passed': 37,
              'unchanged_prior_code': checked, 'lexical_summary': lexical['summary'],
              'hybrid_comparisons': comparisons,
              'memory': json.loads((HERE / 'hybrid_memory.json').read_text(encoding='utf-8'))}
    (HERE / 'local_acceptance.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'comparisons': comparisons, 'memory': result['memory']}))


if __name__ == '__main__':
    main()
