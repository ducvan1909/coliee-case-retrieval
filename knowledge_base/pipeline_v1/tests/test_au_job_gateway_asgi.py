"""ASGI route tests for the AU job gateway, using a mocked backend."""

from __future__ import annotations

import json
import inspect
import importlib.util
from pathlib import Path
import tempfile
import threading
import time
import unittest


_REQUIRED_ASGI_PACKAGES = ("fastapi", "httpx", "starlette")
_MISSING_ASGI_PACKAGES = tuple(
    name for name in _REQUIRED_ASGI_PACKAGES
    if importlib.util.find_spec(name) is None
)
_ASGI_IMPORT_ERROR = None
TestClient = None
starlette_routing = None
job_gateway = None

if not _MISSING_ASGI_PACKAGES:
    try:
        from fastapi.testclient import TestClient
        from starlette import routing as starlette_routing

        from knowledge_base.pipeline_v1.deployments.modal import job_gateway
    except ModuleNotFoundError as exc:
        _ASGI_IMPORT_ERROR = exc


def _bridge_fastapi_starlette_startup_args():
    """Bridge this machine's FastAPI 0.115 / Starlette 1.6 signature mismatch.

    The app uses a lifespan context manager, so the removed legacy startup
    lists are unused. Keep this shim in the test process only.
    """
    original = starlette_routing.Router.__init__
    if "on_startup" in inspect.signature(original).parameters:
        return

    def compatible_init(self, *args, on_startup=None, on_shutdown=None, **kwargs):
        return original(self, *args, **kwargs)

    starlette_routing.Router.__init__ = compatible_init


if TestClient is not None:
    _bridge_fastapi_starlette_startup_args()


def _payload(text="ASGI mock input"):
    return {
        "model": "mock-model",
        "messages": [{"role": "user", "content": text}],
    }


def _job_id(payload):
    return job_gateway.payload_job_id(payload)


