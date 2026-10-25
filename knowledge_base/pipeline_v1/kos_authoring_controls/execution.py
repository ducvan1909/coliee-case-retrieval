"""Bounded, sequential control transport. No semantic evaluation or corpus dispatch.

``run_jobs(root, cfg, jobs, opener=..., execute=False)`` binds the exact ordered
job list and runtime in root. Dry runs never access the network.
Receipts and intents are immutable; ledger/report are derived checkpoints.
An ambiguous POST is retrieval-only forever, including after a remote 404.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from urllib import request
from urllib.error import HTTPError
from urllib.parse import urlsplit
import uuid

from ..au_compact.jobs_client import complete_job, payload_digest, JobTransportError
from ..au_target_context.readiness import ReadinessGate
from ..k0_authoring import token_budget

MAX_POSTS, MAX_INPUT, MAX_OUTPUT, MAX_TOTAL = 12, 6000, 800, 30000


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _seal(value):
    return dict(value, record_sha256=payload_digest(value))


def _verify_record(value):
    if not isinstance(value, dict) or value.get('record_sha256') != payload_digest(
            {k: v for k, v in value.items() if k != 'record_sha256'}):
        raise ValueError('immutable record digest mismatch')


def _write(path, value, *, immutable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')
    if immutable:
        with path.open('xb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        return
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def _lock(root):
    """OS lock releases on crash; the persistent lock file is not a stale lock."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'lock').open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _usage(body):
    value = body.get('usage', body.get('_usage')) if isinstance(body, dict) else None
    if not isinstance(value, dict):
        return None
    keys = ('prompt_tokens', 'completion_tokens', 'total_tokens')
    if 'input_tokens' in value:
        keys = ('input_tokens', 'output_tokens', 'total_tokens')
    if not all(type(value.get(k)) is int and value[k] >= 0 for k in keys):
        return None
    if value[keys[2]] < value[keys[0]] + value[keys[1]]:
        return None
    return dict(zip(('input_tokens', 'output_tokens', 'total_tokens'), (value[k] for k in keys)))


