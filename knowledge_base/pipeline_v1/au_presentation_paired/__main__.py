"""Explicit local preflight and opt-in frozen jobs execution."""
import argparse
import json
from pathlib import Path
from ..au_context_paired.__main__ import study_config
from ..au_compact.runner import _atomic
from .core import DEFAULT_MANIFEST, DEFAULT_PARENT, preflight
from .runner import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preflight', 'run'))
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--parent-workload', type=Path, default=DEFAULT_PARENT)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        cfg, _, _ = study_config(args)
        if args.command == 'preflight':
            if args.execute: parser.error('--execute applies only to run')
            result = preflight(args.manifest, parent=args.parent_workload, cfg=cfg)
            # An offline report is separate from the fresh execution directory.
            report_path = args.output_root.with_name(args.output_root.name + '.preflight.json')
            if report_path.exists():
                raise ValueError('preflight report exists; choose a fresh report/output name')
            _atomic(report_path, result)
        else:
            result = run(args.manifest, parent=args.parent_workload, output_root=args.output_root,
                         cfg=cfg, execute=args.execute)
            report_path = args.output_root / 'run.json' if args.execute else None
        print(json.dumps({'status': result['status'], 'report': str(report_path) if report_path else None,
                          'network_executed': bool(args.execute), 'semantic_quality': 'not_assessed'}))
        return 0 if result['status'] in ('pass', 'complete', 'not_executed') else 1
    except (ValueError, KeyError, OSError) as exc:
        # Never print configuration, credentials, or arbitrary provider errors.
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__, 'network_executed': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
