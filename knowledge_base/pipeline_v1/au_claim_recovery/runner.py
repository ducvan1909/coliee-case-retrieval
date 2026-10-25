"""Sequential bounded repair on the existing durable jobs transport."""
from __future__ import annotations

import copy
import os
import time
from pathlib import Path
from urllib import request as urlrequest

from .core import (VERSION, load, require, fingerprint, preflight, validate_repair,
                   parse_body, _put, original)
from ..au_claim.runner import _worker, TERMINAL, mock_response as stage_mock
from ..au_target_context.runner import Accounting, MockJobs, _receipt
from ..au_target_context.readiness import ReadinessGate, ReadinessDeadlineError
from ..au_compact.runner import _atomic
from ..au_presentation_paired.core import profile


def _normalize(body, job, cfg):
    value = parse_body(body, job, cfg)
    result = validate_repair(value, job) if 'original_output' in job else original.validate_response(value, job)
    return value, result


class RecoveryAccounting(Accounting):
    """The reused worker validates AU structure; commit adds the repair gate."""
    def commit(self, job, receipt, status):
        if status == 'verified':
            try:
                value, normalized = _normalize(receipt['raw_response'], job, {'model': job['payload']['model']})
                require(value == receipt['model_output'] and normalized == receipt['normalized'],
                        'worker output mismatch')
            except (ValueError, TypeError, KeyError, IndexError):
                receipt = copy.deepcopy(receipt)
                receipt.update(normalized=None, status='invalid', error='repair_contract_validation')
                status = 'invalid'
        super().commit(job, receipt, status)


def mock_response(job):
    if 'original_output' not in job:
        return stage_mock(job)
    value = copy.deepcopy(job['original_output'])
    for field in job['offending_fields']:
        _put(value, field['path'], 'Synthetic shortened text; semantic quality not assessed.')
    return value


def _stage2(w, job, receipt):
    normalized = receipt.get('normalized')
    row = next(r for r in w['rows'] if r['target_id'] == job['target_id'])
    if (job['stage'] == 1 and receipt['status'] == 'verified' and normalized and
            normalized['context_request'] is not None and row['context_refs']):
        return original.build_job(row, w['identity'], stage=2, draft=normalized)
    return None


def _validate_cache(root, ledger, w, cfg):
    allowed = {j['request_id']: j for j in w['jobs']}
    for job in w['jobs']:
        entry = ledger['jobs'].get(job['request_id'])
        if entry and entry.get('receipt_sha256') and entry['status'] == 'verified':
            receipt = _receipt(root, entry)
            raw, normalized = _normalize(receipt['raw_response'], job, cfg)
            require(raw == receipt['model_output'] and normalized == receipt['normalized'], 'cached repair changed')
            second = _stage2(w, job, receipt)
            if second:
                allowed[second['request_id']] = second
    require(set(ledger['jobs']) <= set(allowed), 'foreign recovery jobs')
    for rid, entry in ledger['jobs'].items():
        require(entry['job'] == allowed[rid] and entry['status'] in (*TERMINAL, 'reserved', 'pending'),
                'cached job changed')
        if entry.get('receipt_sha256'):
            receipt = _receipt(root, entry)
            require(receipt['status'] == entry['status'], 'cached status mismatch')
            if 'raw_response' in receipt:
                try:
                    raw, normalized = _normalize(receipt['raw_response'], allowed[rid], cfg)
                except (ValueError, TypeError, KeyError, IndexError):
                    require(entry['status'] == 'invalid' and receipt.get('normalized') is None,
                            'cached invalid output mismatch')
                else:
                    require(entry['status'] == 'verified' and raw == receipt['model_output'] and
                            normalized == receipt['normalized'], 'cached output changed')
            else:
                require(entry['status'] not in ('verified', 'invalid'), 'terminal receipt missing raw output')
        else:
            require(entry['status'] == 'reserved', 'missing receipt')
    known = {e['job']['payload_sha256'] for e in ledger['jobs'].values()}
    for ordinal, attempt in enumerate(ledger['attempts'], 1):
        require(attempt['ordinal'] == ordinal and attempt['job_id'] in known and
                attempt['payload_sha256'] == attempt['job_id'], 'foreign attempt')
        path = root / 'attempt_receipts' / f'{ordinal:03d}.json'
        if path.exists():
            require(load(path) == attempt, 'attempt receipt changed')
        require(sum(a['job_id'] == attempt['job_id'] for a in ledger['attempts']) <= 2, 'retry overflow')
    return allowed


