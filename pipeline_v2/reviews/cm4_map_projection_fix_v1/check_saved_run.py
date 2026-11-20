"""Read-only, zero-inference projection of a saved CM4 search boundary."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from pipeline_v2.agent_harness.contracts import encode
from pipeline_v2.experiments.context_manager_v2.live import runtime, binding
from pipeline_v2.experiments.uncapped_probe.runner import Trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source_run.resolve(), args.out_dir.resolve()
    if out.exists() or out == source or out.is_relative_to(source):
        raise ValueError('Use a fresh output directory outside the historical run')
    protected = [source / 'session/events.sqlite3', source / 'plan.json', source / 'trace.jsonl']
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in protected}
    db = sqlite3.connect((source / 'session/events.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        events = [dict(json.loads(row), seq=seq) for seq, row in db.execute('SELECT seq, record FROM events ORDER BY seq')]
    finally:
        db.close()
    plan = json.loads((source / 'plan.json').read_bytes())
    out.mkdir(parents=True)
    trace = Trace(out)
    with runtime(Path.cwd().resolve(), out, plan['settings'], plan['options'], trace) as (engine, transport):
        backend = engine.harness.hybrid_search
        with patch.object(transport, 'send_structured', side_effect=AssertionError('Inference forbidden')), \
             patch.object(backend, 'search', side_effect=AssertionError('Retrieval forbidden')), \
             patch.object(engine, 'events', return_value=events), \
             patch.object(engine.harness.ledger, 'read', return_value=events):
            results = engine.prepare(admit=False)
            assert results['status'] == 'ready', results['status']
            assert 'query_navigation' not in results['payload']['m6']
            progress = results['payload']['m6']['query_review']
            assert progress['phase'] == 'surveying' and progress['survey_exposed'] == 0
            context = deepcopy(engine.context())
            context.update(mode='query', candidate_id=None, stage='ready', offset=0, back=[])
            with patch.object(engine, 'context', return_value=context):
                query = engine.prepare(admit=False)
            assert query['status'] == 'ready', query['status']
            page = query['manifest']['dispatch_m6']['query_navigation']
            page_tokens = engine.harness.m3.page_tokens(page)
            assert page_tokens <= plan['settings']['query_navigation']['map_max_tokens']
            assert results['input_tokens'] <= 8500 and query['input_tokens'] <= 8500
            (out / 'results_preview.json').write_bytes(encode(results))
            (out / 'query_preview.json').write_bytes(encode(query))
            report = {'status': 'PASS', 'source_run': str(source), 'code_binding': binding(),
                      'source_events': len(events), 'source_controller_requests': len(engine.state().requests),
                      'results_input_tokens': results['input_tokens'], 'query_input_tokens': query['input_tokens'],
                      'query_map_tokens': page_tokens, 'query_map_cap': 2400,
                      'survey_exposed': progress['survey_exposed'], 'retrieved': progress['retrieved'],
                      'controller_requests_this_check': 0, 'embedding_requests_this_check': 0,
                      'retrieval_requests_this_check': 0}
    after = {str(p): sha256(p.read_bytes()).hexdigest() for p in protected}
    assert before == after, 'Historical evidence changed'
    report['historical_files_unchanged'] = True
    (out / 'report.json').write_bytes(encode(report))
    print(json.dumps({key: value for key, value in report.items() if key != 'code_binding'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
