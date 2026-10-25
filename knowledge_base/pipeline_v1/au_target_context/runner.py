"""C1..4 independent jobs, atomic checkpoints and private recovery permits."""
from __future__ import annotations

import copy
import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .contracts import *
from .core import (load, require, preflight, fingerprint, code_hash, guard_output,
                   build_stage1, build_stage2, validate_stage1, validate_stage2,
                   DEFAULT_MANIFEST, DEFAULT_PARENT)
from ..au_compact.jobs_client import complete_job, payload_digest, JobTransportError
from ..au_compact.runner import _atomic, _usage
from ..au_context_paired.transport import PairedTransport, Response
from ..au_presentation_paired.core import profile
from .readiness import ReadinessGate, ReadinessDeadlineError


class BudgetError(RuntimeError):
    pass


class HostPolicyError(RuntimeError):
    """Host gates must not become a provider JSON error or terminal failure."""


class Accounting:
    """Lock reserve/commit/save, never hold the aggregate lock across HTTP."""
    def __init__(self, root, ledger, budget, opener):
        self.root, self.ledger, self.budget, self.opener = root, ledger, budget, opener
        self.lock = threading.RLock()

    def save(self):
        with self.lock:
            self.ledger['ledger_sha256'] = fingerprint({k: v for k, v in self.ledger.items() if k != 'ledger_sha256'})
            _atomic(self.root / 'runtime_ledger.json', self.ledger)

    def reserve(self, job):
        rid = job['request_id']
        with self.lock:
            old = self.ledger['jobs'].get(rid)
            if old is not None:
                require(old['job'] == job, 'resume job changed')
                return copy.deepcopy(old)
            require(len(self.ledger['jobs']) < self.budget['max_requests'], 'logical request budget exhausted')
            self.ledger['jobs'][rid] = {'job': copy.deepcopy(job), 'status': 'reserved'}
            self.save()
            return copy.deepcopy(self.ledger['jobs'][rid])

    def commit(self, job, receipt, status):
        with self.lock:
            receipt = copy.deepcopy(receipt)
            receipt.update(request_id=job['request_id'], payload_sha256=job['payload_sha256'])
            receipt['receipt_sha256'] = fingerprint(receipt)
            path = self.root / 'receipts' / (job['request_id'] + '.json')
            # Pending checkpoints may be superseded; terminal receipts are immutable.
            old = self.ledger['jobs'][job['request_id']]
            require(old['status'] not in ('verified', 'invalid', 'failed'), 'terminal receipt overwrite prohibited')
            _atomic(path, receipt)
            old.update(status=status, receipt_sha256=receipt['receipt_sha256'])
            self.save()

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.ledger)

    def dispatch(self, req, proof=None, **kwargs):
        method = req.get_method()
        if method == 'GET':
            with self.lock:
                self.ledger['get_polls'] += 1
                self.save()
            try:
                with self.opener(req, **kwargs) as response:
                    raw = response.read()
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeError):
                    body = None
                if isinstance(body, dict) and body.get('job_id'):
                    with self.lock:
                        self.ledger.setdefault('observed_jobs', {})[body['job_id']] = body.get('status')
                        self.save()
                return Response(raw)
            except HTTPError:
                raise
        require(method == 'POST', 'unsupported method')
        wire = json.loads(req.data)
        payload, jid = wire['payload'], wire['job_id']
        require(jid == payload_digest(payload), 'job digest mismatch')
        with self.lock:
            if getattr(self, 'readiness', None):
                self.readiness.check()
            require(any(j['job']['payload_sha256'] == jid for j in self.ledger['jobs'].values()), 'unreserved payload')
            prior = [a for a in self.ledger['attempts'] if a['job_id'] == jid]
            observations = (proof or {}).get('observations', [])
            require(proof and proof.get('job_id') == jid and proof.get('gateway_url') == req.full_url.rstrip('/')
                    and len(observations) == 2 and all(o.get('http_status') == 404 and o.get('detail') == 'Unknown job'
                    and o.get('health', {}).get('ready') is True and o.get('job_url') == req.full_url.rstrip('/') + '/' + jid for o in observations)
                    and observations[1]['observed_monotonic'] - observations[0]['observed_monotonic'] >= proof['backoff_seconds'],
                    'fresh authoritative absence evidence required')
            recovery = self.ledger.setdefault('job_recovery', {}).get(jid, {})
            if prior:
                require(len(prior) < 2 and not recovery.get('retry_used') and jid not in self.ledger.get('observed_jobs', {})
                        and not any(a.get('acknowledgement') == 'received' for a in prior), 'unsafe duplicate POST')
            inp = sum(len(m['content'].encode()) for m in payload['messages'])
            out = payload['max_tokens']
            prior_cost = self.ledger.get('recovery_prior_accounting', {})
            if (prior_cost.get('provider_attempts', 0) + len(self.ledger['attempts']) >= self.budget['max_provider_attempts']
                    or prior_cost.get('reserved_input_tokens', 0) + self.ledger['reserved_input_tokens'] + inp > self.budget['max_total_input_tokens']
                    or prior_cost.get('reserved_output_tokens', 0) + self.ledger['reserved_output_tokens'] + out > self.budget['max_total_output_tokens']):
                raise BudgetError('aggregate POST/reservation budget exhausted')
            recovery.update(last_absence_proof=proof, retry_used=bool(prior))
            self.ledger['job_recovery'][jid] = recovery
            attempt = {'ordinal': len(self.ledger['attempts']) + 1, 'job_id': jid, 'payload_sha256': jid,
                       'reserved_input_tokens': inp, 'reserved_output_tokens': out,
                       'usage': None, 'usage_state': 'unknown', 'acknowledgement': 'unknown',
                       'started_at_unix': time.time(), 'phase': 'extraction',
                       'input_estimate_method': 'full_prompt_utf8_bytes; not exact tokens'}
            self.ledger['attempts'].append(attempt)
            self.ledger['provider_attempts'] = len(self.ledger['attempts'])
            self.ledger['reserved_input_tokens'] += inp
            self.ledger['reserved_output_tokens'] += out
            self.save()  # Durable BEFORE network, including unknown ACK/process death.
        started = time.perf_counter()
        outcome = {}
        try:
            with self.opener(req, **kwargs) as response:
                raw = response.read()
            body = json.loads(raw)
            outcome['acknowledgement'] = 'received'
            usage = _usage(body)
            outcome.update(usage=usage, usage_state='provider' if usage else 'unknown')
            with self.lock:
                if isinstance(body, dict) and body.get('job_id'):
                    self.ledger.setdefault('observed_jobs', {})[jid] = body.get('status')
            return Response(raw)
        except HTTPError as exc:
            outcome['http_status'] = exc.code
            raw = exc.read()
            try: diagnostic = json.loads(raw)
            except (ValueError, UnicodeError): diagnostic = None
            outcome['provably_not_accepted'] = bool(exc.code == 503 and isinstance(diagnostic, dict)
                and diagnostic.get('accepted') is False and diagnostic.get('error') == 'provider_unavailable')
            raise HTTPError(exc.url, exc.code, exc.reason, exc.headers, io.BytesIO(raw)) from exc
        finally:
            with self.lock:
                attempt.update(outcome, latency_ms=round((time.perf_counter()-started)*1000, 3))
                path = self.root / 'attempt_receipts' / f"{attempt['ordinal']:03d}.json"
                require(not path.exists(), 'immutable attempt receipt exists')
                _atomic(path, copy.deepcopy(attempt))
                self.save()


