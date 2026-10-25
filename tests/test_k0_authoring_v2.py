"""Independent protocol/runtime tests for the frozen-source K0 authoring v2 pilot.

These tests establish local contract and checkpoint behavior only. They do not
score AU correctness, semantic quality, or gold agreement, and never execute a
provider request.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.k0_authoring_v2 import core, runner, tools
from knowledge_base.pipeline_v1.kos_authoring_controls_v2 import controls


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "knowledge_base/pipeline_v1/outputs/k0_ready_20261023"
PROTECTED = ROOT / "knowledge_base/pipeline_v1/outputs/k0_v2_implementation_20261025/protected_before.json"
COUNTS = {"011904": (8, 21), "045155": (5, 30), "099980": (3, 7)}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AdvancingClock:
    """Deterministic monotonic clock; simulated sleeps advance deadlines."""
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.01
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, float(seconds))


class K0AuthoringV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = read_json(PARENT / "input/workload.json")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="k0-authoring-v2-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "run"
        self.workload = core.prepare(self.root)
        self.workload_path = self.root / "input/workload.json"
        self.cfg = core.runtime_config(self.workload["identity"])

    def case(self, case_id):
        return next(c for c in self.workload["cases"] if c["case_id"] == case_id)

    def job(self, case_id, state=None):
        case = self.case(case_id)
        state = state or tools.initial_state(case)
        return core.build_job(self.workload, case, state, self.cfg)

    def mock_run(self, **kwargs):
        clock = AdvancingClock()
        return runner.run(self.workload_path, self.root, mock=True, cfg=self.cfg,
                          clock=clock, sleep=clock.sleep, **kwargs)

    @staticmethod
    def valid_au(job, claim="The court applied a legal rule to the material facts."):
        return {"claim": claim, "kind": None,
                "evidence_ids": [next(iter(job["catalog"]["evidence"]))], "limits": None}

    def test_workload_is_exact_frozen_delivered_union_with_per_case_counts(self):
        self.assertEqual(core._parent(PARENT)[1]["cases"], self.parent["cases"])
        actual = {c["case_id"]: (len(c["scopes"]),
                    sum(len(s["evidence_ids"]) for s in c["scopes"]))
                  for c in self.workload["cases"]}
        self.assertEqual(actual, COUNTS)
        self.assertEqual(sum(x[0] for x in actual.values()), 16)
        self.assertEqual(sum(x[1] for x in actual.values()), 58)
        self.assertEqual(self.workload["semantic_quality"], "not_assessed")

    def test_preflight_and_initial_job_are_offline_bounded_and_three_field_wire(self):
        result = core.preflight(self.workload_path, cfg=self.cfg)
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["network_executed"])
        self.assertEqual((result["case_count"], result["scope_count"], result["part_count"]), (3, 16, 58))
        for case_id in COUNTS:
            job = self.job(case_id)
            self.assertLessEqual(job["input_reservation"], 6000)
            self.assertEqual(job["payload"]["max_tokens"], 800)
            self.assertEqual(job["payload_sha256"], core.fingerprint(job["payload"]))
            self.assertIn("empty_reason", job["payload"]["ebnf"])
            self.assertNotIn("assessed_scope_ids", job["payload"]["ebnf"])
            self.assertIn(json.dumps('"aus":'), job["payload"]["ebnf"].splitlines()[0])

    def test_wire_is_exact_and_missing_context_with_positive_au_stays_unresolved(self):
        job = self.job("045155")
        wire = {"aus": [self.valid_au(job)], "empty_reason": None,
                "next_action": {"tool": "finish_case", "reason": "needs_context"}}
        normalized = core.validate_response(wire, job)
        self.assertEqual(len(normalized["aus"]), 1)
        self.assertEqual(normalized["assessed_scope_ids"], [])
        self.assertEqual(normalized["unresolved_scope_ids"], job["active_scope_ids"])
        self.assertFalse(normalized["work_scope_complete"])
        self.assertEqual(normalized["semantic_quality"], "not_assessed")
        for malformed in (
            dict(wire, assessed_scope_ids=[]),
            {k: v for k, v in wire.items() if k != "empty_reason"},
            dict(wire, empty_reason="not-an-enum"),
        ):
            with self.subTest(keys=tuple(malformed)):
                with self.assertRaises((ValueError, TypeError)):
                    core.validate_response(malformed, job)

    def test_uncertain_empty_response_is_valid_without_forced_au_quota(self):
        job = self.job("011904")
        response = {"aus": [], "empty_reason": "insufficient_context",
                    "next_action": {"tool": "finish_case", "reason": "needs_context"}}
        normalized = core.validate_response(response, job)
        self.assertEqual(normalized["aus"], [])
        self.assertEqual(normalized["assessment_result"], "uncertain")
        self.assertEqual(normalized["unresolved_scope_ids"], job["active_scope_ids"])
        self.assertFalse(normalized["work_scope_complete"])
        empty_assessment = core.validate_response({"aus": [], "empty_reason": "no_independent_legal_point",
            "next_action": {"tool": "finish_case", "reason": "work_scope_complete"}}, job)
        self.assertEqual(empty_assessment["aus"], [])
        self.assertTrue(empty_assessment["work_scope_complete"])
        self.assertEqual(empty_assessment["assessment_result"], "no_au_candidate")

    def test_claim_wire_allows_legal_point_with_optional_kind_and_soft_length(self):
        job = self.job("099980")
        claim = ("The rule, its rationale, and the exception apply together to this dispute; "
                 "the court attributed that conclusion to the majority opinion. ") * 4
        response = {"aus": [self.valid_au(job, claim)], "empty_reason": None,
                    "next_action": {"tool": "finish_case", "reason": "work_scope_complete"}}
        normalized = core.validate_response(response, job)
        self.assertEqual(len(normalized["aus"]), 1)
        self.assertIsNone(normalized["aus"][0]["kind"])
        self.assertEqual(normalized["aus"][0]["semantic_quality"], "not_assessed")
        self.assertTrue(any(w["code"] == "length_threshold_exceeded" for w in normalized["warnings"]))

    def test_real_draft_ids_are_bound_for_replacement_and_unknown_ids_rejected(self):
        case = self.case("045155")
        state = tools.initial_state(case)
        state["drafts"] = {"k0au-" + "a" * 24: {"claim": "existing"}}
        job = core.build_job(self.workload, case, state, self.cfg)
        grammar = job["payload"]["ebnf"]
        self.assertIn("k0au-" + "a" * 24, grammar)
        item = self.valid_au(job)
        item["replace_id"] = "k0au-" + "a" * 24
        response = {"aus": [item], "empty_reason": None,
                    "next_action": {"tool": "finish_case", "reason": "work_scope_complete"}}
        self.assertEqual(len(core.validate_response(response, job)["aus"]), 1)
        item["replace_id"] = "k0au-" + "b" * 24
        self.assertEqual(core.validate_response(response, job)["au_errors"],
                         [{"index": 0, "code": "invalid_AU"}])

    def test_evidence_ids_must_be_in_current_delivered_case_catalog(self):
        job = self.job("045155")
        bad = self.valid_au(job)
        bad["evidence_ids"] = ["unopened-or-foreign-evidence"]
        response = {"aus": [bad], "empty_reason": None,
                    "next_action": {"tool": "finish_case", "reason": "work_scope_complete"}}
        normalized = core.validate_response(response, job)
        self.assertEqual(normalized["aus"], [])
        self.assertEqual(normalized["au_errors"], [{"index": 0, "code": "invalid_AU"}])
        self.assertEqual(normalized["unresolved_scope_ids"], job["active_scope_ids"])

        foreign_case = self.case("011904")
        foreign_ref = next(iter(foreign_case["evidence_catalog"].values()))
        injected_id = "foreign-evidence-test"
        job_with_foreign = copy.deepcopy(job)
        job_with_foreign["catalog"]["evidence"][injected_id] = foreign_ref
        foreign = self.valid_au(job_with_foreign)
        foreign["evidence_ids"] = [injected_id]
        response["aus"] = [foreign]
        rejected = core.validate_response(response, job_with_foreign)
        self.assertEqual(rejected["aus"], [])
        self.assertEqual(rejected["au_errors"], [{"index": 0, "code": "invalid_AU"}])

    def test_revisit_of_previously_assessed_active_scope_is_demoted_on_missing_context(self):
        case = self.case("011904")
        state = tools.initial_state(case)
        sid = case["scopes"][0]["scope_id"]
        # Model a durable state produced by an earlier completed assessment;
        # current response reopens the same scope and reports missing context.
        state["read_ledger"][sid].update(state="assessed", assessed=True)
        state["active_scope_ids"] = [sid]
        second_job = core.build_job(self.workload, case, state, self.cfg)
        second = core.validate_response({"aus": [self.valid_au(second_job)], "empty_reason": None,
            "next_action": {"tool": "finish_case", "reason": "needs_context"}}, second_job)
        state = tools.apply_turn(case, state, second)
        self.assertFalse(state["read_ledger"][sid]["assessed"])
        self.assertEqual(state["read_ledger"][sid]["state"], "unresolved")
        self.assertFalse(state["work_scope_complete"])

    def test_mock_run_checkpoints_resume_without_replaying_completed_jobs(self):
        opener_calls = []
        def no_network(*args, **kwargs):
            opener_calls.append((args, kwargs))
            raise AssertionError("mock must not use network")
        dry_clock = AdvancingClock()
        dry = runner.run(self.workload_path, self.root, mock=False, opener=no_network,
                         cfg=self.cfg, clock=dry_clock, sleep=dry_clock.sleep)
        first = self.mock_run(opener=no_network, max_new_requests=1)
        resumed = self.mock_run(opener=no_network)
        repeated = self.mock_run(opener=no_network)
        self.assertEqual(dry["status"], "not_executed")
        self.assertEqual(dry["provider_POST_attempts"], 0)
        self.assertEqual(first["status"], "incomplete")
        self.assertEqual(first["provider_POST_attempts"], 0)
        self.assertEqual(first["transport_POST_attempts"], 1)
        self.assertEqual(resumed["status"], "complete")
        self.assertTrue(resumed["execution_complete"])
        self.assertFalse(resumed["work_scope_complete"])
        self.assertFalse(resumed["semantic_pass"])
        self.assertTrue(all(row["state"]["case_status"] == "partial" for row in resumed["results"]))
        self.assertEqual(resumed["provider_POST_attempts"], 0)
        self.assertEqual(resumed["transport_POST_attempts"], 3)
        self.assertEqual(repeated["transport_POST_attempts"], 3)
        self.assertEqual(resumed["results"], repeated["results"])
        self.assertEqual(opener_calls, [])
        self.assertLessEqual(resumed["reserved_input_tokens"] + resumed["reserved_output_tokens"], 30000)

    def test_execute_gate_requires_native_cpu_and_live_control_proof_before_transport(self):
        with patch.object(core, "require_cpu", side_effect=ValueError("native proof missing")) as cpu, \
             patch.object(core, "require_controls") as proof, \
             patch.object(runner, "_adapter", side_effect=AssertionError("must stop at missing gate")) as adapter:
            with self.assertRaisesRegex(ValueError, "native proof missing"):
                runner.run(self.workload_path, self.root, execute=True, cfg=self.cfg,
                           opener=lambda *a, **k: self.fail("network request"))
        cpu.assert_called_once()
        proof.assert_not_called()
        adapter.assert_not_called()

        with patch.object(core, "require_cpu") as cpu, \
             patch.object(core, "require_controls", side_effect=ValueError("live controls missing")) as proof, \
             patch.object(runner, "_adapter", side_effect=AssertionError("must stop at missing control proof")) as adapter:
            with self.assertRaisesRegex(ValueError, "live controls missing"):
                runner.run(self.workload_path, self.root, execute=True, cfg=self.cfg,
                           opener=lambda *a, **k: self.fail("network request"))
        cpu.assert_called_once()
        proof.assert_called_once()
        adapter.assert_not_called()

    def test_current_control_proof_is_verified_offline_and_tampered_copy_is_rejected(self):
        control_root = Path(core.DEFAULT_CONTROLS)
        report_file = control_root / "recovered_report/report.json"
        self.assertTrue(report_file.is_file())
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline proof check used network")):
            verified = core.require_controls(control_root, self.workload)
        self.assertIsInstance(verified, str)
        self.assertEqual(len(verified), 64)

        clone = Path(self.temp.name) / "tampered-controls"
        shutil.copytree(control_root, clone)
        altered = read_json(clone / "recovered_report/report.json")
        altered["sha256"] = "0" * 64
        (clone / "recovered_report/report.json").write_text(json.dumps(altered), encoding="utf-8")
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline proof check used network")):
            with self.assertRaises((ValueError, TypeError, KeyError)):
                core.require_controls(clone, self.workload)

    def test_budget_caps_and_numeric_config_binding_are_stable_on_resume(self):
        integer_cfg = copy.deepcopy(self.cfg)
        defaults = {"readiness_seconds": 600, "job_wait_seconds": 600,
                    "job_poll_seconds": 1, "timeout": 60}
        for key, default in defaults.items():
            integer_cfg[key] = int(integer_cfg.get(key, default))
        clock1 = AdvancingClock()
        first = runner.run(self.workload_path, self.root, mock=True, cfg=integer_cfg,
                           clock=clock1, sleep=clock1.sleep)
        # The same logical bounds arriving as floats must bind to the same
        # persisted normalized config and resume without a digest mismatch.
        float_cfg = copy.deepcopy(integer_cfg)
        for key in defaults:
            float_cfg[key] = float(float_cfg[key])
        clock2 = AdvancingClock()
        second = runner.run(self.workload_path, self.root, mock=True, cfg=float_cfg,
                            clock=clock2, sleep=clock2.sleep)
        self.assertEqual(first["status"], "complete")
        self.assertEqual(second["status"], "complete")
        self.assertLessEqual(first["transport_POST_attempts"], 12)
        self.assertLessEqual(first["reserved_input_tokens"] + first["reserved_output_tokens"], 30000)
        self.assertTrue(all(row["job"]["input_reservation"] <= 6000
                            and row["job"]["payload"]["max_tokens"] <= 800
                            for row in read_json(self.root / "mock/runtime_ledger.json")["jobs"].values()))

    def test_tampered_mock_checkpoint_is_rejected_before_any_dispatch(self):
        self.mock_run()
        ledger_path = self.root / "mock/runtime_ledger.json"
        ledger = read_json(ledger_path)
        entry = next(iter(ledger["jobs"].values()))
        entry["job"]["input_reservation"] += 1
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        clock = AdvancingClock()
        with self.assertRaises((ValueError, TypeError, KeyError)):
            runner.run(self.workload_path, self.root, mock=True, cfg=self.cfg,
                       opener=lambda *a, **k: self.fail("tampered resume must not dispatch"),
                       clock=clock, sleep=clock.sleep)

    def test_all_72_protected_baseline_hashes_remain_unchanged(self):
        manifest = read_json(PROTECTED)
        self.assertEqual(len(manifest), 72)
        changed = {path: (expected, sha256(path)) for path, expected in manifest.items()
                   if not Path(path).is_file() or sha256(path) != expected}
        self.assertEqual(changed, {})


if __name__ == "__main__":
    unittest.main()
