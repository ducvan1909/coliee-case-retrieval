"""Offline behavior checks for the disposable runner; never calls inference."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.m6_hybrid import EmbeddingBudget, EmbeddingBudgetExceeded, EmbeddingJournal
from pipeline_v2.tests.test_m6_adaptive import Tools, Transport
from pipeline_v2.experiments.uncapped_probe import runner


ROOT = Path(__file__).resolve().parents[4]
DIRECTORY = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def settings(self, name='settings.json'):
        return json.loads((DIRECTORY / name).read_text(encoding='utf-8'))

    def harness(self, directory, transport, mode='uncapped'):
        tools = Tools()
        identity = RunIdentity('probe', 'A', tools.a.source_hash, 'candidates', 'index',
                               'profile', 'model', 'prompt', 'tools', 'tokenizer')
        agent = runner.ProbeHarness(
            directory, identity=identity,
            budget=Budget(20, 20, 100000, 8500, 512, max_retries=0),
            m3_tools=tools, transport=transport, trace=runner.Trace(directory),
            experiment_mode=mode, experiment_root=ROOT,
            config=AdaptiveConfig(channel='lexical_both'))
        return agent, tools

    def test_uncapped_removes_practical_aggregate_stops_but_keeps_context(self):
        value = self.settings()
        value['budget']['max_requests'] = 1
        result = runner.settings(value)
        self.assertEqual(result['budget']['max_requests'], 2 ** 60)
        self.assertEqual(result['budget']['max_actions'], 2 ** 60)
        self.assertEqual(result['budget']['max_input_tokens'], 2 ** 60)
        self.assertIsNone(result['budget']['max_total_tokens'])
        self.assertEqual(result['budget']['max_payload_tokens'], 8500)
        self.assertEqual(result['budget']['max_output_tokens'], 512)
        self.assertEqual(result['budget']['max_retries'], 0)
        self.assertEqual(result['adaptive_config']['no_progress_actions'], 2 ** 60)
        self.assertEqual(result['embedding_budget']['max_requests'], 2 ** 60)

    def test_rt5_keeps_distinct_controller_embedding_limits(self):
        result = runner.settings(self.settings('rt5_settings.json'))
        self.assertEqual(result['experiment_mode'], 'rt5')
        self.assertEqual(result['budget']['max_requests'], 8)
        self.assertEqual(result['budget']['max_actions'], 8)
        self.assertEqual(result['budget']['max_input_tokens'], 68000)
        self.assertEqual(result['budget']['max_total_tokens'], 72096)
        self.assertEqual(result['embedding_budget'], {'max_requests': 5, 'max_input_tokens': 2240})
        self.assertEqual(result['adaptive_config']['no_progress_actions'], 4)

    def test_other_query_and_changed_context_are_rejected(self):
        value = self.settings()
        value['query_id'] = '095448.txt'
        with self.assertRaises(HarnessError):
            runner.settings(value)
        value = self.settings()
        value['budget']['max_payload_tokens'] = 10000
        with self.assertRaises(HarnessError):
            runner.settings(value)

    def test_trace_accepts_durable_event_kind(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            trace = runner.Trace(temporary)
            trace.emit('ledger_event', kind='run_created')
            row = json.loads((Path(temporary) / 'trace.jsonl').read_text(encoding='utf-8'))
            self.assertEqual((row['event'], row['kind']), ('ledger_event', 'run_created'))

    def test_stop_before_first_request_never_sends(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            transport = Transport([])
            agent, tools = self.harness(Path(temporary), transport)
            (Path(temporary) / 'STOP').touch()
            result = agent.run()
            self.assertEqual(result['stop_detail'], 'operator_stop_file')
            self.assertEqual(result['usage']['requests'], 0)
            self.assertEqual(transport.payloads, [])
            self.assertEqual(tools.reads, [])

    def test_stop_after_response_does_not_execute_pending_action(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            directory = Path(temporary)
            def model_reply(body):
                (directory / 'STOP').touch()
                return {'action': 'search_cases_by_issue', 'args': {
                    'issue': 'procedural fairness', 'source_proposition': 'A fair hearing requires notice.',
                    'a_paragraph_ref': next(iter(body['m6']['a_paragraphs']))}}
            transport = Transport([model_reply])
            agent, tools = self.harness(directory, transport)
            result = agent.run()
            state = RunState(agent.events())
            self.assertEqual(result['stop_detail'], 'operator_stop_file')
            self.assertEqual(result['usage']['requests'], 1)
            self.assertIsNotNone(state.pending_action)
            self.assertIsNone(state.active_action)
            self.assertFalse(any(row['kind'] == 'action_started' for row in agent.events()))

    def test_interrupted_controller_is_unknown_on_recovery_without_resend(self):
        class Interrupted(Transport):
            def send_structured(self, *args):
                raise KeyboardInterrupt()
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            directory = Path(temporary)
            agent, _ = self.harness(directory, Interrupted([]))
            with self.assertRaises(KeyboardInterrupt):
                agent.run()
            self.assertIsNotNone(RunState(agent.events()).in_flight)
            transport = Transport([])
            resumed, _ = self.harness(directory, transport)
            result = resumed.run()
            state = RunState(resumed.events())
            self.assertEqual(result['usage']['requests'], 1)
            self.assertEqual(transport.payloads, [])
            self.assertEqual(state.last_receipt['status'], 'unknown')

    def test_status_does_not_create_missing_run_or_initialize_runtime(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'absent'
            with patch.object(runner, 'runtime', side_effect=AssertionError('must not init runtime')):
                report = runner.status(directory)
            self.assertFalse(directory.exists())
            self.assertEqual(report['candidate_ids'], [])
            self.assertIsNone(report['in_flight'])

    def test_rt5_fifth_embedding_admitted_and_sixth_blocked(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            journal = EmbeddingJournal(directory, directory, EmbeddingBudget(5, 2240))
            for number in range(5):
                journal.start_operation(fingerprint(['action', number]), 'query words', '021095.txt', 3)
                journal.reserve('request-' + str(number), 1)
                journal.context = None
            self.assertEqual(journal.remaining(), {'requests': 0, 'input_tokens': 2235})
            journal.start_operation(fingerprint(['action', 5]), 'query words', '021095.txt', 3)
            with self.assertRaises(EmbeddingBudgetExceeded):
                journal.reserve('request-5', 1)
            self.assertEqual(len([row for row in journal.events() if row['kind'] == 'embedding_admitted']), 5)

    def test_uncapped_executes_more_than_eight_controller_actions_without_no_progress_stop(self):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            def search(number):
                return lambda body: {'action': 'search_cases_by_issue', 'args': {
                    'issue': f'procedural fairness source {number}',
                    'source_proposition': f'Notice is required for source {number}.',
                    'a_paragraph_ref': next(iter(body['m6']['a_paragraphs']))}}
            def reload(body):
                return {'action': 'reload_evidence', 'args': {
                    'evidence_ref': next(iter(body['m6']['reloads']))}}
            steps = []
            for number in range(6):
                steps.append(search(number))
                if number < 5:
                    steps.append(reload)
            steps.append('finish_case_review')
            transport = Transport(steps)
            agent, _ = self.harness(Path(temporary), transport)
            result = agent.run()
            self.assertEqual(result['stop_reason'], 'complete')
            self.assertEqual(result['usage']['requests'], 12)
            self.assertEqual(result['usage']['actions'], 12)
            self.assertEqual(len(transport.payloads), 12)

    def test_uncapped_allows_more_than_five_embedding_reservations(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            caps = runner.settings(self.settings())['embedding_budget']
            journal = EmbeddingJournal(directory, directory, EmbeddingBudget(**caps))
            for number in range(7):
                journal.start_operation(fingerprint(['uncapped', number]), 'query words', '021095.txt', 3)
                journal.reserve('request-' + str(number), 448)
                journal.context = None
            self.assertEqual(len([row for row in journal.events() if row['kind'] == 'embedding_admitted']), 7)
            self.assertEqual(journal.remaining()['requests'], 2 ** 60 - 7)

    def test_embedding_token_cap_blocks_even_when_request_budget_remains(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            journal = EmbeddingJournal(directory, directory, EmbeddingBudget(20, 2240))
            for number in range(5):
                journal.start_operation(fingerprint(['token', number]), 'query words', '021095.txt', 3)
                journal.reserve('request-' + str(number), 448)
                journal.context = None
            self.assertEqual(journal.remaining(), {'requests': 15, 'input_tokens': 0})
            journal.start_operation(fingerprint(['token', 5]), 'query words', '021095.txt', 3)
            with self.assertRaisesRegex(EmbeddingBudgetExceeded, 'input_token_cap'):
                journal.reserve('request-5', 1)


if __name__ == '__main__':
    unittest.main()
