"""Regression replay for the v15 M6 payload-cap failure; no provider calls."""

import json
from pathlib import Path
from unittest.mock import patch
import unittest

from jsonschema import ValidationError

from pipeline_v2.agent_harness.contracts import Budget, RunIdentity
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.agent_harness.adaptive_policy import ToolSemanticError, catalog, translate
from pipeline_v2.m6 import AdaptiveConfig, AdaptiveHarness, M6_INSTRUCTIONS


ROOT = Path(__file__).resolve().parents[2]
V15_RUN = ROOT / "pipeline_v2/reviews/m6_discovery_pilot/runs_v15/017984.txt"
TOKENIZER = ROOT / "cache/tokenizers/qwen36_27b_fp8"
PAYLOAD_CAP = 7400


def _ledger_events(path):
    import sqlite3

    connection = sqlite3.connect(path)
    try:
        return [dict(json.loads(record), seq=seq) for seq, record in connection.execute(
            "SELECT seq, record FROM events ORDER BY seq"
        )]
    finally:
        connection.close()


def _contains_keyword(value, keyword="pattern"):
    if isinstance(value, dict):
        return keyword in value or any(_contains_keyword(item, keyword) for item in value.values())
    if isinstance(value, list):
        return any(_contains_keyword(item, keyword) for item in value)
    return False


