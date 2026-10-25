"""Independent host-side contract tests for Plan 12 repair wire data.

These tests exercise JSON Schema and host normalization only. They do not
compile a provider grammar, call a model, or judge whether any AU is correct.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError

from knowledge_base.pipeline_v1.repair_agent.core import POLICY
from knowledge_base.pipeline_v1.repair_agent.formal_probe import (
    _branch_exercised, _coverage, envelope as formal_envelope, fixtures, remote_cases,
    run_formal_probe, synthetic_task, validate_output,
)
from knowledge_base.pipeline_v1.repair_agent.tools import RepairSession
from knowledge_base.pipeline_v1.repair_agent.wire import normalize, wire_schema
from knowledge_base.pipeline_v1.tests.test_repair_agent import task_fixture


def envelope(task, decisions, *, name="submit_revision", arguments=None):
    args = arguments if arguments is not None else {
        "task_id": task["task_id"], "decisions": decisions,
    }
    return {"tool_calls": [{"name": name, "arguments": args}]}


def supported(proposal_id, *, reason="Supported by supplied witness"):
    return {
        "proposal_id": proposal_id,
        "verdict": "supported",
        "reason": reason,
        "primary_proposition": {"atom_id": "a", "quote": "Rule X."},
    }


def uncertain(proposal_id, *, reason="Unclear"):
    return {"proposal_id": proposal_id, "verdict": "uncertain", "reason": reason}


def defect(proposal_id, *, defect_type="qualification", correction=None,
           retained=None, reason="Synthetic protocol fixture"):
    row = {
        "proposal_id": proposal_id,
        "verdict": "defect_found",
        "reason": reason,
        "defect_type": defect_type,
        "witnesses": [{"atom_id": "a", "quote": "Rule X."}],
        "correction": correction or {"action": "reject"},
    }
    if retained is not None:
        row["retained_proposal_id"] = retained
    return row


class RepairFormalWireTests(unittest.TestCase):
    def setUp(self):
        self.task = task_fixture()
        second = copy.deepcopy(self.task["original_proposals"][0])
        second["proposal_id"] = "proposal-second"
        self.task["original_proposals"].append(second)
        self.ids = [p["proposal_id"] for p in self.task["original_proposals"]]
        self.schema = wire_schema(self.task, "R2", 1, ["a"])

    def assert_schema_accepts(self, value):
        Draft202012Validator(self.schema).validate(value)

    def assert_schema_rejects(self, value):
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.schema).validate(value)

    def assert_host_accepts(self, value):
        return normalize(value, self.task, "R2", 1, ["a"])

    def test_reason_bounds_and_json_unicode_escapes(self):
        # Escaped JSON round-trips to actual Unicode before host validation.
        decision = supported(self.ids[0], reason="Tòa án áp dụng Điều é")
        value = envelope(self.task, [decision, uncertain(self.ids[1])])
        wire = json.loads(json.dumps(value, ensure_ascii=True))
        self.assert_schema_accepts(wire)
        self.assertEqual(self.assert_host_accepts(wire)["tool_calls"][0]["arguments"]["decisions"][0]["reason"], decision["reason"])

        self.assert_schema_rejects(envelope(self.task, [supported(self.ids[0], reason=""), uncertain(self.ids[1])]))
        self.assert_schema_accepts(envelope(self.task, [supported(self.ids[0], reason="x" * 120), uncertain(self.ids[1])]))
        self.assert_schema_rejects(envelope(self.task, [supported(self.ids[0], reason="x" * 121), uncertain(self.ids[1])]))

        # The wire's span indexes have inclusive lower bounds 0 and 1.
        span_schema = wire_schema(self.task, "R2", 1, ["a"])
        valid_span = {"tool_calls": [{"name": "open_span", "arguments": {
            "atom_id": "a", "start_char": 0, "end_char": 1,
        }}]}
        Draft202012Validator(span_schema).validate(valid_span)
        for args in ({"atom_id": "a", "start_char": -1, "end_char": 1},
                     {"atom_id": "a", "start_char": 0, "end_char": 0}):
            with self.assertRaises(ValidationError):
                Draft202012Validator(span_schema).validate({"tool_calls": [{"name": "open_span", "arguments": args}]})

    def test_optional_fields_and_unique_items_are_distinct_contract_rules(self):
        # needed_context is optional; when present it must be valid and unique.
        self.assert_schema_accepts(envelope(self.task, [supported(self.ids[0]), uncertain(self.ids[1])]))
        with_context = [supported(self.ids[0]), {
            **uncertain(self.ids[1]), "needed_context": ["condition", "exception"],
        }]
        self.assert_schema_accepts(envelope(self.task, with_context))
        with_duplicate_context = copy.deepcopy(with_context)
        with_duplicate_context[1]["needed_context"] = ["condition", "condition"]
        self.assert_schema_rejects(envelope(self.task, with_duplicate_context))

        au = {
            "kind": "holding", "claim": "Synthetic replacement claim",
            "evidence_ref_ids": ["a", "a"], "speaker": "current_court",
            "attribution_role": "proposition",
        }
        replacement = {"action": "replace", "replacements": [{
            "au": au, "primary_proposition": {"atom_id": "a", "quote": "Rule X."},
        }]}
        self.assert_schema_rejects(envelope(self.task, [
            defect(self.ids[0], correction=replacement), uncertain(self.ids[1]),
        ]))
        au["evidence_ref_ids"] = ["a"]
        au["claim"] = "x" * 300
        self.assert_schema_accepts(envelope(self.task, [
            defect(self.ids[0], correction=replacement), uncertain(self.ids[1]),
        ]))
        au["claim"] = "x" * 301
        self.assert_schema_rejects(envelope(self.task, [
            defect(self.ids[0], correction=replacement), uncertain(self.ids[1]),
        ]))

    def test_other_kind_conditional_and_optional_other_kind(self):
        def replacement(kind, other_kind_marker=...):
            au = {
                "kind": kind, "claim": "Synthetic replacement claim",
                "evidence_ref_ids": ["a"], "speaker": "current_court",
                "attribution_role": "proposition",
            }
            if other_kind_marker is not ...:
                au["other_kind"] = other_kind_marker
            return {"action": "replace", "replacements": [{
                "au": au, "primary_proposition": {"atom_id": "a", "quote": "Rule X."},
            }]}

        def pair(correction):
            return envelope(self.task, [
                defect(self.ids[0], correction=correction), uncertain(self.ids[1]),
            ])

        self.assert_schema_accepts(pair(replacement("other", "custom kind")))
        self.assert_schema_accepts(pair(replacement("other", "k" * 160)))
        self.assert_schema_rejects(pair(replacement("other", "k" * 161)))
        self.assert_schema_rejects(pair(replacement("other", None)))
        self.assert_schema_rejects(pair(replacement("other", "")))
        self.assert_schema_accepts(pair(replacement("holding", None)))
        self.assert_schema_rejects(pair(replacement("holding", "custom kind")))
        # The host normalizer fills optional omitted fields. That default must
        # still respect the conditional contract for kind=other.
        with self.assertRaises(ValidationError):
            self.assert_host_accepts(pair(replacement("other")))

    def test_duplicate_condition_requires_retained_id_and_host_binding(self):
        duplicate = defect(self.ids[0], defect_type="duplicate", retained=self.ids[1])
        payload = envelope(self.task, [duplicate, supported(self.ids[1])])
        self.assert_schema_accepts(payload)
        self.assert_host_accepts(payload)

        missing_reference = defect(self.ids[0], defect_type="duplicate")
        self.assert_schema_rejects(envelope(self.task, [missing_reference, supported(self.ids[1])]))
        wrong_action = defect(
            self.ids[0], defect_type="duplicate", retained=self.ids[1],
            correction={"action": "replace", "replacements": []},
        )
        self.assert_schema_rejects(envelope(self.task, [wrong_action, supported(self.ids[1])]))
        self_reference = defect(self.ids[0], defect_type="duplicate", retained=self.ids[0])
        with self.assertRaisesRegex(ValueError, "duplicate_requires_distinct_supported_retained"):
            self.assert_host_accepts(envelope(self.task, [self_reference, supported(self.ids[1])]))
        retained_uncertain = defect(self.ids[0], defect_type="duplicate", retained=self.ids[1])
        with self.assertRaisesRegex(ValueError, "duplicate_requires_distinct_supported_retained"):
            self.assert_host_accepts(envelope(self.task, [retained_uncertain, uncertain(self.ids[1])]))
        stray_reference = defect(self.ids[0], retained=self.ids[1])
        self.assert_schema_rejects(envelope(self.task, [stray_reference, supported(self.ids[1])]))

    def test_every_original_proposal_has_exactly_one_decision(self):
        valid = envelope(self.task, [supported(self.ids[0]), uncertain(self.ids[1])])
        self.assert_host_accepts(valid)
        # The bound schema enforces the required count and known ID enum;
        # the host adds the cross-item uniqueness/set equality check.
        self.assert_schema_rejects(envelope(self.task, [supported(self.ids[0])]))
        self.assert_schema_rejects(envelope(self.task, [
            supported(self.ids[0]), uncertain("foreign-proposal"),
        ]))
        with self.assertRaisesRegex(ValueError, "foreign_or_missing_revision_identity"):
            self.assert_host_accepts(envelope(self.task, [
                supported(self.ids[0]), uncertain(self.ids[0]),
            ]))

    def test_response_and_arm_tool_restrictions(self):
        two_calls = {
            "tool_calls": [
                {"name": "get_related_aus", "arguments": {}},
                {"name": "get_related_aus", "arguments": {}},
            ],
        }
        self.assert_schema_rejects(two_calls)
        r1 = wire_schema(self.task, "R1", 1, ["a"])
        r2_final = wire_schema(self.task, "R2", 2, ["a"])
        for schema in (r1, r2_final):
            names = [row["properties"]["name"]["const"] for row in schema["properties"]["tool_calls"]["items"]["oneOf"]]
            self.assertEqual(names, ["submit_revision"])
        r2_first_names = [row["properties"]["name"]["const"] for row in self.schema["properties"]["tool_calls"]["items"]["oneOf"]]
        self.assertIn("expand_context", r2_first_names)
        self.assertIn("submit_revision", r2_first_names)
        self.assertEqual(POLICY["tool_calls"], 8)
        # Exercise the session's actual task-level cap independently from the
        # per-response JSON Schema's maxItems=1 constraint.
        session = RepairSession(self.task, "R2")
        for _ in range(8):
            self.assertTrue(session.call_tool("get_related_aus", {})["ok"])
        capped = session.call_tool("get_related_aus", {})
        self.assertFalse(capped["ok"])
        self.assertEqual(capped["error"]["code"], "tool_budget_exhausted")

    def test_local_probe_pass_is_not_backend_or_semantic_pass(self):
        adapter_path = "knowledge_base.pipeline_v1.repair_agent.adapter.JobsAdapter"
        ids = {row["case_id"] for row in remote_cases()}
        with tempfile.TemporaryDirectory() as temp, patch(adapter_path, side_effect=AssertionError("unexpected dispatch")) as adapter:
            report = run_formal_probe(Path(temp))
            adapter.assert_not_called()

        self.assertEqual("prepared", report["status"])
        self.assertEqual("pass", report["host_check_status"])
        self.assertEqual("unverified", report["backend_compilation"])
        self.assertEqual("not_evaluated", report["semantic_quality"])
        self.assertEqual(0, report["cost_summary"]["attempts"])
        self.assertEqual([], report["executed_case_ids"])
        self.assertEqual(ids, set(report["unrun_case_ids"]))
        self.assertEqual(ids, set(report["uncovered_case_ids"]))
        self.assertTrue(all(row["status"] == "prepared" for row in report["cases"]))
        self.assertTrue(all(row["provider_usage"] is None for row in report["cases"]))

    def test_valid_model_rewrite_does_not_prove_invalid_challenge_enforcement(self):
        # A model can repair or ignore the suggested invalid value. A valid
        # response then proves host acceptance, not that the endpoint grammar
        # enforced the invalid bound/uniqueness challenge.
        fixture = next(row for row in fixtures() if row["case_id"] == "reason_length_121")
        valid_rewrite = formal_envelope(synthetic_task())
        self.assertNotEqual(
            valid_rewrite["tool_calls"][0]["arguments"]["decisions"][0]["reason"],
            "x" * 121,
        )
        self.assertFalse(
            _coverage(valid_rewrite, fixture),
            "an unrelated valid rewrite must not count as enforcement coverage",
        )
        self.assertFalse(
            _branch_exercised(valid_rewrite, fixture),
            "an unrelated valid rewrite must not count as the reason-length boundary",
        )
        check = validate_output(valid_rewrite, fixture["task"], fixture["arm"], fixture["turn"])
        self.assertTrue(check["valid"])

        adapter_path = "knowledge_base.pipeline_v1.repair_agent.adapter.JobsAdapter"
        cfg = {"model": "synthetic", "jobs_url": "synthetic", "token": "synthetic"}
        with tempfile.TemporaryDirectory() as temp, patch(adapter_path) as adapter:
            adapter.return_value.return_value = {"output": valid_rewrite, "provider_usage": None}
            report = run_formal_probe(temp, cfg, [fixture["case_id"]])
        row = report["cases"][0]
        self.assertEqual("valid_output_under_invalid_challenge", row["coverage_kind"])
        self.assertEqual("unverified", row["grammar_enforcement"])
        self.assertEqual("unverified", row["backend_compilation"])
        self.assertEqual("not_evaluated", report["semantic_quality"])
        self.assertEqual("uncovered", row["target_branch_status"])

        impossible = next(row for row in fixtures() if row["case_id"] == "duplicate_1_anchor")
        uncertain_one_proposal = formal_envelope(impossible["task"])
        self.assertFalse(_branch_exercised(uncertain_one_proposal, impossible))


if __name__ == "__main__":
    unittest.main()
