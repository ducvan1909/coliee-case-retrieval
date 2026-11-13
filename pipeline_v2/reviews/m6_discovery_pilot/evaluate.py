"""Freeze M6 discovery runs, then diagnose candidate coverage against train gold."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

from pipeline_v2.agent_harness.contracts import HarnessError, encode, fingerprint
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.full_search.hybrid import RUNTIME_DIR
from pipeline_v2.m6_hybrid import EmbeddingBudget, EmbeddingJournal


TRAIN_LABELS = Path('data/task1_train_files_2026/clean_task1_train_labels_2026.json')


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    with path.open('xb') as file:
        file.write(encode(obj))


def collect(root, manifest_path, runs):
    """Load and bind run artifacts before any access to labels."""
    manifest = read(manifest_path)
    queries = manifest['queries']
    cohort_path = root / manifest['cohort']
    cohort = read(cohort_path)
    if (len(queries) != 3 or len(set(queries)) != 3 or queries != cohort['discovery_queries'][:3]
            or set(queries) & set(cohort['holdout_queries'])):
        raise HarnessError('Unexpected pilot cohort')
    records = {}
    receipts = {}
    for query in queries:
        directory = runs / query
        settings = {**manifest['profile'], 'query_id': query}
        paths = [directory / name for name in ('plan.json', 'first_payload.json', 'events.sqlite3')]
        paths += sorted(directory.glob('report_*.json'))
        hashes = {str(path.resolve()): digest(path) for path in paths}
        plan = read(directory / 'plan.json')
        preview = read(directory / 'first_payload.json')
        events = Ledger(directory).read()
        state = RunState(events)
        if (plan['settings'] != settings or plan['preflight_status'] != 'ready'
                or fingerprint(preview) != plan['first_payload_sha256'] or not state.config
                or state.config['identity'] != plan['binding']['identity']
                or state.config['identity']['query_id'] != query):
            raise HarnessError(f'Prepared settings or identity mismatch for {query}')
        if state.final is None or state.in_flight or state.active_action or state.pending_action:
            raise HarnessError(f'Run has no terminal ledger for {query}; resolve or resume before freeze')
        journal = EmbeddingJournal(directory, root, EmbeddingBudget(**settings['embedding_budget']))
        if journal.path.is_file():
            hashes[str(journal.path.resolve())] = digest(journal.path)
        for event in journal.events():
            if event['kind'] != 'embedding_admitted':
                continue
            path = root / event['m3_ledger']
            expected = root / RUNTIME_DIR / event['m3_request_id'] / 'ledger.sqlite3'
            if path.resolve() != expected or not path.resolve().is_relative_to(root / RUNTIME_DIR):
                raise HarnessError('Invalid embedding ledger link')
            hashes[str(path)] = digest(path) if path.is_file() else None
        usage = journal.usage()
        for filename, expected in hashes.items():
            path = Path(filename)
            if (digest(path) if path.is_file() else None) != expected:
                raise HarnessError(f'Artifact changed during freeze for {query}')
        provider_receipts = [receipt for path in paths if path.name.startswith('report_')
                             for receipt in read(path).get('modal_receipts_this_invocation', [])]
        records[query] = (state, events, usage, provider_receipts)
        receipts[query] = hashes
    return {'manifest_sha256': digest(manifest_path), 'cohort_sha256': digest(cohort_path),
            'runs': receipts}, records


def summarize(state, events, gold):
    snap = state.snapshot()
    candidates = set(snap['candidates'])
    active = defaultdict(list)
    pending = defaultdict(list)
    opened = defaultdict(list)
    delivered = defaultdict(set)
    rejected = defaultdict(list)
    retrieved = defaultdict(list)
    paired_payloads = defaultdict(list)
    attempts, trace, reply_rejections = {}, [], []
    for event in events:
        kind = event['kind']
        seq = event['seq']
        if kind == 'request_admitted':
            payload = json.loads(event['payload'])
            attempts[event['request_id']] = payload
            trace.append({'seq': seq, 'kind': kind, 'request_id': event['request_id'],
                          'input_tokens': event['admitted_input_tokens'],
                          'raw_refs': event['current_payload_source_refs'],
                          'available_tools': [tool['name'] for tool in payload.get('available_tools', [])]})
        elif kind == 'request_result':
            row = {k: event[k] for k in ('seq', 'kind', 'request_id', 'status', 'error',
                                         'input_tokens', 'output_tokens', 'provider_latency_ms')}
            diagnostic = event.get('m6_reply')
            if diagnostic is not None:
                row['m6_reply'] = diagnostic
                if diagnostic.get('rejection') is not None:
                    reply_rejections.append(seq)
            trace.append(row)
            if event['received_response']:
                payload = attempts[event['request_id']]
                for row in payload['excerpts']:
                    delivered[row['case_id']].add(row['ref'])
                for pair in payload.get('m6', {}).get('pair_refs', {}).values():
                    paired_payloads[pair['candidate_id']].append(seq)
        elif kind == 'action_started':
            attempts[event['action_id']] = event['action']
            trace.append({k: event[k] for k in ('seq', 'kind', 'action_id', 'request_id', 'action')})
        elif kind == 'action_result':
            result = event.get('result') or {}
            observation = result.get('observation', {})
            for hit in observation.get('hits', []):
                retrieved[hit['case_id']].append({'seq': seq, 'rank': hit.get('rank'),
                                                  'channel_ranks': hit.get('channel_ranks')})
            for row in result.get('excerpts', []):
                opened[row['case_id']].append({'seq': seq, 'ref': row['ref'], 'source_hash': row['source_hash'],
                                               'span_bytes': row['span_bytes']})
            if event.get('status') == 'error':
                action = attempts[event['action_id']]
                for row in action['args'].get('assessments', []):
                    rejected[row['candidate_id']].append({'seq': seq, 'reason': event.get('reason')})
            trace.append({'seq': seq, 'kind': kind, 'action_id': event['action_id'], 'status': event['status'],
                          'reason': event.get('reason'), 'candidate_hits': [hit['case_id'] for hit in observation.get('hits', [])],
                          'coverage': observation.get('coverage'), 'm3_request_id': observation.get('request_id'),
                          'local_elapsed_ms': event.get('local_elapsed_ms')})
        elif kind in ('source_drift', 'run_stopped'):
            trace.append({key: value for key, value in event.items() if key != 'at_utc'})
    for row in snap['assessments']:
        if row['assessment_id'] in snap['active_assessment_ids']:
            active[row['candidate_id']].append(row)
    for row in snap.get('pending_assessments', []):
        pending[row['candidate_id']].append(row)

    prediction = snap['prediction']
    pairs = {}
    for case in sorted(candidates | gold | set(prediction or [])):
        if case not in candidates:
            stage = 'retrieval'
        elif not opened[case] and not delivered[case]:
            stage = 'source_open'
        elif not delivered[case] or (not paired_payloads[case] and not active[case] and not pending[case]):
            stage = 'evidence_delivery'
        elif not active[case]:
            stage = 'assessment_rejected' if rejected[case] else 'assessment_pending' if pending[case] else 'assessment_missing'
        elif prediction is None:
            stage = 'selector_unavailable'
        else:
            stage = 'selected' if case in prediction else 'selection'
        pairs[case] = {'gold': case in gold, 'first_gap': stage, 'retrieval_hits': retrieved[case],
                       'opens': opened[case], 'delivered_refs': sorted(delivered[case]),
                       'paired_payload_receipt_seqs': paired_payloads[case], 'active_assessments': active[case],
                       'pending_assessments': pending[case], 'rejected_assessments': rejected[case]}
    search_executed = any(
        event['kind'] == 'action_started' and event['executes_tool']
        and event['action']['action'] in ('search_corpus', 'search_identity') for event in events
    )
    return {'gold_count': len(gold), 'pool_count': len(candidates), 'gold_retrieved': len(candidates & gold),
            'gold_opened': sum(bool(opened[case] or delivered[case]) for case in gold),
            'gold_delivered': sum(bool(delivered[case]) for case in gold),
            'gold_assessed': sum(bool(active[case]) for case in gold), 'prediction': prediction,
            'gold_stage_counts': dict(Counter(pairs[case]['first_gap'] for case in gold)), 'pairs': pairs,
            'search_action_executed': search_executed, 'reply_rejection_seqs': reply_rejections,
            'stop_reason': snap['stop_reason'], 'stop_detail': snap.get('stop_detail'), 'trace': trace,
            'controller_usage': snap['usage']}


def score(root, manifest_path, runs, freeze_path):
    bound, records = collect(root, manifest_path, runs)
    if bound != read(freeze_path):
        raise HarnessError('Frozen pilot inputs changed before scoring')
    labels_path = root / TRAIN_LABELS
    labels_bytes = labels_path.read_bytes()
    labels = json.loads(labels_bytes)
    results = {}
    tp = fp = fn = 0
    for query, (state, events, usage, provider_receipts) in records.items():
        gold = labels.get(query)
        if not isinstance(gold, list) or not all(isinstance(case, str) for case in gold):
            raise HarnessError(f'Missing or invalid train gold for {query}')
        row = summarize(state, events, set(gold))
        row['embedding_usage'] = usage
        row['controller_provider_receipts'] = provider_receipts
        results[query] = row
        if row['prediction'] is not None:
            predicted = set(row['prediction'])
            tp += len(predicted & set(gold))
            fp += len(predicted - set(gold))
            fn += len(set(gold) - predicted)
    gold_total = sum(row['gold_count'] for row in results.values())
    gold_retrieved = sum(row['gold_retrieved'] for row in results.values())
    metrics = None
    if all(row['prediction'] is not None for row in results.values()):
        metrics = {'tp': tp, 'fp': fp, 'fn': fn, 'precision': tp / (tp + fp) if tp + fp else None,
                   'recall': tp / (tp + fn) if tp + fn else None,
                   'f1': 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None}
    stages = Counter()
    for row in results.values():
        stages.update(row['gold_stage_counts'])
    return {'protocol': 'discovery_diagnostic', 'train_labels_sha256': sha256(labels_bytes).hexdigest(),
            'freeze_sha256': digest(freeze_path), 'gold_total': gold_total, 'gold_retrieved': gold_retrieved,
            'candidate_recall': gold_retrieved / gold_total if gold_total else None,
            'gold_stage_counts': dict(stages), 'final_metrics': metrics, 'queries': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('freeze', 'score'):
        command = commands.add_parser(name)
        command.add_argument('--manifest', type=Path, required=True)
        command.add_argument('--runs-dir', type=Path, required=True)
        command.add_argument('--out', type=Path, required=True)
        if name == 'score':
            command.add_argument('--freeze', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    result = (collect(root, args.manifest, args.runs_dir)[0] if args.command == 'freeze'
              else score(root, args.manifest, args.runs_dir, args.freeze))
    write(args.out, result)
    print(args.out)


if __name__ == '__main__':
    main()
