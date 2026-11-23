"""CM4 orchestration with injected provider responses; never calls Modal."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.agent_harness import RunIdentity
from pipeline_v2.agent_harness.contracts import ModelReply, TransportError, fingerprint
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.experiments.context_manager_v2.live import LoopGuard, load_settings, run_loop, PASSAGE_INSTRUCTIONS
from pipeline_v2.tests.test_m6_adaptive import Tools


class Trace:
    def __init__(self):
        self.rows = []

    def emit(self, name, **fields):
        self.rows.append((name, fields))

    @contextmanager
    def stage(self, name, **fields):
        self.emit(name, **fields)
        yield


def count(body):
    return len(body) // 6 + 100


class Transport:
    def __init__(self, select):
        self.select, self.calls, self.receipts = select, [], []
        self.last_call_id = None

    def send_structured(self, body, request_id, schema):
        self.calls.append((body, request_id, deepcopy(schema)))
        self.last_call_id = 'fake-call-' + str(len(self.calls))
        self.receipts.append({'request_id': request_id, 'call_id': self.last_call_id, 'submission_attempted': True})
        reply = self.select(json.loads(body), request_id)
        if isinstance(reply, BaseException):
            raise reply
        return ModelReply(action=json.dumps(reply), input_tokens=count(body), output_tokens=19, latency_ms=23.5)


class LiveTests(unittest.TestCase):
    def test_guard_counts_new_reviewed_bytes_within_the_same_paragraph(self):
        state = RunState()
        guard = LoopGuard()
        base = {'source_hash': 'source-a', 'paragraph_handle': 'p000001',
                'decision': 'no_search_needed', 'status': 'screened'}
        decisions = {'bad': {**base, 'status': 'unresolved', 'visible_span_bytes': [0, 927]}}
        context = {'mode': 'query_leaf', 'source_gate': decisions}
        self.assertEqual(guard.observe(state, context)['screened_query_bytes'], 0)
        decisions['s1'] = {**base, 'visible_span_bytes': [0, 239]}
        self.assertEqual(guard.observe(state, context)['screened_query_bytes'], 239)
        self.assertEqual(guard.observe(state, context)['no_progress'], 1)
        decisions['s2'] = {**base, 'visible_span_bytes': [239, 285]}
        outcome = guard.observe(state, context)
        self.assertEqual(outcome['screened_query_bytes'], 285)
        self.assertEqual(outcome['no_progress'], 0)
        decisions['duplicate'] = {**base, 'visible_span_bytes': [5, 250], 'reason': 'Reworded.'}
        self.assertEqual(guard.observe(state, context)['no_progress'], 1)
        decisions['s2']['status'] = 'unresolved'
        self.assertEqual(guard.observe(state, context)['no_progress'], 2)
        decisions['s2']['status'] = 'screened'
        self.assertEqual(guard.observe(state, context)['no_progress'], 3)

    def test_passage_prompt_requires_one_case_conclusion_and_honest_context_reading(self):
        self.assertIn('conclude_candidate exactly once', PASSAGE_INSTRUCTIONS)
        self.assertIn('cannot be repeated, revised, or retracted', PASSAGE_INSTRUCTIONS)
        self.assertIn('Leaving a case does not finalize it', PASSAGE_INSTRUCTIONS)
        self.assertIn('revisit_case_passage', PASSAGE_INSTRUCTIONS)
        self.assertIn('does not semantically identify the speaker', PASSAGE_INSTRUCTIONS)
        self.assertNotIn('Return only passage assessments', PASSAGE_INSTRUCTIONS)
        self.assertNotIn('Survey every results page', PASSAGE_INSTRUCTIONS)

    def test_conclusion_wording_and_repeated_search_feedback_are_not_new_progress(self):
        state = RunState()
        guard = LoopGuard(cycle_limit=3)
        context = {'mode': 'assessment', 'candidate_id': 'B', 'stage': 'reading'}
        guard.observe(state, context)
        context['candidate_conclusions'] = {'q1': {'B': {'decision': 'not_select', 'reason': 'Insufficient evidence'}}}
        self.assertEqual(guard.observe(state, context)['no_progress'], 0)
        context['candidate_conclusions']['q1']['B']['reason'] = 'Different wording'
        context['passage_session'] = {'search_feedback': {'status': 'already_read', 'focus': 'new words'}}
        self.assertEqual(guard.observe(state, context)['no_progress'], 1)
        context['passage_session']['search_feedback']['focus'] = 'other words'
        self.assertTrue(guard.observe(state, context)['stop'])

    def test_default_settings_use_fifty_search_results_but_explicit_settings_are_preserved(self):
        default = load_settings()
        self.assertEqual(default['adaptive_config']['search_limit'], 50)
        self.assertEqual(default['budget']['max_output_tokens'], 1024)

        configured = json.loads(load_settings.__globals__['DEFAULT_SETTINGS'].read_bytes())
        configured['adaptive_config']['search_limit'] = 7
        with TemporaryDirectory() as directory:
            settings_path = Path(directory) / 'settings.json'
            settings_path.write_text(json.dumps(configured), encoding='utf-8')
            explicit = load_settings(settings_path)

        self.assertEqual(explicit['adaptive_config']['search_limit'], 7)

    def test_revising_annotations_on_same_evidence_does_not_reset_guard(self):
        state = RunState()
        context = {'mode': 'assessment', 'stage': 'assessed', 'candidate_id': 'B'}
        guard = LoopGuard(cycle_limit=3)
        state.catalog['a'] = {'case_id': 'A', 'source_hash': 'a', 'span_bytes': [0, 10], 'text': 'Query rule'}
        state.catalog['b'] = {'case_id': 'B', 'source_hash': 'b', 'span_bytes': [0, 10], 'text': 'Source law'}
        row = {'candidate_id': 'B', 'a_context_refs': ['a'], 'b_passage_refs': ['b'], 'status': 'accepted',
               'case_relation': 'supported', 'passage_location': 'pinpoint', 'speaker': {'role': 'unknown'}}
        state.assessments['first'] = row
        self.assertEqual(guard.observe(state, context)['cycles'], 1)
        state.assessments['second'] = {**row, 'passage_location': 'bounded'}
        second = guard.observe(state, context)
        self.assertEqual(second['cycles'], 2)
        self.assertTrue(second['warning'])
        state.assessments['third'] = {**row, 'speaker': {'role': 'court'}, 'case_relation': 'unknown'}
        self.assertTrue(guard.observe(state, context)['stop'])

    def test_fresh_fetched_raw_before_delivery_resets_cycle_but_duplicate_bytes_do_not(self):
        state = RunState()
        context = {'mode': 'assessment', 'stage': 'missing_evidence', 'candidate_id': 'B'}
        guard = LoopGuard(cycle_limit=3)
        old = {'case_id': 'B', 'source_hash': 'hash', 'span_bytes': [0, 10], 'text': 'Source law'}
        fresh = {**old, 'span_bytes': [10, 20]}
        state.catalog['old'] = old
        state.delivered.add('old')
        self.assertEqual(guard.observe(state, context)['cycles'], 1)
        state.catalog['separator'] = {**old, 'span_bytes': [20, 22], 'text': '\r\n'}
        self.assertEqual(guard.observe(state, context)['cycles'], 2)
        state.catalog['fresh'] = fresh
        self.assertFalse(guard.observe(state, context)['stop'])
        self.assertEqual(state.delivered, {'old'})
        state.catalog['same-bytes-different-ref'] = dict(fresh)
        self.assertEqual(guard.observe(state, context)['cycles'], 2)
        self.assertTrue(guard.observe(state, context)['stop'])

    def engine(self, directory):
        tools = Tools()
        identity = RunIdentity('live-fixture', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
        return Engine(Path(directory) / 'session', identity=identity, tools=tools, count_tokens=count,
            raw_reader=lambda case: {'A': tools.a, 'B': tools.b}[case].text.encode(),
            execution_mode='live', run_binding={'fixture': 'no provider'})

    def test_preview_has_no_admission_and_provider_schema_telemetry_are_exact(self):
        with TemporaryDirectory() as d:
            e = self.engine(d)
            preview = e.prepare(admit=False)
            self.assertEqual(preview['status'], 'ready')
            self.assertFalse(e.state().requests)
            t = Transport(lambda body, _: {'action': 'finish_case_review', 'args': {'reason': 'failure'}})
            run_loop(e, t, Trace())
            self.assertEqual(len(t.calls), 1)
            admission = next(x for x in e.events() if x['kind'] == 'request_admitted')
            self.assertEqual(admission['output_token_cap'], 1024)
            self.assertEqual(json.loads(t.calls[0][0])['max_output_tokens'], 1024)
            manifest = json.loads((e.directory / admission['cm_manifest_path']).read_bytes())
            self.assertEqual(fingerprint(t.calls[0][2]), manifest['schema_sha256'])
            self.assertEqual(t.calls[0][2], preview['manifest']['schema'])
            self.assertNotIn('show_context_page', {x['properties']['action']['const'] for x in t.calls[0][2]['anyOf']})
            receipt = next(x for x in e.events() if x['kind'] == 'request_result')
            self.assertFalse(admission['cm_scripted_offline'])
            self.assertEqual(receipt['output_tokens'], 19)
            self.assertEqual(receipt['provider_latency_ms'], 23.5)
            self.assertIsNotNone(receipt['transport_elapsed_ms'])
            self.assertEqual(receipt['transport_metadata']['call_id'], 'fake-call-1')

    def test_malformed_output_preserves_provider_usage_and_never_executes(self):
        with TemporaryDirectory() as d:
            e = self.engine(d)
            t = Transport(lambda *_: {'action': 'invented_tool', 'args': {}})
            run_loop(e, t, Trace())
            receipt = next(x for x in e.events() if x['kind'] == 'request_result')
            self.assertEqual(receipt['status'], 'malformed')
            self.assertEqual(receipt['output_tokens'], 19)
            self.assertFalse(any(x['kind'] == 'action_started' for x in e.events()))

    def test_unknown_transport_is_durable_and_no_resend(self):
        with TemporaryDirectory() as d:
            e = self.engine(d)
            t = Transport(lambda *_: TransportError('uncertain', unknown=True, input_tokens=12))
            run_loop(e, t, Trace())
            self.assertEqual(len(t.calls), 1)
            receipt = next(x for x in e.events() if x['kind'] == 'request_result')
            self.assertEqual(receipt['status'], 'unknown')
            self.assertEqual(receipt['input_tokens'], 12)
            run_loop(self.engine(d), t, Trace())
            self.assertEqual(len(t.calls), 1)

    def test_crash_after_admission_never_calls_provider_on_resume(self):
        with TemporaryDirectory() as d:
            e = self.engine(d)
            e.prepare()
            t = Transport(lambda *_: self.fail('Must not resend'))
            run_loop(self.engine(d), t, Trace())
            self.assertFalse(t.calls)
            self.assertEqual(e.state().last_receipt['status'], 'unknown')

    def test_stop_before_request_and_after_response_before_tool(self):
        for during_response in (False, True):
            with self.subTest(during_response=during_response), TemporaryDirectory() as d:
                e = self.engine(d)
                def select(body, _):
                    (Path(d) / 'STOP').write_text('stop')
                    return {'action': 'finish_case_review', 'args': {'reason': 'failure'}}
                t = Transport(select)
                if not during_response:
                    (Path(d) / 'STOP').write_text('stop')
                run_loop(e, t, Trace())
                self.assertEqual(len(t.calls), int(during_response))
                self.assertFalse(any(x['kind'] == 'action_started' for x in e.events()))
                if during_response:
                    self.assertEqual(e.state().last_receipt['output_tokens'], 19)

    def test_navigation_cycle_stops_despite_changing_handles_and_revisions(self):
        with TemporaryDirectory() as d:
            e = self.engine(d)
            e.step(lambda p: choose(p, 'search_cases_by_issue', issue='procedural fairness',
                                    source_proposition='The query needs evidence for a fairness rule.'))
            def select(body, _):
                mode = body['m6']['cm_context']['mode']
                target = 'pool' if mode != 'pool' else 'query'
                return {'action': 'show_context_page', 'args': {'page_ref': body['m6']['cm_page']['controls'][target]}}
            t = Transport(select)
            run_loop(e, t, Trace(), no_progress_limit=6, cycle_limit=3, loop_guard_mode='stop')
            self.assertLessEqual(len(t.calls), 8)
            self.assertIsNotNone(e.state().final)
            self.assertFalse(e.state().in_flight)
            warnings = [json.loads(body)['last_action_feedback'].get('progress_warning') for body, _, _ in t.calls]
            self.assertTrue(any(warning and warning['cycles'] == 2 for warning in warnings))

    def test_returned_action_after_crash_executes_without_second_provider_call(self):
        with TemporaryDirectory() as d:
            e = self.engine(d)
            p = e.prepare()
            e.reply(p['request_id'], {'action': 'finish_case_review', 'args': {'reason': 'failure'}},
                    telemetry=ModelReply({}, p['input_tokens'], 5, 1))
            # A successful response exists; the action has not started.
            t = Transport(lambda *_: self.fail('Do not resend the completed controller request'))
            run_loop(self.engine(d), t, Trace())
            self.assertFalse(t.calls)
            self.assertIsNotNone(e.state().final)
            self.assertEqual(len([x for x in e.events() if x['kind'] == 'action_started']), 1)

    def test_provider_usage_exceeding_admission_is_terminal_without_action(self):
        class BadTelemetry(Transport):
            def send_structured(self, body, request_id, schema):
                reply = super().send_structured(body, request_id, schema)
                return ModelReply(reply.action, 1000000, reply.output_tokens, reply.latency_ms)
        with TemporaryDirectory() as d:
            e = self.engine(d)
            t = BadTelemetry(lambda *_: {'action': 'finish_case_review', 'args': {'reason': 'failure'}})
            run_loop(e, t, Trace())
            self.assertEqual(e.state().last_receipt['telemetry_error'], 'provider_usage_exceeded_admission')
            self.assertIsNotNone(e.state().final)
            self.assertFalse(any(x['kind'] == 'action_started' for x in e.events()))

    def test_stop_after_admission_closes_request_without_submission(self):
        with TemporaryDirectory() as d:
            class StopAfterCompile(Trace):
                @contextmanager
                def stage(self, name, **fields):
                    yield
                    if name == 'compile_context':
                        (Path(d) / 'STOP').write_text('stop')
            e = self.engine(d)
            t = Transport(lambda *_: self.fail('Must not submit after STOP'))
            run_loop(e, t, StopAfterCompile())
            self.assertFalse(t.calls)
            self.assertFalse(e.state().in_flight)
            self.assertFalse(e.state().last_receipt['transport_metadata']['submission_attempted'])
            self.assertEqual(e.state().final['stop_detail'], 'operator_stop_file')
            self.assertEqual(e.state().final['stop_reason'], 'no_progress')

    def test_bare_action_without_modelreply_contract_never_executes(self):
        class BareTransport(Transport):
            def send_structured(self, body, request_id, schema):
                super().send_structured(body, request_id, schema)
                return {'action': 'finish_case_review', 'args': {'reason': 'failure'}}
        with TemporaryDirectory() as d:
            e = self.engine(d)
            t = BareTransport(lambda *_: {'action': 'finish_case_review', 'args': {'reason': 'failure'}})
            run_loop(e, t, Trace())
            self.assertEqual(e.state().last_receipt['status'], 'malformed')
            self.assertFalse(any(x['kind'] == 'action_started' for x in e.events()))

    def test_malformed_unicode_and_duplicate_json_keep_usage_and_stop(self):
        outputs = ['\ud800', '{"action":"finish_case_review","action":"show_context_page","args":{}}',
                   '{"action":"finish_case_review","args":{"reason":"\ud800"}}']
        for raw in outputs:
            with self.subTest(raw=repr(raw)), TemporaryDirectory() as d:
                e = self.engine(d)
                p = e.prepare()
                e.reply(p['request_id'], raw, telemetry=ModelReply(raw, 10, 3, 4))
                receipt = e.state().last_receipt
                self.assertEqual(receipt['status'], 'malformed')
                self.assertEqual((receipt['input_tokens'], receipt['output_tokens'], receipt['provider_latency_ms']), (10, 3, 4))
                self.assertFalse(e.state().in_flight)
                self.assertIsNotNone(e.state().final)
                self.assertFalse(any(x['kind'] == 'action_started' for x in e.events()))


if __name__ == '__main__':
    unittest.main()