class JobAccounting:
    """Worker-local permit; PairedTransport gets only a locked ledger snapshot."""
    def __init__(self, aggregate):
        self.aggregate = aggregate
        self.recovery_proof = None

    @property
    def ledger(self):
        return self.aggregate.snapshot()

    def block(self, reason):
        if 'readiness' in reason or 'deadline' in reason:
            gate = getattr(self.aggregate, 'readiness', None)
            if gate:
                gate.stop()
            raise ReadinessDeadlineError('host readiness/retrieval deadline exhausted')
        raise BudgetError(reason)

    def __call__(self, req, **kwargs):
        proof, self.recovery_proof = self.recovery_proof, None
        from .core import TargetContextError
        gate = getattr(self.aggregate, 'readiness', None)
        if gate and req.get_method() == 'POST':
            gate.check()
        try:
            response = self.aggregate.dispatch(req, proof, **kwargs)
            if gate and req.full_url == gate.health_url:
                raw = response.read()
                response.close()
                try:
                    body = json.loads(raw)
                    ready = isinstance(body, dict) and body.get('ready') is True
                    gate.record(200, ready, None if ready else 'NotReady')
                except (ValueError, UnicodeError):
                    gate.record(200, False, 'InvalidHealthResponse')
                return Response(raw)
            return response
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if gate and req.full_url == gate.health_url:
                gate.record(exc.code if isinstance(exc, HTTPError) else None, False,
                            'HTTPError' if isinstance(exc, HTTPError) else
                            'TimeoutError' if isinstance(exc, TimeoutError) else 'TransportError')
            raise
        except TargetContextError as exc:
            # complete_job treats ValueError as an invalid provider envelope.
            # Preserve host policy failures as resumable local checkpoints.
            raise HostPolicyError('host dispatch policy rejected request') from exc


