"""Sequential case turns over durable jobs, with replay-derived checkpoints."""
from __future__ import annotations

import copy
import io
import json
import os
import re
import time
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError

from . import core
from .tools import initial_state, apply_turn
from ..au_target_context.runner import (Accounting, JobAccounting, MockJobs,
                                         BudgetError, _receipt)
from ..au_target_context.readiness import ReadinessGate, ReadinessDeadlineError
from ..au_context_paired.transport import PairedTransport, Response
from ..au_compact.jobs_client import complete_job, payload_digest, JobTransportError
from ..au_compact.runner import _atomic
from ..au_presentation_paired.core import profile

TERMINAL = ('verified', 'invalid', 'failed')
MAX_ATTEMPTS, MAX_INPUT, MAX_OUTPUT, MAX_TOTAL = 12, 6000, 800, 30000
TEMPLATE_MARGIN = 128


def _input(payload):
    return core.input_reservation(payload)


def _usage(body):
    value = body.get('usage') if isinstance(body, dict) else None
    keys = ('prompt_tokens', 'completion_tokens', 'total_tokens')
    if not isinstance(value, dict) or not all(type(value.get(k)) is int and value[k] >= 0 for k in keys):
        return None
    if value['total_tokens'] < value['prompt_tokens'] + value['completion_tokens']:
        return None
    return dict(zip(('input_tokens', 'output_tokens', 'total_tokens'), (value[k] for k in keys)))


def _normalize_body(body, job, cfg):
    core.require(isinstance(body, dict) and body.get('model') == cfg['model'], 'response model mismatch')
    choices = body.get('choices')
    core.require(isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict), 'one choice required')
    choice = choices[0]
    core.require(choice.get('finish_reason') == 'stop', 'incomplete generation')
    def pairs(items):
        core.require(len({k for k, _ in items}) == len(items), 'duplicate JSON keys')
        return dict(items)
    def constant(_):
        raise ValueError('nonfinite JSON constant')
    content = choice['message']['content']
    core.require(isinstance(content, str), 'JSON content string required')
    value = json.loads(content, object_pairs_hook=pairs, parse_constant=constant)
    core.require(isinstance(value, dict), 'JSON object root required')
    return value, core.validate_response(value, job)


