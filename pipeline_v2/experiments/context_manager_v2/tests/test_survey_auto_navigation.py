"""Independent regressions for deterministic navigation during A survey."""
import json
from tempfile import TemporaryDirectory

from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2 import source_gate
from pipeline_v2.experiments.context_manager_v2.tests import test_map_first as map_first
from pipeline_v2.tests.test_m3_source_tools import SourceToolsFixture


class SurveyAutoNavigationTests(SourceToolsFixture):
    """Exercise auto reads with the real MapFirstQueryTools and local ledger."""

    def setUp(self):
        super().setUp()
        self.small_text = ("Query heading.\n[1] The court requires a fair opportunity to respond. "
                           + ("Judicial review procedure and notice; evidence. " * 28))
        self.medium_text = "Query heading. " + ("Judicial review procedure and notice; evidence. " * 60)
        first = "[1] " + ("The court considered the notice and the opportunity to answer. " * 8)
        second = "[2] " + ("The court considered the applicable review standard and remedy. " * 8)
        text = first + "\n" + second
        self.query_text = text
        first_end = len(first.encode("utf-8"))
        second_start = first_end + 1
        for case_id, body in (("000001.txt", self.small_text), ("000002.txt", self.medium_text)):
            raw = body.encode("utf-8")
            self.add_case(case_id, body, [{"handle": "all", "span_bytes": [0, len(raw)]}])
        raw = text.encode("utf-8")
        self.add_case("000003.txt", text, [
            {"handle": "p1", "span_bytes": [0, first_end]},
            {"handle": "p2", "span_bytes": [second_start, len(raw)]},
        ])
        self.reader = self.make_session()
        self.addCleanup(self.reader.close)

    def make_two_paragraph_engine(self, directory):
        engine, tools = map_first.MapFirstTests.make_engine(
            self, directory, leaf_bytes=600, query_case="000003.txt", gate_enabled=True)
        engine.survey_first = True

        # Keep a complete paragraph fitting while forcing the complete A text
        # and its ancestor region through the child-reader path.
        original = engine.harness.count_tokens

        def bounded_counter(body):
            payload = json.loads(body)
            if any(row["span_bytes"][1] - row["span_bytes"][0] > 600
                   for row in payload.get("excerpts", [])):
                return 9000
            return original(body)

        engine.harness.count_tokens = bounded_counter
        return engine, tools, tools.query_tree.raw

    @staticmethod
    def decide(prepared, engine, *, complete):
        action = choose(prepared, "assess_source_need", decision="no_search_needed",
                        attribution="court", reason_code="procedural_history",
                        reason="This displayed paragraph does not need another source.",
                        context_complete=complete)
        engine.reply(prepared["request_id"], action)
        engine.execute_pending()

    def test_initial_preview_is_read_only_and_admission_persists_exact_raw_view(self):
        with TemporaryDirectory() as directory:
            engine, tools, raw = self.make_two_paragraph_engine(directory)
            before_usage = engine.state().usage().copy()
            before_delivered = set(engine.state().delivered)
            before_context = engine.context().copy()

            preview = engine.prepare(admit=False)
            self.assertEqual(preview["status"], "ready")
            self.assertEqual(engine.state().usage(), before_usage)
            self.assertEqual(engine.state().delivered, before_delivered)
            self.assertEqual(engine.context(), before_context)
            self.assertFalse(any(event.get("cm_auto_query_view") for event in engine.events()))
            self.assertEqual(len(preview["payload"]["excerpts"]), 1)
            row = preview["payload"]["excerpts"][0]
            self.assertEqual(row["text"].encode("utf-8"), raw[
                row["span_bytes"][0]:row["span_bytes"][1]])
            canonical = preview["manifest"]["excerpts"][0]
            self.assertEqual(row["ref"], map_first.wire_ref(preview, canonical["ref"]))
            self.assertEqual(row["text"], canonical["text"])
            self.assertEqual(canonical["source_hash"], tools.query_tree.source_hash)

            admitted = engine.prepare()
            self.assertEqual(admitted["payload"]["excerpts"], preview["payload"]["excerpts"])
            self.assertEqual(engine.context()["mode"], "query_leaf")
            self.assertEqual(engine.context()["query_leaf_region"],
                             admitted["manifest"]["context"]["query_leaf_region"])
            auto_events = [event for event in engine.events()
                           if event.get("cm_auto_query_view")]
            self.assertEqual(len(auto_events), 1)
            self.assertEqual(auto_events[0]["cm_auto_query_view"], {
                key: admitted["manifest"]["context"][key]
                for key in ("mode", "query_leaf_region", "offset", "back", "revision")})
            self.assertFalse(any(event["kind"] == "action_started" for event in engine.events()),
                             "An automatic raw offer must not require a navigation tool action.")

            reopened, _, _ = self.make_two_paragraph_engine(directory)
            self.assertEqual(reopened.context(), engine.context())

    def test_unresolved_current_paragraph_blocks_auto_advance_then_settled_one_advances(self):
        with TemporaryDirectory() as directory:
            engine, tools, raw = self.make_two_paragraph_engine(directory)
            first = engine.prepare()
            self.assertEqual(first["manifest"]["context"]["mode"], "query_leaf")
            first_region = first["manifest"]["context"]["query_leaf_region"]
            first_span = tools.query_tree.region(first_region)["span_bytes"]
            first_bytes = raw[first_span[0]:first_span[1]]
            self.assertIn(b"[1]", first_bytes)

            # An incomplete judgment leaves an unresolved draft in this view.
            self.decide(first, engine, complete=False)
            unresolved = engine.prepare()
            self.assertEqual(unresolved["manifest"]["context"]["query_leaf_region"], first_region)
            self.assertIn("assess_source_need", {
                row["properties"]["action"]["const"]
                for row in unresolved["manifest"]["schema"]["anyOf"]})
            self.assertTrue(any(row["status"] == "unresolved"
                                for row in engine.context().get("source_gate", {}).values()))

            self.decide(unresolved, engine, complete=True)
            before = engine.state().usage().copy()
            before_delivered = set(engine.state().delivered)
            preview_next = engine.prepare(admit=False)
            self.assertEqual(preview_next["status"], "ready")
            next_context = preview_next["manifest"]["context"]
            self.assertEqual(next_context["mode"], "query_leaf")
            next_region = next_context["query_leaf_region"]
            next_span = tools.query_tree.region(next_region)["span_bytes"]
            self.assertGreaterEqual(next_span[0], first_span[1])
            self.assertIn(b"[2]", raw[next_span[0]:next_span[1]])
            self.assertEqual(engine.state().usage(), before)
            self.assertEqual(engine.state().delivered, before_delivered)
            self.assertEqual(engine.context()["query_leaf_region"], first_region,
                             "Previewing the next region must not persist navigation state.")

            admitted_next = engine.prepare()
            self.assertEqual(admitted_next["payload"]["excerpts"], preview_next["payload"]["excerpts"])
            self.assertEqual(engine.context()["query_leaf_region"], next_region)
            actions = [event["action"]["action"] for event in engine.events()
                       if event["kind"] == "action_started"]
            self.assertEqual(actions, ["assess_source_need", "assess_source_need"],
                             "No open_query/show_context_page action should sit between A regions.")
            self.decide(admitted_next, engine, complete=True)
            finished = engine.prepare(admit=False)
            self.assertTrue(source_gate.progress(engine.context(), engine.harness.query_paragraphs)["complete"])
            self.assertEqual(engine.context()["query_leaf_region"], next_region)
            self.assertIsNone(engine.state().final)
            self.assertNotIn("search_corpus", {
                row["properties"]["action"]["const"]
                for row in finished["manifest"]["schema"]["anyOf"]})
            self.assertEqual(len([event for event in engine.events()
                                  if event["kind"] == "action_started"]), 3)

    def test_admitted_raw_without_response_adds_no_screening_coverage(self):
        with TemporaryDirectory() as directory:
            engine, _ = map_first.MapFirstTests.make_engine(
                self, directory, query_case="000001.txt", gate_enabled=True)
            engine.survey_first = True
            first = engine.prepare()
            row = first["payload"]["excerpts"][0]
            self.assertTrue(row["text"])
            self.assertEqual(engine.state().delivered, set())
            self.assertFalse(any(event["kind"] == "action_started" for event in engine.events()))

            # The offered text alone does not screen a paragraph. With no
            # response, the durable coverage and source-gate ledger stay empty.
            source_gate = engine.context().get("source_gate", {})
            self.assertEqual(source_gate, {})
            self.assertEqual(engine.state().delivered, set())
            self.assertIsNone(engine.state().final)
