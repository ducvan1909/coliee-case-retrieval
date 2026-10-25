"""Durable job transport; a poll never launches another model request."""
from __future__ import annotations

import hashlib
import json
import time
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


def payload_digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class JobTransportError(ValueError):
    def __init__(self, trace):
        self.trace = trace
        super().__init__(json.dumps(trace))


def complete_job(cfg, payload, opener=urlrequest.urlopen, *, clock=time.monotonic,
                 sleep=time.sleep):
    """Submit once, recover a lost acknowledgement by GET, then poll the same ID.

    A deadline ends waiting, not the server job. Repeating this call with the
    identical payload retrieves the existing job. No synchronous fallback.
    """
    base = str(cfg.get("jobs_url", "")).rstrip("/")
    if not base:
        raise ValueError("jobs transport requires jobs_url")
    job_id = payload_digest(payload)
    started = clock()
    wait = float(cfg.get("job_wait_seconds", 1800))
    interval = float(cfg.get("job_poll_seconds", 2))
    if wait <= 0 or interval <= 0:
        raise ValueError("job wait/poll must be positive")
    trace = {"transport": "jobs", "job_id": job_id, "payload_sha256": job_id,
             "polls": 0, "submit_attempts": 0, "events": [], "started_at_unix": time.time()}
    headers = {"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"}

    def fail(kind, **fields):
        trace.update(latency_ms=round((clock() - started) * 1000, 3),
                     finished_at_unix=time.time(),
                     failure_diagnostic={"kind": kind, **fields})
        raise JobTransportError(trace)

    def http(method, suffix, value=None):
        remaining = wait - (clock() - started)
        if remaining <= 0:
            fail("job_wait_timeout", retryable=True, outcome="server_job_may_continue")
        req = urlrequest.Request(base + suffix,
                                 data=None if value is None else json.dumps(value).encode(),
                                 headers=headers, method=method)
        timeout = max(0.001, min(float(cfg.get("timeout", 60)), remaining))
        try:
            with opener(req, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            if not isinstance(body, dict):
                fail("job_invalid_envelope", retryable=False)
            return body
        except HTTPError as exc:
            if exc.code in {404, 429, 502, 503, 504}:
                trace["events"].append({"method": method, "http_status": exc.code})
                return None
            fail("job_http", http_status=exc.code, retryable=False)
        except (URLError, TimeoutError, OSError) as exc:
            trace["events"].append({"method": method, "error": type(exc).__name__})
            return None
        except JobTransportError:
            raise
        except (ValueError, UnicodeError):
            fail("job_invalid_envelope", retryable=False)

    # GET first allows process resume without even resubmitting a finished job.
    trace["polls"] += 1
    row = http("GET", "/" + job_id)
    if row is None:
        trace["submit_attempts"] += 1
        row = http("POST", "", {"job_id": job_id, "payload": payload})
    while True:
        if row is not None:
            if row.get("job_id") != job_id or row.get("payload_sha256") != job_id:
                fail("job_identity_mismatch", retryable=False)
            status = row.get("status")
            trace["job_status"] = status
            if status == "completed":
                body = row.get("response")
                if not isinstance(body, dict) or row.get("response_sha256") != payload_digest(body):
                    fail("job_result_digest_mismatch", retryable=False)
                trace["latency_ms"] = round((clock() - started) * 1000, 3)
                trace["finished_at_unix"] = time.time()
                trace["server_timing"] = {k: row.get(k) for k in
                                           ("created_at", "started_at", "finished_at", "inference_seconds")}
                return body, trace
            if status in {"failed", "interrupted"}:
                fail("job_" + status, retryable=False,
                     outcome="explicit_review_required", server_error=row.get("error"))
            if status not in {"queued", "running"}:
                fail("job_invalid_status", retryable=False)
        remaining = wait - (clock() - started)
        if remaining <= 0:
            fail("job_wait_timeout", retryable=True, outcome="server_job_may_continue")
        sleep(min(interval, remaining))
        trace["polls"] += 1
        row = http("GET", "/" + job_id)

