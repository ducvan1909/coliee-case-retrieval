"""Independent offline lifecycle and durability tests for the bulk gateway."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import URLError
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from knowledge_base.pipeline_v1.deployments.modal import job_gateway_bulk as gateway_module
from knowledge_base.pipeline_v1.bulk_execution import transport as bulk_transport


def _payload(index: int) -> dict:
    return {"model": "mock-qwen", "messages": [
        {"role": "user", "content": f"offline payload {index}"}],
        "max_tokens": 32, "stream": False}


def _capsules(count: int) -> list[dict]:
    return [{"job_id": gateway_module.payload_job_id(payload), "payload": payload}
            for payload in (_payload(index) for index in range(count))]


def _successful_response(index: int) -> dict:
    return {"choices": [{"finish_reason": "stop",
                         "message": {"content": f"mock response {index}"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}


class BulkGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "job-store"
        self.commits = []
        self.gateway = gateway_module.JobGateway(self.root, lambda: self.commits.append(True))
        self.gateway.recover()

    def tearDown(self):
        self.temp.cleanup()

    def submit(self, mode="bulk", capsules=None):
        capsules = capsules or _capsules(2)
        gid = self.gateway.group_id(mode, capsules)
        result = self.gateway.submit_group(mode, gid, capsules)
        return gid, result, capsules

    def finish(self, gid, capsules, index, *, mode="bulk", status="completed"):
        capsule = capsules[index]
        record = self.gateway.read(capsule["job_id"])
        record.update(status="running", started_at=gateway_module.now(),
                      updated_at=gateway_module.now())
        self.gateway.persist(record)
        record.update(status=status, finished_at=gateway_module.now(),
                      updated_at=gateway_module.now(), inference_seconds=0.01)
        if status == "completed":
            response = _successful_response(index)
            record.update(response=response, usage=response["usage"],
                          response_sha256=gateway_module.payload_job_id(response))
        else:
            record["error"] = {"phase": "restart", "kind": "unknown_inference_outcome",
                               "outcome_unknown": True}
        self.gateway.persist(record)
        return record

    def test_mode_and_order_are_bound_into_canonical_group_identity(self):
        jobs = _capsules(2)
        bulk = self.gateway.group_id("bulk", jobs)
        corpus = self.gateway.group_id("corpus", jobs)
        reversed_jobs = self.gateway.group_id("bulk", list(reversed(jobs)))

        self.assertEqual(bulk, gateway_module.payload_job_id({"mode": "bulk", "jobs": jobs}))
        self.assertNotEqual(bulk, corpus)
        self.assertNotEqual(bulk, reversed_jobs)
        with self.assertRaises(ValueError):
            gateway_module.JobGateway(self.root / "bad", lambda: None, concurrency=2)
        with self.assertRaises(ValueError):
            gateway_module.JobGateway(self.root / "bad2", lambda: None,
                                      concurrency=4, server_concurrency=2)

    def test_terminal_events_are_unique_and_paginated_in_completion_order(self):
        gid, _ack, jobs = self.submit()
        # Job 1 finishes first even though it appears second in the POST list.
        receipt = self.finish(gid, jobs, 1)
        # Re-persisting an already terminal receipt must not append a second event.
        self.gateway.persist(receipt)
        self.finish(gid, jobs, 0)

        first = self.gateway.progress("bulk", gid, after=0, limit=1)
        second = self.gateway.progress("bulk", gid, after=1, limit=1)
        self.assertEqual([row["job_id"] for row in first["results"]], [jobs[1]["job_id"]])
        self.assertEqual([row["job_id"] for row in second["results"]], [jobs[0]["job_id"]])
        self.assertEqual((first["cursor"], first["next_cursor"]), (0, 1))
        self.assertEqual((second["cursor"], second["next_cursor"]), (1, 2))
        self.assertEqual(first["counts"]["completed"], 2)
        self.assertNotIn("payload", first["results"][0])
        self.assertEqual(first["results"][0]["response_sha256"],
                         gateway_module.payload_job_id(first["results"][0]["response"]))

    def test_partial_group_commit_recovers_authoritative_active_manifest(self):
        jobs = _capsules(3)
        gid = self.gateway.group_id("bulk", jobs)
        fail_commit = [False]

        def commit():
            self.commits.append(True)
            if fail_commit[0]:
                raise OSError("simulated volume commit failure")

        self.gateway.commit = commit
        fail_commit[0] = True
        with self.assertRaises(OSError):
            self.gateway.submit_group("bulk", gid, jobs)

        self.assertTrue(self.gateway.poisoned)
        self.assertTrue(self.gateway.group_path("bulk", gid, kind="active").is_file())
        self.assertFalse(list((self.root / "pending").glob("*.json")))

        recovered_calls = []
        restarted = gateway_module.JobGateway(self.root, lambda: None)
        restarted.recover()
        self.assertEqual(set(restarted.pending), {job["job_id"] for job in jobs[:16]})
        self.assertEqual(restarted.groups[("bulk", gid)]["jobs"], jobs)
        def backend(payload):
            recovered_calls.append(gateway_module.payload_job_id(payload))
            if len(recovered_calls) == len(jobs):
                restarted.stop_event.set()
            return 200, json.dumps(_successful_response(len(recovered_calls) - 1)).encode()

        restarted.call_backend = backend
        restarted.run()
        # The original admission never dispatched. Recovery rebuilt the queue,
        # and each admitted capsule was called once after restart.
        self.assertEqual(recovered_calls, [job["job_id"] for job in jobs])
        self.assertEqual(restarted.progress("bulk", gid)["counts"]["completed"], 3)

    def test_running_claim_is_committed_before_backend_dispatch(self):
        gid, _ack, jobs = self.submit(capsules=_capsules(1))
        observed = []
        stop = threading.Event()

        def backend(payload):
            job_id = gateway_module.payload_job_id(payload)
            marker = json.loads((self.root / "pending" / (job_id + ".json")).read_text())
            state = json.loads(self.gateway.group_path("bulk", gid, kind="states").read_text())
            observed.append((marker["status"], state["statuses"][job_id]))
            stop.set()
            self.gateway.stop_event.set()
            return 200, json.dumps(_successful_response(0)).encode()

        self.gateway.call_backend = backend
        worker = threading.Thread(target=self.gateway.run, daemon=True)
        worker.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and worker.is_alive():
            if stop.wait(0.01):
                break
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(observed, [("running", "running")])
        self.assertEqual(self.gateway.progress("bulk", gid)["counts"]["completed"], 1)

    def test_claim_commit_failure_prevents_backend_dispatch_and_poisons_gateway(self):
        _gid, _ack, jobs = self.submit(capsules=_capsules(1))
        invoked = []

        def fail_running_commit():
            marker = json.loads((self.root / "pending" /
                                 (jobs[0]["job_id"] + ".json")).read_text())
            if marker["status"] == "running":
                raise OSError("claim commit failed")

        self.gateway.commit = fail_running_commit
        self.gateway.call_backend = lambda payload: invoked.append(payload)
        self.gateway.run()

        self.assertTrue(self.gateway.poisoned)
        self.assertEqual(invoked, [])
        self.assertEqual(json.loads((self.root / "pending" /
                                     (jobs[0]["job_id"] + ".json")).read_text())["status"], "running")

    def test_unknown_backend_outcome_is_sticky_and_leaves_other_job_queued(self):
        gid, _ack, jobs = self.submit()
        calls = []

        def backend(payload):
            calls.append(payload)
            raise URLError("unknown provider outcome")

        self.gateway.call_backend = backend
        first = self.gateway.read(jobs[0]["job_id"])
        first.update(status="running", started_at=gateway_module.now())
        self.gateway.persist(first)
        self.gateway.execute(first)
        self.gateway.run()

        self.assertEqual(len(calls), 1)
        self.assertTrue(self.gateway.backend_uncertain)
        self.assertEqual(self.gateway.pending[jobs[1]["job_id"]]["status"], "queued")
        progress = self.gateway.progress("bulk", gid)
        self.assertEqual(progress["status"], "blocked")
        self.assertEqual(progress["counts"]["interrupted"], 1)
        self.assertEqual(progress["counts"]["queued"], 1)

    def test_probe_reservation_excludes_jobs_and_active_jobs_exclude_probe(self):
        gate = gateway_module.InferenceGate(4)
        self.assertTrue(gate.acquire_job(lambda: False))
        self.assertFalse(gate.acquire())
        gate.release_job()
        self.assertTrue(gate.acquire())

        admitted = threading.Event()
        worker = threading.Thread(
            target=lambda: (gate.acquire_job(lambda: False), admitted.set(), gate.release_job()),
            daemon=True)
        worker.start()
        self.assertFalse(admitted.wait(0.05))
        gate.release()
        self.assertTrue(admitted.wait(1))
        worker.join(timeout=1)

    def test_worker_claim_does_not_glob_archive_payloads(self):
        gid, _ack, jobs = self.submit(capsules=_capsules(1))
        archive = self.root / "archive"
        archive.mkdir(exist_ok=True)
        for index in range(30):
            (archive / (f"historical-{index:03d}.json")).write_text("{}", encoding="utf-8")
        dispatched = threading.Event()

        def backend(payload):
            dispatched.set()
            self.gateway.stop_event.set()
            return 200, json.dumps(_successful_response(0)).encode()

        self.gateway.call_backend = backend
        original_glob = Path.glob

        def reject_archive_glob(path, pattern):
            if path == archive:
                raise AssertionError("worker attempted an archive-wide scan")
            return original_glob(path, pattern)

        with patch.object(Path, "glob", reject_archive_glob):
            worker = threading.Thread(target=self.gateway.run, daemon=True)
            worker.start()
            self.assertTrue(dispatched.wait(2), "job was not dispatched")
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(self.gateway.progress("bulk", gid)["counts"]["completed"], 1)

    def test_deque_refill_has_receipt_commit_barrier_and_recovers_after_restart(self):
        jobs = _capsules(20)
        gid, _ack, _jobs = self.submit(capsules=jobs)
        self.assertEqual(len(self.gateway.pending), 16)
        self.assertEqual(list(self.gateway.admission_deques[("bulk", gid)]), [16, 17, 18, 19])

        snapshots = []
        real_commit = self.gateway.commit

        def observe_commit():
            receipt = self.gateway.path(jobs[0]["job_id"])
            if receipt.exists():
                state = json.loads(self.gateway.group_path("bulk", gid, kind="states").read_text())
                marker = self.gateway.marker_path(jobs[16]["job_id"])
                snapshots.append((state["statuses"][jobs[0]["job_id"]], marker.exists(),
                                  self.gateway.path(jobs[0]["job_id"]).exists()))
            real_commit()

        self.gateway.commit = observe_commit
        self.finish(gid, jobs, 0)
        # First durable commit exposes the terminal receipt/event while the old
        # marker remains; second commit removes it and admits the next deque item.
        self.assertGreaterEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-2:], [("completed", False, True),
                                         ("completed", True, True)])
        self.assertEqual(len(self.gateway.pending), 16)
        self.assertTrue(self.gateway.marker_path(jobs[16]["job_id"]).exists())
        self.assertEqual(list(self.gateway.admission_deques[("bulk", gid)]), [17, 18, 19])

        restarted = gateway_module.JobGateway(self.root, lambda: None)
        restarted.recover()
        self.assertEqual(len(restarted.pending), 16)
        self.assertEqual(list(restarted.admission_deques[("bulk", gid)]), [17, 18, 19])
        record = restarted.read(jobs[1]["job_id"])
        record.update(status="running", started_at=gateway_module.now())
        restarted.persist(record)
        record.update(status="completed", finished_at=gateway_module.now(),
                      response=_successful_response(1), usage=_successful_response(1)["usage"],
                      response_sha256=gateway_module.payload_job_id(_successful_response(1)))
        restarted.persist(record)
        self.assertEqual(len(restarted.pending), 16)
        self.assertTrue(restarted.marker_path(jobs[17]["job_id"]).exists())
        self.assertEqual(list(restarted.admission_deques[("bulk", gid)]), [18, 19])

    def test_http_routes_round_trip_transport_and_enforce_mode_body_limits(self):
        jobs = _capsules(1)
        gid = self.gateway.group_id("bulk", jobs)
        app = gateway_module.create_app(self.root / "asgi-store", lambda: None)
        calls = []

        def backend(payload):
            index = len(calls)
            calls.append(payload)
            if index == 0:
                app.state.gateway.stop_event.set()
            return 200, json.dumps(_successful_response(index)).encode()

        app.state.gateway.call_backend = backend

        class Response:
            def __init__(self, response):
                self.body = response.content
                self.status = response.status_code
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _limit=-1): return self.body

        with TestClient(app) as http:
            def opener(request, **_kwargs):
                response = http.request(request.get_method(), request.full_url,
                                        content=request.data, headers=dict(request.header_items()))
                return Response(response)

            client = bulk_transport.GroupTransport(
                {"url": "http://test/v1/chat/completions", "token": "offline", "timeout": 2},
                opener=opener)
            ack, recovered = client.admit("bulk", jobs)
            self.assertFalse(recovered)
            self.assertEqual((ack["group_id"], ack["mode"]), (gid, "bulk"))
            deadline = time.monotonic() + 2
            page = None
            while time.monotonic() < deadline:
                page = client.progress("bulk", gid, 0)
                if page["results"]:
                    break
                time.sleep(0.01)
            self.assertEqual(page["next_cursor"], 1)
            self.assertEqual(page["results"][0]["job_id"], jobs[0]["job_id"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(http.get(f"/v1/corpora/{gid}?after=-1").status_code, 400)

            over_batch = b'{"padding":"' + b'x' * (4 * 1024 * 1024) + b'"}'
            over_corpus = b'{"padding":"' + b'x' * (16 * 1024 * 1024) + b'"}'
            self.assertEqual(http.post("/v1/batches", content=over_batch).status_code, 413)
            self.assertEqual(http.post("/v1/corpora", content=over_corpus).status_code, 413)


if __name__ == "__main__":
    unittest.main()
