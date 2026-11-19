"""Offline checks for cross-need labels, identity, and durable host selection."""

from tempfile import TemporaryDirectory
from unittest import TestCase

from pipeline_v2.agent_harness import ToolResult
from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.agent_harness.selection import aggregate_assessments, select_supported_cases
from pipeline_v2.tests.test_m6_adaptive import Tools, Transport, harness, source


def assessment(a, b, *, relation="supported", ident="first"):
    rows = [source("A", a).to_record(), source("B", b).to_record()]
    return {"query_id": "A", "candidate_id": "B", "assessment_id": ident, "case_relation": relation,
            "raw_evidence": {"a_context_refs": [rows[0]], "b_passage_refs": [rows[1]]}}


class SourceSelectionTests(TestCase):
    def test_m6_opens_only_the_cap_bound_displayed_lead(self):
        class MultipleLeads(Tools):
            def search_corpus(self, args):
                hits = [{"case_id": "B", "rank": i, "open_ref": {
                    "case_id": "B", "source_hash": self.b.source_hash, "passage_ids": [f"B-{i}"],
                }} for i in range(1, 5)]
                return ToolResult({"hits": hits}, candidates=("B",))

        def choose_second(body):
            card, = body["m6"]["candidates"].values()
            self.assertEqual([lead["open_ref"]["passage_ids"] for lead in card["leads"]],
                             [["B-1"], ["B-2"], ["B-3"]])
            return {"action": "open_retrieved_passage", "args": {"lead_ref": card["leads"][1]["lead_ref"]}}

        with TemporaryDirectory() as run:
            tools = MultipleLeads()
            h = harness(run, Transport(["search_cases_by_issue", choose_second, "finish_case_review"]),
                        tools, explicit_leads=True)
            self.assertEqual(h.run()["stop_reason"], "complete")
            self.assertEqual([args["passage_ids"] for action, args in tools.reads if action == "open"], [["B-2"]])

    def test_cross_anchor_max_and_parallel_identifier_in_candidate_header(self):
        positive = assessment("[1] The applicable test is in [2010] F.C.J. No. 500.",
                              "2010 FC 413; [2010] FCJ No 500\n[1] The test is as follows.")
        similar = assessment("[1] A seeks an extension.", "[1] B seeks an extension.",
                             relation="similarity_only", ident="second")
        self.assertEqual(aggregate_assessments([similar, positive], []), ("supported", "first"))
        self.assertEqual(aggregate_assessments([similar], []), ("similarity_only", None))

    def test_shared_citation_and_unresolved_parallel_cite_are_not_selection_witnesses(self):
        for b in ("2008 FC 30\n[1] We apply 2010 FC 413.",
                  "2010 FC 414\nCases cited:\n 2010 FC 413\n[1] The reasons begin."):
            row = assessment("[1] We apply 2010 FC 413.", b)
            label, ref = aggregate_assessments([row], [])
            self.assertEqual(label, "supported")
            self.assertIsNone(ref)
            self.assertEqual(select_supported_cases({"candidate_states": {
                "B": {"case_relation": label, "selection_assessment_id": ref}}})["prediction"], [])
        row = assessment("[1] We apply [2010] FCJ No 500.", "2010 FC 413\n[1] The test is as follows.")
        self.assertEqual(aggregate_assessments([row], []), ("supported", None))

    def test_valid_host_selection_after_raw_leaves_payload_and_rejects_stale_evidence(self):
        steps = ["search_cases_by_issue", "read_case_passages", "assess_case_link", "finish_case_review"]
        with TemporaryDirectory() as run:
            h = harness(run, Transport(steps), selector_fingerprint="fixture",
                        selector=lambda s: {"prediction": ["B"], "assessment_ids": s["active_assessment_ids"]})
            result = h.run()
            self.assertEqual(result["prediction"], ["B"])
            self.assertEqual(result["selection_status"], "selected")
            state = RunState(h.events())
            aid, = state.active_assessments.values()
            row = state.assessments[aid]
            args = {"prediction": ["B"], "assessment_ids": [aid]}
            with self.assertRaisesRegex(HarnessError, "inactive or unknown"):
                h._validate_prediction(state, {**args, "assessment_ids": ["missing"]}, require_current=False)
            with self.assertRaisesRegex(HarnessError, "requires an active assessment"):
                h._validate_prediction(state, {**args, "prediction": ["different"]}, require_current=False)
            pair = row["source_need_id"], row["candidate_id"]
            state.pending_assessments[pair] = {}
            with self.assertRaisesRegex(HarnessError, "pending review"):
                h._validate_prediction(state, args, require_current=False)
            del state.pending_assessments[pair]
            ref = row["b_passage_refs"][0]
            state.catalog[ref] = {**state.catalog[ref], "text": "tampered"}
            with self.assertRaisesRegex(HarnessError, "does not match the ledger"):
                h._validate_prediction(state, args, require_current=False)
