"""Offline recovery and migration contract tests for the paired AU runner."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError


class _Response:
    def __init__(self, value):
        self.raw = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.raw


class _FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def _http_error(request, status, body):
    from io import BytesIO
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return HTTPError(request.full_url, status, "fixture", {}, BytesIO(raw))


class RecoveryTransportTests(unittest.TestCase):
    def setUp(self):
        from knowledge_base.pipeline_v1.au_context_paired.runner import _Accounting
        from knowledge_base.pipeline_v1.au_context_paired.transport import PairedTransport
        from knowledge_base.pipeline_v1.au_compact.jobs_client import payload_digest
        self.Accounting = _Accounting
        self.PairedTransport = PairedTransport
        self.payload_digest = payload_digest

    def _config(self, **overrides):
        return {"jobs_url": "https://unit.invalid/jobs", "token": "fixture-only",
                "job_wait_seconds": 1800, "job_poll_seconds": 1, "timeout": 30,
                **overrides}

    @staticmethod
    def _ledger():
        return {"provider_attempts": 0, "get_polls": 0, "warmup_attempts": 0,
                "probe_attempts": 0, "reserved_input_tokens": 0,
                "reserved_output_tokens": 0, "attempts": []}

    def test_ready_and_two_authoritative_absences_allow_one_same_job_retry_then_resume_get_only(self):
        from knowledge_base.pipeline_v1.au_compact.jobs_client import complete_job

        payload = {"model": "fixture", "messages": [{"role": "user", "content": "same prompt"}],
                   "max_tokens": 8}
        job = self.payload_digest(payload)
        response = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}}
        completed = {"job_id": job, "payload_sha256": job, "status": "completed",
                     "response": response, "response_sha256": self.payload_digest(response)}
        calls, clock = [], _FakeClock()
        post_count = 0

        def endpoint(request, **_kwargs):
            nonlocal post_count
            method, url = request.get_method(), request.full_url
            calls.append((method, url, request.data))
            if url.endswith("/health"):
                return _Response({"ready": True})
            if method == "GET":
                if post_count >= 2:
                    return _Response(completed)
                raise _http_error(request, 404, {"detail": "Unknown job"})
            if method == "POST":
                persisted = json.loads((root / "runtime_ledger.json").read_text(encoding="utf-8"))
                self.assertEqual(persisted["provider_attempts"], post_count + 1)
                post_count += 1
                self.assertEqual(json.loads(request.data), {"job_id": job, "payload": payload})
                if post_count == 1:
                    raise _http_error(request, 503, {"error": "busy"})
                return _Response(completed)
            self.fail(f"unexpected method {method}")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            budget = {"max_provider_attempts": 10, "max_total_input_tokens": 10000,
                      "max_total_output_tokens": 100}
            ledger = self._ledger()
            accounting = self.Accounting(root, ledger, budget, endpoint)
            transport = self.PairedTransport(self._config(), accounting, clock=clock,
                                             sleep=clock.sleep, readiness_seconds=600,
                                             backoff_seconds=1)
            body, trace = complete_job(self._config(), payload, transport,
                                       clock=clock, sleep=clock.sleep)
            self.assertEqual(body, response)
            self.assertEqual(trace["job_id"], job)
            posts = [entry for entry in calls if entry[0] == "POST"]
            self.assertEqual(len(posts), 2)  # initial uncertain POST + one proven recovery POST
            self.assertEqual(posts[0][2], posts[1][2])
            self.assertEqual([a["job_id"] for a in ledger["attempts"]], [job, job])
            self.assertTrue(ledger["job_recovery"][job]["retry_used"])
            self.assertTrue(all(o["health"]["ready"] is True
                                for o in ledger["job_recovery"][job]["last_absence_proof"]["observations"]))
            saved = json.loads((root / "runtime_ledger.json").read_text(encoding="utf-8"))
            prior = (saved["provider_attempts"], saved["reserved_input_tokens"],
                     saved["reserved_output_tokens"])

            # A fresh process has no in-memory POST permit. The completed job is found by GET.
            resumed_accounting = self.Accounting(root, saved, budget, endpoint)
            resumed_transport = self.PairedTransport(self._config(), resumed_accounting,
                                                      clock=clock, sleep=clock.sleep,
                                                      readiness_seconds=600, backoff_seconds=1)
            again, _ = complete_job(self._config(), payload, resumed_transport,
                                    clock=clock, sleep=clock.sleep)
            self.assertEqual(again, response)
            self.assertEqual(sum(row[0] == "POST" for row in calls), 2)
            self.assertEqual((saved["provider_attempts"], saved["reserved_input_tokens"],
                              saved["reserved_output_tokens"]), prior)

    def test_health_503_must_be_followed_by_fresh_ready_before_job_post(self):
        from knowledge_base.pipeline_v1.au_compact.jobs_client import complete_job

        payload = {"model": "fixture", "messages": [{"role": "user", "content": "locked"}],
                   "max_tokens": 8}
        job = self.payload_digest(payload)
        clock, events = _FakeClock(), []
        health_count = 0

        def endpoint(request, **_kwargs):
            nonlocal health_count
            events.append((request.get_method(), request.full_url))
            if request.full_url.endswith("/health"):
                health_count += 1
                if health_count == 1:
                    raise _http_error(request, 503, {"detail": "warming"})
                events.append(("HEALTH_READY", request.full_url))
                return _Response({"ready": True})
            if request.get_method() == "GET":
                raise _http_error(request, 404, {"detail": "Unknown job"})
            raise RuntimeError("stop after observing recovery POST")

        with tempfile.TemporaryDirectory() as folder:
            accounting = self.Accounting(Path(folder), self._ledger(),
                                         {"max_provider_attempts": 5,
                                          "max_total_input_tokens": 10000,
                                          "max_total_output_tokens": 100}, endpoint)
            transport = self.PairedTransport(self._config(job_wait_seconds=3), accounting,
                                             clock=clock, sleep=clock.sleep,
                                             readiness_seconds=600, backoff_seconds=1)
            with self.assertRaisesRegex(RuntimeError, "recovery POST"):
                complete_job(self._config(job_wait_seconds=3), payload, transport,
                             clock=clock, sleep=clock.sleep)
        first_post = next(i for i, row in enumerate(events) if row[0] == "POST")
        before_post = events[:first_post]
        self.assertGreaterEqual(sum(row[0] == "HEALTH_READY" for row in before_post), 2)
        self.assertGreaterEqual(sum(row[0] == "GET" and row[1].endswith("/" + job)
                                    for row in before_post), 2)

    def test_generic_html_404_never_posts_and_wait_is_capped_at_600_seconds(self):
        from knowledge_base.pipeline_v1.au_compact.jobs_client import JobTransportError
        from knowledge_base.pipeline_v1.au_context_paired.runner import PairedRunError
        from urllib.request import Request

        payload = {"model": "fixture", "messages": [{"role": "user", "content": "locked"}],
                   "max_tokens": 8}
        job = self.payload_digest(payload)
        clock, calls = _FakeClock(), []

        def endpoint(request, **_kwargs):
            calls.append((request.get_method(), request.full_url))
            if request.full_url.endswith("/health"):
                return _Response({"ready": True})
            raise _http_error(request, 404, b"<html>generic not found</html>")

        with tempfile.TemporaryDirectory() as folder:
            accounting = self.Accounting(Path(folder), self._ledger(),
                                         {"max_provider_attempts": 5,
                                          "max_total_input_tokens": 10000,
                                          "max_total_output_tokens": 100}, endpoint)
            transport = self.PairedTransport(self._config(), accounting, clock=clock,
                                             sleep=clock.sleep, readiness_seconds=1800,
                                             backoff_seconds=300)
            request = Request("https://unit.invalid/jobs/" + job, method="GET")
            with self.assertRaises(PairedRunError):
                transport(request, timeout=1800)
        self.assertEqual(clock.value, 600)
        self.assertFalse(any(method == "POST" for method, _url in calls))

    def test_running_job_honors_configured_1800_second_job_deadline_without_resubmission(self):
        from knowledge_base.pipeline_v1.au_compact.jobs_client import complete_job, JobTransportError

        payload = {"model": "fixture", "messages": [{"role": "user", "content": "locked"}],
                   "max_tokens": 8}
        job = self.payload_digest(payload)
        clock, calls = _FakeClock(), []

        def endpoint(request, **_kwargs):
            calls.append(request.get_method())
            if request.full_url.endswith("/health"):
                return _Response({"ready": True})
            return _Response({"job_id": job, "payload_sha256": job, "status": "running"})

        with tempfile.TemporaryDirectory() as folder:
            accounting = self.Accounting(Path(folder), self._ledger(),
                                         {"max_provider_attempts": 5,
                                          "max_total_input_tokens": 10000,
                                          "max_total_output_tokens": 100}, endpoint)
            transport = self.PairedTransport(self._config(job_poll_seconds=300), accounting,
                                             clock=clock, sleep=clock.sleep,
                                             readiness_seconds=600, backoff_seconds=300)
            with self.assertRaises(JobTransportError):
                complete_job(self._config(job_poll_seconds=300), payload, transport,
                             clock=clock, sleep=clock.sleep)
        # The 600-second bound applies to readiness/absence recovery. An
        # acknowledged running inference retains its configured 30-minute wait.
        self.assertEqual(clock.value, 1800)
        self.assertNotIn("POST", calls)

    def test_failed_and_interrupted_jobs_are_terminal_without_post(self):
        from knowledge_base.pipeline_v1.au_compact.jobs_client import complete_job, JobTransportError

        payload = {"model": "fixture", "messages": [{"role": "user", "content": "locked"}],
                   "max_tokens": 8}
        job = self.payload_digest(payload)
        for status in ("failed", "interrupted"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as folder:
                clock, calls = _FakeClock(), []

                def endpoint(request, **_kwargs):
                    calls.append(request.get_method())
                    if request.full_url.endswith("/health"):
                        return _Response({"ready": True})
                    return _Response({"job_id": job, "payload_sha256": job,
                                      "status": status, "error": "fixture"})

                accounting = self.Accounting(Path(folder), self._ledger(),
                                             {"max_provider_attempts": 5,
                                              "max_total_input_tokens": 10000,
                                              "max_total_output_tokens": 100}, endpoint)
                transport = self.PairedTransport(self._config(), accounting, clock=clock,
                                                 sleep=clock.sleep)
                with self.assertRaises(JobTransportError):
                    complete_job(self._config(), payload, transport, clock=clock, sleep=clock.sleep)
                self.assertNotIn("POST", calls)


class LocalMigrationArtifactAuditTests(unittest.TestCase):
    """Audit the current local migrated artifact; it is not a checked-in fixture."""

    def test_actual_migration_preserves_counters_payloads_receipts_and_source_provenance(self):
        from knowledge_base.pipeline_v1.au_context_paired import runner
        from knowledge_base.pipeline_v1.au_context_paired.build import read_json
        from knowledge_base.pipeline_v1.au_compact import runner as compact

        base = Path(__file__).resolve().parents[1] / "knowledge_base/pipeline_v1/outputs/au_context_paired"
        migrated_root = base / "pilot_20261014_084923_recovered_v1"
        if not (migrated_root / "migration_manifest.json").is_file():
            self.skipTest("local pilot migration artifact is absent; reproducible migration fixture remains untested")
        migration = read_json(migrated_root / "migration_manifest.json")
        workload = read_json(migrated_root / "workload.json")
        new_ledger = read_json(migrated_root / "live/runtime_ledger.json")
        self.assertEqual(migration["status"], "complete")
        self.assertEqual(migration["network_requests"], 0)
        self.assertEqual(migration["semantic_quality"], "not_assessed")
        self.assertEqual(migration["copied_receipts"], 4)
        self.assertEqual(migration["counters_preserved"]["provider_attempts"], 24)
        self.assertEqual(migration["counters_preserved"]["warmup_attempts"], 18)
        self.assertEqual(migration["counters_preserved"]["probe_attempts"], 1)
        self.assertEqual(migration["counters_preserved"]["requests"], 5)
        self.assertTrue(migration["payloads_unchanged"])
        self.assertTrue(migration["rendered_inputs_unchanged"])
        self.assertTrue(all(migration["old_checkpoint_preservation"].values()))
        self.assertEqual(new_ledger["provider_attempts"], 24)
        self.assertEqual(new_ledger["warmup_attempts"], 18)
        self.assertEqual(new_ledger["probe_attempts"], 1)
        self.assertEqual(new_ledger["requests"], 5)
        self.assertEqual(len(new_ledger["reservations"]), 5)
        self.assertEqual(len(new_ledger["terminal"]), 4)

        parent = Path(workload["migration"]["parent_workload_path"])
        parent_live = Path(workload["migration"]["parent_live"])
        old_workload = read_json(parent)
        old_ledger = read_json(parent_live / "runtime_ledger.json")
        cfg = {"url": old_workload["identity"]["url"],
               "jobs_url": old_workload["identity"]["url"].removesuffix("/chat/completions") + "/jobs",
               "model": old_workload["identity"]["model"],
               "enable_thinking": old_workload["identity"]["enable_thinking"],
               "transport": old_workload["identity"]["transport"],
               "string_decoder": old_workload["identity"]["string_decoder"]}
        old_requests = {row["request_id"]: row for row in old_workload["manifest"]["requests"]}
        for rid, old_key in old_ledger["terminal"].items():
            old_row = read_json(parent_live / "receipts" / (old_key + ".json"))
            new_key = new_ledger["terminal"][rid]
            new_row = read_json(migrated_root / "live/receipts" / (new_key + ".json"))
            self.assertEqual(new_row["cache_key"], runner.receipt_key(
                old_requests[rid], migration["new_identity"], cfg))
            self.assertEqual(new_row["request"], old_row["request"])
            self.assertEqual(new_row["compact_response"], old_row["compact_response"])
            self.assertEqual(new_row["receipt"], old_row["receipt"])
            self.assertEqual(new_row["migration_provenance"]["original_row_sha256"], old_row["row_sha256"])
            self.assertEqual(new_row["row_sha256"], compact._hash(
                {k: v for k, v in new_row.items() if k != "row_sha256"}))
        for rid, reservation in new_ledger["reservations"].items():
            self.assertEqual(reservation["cache_key"], runner.receipt_key(
                old_requests[rid], migration["new_identity"], cfg))


if __name__ == "__main__":
    unittest.main()
