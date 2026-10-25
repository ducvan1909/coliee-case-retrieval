"""Claim jobs on the existing durable transport; no environment or deployment."""
from __future__ import annotations

import copy
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import request as urlrequest

from .contracts import VERSION, BUDGET
from .core import (load, require, guard_output, fingerprint, code_hash, preflight,
                   build_job, validate_response, runtime_config)
from ..au_target_context.runner import Accounting, JobAccounting, MockJobs, _receipt
from ..au_target_context.readiness import ReadinessGate, ReadinessDeadlineError
from ..au_context_paired.transport import PairedTransport
from ..au_compact.jobs_client import complete_job, JobTransportError
from ..au_compact.runner import _atomic, _usage
from ..au_presentation_paired.core import profile

TERMINAL = ('verified', 'invalid', 'failed')


def _normalize_body(body, job, cfg):
    require(isinstance(body, dict) and body.get('model') == cfg['model'], 'response model mismatch')
    choice = body['choices'][0]
    require(choice.get('finish_reason') == 'stop', 'incomplete generation')
    def pairs(items):
        require(len({k for k, _ in items}) == len(items), 'duplicate JSON keys')
        return dict(items)
    value = json.loads(choice['message']['content'], object_pairs_hook=pairs)
    return value, validate_response(value, job)


def mock_response(job):
    mode = int(fingerprint(job['target_id'])[:2], 16) % 4
    return {'aus': [] if mode == 0 else [{'claim': 'Synthetic mock legal point; semantic quality not assessed.',
            'kind': None, 'evidence_ids': ['s1'], 'limits': None}],
            'context_request': {'question': 'Does the surrounding source qualify this legal point?'}
            if (job['stage'] == 1 and mode in (1, 2)) or (job['stage'] == 2 and mode == 2) else None}


def _worker(job, accounting, cfg, clock, sleep):
    prior = accounting.reserve(job)
    if prior['status'] in TERMINAL:
        return _receipt(accounting.root, prior)
    started = clock()
    receipt = {'stage': job['stage'], 'normalized': None, 'usage': None, 'usage_state': 'unknown'}
    status = 'pending'
    try:
        accounting.readiness.check()
        transport = PairedTransport(cfg, JobAccounting(accounting), clock=clock, sleep=sleep,
                                    readiness_seconds=accounting.readiness.worker_limit)
        body, trace = complete_job(cfg, job['payload'], transport, clock=clock, sleep=sleep)
        receipt.update(raw_response=body, transport_trace=trace, usage=_usage(body),
                       usage_state='provider' if _usage(body) else 'unknown')
        try:
            value, normalized = _normalize_body(body, job, cfg)
            receipt.update(model_output=value, normalized=normalized)
            status = 'verified'
        except (ValueError, TypeError, KeyError, IndexError):
            status = 'invalid'
            receipt['error'] = 'output_protocol_validation'
            if body.get('choices', [{}])[0].get('finish_reason') == 'length':
                receipt['error_code'] = 'incomplete_generation'
    except JobTransportError as exc:
        trace = copy.deepcopy(exc.trace)
        trace.get('failure_diagnostic', {}).pop('server_error', None)
        receipt.update(transport_trace=trace, error='job_transport')
        status = 'failed' if trace.get('failure_diagnostic', {}).get('retryable') is False else 'pending'
    except ReadinessDeadlineError:
        receipt['error'] = 'readiness_deadline'
    except Exception as exc:
        receipt['error'] = type(exc).__name__  # Never persist exception text/auth.
    receipt.update(status=status, latency_ms=round((clock() - started) * 1000, 3))
    accounting.commit(job, receipt, status)
    return receipt


