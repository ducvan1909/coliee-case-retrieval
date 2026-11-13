"""Independent behavioral tests for the local M4 harness."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from pipeline_v2.agent_harness import (
    AgentHarness, Budget, HarnessError, ModelReply, RunIdentity, SourceExcerpt, ToolResult,
    TransportError,
)
from pipeline_v2.agent_harness.schema import (
    RESPONSE_SCHEMA_VERSION, ResponseSchemaError, response_schema, validate_model_response,
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def excerpt(case_id, raw, span=(0, None), *, source_hash=None):
    start, end = span
    end = len(raw) if end is None else end
    text = raw[start:end].decode("utf-8")
    return SourceExcerpt(case_id, source_hash or digest(raw), (start, end), text,
                         digest(text.encode("utf-8")), {"fixture": case_id})


def identity():
    return RunIdentity(
        run_id="fixture-run", query_id="A.txt", query_source_hash="a" * 64,
        candidate_fingerprint="candidates-v1", index_fingerprint="index-v1",
        profile_fingerprint="profile-v1", model_fingerprint="model-v1",
        prompt_fingerprint="prompt-v1", tools_fingerprint="tools-v1",
        tokenizer_fingerprint="tokenizer-v1",
    )


def budget(**overrides):
    values = dict(max_requests=12, max_actions=12, max_input_tokens=100_000,
                  max_payload_tokens=100_000, max_output_tokens=2_000,
                  max_total_tokens=None, max_retries=0)
    values.update(overrides)
    return Budget(**values)


class Replay:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.payloads = []
        self.request_ids = []

    def __call__(self, payload, request_id):
        self.payloads.append(json.loads(payload))
        self.request_ids.append(request_id)
        value = next(self.actions)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value(self.payloads[-1])
        return ModelReply(value, input_tokens=1, output_tokens=1, latency_ms=1.0)


class StructuredReplay:
    def __init__(self, raw_reply):
        self.raw_reply = raw_reply
        self.schemas = []
        self.payloads = []
        self.request_ids = []

    def send_structured(self, payload, request_id, schema):
        self.payloads.append(json.loads(payload))
        self.request_ids.append(request_id)
        self.schemas.append(schema)
        return ModelReply(self.raw_reply, input_tokens=17, output_tokens=9, latency_ms=12.5)


class M4HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = Path(self.temp.name) / "run"
        self.a_raw = "A context, naïve but current.".encode("utf-8")
        self.b_raw = "B passage supports the issue.".encode("utf-8")
        self.a = excerpt("A.txt", self.a_raw, source_hash="a" * 64)
        self.b = excerpt("B.txt", self.b_raw)

    @staticmethod
    def assess_action(a_ref, b_ref, *, need="need-1", candidate="B.txt"):
        return {"action": "assess_links", "args": {"assessments": [{
            "source_need_id": need, "candidate_id": candidate,
            "a_context_refs": [a_ref], "b_passage_refs": [b_ref],
            "case_relation": "supported", "passage_location": "pinpoint",
            "reason": "The current excerpts identify the same proposition.",
        }]}}

    def make_harness(self, replay, *, tools=None, initial=None, verify_source=None,
                     run_dir=None, budget_value=None, response_contract=None, identity_value=None):
        return AgentHarness(
            run_dir or self.run_dir, identity=identity_value or identity(), budget=budget_value or budget(),
            baseline=["baseline.txt"], tools=tools or {},
            count_tokens=lambda payload: len(payload), transport=replay,
            initial_observation=initial, verify_source=verify_source,
            response_contract=response_contract,
        )

    def test_tool_result_is_delivered_on_next_turn_before_raw_evidence_can_be_assessed(self):
        a_ref, b_ref = self.a.ref, self.b.ref
        replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:parent"]}},
            {"action": "reload_source", "args": {"refs": [a_ref, b_ref]}},
            lambda payload: self.assess_action(a_ref, b_ref),
            {"action": "reload_source", "args": {"refs": [a_ref, b_ref]}},
            lambda payload: {
                "action": "stop", "args": {"reason": "complete", "prediction": ["B.txt"],
                    "assessment_ids": [payload["assessments"][0]["assessment_id"]]},
            },
        ])
        opened = []

        def open_source(args):
            opened.append(args)
            return ToolResult({"status": "opened"}, excerpts=(self.b,), candidates=("B.txt",))

        harness = self.make_harness(
            replay, tools={"open_source": open_source},
            initial=ToolResult({"query_map": "A preview"}, excerpts=(self.a,)),
        )
        result = harness.run()

        self.assertEqual(result["stop_reason"], "complete", result)
        self.assertEqual(result["prediction"], ["B.txt"])
        self.assertEqual(len(opened), 1)
        self.assertEqual(replay.payloads[0]["current_payload_source_refs"], [a_ref])
        self.assertNotIn(b_ref, replay.payloads[0]["current_payload_source_refs"])
        self.assertEqual(replay.payloads[1]["current_payload_source_refs"], [b_ref])
        self.assertEqual(set(replay.payloads[2]["current_payload_source_refs"]), {a_ref, b_ref})
        events = harness.events()
        kinds = [event["kind"] for event in events]
        first_result = kinds.index("action_result")
        next_admission = kinds.index("request_admitted", kinds.index("request_result") + 1)
        self.assertLess(first_result, next_admission)
        self.assertEqual(result["usage"]["requests"], 5)
        self.assertEqual(result["usage"]["actions"], 5)

    def test_search_preview_and_pending_source_request_are_not_citable_evidence(self):
        replay = Replay([
            {"action": "search_corpus", "args": {"intent": "issue", "channel": "bm25",
                "text": "procedural fairness", "limit": 5}},
            self.assess_action(self.a.ref, self.b.ref),
        ])

        def search(_args):
            return ToolResult(
                {"preview": "B preview only"}, candidates=("B.txt",),
                source_requests=({"case_id": "B.txt", "source_hash": self.b.source_hash,
                                 "pending_refs": ["pending-B"]},),
            )

        harness = self.make_harness(
            replay, tools={"search_corpus": search},
            initial=ToolResult({"query_preview": "A map only"}, excerpts=(self.a,)),
        )
        result = harness.run()

        self.assertEqual(result["stop_reason"], "failure")
        self.assertTrue(result["fallback"])
        self.assertEqual(result["prediction"], ["baseline.txt"])
        self.assertEqual(result["active_assessment_ids"], [])
        self.assertEqual(result["stop_detail"], "assessment_state:ref_not_in_current_payload")
        self.assertNotIn(self.b.ref, result["source_catalog"])
        self.assertEqual(result["source_requests"][0]["pending_refs"], ["pending-B"])

    def test_revising_query_context_invalidates_dependent_assessment(self):
        a2_raw = b"A second context span."
        a2_start = len(self.a_raw)
        a2 = SourceExcerpt("A.txt", "a" * 64, (a2_start, a2_start + len(a2_raw)),
                           a2_raw.decode("utf-8"), digest(a2_raw), {"fixture": "A.txt"})
        replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:parent"]}},
            {"action": "reload_source", "args": {"refs": [self.a.ref, self.b.ref]}},
            lambda payload: self.assess_action(self.a.ref, self.b.ref),
            {"action": "open_query", "args": {"handle": "A:more"}},
            {"action": "reload_source", "args": {"refs": [a2.ref, self.b.ref]}},
            lambda payload: self.assess_action(a2.ref, self.b.ref),
            {"action": "reload_source", "args": {"refs": [a2.ref, self.b.ref]}},
            lambda payload: {
                "action": "stop", "args": {"reason": "complete", "prediction": ["B.txt"],
                    "assessment_ids": [payload["assessments"][0]["assessment_id"]]},
            },
        ])

        def open_source(_args):
            return ToolResult({"status": "opened"}, excerpts=(self.b,), candidates=("B.txt",))

        def open_query(_args):
            return ToolResult({"status": "expanded"}, excerpts=(a2,))

        harness = self.make_harness(
            replay, tools={"open_source": open_source, "open_query": open_query},
            initial=ToolResult({"query_map": "A preview"}, excerpts=(self.a,)),
        )
        result = harness.run()

        self.assertEqual(result["stop_reason"], "complete")
        assessments = result["assessments"]
        self.assertEqual(len(assessments), 2)
        self.assertIsNotNone(assessments[0]["invalidated_at"])
        self.assertEqual(assessments[0]["invalidation_reason"], "assessment_revision")
        self.assertIsNone(assessments[1].get("invalidated_at"))
        self.assertEqual(len(result["active_assessment_ids"]), 1)
        self.assertEqual(result["prediction"], ["B.txt"])

    def test_unknown_transport_receipt_is_not_resent_and_resume_keeps_budget(self):
        replay = Replay([TransportError("receipt uncertain", unknown=True)])
        harness = self.make_harness(replay)
        first = harness.run()
        second = harness.run()

        self.assertEqual(first["stop_reason"], "failure")
        self.assertEqual(first["usage"]["unknown_receipts"], 1)
        self.assertEqual(first["usage"]["requests"], 1)
        self.assertEqual(second["usage"]["requests"], 1)
        self.assertEqual(second["prediction"], ["baseline.txt"])
        self.assertEqual(len(replay.request_ids), 1)
        self.assertEqual(len(harness.events()), len({event["seq"] for event in harness.events()}))

    def test_source_drift_invalidates_assessment_and_falls_back(self):
        replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:parent"]}},
            {"action": "reload_source", "args": {"refs": [self.a.ref, self.b.ref]}},
            lambda payload: self.assess_action(self.a.ref, self.b.ref),
            {"action": "reload_source", "args": {"refs": [self.a.ref, self.b.ref]}},
        ])

        b_verifications = 0

        def verify(case_id, _source_hash):
            nonlocal b_verifications
            if case_id == "B.txt":
                b_verifications += 1
                if b_verifications > 3:
                    raise RuntimeError("fixture source changed")
            return True

        harness = self.make_harness(
            replay, tools={"open_source": lambda _args: ToolResult({"status": "opened"},
                excerpts=(self.b,), candidates=("B.txt",))},
            initial=ToolResult({"query_map": "A"}, excerpts=(self.a,)),
            verify_source=verify,
        )
        result = harness.run()

        self.assertEqual(result["stop_reason"], "failure")
        self.assertEqual(result["stop_detail"], "source_drift")
        self.assertEqual(result["prediction"], ["baseline.txt"])
        self.assertTrue(any(event["kind"] == "source_drift" for event in harness.events()))
        self.assertEqual(result["active_assessment_ids"], [])
        self.assertTrue(result["assessments"])
        self.assertIsNotNone(result["assessments"][0]["invalidated_at"])
        self.assertEqual(result["assessments"][0]["invalidation_reason"], "source_drift")

    def test_budget_stop_uses_fallback_and_unknown_model_reply_is_accounted(self):
        replay = Replay([{"action": "stop", "args": {"reason": "budget"}}])
        harness = self.make_harness(replay)
        result = harness.run()

        self.assertEqual(result["stop_reason"], "budget")
        self.assertEqual(result["prediction"], ["baseline.txt"])
        self.assertTrue(result["fallback"])
        self.assertEqual(result["usage"]["requests"], 1)
        self.assertEqual(result["usage"]["reported_input_tokens"], 1)
        self.assertEqual(result["usage"]["reported_output_tokens"], 1)

    def test_oversized_whole_query_falls_back_to_navigation_excerpt_without_claiming_full_read(self):
        raw = ("A long query source with legal context. " * 80).encode("utf-8")
        query_hash = digest(raw)
        query_identity = replace(identity(), query_source_hash=query_hash)
        navigation = excerpt("A.txt", raw, span=(0, 24), source_hash=query_hash)
        full = SourceExcerpt("A.txt", query_hash, (0, len(raw)), raw.decode("utf-8"),
                             query_hash, {"fixture": "whole query"})
        replay = Replay([{"action": "stop", "args": {"reason": "budget"}}])
        harness = AgentHarness(
            self.run_dir, identity=query_identity, budget=budget(max_payload_tokens=1_000,
                max_input_tokens=1_000), baseline=["baseline.txt"], tools={},
            count_tokens=lambda payload: len(payload), transport=replay,
            initial_observation=ToolResult({"navigation": "query map"}, excerpts=(navigation,)),
            query_excerpt=full,
        )
        harness.run()

        payload = replay.payloads[0]
        self.assertEqual(payload["query_delivery"], "navigation")
        self.assertEqual(payload["current_payload_source_refs"], [navigation.ref])
        self.assertNotEqual(payload["excerpts"][0]["ref"], full.ref)

    def test_new_tool_excerpt_is_delivered_before_older_pending_excerpt(self):
        a2_raw = b"Older pending context."
        a2_start = len(self.a_raw)
        a2 = SourceExcerpt("A.txt", "a" * 64, (a2_start, a2_start + len(a2_raw)),
                           a2_raw.decode("utf-8"), digest(a2_raw), {"fixture": "older A"})
        replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:new"]}},
            {"action": "stop", "args": {"reason": "budget"}},
        ])

        def count_tokens(payload):
            body = json.loads(payload)
            return 100 + sum(len(row["text"].encode("utf-8")) for row in body["excerpts"]) \
                + 20 * len(body["excerpts"])

        harness = AgentHarness(
            self.run_dir, identity=identity(), budget=budget(max_payload_tokens=160,
                max_input_tokens=2_000), baseline=["baseline.txt"],
            tools={"open_source": lambda _args: ToolResult({"status": "opened"},
                excerpts=(self.b,), candidates=("B.txt",))}, count_tokens=count_tokens,
            transport=replay,
            initial_observation=ToolResult({"query_map": "A"}, excerpts=(self.a, a2)),
        )
        harness.run()

        self.assertIn(self.b.ref, replay.payloads[1]["current_payload_source_refs"])
        self.assertNotIn(a2.ref, replay.payloads[1]["current_payload_source_refs"])

    def test_response_schema_branches_unknown_speaker_without_type(self):
        valid = {"action": "assess_links", "args": {"assessments": [{
            "source_need_id": "need-1", "candidate_id": "B.txt",
            "a_context_refs": [self.a.ref], "b_passage_refs": [self.b.ref],
            "case_relation": "unknown", "passage_location": "pinpoint",
            "reason": "Passage located; link evidence remains unresolved.",
            "speaker": {"role": "unknown"},
        }]}}
        self.assertEqual(validate_model_response(valid), valid)

        forbidden = json.loads(json.dumps(valid))
        forbidden["args"]["assessments"][0]["speaker"]["type"] = "quotation"
        with self.assertRaises(ResponseSchemaError):
            validate_model_response(forbidden)

    def test_unknown_relation_and_pinpoint_are_independent_and_stay_nonpositive(self):
        action = {"action": "assess_links", "args": {"assessments": [{
            "source_need_id": "need-1", "candidate_id": "B.txt",
            "a_context_refs": [self.a.ref], "b_passage_refs": [self.b.ref],
            "case_relation": "unknown", "passage_location": "pinpoint",
            "reason": "A specific passage is located, but A to B is unestablished.",
            "speaker": {"role": "unknown"},
        }]}}
        replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:parent"]}},
            {"action": "reload_source", "args": {"refs": [self.a.ref, self.b.ref]}},
            action,
            {"action": "stop", "args": {"reason": "complete", "prediction": [],
                "assessment_ids": []}},
        ])
        harness = self.make_harness(replay,
            tools={"open_source": lambda _args: ToolResult({"opened": True},
                excerpts=(self.b,), candidates=("B.txt",))},
            initial=ToolResult({"source_need": "need-1"}, excerpts=(self.a,)),
            response_contract=RESPONSE_SCHEMA_VERSION)
        result = harness.run()

        self.assertEqual(result["stop_reason"], "complete")
        self.assertEqual(result["prediction"], [])
        self.assertEqual(result["assessments"][0]["case_relation"], "unknown")
        self.assertEqual(result["assessments"][0]["passage_location"], "pinpoint")
        self.assertEqual(result["assessments"][0]["speaker"], {"role": "unknown"})
        self.assertEqual(result["usage"]["requests"], 4)
        self.assertEqual(result["candidate_states"]["B.txt"]["case_relation"], "unknown")
        self.assertNotIn("B.txt", result["prediction"])

    def test_unknown_speaker_with_forbidden_type_is_rejected_without_repair(self):
        action = self.assess_action(self.a.ref, self.b.ref)
        action["args"]["assessments"][0]["speaker"] = {
            "role": "unknown", "type": "quotation",
        }
        replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:parent"]}},
            {"action": "reload_source", "args": {"refs": [self.a.ref, self.b.ref]}},
            action,
        ])
        harness = self.make_harness(replay,
            tools={"open_source": lambda _args: ToolResult({"opened": True},
                excerpts=(self.b,), candidates=("B.txt",))},
            initial=ToolResult({"source_need": "need-1"}, excerpts=(self.a,)),
            response_contract=RESPONSE_SCHEMA_VERSION)
        result = harness.run()

        self.assertEqual(result["stop_reason"], "failure")
        self.assertEqual(result["prediction"], ["baseline.txt"])
        self.assertEqual(result["assessments"], [])
        self.assertEqual(result["usage"]["requests"], 3)
        self.assertEqual(result["usage"]["actions"], 2)
        self.assertEqual(result["assessment_validation"]["schema_rejected_responses"], 1)
        self.assertEqual(result["assessment_validation"]["rejected_actions"], 0)
        rejected = [event for event in harness.events() if event["kind"] == "request_result"][-1]
        self.assertEqual(rejected["status"], "malformed")
        self.assertTrue(str(rejected["error"]).startswith("response_schema:"))
        self.assertEqual(result["assessment_validation"]["schema_rejected_responses"], 1)

    def test_empty_evidence_is_pending_not_invalid_schema(self):
        pending_action = {"action": "assess_links", "args": {"assessments": [{
            "source_need_id": "need-1", "candidate_id": "B.txt",
            "a_context_refs": [], "b_passage_refs": [],
            "case_relation": "unknown", "passage_location": "unresolved",
            "reason": "Search found B but no raw evidence has been opened.",
            "speaker": {"role": "unknown"},
        }]}}
        replay = Replay([
            pending_action,
            {"action": "stop", "args": {"reason": "budget"}},
        ])
        harness = self.make_harness(replay, initial=ToolResult(
            {"query_map": "A"}, candidates=("B.txt",)),
            response_contract=RESPONSE_SCHEMA_VERSION)
        result = harness.run()

        self.assertEqual(result["stop_reason"], "budget")
        self.assertTrue(result["fallback"])
        self.assertEqual(result["prediction"], ["baseline.txt"])
        self.assertEqual(result["pending_assessments"][0]["status"], "pending_evidence")
        self.assertEqual(result["pending_assessments"][0]["case_relation"], "unknown")
        self.assertEqual(result["pending_assessments"][0]["missing_evidence"],
                         ["a_context_refs", "b_passage_refs"])
        self.assertEqual(result["candidate_states"]["B.txt"]["status"], "pending_evidence")
        self.assertEqual(result["assessment_validation"]["pending_evidence"], 1)
        self.assertEqual(result["assessment_validation"]["rejected_actions"], 0)

    def test_nonempty_crosswired_current_refs_fallback_with_provenance_error(self):
        invalid_action = self.assess_action(self.b.ref, self.a.ref)
        invalid_replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:parent"]}},
            {"action": "reload_source", "args": {"refs": [self.a.ref, self.b.ref]}},
            invalid_action,
        ])
        invalid_harness = self.make_harness(invalid_replay, run_dir=self.run_dir.parent / "invalid",
            tools={"open_source": lambda _args: ToolResult({"opened": True},
                excerpts=(self.b,), candidates=("B.txt",))},
            initial=ToolResult({"query_map": "A"}, excerpts=(self.a,)),
            response_contract=RESPONSE_SCHEMA_VERSION)
        invalid = invalid_harness.run()
        self.assertEqual(invalid["stop_reason"], "failure")
        self.assertEqual(invalid["prediction"], ["baseline.txt"])
        self.assertEqual(invalid["pending_assessments"], [])
        self.assertEqual(invalid["usage"]["requests"], 3)
        self.assertEqual(invalid["assessment_validation"]["pending_evidence"], 0)
        self.assertEqual(invalid["assessment_validation"]["rejected_actions"], 1)
        rejected = [event for event in invalid_harness.events() if event["kind"] == "action_result"][-1]
        self.assertEqual(rejected["status"], "error")
        self.assertEqual(rejected["reason"],
                         "assessment_state:a_context_refs_belongs_to_another_case")

    def test_retrieval_only_candidate_stays_unknown_without_assessment(self):
        replay = Replay([
            {"action": "search_corpus", "args": {"intent": "issue", "channel": "bm25",
                "text": "notice", "limit": 5}},
            {"action": "stop", "args": {"reason": "budget"}},
        ])

        def search(_args):
            return ToolResult({"hits": [{"case_id": "B.txt", "preview": "ranked snippet"}]},
                candidates=("B.txt",), source_requests=({"case_id": "B.txt",
                    "source_hash": self.b.source_hash, "pending_refs": ["B:open"]},))

        harness = self.make_harness(replay, tools={"search_corpus": search},
                                    response_contract=RESPONSE_SCHEMA_VERSION)
        result = harness.run()
        self.assertEqual(result["stop_reason"], "budget")
        self.assertEqual(result["prediction"], ["baseline.txt"])
        self.assertEqual(result["assessments"], [])
        self.assertEqual(result["pending_assessments"], [])
        self.assertEqual(result["candidate_states"]["B.txt"]["case_relation"], "unknown")
        self.assertEqual(result["candidate_states"]["B.txt"]["status"], "retrieval_only")
        self.assertEqual(result["candidate_states"]["B.txt"]["missing_evidence"],
                         ["a_context_refs", "b_passage_refs"])
        self.assertEqual(result["assessment_validation"]["pending_evidence"], 0)
        self.assertEqual(result["source_requests"][0]["pending_refs"], ["B:open"])
        self.assertEqual(result["usage"]["requests"], 2)

    def test_correctly_shaped_assessment_with_stale_current_ref_is_not_repaired(self):
        replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:parent"]}},
            self.assess_action(self.a.ref, self.b.ref),
        ])
        harness = self.make_harness(replay,
            tools={"open_source": lambda _args: ToolResult({"opened": True},
                excerpts=(self.b,), candidates=("B.txt",))},
            initial=ToolResult({"query_map": "A"}, excerpts=(self.a,)),
            response_contract=RESPONSE_SCHEMA_VERSION)
        result = harness.run()

        self.assertEqual(result["stop_reason"], "failure")
        self.assertEqual(result["prediction"], ["baseline.txt"])
        self.assertEqual(result["usage"]["requests"], 2)
        self.assertEqual(result["usage"]["actions"], 2)
        self.assertEqual(result["current_payload_source_refs"], [self.b.ref])
        rejected = [event for event in harness.events() if event["kind"] == "action_result"][-1]
        self.assertEqual(rejected["status"], "error")
        self.assertEqual(rejected["reason"], "assessment_state:ref_not_in_current_payload")
        self.assertEqual(result["assessment_validation"]["rejected_actions"], 1)

    def test_structured_transport_receives_pinned_schema_and_duplicate_key_usage_is_kept(self):
        transport = StructuredReplay(
            '{"action":"stop","args":{"reason":"budget","reason":"failure"}}')
        harness = self.make_harness(transport, response_contract=RESPONSE_SCHEMA_VERSION)
        result = harness.run()

        self.assertEqual(transport.schemas, [response_schema({})])
        self.assertEqual(result["stop_reason"], "failure")
        self.assertEqual(result["prediction"], ["baseline.txt"])
        self.assertEqual(result["usage"]["requests"], 1)
        self.assertEqual(result["usage"]["reported_input_tokens"], 17)
        self.assertEqual(result["usage"]["reported_output_tokens"], 9)
        self.assertEqual(result["usage"]["reported_provider_latency_ms"], 12.5)
        self.assertEqual(result["assessment_validation"]["schema_rejected_responses"], 1)
        self.assertEqual(len(transport.request_ids), 1)
        receipt = next(event for event in harness.events() if event["kind"] == "request_result")
        self.assertEqual(receipt["status"], "malformed")
        self.assertEqual(receipt["error"], "response_schema:duplicate_json_key")

    def test_run_binds_response_validator_and_rejects_resume_with_changed_identity(self):
        replay = Replay([{"action": "stop", "args": {"reason": "budget"}}])
        harness = self.make_harness(replay, response_contract=RESPONSE_SCHEMA_VERSION)
        result = harness.run()

        self.assertEqual(result["config"]["response_contract"], RESPONSE_SCHEMA_VERSION)
        self.assertEqual(result["config"]["assessment_schema_version"], "m4-assessment-v2")
        self.assertTrue(result["config"]["response_schema_fingerprint"])
        self.assertTrue(result["config"]["assessment_validator_fingerprint"])
        changed = self.make_harness(Replay([]), response_contract=RESPONSE_SCHEMA_VERSION,
            identity_value=replace(identity(), prompt_fingerprint="different-prompt"))
        with self.assertRaisesRegex(HarnessError, "response binding differs"):
            changed.run()

    def _quoted_excerpt(self, *, cue_span=None):
        raw = b"Authority states: [12] the quoted proposition applies."
        marker_start = raw.index(b"[12]")
        marker_end = marker_start + len(b"[12]")
        cue_span = cue_span or (0, marker_start)
        components = [
            {"unit_id": "B:attribution", "unit_kind": "paragraph",
             "span_bytes": [0, marker_start], "paragraph_role": "current_case"},
            {"unit_id": "B:quoted", "unit_kind": "paragraph",
             "span_bytes": [marker_start, len(raw)], "paragraph_role": "quoted",
             "observed_marker": 12, "marker_span_bytes": [marker_start, marker_end],
             "attribution_unit_id": "B:attribution",
             "role_evidence_refs": [{"span_bytes": list(cue_span), "kind": "local_quote_introduction"}]},
        ]
        return SourceExcerpt("B.txt", digest(raw), (0, len(raw)), raw.decode("utf-8"),
                             digest(raw), {"components": components})

    def test_quoted_speaker_accepts_delivered_container_and_attribution_cue(self):
        quoted = self._quoted_excerpt()
        action = {"action": "assess_links", "args": {"assessments": [{
            "source_need_id": "need-quote", "candidate_id": "B.txt",
            "a_context_refs": [self.a.ref], "b_passage_refs": [quoted.ref],
            "case_relation": "unknown", "passage_location": "pinpoint",
            "reason": "B contains a pinpointed quotation; attribution route is documented.",
            "speaker": {"role": "quoted_source", "type": "quotation"},
            "speaker_evidence_refs": [quoted.ref], "container_refs": [quoted.ref],
            "quote_chain_refs": [quoted.ref],
        }]}}
        replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:quoted"]}},
            {"action": "reload_source", "args": {"refs": [self.a.ref, quoted.ref]}},
            action,
            {"action": "stop", "args": {"reason": "budget"}},
        ])
        harness = self.make_harness(replay,
            tools={"open_source": lambda _args: ToolResult({"opened": True},
                excerpts=(quoted,), candidates=("B.txt",))},
            initial=ToolResult({"query_map": "A"}, excerpts=(self.a,)),
            response_contract=RESPONSE_SCHEMA_VERSION)
        result = harness.run()

        self.assertEqual(result["stop_reason"], "budget")
        assessment = result["assessments"][0]
        self.assertEqual(assessment["speaker"], {"role": "quoted_source", "type": "quotation"})
        self.assertEqual(assessment["container_ids"], ["B:quoted"])
        self.assertEqual(assessment["quoted_markers"], [{"container_id": "B:quoted", "marker": 12}])
        self.assertEqual(assessment["case_relation"], "unknown")
        self.assertEqual(assessment["passage_location"], "pinpoint")

    def test_quoted_speaker_rejects_undelivered_attribution_cue_without_repair(self):
        quoted = self._quoted_excerpt(cue_span=(500, 520))
        action = {"action": "assess_links", "args": {"assessments": [{
            "source_need_id": "need-quote", "candidate_id": "B.txt",
            "a_context_refs": [self.a.ref], "b_passage_refs": [quoted.ref],
            "case_relation": "supported", "passage_location": "pinpoint",
            "reason": "The cue reference falls outside the delivered B excerpt.",
            "speaker": {"role": "quoted_source", "type": "quotation"},
            "speaker_evidence_refs": [quoted.ref], "container_refs": [quoted.ref],
            "quote_chain_refs": [quoted.ref],
        }]}}
        replay = Replay([
            {"action": "open_source", "args": {"handles": ["B:quoted"]}},
            {"action": "reload_source", "args": {"refs": [self.a.ref, quoted.ref]}},
            action,
        ])
        harness = self.make_harness(replay,
            tools={"open_source": lambda _args: ToolResult({"opened": True},
                excerpts=(quoted,), candidates=("B.txt",))},
            initial=ToolResult({"query_map": "A"}, excerpts=(self.a,)),
            response_contract=RESPONSE_SCHEMA_VERSION)
        result = harness.run()

        self.assertEqual(result["stop_reason"], "failure")
        self.assertEqual(result["prediction"], ["baseline.txt"])
        self.assertEqual(result["usage"]["requests"], 3)
        rejected = [event for event in harness.events() if event["kind"] == "action_result"][-1]
        self.assertEqual(rejected["status"], "error")
        self.assertEqual(rejected["reason"],
                         "assessment_state:quote_chain_ref_lacks_a_delivered_attribution_cue")


if __name__ == "__main__":
    unittest.main()