def _usage_summary(root, ledger):
    """A final receipt explains only the last attempt, never an earlier retry."""
    receipts = {e['job']['payload_sha256']: _receipt(root, e)
                for e in ledger['jobs'].values() if e.get('receipt_sha256')}
    known, unknown = [], 0
    for i, attempt in enumerate(ledger['attempts']):
        later = any(a['job_id'] == attempt['job_id'] for a in ledger['attempts'][i+1:])
        usage = attempt.get('usage')
        if not later:
            usage = receipts.get(attempt['job_id'], {}).get('usage') or usage
        if usage is not None:
            known.append(usage)
        elif not attempt.get('provably_not_accepted'):
            unknown += 1
    # Existing remote jobs retrieved without a local POST also count.
    attempted = {a['job_id'] for a in ledger['attempts']}
    for jid, receipt in receipts.items():
        trace = receipt.get('transport_trace') or {}
        observed_remote = ('raw_response' in receipt or jid in ledger.get('observed_jobs', {}) or
                           trace.get('job_status') in ('queued', 'running', 'completed', 'failed', 'interrupted'))
        if jid not in attempted and observed_remote:
            if receipt.get('usage') is None:
                unknown += 1
            else:
                known.append(receipt['usage'])
    subtotal = {k: sum(u[k] for u in known) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
    return subtotal, unknown


def _provider_request_cap_exceeded(root, ledger):
    """Measured violations must stop admission even if aggregate usage is low."""
    usages = [a.get('usage') for a in ledger['attempts']]
    usages += [_receipt(root, e).get('usage') for e in ledger['jobs'].values() if e.get('receipt_sha256')]
    return any(u is not None and (u['input_tokens'] > MAX_INPUT or u['output_tokens'] > MAX_OUTPUT) for u in usages)


class K0Accounting(Accounting):
    """Reuse durable ledger/receipts; enforce K0 full-payload admission at POST."""
    def dispatch(self, req, proof=None, **kwargs):
        if req.get_method() == 'GET':
            return super().dispatch(req, proof, **kwargs)
        core.require(req.get_method() == 'POST', 'unsupported method')
        wire = json.loads(req.data)
        payload, jid = wire['payload'], wire['job_id']
        core.require(jid == payload_digest(payload), 'job digest mismatch')
        with self.lock:
            self.readiness.check()
            entries = [e for e in self.ledger['jobs'].values() if e['job']['payload_sha256'] == jid]
            core.require(len(entries) == 1 and entries[0]['job']['payload'] == payload, 'unreserved payload')
            observations = (proof or {}).get('observations', [])
            core.require(proof and proof.get('job_id') == jid and proof.get('gateway_url') == req.full_url.rstrip('/')
                and len(observations) == 2 and all(o.get('http_status') == 404 and o.get('detail') == 'Unknown job'
                    and o.get('health', {}).get('ready') is True and o.get('job_url') == req.full_url.rstrip('/') + '/' + jid
                    for o in observations)
                and observations[1]['observed_monotonic'] - observations[0]['observed_monotonic'] >= proof['backoff_seconds'],
                'fresh authoritative absence evidence required')
            prior = [a for a in self.ledger['attempts'] if a['job_id'] == jid]
            recovery = self.ledger.setdefault('job_recovery', {}).get(jid, {})
            if prior:
                core.require(len(prior) < 2 and not recovery.get('retry_used')
                    and jid not in self.ledger.get('observed_jobs', {})
                    and not any(a.get('acknowledgement') == 'received' for a in prior), 'unsafe duplicate POST')
            inp, out = _input(payload), payload['max_tokens']
            core.require(entries[0]['job']['input_reservation'] == inp and inp <= MAX_INPUT
                         and type(out) is int and 0 < out <= MAX_OUTPUT, 'request reservation mismatch')
            subtotal, unknown = _usage_summary(self.root, self.ledger)
            if not self.mock and _provider_request_cap_exceeded(self.root, self.ledger):
                raise BudgetError('provider per-request cap exceeded')
            if unknown and not self.mock:
                raise BudgetError('unknown usage stops new admission')
            if self.max_new_requests is not None and len(self.ledger['attempts']) - self.invocation_start >= self.max_new_requests:
                raise BudgetError('invocation POST limit exhausted')
            if (len(self.ledger['attempts']) >= MAX_ATTEMPTS
                or self.ledger['reserved_input_tokens'] + self.ledger['reserved_output_tokens'] + inp + out > MAX_TOTAL
                or (not self.mock and subtotal['total_tokens'] + inp + out > MAX_TOTAL)):
                raise BudgetError('K0 aggregate budget exhausted')
            recovery.update(last_absence_proof=proof, retry_used=bool(prior))
            self.ledger['job_recovery'][jid] = recovery
            attempt = {'ordinal': len(self.ledger['attempts']) + 1, 'job_id': jid, 'payload_sha256': jid,
                'reserved_input_tokens': inp, 'reserved_output_tokens': out, 'usage': None,
                'usage_state': 'unknown', 'acknowledgement': 'unknown', 'started_at_unix': time.time(),
                'phase': 'authoring', 'input_estimate_method': core.counter_identity()['method']}
            self.ledger['attempts'].append(attempt)
            self.ledger['provider_attempts'] = len(self.ledger['attempts'])
            self.ledger['reserved_input_tokens'] += inp
            self.ledger['reserved_output_tokens'] += out
            self.save()  # Admission and unknown outcome durable before POST.
        started, outcome = time.perf_counter(), {}
        try:
            with self.opener(req, **kwargs) as response:
                raw = response.read()
            body = json.loads(raw)
            outcome['acknowledgement'] = 'received'
            usage = _usage(body.get('response', body)) if isinstance(body, dict) else None
            outcome.update(usage=usage, usage_state='observed' if usage is not None else 'unknown')
            if isinstance(body, dict) and body.get('job_id'):
                self.ledger.setdefault('observed_jobs', {})[jid] = body.get('status')
            return Response(raw)
        except HTTPError as exc:
            outcome['http_status'] = exc.code
            raw = exc.read()
            try:
                diagnostic = json.loads(raw)
            except (ValueError, UnicodeError):
                diagnostic = None
            outcome['provably_not_accepted'] = bool(exc.code == 503 and isinstance(diagnostic, dict)
                and diagnostic.get('accepted') is False and diagnostic.get('error') == 'provider_unavailable')
            raise HTTPError(exc.url, exc.code, exc.reason, exc.headers, io.BytesIO(raw)) from exc
        finally:
            with self.lock:
                attempt.update(outcome, latency_ms=round((time.perf_counter() - started) * 1000, 3))
                path = self.root / 'attempt_receipts' / f"{attempt['ordinal']:03d}.json"
                core.require(not path.exists(), 'immutable attempt receipt exists')
                _atomic(path, attempt)
                self.save()


def _worker(job, accounting, cfg, clock, sleep):
    old = accounting.reserve(job)
    if old['status'] in TERMINAL:
        return _receipt(accounting.root, old)
    started = clock()
    receipt = {'normalized': None, 'usage': None, 'usage_state': 'unknown'}
    status = 'pending'
    try:
        accounting.readiness.check()
        transport = PairedTransport(cfg, JobAccounting(accounting), clock=clock, sleep=sleep,
                                    readiness_seconds=accounting.readiness.worker_limit)
        body, trace = complete_job(cfg, job['payload'], transport, clock=clock, sleep=sleep)
        receipt.update(raw_response=body, transport_trace=trace, usage=_usage(body),
                       usage_state='mock_unavailable' if accounting.mock else 'provider' if _usage(body) is not None else 'unknown')
        try:
            value, normalized = _normalize_body(body, job, cfg)
            receipt.update(model_output=value, normalized=normalized)
            status = 'invalid' if normalized.get('au_errors') else 'verified'
            if status == 'invalid':
                receipt['error'] = 'local_candidate_errors'
        except (ValueError, TypeError, KeyError, IndexError):
            status = 'invalid'
            receipt['error'] = 'output_protocol_validation'
            choices = body.get('choices')
            if isinstance(choices, list) and choices and isinstance(choices[0], dict) and choices[0].get('finish_reason') == 'length':
                receipt['error_code'] = 'incomplete_generation'
    except JobTransportError as exc:
        trace = copy.deepcopy(exc.trace)
        trace.get('failure_diagnostic', {}).pop('server_error', None)
        receipt.update(transport_trace=trace, error='job_transport')
        status = 'failed' if trace.get('failure_diagnostic', {}).get('retryable') is False else 'pending'
    except ReadinessDeadlineError:
        receipt['error'] = 'readiness_deadline'
    except BudgetError as exc:
        receipt['error'] = ('unknown_usage' if str(exc) == 'unknown usage stops new admission'
                            else 'budget_exhausted' if str(exc) == 'K0 aggregate budget exhausted'
                            else 'invocation_limit' if str(exc) == 'invocation POST limit exhausted'
                            else 'admission_paused')
    except Exception as exc:
        receipt['error'] = type(exc).__name__
    receipt.update(status=status, latency_ms=round((clock() - started) * 1000, 3))
    accounting.commit(job, receipt, status)
    return receipt


def _validate_job(job):
    core.require(isinstance(job, dict) and isinstance(job.get('request_id'), str)
        and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job['request_id']) is not None, 'unsafe request ID')
    core.require(job['payload_sha256'] == payload_digest(job['payload'])
        and job['input_reservation'] == _input(job['payload']) <= MAX_INPUT
        and job['payload']['max_tokens'] == MAX_OUTPUT, 'job payload binding/cap mismatch')


