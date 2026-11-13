"""Offline tests for the fixed M5 evidence to M4 assessment bridge."""

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from pipeline_v2.agent_harness import (
    AgentHarness, Budget, HarnessError, ModelReply, RunIdentity, SourceExcerpt, ToolResult, TransportError,
)
from pipeline_v2.m5 import FixedSchedule, run_fixed_baseline
from pipeline_v2.m5_assessment import assess_fixed_baseline


def digest(raw):
    return sha256(raw).hexdigest()


def make_excerpt(case_id, source_hash, start, text):
    raw = text.encode("utf-8")
    return SourceExcerpt(case_id, source_hash, (start, start + len(raw)), text, digest(raw),
                         {"fixture": case_id, "offset": start})


class FixedFixtureTools:
    """Generate a genuine fixed-baseline result using deterministic offline tools."""

    query_id = "A.txt"
    query_hash = "a" * 64
    candidate_id = "B.txt"
    candidate_hash = "b" * 64

    def __init__(self, *, need_count=1, open_candidate=True, candidate_count=1):
        self.query_case = self.query_id
        self.fingerprint = "fixed-fixture-tools-v1"
        self.calls = []
        self.rows = []
        self.a_excerpts = {}
        for index in range(need_count):
            text = f"A source need {index + 1}."
            start = index * 100
            raw = text.encode("utf-8")
            handle = f"need-{index + 1}"
            excerpt_value = make_excerpt(self.query_id, self.query_hash, start, text)
            self.a_excerpts[tuple([start, start + len(raw)])] = excerpt_value
            self.rows.append({
                "handle": handle,
                "span_bytes": [start, start + len(raw)],
                "unit_kind": "paragraph",
                "anchor_refs": [f"anchor-{index + 1}"],
                "previews": [{
                    "preview_id": f"preview-{index + 1}", "text": text,
                    "text_sha256": digest(raw), "span_bytes": [start, start + len(raw)],
                    "anchor_refs": [f"anchor-{index + 1}"],
                }],
            })
        self.open_candidate = open_candidate
        self.candidate_count = candidate_count
        self.b_excerpt = make_excerpt(self.candidate_id, self.candidate_hash, 10,
                                      "B passage discussing the legal issue.")

    def actions(self):
        return {"open_query": self.open_query, "search_corpus": self.search_corpus,
                "search_case": self.search_case, "open_source": self.open_source}

    def open_query(self, args):
        self.calls.append(("open_query", dict(args)))
        if "offset" in args:
            return ToolResult({"case_id": self.query_id, "source_hash": self.query_hash,
                               "total": len(self.rows), "offset": 0, "next_offset": None,
                               "items": [{key: value for key, value in row.items()}
                                         for row in self.rows]})
        span = tuple(args["hit_spans"][0])
        return ToolResult({"case_id": self.query_id, "source_hash": self.query_hash},
                          excerpts=(self.a_excerpts[span],))

    def search_corpus(self, args):
        self.calls.append(("search_corpus", dict(args)))
        hits = []
        for index in range(self.candidate_count):
            candidate = f"{self.candidate_id[:-4]}{index + 1}.txt" if self.candidate_count > 1 else self.candidate_id
            candidate_hash = ("b" if index == 0 else "c") * 64
            hits.append({"case_id": candidate, "source_hash": candidate_hash,
                         "score": 1.0 - index / 10,
                         "open_ref": {"case_id": candidate, "source_hash": candidate_hash,
                                      "passage_ids": [f"p-{candidate}"]}})
        return ToolResult({"hits": hits})

    def search_case(self, args):
        self.calls.append(("search_case", dict(args)))
        return ToolResult({"hits": []})

    def open_source(self, args):
        self.calls.append(("open_source", dict(args)))
        if not self.open_candidate:
            return ToolResult({"case_id": args["case_id"], "source_hash": args["source_hash"]})
        candidate_id = args["case_id"]
        source_hash = args["source_hash"]
        if candidate_id == self.candidate_id:
            excerpt_value = self.b_excerpt
        else:
            excerpt_value = make_excerpt(candidate_id, source_hash, 10,
                                          f"{candidate_id} passage discussing the legal issue.")
        return ToolResult({"case_id": candidate_id, "source_hash": source_hash}, excerpts=(excerpt_value,))

    def frozen_result(self, **schedule):
        return run_fixed_baseline(self, schedule=FixedSchedule(
            max_map_pages=1, max_anchor_needs=2, max_unmarked_needs=0,
            hits_per_channel=max(1, self.candidate_count), max_candidate_opens=self.candidate_count,
            **schedule,
        ))


