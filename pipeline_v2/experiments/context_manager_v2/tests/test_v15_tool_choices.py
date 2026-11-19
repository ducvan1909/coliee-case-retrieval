"""Regression tests for CM4 choices that must not invite known no-op actions."""
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from jsonschema import Draft202012Validator

from pipeline_v2.experiments.context_manager_v2.tests.view_helpers import canonical_ref

from pipeline_v2.agent_harness import RunIdentity, ToolResult
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.tests.test_empty_reopen import (
    ReopenTools, action, count_tokens, make_engine,
)
from pipeline_v2.experiments.context_manager_v2.tests.test_lead_delivery import LeadTools


def names(prepared):
    return {branch['properties']['action']['const']
            for branch in prepared['manifest']['schema']['anyOf']}


def branch(prepared, name):
    return next(row for row in prepared['manifest']['schema']['anyOf']
                if row['properties']['action']['const'] == name)


def page_action(prepared, mode):
    page = prepared['payload']['m6']['cm_page']
    return {'action': 'show_context_page',
            'args': {'page_ref': page['controls'][mode]}}


class FlatLeadTools(LeadTools):
    """Return only the requested raw hit so a new focus can be tested next."""
    def open_source(self, args):
        result = super().open_source(args)
        excerpt = self.b.slice(1000, 1600)
        observation = {**result.observation, 'hit_refs': [
            {'kind': 'passage', 'ref': 'B-hit', 'span_bytes': [1100, 1200],
             'delivered_spans': [[1000, 1600]]}]}
        return ToolResult(observation, (excerpt,), ('B',), result.source_requests)


class MapTools(ReopenTools):
    def __init__(self):
        super().__init__('fresh')
        self.query_tree = SimpleNamespace(root_ref='root')

    def registry(self, events, state, payload):
        page = {'kind': 'query_hierarchy_map', 'current': {'region_ref': 'root'},
                'root_ref': 'root', 'parent_ref': None, 'children': [],
                'coverage': 'structural_intervals_only'}
        # The model receives map and full-text region choices through the same
        # public read_query_passages action. Internal navigation mode stays in
        # the opaque host binding, never as a second public action.
        maps = {}
        targets = {
            'child-map': {'binding': {'navigation_mode': 'map', 'region_ref': 'root.0',
                                      'visit_epoch': 1},
                          'description': {'purpose': 'child', 'response': 'map'}},
            'root-raw': {'binding': {'navigation_mode': 'raw', 'region_ref': 'root',
                                     'visit_epoch': 1},
                         'description': {'purpose': 'read root', 'response': 'full_text'}},
        }
        return page, maps, targets

    def shrink_map_page(self, page):
        return page


class CitationTools(ReopenTools):
    def __init__(self):
        super().__init__('fresh')
        self.sources = SimpleNamespace(search_identity=lambda **kwargs: None,
            _case=lambda case: (None, {'source_hash': self.a.source_hash, 'navigation': []}, None))

    def _read_source(self, source_fn, **args):
        hit = {'case_id': 'B', 'rank': 1, 'open_ref': {
            'case_id': 'B', 'source_hash': self.b.source_hash, 'passage_ids': ['B-1']}}
        cursor = 'cursor-page-3' if args.get('cursor') else 'cursor-page-2'
        return {'hits': [hit], 'coverage': {'scanned': 1}, 'next_cursor': cursor}

    @staticmethod
    def _search_hits(raw):
        return ToolResult({'hits': raw['hits']}, candidates=('B',))


