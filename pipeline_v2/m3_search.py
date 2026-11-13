"""Local source reading tools for the accepted M3 corpus snapshot."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('search-case', 'case-map', 'case-anchors', 'search-phrase',
                 'search-identity', 'open-source', 'revalidate'):
        command = commands.add_parser(name)
        if name != 'revalidate':
            command.add_argument('--case-id', required=name not in ('search-phrase', 'search-identity'))
        if name.startswith('search-'):
            command.add_argument('--text', required=True)
        if name in ('search-case', 'search-phrase', 'search-identity', 'open-source'):
            command.add_argument('--cursor')
        if name in ('case-map', 'case-anchors'):
            command.add_argument('--offset', type=int, default=0)
        if name not in ('open-source', 'revalidate'):
            command.add_argument('--limit', type=int, default=20)
        if name == 'search-case':
            command.add_argument('--mode', choices=('lexical', 'literal'), default='lexical')
        if name == 'case-anchors':
            command.add_argument('--handle')
            command.add_argument('--source', action='store_true')
        if name in ('search-phrase', 'search-identity'):
            command.add_argument('--case-scan-limit', type=int)
        if name == 'search-phrase':
            command.add_argument('--matching-mode', choices=('exact_case_sensitive', 'unicode_casefold_mapped'),
                                 default='exact_case_sensitive')
        if name == 'open-source':
            command.add_argument('--source-hash', required=True)
            command.add_argument('--handle', action='append', default=[])
            command.add_argument('--passage-id', action='append', default=[])
            command.add_argument('--hit-span', action='append', default=[], help='START:END UTF-8 byte offsets')
            command.add_argument('--byte-budget', type=int, default=65536)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    cli_request_id = uuid.uuid4().hex
    phase = 'session_open'
    session_initialization_seconds = None
    session = None
    try:
        from .full_search.source_tools import SourceToolsSession
        session = SourceToolsSession(ROOT)
        session_initialization_seconds = time.perf_counter() - started
        phase = 'tool'
        if args.command == 'case-map':
            result = session.case_map(args.case_id, args.offset, args.limit)
        elif args.command == 'case-anchors':
            result = session.case_anchors(args.case_id, args.handle, args.offset, args.limit, args.source)
        elif args.command == 'search-case':
            result = session.search_case(args.case_id, args.text, args.mode, args.limit, args.cursor)
        elif args.command == 'search-phrase':
            result = session.search_phrase(args.text, args.case_id, args.matching_mode,
                                            args.limit, args.cursor, args.case_scan_limit)
        elif args.command == 'search-identity':
            result = session.search_identity(args.text, args.case_id, args.limit,
                                              args.cursor, args.case_scan_limit)
        elif args.command == 'open-source':
            spans = [[int(part) for part in span.split(':')] for span in args.hit_span]
            result = session.open_source(args.case_id, args.source_hash, args.handle,
                                         args.passage_id, spans, args.byte_budget, args.cursor)
        else:
            result = session.revalidate()
        result.update(internal_cli_seconds=time.perf_counter() - started,
                      cli_timing_origin='after_argument_parse_excludes_process_startup',
                      cli_request_id=cli_request_id, phase=phase,
                      session_initialization_seconds=session_initialization_seconds)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        from .retrieval.common import M3Error
        elapsed = time.perf_counter() - started
        if phase == 'session_open':
            session_initialization_seconds = elapsed
        error = {'status': 'error', 'error_type': type(exc).__name__, 'model_requests': 0,
                 'internal_cli_seconds': elapsed,
                 'cli_timing_origin': 'after_argument_parse_excludes_process_startup',
                 'cli_request_id': cli_request_id, 'phase': phase,
                 'session_initialization_seconds': session_initialization_seconds}
        if isinstance(exc, M3Error):
            error['error'] = str(exc)
        print(json.dumps(error), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 2
    finally:
        if session is not None:
            session.close()


if __name__ == '__main__':
    raise SystemExit(main())
