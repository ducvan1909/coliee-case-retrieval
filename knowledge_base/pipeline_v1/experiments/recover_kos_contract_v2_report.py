"""Offline recovery from immutable v2 evidence; never resumes transport."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from knowledge_base.pipeline_v1.kos_authoring_controls_v2 import controls as c
from knowledge_base.pipeline_v1.kos_authoring_controls_v2 import __main__ as cli


def build_report(root, output_dir=None):
    root = Path(root).resolve()
    destination = root / 'recovered_report'
    if output_dir is not None and Path(output_dir).resolve() != destination:
        raise ValueError('only root/recovered_report is writable')
    if destination.is_symlink() or destination.resolve() != destination:
        raise ValueError('redirected report directory')
    c.preflight(root)
    cli.require_cpu(root, 'balanced')
    e = c.execution
    digest = e.payload_digest
    manifest = e._load(root / 'input/manifest.json')
    binding = e._load(root / 'live/binding.json')
    binding_sha = digest(binding)  # Preserve persisted numeric JSON types exactly.
    entries = [dict(row, job_id=digest(row['payload']),
                    input_reservation=c.token_budget.input_reservation(row['payload']))
               for row in manifest['jobs']]
    files = [Path(e.__file__), Path(e.complete_job.__code__.co_filename),
             Path(sys.modules[e.ReadinessGate.__module__].__file__), Path(c.token_budget.__file__)]
    runtime = {'python': sys.version, 'platform': platform.platform(),
               'code': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
               'counter': c.token_budget.counter_identity()}
    limits = [e.MAX_POSTS, e.MAX_INPUT, e.MAX_OUTPUT, e.MAX_TOTAL]
    cfg = binding['config']
    if (set(binding) != {'version', 'jobs', 'config', 'runtime', 'limits'}
            or binding['version'] != 1 or digest(binding['jobs']) != digest(entries)
            or binding['runtime'] != runtime or binding['limits'] != limits):
        raise ValueError('job/code/runtime/counter/limits binding mismatch')
    if (set(cfg) != {'jobs_url', 'model', 'readiness_seconds', 'job_wait_seconds',
                     'job_poll_seconds', 'timeout'}
            or any(cfg[k] != manifest['identity'][k] for k in ('jobs_url', 'model'))):
        raise ValueError('runtime identity mismatch')
    for key, cap in [('readiness_seconds', 600), ('job_wait_seconds', 600),
                     ('job_poll_seconds', 60), ('timeout', 60)]:
        value = cfg[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= cap:
            raise ValueError('invalid persisted transport bound')
    by_id = {row['job_id']: row for row in entries}
    if len(by_id) != len(entries) or len({row['name'] for row in entries}) != len(entries):
        raise ValueError('duplicate workload jobs')
    intents, receipts, evidence = {}, {}, {}
    for kind in ('intents', 'receipts'):
        folder = root / 'live' / kind
        for path in sorted(folder.rglob('*')):
            if path.is_dir():
                if kind != 'receipts' or path.parent != folder or path.name not in by_id:
                    raise ValueError('unknown record directory')
                continue
            jid = path.stem if kind == 'intents' else path.parent.name
            if (path.suffix != '.json' or jid not in by_id or path.is_symlink()
                    or path.relative_to(folder).parts != ((jid + '.json',) if kind == 'intents'
                                                         else (jid, path.name))):
                raise ValueError('unknown record path/job ID')
            row = e._load(path)
            e._verify_record(row)
            if row.get('binding_sha256') != binding_sha or row.get('job_id') != jid:
                raise ValueError('persisted record binding mismatch')
            evidence[str(path.relative_to(root))] = row['record_sha256']
            if kind == 'intents':
                if row.get('reserved_tokens') != by_id[jid]['input_reservation'] + e.MAX_OUTPUT:
                    raise ValueError('intent reservation mismatch')
                intents[jid] = row
            else:
                if not path.stem.isdecimal():
                    raise ValueError('invalid receipt sequence')
                if row.get('usage') != e._usage(row.get('raw_response')):
                    raise ValueError('receipt usage mismatch')
                if jid not in receipts or int(path.stem) > receipts[jid][0]:
                    receipts[jid] = (int(path.stem), row)
    latest = {jid: pair[1] for jid, pair in receipts.items()}
    observed = set(intents) | {jid for jid, r in latest.items() if r.get('observed_remote', True)}
    known = [r['usage'] for r in latest.values() if r.get('usage') is not None]
    unknown = sum(latest.get(jid, {}).get('usage') is None for jid in observed)
    usage = {k: sum(u[k] for u in known) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
    reserved = sum(by_id[jid]['input_reservation'] + e.MAX_OUTPUT for jid in observed)
    violation = (len(intents) > e.MAX_POSTS or reserved > e.MAX_TOTAL
                 or usage['total_tokens'] > e.MAX_TOTAL
                 or any(u['input_tokens'] > e.MAX_INPUT or u['output_tokens'] > e.MAX_OUTPUT for u in known))
    results = [cli.evaluate_row(row, latest.get(row['job_id'], {})) for row in entries]
    incomplete = unknown or any(latest.get(jid, {}).get('status') != 'completed' for jid in by_id)
    failed = violation or any(r['status'] != 'structural_control_pass' for r in results)
    report = {'status': 'incomplete' if incomplete else 'control_failed' if failed else 'semantic_review_pending',
              'rows': results, 'protocol_valid_count': sum(r['protocol_valid'] for r in results),
              'structural_control_pass_count': sum(r['status'] == 'structural_control_pass' for r in results),
              'semantic_quality': 'semantic_review_pending', 'semantic_pass': False,
              'corpus_dispatch_allowed': False, 'K1_allowed': False,
              'POST_attempts': len(intents), 'actual_usage': usage,
              'reserved_tokens': reserved, 'known_usage_count': len(known),
              'planned_reserved_tokens': sum(r['input_reservation'] + e.MAX_OUTPUT for r in entries),
              'unknown_usage_count': unknown, 'budget_violation': violation,
              'binding_sha256': binding_sha, 'manifest_sha256': manifest['sha256'],
              'generation_code_sha256': c.code_hash(),
              'reporter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'evidence_record_sha256': evidence, 'offline': True}
    report['sha256'] = digest(report)
    destination.mkdir(exist_ok=True)
    target = destination / 'report.json'
    if target.is_symlink():
        raise ValueError('redirected derived report')
    if target.exists():
        previous = e._load(target)
        if (not isinstance(previous, dict) or previous.get('sha256') != digest(
                {k: v for k, v in previous.items() if k != 'sha256'})):
            raise ValueError('existing derived report digest mismatch')
        if previous['sha256'] == report['sha256']:
            return previous
        history = destination / 'history'
        if history.is_symlink() or history.resolve() != history:
            raise ValueError('redirected report history')
        history.mkdir(exist_ok=True)
        archive = history / (previous['sha256'] + '.json')
        if archive.is_symlink():
            raise ValueError('redirected history report')
        if archive.exists():
            if digest(e._load(archive)) != digest(previous):
                raise ValueError('existing history report mismatch')
        else:
            with archive.open('xb') as handle:
                handle.write(target.read_bytes())
    c.v1._atomic(target, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=c.DEFAULT_ROOT,
                        help='existing input run root (no transport execution)')
    args = parser.parse_args(argv)
    try:
        report = build_report(args.output_root)
        print(json.dumps({k: report[k] for k in ('status', 'protocol_valid_count',
              'structural_control_pass_count', 'POST_attempts', 'actual_usage', 'unknown_usage_count')}
              | {'path': str(args.output_root.resolve() / 'recovered_report/report.json')}))
        return {'semantic_review_pending': 0, 'control_failed': 3, 'incomplete': 4}[report['status']]
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__, 'reason': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