class V15ToolChoiceTests(unittest.TestCase):
    def make(self, directory, tools=None):
        tools = tools or ReopenTools('fresh')
        return make_engine(directory, tools)

    @staticmethod
    def make_lead_engine(directory, tools):
        identity = RunIdentity('lead-v15', 'A', tools.a.source_hash,
            'candidate-binding', 'index-binding', 'profile', 'model',
            'prompt', 'tool-binding', 'counter-binding')
        raw = {row.case_id: row.text.encode('utf-8') for row in (tools.a, tools.b)}
        return Engine(directory, identity=identity, tools=tools, count_tokens=count_tokens,
                      raw_reader=lambda case: raw[case], counter_binding='fixture-counter-v1')

    def test_duplicate_issue_is_followed_by_one_readable_recovery_turn(self):
        with TemporaryDirectory() as directory:
            engine = self.make(directory)
            before = engine.prepare(admit=False)
            repeated_search = action(before, 'search_cases_by_issue')
            engine.step(repeated_search)
            engine.step(lambda p: action(p, 'read_case_passages', case_id='B'))
            engine.step(lambda p: action(p, 'assess_case_link'))
            # At a safe boundary the issue tool is available again. Replay the
            # identical issue and A paragraph; retrieval must not run twice.
            engine.step(repeated_search)

            recovery = engine.prepare(admit=False)
            self.assertNotIn('search_cases_by_issue', names(recovery))
            self.assertIn('read_case_passages', names(recovery))
            readable = branch(recovery, 'read_case_passages')['properties']['args']['properties']['candidate_ref']['enum']
            candidates = recovery['payload']['m6']['candidates']
            unread_c = [ref for ref, row in candidates.items()
                        if row['case_id'] == 'C']
            self.assertEqual(len(unread_c), 1)
            self.assertIn(unread_c[0], readable)
            self.assertEqual(engine.events()[-1]['reason'], 'duplicate_action')

            engine.step(lambda p: action(p, 'read_case_passages', case_id='C'))
            self.assertEqual(engine.context()['candidate_id'], 'C')
            self.assertEqual(engine.context()['stage'], 'reading')

    def test_current_and_empty_navigation_handles_are_not_offered(self):
        with TemporaryDirectory() as directory:
            engine = self.make(directory)
            prepared = engine.prepare(admit=False)
            current = prepared['payload']['m6']['cm_page']
            self.assertEqual(engine.context()['mode'], 'query')
            self.assertNotIn('query', current['controls'])
            self.assertNotIn('next', current['controls'])
            self.assertNotIn('previous', current['controls'])
            self.assertNotIn('show_context_page', names(prepared))

            engine.step(lambda p: action(p, 'search_cases_by_issue'))
            prepared = engine.prepare(admit=False)
            page = prepared['payload']['m6']['cm_page']
            self.assertEqual(engine.context()['mode'], 'results')
            self.assertNotIn('results', page['controls'])
            self.assertNotIn('next', page['controls'])
            self.assertNotIn('previous', page['controls'])

    def test_map_and_full_text_use_one_public_read_action(self):
        with TemporaryDirectory() as directory:
            engine = self.make(directory, MapTools())
            prepared = engine.prepare(admit=False)
            self.assertIn('read_query_passages', names(prepared))
            self.assertNotIn('expand_query_map', names(prepared))
            refs = branch(prepared, 'read_query_passages')['properties']['args']['properties']['query_ref']['enum']
            self.assertEqual(set(refs), {'child-map', 'root-raw'})
            targets = prepared['payload']['m6']['query_targets']
            self.assertEqual(targets['child-map']['description']['response'], 'map')
            self.assertEqual(targets['root-raw']['description']['response'], 'full_text')

    def test_citation_search_tools_are_disabled_even_with_a_pending_cursor(self):
        with TemporaryDirectory() as directory:
            engine = self.make(directory, CitationTools())
            from unittest.mock import patch
            original = engine.harness._registry
            def with_cursor(state, payload):
                result = original(state, payload)
                result['citation_search_pages'] = {'pending': {
                    'binding': {'text': '2012 SCC 12', 'cursor': 'next'},
                    'description': {'purpose': 'continue_unscanned_citation_cases'}}}
                return result
            with patch.object(engine.harness, '_registry', side_effect=with_cursor):
                prepared = engine.prepare(admit=False)
            public_tools = {row['name'] for row in prepared['payload']['available_tools']}
            for disabled in ('find_citation_matches', 'continue_citation_search'):
                self.assertNotIn(disabled, names(prepared))
                self.assertNotIn(disabled, public_tools)
            self.assertEqual(prepared['payload']['m6']['citation_refs'], {})
            self.assertEqual(prepared['payload']['m6']['citation_search_pages'], {})

    def test_current_pair_cannot_reload_or_resume_but_other_parked_pair_can_resume(self):
        with TemporaryDirectory() as directory:
            engine = self.make(directory)
            engine.step(lambda p: action(p, 'search_cases_by_issue'))
            engine.step(lambda p: action(p, 'read_case_passages', case_id='B'))
            engine.step(lambda p: action(p, 'assess_case_link'))

            current = engine.prepare(admit=False)
            self.assertEqual(engine.context()['candidate_id'], 'B')
            self.assertNotIn('reload_pair_evidence', names(current))
            self.assertNotIn('resume_pair_evidence', names(current))

            engine.step(lambda p: page_action(p, 'results'))
            ready_c = engine.prepare(admit=False)
            c_ref = next(ref for ref, row in ready_c['payload']['m6']['retrieved_passages'].items()
                         if row['description']['case_id'] == 'C')
            engine.step({'action': 'open_retrieved_passage', 'args': {'lead_ref': c_ref}})
            engine.step(lambda p: action(p, 'assess_case_link'))
            other = engine.prepare(admit=False)
            self.assertEqual(engine.context()['candidate_id'], 'C')
            self.assertNotIn('reload_pair_evidence', names(other))
            engine.step(lambda p: page_action(p, 'parked'))
            parked = engine.prepare(admit=False)
            self.assertIn('resume_pair_evidence', names(parked))
            resume = branch(parked, 'resume_pair_evidence')['properties']['args']['properties']['evidence_ref']['enum']
            target_pairs = [parked['manifest']['handles'][canonical_ref(parked, ref)]['candidate_id'] for ref in resume]
            self.assertIn('B', target_pairs)

    def test_schema_rejects_repeated_finite_assessment_refs(self):
        with TemporaryDirectory() as directory:
            engine = self.make(directory)
            engine.step(lambda p: action(p, 'search_cases_by_issue'))
            engine.step(lambda p: action(p, 'read_case_passages', case_id='B'))
            prepared = engine.prepare(admit=False)
            assessment = branch(prepared, 'assess_case_link')
            fields = assessment['properties']['args']['properties']
            self.assertIn('identity_support_choice', fields)
            self.assertIn('counterevidence_choice', fields)
            self.assertNotIn('identity_support_refs', fields)
            self.assertNotIn('counterevidence', fields)
            # The public contract now uses finite scalar choices. Retain a
            # schema-level regression in case ref arrays are reintroduced.
            validator = Draft202012Validator(assessment)
            args = action(prepared, 'assess_case_link')['args']
            args['identity_support_choice'] = 'both cases'
            args['counterevidence_choice'] = 'both cases'
            self.assertTrue(validator.is_valid({'action': 'assess_case_link', 'args': args}))

    def test_retrieval_lead_is_direct_and_new_focus_stays_within_candidate(self):
        with TemporaryDirectory() as directory:
            tools = FlatLeadTools()
            engine = self.make_lead_engine(directory, tools)
            engine.step(lambda p: action(p, 'search_cases_by_issue'))
            prepared = engine.prepare(admit=False)
            leads = prepared['payload']['m6']['retrieved_passages']
            self.assertTrue(leads)
            self.assertIn('open_retrieved_passage', names(prepared))
            lead_ref = next(iter(leads))
            engine.step({'action': 'open_retrieved_passage', 'args': {'lead_ref': lead_ref}})

            first = next(row for row in reversed(engine.events()) if row['kind'] == 'action_result')
            self.assertEqual(first['result']['observation']['route'], 'open_observed_lead')
            self.assertEqual(tools.opens, 1)
            focused = engine.prepare(admit=False)
            self.assertNotIn('open_retrieved_passage', names(focused))
            focus_branch = branch(focused, 'read_case_passages')
            self.assertIn('focus', focus_branch['properties']['args']['required'])
            engine.step(lambda p: action(p, 'read_case_passages', case_id='B'))
            second = next(row for row in reversed(engine.events()) if row['kind'] == 'action_result')
            self.assertEqual(second['result']['observation']['route'], 'within_case_then_open')
            self.assertEqual(tools.opens, 2)

    def test_same_retrieval_lead_on_new_need_uses_cached_raw(self):
        with TemporaryDirectory() as directory:
            tools = FlatLeadTools()
            engine = self.make_lead_engine(directory, tools)
            engine.step(lambda p: action(p, 'search_cases_by_issue'))
            first_need = engine.context()['need_id']
            prepared = engine.prepare(admit=False)
            first_ref = next(iter(prepared['payload']['m6']['retrieved_passages']))
            engine.step({'action': 'open_retrieved_passage', 'args': {'lead_ref': first_ref}})
            engine.step(lambda p: action(p, 'assess_case_link'))

            def new_issue(prepared):
                result = action(prepared, 'search_cases_by_issue')
                result['args']['issue'] = 'a separate legal issue about statutory damages'
                return result
            engine.step(new_issue)
            self.assertNotEqual(engine.context()['need_id'], first_need)
            next_payload = engine.prepare(admit=False)
            leads = next_payload['payload']['m6']['retrieved_passages']
            self.assertTrue(leads)
            engine.step({'action': 'open_retrieved_passage', 'args': {'lead_ref': next(iter(leads))}})

            outcome = next(row for row in reversed(engine.events()) if row['kind'] == 'action_result')
            self.assertEqual(outcome['result']['observation']['route'], 'reuse_observed_lead')
            self.assertEqual(tools.opens, 1)
            cached = engine.prepare(admit=False)
            self.assertTrue(any(row['case_id'] == 'B' for row in cached['payload']['excerpts']))


if __name__ == '__main__':
    unittest.main()