class StructuredReplay:
    def __init__(self, actions):
        self.actions = list(actions)
        self.payloads = []
        self.schemas = []
        self.request_ids = []

    def count_tokens(self, payload):
        return len(payload)

    def send_structured(self, payload, request_id, schema):
        self.payloads.append(json.loads(payload))
        self.request_ids.append(request_id)
        self.schemas.append(schema)
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return ModelReply(action, input_tokens=17, output_tokens=6, latency_ms=3.0)


def valid_reply(**args):
    return {"action": "assess_case_link", "args": {
        "case_relation": "similarity_only", "passage_location": "pinpoint",
        "reason": "The opened passages show topic similarity but no citation or reliance.", **args,
    }}


def make_budget(**overrides):
    values = dict(max_requests=5, max_actions=5, max_input_tokens=20000,
                  max_payload_tokens=4096, max_output_tokens=256,
                  max_total_tokens=21280, max_retries=0)
    values.update(overrides)
    return Budget(**values)


class M5AssessmentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_bridge(self, collection, replay, *, budget=None, run_name="assessment"):
        return assess_fixed_baseline(
            collection, self.root / run_name, budget=budget or make_budget(),
            transport=replay, count_tokens=replay.count_tokens,
            verify_source=lambda case_id, source_hash: True,
            model_fingerprint="fixture-model", tokenizer_fingerprint="fixture-tokenizer",
            prompt_fingerprint="fixture-prompt",
        )

    def test_accepted_assessment_uses_only_bound_raw_refs_and_keeps_selection_pending(self):
        collection = FixedFixtureTools().frozen_result()
        replay = StructuredReplay([valid_reply()])

        result = self.run_bridge(collection, replay)

        self.assertEqual(len(replay.payloads), 1)
        self.assertEqual(replay.schemas[0]["properties"]["action"]["const"], "assess_case_link")
        payload = replay.payloads[0]
        need_id = collection["pairs"][0]["locator_source_need_id"]
        a_refs = next(row["a_context_refs"] for row in collection["source_needs"]
                      if row["source_need_id"] == need_id)
        b_refs = collection["pairs"][0]["b_passage_refs"]
        self.assertEqual(set(payload["current_payload_source_refs"]), set(a_refs + b_refs))
        assessment = result["assessments"][0]
        self.assertEqual(assessment["source_need_id"], need_id)
        self.assertEqual(assessment["candidate_id"], "B.txt")
        self.assertEqual(assessment["a_context_refs"], a_refs)
        self.assertEqual(assessment["b_passage_refs"], b_refs)
        self.assertEqual(assessment["case_relation"], "similarity_only")
        self.assertEqual(result["pairs"][0]["case_relation"], "similarity_only")
        self.assertEqual(result["selection_status"], "pending_selection")
        self.assertEqual(result["selected"], [])
        self.assertEqual(result["usage"]["requests"], 1)
        self.assertEqual(result["model_requests"], 1)

    def test_unopened_retrieval_candidate_stays_pending_without_model_call(self):
        collection = FixedFixtureTools(open_candidate=False).frozen_result()
        replay = StructuredReplay([])

        result = self.run_bridge(collection, replay)

        self.assertEqual(replay.payloads, [])
        self.assertEqual(result["model_requests"], 0)
        self.assertEqual(result["pairs"][0]["case_relation"], "unknown")
        self.assertEqual(result["pairs"][0]["assessment_status"], "pending_evidence")
        self.assertEqual(result["assessment_contexts"][0]["status"], "pending_evidence")
        self.assertEqual(result["assessment_contexts"][0]["reason"], "missing_a_or_b_context")

    def test_other_source_needs_for_same_candidate_are_pending_and_not_assessed(self):
        collection = FixedFixtureTools(need_count=2).frozen_result()
        replay = StructuredReplay([valid_reply()])

        result = self.run_bridge(collection, replay)

        self.assertEqual(len(replay.payloads), 1)
        contexts = result["assessment_contexts"]
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[0]["status"], "accepted")
        self.assertEqual(contexts[1]["status"], "pending_evidence")
        self.assertEqual(contexts[1]["reason"], "b_context_not_acquired_for_need")

    def test_forged_or_wrong_side_refs_in_frozen_pair_fail_before_model_call(self):
        for mutate in (
            ("candidate_side_uses_A_ref", lambda result, a, b: result["pairs"][0].update(b_passage_refs=[a])),
            ("query_side_uses_B_ref", lambda result, a, b: result["source_needs"][0].update(a_context_refs=[b])),
        ):
            collection = FixedFixtureTools().frozen_result()
            a_ref = collection["source_needs"][0]["a_context_refs"][0]
            b_ref = collection["pairs"][0]["b_passage_refs"][0]
            label, apply_mutation = mutate
            apply_mutation(collection, a_ref, b_ref)
            replay = StructuredReplay([valid_reply()])
            with self.subTest(case=label), self.assertRaises(HarnessError):
                self.run_bridge(collection, replay)
            self.assertEqual(replay.payloads, [])

    def test_extra_forged_model_fields_are_rejected_without_retry_and_usage_is_kept(self):
        collection = FixedFixtureTools().frozen_result()
        replay = StructuredReplay([valid_reply(a_context_refs=["forged"], extra="ignored")])

        result = self.run_bridge(collection, replay)

        self.assertEqual(len(replay.payloads), 1)
        self.assertEqual(result["model_requests"], 1)
        self.assertEqual(result["usage"]["requests"], 1)
        self.assertEqual(result["usage"]["reported_input_tokens"], 17)
        self.assertEqual(result["usage"]["reported_output_tokens"], 6)
        self.assertEqual(result["status"], "assessment_failed")
        self.assertEqual(result["assessment_contexts"][0]["status"], "error")

    def test_budget_stop_and_resume_do_not_duplicate_completed_model_call(self):
        collection = FixedFixtureTools(candidate_count=2).frozen_result()
        replay = StructuredReplay([valid_reply()])
        budget = make_budget(max_requests=1, max_actions=1)

        first = self.run_bridge(collection, replay, budget=budget, run_name="resume")
        second = self.run_bridge(collection, replay, budget=budget, run_name="resume")

        self.assertEqual(len(replay.payloads), 1)
        self.assertEqual(first["usage"]["requests"], 1)
        self.assertEqual(second["usage"]["requests"], 1)
        self.assertEqual(first["assessment_contexts"][1]["status"], "pending_budget")
        self.assertEqual(second["assessment_contexts"][1]["status"], "pending_budget")

    def test_uncertain_receipt_is_not_resent_after_resume(self):
        collection = FixedFixtureTools().frozen_result()
        replay = StructuredReplay([TransportError("receipt uncertain", unknown=True)])

        first = self.run_bridge(collection, replay, run_name="uncertain")
        second = self.run_bridge(collection, replay, run_name="uncertain")

        self.assertEqual(first["status"], "assessment_failed")
        self.assertEqual(second["status"], "assessment_failed")
        self.assertEqual(first["usage"]["unknown_receipts"], 1)
        self.assertEqual(first["usage"]["requests"], 1)
        self.assertEqual(second["usage"]["requests"], 1)
        self.assertEqual(len(replay.request_ids), 1)
        self.assertEqual(second["assessment_contexts"][0]["status"], "error")

    def test_input_cap_stops_before_any_model_call(self):
        collection = FixedFixtureTools().frozen_result()
        replay = StructuredReplay([valid_reply()])

        result = self.run_bridge(collection, replay, budget=make_budget(
            max_input_tokens=1, max_payload_tokens=1), run_name="input-cap")

        self.assertEqual(replay.payloads, [])
        self.assertEqual(result["model_requests"], 0)
        self.assertEqual(result["assessment_contexts"][0]["status"], "pending_budget")

    def test_m4_candidate_seed_requires_candidate_to_be_registered(self):
        b = make_excerpt("B.txt", "b" * 64, 0, "candidate evidence")
        identity = RunIdentity(
            run_id="seed-guard", query_id="A.txt", query_source_hash="a" * 64,
            candidate_fingerprint="fixture-candidates", index_fingerprint="fixture-index",
            profile_fingerprint="fixture-profile", model_fingerprint="fixture-model",
            prompt_fingerprint="fixture-prompt", tools_fingerprint="fixture-tools",
            tokenizer_fingerprint="fixture-tokenizer",
        )
        with tempfile.TemporaryDirectory() as run_dir, self.assertRaises(HarnessError):
            AgentHarness(
                run_dir, identity=identity, budget=make_budget(), baseline=[], tools={},
                count_tokens=len, transport=lambda *_args: None,
                initial_observation=ToolResult({"fixture": True}, candidates=()),
                initial_candidate_excerpts=(b,),
            )


if __name__ == "__main__":
    unittest.main()
