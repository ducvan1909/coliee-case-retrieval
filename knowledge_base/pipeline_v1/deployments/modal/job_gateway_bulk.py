"""Isolated C4 bulk/corpus gateway with durable completion cursors; no retries.

Client identity: sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest().
"""

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response


STORE_MUTEX = threading.RLock()
JOB_ID = re.compile(r"[0-9a-f]{64}\Z")


def validate_concurrency(value):
    if type(value) is not int or value not in (1, 2, 4):
        raise ValueError("Concurrency must be an integer in {1, 2, 4}")
    return value


class InferenceGate:
    """One shared gate: bounded jobs OR one exclusive probe/diagnostic.

    Reservations span durable claim, backend call and final persistence. Never
    acquire a reservation while holding STORE_MUTEX. Failed exclusive attempts
    return immediately, including when just one of many workers remains active.
    """

    def __init__(self, limit):
        self.limit = limit
        self.condition = threading.Condition()
        self.active = 0
        self.exclusive = False

    def acquire_job(self, unavailable, exclusive=False):
        with self.condition:
            while self.exclusive or (self.active > 0 if exclusive else self.active >= self.limit):
                if unavailable():
                    return False
                self.condition.wait(0.1)
            if unavailable():
                return False
            if exclusive:
                self.exclusive = True
            else:
                self.active += 1
            return True

    def release_job(self, exclusive=False):
        with self.condition:
            if exclusive:
                self.exclusive = False
            else:
                self.active -= 1
            self.condition.notify_all()

    def acquire(self, blocking=False):
        if blocking:
            raise ValueError("Exclusive diagnostics must not wait for inference")
        with self.condition:
            if self.active or self.exclusive:
                return False
            self.exclusive = True
            return True

    def release(self):
        with self.condition:
            self.exclusive = False
            self.condition.notify_all()


