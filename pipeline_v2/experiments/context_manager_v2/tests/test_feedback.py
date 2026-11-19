"""Regressions for the live CM4 repeated-search feedback failure."""
from copy import deepcopy
import json
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator
from pipeline_v2.agent_harness import RunIdentity, ToolResult
from pipeline_v2.agent_harness.contracts import encode
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.cli import choose, quote_for_paragraph
from pipeline_v2.tests.test_m6_adaptive import Tools
from pipeline_v2.m6 import AdaptiveConfig


def count(body):
    return len(body) // 6 + 100


class ManyTools(Tools):
    def __init__(self, size=3):
        super().__init__()
        self.ids = ['B', *[f'fixture-{i}' for i in range(1, size)]] if size else []
        self.search_calls = 0

    def search_corpus(self, args):
        self.search_calls += 1
        return ToolResult({'hits': [{'case_id': case, 'rank': i + 1,
            'open_ref': {'case_id': case, 'source_hash': self.b.source_hash, 'passage_ids': ['fixture']}}
            for i, case in enumerate(self.ids)]}, candidates=tuple(self.ids))


class FeedbackTests(unittest.TestCase):
    def make(self, directory, size=3):
        tools = ManyTools(size)
        identity = RunIdentity('feedback', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
        kwargs = dict(identity=identity, tools=tools, count_tokens=count,
            config=AdaptiveConfig(channel='case_bm25'),
            raw_reader=lambda case: {'A': tools.a, 'B': tools.b}[case].text.encode())
        return Engine(directory, **kwargs), tools, kwargs

    def search(self, p):
        return choose(p, 'search_cases_by_issue', issue='procedural fairness',
                      source_proposition='The notice requirement needs a source.')

    def test_success_exposes_ordered_results_feedback_and_gates_new_search(self):
        with TemporaryDirectory() as d:
            e, tools, _ = self.make(d)
            e.step(self.search)
            p = e.prepare(admit=False)
            payload = json.loads(encode(p['payload']))  # Test wire form after sorted-key serialization.
            feedback = payload['last_action_feedback']
            self.assertEqual(feedback['last_action']['status'], 'success')
            self.assertTrue(feedback['last_action']['search_executed'])
            self.assertEqual(feedback['last_action']['hit_count'], 3)
            self.assertEqual([x['case_id'] for x in payload['m6']['cm_page']['candidates']], tools.ids)
            self.assertEqual([x['original_rank'] for x in payload['m6']['cm_page']['candidates']], [1, 2, 3])
            self.assertTrue(all(x['read_allowed'] for x in payload['m6']['cm_page']['candidates']))
            names = [x['name'] for x in payload['available_tools']]
            self.assertIn('read_case_passages', names)
            self.assertIn('record_missing_evidence', names)
            self.assertNotIn('search_cases_by_issue', names)
            self.assertEqual(feedback['next_options'], names)
            repeated_search = {'action': 'search_cases_by_issue', 'args': {'issue': 'procedural fairness',
                'anchor_quote': quote_for_paragraph(payload),
                'source_proposition': 'The notice requirement needs a source.'}}
            self.assertFalse(Draft202012Validator(p['manifest']['schema']).is_valid(repeated_search))
            def read_b(p):
                ref = next(k for k, v in p['payload']['m6']['candidates'].items() if v['case_id'] == 'B')
                return choose(p, 'read_case_passages', candidate_ref=ref, focus='procedural fairness')
            e.step(read_b)
            self.assertEqual(e.context()['candidate_id'], 'B')
            self.assertEqual(e.context()['stage'], 'reading')

    def test_explicit_missing_releases_results_boundary_and_duplicate_preserves_focus(self):
        with TemporaryDirectory() as d:
            e, tools, kwargs = self.make(d, 1)
            e.step(self.search)
            e.step(lambda p: choose(p, 'record_missing_evidence', reason='Retrieved leads need different source context.'))
            before = deepcopy(e.context())
            calls = tools.search_calls
            e.step(self.search)
            self.assertEqual(tools.search_calls, calls)
            after = e.context()
            for key in ('need_id', 'candidate_id', 'stage', 'mode', 'offset'):
                self.assertEqual(after[key], before[key])
            self.assertNotEqual(after['stage'], 'no_hit')
            reopened = Engine(d, **kwargs)
            p = reopened.prepare(admit=False)
            feedback = p['payload']['last_action_feedback']
            self.assertEqual(feedback['last_action']['status'], 'duplicate')
            self.assertFalse(feedback['last_action']['search_executed'])
            self.assertIsNone(feedback['last_action']['hit_count'])
            self.assertEqual(feedback['last_successful_search']['hit_count'], 1)
            self.assertEqual(feedback['missing_reason'], before['missing_reason'])
            self.assertEqual(len(p['payload']['m6']['candidates']), 1)

    def test_real_empty_search_is_no_hit_and_allows_search_again(self):
        with TemporaryDirectory() as d:
            e, _, _ = self.make(d, 0)
            e.step(self.search)
            self.assertEqual(e.context()['stage'], 'no_hit')
            p = e.prepare(admit=False)
            self.assertIn('search_cases_by_issue', [x['name'] for x in p['payload']['available_tools']])
            feedback = p['payload']['last_action_feedback']
            self.assertTrue(feedback['last_action']['search_executed'])
            self.assertEqual(feedback['last_action']['hit_count'], 0)

    def test_feedback_and_ordered_page_stay_bounded_for_large_pool(self):
        with TemporaryDirectory() as d:
            e, _, _ = self.make(d, 10000)
            e.step(self.search)
            p = e.prepare(admit=False)
            self.assertLessEqual(len(p['payload']['m6']['cm_page']['candidates']), 5)
            summary = p['payload']['last_action_feedback']['last_successful_search']
            self.assertEqual(summary['hit_count'], 10000)
            self.assertEqual(len(summary['first_results_native_order']), 5)
            self.assertEqual(summary['results_omitted'], 9995)
            self.assertNotIn('excerpts', p['payload']['last_action_feedback'])


if __name__ == '__main__':
    unittest.main()
