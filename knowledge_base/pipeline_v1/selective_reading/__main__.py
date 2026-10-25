"""Local prepare/preflight; remote run is reserved for Main."""
from __future__ import annotations

import argparse
from pathlib import Path
from knowledge_base.config import settings
from ..au_runtime_config import load_au_runtime_config
from ..milestone1.core import ROOT, load, digest
from ..bulk_execution.storage import write_json
from .core import (VERSION, CAPS, build_manifest, prepare, host_selection,
                   extraction_task, planner_task)
from .catalog import get_case_overview, read_region
from .runtime import _output_root
from . import run


def preflight(manifest, tasks, arm):
    cases = sorted({t['request']['case_id'] for t in tasks})
    selection = {case: host_selection(tasks, manifest['seed'], case) for case in cases}
    h_initial = [extraction_task(read_region(tasks, nav), manifest, 'H', 'initial')
                 for case in cases for nav in selection[case]]
    plans = [planner_task(manifest, case, get_case_overview(tasks, case)) for case in cases]
    # Planner IDs are not guessed. Use the three largest eligible payloads per
    # case as the initial P byte bound; actual selection occurs only after plan.
    p_bound = sum(sum(sorted((extraction_task(t, manifest, 'P', 'initial')['estimate']
                            for t in tasks if t['request']['case_id'] == case), reverse=True)[:3])
                  for case in cases) + sum(p['estimate'] for p in plans)
    groups = [h_initial[i:i+4] for i in range(0, len(h_initial), 4)]
    group_estimates = [sum(t['estimate'] for t in g) for g in groups]
    h_bytes = sum(t['estimate'] for t in h_initial)
    if h_bytes > CAPS['input_estimate_bytes'] or any(n > CAPS['actual_input_tokens'] for n in group_estimates):
        raise ValueError('initial_local_admission_impossible')
    return {'status': 'pass', 'version': VERSION, 'manifest_sha256': digest(manifest),
        'universe_sha256': manifest['universe_sha256'], 'arm': arm,
        'universe_targets': 30, 'initial_extractions_per_arm': 15, 'server_concurrency': 4,
        'caps': CAPS, 'H_initial_estimated_input_bytes': h_bytes,
        'P_initial_estimated_input_bytes_upper_bound': p_bound,
        'H_initial_reservations': [{'requests': len(g), 'estimate_bytes': n,
            'conservative_input_reservation_fits_from_zero': n <= CAPS['actual_input_tokens']}
            for g, n in zip(groups, group_estimates)],
        'admission_policy': 'groups_max4_commit_provider_usage_then_reserve_next',
        'actual_admission_simulation': 'first_group_checked_later_groups_depend_on_provider_usage',
        'estimate_is_provider_usage': False, 'planner_decoder': 'closed_exact_JSON_strings_no_fallback',
        'planner_output_token_cap': 800,
        'planner_longest_output_utf8_bytes': max(len(o.encode()) for p in plans for o in p['allowed_outputs']),
        'H_selected_navigation_ids': selection, 'remote_calls': 0,
        'semantic_quality_claim': False, 'execution_evidence': 'local_preflight'}


def main():
    parser = argparse.ArgumentParser(description='EXACT30 H/P selective-reading pilot')
    parser.add_argument('command', choices=['prepare', 'preflight', 'run'])
    parser.add_argument('--parent-manifest', default=str(ROOT/'outputs/bulk_trial30_20261013/manifest.json'))
    parser.add_argument('--manifest')
    parser.add_argument('--workload-id', default='selective_trial30_20261013')
    parser.add_argument('--seed', type=int, default=20261013)
    parser.add_argument('--arm', choices=['H', 'P'], default='H')
    parser.add_argument('--source-store', default=str(ROOT/'outputs/source_store_v1'))
    parser.add_argument('--atom-root', default=str(ROOT/'outputs/plan04_sentence_atoms_v1'))
    parser.add_argument('--url')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume-input-estimate-bytes',type=int)
    args = parser.parse_args()
    try:
        if args.execute and args.command != 'run':
            raise ValueError('execute_only_for_run')
        root = Path(args.output_root).resolve()
        path = Path(args.manifest or root/'manifest.json').resolve()
        if args.command == 'prepare':
            manifest = build_manifest(load(args.parent_manifest), args.workload_id, args.seed)
        else:
            manifest = load(path)
        _output_root(root, args.source_store, args.atom_root, manifest)
        if (path == Path(args.parent_manifest).resolve() or any(path.is_relative_to(Path(p).resolve())
                for p in (args.source_store, args.atom_root, ROOT/'outputs/bulk_trial30_20261013'))):
            raise ValueError('manifest_overwrites_dependency')
        tasks = prepare(manifest, args.source_store, args.atom_root)
        if args.command in ('prepare', 'preflight'):
            if path.exists() and load(path) != manifest:
                raise ValueError('locked_manifest_conflict')
            if args.command == 'prepare' and not path.exists():
                write_json(path, manifest)
            report = preflight(manifest, tasks, args.arm)
            write_json(root/'preflight.json', report)
            write_json(root/'prepared.json', {'manifest_sha256': digest(manifest),
                'case_overviews': [get_case_overview(tasks, c) for c in sorted({t['request']['case_id'] for t in tasks})]})
            print(f'SELECTIVE LOCAL PREFLIGHT PASS targets=30 — {root/"preflight.json"}')
            return 0
        if not args.execute or not args.url:
            raise ValueError('run_requires_execute_and_explicit_bulk_url')
        cfg, _, policy = load_au_runtime_config(settings(), 'AU_COMPACT_')
        if not cfg.get('token'):
            raise ValueError('runtime_credentials_missing')
        cfg['url'] = args.url
        report = run(manifest, cfg, args.arm, root, execute=True, source_store=args.source_store,
                     atom_root=args.atom_root, policy=policy,resume_input_estimate_bytes=args.resume_input_estimate_bytes)
        print(f'SELECTIVE {args.arm} {report["status"].upper()} selective_pass={report["selective_pass"]} — {root/"run.json"}')
        return 0 if report['status'] == 'complete' else 3
    except Exception as exc:
        safe = str(exc)
        if len(safe) > 100 or not safe.replace('_', '').isalnum():
            safe = type(exc).__name__
        print(f'SELECTIVE ERROR {safe}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