@unittest.skipUnless(
    TestClient is not None,
    "ASGI tests require FastAPI, Starlette, and httpx"
    + (f"; import failed: {_ASGI_IMPORT_ERROR}" if _ASGI_IMPORT_ERROR else "")
    + (f"; missing: {', '.join(_MISSING_ASGI_PACKAGES)}" if _MISSING_ASGI_PACKAGES else ""),
)
class JobGatewayASGITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = job_gateway.create_app(
            Path(self.temp_dir.name) / "jobs",
            lambda: None,
            backend_url="http://backend.invalid/v1/chat/completions",
            backend_timeout=1,
        )
        # Starlette 1.6 expects this attribute; FastAPI 0.115.6 predates it.
        self.app.max_body_size = None
        self.gateway = self.app.state.gateway
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        # Unblock a mocked in-flight request before lifespan shutdown joins it.
        release = getattr(self, "release_backend", None)
        if release is not None:
            release.set()
        self.client.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def install_backend(self, callback):
        self.gateway.call_backend = callback

    def get_until(self, job_id, expected, timeout=2):
        deadline = time.monotonic() + timeout
        response = self.client.get(f"/v1/jobs/{job_id}")
        while time.monotonic() < deadline:
            self.assertEqual(response.status_code, 200, response.text)
            record = response.json()
            if record["status"] == expected:
                return record
            time.sleep(0.005)
            response = self.client.get(f"/v1/jobs/{job_id}")
        self.fail(f"job {job_id} did not reach {expected}; got {record['status']}")

    def test_get_missing_post_queued_completed_duplicate_and_digest(self):
        missing = self.client.get(f"/v1/jobs/{'a' * 64}")
        self.assertEqual(missing.status_code, 404)

        calls = []
        result = {
            "choices": [{"message": {"content": "mock AU"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }

        def backend(payload):
            calls.append(payload)
            return 200, json.dumps(result).encode("utf-8")

        self.install_backend(backend)
        payload = _payload()
        job_id = _job_id(payload)
        submitted = self.client.post(
            "/v1/jobs", json={"job_id": job_id, "payload": payload}
        )
        self.assertEqual(submitted.status_code, 202, submitted.text)
        self.assertEqual(submitted.json()["status"], "queued")

        completed = self.get_until(job_id, "completed")
        self.assertEqual(completed["payload_sha256"], job_id)
        self.assertEqual(completed["response"], result)
        self.assertEqual(
            completed["response_sha256"], job_gateway.payload_job_id(result)
        )
        self.assertNotIn("payload", completed)

        duplicate = self.client.post(
            "/v1/jobs", json={"job_id": job_id, "payload": payload}
        )
        self.assertEqual(duplicate.status_code, 202, duplicate.text)
        self.assertEqual(duplicate.json()["status"], "completed")
        self.assertEqual(len(calls), 1)

    def test_post_rejects_invalid_payload_digest(self):
        calls = []
        self.install_backend(lambda payload: calls.append(payload))
        response = self.client.post(
            "/v1/jobs",
            json={"job_id": "0" * 64, "payload": _payload("wrong digest")},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(calls, [])

    def test_get_remains_available_and_sync_route_returns_409_while_worker_runs(self):
        started = threading.Event()
        self.release_backend = threading.Event()
        calls = []
        result = {"choices": [{"message": {"content": "mock AU"}}]}

        def backend(payload):
            calls.append(payload)
            if payload == job_payload:
                started.set()
                if not self.release_backend.wait(2):
                    raise TimeoutError("test backend release timed out")
            return 200, json.dumps(result).encode("utf-8")

        self.install_backend(backend)
        job_payload = _payload("hold worker")
        job_id = _job_id(job_payload)
        submitted = self.client.post(
            "/v1/jobs", json={"job_id": job_id, "payload": job_payload}
        )
        self.assertEqual(submitted.status_code, 202, submitted.text)
        self.assertTrue(started.wait(1), "mock worker did not enter backend")
        try:
            running = self.client.get(f"/v1/jobs/{job_id}")
            self.assertEqual(running.status_code, 200, running.text)
            self.assertEqual(running.json()["status"], "running")

            busy = self.client.post("/v1/chat/completions", json=_payload("sync probe"))
            self.assertEqual(busy.status_code, 409, busy.text)
            self.assertEqual(len(calls), 1)
        finally:
            self.release_backend.set()
        self.get_until(job_id, "completed")

    def test_commit_failure_returns_503_and_never_dispatches(self):
        calls = []

        def fail_commit():
            raise OSError("mock durable commit failure")

        self.gateway.commit = fail_commit
        self.install_backend(lambda payload: calls.append(payload))
        payload = _payload("commit must precede dispatch")
        response = self.client.post(
            "/v1/jobs", json={"job_id": _job_id(payload), "payload": payload}
        )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(calls, [])
        self.assertTrue(self.gateway.poisoned)

    def test_backend_timeout_interrupts_current_job_and_leaves_next_queued(self):
        started = threading.Event()
        self.release_backend = threading.Event()
        calls = []

        def backend(payload):
            calls.append(payload)
            started.set()
            if not self.release_backend.wait(2):
                raise TimeoutError("test backend release timed out")
            raise TimeoutError("mock backend timed out")

        self.install_backend(backend)
        first_payload = _payload("first times out")
        first_id = _job_id(first_payload)
        first = self.client.post(
            "/v1/jobs", json={"job_id": first_id, "payload": first_payload}
        )
        self.assertEqual(first.status_code, 202, first.text)
        self.assertTrue(started.wait(1), "mock worker did not enter backend")

        second_payload = _payload("must remain queued")
        second_id = _job_id(second_payload)
        second = self.client.post(
            "/v1/jobs", json={"job_id": second_id, "payload": second_payload}
        )
        self.assertEqual(second.status_code, 202, second.text)
        self.assertEqual(second.json()["status"], "queued")
        self.release_backend.set()

        first_record = self.get_until(first_id, "interrupted")
        self.assertTrue(first_record["error"]["outcome_unknown"])
        deadline = time.monotonic() + 1
        second_record = self.client.get(f"/v1/jobs/{second_id}").json()
        while time.monotonic() < deadline and second_record["status"] != "queued":
            time.sleep(0.005)
            second_record = self.client.get(f"/v1/jobs/{second_id}").json()
        self.assertEqual(second_record["status"], "queued")
        self.assertEqual(calls, [first_payload])


if __name__ == "__main__":
    unittest.main()