def _validate_cache(root, ledger, first_jobs, rows, identity, cfg):
    """All cache validation precedes readiness/GET/POST, including raw envelopes."""
    allowed = {j['request_id']: j for j in first_jobs}
    for row, job in zip(rows, first_jobs):
        entry = ledger['jobs'].get(job['request_id'])
        if entry and entry['status'] == 'verified':
            receipt = _receipt(root, entry)
            raw, normalized = _normalize_body(receipt['raw_response'], job, cfg)
            require(raw == receipt['model_output'] and normalized == receipt['normalized'], 'cached raw stage1 changed')
            if normalized['context_request'] is not None and row['context_refs']:
                extra = build_job(row, identity, stage=2, draft=normalized)
                allowed[extra['request_id']] = extra
    require(set(ledger['jobs']) <= set(allowed), 'foreign cached jobs')
    for rid, entry in ledger['jobs'].items():
        require(entry['job'] == allowed[rid] and entry['status'] in (*TERMINAL, 'reserved', 'pending'), 'cached job changed')
        if entry.get('receipt_sha256'):
            receipt = _receipt(root, entry)
            require(receipt['status'] == entry['status'], 'receipt status mismatch')
            if 'raw_response' in receipt:
                try:
                    raw, normalized = _normalize_body(receipt['raw_response'], allowed[rid], cfg)
                except (ValueError, TypeError, KeyError, IndexError):
                    require(entry['status'] == 'invalid', 'cached raw response invalid')
                else:
                    require(entry['status'] == 'verified' and raw == receipt['model_output']
                            and normalized == receipt['normalized'], 'cached raw response changed')
            else:
                require(entry['status'] not in ('verified', 'invalid'), 'terminal output cache missing raw response')
    known = {j['job']['payload_sha256'] for j in ledger['jobs'].values()}
    for ordinal, attempt in enumerate(ledger['attempts'], 1):
        require(attempt['ordinal'] == ordinal and attempt['job_id'] in known
                and attempt['payload_sha256'] == attempt['job_id'], 'foreign attempt')
        attempt_path = root / 'attempt_receipts' / f'{ordinal:03d}.json'
        if attempt_path.exists(): require(load(attempt_path) == attempt, 'attempt checkpoint changed')
        require(sum(a['job_id'] == attempt['job_id'] for a in ledger['attempts']) <= 2, 'retry overflow')
    return allowed