class MockJobs:
    """Real jobs-client envelope path with a local, thread-safe fake provider."""
    def __init__(self, jobs, delay=.15, response_factory=None):
        self.jobs = {j['payload_sha256']: j for j in jobs}
        self.finished = {}
        self.lock = threading.Lock()
        self.inflight = self.max_inflight = 0
        self.delay = delay
        self.response_factory = response_factory or mock_response

    def add(self, jobs):
        with self.lock: self.jobs.update({j['payload_sha256']: j for j in jobs})

    def __call__(self, req, **kwargs):
        if req.full_url.endswith('/health'): return Response(b'{"ready":true}')
        if req.get_method() == 'GET':
            jid = req.full_url.rsplit('/', 1)[-1]
            with self.lock: body = self.finished.get(jid)
            if body is None: raise HTTPError(req.full_url, 404, 'Unknown job', {}, io.BytesIO(b'{"detail":"Unknown job"}'))
            return Response(json.dumps(body).encode())
        wire = json.loads(req.data); jid = wire['job_id']
        with self.lock:
            job = self.jobs[jid]
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            time.sleep(self.delay)
            value = self.response_factory(job)
            body = {'model': wire['payload']['model'], 'choices': [{'finish_reason': 'stop',
                    'message': {'content': json.dumps(value)}}]}
            envelope = {'job_id': jid, 'payload_sha256': jid, 'status': 'completed',
                        'response': body, 'response_sha256': payload_digest(body)}
            with self.lock: self.finished[jid] = envelope
            return Response(json.dumps(envelope).encode())
        finally:
            with self.lock: self.inflight -= 1


def mock_response(job):
    base = {'version': stage1_version(job.get('prompt_profile')) if job['stage'] == 1 else STAGE2, 'request_id': job['request_id'], 'target_id': job['target_id']}
    if job['stage'] == 1:
        # Protocol exercise, deliberately no semantic quality assertion.
        mode = int(fingerprint(job['target_id'])[:2], 16) % 4
        anchors = [] if mode in (2, 3) else [{'anchor_id': job['anchor_ids'][0], 'kind': 'unresolved_kind',
            'primary_claim': 'Synthetic mock draft; not a validated legal proposition.',
            'target_ref_ids': list(job['catalog']['target_refs'])[:1], 'needs_context': ['scope'] if mode == 1 else []}]
        if job.get('prompt_profile') == 'evidence_first_v1':
            for anchor in anchors:
                del anchor['primary_claim']
        if job.get('prompt_profile') == 'primary_support_v1':
            for anchor in anchors:
                del anchor['primary_claim']
                anchor['primary_ref_id'] = anchor.pop('target_ref_ids')[0]
                anchor['supporting_ref_ids'] = []
        return {**base, 'decision': ('positive', 'positive', 'needs_context', 'unresolved')[mode], 'anchors': anchors,
                'needs_context': ['scope'] if mode == 2 else [],
                'reason': ('none', 'missing_qualification', 'insufficient_target', 'uncertain_eligibility')[mode]}
    if not job['locked_anchors']:
        # Protocol defense for callers constructing a stage2 job manually.
        return {**base, 'decision': 'revisit_target', 'anchors': [], 'reason': 'revisit_target_required'}
    return {**base, 'decision': 'complete', 'anchors': [{'anchor_id': a['anchor_id'], 'decision': 'keep',
            'supplements': [{'slot': 'scope', 'text': 'Synthetic mock scope.',
                'context_ref_ids': list(job['catalog']['context_refs'])[:1]}] if job['catalog']['context_refs'] else [],
            'reason': 'none'} for a in job['locked_anchors']], 'reason': 'none'}


