"""Durability and dispatch contract tests for the AU job gateway."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
import tempfile
import time
import sys
import types
import unittest
from urllib.error import HTTPError

try:
    from fastapi import HTTPException
except ModuleNotFoundError:
    # Gateway lifecycle tests use JobGateway directly; keep them runnable in
    # the repo's minimal venv without installing the deployment-only web stack.
    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    fastapi_stub = types.ModuleType("fastapi")
    fastapi_stub.HTTPException = HTTPException
    fastapi_stub.FastAPI = object
    fastapi_stub.Request = object
    responses_stub = types.ModuleType("fastapi.responses")
    responses_stub.JSONResponse = object
    responses_stub.Response = object
    fastapi_stub.responses = responses_stub
    sys.modules.setdefault("fastapi", fastapi_stub)
    sys.modules.setdefault("fastapi.responses", responses_stub)

from knowledge_base.pipeline_v1.deployments.modal import job_gateway


def _payload(text="private source text"):
    return {"model": "mock-model", "messages": [
        {"role": "user", "content": text},
    ]}


def _mock_success(gateway, result=None, *, before_dispatch=None):
    if result is None:
        result = {"choices": [{"message": {"content": "mock AU"}}],
                  "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
    calls = []

    def call_backend(payload):
        calls.append(payload)
        if before_dispatch is not None:
            before_dispatch(payload)
        return 200, json.dumps(result).encode("utf-8")

    gateway.call_backend = call_backend
    return calls, result


class JobGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_gateway(self, *, commit=None):
        root = Path(self.temp_dir.name) / "jobs"
        commits = []

        def do_commit():
            commits.append(True)
            if commit is not None:
                commit()

        gateway = job_gateway.JobGateway(root, do_commit)
        gateway.recover()
        return gateway, commits

    def wait_for_status(self, gateway, job_id, status, timeout=2):
        deadline = time.monotonic() + timeout
        # Match the production GET route: serialize reads with atomic replace.
        # Windows can deny an unlocked read while the worker replaces the file.
        with job_gateway.STORE_MUTEX:
            record = gateway.read(job_id)
        while time.monotonic() < deadline:
            with job_gateway.STORE_MUTEX:
                record = gateway.read(job_id)
            if record["status"] == status:
                return record
            time.sleep(0.005)
        self.fail(f"job {job_id} did not reach {status}; got {record['status']}")

    def test_duplicate_submission_dispatches_once_and_returns_saved_completion(self):
        gateway, _commits = self.make_gateway()
        payload = _payload()
        job_id = job_gateway.payload_job_id(payload)
        calls, _result = _mock_success(gateway)
        gateway.start()
        try:
            first = gateway.submit(job_id, payload)
            completed = self.wait_for_status(gateway, job_id, "completed")
            duplicate = gateway.submit(job_id, payload)

            self.assertEqual(first["status"], "queued")
            self.assertEqual(duplicate["status"], "completed")
            self.assertEqual(len(calls), 1)
            self.assertNotIn("payload", duplicate)
            self.assertEqual(duplicate["payload_sha256"], job_id)
            self.assertEqual(duplicate["response"], completed["response"])
            self.assertEqual(duplicate["response_sha256"],
                             job_gateway.payload_job_id(completed["response"]))
        finally:
            gateway.stop()

    def test_submission_rejects_job_id_that_does_not_match_payload(self):
        gateway, _commits = self.make_gateway()
        payload = _payload("first payload")
        job_id = job_gateway.payload_job_id(payload)
        gateway.submit(job_id, payload)

        with self.assertRaises(HTTPException) as raised:
            gateway.submit(job_id, _payload("conflicting payload"))
        self.assertEqual(raised.exception.status_code, 409)

    def test_completed_job_is_recovered_from_durable_store_after_restart(self):
        gateway, _commits = self.make_gateway()
        payload = _payload()
        job_id = job_gateway.payload_job_id(payload)
        _mock_success(gateway)
        gateway.submit(job_id, payload)
        record = gateway.read(job_id)
        record.update(status="running", started_at=job_gateway.now())
        gateway.persist(record)
        gateway.execute(record)

        restarted, _ = self.make_gateway()
        recovered = restarted.read(job_id)

        self.assertEqual(recovered["status"], "completed")
        self.assertTrue(recovered["response"])
        self.assertEqual(restarted.public(recovered)["response_sha256"],
                         job_gateway.payload_job_id(recovered["response"]))

    def test_running_job_becomes_interrupted_on_restart_and_is_never_redispatched(self):
        gateway, _commits = self.make_gateway()
        payload = _payload()
        job_id = job_gateway.payload_job_id(payload)
        gateway.submit(job_id, payload)
        record = gateway.read(job_id)
        record.update(status="running", started_at=job_gateway.now())
        gateway.persist(record)

        restarted, _ = self.make_gateway()
        calls, _ = _mock_success(restarted)
        restarted.start()
        try:
            interrupted = restarted.read(job_id)
            self.assertEqual(interrupted["status"], "interrupted")
            self.assertEqual(interrupted["error"]["kind"], "unknown_inference_outcome")
            self.assertEqual(calls, [])
        finally:
            restarted.stop()

    def test_queued_job_resumes_after_restart(self):
        gateway, _commits = self.make_gateway()
        payload = _payload()
        job_id = job_gateway.payload_job_id(payload)
        gateway.submit(job_id, payload)
        restarted, _ = self.make_gateway()
        calls, _ = _mock_success(restarted)
        restarted.start()
        try:
            completed = self.wait_for_status(restarted, job_id, "completed")
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(len(calls), 1)
        finally:
            restarted.stop()

    def test_failed_provider_job_is_persisted_locally_without_retry(self):
        gateway, _commits = self.make_gateway()
        payload = _payload()
        job_id = job_gateway.payload_job_id(payload)
        gateway.submit(job_id, payload)
        calls = []

        def failed_backend(_payload):
            calls.append(True)
            raise HTTPError("http://backend.invalid", 500, "private provider detail", {},
                            io.BytesIO(b"private provider detail"))

        gateway.call_backend = failed_backend
        record = gateway.read(job_id)
        record.update(status="running", started_at=job_gateway.now())
        gateway.persist(record)
        gateway.execute(record)

        failed = gateway.read(job_id)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"],
                         {"phase": "backend_dispatch", "kind": "backend_http_error"})
        self.assertEqual(calls, [True])

    def test_queued_and_running_states_are_committed_before_backend_dispatch(self):
        root = Path(self.temp_dir.name) / "jobs"
        states_seen_at_commit = []
        job_id_holder = []

        def commit():
            if job_id_holder:
                path = root / (job_id_holder[0] + ".json")
                if path.exists():
                    states_seen_at_commit.append(
                        json.loads(path.read_text(encoding="utf-8"))["status"]
                    )

        gateway, _ = self.make_gateway(commit=commit)
        payload = _payload()
        job_id = job_gateway.payload_job_id(payload)
        job_id_holder.append(job_id)
        dispatch_states = []

        def before_dispatch(_payload):
            dispatch_states.append(gateway.read(job_id)["status"])

        calls, _ = _mock_success(gateway, before_dispatch=before_dispatch)
        gateway.start()
        try:
            gateway.submit(job_id, payload)
            self.wait_for_status(gateway, job_id, "completed")
        finally:
            gateway.stop()

        self.assertIn("queued", states_seen_at_commit)
        self.assertIn("running", states_seen_at_commit)
        self.assertEqual(dispatch_states, ["running"])
        self.assertEqual(len(calls), 1)

    def test_payload_and_backend_failure_details_never_appear_in_logs(self):
        gateway, _commits = self.make_gateway()
        secret = "CONFIDENTIAL_SOURCE_DO_NOT_LOG"
        payload = _payload(secret)
        job_id = job_gateway.payload_job_id(payload)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger()
        logger.addHandler(handler)
        try:
            gateway.submit(job_id, payload)
            record = gateway.read(job_id)
            record.update(status="running", started_at=job_gateway.now())
            gateway.persist(record)

            def backend_with_secret_error(_payload):
                raise RuntimeError(secret)

            gateway.call_backend = backend_with_secret_error
            gateway.execute(record)
        finally:
            logger.removeHandler(handler)
            handler.close()

        self.assertNotIn(secret, stream.getvalue())
        self.assertNotIn("Bearer", stream.getvalue())
        self.assertNotIn(secret, json.dumps(gateway.public(gateway.read(job_id))))


if __name__ == "__main__":
    unittest.main()
