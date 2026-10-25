"""Independent, offline contract tests for the M1 concurrency benchmark."""
from __future__ import annotations

import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from knowledge_base.pipeline_v1.au_compact.core import build_evidence_catalog
from knowledge_base.pipeline_v1.au_compact.prompting import build_prompt
from knowledge_base.pipeline_v1.au_compact.runner import _render
from knowledge_base.pipeline_v1.au_compact.decoding import build_decoding
from knowledge_base.pipeline_v1.au_compact.manifest import _binding_path
from knowledge_base.pipeline_v1.source_contract import open_source
from knowledge_base.pipeline_v1.concurrency_benchmark import core
from knowledge_base.pipeline_v1.concurrency_benchmark import __main__ as benchmark_cli


PIPELINE = Path(__file__).resolve().parents[1]
PARENT_MANIFEST = PIPELINE / "manifests/au_compact_kos5_full_m1.v1.json"
SOURCE_STORE = PIPELINE / "outputs/source_store_v1"
ATOM_ROOT = PIPELINE / "outputs/plan04_sentence_atoms_v1"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class ConcurrencyBenchmarkIndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [str(path) for path in (PARENT_MANIFEST,
                   SOURCE_STORE / "source_store_manifest.json",
                   ATOM_ROOT / "sentence_atom_build_manifest.json") if not path.is_file()]
        if missing:
            raise RuntimeError("M1 concurrency fixtures missing: " + ", ".join(missing))
        cls.parent = _load(PARENT_MANIFEST)
        cls.manifest = core.build_manifest(cls.parent, source_store=SOURCE_STORE,
            atom_root=ATOM_ROOT, count=30, benchmark_id="offline-independent-test")

    def test_manifest_selects_thirty_per_case_length_quantiles_in_parent_order(self):
        before = copy.deepcopy(self.parent)
        manifest = self.manifest
        self.assertEqual(self.parent, before)
        self.assertEqual(len(manifest["requests"]), 30)
        selected = manifest["requests"]
        expected = set()
        for case_id in sorted(core.CASES):
            case_rows = [q for q in self.parent["requests"] if q["case_id"] == case_id]
            case_rows.sort(key=lambda q: (
                sum(r["end_char"]-r["start_char"] for r in q["source_refs"]
                    if r["role"] == "target"), q["request_id"]))
            self.assertGreaterEqual(len(case_rows), 6)
            expected.update(case_rows[round(j*(len(case_rows)-1)/5)]["request_id"]
                             for j in range(6))
        self.assertEqual([q["request_id"] for q in selected],
                         [q["request_id"] for q in self.parent["requests"]
                          if q["request_id"] in expected])
        self.assertEqual({case: sum(q["case_id"] == case for q in selected)
                          for case in core.CASES}, {case: 6 for case in core.CASES})
        for request in selected:
            original = next(q for q in self.parent["requests"]
                            if q["request_id"] == request["request_id"])
            self.assertEqual(request["source_hash"], original["source_hash"])
            self.assertEqual(request["case_id"], original["case_id"])
            self.assertEqual(request["expected_target_ids"], original["expected_target_ids"])
            self.assertEqual(request["source_refs"], original["source_refs"])
            self.assertEqual(request["spec"], original["spec"])
            self.assertEqual(request["atom_binding"], original["atom_binding"])
            self.assertEqual(request["request_id"], original["request_id"])

    def test_benchmark_salt_changes_request_and_grammar_identity_only(self):
        manifest = self.manifest
        tasks = core.prepare(manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT)
        for task, original in zip(tasks, manifest["requests"]):
            left = core._effective(original, manifest, 1)
            right = core._effective(original, manifest, 2)
            self.assertNotEqual(left["request_id"], right["request_id"])
            for field in ("case_id", "source_hash", "expected_target_ids",
                          "source_refs", "spec", "atom_binding", "hint_payload"):
                self.assertEqual(left[field], right[field], field)
                self.assertEqual(left[field], original[field], field)

            catalog = task["catalog"]
            left_rendered = _render(left, catalog)
            original_rendered = _render(original, catalog)
            self.assertEqual(build_prompt(left, left_rendered).replace(
                left["request_id"], original["request_id"]),
                build_prompt(original, original_rendered))
            atom_ids = list(catalog["atoms"])
            target_atoms = [atom_id for atom_id, atom in catalog["atoms"].items()
                            if atom["target_intersecting"]]
            left_grammar = build_decoding(left["request_id"], left["expected_target_ids"][0],
                                          atom_ids, target_atoms)["ebnf"]
            original_grammar = build_decoding(original["request_id"],
                original["expected_target_ids"][0], atom_ids, target_atoms)["ebnf"]
            self.assertEqual(left_grammar.replace(left["request_id"], original["request_id"]),
                             original_grammar)

    def test_prepare_revalidates_original_source_and_catalog_without_remote_calls(self):
        manifest = self.manifest
        tasks = core.prepare(manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT)
        self.assertEqual(len(tasks), 30)
        for task, request in zip(tasks[:3], manifest["requests"][:3]):
            self.assertEqual(task["request"], request)
            source = open_source(SOURCE_STORE, request["case_id"], request["source_hash"])
            self.assertEqual(task["source"], source)
            expected_binding = _binding_path(request["atom_binding"], ATOM_ROOT)
            self.assertEqual(task["binding"], expected_binding)
            expected_catalog = build_evidence_catalog(request, expected_binding, source)
            self.assertEqual(task["catalog"], expected_catalog)

    def test_prepare_rejects_tampered_source_identity(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["requests"][0]["source_hash"] = "0" * 64
        with self.assertRaises((ValueError, KeyError)):
            core.prepare(manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT)

    def test_arm_prompt_and_grammar_preserve_source_fields_and_salt_ids(self):
        manifest = self.manifest
        tasks = core.prepare(manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT)
        for task, original in zip(tasks, manifest["requests"]):
            effective = task["request"]
            rendered = _render(effective, task["catalog"])
            original_rendered = _render(original, task["catalog"])
            effective_prompt = build_prompt(effective, rendered)
            original_prompt = build_prompt(original, original_rendered)
            self.assertEqual(effective_prompt.replace(effective["request_id"],
                                                       original["request_id"]),
                             original_prompt)
            catalog_ids = list(task["catalog"]["atoms"])
            target_ids = [atom_id for atom_id, atom in task["catalog"]["atoms"].items()
                          if atom["target_intersecting"]]
            effective_grammar = build_decoding(effective["request_id"],
                effective["expected_target_ids"][0], catalog_ids, target_ids)
            original_grammar = build_decoding(original["request_id"],
                original["expected_target_ids"][0], catalog_ids, target_ids)
            self.assertEqual(effective_grammar["ebnf"].replace(effective["request_id"],
                                                                 original["request_id"]),
                             original_grammar["ebnf"])

    def test_execute_false_is_a_strict_no_remote_preflight(self):
        manifest = self.manifest
        caller = Mock(side_effect=AssertionError("remote caller invoked"))
        capability_fetch = Mock(side_effect=AssertionError("capability fetch invoked"))
        warmup_fn = Mock(side_effect=AssertionError("warmup invoked"))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "arm"
            with self.assertRaises(ValueError):
                core.run(manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT,
                         cfg={"model": manifest["requests"][0]["spec"]["model"]},
                         concurrency=1, output_root=output, execute=False,
                         capability_fetch=capability_fetch, caller=caller,
                         warmup_fn=warmup_fn)
            self.assertFalse(output.exists())
        caller.assert_not_called()
        capability_fetch.assert_not_called()
        warmup_fn.assert_not_called()

    @staticmethod
    def _mock_manifest(count=10):
        cases = ["011904", "013009", "013948", "045155", "099980"]
        requests = [{"request_id": f"original-{i}", "case_id": cases[i % len(cases)],
                    "expected_target_ids": [f"target-{i}"]} for i in range(count)]
        return {"benchmark_id": "offline-state-test", "requests": requests}

    @staticmethod
    def _mock_tasks(manifest):
        return [{"request": q, "source": "fixed source", "binding": {},
                 "catalog": {"atoms": {}}, "rendered": "fixed rendered source"}
                for q in manifest["requests"]]

    @staticmethod
    def _capability_info(concurrency, **overrides):
        info = {"experiment": core.VERSION, "gateway_concurrency": concurrency,
                "server_concurrency": concurrency, "max_containers": 1,
                "model": core.MODEL, "context_length": 12288,
                "max_total_tokens": 12288, "ready": True,
                "backend_outcome_unknown": False, "app": "coliee-qwen35-9b-concurrency",
                "backend_retry": False, "exclusive_probes": True,
                "cuda_graph_max_bs": concurrency, "gpu": "L40S:1",
                "model_revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
                "job_volume": "coliee-qwen35-9b-concurrency-jobs",
                "job_store_subdir": f"c{concurrency}", "cpu": 4,
                "memory_mb": 16384, "poisoned": False, "stopping": False}
        info.update(overrides)
        return info

    @staticmethod
    def _valid_compact(request):
        return {"request_id": request["request_id"],
                "target_id": request["expected_target_ids"][0],
                "decision": "hard_negative", "coverage_status": "complete", "aus": [],
                "hard_negative_reason": "citation_without_proposition",
                "unresolved_reason": None}

    def _run_mocked(self, manifest, root, concurrency, caller, *, capability_info=None,
                    capability_fetch=None, warmup_fn=None, warmup_policy=None):
        cfg = {"url": f"https://host--coliee-qwen35-9b-concurrency-server.modal.run/v1/chat/completions",
               "token": "test-token", "model": core.MODEL, "enable_thinking": False}
        fetch = capability_fetch or Mock(return_value=capability_info or
                                         self._capability_info(concurrency))
        with patch.object(core, "prepare", return_value=self._mock_tasks(manifest)), \
             patch.object(core.runner, "_normalize", return_value={"target_results": []}):
            return core.run(manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT,
                cfg=cfg, concurrency=concurrency, output_root=root, execute=True,
                capability_fetch=fetch,
                warmup_fn=warmup_fn or Mock(return_value={"status": "success"}),
                caller=caller, warmup_policy=warmup_policy)

    def test_run_worker_pool_caps_active_callers_at_two_and_four(self):
        for limit in (2, 4):
            with self.subTest(concurrency=limit), tempfile.TemporaryDirectory() as temporary:
                manifest = self._mock_manifest(10)
                active = 0
                maximum = 0
                calls = []
                lock = threading.Lock()

                def caller(_cfg, request, _rendered, *, catalog):
                    nonlocal active, maximum
                    with lock:
                        active += 1
                        maximum = max(maximum, active)
                        calls.append(request["request_id"])
                    time.sleep(0.03)
                    with lock:
                        active -= 1
                    return self._valid_compact(request), {"finish_reason": "stop",
                        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                        "latency_ms": 30}

                result = self._run_mocked(manifest, Path(temporary) / f"c{limit}",
                                          limit, caller)
                self.assertEqual(len(calls), 10)
                self.assertEqual(maximum, limit)
                self.assertLessEqual(maximum, limit)
                self.assertEqual(result["completed_count"], 10)
                self.assertTrue(result["performance_eligible"])

    def test_resume_with_reservation_but_no_cache_is_not_performance_eligible(self):
        manifest = self._mock_manifest(10)
        concurrency = 2
        root = Path(tempfile.mkdtemp())
        try:
            effective = core._effective(manifest["requests"][0], manifest, concurrency)
            reservation = root / "reservations" / (effective["request_id"] + ".json")
            reservation.parent.mkdir(parents=True)
            reservation.write_text("{}", encoding="utf-8")
            self.assertFalse((root / "cache").exists())

            def caller(_cfg, request, _rendered, *, catalog):
                return self._valid_compact(request), {"finish_reason": "stop",
                    "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                    "latency_ms": 1}

            result = self._run_mocked(manifest, root, concurrency, caller)
            self.assertEqual(result["cache_hits"], 0)
            self.assertFalse(result["performance_eligible"])
            self.assertIsNone(result["targets_per_second"])
        finally:
            import shutil
            shutil.rmtree(root)

    def test_transport_unknown_stops_new_admission(self):
        manifest = self._mock_manifest(10)
        calls = []

        def caller(_cfg, request, _rendered, *, catalog):
            calls.append(request["request_id"])
            receipt = {"finish_reason": "host_unresolved", "usage": None,
                       "usage_state": "unavailable",
                       "failure_diagnostic": {"kind": "transport", "retryable": True}}
            from knowledge_base.pipeline_v1.au_compact.runner import CompactRunError
            raise CompactRunError(json.dumps(receipt))

        with tempfile.TemporaryDirectory() as temporary:
            result = self._run_mocked(manifest, Path(temporary) / "c1", 1, caller)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result["stop_dispatch"])
        self.assertEqual(result["completed_count"], 1)
        self.assertFalse(result["performance_eligible"])

    def test_capability_gate_rejects_unsafe_gateway_configuration_before_warmup(self):
        manifest = self._mock_manifest(10)
        warmup = Mock(return_value={"status": "success"})
        caller = Mock(return_value=(None, {}))
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                self._run_mocked(manifest, Path(temporary) / "c1", 1, caller,
                    capability_info=self._capability_info(1, backend_retry=True,
                                                          exclusive_probes=False),
                    warmup_fn=warmup)
        warmup.assert_not_called()
        caller.assert_not_called()

    def test_capability_startup_retries_503_before_one_injected_warmup(self):
        manifest = self._mock_manifest(10)
        concurrency = 2
        attempts = []
        info = self._capability_info(concurrency)

        def fetch(_cfg):
            attempts.append(True)
            if len(attempts) == 1:
                raise HTTPError("https://endpoint.invalid/health", 503,
                                "starting", {}, io.BytesIO(b"starting"))
            return info

        warmup = Mock(return_value={"status": "success"})

        def caller(_cfg, request, _rendered, *, catalog):
            return self._valid_compact(request), {"finish_reason": "stop",
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                "latency_ms": 1}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "c2"
            result = self._run_mocked(manifest, root, concurrency, caller,
                capability_fetch=fetch, warmup_fn=warmup,
                warmup_policy={"max_attempts": 2, "max_wait_seconds": 2,
                               "initial_backoff_seconds": 0})
            self.assertEqual(result["status"], "complete")
            startup = json.loads((root / "capability_startup.json").read_text(encoding="utf-8"))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(warmup.call_count, 1)
        self.assertEqual([event["http_status"] for event in startup["attempts"][:1]], [503])

    def test_endpoint_hostname_is_restricted_before_capability_or_warmup(self):
        manifest = self._mock_manifest(10)
        cfg = {"url": "https://attacker.invalid/--coliee-qwen35-9b-concurrency-server.fake/v1/chat/completions",
               "token": "test-token", "model": core.MODEL, "enable_thinking": False}
        capability_fetch = Mock(return_value=self._capability_info(1))
        warmup = Mock(return_value={"status": "success"})
        caller = Mock(return_value=(None, {}))
        with patch.object(core, "prepare", return_value=self._mock_tasks(manifest)):
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(ValueError):
                    core.run(manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT,
                        cfg=cfg, concurrency=1, output_root=Path(temporary) / "c1",
                        execute=True, capability_fetch=capability_fetch,
                        warmup_fn=warmup, caller=caller)
        capability_fetch.assert_not_called()
        warmup.assert_not_called()
        caller.assert_not_called()

    def test_baseline_runtime_ledger_root_is_rejected_without_mutation_or_remote_calls(self):
        manifest = self._mock_manifest(10)
        cfg = {"url": "https://host--coliee-qwen35-9b-concurrency-server.modal.run/v1/chat/completions",
               "token": "test-token", "model": core.MODEL, "enable_thinking": False}
        capability_fetch = Mock(return_value=self._capability_info(1))
        warmup = Mock(return_value={"status": "success"})
        caller = Mock(return_value=(None, {}))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "existing-baseline"
            root.mkdir()
            sentinel = root / "runtime_ledger.json"
            sentinel.write_text('{"baseline":"preserve"}', encoding="utf-8")
            original = sentinel.read_bytes()
            with patch.object(core, "prepare", return_value=self._mock_tasks(manifest)):
                with self.assertRaises(ValueError):
                    core.run(manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT,
                        cfg=cfg, concurrency=1, output_root=root, execute=True,
                        capability_fetch=capability_fetch, warmup_fn=warmup, caller=caller)
            self.assertEqual(sentinel.read_bytes(), original)
            self.assertEqual(set(p.name for p in root.iterdir()), {"runtime_ledger.json"})
        capability_fetch.assert_not_called()
        warmup.assert_not_called()
        caller.assert_not_called()

    def test_cli_preflight_does_not_write_into_a_baseline_output_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "baseline-output"
            root.mkdir()
            sentinel = root / "runtime_ledger.json"
            sentinel.write_text('{"baseline":"preserve"}', encoding="utf-8")
            original = sentinel.read_bytes()
            argv = ["concurrency_benchmark", "preflight",
                    "--manifest", str(PIPELINE / "outputs/concurrency_step1_20261012/manifest.json"),
                    "--source-store", str(SOURCE_STORE), "--atom-root", str(ATOM_ROOT),
                    "--output-root", str(root)]
            output = io.StringIO()
            with patch.object(sys, "argv", argv), redirect_stdout(output):
                status = benchmark_cli.main()
            self.assertNotEqual(status, 0,
                "CLI preflight must refuse baseline output roots before writing a report")
            self.assertEqual(sentinel.read_bytes(), original)
            self.assertEqual({path.name for path in root.iterdir()}, {"runtime_ledger.json"})

    def test_compare_requires_protocol_and_full_target_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for concurrency in (1, 2, 4):
                arm = root / f"c{concurrency}"
                arm.mkdir()
                row = {"original_request": {"request_id": "target-1"},
                       "request": {"request_id": f"arm-{concurrency}"},
                       "status": "unresolved",
                       "compact_response": {"request_id": f"arm-{concurrency}",
                                            "coverage_status": "needs_split"}}
                report = {"identity": {"manifest_sha256": "same-manifest"},
                          "concurrency": concurrency, "status": "complete",
                          "performance_eligible": True, "protocol_pass": False,
                          "expected_count": 2, "completed_count": 1,
                          "request_ledger": [row], "wall_seconds": 1.0,
                          "targets_per_second": 1.0, "latency_ms": {}, "tokens": {},
                          "cache_hits": 0, "needs_split": 1}
                (arm / "run.json").write_text(json.dumps(report), encoding="utf-8")
            summary = core.compare(root)
            self.assertFalse(summary["comparable_fresh"])

    def test_compare_ignores_only_request_id_when_listing_output_differences(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for concurrency in (1, 2, 4):
                arm = root / f"c{concurrency}"
                arm.mkdir()
                row = {"original_request": {"request_id": "target-1"},
                       "request": {"request_id": f"arm-{concurrency}"},
                       "status": "protocol_verified",
                       "compact_response": {"request_id": f"arm-{concurrency}",
                           "target_id": "target-1", "decision": "hard_negative",
                           "coverage_status": "complete", "aus": []}}
                report = {"identity": {"manifest_sha256": "same-manifest"},
                          "concurrency": concurrency, "status": "complete",
                          "performance_eligible": True, "protocol_pass": True,
                          "expected_count": 1, "completed_count": 1,
                          "request_ledger": [row], "wall_seconds": 1.0,
                          "targets_per_second": 1.0, "latency_ms": {}, "tokens": {},
                          "cache_hits": 0, "needs_split": 0}
                (arm / "run.json").write_text(json.dumps(report), encoding="utf-8")
            summary = core.compare(root)
            self.assertTrue(summary["comparable_fresh"])
            self.assertEqual(summary["changed_output_request_ids"],
                             {"1": [], "2": [], "4": []})


if __name__ == "__main__":
    unittest.main()
