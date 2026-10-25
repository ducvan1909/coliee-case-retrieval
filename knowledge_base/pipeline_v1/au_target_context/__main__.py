"""Local prepare/preflight/dryrun/mock and explicit jobs execution."""
import argparse
import json
from pathlib import Path

from .core import prepare, preflight, load, DEFAULT_MANIFEST, DEFAULT_PARENT, guard_output
from .runner import run
from .prompts import DEFAULT_PROMPT_PROFILE, PROMPT_PROFILES
from ..au_context_paired.__main__ import study_config
from ..au_context_paired.build import write_new


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'preflight', 'run', 'anchor-order-probe'))
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--parent-workload', type=Path, default=DEFAULT_PARENT)
    parser.add_argument('--workload', type=Path)
    parser.add_argument('--prompt-profile', choices=PROMPT_PROFILES, default=None,
                        help='prepare or anchor-order-probe; defaults baseline_v2 / evidence_first_v1')
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--target-id', action='append', dest='target_ids')
    parser.add_argument('--concurrency', type=int, choices=range(1, 5), default=4)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--mock', action='store_true')
    args = parser.parse_args(argv)
    if args.command not in ('prepare', 'anchor-order-probe') and args.prompt_profile is not None:
        parser.error('--prompt-profile applies only to prepare; no runtime override')
    if args.command not in ('run', 'anchor-order-probe') and (args.execute or args.mock or args.target_ids):
        parser.error('--execute/--mock/--target-id apply only to run')
    if args.command not in ('prepare', 'anchor-order-probe') and not args.workload:
        parser.error('--workload required for preflight/run')
    try:
        cfg, _, _ = study_config(args)
        if args.command == 'anchor-order-probe':
            if args.workload or args.target_ids:
                parser.error('anchor-order-probe uses only synthetic jobs; omit --workload/--target-id')
            from .anchor_order_probe import run_probe
            result = run_probe(args.output_root, cfg=cfg, execute=args.execute, mock=args.mock,
                               concurrency=args.concurrency,
                               prompt_profile=args.prompt_profile or 'evidence_first_v1')
            print(json.dumps({'status': result['status'], 'report': str(args.output_root / 'probe.json'),
                              'endpoint_constraint_status': result['endpoint_constraint_status'],
                              'network_executed': result['network_executed'], 'semantic_quality': 'not_assessed'}))
            if args.execute:
                return 0 if (result['status'] == 'complete' and
                             result['endpoint_constraint_status'] == 'observed_valid_positive') else 1
            return 0 if result['status'] in ('prepared', 'complete') else 1
        if args.command == 'prepare':
            value = prepare(args.output_root, manifest=args.manifest, parent=args.parent_workload, cfg=cfg,
                            prompt_profile=args.prompt_profile or DEFAULT_PROMPT_PROFILE)
            result = {'status': 'prepared', 'target_count': len(value['rows']),
                      'prompt_profile': value['prompt_profile'], 'prompt_sha': value['prompt_sha']}
            path = args.output_root / 'workload.json'
        elif args.command == 'preflight':
            value = load(args.workload)
            result = preflight(value, cfg=cfg)
            guard_output(args.output_root, [args.workload.parent, value['source_store'], value['atom_root'],
                                           DEFAULT_MANIFEST.parent, DEFAULT_PARENT.parent])
            path = args.output_root / 'preflight.json'
            write_new(path, result)
        else:
            result = run(args.workload, output_root=args.output_root, cfg=cfg,
                         execute=args.execute, mock=args.mock, concurrency=args.concurrency,
                         target_ids=args.target_ids)
            path = args.output_root / 'run.json'
            if not args.execute and not args.mock:
                value = load(args.workload)
                guard_output(args.output_root, [args.workload.parent, value['source_store'], value['atom_root'],
                                               DEFAULT_MANIFEST.parent, DEFAULT_PARENT.parent])
                write_new(path, result)
        print(json.dumps({'status': result['status'], 'report': str(path),
                          'prompt_profile': result['prompt_profile'], 'prompt_sha': result['prompt_sha'],
                          'network_executed': bool(args.execute), 'semantic_quality': 'not_assessed'}))
        return 0 if result['status'] in ('prepared', 'pass', 'complete', 'not_executed') else 1
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__,
                          'network_execution_authorized': bool(args.execute)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
