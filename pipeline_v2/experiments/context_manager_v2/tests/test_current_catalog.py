"""CM4 must not publish legacy tools, decisions or unusable recovery routes."""
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.experiments.context_manager_v2 import source_gate
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.tests.test_query_review_acceptance import make, start, survey


class CurrentCatalogTests(unittest.TestCase):
    def test_gate_offers_only_current_decisions(self):
        fields = source_gate.assessment_properties(['p'], ['s'])
        self.assertEqual(fields['decision']['enum'],
                         ['search_needed', 'need_more_context', 'no_search_needed'])

    def test_obsolete_decisions_are_rejected_by_host(self):
        from pipeline_v2.experiments.context_manager_v2.tests.test_source_grounding import SourceGroundingTests
        for decision in ('has_source_signal', 'no_source_signal'):
            with self.subTest(decision=decision), self.assertRaises(HarnessError):
                SourceGroundingTests().assess('The notice rule needs a source.', decision=decision)

    def test_catalog_and_recovery_routes_drop_legacy_names(self):
        obsolete = ['choose_query_anchor', 'defer_query_anchor', 'resume_query_anchor',
                    'close_query_anchor', 'find_citation_matches', 'continue_citation_search', 'reload_evidence']
        payload = {'available_tools': [{'name': name} for name in [*obsolete, 'read_query_span']],
                   'm6': {'closable_anchor_drafts': {'stale': {}}},
                   'last_action_feedback': {'anchor_resolution': {'status': 'awaiting_choice'},
                       'navigation_options': [{'tool': name} for name in [*obsolete, 'read_query_span']]}}
        schema = {'anyOf': [{'properties': {'action': {'const': name}}}
                            for name in [*obsolete, 'read_query_span']]}
        result = Engine._current_tool_catalog(payload, schema)
        self.assertEqual([b['properties']['action']['const'] for b in result['anyOf']], ['read_query_span'])
        self.assertEqual(payload['last_action_feedback']['navigation_options'], [{'tool': 'read_query_span'}])
        self.assertNotIn('anchor_resolution', payload['last_action_feedback'])
        self.assertNotIn('closable_anchor_drafts', payload['m6'])

    def test_live_style_views_have_no_legacy_tools_or_decisions(self):
        forbidden = {'choose_query_anchor', 'defer_query_anchor', 'resume_query_anchor',
                     'close_query_anchor', 'find_citation_matches', 'continue_citation_search', 'reload_evidence'}
        with TemporaryDirectory() as directory:
            engine, _ = make(directory, 6)
            for stage in range(3):
                if stage == 1:
                    start(engine)
                elif stage == 2:
                    survey(engine)
                prepared = engine.prepare(admit=False)
                names = {tool['name'] for tool in prepared['payload']['available_tools']}
                self.assertFalse(names & forbidden)
                for options in ('navigation_options', 'evidence_options'):
                    for option in prepared['payload']['last_action_feedback'].get(options, []):
                        self.assertIn(option['tool'], names)


if __name__ == '__main__':
    unittest.main()
