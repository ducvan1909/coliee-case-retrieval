"""Reproject saved survey/screening boundaries without resending paid work."""
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
    files = [source / 'session/events.sqlite3', source / 'plan.json', source / 'trace.jsonl',
             source / 'result.json', source / 'STOP']
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in files}
    db = sqlite3.connect((source / 'session/events.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        events = [dict(json.loads(row), seq=seq) for seq, row in db.execute('SELECT seq, record FROM events ORDER BY seq')]
    finally:
        db.close()
    admissions = [row for row in events if row['kind'] == 'request_admitted']
    plan = json.loads((source / 'plan.json').read_bytes())
    out.mkdir(parents=True)
    results = []
    with runtime(Path.cwd().resolve(), out, plan['settings'], plan['options'], Trace(out)) as (engine, transport):
        with patch.object(transport, 'send_structured', side_effect=AssertionError('Inference forbidden')), \
             patch.object(engine.harness.hybrid_search, 'search', side_effect=AssertionError('Retrieval forbidden')):
            for turn, expected_offset, expected_seen in ((8, 5, 5), (12, 10, 10), (44, 10, 10)):
                prefix = deepcopy([row for row in events if row['seq'] < admissions[turn - 1]['seq']])
                with patch.object(engine, 'events', return_value=prefix), \
                     patch.object(engine.harness.ledger, 'read', return_value=prefix):
                    prepared = engine.prepare(admit=False)
                    assert prepared['status'] == 'ready', (turn, prepared['status'])
                    names = {branch['properties']['action']['const'] for branch in prepared['manifest']['schema']['anyOf']}
                    assert not names & {'assess_source_need', 'defer_source_need', 'defer_approved_source_need',
                                        'resume_approved_source_need', 'revisit_source_need'}
                    feedback = prepared['payload']['last_action_feedback']
                    assert 'query_gate_progress' not in feedback
                    assert feedback['query_gate_paused']['screening_paused'] is True
                    dispatch = prepared['manifest']['dispatch_m6']
                    control = dispatch['cm_page']['controls']['next_unseen']
                    target = prepared['manifest']['handles'][control]
                    assert target['mode'] == 'results' and target['offset'] == expected_offset, (turn, target)
                    assert dispatch['query_review']['survey_exposed'] == expected_seen
                    assert prepared['input_tokens'] <= 8500
                    assert engine.state().final is None
                    # Preview compilation must not mutate historical state or advance exposure.
                    assert prefix == [row for row in events if row['seq'] < admissions[turn - 1]['seq']]
                    (out / f'turn-{turn}-preview.json').write_bytes(encode(prepared))
                    results.append({'before_turn': turn, 'status': 'PASS', 'input_tokens': prepared['input_tokens'],
                                    'survey_exposed': expected_seen, 'next_unseen_offset': target['offset'],
                                    'gate_mutations_offered': False})
    assert before == {str(p): sha256(p.read_bytes()).hexdigest() for p in files}
    report = {'status': 'PASS', 'source_run': str(source), 'source_controller_requests': len(admissions),
              'checks': results, 'code_binding': binding(), 'historical_files_unchanged': True,
              'controller_requests_this_check': 0, 'embedding_requests_this_check': 0,
              'retrieval_requests_this_check': 0}
    (out / 'report.json').write_bytes(encode(report))
    print(json.dumps({k: v for k, v in report.items() if k != 'code_binding'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