def _reconcile(root, ledger, cfg):
    """Recover receipt-before-ledger crashes, without trusting persisted states."""
    for rid, entry in ledger['jobs'].items():
        job = entry['job']
        _validate_job(job)
        core.require(rid == job['request_id'] and entry['status'] in (*TERMINAL, 'reserved', 'pending'), 'invalid job entry')
        path = root / 'receipts' / (rid + '.json')
        if path.exists() and (not entry.get('receipt_sha256') or entry['status'] == 'pending'):
            receipt = core.load(path)
            core.require(receipt.get('receipt_sha256') == core.fingerprint({k: v for k, v in receipt.items() if k != 'receipt_sha256'})
                and receipt['request_id'] == rid and receipt['payload_sha256'] == job['payload_sha256'], 'orphan receipt mismatch')
            entry.update(status=receipt['status'], receipt_sha256=receipt['receipt_sha256'])
        if entry.get('receipt_sha256'):
            receipt = _receipt(root, entry)
            core.require(receipt['status'] == entry['status'], 'receipt status mismatch')
            if 'raw_response' in receipt:
                core.require(receipt.get('usage') == _usage(receipt['raw_response']), 'cached usage changed')
                try:
                    raw, normalized = _normalize_body(receipt['raw_response'], job, cfg)
                except (ValueError, KeyError, TypeError, IndexError):
                    core.require(entry['status'] == 'invalid' and receipt.get('normalized') is None, 'invalid cached envelope')
                else:
                    expected = 'invalid' if normalized.get('au_errors') else 'verified'
                    core.require(entry['status'] == expected and raw == receipt.get('model_output')
                                 and normalized == receipt.get('normalized'), 'cached response changed')
            else:
                core.require(entry['status'] not in ('verified', 'invalid'), 'missing cached response')
        else:
            core.require(entry['status'] == 'reserved', 'missing cached receipt')
    known = {e['job']['payload_sha256']: e['job'] for e in ledger['jobs'].values()}
    for ordinal, attempt in enumerate(ledger['attempts'], 1):
        core.require(attempt['ordinal'] == ordinal and attempt['job_id'] == attempt['payload_sha256']
                     and attempt['job_id'] in known, 'foreign attempt')
        job = known[attempt['job_id']]
        core.require(attempt['reserved_input_tokens'] == _input(job['payload'])
                     and attempt['reserved_output_tokens'] == job['payload']['max_tokens'], 'attempt reservation changed')
        path = root / 'attempt_receipts' / f'{ordinal:03d}.json'
        if path.exists():
            saved = core.load(path)
            if saved != attempt:
                # Only a crash after the immutable receipt write can advance an unknown attempt.
                core.require(attempt.get('acknowledgement') == 'unknown' and 'latency_ms' not in attempt
                             and all(saved.get(k) == v for k, v in attempt.items()
                                     if k not in ('usage', 'usage_state', 'acknowledgement')), 'attempt checkpoint changed')
                ledger['attempts'][ordinal - 1] = saved
        core.require(sum(a['job_id'] == attempt['job_id'] for a in ledger['attempts']) <= 2, 'retry overflow')
    core.require(ledger['provider_attempts'] == len(ledger['attempts']) <= MAX_ATTEMPTS, 'attempt count mismatch')
    for key in ('reserved_input_tokens', 'reserved_output_tokens'):
        core.require(ledger[key] == sum(a[key] for a in ledger['attempts']), 'reservation mismatch')
    core.require(ledger['reserved_input_tokens'] + ledger['reserved_output_tokens'] <= MAX_TOTAL, 'aggregate reservation exceeded')
    core.require(len(ledger['jobs']) <= MAX_ATTEMPTS, 'logical request cap exceeded')
    receipt_ids = {p.stem for p in (root / 'receipts').glob('*.json')}
    core.require(receipt_ids <= set(ledger['jobs']), 'foreign receipt')
    core.require({p.name for p in (root / 'attempt_receipts').glob('*.json')} <=
                 {f'{i:03d}.json' for i in range(1, len(ledger['attempts']) + 1)}, 'foreign attempt receipt')