def run_jobs(root, cfg, jobs, opener=request.urlopen, execute=False, *, selected_names=None,
             clock=time.monotonic, sleep=time.sleep):
    """Return a structured partial/complete report; execute=False is local only.

    Jobs contain name, payload, validation_job and optional expected (opaque host metadata). Names and
    payload hashes must be unique. New attempts require known prior usage and
    room under both cumulative reservation and measured-usage ceilings.
    Failed/pending receipts resume by GET; completed receipts are never rerun.
    selected_names selects stages without changing the full workload binding.
    Main must apply CPU/semantic gates before selecting subsequent stages.
    """
    # Copy caller data and reject non-JSON/nonfinite objects before any mutation.
    jobs = json.loads(json.dumps(jobs, allow_nan=False))
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('nonempty ordered jobs list required')
    cfg = dict(cfg)
    base = str(cfg.get('jobs_url', '')).rstrip('/')
    url = urlsplit(base)
    if url.scheme not in ('http', 'https') or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('plain jobs URL without credentials/query required')
    cfg['jobs_url'] = base
    for key, default, cap in (('readiness_seconds', 600, 600), ('job_wait_seconds', 600, 600),
                              ('job_poll_seconds', 2, 60), ('timeout', 60, 60)):
        value = float(cfg.get(key, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError('finite positive transport bounds required')
        cfg[key] = min(value, cap)
    identity = {k: cfg.get(k) for k in ('jobs_url', 'model', 'readiness_seconds',
                'job_wait_seconds', 'job_poll_seconds', 'timeout')}
    files = [Path(__file__), Path(sys.modules[complete_job.__module__].__file__),
             Path(sys.modules[ReadinessGate.__module__].__file__), Path(token_budget.__file__)]
    runtime = {'python': sys.version, 'platform': platform.platform(),
               'code': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
               'counter': token_budget.counter_identity()}
    names, ids, entries = set(), set(), []
    for job in jobs:
        if (not isinstance(job, dict) or not {'name', 'payload', 'validation_job'} <= set(job)
                or set(job) - {'name', 'payload', 'validation_job', 'expected'}):
            raise ValueError('job keys must be name, payload, validation_job, optional expected')
        name, payload = job['name'], job['payload']
        if not isinstance(name, str) or not name or name in names or not isinstance(payload, dict):
            raise ValueError('unique nonempty names and object payloads required')
        if payload.get('max_tokens') != MAX_OUTPUT or type(payload.get('max_tokens')) is not int:
            raise ValueError('output cap must be 800')
        jid = payload_digest(payload)
        reserve = token_budget.input_reservation(payload)
        if reserve > MAX_INPUT or jid in ids:
            raise ValueError('input ceiling or duplicate payload')
        names.add(name)
        ids.add(jid)
        entries.append(dict(job, job_id=jid, input_reservation=reserve))
    if selected_names is None:
        selected = names
    else:
        if (not isinstance(selected_names, (list, tuple, set, frozenset)) or
                any(not isinstance(n, str) for n in selected_names)):
            raise ValueError('selected_names must be a collection of job names')
        selected = set(selected_names)
        if len(selected) != len(selected_names) or not selected <= names:
            raise ValueError('selected_names must be unique listed names')
    selected_entries = [e for e in entries if e['name'] in selected]
    binding = {'version': 1, 'jobs': entries, 'config': identity, 'runtime': runtime,
               'limits': [MAX_POSTS, MAX_INPUT, MAX_OUTPUT, MAX_TOTAL]}
    binding_sha = payload_digest(binding)
    root = Path(root).resolve()
    with _lock(root):
        binding_path = root / 'binding.json'
        if binding_path.exists():
            if _load(binding_path) != binding:
                raise ValueError('exact job list/config/code/runtime binding changed')
        else:
            if any(p.name != 'lock' for p in root.iterdir()):
                raise ValueError('unbound existing transport output is read-only')
            _write(binding_path, binding, immutable=True)

        def records():
            intents, receipts = {}, {}
            for path in sorted((root / 'intents').glob('*.json')):
                row = _load(path)
                _verify_record(row)
                jid = path.stem
                if jid not in ids or row.get('binding_sha256') != binding_sha or row.get('job_id') != jid:
                    raise ValueError('intent binding mismatch')
                intents[jid] = row
            for entry in entries:
                jid = entry['job_id']
                for path in sorted((root / 'receipts' / jid).glob('*.json')):
                    row = _load(path)
                    _verify_record(row)
                    if row.get('binding_sha256') != binding_sha or row.get('job_id') != jid:
                        raise ValueError('receipt binding mismatch')
                    if 'raw_response' in row and row.get('usage') != _usage(row['raw_response']):
                        raise ValueError('receipt usage mismatch')
                    receipts[jid] = row
            return intents, receipts

        def checkpoint(reason=None):
            intents, receipts = records()  # Also recovers orphan receipts before ledger.
            observed = set(intents) | {jid for jid, r in receipts.items() if r.get('observed_remote', True)}
            known = [r['usage'] for r in receipts.values() if r.get('usage') is not None]
            unknown = sum(receipts.get(jid, {}).get('usage') is None for jid in observed)
            totals = {k: sum(u[k] for u in known) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
            reserve = sum(e['input_reservation'] + MAX_OUTPUT for e in entries if e['job_id'] in observed)
            violation = (len(intents) > MAX_POSTS or reserve > MAX_TOTAL or totals['total_tokens'] > MAX_TOTAL or
                         any(u['input_tokens'] > MAX_INPUT or u['output_tokens'] > MAX_OUTPUT for u in known))
            rows = [{'name': e['name'], 'job_id': e['job_id'],
                     'status': receipts.get(e['job_id'], {}).get('status', 'pending'),
                     'usage': receipts.get(e['job_id'], {}).get('usage')} for e in entries]
            complete = all(r['status'] == 'completed' for r in rows if r['name'] in selected) and not unknown and not violation
            report = {'status': 'complete' if complete else 'partial', 'reason': reason,
                      'binding_sha256': binding_sha, 'rows': [r for r in rows if r['name'] in selected],
                      'selected_names': [e['name'] for e in selected_entries], 'receipts': receipts,
                      'workload_status': 'complete' if all(r['status'] == 'completed' for r in rows) and not unknown and not violation else 'partial',
                      'POST_attempts': len(intents),
                      'reserved_tokens': reserve, 'actual_usage': totals, 'unknown_usage_count': unknown,
                      'planned_reserved_tokens': sum(e['input_reservation'] + MAX_OUTPUT for e in entries),
                      'known_usage_count': len(known),
                      'budget_violation': violation, 'semantic_quality': 'not_assessed',
                      'execute': bool(execute)}
            _write(root / 'ledger.json', {'binding_sha256': binding_sha, 'attempts': list(intents.values()),
                                         'receipts': receipts})
            _write(root / 'report.json', report)
            return report

        report = checkpoint()
        if not execute or report['status'] == 'complete':
            return report
        if not isinstance(cfg.get('token'), str) or not cfg['token']:
            raise ValueError('execution requires token')
        gate = ReadinessGate(cfg, opener, clock, sleep,
                             lambda row: _write(root / 'readiness.json', row))
        gate.warmup(True)
        if gate.snapshot()['status'] != 'ready':
            return checkpoint('readiness')
        for entry in selected_entries:
            jid = entry['job_id']
            intents, receipts = records()
            if receipts.get(jid, {}).get('status') == 'completed':
                continue
            initial_missing = False

            def audit(req, **kwargs):
                nonlocal initial_missing
                method = req.get_method()
                if method == 'POST':
                    wire = json.loads(req.data)
                    current = checkpoint()
                    intents_now, receipts_now = records()
                    if wire != {'job_id': jid, 'payload': entry['payload']}:
                        raise ValueError('unlisted dispatch')
                    if jid in intents_now or receipts_now.get(jid, {}).get('observed_remote', False):
                        raise ValueError('existing job is retrieval-only, including 404')
                    if not initial_missing or gate.snapshot()['status'] != 'ready':
                        raise ValueError('POST requires definitive GET 404 and readiness')
                    reserve = entry['input_reservation'] + MAX_OUTPUT
                    if (current['unknown_usage_count'] or current['budget_violation'] or
                        current['POST_attempts'] >= MAX_POSTS or
                        current['reserved_tokens'] + reserve > MAX_TOTAL or
                        current['actual_usage']['total_tokens'] + reserve > MAX_TOTAL):
                        raise ValueError('POST blocked by cumulative budget/unknown usage')
                    _write(root / 'intents' / (jid + '.json'),
                           _seal({'job_id': jid, 'binding_sha256': binding_sha,
                                  'reserved_tokens': reserve, 'started_at_unix': time.time()}), immutable=True)
                try:
                    return opener(req, **kwargs)
                except HTTPError as exc:
                    if method == 'GET' and exc.code == 404:
                        initial_missing = True
                    raise

            started = clock()
            try:
                body, trace = complete_job(cfg, entry['payload'], opener=audit, clock=clock, sleep=sleep)
                receipt = {'raw_response': body, 'usage': _usage(body), 'trace': trace, 'status': 'completed'}
            except Exception as exc:
                receipt = {'usage': None, 'trace': exc.trace if isinstance(exc, JobTransportError) else None,
                           'status': 'partial', 'error_type': type(exc).__name__}
            receipt.update(job_id=jid, binding_sha256=binding_sha,
                           observed_remote=(jid in records()[0] or receipt['status'] == 'completed' or
                                            not initial_missing),
                           latency_ms=round((clock() - started) * 1000, 3))
            _write(root / 'receipts' / jid / (str(time.time_ns()) + '.json'), _seal(receipt), immutable=True)
            report = checkpoint()
            if receipt['status'] != 'completed' or report['unknown_usage_count'] or report['budget_violation']:
                return checkpoint('retrieval_pending_or_usage_blocked')
        return checkpoint()
