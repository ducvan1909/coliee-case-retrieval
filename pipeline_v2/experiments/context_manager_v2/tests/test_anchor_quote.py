"""CM4 anchor_quote regressions. All retrieval uses local deterministic fixtures."""
import re
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.agent_harness import ToolResult
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.tests import test_engine
from pipeline_v2.tests.test_m6_adaptive import Tools, source


ISSUE = 'breach of procedural fairness'
PROPOSITION = 'The Board misled the applicants about the Convention ground.'
ANCHOR = 'the Board breached procedural fairness in misleading the applicants'
UNIQUE_ANCHOR = 'The respondent states that ' + ANCHOR


class AnchorTools(Tools):
    def __init__(self, text):
        super().__init__()
        self.a = source('A', text)
        self.b = source('B', 'Candidate filler evidence. ' * 5000)
        raw = text.encode('utf-8')
        markers = list(re.finditer(rb'\[\d+\]', raw))
        handles = {14: 'p000021', 16: 'p000024', 17: 'p000025'}
        self.query_paragraphs = tuple(
            {'handle': handles[int(marker.group()[1:-1])], 'span_bytes': (
                marker.start(),
                markers[index + 1].start() if index + 1 < len(markers) else len(raw))}
            for index, marker in enumerate(markers))
        self.search_calls = 0
        self.search_args = []

    def search_corpus(self, args):
        self.search_calls += 1
        self.search_args.append(args)
        return ToolResult({'hits': [{
            'case_id': 'B',
            'rank': 1,
            'open_ref': {'case_id': 'B', 'source_hash': self.b.source_hash,
                         'passage_ids': ['B-1']},
        }]}, candidates=('B',))


def full_query_text(*, repeated=False):
    duplicate = f' The record restates: {ANCHOR}.' if repeated else ''
    second = (f'[16] {"procedural history without the material proposition. " * 25}'
              f'{UNIQUE_ANCHOR}.{duplicate} {"background facts not needed for this issue. " * 80}\r\n'
              'The Board had already promised an opportunity to respond.')
    return ('[14] State protection, generalized risk, nexus to a Convention ground, '
            'and credibility are reviewable on a standard of reasonableness. Évidence remains tied to the record.\r\n'
            + second)


class AnchorQuoteTests(unittest.TestCase):
    def make_engine(self, directory, *, repeated=False, text=None):
        tools = AnchorTools(text if text is not None else full_query_text(repeated=repeated))
        engine, _ = test_engine.EngineTests().make(directory, tools)
        return engine, tools

    @staticmethod
    def search_args(prepared, *, anchor_quote):
        branch = next(branch for branch in prepared['manifest']['schema']['anyOf']
                      if branch['properties']['action']['const'] == 'search_cases_by_issue')
        schema = branch['properties']['args']['properties']
        required = branch['properties']['args']['required']
        assert 'anchor_quote' in required
        assert 'a_paragraph_ref' not in schema
        return {'issue': ISSUE, 'source_proposition': PROPOSITION,
                'anchor_quote': anchor_quote}

    def test_quote_resolves_the_intended_paragraph_and_survives_assessment_crop(self):
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory)
            prepared = engine.prepare(admit=False)
            quote = self.search_args(prepared, anchor_quote=UNIQUE_ANCHOR)
            expected_paragraph_span = next(row['span_bytes'] for row in
                prepared['payload']['m6']['a_paragraphs'].values()
                if row['paragraph_handle'] == 'p000024')
            searched = engine.step(lambda current: choose(
                current, 'search_cases_by_issue', **quote))

            search_action = next(row['action'] for row in engine.events()
                                 if row['kind'] == 'action_started'
                                 and row['action']['action'] == 'search_corpus')
            need = search_action['args']['_m6_need']
            expected_start = tools.a.text.encode('utf-8').index(UNIQUE_ANCHOR.encode('utf-8'))
            expected_span = [expected_start, expected_start + len(UNIQUE_ANCHOR.encode('utf-8'))]

            # The configured lexical_both channel queries both local indexes.
            self.assertEqual(tools.search_calls, 2)
            self.assertEqual(need['a_anchor']['span_bytes'], expected_span)
            self.assertEqual(need['a_anchor']['text'], UNIQUE_ANCHOR)
            self.assertEqual(need['a_paragraph']['paragraph_handle'], 'p000024')
            self.assertEqual(need['a_paragraph']['span_bytes'],
                             expected_paragraph_span)
            self.assertEqual(searched['status'], 'ready')

            engine.step(lambda current: test_engine.EngineTests().action(current, 'read_case_passages'))
            assessment_payload = engine.prepare(admit=False)['payload']
            query_row = next(row for row in assessment_payload['excerpts']
                             if row['case_id'] == 'A')
            candidate_row = next(row for row in assessment_payload['excerpts']
                                 if row['case_id'] == 'B')
            query_raw = query_row['text'].encode('utf-8')
            query_start = query_row['span_bytes'][0]
            self.assertNotEqual(query_row['span_bytes'], [0, len(tools.a.text.encode('utf-8'))],
                                'assessment payload should contain a cropped A window')
            self.assertLess(len(candidate_row['text']), len(tools.b.text),
                            'large B fixture should be cropped by the payload budget')
            self.assertIn(UNIQUE_ANCHOR.encode('utf-8'), query_raw)
            self.assertLessEqual(query_start, expected_span[0])
            self.assertGreaterEqual(query_row['span_bytes'][1], expected_span[1])

    def test_unmatched_or_ambiguous_quote_stages_the_saved_issue_without_search(self):
        for repeated, bad_quote, expected_status in (
            (False, 'This sentence is absent from the query case.', 'needs_query_text'),
            (True, ANCHOR, 'awaiting_choice'),
        ):
            with self.subTest(status=expected_status), TemporaryDirectory() as directory:
                engine, tools = self.make_engine(directory, repeated=repeated)
                prepared = engine.prepare(admit=False)
                bad = self.search_args(prepared, anchor_quote=bad_quote)
                engine.step(lambda current: choose(
                    current, 'search_cases_by_issue', **bad))

                self.assertEqual(tools.search_calls, 0)
                events = engine.events()
                self.assertIsNone(engine.state().final)
                self.assertFalse(any(row['kind'] == 'action_started'
                                     and row['action'].get('executes_tool')
                                     and row['action']['action'] == 'search_corpus'
                                     for row in events))

                correction = engine.prepare(admit=False)
                resolution = correction['payload']['last_action_feedback']['anchor_resolution']
                self.assertEqual(resolution['status'], expected_status)
                self.assertEqual(resolution['issue'], ISSUE)
                if repeated:
                    ref = resolution['candidates'][0]['anchor_ref']
                    engine.step(lambda current: choose(current, 'choose_query_anchor', anchor_ref=ref))
                    self.assertGreater(tools.search_calls, 0)


if __name__ == '__main__':
    unittest.main()
