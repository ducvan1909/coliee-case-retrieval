"""CM4 regressions for one query-reading interface and whole-region delivery."""
import json
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.experiments.context_manager_v2.tests.view_helpers import wire_ref

from pipeline_v2.agent_harness import RunIdentity
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.query_navigation import QueryNavigationConfig
from pipeline_v2.experiments.context_manager_v2.query_options import MapFirstQueryTools
from pipeline_v2.tests.test_m3_source_tools import SourceToolsFixture
from pipeline_v2.tests.test_m4_tools import LexicalFixture


def count_tokens(body):
    # Stable offline counter with fixed prompt overhead; no provider is invoked.
    return len(body.decode("utf-8")) // 4 + 100


def branch(prepared, name):
    return next(row for row in prepared["manifest"]["schema"]["anyOf"]
                if row["properties"]["action"]["const"] == name)


def names(prepared):
    return {row["properties"]["action"]["const"]
            for row in prepared["manifest"]["schema"]["anyOf"]}


def target_rows(prepared):
    return {wire_ref(prepared, ref): row
            for ref, row in prepared["manifest"]["dispatch_m6"]["query_targets"].items()}


def choose_target(prepared, predicate):
    options = target_rows(prepared)
    return next(ref for ref, row in options.items() if predicate(ref, row))


