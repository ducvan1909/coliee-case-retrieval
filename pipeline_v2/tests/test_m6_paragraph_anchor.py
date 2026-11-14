"""Independent tests for M6 paragraph-bound issue search provenance."""
from copy import deepcopy
from hashlib import sha256
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pipeline_v2.agent_harness import Budget, RunIdentity, SourceExcerpt
from pipeline_v2.agent_harness.adaptive_policy import VERSION, ToolSemanticError, catalog, translate
from pipeline_v2.agent_harness.contracts import fingerprint
from pipeline_v2.agent_harness.evidence import slice_record
from pipeline_v2.agent_harness.ledger import RunState
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

    def clipped_body(self, agent, body, ranges):
        source = next(row for row in body['excerpts'] if row['case_id'] == self.query_id)
        result = deepcopy(body)
        result['excerpts'] = [slice_record(source, start, end) for start, end in ranges]
        result['current_payload_source_refs'] = [row['ref'] for row in result['excerpts']]
        result['m6']['a_paragraphs'] = agent._visible_paragraphs(result)
        return result

    def test_clipped_paragraphs_are_searchable_with_exact_raw_provenance(self):
        with TemporaryDirectory() as temp:
            agent, body = self.prepared_payload(temp)
            start = self.paragraph_spans[0][0] + 2
            end = self.paragraph_spans[1][1] - 3
            clipped = self.clipped_body(agent, body, [(start, end)])
            self.assertEqual(len(clipped['m6']['a_paragraphs']), 2)
            self.assertIn('search_cases_by_issue', {row['name'] for row in catalog(clipped)[0]})
            raw = self.text.encode('utf-8')
            for handle, row in clipped['m6']['a_paragraphs'].items():
                need = translate(clipped, self.search_action(None, handle))['args']['_m6_need']
                left, right = row['span_bytes']
                self.assertEqual(row['paragraph_coverage'], 'partial')
                self.assertEqual(row['text_sha256'], sha256(raw[left:right]).hexdigest())
                self.assertEqual(need['a_paragraph'], {'handle': handle, **row})
                self.assertEqual(need['a_sources'][0]['span_bytes'], row['span_bytes'])

    def test_beginning_middle_and_end_utf8_fragments(self):
        with TemporaryDirectory() as temp:
            agent, body = self.prepared_payload(temp)
            start, end = self.paragraph_spans[1]
            middle = start + len('Deuxième règle: '.encode('utf-8'))
            for left, right in ((start, middle), (middle, end - 3), (middle, end)):
                with self.subTest(span=(left, right)):
                    clipped = self.clipped_body(agent, body, [(left, right)])
                    handle = f'p-second@{left}:{right}'
                    self.assertEqual(set(clipped['m6']['a_paragraphs']), {handle})
                    row = clipped['m6']['a_paragraphs'][handle]
                    self.assertEqual(row['paragraph_span_bytes'], list(self.paragraph_spans[1]))
                    self.assertEqual(row['paragraph_handle'], 'p-second')
                    self.assertEqual(row['preview'], self.text.encode('utf-8')[left:right].decode('utf-8'))
                    translate(clipped, self.search_action(None, handle))

    def test_disjoint_or_overlapping_pieces_never_stitched_and_order_is_stable(self):
        with TemporaryDirectory() as temp:
            agent, body = self.prepared_payload(temp)
            start, end = self.paragraph_spans[1]
            a = start + len('Deuxième règle: '.encode('utf-8'))
            b = a + len('notice and '.encode('utf-8'))
            for spans in ([(start, a), (b, end)], [(start, b), (a, end)]):
                one = self.clipped_body(agent, body, spans)
                two = self.clipped_body(agent, body, list(reversed(spans)))
                self.assertEqual(one['m6']['a_paragraphs'], two['m6']['a_paragraphs'])
                self.assertEqual(len(one['m6']['a_paragraphs']), 2)
                self.assertNotIn('p-second', one['m6']['a_paragraphs'])
                self.assertEqual(fingerprint(catalog(one)[1]), fingerprint(catalog(two)[1]))
                for handle in one['m6']['a_paragraphs']:
                    self.assertEqual(translate(one, self.search_action(None, handle)),
                                     translate(two, self.search_action(None, handle)))

    def test_full_precedence_and_duplicate_contained_piece_dedup(self):
        with TemporaryDirectory() as temp:
            agent, body = self.prepared_payload(temp)
            start, end = self.paragraph_spans[1]
            middle = start + len('Deuxième règle: '.encode('utf-8'))
            ranges = [(start, end), (middle, end), (start, middle), (start, end)]
            clipped = self.clipped_body(agent, body, ranges)
            self.assertEqual(set(clipped['m6']['a_paragraphs']), {'p-second'})
            self.assertEqual(clipped['m6']['a_paragraphs']['p-second']['paragraph_coverage'], 'full')
            # Distinct raw excerpts cover the same prefix intersection; narrowest wins.
            ranges = [(0, middle), (start, middle), (start + len('Deuxième '.encode('utf-8')), middle)]
            one = self.clipped_body(agent, body, ranges)
            two = self.clipped_body(agent, body, list(reversed(ranges)))
            self.assertEqual(one['m6']['a_paragraphs'], two['m6']['a_paragraphs'])
            partial = one['m6']['a_paragraphs'][f'p-second@{start}:{middle}']
            narrow = next(row for row in one['excerpts'] if tuple(row['span_bytes']) == (start, middle))
            self.assertEqual(partial['source_ref'], narrow['ref'])

    def test_stale_foreign_and_empty_raw_do_not_offer_search(self):
        with TemporaryDirectory() as temp:
            agent, body = self.prepared_payload(temp)
            original = next(row for row in body['excerpts'] if row['case_id'] == self.query_id)
            for mode in ('stale', 'foreign_case', 'foreign_source', 'no_raw'):
                clipped = deepcopy(body)
                if mode == 'stale': clipped['current_payload_source_refs'] = []
                if mode == 'no_raw': clipped['excerpts'] = []
                if mode.startswith('foreign'):
                    row = deepcopy(original)
                    row['case_id' if mode == 'foreign_case' else 'source_hash'] = '000099.txt' if mode == 'foreign_case' else 'f' * 64
                    clipped['excerpts'] = [row]
                clipped['m6']['a_paragraphs'] = agent._visible_paragraphs(clipped)
                self.assertEqual(clipped['m6']['a_paragraphs'], {}, mode)
                self.assertNotIn('search_cases_by_issue', {row['name'] for row in catalog(clipped)[0]})

    def test_tampered_hash_span_coverage_and_current_ref_rejected(self):
        with TemporaryDirectory() as temp:
            agent, body = self.prepared_payload(temp)
            start, end = self.paragraph_spans[1]
            start += len('Deuxième règle: '.encode('utf-8'))
            clipped = self.clipped_body(agent, body, [(start, end)])
            handle = next(iter(clipped['m6']['a_paragraphs']))
            for mutation in ('hash', 'span', 'coverage', 'original', 'stale', 'foreign'):
                modified = deepcopy(clipped)
                row = modified['m6']['a_paragraphs'][handle]
                if mutation == 'hash': row['text_sha256'] = '0' * 64
                if mutation == 'span': row['span_bytes'] = [start + 1, end]
                if mutation == 'coverage': row['paragraph_coverage'] = 'full'
                if mutation == 'original': row['paragraph_span_bytes'] = [end, end + 5]
                if mutation == 'stale': modified['current_payload_source_refs'] = []
                if mutation == 'foreign': row['source_hash'] = 'f' * 64
                with self.subTest(mutation=mutation), self.assertRaises(ToolSemanticError):
                    translate(modified, self.search_action(None, handle))

    def test_partial_need_pairs_only_actual_fragment_with_new_b(self):
        with TemporaryDirectory() as temp:
            agent, body = self.prepared_payload(temp)
            start, end = self.paragraph_spans[1]
            clipped = self.clipped_body(agent, body, [(0, end - 3)])
            handle = f'p-second@{start}:{end - 3}'
            need = translate(clipped, self.search_action(None, handle))['args']['_m6_need']
            # The source ref may still identify a wider excerpt; pairing must slice
            # to the exact search fragment, preserving neither unseen prefix nor tail.
            clipped_source = clipped['excerpts'][0]
            b_raw = b'The notice requirement applies.'
            b = SourceExcerpt('000002.txt', sha256(b_raw).hexdigest(), (0, len(b_raw)),
                              b_raw.decode(), sha256(b_raw).hexdigest()).to_record()
            state = RunState()
            state.full_query_considered = True
            state.initial_result = {'observation': {}}
            state.pending = [b['ref']]
            state.catalog = {clipped_source['ref']: clipped_source, b['ref']: b}
            state.delivered = {clipped_source['ref']}
            state.candidates = {'000002.txt': None}
            state.observation = {'case_id': '000002.txt', 'm6_opened_candidate': '000002.txt'}
            event = {'kind': 'action_result', 'action_id': 'fixture-action', 'status': 'success',
                     'result': {'observation': {'m6_source_need': need, 'hits': [{'case_id': '000002.txt'}]},
                                'candidates': ['000002.txt']}}
            started = {'kind': 'action_started', 'action_id': 'fixture-action',
                       'action': {'action': 'search_corpus', 'args': {}}}
            with patch.object(agent, 'events', return_value=[started, event]):
                paired = agent._fit_opened_pair(state, 18000)
            self.assertIsNotNone(paired)
            delivered = json.loads(paired[0])
            raw_a = next(row for row in delivered['excerpts'] if row['case_id'] == self.query_id)
            self.assertEqual(raw_a['span_bytes'], [start, end - 3])
            self.assertEqual(raw_a['text'], self.text.encode('utf-8')[start:end - 3].decode('utf-8'))
            self.assertEqual(delivered['m6']['a_paragraphs'][handle]['paragraph_coverage'], 'partial')
            self.assertIn('assess_case_link', {row['name'] for row in delivered['available_tools']})
            self.assertEqual(VERSION, 'm6-adaptive-purpose-v8')


if __name__ == "__main__":
    unittest.main()
