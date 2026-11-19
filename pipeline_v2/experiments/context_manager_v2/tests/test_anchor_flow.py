"""Offline regressions for CM4's recoverable, source-grounded anchor flow."""

from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.experiments.context_manager_v2.anchor_quote import find_anchor
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.tests import test_engine
from pipeline_v2.experiments.context_manager_v2.tests.test_anchor_quote import (
    ANCHOR, ISSUE, PROPOSITION, AnchorTools, full_query_text,
)


def action_names(prepared):
    return {row['properties']['action']['const']
            for row in prepared['manifest']['schema']['anyOf']}


def branch(prepared, name):
    return next(row for row in prepared['manifest']['schema']['anyOf']
                if row['properties']['action']['const'] == name)


def one_search(engine, tools):
    """Count logical retrieval dispatches, not per-channel local index calls."""
    rows = [row for row in engine.events()
            if row['kind'] == 'action_started'
            and row['action'].get('action') == 'search_corpus']
    logical = {row['action']['args']['_m6_need']['source_need_id'] for row in rows}
    return rows, logical


class AnchorFlowTests(unittest.TestCase):
    def make_engine(self, directory, *, repeated=False, text=None):
        tools = AnchorTools(text if text is not None else full_query_text(repeated=repeated))
        engine, _ = test_engine.EngineTests().make(directory, tools)
        return engine, tools

    def issue_action(self, prepared, *, issue=ISSUE, proposition=PROPOSITION,
                     quote=ANCHOR):
        action = choose(prepared, 'search_cases_by_issue', issue=issue,
                        source_proposition=proposition, anchor_quote=quote)
        return action

    def stage(self, engine, *, issue=ISSUE, proposition=PROPOSITION,
              quote=ANCHOR):
        return engine.step(lambda p: self.issue_action(
            p, issue=issue, proposition=proposition, quote=quote))

    @staticmethod
    def internal_anchor_body(prepared, tools):
        """Restore private source bindings omitted from the model-facing payload."""
        body = dict(prepared['payload'])
        body['query_source_hash'] = tools.a.source_hash
        body['excerpts'] = [dict(row, source_hash=(tools.a.source_hash
            if row['case_id'] == 'A' else tools.b.source_hash))
            for row in body['excerpts']]
        return body

    def test_typographic_quote_wrappers_match_without_changing_apostrophes_or_negation(self):
        """Wrapper tolerance may equate delimiters, never rewrite legal meaning."""
        text = ('[14] The Court said “the applicant\'s argument was not neutralized '
                'by the finding” and considered the record.')
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory, text=text)
            body = self.internal_anchor_body(engine.prepare(admit=False), tools)

            resolved, suggestions = find_anchor(
                body, "'the applicant's argument was not neutralized by the finding'")

            self.assertIsNotNone(resolved)
            self.assertEqual(suggestions, [])
            _, anchor = resolved
            self.assertIn("applicant's", anchor['text'])
            self.assertIn('not neutralized', anchor['text'])
            self.assertIn('“', text)
            left, right = anchor['span_bytes']
            source_bytes = text.encode('utf-8')
            # Byte span points to the complete, source-exact phrase including its
            # original curly wrappers (the request used straight apostrophe marks).
            self.assertEqual(source_bytes[left:right].decode('utf-8'), anchor['text'])

            # Removing negation or splitting a possessive is not a typography
            # difference. A fuzzy candidate may be offered, but must not resolve.
            changed, candidates = find_anchor(
                body, 'the applicant argument was neutralized by the finding')
            self.assertIsNone(changed)
            if candidates:
                candidate_text = candidates[0][1]['text'].casefold()
                self.assertIn("applicant's", candidate_text)
                self.assertIn('not neutralized', candidate_text)

    def test_repeated_quote_offers_bounded_explicit_choices_and_searches_once(self):
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory, repeated=True)
            self.stage(engine, quote=ANCHOR)

            self.assertEqual(tools.search_calls, 0,
                             'an ambiguous quote must not reach retrieval')
            prepared = engine.prepare(admit=False)
            feedback = prepared['payload']['last_action_feedback']['anchor_resolution']
            self.assertEqual(feedback['status'], 'awaiting_choice')
            self.assertGreaterEqual(len(feedback['candidates']), 2)
            self.assertLessEqual(len(feedback['candidates']), 3)
            self.assertIn('choose_query_anchor', action_names(prepared))
            self.assertIn('defer_query_anchor', action_names(prepared))

            offered = {row['anchor_ref'] for row in feedback['candidates']}
            enum = branch(prepared, 'choose_query_anchor')['properties']['args']['properties'][
                'anchor_ref']['enum']
            self.assertEqual(set(enum), offered,
                             'only concrete candidates currently shown may be selected')
            selected = feedback['candidates'][1]
            engine.step(lambda p: choose(
                p, 'choose_query_anchor', anchor_ref=selected['anchor_ref']))

            rows, logical_searches = one_search(engine, tools)
            self.assertTrue(rows)
            self.assertEqual(len(logical_searches), 1)
            self.assertEqual(tools.search_calls, 2,
                             'one logical retrieval is dispatched to two local lexical channels')
            self.assertEqual(len({row['action']['args']['_m6_need']['source_need_id']
                                  for row in rows}), 1)

    def test_approximate_quote_is_only_a_candidate_until_explicit_confirmation(self):
        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory)
            near_miss = 'the Board breached procedural fairness while misleading applicants'
            self.stage(engine, quote=near_miss)

            self.assertEqual(tools.search_calls, 0)
            prepared = engine.prepare(admit=False)
            feedback = prepared['payload']['last_action_feedback']['anchor_resolution']
            self.assertEqual(feedback['status'], 'awaiting_choice')
            self.assertTrue(feedback['candidates'])
            option = feedback['candidates'][0]
            self.assertNotEqual(option['text'], near_miss)
            self.assertIn(option['anchor_ref'], branch(prepared, 'choose_query_anchor')
                          ['properties']['args']['properties']['anchor_ref']['enum'])

            engine.step(lambda p: choose(
                p, 'choose_query_anchor', anchor_ref=option['anchor_ref']))
            rows, logical_searches = one_search(engine, tools)
            self.assertTrue(rows)
            self.assertEqual(len(logical_searches), 1)

    def test_defer_continue_and_resume_keeps_original_issue_and_proposition(self):
        original_issue = 'original issue: notice and opportunity to respond'
        original_proposition = 'The Board misstated the applicants\' procedural rights.'
        other_issue = 'separate issue: state protection and generalized risk'
        other_proposition = 'The Court applied the state protection finding.'

        with TemporaryDirectory() as directory:
            engine, tools = self.make_engine(directory, repeated=True)
            self.stage(engine, issue=original_issue, proposition=original_proposition,
                       quote=ANCHOR)
            self.assertEqual(tools.search_calls, 0)
            engine.step(lambda p: choose(p, 'defer_query_anchor'))

            after_defer = engine.prepare(admit=False)
            self.assertIn('search_cases_by_issue', action_names(after_defer),
                          'parking an unresolved anchor must allow another useful task')
            self.assertIn('resume_query_anchor', action_names(after_defer))
            parked = after_defer['payload']['last_action_feedback']['anchor_resolution']['parked']
            self.assertEqual(len(parked), 1)
            self.assertEqual(parked[0]['issue'], original_issue)

            # Finish one independent, exact-anchor search while the first draft is
            # parked. A unique quote is sufficient to dispatch this search.
            engine.step(lambda p: self.issue_action(
                p, issue=other_issue, proposition=other_proposition,
                quote='reviewable on a standard of reasonableness'))
            rows, logical_searches = one_search(engine, tools)
            self.assertTrue(rows)
            self.assertEqual(len(logical_searches), 1)
            latest_need = rows[-1]['action']['args']['_m6_need']
            self.assertEqual(latest_need['source_proposition'], other_proposition)

            # Complete the second candidate's assessment boundary so resume is
            # offered from a safe point, then return to the saved first issue.
            engine.step(lambda p: test_engine.EngineTests().action(p, 'read_case_passages'))
            assessment = engine.prepare(admit=False)
            pair_ref = next(iter(assessment['payload']['m6']['pair_refs']))
            engine.step(lambda p: choose(p, 'assess_case_link', pair_ref=pair_ref,
                                         case_relation='unknown',
                                         passage_location='bounded',
                                         reason='The visible excerpts are insufficient to establish reliance.'))

            resumed = engine.prepare(admit=False)
            self.assertIn('resume_query_anchor', action_names(resumed))
            self.assertFalse(resumed['payload']['last_action_feedback']['review_progress']['complete_policy_allowed'])
            saved = resumed['payload']['last_action_feedback']['anchor_resolution']['parked'][0]
            self.assertEqual(saved['issue'], original_issue)
            engine.step(lambda p: choose(p, 'resume_query_anchor',
                                         draft_ref=saved['draft_ref']))

            restored = engine.prepare(admit=False)
            resolution = restored['payload']['last_action_feedback']['anchor_resolution']
            self.assertEqual(resolution['status'], 'awaiting_choice')
            self.assertEqual(resolution['issue'], original_issue)
            self.assertEqual(resolution['source_proposition'], original_proposition)
            self.assertTrue(resolution['candidates'])
            self.assertEqual(tools.search_calls, 2,
                             'only the independent exact search ran; resume itself must not search')


if __name__ == '__main__':
    unittest.main()
