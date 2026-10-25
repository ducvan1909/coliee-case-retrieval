"""Offline contract tests for the durable AU jobs client."""

from __future__ import annotations

import hashlib
import json
import unittest
from urllib.error import HTTPError, URLError

from knowledge_base.pipeline_v1.au_compact import jobs_client


JOB_ID = "au-job-2026-001"
SOURCE_HASH = "source-sha256-abc"
RESULT = {"aus": [{"text": "A court must give reasons."}]}


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _Response:
    def __init__(self, value: dict):
        self._body = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def _cfg(**overrides):
    values = {
        "jobs_url": "https://jobs.invalid/v1/jobs",
        "token": "test-token-never-logged",
        "timeout": 1,
        "job_wait_seconds": 0.05,
        "job_poll_seconds": 0.01,
    }
    return {**values, **overrides}


def _completed(job_id, result=RESULT):
    return {
        "job_id": job_id,
        "payload_sha256": job_id,
        "status": "completed",
        "response": result,
        "response_sha256": _canonical_digest(result),
    }


def _request_parts(request):
    return request.full_url, request.get_method(), request.data


class JobsClientTests(unittest.TestCase):
    def test_post_timeout_recovers_by_get_using_the_same_job_id(self):
        calls = []
        payload = {"source_hash": SOURCE_HASH, "document": "payload"}
        job_id = _canonical_digest(payload)

        def opener(request, **kwargs):
            calls.append(request)
            if len(calls) == 1:
                raise HTTPError(request.full_url, 404, "missing", {}, None)
            if request.get_method() == "POST":
                raise TimeoutError("POST response timed out")
            return _Response(_completed(job_id=job_id))

        body, trace = jobs_client.complete_job(
            _cfg(), payload,
            opener=opener,
        )

        self.assertEqual(body, RESULT)
        self.assertEqual(len(calls), 3)
        missing_url, missing_method, _ = _request_parts(calls[0])
        post_url, post_method, post_data = _request_parts(calls[1])
        get_url, get_method, _ = _request_parts(calls[2])
        self.assertEqual(missing_method, "GET")
        self.assertTrue(missing_url.rstrip("/").endswith(job_id))
        self.assertEqual(post_method, "POST")
        self.assertEqual(get_method, "GET")
        self.assertTrue(get_url.rstrip("/").endswith(job_id))
        self.assertEqual(post_url.rstrip("/"), _cfg()["jobs_url"])
        self.assertEqual(json.loads(post_data), {"job_id": job_id, "payload": payload})
        self.assertIn(job_id, repr(trace))
        self.assertNotIn("document", repr(trace))
        self.assertNotIn(_cfg()["token"], repr(trace))

    def test_completed_result_is_returned_only_after_digest_validation(self):
        payload = {"source_hash": SOURCE_HASH, "document": "payload"}
        job_id = _canonical_digest(payload)

        def opener(request, **kwargs):
            return _Response(_completed(job_id=job_id))

        body, _trace = jobs_client.complete_job(
            _cfg(), payload,
            opener=opener,
        )

        self.assertEqual(body, RESULT)

    def test_completed_result_with_wrong_digest_is_rejected(self):
        payload = {"source_hash": SOURCE_HASH, "document": "payload"}
        response = _completed(job_id=_canonical_digest(payload))
        response["response_sha256"] = "0" * 64

        def opener(request, **kwargs):
            return _Response(response)

        with self.assertRaises(jobs_client.JobTransportError):
            jobs_client.complete_job(
                _cfg(), payload,
                opener=opener,
            )

    def test_job_timeout_reports_identity_and_retryable_diagnostic(self):
        calls = []
        payload = {"source_hash": SOURCE_HASH, "document": "payload"}
        job_id = _canonical_digest(payload)
        current = [0.0]

        def opener(request, **kwargs):
            calls.append(request)
            if request.get_method() == "GET" and len(calls) == 1:
                raise HTTPError(request.full_url, 404, "missing", {}, None)
            if request.get_method() == "POST":
                return _Response({"job_id": job_id, "payload_sha256": job_id, "status": "queued"})
            return _Response({"job_id": job_id, "payload_sha256": job_id, "status": "running"})

        def sleep(seconds):
            current[0] += seconds

        cfg = _cfg(job_wait_seconds=0.02, job_poll_seconds=0.02)
        with self.assertRaises(jobs_client.JobTransportError) as raised:
            jobs_client.complete_job(
                cfg, payload, opener=opener, clock=lambda: current[0], sleep=sleep,
            )

        diagnostic = json.dumps(raised.exception.trace, ensure_ascii=False, default=str)
        self.assertIn(job_id, diagnostic)
        self.assertTrue(raised.exception.trace["failure_diagnostic"]["retryable"])
        self.assertLessEqual(len(calls), 3)

    def test_transport_error_does_not_trigger_payload_or_model_retry(self):
        calls = []
        payload = {"source_hash": SOURCE_HASH, "document": "payload"}
        current = [0.0]

        def opener(request, **kwargs):
            calls.append(request)
            if request.get_method() == "GET":
                raise HTTPError(request.full_url, 404, "missing", {}, None)
            raise URLError("temporary network failure")

        def sleep(seconds):
            current[0] += seconds

        with self.assertRaises(jobs_client.JobTransportError):
            jobs_client.complete_job(
                _cfg(job_wait_seconds=0.02, job_poll_seconds=0.01), payload,
                opener=opener, clock=lambda: current[0], sleep=sleep,
            )

        self.assertEqual(sum(request.get_method() == "POST" for request in calls), 1)
