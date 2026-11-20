"""Local CM4 query policy acceptance; no providers, gold or historic cache."""
from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest
from pipeline_v2.agent_harness import RunIdentity, ToolResult
from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2 import query_review, source_gate
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.tests.test_source_gate import screen, names
from pipeline_v2.experiments.context_manager_v2.tests.test_engine import count
from pipeline_v2.tests.test_m6_adaptive import Tools, source


class ManyTools(Tools):
    def __init__(self, size=50):
        super().__init__()
        self.a = source('A', 'A specific fairness rule requires notice.')
        self.query_paragraphs = ({'handle': 'p000001', 'span_bytes': self.a.span_bytes},)
        self.raw_cases = {f'B{i:02}': source(f'B{i:02}', f'Candidate {i} discusses the notice rule.') for i in range(size)}
        self.searches = 0
    def search_corpus(self, args):
        self.searches += 1
        hits = [{'case_id': case, 'rank': i + 1, 'preview': row.text,
                 'open_ref': {'case_id': case, 'source_hash': row.source_hash, 'passage_ids': [case + '-1']}}
                for i, (case, row) in enumerate(self.raw_cases.items())]
        return ToolResult({'hits': hits}, candidates=tuple(self.raw_cases))
    def verify_source(self, case, digest):
        row = self.a if case == 'A' else self.raw_cases[case]
        return row.source_hash == digest
    def open_source(self, args):
        case = args['case_id']
        self.reads.append(case)
        return ToolResult({}, (self.raw_cases[case],), (case,))


