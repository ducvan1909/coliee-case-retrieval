"""Source-bound protocol regressions from sanitized Plan 12 live failures.

These fixtures preserve observed wire shapes and accounting only. They do not
adjudicate AU correctness and are not gold labels.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jsonschema import Draft202012Validator

from knowledge_base.pipeline_v1.repair_agent import runtime
from knowledge_base.pipeline_v1.repair_agent.adapter import JobsAdapter
from knowledge_base.pipeline_v1.repair_agent.runtime import MockAdapter, run_arm
from knowledge_base.pipeline_v1.repair_agent.runtime import (
    bound_messages,
    configure_context_budget,
    estimate_input,
    model_result,
    next_messages,
)
from knowledge_base.pipeline_v1.repair_agent.tools import RepairSession
from knowledge_base.pipeline_v1.repair_agent.wire import (
    decoding,
    normalize,
    payload,
    wire_schema,
)
from knowledge_base.pipeline_v1.repair_agent.probe import CASES, run_probe
from knowledge_base.pipeline_v1.repair_agent.core import build_tasks


ROOT = Path(__file__).resolve().parents[3]
PRIOR_FAILURES = ROOT / "knowledge_base" / "pipeline_v1" / "outputs" / "plan12_repair_fix_20261011" / "prior_live_failures.json"
V6_RUN = ROOT / "knowledge_base" / "pipeline_v1" / "outputs" / "plan11_semantic_v6_gate_20261011" / "run" / "run.json"
EXACT_REVIEW = ROOT / "knowledge_base" / "pipeline_v1" / "outputs" / "plan12_agent_repair_20261011" / "inputs" / "review.source_exact.v2.json"
SOURCE_STORE = ROOT / "knowledge_base" / "pipeline_v1" / "outputs" / "source_store_v1"
ATOM_ROOT = ROOT / "knowledge_base" / "pipeline_v1" / "outputs" / "plan04_sentence_atoms_v1"


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _unresolved_submit(task):
    decisions = [{
        "proposal_id": proposal["proposal_id"],
        "verdict": "uncertain",
        "reason": "bounded protocol regression",
    } for proposal in task["original_proposals"]]
    return {"tool_calls": [{"name": "submit_revision", "arguments": {
        "task_id": task["task_id"], "decisions": decisions,
    }}]}


def _run_adapter(script):
    return MockAdapter(script)


class _RepairFixtureBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = (V6_RUN, EXACT_REVIEW, SOURCE_STORE / "source_store_manifest.json",
                    ATOM_ROOT / "sentence_atom_build_manifest.json")
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError("Plan 12 frozen source fixture prerequisite missing")
        cls.manifest = build_tasks(V6_RUN, EXACT_REVIEW, SOURCE_STORE, ATOM_ROOT)
        cls.tasks = {task["case_id"]: task for task in cls.manifest["tasks"]}

    def task(self, case_id="013948"):
        return copy.deepcopy(self.tasks[case_id])


class Plan12LiveFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PRIOR_FAILURES.is_file():
            raise RuntimeError("sanitized Plan 12 live failure fixture is missing")
        cls.fixture = _read_json(PRIOR_FAILURES)

    def test_fixture_preserves_actual_r1_truncation_and_invalid_revision_witnesses(self):
        r1 = next(row for row in self.fixture["observations"] if row["arm"] == "R1")
        self.assertEqual(r1["old_run_status"], "complete")
        self.assertEqual(r1["provider_total_tokens"], 7463)
        self.assertEqual(len(r1["tasks"]), 2)
        self.assertTrue(all(task["status"] == "technical_invalid" for task in r1["tasks"]))
        attempts = r1["attempts"]
        self.assertEqual(attempts[0]["finish_reason"], "length")
        self.assertEqual(attempts[0]["provider_usage"]["completion_tokens"], 1200)
        self.assertIsNone(attempts[0]["output"])
        second_call = attempts[1]["output"]["tool_calls"]
        self.assertEqual(len(second_call), 1)
        bad_au = second_call[0]["arguments"]["decisions"][0]["replacements"][0]["au"]
        self.assertIsInstance(bad_au, str)

    def test_fixture_preserves_actual_r2_repeated_read_and_accounting(self):
        r2 = next(row for row in self.fixture["observations"] if row["arm"] == "R2")
        self.assertEqual(r2["provider_total_tokens"], 5968)
        first, second = r2["attempts"]
        self.assertEqual(first["task_id"], "task-83343db74c9a9ee637166927b44f04608cc2d732b5c52c54ef31b349ed578e28")
        names = [call["name"] for call in first["output"]["tool_calls"]]
        self.assertEqual(len(names), 15)
        self.assertEqual(names.count("open_span"), 15)
        self.assertEqual(second["output"]["tool_calls"][0]["name"], "get_repair_task")
        self.assertEqual(second["provider_usage"]["prompt_tokens"], 3050)
        self.assertEqual(r2["tasks"][1]["status"], "budget_exhausted")


class Plan12WireRegressionTests(_RepairFixtureBase):
    def _wire_ids(self, task):
        return [atom["atom_id"] for atom in task["supplied_atom_catalog"]]

    def test_compact_keep_requires_explicit_primary_witness_and_does_not_invent_fields(self):
        task = self.task("013948")
        proposal = task["original_proposals"][0]
        ids = self._wire_ids(task)
        missing_witness = {"tool_calls": [{"name": "submit_revision", "arguments": {
            "task_id": task["task_id"], "decisions": [{
                "proposal_id": item["proposal_id"],
                "verdict": "supported" if item["proposal_id"] == proposal["proposal_id"] else "uncertain",
                "reason": "keep baseline" if item["proposal_id"] == proposal["proposal_id"] else "no primary available",
            } for item in task["original_proposals"]],
        }}]}
        with self.assertRaises(Exception):
            normalize(missing_witness, task, "R1", 1, ids)
        explicit = copy.deepcopy(missing_witness)
        keep = explicit["tool_calls"][0]["arguments"]["decisions"][0]
        target = task["raw_targets"][0]
        atom = next(a for a in task["supplied_atom_catalog"]
                    if a["start_char"] < target["end_char"] and a["end_char"] > target["start_char"])
        start = max(atom["start_char"], target["start_char"])
        end = min(atom["end_char"], target["end_char"])
        keep["primary_proposition"] = {"atom_id": atom["atom_id"],
                                       "quote": atom["quote"][start-atom["start_char"]:min(end, start+20)-atom["start_char"]]}
        normalized = normalize(explicit, task, "R1", 1, ids)
        self.assertEqual(normalized["tool_calls"][0]["arguments"]["decisions"][0]["primary_proposition"],
                         keep["primary_proposition"])

    def test_evidenced_correction_never_infers_missing_au_fields(self):
        task = self.task("013948")
        proposal = task["original_proposals"][0]
        compact_au = {"kind": "holding", "claim": "fixture claim",
                      "evidence_ref_ids": [self._wire_ids(task)[0]],
                      "speaker": "current_court", "attribution_role": "proposition"}
        decisions = [{
                "proposal_id": proposal["proposal_id"], "verdict": "defect_found",
                "defect_type": "qualification", "witnesses": [{"atom_id": self._wire_ids(task)[0], "quote": task["supplied_atom_catalog"][0]["quote"][:12]}],
                "reason": "explicit fixture; not semantic evidence", "correction": {"action": "replace", "replacements": [
                    {"au": compact_au, "primary_proposition": {
                        "atom_id": self._wire_ids(task)[0],
                        "quote": task["supplied_atom_catalog"][0]["quote"][:12],
                    }}]},
        }]
        decisions.extend({"proposal_id": item["proposal_id"], "verdict": "uncertain",
                          "reason": "no primary available"}
                         for item in task["original_proposals"][1:])
        wire = {"tool_calls": [{"name": "submit_revision", "arguments": {
            "task_id": task["task_id"], "decisions": decisions,
        }}]}
        normalized = normalize(wire, task, "R1", 1, self._wire_ids(task))
        au = normalized["tool_calls"][0]["arguments"]["decisions"][0]["correction"]["replacements"][0]["au"]
        self.assertEqual(au["claim"], "fixture claim")
        self.assertEqual(au["speaker"], "current_court")
        self.assertEqual(au["evidence_ref_ids"], [self._wire_ids(task)[0]])
        self.assertIsNone(au["other_kind"])
        self.assertEqual(au["needs_context"], [])

        missing_other_label = copy.deepcopy(wire)
        missing_other_label["tool_calls"][0]["arguments"]["decisions"][0]["correction"]["replacements"][0]["au"]["kind"] = "other"
        with self.assertRaises(Exception):
            normalize(missing_other_label, task, "R1", 1, self._wire_ids(task))

        for missing in ("claim", "speaker", "evidence_ref_ids"):
            with self.subTest(missing=missing):
                incomplete_au = copy.deepcopy(wire)
                del incomplete_au["tool_calls"][0]["arguments"]["decisions"][0]["correction"]["replacements"][0]["au"][missing]
                with self.assertRaises(Exception):
                    normalize(incomplete_au, task, "R1", 1, self._wire_ids(task))

    def test_wire_schema_has_one_call_and_only_submit_on_final_r2_turn(self):
        task = self.task("013948")
        ids = self._wire_ids(task)
        Draft202012Validator.check_schema(wire_schema(task, "R2", 1, ids))
        first = wire_schema(task, "R2", 1, ids)["properties"]["tool_calls"]
        final = wire_schema(task, "R2", 2, ids)["properties"]["tool_calls"]
        self.assertEqual(first["maxItems"], 1)
        self.assertGreater(len(first["items"]["oneOf"]), 1)
        self.assertEqual(final["maxItems"], 1)
        self.assertEqual([x["properties"]["name"]["const"] for x in final["items"]["oneOf"]], ["submit_revision"])

        non_submit = {"tool_calls": [{"name": "get_repair_task", "arguments": {}}]}
        with self.assertRaises(Exception):
            normalize(non_submit, task, "R2", 2, ids)
        multi = {"tool_calls": [{"name": "get_repair_task", "arguments": {}},
                                {"name": "get_related_aus", "arguments": {}}]}
        with self.assertRaises(Exception):
            normalize(multi, task, "R2", 1, ids)

    def test_local_grammar_generation_is_deterministic_and_bound_to_wire_schema(self):
        task = self.task("013948")
        ids = self._wire_ids(task)
        generated = decoding(task, "R2", 2, ids)
        self.assertEqual(generated, decoding(task, "R2", 2, ids))
        self.assertTrue(generated["ebnf"].startswith("root ::= "))
        self.assertIn("submit_revision", generated["ebnf"])
        self.assertNotIn("get_repair_task", generated["ebnf"])
        schema = wire_schema(task, "R2", 2, ids)
        self.assertEqual(schema["properties"]["tool_calls"]["maxItems"], 1)

    def test_source_free_six_case_decoder_probe_prepares_only_bounded_payloads(self):
        with TemporaryDirectory() as folder:
            report = run_probe(Path(folder))
            payloads = {name: _read_json(Path(folder) / (name + ".payload.json")) for name, _ in CASES}
        self.assertEqual(len(report["cases"]), len(CASES))
        self.assertEqual([row["case"] for row in report["cases"]], [name for name, _ in CASES])
        self.assertEqual(report["status"], "prepared")
        self.assertEqual(report["semantic_quality"], "not_evaluated")
        self.assertTrue(all(row["backend_compilation"] == "pending_probe" for row in report["cases"]))
        self.assertTrue(all(estimate_input(request["messages"]) <= runtime.POLICY["input_tokens"]
                            for request in payloads.values()))
        for name in ("replace_types", "supported_witness"):
            self.assertTrue(payloads[name]["ebnf"])
        self.assertIn("submit_revision", payloads["calls"]["ebnf"])

    def test_forced_keep_and_replace_decoders_expose_only_the_selected_decision_branch(self):
        task = self.task("013948")
        ids = self._wire_ids(task)
        for verdict in ("supported", "uncertain", "defect_found"):
            with self.subTest(verdict=verdict):
                generated = decoding(task, "R1", 1, ids, forced_verdict=verdict)
                self.assertIn(verdict, generated["ebnf"])
                for other in {"supported", "uncertain", "defect_found"} - {verdict}:
                    encoded_terminal = json.dumps(json.dumps(other, separators=(",", ":")), ensure_ascii=True)
                    self.assertNotIn(encoded_terminal, generated["ebnf"])

    def test_json_schema_enforces_other_kind_conditional_while_grammar_is_not_claimed_compiled(self):
        task = self.task("013948")
        schema = wire_schema(task, "R1", 1, self._wire_ids(task))
        Draft202012Validator.check_schema(schema)
        submit = next(call for call in schema["properties"]["tool_calls"]["items"]["oneOf"]
                      if call["properties"]["name"].get("const") == "submit_revision")
        decision = next(choice for choice in submit["properties"]["arguments"]["properties"]["decisions"]["items"]["oneOf"]
                        if choice["properties"]["verdict"].get("const") == "defect_found")
        correction = next(choice for choice in decision["properties"]["correction"]["oneOf"] if choice["properties"]["action"].get("const") == "replace")
        au_schema = correction["properties"]["replacements"]["items"]["properties"]["au"]
        valid = {"kind": "other", "other_kind": "case-management rule", "claim": "fixture",
                 "evidence_ref_ids": [self._wire_ids(task)[0]], "speaker": "current_court",
                 "attribution_role": "proposition"}
        invalid_other = dict(valid, other_kind=None)
        invalid_non_other = dict(valid, kind="holding")
        invalid_non_other["other_kind"] = "a label that must be null"
        validator = Draft202012Validator(au_schema)
        self.assertTrue(validator.is_valid(valid))
        self.assertFalse(validator.is_valid(invalid_other))
        self.assertFalse(validator.is_valid(invalid_non_other))
        generated = decoding(task, "R1", 1, self._wire_ids(task))["ebnf"]
        self.assertIn("other_kind", generated)
        # The generated text is an invariant check only. xgrammar/lark are
        # absent in this environment, and the generator does not compile or
        # prove the schema's if/then/else conditionals are enforced remotely.

    def test_decoder_payload_locks_model_budget_and_final_turn_grammar(self):
        task = self.task("013948")
        ids = self._wire_ids(task)
        messages = runtime.initial_messages(task, "R2")
        request = payload(messages, task, "R2", 2, "attempt-fixture", ids)
        self.assertEqual(request["model"], runtime.MODEL)
        self.assertEqual(request["max_tokens"], runtime.POLICY["output_tokens"])
        self.assertEqual(request["chat_template_kwargs"], {"enable_thinking": False})
        self.assertIn("submit_revision", request["ebnf"])
        self.assertNotIn("open_span", request["ebnf"])
        for atom_id in ids:
            self.assertIn(atom_id, request["ebnf"])
        self.assertIn("attempt-fixture", request["messages"][-1]["content"])

    def test_read_receipts_do_not_echo_supplied_context_again(self):
        task = self.task("013948")
        session = RepairSession(task, "R2")
        event = session.call_tool("get_repair_task", {})
        self.assertTrue(event["ok"])
        receipt = model_result(event)
        serialized = json.dumps(receipt, ensure_ascii=False)
        self.assertNotIn("supplied_atom_catalog", serialized)
        self.assertNotIn("original_proposals", serialized)

        opened = session.call_tool("open_span", {"atom_id": task["supplied_atom_catalog"][0]["atom_id"]})
        self.assertTrue(opened["ok"])
        open_receipt = model_result(opened)
        self.assertNotIn("quote", open_receipt.get("result", {}))
        self.assertNotIn("case_id", open_receipt.get("result", {}))

        expanded = session.call_tool("expand_context", {
            "direction": task["expansion_atom_catalog"][0]["direction"],
            "reason": "bounded receipt probe",
        })
        self.assertTrue(expanded["ok"])
        expansion_receipt = model_result(expanded)
        self.assertNotIn("quote", json.dumps(expansion_receipt, ensure_ascii=False))
        self.assertNotIn("start_char", json.dumps(expansion_receipt, ensure_ascii=False))

    def test_jobs_payload_receives_expanded_context_catalog_for_next_turn(self):
        task = self.task("013948")
        self.assertTrue(task["expansion_atom_catalog"], "fixture requires bounded adjacent context")
        adapter = JobsAdapter({"model": runtime.MODEL, "enable_thinking": False,
                               "jobs_url": "https://fixture.invalid/jobs", "token": "fixture-token"})
        session = RepairSession(task, "R2")
        initial = json.loads(runtime.initial_messages(task, "R2")[1]["content"])
        initial_catalog = {row["atom_id"]: row for row in initial["supplied_atom_catalog"]}
        event = session.call_tool("expand_context", {"direction": task["expansion_atom_catalog"][0]["direction"],
                                                       "reason": "bounded fixture expansion"})
        self.assertTrue(event["ok"])
        added_ids = set(session.state["expanded_atom_ids"])
        messages = next_messages(task, "R2", session, [event])
        next_data = json.loads(messages[1]["content"])
        next_catalog = {row["atom_id"]: row for row in next_data["supplied_atom_catalog"]}
        self.assertTrue(set(initial_catalog) <= set(next_catalog))
        for atom_id, initial_atom in initial_catalog.items():
            self.assertEqual(next_catalog[atom_id], initial_atom)
        self.assertEqual(set(next_catalog) - set(initial_catalog), added_ids)
        request = adapter.prepare_payload(messages, task=task, turn=2, arm="R2", attempt_id="fixture-next")
        self.assertTrue(added_ids)
        self.assertTrue(added_ids <= set(next_catalog))
        self.assertIn("submit_revision", request["ebnf"])
        self.assertNotIn("open_span", request["ebnf"])
        for atom_id in added_ids:
            self.assertIn(atom_id, request["ebnf"])

    def test_context_admitter_keeps_whole_atoms_and_reserves_second_turn_under_cap(self):
        task = self.task("013948")
        session = configure_context_budget(RepairSession(task, "R2"))
        initial_ids = set(session.state["read_atom_ids"])
        direction = task["expansion_atom_catalog"][0]["direction"]
        event = session.call_tool("expand_context", {"direction": direction,
                                                       "reason": "context budget regression"})
        self.assertTrue(event["ok"])
        self.assertTrue(initial_ids <= set(session.state["read_atom_ids"]))
        added = set(session.state["expanded_atom_ids"])
        self.assertEqual(set(session.state["read_atom_ids"]) - initial_ids, added)
        for atom_id in added:
            whole = session.catalog[atom_id]
            self.assertIn(whole, task["expansion_atom_catalog"])
        next_request_messages = next_messages(task, "R2", session, [event])
        self.assertLessEqual(estimate_input(bound_messages(next_request_messages, "0" * 64)),
                             runtime.POLICY["input_tokens"])



class Plan12LiveRuntimeStatusTests(_RepairFixtureBase):
    def _script(self, task, output):
        return {task["task_id"]: [{"output": output, "mock_usage": None}]}

    def test_all_technical_invalid_tasks_make_run_failed(self):
        tasks = [self.tasks[case] for case in ("011904", "013948")]
        r1 = next(row for row in _read_json(PRIOR_FAILURES)["observations"] if row["arm"] == "R1")
        actual = {item["task_id"]: item for item in r1["attempts"]}
        script = {}
        for task in tasks:
            attempt = next(row for row in r1["attempts"] if row["task_id"] == task["task_id"])
            value = {"output": attempt["output"], "provider_usage": attempt["provider_usage"],
                     "finish_reason": attempt["finish_reason"], "mock_usage": None}
            script[task["task_id"]] = [value]
        with TemporaryDirectory() as folder:
            report = run_arm(self.manifest, "R1", folder, MockAdapter(script),
                             [task["task_id"] for task in tasks])
        self.assertTrue(all(row["status"] == "technical_invalid" for row in report["tasks"]))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["attempts"][0]["response"]["finish_reason"], "length")
        self.assertEqual(report["attempts"][0]["response"]["provider_usage"]["total_tokens"], 3549)

    def test_mixed_revision_and_technical_invalid_tasks_make_run_partial(self):
        invalid, valid = self.tasks["011904"], self.tasks["013948"]
        bad = {"tool_calls": [{"name": "get_repair_task", "arguments": {}},
                              {"name": "get_related_aus", "arguments": {}}]}
        script = {
            invalid["task_id"]: [{"output": bad, "mock_usage": None}],
            valid["task_id"]: [{"output": _unresolved_submit(valid), "mock_usage": None}],
        }
        with TemporaryDirectory() as folder:
            report = run_arm(self.manifest, "R1", folder, MockAdapter(script),
                             [invalid["task_id"], valid["task_id"]])
        by_id = {row["task_id"]: row["status"] for row in report["tasks"]}
        self.assertEqual(by_id[invalid["task_id"]], "technical_invalid")
        self.assertEqual(by_id[valid["task_id"]], "revision_submitted")
        self.assertEqual(report["status"], "partial")

    def test_provider_usage_cap_remains_incomplete_and_stops_before_tool_execution(self):
        task = self.tasks["011904"]

        class OverCapAdapter:
            is_mock = False
            identity = {"kind": "offline_cap_fixture", "case": "input_over_cap"}

            def __init__(self):
                self.calls = 0

            def __call__(self, messages, *, task, turn, arm, attempt_id):
                self.calls += 1
                return {"output": _unresolved_submit(task), "provider_usage": {
                    "prompt_tokens": runtime.POLICY["input_tokens"] + 1,
                    "completion_tokens": 1,
                    "total_tokens": runtime.POLICY["input_tokens"] + 2,
                }}

        adapter = OverCapAdapter()
        with TemporaryDirectory() as folder:
            report = run_arm(self.manifest, "R1", folder, adapter, [task["task_id"]])
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(report["status"], "incomplete")
        row = report["tasks"][0]
        self.assertEqual(row["status"], "actual_usage_cap_violation")
        self.assertIsNone(row["session"]["revision"])
        self.assertEqual(row["session"]["events"], [])

    def test_r2_turn_messages_and_reservations_remain_within_input_and_total_caps(self):
        task = self.tasks["013948"]

        class RecordedR2Adapter:
            is_mock = False
            identity = {"kind": "offline_message_cap_fixture", "scenario": "one_context_expansion"}

            def __init__(self):
                self.requests = []

            def __call__(self, messages, *, task, turn, arm, attempt_id):
                self.requests.append(copy.deepcopy(messages))
                if turn == 1:
                    direction = task["expansion_atom_catalog"][0]["direction"]
                    output = {"tool_calls": [{"name": "expand_context", "arguments": {
                        "direction": direction, "reason": "bounded offline expansion"}}]}
                else:
                    output = _unresolved_submit(task)
                output["schema_version"] = "repair-selection-v1"
                return {"output": output, "provider_usage": None}

        adapter = RecordedR2Adapter()
        with TemporaryDirectory() as folder:
            report = run_arm(self.manifest, "R2", folder, adapter, [task["task_id"]])
        self.assertEqual(len(adapter.requests), 2)
        self.assertTrue(all(attempt["reserved_input_tokens"] <= runtime.POLICY["input_tokens"]
                            for attempt in report["attempts"]))
        self.assertTrue(all(estimate_input(bound_messages(messages, attempt["attempt_id"])) <= attempt["reserved_input_tokens"]
                            for messages, attempt in zip(adapter.requests, report["attempts"])))
        self.assertLessEqual(sum(attempt["charged_tokens"] for attempt in report["attempts"]),
                             runtime.POLICY["total_tokens"])
        initial = json.loads(adapter.requests[0][1]["content"])
        second = json.loads(adapter.requests[1][1]["content"])
        initial_by_id = {row["atom_id"]: row for row in initial["supplied_atom_catalog"]}
        second_by_id = {row["atom_id"]: row for row in second["supplied_atom_catalog"]}
        self.assertTrue(set(initial_by_id) <= set(second_by_id))
        for atom_id, original in initial_by_id.items():
            self.assertEqual(second_by_id[atom_id], original)
        self.assertTrue(set(second_by_id) - set(initial_by_id))
        serialized_receipts = json.dumps(second.get("tool_results", []), ensure_ascii=False)
        self.assertNotIn("quote", serialized_receipts)
        self.assertNotIn("start_char", serialized_receipts)
        self.assertEqual(report["status"], "complete")
        self.assertIsNone(report["semantic_metrics"])
        self.assertEqual(report["semantic_status"], "semantic_review_pending")

    def test_terminal_cache_replay_does_not_dispatch_again_and_identity_changes_cache_key(self):
        task = self.tasks["013948"]
        script = self._script(task, _unresolved_submit(task))
        adapter = MockAdapter(script)
        with TemporaryDirectory() as folder:
            first = run_arm(self.manifest, "R1", folder, adapter, [task["task_id"]])
            replay_adapter = MockAdapter(script)
            replay = run_arm(self.manifest, "R1", folder, replay_adapter, [task["task_id"]])
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(replay_adapter.calls, 0)
        self.assertEqual(first["run_key"], replay["run_key"])

        identity = {"kind": "fixture", "endpoint": "a"}
        baseline = runtime.fingerprint(task, "R1", identity)
        with patch.object(runtime, "MODEL", runtime.MODEL + "-identity-probe"):
            model_changed = runtime.fingerprint(task, "R1", identity)
        endpoint_changed = runtime.fingerprint(task, "R1", {"kind": "fixture", "endpoint": "b"})
        original_read_text = Path.read_text

        def altered_implementation(path, *args, **kwargs):
            content = original_read_text(path, *args, **kwargs)
            return content + "\n# synthetic implementation identity probe" if path.name == "runtime.py" else content

        with patch.object(Path, "read_text", new=altered_implementation):
            code_changed = runtime.fingerprint(task, "R1", identity)
        self.assertNotEqual(baseline, model_changed)
        self.assertNotEqual(baseline, endpoint_changed)
        self.assertNotEqual(baseline, code_changed)

    def test_locked_caps_and_preflight_account_for_both_r2_turns(self):
        self.assertEqual({key: runtime.POLICY[key] for key in (
            "input_tokens", "output_tokens", "total_tokens", "source_model_attempts",
            "concurrency", "tool_calls", "model_turns", "expansions", "expansion_chars",
        )}, {"input_tokens": 6000, "output_tokens": 1200, "total_tokens": 20000,
             "source_model_attempts": 8, "concurrency": 1, "tool_calls": 8,
             "model_turns": 2, "expansions": 1, "expansion_chars": 1200})
        report = runtime.preflight(self.manifest, "R2", [self.tasks["013948"]["task_id"]])
        row = report["tasks"][0]
        self.assertEqual(self.tasks["013948"]["selection"], "repair")
        self.assertEqual(report["selected_task_ids"], [self.tasks["013948"]["task_id"]])
        self.assertEqual(report["max_attempts_required"], 2)
        self.assertEqual(report["status"], "pass")
        self.assertIn("second_turn_input_bound", row)
        self.assertGreaterEqual(row["second_turn_input_bound"], row["estimated_input_tokens"])
        self.assertEqual(report["worst_case_reserved_tokens"],
                         report["initial_reserved_tokens"] + row["second_turn_input_bound"] + runtime.POLICY["output_tokens"])
        if max(row["estimated_input_tokens"], row["second_turn_input_bound"]) > runtime.POLICY["input_tokens"]:
            self.assertEqual(report["status"], "budget_risk")
        if report["worst_case_reserved_tokens"] > runtime.POLICY["total_tokens"]:
            self.assertEqual(report["status"], "budget_risk")

        two_target = runtime.preflight(self.manifest, "R2", [
            self.tasks["013948"]["task_id"], self.tasks["011904"]["task_id"]])
        if two_target["worst_case_reserved_tokens"] > runtime.POLICY["total_tokens"]:
            self.assertEqual(two_target["status"], "budget_risk")
        self.assertEqual(set(two_target["selected_task_ids"]), {
            self.tasks["013948"]["task_id"], self.tasks["011904"]["task_id"]})
        self.assertEqual(two_target["max_attempts_required"], 4)

        all_tasks = runtime.preflight(self.manifest, "R2")
        self.assertEqual(set(all_tasks["selected_task_ids"]), {task["task_id"] for task in self.manifest["tasks"]})
        self.assertEqual(all_tasks["max_attempts_required"], 2 * sum(bool(task["original_proposals"]) for task in self.manifest["tasks"]))
        self.assertEqual(all_tasks["policy"], runtime.POLICY)


if __name__ == "__main__":
    unittest.main()