def _advance(case, state, job, receipt):
    normalized = receipt.get('normalized')
    if normalized is None:
        if 'raw_response' not in receipt:
            return state
        # Response/truncation is still evidence of source delivery. Assessment
        # remains false; replay always derives this once from the initial state.
        delivered = copy.deepcopy(state)
        delivered['active_scope_ids'] = list(job['active_scope_ids'])
        for sid in job['active_scope_ids']:
            entry = delivered['read_ledger'][sid]
            entry['delivered_count'] += 1
            if not entry['assessed']:
                entry['state'] = 'delivered'
        return delivered
    core.require(normalized['delivered_scope_ids'] == job['active_scope_ids'], 'receipt delivery changed')
    return apply_turn(case, state, normalized)


def _replay(w, ledger, cfg):
    states, pauses, visited = {}, {}, set()
    for case in w['cases']:
        cid = case['case_id']
        state = initial_state(case)
        for _ in range(MAX_ATTEMPTS + 1):
            if state.get('finished'):
                break
            try:
                job = core.build_job(w, case, state, cfg)
            except (ValueError, TypeError, KeyError) as exc:
                pauses[cid] = 'job_build_' + type(exc).__name__
                break
            _validate_job(job)
            entry = ledger['jobs'].get(job['request_id'])
            if entry is None:
                break
            core.require(entry['job'] == job and job['request_id'] not in visited, 'cached job/state binding changed')
            visited.add(job['request_id'])
            if not entry.get('receipt_sha256'):
                break
            receipt = _receipt(Path(ledger['_root']), entry)
            state = _advance(case, state, job, receipt)
            if receipt['status'] != 'verified':
                if receipt['status'] in TERMINAL:
                    pauses[cid] = receipt['status']
                break
        states[cid] = state
    core.require(visited == set(ledger['jobs']), 'foreign or unreachable cached jobs')
    return states, pauses


