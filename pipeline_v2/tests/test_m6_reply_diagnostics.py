"""Regressions for durable diagnostics on rejected M6 model replies."""
import json
import tempfile
import unittest

from pipeline_v2.agent_harness.contracts import ModelReply, TransportError
from pipeline_v2.tests.test_m6_adaptive import Transport, harness


class ReplyTransport(Transport):
    def __init__(self, reply):
        super().__init__([])
        self.reply = reply
        self.request_ids = []

    def send_structured(self, payload, request_id, schema):
        self.request_ids.append(request_id)
        return self.reply


class ProviderFailureTransport(Transport):
    def __init__(self):
        super().__init__([])
        self.request_ids = []

    def send_structured(self, payload, request_id, schema):
        self.request_ids.append(request_id)
        raise TransportError("provider_unavailable", input_tokens=7,
                             output_tokens=0, latency_ms=12.5)


class M6ReplyDiagnosticsTests(unittest.TestCase):
    def _rejected(self, raw_action):
        with tempfile.TemporaryDirectory() as directory:
            transport = ReplyTransport(ModelReply(raw_action, 7, 3, 12.5))
            agent = harness(directory, transport)
            result = agent.run()
            events = agent.events()
            receipt = next(event for event in events if event["kind"] == "request_result")
            request = next(event for event in events if event["kind"] == "request_admitted")
            # Reopening a completed rejection must reuse the durable receipt, not send again.
            resumed = harness(directory, ReplyTransport(None))
            resumed_result = resumed.run()
            self.assertEqual(resumed_result["usage"], result["usage"])
            self.assertEqual(len(transport.request_ids), 1)
            self.assertEqual(len(resumed.transport.underlying.request_ids), 0)
            return result, receipt, request, transport

    def test_invalid_json_reply_is_durable_and_keeps_raw_reply_and_usage(self):
        raw = '{"action": '
        result, receipt, request, transport = self._rejected(raw)

        self.assertEqual(receipt["status"], "malformed")
        self.assertTrue(receipt["received_response"])
        self.assertEqual(receipt["schema_validation"], "rejected")
        self.assertEqual(receipt["request_id"], request["request_id"])
        diagnostic = receipt["m6_reply"]
        self.assertEqual(diagnostic["request_id"], request["request_id"])
        self.assertEqual(diagnostic["raw_action"], raw)
        self.assertEqual(diagnostic["rejection"]["stage"], "parse")
        self.assertTrue(diagnostic["rejection"]["code"])
        self.assertEqual(receipt["input_tokens"], 7)
        self.assertEqual(receipt["output_tokens"], 3)
        self.assertEqual(receipt["provider_latency_ms"], 12.5)
        self.assertEqual(result["usage"]["reported_input_tokens"], 7)
        self.assertEqual(result["usage"]["reported_output_tokens"], 3)
        self.assertEqual(transport.request_ids, [request["request_id"]])

    def test_schema_and_semantic_rejections_record_distinct_reason_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = ReplyTransport(None)
            agent = harness(directory, transport)
            paragraph_ref = next(iter(agent.prepare()["payload"]["m6"]["a_paragraphs"]))

        cases = (
            (json.dumps({"action": "search_cases_by_issue", "args": {
                "issue": "procedural fairness", "a_paragraph_ref": "invented-ref"}}), "schema",
             "schema_validation_failed", ["args", "a_paragraph_ref"], "enum"),
            (json.dumps({"action": "search_cases_by_issue", "args": {
                "issue": "fairness", "a_paragraph_ref": paragraph_ref}}), "semantics",
             "issue_requires_legal_phrase", None, None),
        )
        for raw, expected_stage, expected_code, expected_path, expected_validator in cases:
            with self.subTest(stage=expected_stage):
                _, receipt, request, _ = self._rejected(raw)
                diagnostic = receipt["m6_reply"]
                self.assertEqual(receipt["status"], "malformed")
                self.assertTrue(receipt["received_response"])
                self.assertEqual(diagnostic["request_id"], request["request_id"])
                self.assertEqual(diagnostic["raw_action"], raw)
                self.assertEqual(diagnostic["rejection"]["stage"], expected_stage)
                self.assertEqual(diagnostic["rejection"]["code"], expected_code)
                if expected_path is not None:
                    self.assertEqual(diagnostic["rejection"]["path"], expected_path)
                    self.assertEqual(diagnostic["rejection"]["validator"], expected_validator)

    def test_provider_error_has_no_model_reply_diagnostic_and_is_not_malformed(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = ProviderFailureTransport()
            agent = harness(directory, transport)
            result = agent.run()
            receipt = next(event for event in agent.events() if event["kind"] == "request_result")
            request = next(event for event in agent.events() if event["kind"] == "request_admitted")
            resumed = harness(directory, ProviderFailureTransport()).run()

        self.assertEqual(receipt["status"], "error")
        self.assertFalse(receipt["received_response"])
        self.assertEqual(receipt["error"], "transport_error")
        self.assertNotIn("m6_reply", receipt)
        self.assertEqual(receipt["request_id"], request["request_id"])
        self.assertEqual(receipt["input_tokens"], 7)
        self.assertEqual(receipt["output_tokens"], 0)
        self.assertEqual(receipt["provider_latency_ms"], 12.5)
        self.assertEqual(result["usage"]["requests"], 1)
        self.assertEqual(resumed["usage"]["requests"], 1)
        self.assertEqual(transport.request_ids, [request["request_id"]])


if __name__ == "__main__":
    unittest.main()
