"""Rebuild payloads without model/embedding/retrieval; optionally read a local lead."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

from pipeline_v2.agent_harness.contracts import HarnessError, encode, fingerprint
from pipeline_v2.agent_harness.evidence import normalize_result
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.m6_hybrid import EmbeddingBudget, EmbeddingJournal, HybridSearch
from . import policy, runner


def dry_open(harness, state, prefix, fitted, output):
    """Script one model choice and real local source read, not model inference."""
    body = json.loads(fitted[0])
    choices = policy.hydrate_body(body)['m6']['candidates']
    key, candidate = min(choices.items(), key=lambda row: row[1]['case_id'])
    if not candidate.get('open_ref') or candidate.get('already_opened'):
        raise HarnessError('Dry read requires an existing unopened passage lead; no retrieval allowed')
    need = candidate['needs'][0]
    action = policy.translate(body, {'action': 'read_case_passages', 'args': {
        'candidate_ref': key, 'focus': need['intent']}})
    scripted = list(prefix)

    def add(kind, **fields):
        row = {'seq': scripted[-1]['seq'] + 1, 'kind': kind, 'at_utc': 'scripted-offline', **fields}
        scripted.append(row)
        state.apply(row)

    request_id = 'offline-scripted-read-only'
    add('request_admitted', request_id=request_id, retry_of=None, payload=fitted[0].decode('utf-8'),
        admitted_input_tokens=fitted[1], output_token_cap=512, consumed_refs=fitted[2],
        remaining_excerpts=fitted[3], excerpts=fitted[4],
        current_payload_source_refs=body['current_payload_source_refs'])
    add('request_result', request_id=request_id, status='success', received_response=True,
        action=action, input_tokens=None, output_tokens=None, provider_latency_ms=None,
        transport_elapsed_ms=None, error=None)
    action_id = fingerprint([request_id, 'action'])
    add('action_started', action_id=action_id, request_id=request_id, action=action,
        action_fingerprint=fingerprint(action), executes_tool=True)
    result = harness._read_candidate(action['args'])
    normalized = normalize_result(result, state, preserve_provenance=True)
    add('action_result', action_id=action_id, status='success', result=normalized,
        reason=None, reload_refs=[], invalidated_assessments=[], assessments=[],
        pending_assessments=[], final=None, local_elapsed_ms=0)
    harness.events = lambda: scripted
    next_payload = harness._fit_payload(state, 8500)
    if next_payload:
        (output / 'after_scripted_candidate_read_payload.json').write_bytes(next_payload[0])
    (output / 'scripted_candidate_read_events.json').write_bytes(encode(scripted[len(prefix):]))
    next_body = json.loads(next_payload[0]) if next_payload else {}
    return {'scripted_model_action': True, 'candidate_id': candidate['case_id'],
            'local_raw_read_only': True, 'status': 'ready' if next_payload else 'unfit',
            'input_tokens': next_payload[1] if next_payload else None,
            'raw_cases': sorted({row['case_id'] for row in next_body.get('excerpts', [])}),
            'assessment_tool_available': any(tool['name'] == 'assess_case_link'
                                             for tool in next_body.get('available_tools', [])),
            'pair_count': len(next_body.get('m6', {}).get('pair_refs', {})),
            'pending_source_count': next_body.get('pending_source_count'),
            'controller_inference_requests': 0, 'embedding_requests': 0}


def replay(root, source_run, output, *, dry_open_first=False):
    source_run, output = Path(source_run).resolve(), Path(output).resolve()
    if output == source_run or output.is_relative_to(source_run):
        raise HarnessError('Replay output must be outside the historical run')
    if output.exists():
        raise HarnessError('Replay requires fresh output directory')
    output.mkdir(parents=True)
    before = {str(path.relative_to(source_run)): sha256(path.read_bytes()).hexdigest()
              for path in source_run.rglob('*') if path.is_file()}
    events = Ledger(source_run).read()
    if not events or events[-1]['kind'] != 'run_stopped':
        raise HarnessError('Expected a terminal recorded run')
    prefix = events[:-1]
    state = RunState(prefix)
    if state.in_flight or state.active_action or state.pending_action:
        raise HarnessError('Replay requires a safe next-request boundary')
    plan = json.loads((source_run / 'plan.json').read_bytes())
    cfg = runner.settings(plan['settings'])
    captured = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(ModalQwenTransport, 'send_structured', side_effect=AssertionError('No inference allowed')))
        stack.enter_context(patch.object(HybridSearch, 'search', side_effect=AssertionError('No retrieval allowed')))
        harness, transport, _ = stack.enter_context(runner.runtime(Path(root), output, cfg, runner.Trace(output)))
        recorded_identity = state.config['identity']
        source_binding_fields = ('query_id', 'query_source_hash', 'candidate_fingerprint',
                                 'index_fingerprint', 'tools_fingerprint', 'tokenizer_fingerprint')
        if any(getattr(harness.identity, key) != recorded_identity[key] for key in source_binding_fields):
            raise HarnessError('Replay source/index/tools/tokenizer differ from the recorded run')
        harness.events = lambda: prefix
        harness.hybrid_search.journal = EmbeddingJournal(source_run, root, EmbeddingBudget(**cfg['embedding_budget']))
        counter = harness._count

        def count(body):
            tokens = counter(body)
            payload = json.loads(body)
            if 'm6' in payload:
                captured.append((tokens, payload))
            return tokens

        harness._count = count
        fixed_registry = harness._registry
        harness._registry = policy.OriginalAdaptiveHarness._registry.__get__(harness)
        with patch.dict(policy._m6.__dict__, {'catalog': lambda body: policy.catalog(body, compact_prompt=False)}):
            baseline = harness._fit_payload(state, cfg['budget']['max_payload_tokens'])
        baseline_best = min(captured, key=lambda row: row[0]) if captured else None
        if baseline_best:
            (output / 'baseline_smallest_payload.json').write_bytes(encode(baseline_best[1]))
        harness._registry = fixed_registry
        captured.clear()
        fitted = harness._fit_payload(state, cfg['budget']['max_payload_tokens'])
        best = min(captured, key=lambda row: row[0]) if captured else None
        payload = json.loads(fitted[0]) if fitted else best[1] if best else None
        decomposition = {}
        if payload:
            total = counter(encode(payload))
            for key in payload:
                reduced = dict(payload)
                reduced.pop(key)
                # Token counter only requires the output cap, which must remain.
                if key != 'max_output_tokens':
                    decomposition[key] = total - counter(encode(reduced))
            for key in payload.get('m6', {}):
                reduced = {**payload, 'm6': dict(payload['m6'])}
                reduced['m6'].pop(key)
                decomposition['m6.' + key] = total - counter(encode(reduced))
            (output / ('payload.json' if fitted else 'smallest_rejected_payload.json')).write_bytes(encode(payload))
        report = {'source_run': str(source_run), 'source_prefix_last_seq': prefix[-1]['seq'],
                  'source_stop': events[-1]['final'], 'input_cap': cfg['budget']['max_payload_tokens'],
                  'baseline_status': 'ready' if baseline else 'unfit',
                  'baseline_smallest_rendered_tokens': baseline_best[0] if baseline_best else None,
                  'status': 'ready' if fitted else 'unfit', 'input_tokens': fitted[1] if fitted else None,
                  'smallest_rendered_tokens': best[0] if best else None,
                  'render_attempts': len(captured), 'token_removal_deltas': decomposition,
                  'token_note': 'Removal deltas overlap and are not additive; full rendered prompt is authoritative.',
                  'candidate_ids': sorted(state.candidates),
                  'recorded_controller_requests': state.usage()['requests'],
                  'source_bindings_match': True,
                  'candidate_read_choices': [row['case_id'] for row in (payload or {}).get('m6', {}).get('candidates', {}).values()],
                  'controller_inference_requests': 0, 'embedding_requests': 0, 'retrieval_requests': 0,
                  'source_files_sha256': before, 'replay_code_binding': runner.code_binding(Path(root))}
        if dry_open_first:
            if not fitted:
                raise HarnessError('Cannot dry-open candidate without a fitting next payload')
            report['after_scripted_candidate_read'] = dry_open(harness, state, prefix, fitted, output)
    after = {str(path.relative_to(source_run)): sha256(path.read_bytes()).hexdigest()
             for path in source_run.rglob('*') if path.is_file()}
    if before != after:
        raise HarnessError('Historical run bytes changed during read-only replay')
    report['historical_run_unchanged'] = True
    (output / 'report.json').write_bytes(encode(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--dry-open-first-candidate', action='store_true')
    args = parser.parse_args()
    result = replay(args.root.resolve(), args.source_run, args.output_dir,
                    dry_open_first=args.dry_open_first_candidate)
    print(json.dumps({key: result[key] for key in ('status', 'input_tokens', 'smallest_rendered_tokens', 'historical_run_unchanged')}))


if __name__ == '__main__':
    main()
