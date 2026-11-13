"""Independent tests for M6 paragraph-bound issue search provenance."""
from copy import deepcopy
from hashlib import sha256
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.adaptive_policy import catalog, translate
from pipeline_v2.agent_harness.evidence import slice_record
from pipeline_v2.m4 import M3Tools
from pipeline_v2.m6 import AdaptiveHarness
from pipeline_v2.tests.test_m3_source_tools import SourceToolsFixture
from pipeline_v2.tests.test_m4_tools import LexicalFixture


class NoInferenceTransport:
    """prepare() must not call this transport."""
    def count_tokens(self, payload):
        return len(payload) // 10 + 1

    def send_structured(self, *args, **kwargs):
        raise AssertionError("paragraph contract tests must not run inference")


class M6ParagraphAnchorTests(SourceToolsFixture):
    def setUp(self):
        super().setUp()
        self.query_id = "000001.txt"
        self.text = "Énoncé initial.\n\nDeuxième règle: notice and an opportunity to respond.\n"
        raw = self.text.encode("utf-8")
        first_start = 0
        first_end = len("Énoncé initial.".encode("utf-8"))
        second_start = len("Énoncé initial.\n\n".encode("utf-8"))
        second_end = len(raw)
        self.paragraph_spans = ([first_start, first_end], [second_start, second_end])
        self.add_case(self.query_id, self.text, [
            {"handle": "p-first", "span_bytes": list(self.paragraph_spans[0])},
            {"handle": "p-second", "span_bytes": list(self.paragraph_spans[1])},
        ])
        self.reader = self.make_session()
        self.addCleanup(self.reader.close)
        self.tools = M3Tools(self.reader, LexicalFixture(), self.query_id,
                             byte_budget=4096, map_limit=10)
        self.identity = RunIdentity(
            "paragraph-test", self.query_id, self.sources[self.query_id],
            "candidates", "index", "profile", "model", "prompt", "tools", "tokenizer")

    def prepared_payload(self, run_dir):
        agent = AdaptiveHarness(
            run_dir, identity=self.identity,
            budget=Budget(4, 4, 100000, 18000, 512),
            m3_tools=self.tools, transport=NoInferenceTransport())
        prepared = agent.prepare()
        self.assertEqual(prepared["status"], "ready")
        return agent, prepared["payload"]

    @staticmethod
    def search_action(tool, handle):
        return {"action": "search_cases_by_issue", "args": {
            "issue": "procedural fairness notice", "a_paragraph_ref": handle}}

    def test_tool_requires_offered_paragraph_and_narrows_provenance_to_utf8_range(self):
        with TemporaryDirectory() as temp:
            agent, body = self.prepared_payload(temp)
            paragraphs = body["m6"]["a_paragraphs"]
            self.assertEqual(set(paragraphs), {"p-first", "p-second"})
            row = paragraphs["p-second"]
            start, end = self.paragraph_spans[1]
            raw = self.text.encode("utf-8")
            self.assertEqual(row["span_bytes"], [start, end])
            self.assertEqual(row["case_id"], self.query_id)
            self.assertEqual(row["source_hash"], sha256(raw).hexdigest())
            source = next(excerpt for excerpt in body["excerpts"]
                          if excerpt["ref"] == row["source_ref"])
            local_start = start - source["span_bytes"][0]
            local_end = end - source["span_bytes"][0]
            self.assertEqual(source["text"].encode("utf-8")[local_start:local_end].decode("utf-8"),
                             raw[start:end].decode("utf-8"))
            self.assertEqual(row["text_sha256"], sha256(raw[start:end]).hexdigest())

            tool = next(t for t in body["available_tools"] if t["name"] == "search_cases_by_issue")
            self.assertEqual(tool["parameters"]["required"], ["issue", "a_paragraph_ref"])
            schema = catalog(body)[1]
            translated = translate(body, self.search_action(tool, "p-second"))
            need = translated["args"]["_m6_need"]
            self.assertEqual(need["a_paragraph"]["handle"], "p-second")
            self.assertEqual(need["a_paragraph"]["span_bytes"], [start, end])
            self.assertEqual(need["a_sources"], [{
                "case_id": self.query_id, "source_hash": self.sources[self.query_id],
                "span_bytes": [start, end]}])
            self.assertEqual(need["a_refs"], [row["source_ref"]])
            self.assertIsNotNone(schema)
            self.assertEqual(agent.inspect()["usage"]["requests"], 0)

    def test_foreign_handle_is_not_in_contract_and_is_rejected(self):
        with TemporaryDirectory() as temp:
            _, body = self.prepared_payload(temp)
            tools, schema, _, _ = catalog(body)
            search_tool = next(t for t in tools if t["name"] == "search_cases_by_issue")
            self.assertEqual(search_tool["parameters"]["properties"]["a_paragraph_ref"]["enum"],
                             ["p-first", "p-second"])
            with self.assertRaises(Exception):
                translate(body, self.search_action(search_tool, "paragraph-from-another-case"))
            with self.assertRaises(Exception):
                translate(body, {"action": "search_cases_by_issue", "args": {
                    "issue": "procedural fairness notice"}})
            self.assertTrue(schema["anyOf"])

    def test_no_wholly_covered_paragraph_means_no_search_tool(self):
        with TemporaryDirectory() as temp:
            agent, body = self.prepared_payload(temp)
            a = next(row for row in body["excerpts"] if row["case_id"] == self.query_id)
            # This clipped source ends inside p-second, so neither paragraph is fully present.
            start = self.paragraph_spans[0][0] + 2
            end = self.paragraph_spans[1][1] - 3
            clipped = slice_record(a, start, end)
            clipped_body = deepcopy(body)
            clipped_body["excerpts"] = [clipped if row["ref"] == a["ref"] else row
                                         for row in body["excerpts"]]
            clipped_body["current_payload_source_refs"] = [row["ref"] for row in clipped_body["excerpts"]]
            clipped_body["m6"]["a_paragraphs"] = agent._visible_paragraphs(clipped_body)
            self.assertEqual(clipped_body["m6"]["a_paragraphs"], {})
            names = {row["name"] for row in catalog(clipped_body)[0]}
            self.assertNotIn("search_cases_by_issue", names)


if __name__ == "__main__":
    unittest.main()
