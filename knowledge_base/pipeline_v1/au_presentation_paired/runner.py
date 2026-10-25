"""Frozen payload execution with persistent source-only accounting and recovery."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from pathlib import Path
from urllib import request as urlrequest

from ..au_compact import runner as compact
from ..au_compact.core import build_evidence_catalog, deduplicate_lists
from ..au_compact.jobs_client import complete_job, JobTransportError, payload_digest
from ..au_compact.manifest import _binding_path
from ..au_context_paired.build import read_json, fingerprint
from ..au_context_paired.runner import _Accounting, PairedRunError, _immutable
from ..au_context_paired.transport import PairedTransport
from ..source_contract import open_source
from .core import BUDGET, STRATEGY, DEFAULT_PARENT, PresentationError, require, preflight


def receipt_key(payload, identity, cfg):
    return fingerprint({'payload_sha256': payload_digest(payload), 'identity': identity,
                        'model': cfg['model'], 'url': cfg['url'], 'jobs_url': cfg['jobs_url']})


def _clean_trace(trace):
    value = copy.deepcopy(trace)
    if isinstance(value.get('failure_diagnostic'), dict):
        value['failure_diagnostic'].pop('server_error', None)
    return value


def _check_row(row, key, v, identity):
    require(row.get('cache_key') == key and row.get('identity') == identity
            and row.get('request') == v['request'] and row.get('payload_sha256') == v['payload_sha256']
            and row.get('row_sha256') == fingerprint({k: x for k, x in row.items() if k != 'row_sha256'}),
            'corrupt/stale immutable receipt')


def run(manifest, *, output_root, cfg, parent=None, execute=False,
        opener=urlrequest.urlopen, clock=time.monotonic, sleep=time.sleep):
    """No remote action unless execute=True; resume only the identical frozen run."""
    manifest_path = Path(manifest) if isinstance(manifest, (str, Path)) else None
    m = read_json(manifest_path) if manifest_path else copy.deepcopy(manifest)
    parent_path = Path(parent or DEFAULT_PARENT) if not isinstance(parent, dict) else None
    p = read_json(parent_path) if parent_path else copy.deepcopy(parent)
    checked = preflight(m, parent=p, cfg=cfg)
    if not execute:
        return {**checked, 'status': 'not_executed'}
    require(bool(cfg.get('token')), 'execution requires local token')
    root = Path(output_root).resolve()
    if manifest_path:
        require(not manifest_path.resolve().is_relative_to(root), 'output root contains frozen manifest')
    if parent_path:
        require(not parent_path.resolve().is_relative_to(root), 'output root contains parent artifact')
    for source_root in (m['source_store'], m['atom_root']):
        require(not root.is_relative_to(Path(source_root).resolve()), 'output root overlaps source artifacts')
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.runner.lock'
    require(not lock.exists(), 'writer lock exists; confirm stopped process before removal')
    require((root / 'runtime_ledger.json').exists() or not any(root.iterdir()), 'new output root must be fresh')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise PresentationError('writer lock exists; confirm stopped process before removal') from None
    os.close(fd)
    try:
        return _execute(m, p, checked, root, cfg, opener, clock, sleep,
                        hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path else None,
                        hashlib.sha256(parent_path.read_bytes()).hexdigest() if parent_path else None)
    finally:
        lock.unlink()


def _execute(m, parent, checked, root, cfg, opener, clock, sleep, raw_manifest_sha, raw_parent_sha):
    bound = {'manifest_sha256': m['manifest_sha256'], 'parent_workload_sha256': parent['workload_sha256'],
             'run_profile': checked['run_profile'], 'code_sha256': checked['code_sha256'], 'budget': BUDGET,
             'manifest_file_sha256': raw_manifest_sha, 'parent_file_sha256': raw_parent_sha}
    identity = fingerprint(bound)
    path = root / 'runtime_ledger.json'
    ledger = read_json(path) if path.exists() else {
        'identity': identity, 'workload_sha256': m['manifest_sha256'], 'manifest_sha256': m['manifest_sha256'],
        'run_binding': bound, 'provider_attempts': 0, 'get_polls': 0, 'warmup_attempts': 0,
        'probe_attempts': 0, 'requests': 0, 'reserved_input_tokens': 0, 'reserved_output_tokens': 0,
        'attempts': [], 'reservations': {}, 'terminal': {}, 'readiness_strategy': STRATEGY}
    require(ledger.get('identity') == identity and ledger.get('run_binding') == bound, 'stale runtime identity')
    require(ledger['warmup_attempts'] == ledger['probe_attempts'] == 0, 'source-only run has warmup/probe POST')
    variants = [(row, next(v for v in row['variants'] if v['arm'] == arm))
                for row in m['rows'] for arm in row['variant_order']]
    by_id = {v['request']['request_id']: v for _, v in variants}
    require(set(ledger['reservations']) <= set(by_id) and set(ledger['terminal']) <= set(by_id), 'foreign ledger requests')
    require(ledger['requests'] == len(ledger['reservations']) <= 64, 'reservation counter mismatch')
    require(ledger['provider_attempts'] == len(ledger['attempts']) <= 100, 'POST counter mismatch')
    require(ledger['reserved_input_tokens'] == sum(a['reserved_input_tokens'] for a in ledger['attempts']) <= 800000,
            'input accounting mismatch')
    require(ledger['reserved_output_tokens'] == sum(a['reserved_output_tokens'] for a in ledger['attempts']) <= 80000,
            'output accounting mismatch')
    for a in ledger['attempts']:
        require(a['payload_sha256'] in {v['payload_sha256'] for _, v in variants} and a['phase'] == 'extraction',
                'foreign POST in ledger')
        receipt = root / 'attempt_receipts' / f"{a['ordinal']:03d}.json"
        if receipt.exists():
            prior = read_json(receipt)
            require(all(prior.get(k) == a.get(k) for k in ('ordinal', 'phase', 'payload_sha256', 'job_id')),
                    'attempt receipt identity mismatch')
            a.update(prior)
    counted = _Accounting(root, ledger, dict(BUDGET), opener)
    counted.save()

    def report(reason=None):
        rows = [read_json(root / 'receipts' / (ledger['terminal'][rid] + '.json'))
                for rid in by_id if rid in ledger['terminal']]
        jobs = {r['payload_sha256']: r['receipt'].get('usage') for r in rows}
        usage, seen = [], set()
        for a in ledger['attempts']:
            job = a['job_id']
            if a.get('provably_not_accepted'):
                usage.append(a.get('usage'))
            elif job in jobs:
                if job not in seen: usage.append(jobs[job]); seen.add(job)
            else:
                usage.append(a.get('usage'))
        usage.extend(u for job, u in jobs.items() if job not in seen)
        unknown = sum(u is None for u in usage)
        known = sum(u['total_tokens'] for u in usage if u is not None)
        pending = [rid for rid in by_id if rid not in ledger['terminal']]
        result = {'artifact_type': 'AUPresentationPairedRun', 'schema_version': 'au-presentation-paired-v1',
                  **bound, 'identity': identity, 'workload_sha256': m['manifest_sha256'],
                  'status': 'complete' if not pending and not reason else 'incomplete',
                  'stop_reason': reason, 'pending_request_ids': pending, 'request_ledger': rows,
                  'runtime_ledger': ledger, 'execution_ledger': ledger,
                  'protocol_verified_count': sum(r['status'] == 'protocol_verified' for r in rows),
                  'terminal_unresolved_count': sum(r['status'] == 'unresolved' for r in rows),
                  'target_count': 32, 'unique_requests': 64, 'readiness_strategy': STRATEGY,
                  'semantic_gold': False, 'semantic_quality_claim': False,
                  'usage_state': 'unknown' if unknown else 'provider', 'known_total_tokens': known,
                  'actual_total_tokens': None if unknown else known, 'unknown_usage_count': unknown,
                  'provider_usage': usage, 'usage_attribution': 'observed provider usage; new billing unverified',
                  'current_run_provider_POST_attempts': ledger['provider_attempts'],
                  'server_recovered_jobs_without_POST': sum(not any(a['job_id'] == job for a in ledger['attempts']) for job in jobs),
                  'local_preparation_seconds': m['preparation_seconds'], 'review_usage': 'unavailable'}
        compact._atomic(root / 'run.json', result)
        return result

    # Recover receipt -> ledger crash window before any network operation.
    for _, v in variants:
        rid = v['request']['request_id']; key = receipt_key(v['payload'], identity, cfg)
        rp = root / 'receipts' / (key + '.json')
        if rp.exists():
            _check_row(read_json(rp), key, v, identity)
            require(rid in ledger['reservations'], 'receipt without pre-dispatch reservation')
            ledger['terminal'][rid] = key
        elif rid in ledger['terminal']:
            raise PresentationError('terminal receipt missing')
        if rid in ledger['reservations']:
            require(ledger['reservations'][rid] == {'cache_key': key, 'payload_sha256': v['payload_sha256'],
                    'prompt_bytes': v['input_reservation_utf8_bytes'], 'output_tokens': 800}, 'reservation identity mismatch')
    counted.save(); report()
    if len(ledger['terminal']) == 64:
        return report()
    transport = PairedTransport(cfg, counted, clock=clock, sleep=sleep, readiness_seconds=600)
    try:
        ledger['readiness'] = transport.ensure_ready(timeout=cfg.get('timeout', 60))
        counted.save()
        for pair, v in variants:
            q, payload = v['request'], v['payload']
            rid = q['request_id']; key = receipt_key(payload, identity, cfg)
            if rid in ledger['terminal']: continue
            if rid not in ledger['reservations']:
                require(ledger['requests'] < 64, 'unique request cap exhausted')
                ledger['requests'] += 1
                ledger['reservations'][rid] = {'cache_key': key, 'payload_sha256': v['payload_sha256'],
                                               'prompt_bytes': v['input_reservation_utf8_bytes'], 'output_tokens': 800}
                counted.save(); report()  # Durable unique reservation BEFORE complete_job/POST.
            body = value = None
            receipt = {'usage': None, 'usage_state': 'unknown'}
            source = open_source(m['source_store'], q['case_id'], q['source_hash'])
            binding = _binding_path(q['atom_binding'], m['atom_root'])
            catalog = build_evidence_catalog(q, binding, source)
            started = clock()
            try:
                body, trace = complete_job(cfg, payload, transport, clock=clock, sleep=sleep)
            except JobTransportError as exc:
                trace = _clean_trace(exc.trace)
                receipt.update(transport_trace=trace, failure_diagnostic=trace.get('failure_diagnostic'),
                               latency_ms=round((clock()-started)*1000, 3))
                _immutable(root / 'pending_receipts' / (key + f"-{ledger['get_polls']}.json"), receipt)
                counted.save()
                return report('job pending; explicit review or resume same payload required')
            # Completed generation failures are terminal; transport uncertainty above is pending.
            usage = compact._usage(body)
            receipt.update(usage=usage, usage_state='provider' if usage else 'unknown', raw_response=body,
                           transport_trace=_clean_trace(trace), latency_ms=round((clock()-started)*1000, 3),
                           estimated_input_tokens=v['input_reservation_utf8_bytes'],
                           input_estimate_method='full_prompt_utf8_bytes')
            try:
                choice = body['choices'][0]
                receipt['finish_reason'] = choice.get('finish_reason')
                require(choice.get('finish_reason') == 'stop', 'incomplete generation')
                receipt['raw_content'] = choice['message']['content']
                value = json.loads(choice['message']['content'])
                cleaned, cleanup = deduplicate_lists(value)
                receipt['exact_duplicate_cleanup'] = cleanup
                normalized = compact._normalize(cleaned, q, binding, source)
                status = 'protocol_verified'
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                receipt['failure_diagnostic'] = {'kind': 'output_validation', 'error': type(exc).__name__}
                normalized = compact._terminal_full(q, 'unresolved', 'other')
                status = 'unresolved'
            receipt['provider_POST_attempts_for_job'] = sum(a['job_id'] == v['payload_sha256'] for a in ledger['attempts'])
            receipt['server_recovered_without_POST'] = receipt['provider_POST_attempts_for_job'] == 0
            row = {'cache_key': key, 'identity': identity, 'pair_id': pair['pair_id'], 'arm': v['arm'],
                   'request': q, 'payload_sha256': v['payload_sha256'], 'status': status,
                   'compact_response': value, 'response': normalized, 'receipt': receipt,
                   'source_catalog': {'atoms': catalog['atoms'], 'metrics': catalog['metrics']},
                   'catalog_sha256': v['catalog_sha256']}
            row['row_sha256'] = fingerprint(row)
            _immutable(root / 'receipts' / (key + '.json'), row)
            ledger['terminal'][rid] = key
            counted.save(); report()
        return report()
    except (PairedRunError, TimeoutError, OSError) as exc:
        counted.save()
        return report(counted.block_reason or type(exc).__name__)
