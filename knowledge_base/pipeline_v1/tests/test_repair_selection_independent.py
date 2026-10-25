"""Independent protocol tests for the Plan12 finite evidence-selection wire.

These tests verify source binding and deterministic reconstruction only. They
do not judge whether a quoted span supports an AU claim semantically.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import ValidationError

from knowledge_base.pipeline_v1.repair_agent.core import MODEL, load
from knowledge_base.pipeline_v1.au_candidate_store.core import _hash
from knowledge_base.pipeline_v1.repair_agent.formal_probe import synthetic_task
from knowledge_base.pipeline_v1.repair_agent.formal_probe import selection_fixtures, validate_output
from knowledge_base.pipeline_v1.repair_agent.runtime import (
    fingerprint, initial_messages, next_messages, run_arm,
)
from knowledge_base.pipeline_v1.repair_agent.selection import (
    VERSION, evidence_catalog, model_catalog, normalize_selection,
    selection_decoding, selection_schema,
)
from knowledge_base.pipeline_v1.repair_agent.tools import RepairSession
from knowledge_base.pipeline_v1.tests.test_repair_grammar_independent import _load_lark


PIPELINE = Path(__file__).resolve().parents[1]
V6_MANIFEST = PIPELINE / "repair_agent" / "local_artifacts" / "v6" / "manifest.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON310 = Path(r"C:\Users\ducva\AppData\Local\Programs\Python\Python310\python.exe")
GRAMMAR_CHILD_ENV = "COLIEE_SELECTION_GRAMMAR_CHILD"


def _entry(task, read_ids, quote, *, target_eligible=None):
    matches = [e for e in evidence_catalog(task, read_ids)["entries"]
               if e["quote"] == quote and
               (target_eligible is None or e["target_eligible"] is target_eligible)]
    if len(matches) != 1:
        raise AssertionError(f"expected one selection for {quote!r}; found {len(matches)}")
    return matches[0]


def _prompt_entries(catalog, atom_ids):
    columns = {name: i for i, name in enumerate(catalog["columns"])}
    return [{"evidence_id": row[columns["id"]],
             "atom_id": atom_ids[row[columns["atom_index"]]],
             "relative_start": row[columns["relative_start"]],
             "relative_end": row[columns["relative_end"]],
             "target_eligible": bool(row[columns["target_eligible"]])}
            for row in catalog["entries"]]


def _selection(task, decisions, *, name="submit_revision", arguments=None):
    args = arguments if arguments is not None else {
        "task_id": task["task_id"], "decisions": decisions,
    }
    return {"schema_version": VERSION,
            "tool_calls": [{"name": name, "arguments": args}]}


def _decision(task, *, verdict="supported", evidence_id=None, reason="Protocol fixture"):
    proposal_id = task["original_proposals"][0]["proposal_id"]
    value = {"proposal_id": proposal_id, "verdict": verdict, "reason": reason}
    if verdict == "supported":
        value["primary_proposition"] = evidence_id
    elif verdict == "defect_found":
        value.update(defect_type="qualification", witnesses=[evidence_id],
                     correction={"action": "reject"})
    return value


def _two_span_task():
    task = synthetic_task()
    source = "é😀 § 1. Echo. Echo."
    atom = task["supplied_atom_catalog"][0]
    atom.update(start_char=10, end_char=10 + len(source), quote=source)
    target = task["raw_targets"][0]
    target_quote = "é😀 § 1."
    target.update(start_char=10, end_char=10 + len(target_quote), quote=target_quote)
    task["source_hash"] = atom["source_hash"]
    return task


class RepairSelectionIndependentTests(unittest.TestCase):
    def setUp(self):
        self.task = synthetic_task()
        self.pid = self.task["original_proposals"][0]["proposal_id"]

    def test_finite_ids_are_unique_read_bound_and_view_bound(self):
        task = _two_span_task()
        available = evidence_catalog(task, ["a"])
        ids = [e["evidence_id"] for e in available["entries"]]
        self.assertEqual(len(ids), len(set(ids)))
        schema = selection_schema(task, "R2", 1, ["a"])
        properties = schema["properties"]["tool_calls"]["items"]["oneOf"]
        submit = next(c for c in properties if c["properties"]["name"]["const"] == "submit_revision")
        primary_ids = submit["properties"]["arguments"]["properties"]["decisions"]["items"]["oneOf"][0]["properties"]["primary_proposition"]["enum"]
        self.assertEqual([e["evidence_id"] for e in available["entries"]
                          if e["target_eligible"]], primary_ids)

        with self.assertRaises(ValueError):
            evidence_catalog(task, ["a", "a"])
        with self.assertRaises(ValueError):
            evidence_catalog(task, ["foreign"])

        before_expansion = {e["evidence_id"] for e in evidence_catalog(task, ["a"])["entries"]}
        stale = next(e for e in evidence_catalog(task, ["a", "b"])["entries"]
                     if e["atom_id"] == "b")
        self.assertNotIn(stale["evidence_id"], before_expansion)
        with self.assertRaises(ValidationError):
            normalize_selection(_selection(task, [_decision(
                task, evidence_id=stale["evidence_id"]) ]), task, "R2", 1, ["a"])
        with self.assertRaises(ValidationError):
            normalize_selection(_selection(task, [_decision(task, evidence_id="e-" + "0" * 64)]),
                                task, "R2", 1, ["a"])

    def test_unicode_selection_reconstructs_exact_quote_and_offsets(self):
        task = _two_span_task()
        selected = _entry(task, ["a"], "é😀 § 1.", target_eligible=True)
        normalized = normalize_selection(_selection(
            task, [_decision(task, evidence_id=selected["evidence_id"])]), task, "R1", 1, ["a"])
        witness = normalized["tool_calls"][0]["arguments"]["decisions"][0]["primary_proposition"]
        self.assertEqual({"atom_id": "a", "quote": "é😀 § 1."}, witness)
        session = RepairSession(task, "R1")
        result = session.call_tool("submit_revision", normalized["tool_calls"][0]["arguments"])
        self.assertTrue(result["ok"], result)
        span = result["result"]["verified_assessments"][0]["evidence_spans"][0]
        self.assertEqual(selected["start_char"], span["start_char"])
        self.assertEqual(selected["end_char"], span["end_char"])
        self.assertEqual("é😀 § 1.", span["quote"])

    def test_repeated_subquote_is_omitted_or_explicitly_rejected(self):
        task = _two_span_task()
        atom = task["supplied_atom_catalog"][0]
        repeated_start = atom["quote"].index("Echo.")
        task["raw_targets"][0].update(
            start_char=atom["start_char"] + repeated_start,
            end_char=atom["start_char"] + repeated_start + len("Echo."),
            quote="Echo.")
        catalog = evidence_catalog(task, ["a"])
        self.assertGreater(catalog["ambiguous_omitted"], 0)
        # Neither occurrence may be picked by first-match reconstruction.
        self.assertFalse(any(e["quote"] == "Echo." for e in catalog["entries"]))
        with self.assertRaises(ValidationError):
            normalize_selection(_selection(task, [_decision(task, evidence_id="Echo.")]),
                                task, "R1", 1, ["a"])

    def test_primary_must_be_in_target_and_in_selected_au_evidence(self):
        task = copy.deepcopy(self.task)
        task["expansion_atom_catalog"][0].update(
            start_char=8, end_char=17, quote="Unless Y.", direction="after")
        context = _entry(task, ["a", "b"], "Unless Y.", target_eligible=False)
        with self.assertRaises(ValidationError):
            normalize_selection(_selection(
                task, [_decision(task, evidence_id=context["evidence_id"])]),
                task, "R2", 1, ["a", "b"])

        target = _entry(task, ["a", "b"], "Rule X.", target_eligible=True)
        bad = _decision(task, evidence_id=target["evidence_id"])
        # v2 host validation must enforce primary-proposition membership in AU evidence.
        bad["verdict"] = "defect_found"
        del bad["primary_proposition"]
        bad.update(defect_type="qualification", witnesses=[target["evidence_id"]],
                   correction={"action": "replace", "replacements": [{
                       "au": {"kind": "holding", "claim": "replacement",
                              "evidence_ref_ids": ["b"], "speaker": "current_court",
                              "attribution_role": "proposition"},
                       "primary_proposition": target["evidence_id"]}]})
        with self.assertRaisesRegex(ValueError, "primary_not_selected_evidence"):
            normalize_selection(_selection(task, [bad]), task, "R2", 1, ["a", "b"])

    def test_supported_and_uncertain_preserve_distinct_host_outcomes(self):
        task = copy.deepcopy(self.task)
        target = _entry(task, ["a"], "Rule X.", target_eligible=True)
        supported = normalize_selection(_selection(
            task, [_decision(task, evidence_id=target["evidence_id"])]), task, "R1", 1, ["a"])
        session = RepairSession(task, "R1")
        accepted = session.call_tool("submit_revision", supported["tool_calls"][0]["arguments"])
        self.assertTrue(accepted["ok"], accepted)
        revision = accepted["result"]
        self.assertEqual("supported", revision["assessments"][0]["verdict"])
        self.assertFalse(revision["verified_assessments"][0]["accepted_semantic"])

        task = copy.deepcopy(self.task)
        uncertain = normalize_selection(_selection(task, [_decision(
            task, verdict="uncertain", reason="Cannot identify primary" )]), task, "R1", 1, ["a"])
        session = RepairSession(task, "R1")
        result = session.call_tool("submit_revision", uncertain["tool_calls"][0]["arguments"])
        self.assertTrue(result["ok"], result)
        self.assertEqual("uncertain", result["result"]["assessments"][0]["verdict"])
        self.assertEqual("preserve_baseline", result["result"]["preservation_decisions"][0]["decision"])

    def test_context_expansion_rebuilds_selectable_catalog_for_new_view(self):
        task = copy.deepcopy(self.task)
        session = RepairSession(task, "R2")
        initial = json.loads(initial_messages(task, "R2")[1]["content"])
        initial_ids = {e["evidence_id"] for e in _prompt_entries(
            initial["selection_catalog"], [a["atom_id"] for a in task["supplied_atom_catalog"]])}
        event = session.call_tool("expand_context", {"direction": "after", "reason": "Read context"})
        self.assertTrue(event["ok"], event)
        following = json.loads(next_messages(task, "R2", session, [event])[1]["content"])
        following_atoms = list(session.state["read_atom_ids"])
        later_entries = _prompt_entries(following["selection_catalog"], following_atoms)
        later_ids = {e["evidence_id"] for e in later_entries}
        self.assertTrue(later_ids - initial_ids)
        added = next(e for e in later_entries if e["atom_id"] == "b")
        opened = normalize_selection(_selection(task, [], name="open_span", arguments={
            "span_selection_id": added["evidence_id"]}), task, "R2", 1, ["a", "b"])
        args = opened["tool_calls"][0]["arguments"]
        self.assertEqual("Unless Y.", args["quote"])
        self.assertEqual((8, 17), (args["start_char"], args["end_char"]))

    def test_v6_primary_catalog_clips_partial_atoms_and_ignores_review_gold(self):
        manifest = load(V6_MANIFEST)
        expected = {"011904": (14, 1), "013948": (9, 1),
                    "045155": (18, 2), "099980": (15, 2)}
        by_case = {t["case_id"]: t for t in manifest["tasks"]}
        for case_id, (atom_count, partial_count) in expected.items():
            task = by_case[case_id]
            self.assertEqual(atom_count, len(task["supplied_atom_catalog"]))
            target = task["raw_targets"][0]
            partial = [a for a in task["supplied_atom_catalog"]
                       if a["start_char"] < target["end_char"] < a["end_char"]
                       or a["start_char"] < target["start_char"] < a["end_char"]]
            self.assertEqual(partial_count, len(partial), case_id)
            catalog = evidence_catalog(task, [a["atom_id"] for a in task["supplied_atom_catalog"]])
            for atom in partial:
                clipped = [e for e in catalog["entries"] if e["atom_id"] == atom["atom_id"]
                           and e["target_eligible"] and e["start_char"] >= target["start_char"]
                           and e["end_char"] <= target["end_char"]]
                self.assertTrue(clipped, (case_id, atom["atom_id"]))
                self.assertTrue(all(e["quote"] == atom["quote"][
                    e["start_char"] - atom["start_char"]:e["end_char"] - atom["start_char"]]
                    for e in clipped))

        task = copy.deepcopy(by_case["045155"])
        original = model_catalog(task, [a["atom_id"] for a in task["supplied_atom_catalog"]])
        task["review_oracle"] = [{"secret": "poisoned-review-oracle"}]
        task["semantic_gold"] = True
        self.assertEqual(original, model_catalog(task, [a["atom_id"] for a in task["supplied_atom_catalog"]]))
        serialized = json.dumps(initial_messages(task, "R2"), ensure_ascii=False)
        self.assertNotIn("poisoned-review-oracle", serialized)

    def test_model_output_schema_has_only_finite_evidence_selectors(self):
        task = _two_span_task()
        schema = selection_schema(task, "R2", 1, ["a"])
        serialized = json.dumps(schema)
        for forbidden in ('"quote"', '"start_char"', '"end_char"', '"relative_start"', '"relative_end"'):
            self.assertNotIn(forbidden, serialized)
        catalog = model_catalog(task, ["a"])
        self.assertTrue(catalog["entries"])
        self.assertEqual(["id", "atom_index", "relative_start", "relative_end", "target_eligible"],
                         catalog["columns"])
        self.assertTrue(all(len(e) == len(catalog["columns"]) for e in catalog["entries"]))

    def test_legacy_v2_full_response_is_rejected_at_selection_boundary(self):
        task = copy.deepcopy(self.task)
        legacy = {"tool_calls": [{"name": "submit_revision", "arguments": {
            "task_id": task["task_id"], "decisions": [{
                "proposal_id": self.pid, "verdict": "supported", "reason": "old wire",
                "primary_proposition": {"atom_id": "a", "quote": "Rule X."}}]}}]}
        with self.assertRaises(ValidationError):
            normalize_selection(legacy, task, "R1", 1, ["a"])

    def test_formal_probe_fixtures_migrate_to_selection_contract_without_drift(self):
        mismatches = []
        fixtures = selection_fixtures()
        self.assertTrue(fixtures)
        for fixture in fixtures:
            actual = validate_output(fixture["output"], fixture["task"],
                                     fixture["arm"], fixture["turn"],
                                     contract="selection_v1")["valid"]
            if actual is not fixture["expected_valid"]:
                mismatches.append((fixture["case_id"], fixture["expected_valid"], actual))
        self.assertEqual([], mismatches)

    def test_selection_grammar_runs_in_diagnostic_python310_child(self):
        if not PYTHON310.is_file():
            self.skipTest(f"diagnostic Python 3.10 unavailable: {PYTHON310}")
        env = os.environ.copy()
        env[GRAMMAR_CHILD_ENV] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [str(PYTHON310), "-m", "unittest",
             "knowledge_base.pipeline_v1.tests.test_repair_selection_independent.RepairSelectionGrammarChildTests", "-v"],
            cwd=REPO_ROOT, env=env, text=True, capture_output=True, timeout=180,
        )
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertIn("Ran 1 test", output, output)


class RepairSelectionGrammarChildTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get(GRAMMAR_CHILD_ENV) == "1", "runs in explicit grammar child")
    def test_finite_ids_and_unique_witnesses_are_enforced_by_emitted_grammar(self):
        task = _two_span_task()
        evidence = _entry(task, ["a"], "é😀 § 1.", target_eligible=True)
        grammar = selection_decoding(task, "R1", 1, ["a"])["ebnf"]
        lark, converter = _load_lark()
        parser = lark.Lark(converter(grammar), start="root", parser="earley", lexer="dynamic_complete")
        serialize = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        valid = _selection(task, [_decision(task, evidence_id=evidence["evidence_id"])])
        parser.parse(serialize(valid))
        foreign = copy.deepcopy(valid)
        foreign["tool_calls"][0]["arguments"]["decisions"][0]["primary_proposition"] = "foreign-id"
        with self.assertRaises(lark.exceptions.UnexpectedInput):
            parser.parse(serialize(foreign))

        duplicate = _decision(task, verdict="defect_found", evidence_id=evidence["evidence_id"])
        duplicate["witnesses"] = [evidence["evidence_id"], evidence["evidence_id"]]
        with self.assertRaises(lark.exceptions.UnexpectedInput):
            parser.parse(serialize(_selection(task, [duplicate])))


class RepairSelectionAdapterCacheTests(unittest.TestCase):
    def setUp(self):
        self.task = synthetic_task()
        self.pid = self.task["original_proposals"][0]["proposal_id"]

    def test_duplicate_json_key_survives_as_transport_diagnostic(self):
        from knowledge_base.pipeline_v1.repair_agent.adapter import JobsAdapter

        task = copy.deepcopy(self.task)
        messages = initial_messages(task, "R1")
        adapter = JobsAdapter({"model": MODEL, "enable_thinking": False,
                               "jobs_url": "https://invalid.local", "token": "test-token"})
        content = '{"schema_version":"repair-selection-v1","schema_version":"repair-selection-v1","tool_calls":[]}'
        body = {"choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": {}}
        trace = {"job_id": "local-test", "latency_ms": 1}
        with patch("knowledge_base.pipeline_v1.repair_agent.adapter.complete_job",
                   return_value=(body, trace)):
            response = adapter(messages, task=task, turn=1, arm="R1", attempt_id="a" * 64)
        self.assertIsNone(response["output"])
        self.assertEqual("ValueError", response["parse_error"]["type"])
        self.assertIn("duplicate_model_json_key", response["parse_error"]["message"])

    def test_malformed_json_keeps_json_decode_diagnostic(self):
        from knowledge_base.pipeline_v1.repair_agent.adapter import JobsAdapter

        task = copy.deepcopy(self.task)
        messages = initial_messages(task, "R1")
        adapter = JobsAdapter({"model": MODEL, "enable_thinking": False,
                               "jobs_url": "https://invalid.local", "token": "test-token"})
        content = '{"schema_version":"repair-selection-v1","tool_calls":['
        body = {"choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": {}}
        with patch("knowledge_base.pipeline_v1.repair_agent.adapter.complete_job",
                   return_value=(body, {"job_id": "local-malformed", "latency_ms": 1})):
            response = adapter(messages, task=task, turn=1, arm="R1", attempt_id="b" * 64)
        self.assertIsNone(response["output"])
        self.assertEqual("JSONDecodeError", response["parse_error"]["type"])
        self.assertEqual(content, response["raw_content"])

    def test_length_finish_reason_does_not_accept_partial_json_and_is_identifiable(self):
        from knowledge_base.pipeline_v1.repair_agent.adapter import JobsAdapter

        task = copy.deepcopy(self.task)
        messages = initial_messages(task, "R1")
        adapter = JobsAdapter({"model": MODEL, "enable_thinking": False,
                               "jobs_url": "https://invalid.local", "token": "test-token"})
        content = '{"schema_version":"repair-selection-v1","tool_calls":[{"name":"submit_revision"'
        body = {"choices": [{"finish_reason": "length", "message": {"content": content}}], "usage": {}}
        with patch("knowledge_base.pipeline_v1.repair_agent.adapter.complete_job",
                   return_value=(body, {"job_id": "local-truncated", "latency_ms": 1})):
            response = adapter(messages, task=task, turn=1, arm="R1", attempt_id="c" * 64)
        self.assertIsNone(response["output"])
        self.assertEqual("length", response["finish_reason"])
        self.assertEqual(_hash(content), response["content_sha256"])
        self.assertEqual(content, response["raw_content"])
        self.assertEqual("FinishReason", response["parse_error"]["type"])
        self.assertEqual("non_stop_completion", response["parse_error"]["message"])

    def test_runtime_selection_submission_and_checkpoint_replay_do_not_redispatch(self):
        task = synthetic_task()
        manifest = {"tasks": [task], "manifest_sha256": _hash([task]),
                    "source_workload": [{"case_id": task["case_id"]}],
                    "task_case_ids": [task["case_id"]], "task_workload": "synthetic protocol fixture"}

        class LocalSelectionAdapter:
            is_mock = False

            def __init__(self):
                self.calls = 0
                self.identity = {"kind": "local_selection_protocol_fixture",
                                 "wire_version": VERSION, "fixture": "uncertain-v1"}

            def prepare_payload(self, messages, **_kwargs):
                return {"messages": messages}

            def __call__(self, _messages, *, task, **_kwargs):
                self.calls += 1
                return {"output": _selection(task, [_decision(
                    task, verdict="uncertain", reason="Local protocol fixture")]),
                        "finish_reason": "stop", "provider_usage": None}

        with tempfile.TemporaryDirectory() as temp:
            adapter = LocalSelectionAdapter()
            with patch("knowledge_base.pipeline_v1.repair_agent.runtime.verify_manifest", return_value=True):
                first = run_arm(manifest, "R1", temp, adapter)
                second = run_arm(manifest, "R1", temp, adapter)
            self.assertEqual("complete", first["status"])
            self.assertEqual("revision_submitted", first["tasks"][0]["status"])
            self.assertEqual("complete", second["status"])
            self.assertEqual(1, adapter.calls)
            self.assertEqual(1, len(second["attempts"]))
            self.assertEqual("uncertain", second["tasks"][0]["session"]["revision"]["assessments"][0]["verdict"])

    def test_wire_version_participates_in_cache_fingerprint(self):
        task = copy.deepcopy(self.task)
        base = {"kind": "jobs_ebnf_selection_host_v1", "wire_version": VERSION}
        old = {**base, "wire_version": "repair-wire-v2"}
        self.assertNotEqual(fingerprint(task, "R2", base), fingerprint(task, "R2", old))


if __name__ == "__main__":
    unittest.main()
