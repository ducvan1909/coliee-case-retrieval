"""Run the full-corpus hybrid search or a local cached-vector diagnostic."""

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
    for command in ('search', 'diagnostic'):
        mode = commands.add_parser(command)
        mode.add_argument('--query', required=True)
        mode.add_argument('--query-case', required=True)
        mode.add_argument('--limit', type=int, default=20)
        if command == 'search':
            mode.add_argument('--env-file')
        else:
            mode.add_argument('--passage-id', required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    session = None
    try:
        from .full_search.hybrid import HybridSession
        if args.command == 'search':
            from .deploy_modal import build_environment, parse_env
            path = ROOT / (args.env_file or 'pipeline_v2/.env')
            settings = parse_env(path) if args.env_file or path.is_file() else {}
            os.environ.update(build_environment(settings))
        with HybridSession(ROOT) as session:
            if args.command == 'diagnostic':
                result = session.search_cached(args.query, args.query_case, args.passage_id, args.limit)
            else:
                result = session.search(args.query, args.query_case, args.limit)
        result['internal_cli_seconds'] = time.perf_counter() - started
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        from .retrieval.common import M3Error
        error = {'status': 'error', 'error_type': type(exc).__name__,
                 'internal_cli_seconds': time.perf_counter() - started}
        if isinstance(exc, M3Error):
            error['error'] = str(exc)
        if session is not None:
            error['request_id'] = session.last_request_id
        print(json.dumps(error), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 2


if __name__ == '__main__':
    raise SystemExit(main())
