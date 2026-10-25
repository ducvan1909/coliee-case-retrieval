"""Validate-first regressions for the Plan12 repair runtime.

These are protocol and preservation checks over the fixed v6 development
fixture. A passing test does not adjudicate the semantic correctness of an AU.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.repair_agent import runtime, wire
from knowledge_base.pipeline_v1.repair_agent.core import build_tasks
from knowledge_base.pipeline_v1.repair_agent.probe import CASES, run_probe
from knowledge_base.pipeline_v1.repair_agent.runtime import run_arm
from knowledge_base.pipeline_v1.repair_agent import tools as repair_tools
from knowledge_base.pipeline_v1.repair_agent.tools import RepairSession


ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "knowledge_base" / "pipeline_v1"
V6_RUN = PIPELINE / "outputs" / "plan11_semantic_v6_gate_20261011" / "run" / "run.json"
EXACT_REVIEW = PIPELINE / "outputs" / "plan12_agent_repair_20261011" / "inputs" / "review.source_exact.v2.json"
SOURCE_STORE = PIPELINE / "outputs" / "source_store_v1"
ATOM_ROOT = PIPELINE / "outputs" / "plan04_sentence_atoms_v1"
PRIOR_REJECT = PIPELINE / "outputs" / "plan12_validate_first_20261011" / "prior_all_reject.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _target_witness(task):
    target = task["raw_targets"][0]
    for atom in task["supplied_atom_catalog"]:
        start = max(atom["start_char"], target["start_char"])
        end = min(atom["end_char"], target["end_char"])
        if start >= end:
            continue
        text = atom["quote"][start - atom["start_char"]:end - atom["start_char"]]
        for length in range(1, len(text) + 1):
            for offset in range(len(text) - length + 1):
                quote = text[offset:offset + length]
                if quote.strip() and atom["quote"].count(quote) == 1:
                    return {"atom_id": atom["atom_id"], "quote": quote}
    raise AssertionError("fixture lacks a unique exact witness inside raw TARGET")


class ValidateFirstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = (V6_RUN, EXACT_REVIEW, PRIOR_REJECT,
                    SOURCE_STORE / "source_store_manifest.json",
                    ATOM_ROOT / "sentence_atom_build_manifest.json")
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError("Plan12 validate-first fixture prerequisites missing: " + ", ".join(missing))
        cls.manifest = build_tasks(V6_RUN, EXACT_REVIEW, SOURCE_STORE, ATOM_ROOT)
        cls.task = copy.deepcopy(next(t for t in cls.manifest["tasks"] if t["case_id"] == "013948"))

    def _supported(self, proposal, witness):
        return {"proposal_id": proposal["proposal_id"], "verdict": "supported",
                "reason": "Exact TARGET witness supports retained original.",
                "primary_proposition": copy.deepcopy(witness)}

    def _uncertain(self, proposal):
        return {"proposal_id": proposal["proposal_id"], "verdict": "uncertain",
                "reason": "Attribution remains unclear from supplied context.",
                "needed_context": ["attribution"]}

    def _defect(self, proposal, witness, *, defect_type="attribution", correction=None,
                retained_proposal_id=None):
        decision = {"proposal_id": proposal["proposal_id"], "verdict": "defect_found",
                    "reason": "The cited span identifies a different speaker.",
                    "defect_type": defect_type, "witnesses": [copy.deepcopy(witness)],
                    "correction": correction or {"action": "reject"}}
        if retained_proposal_id is not None:
            decision["retained_proposal_id"] = retained_proposal_id
        return decision

    def _all_supported(self, task=None):
        task = task or self.task
        witness = _target_witness(task)
        return [self._supported(p, witness) for p in task["original_proposals"]]

    def _submit(self, decisions, task=None, arm="R1"):
        task = task or self.task
        session = RepairSession(task, arm)
        args = {"task_id": task["task_id"], "decisions": decisions}
        return session, session.call_tool("submit_revision", args)

    def test_prior_live_all_action_reject_outputs_fail_new_runtime_wire(self):
        """Replay the preserved R1/R2 observations; action-only cannot bypass assessment."""
        prior = _json(PRIOR_REJECT)
        self.assertEqual(prior["semantic_status"], "Main preliminary review, not gold")
        self.assertTrue(prior["history_unchanged"])
        self.assertEqual({row["arm"]: row["run_sha256"] for row in prior["observations"]}, {
            "R1": "5da86acf6c15fdfe93df7d27537e23108934289b7f01b71cc193d2bd68f8843a",
            "R2": "1eaf27e6002bc49e6fa49fa7e644e75aba1cf292f6513194b17104b8ae87ad9e",
        })
        for observation in prior["observations"]:
            self.assertEqual(len(observation["decisions"]), len(self.task["original_proposals"]))
            self.assertTrue(all(row["action"] == "reject" for row in observation["decisions"]))
            output = {"tool_calls": [{"name": "submit_revision", "arguments": {
                "task_id": self.task["task_id"], "decisions": observation["decisions"]}}]}
            with self.subTest(arm=observation["arm"]):
                with self.assertRaises(Exception):
                    wire.normalize(output, self.task, observation["arm"], 1,
                                   [a["atom_id"] for a in self.task["supplied_atom_catalog"]])

    def test_supported_preserves_original_au_and_requires_exact_primary(self):
        task = self.task
        decisions = self._all_supported(task)
        session, event = self._submit(decisions, task)
        self.assertTrue(event["ok"], event.get("error"))
        revision = event["result"]
        self.assertEqual(revision["semantic_status"], "semantic_review_pending")
        self.assertFalse(revision["verified_assessments"][0]["entailment_validated"])
        self.assertEqual(revision["assessments"][0]["primary_proposition"], decisions[0]["primary_proposition"])
        by_id = {p["proposal_id"]: p for p in task["original_proposals"]}
        kept = {row["original_proposal_id"]: row["au"] for row in revision["verified_replacements"]}
        self.assertEqual(set(kept), set(by_id))
        for proposal_id, au in kept.items():
            self.assertEqual(au, by_id[proposal_id]["proposal"])
        self.assertEqual(session.state["revision"], revision)

        missing_witness = copy.deepcopy(decisions)
        missing_witness[0].pop("primary_proposition")
        invalid_session, rejected = self._submit(missing_witness, task)
        self.assertFalse(rejected["ok"])
        self.assertIsNone(invalid_session.state["revision"])

    def test_uncertain_preserves_baseline_as_pending_without_no_au_conversion(self):
        task = self.task
        decisions = self._all_supported(task)
        uncertain_id = decisions[1]["proposal_id"]
        decisions[1] = self._uncertain(task["original_proposals"][1])
        _, event = self._submit(decisions, task)
        self.assertTrue(event["ok"], event.get("error"))
        revision = event["result"]
        preserved = {row["proposal_id"]: row for row in revision["preservation_decisions"]}
        self.assertEqual(preserved[uncertain_id]["decision"], "preserve_baseline")
        self.assertFalse(preserved[uncertain_id]["accepted_semantic"])
        self.assertNotIn(uncertain_id, {row["original_proposal_id"] for row in revision["verified_replacements"]})
        self.assertNotIn("no_au", json.dumps(revision, ensure_ascii=False).lower())
        original = next(p for p in task["original_proposals"] if p["proposal_id"] == uncertain_id)
        self.assertIn(original, revision["original_proposals"])

    def test_defect_requires_witness_reason_type_and_repair_action(self):
        task = self.task
        witness = _target_witness(task)
        valid = self._all_supported(task)
        valid[0] = self._defect(task["original_proposals"][0], witness)
        self.assertTrue(self._submit(valid, task)[1]["ok"])

        # A structurally valid replacement goes through the same evidence and
        # exact-primary source checks as an ordinary revision.
        replacement_batch = self._all_supported(task)
        source_proposal = task["original_proposals"][0]
        replacement_au = copy.deepcopy(source_proposal["proposal"])
        replacement_au["claim"] = "Synthetic replacement used only for protocol validation."
        replacement_au["evidence_ref_ids"] = [witness["atom_id"]]
        replacement = self._defect(source_proposal, witness, defect_type="qualification",
            correction={"action": "replace", "replacements": [{"au": replacement_au,
                                                                    "primary_proposition": witness}]})
        replacement_batch[0] = replacement
        _, replaced = self._submit(replacement_batch, task)
        self.assertTrue(replaced["ok"], replaced.get("error"))
        repaired_au = next(row["au"] for row in replaced["result"]["verified_replacements"]
                           if row["original_proposal_id"] == source_proposal["proposal_id"])
        self.assertEqual(repaired_au["claim"], replacement_au["claim"])
        self.assertEqual(replaced["result"]["semantic_status"], "semantic_review_pending")

        for mutation in ("witnesses", "reason", "defect_type", "correction"):
            malformed = copy.deepcopy(valid)
            if mutation == "witnesses":
                malformed[0][mutation] = []
            else:
                malformed[0].pop(mutation)
            with self.subTest(missing=mutation):
                _, event = self._submit(malformed, task)
                self.assertFalse(event["ok"])
                self.assertIsNone(RepairSession(task, "R1").state["revision"])

    def test_duplicate_requires_other_supported_in_batch_and_rejects_cycles_and_foreign_ids(self):
        task = self.task
        witness = _target_witness(task)
        decisions = self._all_supported(task)
        retained = decisions[0]["proposal_id"]
        duplicate = task["original_proposals"][1]
        decisions[1] = self._defect(duplicate, witness, defect_type="duplicate",
                                    retained_proposal_id=retained)
        _, valid = self._submit(decisions, task)
        self.assertTrue(valid["ok"], valid.get("error"))

        cases = []
        self_ref = copy.deepcopy(decisions)
        self_ref[1]["retained_proposal_id"] = duplicate["proposal_id"]
        cases.append(("self", self_ref))
        foreign = copy.deepcopy(decisions)
        foreign[1]["retained_proposal_id"] = "proposal-foreign"
        cases.append(("foreign", foreign))
        cycle = copy.deepcopy(decisions)
        cycle[0] = self._defect(task["original_proposals"][0], witness, defect_type="duplicate",
                               retained_proposal_id=duplicate["proposal_id"])
        cycle[1]["retained_proposal_id"] = task["original_proposals"][0]["proposal_id"]
        cases.append(("cycle", cycle))
        no_supported_retain = copy.deepcopy(decisions)
        no_supported_retain[0] = self._defect(task["original_proposals"][0], witness, defect_type="duplicate",
                                             retained_proposal_id=task["original_proposals"][2]["proposal_id"])
        no_supported_retain[2] = self._defect(task["original_proposals"][2], witness)
        cases.append(("retained_not_supported", no_supported_retain))

        for label, invalid in cases:
            with self.subTest(invalid_duplicate=label):
                _, event = self._submit(invalid, task)
                self.assertFalse(event["ok"])

    def test_other_kind_requires_a_nonempty_label_on_replacement(self):
        task = self.task
        witness = _target_witness(task)
        decisions = self._all_supported(task)
        original = task["original_proposals"][0]
        au = copy.deepcopy(original["proposal"])
        au["kind"] = "other"
        au.pop("other_kind", None)
        au["evidence_ref_ids"] = [witness["atom_id"]]
        decisions[0] = self._defect(original, witness, defect_type="evidence_support",
            correction={"action": "replace", "replacements": [{"au": au,
                                                                    "primary_proposition": witness}]})
        envelope = {"tool_calls": [{"name": "submit_revision", "arguments": {
            "task_id": task["task_id"], "decisions": decisions}}]}
        with self.assertRaises(Exception):
            wire.normalize(envelope, task, "R1", 1,
                           [a["atom_id"] for a in task["supplied_atom_catalog"]])

    def test_invalid_final_revision_validation_does_not_commit_partial_session_state(self):
        task = self.task
        session = RepairSession(task, "R1")
        args = {"task_id": task["task_id"], "decisions": self._all_supported(task)}
        validate = repair_tools.validate
        revision_validations = 0

        def fail_second_revision_validation(name, value):
            nonlocal revision_validations
            if name == "revision":
                revision_validations += 1
                if revision_validations == 2:
                    raise ValueError("synthetic_final_revision_validation_failure")
            return validate(name, value)

        with patch.object(repair_tools, "validate", side_effect=fail_second_revision_validation):
            event = session.call_tool("submit_revision", args)
        self.assertFalse(event["ok"])
        self.assertEqual(revision_validations, 2)
        self.assertIsNone(session.state["revision"])

    def test_empty_original_batches_are_baseline_no_proposals_with_zero_dispatch(self):
        empty_tasks = [t for t in self.manifest["tasks"]
                       if t["case_id"] in {"045155", "099980"} and not t["original_proposals"]]
        self.assertEqual({t["case_id"] for t in empty_tasks}, {"045155", "099980"})
        task_ids = [t["task_id"] for t in empty_tasks]

        class NoDispatchAdapter:
            is_mock = True
            identity = {"kind": "zero_proposal_no_dispatch"}
            calls = 0

            def __call__(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("empty proposal collection must not dispatch a model request")

        adapter = NoDispatchAdapter()
        with tempfile.TemporaryDirectory() as output_root:
            report = run_arm(self.manifest, "R1", output_root, adapter, task_ids)
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["attempts"], [])
        self.assertEqual(report["cost_summary"]["source_model_attempts"], 0)
        coverage = report["revision_coverage"]
        self.assertEqual(coverage["selected"], len(task_ids))
        self.assertEqual(coverage["valid"], 0)
        self.assertEqual(coverage["validation_required"], 0)
        self.assertEqual(coverage["no_proposals"], len(task_ids))
        self.assertIsNone(report["semantic_metrics"])
        self.assertEqual(report["semantic_status"], "semantic_review_pending")
        for task in report["tasks"]:
            self.assertEqual(task["status"], "baseline_no_proposals")
            self.assertEqual(task["model_turns"], 0)
            self.assertEqual(task["session"]["revision"], None)
            self.assertEqual(task["preservation_decision"],
                             "preserve_empty_baseline_no_new_noAU_inference")

    def test_mixed_verdict_batch_and_v2_grammar_branches(self):
        task = self.task
        witness = _target_witness(task)
        decisions = self._all_supported(task)
        decisions[1] = self._uncertain(task["original_proposals"][1])
        decisions[2] = self._defect(task["original_proposals"][2], witness)
        _, event = self._submit(decisions, task)
        self.assertTrue(event["ok"], event.get("error"))
        self.assertEqual({row["verdict"] for row in event["result"]["assessments"]},
                         {"supported", "uncertain", "defect_found"})
        self.assertEqual(event["result"]["semantic_status"], "semantic_review_pending")
        self.assertTrue(all(not row["entailment_validated"] and not row["defect_semantics_validated"]
                            for row in event["result"]["verified_assessments"]))

        # Validate-first still requires exactly one decision for every original.
        for incomplete in (decisions[:-1], decisions[:-1] + [copy.deepcopy(decisions[0])]):
            with self.subTest(decision_count=len(incomplete)):
                envelope = {"tool_calls": [{"name": "submit_revision", "arguments": {
                    "task_id": task["task_id"], "decisions": incomplete}}]}
                with self.assertRaises(Exception):
                    wire.normalize(envelope, task, "R1", 1,
                                   [a["atom_id"] for a in task["supplied_atom_catalog"]])

        allowed = [a["atom_id"] for a in task["supplied_atom_catalog"]]
        for verdict in ("supported", "uncertain", "defect_found"):
            payload = wire.decoding(task, "R1", 1, allowed, forced_verdict=verdict)
            self.assertIn("ebnf", payload)
            self.assertNotIn("response_format", payload)
            grammar = payload["ebnf"]
            self.assertIn(verdict, grammar)
            self.assertIn("root ::=", grammar)

    def test_live_runtime_rejects_action_only_and_keeps_legacy_direct_api_offline(self):
        """The old direct session remains opt-in; the runtime path must fail closed."""
        task = self.task
        old = _json(PRIOR_REJECT)["observations"][0]["decisions"]

        class Adapter:
            is_mock = True
            identity = {"kind": "validate_first_action_only_replay"}
            calls = 0

            def __call__(self, messages, *, task, turn, arm, attempt_id):
                self.calls += 1
                return {"output": {"tool_calls": [{"name": "submit_revision", "arguments": {
                    "task_id": task["task_id"], "decisions": copy.deepcopy(old)}}]}, "mock_usage": None}

        # Direct v1 session compatibility is explicitly offline-only.
        legacy = RepairSession(task, "R1", legacy_offline=True)
        legacy_decisions = [{"proposal_id": p["proposal_id"], "action": "unresolved",
                             "reason": "offline legacy API", "replacements": [],
                             "primary_proposition": None} for p in task["original_proposals"]]
        legacy_event = legacy.call_tool("submit_revision", {"task_id": task["task_id"], "decisions": legacy_decisions})
        self.assertTrue(legacy_event["ok"], legacy_event.get("error"))

        adapter = Adapter()
        with tempfile.TemporaryDirectory() as output_root:
            report = run_arm(self.manifest, "R1", output_root, adapter, [task["task_id"]])
        record = next(row for row in report["tasks"] if row["task_id"] == task["task_id"])
        self.assertEqual(record["status"], "technical_invalid")
        self.assertEqual(adapter.calls, 1)
        self.assertIsNone(record["session"]["revision"])

    def test_r1_r2_turn_caps_context_receipts_and_v2_schema_cache_identity(self):
        task = self.task
        expansion = next((a for a in task["expansion_atom_catalog"]
                          if a["direction"] == "after"), None)
        self.assertIsNotNone(expansion, "013948 fixture needs a bounded adjacent context atom")

        class Adapter:
            is_mock = True
            identity = {"kind": "validate_first_turn_probe"}

            def __init__(self):
                self.calls = []

            def __call__(self, messages, *, task, turn, arm, attempt_id):
                self.calls.append(copy.deepcopy(messages))
                if turn == 1 and arm == "R2":
                    output = {"tool_calls": [{"name": "expand_context", "arguments": {
                        "direction": "after", "reason": "Check nearby qualification."}}]}
                else:
                    decisions = [self_owner._uncertain(p) for p in task["original_proposals"]]
                    output = {"tool_calls": [{"name": "submit_revision", "arguments": {
                        "task_id": task["task_id"], "decisions": decisions}}]}
                return {"output": output, "mock_usage": None}

        self_owner = self
        for arm, cap in (("R1", 1), ("R2", 2)):
            adapter = Adapter()
            with tempfile.TemporaryDirectory() as output_root:
                report = run_arm(self.manifest, arm, output_root, adapter, [task["task_id"]])
            self.assertLessEqual(len(adapter.calls), cap)
            self.assertEqual(report["tasks"][0]["model_turns"], cap)
            self.assertEqual(report["tasks"][0]["status"], "revision_submitted")
            if arm == "R2":
                second = json.loads(adapter.calls[1][1]["content"])
                initial = json.loads(adapter.calls[0][1]["content"])
                initial_ids = {a["atom_id"] for a in initial["supplied_atom_catalog"]}
                second_ids = {a["atom_id"] for a in second["supplied_atom_catalog"]}
                self.assertTrue(initial_ids <= second_ids)
                self.assertIn(expansion["atom_id"], second_ids)
                self.assertEqual(second["original_proposals"], initial["original_proposals"])
                receipt = second["tool_results"][0]["result"]
                self.assertIn(expansion["atom_id"], receipt["atom_ids"])
                self.assertNotIn("quote", json.dumps(receipt))

        contract = Path(runtime.CONTRACTS) / "repair_wire.v2.json"
        baseline = runtime.fingerprint(task, "R1", {"kind": "cache-probe"})
        with tempfile.TemporaryDirectory() as folder:
            temp_contract = Path(folder) / "repair_wire.v2.json"
            value = _json(contract)
            temp_contract.write_text(json.dumps(value), encoding="utf-8")
            with patch.object(runtime, "CONTRACTS", Path(folder)):
                before = runtime.fingerprint(task, "R1", {"kind": "cache-probe"})
                value["$id"] += ":changed"
                temp_contract.write_text(json.dumps(value), encoding="utf-8")
                after = runtime.fingerprint(task, "R1", {"kind": "cache-probe"})
        self.assertNotEqual(before, after)
        self.assertEqual(len(baseline), 64)

    def test_source_free_probe_prepares_verdict_cases_without_claiming_backend_support(self):
        cases = {name for name, _ in CASES}
        self.assertTrue({"supported_witness", "uncertain", "defect_reject"} <= cases)
        with tempfile.TemporaryDirectory() as folder:
            report = run_probe(Path(folder))
        self.assertEqual(report["status"], "prepared")
        self.assertEqual(report["semantic_quality"], "not_evaluated")
        self.assertIn(report["decoder_support"], {"unverified", "pending_probe"})
        self.assertTrue(all(row["status"] == "prepared" for row in report["cases"]))


if __name__ == "__main__":
    unittest.main()
