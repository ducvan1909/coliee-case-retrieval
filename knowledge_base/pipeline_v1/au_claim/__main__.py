"""Claim-first AU pilot: offline by default, explicit remote execution."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'preflight', 'run', 'compare'))
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--parent-workload', type=Path)
    parser.add_argument('--workload', type=Path)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--baseline-run', type=Path)
    parser.add_argument('--concurrency', type=int, choices=range(1,5), default=2)
    parser.add_argument('--target-id', action='append', dest='target_ids')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--mock', action='store_true')
    args = parser.parse_args(argv)
    if args.command != 'prepare' and args.workload is None:
        parser.error('--workload required')
    if args.command != 'run' and (args.execute or args.mock or args.target_ids):
        parser.error('--execute/--mock/--target-id apply only to run')
    if args.command == 'compare' and args.run is None:
        parser.error('--run required for compare')
    try:
        from . import core
        from ..au_context_paired.build import write_new
        if args.command == 'compare':
            from .compare import compare
            value = compare(args.workload, args.run, args.output_root, baseline_run=args.baseline_run)
            path = args.output_root / 'comparison.json'
        else:
            from ..au_context_paired.__main__ import study_config
            cfg, _, _ = study_config(args)
            if args.command == 'prepare':
                options = {'cfg':cfg}
                if args.parent_workload is not None:
                    options['parent_workload'] = args.parent_workload
                value = core.prepare(args.output_root, **options)
                path = args.output_root / 'workload.json'
                value = {'status':'prepared', 'target_count':len(value['rows'])}
            elif args.command == 'preflight':
                value = core.preflight(args.workload, cfg=cfg)
                w = core.load(args.workload)
                core.guard_output(args.output_root, [args.workload.parent, w['source_store'],w['atom_root']])
                path = args.output_root / 'preflight.json'
                write_new(path, value)
            else:
                from .runner import run
                value = run(args.workload, output_root=args.output_root, cfg=cfg,
                            execute=args.execute, mock=args.mock, concurrency=args.concurrency,
                            target_ids=args.target_ids)
                path = args.output_root / 'run.json'
                if not args.execute and not args.mock and not path.exists():
                    w = core.load(args.workload)
                    core.guard_output(args.output_root, [args.workload.parent,w['source_store'],w['atom_root']])
                    write_new(path, value)
        print(json.dumps({'status':value['status'],'report':str(path),
                          'execution_requested':bool(args.execute),'semantic_quality':'not_assessed'}))
        return 0 if value['status'] in ('prepared','pass','complete','not_executed','semantic_review_pending') else 1
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print(json.dumps({'status':'blocked','error_type':type(exc).__name__,
                          'execution_requested':bool(args.execute)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