def run(workload, output_root, cfg=None, execute=False, mock=False, concurrency=2,
        opener=urlrequest.urlopen, target_ids=None, clock=time.perf_counter, sleep=time.sleep):
    """Dry by default; mock always replaces the opener and makes zero network calls."""
    require(type(concurrency) is int and 1 <= concurrency <= 4, 'concurrency must be C1..4')
    require(not (execute and mock), 'execute and mock are mutually exclusive')
    started = clock()
    w = load(workload)
    checked = preflight(w, cfg)
    requested = {r['target_id'] for r in w['rows']} if target_ids is None else set(target_ids)
    require(bool(requested) and requested <= {r['target_id'] for r in w['rows']}, 'unknown/empty TARGET selection')
    rows = [r for r in w['rows'] if r['target_id'] in requested]
    if not execute and not mock:
        return {**checked, 'artifact_type': 'AUClaimRun', 'status': 'not_executed', 'mode': 'dryrun',
                'selected_target_ids': [r['target_id'] for r in rows], 'selected_target_count': len(rows),
                'results': [], 'protocol_counts': {}, 'usage': None, 'provider_POST_attempts': 0,
                'network_requests': 0, 'network_executed': False}
    cfg = copy.deepcopy(cfg if cfg is not None else runtime_config(w['identity']))
    runtime = profile(w, cfg)
    if execute: require(bool(cfg.get('token')), 'execution requires token')
    if mock: cfg.update(token='local-mock', job_poll_seconds=.001, job_wait_seconds=10)
    root = Path(output_root).resolve()
    protected = [w['source_store'], w['atom_root'], Path(w['reference_checklist_path']).parent,
                 Path(__file__).parent, *[Path(b['path']).parent for b in w['parent_bindings']]]
    if isinstance(workload, (str, Path)): protected.append(Path(workload).resolve().parent)
    guard_output(root, protected)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'runtime_ledger.json'
    require(path.exists() or not any(root.iterdir()), 'execution root must be fresh or resumable')
    lock = root / '.runner.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        bound = {'workload_sha256': w['workload_sha256'], 'code_sha256': code_hash(),
                 'selected_target_ids': [r['target_id'] for r in rows], 'mode': 'mock' if mock else 'execute',
                 'run_profile': runtime, 'budget': w['budget'], 'concurrency': concurrency}
        ledger = load(path) if path.exists() else {'identity': fingerprint(bound), 'binding': bound,
            'jobs': {}, 'attempts': [], 'provider_attempts': 0, 'get_polls': 0,
            'reserved_input_tokens': 0, 'reserved_output_tokens': 0}
        require(ledger['identity'] == fingerprint(bound) and ledger['binding'] == bound, 'stale run binding')
        if path.exists():
            require(ledger.get('ledger_sha256') == fingerprint({k: v for k, v in ledger.items() if k != 'ledger_sha256'}), 'ledger digest changed')
        require(ledger['provider_attempts'] == len(ledger['attempts']) <= BUDGET['max_provider_attempts'], 'attempt count mismatch')
        for field, cap in (('reserved_input_tokens', 'max_total_input_tokens'), ('reserved_output_tokens', 'max_total_output_tokens')):
            require(ledger[field] == sum(a[field] for a in ledger['attempts']) <= BUDGET[cap], 'reservation mismatch')
        require(len(ledger['jobs']) <= BUDGET['max_requests'], 'logical budget exceeded')
        first_jobs = [build_job(r, w['identity']) for r in rows]
        allowed = _validate_cache(root, ledger, first_jobs, rows, w['identity'], cfg)
        fake = MockJobs(first_jobs, delay=.001, response_factory=mock_response) if mock else None
        accounting = Accounting(root, ledger, w['budget'], fake if fake is not None else opener)
        accounting.save()
        accounting.readiness = ReadinessGate(cfg, accounting.dispatch, clock, sleep,
            lambda diagnostic: _atomic(root / 'readiness.json', diagnostic))
        unfinished = any(ledger['jobs'].get(rid, {}).get('status') not in TERMINAL for rid in allowed)
        try: accounting.readiness.warmup(unfinished)
        except ReadinessDeadlineError: pass  # Workers checkpoint pending locally.
        def batch(jobs):
            result = {}
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(_worker, j, accounting, cfg, clock, sleep): j for j in jobs}
                for future in as_completed(futures):
                    job = futures[future]
                    try: result[job['target_id']] = future.result()
                    except Exception as exc:
                        result[job['target_id']] = {'status': 'pending', 'normalized': None, 'error': type(exc).__name__}
            return result
        first = batch(first_jobs)
        second_jobs = [build_job(r, w['identity'], stage=2, draft=first[r['target_id']]['normalized'])
                       for r in rows if r['context_refs'] and
                       (first[r['target_id']].get('normalized') or {}).get('context_request') is not None]
        require(len(second_jobs) <= len(rows), 'stage2 request bound exceeded')
        if fake: fake.add(second_jobs)
        second = batch(second_jobs)
        results = []
        for row in rows:
            one, two = first[row['target_id']], second.get(row['target_id'])
            initial, final = one.get('normalized'), (two or one).get('normalized')
            needs = bool((final or initial or {}).get('context_request')) or bool(two and final is None)
            status = ('unresolved' if needs else 'complete') if (two or one)['status'] == 'verified' else (two or one)['status']
            receipts = [r for r in (one, two) if r]
            results.append({'target_id': row['target_id'], 'case_id': row['case_id'], 'source_hash': row['source_hash'],
                'target': row['target'], 'stage1_status': one['status'], 'stage2_status': two['status'] if two else 'not_needed',
                'draft_status': 'needs_context' if initial and initial['needs_context'] else one['status'],
                'status': status, 'initial_output': initial, 'output': final, 'needs_context': needs,
                'protocol_complete': all(r['status'] == 'verified' for r in receipts),
                'failed': any(r['status'] == 'failed' for r in receipts), 'logical_requests': len(receipts),
                'usage': [r.get('usage') for r in receipts], 'client_latency_ms': sum(r.get('latency_ms', 0) for r in receipts),
                'semantic_quality': 'not_assessed'})
        snap = accounting.snapshot()
        counts = {s: sum(e['status'] == s for e in snap['jobs'].values()) for s in (*TERMINAL, 'reserved', 'pending')}
        receipts = [_receipt(root, e) for e in snap['jobs'].values() if e.get('receipt_sha256')]
        usage_by_job = {e['job']['payload_sha256']: None for e in snap['jobs'].values()}
        usage_by_job.update({r['payload_sha256']: r.get('usage') for r in receipts})
        known = [u for u in usage_by_job.values() if u is not None]
        subtotal = {k: sum(u.get(k, 0) for u in known) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
        unknown = sum(u is None for u in usage_by_job.values())
        unknown_attempts = sum(a.get('usage') is None and not a.get('provably_not_accepted') and
            (any(b['job_id'] == a['job_id'] for b in snap['attempts'][i+1:]) or usage_by_job.get(a['job_id']) is None)
            for i, a in enumerate(snap['attempts']))
        complete = len(snap['jobs']) == len(first_jobs) + len(second_jobs) and all(r['protocol_complete'] for r in results)
        for result in results:
            jobs = [e['job'] for e in snap['jobs'].values() if e['job']['target_id'] == result['target_id']]
            attempts = [a for a in snap['attempts'] if a['job_id'] in {j['payload_sha256'] for j in jobs}]
            result.update(request_ids=[j['request_id'] for j in jobs],
                          transport_POST_attempts=len(attempts), provider_POST_attempts=len(attempts) if execute else 0)
        report = {'artifact_type': 'AUClaimRun', 'version': VERSION, 'workload_sha256': w['workload_sha256'],
            'identity': snap['identity'], 'mode': bound['mode'], 'status': 'complete' if complete else 'incomplete',
            'protocol_complete': complete, 'protocol_counts': counts, 'protocol_verified': counts['verified'],
            'protocol_invalid': counts['invalid'], 'failed': counts['failed'], 'pending': counts['reserved'] + counts['pending'],
            'needs_context': sum(r['needs_context'] for r in results), 'results': results,
            'selected_target_count': len(rows), 'frozen_target_count': len(w['rows']), 'concurrency': concurrency,
            'logical_requests': len(snap['jobs']), 'stage1_requests': len(first_jobs), 'stage2_requests': len(second_jobs),
            'provider_POST_attempts': snap['provider_attempts'] if execute else 0,
            'transport_POST_attempts': snap['provider_attempts'], 'GET_polls': snap['get_polls'],
            'network_executed': bool(execute), 'network_requests': 0 if mock else snap['provider_attempts'] + snap['get_polls'],
            'usage': {'known_provider_usage_observed_subtotal': subtotal, 'unknown_usage_jobs': unknown,
                      'unknown_provider_attempts': unknown_attempts, 'usage_is_complete': not mock and unknown == unknown_attempts == 0},
            'known_provider_usage_observed_subtotal': subtotal, 'unknown_usage_jobs': unknown,
            'unknown_provider_attempts': unknown_attempts,
            'total_provider_usage': subtotal if not mock and unknown == unknown_attempts == 0 else None,
            'reserved_input_utf8_bytes': snap['reserved_input_tokens'], 'reserved_output_tokens': snap['reserved_output_tokens'],
            'client_latency_ms': sum(r.get('latency_ms', 0) for r in receipts),
            'POST_ack_latency_ms': sum(a.get('latency_ms', 0) for a in snap['attempts']),
            'elapsed_wall_ms': round((clock() - started) * 1000, 3), 'readiness': accounting.readiness.snapshot(),
            'semantic_quality': 'not_assessed', 'mock_max_inflight': fake.max_inflight if fake else None, 'budget': dict(BUDGET)}
        _atomic(root / 'run.json', report)
        return report
    finally:
        lock.unlink()
