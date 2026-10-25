"""Independent protocol and recovery regressions for authoring controls v2.

These are local contract tests only. The fictional controls establish wire and
host-state behavior; they do not measure AU quality or treat model_silver as gold.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from knowledge_base.pipeline_v1.k0_authoring import core as k0
from knowledge_base.pipeline_v1.kos_authoring_controls import controls as frozen_v1
from knowledge_base.pipeline_v1.kos_authoring_controls import execution as shared_execution
from knowledge_base.pipeline_v1.kos_authoring_controls_v2 import controls
from knowledge_base.pipeline_v1.kos_authoring_controls_v2 import __main__ as cli


def response(*, aus=None, reason=None, action=None, **extra):
    value = {"aus": [] if aus is None else aus,
             "empty_reason": reason,
             "next_action": action or {"tool": "finish_case", "reason": "work_scope_complete"}}
    value.update(extra)
    return value


class FrozenFixtureParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = k0.load(frozen_v1.BASELINE / "input/manifest.json")
        model = manifest["jobs"][0]["job"]["payload"]["model"]
        cls.v1_rows = frozen_v1.balanced_jobs({"model": model})
        cls.v2_rows = controls.balanced_jobs({"model": model})

    def test_nine_fictional_source_and_identifier_fixtures_match_frozen_v1(self):
        self.assertEqual(len(self.v1_rows), 9)
        self.assertEqual(len(self.v2_rows), 9)
        for before, after in zip(self.v1_rows, self.v2_rows):
            with self.subTest(name=before["name"]):
                old_job, new_job = before["validation_job"], after["validation_job"]
                self.assertEqual(after["name"], before["name"])
                self.assertEqual(new_job["case_id"], old_job["case_id"])
                self.assertEqual(new_job["source_hash"], old_job["source_hash"])
                self.assertEqual(new_job["active_scope_ids"], old_job["active_scope_ids"])
                self.assertEqual(new_job["catalog"]["evidence"], old_job["catalog"]["evidence"])
                self.assertEqual(after["expected"], before["expected"])

    def test_captured_v1_uncertain_intents_remain_unresolved_without_wire_assessment(self):
        # The frozen v1 records identify intent. This test only maps that intent
        # into v2 host state; it does not rewrite or upgrade any v1 result.
        for row in self.v1_rows:
            if row["expected"]["group"] != "uncertain":
                continue
            job = row["validation_job"]
            normalized = controls.validate(
                response(reason="uncertain", action={"tool": "finish_case", "reason": "needs_context"}),
                job,
            )
            self.assertEqual(normalized["delivered_scope_ids"], job["active_scope_ids"])
            self.assertEqual(normalized["assessed_scope_ids"], [])
            self.assertEqual(normalized["next_action"], {"tool": "finish_case", "reason": "needs_context"})


class WireAndHostStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = FrozenFixtureParityTests.v2_rows

    def test_wire_is_exactly_three_fields_and_old_assessed_field_is_rejected(self):
        job = self.rows[0]["validation_job"]
        good = response(reason="no_independent_legal_point")
        normalized = controls.validate(good, job)
        self.assertEqual(normalized["delivered_scope_ids"], job["active_scope_ids"])
        self.assertEqual(normalized["assessed_scope_ids"], job["active_scope_ids"])
        with self.assertRaises((ValueError, TypeError)):
            controls.validate({**good, "assessed_scope_ids": []}, job)

    def test_uncertain_never_assesses_and_needs_context_keeps_scope_unresolved(self):
        for row in self.rows:
            job = row["validation_job"]
            value = response(reason="insufficient_context",
                             action={"tool": "finish_case", "reason": "needs_context"})
            normalized = controls.validate(value, job)
            self.assertEqual(normalized["assessed_scope_ids"], [])
            self.assertEqual(normalized["unresolved_scope_ids"], job["active_scope_ids"])

    def test_empty_navigation_with_null_reason_means_no_assessment(self):
        job = self.rows[0]["validation_job"]
        target = job["allowed_scope_ids"][-1]
        if target in job["active_scope_ids"]:
            target = "navigation-only-scope"
            job["allowed_scope_ids"] = [*job["allowed_scope_ids"], target]
        normalized = controls.validate(response(reason=None, action={"tool": "open_region", "scope_ids": [target]}), job)
        self.assertEqual(normalized["assessed_scope_ids"], [])
        self.assertEqual(normalized["delivered_scope_ids"], job["active_scope_ids"])

    def test_uncertain_mixed_scope_response_leaves_all_active_scopes_unresolved(self):
        row = copy.deepcopy(self.rows[0])
        job = row["validation_job"]
        job["active_scope_ids"] = ["scope-a", "scope-b"]
        job["allowed_scope_ids"] = ["scope-a", "scope-b"]
        normalized = controls.validate(response(reason="uncertain", action={
            "tool": "finish_case", "reason": "needs_context"}), job)
        self.assertEqual(normalized["assessed_scope_ids"], [])
        self.assertEqual(normalized["unresolved_scope_ids"], ["scope-a", "scope-b"])

    def test_consistent_multi_scope_pure_negative_is_allowed(self):
        row = copy.deepcopy(self.rows[0])
        job = row["validation_job"]
        job["active_scope_ids"] = ["scope-a", "scope-b"]
        job["allowed_scope_ids"] = ["scope-a", "scope-b"]
        normalized = controls.validate(response(reason="no_independent_legal_point"), job)
        self.assertEqual(normalized["assessed_scope_ids"], ["scope-a", "scope-b"])
        self.assertEqual(normalized["unresolved_scope_ids"], [])
        self.assertTrue(normalized["work_scope_complete"])
        self.assertEqual(normalized["assessment_basis"], "author_self_report")
        self.assertEqual(normalized["semantic_quality"], "not_assessed")

    def test_empty_reason_and_action_combinations_are_consistent(self):
        job = self.rows[0]["validation_job"]
        with self.assertRaises((ValueError, TypeError)):
            controls.validate(response(reason=None), job)  # terminal empty, no reason
        with self.assertRaises((ValueError, TypeError)):
            controls.validate(response(reason="uncertain"), job)  # uncertain but normal finish
        for bad_reason in ("unknown_reason", 7, [], {}):
            with self.subTest(reason=bad_reason), self.assertRaises((ValueError, TypeError)):
                controls.validate(response(reason=bad_reason), job)
        unresolved = controls.validate(response(reason="no_independent_legal_point",
            action={"tool": "finish_case", "reason": "needs_context"}), job)
        self.assertEqual(unresolved["assessed_scope_ids"], [])
        self.assertEqual(unresolved["unresolved_scope_ids"], job["active_scope_ids"])
        self.assertFalse(unresolved["work_scope_complete"])
        self.assertEqual(unresolved["assessment_result"], "uncertain")
        self.assertEqual(unresolved["empty_reason"], "no_independent_legal_point")

    def test_positive_requires_null_empty_reason_and_syntactically_valid_au(self):
        job = self.rows[0]["validation_job"]
        evidence_id = next(iter(job["catalog"]["evidence"]))
        au = {"claim": "A fictional legal point.", "kind": None,
              "evidence_ids": [evidence_id], "limits": None}
        valid = controls.validate(response(aus=[au], reason=None), job)
        self.assertEqual(len(valid["aus"]), 1)
        with self.assertRaises((ValueError, TypeError)):
            controls.validate(response(aus=[au], reason="uncertain"), job)

    def test_empty_positive_control_is_protocol_valid_but_fails_expected_count(self):
        row = next(row for row in self.rows if row["expected"]["group"] == "positive")
        output = response(reason="uncertain", action={
            "tool": "finish_case", "reason": "needs_context"})
        receipt = {"status": "completed", "usage": None, "latency_ms": 1,
                   "raw_response": {"model": row["payload"]["model"], "choices": [{
                       "finish_reason": "stop", "message": {"content": json.dumps(output)}}]}}
        evaluated = cli.evaluate_row(row, receipt)
        self.assertTrue(evaluated["protocol_valid"])
        self.assertEqual(evaluated["AU_count"], 0)
        self.assertEqual(evaluated["status"], "control_failed")
        self.assertFalse(evaluated["normalized"]["work_scope_complete"])
        self.assertEqual(evaluated["semantic_quality"], "semantic_review_pending")

    def test_au_does_not_close_unresolved_scope_when_action_needs_context(self):
        job = self.rows[0]["validation_job"]
        evidence_id = next(iter(job["catalog"]["evidence"]))
        au = {"claim": "A supported fictional point.", "kind": None,
              "evidence_ids": [evidence_id], "limits": None}
        normalized = controls.validate(response(
            aus=[au], reason=None,
            action={"tool": "finish_case", "reason": "needs_context"}), job)
        self.assertEqual(len(normalized["aus"]), 1)
        self.assertEqual(normalized["assessed_scope_ids"], [])
        self.assertEqual(normalized["unresolved_scope_ids"], job["active_scope_ids"])
        self.assertFalse(normalized["work_scope_complete"])
        self.assertEqual(normalized["semantic_quality"], "not_assessed")

    def test_id_types_unknown_ids_and_soft_length_contract(self):
        job = self.rows[0]["validation_job"]
        good = response(reason="no_independent_legal_point")
        for malformed in (None, "scope", [1], ["not-opened"]):
            altered = copy.deepcopy(job)
            altered["active_scope_ids"] = malformed
            with self.subTest(active_scope_ids=malformed), self.assertRaises((ValueError, TypeError)):
                controls.validate(good, altered)
        evidence_id = next(iter(job["catalog"]["evidence"]))
        valid_au = {"claim": "A fictional legal point.", "kind": None,
                    "evidence_ids": [evidence_id], "limits": None}
        for bad_ids in ([1], ["not-opened"]):
            au = {**valid_au, "evidence_ids": bad_ids}
            with self.subTest(evidence_ids=bad_ids):
                normalized = controls.validate(response(aus=[au]), job)
                self.assertEqual(normalized["aus"], [])
                self.assertEqual(normalized["au_errors"], [{"index": 0, "code": "invalid_AU"}])
        long_au = {"claim": "x" * 501, "kind": None,
                   "evidence_ids": [evidence_id], "limits": None}
        normalized = controls.validate(response(aus=[long_au]), job)
        self.assertTrue(any(w.get("code") == "length_threshold_exceeded" for w in normalized["warnings"]))


class LocalGateAndResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = k0.load(frozen_v1.BASELINE / "input/manifest.json")
        model = manifest["jobs"][0]["job"]["payload"]["model"]
        cls.job = controls.balanced_jobs({"model": model})[0]
        cls.cfg = {"jobs_url": "http://127.0.0.1:8765/v1/jobs", "model": model,
                   "token": "local-test-token", "job_wait_seconds": 2,
                   "job_poll_seconds": 0.01, "timeout": 1}

    def test_cpu_gate_binds_current_bundle_hash(self):
        from knowledge_base.pipeline_v1.k0_authoring.token_budget import EXPECTED
        with tempfile.TemporaryDirectory(prefix="kos-controls-v2-cpu-") as temp:
            root = Path(temp)
            bundle = root / "input" / "cpu_balanced.json"
            bundle.parent.mkdir()
            bundle.write_text('{"jobs":[]}', encoding="utf-8")
            report = {"status": "pass", "protocol_pass": True,
                      "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                      "tokenizer_sha256": EXPECTED["tokenizer.json"], "xgrammar_version": "0.2.1",
                      "actual_stop_token_ids": [248046, 248044]}
            (root / "cpu_balanced.json").write_text(json.dumps(report), encoding="utf-8")
            cli.require_cpu(root, "balanced")
            report["bundle_sha256"] = "0" * 64
            (root / "cpu_balanced.json").write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises((ValueError, TypeError)):
                cli.require_cpu(root, "balanced")

    def test_stale_or_ambiguous_resume_is_get_only_after_remote_404(self):
        methods = []

        def opener(req, **kwargs):
            methods.append(req.get_method())
            if req.get_method() == "GET":
                raise HTTPError(req.full_url, 404, "missing", {}, None)
            self.fail("resume must not POST after an ambiguous prior attempt")

        with tempfile.TemporaryDirectory(prefix="kos-controls-v2-resume-") as temp:
            run = shared_execution.run_jobs(temp, self.cfg, [copy.deepcopy(self.job)], execute=False,
                                     selected_names=[self.job["name"]])
            job_id = run["rows"][0]["job_id"]
            receipt = {"job_id": job_id, "binding_sha256": run["binding_sha256"],
                       "status": "partial", "usage": None, "observed_remote": True}
            receipt_path = Path(temp) / "receipts" / job_id / "orphan.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps(shared_execution._seal(receipt)), encoding="utf-8")
            with patch.object(shared_execution.ReadinessGate, "warmup", return_value=None), \
                 patch.object(shared_execution.ReadinessGate, "snapshot", return_value={"status": "ready"}):
                result = shared_execution.run_jobs(temp, self.cfg, [copy.deepcopy(self.job)], opener=opener,
                    execute=True, selected_names=[self.job["name"]], clock=lambda: 1.0, sleep=lambda _: None)
        self.assertEqual(methods, ["GET"])
        self.assertEqual(result["POST_attempts"], 0)


if __name__ == "__main__":
    unittest.main()
