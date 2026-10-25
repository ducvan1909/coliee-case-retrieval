"""Origin export, offline inspection, and opt-in portable bounded authoring."""
import argparse
import json

from . import core


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('export', 'inspect', 'prepare', 'preflight', 'run'))
    p.add_argument('--repo-root')
    p.add_argument('--bundle', default=core.DEFAULT_BUNDLE)
    p.add_argument('--output-root', default=core.DEFAULT_RUN)
    p.add_argument('--history-root')
    p.add_argument('--controls-root')
    p.add_argument('--check-runtime', action='store_true')
    p.add_argument('--refresh-derived', action='store_true')
    p.add_argument('--max-new-requests', type=int, choices=range(1, 13))
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--mock', action='store_true')
    a = p.parse_args(argv)
    if a.command != 'run' and (a.execute or a.mock or a.max_new_requests is not None):
        p.error('execution flags apply only to run')
    if a.command != 'export' and (a.history_root or a.controls_root):
        p.error('origin roots apply only to export')
    try:
        if a.command == 'export':
            result = core.export(a.bundle, a.repo_root, a.history_root, a.controls_root, a.refresh_derived)
        elif a.command == 'inspect':
            result = core.inspect(a.bundle, a.repo_root, a.check_runtime)
        elif a.command == 'prepare':
            result = core.prepare(a.output_root, a.bundle, a.repo_root)
        elif a.command == 'preflight':
            result = core.preflight(a.output_root, a.repo_root)
        else:
            from .runner import run
            result = run(a.output_root, a.repo_root, execute=a.execute, mock=a.mock,
                         max_new_requests=a.max_new_requests)
        printable = dict(result)
        if 'history' in printable:
            h = printable['history']
            printable['history'] = {k: h[k] for k in ('status', 'logical_requests',
                'protocol_counts', 'work_scope_complete', 'total_provider_usage', 'semantic_quality')}
            printable['history']['AU_count'] = sum(len(r['state']['drafts']) for r in h['results'])
        print(json.dumps(printable, ensure_ascii=False))
        return 3 if result['status'] == 'incomplete' else 0
    except Exception as exc:
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__,
            'reason': str(exc), 'semantic_quality': 'not_assessed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
