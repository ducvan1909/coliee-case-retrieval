"""Offline CM0 measurements and CM1 context projections. No inference entry point."""
import argparse
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
from time import perf_counter

from pipeline_v2.agent_harness.contracts import encode, fingerprint
from pipeline_v2.agent_harness.ledger import Ledger
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.experiments.uncapped_probe.policy import INSTRUCTIONS
from .core import Config, Session, Snapshot, digest_file, require, write_once


def counter(root):
    transport = ModalQwenTransport(root / 'cache/tokenizers/qwen36_27b_fp8', instructions=INSTRUCTIONS)
    return transport.count_tokens, fingerprint([transport.tokenizer_fingerprint, transport.prompt_fingerprint])


def measurements(payload, count):
    total = count(encode(payload))
    deltas = {}
    for key in payload:
        if key == 'max_output_tokens':
            continue
        reduced = dict(payload)
        reduced.pop(key)
        deltas[key] = total - count(encode(reduced))
    return {'input_tokens': total, 'removal_deltas_nonadditive': deltas,
            'raw_bytes': sum(r['span_bytes'][1] - r['span_bytes'][0] for r in payload.get('excerpts', []))}


def synthetic(size):
    needs = {f'need-{n}': {'source_need_id': f'need-{n}', 'intent': f'legal issue {n}'} for n in range(3)}
    candidates = [{'case_id': f'{n:06}.txt', 'need_ids': [f'need-{n % 3}'], 'leads': []} for n in range(size)]
    operations = [{'operation_id': f'op-{i}', 'need_id': f'need-{i}', 'status': 'success',
                   'hits': [{'case_id': r['case_id'], 'rank': j + 1} for j, r in enumerate(candidates) if f'need-{i}' in r['need_ids']]}
                  for i in range(3)]
    return Snapshot('query.txt', {'source_hashes': {}, 'fixture': True}, candidates, needs, operations)