class MapFirstTests(SourceToolsFixture):
    """Use the real query tree, source reader, CM4 registry, and decoder schema."""

    def setUp(self):
        super().setUp()
        # Both complete query texts are >1024 bytes but fit their full next
        # payload under this suite's deterministic offline counter.
        self.small_text = ("Query heading.\n[1] The court requires a fair opportunity to respond. "
                           + ("Judicial review procedure and notice; evidence. " * 28))
        self.medium_text = "Query heading. " + ("Judicial review procedure and notice; evidence. " * 60)
        self.query_text = self.medium_text
        for case_id, text in (("000001.txt", self.small_text), ("000002.txt", self.medium_text)):
            raw = text.encode("utf-8")
            self.add_case(case_id, text, [{"handle": "all", "span_bytes": [0, len(raw)]}])
        self.reader = self.make_session()
        self.addCleanup(self.reader.close)

    def make_engine(self, directory, *, leaf_bytes=4096, query_case="000002.txt", gate_enabled=False):
        tools = MapFirstQueryTools(
            self.reader, LexicalFixture(), query_case, byte_budget=8192, map_limit=2,
            navigation_config=QueryNavigationConfig(max_children=2, leaf_bytes=leaf_bytes,
                                                    snippet_chars=24),
            count_tokens=count_tokens, output_token_cap=512,
        )
        initial, whole = tools.query_start()
        identity = RunIdentity(
            "map-first", query_case, whole.source_hash, "candidate-binding",
            "index-binding", "profile", "model", "prompt", tools.fingerprint,
            "counter-binding",
        )
        engine = Engine(
            directory, identity=identity, tools=tools, count_tokens=count_tokens,
            raw_reader=lambda case_id: (self.case_dir / case_id).read_bytes(),
            initial_observation=initial, query_excerpt=whole,
            counter_binding="map-first-counter-v1", gate_enabled=gate_enabled,
        )
        return engine, tools

    def test_results_registry_does_not_build_an_unused_query_map(self):
        from unittest.mock import patch
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory)
            context = engine.context()
            context.update(mode='results', stage='results_ready')
            with patch.object(engine, 'context', return_value=context), patch.object(
                    tools, 'map_page', side_effect=AssertionError('Unused map must not compile')):
                prepared = engine.prepare(admit=False)
            self.assertEqual(prepared['status'], 'ready')
            self.assertNotIn('query_navigation', prepared['payload']['m6'])
            self.assertEqual(prepared['manifest']['dispatch_m6']['query_targets'], {})

    def test_map_cap_counts_exact_compact_projection_and_keeps_routes(self):
        from pipeline_v2.agent_harness.contracts import encode
        from pipeline_v2.experiments.context_manager_v2.model_view import project
        with TemporaryDirectory() as directory:
            _, tools = self.make_engine(directory, leaf_bytes=1024)
            tools.navigation_config = QueryNavigationConfig(max_children=2, leaf_bytes=1024,
                snippet_chars=24, map_max_tokens=2400)
            def status(_):
                return {'map_opened': True, 'map_seen': True, 'preview_seen': True,
                        'raw_read': 'partial', 'search_used': True, 'raw_offered': 'partial'}
            page = tools.map_page(tools.query_tree.root_ref, status=status,
                totals={'maps_opened': 10, 'maps_seen': 10, 'previews_seen': 60,
                        'raw_read_bytes': 12345, 'search_source_spans': 4}, compact=True)
            minimal = {'query_id': tools.query_case, 'query_source_hash': tools.query_tree.source_hash,
                       'max_output_tokens': tools.output_token_cap, 'excerpts': [],
                       'current_payload_source_refs': [], 'm6': {'query_navigation': page}}
            wire, _, _ = project(minimal, {})
            self.assertEqual(tools.page_tokens(page), tools.navigation_counter(encode(wire)))
            self.assertLessEqual(tools.page_tokens(page), 2400)
            self.assertEqual([row['region_ref'] for row in page['children']],
                             [row['region_ref'] for row in tools.query_tree.children(tools.query_tree.root_ref)])
            self.assertTrue(all(row['snippets'] for row in page['children']))
            self.assertGreater(tools.navigation_counter(encode(minimal)), tools.page_tokens(page))

    def test_truly_unfit_query_map_is_a_recorded_terminal_not_an_exception(self):
        from unittest.mock import patch
        from pipeline_v2.agent_harness.contracts import HarnessError
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory)
            error = HarnessError('Query map with nonempty literal previews cannot fit its explicit token cap')
            with patch.object(tools, 'map_page', side_effect=error):
                result = engine.prepare(admit=False)
            self.assertEqual(result['status'], 'unfit')
            self.assertEqual(engine.state().final['stop_detail'], 'query_navigation_map_unfit')
            self.assertEqual(engine.state().usage()['requests'], 0)

    def test_query_leaf_shows_gate_feedback_and_hides_settled_paragraph(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory, query_case="000001.txt", gate_enabled=True)
            engine.step(lambda p: choose(p, "read_query_passages"))

            def screen(p, complete):
                return choose(p, "assess_source_need", decision="no_search_needed", attribution="court",
                              reason_code="procedural_history", reason="The passage gives procedural context.",
                              context_complete=complete)

            engine.step(lambda p: screen(p, False))
            retry = engine.prepare(admit=False)
            feedback = retry["payload"]["last_action_feedback"]["last_action"]
            self.assertEqual(feedback["action"], "assess_source_need")
            self.assertEqual(feedback["source_gate"]["decision"], "need_more_context")
            self.assertTrue(feedback["source_gate"]["validation_message"])
            self.assertIn("assess_source_need", names(retry))
            engine.step(lambda p: screen(p, True))
            settled = engine.prepare(admit=False)
            self.assertNotIn("assess_source_need", names(settled))
            self.assertTrue(settled["payload"]["m6"]["a_paragraphs"])
            feedback = settled["payload"]["last_action_feedback"]["last_action"]["source_gate"]
            self.assertEqual(feedback["status"], "screened")

    def test_small_and_medium_roots_over_1024_bytes_arrive_whole_when_they_fit(self):
        for case_id, text in (("000001.txt", self.small_text), ("000002.txt", self.medium_text)):
            with self.subTest(case_id=case_id), TemporaryDirectory() as directory:
                engine, tools = self.make_engine(directory, leaf_bytes=4096, query_case=case_id)
                raw = text.encode("utf-8")
                root = tools.query_tree.root_ref
                self.assertGreater(len(raw), 1024)

                prepared = engine.prepare(admit=False)
                self.assertIn("read_query_passages", names(prepared))
                self.assertNotIn("expand_query_map", names(prepared))
                self.assertNotIn("query_navigation", prepared["payload"]["m6"])
                self.assertEqual(len(target_rows(prepared)), 1)
                self.assertTrue(prepared["payload"]["m6"]["whole_query_fit"]["fits"])
                self.assertIn("query_ref", branch(prepared, "read_query_passages")["properties"]["args"]["properties"])
                target = choose_target(prepared, lambda _key, row:
                                       row["binding"]["region_ref"] == root
                                       and row["description"].get("response") == "full_text")

                engine.step({"action": "read_query_passages", "args": {"query_ref": target}})
                delivered = engine.prepare(admit=False)
                self.assertLessEqual(delivered["input_tokens"], 8500)
                excerpts = [row for row in delivered["payload"]["excerpts"]
                            if row["case_id"] == case_id
                            and row["ref"] in delivered["payload"]["current_payload_source_refs"]]
                self.assertEqual(len(excerpts), 1)
                excerpt = excerpts[0]
                self.assertEqual(tuple(excerpt["span_bytes"]), (0, len(raw)))
                self.assertEqual(excerpt["text"].encode("utf-8"), raw,
                                 "a fitting region must arrive whole, without head/tail clipping")

    def test_query_leaf_preserves_repair_feedback_and_full_text_at_budget_limit(self):
        with TemporaryDirectory() as directory:
            engine, _ = self.make_engine(directory, query_case="000001.txt")
            ready = engine.prepare(admit=False)
            target = next(iter(target_rows(ready)))
            engine.step({"action": "read_query_passages", "args": {"query_ref": target}})
            initial = engine.prepare(admit=False)
            invalid = {"action": "search_cases_by_issue", "args": {
                "issue": "fairness", "source_proposition": "The court requires an opportunity to respond.",
                "anchor_quote": "The court requires a fair opportunity to respond."}}
            engine.step(invalid)
            self.assertTrue(engine.state().last_receipt["cm_tool_repair"]["retry_allowed"])
            self.assertFalse(any(row["kind"] == "action_started" and row["action"]["action"] == "search_corpus"
                                 for row in engine.events()))

            def constrained(body):
                payload = json.loads(body)
                if payload["last_action_feedback"].get("tool_repair") and "a_paragraphs" in payload["m6"]:
                    return 8501
                return count_tokens(body)

            engine.harness.count_tokens = constrained
            correction = engine.prepare()
            feedback = correction["payload"]["last_action_feedback"]
            self.assertEqual(feedback["tool_repair"]["code"], "issue_requires_legal_phrase")
            self.assertEqual(feedback["tool_repair"]["fields"], ["issue"])
            self.assertLessEqual(correction["input_tokens"], 8500)
            self.assertNotIn("a_paragraphs", correction["payload"]["m6"])
            self.assertTrue(correction["manifest"]["dispatch_m6"]["a_paragraphs"])
            self.assertEqual(correction["payload"]["excerpts"], initial["payload"]["excerpts"])

            valid = {**invalid, "args": {**invalid["args"], "issue": "procedural fairness"}}
            engine.reply(correction["request_id"], valid)
            self.assertEqual(engine.state().last_receipt["status"], "success")
            search = engine.state().pending_action["action"]
            self.assertEqual(search["action"], "search_corpus")
            self.assertEqual(search["args"]["_m6_need"]["a_anchor"]["text"], valid["args"]["anchor_quote"])

    def test_over_budget_region_returns_a_map_then_child_uses_same_tool_and_exact_raw(self):
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory, leaf_bytes=2048)
            original_count = engine.harness.count_tokens

            # Force a realistic budget split based on source span size while
            # leaving the map and each sufficiently small child below the cap.
            def constrained_count(body):
                payload = json.loads(body)
                if any(row["span_bytes"][1] - row["span_bytes"][0] > 700
                       for row in payload["excerpts"]):
                    return 9000
                return original_count(body)

            engine.harness.count_tokens = constrained_count
            current = engine.prepare(admit=False)
            self.assertIn("read_query_passages", names(current))
            self.assertNotIn("expand_query_map", names(current))
            initial_page = current["manifest"]["dispatch_m6"]["query_navigation"]
            oversized_child = initial_page["children"][0]["region_ref"]
            stable_regions = {oversized_child: tuple(tools.query_tree.region(oversized_child)["span_bytes"])}
            child_map = choose_target(current, lambda _key, row:
                                      row["binding"]["region_ref"].startswith(oversized_child)
                                      and row["description"].get("response") == "map")
            engine.step({"action": "read_query_passages", "args": {"query_ref": child_map}})
            current = engine.prepare(admit=False)
            first_page = current["manifest"]["dispatch_m6"]["query_navigation"]
            self.assertEqual(first_page["current"]["region_ref"], oversized_child + "~")
            stable_regions[first_page["current"]["region_ref"]] = tuple(
                tools.query_tree.region(first_page["current"]["region_ref"])["span_bytes"])
            self.assertTrue(first_page["children"])
            self.assertIn("read_query_passages", names(current))
            self.assertNotIn("expand_query_map", names(current))

            # Select a child through read_query_passages. It may return either a
            # deeper map or its full text, but the public tool stays unchanged.
            child = first_page["children"][0]["region_ref"]
            child_choice = choose_target(current, lambda _key, row:
                                         row["binding"]["region_ref"].startswith(child)
                                         and row["description"].get("response") == "map")
            engine.step({"action": "read_query_passages", "args": {"query_ref": child_choice}})
            current = engine.prepare(admit=False)
            second_page = current["manifest"]["dispatch_m6"].get("query_navigation")
            self.assertTrue(second_page is None or second_page["current"]["region_ref"] != first_page["current"]["region_ref"])
            if second_page:
                region_ref = second_page["current"]["region_ref"]
                stable_regions[region_ref] = tuple(tools.query_tree.region(region_ref)["span_bytes"])
            self.assertIn("read_query_passages", names(current))
            self.assertNotIn("expand_query_map", names(current))

            # Parent/root is a useful route while viewing the child map.
            parent_ref = first_page["parent_ref"]
            if parent_ref is not None:
                parent_choice = choose_target(current, lambda _key, row:
                                              row["binding"]["region_ref"] == parent_ref)
                engine.step({"action": "read_query_passages", "args": {"query_ref": parent_choice}})
                current = engine.prepare(admit=False)
                self.assertEqual(current["manifest"]["dispatch_m6"]["query_navigation"]["current"]["region_ref"], parent_ref)
                stable_regions[parent_ref] = tuple(tools.query_tree.region(parent_ref)["span_bytes"])
                self.assertIn("read_query_passages", names(current))
                # Re-enter the same oversized branch using the unified interface.
                oversized_choice = choose_target(current, lambda _key, row:
                                                  row["binding"]["region_ref"].startswith(oversized_child)
                                                  and row["description"].get("response") == "map")
                engine.step({"action": "read_query_passages", "args": {"query_ref": oversized_choice}})
                current = engine.prepare(admit=False)

            # Keep choosing a descendant map until a whole child fits. Every
            # transition is again the single public read tool.
            for _ in range(10):
                full_targets = [(ref, row) for ref, row in target_rows(current).items()
                                if row["description"].get("response") == "full_text"]
                if full_targets:
                    ref, option = full_targets[0]
                    selected_span = tools.query_tree.region(option["binding"]["region_ref"])["span_bytes"]
                    engine.step({"action": "read_query_passages", "args": {"query_ref": ref}})
                    delivered = engine.prepare(admit=False)
                    excerpts = [row for row in delivered["payload"]["excerpts"]
                                if row["case_id"] == "000002.txt"
                                and row["ref"] in delivered["payload"]["current_payload_source_refs"]]
                    self.assertEqual(len(excerpts), 1)
                    excerpt = excerpts[0]
                    raw = self.query_text.encode("utf-8")
                    start, end = selected_span
                    self.assertEqual(tuple(excerpt["span_bytes"]), (start, end))
                    self.assertEqual(excerpt["text"].encode("utf-8"), raw[start:end])
                    self.assertLessEqual(delivered["input_tokens"], 8500)
                    break

                maps = [(ref, row) for ref, row in target_rows(current).items()
                        if row["description"].get("response") == "map"]
                self.assertTrue(maps, "a budget-limited map must expose another useful region")
                current_region = current["manifest"]["dispatch_m6"].get("query_navigation", {}).get("current", {}).get("region_ref")
                descendant = next(((ref, row) for ref, row in maps
                                   if row["binding"]["region_ref"].startswith(current_region or "")), maps[0])
                engine.step({"action": "read_query_passages", "args": {"query_ref": descendant[0]}})
                current = engine.prepare(admit=False)
                map_page = current["manifest"]["dispatch_m6"].get("query_navigation")
                if map_page:
                    region_ref = map_page["current"]["region_ref"]
                    stable_regions[region_ref] = tuple(tools.query_tree.region(region_ref)["span_bytes"])
                self.assertIn("read_query_passages", names(current))
                self.assertNotIn("expand_query_map", names(current))
            else:
                self.fail("A complete fitting child was not reachable through read_query_passages")

            for region_ref, original_span in stable_regions.items():
                self.assertEqual(tuple(tools.query_tree.region(region_ref)["span_bytes"]), original_span)

if __name__ == "__main__":
    unittest.main()
