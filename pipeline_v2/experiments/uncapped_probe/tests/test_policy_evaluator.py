"""Offline RT4/evaluation contracts; source fixtures, never provider calls."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jsonschema import ValidationError
from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.adaptive_policy import catalog as production_catalog
from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.experiments.uncapped_probe import evaluator, policy
from pipeline_v2.tests.test_m6_adaptive import Tools, Transport


class PolicyEvaluatorTests(unittest.TestCase):
    def make_harness(self, directory, steps=()):
        tools = Tools()
        identity = RunIdentity('probe', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
        return policy.AdaptiveHarness(directory, identity=identity,
            budget=Budget(20, 20, 1000000, 18000, 512), m3_tools=tools, transport=Transport(steps))

    def test_debug_field_required_and_never_changes_query_or_production_schema(self):
        with TemporaryDirectory() as directory:
            harness = self.make_harness(directory)
            body = harness.prepare()['payload']
            args = {'a_paragraph_ref': next(iter(body['m6']['a_paragraphs'])),
                    'issue': 'procedural fairness', 'source_proposition': 'Notice is required before the decision.'}
            result = policy.translate(body, {'action': 'search_cases_by_issue', 'args': args})
            self.assertEqual(result['args']['text'], args['issue'])
            self.assertEqual(result['args']['_m6_need']['source_proposition'], args['source_proposition'])
            del args['source_proposition']
            with self.assertRaises(ValidationError):
                policy.translate(body, {'action': 'search_cases_by_issue', 'args': args})
            tools = production_catalog(body)[0]
            search = next(tool for tool in tools if tool['name'] == 'search_cases_by_issue')
            self.assertNotIn('source_proposition', search['parameters']['properties'])

    def test_blank_multiline_and_overlong_debug_rejected(self):
        with TemporaryDirectory() as directory:
            body = self.make_harness(directory).prepare()['payload']
            for proposition in ('    ', 'First\nSecond', 'x' * 241):
                action = {'action': 'search_cases_by_issue', 'args': {
                    'issue': 'procedural fairness',
                    'a_paragraph_ref': next(iter(body['m6']['a_paragraphs'])),
                    'source_proposition': proposition}}
                with self.subTest(proposition=proposition[:20]), self.assertRaises((ValidationError, HarnessError)):
                    policy.translate(body, action)

    def test_complete_scripted_loop_preserves_debug_in_ledger(self):
        with TemporaryDirectory() as directory:
            harness = self.make_harness(directory, ['search_cases_by_issue', 'read_case_passages',
                'reload_evidence', 'assess_case_link', 'finish_case_review'])
            result = harness.run()
            self.assertEqual(result['stop_reason'], 'complete')
            events = harness.events()
            search = next(row['action'] for row in events if row['kind'] == 'action_started'
                          and row['action']['action'] == 'search_corpus')
            self.assertIn('source_proposition', search['args']['_m6_need'])
            self.assertEqual(search['args']['text'], 'procedural fairness')

    def test_operator_stop_pending_action_freezes_and_gold_only_read_by_score(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'run'
            harness = self.make_harness(run, ['search_cases_by_issue'])
            with harness.ledger.writer() as db:
                state = RunState(harness.ledger.read(db))
                harness._start(db, state)
                harness._turn(db, state)
                self.assertIsNotNone(state.pending_action)
                harness._stop(db, state, 'no_progress', 'operator_stop_file')
            frozen = evaluator.freeze(run)  # No labels exist yet.
            self.assertIsNotNone(frozen['unexecuted_returned_action'])
            labels = root / evaluator.LABELS
            labels.parent.mkdir(parents=True)
            labels.write_text(json.dumps({'A': ['B', 'C']}), encoding='utf-8')
            report = evaluator.score(root, run, frozen)
            self.assertEqual(report['gold_denominator'], 2)
            self.assertEqual(report['query_denominator'], 1)
            self.assertEqual(report['actual_pool']['recall'], 0)
            self.assertEqual(report['model_calls_this_tool'], 0)
            with (run / 'events.sqlite3').open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaises(HarnessError):
                evaluator.score(root, run, frozen)


if __name__ == '__main__':
    unittest.main()
