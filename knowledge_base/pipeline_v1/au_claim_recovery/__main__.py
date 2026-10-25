"""Bounded length recovery. Prepare/preflight/dry run are offline."""
import argparse
import json
from pathlib import Path

from .core import prepare, preflight
from .runner import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'preflight', 'run'))
    parser.add_argument('--parent-root', type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--mock', action='store_true')
    args = parser.parse_args(argv)
    if args.execute:
        print(json.dumps({'status': 'disabled', 'reason': 'Length is a soft target; no model repair is allowed solely for exceeding it.',
                          'next': 'Use au_claim_soft import to revalidate saved responses offline.',
                          'network_executed': False}))
        return 1
    if args.command != 'run' and (args.execute or args.mock):
        parser.error('--execute/--mock apply only to run')
    if args.command == 'prepare' and args.parent_root is None:
        parser.error('--parent-root required for prepare')
    try:
        cfg = None
        if args.execute:
            from ..au_context_paired.__main__ import study_config
            cfg, _, _ = study_config(args)
        if args.command == 'prepare':
            w = prepare(args.parent_root, args.output_root)
            result = {'status': 'prepared', 'repair_requests': len(w['jobs'])}
        elif args.command == 'preflight':
            w = preflight(args.output_root / 'workload.json')
            result = {'status': 'pass', 'repair_requests': len(w['jobs'])}
        else:
            result = run(args.output_root, cfg=cfg, execute=args.execute, mock=args.mock)
        report = args.output_root / 'workload.json'
        if args.command == 'run' and (args.execute or args.mock):
            report = args.output_root / ('mock' if args.mock else 'live') / 'run.json'
        print(json.dumps({'status': result['status'], 'report': str(report),
                          'repair_requests': result.get('repair_requests'),
                          'new_logical_jobs': result.get('new_accounting', {}).get('logical_requests', 0),
                          'network_executed': result.get('network_executed', False),
                          'semantic_quality': 'not_assessed'}, ensure_ascii=False))
        return 0 if result['status'] in ('prepared', 'pass', 'complete', 'not_executed') else 1
    except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
