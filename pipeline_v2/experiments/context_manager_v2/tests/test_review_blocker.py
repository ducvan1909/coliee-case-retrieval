"""Regression for premature controller stops while results remain unread."""
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator

from pipeline_v2.agent_harness import RunIdentity
from pipeline_v2.agent_harness.selection import select_supported_cases, selector_fingerprint
from pipeline_v2.experiments.context_manager_v2.cli import choose, choose_read
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.tests.test_empty_reopen import ReopenTools, count_tokens
from pipeline_v2.experiments.context_manager_v2.tests.test_source_gate import names, screen
from pipeline_v2.m6 import AdaptiveConfig


def assess(prepared, relation):
    return choose(prepared, 'assess_case_link', case_relation=relation, passage_location='bounded',
                  reason='The model reviewed the displayed source passages.')


def read_candidate(prepared, case_id):
    card = next(row for row in prepared['payload']['m6']['cm_page']['candidates']
                if row['case_id'] == case_id)
    return choose_read(prepared, card, 'procedural fairness')


class ReviewBlockerTests(unittest.TestCase):
    def make_engine_after_first_candidate(self, directory):
        tools = ReopenTools('empty')
        identity = RunIdentity('review-blocker', 'A', tools.a.source_hash, 'corpus', 'index',
                               'profile', 'model', 'prompt', 'tools', 'counter')
        raw = {row.case_id: row.text.encode('utf-8') for row in (tools.a, tools.b, tools.c)}
        engine = Engine(directory, identity=identity, tools=tools, config=AdaptiveConfig(channel='case_bm25'),
                        count_tokens=count_tokens, raw_reader=raw.__getitem__, gate_enabled=True,
                        selector=select_supported_cases, selector_fingerprint=selector_fingerprint())
        engine.step(lambda prepared: screen(prepared, tools.a.text))
        engine.step(lambda prepared: choose(prepared, 'search_cases_by_issue', issue='procedural fairness',
                                            source_proposition='The query considers procedural fairness.'))
        engine.step(lambda prepared: read_candidate(prepared, 'B'))
        engine.step(lambda prepared: assess(prepared, 'supported'))
        return engine

    def test_report_after_assessment_preserves_route_to_unreviewed_candidate(self):
        with TemporaryDirectory() as directory:
            engine = self.make_engine_after_first_candidate(directory)
            prepared = engine.prepare(admit=False)
            self.assertNotIn('finish_case_review', names(prepared))
            self.assertNotIn('finish_case_review', [tool['name'] for tool in prepared['payload']['available_tools']])
            validator = Draft202012Validator(prepared['manifest']['schema'])
            self.assertFalse(validator.is_valid({'action': 'finish_case_review', 'args': {'reason': 'failure'}}))
            reason = 'I do not see how to open the next candidate case.'
            report = choose(prepared, 'report_review_blocker', kind='cannot_find_next_step', reason=reason)
            self.assertTrue(validator.is_valid(report))
            engine.step(report)
            self.assertIsNone(engine.state().final)

            after = engine.prepare(admit=False)
            feedback = after['payload']['last_action_feedback']
            blocker = feedback['review_blocker']
            self.assertEqual((blocker['kind'], blocker['reason']), ('cannot_find_next_step', reason))
            self.assertFalse(Draft202012Validator(after['manifest']['schema']).is_valid(report))
            navigation = next(option for option in feedback['navigation_options'] if option['view'] == 'results')
            engine.step({'action': navigation['tool'], 'args': navigation['args']})
            engine.step(lambda prepared: read_candidate(prepared, 'C'))
            engine.step(lambda prepared: assess(prepared, 'similarity_only'))

            done = engine.prepare(admit=False)
            self.assertIn('finish_case_review', names(done))
            finish = choose(done, 'finish_case_review', reason='complete_policy')
            self.assertTrue(Draft202012Validator(done['manifest']['schema']).is_valid(finish))
            engine.step(finish)
            self.assertEqual(engine.state().final['prediction'], ['B'])

    def test_host_failure_exposes_partial_supported_cases_without_final_prediction(self):
        with TemporaryDirectory() as directory:
            engine = self.make_engine_after_first_candidate(directory)
            engine.stop('test_source_unavailable', status='failure')
            review = engine.inspect()
            self.assertEqual(review['state']['stop_reason'], 'failure')
            self.assertIsNone(review['state']['prediction'])
            self.assertEqual(review['partial_supported_cases'], ['B'])

    def test_missing_identity_suggests_an_offered_header_read(self):
        with TemporaryDirectory() as directory:
            engine = self.make_engine_after_first_candidate(directory)
            accepted_before = dict(engine.state().active_assessments)
            engine.step(lambda prepared: choose(prepared, 'report_review_blocker', kind='missing_identity',
                                                reason='I still need the opening text of the candidate.'))
            payload = engine.prepare(admit=False)['payload']
            suggestions = payload['last_action_feedback']['review_blocker']['suggested_tools']
            self.assertIn('open_candidate_header', suggestions)
            self.assertLessEqual(set(suggestions), {tool['name'] for tool in payload['available_tools']})
            self.assertEqual(engine.state().active_assessments, accepted_before)
            self.assertIsNone(engine.state().final)


if __name__ == '__main__':
    unittest.main()
