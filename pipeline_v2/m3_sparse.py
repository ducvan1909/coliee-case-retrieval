"""Build and query the immutable sparse BM25 sidecar."""

import argparse
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    builder = commands.add_parser('build')
    builder.add_argument('--output', required=True)
    for name in ('search', 'diagnostic-hybrid', 'search-hybrid'):
        command = commands.add_parser(name)
        command.add_argument('--index-dir')
        command.add_argument('--query', required=True)
        command.add_argument('--query-case')
        command.add_argument('--limit', type=int, default=20 if 'hybrid' in name else 100)
        if name == 'search':
            command.add_argument('--channel', choices=('case', 'passage'), required=True)
            command.add_argument('--unique-cases', action='store_true')
        if name == 'diagnostic-hybrid':
            command.add_argument('--passage-id', required=True)
        if name == 'search-hybrid':
            command.add_argument('--env-file')
    args = parser.parse_args(argv)
    started = time.perf_counter()
    session = None
    try:
        from .sparse_bm25.index import build_sparse, SparseSession, SparseHybridSession
        if args.command == 'build':
            result = build_sparse(ROOT, args.output)
        elif args.command == 'search':
            session = SparseSession(ROOT, args.index_dir)
            result = session.search(args.query, args.channel, args.limit, args.query_case, args.unique_cases)
        else:
            if args.command == 'search-hybrid':
                from .deploy_modal import parse_env, build_environment
                path = ROOT / (args.env_file or 'pipeline_v2/.env')
                settings = parse_env(path) if args.env_file or path.is_file() else {}
                os.environ.update(build_environment(settings))
            session = SparseHybridSession(ROOT, args.index_dir)
            if args.command == 'diagnostic-hybrid':
                result = session.search_cached(args.query, args.query_case, args.passage_id, args.limit)
            else:
                result = session.search(args.query, args.query_case, args.limit)
        result['internal_cli_seconds'] = time.perf_counter() - started
        result['cli_timing_origin'] = 'after_argument_parse_excludes_process_startup'
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        from .retrieval.common import M3Error
        error = {'status': 'error', 'error_type': type(exc).__name__,
                 'internal_cli_seconds': time.perf_counter() - started}
        if isinstance(exc, M3Error):
            error['error'] = str(exc)
        print(json.dumps(error), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 2
    finally:
        if session is not None:
            session.close()


if __name__ == '__main__':
    raise SystemExit(main())
