"""Experimental bounded, single-container durable queue; no backend retries.

Client identity: sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest().
"""

import asyncio
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
                 backend_timeout=1800, max_body_bytes=4 * 1024 * 1024,
                 concurrency=1, server_concurrency=None):
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

    def unavailable(self):
        return self.poisoned or self.backend_uncertain or self.stop_event.is_set()

    def benchmark_info(self):
        # Configuration evidence only; live scheduler evidence stays in the
        # existing exclusive diagnostics route. No inference reservation here.
        with STORE_MUTEX:
            return {"experiment": "au-concurrency-v1",
                    "app": "coliee-qwen35-9b-concurrency",
                    "gateway_concurrency": self.concurrency,
                    "server_concurrency": self.server_concurrency,
                    "cuda_graph_max_bs": self.server_concurrency,
                    "max_containers": 1, "model": "Qwen/Qwen3.5-9B",
                    "model_revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
                    "gpu": "L40S:1", "context_length": 12288,
                    "cpu": 4, "memory_mb": 16384,
                    "max_total_tokens": 12288,
                    "job_volume": "coliee-qwen35-9b-concurrency-jobs",
                    "job_store_subdir": f"c{self.concurrency}",
                    "backend_retry": False, "exclusive_probes": True,
                    "configuration_evidence": "configured_not_live_scheduler",
                    "ready": not self.unavailable(), "poisoned": self.poisoned,
                    "stopping": self.stop_event.is_set(),
                    "backend_outcome_unknown": self.backend_uncertain}

    def path(self, job_id):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise HTTPException(400, "job_id must be 64 lowercase hex characters")
        return self.root / (job_id + ".json")

    def read(self, job_id):
        path = self.path(job_id)
        if not path.exists():
            raise HTTPException(404, "Unknown job")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["job_id"] != job_id or payload_job_id(record["payload"]) != job_id:
            raise ValueError("Invalid durable record identity")
        return record

    def persist(self, record):
        # Caller holds STORE_MUTEX through both replace and Volume commit.
        path = self.path(record["job_id"])
        temporary = path.with_suffix(".tmp")
        try:
            data = canonical_payload(record)
            with temporary.open("wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            self.commit()
        except Exception:
            # Durability is unknown: refuse admission/dispatch until restart.
            self.poisoned = True
            raise

    @staticmethod
    def public(record):
        result = {key: value for key, value in record.items() if key != "payload"}
        result["payload_sha256"] = record["job_id"]
        return result

    def submit(self, job_id, payload, *, exclusive=False):
        self.path(job_id)
        if not isinstance(payload, dict) or payload.get("stream") not in (None, False):
            raise HTTPException(400, "payload must be a non-streaming chat completion object")
        try:
            encoded = canonical_payload(payload)
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, "Invalid JSON payload") from None
        if hashlib.sha256(encoded).hexdigest() != job_id:
            raise HTTPException(409, "job_id does not match canonical payload")
        with STORE_MUTEX:
            if self.unavailable():
                raise HTTPException(503, "Gateway unavailable; recover after restart")
            if self.path(job_id).exists():
                existing = self.read(job_id)
                if canonical_payload(existing["payload"]) != encoded:
                    raise HTTPException(409, "Conflicting payload")
                if exclusive and existing["status"] == "queued":
                    existing.update(inference_mode="exclusive", updated_at=now())
                    self.persist(existing)
                return self.public(existing)
            record = {"job_id": job_id, "payload_sha256": job_id,
                      "payload": payload, "status": "queued",
                      "created_at": now(), "updated_at": now()}
            if exclusive:
                record["inference_mode"] = "exclusive"
            self.persist(record)
            self.wake.set()
            return self.public(record)

    def recover(self):
        with STORE_MUTEX:
            self.root.mkdir(parents=True, exist_ok=True)
            for path in sorted(self.root.glob("*.json")):
                record = self.read(path.stem)
                if record["status"] == "running":
                    record.update(status="interrupted", updated_at=now(), finished_at=now(),
                                  error={"phase": "restart", "kind": "unknown_inference_outcome"})
                    self.persist(record)

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

    def run(self):
        while not self.stop_event.is_set():
            if self.unavailable():
                return
            self.wake.clear()
            try:
                # Idle scans must not block synchronous probes or diagnostics.
                with STORE_MUTEX:
                    if self.stop_event.is_set() or self.poisoned or self.backend_uncertain:
                        return
                    queued = [self.read(p.stem) for p in sorted(self.root.glob("*.json"))]
                    queued = [r for r in queued if r["status"] == "queued"]
                    candidate = min(queued, key=lambda r: (r["created_at"], r["job_id"])) if queued else None
                if candidate is not None:
                    # Never wait for inference while holding the store lock.
                    exclusive = candidate.get("inference_mode") == "exclusive"
                    if not self.inference.acquire_job(self.unavailable, exclusive):
                        return
                    try:
                        with STORE_MUTEX:
                            if self.stop_event.is_set() or self.poisoned or self.backend_uncertain:
                                return
                            record = self.read(candidate["job_id"])
                            if record["status"] != "queued":
                                continue
                            if (record.get("inference_mode") == "exclusive") != exclusive:
                                continue  # Diagnostic admission upgraded a queued job.
                            record.update(status="running", started_at=now(), updated_at=now())
                            self.persist(record)  # Must succeed before dispatch.
                        self.execute(record)
                        continue
                    finally:
                        self.inference.release_job(exclusive)
            except Exception:
                # Never print exception messages, request data, or provider bodies.
                with STORE_MUTEX:
                    self.poisoned = True
                return
            self.wake.wait(1)

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

    async def body(self, request):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > self.max_body:
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
                    raise HTTPException(504, "Backend outcome unknown; restart required") from None
            finally:
                gateway.inference.release()
        return await asyncio.to_thread(proxy)

    return app
