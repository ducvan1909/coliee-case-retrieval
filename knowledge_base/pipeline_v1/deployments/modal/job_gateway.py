"""Private, single-container durable queue; no backend retries.

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
INFERENCE_MUTEX = threading.Lock()
JOB_ID = re.compile(r"[0-9a-f]{64}\Z")


def canonical_payload(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def payload_job_id(payload):
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class JobGateway:
    def __init__(self, store_root, commit, backend_url="http://127.0.0.1:8001/v1/chat/completions",
                 backend_timeout=1800, max_body_bytes=4 * 1024 * 1024):
        if not 0 < backend_timeout <= 1800 or max_body_bytes <= 0:
            raise ValueError("Invalid gateway limits")
        self.root = Path(store_root)
        self.commit = commit
        self.backend_url = backend_url
        self.timeout = backend_timeout
        self.max_body = max_body_bytes
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.poisoned = False
        self.backend_uncertain = False
        self.worker = None

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

    def submit(self, job_id, payload):
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
            if self.poisoned or self.stop_event.is_set():
                raise HTTPException(503, "Gateway unavailable; recover after restart")
            if self.path(job_id).exists():
                existing = self.read(job_id)
                if canonical_payload(existing["payload"]) != encoded:
                    raise HTTPException(409, "Conflicting payload")
                return self.public(existing)
            record = {"job_id": job_id, "payload_sha256": job_id,
                      "payload": payload, "status": "queued",
                      "created_at": now(), "updated_at": now()}
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
        self.recover()
        self.worker = threading.Thread(target=self.run, name="durable-job-worker", daemon=True)
        self.worker.start()

    def stop(self, grace_seconds=50):
        already_stopping = self.stop_event.is_set()
        self.stop_event.set()
        self.wake.set()
        if self.worker is not None and not already_stopping:
            self.worker.join(timeout=grace_seconds)
        # Do not declare a running request interrupted while it may still finish.
        # A killed container leaves running on disk; next startup reconciles it.

    def call_backend(self, payload):
        request = urllib.request.Request(self.backend_url, data=canonical_payload(payload),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.status, response.read()

    def run(self):
        while not self.stop_event.is_set():
            if self.poisoned or self.backend_uncertain:
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
                    with INFERENCE_MUTEX:
                        with STORE_MUTEX:
                            if self.stop_event.is_set() or self.poisoned or self.backend_uncertain:
                                return
                            record = self.read(candidate["job_id"])
                            if record["status"] != "queued":
                                continue
                            record.update(status="running", started_at=now(), updated_at=now())
                            self.persist(record)  # Must succeed before dispatch.
                        self.execute(record)
                        continue
            except Exception:
                # Never print exception messages, request data, or provider bodies.
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
            self.backend_uncertain = uncertain
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
            if not INFERENCE_MUTEX.acquire(blocking=False):
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
                INFERENCE_MUTEX.release()
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
            if not INFERENCE_MUTEX.acquire(blocking=False):
                raise HTTPException(409, "Inference busy")
            try:
                with STORE_MUTEX:
                    if gateway.poisoned or gateway.backend_uncertain or gateway.stop_event.is_set():
                        raise HTTPException(503, "Backend unavailable until restart")
                    original = gateway.read(PAYLOAD_SHA256)
                    if original["status"] not in ("completed", "failed", "interrupted"):
                        raise HTTPException(409, "Original job is not terminal")
                    return diagnostic_job(gateway.submit(payload_job_id(payload), payload))
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(503, "Durable store unavailable") from None
            finally:
                INFERENCE_MUTEX.release()
        return JSONResponse(await asyncio.to_thread(admit), status_code=202)

    @app.get("/health")
    async def health():
        return JSONResponse({"ready": not gateway.poisoned and not gateway.stop_event.is_set(),
                             "backend_outcome_unknown": gateway.backend_uncertain},
                            status_code=503 if gateway.poisoned or gateway.stop_event.is_set() else 200)

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
            if not INFERENCE_MUTEX.acquire(blocking=False):
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
                    gateway.backend_uncertain = True
                    raise HTTPException(504, "Backend outcome unknown; restart required") from None
            finally:
                INFERENCE_MUTEX.release()
        return await asyncio.to_thread(proxy)

    return app
