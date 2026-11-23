"""Strict live-style two-turn source gate and explicit draft close regressions."""
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator

from pipeline_v2.agent_harness import RunIdentity
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.source_gate import (
    commit_decision, evaluate, progress, screening_choices,
)
from pipeline_v2.experiments.context_manager_v2.tests import test_engine, test_anchor_flow
from pipeline_v2.tests.test_m6_adaptive import Tools, source


AUTHORITY = 'The Court stated the fairness rule in 2010 FC 413.'


def make_engine(directory, text=AUTHORITY, *, paragraphs=None):
    tools = Tools()
    tools.a = source('A', text)
    tools.query_paragraphs = paragraphs or ({'handle': 'p000001', 'span_bytes': tools.a.span_bytes},)
    identity = RunIdentity('source-gate', 'A', tools.a.source_hash, 'c', 'i', 'p', 'm', 'p', 't', 'z')
    engine = Engine(directory, identity=identity, tools=tools, count_tokens=test_engine.count,
                    raw_reader=lambda case: {'A': tools.a, 'B': tools.b}[case].text.encode(), gate_enabled=True)
    return engine, tools


def screen(prepared, text, decision='search_needed', reason_code='authority_reference'):
    refs = {}
    if decision == 'search_needed':
        ref = next(iter(prepared['payload']['m6']['source_gate_segments']))
        refs = dict(proposition_ref=ref, signal_ref=ref)
    return choose(prepared, 'assess_source_need', decision=decision,
                  attribution='court', reason_code=reason_code,
                  reason='The selected paragraph states the indicated source role.', context_complete=True, **refs)


def names(prepared):
    return {branch['properties']['action']['const'] for branch in prepared['manifest']['schema']['anyOf']}