def run(args):
    root, out = args.root.resolve(), args.output_dir.resolve()
    require(not out.exists(), 'Fresh output directory required')
    source = args.source_run.resolve()
    artifacts = args.payload_dir.resolve()
    require(not out.is_relative_to(source) and not out.is_relative_to(artifacts), 'Output must be outside source evidence')
    count, binding = counter(root)
    started = perf_counter()
    out.mkdir(parents=True)
    result = {'milestones': ['CM0', 'CM1'], 'command': args.command, 'controller_requests': 0,
              'embedding_requests': 0, 'retrieval_requests': 0, 'counter_binding': binding,
              'scope': 'offline projection and dispatch intents; no live or CM2 evidence lifecycle'}
    if args.command in ('measure', 'replay'):
        paths = [source / 'events.sqlite3', artifacts / 'payload.json', artifacts / 'after_scripted_candidate_read_payload.json']
        before = {str(p): digest_file(p) for p in paths}
        payloads = [json.loads(p.read_bytes()) for p in paths[1:]]
        result['CM0'] = {'payloads': {p.name: measurements(v, count) for p, v in zip(paths[1:], payloads)},
                        'minimal_instruction_template': count(encode({'max_output_tokens': 512})),
                        'budget': Config().__dict__, 'budget_status': 'experimental targets; exact totals authoritative'}
        if args.command == 'replay':
            events = Ledger(source).read()
            prefix = events[:-1] if events[-1]['kind'] == 'run_stopped' else events
            snapshot = Snapshot.from_events(prefix, {'source_run_hashes': before})
            # Verify supplied raw directly against corpus, then bind its source hash.
            for payload in payloads:
                for row in payload['excerpts']:
                    raw = (root / 'data/task1_train_files_2026/cases' / row['case_id']).read_bytes()
                    require(sha256(raw).hexdigest() == row['source_hash'], 'Corpus source hash mismatch')
                    a, b = row['span_bytes']
                    require(raw[a:b] == row['text'].encode('utf-8'), 'Corpus raw slice mismatch')
                    snapshot.bindings['source_hashes'][row['case_id']] = row['source_hash']
            snapshot = Snapshot.from_record(snapshot.record())
            write_once(out / 'snapshot.json', snapshot.record())
            session = Session(out / 'session', snapshot, count, counter_binding=binding)
            first = session.compile('results')
            require(first['status'] == 'ready', 'Results projection unfit')
            session.receipt(first['request_id'], 'success')  # Explicitly scripted, not provider receipt.
            ref = next(k for k, v in first['manifest']['handles'].items() if v['kind'] == 'candidate')
            intent = session.command(first['request_id'], {'action': 'read_case_passages', 'args': {'candidate_ref': ref, 'focus': 'procedural legal issue'}})
            evidence = {k: payloads[1][k] for k in ('excerpts', 'current_payload_source_refs', 'pending_source_count')}
            paired = session.compile('assessment', evidence=evidence)
            require(paired['status'] == 'ready', 'Supplied A/B view unfit')
            session.receipt(paired['request_id'], 'success')
            session.command(paired['request_id'], {'action': 'record_missing_evidence', 'args': {'reason': 'Scripted CM1 handoff; assessment execution is outside this milestone.'}})
            reopened = Session(out / 'session', Snapshot.from_record(snapshot.record()), count, counter_binding=binding)
            require(reopened.state()['focus'] == session.state()['focus'], 'Resume focus mismatch')
            result['CM1'] = {'result_view_tokens': first['input_tokens'], 'supplied_A_B_view_tokens': paired['input_tokens'],
                             'pool_total': len(snapshot.candidates), 'needs_total': len(snapshot.needs),
                             'shown_candidates': first['manifest']['shown_candidate_ids'], 'scripted_dispatch': intent,
                             'raw_preserved': paired['manifest']['canonical_evidence'] == evidence,
                             'resume_equal': True, 'receipts': 'scripted_offline_not_provider',
                             'source_actions_and_assessment_execution': 'deferred CM2/CM3'}
        require(before == {str(p): digest_file(p) for p in paths}, 'Source evidence changed')
        result['source_hashes'] = before
        result['source_unchanged'] = True
    else:
        rows = []
        for size in (3, 50, 500, 10000):
            snapshot = synthetic(size)
            session = Session(out / f'pool-{size}', snapshot, count, counter_binding=binding)
            seen, cursor, peak, pages = [], None, 0, 0
            while True:
                page = session.compile('pool', cursor=cursor)
                require(page['status'] == 'ready', f'Pool {size} unfit')
                session.receipt(page['request_id'], 'success')
                seen.extend(page['manifest']['shown_candidate_ids'])
                peak = max(peak, page['input_tokens'])
                pages += 1
                cursor = page['view']['page']['controls'].get('next')
                if not cursor:
                    break
                # Full traversal for small fixtures; 10000 pool validates sampled first page,
                # full canonical membership and token bound without quadratic journal replay.
                if size >= 500:
                    break
            expected = [r['case_id'] for r in snapshot.candidates]
            require(seen == expected[:len(seen)] and len(set(seen)) == len(seen), 'Paging lost/reordered candidates')
            if size < 500:
                require(seen == expected, 'Traversal incomplete')
            rows.append({'pool_size': size, 'canonical_count': len(snapshot.candidates), 'view_count': len(seen),
                         'peak_tokens': peak, 'pages': pages, 'full_traversal': size < 500,
                         'limitation': None if size < 500 else 'First-page stress only; full 10000 traversal not benchmarked'})
        result['stress'] = rows
    result['elapsed_seconds'] = perf_counter() - started
    result['code_binding'] = {p.name: digest_file(p) for p in Path(__file__).parent.glob('*.py')}
    write_once(out / 'report.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('measure', 'replay', 'stress'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--source-run', type=Path, default=Path('cache/m6-uncapped-021095-20261114-200422096'))
    parser.add_argument('--payload-dir', type=Path, default=Path('cache/ag-payload-check-20261114-215317655'))
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({'report': str(args.output_dir / 'report.json'), 'requests': 0,
                      'elapsed_seconds': result['elapsed_seconds']}))


if __name__ == '__main__':
    main()
