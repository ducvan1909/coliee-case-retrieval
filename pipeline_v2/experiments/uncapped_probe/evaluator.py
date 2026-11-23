"""Offline one-query retrieval evaluation. Freeze before reading evaluator gold."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from pipeline_v2.agent_harness.contracts import HarnessError, encode, fingerprint
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.m6_hybrid import EmbeddingBudget, EmbeddingJournal, fuse_m6_channels
from pipeline_v2.retrieval_diagnostics import inspect_run, verify_capture

VERSION = 'isolated-one-query-evaluator-v2'
LABELS = 'data/task1_train_files_2026/clean_task1_train_labels_2026.json'


def _read(path):
    return json.loads(Path(path).read_bytes())


def _write(path, value):
    with Path(path).open('xb') as stream:
        stream.write(encode(value))


def _layout(run_dir):
    path = Path(run_dir).resolve()
    if path.name == 'session' and (path / 'events.sqlite3').is_file():
        path = path.parent
    nested = path / 'session' / 'events.sqlite3'
    direct = path / 'events.sqlite3'
    if nested.is_file() and direct.is_file():
        raise HarnessError('Ambiguous controller ledger layout')
    if nested.is_file():
        return path, path / 'session'
    if direct.is_file():
        return path, path
    raise HarnessError('Controller ledger not found')


def _journal(run_dir):
    path = run_dir / 'embedding_events.sqlite3'
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]


def freeze(run_dir):
    """Hash terminal evidence without opening labels; failures remain eligible."""
    run_dir, controller = _layout(run_dir)
    events = Ledger(controller).read()
    state = RunState(events)
    operator_stopped = state.final is not None and state.final.get('stop_detail') == 'operator_stop_file'
    if (not state.config or state.final is None or state.in_flight or state.active_action
            or state.pending_action and not operator_stopped):
        raise HarnessError('Freeze requires a terminal run with resolved local admissions; never resend unknown work')
    # Exclude heartbeat/status/stop files, which may change after terminal state.
    names = [str((controller / 'events.sqlite3').relative_to(run_dir)).replace('\\', '/')]
    names += [str(path.relative_to(run_dir)).replace('\\', '/')
              for path in run_dir.rglob('*') if path.is_file()
              and (path.name in ('plan.json', 'first_payload.json', 'embedding_events.sqlite3')
                   or path.parent.name == 'retrieval_diagnostics'
                   or 'reranker' in path.relative_to(run_dir).parts
                   or path.name.startswith('report_') and path.suffix == '.json')]
    hashes = {name: sha256((run_dir / name).read_bytes()).hexdigest() for name in sorted(set(names))}
    diagnostics = inspect_run(run_dir) if (run_dir / 'embedding_events.sqlite3').exists() else {
        'model_calls_this_tool': 0, 'searches': []}
    return {'version': VERSION, 'run_dir': str(run_dir),
            'controller_dir': str(controller),
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


def _search_links(events):
    """Derive branch IDs from durable parent queries, including failed attempts."""
    starts = {e['action_id']: e['action'] for e in events if e['kind'] == 'action_started'}
    results = {e['action_id']: e for e in events if e['kind'] == 'action_result'}
    dual_profile = any(e['kind'] == 'run_created' and
                       e.get('config', {}).get('cm23', {}).get('passage_review') for e in events)
    links, parents = {}, {}
    for parent, action in starts.items():
        args = action.get('args', {})
        if action.get('action') != 'search_corpus' or args.get('channel') != 'hybrid':
            continue
        observation = (results.get(parent, {}).get('result') or {}).get('observation', {})
        need = args.get('_m6_need', {})
        if observation.get('host_citation_match') or observation.get('search_reuse'):
            parents[parent] = (args, observation)
            continue
        dual = dual_profile or observation.get('cm4_passage_review') or need.get('source_bound')
        texts = {'source': args['text']} if need.get('source_bound') else {
            'issue': args['text'], 'verbatim': need.get('a_anchor', {}).get('text')}
        if not dual:
            texts = {'hybrid': args['text']}
        if any(not isinstance(text, str) for text in texts.values()):
            raise HarnessError('Durable branch query text missing')
        expected = {}
        for name, text in texts.items():
            branch_id = fingerprint([parent, 'cm4-hybrid-branch', text]) if dual else parent
            links.setdefault(branch_id, {'parent_action_id': parent, 'branch': name, 'text': text,
                                         'limit': args['limit'], 'need': need})
            expected[name] = branch_id
        branches = observation.get('dual_retrieval', {}).get('branches', {})
        for name, record in branches.items():
            if name not in expected:
                raise HarnessError('Unexpected CM4 retrieval branch')
            if record.get('reused_branch'):
                target = record['reused_branch']
                if target not in expected or texts[name] != texts[target]:
                    raise HarnessError('Invalid reused CM4 branch')
            elif (record.get('action_id') != expected[name]
                  or record.get('query_sha256') != sha256(texts[name].encode('utf-8')).hexdigest()):
                raise HarnessError('CM4 branch differs from durable query action')
        if observation.get('dual_retrieval') and set(branches) != set(expected):
            raise HarnessError('CM4 branch records missing')
        _validate_review(observation)
        parents[parent] = (args, observation)
    return links, parents


def _validate_review(observation):
    dual = observation.get('dual_retrieval')
    if not dual:
        return
    pool, passages = dual['rerank_pool'], dual['scored_passages']
    hits = observation.get('hits', [])
    if len(pool) != len(set(pool)) or len(pool) > 50 or len(hits) > 10:
        raise HarnessError('Invalid CM4 pool/review limits')
    refs = [p['hit_ref'] for p in passages]
    if len(refs) != len(set(refs)) or any(p['case_id'] not in pool for p in passages):
        raise HarnessError('Invalid CM4 scored passage pool')
    ordered = sorted(passages, key=lambda p: (-p['score'], p['case_rank'], p['hit_ref']))
    if passages != ordered or len(hits) != min(10, len(passages)):
        raise HarnessError('CM4 retained passages are not the top ten')
    for rank, (hit, scored) in enumerate(zip(hits, passages), 1):
        if hit != {**scored, 'rank': rank} and {
                k: v for k, v in hit.items() if k != 'preview'} != {**scored, 'rank': rank}:
            raise HarnessError('CM4 retained passage differs from scored passage')


def _funnel(events, parents, gold, state, complete):
    context = {}
    packets = {}
    for event in events:
        if 'cm_context' in event:
            context = event['cm_context']
            packet = context.get('passage_session', {}).get('identity_packet')
            if packet:
                packets[packet['packet_id']] = packet
    pools, scored, retained, unique = set(), set(), [], set()
    searches = []
    for parent, (args, obs) in parents.items():
        if not obs.get('cm4_passage_review'):
            continue
        dual = obs.get('dual_retrieval', {})
        pool = set(dual.get('rerank_pool', []))
        passages = dual.get('scored_passages', [])
        hits = obs.get('hits', [])
        cases = {h['case_id'] for h in hits}
        if dual and (not cases <= pool or any(h['case_id'] not in pool for h in passages)
                     or any(h['hit_ref'] not in {p['hit_ref'] for p in passages} for h in hits)):
            raise HarnessError('CM4 retained passages differ from rerank pool')
        pools.update(pool)
        scored.update(h['case_id'] for h in passages)
        retained.extend(hits)
        unique.update(cases)
        searches.append({'parent_action_id': parent, 'source_need': args.get('_m6_need'),
            'hybrid_pool': _metric(pool, gold), 'scored_passage_count': len(passages),
            'retained_passage_count': len(hits), 'retained_unique_b': _metric(cases, gold),
            'missing_passage': dual.get('missing_passage', []),
            'retained_passages': hits, 'search_reuse': obs.get('search_reuse'),
            'host_citation_match': obs.get('host_citation_match')})
    conclusions = [dict(row, case_id=case, search_query_id=query)
                   for query, rows in context.get('candidate_conclusions', {}).items()
                   for case, row in rows.items()]
    checked = {row['case_id'] for row in conclusions if row.get('identity_packet_id')}
    selected = {row['case_id'] for row in conclusions if row.get('decision') == 'select'}
    rejected = {row['case_id'] for row in conclusions if row.get('decision') == 'not_select'}
    identity_selected = {row['case_id'] for row in conclusions
                         if row.get('identity_packet_id') and row.get('decision') == 'select'}
    for search in searches:
        rows = [row for row in conclusions if row['search_query_id'] == search['parent_action_id']]
        search['identity_conclusions'] = rows
        search['concluded_select'] = _metric({row['case_id'] for row in rows
                                             if row.get('decision') == 'select'}, gold)
        search['pending_b'] = sorted(set(search['retained_unique_b']['cases']) - {row['case_id'] for row in rows})
    prediction = state.snapshot().get('prediction')
    predicted = set(prediction or [])
    tp = len(predicted & gold)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(gold) if gold else None
    return {'available': bool(searches), 'hybrid_pool': _metric(pools, gold, complete=complete),
        'scored_passage_cases': _metric(scored, gold, complete=complete),
        'retained_passage_count': len(retained),
        'retained_unique_b': _metric(unique, gold, complete=complete),
        'identity_requested': _metric({p['case_id'] for p in packets.values()}, gold),
        'identity_concluded': _metric(checked, gold),
        'identity_selected': _metric(identity_selected, gold),
        'concluded_select': _metric(selected, gold),
        'concluded_not_select': _metric(rejected, gold),
        'pending_unique_b': sorted(unique - {row['case_id'] for row in conclusions}),
        'gold_losses': {'pool_to_scored': sorted((pools - scored) & gold),
                        'scored_to_retained': sorted((scored - unique) & gold),
                        'retained_without_select': sorted((unique - selected) & gold)},
        'identity_conclusions': conclusions,
        'identity_labels_origin': 'model_inferred_not_gold',
        'host_citation_matches': context.get('host_citation_matches', {}),
        'prediction': {**_metric(predicted, gold, complete=prediction is not None), 'available': prediction is not None,
            'precision': precision if prediction is not None else None,
            'recall': recall if prediction is not None else None,
            'f1': (2 * precision * recall / (precision + recall) if recall and precision else 0.0)
                  if prediction is not None else None,
            'false_positive': sorted(predicted - gold), 'false_negative': sorted(gold - predicted),
            'fallback': state.snapshot().get('fallback')}, 'searches': searches}


def score(root, run_dir, frozen):
    """Validate frozen inputs, then read pair gold in this evaluator only."""
    run_dir, controller = _layout(run_dir)
    if freeze(run_dir) != frozen:
        raise HarnessError('Frozen run evidence changed')
    events = Ledger(controller).read()
    state = RunState(events)
    links, parents = _search_links(events)
    embedding_events = _journal(run_dir)
    admissions = {row['operation']: row for row in embedding_events if row['kind'] == 'search_admitted'}
    returned = {row['operation']: row for row in embedding_events if row['kind'] == 'search_returned'}
    captures = []
    for operation, admission in admissions.items():
        receipt = returned.get(operation)
        if receipt and receipt.get('diagnostic_status') == 'saved':
            body = verify_capture(run_dir, receipt, admission)
            link = links.get(body['action_id'], {})
            if (link.get('text') != body['query'] or link.get('limit') != body['limit']
                    or body['query_case'] != frozen['query_id']):
                raise HarnessError('Diagnostic differs from durable query action')
            obs = parents[link['parent_action_id']][1]
            record = obs.get('dual_retrieval', {}).get('branches', {}).get(link['branch'])
            if record and (record.get('request_id') != body['m3_request_id']
                           or record.get('cases') != [h['case_id'] for h in body['result']['hits']]):
                raise HarnessError('CM4 branch result differs from diagnostic')
            captures.append((body, link['need']))
    complete = (len(captures) == len(admissions)
                and {row['action_id'] for row in admissions.values()} == set(links))
    # No solver imports this module. Labels are first opened after all above checks.
    labels_bytes = (Path(root) / LABELS).read_bytes()
    values = json.loads(labels_bytes).get(frozen['query_id'])
    if not isinstance(values, list) or not all(isinstance(case, str) for case in values):
        raise HarnessError('Missing or invalid pair gold for query')
    gold = set(values)
    channel_union = {key: set() for key in ('case_bm25', 'passage_bm25', 'dense_passage')}
    fused_union = {k: set() for k in (3, 5, 10, 20, 50)}
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
            cases = {hit['case_id'] for hit in fuse_m6_channels(channels, k)}
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
    from pipeline_v2.experiments.context_manager_v2.reranker_modal import ModalReranker
    reranker_usage = ModalReranker(run_dir / 'reranker', '').usage()
    return {'version': VERSION, 'protocol': 'single_discovery_query_diagnostic',
            'query_id': frozen['query_id'], 'query_denominator': 1, 'gold_denominator': len(gold),
            'gold': sorted(gold), 'labels_sha256': sha256(labels_bytes).hexdigest(),
            'freeze_sha256': sha256(encode(frozen)).hexdigest(), 'stop_reason': snap['stop_reason'],
            'controller_usage': snap['usage'], 'embedding_usage': usage,
            'reranker_usage': reranker_usage,
            'channels': {key: _metric(cases, gold, complete=complete) for key, cases in channel_union.items()},
            'observed_channel_union': _metric(set().union(*channel_union.values()), gold, complete=complete),
            'offline_rrf_union_at_k': {str(k): _metric(cases, gold, complete=complete) for k, cases in fused_union.items()},
            'delivered_hybrid_hits': _metric(delivered, gold, complete=complete), 'actual_pool': _metric(state.candidates, gold),
            'cm4_funnel': _funnel(events, parents, gold, state, complete),
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
    run_root, _ = _layout(args.run_dir)
    if args.out.resolve().is_relative_to(run_root):
        raise HarnessError('Evaluator output must be outside the frozen run')
    result = freeze(args.run_dir) if args.command == 'freeze' else score(args.root, args.run_dir, _read(args.freeze))
    _write(args.out, result)
    print(json.dumps({'output': str(args.out), 'query_id': result['query_id'], 'model_calls': 0}))


if __name__ == '__main__':
    main()
