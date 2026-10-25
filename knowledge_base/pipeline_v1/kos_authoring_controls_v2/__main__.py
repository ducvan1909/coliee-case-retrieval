"""Prepare/preflight, dry-run by default, CPU-gated opt-in model execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import controls as c
from ..kos_authoring_controls.__main__ import require_cpu


def evaluate_row(row, receipt):
    result = {'name': row['name'], 'expected': row['expected'], 'status': 'invalid',
              'protocol_valid': False, 'semantic_quality': 'semantic_review_pending',
              'usage': receipt.get('usage'), 'latency_ms': receipt.get('latency_ms')}
    try:
        if receipt.get('status') != 'completed':
            raise ValueError('completed receipt required')
        body = receipt['raw_response']
        if body.get('model') != row['payload']['model'] or len(body['choices']) != 1:
            raise ValueError('model/choice mismatch')
        choice = body['choices'][0]
        if choice['finish_reason'] != 'stop':
            raise ValueError('incomplete generation')
        def pairs(items):
            if len({k for k, _ in items}) != len(items):
                raise ValueError('duplicate JSON keys')
            return dict(items)
        def constant(_):
            raise ValueError('nonfinite JSON')
        value = json.loads(choice['message']['content'], object_pairs_hook=pairs,
                           parse_constant=constant)
        normalized = c.validate(value, row['validation_job'])
        count, group = len(normalized['aus']), row['expected']['group']
        protocol = not normalized['au_errors']
        structural = protocol and count == row['expected']['AU_count']
        if group == 'negative':
            structural = structural and normalized['assessment_result'] == 'no_au_candidate'
        elif group == 'uncertain':
            structural = (structural and value['empty_reason'] in c.REASONS[3:]
                          and value['next_action'] == {'tool': 'finish_case', 'reason': 'needs_context'})
        else:
            structural = structural and normalized['work_scope_complete']
        result.update(status='structural_control_pass' if structural else 'control_failed',
                      protocol_valid=protocol, model_output=value, normalized=normalized,
                      AU_count=count)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        result['error_type'] = type(exc).__name__
    return result


def evaluate(root):
    c.preflight(root)
    root = Path(root)
    m = c.old.load(root / 'input/manifest.json')
    # Reuse the transport's local binding/digest/usage checks and orphan recovery.
    binding = c.old.load(root / 'live/binding.json')
    transport = c.execution.run_jobs(root / 'live', binding['config'], m['jobs'], execute=False)
    results = [evaluate_row(row, transport['receipts'].get(c.old.fingerprint(row['payload']), {}))
               for row in m['jobs']]
    controls_complete = (all(r['status'] == 'structural_control_pass' for r in results)
                         and transport['workload_status'] == 'complete')
    report = {'status': 'semantic_review_pending' if controls_complete else 'control_failed', 'rows': results,
              'protocol_valid_count': sum(r['protocol_valid'] for r in results),
              'structural_control_pass_count': sum(r['status'] == 'structural_control_pass' for r in results),
              'semantic_quality': 'semantic_review_pending', 'semantic_pass': False,
              'corpus_dispatch_allowed': False, 'K1_allowed': False,
              'code_sha256': c.code_hash(), 'manifest_sha256': m['sha256'],
              'POST_attempts': transport['POST_attempts'], 'actual_usage': transport['actual_usage'],
              'unknown_usage_count': transport['unknown_usage_count'],
              'budget_violation': transport['budget_violation']}
    report['sha256'] = c.old.fingerprint(report)
    c.v1._atomic(root / 'balanced_evaluation.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'preflight', 'run', 'evaluate'])
    parser.add_argument('--output-root', type=Path, default=c.DEFAULT_ROOT)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.execute and args.command != 'run':
            raise ValueError('--execute is only valid for run')
        if args.command == 'prepare':
            c.prepare(args.output_root)
            result = {'status': 'prepared', 'inference': 0}
        elif args.command == 'preflight':
            result = c.preflight(args.output_root)
        elif args.command == 'evaluate':
            result = evaluate(args.output_root)
        else:
            c.preflight(args.output_root)
            m = c.old.load(args.output_root / 'input/manifest.json')
            if not args.execute:
                result = {'status': 'not_executed', 'inference': 0, 'model_requests_planned': 9,
                          'workload_sha256': m['workload_sha256'],
                          'reserved_input_and_output_tokens': m['reserved_input_and_output_tokens']}
            else:
                require_cpu(args.output_root, 'balanced')
                from ..au_context_paired.__main__ import study_config
                cfg, _, _ = study_config(args)
                if c.runtime_identity(cfg) != m['identity']:
                    raise ValueError('frozen runtime identity mismatch')
                result = c.execution.run_jobs(args.output_root / 'live', cfg, m['jobs'], execute=True)
                if result['status'] == 'complete':
                    result = evaluate(args.output_root)
        print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'jobs', 'receipts')},
                         ensure_ascii=False))
        return 0 if result['status'] in ('prepared', 'pass', 'not_executed', 'complete',
                                        'semantic_review_pending') else 1
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
