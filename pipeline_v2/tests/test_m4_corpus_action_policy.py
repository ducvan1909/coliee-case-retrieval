"""Offline tests for the one-search M4 corpus action policy."""

import json
from jsonschema import Draft202012Validator
import unittest

from pipeline_v2.agent_harness.contracts import ModelReply, TransportError, encode
from pipeline_v2.agent_harness.corpus_action_policy import CorpusActionTransport
from pipeline_v2.agent_harness.model_tools import CORPUS_MODEL_TOOLS
from pipeline_v2.agent_harness.schema import response_schema


QUERY_ID = "001001.txt"
CANDIDATE_ID = "001002.txt"
QUERY_REF = "query-raw-ref"
CANDIDATE_REF = "candidate-raw-ref"
OPEN_REF = {
    "case_id": CANDIDATE_ID,
    "source_hash": "b" * 64,
    "passage_ids": ["p000001"],
}


def excerpt(ref, case_id, text):
    return {"ref": ref, "case_id": case_id, "text": text}


def payload(*, observation, excerpts=None, current_refs=None, reloadable_refs=None,
            query_delivery="continuation", candidates=1, active=0):
    return encode({
        "query_id": QUERY_ID,
        "query_source_hash": "a" * 64,
        "max_output_tokens": 128,
        "query_delivery": query_delivery,
        "candidate_count": candidates,
        "active_assessment_count": active,
        "pending_source_count": 0,
        "excerpts": list(excerpts or []),
        "current_payload_source_refs": list(current_refs or []),
        "reloadable_source_refs": list(reloadable_refs or []),
        "observation": observation,
    })


class ScriptedTransport:
    def __init__(self, action):
        self.action = action
        self.prompt_fingerprint = "prompt-fixture"
        self.tokenizer_fingerprint = "tokenizer-fixture"
        self.receipts = []
        self.last_call_id = None
        self.calls = []
        self.counted_payloads = []

    def count_tokens(self, body):
        self.counted_payloads.append(body)
        return len(body)

    def send_structured(self, body, request_id, schema):
        self.calls.append((body, request_id, schema))
        reply = self.action
        if isinstance(reply, BaseException):
            raise reply
        return ModelReply(reply, input_tokens=len(body), output_tokens=23, latency_ms=45.0)


def harness_transport(action):
    underlying = ScriptedTransport(action)
    return CorpusActionTransport(underlying), underlying


class CorpusActionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.full_schema = response_schema({"search_corpus", "open_source", "open_query"})

    @staticmethod
    def action(name, args):
        return {"action": name, "args": args}

    def invoke(self, action, body, policy_schema=None):
        wrapped, underlying = harness_transport(action)
        expected_token_count = wrapped.count_tokens(body)
        reply = wrapped.send_structured(
            body, "request-1", policy_schema or self.full_schema,
        )
        self.assertEqual(len(underlying.calls), 1)
        sent, _, narrowed = underlying.calls[0]
        self.assertEqual(underlying.counted_payloads[-1], sent)
        self.assertEqual(expected_token_count, len(sent))
        augmented = json.loads(sent)
        self.assertEqual(augmented["available_tool"],
                         CORPUS_MODEL_TOOLS[wrapped.policy_receipts[0]["allowed_action"]])
        self.assertNotIn("available_tools", augmented)
        original = json.loads(body)
        self.assertEqual({key: value for key, value in augmented.items() if key != "available_tool"},
                         original)
        self.assertEqual(wrapped.policy_receipts[0]["status"], "accepted")
        self.assertEqual(len(narrowed["anyOf"]), 1)
        self.assertTrue(Draft202012Validator(narrowed).is_valid(underlying.action))
        self.assertTrue(Draft202012Validator(self.full_schema).is_valid(reply.action))
        return reply, narrowed, wrapped, underlying

    def test_hit_allows_only_exact_open_source_action(self):
        body = payload(
            observation={"action": "search_corpus", "hits": [
                {"case_id": CANDIDATE_ID, "open_ref": OPEN_REF},
            ]},
            excerpts=[excerpt(QUERY_REF, QUERY_ID, "A raw passage.")],
            current_refs=[QUERY_REF],
            reloadable_refs=[QUERY_REF],
        )
        reply, schema, wrapped, underlying = self.invoke(
            self.action("read_case_passages", {}), body,
        )
        self.assertEqual(reply.input_tokens, len(underlying.calls[0][0]))
        self.assertEqual(reply.output_tokens, 23)
        self.assertEqual(reply.latency_ms, 45.0)
        self.assertEqual(schema["anyOf"][0]["properties"]["action"]["const"], "read_case_passages")
        self.assertEqual(underlying.calls[0][1], "request-1")
        self.assertEqual(wrapped.policy_receipts[0]["allowed_action"], "open_source")
        self.assertEqual(reply.action, self.action("open_source", OPEN_REF))

    def test_both_current_raw_sides_allow_one_assessment_with_bound_refs(self):
        body = payload(
            observation={"action": "open_source", "case_id": CANDIDATE_ID},
            excerpts=[
                excerpt(QUERY_REF, QUERY_ID, "A raw passage."),
                excerpt(CANDIDATE_REF, CANDIDATE_ID, "B raw passage."),
            ],
            current_refs=[QUERY_REF, CANDIDATE_REF],
            reloadable_refs=[QUERY_REF, CANDIDATE_REF],
        )
        model_action = self.action("assess_case_link", {
            "case_relation": "unknown",
            "passage_location": "pinpoint",
            "reason": "The legal relationship remains uncertain.",
        })
        reply, schema, _, _ = self.invoke(model_action, body)
        self.assertEqual(reply.action["action"], "assess_links")
        row, = reply.action["args"]["assessments"]
        self.assertEqual(row["candidate_id"], CANDIDATE_ID)
        self.assertEqual(row["source_need_id"], "need-1")
        self.assertEqual(row["a_context_refs"], [QUERY_REF])
        self.assertEqual(row["b_passage_refs"], [CANDIDATE_REF])
        self.assertEqual(row["speaker"], {"role": "unknown"})
        self.assertEqual(schema["anyOf"][0]["properties"]["action"]["const"], "assess_case_link")
        validator = Draft202012Validator(schema)
        for extra in ({"reason": "x" * 121}, {"b_passage_refs": ["other-ref"]}):
            self.assertFalse(validator.is_valid(self.action("assess_case_link", model_action["args"] | extra)))

    def test_b_only_after_open_reloads_known_a_and_current_b(self):
        body = payload(
            observation={"action": "open_source", "case_id": CANDIDATE_ID},
            excerpts=[excerpt(CANDIDATE_REF, CANDIDATE_ID, "B raw passage.")],
            current_refs=[CANDIDATE_REF],
            reloadable_refs=[QUERY_REF, CANDIDATE_REF],
        )
        reply, schema, _, _ = self.invoke(
            self.action("reload_delivered_passages", {}), body,
        )
        self.assertEqual(reply.action["args"]["refs"], [QUERY_REF, CANDIDATE_REF])
        self.assertEqual(schema["anyOf"][0]["properties"]["action"]["const"],
                         "reload_delivered_passages")

    def test_after_assessment_policy_stops_and_no_hit_search_stops(self):
        after_assessment = payload(
            observation={"action": "assess_links"},
            excerpts=[excerpt(QUERY_REF, QUERY_ID, "A raw passage."),
                      excerpt(CANDIDATE_REF, CANDIDATE_ID, "B raw passage.")],
            current_refs=[QUERY_REF, CANDIDATE_REF],
            active=1,
        )
        reply, schema, _, _ = self.invoke(
            self.action("finish_case_review", {}),
            after_assessment,
        )
        self.assertEqual(schema["anyOf"][0]["properties"]["action"]["const"],
                         "finish_case_review")
        self.assertEqual(reply.action["args"]["reason"], "complete")
        self.assertEqual(reply.action["args"]["prediction"], [])

        no_hits = payload(
            observation={"action": "search_corpus", "hits": []},
            excerpts=[excerpt(QUERY_REF, QUERY_ID, "A raw passage.")],
            current_refs=[QUERY_REF],
            reloadable_refs=[QUERY_REF],
            candidates=0,
        )
        reply, schema, _, _ = self.invoke(
            self.action("finish_case_review", {}), no_hits,
        )
        self.assertEqual(schema["anyOf"][0]["properties"]["action"]["const"],
                         "finish_case_review")
        self.assertEqual(reply.action["args"]["reason"], "no_progress")

    def test_search_alias_translates_to_fixed_bm25_channel_and_one_hit_cap(self):
        body = payload(
            observation={"kind": "query_map"},
            excerpts=[excerpt(QUERY_REF, QUERY_ID, "A raises an appeal limitation issue.")],
            current_refs=[QUERY_REF],
            query_delivery="navigation",
            candidates=0,
        )
        model_action = self.action("search_cases_by_issue", {
            "issue": "appeal limitation",
        })
        reply, schema, _, underlying = self.invoke(model_action, body)
        self.assertEqual(
            schema["anyOf"][0]["properties"]["action"]["const"], "search_cases_by_issue",
        )
        self.assertEqual(
            reply.action,
            self.action("search_corpus", {
                "channel": "passage_bm25", "limit": 1, "text": "appeal limitation",
            }),
        )
        self.assertEqual(len(underlying.calls), 1)

    def test_model_cannot_supply_search_channel_limit_or_unknown_argument(self):
        body = payload(
            observation={"kind": "query_map"},
            excerpts=[excerpt(QUERY_REF, QUERY_ID, "A raises an appeal limitation issue.")],
            current_refs=[QUERY_REF],
            query_delivery="navigation",
            candidates=0,
        )
        wrapped, underlying = harness_transport(self.action("search_cases_by_issue", {
            "issue": "appeal limitation", "limit": 100,
        }))
        with self.assertRaises(TransportError) as caught:
            wrapped.send_structured(body, "request-bad-search-args", self.full_schema)
        self.assertEqual(len(underlying.calls), 1)
        self.assertEqual(caught.exception.input_tokens, len(underlying.calls[0][0]))
        self.assertEqual(caught.exception.output_tokens, 23)
        self.assertEqual(wrapped.policy_receipts[0]["status"], "rejected")

    def test_open_alias_rejects_model_supplied_refs_or_unknown_args(self):
        body = payload(
            observation={"action": "search_corpus", "hits": [
                {"case_id": CANDIDATE_ID, "open_ref": OPEN_REF},
            ]},
            excerpts=[excerpt(QUERY_REF, QUERY_ID, "A raw passage.")],
            current_refs=[QUERY_REF],
            reloadable_refs=[QUERY_REF],
        )
        wrapped, underlying = harness_transport(self.action(
            "read_case_passages", {"case_id": CANDIDATE_ID},
        ))
        with self.assertRaises(TransportError) as caught:
            wrapped.send_structured(body, "request-bad-open", self.full_schema)
        self.assertEqual(len(underlying.calls), 1)
        self.assertEqual(caught.exception.input_tokens, len(underlying.calls[0][0]))
        self.assertEqual(caught.exception.output_tokens, 23)
        self.assertEqual(wrapped.policy_receipts[0]["status"], "rejected")
        self.assertEqual(wrapped.policy_receipts[0]["model_action"], "read_case_passages")

    def test_forbidden_second_search_is_rejected_after_one_send_with_usage(self):
        body = payload(
            observation={"action": "search_corpus", "hits": [
                {"case_id": CANDIDATE_ID, "open_ref": OPEN_REF},
            ]},
            excerpts=[excerpt(QUERY_REF, QUERY_ID, "A raw passage.")],
            current_refs=[QUERY_REF],
            reloadable_refs=[QUERY_REF],
        )
        forbidden = self.action("search_cases_by_issue", {"issue": "another query"})
        wrapped, underlying = harness_transport(forbidden)
        with self.assertRaises(TransportError) as caught:
            wrapped.send_structured(body, "request-forbidden-search", self.full_schema)

        self.assertEqual(len(underlying.calls), 1)
        self.assertEqual(caught.exception.input_tokens, len(underlying.calls[0][0]))
        self.assertEqual(caught.exception.output_tokens, 23)
        self.assertEqual(caught.exception.latency_ms, 45.0)
        receipt = wrapped.policy_receipts[0]
        self.assertEqual(receipt["allowed_action"], "open_source")
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["error_code"], "corpus_action_policy_rejected")

    def test_bad_query_hit_is_not_opened(self):
        query_as_candidate = {**OPEN_REF, "case_id": QUERY_ID}
        body = payload(
            observation={"action": "search_corpus", "hits": [
                {"case_id": QUERY_ID, "open_ref": query_as_candidate},
            ]},
            excerpts=[excerpt(QUERY_REF, QUERY_ID, "A raw passage.")],
            current_refs=[QUERY_REF],
            reloadable_refs=[QUERY_REF],
        )
        reply, schema, _, _ = self.invoke(
            self.action("finish_case_review", {}), body,
        )
        self.assertEqual(reply.action["action"], "stop")
        self.assertEqual(schema["anyOf"][0]["properties"]["action"]["const"],
                         "finish_case_review")


if __name__ == "__main__":
    unittest.main()