def make(directory, size=50):
    tools = ManyTools(size)
    identity = RunIdentity('query-review', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
    engine = Engine(directory, identity=identity, tools=tools, count_tokens=count,
                    raw_reader=lambda case: (tools.a if case == 'A' else tools.raw_cases[case]).text.encode(),
                    config=AdaptiveConfig(search_limit=50), gate_enabled=True)
    return engine, tools


def start(engine):
    engine.step(lambda p: choose(p, 'assess_source_need', decision='search_needed',
        proposition_ref=next(iter(p['payload']['m6']['source_gate_segments'])), attribution='court',
        reason_code='legal_proposition', reason='The specific legal rule needs a source.', context_complete=True))
    engine.step(lambda p: choose(p, 'search_cases_by_issue', issue='specific notice fairness rule',
                                 source_proposition='The notice rule requires a source.'))


def survey(engine):
    while True:
        p = engine.prepare(admit=False)
        if p['payload']['m6']['query_review']['phase'] == 'reviewing':
            break
        def action(p):
            controls = p['payload']['m6']['cm_page']['controls']
            if 'next_unseen' in controls or 'next' in controls:
                return choose(p, 'show_context_page', page_ref=controls.get('next_unseen', controls.get('next')))
            return choose(p, 'prioritize_query_results',
                          candidate_refs=list(p['payload']['m6']['query_result_choices']),
                          priority='read_next', reason='These are the final survey cards.')
        engine.step(action)


def close(engine):
    while query_review.pending_read_next(query_review.active(engine.events(), engine.context())):
        p = engine.prepare(admit=False)
        if 'read_next' in p['payload']['m6']['cm_page']['controls']:
            engine.step(choose(p, 'show_context_page', page_ref=p['payload']['m6']['cm_page']['controls']['read_next']))
            continue
        def downgrade(p):
            pending = query_review.pending_read_next(query_review.active(engine.events(), engine.context()))
            choices = [ref for ref, case in p['payload']['m6']['query_result_choices'].items() if case in pending]
            return choose(p, 'prioritize_query_results', candidate_refs=choices, priority='maybe',
                          reason='Explicitly postpone these leads for a more specific query.')
        engine.step(downgrade)
    engine.step(lambda p: choose(p, 'conclude_search_query', outcome='partially_resolved',
        reason='A more specific query may be needed.', unresolved_reason='The remaining cards were surveyed but not verified.',
        remaining_source_need='Find a source supporting the exact rule.'))


class QueryReviewAcceptance(unittest.TestCase):
    def test_fifty_hits_must_all_be_delivered_before_raw_or_conclusion(self):
        with TemporaryDirectory() as d:
            engine, tools = make(d)
            start(engine)
            p = engine.prepare(admit=False)
            self.assertNotIn('open_retrieved_passage', names(p))
            self.assertNotIn('conclude_search_query', names(p))
            self.assertEqual(p['payload']['m6']['query_review']['survey_exposed'], 0)
            engine.prepare(admit=False)
            self.assertEqual(query_review.active(engine.events(), engine.context())['survey_exposed'], [])
            survey(engine)
            q = query_review.active(engine.events(), engine.context())
            self.assertEqual(len(q['survey_exposed']), 50)
            self.assertFalse(tools.reads)
            p = engine.prepare(admit=False)
            self.assertNotIn('conclude_search_query', names(p))
            self.assertNotIn('search_cases_by_issue', names(p))
            close(engine)
            report = list(engine.inspect()['search_queries'].values())[0]['conclusion']
            self.assertEqual(len(report['not_read_candidate_ids']), 50)
            self.assertEqual(len(report['unresolved_candidate_ids']), 50)
            self.assertEqual(len(engine.state().active_assessments), 0)

    def test_reopen_same_source_after_conclusion_and_resume_without_retrieval_replay(self):
        with TemporaryDirectory() as d:
            engine, tools = make(d, 1)
            start(engine)
            survey(engine)
            before = deepcopy(query_review.active(engine.events(), engine.context()))
            engine2, _ = make(d, 1)
            self.assertEqual(query_review.active(engine2.events(), engine2.context()), before)
            close(engine2)
            p = engine2.prepare(admit=False)
            # Query raw may require returning to its view first.
            if 'revisit_source_need' not in names(p):
                engine2.step(lambda p: choose(p, 'show_context_page', page_ref=p['payload']['m6']['cm_page']['controls']['query']))
            engine2.step(lambda p: choose(p, 'revisit_source_need', reason='Refine the previous source query.'))
            engine2.step(lambda p: choose(p, 'search_cases_by_issue', issue='different legal notice threshold',
                                         source_proposition='A different formulation needs retrieval.'))
            self.assertEqual(len(engine2.inspect()['search_queries']), 2)
            self.assertEqual(query_review.active(engine2.events(), engine2.context())['survey_exposed'], [])

    def test_receipt_delivery_ignores_unreceived_and_preview_and_preserves_snapshot(self):
        operation = {'kind': 'action_started', 'action_id': 'op', 'action': {'action': 'search_corpus',
                     'args': {'text': 'notice rule', '_m6_need': {'source_need_id': 'need'}}}}
        events = [operation, {'kind': 'action_result', 'action_id': 'op', 'status': 'success',
                  'result': {'observation': {'hits': [{'case_id': 'B'}]}}},
                  {'kind': 'request_admitted', 'request_id': 'r', 'cm_search_query_id': 'op',
                   'cm_survey_candidates': ['B'], 'excerpts': [], 'current_payload_source_refs': []}]
        self.assertEqual(query_review.active(events, {})['survey_exposed'], [])
        events.append({'kind': 'request_result', 'request_id': 'r', 'received_response': False})
        self.assertEqual(query_review.active(events, {})['survey_exposed'], [])
        events.append({'kind': 'request_result', 'request_id': 'r', 'received_response': True})
        self.assertEqual(query_review.active(events, {})['survey_exposed'], ['B'])
        operation['action']['args']['text'] = 'notice rule'
        self.assertEqual(query_review.active(events, {})['candidate_ids'], ['B'])

    def test_partial_span_without_signal_can_search_but_does_not_clear_unread_tail(self):
        full = source('A', 'A specific rule needs a source. ' + 'More context. ' * 30)
        partial = full.slice(0, 30).to_record()
        paragraph = {'source_ref': partial['ref'], 'source_hash': full.source_hash,
                     'paragraph_handle': 'p1', 'span_bytes': [0, 30],
                     'paragraph_span_bytes': list(full.span_bytes), 'paragraph_coverage': 'partial'}
        payload = {'query_id': 'A', 'query_source_hash': full.source_hash,
                   'current_payload_source_refs': [partial['ref']], 'excerpts': [partial],
                   'm6': {'a_paragraphs': {'p': paragraph}}}
        payload['m6']['source_gate_segments'] = source_gate.segments(payload)
        args = {'paragraph_ref': 'p', 'decision': 'search_needed', 'proposition_ref': next(iter(payload['m6']['source_gate_segments'])),
                'attribution': 'court', 'reason_code': 'legal_proposition', 'reason': 'The rule needs a source.',
                'context_complete': True, 'sufficient_for_search': True}
        decision = source_gate.evaluate(payload, args, [{'handle': 'p1', 'span_bytes': full.span_bytes}])
        self.assertEqual(decision['status'], 'approved')
        self.assertIsNone(decision['signal'])
        self.assertFalse(decision['paragraph_complete'])
        context = {}
        source_gate.commit_decision(context, decision)
        self.assertFalse(source_gate.progress(context, [{'handle': 'p1', 'span_bytes': full.span_bytes}])['complete'])
        args.update(decision='no_search_needed')
        negative = source_gate.evaluate(payload, args, [{'handle': 'p1', 'span_bytes': full.span_bytes}])
        source_gate.commit_decision(context, negative)
        self.assertFalse(source_gate.progress(context, [{'handle': 'p1', 'span_bytes': full.span_bytes}])['complete'])

    def test_exact_duplicate_after_conclusion_returns_prior_conclusion(self):
        with TemporaryDirectory() as d:
            engine, tools = make(d, 1)
            start(engine)
            survey(engine)
            close(engine)
            engine.step(lambda p: choose(p, 'revisit_source_need', reason='Check the earlier exact query.'))
            calls = tools.searches
            engine.step(lambda p: choose(p, 'search_cases_by_issue', issue='specific notice fairness rule',
                                         source_proposition='The notice rule requires a source.'))
            feedback = engine.prepare(admit=False)['payload']['last_action_feedback']['last_action']
            self.assertIn('concluded_query_id', feedback)
            self.assertEqual(tools.searches, calls)
            self.assertIsNone(query_review.active(engine.events(), engine.context()))
            self.assertEqual(len(engine.inspect()['search_queries']), 1)

    def test_no_supported_outcome_reads_active_assessment_ids(self):
        from pipeline_v2.agent_harness.ledger import RunState
        state = RunState()
        state.active_assessments[('n', 'B')] = 'assessment'
        state.assessments['assessment'] = {'case_relation': 'supported'}
        q = {'phase': 'reviewing', 'query_id': 'q', 'issue': 'notice rule',
             'candidate_ids': ['B'], 'need_id': 'n', 'raw_exposed': ['B'],
             'survey_exposed': ['B'], 'priorities': {}, 'conclusion': None}
        args = {'outcome': 'no_supported_source_found', 'reason': 'No direct reliance.',
                'unresolved_reason': '', 'remaining_source_need': ''}
        with self.assertRaises(HarnessError):
            query_review.conclude(q, state, args)
        state.assessments['assessment']['case_relation'] = 'unknown'
        self.assertEqual(query_review.progress(q, state)['unresolved'], 1)
        with self.assertRaises(HarnessError):
            query_review.conclude(q, state, {**args, 'outcome': 'resolved'})
        state.assessments['assessment']['case_relation'] = 'similarity_only'
        self.assertEqual(query_review.conclude(q, state, args)['unresolved_candidate_ids'], [])
        self.assertEqual(query_review.progress(q, state)['assessed_by_relation'], {'similarity_only': 1})

    def test_warn_guard_continues_navigation_until_explicit_cap(self):
        from pipeline_v2.experiments.context_manager_v2.tests.test_live import LiveTests, Transport, Trace
        from pipeline_v2.experiments.context_manager_v2.live import run_loop
        with TemporaryDirectory() as d:
            engine = LiveTests().engine(d)
            engine.step(lambda p: choose(p, 'search_cases_by_issue', issue='procedural fairness',
                source_proposition='The query needs evidence for a fairness rule.'))
            def select(body, _):
                mode = body['m6']['cm_context']['mode']
                target = 'pool' if mode != 'pool' else 'query'
                return {'action': 'show_context_page', 'args': {'page_ref': body['m6']['cm_page']['controls'][target]}}
            transport, trace = Transport(select), Trace()
            run_loop(engine, transport, trace, max_turns=11, no_progress_limit=2, cycle_limit=2)
            self.assertGreater(len(transport.calls), 3)
            self.assertEqual(engine.state().final['stop_detail'], 'explicit_turn_cap')
            self.assertTrue(any(name == 'progress_warning' for name, _ in trace.rows))

    def test_token_fitting_counts_only_the_two_actual_cards(self):
        import json
        with TemporaryDirectory() as d:
            engine, _ = make(d, 7)
            start(engine)
            engine.harness.count_tokens = lambda raw: 2000 + 2000 * len(json.loads(raw).get('m6', {}).get('cm_page', {}).get('candidates', []))
            p = engine.prepare(admit=False)
            shown = [card['case_id'] for card in p['payload']['m6']['cm_page']['candidates']]
            self.assertEqual(len(shown), 2)
            self.assertEqual(query_review.active(engine.events(), engine.context())['survey_exposed'], [])
            engine.step(lambda p: choose(p, 'show_context_page', page_ref=p['payload']['m6']['cm_page']['controls'].get('next_unseen', p['payload']['m6']['cm_page']['controls'].get('next'))))
            self.assertEqual(query_review.active(engine.events(), engine.context())['survey_exposed'], shown)
            next_shown = [card['case_id'] for card in engine.prepare(admit=False)['payload']['m6']['cm_page']['candidates']]
            self.assertFalse(set(shown) & set(next_shown))
            self.assertEqual(next_shown, ['B02', 'B03'])

    def test_cross_window_query_region_uses_only_received_contiguous_bytes(self):
        from pipeline_v2.agent_harness.ledger import RunState
        with TemporaryDirectory() as d:
            engine, tools = make(d, 1)
            raw = tools.a
            cut = 18
            parts = [raw.slice(0, cut).to_record(), raw.slice(cut, raw.span_bytes[1]).to_record()]
            state = RunState()
            for i, part in enumerate(parts):
                key = str(i)
                state.requests[key] = {'excerpts': [part], 'current_payload_source_refs': [part['ref']]}
                state.receipts[key] = {'received_response': True}
            target = {'source_hash': raw.source_hash, 'span_bytes': list(raw.span_bytes)}
            combined = engine._combined_query_record(state, target)
            self.assertEqual(combined['text'], raw.text)
            self.assertEqual(tuple(combined['span_bytes']), raw.span_bytes)
            payload = {'query_id': 'A', 'query_source_hash': raw.source_hash,
                'm6': {'a_paragraphs': {'p': {'span_bytes': list(parts[1]['span_bytes']),
                    'paragraph_span_bytes': list(raw.span_bytes), 'paragraph_handle': 'p000001'}}}}
            self.assertTrue(source_gate.span_options(state, payload))
            state.receipts['0']['received_response'] = False
            self.assertFalse(source_gate.span_options(state, payload))
            with self.assertRaises(HarnessError):
                engine._combined_query_record(state, target)
            state.receipts['0']['received_response'] = True
            state.requests['0']['excerpts'] = [raw.slice(0, cut - 1).to_record()]
            self.assertFalse(source_gate.span_options(state, payload))

    def test_active_query_blocks_all_gate_mutations_and_keeps_partial_coverage(self):
        from copy import deepcopy
        from pipeline_v2.experiments.context_manager_v2.engine import GATE_MUTATIONS
        with TemporaryDirectory() as d:
            engine, _ = make(d, 50)
            start(engine)
            saved = deepcopy(engine.context()['source_gate'])
            p = engine.prepare(admit=False)
            self.assertFalse(names(p) & GATE_MUTATIONS)
            self.assertNotIn('query_gate_progress', p['payload']['last_action_feedback'])
            self.assertTrue(p['payload']['last_action_feedback']['query_gate_paused']['screening_paused'])
            for name in GATE_MUTATIONS:
                with self.assertRaises(HarnessError):
                    engine._verify_gate_mutation(name, engine.context())
            self.assertEqual(engine.context()['source_gate'], saved)
            # One approved proposition does not settle a larger paragraph.
            decision = next(iter(saved.values()))
            decision['paragraph_span_bytes'] = [0, 1000]
            self.assertFalse(source_gate.progress({'source_gate': saved}, [{'handle': 'p000001'}])['complete'])

    def test_return_from_query_reading_resumes_first_unseen_and_deduplicates_routes(self):
        with TemporaryDirectory() as d:
            engine, _ = make(d, 50)
            start(engine)
            engine.step(lambda p: choose(p, 'show_context_page', page_ref=p['payload']['m6']['cm_page']['controls']['next_unseen']))
            p = engine.prepare(admit=False)
            self.assertEqual(p['payload']['m6']['cm_page']['survey_position']['offset'], 5)
            controls = p['payload']['m6']['cm_page']['controls']
            self.assertIn('previous', controls)
            self.assertNotIn('results', controls)
            engine.step(lambda p: choose(p, 'show_context_page', page_ref=p['payload']['m6']['cm_page']['controls']['query']))
            p = engine.prepare(admit=False)
            route = p['payload']['m6']['cm_page']['controls']['next_unseen']
            engine.step(choose(p, 'show_context_page', page_ref=route))
            p = engine.prepare(admit=False)
            self.assertEqual(p['payload']['m6']['cm_page']['survey_position']['offset'], 10)
            self.assertEqual(query_review.active(engine.events(), engine.context())['survey_exposed'], [f'B{i:02}' for i in range(10)])

    def test_priority_unchanged_is_not_offered_but_change_is_allowed(self):
        from jsonschema import Draft202012Validator
        from pipeline_v2.experiments.context_manager_v2.tests.view_helpers import canonical_ref, wire_ref
        with TemporaryDirectory() as d:
            engine, _ = make(d, 7)
            start(engine)
            def prioritize(p):
                return choose(p, 'prioritize_query_results', candidate_refs=list(p['payload']['m6']['query_result_choices']),
                              priority='read_next', reason='These cards look relevant.')
            engine.step(prioritize)
            p = engine.prepare(admit=False)
            choices = list(p['payload']['m6']['query_result_choices'])
            action = {'action': 'prioritize_query_results', 'args': {'candidate_refs': choices,
                'priority': 'read_next', 'reason': 'Different reason, same classification.'}}
            self.assertFalse(Draft202012Validator(p['manifest']['schema']).is_valid(action))
            helper_action = choose(p, 'prioritize_query_results', candidate_refs=choices,
                                   priority='maybe', reason='Compare the evidence before selecting.')
            self.assertTrue(Draft202012Validator(p['manifest']['schema']).is_valid(helper_action))
            self.assertEqual(len([tool for tool in p['payload']['available_tools']
                                  if tool['name'] == 'prioritize_query_results']), 1)
            action['args']['priority'] = 'maybe'
            self.assertTrue(Draft202012Validator(p['manifest']['schema']).is_valid(action))
            engine.step(action)
            query = query_review.active(engine.events(), engine.context())
            self.assertTrue(all(query['priorities'][case]['priority'] == 'maybe' for case in query['survey_exposed']))

    def test_read_next_backlog_requires_read_or_explicit_downgrade(self):
        with TemporaryDirectory() as d:
            engine, _ = make(d, 7)
            start(engine)
            engine.step(lambda p: choose(p, 'prioritize_query_results',
                candidate_refs=list(p['payload']['m6']['query_result_choices'])[:1],
                priority='read_next', reason='The highest ranked lead deserves reading.'))
            survey(engine)
            p = engine.prepare(admit=False)
            self.assertEqual(p['payload']['m6']['query_review']['pending_read_next'], 3)
            self.assertNotIn('conclude_search_query', names(p))
            engine.step(choose(p, 'show_context_page', page_ref=p['payload']['m6']['cm_page']['controls']['read_next']))
            p = engine.prepare(admit=False)
            self.assertEqual(p['payload']['m6']['cm_page']['offset'], 0)
            close(engine)
            query = next(iter(engine.inspect()['search_queries'].values()))
            self.assertEqual(query['conclusion']['counters']['raw_exposed'], 0)
            self.assertEqual(query['conclusion']['outcome'], 'partially_resolved')

    def test_literal_survey_preview_is_bound_and_not_raw_receipt(self):
        from hashlib import sha256
        with TemporaryDirectory() as d:
            engine, tools = make(d, 1)
            raw = tools.raw_cases['B00'].text.encode()
            preview = engine._survey_preview({'case_id': 'B00', 'source_hash': sha256(raw).hexdigest(),
                                              'span_bytes': [0, len(raw)]})
            self.assertEqual(preview['text'], raw.decode())
            self.assertEqual(preview['text_sha256'], sha256(raw).hexdigest())
            self.assertTrue(preview['lead_only'])
            start(engine)
            p = engine.prepare(admit=False)
            self.assertFalse(p['payload']['m6']['cm_page']['candidates'][0]['read_allowed'])
            self.assertEqual(query_review.active(engine.events(), engine.context())['raw_exposed'], [])

    def test_settled_proposition_is_signal_only_and_other_sentence_stays_selectable(self):
        text = 'The first legal rule needs a source. Another independent rule needs a source.'
        raw = source('A', text).to_record()
        paragraph = {'source_ref': raw['ref'], 'source_hash': raw['source_hash'], 'paragraph_handle': 'p1',
            'span_bytes': list(raw['span_bytes']), 'paragraph_span_bytes': list(raw['span_bytes']), 'paragraph_coverage': 'full'}
        payload = {'query_id': 'A', 'query_source_hash': raw['source_hash'], 'excerpts': [raw],
                   'current_payload_source_refs': [raw['ref']], 'm6': {'a_paragraphs': {'p': paragraph}}}
        initial = source_gate.segments(payload)
        first, second = list(initial)
        payload['m6']['source_gate_segments'] = initial
        args = {'paragraph_ref': 'p', 'proposition_ref': first, 'decision': 'search_needed',
                'attribution': 'court', 'reason_code': 'legal_proposition', 'reason': 'The first rule needs a source.',
                'context_complete': True}
        decision = source_gate.evaluate(payload, args, [{'handle': 'p1'}])
        context = {}; source_gate.commit_decision(context, decision)
        context['source_gate'][decision['source_need_ref']]['status'] = 'searched'
        filtered = source_gate.segments(payload, context)
        self.assertFalse(filtered[first]['proposition_selectable'])
        self.assertTrue(filtered[second]['proposition_selectable'])
        props = source_gate.assessment_properties(['p'], filtered)
        self.assertNotIn(first, props['proposition_ref']['enum'])
        self.assertIn(first, props['signal_ref']['enum'])
        payload['m6']['source_gate_segments'] = filtered
        self.assertEqual(source_gate.evaluate(payload, args, [{'handle': 'p1'}])['status'], 'unresolved')
        args.update(proposition_ref=second, signal_ref=first)
        self.assertEqual(source_gate.evaluate(payload, args, [{'handle': 'p1'}])['status'], 'approved')
        self.assertFalse(source_gate.commit_decision(context, decision))
        self.assertEqual(context['source_gate'][decision['source_need_ref']]['status'], 'searched')

    def test_conclusion_cannot_hide_unresolved_as_resolved(self):
        class State:
            assessments = {}
            active_assessments = {}
            pending_assessments = {}
        q = {'phase': 'reviewing', 'candidate_ids': ['B'], 'need_id': 'n', 'raw_exposed': [], 'priorities': {}}
        with self.assertRaises(HarnessError):
            query_review.conclude(q, State(), {'outcome': 'resolved', 'reason': 'All results resolved.', 'unresolved_reason': 'Not read.'})


if __name__ == '__main__':
    unittest.main()
