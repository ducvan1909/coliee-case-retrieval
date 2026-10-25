"""Run one offline experiment into a new empty output directory."""
import argparse
from .core import run, DEFAULT_BASELINE, DEFAULT_ORDER_REPORT, DEFAULT_CONTEXT_REPORT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--baseline-root', default=str(DEFAULT_BASELINE))
    parser.add_argument('--order-report', default=str(DEFAULT_ORDER_REPORT))
    parser.add_argument('--context-report', default=str(DEFAULT_CONTEXT_REPORT))
    parser.add_argument('--kos-root', default='G:/Legal-AI/kos_sample')
    args = vars(parser.parse_args())
    try:
        report = run(**args)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, 'OFFLINE FAILED: ' + str(exc) + '\n')
    print('OFFLINE protocol=' + report['protocol_status'] + ' semantic=not_assessed actual_requests=0 report=' + str(args['output_root']) + '/report.json')
    return 0 if report['protocol_status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
