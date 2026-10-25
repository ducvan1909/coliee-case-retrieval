"""K0 CLI: local prepare/preflight, dry run, and explicit mock/live modes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'preflight', 'run'))
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--parent-root', type=Path)
    parser.add_argument('--max-new-requests', type=int, choices=range(1, 13))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--mock', action='store_true')
    args = parser.parse_args(argv)
    if args.command != 'run' and (args.execute or args.mock or args.max_new_requests is not None):
        parser.error('--execute/--mock/--max-new-requests apply only to run')
    if args.command != 'prepare' and args.parent_root is not None:
        parser.error('--parent-root applies only to prepare')
    try:
        from . import core
        from ..au_compact.runner import _atomic
        from ..au_context_paired.__main__ import study_config
        root = args.output_root.resolve()
        workload = root / 'input' / 'workload.json'
        if args.command == 'prepare':
            options = {} if args.parent_root is None else {'parent_root': args.parent_root}
            value = core.prepare(root, **options)
            # Prepare is local; validate the current configured structural identity too.
            cfg, _, _ = study_config(args)
            core.preflight(value, cfg=cfg)
            result, path = {'status': 'prepared'}, workload
        elif args.command == 'preflight':
            cfg, _, _ = study_config(args)
            result = core.preflight(workload, cfg=cfg)
            path = root / 'input' / 'preflight.json'
            _atomic(path, result)
        else:
            from .runner import run
            cfg, _, _ = study_config(args)
            result = run(workload, output_root=root, cfg=cfg, execute=args.execute, mock=args.mock,
                         max_new_requests=args.max_new_requests)
            path = root / ('live' if args.execute else 'mock' if args.mock else 'dryrun') / 'run.json'
            if not args.execute and not args.mock:
                _atomic(path, result)
        print(json.dumps({'status': result['status'], 'report': str(path),
                          'execution_requested': args.execute, 'semantic_quality': 'not_assessed'}))
        return 0 if result['status'] in ('prepared', 'pass', 'complete', 'not_executed') else 1
    except Exception as exc:
        # Types only: exception messages may contain provider text or credentials.
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__,
                          'execution_requested': args.execute, 'semantic_quality': 'not_assessed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
