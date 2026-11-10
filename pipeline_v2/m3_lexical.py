"""Read-only full-corpus BM25; never imports Modal or loads credentials."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('search', 'revalidate'):
        p = subs.add_parser(name)
        p.add_argument('--run-dir', default=None)
        if name == 'search':
            p.add_argument('--query', required=True)
            p.add_argument('--channel', choices=('case', 'passage'), required=True)
            p.add_argument('--limit', type=int, default=100)
            p.add_argument('--query-case')
            p.add_argument('--unique-cases', action='store_true')
    args = parser.parse_args(argv)
    started = time.perf_counter(); session = None
    try:
        from .full_search.lexical import LexicalSession
        session = LexicalSession(ROOT, args.run_dir)
        if args.command == 'revalidate':
            result = session.revalidate()
        else:
            result = session.search(args.query, args.channel, args.limit, args.query_case, args.unique_cases)
        result['internal_cli_seconds'] = time.perf_counter() - started
        result['cli_timing_origin'] = 'after_argument_parse_excludes_process_startup'
        print(json.dumps(result, ensure_ascii=True, sort_keys=True)); return 0
    except Exception as exc:
        from .retrieval.common import M3Error
        print(json.dumps({'status': 'error', 'error': str(exc) if isinstance(exc, M3Error) else type(exc).__name__,
                          'internal_cli_seconds': time.perf_counter() - started}), file=sys.stderr)
        return 2
    finally:
        if session is not None:
            session.close()


if __name__ == '__main__':
    raise SystemExit(main())
