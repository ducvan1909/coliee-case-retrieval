"""Keep an accepted pair assessed when a repeat read adds no B source bytes."""
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.agent_harness import RunIdentity, SourceExcerpt, ToolResult
from pipeline_v2.experiments.context_manager_v2.cli import choose_read, quote_for_paragraph
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.tests.test_m6_adaptive import Tools, source


def count_tokens(body):
    return len(body) // 6 + 100


class ReopenTools(Tools):
    def __init__(self, repeat_result):
        super().__init__()
        text = ("The court applies a distinct notice rule to the motion. "
                "A second passage describes the later procedural exception.")
        self.b = source("B", text)
        self.c = source("C", "A different candidate concerns procedural fairness.")
        split = len("The court applies a distinct notice rule to the motion. ".encode())
        self.first_b = self.b.slice(0, split)
        self.new_b = self.b.slice(split, len(text.encode()))
        self.repeat_result = repeat_result
        self.b_opens = 0

    def search_corpus(self, args):
        hits = []
        for rank, row in enumerate((self.b, self.c), start=1):
            hits.append({
                "case_id": row.case_id,
                "rank": rank,
                "open_ref": {
                    "case_id": row.case_id,
                    "source_hash": row.source_hash,
                    "passage_ids": [row.case_id + "-1"],
                },
            })
        return ToolResult({"hits": hits}, candidates=("B", "C"))

    def open_source(self, args):
        if args["case_id"] == "C":
            return ToolResult({"case_id": "C"}, (self.c,), ("C",))
        self.b_opens += 1
        if self.b_opens == 1:
            return ToolResult({"case_id": "B"}, (self.first_b,), ("B",))
        if self.repeat_result == "empty":
            return ToolResult({"case_id": "B"}, (), ("B",))
        if self.repeat_result == "covered":
            return ToolResult({"case_id": "B"}, (self.first_b,), ("B",))
        if self.repeat_result == "covered_subset":
            return ToolResult({"case_id": "B"}, (self.first_b.slice(4, 35),), ("B",))
        return ToolResult({"case_id": "B"}, (self.new_b,), ("B",))

    def verify_source(self, case, digest):
        return any(row.case_id == case and row.source_hash == digest
                   for row in (self.a, self.b, self.c))


def make_engine(directory, tools):
    identity = RunIdentity(
        "empty-reopen", "A", tools.a.source_hash,
        "candidate-binding", "index-binding", "profile", "model",
        "prompt", "tool-binding", "counter-binding",
    )
    raw = {row.case_id: row.text.encode("utf-8") for row in (tools.a, tools.b, tools.c)}
    return Engine(
        directory,
        identity=identity,
        tools=tools,
        count_tokens=count_tokens,
        raw_reader=lambda case_id: raw[case_id],
        counter_binding="fixture-counter-v1",
    )


def action(prepared, name, *, case_id=None):
    branch = next(row for row in prepared["manifest"]["schema"]["anyOf"]
                  if row["properties"]["action"]["const"] == name)
    args_schema = branch["properties"]["args"]
    args = {}
    for field in args_schema["required"]:
        spec = args_schema["properties"][field]
        if "enum" in spec:
            args[field] = spec["enum"][0]
        elif field in ("issue", "focus"):
            args[field] = "procedural fairness"
        elif field == "anchor_quote":
            args[field] = quote_for_paragraph(prepared["payload"])
        else:
            args[field] = "The displayed passages do not establish the relation."
    if name == "assess_case_link":
        args.update(case_relation="unknown", passage_location="bounded")
    if name == "read_case_passages" and case_id is not None:
        candidates = prepared["payload"]["m6"]["candidates"]
        args["candidate_ref"] = next(
            ref for ref, candidate in candidates.items()
            if candidate["case_id"] == case_id
        )
    return {"action": name, "args": args}


def open_result(prepared, case_id):
    card = next(row for row in prepared["payload"]["m6"]["cm_page"]["candidates"] if row["case_id"] == case_id)
    return choose_read(prepared, card, "procedural fairness")


