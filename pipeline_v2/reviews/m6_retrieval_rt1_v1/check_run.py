"""Check RT1 capture/action/observation links locally; no retrieval or model calls."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from pipeline_v2.agent_harness.contracts import HarnessError, encode
from pipeline_v2.agent_harness.evidence import slice_record
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.m6_hybrid import observation
from pipeline_v2.retrieval_diagnostics import inspect_run, verify_capture


def check_run(run_dir):
    run_dir = Path(run_dir).resolve()
    diagnostics = inspect_run(run_dir)
    events = Ledger(run_dir).read()
    if not events:
        raise HarnessError('An M6 action ledger is required for end-to-end RT1 checking')
    state = RunState(events)
    actions = {row['action_id']: row for row in events if row['kind'] == 'action_started'}
    results = {row['action_id']: row for row in events if row['kind'] == 'action_result'}
    with sqlite3.connect((run_dir / 'embedding_events.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        journal = [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]
    admissions = {row['operation']: row for row in journal if row['kind'] == 'search_admitted'}
    receipts = {row['operation']: row for row in journal if row['kind'] == 'search_returned'}
    checks = []
    for summary in diagnostics['searches']:
        if summary['diagnostic_status'] != 'verified':
            checks.append({'operation': summary['operation'], 'passed': False,
                           'reason': 'Diagnostic not verified', 'diagnostic_status': summary['diagnostic_status']})
            continue
        operation = summary['operation']
        capture = verify_capture(run_dir, receipts[operation], admissions[operation])
        action = actions.get(capture['action_id'], {}).get('action', {})
        args = action.get('args', {})
        if action.get('action') != 'search_corpus' or args.get('channel') != 'hybrid':
            raise HarnessError('Capture does not link to an M6 hybrid search action')
        if args.get('text') != capture['query'] or args.get('limit') != capture['limit']:
            raise HarnessError('M6 action query/limit differs from capture')
        if capture['query_case'] != state.config['identity']['query_id']:
            raise HarnessError('Capture query case differs from M6 run identity')
        need = args.get('_m6_need')
        if not isinstance(need, dict) or not need.get('a_refs'):
            raise HarnessError('M6 search has no source need/ref to A')
        for ref in need['a_refs']:
            source = state.catalog.get(ref)
            if (source is None or source['case_id'] != capture['query_case'] or
                    source['source_hash'] != state.config['identity']['query_source_hash']):
                raise HarnessError('Source need does not bind to raw A in this run')
        paragraph = need.get('a_paragraph')
        if paragraph is not None:
            source = state.catalog[paragraph['source_ref']]
            piece = slice_record(source, *paragraph['span_bytes'])
            if piece['text_sha256'] != paragraph['text_sha256']:
                raise HarnessError('Source need paragraph hash mismatch')
        expected = observation(capture['result'], need)
        event = results.get(capture['action_id'], {})
        actual = event.get('result') or {}
        if event.get('status') != 'success' or encode(actual.get('observation')) != encode(expected.observation):
            raise HarnessError('M6 delivered observation differs from captured response projection')
        if list(actual.get('candidates', [])) != list(expected.candidates):
            raise HarnessError('M6 action candidate list differs from delivered hits')
        if not set(expected.candidates) <= set(state.candidates):
            raise HarnessError('Delivered candidates are missing from the accumulated pool')
        checks.append({'operation': operation, 'passed': True, 'action_id': capture['action_id'],
                       'query_sha256': sha256(capture['query'].encode('utf-8')).hexdigest(),
                       'channel_counts': summary['channel_counts'], 'delivered_hits': summary['delivered_hits'],
                       'raw_a_provenance_bound': True})
    passed = bool(checks) and all(row['passed'] for row in checks)
    return {'status': 'PASS' if passed else 'INCOMPLETE', 'checks': checks,
            'model_calls_this_check': 0, 'retrieval_calls_this_check': 0,
            'limitations': ['Checks saved run data; no live controller behavior or gold evaluation.',
                            'Historical seals and corpus-wide correctness are not re-verified.',
                            'Diagnostic failures/unknowns remain incomplete, never empty successful results.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--out', type=Path, help='Optional new report path, never overwritten')
    args = parser.parse_args()
    if args.out and args.out.exists():
        parser.error('Output already exists; use a new path')
    try:
        report = check_run(args.run_dir)
        if args.out:
            with args.out.open('xb') as stream:
                stream.write(encode(report))
    except (OSError, ValueError, KeyError, sqlite3.Error, HarnessError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