def run(workload, output_root, cfg=None, execute=False, mock=False,
        opener=urlrequest.urlopen, clock=time.perf_counter, sleep=time.sleep, max_new_requests=None):
    """Dry by default. ROOT contains input/, mock/ and live/ separately."""
    core.require(not (execute and mock), 'execute and mock are mutually exclusive')
    core.require(max_new_requests is None or type(max_new_requests) is int and 1 <= max_new_requests <= MAX_ATTEMPTS,
                 'max_new_requests must be 1..12')
    w = core.load(workload)
    checked = core.preflight(w, cfg=cfg)
    if not execute and not mock:
        return {**checked, 'status': 'not_executed', 'mode': 'dryrun', 'network_requests': 0,
                'network_executed': False, 'provider_POST_attempts': 0, 'semantic_quality': 'not_assessed'}
    if cfg is None:
        from argparse import Namespace
        from ..au_context_paired.__main__ import study_config
        cfg, _, _ = study_config(Namespace())
    cfg = copy.deepcopy(cfg)
    runtime = profile(w, cfg)
    if execute:
        core.require(bool(cfg.get('token')), 'execution requires token')
    if mock:
        cfg.update(token='local-mock', job_poll_seconds=.001, job_wait_seconds=10)
    base = Path(output_root).resolve()
    protected = [Path(__file__).parent, w['source_store']]
    if w.get('atom_root'):
        protected.append(w['atom_root'])
    if isinstance(workload, (str, Path)):
        core.require(Path(workload).resolve() == base / 'input' / 'workload.json', 'workload must be ROOT/input/workload.json')
    # A run must never overwrite a source or historical parent directory.
    from ..au_target_context.core import guard_output
    protected.extend(Path(b['path']).parent for b in w.get('parent_bindings', []))
    root = base / ('mock' if mock else 'live')
    guard_output(root, protected)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    started, accounting = clock(), None
    states, pauses = {}, {}
    try:
        path = root / 'runtime_ledger.json'
        core.require(path.exists() or not any(p != lock for p in root.iterdir()), 'execution root must be fresh or resumable')
        bound = {'workload_sha256': w['workload_sha256'], 'code_sha256': core.code_hash(),
                 'mode': 'mock' if mock else 'execute', 'runtime': runtime,
                 'input_counter': core.counter_identity(),
                 'limits': [MAX_ATTEMPTS, MAX_INPUT, MAX_OUTPUT, MAX_TOTAL, TEMPLATE_MARGIN]}
        ledger = core.load(path) if path.exists() else {'identity': core.fingerprint(bound), 'binding': bound,
            'jobs': {}, 'attempts': [], 'provider_attempts': 0, 'get_polls': 0,
            'reserved_input_tokens': 0, 'reserved_output_tokens': 0}
        core.require(ledger['binding'] == bound and ledger['identity'] == core.fingerprint(bound), 'stale run binding')
        if path.exists():
            core.require(ledger.get('ledger_sha256') == core.fingerprint({k: v for k, v in ledger.items() if k != 'ledger_sha256'}), 'ledger digest changed')
        _reconcile(root, ledger, cfg)
        # Temporary root is passed only to replay, never included in persisted identity.
        states, pauses = _replay(w, {**ledger, '_root': str(root)}, cfg)
        fake = MockJobs([], delay=.001, response_factory=core.mock_response) if mock else None
        accounting = K0Accounting(root, ledger, {'max_requests': MAX_ATTEMPTS}, fake if mock else opener)
        accounting.mock = mock
        accounting.max_new_requests = max_new_requests
        accounting.invocation_start = len(ledger['attempts'])
        accounting.save()
        accounting.readiness = ReadinessGate(cfg, accounting.dispatch, clock, sleep,
            lambda value: _atomic(root / 'readiness.json', value))
        needed = any(not states[c['case_id']].get('finished') and c['case_id'] not in pauses for c in w['cases'])
        accounting.readiness.warmup(needed)
        for case in w['cases']:
            cid = case['case_id']
            if cid in pauses:
                continue
            try:
                while not states[cid].get('finished'):
                    job = core.build_job(w, case, states[cid], cfg)
                    _validate_job(job)
                    if (max_new_requests is not None and len(ledger['attempts']) - accounting.invocation_start >= max_new_requests
                        and job['payload_sha256'] not in {a['job_id'] for a in ledger['attempts']}):
                        pauses[cid] = 'invocation_limit'
                        break
                    if job['request_id'] not in ledger['jobs'] and len(ledger['jobs']) >= MAX_ATTEMPTS:
                        pauses[cid] = 'request_budget'
                        break
                    if fake:
                        fake.add([job])
                    receipt = _worker(job, accounting, cfg, clock, sleep)
                    states[cid] = _advance(case, states[cid], job, receipt)
                    _atomic(root / 'state.json', {'states': states, 'binding': bound,
                        'derived_from': {rid: e.get('receipt_sha256') for rid, e in ledger['jobs'].items()}})
                    if receipt['status'] != 'verified':
                        pauses[cid] = receipt.get('error', receipt['status'])
                        break
            except Exception as exc:
                pauses[cid] = type(exc).__name__
        return _report(root, w, accounting, states, pauses, mock, started, clock)
    except Exception as exc:
        if accounting is not None:
            pauses['run'] = type(exc).__name__
            return _report(root, w, accounting, states, pauses, mock, started, clock)
        # Keep existing valid reports/ledgers intact if binding/cache validation fails.
        _atomic(root / 'error.json', {'status': 'blocked', 'error_type': type(exc).__name__,
                                     'network_requests': 0, 'semantic_quality': 'not_assessed'})
        raise
    finally:
        lock.unlink()


