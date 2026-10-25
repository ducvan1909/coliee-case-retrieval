"""Explicit local build/preflight/review, opt-in remote smoke and pilot."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit
from knowledge_base.config import settings
from ..au_runtime_config import load_au_runtime_config
from .build import build, read_json, write_new, DEFAULT_SOURCE_STORE, DEFAULT_ATOM_ROOT, PairedError
from .preflight import preflight
from .review import reference_checklist, validate_checklist, write_review
from .compare import compare

def study_config(args):
    cfg, budget, policy = load_au_runtime_config(settings(), 'AU_COMPACT_')
    # The study profile is explicit CLI behavior; .env is never changed.
    cfg['transport'], cfg['string_decoder'] = 'jobs', 'host_validated'
    if cfg['url'].endswith('/v1/chat/completions'):
        cfg['jobs_url'] = cfg['url'][:-len('/chat/completions')] + '/jobs'
    elif not cfg.get('jobs_url'):
        raise PairedError('AU_JOBS_URL required for nonstandard URL')
    parsed = urlsplit(cfg['url'])
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PairedError('endpoint URL must not contain credentials or query secrets')
    for key in budget:
        override = getattr(args, key, None)
        if override is not None:
            if override < 1:
                raise PairedError('budget overrides must be positive')
            budget[key] = override
    policy['max_attempts'] = min(policy['max_attempts'], 50)
    policy['max_wait_seconds'] = min(policy['max_wait_seconds'], 600)
    return cfg, budget, policy

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'preflight', 'run', 'review-packet', 'compare', 'migrate'))
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--workload')
    parser.add_argument('--run')
    parser.add_argument('--decisions')
    parser.add_argument('--reference-checklist')
    parser.add_argument('--runtime-archive')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--source-store', default=str(DEFAULT_SOURCE_STORE))
    parser.add_argument('--atom-root', default=str(DEFAULT_ATOM_ROOT))
    for key in ('max_requests', 'max_provider_attempts', 'max_total_input_tokens', 'max_total_output_tokens'):
        parser.add_argument('--' + key.replace('_', '-'), type=int)
    args = parser.parse_args(argv)
    try:
        root = Path(args.output_root)
        if args.command == 'build':
            cfg, _, _ = study_config(args)
            value = build(root, cfg=cfg, source_store=args.source_store, atom_root=args.atom_root)
            write_new(root / 'reference_checklist.json', reference_checklist(value))
            print(f"PAIRED BUILD {value['status'].upper()} targets={len(value['pairs'])} requests={len(value['manifest']['requests'])} — {root / 'workload.json'}")
            return 0
        if not args.workload:
            parser.error('--workload required')
        value = read_json(args.workload)
        if args.command == 'migrate':
            if not args.run or not args.reference_checklist:
                parser.error('migrate requires --run and --reference-checklist')
            if args.execute:
                raise PairedError('migration is local only; omit --execute')
            from .migration import migrate, ARCHIVE
            cfg, _, _ = study_config(args)
            result = migrate(args.workload, Path(args.run).parent, args.reference_checklist,
                             root, cfg=cfg, archive_root=args.runtime_archive or ARCHIVE)
            print(f"PAIRED MIGRATION {result['status'].upper()} — {root / 'migration_manifest.json'}")
            return 0
        if args.command == 'preflight':
            cfg, budget, _ = study_config(args)
            result = preflight(value, cfg=cfg, budget=budget, source_store=args.source_store, atom_root=args.atom_root)
            write_new(root / 'preflight.json', result)
            print(f"PAIRED PREFLIGHT {result['status'].upper()} — {root / 'preflight.json'}")
            return 0 if result['status'] == 'pass' else 2
        if args.command == 'run':
            cfg, budget, policy = study_config(args)
            if args.execute:
                if not args.reference_checklist:
                    raise PairedError('--reference-checklist required before remote extraction')
                validate_checklist(read_json(args.reference_checklist), value, require_locked=True)
            from .runner import run
            result = run(value, source_store=args.source_store, atom_root=args.atom_root, cfg=cfg, budget=budget,
                         output_root=root, execute=args.execute, smoke=args.smoke, warmup_policy=policy)
            from ..au_compact.runner import _atomic
            _atomic(root / 'run.json', result)
            print(f"PAIRED RUN {result['status'].upper()} — {root / 'run.json'}")
            return 0 if result['status'] in ('complete', 'smoke_complete', 'planned', 'not_executed') else 3
        if not args.run:
            parser.error('--run required')
        report = read_json(args.run)
        if args.command == 'review-packet':
            packet = write_review(value, report, root)
            print(f"PAIRED REVIEW PENDING rows={len(packet['rows'])} — {root / 'blind_review_packet.json'}")
            return 0
        result = compare(value, report, read_json(args.decisions) if args.decisions else None)
        write_new(root / 'comparison.json', result)
        print(f"PAIRED COMPARISON {result['semantic_review_status'].upper()} — {root / 'comparison.json'}")
        return 0
    except (ValueError, KeyError, OSError) as exc:
        # Exception types from providers are handled inside runner; never echo cfg.
        print('PAIRED ERROR ' + str(exc))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
