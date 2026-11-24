"""A hint or a single tool name alone cannot authorize automatic paging."""
from copy import deepcopy
import unittest

from pipeline_v2.experiments.context_manager_v2.candidate_navigation import propose


def packet():
    context = {'mode': 'results', 'stage': 'ready', 'need_id': 'need', 'candidate_id': None,
               'revision': 2, 'passage_session': {'survey_offset': 0}}
    query = {'query_id': 'query', 'need_id': 'need', 'candidate_ids': ['B1', 'B2'], 'hits': []}
    payload = {'available_tools': [{'name': 'show_context_page'}], 'm6': {
        'query_review': {'query_id': 'query'},
        'cm_page': {'candidates': [{'case_id': 'B1', 'review_complete': True, 'conclusion_status': 'final'}]},
        'candidate_navigation': {'next_unseen_page': 'page2'}}}
    schema = {'anyOf': [{'properties': {'action': {'const': 'show_context_page'},
              'args': {'properties': {'page_ref': {'enum': ['page2']}}}}}]}
    handles = {'page2': {'kind': 'survey_page', 'offset': 1}}
    return context, query, payload, schema, handles


class CandidateNavigationTests(unittest.TestCase):
    def test_proposal_is_detached_and_stable_visited_key_blocks_a_later_revision(self):
        args = packet()
        before = deepcopy(args)
        result = propose(*args)
        self.assertIsNotNone(result)
        self.assertEqual(args, before)
        context = {**args[0], 'candidate_auto_visited': result['candidate_auto_visited'], 'revision': 999}
        self.assertIsNone(propose(context, *args[1:]))
        result['passage_session']['survey_offset'] = 8
        self.assertEqual(args[0]['passage_session']['survey_offset'], 0)

    def test_pending_work_multiple_targets_stale_query_repair_and_stop_do_not_auto(self):
        self.assertIsNone(propose(*packet(), blocked=True))
        for field, value in [('mode', 'query'), ('stage', 'missing_evidence'),
                             ('need_id', 'other'), ('candidate_id', 'B1'), ('active_anchor_draft', 'draft')]:
            args = list(packet())
            args[0][field] = value
            self.assertIsNone(propose(*args), field)
        args = list(packet())
        args[0]['passage_session']['identity_packet'] = {'pending': True}
        self.assertIsNone(propose(*args))
        args = list(packet())
        args[2]['m6']['cm_page']['candidates'][0]['review_complete'] = False
        self.assertIsNone(propose(*args))
        args = list(packet())
        args[2]['m6']['query_review']['query_id'] = 'stale'
        self.assertIsNone(propose(*args))
        args = list(packet())
        args[3]['anyOf'][0]['properties']['args']['properties']['page_ref']['enum'].append('previous')
        self.assertIsNone(propose(*args))
        args = list(packet())
        args[2]['available_tools'].append({'name': 'open_candidate_passages'})
        self.assertIsNone(propose(*args))
