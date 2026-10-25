"""Implementer selection-wire regression; no remote or semantic validation."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError
from knowledge_base.pipeline_v1.repair_agent import selection, runtime
from knowledge_base.pipeline_v1.repair_agent.adapter import JobsAdapter
from knowledge_base.pipeline_v1.repair_agent.core import MODEL, build_tasks
from knowledge_base.pipeline_v1.repair_agent.formal_probe import (
    synthetic_task, fixtures, selection_fixtures, validate_output, run_formal_probe)
from knowledge_base.pipeline_v1.repair_agent.tools import RepairSession


def submit(task, decisions):
    return dict(schema_version=selection.VERSION, tool_calls=[dict(name="submit_revision",
        arguments=dict(task_id=task["task_id"], decisions=decisions))])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.task = synthetic_task()
        self.pid = self.task["original_proposals"][0]["proposal_id"]
        self.eid = selection.evidence_catalog(self.task, ["a"])["entries"][0]["evidence_id"]

    def supported(self):
        return submit(self.task, [dict(proposal_id=self.pid, verdict="supported", reason="Exact address", primary_proposition=self.eid)])

    def test_exact_roundtrip_and_pending_host_contract(self):
        full = selection.normalize_selection(self.supported(), self.task, "R1", 1, ["a"])
        event = RepairSession(self.task, "R1").call_tool("submit_revision", full["tool_calls"][0]["arguments"])
        self.assertTrue(event["ok"], event)
        span = event["result"]["verified_assessments"][0]["evidence_spans"][0]
        self.assertEqual((0, 7, "Rule X."), (span["start_char"], span["end_char"], span["quote"]))
        self.assertFalse(event["result"]["verified_assessments"][0]["accepted_semantic"])

    def test_foreign_unseen_stale_ids_and_full_quotes_rejected(self):
        for bad in ("foreign", {"atom_id": "a", "quote": "Rule X."}):
            out = self.supported(); out["tool_calls"][0]["arguments"]["decisions"][0]["primary_proposition"] = bad
            with self.assertRaises(ValidationError): selection.normalize_selection(out, self.task, "R1", 1, ["a"])
        expanded = selection.evidence_catalog(self.task, ["a", "b"])["entries"]
        self.assertNotIn(self.eid, {e["evidence_id"] for e in expanded})
        with self.assertRaises(ValidationError): selection.normalize_selection(self.supported(), self.task, "R1", 1, ["a", "b"])
        bad = copy.deepcopy(self.task); bad["supplied_atom_catalog"][0]["source_hash"] = "0" * 64
        with self.assertRaises(ValueError): selection.evidence_catalog(bad, ["a"])

    def test_clipped_target_primary_grammar_domain_and_offsets(self):
        self.task["raw_targets"][0].update(start_char=2, end_char=6)
        entries = selection.evidence_catalog(self.task, ["a"])["entries"]
        self.assertEqual([(0, 7, False), (2, 6, True)], [(e["start_char"], e["end_char"], e["target_eligible"]) for e in entries])
        out = self.supported()
        out["tool_calls"][0]["arguments"]["decisions"][0]["primary_proposition"] = entries[1]["evidence_id"]
        full = selection.normalize_selection(out, self.task, "R1", 1, ["a"])
        self.assertEqual("le X", full["tool_calls"][0]["arguments"]["decisions"][0]["primary_proposition"]["quote"])
        out["tool_calls"][0]["arguments"]["decisions"][0]["primary_proposition"] = entries[0]["evidence_id"]
        with self.assertRaises(ValidationError): selection.normalize_selection(out, self.task, "R1", 1, ["a"])

    def test_ambiguous_intersection_omitted_no_supported_or_replace(self):
        self.task["supplied_atom_catalog"][0].update(quote="X X", end_char=3)
        self.task["raw_targets"][0].update(start_char=2, end_char=3)
        catalog = selection.evidence_catalog(self.task, ["a"])
        self.assertEqual(1, catalog["ambiguous_omitted"])
        self.assertFalse(any(e["target_eligible"] for e in catalog["entries"]))
        schema = selection.selection_schema(self.task, "R1", 1, ["a"])
        text = json.dumps(schema)
        self.assertNotIn('"const": "supported"', text)
        self.assertNotIn('"const": "replace"', text)
        self.assertIn('"const": "uncertain"', text)
        selection.selection_decoding(self.task, "R1", 1, ["a"])

    def test_primary_membership_host_guard_before_normalized_response(self):
        self.task["original_proposals"][0]["proposal"]["evidence_ref_ids"] = ["b"]
        with self.assertRaisesRegex(ValueError, "primary_not_selected_evidence"):
            selection.normalize_selection(self.supported(), self.task, "R1", 1, ["a"])

    def test_duplicate_witnesses_schema_and_finite_grammar(self):
        out = submit(self.task, [dict(proposal_id=self.pid, verdict="defect_found", reason="Address check",
            defect_type="qualification", witnesses=[self.eid, self.eid], correction=dict(action="reject"))])
        with self.assertRaises(ValidationError): selection.normalize_selection(out, self.task, "R1", 1, ["a"])
        schema = selection.selection_schema(self.task, "R1", 1, ["a"])
        selection.selection_decoding(self.task, "R1", 1, ["a"])
        def visit(n):
            if isinstance(n, dict):
                if "witnesses" in n.get("properties", {}):
                    w = n["properties"]["witnesses"]
                    self.assertTrue(w["uniqueItems"]); self.assertEqual([self.eid], w["items"]["enum"])
                for v in n.values(): visit(v)
            elif isinstance(n, list):
                for v in n: visit(v)
        visit(schema)

    def test_open_span_exact_selection_and_final_turn_lock(self):
        out = dict(schema_version=selection.VERSION, tool_calls=[dict(name="open_span", arguments=dict(span_selection_id=self.eid))])
        full = selection.normalize_selection(out, self.task, "R2", 1, ["a"])
        args = full["tool_calls"][0]["arguments"]
        self.assertEqual(dict(atom_id="a", start_char=0, end_char=7, quote="Rule X."), args)
        with self.assertRaises(ValidationError): selection.normalize_selection(out, self.task, "R2", 2, ["a"])

    def test_compact_prompt_contains_metadata_once_and_adapter_matches(self):
        messages = runtime.initial_messages(self.task, "R1")
        data = json.loads(messages[1]["content"])
        self.assertEqual(selection.model_catalog(self.task, ["a"]), data["selection_catalog"])
        self.assertNotIn("quote", json.dumps(data["selection_catalog"]))
        adapter = JobsAdapter(dict(model=MODEL, jobs_url="https://example.invalid/v1/jobs", token="synthetic"))
        adapter.prepare_payload(messages, task=self.task, turn=1, arm="R1", attempt_id="local")
        data["selection_catalog"]["entries"] = []
        messages[1]["content"] = json.dumps(data)
        with self.assertRaisesRegex(ValueError, "selection_catalog_prompt_mismatch"):
            adapter.prepare_payload(messages, task=self.task, turn=1, arm="R1", attempt_id="local")

    def test_adapter_raw_parse_and_nonstop_diagnostics(self):
        adapter = JobsAdapter(dict(model=MODEL, jobs_url="https://example.invalid/v1/jobs", token="synthetic"))
        for finish, content in [("stop", '{"x":1,"x":2}'), ("length", "partial")]:
            body = dict(choices=[dict(finish_reason=finish, message=dict(content=content))])
            with patch("knowledge_base.pipeline_v1.repair_agent.adapter.complete_job", return_value=(body, dict(job_id="local", latency_ms=1))):
                response = adapter(runtime.initial_messages(self.task, "R1"), task=self.task, turn=1, arm="R1", attempt_id="local")
            self.assertIsNone(response["output"])
            self.assertEqual(content, response["raw_content"])
            self.assertTrue(response["parse_error"])

    def test_all_full_and_selection_formal_checks_without_downgrade(self):
        for contract, cases in [("full_v2", fixtures()), ("selection_v1", selection_fixtures())]:
            for f in cases:
                with self.subTest(contract=contract, case=f["case_id"]):
                    self.assertEqual(f["expected_valid"], validate_output(f["output"], f["task"], f["arm"], f["turn"], contract=contract)["valid"])
        f = next(f for f in selection_fixtures() if f["case_id"] == "unique_witnesses")
        witnesses = f["output"]["tool_calls"][0]["arguments"]["decisions"][0]["witnesses"]
        self.assertEqual(2, len(witnesses)); self.assertEqual(witnesses[0], witnesses[1])
        with tempfile.TemporaryDirectory() as tmp:
            report = run_formal_probe(tmp, case_ids=["unique_witnesses"])
        self.assertEqual("pass", report["host_check_status"])
        self.assertEqual("pass", report["selection_check_status"])
        self.assertEqual(0, report["cost_summary"]["attempts"])

    def test_real_v6_preflight_and_expansion_catalog_within_cap(self):
        root = Path(__file__).resolve().parents[1] / "outputs"
        m = build_tasks(root / "plan11_semantic_v6_gate_20261011/run/run.json",
            root / "plan12_agent_repair_20261011/inputs/review.source_exact.v2.json",
            root / "source_store_v1", root / "plan04_sentence_atoms_v1")
        for task in m["tasks"]:
            if not task["original_proposals"]: continue
            estimate = runtime.estimate_preflight(task, "R2")
            self.assertLessEqual(max(estimate["estimated_input_tokens"], estimate["second_turn_input_bound"]), 6000)
            session = runtime.configure_context_budget(RepairSession(task, "R2"))
            event = session.call_tool("expand_context", dict(direction="after", reason="Check nearby qualification."))
            self.assertTrue(event["ok"]); self.assertTrue(event["result"]["atoms"])
            messages = runtime.next_messages(task, "R2", session, [event])
            self.assertEqual(selection.model_catalog(task, session.state["read_atom_ids"]), json.loads(messages[1]["content"])["selection_catalog"])


if __name__ == "__main__": unittest.main()
