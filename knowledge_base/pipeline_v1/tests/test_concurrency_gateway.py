"""Independent lifecycle and admission tests for the experimental job gateway."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from knowledge_base.pipeline_v1.deployments.modal import job_gateway_concurrency as gateway_module


def _payload(text):
    return {"model": "offline-test", "messages": [{"role": "user", "content": text}]}


def _success(payload):
    return 200, json.dumps({"choices": [{"message": {"content": payload["messages"][0]["content"]}}],
                            "usage": {"prompt_tokens": 2, "completion_tokens": 1,
                                      "total_tokens": 3}}).encode("utf-8")


class ConcurrencyGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "jobs"

    def tearDown(self):
        self.temp.cleanup()

    def make_gateway(self, concurrency=1, *, store=None, commit=None):
        commits = []

        def durable_commit():
            commits.append(True)
            if commit is not None:
                commit()

        gateway = gateway_module.JobGateway(
            store or self.root, durable_commit, concurrency=concurrency,
            server_concurrency=concurrency,
        )
        gateway.recover()
        return gateway, commits

    def wait_status(self, gateway, job_id, status, timeout=3):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            with gateway_module.STORE_MUTEX:
                last = gateway.read(job_id)
            if last["status"] == status:
                return last
            time.sleep(0.005)
        self.fail(f"{job_id} did not reach {status}; got {last and last['status']}")

    def test_concurrency_configuration_accepts_only_one_two_or_four(self):
        for value in (1, 2, 4):
            with self.subTest(value=value):
                self.assertEqual(gateway_module.validate_concurrency(value), value)
                gateway, _ = self.make_gateway(value, store=self.root / str(value))
                self.assertEqual(gateway.inference.limit, value)
                self.assertEqual(gateway.server_concurrency, value)
        for value in (0, 3, 8, True, "2", 2.0, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    gateway_module.validate_concurrency(value)

    def test_worker_admission_never_exceeds_configured_cap(self):
        for limit in (1, 2, 4):
            with self.subTest(concurrency=limit):
                root = self.root / f"cap-{limit}"
                gateway, _ = self.make_gateway(limit, store=root)
                lock = threading.Lock()
                release = threading.Event()
                filled = threading.Event()
                current = 0
                maximum = 0

                def backend(_payload):
                    nonlocal current, maximum
                    with lock:
                        current += 1
                        maximum = max(maximum, current)
                        if current >= limit:
                            filled.set()
                    if not release.wait(2):
                        raise TimeoutError("test release timed out")
                    with lock:
                        current -= 1
                    return _success(_payload)

                gateway.call_backend = backend
                gateway.start()
                ids = []
                try:
                    for index in range(limit + 2):
                        payload = _payload(f"cap-{limit}-{index}")
                        job_id = gateway_module.payload_job_id(payload)
                        ids.append(job_id)
                        gateway.submit(job_id, payload)
                    self.assertTrue(filled.wait(2), "configured worker capacity was not reached")
                    with lock:
                        self.assertLessEqual(current, limit)
                        self.assertEqual(maximum, limit)
                    release.set()
                    for job_id in ids:
                        self.wait_status(gateway, job_id, "completed")
                finally:
                    release.set()
                    gateway.stop(grace_seconds=2)

    def test_same_payload_has_one_durable_claim_and_one_backend_dispatch(self):
        gateway, _ = self.make_gateway(concurrency=2)
        started = threading.Event()
        release = threading.Event()
        calls = []

        def backend(payload):
            calls.append(payload)
            started.set()
            if not release.wait(2):
                raise TimeoutError("test release timed out")
            return _success(payload)

        gateway.call_backend = backend
        gateway.start()
        payload = _payload("one claim")
        job_id = gateway_module.payload_job_id(payload)
        try:
            first = gateway.submit(job_id, payload)
            self.assertTrue(started.wait(1))
            duplicate = gateway.submit(job_id, payload)
            self.assertEqual(first["status"], "queued")
            self.assertEqual(duplicate["status"], "running")
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            self.wait_status(gateway, job_id, "completed")
            gateway.stop(grace_seconds=2)

    def test_running_claim_is_durable_before_backend_dispatch(self):
        observed = []
        job_id_holder = []
        root = self.root

        def commit_observer():
            if not job_id_holder:
                return
            path = root / (job_id_holder[0] + ".json")
            if path.is_file():
                observed.append(json.loads(path.read_text(encoding="utf-8"))["status"])

        gateway, _ = self.make_gateway(commit=commit_observer)
        dispatch_states = []
        gateway.call_backend = lambda payload: (
            dispatch_states.append(gateway.read(job_id_holder[0])["status"]) or _success(payload)
        )
        payload = _payload("durable before dispatch")
        job_id = gateway_module.payload_job_id(payload)
        job_id_holder.append(job_id)
        gateway.start()
        try:
            gateway.submit(job_id, payload)
            self.wait_status(gateway, job_id, "completed")
        finally:
            gateway.stop(grace_seconds=2)
        self.assertIn("queued", observed)
        self.assertIn("running", observed)
        self.assertEqual(dispatch_states, ["running"])

    def test_restart_converts_running_to_unknown_and_never_replays_it(self):
        gateway, _ = self.make_gateway()
        payload = _payload("was running before restart")
        job_id = gateway_module.payload_job_id(payload)
        gateway.submit(job_id, payload)
        record = gateway.read(job_id)
        record.update(status="running", started_at=gateway_module.now())
        with gateway_module.STORE_MUTEX:
            gateway.persist(record)

        restarted, _ = self.make_gateway(store=self.root)
        calls = []
        restarted.call_backend = lambda value: calls.append(value) or _success(value)
        restarted.start()
        try:
            recovered = self.wait_status(restarted, job_id, "interrupted")
            self.assertEqual(recovered["error"]["kind"], "unknown_inference_outcome")
            self.assertEqual(calls, [])
        finally:
            restarted.stop(grace_seconds=2)

    def test_unknown_backend_outcome_poisoning_blocks_new_admission(self):
        gateway, _ = self.make_gateway(concurrency=2)
        first = _payload("unknown outcome")
        first_id = gateway_module.payload_job_id(first)
        gateway.submit(first_id, first)
        record = gateway.read(first_id)
        record.update(status="running", started_at=gateway_module.now())
        with gateway_module.STORE_MUTEX:
            gateway.persist(record)
        calls = []

        def unknown(_payload):
            calls.append(True)
            raise TimeoutError("provider may have received request")

        gateway.call_backend = unknown
        gateway.execute(record)
        interrupted = gateway.read(first_id)
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertIs(interrupted["error"]["outcome_unknown"], True)
        self.assertTrue(gateway.backend_uncertain)

        second = _payload("must fail closed")
        second_id = gateway_module.payload_job_id(second)
        with self.assertRaises(gateway_module.HTTPException) as raised:
            gateway.submit(second_id, second)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(calls, [True])

    def test_commit_failure_poisoning_prevents_backend_dispatch(self):
        gateway, _ = self.make_gateway(commit=lambda: (_ for _ in ()).throw(OSError()))
        calls = []
        gateway.call_backend = lambda payload: calls.append(payload) or _success(payload)
        payload = _payload("claim commit must succeed")
        job_id = gateway_module.payload_job_id(payload)
        with self.assertRaises(OSError):
            gateway.submit(job_id, payload)
        self.assertTrue(gateway.poisoned)
        self.assertEqual(calls, [])

    def test_exclusive_probe_reservation_never_overlaps_jobs(self):
        gate = gateway_module.InferenceGate(2)
        unavailable = lambda: False
        self.assertTrue(gate.acquire_job(unavailable))
        self.assertFalse(gate.acquire(blocking=False))
        gate.release_job()
        self.assertTrue(gate.acquire(blocking=False))

        job_acquired = threading.Event()
        release_job = threading.Event()

        def queued_job():
            if gate.acquire_job(unavailable):
                job_acquired.set()
                release_job.wait(1)
                gate.release_job()

        worker = threading.Thread(target=queued_job)
        worker.start()
        try:
            self.assertFalse(job_acquired.wait(0.05), "job entered during exclusive probe")
        finally:
            gate.release()
        self.assertTrue(job_acquired.wait(1), "queued job did not resume after probe")
        release_job.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())

    def test_apps_use_separate_stores_and_do_not_share_job_records(self):
        first_store = self.root / "app-one"
        second_store = self.root / "app-two"
        first_app = gateway_module.create_app(first_store, lambda: None, concurrency=1)
        second_app = gateway_module.create_app(second_store, lambda: None, concurrency=1)
        first_gateway, second_gateway = first_app.state.gateway, second_app.state.gateway
        payload = _payload("separate application store")
        job_id = gateway_module.payload_job_id(payload)
        first_gateway.recover()
        second_gateway.recover()
        first_gateway.submit(job_id, payload)
        with self.assertRaises(gateway_module.HTTPException) as raised:
            second_gateway.read(job_id)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertNotEqual(first_gateway.root, second_gateway.root)


if __name__ == "__main__":
    unittest.main()
