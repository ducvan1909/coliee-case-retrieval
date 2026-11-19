"""Offline one-query retrieval evaluation. Freeze before reading evaluator gold."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from pipeline_v2.agent_harness.contracts import HarnessError, encode
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.full_search.hybrid import fuse_channels
from pipeline_v2.m6_hybrid import EmbeddingBudget, EmbeddingJournal
from pipeline_v2.retrieval_diagnostics import inspect_run, verify_capture

VERSION = 'isolated-one-query-evaluator-v1'
LABELS = 'data/task1_train_files_2026/clean_task1_train_labels_2026.json'


def _read(path):
    return json.loads(Path(path).read_bytes())


def _write(path, value):
    with Path(path).open('xb') as stream:
        stream.write(encode(value))


def freeze(run_dir):
    """Hash terminal evidence without opening labels; failures remain eligible."""
    run_dir = Path(run_dir).resolve()
    events = Ledger(run_dir).read()
    state = RunState(events)
    operator_stopped = state.final is not None and state.final.get('stop_detail') == 'operator_stop_file'
    if (not state.config or state.final is None or state.in_flight or state.active_action
            or state.pending_action and not operator_stopped):
        raise HarnessError('Freeze requires a terminal run with resolved local admissions; never resend unknown work')
    # Exclude heartbeat/status/stop files, which may change after terminal state.
    names = ['events.sqlite3']
    names += [str(path.relative_to(run_dir)).replace('\\', '/')
              for path in run_dir.rglob('*') if path.is_file()
              and (path.name in ('plan.json', 'first_payload.json', 'embedding_events.sqlite3')
                   or path.parent.name == 'retrieval_diagnostics'
                   or path.name.startswith('report_') and path.suffix == '.json')]
    hashes = {name: sha256((run_dir / name).read_bytes()).hexdigest() for name in sorted(set(names))}
    diagnostics = inspect_run(run_dir) if (run_dir / 'embedding_events.sqlite3').exists() else {
        'model_calls_this_tool': 0, 'searches': []}
    return {'version': VERSION, 'run_dir': str(run_dir),
            'query_id': state.config['identity']['query_id'], 'hashes': hashes,
            'stop_reason': state.snapshot()['stop_reason'], 'diagnostics': diagnostics,
            'unexecuted_returned_action': state.pending_action,
            'gold_read': False, 'model_calls_this_tool': 0}


def _metric(cases, gold, *, complete=True):
    cases = set(cases)
    recall = len(cases & gold) / len(gold) if gold else None
    return {'cases': sorted(cases), 'count': len(cases), 'gold_found': len(cases & gold),
            'recall': recall if complete else None, 'complete_observed_search_evidence': complete,
            'observed_lower_bound_recall': recall}


def score(root, run_dir, frozen):
    """Validate frozen inputs, then read pair gold in this evaluator only."""
    run_dir = Path(run_dir).resolve()
    if freeze(run_dir) != frozen:
        raise HarnessError('Frozen run evidence changed')
    events = Ledger(run_dir).read()
    state = RunState(events)
    actions = {event['action_id']: event['action'] for event in events if event['kind'] == 'action_started'}
    journal_path = run_dir / 'embedding_events.sqlite3'
    embedding_events = []
    if journal_path.exists():
        with closing(sqlite3.connect(journal_path.as_uri() + '?mode=ro', uri=True)) as db:
            embedding_events = [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]
    admissions = {row['operation']: row for row in embedding_events if row['kind'] == 'search_admitted'}
    returned = {row['operation']: row for row in embedding_events if row['kind'] == 'search_returned'}
    captures = []
    for operation, admission in admissions.items():
        receipt = returned.get(operation)
        if receipt and receipt.get('diagnostic_status') == 'saved':
            body = verify_capture(run_dir, receipt, admission)
            action = actions.get(body['action_id'], {})
            args = action.get('args', {})
            if (action.get('action') != 'search_corpus' or args.get('text') != body['query']
                    or args.get('limit') != body['limit'] or body['query_case'] != frozen['query_id']):
                raise HarnessError('Diagnostic differs from durable query action')
            captures.append((body, args.get('_m6_need', {})))
    searched_actions = {event['action_id'] for event in events
                        if event['kind'] == 'action_started' and event.get('executes_tool')
                        and event['action']['action'] == 'search_corpus'
                        and event['action']['args'].get('channel') == 'hybrid'}
    complete = (len(captures) == len(admissions)
                and {row['action_id'] for row in admissions.values()} == searched_actions)
    # No solver imports this module. Labels are first opened after all above checks.
    labels_bytes = (Path(root) / LABELS).read_bytes()
    values = json.loads(labels_bytes).get(frozen['query_id'])
    if not isinstance(values, list) or not all(isinstance(case, str) for case in values):
        raise HarnessError('Missing or invalid pair gold for query')
    gold = set(values)
    channel_union = {key: set() for key in ('case_bm25', 'passage_bm25', 'dense_passage')}
    fused_union = {k: set() for k in (3, 5, 10, 20)}
    delivered = set()
    per_search = []
    for body, need in captures:
        result = body['result']
        channels = result['channels']
        ranks = {}
        for name, rows in channels.items():
            channel_union[name].update(row['case_id'] for row in rows)
            ranks[name] = {row['case_id']: row['rank'] for row in rows if row['case_id'] in gold}
        offline = {}
        for k in fused_union:
            cases = {hit['case_id'] for hit in fuse_channels(channels, k)}
            fused_union[k].update(cases)
            offline[str(k)] = _metric(cases, gold)
        hits = {hit['case_id'] for hit in result['hits']}
        added = hits - delivered
        delivered.update(hits)
        per_search.append({'operation': body['operation'], 'query': body['query'],
                           'source_proposition': need.get('source_proposition'), 'a_paragraph': need.get('a_paragraph'),
                           'gold_channel_ranks': ranks, 'delivered': _metric(hits, gold),
                           'new_cases': sorted(added), 'new_gold': sorted(added & gold),
                           'offline_rrf_at_k': offline, 'coverage': result.get('coverage'),
                           'timings': result.get('timings'), 'execution_mode': result.get('execution_mode')})
    snap = state.snapshot()
    usage = EmbeddingJournal(run_dir, root, EmbeddingBudget(0, 0)).usage()
    return {'version': VERSION, 'protocol': 'single_discovery_query_diagnostic',
            'query_id': frozen['query_id'], 'query_denominator': 1, 'gold_denominator': len(gold),
            'gold': sorted(gold), 'labels_sha256': sha256(labels_bytes).hexdigest(),
            'freeze_sha256': sha256(encode(frozen)).hexdigest(), 'stop_reason': snap['stop_reason'],
            'controller_usage': snap['usage'], 'embedding_usage': usage,
            'channels': {key: _metric(cases, gold, complete=complete) for key, cases in channel_union.items()},
            'observed_channel_union': _metric(set().union(*channel_union.values()), gold, complete=complete),
            'offline_rrf_union_at_k': {str(k): _metric(cases, gold, complete=complete) for k, cases in fused_union.items()},
            'delivered_hybrid_hits': _metric(delivered, gold, complete=complete), 'actual_pool': _metric(state.candidates, gold),
            'unexecuted_returned_action': frozen.get('unexecuted_returned_action'),
            'searches': per_search, 'search_diagnostics': frozen['diagnostics'],
            'limitations': ['One discovery query; not representative or final F1.',
                            'Missing/failed searches remain in query denominator; channel coverage may be unknown.',
                            'Offline RRF is diagnostic, not extra candidates delivered to the model.',
                            'Compare uncapped and RT5 separately; additional budget is a confound.'],
            'model_calls_this_tool': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('freeze', 'score'):
        command = commands.add_parser(name)
        command.add_argument('--run-dir', type=Path, required=True)
        command.add_argument('--out', type=Path, required=True)
        if name == 'score':
            command.add_argument('--freeze', type=Path, required=True)
            command.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.out.resolve().is_relative_to(args.run_dir.resolve()):
        raise HarnessError('Evaluator output must be outside the frozen run')
    result = freeze(args.run_dir) if args.command == 'freeze' else score(args.root, args.run_dir, _read(args.freeze))
    _write(args.out, result)
    print(json.dumps({'output': str(args.out), 'query_id': result['query_id'], 'model_calls': 0}))


if __name__ == '__main__':
    main()