def _cost(root, ledger, execute):
    receipts = [_receipt(root, e) for e in ledger['jobs'].values() if e.get('receipt_sha256')]
    usages = {e['job']['payload_sha256']: None for e in ledger['jobs'].values()}
    usages.update({r['payload_sha256']: r.get('usage') for r in receipts})
    # Count each observed attempt once. A final receipt explains only its last attempt.
    observed, unknown = [], 0
    for i, attempt in enumerate(ledger['attempts']):
        later = any(a['job_id'] == attempt['job_id'] for a in ledger['attempts'][i+1:])
        usage = attempt.get('usage') or (None if later else usages.get(attempt['job_id']))
        if usage is not None:
            observed.append(usage)
        elif not attempt.get('provably_not_accepted'):
            unknown += 1
    attempted = {a['job_id'] for a in ledger['attempts']}
    retrieved = [r for r in receipts if r['payload_sha256'] not in attempted and 'raw_response' in r]
    retrieved_usage = [r['usage'] for r in retrieved if r.get('usage') is not None]
    observed.extend(retrieved_usage)
    unknown_jobs = sum(v is None for v in usages.values())
    subtotal = {k: sum(u.get(k, 0) for u in observed) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
    return {'known_usage_observed_subtotal': subtotal, 'unknown_usage_jobs': unknown_jobs,
            'retrieved_jobs_without_local_POST': len(retrieved),
            'retrieved_usage_observed_subtotal': {k: sum(u.get(k, 0) for u in retrieved_usage) for k in subtotal},
            'retrieved_usage_note': 'Observed durable-job usage; no local POST or new billing inferred.',
            'unknown_provider_attempts': unknown, 'usage_is_complete': execute and unknown == unknown_jobs == 0,
            'logical_requests': len(ledger['jobs']), 'transport_POST_attempts': len(ledger['attempts']),
            'provider_POST_attempts': len(ledger['attempts']) if execute else 0, 'GET_polls': ledger['get_polls'],
            'reserved_input_utf8_bytes': ledger['reserved_input_tokens'],
            'reserved_output_tokens': ledger['reserved_output_tokens'],
            'client_latency_ms': sum(r.get('latency_ms', 0) for r in receipts),
            'POST_ack_latency_ms': sum(a.get('latency_ms', 0) for a in ledger['attempts'])}


def run(output_root, cfg=None, execute=False, mock=False, opener=urlrequest.urlopen,
        clock=time.perf_counter, sleep=time.sleep, response_factory=None):
    require(not execute, 'Length-only model repair is disabled; use au_claim_soft offline validation')
    require(not (execute and mock), 'execute and mock are mutually exclusive')
    output = Path(output_root).resolve()
    w = preflight(output / 'workload.json', cfg)
    cfg = copy.deepcopy(cfg if cfg is not None else original.runtime_config(w['identity']))
    runtime = profile(w, cfg)
    if not execute and not mock:
        return {'artifact_type': 'AUClaimRecoveryRun', 'version': VERSION, 'status': 'not_executed',
                'repair_requests': len(w['jobs']), 'network_requests': 0, 'semantic_quality': 'not_assessed'}
    if execute:
        require(bool(cfg.get('token')), 'execution requires token')
    if mock:
        cfg.update(token='local-mock', job_poll_seconds=.001, job_wait_seconds=10)
        runtime = profile(w, cfg)
    root = output / ('mock' if mock else 'live')
    original.guard_output(root, [w['parent_root'], w['source_store'], w['atom_root'], Path(__file__).parent])
    root.mkdir(parents=True, exist_ok=True)
    path, lock = root / 'runtime_ledger.json', root / '.runner.lock'
    require(path.exists() or not any(root.iterdir()), 'execution root must be fresh or resumable')
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    started = clock()
    try:
        bound = {'workload_sha256': w['workload_sha256'], 'code_sha256': w['code_sha256'],
                 'mode': 'mock' if mock else 'execute', 'run_profile': runtime, 'budget': w['budget']}
        ledger = load(path) if path.exists() else {'identity': fingerprint(bound), 'binding': bound,
            'jobs': {}, 'attempts': [], 'provider_attempts': 0, 'get_polls': 0,
            'reserved_input_tokens': 0, 'reserved_output_tokens': 0}
        require(ledger['identity'] == fingerprint(bound) and ledger['binding'] == bound, 'stale recovery binding')
        if path.exists():
            require(ledger['ledger_sha256'] == fingerprint({k: v for k, v in ledger.items() if k != 'ledger_sha256'}),
                    'ledger digest mismatch')
        require(ledger['provider_attempts'] == len(ledger['attempts']) <= w['budget']['max_provider_attempts'],
                'attempt count mismatch')
        require(len(ledger['jobs']) <= w['budget']['max_requests'], 'logical request overflow')
        for key, cap in (('reserved_input_tokens', 'max_total_input_tokens'), ('reserved_output_tokens', 'max_total_output_tokens')):
            require(ledger[key] == sum(a[key] for a in ledger['attempts']) <= w['budget'][cap], 'reservation mismatch')
        allowed = _validate_cache(root, ledger, w, cfg)
        fake = MockJobs(list(allowed.values()), delay=.001, response_factory=response_factory or mock_response) if mock else None
        accounting = RecoveryAccounting(root, ledger, w['budget'], fake if fake is not None else opener)
        accounting.save()
        accounting.readiness = ReadinessGate(cfg, accounting.dispatch, clock, sleep,
            lambda diagnostic: _atomic(root / 'readiness.json', diagnostic))
        unfinished = any(ledger['jobs'].get(rid, {}).get('status') not in TERMINAL for rid in allowed)
        try:
            accounting.readiness.warmup(unfinished)
        except ReadinessDeadlineError:
            pass
        results = []
        def dispatch(job):
            _worker(job, accounting, cfg, clock, sleep)
            return _receipt(root, accounting.snapshot()['jobs'][job['request_id']])
        for job in w['jobs']:
            first = dispatch(job)
            second_job = _stage2(w, job, first)
            second = None
            if second_job:
                if fake:
                    fake.add([second_job])
                second = dispatch(second_job)
            final = second or first
            normalized = final.get('normalized')
            needs = bool((normalized or {}).get('context_request')) or bool(second and not normalized)
            status = ('unresolved' if needs else 'complete') if final['status'] == 'verified' else final['status']
            results.append({'target_id': job['target_id'], 'original_request_id': job['original_request_id'],
                            'repair_status': first['status'], 'stage2_status': second['status'] if second else 'not_needed',
                            'status': status, 'output': normalized, 'needs_context': needs,
                            'semantic_quality': 'not_assessed'})
        snap = accounting.snapshot()
        costs = _cost(root, snap, execute)
        history = w['inherited_accounting']
        subtotal = {k: history['known_usage_observed_subtotal'][k] + costs['known_usage_observed_subtotal'][k]
                    for k in costs['known_usage_observed_subtotal']}
        complete = all(r['status'] in ('complete', 'unresolved') for r in results) and not w['excluded_invalid_request_ids']
        repairs = {r['target_id']: r for r in results}
        merged = []
        for inherited in w['inherited_targets']:
            item = copy.deepcopy(inherited)
            repair = repairs.get(item['target_id'])
            item['origin'] = 'recovery' if repair else 'inherited'
            if repair:
                item.update(status=repair['status'], output=repair['output'],
                            recovery=copy.deepcopy(repair))
                item['recovery']['request_ids'] = [e['job']['request_id'] for e in snap['jobs'].values()
                    if e['job']['target_id'] == item['target_id']]
            merged.append(item)
        report = {'artifact_type': 'AUClaimRecoveryRun', 'version': VERSION, 'status': 'complete' if complete else 'incomplete',
            'workload_sha256': w['workload_sha256'], 'identity': snap['identity'], 'mode': bound['mode'],
            'protocol_complete': complete, 'results': results, 'merged_results': merged,
            'repair_requests': len(w['jobs']),
            'stage2_requests': sum(r['stage2_status'] != 'not_needed' for r in results),
            'inherited_targets': w['inherited_targets'], 'inherited_accounting': history, 'new_accounting': costs,
            'aggregate_known_usage_observed_subtotal': subtotal,
            'total_provider_usage': subtotal if history['usage_is_complete'] and costs['usage_is_complete'] else None,
            'network_requests': costs['transport_POST_attempts'] + costs['GET_polls'] if execute else 0,
            'network_executed': bool(execute), 'readiness': accounting.readiness.snapshot(),
            'elapsed_wall_ms': round((clock()-started)*1000, 3), 'semantic_quality': 'not_assessed'}
        _atomic(root / 'run.json', report)
        return report
    finally:
        lock.unlink()