class V15PayloadRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not V15_RUN.joinpath("events.sqlite3").is_file():
            raise unittest.SkipTest("saved v15 ledger is not present in this checkout")
        if not TOKENIZER.joinpath("tokenizer.json").is_file():
            raise unittest.SkipTest("pinned local tokenizer assets are unavailable")
        cls.events = _ledger_events(V15_RUN / "events.sqlite3")
        cls.prefix = [event for event in cls.events if event["seq"] <= 17]
        cls.run_created = next(event for event in cls.prefix if event["kind"] == "run_created")
        cls.identity = RunIdentity(**cls.run_created["config"]["identity"])
        cls.budget = Budget(**cls.run_created["config"]["budget"])
        cls.state = RunState(cls.prefix)
        cls.transport = ModalQwenTransport(TOKENIZER, instructions=M6_INSTRUCTIONS)
        if not hasattr(cls, "events"):
            return
        cls._source_need = next(
            event["result"]["observation"]["m6_source_need"]
            for event in reversed(cls.prefix)
            if event["kind"] == "action_result"
            and event.get("result")
            and event["result"].get("observation", {}).get("m6_source_need")
        )
        harness = AdaptiveHarness.__new__(AdaptiveHarness)
        harness.identity = cls.identity
        harness.budget = cls.budget
        harness.count_tokens = cls.transport.count_tokens
        harness.transport = cls.transport
        harness.adaptive_config = AdaptiveConfig(**cls.run_created["config"]["m6"]["config"])
        harness.query_paragraphs = (cls._source_need["a_paragraph"],)
        harness.hybrid_search = type("HybridBudget", (), {"remaining": lambda self: {"requests": 1}})()
        harness.events = lambda: cls.prefix
        cls.harness = harness

    def test_v15_after_second_open_fits_raw_a_b_and_assessment_tool(self):
        prepared = self.harness._fit_payload(self.state, PAYLOAD_CAP)
        self.assertIsNotNone(prepared, "the v15-shaped next payload must fit the saved 7400-token cap")
        body = json.loads(prepared[0])
        excerpts_by_case = {row["case_id"] for row in body["excerpts"]}
        self.assertEqual(excerpts_by_case, {self.identity.query_id, "073752.txt"})
        self.assertLessEqual(prepared[1], PAYLOAD_CAP)
        tools, schema, _, pairs = catalog(body)
        names = {tool["name"] for tool in tools}
        self.assertIn("assess_case_link", names)
        self.assertTrue(pairs, "the current raw A/B excerpts must expose an assessable pair")
        self.assertFalse(_contains_keyword(schema), "decoder schema must not contain regex patterns")
        self.assertFalse(any(_contains_keyword(tool["parameters"]) for tool in tools))

    def test_assessment_decoder_schema_leaves_duplicate_refs_to_host(self):
        body = json.loads(self.harness._fit_payload(self.state, PAYLOAD_CAP)[0])
        tools, schema, _, pairs = catalog(body)
        assessment = next(tool for tool in tools if tool["name"] == "assess_case_link")
        self.assertFalse(_contains_keyword(schema, "uniqueItems"))
        self.assertFalse(_contains_keyword(assessment["parameters"], "uniqueItems"))
        pair_ref, pair = next(iter(pairs.items()))
        ref = pair["b_passage_refs"][0]
        action = {"action": "assess_case_link", "args": {
            "pair_ref": pair_ref, "case_relation": "unknown", "passage_location": "unresolved",
            "reason": "The supplied excerpts do not establish reliance.",
            "identity_support_refs": [ref],
        }}
        self.assertEqual(translate(body, action)["action"], "assess_links")
        action["args"]["identity_support_refs"].append(ref)
        with self.assertRaisesRegex(ToolSemanticError, "duplicate_evidence_refs"):
            translate(body, action)

    def test_one_character_focus_is_rejected_and_text_schemas_have_no_patterns(self):
        # Use an actual post-v15 payload so the candidate handle is host-issued.
        body = json.loads(self.harness._fit_payload(self.state, PAYLOAD_CAP)[0])
        tools, _, _, _ = catalog(body)
        read_tool = next(tool for tool in tools if tool["name"] == "read_case_passages")
        candidate_ref = read_tool["parameters"]["properties"]["candidate_ref"]["enum"][0]
        with self.assertRaises(ValidationError):
            translate(body, {"action": "read_case_passages", "args": {
                "candidate_ref": candidate_ref, "focus": "D",
            }})
        self.assertFalse(any(_contains_keyword(tool["parameters"]) for tool in tools))

    def test_v20_zero_new_raw_retires_read_route_but_keeps_continuation(self):
        path = V15_RUN.parents[1] / "runs_v20/017984.txt/events.sqlite3"
        if not path.is_file():
            self.skipTest("saved v20 ledger is not present")
        events = [event for event in _ledger_events(path) if event["seq"] <= 21]
        state = RunState(events)
        body = json.loads(next(event["payload"] for event in events if event["seq"] == 18))
        with patch.object(self.harness, "events", return_value=events):
            body["m6"] = self.harness._registry(state, body)
        tools = {tool["name"]: tool for tool in catalog(body)[0]}
        offered = tools["read_case_passages"]["parameters"]["properties"]["candidate_ref"]["enum"]
        self.assertEqual({body["m6"]["candidates"][ref]["case_id"] for ref in offered},
                         {"049344.txt", "082632.txt"})
        self.assertTrue(any(row["description"]["case_id"] == "073752.txt" and row["binding"].get("cursor")
                            for row in body["m6"]["expansions"].values()))

    def test_v21_offers_assessment_after_second_open_and_fits_after_empty_read(self):
        path = V15_RUN.parents[1] / "runs_v21/017984.txt/events.sqlite3"
        if not path.is_file():
            self.skipTest("saved v21 ledger is not present")
        ledger = _ledger_events(path)
        for cutoff in (25, 29):
            with self.subTest(cutoff=cutoff):
                events = [event for event in ledger if event["seq"] <= cutoff]
                with patch.object(self.harness, "events", return_value=events):
                    fitted = self.harness._fit_payload(RunState(events), PAYLOAD_CAP)
                self.assertIsNotNone(fitted)
                body = json.loads(fitted[0])
                tools = {tool["name"]: tool for tool in catalog(body)[0]}
                readable = tools["read_case_passages"]["parameters"]["properties"]["candidate_ref"]["enum"]
                self.assertIn("082632.txt", {body["m6"]["candidates"][ref]["case_id"] for ref in readable})
                self.assertNotIn("049344.txt", {body["m6"]["candidates"][ref]["case_id"] for ref in readable})
                if cutoff == 25:
                    self.assertIn("assess_case_link", tools)


if __name__ == "__main__":
    unittest.main()
