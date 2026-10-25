"""Offline acceptance checks for the paired prefix-cache observation probe."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from knowledge_base.pipeline_v1.au_compact import runner
from knowledge_base.pipeline_v1.concurrency_benchmark import core as benchmark
from knowledge_base.pipeline_v1.deployments.modal import json_diagnostic
from knowledge_base.pipeline_v1.prefix_cache_probe import core as probe
from knowledge_base.pipeline_v1.milestone1.core import ROOT


PIPELINE = Path(__file__).resolve().parents[1]
PARENT_PATH = ROOT / "outputs/concurrency_step1_adapter_fix_20261012/manifest.json"
SOURCE_STORE = PIPELINE / "outputs/source_store_v1"
ATOM_ROOT = PIPELINE / "outputs/plan04_sentence_atoms_v1"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class PrefixCacheProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        needed = (PARENT_PATH, SOURCE_STORE / "source_store_manifest.json",
                  ATOM_ROOT / "sentence_atom_build_manifest.json")
        missing = [str(path) for path in needed if not path.is_file()]
        if missing:
            raise RuntimeError("prefix-cache fixtures missing: " + ", ".join(missing))
        cls.parent = _load(PARENT_PATH)
        cls.manifest = probe.build_manifest(cls.parent, probe_id="offline-independent")

    def test_locked_manifest_selects_the_median_target_once_per_case(self):
        original = copy.deepcopy(self.parent)
        manifest = probe.build_manifest(self.parent, probe_id="offline-independent")

        self.assertEqual(self.parent, original)
        self.assertEqual(len(manifest["selected_request_ids"]), 5)
        self.assertEqual(manifest["phases"], ["initial", "reuse"])
        self.assertEqual(manifest["source_request_count"], 10)
        self.assertEqual(manifest["client_inflight"], 1)
        self.assertFalse(manifest["cold_cache_claim"])
        selected = {q["request_id"]: q for q in manifest["parent"]["requests"]
                    if q["request_id"] in manifest["selected_request_ids"]}
        self.assertEqual(len(selected), 5)
        self.assertEqual({q["case_id"] for q in selected.values()}, benchmark.CASES)
        expected = set()
        for case in benchmark.CASES:
            rows = [q for q in self.parent["requests"] if q["case_id"] == case]
            rows.sort(key=lambda q: (
                sum(r["end_char"] - r["start_char"] for r in q["source_refs"]
                    if r["role"] == "target"), q["request_id"]))
            expected.add(rows[len(rows) // 2]["request_id"])
        self.assertEqual(set(manifest["selected_request_ids"]), expected)
        for request_id in expected:
            self.assertEqual(selected[request_id], next(
                q for q in self.parent["requests"] if q["request_id"] == request_id))

    def test_prepare_revalidates_parent_then_reconstructs_exact_paired_requests(self):
        tasks = probe.prepare(self.manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT)
        self.assertEqual(len(tasks), 10)
        self.assertEqual([t["phase"] for t in tasks], [
            phase for _request_id in self.manifest["selected_request_ids"]
            for phase in ("initial", "reuse")])
        original_by_id = {q["request_id"]: q for q in self.parent["requests"]}
        for initial, reuse in zip(tasks[::2], tasks[1::2]):
            base_id = initial["request"]["request_id"]
            self.assertEqual(base_id, reuse["request"]["request_id"])
            self.assertEqual(initial["request"], original_by_id[base_id])
            self.assertEqual(reuse["request"], original_by_id[base_id])
            self.assertNotEqual(initial["effective"]["request_id"],
                                reuse["effective"]["request_id"])
            for field in ("case_id", "source_hash", "expected_target_ids",
                          "source_refs", "spec", "atom_binding"):
                self.assertEqual(initial["effective"][field], reuse["effective"][field], field)
            p_initial = runner.build_prompt(initial["effective"], initial["rendered"])
            p_reuse = runner.build_prompt(reuse["effective"], reuse["rendered"])
            self.assertEqual(p_initial.replace(initial["effective"]["request_id"], "<ID>"),
                             p_reuse.replace(reuse["effective"]["request_id"], "<ID>"))
            atoms = initial["catalog"]["atoms"]
            ids = list(atoms)
            targets = [aid for aid, atom in atoms.items() if atom["target_intersecting"]]
            g_initial = runner.build_decoding(initial["effective"]["request_id"],
                initial["effective"]["expected_target_ids"][0], ids, targets)["ebnf"]
            g_reuse = runner.build_decoding(reuse["effective"]["request_id"],
                reuse["effective"]["expected_target_ids"][0], ids, targets)["ebnf"]
            self.assertEqual(g_initial.replace(initial["effective"]["request_id"], "<ID>"),
                             g_reuse.replace(reuse["effective"]["request_id"], "<ID>"))

    @staticmethod
    def _tasks(manifest):
        tasks = []
        for i, request_id in enumerate(manifest["selected_request_ids"]):
            for phase in ("initial", "reuse"):
                effective = {"request_id": f"{request_id}-{phase}",
                    "expected_target_ids": [f"target-{i}"], "case_id": f"case-{i}"}
                original = {"request_id": request_id, "case_id": f"case-{i}"}
                tasks.append({"request": original, "effective": effective,
                    "phase": phase, "rendered": "fixed source prompt",
                    "catalog": {"atoms": {}}, "binding": {}, "source": "fixed source"})
        return tasks

    @staticmethod
    def _cfg():
        return {"url": "https://c4--coliee-qwen35-9b-concurrency-server.us-west.modal.direct/v1/chat/completions",
                "token": "private-test-token", "model": benchmark.MODEL,
                "enable_thinking": False}

    @staticmethod
    def _capability(**overrides):
        value = {"experiment": benchmark.VERSION, "gateway_concurrency": 4,
            "server_concurrency": 4, "model": benchmark.MODEL, "max_containers": 1,
            "gpu": "L40S:1", "context_length": 12288, "max_total_tokens": 12288,
            "cuda_graph_max_bs": 4, "exclusive_probes": True, "backend_retry": False,
            "model_revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "job_volume": "coliee-qwen35-9b-concurrency-jobs", "job_store_subdir": "c4",
            "ready": True, "poisoned": False, "stopping": False,
            "backend_outcome_unknown": False}
        value.update(overrides)
        return value

    @staticmethod
    def _diagnostic(enabled=True):
        return {"backend": {"get_server_info": {"fields": {"server_args": {
            "enable_cache_report": enabled,
            "mamba_radix_cache_strategy": "extra_buffer"}}}}}

    @staticmethod
    def _receipt(*, cached=20, prompt=100, submit_attempts=1, event_status=404,
                 failure=None):
        receipt = {"finish_reason": "stop",
            "usage": {"input_tokens": prompt, "output_tokens": 3,
                      "total_tokens": prompt + 3},
            "cache_observation": {"state": "provider", "cached_tokens": cached,
                                  "prompt_tokens": prompt,
                                  "cached_fraction": cached / prompt if prompt else None},
            "latency_ms": 1,
            "transport_trace": {"submit_attempts": submit_attempts,
                "events": [{"method": "GET", "http_status": event_status}],
                "server_timing": {"inference_seconds": 0.25}}}
        if failure:
            receipt["failure_diagnostic"] = failure
            receipt["finish_reason"] = "host_unresolved"
        return receipt

    def _run(self, root, *, caller=None, diagnostic=None, capability=None):
        tasks = self._tasks(self.manifest)
        return probe.run(self.manifest, cfg=self._cfg(), source_store=SOURCE_STORE,
            atom_root=ATOM_ROOT, output_root=root, execute=True,
            capability_fetch=Mock(return_value=capability or self._capability()),
            diagnostic_fetch=Mock(return_value=diagnostic or self._diagnostic()),
            warmup_fn=Mock(return_value={"status": "success"}),
            caller=caller, policy={"max_attempts": 1, "max_wait_seconds": 1})

    def test_run_dispatches_sequential_pairs_through_real_default_adapter_signature(self):
        tasks = self._tasks(self.manifest)
        compact = {"decision": "hard_negative", "hard_negative_reason": "other"}
        receipt = self._receipt()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(probe, "prepare", return_value=tasks), \
             patch.object(runner, "_normalize", return_value={"target_results": []}), \
             patch.object(runner, "deduplicate_lists", return_value=(compact, {})), \
             patch.object(benchmark, "_default_call", autospec=True,
                          return_value=(compact, copy.deepcopy(receipt))) as default_call:
            result = self._run(Path(directory) / "probe")

        self.assertEqual(default_call.call_count, 10)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["fresh_measurement_eligible"])
        self.assertEqual(result["protocol_verified"], 10)
        for call, task in zip(default_call.call_args_list, tasks):
            self.assertEqual(call.args[0]["transport"], "jobs")
            self.assertEqual(call.args[1], task["effective"])
            self.assertEqual(call.args[2], task["rendered"])
            self.assertEqual(call.kwargs["catalog"], task["catalog"])

    def test_actual_cache_flag_is_a_gate_before_any_source_dispatch(self):
        tasks = self._tasks(self.manifest)
        caller = Mock(side_effect=AssertionError("source call must be gated"))
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(probe, "prepare", return_value=tasks):
            with self.assertRaisesRegex(ValueError, "runtime_cache_report_not_enabled"):
                self._run(Path(directory) / "probe", caller=caller,
                          diagnostic=self._diagnostic(enabled=False))
        caller.assert_not_called()

    def test_execute_gate_rejects_before_prepare_or_remote_capability(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(probe, "prepare", side_effect=AssertionError("prepare must not run")) as prepare, \
             patch.object(benchmark, "wait_capability", side_effect=AssertionError("remote gate must not run")) as wait:
            with self.assertRaisesRegex(ValueError, "prefix_probe_requires_execute"):
                probe.run(self.manifest, cfg={}, source_store=SOURCE_STORE,
                    atom_root=ATOM_ROOT, output_root=Path(directory) / "probe", execute=False)
        prepare.assert_not_called()
        wait.assert_not_called()

    def test_summary_excludes_job_reuse_and_keeps_missing_cache_unknown(self):
        rows = [
            {"request": {"request_id": "fresh"}, "phase": "initial",
             "status": "protocol_verified", "receipt": self._receipt(cached=8)},
            {"request": {"request_id": "reused-job"}, "phase": "reuse",
             "status": "protocol_verified", "receipt": self._receipt(
                 cached=90, submit_attempts=0)},
            {"request": {"request_id": "retried-submit"}, "phase": "initial",
             "status": "protocol_verified", "receipt": self._receipt(
                 cached=90, submit_attempts=2)},
            {"request": {"request_id": "missing"}, "phase": "reuse",
             "status": "protocol_verified", "receipt": {"usage": None,
                 "cache_observation": {"state": "unavailable", "cached_tokens": None,
                                       "prompt_tokens": None},
                 "transport_trace": {"submit_attempts": 1,
                    "events": [{"method": "GET", "http_status": 404}]}}},
        ]
        report = probe.summarize(rows, expected_count=4)
        self.assertEqual(report["provider_report_count"], 1)
        self.assertTrue(report["cache_hit_observed"])
        self.assertEqual(report["cached_tokens"], 8)
        self.assertFalse(report["cache_observations"][1]["fresh_server_job"])
        self.assertEqual(report["cache_observations"][1]["state"], "provider")
        self.assertIsNone(report["cache_observations"][1]["cached_tokens"])
        self.assertIsNone(report["cache_observations"][1]["prompt_tokens"])
        self.assertEqual(rows[1]["receipt"]["cache_observation"]["cached_tokens"], 90)
        self.assertIsNone(report["cache_observations"][3]["cached_tokens"])
        self.assertIsNone(probe.summarize([rows[3]], expected_count=1)["cache_hit_observed"])
        self.assertFalse(report["causal_speedup_claim"])
        self.assertFalse(report["billing_discount_claim"])
        self.assertFalse(report["cold_cache_claim"])

    def test_resume_reuses_rows_but_is_never_fresh_performance_evidence(self):
        tasks = self._tasks(self.manifest)
        compact = {"decision": "hard_negative", "hard_negative_reason": "other"}
        first_caller = Mock(return_value=(compact, self._receipt()))
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(probe, "prepare", return_value=tasks), \
             patch.object(runner, "_normalize", return_value={"target_results": []}), \
             patch.object(runner, "deduplicate_lists", return_value=(compact, {})):
            root = Path(directory) / "probe"
            self._run(root, caller=first_caller)
            first_count = first_caller.call_count
            resumed = self._run(root, caller=Mock(side_effect=AssertionError(
                "cached rows must not be dispatched again")))

        self.assertEqual(first_count, 10)
        self.assertEqual(resumed["completed_count"], 10)
        self.assertTrue(resumed["resume_or_client_cache"])
        self.assertFalse(resumed["fresh_measurement_eligible"])
        self.assertFalse(resumed["causal_speedup_claim"])

    def test_failure_stops_admission_and_resume_does_not_duplicate_uncertain_job(self):
        tasks = self._tasks(self.manifest)
        unknown = runner.CompactRunError(json.dumps({"usage": None,
            "failure_diagnostic": {"kind": "job_wait_timeout", "retryable": True,
                                    "outcome": "server_job_may_continue"}}))
        caller = Mock(side_effect=unknown)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(probe, "prepare", return_value=tasks):
            root = Path(directory) / "probe"
            first = self._run(root, caller=caller)
            attempted = caller.call_count
            resume_caller = Mock(side_effect=AssertionError("uncertain job must not be resubmitted"))
            resumed = self._run(root, caller=resume_caller)

        self.assertEqual(attempted, 1)
        self.assertTrue(first["stop_dispatch"])
        self.assertFalse(first["fresh_measurement_eligible"])
        self.assertEqual(resumed["completed_count"], 1)
        self.assertTrue(resumed["stop_dispatch"])
        self.assertTrue(resumed["resume_or_client_cache"])
        self.assertFalse(resumed["fresh_measurement_eligible"])
        resume_caller.assert_not_called()

    def test_runtime_diagnostic_filter_whitelists_cache_flag_and_strategy_only(self):
        raw = {"enable_cache_report": True,
               "mamba_radix_cache_strategy": "extra_buffer",
               "credential": "private-token", "unknown_field": "private-value",
               "server_args": {"enable_cache_report": True,
                   "mamba_radix_cache_strategy": "extra_buffer",
                   "token": "private-token", "arbitrary": "private-value"}}
        filtered = json_diagnostic.filtered_info(raw)
        self.assertEqual(filtered, {"enable_cache_report": True,
            "mamba_radix_cache_strategy": "extra_buffer",
            "server_args": {"enable_cache_report": True,
                             "mamba_radix_cache_strategy": "extra_buffer"}})
        self.assertNotIn("private", json.dumps(filtered))

    def test_cache_report_flag_is_experimental_and_baseline_server_args_stay_unchanged(self):
        experimental = (PIPELINE / "deployments/modal/qwen35_9b_concurrency.py").read_text(
            encoding="utf-8")
        baseline = (PIPELINE / "deployments/modal/qwen35_9b_l40s.py").read_text(
            encoding="utf-8")
        self.assertIn('"--enable-cache-report": ""', experimental)
        self.assertNotIn('"--enable-cache-report": ""', baseline)


if __name__ == "__main__":
    unittest.main()