def _receipt(root, row):
    receipt = load(root / 'receipts' / (row['job']['request_id'] + '.json'))
    require(receipt['receipt_sha256'] == fingerprint({k: v for k, v in receipt.items() if k != 'receipt_sha256'})
            == row['receipt_sha256'] and receipt['request_id'] == row['job']['request_id']
            and receipt['payload_sha256'] == row['job']['payload_sha256'], 'corrupt receipt')
    return receipt


def _worker(job, accounting, cfg, clock, sleep):
    old = accounting.reserve(job)
    if old['status'] in ('verified', 'invalid', 'failed'):
        return _receipt(accounting.root, old)
    transport = PairedTransport(cfg, JobAccounting(accounting), clock=clock, sleep=sleep,
                                readiness_seconds=(accounting.readiness.worker_limit
                                    if getattr(accounting, 'readiness', None) else
                                    min(30, cfg.get('readiness_seconds', 600))))
    started = clock()
    receipt = {'stage': job['stage'], 'usage': None, 'usage_state': 'unknown', 'normalized': None}
    status = 'pending'
    try:
        if getattr(accounting, 'readiness', None):
            accounting.readiness.check()
        body, trace = complete_job(cfg, job['payload'], transport, clock=clock, sleep=sleep)
        receipt.update(raw_response=body, transport_trace=trace, usage=_usage(body),
                       usage_state='provider' if _usage(body) else 'unknown')
        try:
            require(body.get('model') == cfg['model'], 'response model mismatch')
            choice = body['choices'][0]
            require(choice.get('finish_reason') == 'stop', 'incomplete generation')
            content = choice['message']['content']
            # Reject duplicate JSON object keys; never silently overwrite a field.
            def pairs(items):
                require(len({k for k, _ in items}) == len(items), 'duplicate JSON keys')
                return dict(items)
            value = json.loads(content, object_pairs_hook=pairs)
            receipt['model_output'] = value
            receipt['normalized'] = (validate_stage1 if job['stage'] == 1 else validate_stage2)(value, job)
            status = 'verified'
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            status = 'invalid'
            receipt['error'] = 'output_protocol_validation'
            code = getattr(exc, 'error_code', None)
            receipt['error_code'] = code if code in {
                'anchor_slot_order', 'incomplete_generation'
            } else 'output_protocol_validation'
    except ReadinessDeadlineError:
        receipt.update(error='ReadinessDeadlineError', error_code='readiness_deadline',
                       host_diagnostic=accounting.readiness.snapshot())
    except JobTransportError as exc:
        trace = copy.deepcopy(exc.trace)
        diagnostic = trace.get('failure_diagnostic', {})
        diagnostic.pop('server_error', None)
        receipt.update(transport_trace=trace, error=diagnostic.get('kind', 'job_transport'))
        status = 'failed' if diagnostic.get('retryable') is False else 'pending'
    except Exception as exc:
        # Persist only exception type, never arbitrary provider body or credentials.
        receipt['error'] = type(exc).__name__
    receipt.update(status=status, latency_ms=round((clock()-started)*1000, 3))
    accounting.commit(job, receipt, status)
    return receipt