class SourceGateTests(unittest.TestCase):
    def test_permitted_search_dispatches_unmatched_words_to_retrieval(self):
        for issue in ('equitable hearing requirement', 'judicial review leave to file reply affidavit'):
            with self.subTest(issue=issue), TemporaryDirectory() as directory:
                engine, _ = make_engine(directory)
                engine.step(lambda p: screen(p, AUTHORITY))
                engine.step(lambda p: choose(p, 'search_cases_by_issue', issue=issue,
                                             source_proposition='An affidavit may be filed.'))
                decision, = engine.context()['source_gate'].values()
                self.assertEqual(decision['status'], 'searched')
                search = next(event['action'] for event in engine.events()
                              if event['kind'] == 'action_started'
                              and event['action']['action'] == 'search_corpus')
                self.assertEqual(search['args']['text'], issue)
                self.assertEqual(search['args']['_m6_need']['a_anchor']['span_bytes'],
                                 decision['proposition']['span_bytes'])
                self.assertGreater(len(engine.state().candidates), 0)

    def test_citation_negative_is_honored_and_other_paragraph_remains_available(self):
        first = 'Hargrave observed as follows: <FRAGMENT_SUPPRESSED> para. 31.'
        text = first + '\nThe applicant filed a motion on Monday.'
        cut = len(first.encode('utf-8'))
        paragraphs = ({'handle': 'p000001', 'span_bytes': [0, cut]},
                      {'handle': 'p000002', 'span_bytes': [cut + 1, len(text.encode('utf-8'))]})
        with TemporaryDirectory() as directory:
            engine, _ = make_engine(directory, text, paragraphs=paragraphs)
            engine.step(lambda p: screen(p, text, 'no_search_needed', 'procedural_history'))
            decided, = engine.context()['source_gate'].values()
            self.assertEqual(decided['decision'], 'no_search_needed')
            self.assertEqual(decided['status'], 'screened')
            followup = engine.prepare(admit=False)
            self.assertNotIn('search_cases_by_issue', names(followup))
            self.assertNotIn('defer_source_need', names(followup))
            self.assertEqual(followup['payload']['last_action_feedback']['query_gate_progress']['paragraphs_screened'], 1)
            engine.step(lambda p: screen(p, text, 'no_search_needed', 'facts'))
            self.assertTrue(engine.prepare(admit=False)['payload']['last_action_feedback']['query_gate_progress']['complete'])

    def test_partial_map_view_cannot_rescreen_or_overwrite_a_full_decision(self):
        text = 'The applicant filed the affidavit on Monday. The registry received it on Tuesday.'
        with TemporaryDirectory() as directory:
            engine, tools = make_engine(directory, text)
            original = engine.prepare(admit=False)
            engine.step(lambda p: screen(p, text, 'no_search_needed', 'procedural_history'))
            context = engine.context()
            saved, = context['source_gate'].values()
            partial = tools.a.slice(0, 44).to_record()
            paragraph = {**saved['paragraph'], 'paragraph_coverage': 'partial',
                         'span_bytes': partial['span_bytes'], 'source_ref': partial['ref']}
            payload = {'query_id': 'A', 'query_source_hash': tools.a.source_hash,
                       'excerpts': [partial], 'current_payload_source_refs': [partial['ref']],
                       'm6': {'a_paragraphs': {'p000001@0:44': paragraph}}}
            self.assertEqual(screening_choices(payload, context), [])
            self.assertEqual(screening_choices(payload, {}), ['p000001@0:44'])
            args = screen(original, text, 'no_search_needed', 'procedural_history')['args']
            args['paragraph_ref'] = 'p000001@0:44'
            rejected = evaluate(payload, args, tools.query_paragraphs)
            self.assertNotEqual(rejected['source_need_ref'], saved['source_need_ref'])
            self.assertEqual(rejected['status'], 'screened')
            self.assertFalse(commit_decision(context, rejected))
            self.assertEqual(context['source_gate'][saved['source_need_ref']], saved)
            self.assertTrue(progress(context, tools.query_paragraphs)['complete'])

    def test_positive_opens_search_on_next_turn_and_persists_after_restart(self):
        with TemporaryDirectory() as directory:
            engine, tools = make_engine(directory)
            initial = engine.prepare(admit=False)
            self.assertNotIn('search_cases_by_issue', names(initial))
            self.assertNotIn('open_retrieved_passage', names(initial))
            engine.step(lambda p: screen(p, AUTHORITY))
            approved = engine.prepare(admit=False)
            self.assertEqual(names(approved), {'search_cases_by_issue', 'defer_approved_source_need'})
            self.assertFalse(tools.reads)
            engine, _ = make_engine(directory)
            self.assertIn('search_cases_by_issue', names(engine.prepare(admit=False)))
            engine.step(lambda p: choose(p, 'search_cases_by_issue', issue='procedural fairness rule',
                                        source_proposition='The Court relied on the fairness rule.'))
            self.assertEqual(engine.context()['mode'], 'results')
            engine.step(lambda p: choose(p, 'prioritize_query_results',
                candidate_refs=list(p['payload']['m6']['query_result_choices']),
                priority='read_next', reason='The lead addresses the rule.'))
            engine.step(lambda p: choose(p, 'open_retrieved_passage'))
            engine.step(lambda p: test_engine.EngineTests().action(p, 'assess_case_link'))
            engine.step(lambda p: choose(p, 'conclude_search_query', outcome='partially_resolved',
                reason='The candidate has been assessed.', unresolved_reason='The model kept the relation unknown.', remaining_source_need=''))
            done = engine.prepare(admit=False)
            self.assertIn('complete_policy', next(branch for branch in done['manifest']['schema']['anyOf']
                if branch['properties']['action']['const'] == 'finish_case_review')
                ['properties']['args']['properties']['reason']['enum'])
            empty_prediction = engine.harness._final('complete', 'controller_stop', prediction=[])
            self.assertEqual(empty_prediction['stop_reason'], 'partial')
            self.assertIsNone(empty_prediction['prediction'])
            self.assertFalse(empty_prediction['fallback'])
            engine.step(lambda p: choose(p, 'finish_case_review', reason='complete_policy'))
            final = engine.state().final
            self.assertEqual(final['stop_reason'], 'partial')
            self.assertEqual(final['review_status'], 'partial_with_unresolved_queries')
            self.assertFalse(final['fallback'])
            self.assertIsNone(final['prediction'])
            self.assertEqual(final['unresolved_search_query_count'], 1)
            query_id, = final['unresolved_search_query_ids']
            self.assertTrue(query_id)
            engine, _ = make_engine(directory, AUTHORITY)
            self.assertEqual(engine.state().final, final)

    def test_defer_keeps_search_unexecuted_and_resume_restores_priority(self):
        with TemporaryDirectory() as directory:
            engine, _ = make_engine(directory)
            engine.step(lambda p: screen(p, AUTHORITY))
            engine.step(lambda p: choose(p, 'defer_approved_source_need', reason_code='search_terms_unclear',
                                         reason='The search terms need refinement.'))
            engine, _ = make_engine(directory)
            deferred = engine.prepare(admit=False)
            self.assertNotIn('search_cases_by_issue', names(deferred))
            self.assertIn('resume_approved_source_need', names(deferred))
            self.assertEqual(deferred['payload']['last_action_feedback']['query_gate_progress']['deferred_search_count'], 1)
            self.assertFalse(engine.context().get('source_gate_searches'))
            engine.step(lambda p: choose(p, 'resume_approved_source_need', reason='The quoted test gives a specific query.'))
            self.assertEqual(names(engine.prepare(admit=False)), {'search_cases_by_issue', 'defer_approved_source_need'})

    def test_model_negative_is_honored_regardless_of_source_cue_or_reason_code(self):
        cases = [
            'The decision was based upon a wrong principle.',
            'The applicant filed a motion. <FRAGMENT_SUPPRESSED>',
            'The Respondent says the Federal Court of Appeal has set out the test.',
            'The applicable test is set out in 2010 FC 413.',
            'The court adopted <FRAGMENT_SUPPRESSED> at para. 19.',
        ]
        for text in cases:
            with self.subTest(text=text), TemporaryDirectory() as directory:
                engine, _ = make_engine(directory, text)
                engine.step(lambda p: screen(p, text, 'no_search_needed', 'authority_reference'))
                decided, = engine.context()['source_gate'].values()
                self.assertEqual(decided['status'], 'screened')
                self.assertEqual(decided['reason_code'], 'authority_reference')
                self.assertNotIn('search_cases_by_issue', names(engine.prepare(admit=False)))

    def test_model_positive_opens_retrieval_without_a_host_recognized_citation(self):
        text = 'The Court received the reply affidavit on Monday.'
        with TemporaryDirectory() as directory:
            engine, _ = make_engine(directory, text)
            engine.step(lambda p: screen(p, text, reason_code='facts'))
            approved = engine.prepare(admit=False)
            self.assertIn('search_cases_by_issue', names(approved))
            decided, = engine.context()['source_gate'].values()
            self.assertEqual(decided['decision'], 'search_needed')
            self.assertEqual(decided['reason_code'], 'facts')
            self.assertEqual(decided['status'], 'approved')
            engine.step(lambda p: choose(p, 'search_cases_by_issue', issue='reply affidavit rules',
                                        source_proposition='The Court received an affidavit.'))
            self.assertEqual(engine.context()['stage'], 'results_ready')

    def test_model_unresolved_decision_can_be_deferred(self):
        text = 'The Court received the reply affidavit on Monday.'
        with TemporaryDirectory() as directory:
            engine, _ = make_engine(directory, text)
            engine.step(lambda p: screen(p, text, 'need_more_context', 'source_unresolved'))
            unresolved = engine.prepare(admit=False)
            self.assertNotIn('search_cases_by_issue', names(unresolved))
            self.assertEqual(unresolved['payload']['last_action_feedback']['query_gate_progress']['unresolved_count'], 1)
            engine.step(lambda p: choose(p, 'defer_source_need', reason='The complete query contains no recoverable authority identity.'))
            done = engine.prepare(admit=False)
            self.assertTrue(done['payload']['last_action_feedback']['query_gate_progress']['complete'])

    def test_negative_has_no_retrieval_and_completion_survives_restart(self):
        text = 'The applicant then filed three notices: ' + '\n'.join(
            f'({letter}) A notice scheduling a procedural hearing at the registry with several dates and deadlines.'
            for letter in 'abc')
        self.assertGreater(len(text), 240)
        with TemporaryDirectory() as directory:
            engine, _ = make_engine(directory, text)
            preview = engine.prepare(admit=False)
            self.assertEqual(len(preview['payload']['m6']['source_gate_segments']), 4)
            engine.step(lambda p: screen(p, text, 'no_search_needed', 'procedural_history'))
            engine, _ = make_engine(directory, text)
            done = engine.prepare(admit=False)
            self.assertNotIn('search_cases_by_issue', names(done))
            engine.step(lambda p: choose(p, 'finish_case_review', reason='complete_policy'))
            self.assertEqual(engine.state().final['stop_reason'], 'complete')

    def test_search_cannot_change_anchor_or_use_an_unissued_permit(self):
        with TemporaryDirectory() as directory:
            engine, _ = make_engine(directory)
            engine.step(lambda p: screen(p, AUTHORITY))
            prepared = engine.prepare(admit=False)
            validator = Draft202012Validator(prepared['manifest']['schema'])
            action = choose(prepared, 'search_cases_by_issue', issue='procedural fairness rule',
                            source_proposition='The Court relied on this rule.')
            action['args']['source_need_ref'] = 'invented-permit'
            self.assertFalse(validator.is_valid(action))
            action['args']['anchor_quote'] = AUTHORITY
            self.assertFalse(validator.is_valid(action))

    def test_discarded_draft_remains_auditable_without_blocking_completion(self):
        with TemporaryDirectory() as directory:
            helper = test_anchor_flow.AnchorFlowTests()
            engine, _ = helper.make_engine(directory)
            helper.stage(engine, quote='An invented quote which cannot occur in the source case')
            engine.step(lambda p: choose(p, 'defer_query_anchor'))
            helper.stage(engine)
            engine.step(lambda p: test_engine.EngineTests().action(p, 'read_case_passages'))
            engine.step(lambda p: test_engine.EngineTests().action(p, 'assess_case_link'))
            pending = engine.prepare(admit=False)
            self.assertFalse(pending['payload']['last_action_feedback']['review_progress']['complete_policy_allowed'])
            engine.step(lambda p: choose(p, 'close_query_anchor', resolution='discarded',
                                        replacement_ref='', reason='The corrected exact quote was reviewed.'))
            self.assertFalse(engine.context()['anchor_drafts'])
            self.assertEqual(len(engine.context()['closed_anchor_drafts']), 1)
            done = engine.prepare(admit=False)
            self.assertTrue(done['payload']['last_action_feedback']['review_progress']['complete_policy_allowed'])


if __name__ == '__main__':
    unittest.main()
