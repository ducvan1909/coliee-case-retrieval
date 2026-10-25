"""Offline CLI; no remote execution path."""
import argparse
from .core import run, BASE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('run')
    command.add_argument('--output-root', required=True)
    command.add_argument('--kos-root', default='G:/Legal-AI/kos_sample')
    defaults = {'kos-manifest': BASE / 'manifests/selected_kos_manifest.v1.json',
                'source-store': BASE / 'outputs/source_store_v1',
                'block-manifest': BASE / 'outputs/plan03_source_blocks_v1/sourceblock_build_manifest.json',
                'atom-manifest': BASE / 'outputs/plan04_sentence_atoms_v1/sentence_atom_build_manifest.json',
                'block-policy': BASE / 'policies/sourceblock_policy.v1.json',
                'atom-policy': BASE / 'policies/sentence_atom_policy.v1.json'}
    for key, value in defaults.items():
        command.add_argument('--' + key, default=str(value))
    args = vars(parser.parse_args()); args.pop('command')
    try:
        report = run(**args)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, 'OFFLINE FAILED: ' + str(exc) + '\n')
    print('OFFLINE MATERIALIZED protocol=' + report['protocol_status'] + ' semantic=not_assessed ' + args['output_root'])
    return 0 if report['protocol_status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