def run(workload, *, output_root, cfg=None, execute=False, mock=False, concurrency=4,
        target_ids=None, opener=urlrequest.urlopen, clock=time.perf_counter, sleep=time.sleep):
    """Dryrun by default. Mock uses local jobs envelopes; execute is opt-in."""
    require(type(concurrency) is int and 1 <= concurrency <= 4, 'concurrency must be C1..4')
    require(not (execute and mock), 'execute and mock are mutually exclusive')
    run_started = clock()
    w = load(workload)
    checked = preflight(w, cfg=cfg)
    requested = set(target_ids or [r['target_id'] for r in w['rows']])
    require(bool(requested) and requested <= {r['target_id'] for r in w['rows']}, 'unknown/empty TARGET selection')
    rows = [r for r in w['rows'] if r['target_id'] in requested]
    if not execute and not mock:
        return {**checked, 'status': 'not_executed', 'selected_target_ids': [r['target_id'] for r in rows],
                'selected_target_count': len(rows), 'concurrency': concurrency, 'network_executed': False}
    if cfg is None:
        cfg = {**w['identity'], 'jobs_url': w['identity']['url'].removesuffix('/chat/completions') + '/jobs',
               'timeout': 60, 'job_wait_seconds': 1800, 'job_poll_seconds': 2}
    cfg = copy.deepcopy(cfg)
    runtime = profile(w['parent_workload'], cfg)
    if execute: require(bool(cfg.get('token')), 'execution requires configured token')
    if mock:
        cfg.update(token='local-mock', job_poll_seconds=.001, job_wait_seconds=10)
    root = Path(output_root).resolve()
    protected = [w['source_store'], w['atom_root'], DEFAULT_MANIFEST.parent, DEFAULT_PARENT.parent]
    if isinstance(workload, (str, Path)): protected.append(Path(workload).parent)
    guard_output(root, protected)
    root.mkdir(parents=True, exist_ok=True)
    require((root / 'runtime_ledger.json').exists() or not any(root.iterdir()), 'new execution output must be fresh')
    lockpath = root / '.runner.lock'
    try: fd = os.open(lockpath, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError: raise ValueError('writer lock exists; confirm process stopped before removal') from None
    os.close(fd)
    try:
        bound = {'workload_sha256': w['workload_sha256'], 'code_sha256': code_hash(),
                 'prompt_profile': w['prompt_profile'], 'prompt_sha': w['prompt_sha'],
                 'selected_target_ids': [r['target_id'] for r in rows], 'mode': 'mock' if mock else 'execute',
                 'run_profile': runtime, 'budget': w['budget'], 'concurrency': concurrency}
        identity = fingerprint(bound)
        path = root / 'runtime_ledger.json'
        ledger = load(path) if path.exists() else {'identity': identity, 'binding': bound, 'jobs': {},
            'attempts': [], 'provider_attempts': 0, 'get_polls': 0, 'reserved_input_tokens': 0, 'reserved_output_tokens': 0}
        require(ledger['identity'] == identity and ledger['binding'] == bound, 'stale run/selection identity')
        if 'ledger_sha256' in ledger:
            require(ledger['ledger_sha256'] == fingerprint({k: v for k, v in ledger.items() if k != 'ledger_sha256'}), 'ledger digest mismatch')
        require(ledger['provider_attempts'] == len(ledger['attempts']) <= BUDGET['max_provider_attempts'], 'attempt counter mismatch')
        require(ledger['reserved_input_tokens'] == sum(a['reserved_input_tokens'] for a in ledger['attempts']) <= BUDGET['max_total_input_tokens'], 'input counter mismatch')
        require(ledger['reserved_output_tokens'] == sum(a['reserved_output_tokens'] for a in ledger['attempts']) <= BUDGET['max_total_output_tokens'], 'output counter mismatch')
        require(len(ledger['jobs']) <= BUDGET['max_requests'], 'logical counter overflow')
        prior_cost = ledger.get('recovery_prior_accounting', {})
        require(isinstance(prior_cost, dict), 'invalid recovery accounting')
        if prior_cost:
            manifest_path = prior_cost.get('manifest_path')
            require(bool(manifest_path), 'recovery accounting manifest required')
            recovery_manifest = load(manifest_path)
            manifest_sha = recovery_manifest.get('recovery_sha256')
            require(manifest_sha == prior_cost.get('manifest_sha256') and
                    manifest_sha == fingerprint({k: v for k, v in recovery_manifest.items()
                                                 if k != 'recovery_sha256'}),
                    'recovery accounting manifest digest mismatch')
            require({k: v for k, v in prior_cost.items() if k not in ('manifest_path', 'manifest_sha256')}
                    == recovery_manifest.get('prior_accounting'), 'recovery prior counters changed')
        for key, current, cap in (
                ('provider_attempts', ledger['provider_attempts'], 'max_provider_attempts'),
                ('reserved_input_tokens', ledger['reserved_input_tokens'], 'max_total_input_tokens'),
                ('reserved_output_tokens', ledger['reserved_output_tokens'], 'max_total_output_tokens')):
            value = prior_cost.get(key, 0)
            require(type(value) is int and value >= 0 and value + current <= w['budget'][cap],
                    'recovery aggregate budget exceeded')
        stage1jobs = [build_stage1(row, w['identity']) for row in rows]
        allowed_before_dispatch = {j['request_id']: j for j in stage1jobs}
        for row, job in zip(rows, stage1jobs):
            prior = ledger['jobs'].get(job['request_id'])
            if prior:
                require(prior['job'] == job, 'stage1 job changed before dispatch')
            if prior and prior.get('receipt_sha256'):
                receipt = _receipt(root, prior)
                if prior['status'] == 'verified':
                    valid = validate_stage1(receipt['model_output'], job)
                    require(valid == receipt.get('normalized'), 'cached normalized stage1 changed')
                    extra = build_stage2(row, valid, w['identity'])
                    allowed_before_dispatch.update({j['request_id']: j for j in extra})
        require(set(ledger['jobs']) <= set(allowed_before_dispatch), 'foreign resumed jobs before dispatch')
        for rid, entry in ledger['jobs'].items():
            require(entry['job'] == allowed_before_dispatch[rid], 'resumed payload/catalog changed')
            require(entry['status'] in ('reserved', 'pending', 'verified', 'invalid', 'failed'), 'unknown persisted job state')
            if entry.get('receipt_sha256'): _receipt(root, entry)
            if entry['status'] == 'verified' and entry['job']['stage'] == 2:
                receipt = _receipt(root, entry)
                require(validate_stage2(receipt['model_output'], entry['job']) == receipt['normalized'],
                        'cached normalized stage2 changed')
        known_jids = {entry['job']['payload_sha256'] for entry in ledger['jobs'].values()}
        for ordinal, attempt in enumerate(ledger['attempts'], 1):
            require(attempt['ordinal'] == ordinal and attempt['job_id'] in known_jids
                    and attempt['payload_sha256'] == attempt['job_id'], 'foreign attempt identity')
            receipt_path = root / 'attempt_receipts' / f'{ordinal:03d}.json'
            if receipt_path.exists():
                require(load(receipt_path) == attempt, 'attempt receipt/ledger mismatch')
            require(sum(a['job_id'] == attempt['job_id'] for a in ledger['attempts']) <= 2, 'per-job retry overflow')
        accounting = Accounting(root, ledger, w['budget'], opener)
        accounting.save()
        fake = MockJobs(stage1jobs) if mock else None
        if fake: accounting.opener = fake
        accounting.readiness = ReadinessGate(cfg, accounting.dispatch, clock, sleep,
            lambda diagnostic: _atomic(root / 'readiness.json', diagnostic))
        unfinished = any(ledger['jobs'].get(rid, {}).get('status') not in
                         ('verified', 'invalid', 'failed') for rid in allowed_before_dispatch)
        accounting.readiness.warmup(unfinished)
        def batch(jobs):
            result = {}
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(_worker, j, accounting, cfg, clock, sleep): j for j in jobs}
                for future in as_completed(futures):
                    job = futures[future]
                    try: result[job['target_id']] = future.result()
                    except Exception as exc:
                        # Unexpected local commit failures remain pending and isolated.
                        result[job['target_id']] = {'status': 'pending', 'normalized': None, 'error': type(exc).__name__}
            return result
        s1 = batch(stage1jobs)
        stage2jobs = []
        for row in rows:
            normalized = s1[row['target_id']].get('normalized')
            if normalized: stage2jobs.extend(build_stage2(row, normalized, w['identity']))
        require(len(stage2jobs) <= len(rows), 'more than one stage2 job per TARGET')
        allowed = {j['request_id']: j for j in stage1jobs + stage2jobs}
        require(set(ledger['jobs']) <= set(allowed), 'foreign resumed jobs')
        for rid, entry in ledger['jobs'].items(): require(entry['job'] == allowed[rid], 'resumed payload/catalog changed')
        if fake: fake.add(stage2jobs)
        s2 = batch(stage2jobs)
        results, revisit = [], []
        for row in rows:
            tid = row['target_id']; one, two = s1[tid], s2.get(tid)
            normalized = (two or one).get('normalized')
            if two and normalized is None:
                # Context failure cannot silently promote incomplete stage1 anchors.
                normalized = copy.deepcopy(one.get('normalized'))
                if normalized:
                    normalized['decision'] = 'unresolved'
                    for anchor in normalized['anchors']: anchor['status'] = 'unresolved'
            status = (two or one)['status']
            if not two and normalized and normalized.get('decision') == 'unresolved':
                for anchor in normalized['anchors']: anchor['status'] = 'unresolved'
            if normalized and normalized.get('decision') == 'revisit_target':
                for anchor in normalized['anchors']: anchor['status'] = 'unresolved'
            item = {'target_id': tid, 'case_id': row['case_id'], 'source_hash': row['source_hash'],
                    'prompt_profile': row['prompt_profile'], 'prompt_sha': row['prompt_sha'],
                    'target': row['target'], 'stage1_status': one['status'], 'stage2_status': two['status'] if two else 'not_needed',
                    'status': status, 'output': normalized, 'semantic_quality': 'not_assessed'}
            if normalized and normalized.get('revisit_required'):
                revisit.append({'target_id': tid, 'reason': normalized['reason'],
                                'reason_text': REASON_TEXT_VI[normalized['reason']],
                                'status': 'target_review_required', 'auto_dispatch': False})
            results.append(item)
        snap = accounting.snapshot()
        usage_by_job = {}
        imported_usage = {}
        for entry in snap['jobs'].values():
            if entry.get('receipt_sha256'):
                receipt = _receipt(root, entry)
                usage_by_job[entry['job']['payload_sha256']] = receipt.get('usage')
                if receipt.get('import_provenance') or entry.get('import_provenance'):
                    imported_usage[entry['job']['payload_sha256']] = receipt.get('usage')
        distinct = {a['job_id'] for a in snap['attempts']} | set(usage_by_job)
        known = [u for u in usage_by_job.values() if u is not None]
        # A final job usage explains only the final accepted generation. Earlier
        # uncertain attempts remain unknown, even if they share a digest/job ID.
        unknown_attempts = 0
        for index, attempt in enumerate(snap['attempts']):
            later = any(a['job_id'] == attempt['job_id'] for a in snap['attempts'][index+1:])
            explained = attempt.get('usage') is not None or attempt.get('provably_not_accepted') is True
            if not later and usage_by_job.get(attempt['job_id']) is not None: explained = True
            if not explained: unknown_attempts += 1
        usage_subtotal = {k: sum(u.get(k, 0) for u in known) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
        new_usage = [u for jid, u in usage_by_job.items() if jid not in imported_usage and u is not None]
        new_subtotal = {k: sum(u.get(k, 0) for u in new_usage) for k in usage_subtotal}
        imported_subtotal = {k: sum(u.get(k, 0) for u in imported_usage.values() if u is not None)
                             for k in usage_subtotal}
        prior_usage = prior_cost.get('known_provider_usage_observed_subtotal',
                                    prior_cost.get('known_provider_usage', {}))
        if not isinstance(prior_usage, dict):
            prior_usage = {}
        cumulative_subtotal = {k: prior_usage.get(k, 0) + new_subtotal[k] for k in usage_subtotal}
        if not prior_cost:
            cumulative_subtotal = usage_subtotal
        unknown_jobs = sum(usage_by_job.get(j) is None for j in distinct)
        prior_usage_complete = not prior_cost or (
            all(k in prior_usage for k in usage_subtotal)
            and prior_cost.get('unknown_usage_jobs') == 0
            and prior_cost.get('unknown_provider_attempts', 0) == 0
            and prior_cost.get('usage_is_complete') is not False)
        counts = {state: sum(entry['status'] == state for entry in snap['jobs'].values())
                  for state in ('verified', 'invalid', 'failed', 'pending', 'reserved')}
        terminal_done = counts['pending'] == counts['reserved'] == 0
        by_stage = {}
        for stage in (1, 2):
            receipts = [_receipt(root, entry) for entry in snap['jobs'].values()
                        if entry['job']['stage'] == stage and entry.get('receipt_sha256')]
            traces = [r.get('transport_trace', {}) for r in receipts]
            inference = [t.get('server_timing', {}).get('inference_seconds') for t in traces]
            by_stage[str(stage)] = {'client_latency_ms': sum(r.get('latency_ms', 0) for r in receipts),
                'job_polls': sum(t.get('polls', 0) for t in traces),
                'server_inference_seconds_observed_subtotal': sum(v for v in inference if isinstance(v, (int, float))),
                'server_inference_unknown_jobs': sum(not isinstance(v, (int, float)) for v in inference)}
        report = {'artifact_type': 'AUTargetContextRun', 'version': VERSION, 'identity': identity,
            'prompt_profile': w['prompt_profile'], 'prompt_sha': w['prompt_sha'],
            'stage1_baseline_input_reservation_utf8_bytes': checked['stage1_baseline_input_reservation_utf8_bytes'],
            'stage1_added_input_utf8_bytes': checked['stage1_added_input_utf8_bytes'],
            'stage1_max_added_input_utf8_bytes_per_target': checked['stage1_max_added_input_utf8_bytes_per_target'],
            'status': ('incomplete' if counts['invalid'] or counts['failed'] else 'complete') if terminal_done else 'pending',
            'terminal_done': terminal_done, 'protocol_counts': counts,
            'protocol_verified': counts['verified'], 'protocol_invalid': counts['invalid'],
            'failed': counts['failed'], 'pending': counts['pending'] + counts['reserved'],
            'mode': bound['mode'], 'network_executed': bool(execute), 'semantic_quality': 'not_assessed',
            'selected_target_count': len(rows), 'logical_requests': len(snap['jobs']),
            'frozen_target_count': len(w['rows']),
            'stage1_decision_counts': {d: sum(r.get('normalized', {}).get('decision') == d for r in s1.values()
                                        if r.get('normalized')) for d in STAGE1_DECISIONS},
            'stage1_no_anchor_needs_context': sum(r['normalized']['decision'] == 'needs_context' and not r['normalized']['anchors']
                                                for r in s1.values() if r.get('normalized')),
            'stage1_requests': len(stage1jobs), 'stage2_requests': len(stage2jobs), 'concurrency': concurrency,
            'transport_POST_attempts': snap['provider_attempts'], 'provider_POST_attempts': snap['provider_attempts'] if execute else 0,
            'GET_polls': snap['get_polls'], 'reserved_input_utf8_bytes': snap['reserved_input_tokens'],
            'reserved_output_tokens': snap['reserved_output_tokens'], 'unknown_usage_jobs': unknown_jobs,
            'unknown_provider_attempts': unknown_attempts, 'known_provider_usage_observed_subtotal': cumulative_subtotal,
            'new_generation_usage_observed_subtotal': new_subtotal,
            'imported_receipt_usage_observed_subtotal': imported_subtotal,
            'previous_run_usage_observed_subtotal': prior_usage,
            'previous_run_unknown_usage_jobs': prior_cost.get('unknown_usage_jobs', 0),
            'imported_verified_jobs': len(imported_usage),
            'aggregate_provider_POST_attempts': prior_cost.get('provider_attempts', 0) + snap['provider_attempts'],
            'aggregate_reserved_input_utf8_bytes': prior_cost.get('reserved_input_tokens', 0) + snap['reserved_input_tokens'],
            'aggregate_reserved_output_tokens': prior_cost.get('reserved_output_tokens', 0) + snap['reserved_output_tokens'],
            'total_provider_usage': cumulative_subtotal if not mock and prior_usage_complete and unknown_attempts == unknown_jobs == 0 else None,
            'results': results, 'revisit_queue': revisit, 'mock_max_inflight': fake.max_inflight if fake else None,
            'POST_ack_latency_ms': sum(a.get('latency_ms', 0) for a in snap['attempts']),
            'elapsed_wall_ms': round((clock()-run_started)*1000, 3), 'stage_timings': by_stage,
            'readiness': accounting.readiness.snapshot(),
            'readiness_timing': 'shared warmup measured separately; worker retrieval readiness included in client latency',
            'budget': w['budget']}
        _atomic(root / 'run.json', report)
        return report
    finally:
        lockpath.unlink()
