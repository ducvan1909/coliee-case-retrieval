"""Independent offline behavior tests for the experimental bulk host runner."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from knowledge_base.pipeline_v1.bulk_execution import core, transport as bulk_transport
from knowledge_base.pipeline_v1.bulk_execution import storage as bulk_storage
from knowledge_base.pipeline_v1.concurrency_benchmark import core as benchmark


def _task(index: int) -> dict:
    request = {
        "request_id": f"parent-request-{index:02d}",
        "case_id": "011904",
        "source_hash": f"source-{index:02d}",
        "expected_target_ids": [f"target-{index:02d}"],
        "spec": {"caps": {"output_tokens": 800}},
    }
    atom_id = f"atom-{index:02d}"
    return {
        "request": request,
        "source": "The court held that notice is required.",
        "binding": {"atom_map_relative_path": f"{index}.json"},
        "catalog": {"atoms": {atom_id: {"target_intersecting": True}}},
        "rendered": f"<TARGET atom_id={atom_id}>locked source {index}</TARGET>",
    }


def _prepared(index: int) -> dict:
    task = _task(index)
    effective = copy.deepcopy(task["request"])
    effective["request_id"] = f"effective-{index:02d}"
    payload = {
        "model": benchmark.MODEL,
        "messages": [{"role": "user", "content": f"mock prompt {index:02d}"}],
        "temperature": 0,
        "max_tokens": 800,
        "ebnf": f"mock grammar {index:02d}",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    return {**task, "effective": effective,
            "capsule": {"job_id": bulk_transport.payload_digest(payload), "payload": payload}}


def _manifest(count: int = 30) -> dict:
    return {"requests": [_task(i)["request"] for i in range(count)]}


def _capability(**changes):
    value = {
        "experiment": "au-bulk-v1",
        "app": "coliee-qwen35-9b-bulk",
        "gateway_concurrency": 4,
        "server_concurrency": 4,
        "model": benchmark.MODEL,
        "gpu": "L40S:1",
        "context_length": 12288,
        "max_total_tokens": 12288,
        "max_containers": 1,
        "exclusive_probes": True,
        "backend_retry": False,
        "ready": True,
        "capabilities": {name: True for name in
                         ("bulk_submit", "incremental_progress", "pending_queue", "corpus_runner")},
    }
    value.update(changes)
    return value


def _cfg():
    return {"url": "https://test--coliee-qwen35-9b-bulk-server.us-west.modal.direct/v1/chat/completions",
            "token": "offline-test-token", "model": benchmark.MODEL,
            "enable_thinking": False, "timeout": 1,
            "job_wait_seconds": 2, "job_poll_seconds": 0.001}


def _terminal(job_id: str, status="completed", response=None, **fields):
    body = response if response is not None else {"choices": [{"message": {"content": "{}"}}]}
    digest = bulk_transport.payload_digest(body)
    return {"job_id": job_id, "payload_sha256": job_id, "status": status,
            "response": body if status == "completed" else None,
            "response_sha256": digest if status == "completed" else None,
            **fields}


def _counts(total, *, queued=0, running=0, completed=0, failed=0, interrupted=0):
    return {"total": total, "queued": queued, "running": running,
            "completed": completed, "failed": failed, "interrupted": interrupted}


class _ScriptedTransport:
    def __init__(self, pages, *, recovered=False):
        self.pages = list(pages)
        self.recovered = recovered
        self.admissions = []
        self.progress_calls = []
        self.stats = {"post_attempts": 0, "get_attempts": 0}

    def admit(self, mode, jobs, *, resume=False):
        gid = bulk_transport.group_id(mode, jobs)
        self.admissions.append((mode, copy.deepcopy(jobs), resume))
        self.stats["post_attempts"] += int(not resume)
        return {"group_id": gid, "mode": mode}, self.recovered

    def progress(self, mode, gid, after, *, remaining=None):
        self.progress_calls.append((mode, gid, after))
        self.stats["get_attempts"] += 1
        page = self.pages.pop(0)
        return {"group_id": gid, "mode": mode, "cursor": after,
                "next_cursor": after + len(page["results"]),
                "counts": page["counts"], "results": page["results"],
                "status": page.get("status", "running")}


class BulkExecutionTests(unittest.TestCase):
    def test_build_manifest_binds_parent_without_mutating_it(self):
        parent = _manifest()
        before = copy.deepcopy(parent)
        value = core.build_manifest(parent, workload_id="pilot_30")

        self.assertEqual(value["source_count"], 30)
        self.assertEqual(value["parent_sha256"], benchmark.digest(parent))
        self.assertFalse(value["semantic_quality_claim"])
        parent["requests"].pop()
        self.assertEqual(value["parent"], before)
        self.assertEqual(value["source_count"], 30)

    def test_prepare_builds_arm_scoped_single_target_prompt_and_grammar(self):
        manifest = core.build_manifest(_manifest(), workload_id="pilot_30")
        source_tasks = [_task(0)]
        with patch.object(core.bench, "prepare", return_value=source_tasks):
            bulk = core.prepare(manifest, source_store="unused", atom_root="unused", arm="bulk")
            corpus = core.prepare(manifest, source_store="unused", atom_root="unused", arm="corpus")

        one, other = bulk[0], corpus[0]
        self.assertEqual(one["effective"]["expected_target_ids"], ["target-00"])
        self.assertNotEqual(one["effective"]["request_id"], other["effective"]["request_id"])
        self.assertTrue(one["effective"]["request_id"].startswith("bulk-"))
        self.assertIn("REQUEST_ID=" + one["effective"]["request_id"],
                      one["capsule"]["payload"]["messages"][0]["content"])
        payload = one["capsule"]["payload"]
        self.assertEqual(payload["model"], benchmark.MODEL)
        self.assertEqual(payload["max_tokens"], 800)
        self.assertEqual(payload["temperature"], 0)
        self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])
        self.assertTrue(payload["ebnf"].startswith("root ::= "))
        self.assertNotIn("response_format", payload)
        self.assertEqual(one["capsule"]["job_id"], bulk_transport.payload_digest(payload))
        another_workload = core.build_manifest(_manifest(), workload_id="pilot_31")
        with patch.object(core.bench, "prepare", return_value=source_tasks):
            other = core.prepare(another_workload, source_store="unused",
                                 atom_root="unused", arm="bulk")
        self.assertNotEqual(one["effective"]["request_id"], other[0]["effective"]["request_id"])

    def _run(self, temp, tasks, *, arm="bulk", group_size=16, transport=None,
             capability=None, warmup=None):
        root = Path(temp) / "experiment"
        source = Path(temp) / "source"
        atoms = Path(temp) / "atoms"
        source.mkdir(exist_ok=True)
        atoms.mkdir(exist_ok=True)
        with patch.object(core, "prepare", return_value=tasks), \
             patch.object(core.bench, "wait_capability",
                          return_value=capability or _capability()), \
             patch.object(core, "normalize_receipt", side_effect=self._normalized):
            return core.run(core.build_manifest(_manifest(), workload_id="pilot_30"),
                            cfg=_cfg(), source_store=source, atom_root=atoms,
                            arm=arm, output_root=root, execute=True,
                            group_size=group_size, transport=transport,
                            warmup_fn=warmup or (lambda *_: {"status": "success", "usage": None}),
                            clock=lambda: 10.0, sleep=lambda _seconds: None), root

    @staticmethod
    def _normalized(job, task):
        usage = job.get("usage")
        return {"request": task["effective"], "original_request": task["request"],
                "status": "unresolved" if job["status"] != "completed" else "protocol_verified",
                "compact_response": None, "response": None,
                "receipt": {"usage": usage, "usage_state": "provider" if usage else "unavailable",
                            "failure_diagnostic": ({"kind": "job_" + job["status"],
                                "outcome_unknown": job["status"] == "interrupted"}
                                if job["status"] != "completed" else {})}}

    def test_completion_order_pages_are_cached_and_ledger_stays_manifest_order(self):
        tasks = [_prepared(i) for i in range(3)]
        # The provider completes jobs out of input order and splits them over cursors.
        second = _terminal(tasks[1]["capsule"]["job_id"], usage={"input_tokens": 11, "output_tokens": 2, "total_tokens": 13})
        first = _terminal(tasks[0]["capsule"]["job_id"], usage={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10})
        third = _terminal(tasks[2]["capsule"]["job_id"], usage={"input_tokens": 5, "output_tokens": 1, "total_tokens": 6})
        scripted = _ScriptedTransport([
            {"results": [second, first], "counts": _counts(3, queued=1, completed=2)},
            {"results": [third], "counts": _counts(3, completed=3), "status": "completed"},
        ])
        self.assertEqual(len({task["capsule"]["job_id"] for task in tasks}), 3)
        checked = core.validate_progress(
            {"group_id": bulk_transport.group_id("bulk", [t["capsule"] for t in tasks]),
             "mode": "bulk", "cursor": 0, "next_cursor": 2,
             "counts": _counts(3, queued=1, completed=2), "results": [second, first]},
            gid=bulk_transport.group_id("bulk", [t["capsule"] for t in tasks]),
            mode="bulk", after=0,
            expected_ids={t["capsule"]["job_id"] for t in tasks})
        self.assertEqual(len(checked), 2)
        writes = []
        original_write = core.write_json

        def tracked_write(path, value):
            path = Path(path)
            writes.append((path.parent.name, path.name, copy.deepcopy(value)))
            return original_write(path, value)

        with tempfile.TemporaryDirectory() as temp, patch.object(
                core, "write_json", side_effect=tracked_write):
            report, root = self._run(temp, tasks, transport=scripted, group_size=3)
            self.assertTrue((root / "cache" /
                             (tasks[1]["capsule"]["job_id"] + ".json")).is_file())

        self.assertEqual([row["original_request"]["request_id"] for row in report["request_ledger"]],
                         [task["request"]["request_id"] for task in tasks], report)
        self.assertEqual([call[2] for call in scripted.progress_calls], [0, 2])
        cache_write = next(i for i, event in enumerate(writes)
                           if event[0] == "cache" and event[1] == tasks[1]["capsule"]["job_id"] + ".json")
        first_page_cache_writes = [i for i, event in enumerate(writes)
                                   if event[0] == "cache" and event[1] in {
                                       tasks[0]["capsule"]["job_id"] + ".json",
                                       tasks[1]["capsule"]["job_id"] + ".json"}]
        cursor_write = next(i for i, event in enumerate(writes)
                            if event[0] == "groups" and event[2].get("cursor") == 2)
        self.assertLess(cache_write, cursor_write)
        self.assertEqual(len(first_page_cache_writes), 2)
        self.assertTrue(all(index < cursor_write for index in first_page_cache_writes))
        self.assertEqual(report["tokens"], {"input_tokens": 23, "output_tokens": 6, "total_tokens": 29})
        self.assertTrue(report["performance_eligible"])
        self.assertGreaterEqual(report["setup"]["seconds"], 0)

    def test_cursor_ahead_of_cached_receipts_fails_before_transport(self):
        tasks = [_prepared(0)]
        scripted = _ScriptedTransport([])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "experiment"
            group_dir = root / "groups"
            group_dir.mkdir(parents=True)
            jobs = [tasks[0]["capsule"]["job_id"]]
            gid = bulk_transport.group_id("bulk", [tasks[0]["capsule"]])
            identity = {"version": core.VERSION,
                        "manifest_sha256": benchmark.digest(core.build_manifest(_manifest(), workload_id="pilot_30")),
                        "arm": "bulk", "group_size": 16,
                        "endpoint_sha256": hashlib.sha256(_cfg()["url"].encode()).hexdigest(),
                        "prompt_identity": core.runner.prompt_identity(),
                        "decoder_version": core.runner.RESPONSE_FORMAT_VERSION}
            core.write_json(group_dir / (gid + ".json"),
                            {"group_id": gid, "mode": "bulk", "cursor": 1,
                             "jobs": jobs, "identity": identity, "finished": False})
            source, atoms = Path(temp) / "source", Path(temp) / "atoms"
            source.mkdir(); atoms.mkdir()
            with patch.object(core, "prepare", return_value=tasks), \
                 patch.object(core.bench, "wait_capability", return_value=_capability()), \
                 self.assertRaisesRegex(ValueError, "bulk_cursor_ahead_of_receipts"):
                core.run(core.build_manifest(_manifest(), workload_id="pilot_30"),
                         cfg=_cfg(), source_store=source, atom_root=atoms, arm="bulk",
                         output_root=root, execute=True, transport=scripted,
                         warmup_fn=lambda *_: {"status": "success"})
        self.assertEqual(scripted.admissions, [])
        self.assertEqual(scripted.progress_calls, [])

    def test_changed_completed_receipt_digest_is_rejected_before_caching(self):
        task = _prepared(0)
        bad = _terminal(task["capsule"]["job_id"])
        bad["response"]["choices"][0]["message"]["content"] = "changed after signing"
        with self.assertRaisesRegex(ValueError, "group_response_digest_mismatch"):
            core.validate_progress(
                {"group_id": "g", "mode": "bulk", "cursor": 0,
                 "next_cursor": 1, "counts": _counts(1, completed=1),
                 "results": [bad]}, gid="g", mode="bulk", after=0,
                expected_ids={task["capsule"]["job_id"]})

    def test_progress_counts_cover_cursor_and_page_terminal_statuses(self):
        jobs = [_prepared(i)["capsule"]["job_id"] for i in range(4)]
        rows = [_terminal(jobs[0]), _terminal(jobs[1])]
        value = {"group_id": "g", "mode": "bulk", "cursor": 2,
                 "next_cursor": 4, "counts": _counts(4, queued=1, completed=3),
                 "results": rows}
        # The page is internally within aggregate counts, but the aggregate
        # terminal total cannot account for a cursor already at event 4.
        with self.assertRaisesRegex(ValueError, "group_count_mismatch"):
            core.validate_progress(value, gid="g", mode="bulk", after=2,
                                   expected_ids=set(jobs))

        value["next_cursor"] = 2
        value["cursor"] = 0
        value["counts"] = _counts(4, queued=2, completed=1, interrupted=1)
        with self.assertRaisesRegex(ValueError, "group_count_mismatch"):
            core.validate_progress(value, gid="g", mode="bulk", after=0,
                                   expected_ids=set(jobs))

    def test_local_json_storage_fsyncs_temp_before_atomic_replace(self):
        import os

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "state" / "receipt.json"
            events = []
            real_fsync, real_replace = os.fsync, os.replace

            def tracked_fsync(descriptor):
                events.append(("fsync", descriptor))
                return real_fsync(descriptor)

            def tracked_replace(source, destination):
                events.append(("replace", Path(source), Path(destination)))
                return real_replace(source, destination)

            with patch.object(bulk_storage.os, "fsync", side_effect=tracked_fsync), \
                 patch.object(bulk_storage.os, "replace", side_effect=tracked_replace):
                bulk_storage.write_json(target, {"cursor": 3, "receipts": ["a", "b", "c"]})

            replace_index = next(i for i, event in enumerate(events) if event[0] == "replace")
            self.assertTrue(any(event[0] == "fsync" for event in events[:replace_index]))
            replace_event = events[replace_index]
            self.assertEqual(replace_event[1], target.with_suffix(".json.tmp"))
            self.assertEqual(replace_event[2], target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                             {"cursor": 3, "receipts": ["a", "b", "c"]})
            self.assertFalse(target.with_suffix(".json.tmp").exists())

    def test_duplicate_completion_event_across_pages_fails_closed(self):
        tasks = [_prepared(i) for i in range(2)]
        duplicated = _terminal(tasks[0]["capsule"]["job_id"])
        scripted = _ScriptedTransport([
            {"results": [duplicated],
             "counts": _counts(2, completed=1, queued=1), "status": "running"},
            {"results": [duplicated],
             "counts": _counts(2, completed=1, queued=1), "status": "running"},
        ])
        with tempfile.TemporaryDirectory() as temp:
            report, _ = self._run(temp, tasks, transport=scripted, group_size=2)

        self.assertEqual([call[2] for call in scripted.progress_calls], [0, 1])
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(report["transport_failure"]["kind"], "ValueError")
        self.assertTrue(report["stop_dispatch"])

    def test_cached_completion_is_never_reported_as_fresh_performance(self):
        tasks = [_prepared(0)]
        job_id = tasks[0]["capsule"]["job_id"]
        gid = bulk_transport.group_id("bulk", [tasks[0]["capsule"]])
        scripted = _ScriptedTransport([
            {"results": [_terminal(job_id)], "counts": _counts(1, completed=1),
             "status": "completed"},
        ])
        warmups = []
        with tempfile.TemporaryDirectory() as temp:
            # Seed a prior, identity-bound local result to exercise resume accounting.
            root = Path(temp) / "experiment"
            source, atoms = Path(temp) / "source", Path(temp) / "atoms"
            source.mkdir(); atoms.mkdir()
            manifest = core.build_manifest(_manifest(), workload_id="pilot_30")
            identity = {"version": core.VERSION, "manifest_sha256": benchmark.digest(manifest),
                        "arm": "bulk", "group_size": 16,
                        "endpoint_sha256": hashlib.sha256(_cfg()["url"].encode()).hexdigest(),
                        "prompt_identity": core.runner.prompt_identity(),
                        "decoder_version": core.runner.RESPONSE_FORMAT_VERSION}
            cached = self._normalized(_terminal(job_id), tasks[0])
            cached["identity"] = identity
            core.write_json(root / "cache" / (job_id + ".json"), cached)
            gid = bulk_transport.group_id("bulk", [tasks[0]["capsule"]])
            core.write_json(root / "groups" / (gid + ".json"), {
                "group_id": gid, "mode": "bulk", "cursor": 0,
                "jobs": [job_id], "identity": identity, "finished": False})
            with patch.object(core, "prepare", return_value=tasks), \
                 patch.object(core.bench, "wait_capability", return_value=_capability()), \
                 patch.object(core, "normalize_receipt", side_effect=self._normalized):
                report = core.run(manifest, cfg=_cfg(), source_store=source, atom_root=atoms,
                                  arm="bulk", output_root=root, execute=True,
                                  transport=scripted,
                                  warmup_fn=lambda *_: warmups.append(True) or {"status": "success"},
                                  clock=lambda: 10.0, sleep=lambda _seconds: None)

        self.assertFalse(report["performance_eligible"])
        self.assertTrue(report["resume_or_recovered_receipt"])
        self.assertEqual(warmups, [])
        self.assertTrue(scripted.admissions[0][2])

    def test_interrupted_receipt_stops_later_group_admission_and_counts_usage(self):
        tasks = [_prepared(i) for i in range(2)]
        first = _terminal(tasks[0]["capsule"]["job_id"], "interrupted",
                          usage={"input_tokens": 13, "output_tokens": 4, "total_tokens": 17})
        scripted = _ScriptedTransport([
            {"results": [first], "counts": _counts(1, interrupted=1), "status": "paused"},
        ])
        with tempfile.TemporaryDirectory() as temp:
            report, _ = self._run(temp, tasks, transport=scripted, group_size=1)

        self.assertTrue(report["stop_dispatch"])
        self.assertEqual(len(scripted.admissions), 1)
        self.assertEqual(report["tokens"], {"input_tokens": 13, "output_tokens": 4, "total_tokens": 17}, report)
        self.assertEqual(report["usage_unavailable"], 0)

    def test_terminal_interrupted_progress_drains_remaining_receipt_pages(self):
        tasks = [_prepared(i) for i in range(2)]
        interrupted = _terminal(tasks[0]["capsule"]["job_id"], "interrupted")
        completed = _terminal(tasks[1]["capsule"]["job_id"])
        scripted = _ScriptedTransport([
            {"results": [interrupted],
             "counts": _counts(2, completed=1, interrupted=1), "status": "interrupted"},
            {"results": [completed],
             "counts": _counts(2, completed=1, interrupted=1), "status": "interrupted"},
        ])
        with tempfile.TemporaryDirectory() as temp:
            report, _ = self._run(temp, tasks, transport=scripted, group_size=2)

        self.assertEqual([call[2] for call in scripted.progress_calls], [0, 1])
        self.assertEqual(report["completed_count"], 2)
        self.assertTrue(report["stop_dispatch"])

    def test_finished_unknown_group_resume_never_admits_again(self):
        task = _prepared(0)
        job_id = task["capsule"]["job_id"]
        manifest = core.build_manifest(_manifest(), workload_id="pilot_30")
        identity = {"version": core.VERSION, "manifest_sha256": benchmark.digest(manifest),
                    "arm": "bulk", "group_size": 16,
                    "endpoint_sha256": hashlib.sha256(_cfg()["url"].encode()).hexdigest(),
                    "prompt_identity": core.runner.prompt_identity(),
                    "decoder_version": core.runner.RESPONSE_FORMAT_VERSION}
        gid = bulk_transport.group_id("bulk", [task["capsule"]])
        cached = self._normalized(_terminal(job_id, "interrupted"), task)
        cached["identity"] = identity
        transport = _ScriptedTransport([])
        warmups = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "experiment"
            core.write_json(root / "cache" / (job_id + ".json"), cached)
            core.write_json(root / "groups" / (gid + ".json"), {
                "group_id": gid, "mode": "bulk", "cursor": 1,
                "jobs": [job_id], "identity": identity, "finished": True})
            source, atoms = Path(temp) / "source", Path(temp) / "atoms"
            source.mkdir(); atoms.mkdir()
            with patch.object(core, "prepare", return_value=[task]), \
                 patch.object(core.bench, "wait_capability",
                              return_value=_capability(backend_outcome_unknown=True)), \
                 patch.object(core, "normalize_receipt", side_effect=self._normalized):
                report = core.run(manifest, cfg=_cfg(), source_store=source,
                                  atom_root=atoms, arm="bulk", output_root=root,
                                  execute=True, transport=transport,
                                  warmup_fn=lambda *_: warmups.append(True) or {"status": "success"})

        self.assertEqual(transport.admissions, [])
        self.assertEqual(transport.progress_calls, [])
        self.assertEqual(warmups, [])
        self.assertTrue(report["resume_or_recovered_receipt"])
        self.assertFalse(report["performance_eligible"])

    def test_corpus_arm_admits_whole_frozen_workload_as_one_group(self):
        tasks = [_prepared(i) for i in range(3)]
        receipts = [_terminal(task["capsule"]["job_id"]) for task in tasks]
        scripted = _ScriptedTransport([
            {"results": receipts, "counts": _counts(3, completed=3), "status": "completed"},
        ])
        with tempfile.TemporaryDirectory() as temp:
            report, _ = self._run(temp, tasks, arm="corpus", group_size=1,
                                  transport=scripted)

        self.assertEqual(len(scripted.admissions), 1)
        self.assertEqual(scripted.admissions[0][0], "corpus")
        self.assertEqual(len(scripted.admissions[0][1]), 3)
        self.assertEqual(report["arm"], "corpus")
        self.assertEqual(report["status"], "complete")

    def test_default_transport_recovers_lost_post_ack_without_second_post(self):
        jobs = [_prepared(0)["capsule"]]
        gid = bulk_transport.group_id("bulk", jobs)
        calls = []

        class Response:
            def __init__(self, body): self.body = json.dumps(body).encode()
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _limit=-1): return self.body

        def opener(request, **_kwargs):
            calls.append((request.get_method(), request.full_url,
                          json.loads(request.data) if request.data else None))
            if request.get_method() == "POST":
                raise URLError("lost acknowledgement")
            return Response({"group_id": gid, "mode": "bulk", "cursor": 0,
                             "next_cursor": 0, "counts": _counts(1, queued=1),
                             "results": []})

        client = bulk_transport.GroupTransport(_cfg(), opener=opener)
        ack, recovered = client.admit("bulk", jobs)

        self.assertEqual(ack["group_id"], gid)
        self.assertTrue(recovered)
        self.assertEqual([method for method, *_ in calls], ["POST", "GET"])
        self.assertEqual(calls[0][2], {"batch_id": gid, "jobs": jobs})
        self.assertTrue(calls[1][1].endswith(f"/v1/batches/{gid}?after=0&limit=32"))

    def test_run_uses_default_group_adapter_and_never_gets_each_job(self):
        task = _prepared(0)
        job_id = task["capsule"]["job_id"]
        calls = []

        class Response:
            def __init__(self, body): self.body = json.dumps(body).encode()
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _limit=-1): return self.body

        def opener(request, **_kwargs):
            body = json.loads(request.data) if request.data else None
            calls.append((request.get_method(), request.full_url, body))
            gid = (bulk_transport.group_id("bulk", body["jobs"]) if body else
                   request.full_url.split("/v1/batches/")[1].split("?")[0])
            if request.get_method() == "POST":
                return Response({"group_id": gid, "mode": "bulk", "status": "queued"})
            return Response({"group_id": gid, "mode": "bulk", "cursor": 0,
                             "next_cursor": 1, "counts": _counts(1, completed=1),
                             "results": [_terminal(job_id)], "status": "completed"})

        real_client = bulk_transport.GroupTransport
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(core, "prepare", return_value=[task]), \
             patch.object(core.bench, "wait_capability", return_value=_capability()), \
             patch.object(core, "normalize_receipt", side_effect=self._normalized), \
             patch.object(core, "GroupTransport",
                          side_effect=lambda cfg: real_client(cfg, opener=opener)):
            source, atoms = Path(temp) / "source", Path(temp) / "atoms"
            source.mkdir(); atoms.mkdir()
            report = core.run(core.build_manifest(_manifest(), workload_id="pilot_30"),
                              cfg=_cfg(), source_store=source, atom_root=atoms,
                              arm="bulk", output_root=Path(temp) / "experiment",
                              execute=True, warmup_fn=lambda *_: {"status": "success"},
                              clock=lambda: 10.0, sleep=lambda _seconds: None)

        self.assertEqual([call[0] for call in calls], ["POST", "GET"])
        self.assertEqual(calls[0][2], {"batch_id": calls[1][1].split("/v1/batches/")[1].split("?")[0],
                                      "jobs": [task["capsule"]]})
        self.assertNotIn("/v1/jobs/", " ".join(call[1] for call in calls))
        self.assertEqual(report["status"], "complete")

    def test_lost_post_ack_with_missing_group_fails_unknown_without_repost(self):
        jobs = [_prepared(0)["capsule"]]
        calls = []

        def opener(request, **_kwargs):
            calls.append(request.get_method())
            if request.get_method() == "POST":
                raise URLError("acknowledgement lost")
            raise HTTPError(request.full_url, 404, "not found", {}, None)

        ticks = [0.0]

        def clock():
            ticks[0] += 0.25
            return ticks[0]

        client = bulk_transport.GroupTransport(_cfg(), opener=opener, clock=clock)
        with self.assertRaises(bulk_transport.GroupTransportError) as caught:
            client.admit("bulk", jobs)
        self.assertEqual(caught.exception.kind, "group_ack_unknown")
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertEqual(calls, ["POST", "GET"])
        self.assertEqual(client.stats["http_wall_seconds"], 0.5)

    def test_run_refuses_live_lock_and_changed_execution_identity(self):
        task = _prepared(0)
        transport = _ScriptedTransport([])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "locked"
            root.mkdir()
            (root / "bulk_execution.lock").write_text("active", encoding="utf-8")
            source, atoms = Path(temp) / "source", Path(temp) / "atoms"
            source.mkdir(); atoms.mkdir()
            with patch.object(core, "prepare", return_value=[task]), \
                 patch.object(core.bench, "wait_capability") as capability, \
                 self.assertRaisesRegex(ValueError, "bulk_locked_manual_recovery_required"):
                core.run(core.build_manifest(_manifest(), workload_id="pilot_30"),
                         cfg=_cfg(), source_store=source, atom_root=atoms, arm="bulk",
                         output_root=root, execute=True, transport=transport)
            capability.assert_not_called()
            self.assertTrue((root / "bulk_execution.lock").exists())

            identity_root = Path(temp) / "identity-mismatch"
            identity_root.mkdir()
            core.write_json(identity_root / "execution_identity.json", {"arm": "corpus"})
            with patch.object(core, "prepare", return_value=[task]), \
                 patch.object(core.bench, "wait_capability") as capability, \
                 self.assertRaisesRegex(ValueError, "bulk_resume_identity_mismatch"):
                core.run(core.build_manifest(_manifest(), workload_id="pilot_30"),
                         cfg=_cfg(), source_store=source, atom_root=atoms, arm="bulk",
                         output_root=identity_root, execute=True, transport=transport)
            capability.assert_not_called()
            self.assertEqual(transport.admissions, [])

    def test_real_source_prepare_normalizes_deterministic_negative_without_inference(self):
        pipeline = Path(__file__).resolve().parents[1]
        manifest_path = pipeline / "outputs" / "bulk_trial30_20261013" / "manifest.json"
        source_store = pipeline / "outputs" / "source_store_v1"
        atom_root = pipeline / "outputs" / "plan04_sentence_atoms_v1"
        if not (manifest_path.is_file() and source_store.is_dir() and atom_root.is_dir()):
            self.skipTest("local frozen trial30 source/catalog artifacts are unavailable")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        tasks = core.prepare(manifest, source_store=source_store, atom_root=atom_root, arm="bulk")
        self.assertEqual(len(tasks), 30)
        task = tasks[0]
        compact = {"request_id": task["effective"]["request_id"],
                   "target_id": task["effective"]["expected_target_ids"][0],
                   "decision": "hard_negative", "coverage_status": "complete", "aus": [],
                   "hard_negative_reason": "other", "unresolved_reason": None}
        body = {"choices": [{"finish_reason": "stop",
                             "message": {"content": json.dumps(compact)}}],
                "usage": {"prompt_tokens": 19, "completion_tokens": 7, "total_tokens": 26}}
        capsule = task["capsule"]
        receipt = {"job_id": capsule["job_id"], "payload_sha256": capsule["job_id"],
                   "status": "completed", "response": body,
                   "response_sha256": bulk_transport.payload_digest(body), "usage": body["usage"]}
        normalized = core.normalize_receipt(receipt, task)
        self.assertEqual(normalized["status"], "protocol_verified")
        self.assertEqual(normalized["response"]["request_id"], task["effective"]["request_id"])
        self.assertEqual(normalized["response"]["processed_target_ids"],
                         task["effective"]["expected_target_ids"])
        self.assertEqual(normalized["response"]["target_results"][0]["target_id"],
                         task["effective"]["expected_target_ids"][0])
        self.assertEqual(normalized["response"]["target_results"][0]["authority_units"], [])
        self.assertEqual(normalized["receipt"]["usage"],
                         {"input_tokens": 19, "output_tokens": 7, "total_tokens": 26})
        self.assertFalse(normalized.get("semantic_quality_claim", False))


if __name__ == "__main__":
    unittest.main()