class EmptyReopenTests(unittest.TestCase):
    def prepare_assessed_b(self, directory, tools):
        engine = make_engine(directory, tools)
        engine.step(lambda prepared: action(prepared, "search_cases_by_issue"))
        engine.step(lambda prepared: open_result(prepared, "B"))
        engine.step(lambda prepared: action(prepared, "assess_case_link"))
        self.assertEqual(len(engine.state().active_assessments), 1)
        self.assertEqual(engine.context()["stage"], "assessed")
        return engine

    def reopen_b(self, engine):
        engine.step(lambda prepared: {
            "action": "show_context_page",
            "args": {"page_ref": prepared["payload"]["m6"]["cm_page"]["controls"]["results"]},
        })
        return engine.step(lambda prepared: action(
            prepared, "read_case_passages", case_id="B"))

    def test_empty_or_already_delivered_reopen_preserves_assessed_and_other_candidate_path(self):
        for repeated_read in ("empty", "covered"):
            with self.subTest(repeated_read=repeated_read), TemporaryDirectory() as directory:
                tools = ReopenTools(repeated_read)
                engine = self.prepare_assessed_b(directory, tools)
                prior_assessment_id = engine.state().active_assessments[
                    (engine.context()["need_id"], "B")
                ]

                self.reopen_b(engine)
                self.assertEqual(engine.context()["stage"], "assessed")
                self.assertEqual(engine.context()["mode"], "results")
                self.assertEqual(engine.state().active_assessments[
                    (engine.context()["need_id"], "B")
                ], prior_assessment_id)
                self.assertIsNone(engine.state().pending_action)
                last_action = engine.events()[-1]
                self.assertEqual(last_action["reason"], "reopened_without_new_raw")
                if repeated_read == "empty":
                    self.assertEqual((last_action.get("result") or {}).get("excerpts"), [])

                results = engine.prepare(admit=False)
                c_card = next(card for card in results["payload"]["m6"]["cm_page"]["candidates"]
                              if card["case_id"] == "C")
                self.assertTrue(c_card["read_allowed"])
                self.assertIn("read_case_passages", {
                    row["properties"]["action"]["const"]
                    for row in results["manifest"]["schema"]["anyOf"]
                })
                engine.step(lambda prepared: open_result(prepared, "C"))
                self.assertEqual(engine.context()["candidate_id"], "C")
                self.assertEqual(engine.context()["stage"], "reading")
                last_action = next(row for row in reversed(engine.events())
                                   if row["kind"] == "action_result")
                self.assertTrue(any(row["case_id"] == "C"
                                    for row in (last_action.get("result") or {}).get("excerpts", [])))

    def test_reopen_with_new_b_bytes_allows_assessment_revision(self):
        with TemporaryDirectory() as directory:
            tools = ReopenTools("fresh")
            engine = self.prepare_assessed_b(directory, tools)
            original_id = engine.state().active_assessments[(engine.context()["need_id"], "B")]

            self.reopen_b(engine)
            self.assertEqual(engine.context()["stage"], "reading")
            last_action = next(row for row in reversed(engine.events())
                               if row["kind"] == "action_result")
            self.assertTrue(any(
                row["case_id"] == "B" and row["span_bytes"] == list(tools.new_b.span_bytes)
                for row in (last_action.get("result") or {}).get("excerpts", [])
            ))
            followup = engine.prepare(admit=False)
            self.assertTrue(any(
                row["case_id"] == "B" and row["span_bytes"] == list(tools.new_b.span_bytes)
                for row in followup["payload"]["excerpts"]
            ))
            self.assertIn("assess_case_link", {
                row["properties"]["action"]["const"]
                for row in followup["manifest"]["schema"]["anyOf"]
            })

            engine.step(lambda prepared: action(prepared, "assess_case_link"))
            state = engine.state()
            new_id = state.active_assessments[(engine.context()["need_id"], "B")]
            self.assertNotEqual(new_id, original_id)
            self.assertEqual(state.assessments[new_id]["version"], 2)
            b_refs = state.assessments[new_id]["b_passage_refs"]
            self.assertTrue(any(tuple(state.catalog[ref]["span_bytes"]) == tools.new_b.span_bytes
                                for ref in b_refs))

    def test_covered_subspan_reloads_exact_text_without_revision(self):
        with TemporaryDirectory() as directory:
            engine = self.prepare_assessed_b(directory, ReopenTools("covered_subset"))
            self.reopen_b(engine)
            restored = engine.prepare(admit=False)
            candidate, = (row for row in restored["payload"]["excerpts"] if row["case_id"] == "B")
            self.assertEqual(candidate["span_bytes"], [4, 35])
            self.assertEqual(engine.context()["stage"], "assessed")
            self.assertEqual(engine.events()[-1]["reason"], "reopened_without_new_raw")
            self.assertFalse(engine.events()[-1]["result"]["excerpts"])
            self.assertTrue(engine.events()[-1]["reload_refs"])

    def test_defer_pair_releases_other_candidates_and_stays_unresolved(self):
        with TemporaryDirectory() as directory:
            engine = make_engine(directory, ReopenTools("empty"))
            engine.step(lambda p: action(p, "search_cases_by_issue"))
            engine.step(lambda p: open_result(p, "B"))
            engine.step(lambda p: action(p, "record_missing_evidence"))
            engine.step(lambda p: action(p, "defer_case_pair"))
            self.assertIsNone(engine.context()["candidate_id"])
            result = engine.prepare(admit=False)
            cards = {row["case_id"]: row for row in result["payload"]["m6"]["cm_page"]["candidates"]}
            self.assertFalse(cards["B"]["read_allowed"])
            self.assertTrue(cards["C"]["read_allowed"])
            progress = result["payload"]["last_action_feedback"]["review_progress"]
            self.assertEqual(progress["deferred_pairs"], 1)
            self.assertEqual(progress["unreviewed_pairs"], 1)
            self.assertFalse(progress["complete_policy_allowed"])
            engine.step(lambda p: open_result(p, "C"))
            engine.step(lambda p: action(p, "assess_case_link"))
            result = engine.prepare(admit=False)
            self.assertTrue(result["payload"]["last_action_feedback"]["review_progress"]["complete_policy_allowed"])
            engine.step({"action": "finish_case_review", "args": {"reason": "complete_policy"}})
            self.assertEqual(engine.state().final["stop_reason"], "partial")
            self.assertEqual(engine.state().final["review_status"], "partial_with_deferred_pairs")
            self.assertFalse(engine.state().final["fallback"])
            self.assertEqual(engine.state().final["deferred_pair_count"], 1)


if __name__ == "__main__":
    unittest.main()