def _report(root, w, accounting, states, pauses, mock, started, clock):
    snap = accounting.snapshot()
    subtotal, unknown = _usage_summary(root, snap)
    if subtotal['total_tokens'] > MAX_TOTAL:
        pauses['run'] = 'provider_usage_cap_exceeded'
    if not mock and unknown:
        pauses['run'] = 'unknown_provider_usage'
    if not mock and _provider_request_cap_exceeded(root, snap):
        pauses['run'] = 'provider_per_request_cap_exceeded'
    results = []
    for case in w['cases']:
        cid = case['case_id']
        state = states.get(cid, initial_state(case))
        ledger_rows = list(state.get('read_ledger', {}).values())
        accounted = bool(ledger_rows) and all(r.get('assessed') is True or
            (r.get('state') == 'unresolved' and state.get('stop_reason') == 'needs_context') for r in ledger_rows)
        complete = bool(state.get('finished')) and accounted and cid not in pauses
        results.append({'case_id': cid, 'state': state, 'work_scope_complete': complete,
                        'case_source_assessment_complete': False, 'case_source_status': 'partial',
                        'pause_reason': pauses.get(cid), 'semantic_quality': 'not_assessed'})
    complete = all(r['work_scope_complete'] for r in results) and 'run' not in pauses
    receipts = [_receipt(root, e) for e in snap['jobs'].values() if e.get('receipt_sha256')]
    counts = {s: sum(e['status'] == s for e in snap['jobs'].values()) for s in (*TERMINAL, 'reserved', 'pending')}
    report = {'artifact_type': 'K0AuthoringRun', 'status': 'complete' if complete else 'incomplete',
        'workload_sha256': w['workload_sha256'], 'identity': snap['identity'], 'mode': 'mock' if mock else 'execute',
        'work_scope_complete': complete, 'protocol_complete': complete, 'case_source_assessment_complete': False,
        'case_source_status': 'partial', 'semantic_quality': 'not_assessed', 'results': results,
        'pauses': pauses, 'protocol_counts': counts, 'logical_requests': len(snap['jobs']),
        'transport_POST_attempts': snap['provider_attempts'], 'provider_POST_attempts': 0 if mock else snap['provider_attempts'],
        'GET_polls': snap['get_polls'], 'network_executed': not mock,
        'network_requests': 0 if mock else snap['get_polls'] + snap['provider_attempts'],
        'reserved_input_tokens': snap['reserved_input_tokens'], 'reserved_output_tokens': snap['reserved_output_tokens'],
        'input_count_method': core.counter_identity()['method'], 'input_counter': core.counter_identity(),
        'reserved_input_utf8_bytes': snap['reserved_input_tokens'] if 'UTF8_bytes' in core.counter_identity()['method'] else None,
        'known_provider_usage_observed_subtotal': None if mock else subtotal,
        'unknown_provider_attempts': 0 if mock else unknown,
        'total_provider_usage': subtotal if not mock and unknown == 0 else None,
        'usage_is_complete': not mock and unknown == 0,
        'grammar_compile': 'not_checked', 'max_new_requests_this_invocation': accounting.max_new_requests,
        'client_latency_ms': sum(r.get('latency_ms', 0) for r in receipts),
        'POST_ack_latency_ms': sum(a.get('latency_ms', 0) for a in snap['attempts']),
        'elapsed_wall_ms': round((clock() - started) * 1000, 3),
        'readiness': accounting.readiness.snapshot() if hasattr(accounting, 'readiness') else {'status': 'not_started'}}
    _atomic(root / 'state.json', {'states': states, 'binding': snap['binding'],
        'derived_from': {rid: e.get('receipt_sha256') for rid, e in snap['jobs'].items()}})
    _atomic(root / 'run.json', report)
    return report
