"""Independent concurrency regressions for the durable AU job gateway."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

try:
    from knowledge_base.pipeline_v1.deployments.modal import job_gateway
except ModuleNotFoundError as error:
    if error.name not in {"fastapi", "starlette"}:
        raise
    # The worker tests do not exercise the web adapter; keep the suite offline.
    import sys
    import types

    class _HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    fastapi_stub = types.ModuleType("fastapi")
    fastapi_stub.FastAPI = object
    fastapi_stub.HTTPException = _HTTPException
    fastapi_stub.Request = object
    responses_stub = types.ModuleType("fastapi.responses")
    responses_stub.JSONResponse = object
    responses_stub.Response = object
    fastapi_stub.responses = responses_stub
    sys.modules.setdefault("fastapi", fastapi_stub)
    sys.modules.setdefault("fastapi.responses", responses_stub)
    from knowledge_base.pipeline_v1.deployments.modal import job_gateway


def _payload(text="job payload"):
    return {"model": "test-model", "messages": [{"role": "user", "content": text}]}


class GatewayIdleLockRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.gateway = job_gateway.JobGateway(Path(self.temp.name) / "jobs", lambda: None)
        self.gateway.recover()

    def _wait(self, event, message):
        self.assertTrue(event.wait(2), message)

    def test_idle_scan_runs_without_inference_mutex_and_rechecks_stale_candidate(self):
        payload = _payload("stale before dispatch")
        job_id = job_gateway.payload_job_id(payload)
        self.gateway.submit(job_id, payload)
        scanned = threading.Event()
        original_read = self.gateway.read

        def observed_read(candidate_id):
            if not scanned.is_set():
                scanned.set()
            return original_read(candidate_id)

        calls = []
        self.gateway.read = observed_read
        self.gateway.call_backend = lambda value: calls.append(value) or (200, b"{}")
        job_gateway.INFERENCE_MUTEX.acquire()
        self.gateway.start()
        try:
            self._wait(scanned, "worker did not scan the queued record while inference was occupied")
            # Simulate another safe state transition after candidate scan but before lock acquisition.
            with job_gateway.STORE_MUTEX:
                record = original_read(job_id)
                record.update(status="completed", response={"choices": []},
                              response_sha256=job_gateway.payload_job_id({"choices": []}))
                self.gateway.persist(record)
        finally:
            job_gateway.INFERENCE_MUTEX.release()

        try:
            time.sleep(0.05)
            self.assertEqual(calls, [])
            self.assertEqual(original_read(job_id)["status"], "completed")
            self.assertFalse(self.gateway.poisoned)
        finally:
            self.gateway.stop()

    def test_real_dispatch_holds_mutex_and_duplicate_submit_dispatches_once(self):
        payload = _payload("dispatch once")
        job_id = job_gateway.payload_job_id(payload)
        first = self.gateway.submit(job_id, payload)
        duplicate = self.gateway.submit(job_id, payload)
        calls = []
        mutex_was_held = []

        def dispatch(value):
            calls.append(value)
            acquired = job_gateway.INFERENCE_MUTEX.acquire(blocking=False)
            mutex_was_held.append(not acquired)
            if acquired:
                job_gateway.INFERENCE_MUTEX.release()
            return 200, json.dumps({"choices": [], "usage": {}}).encode()

        self.gateway.call_backend = dispatch
        self.gateway.start()
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and self.gateway.read(job_id)["status"] != "completed":
                time.sleep(0.005)
            record = self.gateway.read(job_id)
            self.assertEqual(record["status"], "completed")
            self.assertEqual(first["status"], "queued")
            self.assertEqual(duplicate["status"], "queued")
            self.assertEqual(len(calls), 1)
            self.assertEqual(mutex_was_held, [True])
        finally:
            self.gateway.stop()


if __name__ == "__main__":
    unittest.main()
