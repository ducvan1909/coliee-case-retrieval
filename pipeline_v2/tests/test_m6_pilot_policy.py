"""Independent regressions for failure modes seen in the M6 pilot."""
import tempfile
import unittest

from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.agent_harness.adaptive_policy import catalog, translate
from pipeline_v2.m4 import M3Tools
from pipeline_v2.m6 import AdaptiveConfig, AdaptiveHarness
from pipeline_v2.tests.test_m3_source_tools import SourceToolsFixture
from pipeline_v2.tests.test_m4_tools import LexicalFixture
from pipeline_v2.tests.test_m6_adaptive import Tools, Transport, harness


class RecordingTools(Tools):
    def __init__(self):
        super().__init__()
        self.search_calls = []

    def search_corpus(self, args):
        self.search_calls.append(args)
        return super().search_corpus(args)


class PilotPolicyTests(unittest.TestCase):
    def test_issue_schema_uses_length_without_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            body = harness(directory, Transport([])).prepare()['payload']
        tool = next(row for row in body['available_tools'] if row['name'] == 'search_cases_by_issue')
        self.assertEqual(tool['parameters']['properties']['issue'],
                         {'type': 'string', 'minLength': 4, 'maxLength': 160})

    def test_complete_policy_before_any_search_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = harness(directory, Transport(['finish_case_review'])).run()
        self.assertNotEqual(result['stop_reason'], 'complete')
        self.assertIsNone(result['prediction'])

    def test_one_character_issue_is_rejected_before_retrieval(self):
        tools = RecordingTools()
        with tempfile.TemporaryDirectory() as directory:
            agent = harness(directory, Transport([]), tools)
            body = agent.prepare()['payload']
        for issue in ('t', 'é', 'fair'):
            with self.subTest(issue=issue):
                with self.assertRaises(Exception):
                    translate(body, {'action': 'search_cases_by_issue', 'args': {'issue': issue,
                              'a_paragraph_ref': next(iter(body['m6']['a_paragraphs']))}})
        self.assertEqual(tools.search_calls, [])

    def test_executed_reload_pair_is_not_offered_again(self):
        chosen_reload = []

        def first_reload(body):
            ref = next(key for key, refs in body['m6']['reloads'].items() if len(refs) == 2)
            chosen_reload.append(ref)
            return {'action': 'reload_evidence', 'args': {'evidence_ref': ref}}

        def duplicate_reload_guard(body):
            self.assertNotIn(chosen_reload[0], body['m6']['reloads'])
            return {'action': 'finish_case_review', 'args': {'reason': 'no_progress'}}

        with tempfile.TemporaryDirectory() as directory:
            transport = Transport(['search_cases_by_issue', 'read_case_passages',
                                   first_reload, duplicate_reload_guard])
            agent = harness(directory, transport,
                            config=AdaptiveConfig(no_progress_actions=2))
            result = agent.run()
        self.assertEqual(result['stop_reason'], 'no_progress')
        self.assertGreaterEqual(result['usage']['requests'], 3)


class NavigationRetirementTests(SourceToolsFixture):
    def test_executed_query_navigation_binding_is_not_offered_again(self):
        for case in ('000001.txt', '000002.txt'):
            raw = 'A procedural fairness issue appears in this decision.\nA second paragraph supplies context.'
            self.add_case(case, raw, [{'span_bytes': [0, len(raw.encode('utf-8'))]}])
        reader = self.make_session()
        self.addCleanup(reader.close)
        tools = M3Tools(reader, LexicalFixture(), '000001.txt', byte_budget=4096, map_limit=1)
        initial, full = tools.query_start()
        identity = RunIdentity('navigation-retirement', '000001.txt', full.source_hash,
                               'candidates', 'index', 'profile', 'model', 'prompt', 'tools', 'tokenizer')

        class InspectingTransport(Transport):
            def __init__(self):
                super().__init__([])
                self.payloads = []

            def send_structured(self, payload, request_id, schema):
                import json
                body = json.loads(payload)
                self.payloads.append(body)
                if len(self.payloads) == 1:
                    ref = next(iter(body['m6']['query_targets']))
                    self.used_query_ref = ref
                    action = {'action': 'read_query_passages', 'args': {'query_ref': ref}}
                else:
                    action = {'action': 'finish_case_review', 'args': {'reason': 'no_progress'}}
                from pipeline_v2.agent_harness.contracts import ModelReply
                return ModelReply(action, 1, 1, 1)

        transport = InspectingTransport()
        with tempfile.TemporaryDirectory() as directory:
            agent = AdaptiveHarness(directory, identity=identity, budget=Budget(4, 4, 50000, 8000, 512),
                                    m3_tools=tools, transport=transport,
                                    initial_observation=initial, query_excerpt=full)
            agent.run()
        self.assertIn('read_query_passages', [tool['name'] for tool in transport.payloads[0]['available_tools']])
        self.assertNotIn(transport.used_query_ref, transport.payloads[1]['m6']['query_targets'])


if __name__ == '__main__':
    unittest.main()