def canonical_payload(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def payload_job_id(payload):
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class JobGateway:
    def __init__(self, store_root, commit, backend_url="http://127.0.0.1:8001/v1/chat/completions",
                 backend_timeout=1800, max_body_bytes=16 * 1024 * 1024,
                 concurrency=4, server_concurrency=None):
        if not 0 < backend_timeout <= 1800 or max_body_bytes <= 0:
            raise ValueError("Invalid gateway limits")
        self.root = Path(store_root)
        self.commit = commit
        self.backend_url = backend_url
        self.timeout = backend_timeout
        self.max_body = max_body_bytes
        self.concurrency = validate_concurrency(concurrency)
        self.server_concurrency = validate_concurrency(
            concurrency if server_concurrency is None else server_concurrency)
        if self.server_concurrency != self.concurrency:
            raise ValueError("Gateway and server concurrency must match")
        self.inference = InferenceGate(self.concurrency)
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.poisoned = False
        self.backend_uncertain = False
        self.worker = None
        self.workers = []
        self.lifecycle_mutex = threading.Lock()
        if self.concurrency != 4:
            raise ValueError("Bulk deployment requires C4")
        self.groups = {}
        self.states = {}
        self.pending = {}
        self.memberships = {}
        self.initialized = False
        self.admission_window = 16
        self.admission_deques = {}
        self.admission_groups = deque()
        self.retirement_candidates = set()
        self.recovering = False

    def atomic_write(self, path, value, *, commit=True):
        """All mutations run under STORE_MUTEX; poison on uncertain durability."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        try:
            with temporary.open('wb') as output:
                output.write(canonical_payload(value))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            if commit:
                self.commit()
        except Exception:
            self.poisoned = True
            raise

    def commit_store(self):
        try:
            self.commit()
        except Exception:
            self.poisoned = True
            raise

    def write_unknown(self):
        self.atomic_write(self.root / 'unhealthy.json', {'backend_outcome_unknown': True})

    def benchmark_info(self):
        with STORE_MUTEX:
            return {'experiment': 'au-bulk-v1', 'app': 'coliee-qwen35-9b-bulk',
                    'gateway_concurrency': 4, 'server_concurrency': 4,
                    'cuda_graph_max_bs': 4, 'max_containers': 1,
                    'model': 'Qwen/Qwen3.5-9B',
                    'model_revision': 'c202236235762e1c871ad0ccb60c8ee5ba337b9a',
                    'gpu': 'L40S:1', 'context_length': 12288, 'cpu': 4,
                    'memory_mb': 16384, 'max_total_tokens': 12288,
                    'job_volume': 'coliee-qwen35-9b-bulk-jobs',
                    'job_store_subdir': 'bulk-v1', 'admission_window': 16,
                    'batch_max_jobs': 32, 'batch_max_bytes': 4 * 1024 * 1024,
                    'corpus_max_jobs': 600, 'corpus_max_bytes': 16 * 1024 * 1024,
                    'capabilities': {'bulk_submit': True, 'incremental_progress': True,
                                     'pending_queue': True, 'corpus_runner': True},
                    'backend_retry': False, 'exclusive_probes': True,
                    'configuration_evidence': 'configured_not_live_scheduler',
                    'unhealthy': self.unavailable(), 'ready': not self.unavailable(),
                    'poisoned': self.poisoned, 'stopping': self.stop_event.is_set(),
                    'backend_outcome_unknown': self.backend_uncertain}

    def path(self, job_id):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise HTTPException(400, 'job_id must be 64 lowercase hex characters')
        return self.root / 'archive' / (job_id + '.json')

    def marker_path(self, job_id):
        self.path(job_id)
        return self.root / 'pending' / (job_id + '.json')

    def group_path(self, mode, group_id, kind='manifests'):
        if mode not in ('bulk', 'corpus') or not isinstance(group_id, str) or not JOB_ID.fullmatch(group_id):
            raise HTTPException(400, 'Invalid group identity')
        return self.root / kind / mode / (group_id + '.json')

    @staticmethod
    def group_id(mode, jobs):
        return payload_job_id({'mode': mode, 'jobs': jobs})

    def load_manifest(self, key):
        if key in self.groups:
            return self.groups[key]
        path = self.group_path(*key)
        if not path.exists():
            path = self.group_path(*key, kind='active')
        if not path.exists():
            raise HTTPException(404, 'Unknown group')
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if manifest['mode'] != key[0] or manifest['group_id'] != key[1] or self.group_id(key[0], manifest['jobs']) != key[1]:
            raise ValueError('Invalid manifest identity')
        return manifest

    def read(self, job_id):
        archive = self.path(job_id)
        marker = self.marker_path(job_id)
        path = archive if archive.exists() else marker
        if not path.exists():
            raise HTTPException(404, 'Unknown job')
        record = json.loads(path.read_text(encoding='utf-8'))
        if record['job_id'] != job_id:
            raise ValueError('Invalid receipt identity')
        if 'payload' not in record:
            ref = record['payload_ref']
            capsule = self.load_manifest((ref['mode'], ref['group_id']))['jobs'][ref['index']]
            if capsule['job_id'] != job_id:
                raise ValueError('Invalid payload reference')
            record['payload'] = capsule['payload']
        if payload_job_id(record['payload']) != job_id:
            raise ValueError('Invalid durable payload identity')
        return record

    def load_state(self, key):
        if key in self.states:
            return self.states[key]
        path = self.group_path(*key, kind='states')
        if not path.exists():
            raise HTTPException(404, 'Unknown group')
        return json.loads(path.read_text(encoding='utf-8'))

    def save_state(self, key, *, commit=True):
        self.atomic_write(self.group_path(*key, kind='states'), self.states[key], commit=commit)

    @staticmethod
    def validate_state(manifest, state):
        ids = {capsule['job_id'] for capsule in manifest['jobs']}
        statuses, events = state['statuses'], state['events']
        terminal = {'completed', 'failed', 'interrupted'}
        if (set(statuses) != ids or any(s not in terminal | {'queued', 'running'} for s in statuses.values())
                or not isinstance(events, list) or len(events) != len(set(events))
                or any(j not in ids or statuses[j] not in terminal for j in events)
                or {j for j, status in statuses.items() if status in terminal} != set(events)):
            raise ValueError('Invalid completion index')

    def checkpoint(self, record):
        """Index each terminal job once; event ordering is commit ordering."""
        terminal = record['status'] in ('completed', 'failed', 'interrupted')
        for key in self.memberships.get(record['job_id'], ()):
            state = self.states[key]
            previous = state['statuses'][record['job_id']]
            state['statuses'][record['job_id']] = record['status']
            if terminal and previous not in ('completed', 'failed', 'interrupted'):
                state['events'].append(record['job_id'])
            if len(state['events']) == len(state['statuses']):
                self.retirement_candidates.add(key)
            self.save_state(key, commit=False)

    def retire_groups(self, *, commit=True):
        changed = False
        for key in tuple(self.retirement_candidates):
            if key not in self.states:
                self.retirement_candidates.discard(key)
                continue
            state = self.states[key]
            active = self.group_path(*key, kind='active')
            archive = self.group_path(*key)
            try:
                archive.parent.mkdir(parents=True, exist_ok=True)
                if active.exists():
                    os.replace(active, archive)  # One payload manifest; no copies.
            except Exception:
                self.poisoned = True
                raise
            changed = True
            for job_id in state['statuses']:
                members = self.memberships.get(job_id)
                if members:
                    members.discard(key)
                    if not members:
                        del self.memberships[job_id]
            del self.states[key]
            del self.groups[key]
            self.admission_deques.pop(key, None)
            self.retirement_candidates.discard(key)
        if changed and commit:
            self.commit_store()
        return changed

    def persist(self, record):
        terminal = record['status'] in ('completed', 'failed', 'interrupted')
        durable = {k: v for k, v in record.items() if k != 'payload' or 'payload_ref' not in record}
        target = self.path(record['job_id']) if terminal else self.marker_path(record['job_id'])
        # Receipt and status index are committed together. A terminal marker is
        # removed only after that commit, so restart can finish any partial step.
        self.atomic_write(target, durable, commit=False)
        if record.get('error', {}).get('outcome_unknown') or record.get('error', {}).get('kind') == 'unknown_inference_outcome':
            self.backend_uncertain = True
            self.atomic_write(self.root / 'unhealthy.json', {'backend_outcome_unknown': True}, commit=False)
        self.checkpoint(record)
        self.commit_store()  # Including running: strictly before backend dispatch.
        if terminal:
            try:
                self.marker_path(record['job_id']).unlink(missing_ok=True)
                self.pending.pop(record['job_id'], None)
                # Cleanup, all manifest retirements and bounded refill share ONE
                # commit after the receipt+event checkpoint is already durable.
                if not self.recovering:
                    self.retire_groups(commit=False)
                    self.admit_window(commit=False)
                self.commit_store()
            except Exception:
                self.poisoned = True
                raise
        else:
            self.pending[record['job_id']] = durable
        self.wake.set()

    def seed_admission(self, key):
        """One manifest pass on submission/recovery; deque is not durable state."""
        state = self.states[key]
        remaining = deque()
        for index, capsule in enumerate(self.groups[key]['jobs']):
            job_id = capsule['job_id']
            if state['statuses'][job_id] != 'queued':
                continue
            if job_id in self.pending:
                state['statuses'][job_id] = self.pending[job_id]['status']
            elif self.path(job_id).exists():
                self.checkpoint(self.read(job_id))
            else:
                remaining.append(index)
        self.save_state(key, commit=False)
        if remaining:
            self.admission_deques[key] = remaining
            self.admission_groups.append(key)

    def admit_window(self, *, commit=True):
        """Consume unadmitted indices only; never rescan finished capsules."""
        if self.unavailable():
            return False
        changed = False
        while self.admission_groups and len(self.pending) < self.admission_window:
            key = self.admission_groups[0]
            remaining = self.admission_deques.get(key)
            if not remaining or key not in self.groups:
                self.admission_groups.popleft()
                self.admission_deques.pop(key, None)
                continue
            index = remaining.popleft()
            state = self.states[key]
            capsule = self.groups[key]['jobs'][index]
            job_id = capsule['job_id']
            if state['statuses'][job_id] != 'queued' or job_id in self.pending:
                continue  # Shared job already admitted/finished via another group.
            if self.path(job_id).exists():
                self.checkpoint(self.read(job_id))
                changed = True
                continue
            stamp = now()
            record = {'job_id': job_id, 'payload_sha256': job_id, 'status': 'queued',
                      'payload_ref': {'mode': key[0], 'group_id': key[1], 'index': index},
                      'created_at': stamp, 'updated_at': stamp}
            self.atomic_write(self.marker_path(job_id), record, commit=False)
            self.pending[job_id] = record
            changed = True
        changed = self.retire_groups(commit=False) or changed
        if changed and commit:
            self.commit_store()
        return changed

    def submit_group(self, mode, group_id, jobs):
        self.group_path(mode, group_id)
        bound = 32 if mode == 'bulk' else 600
        if not isinstance(jobs, list) or not 1 <= len(jobs) <= bound:
            raise HTTPException(400, f'Expected 1..{bound} jobs')
        try:
            body_key = 'batch_id' if mode == 'bulk' else 'corpus_id'
            body_bytes = len(canonical_payload({body_key: group_id, 'jobs': jobs}))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise HTTPException(400, 'Invalid JSON payload') from None
        if body_bytes > (4 if mode == 'bulk' else 16) * 1024 * 1024:
            raise HTTPException(413, 'Request body too large')
        seen = set()
        for capsule in jobs:
            if not isinstance(capsule, dict) or set(capsule) != {'job_id', 'payload'}:
                raise HTTPException(400, 'Expected job_id and payload capsules')
            job_id, payload = capsule['job_id'], capsule['payload']
            self.path(job_id)
            if job_id in seen:
                raise HTTPException(400, 'Duplicate job_id in group')
            seen.add(job_id)
            if not isinstance(payload, dict) or payload.get('stream') not in (None, False):
                raise HTTPException(400, 'Expected non-streaming chat payload')
            try:
                expected = payload_job_id(payload)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise HTTPException(400, 'Invalid JSON payload') from None
            if expected != job_id:
                raise HTTPException(409, 'job_id does not match canonical payload')
        if self.group_id(mode, jobs) != group_id:
            raise HTTPException(409, 'Group ID does not match canonical mode and jobs')
        key = (mode, group_id)
        with STORE_MUTEX:
            if self.poisoned:
                raise HTTPException(503, 'Durable store unavailable')
            if not self.initialized:
                self.recover()
            if self.group_path(*key).exists() or self.group_path(*key, kind='active').exists():
                existing = self.load_manifest(key)
                if canonical_payload(existing['jobs']) != canonical_payload(jobs):
                    raise HTTPException(409, 'Conflicting immutable group')
                return self.progress(mode, group_id, 0, 16)
            if self.unavailable():
                raise HTTPException(503, 'Gateway unavailable')
            # Active manifest is the authoritative admission source. It stores
            # payloads ONCE, before writing the recoverable status index/markers.
            # Retirement moves this same file into manifests, never rewrites it.
            manifest = {'mode': mode, 'group_id': group_id, 'jobs': jobs, 'created_at': now()}
            self.atomic_write(self.group_path(*key, kind='active'), manifest, commit=False)
            self.groups[key] = manifest
            self.states[key] = {'statuses': {j['job_id']: 'queued' for j in jobs}, 'events': []}
            for capsule in jobs:
                self.memberships.setdefault(capsule['job_id'], set()).add(key)
            self.save_state(key, commit=False)
            self.commit_store()  # Entire group durable before acknowledgement.
            self.seed_admission(key)
            self.admit_window(commit=False)
            self.commit_store()  # Shared receipt updates/admission/cleanup together.
            self.wake.set()
            return self.progress(mode, group_id, 0, 16)

    def submit(self, job_id, payload, *, exclusive=False):
        """Private single-job compatibility/replay path, never retries."""
        self.path(job_id)
        if not isinstance(payload, dict) or payload.get('stream') not in (None, False):
            raise HTTPException(400, 'Expected non-streaming chat payload')
        if payload_job_id(payload) != job_id:
            raise HTTPException(409, 'job_id does not match canonical payload')
        with STORE_MUTEX:
            if self.unavailable():
                raise HTTPException(503, 'Gateway unavailable')
            if self.path(job_id).exists() or job_id in self.pending:
                record = self.read(job_id)
                if exclusive and record['status'] == 'queued':
                    record['inference_mode'] = 'exclusive'
                    self.persist(record)
                return self.public(record)
            if len(self.pending) >= self.admission_window:
                raise HTTPException(429, 'Admission window full')
            record = {'job_id': job_id, 'payload': payload, 'status': 'queued',
                      'created_at': now(), 'updated_at': now()}
            if exclusive:
                record['inference_mode'] = 'exclusive'
            self.persist(record)
            return self.public(record)

    def progress(self, mode, group_id, after=0, limit=16):
        with STORE_MUTEX:
            if self.poisoned:
                raise HTTPException(503, 'Durable store unavailable')
            key = (mode, group_id)
            self.group_path(*key)
            state = self.load_state(key)
            sequence = len(state['events'])
            if type(after) is not int or not 0 <= after <= sequence or type(limit) is not int or not 1 <= limit <= 32:
                raise HTTPException(400, 'after must be 0..sequence and limit 1..32')
            counts = {s: 0 for s in ('queued', 'running', 'completed', 'failed', 'interrupted')}
            for status in state['statuses'].values():
                counts[status] += 1
            counts['total'] = len(state['statuses'])
            terminal = counts['completed'] + counts['failed'] + counts['interrupted']
            status = ('completed' if counts['completed'] == counts['total'] else
                      'interrupted' if terminal == counts['total'] and counts['interrupted'] else
                      'failed' if terminal == counts['total'] else
                      'blocked' if self.unavailable() else 'running' if counts['running'] else 'queued')
            job_ids = state['events'][after:after + limit]
            results = []
            for job_id in job_ids:
                # Read only this page's terminal receipts, never the archive.
                receipt = json.loads(self.path(job_id).read_text(encoding='utf-8'))
                result = self.public(receipt)
                result.pop('payload_ref', None)
                for field in ('response', 'response_sha256', 'usage', 'inference_seconds', 'error'):
                    result.setdefault(field, None)
                result['timestamps'] = {k: receipt.get(k) for k in ('created_at', 'started_at', 'updated_at', 'finished_at')}
                results.append(result)
            return {'group_id': group_id, 'mode': mode, 'status': status, 'counts': counts,
                    'cursor': after, 'next_cursor': after + len(results), 'results': results}

    def recover(self):
        with STORE_MUTEX:
            if self.initialized:
                return
            self.root.mkdir(parents=True, exist_ok=True)
            self.backend_uncertain = (self.root / 'unhealthy.json').exists()
            # Exactly one startup scan of active manifests and pending markers;
            # immutable historical manifests/receipts are never globbed.
            for mode in ('bulk', 'corpus'):
                for path in sorted((self.root / 'active' / mode).glob('*.json')):
                    manifest = json.loads(path.read_text(encoding='utf-8'))
                    key = (mode, path.stem)
                    if self.group_id(mode, manifest['jobs']) != key[1] or manifest['mode'] != mode or manifest['group_id'] != key[1]:
                        raise ValueError('Invalid active manifest')
                    self.groups[key] = manifest
                    state_path = self.group_path(*key, kind='states')
                    self.states[key] = (json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else
                                        {'statuses': {j['job_id']: 'queued' for j in manifest['jobs']}, 'events': []})
                    self.validate_state(manifest, self.states[key])
                    for capsule in manifest['jobs']:
                        self.memberships.setdefault(capsule['job_id'], set()).add(key)
            for path in sorted((self.root / 'pending').glob('*.json')):
                self.pending[path.stem] = json.loads(path.read_text(encoding='utf-8'))
            self.initialized = True
            self.recovering = True
            # Inspect referenced paths once, not all archived payloads.
            ids = dict.fromkeys([*self.memberships, *self.pending])
            for job_id in ids:
                if not self.path(job_id).exists() and job_id not in self.pending:
                    indexed = [(key, self.states[key]['statuses'][job_id])
                               for key in self.memberships.get(job_id, ())]
                    if any(status in ('completed', 'failed', 'interrupted') for _, status in indexed):
                        self.poisoned = True
                        raise ValueError('Terminal index without durable receipt')
                    if any(status == 'running' for _, status in indexed):
                        # Fail closed even if a damaged/partial store retained
                        # running index but lost the claim marker. Never infer
                        # that absence means it is safe to dispatch again.
                        key = indexed[0][0]
                        index = next(i for i, capsule in enumerate(self.groups[key]['jobs'])
                                     if capsule['job_id'] == job_id)
                        stamp = now()
                        self.persist({'job_id': job_id, 'status': 'interrupted',
                                      'payload_ref': {'mode': key[0], 'group_id': key[1], 'index': index},
                                      'created_at': stamp, 'updated_at': stamp, 'finished_at': stamp,
                                      'error': {'phase': 'restart', 'kind': 'unknown_inference_outcome',
                                                'outcome_unknown': True}})
                    continue  # Unadmitted capsule; controller will admit it.
                record = self.read(job_id)
                if record['status'] == 'running':
                    record.update(status='interrupted', updated_at=now(), finished_at=now(),
                                  error={'phase': 'restart', 'kind': 'unknown_inference_outcome', 'outcome_unknown': True})
                    self.persist(record)
                elif record['status'] in ('completed', 'failed', 'interrupted'):
                    self.persist(record)  # Idempotent checkpoint and marker cleanup.
                else:
                    self.checkpoint(record)
            self.commit_store()
            self.retire_groups(commit=False)
            for key in tuple(self.groups):
                self.seed_admission(key)
            self.recovering = False
            self.admit_window(commit=False)
            self.commit_store()

    def run(self):
        while not self.unavailable():
            self.wake.clear()
            try:
                with STORE_MUTEX:
                    queued = [r for r in self.pending.values() if r['status'] == 'queued']
                    candidate = min(queued, key=lambda r: (r['created_at'], r['job_id'])) if queued else None
                if candidate is not None:
                    exclusive = candidate.get('inference_mode') == 'exclusive'
                    if not self.inference.acquire_job(self.unavailable, exclusive):
                        return
                    try:
                        with STORE_MUTEX:
                            if self.unavailable():
                                return
                            record = self.read(candidate['job_id'])
                            if record['status'] != 'queued' or (record.get('inference_mode') == 'exclusive') != exclusive:
                                continue
                            record.update(status='running', started_at=now(), updated_at=now())
                            self.persist(record)
                        self.execute(record)
                        continue
                    finally:
                        self.inference.release_job(exclusive)
            except Exception:
                with STORE_MUTEX:
                    self.poisoned = True
                return
            self.wake.wait(1)

    def unavailable(self):
        return self.poisoned or self.backend_uncertain or self.stop_event.is_set()





    @staticmethod
    def public(record):
        result = {key: value for key, value in record.items() if key != "payload"}
        result["payload_sha256"] = record["job_id"]
        return result



    def start(self):
        with self.lifecycle_mutex:
            if self.workers or self.stop_event.is_set():
                raise RuntimeError("Gateway lifecycle already started or stopped")
            self.recover()
            self.workers = [threading.Thread(target=self.run,
                name=f"durable-job-worker-{index}", daemon=True)
                for index in range(self.concurrency)]
            self.worker = self.workers[0]
            for worker in self.workers:
                worker.start()

    def stop(self, grace_seconds=50):
        with self.lifecycle_mutex:
            with STORE_MUTEX:
                already_stopping = self.stop_event.is_set()
                self.stop_event.set()
            workers = list(self.workers)
        self.wake.set()
        if already_stopping:
            return  # Modal exit + ASGI lifespan must not add a second grace budget.
        # One grace budget for ALL workers, rather than N times the budget.
        deadline = time.monotonic() + max(0, grace_seconds)
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(timeout=max(0, deadline - time.monotonic()))
        # Do not declare a running request interrupted while it may still finish.
        # A killed container leaves running on disk; next startup reconciles it.

    def call_backend(self, payload):
        request = urllib.request.Request(self.backend_url, data=canonical_payload(payload),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.status, response.read()


    def execute(self, record):
        began = time.monotonic()
        phase = "backend_dispatch"
        try:
            status, body = self.call_backend(record["payload"])
            record["provider_http_status"] = status
            phase = "backend_response_decode"
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError("Expected provider response object")
            record.update(status="completed", response=result, usage=result.get("usage"),
                          provider_http_status=status, response_sha256=payload_job_id(result))
        except urllib.error.HTTPError as error:
            # HTTP failure is known; do not store error strings potentially echoing inputs.
            record.update(status="failed", provider_http_status=error.code,
                          error={"phase": phase, "kind": "backend_http_error"})
            error.close()
        except Exception as error:
            uncertain = phase == "backend_dispatch"
            if uncertain:
                # Sticky across concurrent successes/decode failures. Already
                # claimed calls may finish; all subsequent claims fail closed.
                with STORE_MUTEX:
                    self.backend_uncertain = True
            record.update(status="interrupted" if uncertain else "failed",
                          error={"phase": phase, "kind": type(error).__name__,
                                 "outcome_unknown": uncertain})
        record.update(finished_at=now(), updated_at=now(),
                      inference_seconds=time.monotonic() - began)
        with STORE_MUTEX:
            self.persist(record)

    async def body(self, request, max_bytes=None):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > (self.max_body if max_bytes is None else max_bytes):
                raise HTTPException(413, "Request body too large")
            data.extend(chunk)
        def reject_constant(value):
            raise ValueError("Non-finite JSON")
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate JSON key")
                result[key] = value
            return result
        try:
            value = json.loads(data, parse_constant=reject_constant, object_pairs_hook=unique_object)
            if not isinstance(value, dict):
                raise ValueError("Expected JSON object")
            canonical_payload(value)
            return value
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise HTTPException(400, "Invalid JSON object") from None


def create_app(store_root, commit, **options):
    """Return FastAPI app; app.state.gateway exposes start/stop and queue state."""
    diagnostic_inspector = options.pop("diagnostic_inspector", None)
    gateway = JobGateway(store_root, commit, **options)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(gateway.start)
        yield
        await asyncio.to_thread(gateway.stop)

    app = FastAPI(lifespan=lifespan)
    app.state.gateway = gateway

    async def admit_group(request, mode):
        bound = (4 if mode == 'bulk' else 16) * 1024 * 1024
        value = await gateway.body(request, max_bytes=bound)
        id_key = 'batch_id' if mode == 'bulk' else 'corpus_id'
        if set(value) != {id_key, 'jobs'}:
            raise HTTPException(400, f'Expected {id_key} and jobs')
        try:
            result = await asyncio.to_thread(gateway.submit_group, mode, value[id_key], value['jobs'])
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'Durable store unavailable') from None
        return JSONResponse(result, status_code=202)

    async def group_progress(mode, group_id, after, limit):
        if not re.fullmatch(r'[0-9]+', after) or not re.fullmatch(r'[0-9]+', limit) or len(after) > 6 or len(limit) > 2:
            raise HTTPException(400, 'Expected integer cursor and limit')
        try:
            return await asyncio.to_thread(gateway.progress, mode, group_id, int(after), int(limit))
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'Durable store unavailable') from None

    @app.post('/v1/batches')
    async def batches(request: Request):
        return await admit_group(request, 'bulk')

    @app.get('/v1/batches/{group_id}')
    async def batch_progress(group_id: str, after: str = '0', limit: str = '16'):
        return await group_progress('bulk', group_id, after, limit)

    @app.post('/v1/corpora')
    async def corpora(request: Request):
        return await admit_group(request, 'corpus')

    @app.get('/v1/corpora/{group_id}')
    async def corpus_progress(group_id: str, after: str = '0', limit: str = '16'):
        return await group_progress('corpus', group_id, after, limit)

    # Modal's unauthenticated=False protects all routes at its proxy. This app
    # has no standalone auth layer: never expose it outside that private server.
    @app.get("/v1/diagnostics/json/info")
    async def diagnostic_info():
        def inspect():
            if not gateway.inference.acquire(blocking=False):
                raise HTTPException(409, "Inference busy")
            try:
                if gateway.poisoned or gateway.backend_uncertain or gateway.stop_event.is_set():
                    raise HTTPException(503, "Backend unavailable until restart")
                if diagnostic_inspector is None:
                    raise HTTPException(503, "Runtime inspector unavailable")
                return diagnostic_inspector()
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(503, "Runtime inspection unavailable") from None
            finally:
                gateway.inference.release()
        return await asyncio.to_thread(inspect)

    @app.post("/v1/diagnostics/json/replay")
    async def diagnostic_replay(request: Request):
        try:
            from .json_diagnostic import CASE_ID, PAYLOAD_SHA256, replay_payload, diagnostic_job
        except ImportError:
            from json_diagnostic import CASE_ID, PAYLOAD_SHA256, replay_payload, diagnostic_job
        value = await gateway.body(request)
        if (set(value) != {"case_id", "payload_sha256", "payload"}
                or value["case_id"] != CASE_ID or value["payload_sha256"] != PAYLOAD_SHA256):
            raise HTTPException(400, "Pinned diagnostic identity required")
        try:
            payload = replay_payload(value["payload"], payload_job_id)
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(409, "Pinned diagnostic payload mismatch") from None
        def admit():
            if not gateway.inference.acquire(blocking=False):
                raise HTTPException(409, "Inference busy")
            try:
                with STORE_MUTEX:
                    if gateway.poisoned or gateway.backend_uncertain or gateway.stop_event.is_set():
                        raise HTTPException(503, "Backend unavailable until restart")
                    original = gateway.read(PAYLOAD_SHA256)
                    if original["status"] not in ("completed", "failed", "interrupted"):
                        raise HTTPException(409, "Original job is not terminal")
                    return diagnostic_job(gateway.submit(payload_job_id(payload), payload, exclusive=True))
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(503, "Durable store unavailable") from None
            finally:
                gateway.inference.release()
        return JSONResponse(await asyncio.to_thread(admit), status_code=202)

    @app.get("/health")
    async def health():
        info = await asyncio.to_thread(gateway.benchmark_info)
        return JSONResponse(info, status_code=200 if info["ready"] else 503)

    @app.get("/v1/benchmark/info")
    async def benchmark_info():
        return await asyncio.to_thread(gateway.benchmark_info)

    @app.post("/v1/jobs")
    async def submit(request: Request):
        value = await gateway.body(request)
        if set(value) != {"job_id", "payload"}:
            raise HTTPException(400, "Expected job_id and payload")
        try:
            result = await asyncio.to_thread(gateway.submit, value["job_id"], value["payload"])
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Durable store unavailable") from None
        return JSONResponse(result, status_code=202)

    @app.get("/v1/jobs/{job_id}")
    async def get(job_id: str):
        def read():
            with STORE_MUTEX:
                if gateway.poisoned:
                    raise HTTPException(503, "Durable store unavailable")
                return gateway.public(gateway.read(job_id))
        try:
            return await asyncio.to_thread(read)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Durable store unavailable") from None

    @app.post("/v1/chat/completions")
    async def synchronous(request: Request):
        payload = await gateway.body(request)
        if payload.get("stream") not in (None, False):
            raise HTTPException(400, "Streaming is unsupported")
        def proxy():
            if not gateway.inference.acquire(blocking=False):
                raise HTTPException(409, "Inference busy; poll jobs or try probe later")
            try:
                if gateway.poisoned or gateway.backend_uncertain or gateway.stop_event.is_set():
                    raise HTTPException(503, "Backend unavailable until restart")
                try:
                    status, body = gateway.call_backend(payload)
                    return Response(body, status_code=status, media_type="application/json")
                except urllib.error.HTTPError as error:
                    status = error.code
                    error.close()
                    raise HTTPException(status, "Backend HTTP failure") from None
                except Exception:
                    with STORE_MUTEX:
                        gateway.backend_uncertain = True
                        gateway.write_unknown()
                    raise HTTPException(504, "Backend outcome unknown; restart required") from None
            finally:
                gateway.inference.release()
        return await asyncio.to_thread(proxy)

    return app
