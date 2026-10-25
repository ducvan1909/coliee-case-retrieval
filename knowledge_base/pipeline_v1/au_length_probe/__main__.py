"""Bounded command line; a watchdog also caps blocking native compilation."""
import argparse
import json
import multiprocessing
from pathlib import Path

from .core import ORIGINAL_VARIANTS, VARIANTS, _identity, _write, offline, prepare, runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'offline', 'runtime'))
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--tokenizer-path', type=Path)
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=list(ORIGINAL_VARIANTS))
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--max-seconds', type=float, default=120)
    parser.add_argument('--max-cases', type=int, default=256)
    parser.add_argument('--report-max-bytes', type=int, default=2_000_000)
    args = parser.parse_args()
    if (not 1 <= args.max_seconds <= 600 or not 1 <= args.max_cases <= 256
            or not 1 <= args.repeats <= 10 or not 4096 <= args.report_max_bytes <= 5_000_000):
        parser.error('limits: seconds 1..600, cases 1..256, repeats 1..10, report bytes 4096..5000000')
    if args.output_root.exists(): parser.error('output root already exists; no overwrites')
    try:
        if args.command == 'prepare':
            report = prepare(args.output_root, report_max_bytes=args.report_max_bytes)
        elif args.command == 'runtime':
            report = runtime(args.output_root, max_seconds=args.max_seconds, report_max_bytes=args.report_max_bytes)
        else:
            if args.tokenizer_path is None: parser.error('offline requires --tokenizer-path')
            kwargs = dict(tokenizer_path=args.tokenizer_path, output_root=args.output_root,
                          variants=args.variants, repeats=args.repeats, max_seconds=args.max_seconds,
                          max_cases=args.max_cases, report_max_bytes=args.report_max_bytes)
            process = multiprocessing.get_context('spawn').Process(target=offline, kwargs=kwargs)
            process.start(); process.join(args.max_seconds)
            timed_out = process.is_alive()
            if timed_out:
                process.terminate(); process.join(5)
                if process.is_alive(): process.kill(); process.join()
            path = args.output_root / 'report.json'
            if not path.exists():
                args.output_root.mkdir(parents=True, exist_ok=True)
                report = _write(args.output_root, {**_identity(), 'status': 'TIME_LIMIT' if timed_out else 'ERROR',
                                'recommended': None}, args.report_max_bytes)
            else: report = json.loads(path.read_text(encoding='utf-8'))
        print(json.dumps({'status': report['status'], 'report': str(args.output_root / 'report.json')}))
        return 0 if report['status'] in ('PREPARED', 'PASS', 'OBSERVED') else 2
    except Exception as exc:
        # Never render exception messages: transport/config errors can carry secrets.
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
