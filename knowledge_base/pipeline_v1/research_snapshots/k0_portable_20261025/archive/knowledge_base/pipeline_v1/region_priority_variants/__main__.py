"""Offline CLI with explicit sequential stages and mandatory Stage 1 lock."""
import argparse
from .core import run, BASE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('order', 'context'), required=True)
    parser.add_argument('--output-root')
    parser.add_argument('--order-report')
    parser.add_argument('--kos-root', default='G:/Legal-AI/kos_sample')
    parser.add_argument('--baseline-root', default=str(BASE / 'outputs/region_priority_offline_20261013'))
    defaults = {'kos-manifest': BASE / 'manifests/selected_kos_manifest.v1.json',
                'source-store': BASE / 'outputs/source_store_v1',
                'block-manifest': BASE / 'outputs/plan03_source_blocks_v1/sourceblock_build_manifest.json',
                'atom-manifest': BASE / 'outputs/plan04_sentence_atoms_v1/sentence_atom_build_manifest.json',
                'block-policy': BASE / 'policies/sourceblock_policy.v1.json',
                'atom-policy': BASE / 'policies/sentence_atom_policy.v1.json'}
    for key, value in defaults.items():
        parser.add_argument('--' + key, default=str(value))
    args = vars(parser.parse_args())
    try:
        report = run(**args)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, 'OFFLINE FAILED: ' + str(exc) + '\n')
    print('OFFLINE MATERIALIZED stage=' + report['stage'] + ' protocol=' + report['protocol_status'] +
          ' semantic=not_assessed seconds=' + str(round(report['cost']['latency_seconds'], 3)))
    return 0 if report['protocol_status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
