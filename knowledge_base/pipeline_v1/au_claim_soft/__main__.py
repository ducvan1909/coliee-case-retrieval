"""Reclassify original responses offline; never call a provider."""
import argparse
import json
from pathlib import Path
from .core import import_run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['import'])
    parser.add_argument('--parent-root', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = import_run(args.parent_root, args.output_root)
    except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__}))
        return 1
    print(json.dumps({k: report[k] for k in ('status', 'target_count', 'warning_count',
                     'needs_context', 'network_requests', 'semantic_quality')}))
    return 0 if report['protocol_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
