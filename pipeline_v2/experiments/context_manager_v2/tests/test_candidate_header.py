"""Exercise CM4 candidate identity reads and their evidence binding."""
from pipeline_v2.experiments.context_manager_v2.tests.view_helpers import survey_results, conclude_query
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator

from pipeline_v2.agent_harness import RunIdentity, ToolResult
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.tests.test_source_gate import names, screen
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.tests.test_m6_adaptive import Tools, source


class CandidateHeaderTools(Tools):
    def __init__(self, *, body_start=None):
        super().__init__()
        heading = 'Court of Appeal | Example v. Minister | 2012 SCC 12\n'
        prefix = heading.ljust(1023, '.') + 'é\n'
        bridge = 'Context outside the first page.\n' * 8
        body_text = '[35]\nThe Court discusses the procedural fairness standard.\n'
        self.b = source('B', prefix + bridge + body_text)
        start = len((prefix + bridge).encode()) if body_start is None else body_start
        self.body = self.b.slice(start, self.b.span_bytes[1])
        self.raw = {row.case_id: row.text.encode() for row in (self.a, self.b)}
        self.corpus_searches = []

    def search_corpus(self, args):
        self.corpus_searches.append(args)
        return super().search_corpus(args)

    def open_source(self, args):
        self.reads.append(('open', args))
        return ToolResult({'case_id': 'B'}, (self.body,), ('B',))


class CandidateHeaderTests(unittest.TestCase):
    @staticmethod
    def make_engine(directory, tools):
        identity = RunIdentity('candidate-header', 'A', tools.a.source_hash, 'cases', 'index',
                               'profile', 'model', 'prompt', 'tools', 'tokenizer')
        return Engine(directory, identity=identity, tools=tools, config=AdaptiveConfig(channel='case_bm25'),
                      count_tokens=lambda body: len(body) // 6 + 100, raw_reader=tools.raw.__getitem__,
                      gate_enabled=True)

    def open_body(self, engine, tools):
        self.assertNotIn('open_candidate_header', names(engine.prepare(admit=False)))
        engine.step(lambda p: screen(p, tools.a.text))
        engine.step(lambda p: choose(p, 'search_cases_by_issue', issue='procedural fairness',
                                     source_proposition='The issue is the applicable fairness standard.'))
        self.assertNotIn('open_candidate_header', names(engine.prepare(admit=False)))
        survey_results(engine)
        engine.step(lambda p: choose(p, 'open_retrieved_passage'))
        prepared = engine.prepare(admit=False)
        self.assertIn('open_candidate_header', names(prepared))
        self.assertEqual([row['span_bytes'] for row in prepared['payload']['excerpts'] if row['case_id'] == 'B'],
                         [list(tools.body.span_bytes)])
        return prepared

    def test_header_adds_verified_utf8_prefix_to_evidence_without_another_search(self):
        with TemporaryDirectory() as directory:
            tools = CandidateHeaderTools()
            engine = self.make_engine(directory, tools)
            prepared = self.open_body(engine, tools)
            action = choose(prepared, 'open_candidate_header')
            self.assertEqual(action, {'action': 'open_candidate_header', 'args': {}})
            validator = Draft202012Validator(prepared['manifest']['schema'])
            self.assertTrue(validator.is_valid(action))
            self.assertFalse(validator.is_valid({**action, 'args': {'candidate_id': 'someone else'}}))
            query = [row for row in prepared['payload']['excerpts'] if row['case_id'] == 'A']

            engine.step(action)
            reopened = self.make_engine(directory, tools)
            updated = reopened.prepare(admit=False)
            excerpts = updated['payload']['excerpts']
            self.assertEqual([row for row in excerpts if row['case_id'] == 'A'], query)
            candidates = {tuple(row['span_bytes']): row['text'] for row in excerpts if row['case_id'] == 'B'}
            expected = tools.raw['B'][:1023].decode()
            self.assertEqual(candidates[(0, 1023)], expected)
            self.assertEqual(candidates[tools.body.span_bytes], tools.body.text)
            self.assertEqual([kind for kind, _ in tools.reads], ['open'])
            self.assertEqual(len(tools.corpus_searches), 1)
            self.assertNotIn('open_candidate_header', names(updated))

            reopened.step(lambda p: choose(p, 'assess_case_link', case_relation='supported',
                                            passage_location='bounded', reason='The candidate was identified.'))
            assessment, = reopened.state().assessments.values()
            self.assertEqual({tuple(row['span_bytes']) for row in assessment['raw_evidence']['b_passage_refs']},
                             {(0, 1023), tools.body.span_bytes})

    def test_model_can_still_submit_supported_without_opening_header(self):
        with TemporaryDirectory() as directory:
            tools = CandidateHeaderTools()
            engine = self.make_engine(directory, tools)
            self.open_body(engine, tools)
            engine.step(lambda p: choose(p, 'assess_case_link', case_relation='supported',
                                          passage_location='bounded', reason='The model considers the body enough.'))
            assessment, = engine.state().assessments.values()
            self.assertEqual(assessment['case_relation'], 'supported')
            self.assertEqual([tuple(row['span_bytes']) for row in assessment['raw_evidence']['b_passage_refs']],
                             [tools.body.span_bytes])

    def test_header_uses_catalog_bytes_when_part_overlaps_the_body(self):
        with TemporaryDirectory() as directory:
            tools = CandidateHeaderTools(body_start=512)
            engine = self.make_engine(directory, tools)
            self.open_body(engine, tools)
            engine.step(lambda p: choose(p, 'open_candidate_header'))
            opened = engine.events()[-1]['result']['excerpts']
            self.assertEqual([row['span_bytes'] for row in opened], [[0, 512]])
            prepared = engine.prepare(admit=False)
            rows = {tuple(row['span_bytes']): row['text']
                    for row in prepared['payload']['excerpts'] if row['case_id'] == 'B'}
            self.assertEqual(set(rows), {(0, 512), tools.body.span_bytes})
            prefix = rows[(0, 512)].encode() + rows[tools.body.span_bytes].encode()[:511]
            self.assertEqual(prefix, tools.raw['B'][:1023])
            self.assertEqual(rows[tools.body.span_bytes], tools.body.text)


if __name__ == '__main__':
    unittest.main()
