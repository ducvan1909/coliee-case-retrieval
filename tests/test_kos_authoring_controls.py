"""Independent local regressions for the Plan 39 controls-first package."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from knowledge_base.pipeline_v1.k0_authoring import core as old
from knowledge_base.pipeline_v1.kos_authoring_controls import controls
from knowledge_base.pipeline_v1.kos_authoring_controls import __main__ as cli
from knowledge_base.pipeline_v1.kos_authoring_controls import execution


class PositiveControlTests(unittest.TestCase):
    def setUp(self):
        self.baseline = old.load(controls.BASELINE / "input/manifest.json")
        self.old_job = copy.deepcopy(self.baseline["jobs"][0]["job"])
        self.rows = controls.positive_only({"model": self.old_job["payload"]["model"]})

    def test_positive_only_preserves_the_frozen_synthetic_job_contract(self):
        self.assertEqual(len(self.rows), 1)
        row = self.rows[0]
        payload = row["payload"]
        prior = self.old_job["payload"]

        self.assertEqual(row["name"], "positive_only")
        self.assertEqual(row["validation_job"]["catalog"], self.old_job["catalog"])
        self.assertEqual(row["validation_job"]["active_scope_ids"], self.old_job["active_scope_ids"])
        self.assertEqual(payload["ebnf"], prior["ebnf"])
        for key in ("model", "temperature", "max_tokens", "chat_template_kwargs"):
            self.assertEqual(payload[key], prior[key], key)
        prior_text = prior["messages"][0]["content"]
        actual_text = payload["messages"][0]["content"]
        self.assertTrue(actual_text.endswith(prior_text))
        self.assertEqual(row["validation_job"]["payload_sha256"], old.fingerprint(payload))
        self.assertEqual(row["validation_job"]["input_reservation"], old.input_reservation(payload))
        self.assertLessEqual(row["validation_job"]["input_reservation"], 6000)

        # The added demonstration must be a complete old-wire JSON response and
        # its illustrative IDs must remain outside the actual evidence catalog.
        demo_prefix = actual_text[:-len(prior_text)]
        json_text = demo_prefix.split("JSON: ", 1)[1].split("\nEND EXAMPLES.", 1)[0]
        example = json.loads(json_text)
        self.assertEqual(set(example), {"aus", "assessed_scope_ids", "next_action"})
        self.assertEqual(set(example["aus"][0]), {"claim", "kind", "evidence_ids", "limits"})
        self.assertEqual(example["aus"][0]["evidence_ids"], ["demo-e"])
        self.assertEqual(example["assessed_scope_ids"], ["demo-r"])
        self.assertNotIn("demo-e", self.old_job["catalog"]["evidence"])
        self.assertNotIn("demo-r", self.old_job["active_scope_ids"])
        self.assertNotIn("kos", demo_prefix.casefold())
        self.assertNotIn("review input", demo_prefix.casefold())
        self.assertNotIn("kos", actual_text.casefold())
        self.assertNotIn("review input", actual_text.casefold())


class FinalWireValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg_model = old.load(controls.BASELINE / "input/manifest.json")["jobs"][0]["job"]["payload"]["model"]
        cls.rows = controls.balanced_jobs({"model": cfg_model})
        cls.positive = cls.rows[0]["validation_job"]
        cls.scope_id = cls.positive["active_scope_ids"][0]
        cls.evidence_id = next(iter(cls.positive["catalog"]["evidence"]))

    def _response(self, *, aus=None, assessed=None, reason=None, action=None):
        return {
            "aus": [] if aus is None else aus,
            "assessed_scope_ids": [] if assessed is None else assessed,
            "empty_reason": reason,
            "next_action": action or {"tool": "finish_case", "reason": "work_scope_complete"},
        }

    def _au(self):
        return {"claim": "A fictional rule supported by the supplied source.",
                "kind": None, "evidence_ids": [self.evidence_id], "limits": None}

    def test_empty_reason_must_match_result_and_assessment_state(self):
        good_positive = self._response(aus=[self._au()], assessed=[self.scope_id])
        self.assertEqual(controls.validate(good_positive, self.positive, final_wire=True)["empty_reason"], None)

        for reason in controls.NEGATIVE:
            with self.subTest(reason=reason):
                good_negative = self._response(assessed=[self.scope_id], reason=reason)
                self.assertEqual(controls.validate(good_negative, self.positive, final_wire=True)["empty_reason"], reason)
                with self.assertRaises(ValueError):
                    controls.validate(self._response(reason=reason), self.positive, final_wire=True)

        for reason in controls.REASONS[3:]:
            with self.subTest(reason=reason):
                uncertain = self._response(reason=reason,
                    action={"tool": "finish_case", "reason": "needs_context"})
                self.assertEqual(controls.validate(uncertain, self.positive, final_wire=True)["empty_reason"], reason)
                with self.assertRaises(ValueError):
                    controls.validate(self._response(assessed=[self.scope_id], reason=reason),
                                      self.positive, final_wire=True)

    def test_reason_cannot_be_used_to_close_uncertainty_or_navigation(self):
        with self.assertRaises(ValueError):
            controls.validate(self._response(aus=[self._au()], assessed=[self.scope_id],
                                              reason="uncertain"), self.positive, final_wire=True)
        with self.assertRaises(ValueError):
            controls.validate(self._response(reason="uncertain"), self.positive, final_wire=True)
        navigation = self._response(action={"tool": "open_region", "scope_ids": [self.scope_id]})
        self.assertIsNone(controls.validate(navigation, self.positive, final_wire=True)["empty_reason"])
        with self.assertRaises(ValueError):
            controls.validate(self._response(reason="made_up_reason"), self.positive, final_wire=True)


class ControlEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model = old.load(controls.BASELINE / "input/manifest.json")["jobs"][0]["job"]["payload"]["model"]
        cls.positive = controls.positive_only({"model": model})[0]

    def test_positive_count_alone_never_becomes_semantic_quality_pass(self):
        row = copy.deepcopy(self.positive)
        row["payload"]["messages"] = [{"role": "user", "content": "synthetic"}]
        # One syntactically valid but content-empty-for-this-control AU is enough
        # to exercise the evaluator's count gate without calling a model.
        evidence_id = next(iter(row["validation_job"]["catalog"]["evidence"]))
        output = {
            "aus": [{"claim": "A legal point.", "kind": None,
                      "evidence_ids": [evidence_id], "limits": None}],
            "assessed_scope_ids": row["validation_job"]["active_scope_ids"],
            "next_action": {"tool": "finish_case", "reason": "work_scope_complete"},
        }
        receipt = {"raw_response": {"model": row["payload"]["model"], "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(output)}}]}}
        evaluated = cli.evaluate_row(row, receipt)

        self.assertEqual(evaluated["AU_count"], 1)
        self.assertEqual(evaluated["lexical_concept_hints"], {
            concept: False for concept in row["expected"]["concepts"]})
        self.assertEqual(evaluated["semantic_quality"], "agent_review_pending")
        self.assertEqual(evaluated["status"], "structural_control_pass")
        self.assertNotEqual(evaluated["semantic_quality"], "pass")

    def test_positive_gate_requires_main_source_review_even_after_structural_pass(self):
        row = copy.deepcopy(self.positive)
        evidence_id = next(iter(row["validation_job"]["catalog"]["evidence"]))
        output = {"aus": [{"claim": "A legal point.", "kind": None,
                           "evidence_ids": [evidence_id], "limits": None}],
                  "assessed_scope_ids": row["validation_job"]["active_scope_ids"],
                  "next_action": {"tool": "finish_case", "reason": "work_scope_complete"}}
        receipt = {"raw_response": {"model": row["payload"]["model"], "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(output)}}]}}
        evaluated = cli.evaluate_row(row, receipt)
        self.assertEqual(evaluated["status"], "structural_control_pass")
        self.assertEqual(evaluated["semantic_quality"], "agent_review_pending")

        with tempfile.TemporaryDirectory(prefix="kos-control-review-gate-") as temp:
            root = Path(temp)
            evaluation = {"status": "agent_review_pending", "code_sha256": controls.code_hash(),
                          "rows": [evaluated]}
            evaluation["sha256"] = old.fingerprint(evaluation)
            (root / "positive_evaluation.json").write_text(json.dumps(evaluation), encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                cli.positive_gate(root)

            rejected = {"evaluation_sha256": evaluation["sha256"],
                        "decision": "rejected", "basis": "main_agent_source_review",
                        "reason": "The claim does not express the supplied rule."}
            (root / "positive_agent_review.json").write_text(json.dumps(rejected), encoding="utf-8")
            with self.assertRaises(ValueError):
                cli.positive_gate(root)

    def test_cpu_report_must_bind_exact_bundle_hash(self):
        from knowledge_base.pipeline_v1.k0_authoring.token_budget import EXPECTED

        with tempfile.TemporaryDirectory(prefix="kos-control-cpu-") as temp:
            root = Path(temp)
            bundle = root / "input" / "cpu_positive.json"
            bundle.parent.mkdir()
            bundle.write_text('{"jobs":[]}', encoding="utf-8")
            report = {
                "status": "pass", "protocol_pass": True,
                "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                "tokenizer_sha256": EXPECTED["tokenizer.json"],
                "xgrammar_version": "0.2.1", "actual_stop_token_ids": [248046, 248044],
            }
            (root / "cpu_positive.json").write_text(json.dumps(report), encoding="utf-8")
            cli.require_cpu(root, "positive")

            report["bundle_sha256"] = "0" * 64
            (root / "cpu_positive.json").write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(ValueError):
                cli.require_cpu(root, "positive")


class ExecutionRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model = old.load(controls.BASELINE / "input/manifest.json")["jobs"][0]["job"]["payload"]["model"]
        cls.job = controls.positive_only({"model": model})[0]
        cls.cfg = {"jobs_url": "http://127.0.0.1:8765/v1/jobs", "model": model,
                   "token": "local-test-token", "job_wait_seconds": 2,
                   "job_poll_seconds": 0.01, "timeout": 1}

    def _seed_orphan(self, root, usage):
        jobset = [copy.deepcopy(self.job)]
        dry = execution.run_jobs(root, self.cfg, jobset, execute=False,
                                 selected_names=[self.job["name"]])
        job_id = dry["rows"][0]["job_id"]
        receipt = {"job_id": job_id, "binding_sha256": dry["binding_sha256"],
                   "status": "partial", "usage": usage, "observed_remote": True}
        path = Path(root) / "receipts" / job_id / "orphan.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(execution._seal(receipt)), encoding="utf-8")
        return job_id

    def _resume_with_404(self, root):
        methods = []

        def opener(req, **kwargs):
            methods.append(req.get_method())
            if req.get_method() == "GET":
                raise HTTPError(req.full_url, 404, "missing", {}, None)
            self.fail("the guarded POST must never reach the transport opener")

        with patch.object(execution.ReadinessGate, "warmup", return_value=None), \
             patch.object(execution.ReadinessGate, "snapshot", return_value={"status": "ready"}):
            report = execution.run_jobs(root, self.cfg, [copy.deepcopy(self.job)], opener=opener,
                execute=True, selected_names=[self.job["name"]], clock=lambda: 1.0, sleep=lambda _: None)
        return report, methods

    def test_orphan_receipt_remains_retrieval_only_after_remote_404(self):
        with tempfile.TemporaryDirectory(prefix="kos-control-orphan-") as temp:
            self._seed_orphan(temp, {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
            report, methods = self._resume_with_404(temp)
        self.assertEqual(methods, ["GET"])
        self.assertEqual(report["POST_attempts"], 0)

    def test_unknown_usage_allows_get_but_blocks_post(self):
        with tempfile.TemporaryDirectory(prefix="kos-control-unknown-usage-") as temp:
            self._seed_orphan(temp, None)
            report, methods = self._resume_with_404(temp)
        self.assertEqual(methods, ["GET"])
        self.assertGreaterEqual(report["unknown_usage_count"], 1)
        self.assertEqual(report["POST_attempts"], 0)

    def test_stage_selection_reuses_one_full_ordered_workload_binding(self):
        model = self.job["payload"]["model"]
        positive = controls.positive_only({"model": model})
        balanced = controls.balanced_jobs({"model": model})
        full_workload = positive + balanced
        with tempfile.TemporaryDirectory(prefix="kos-control-stages-") as temp:
            first = execution.run_jobs(temp, self.cfg, full_workload, execute=False,
                selected_names=[row["name"] for row in positive])
            second = execution.run_jobs(temp, self.cfg, full_workload, execute=False,
                selected_names=[row["name"] for row in balanced])
        self.assertEqual(first["binding_sha256"], second["binding_sha256"])
        self.assertEqual(first["selected_names"], ["positive_only"])
        self.assertEqual(second["selected_names"], [row["name"] for row in balanced])
        self.assertEqual(len(full_workload), 10)


if __name__ == "__main__":
    unittest.main()
