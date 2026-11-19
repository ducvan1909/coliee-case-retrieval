"""Regression for AG findings and context-dependent tool choices, offline only."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator, ValidationError
from pipeline_v2.experiments.context_manager_v1.core import Session, Config
from pipeline_v2.experiments.context_manager_v1.cli import synthetic


def counter(value):
    return len(value) // 6 + 100


def branches(page):
    return {branch['properties']['action']['const']: branch['properties']['args']['properties']
            for branch in page['manifest']['schema']['anyOf']}


class ContextRulesTests(unittest.TestCase):
    def test_pool_read_enum_only_current_need_and_cards_explain_eligibility(self):
        with TemporaryDirectory() as d:
            s = Session(d, synthetic(12), counter)
            p = s.compile('pool')
            fields = branches(p)['read_case_passages']
            expected = {ref for ref, target in p['manifest']['handles'].items()
                        if target['kind'] == 'candidate' and s.state()['focus']['need_id'] in target['canonical']['need_ids']}
            self.assertEqual(set(fields['candidate_ref']['enum']), expected)
            for card in p['view']['page']['cards']:
                self.assertEqual(card['read_allowed'], card['ref'] in expected)
                self.assertEqual(card['belongs_to_current_need'], card['ref'] in expected)
            for ref, target in p['manifest']['handles'].items():
                if target['kind'] == 'candidate' and ref not in expected:
                    with self.assertRaises(ValidationError):
                        Draft202012Validator(p['manifest']['schema']).validate({
                            'action': 'read_case_passages', 'args': {'candidate_ref': ref, 'focus': 'legal issue'}})

    def test_reading_focus_does_not_offer_other_B_or_other_need(self):
        with TemporaryDirectory() as d:
            s = Session(d, synthetic(12), counter)
            p = s.compile('results'); s.receipt(p['request_id'], 'success')
            ref = branches(p)['read_case_passages']['candidate_ref']['enum'][0]
            s.command(p['request_id'], {'action': 'read_case_passages', 'args': {'candidate_ref': ref, 'focus': 'legal issue'}})
            q = s.compile('candidates'); s.receipt(q['request_id'], 'success')
            self.assertNotIn('set_context_focus', branches(q))
            choices = branches(q).get('read_case_passages', {}).get('candidate_ref', {}).get('enum', [])
            self.assertEqual({q['manifest']['handles'][r]['case_id'] for r in choices}, {s.state()['focus']['candidate_id']})
            s.command(q['request_id'], {'action': 'record_missing_evidence', 'args': {'reason': 'Read more source reasoning'}})
            t = s.compile('needs')
            permitted = branches(t)['set_context_focus']['need_ref']['enum']
            self.assertTrue(permitted)
            self.assertTrue(all(t['manifest']['handles'][r]['need_id'] != s.state()['focus']['need_id'] for r in permitted))

    def test_previous_returns_actual_shrunk_page_across_resume(self):
        def shrink_counter(value):
            body = json.loads(value)
            return 100 + 350 * len(body.get('page', {}).get('cards', []))
        with TemporaryDirectory() as d:
            snap = synthetic(12)
            s = Session(d, snap, shrink_counter)
            page = s.compile('pool'); s.receipt(page['request_id'], 'success')
            self.assertEqual(page['view']['page']['count'], 2)
            page = s.compile('pool', page['view']['page']['controls']['next']); s.receipt(page['request_id'], 'success')
            self.assertEqual(page['view']['page']['start'], 2)
            page = s.compile('pool', page['view']['page']['controls']['next']); s.receipt(page['request_id'], 'success')
            self.assertEqual(page['view']['page']['start'], 4)
            s = Session(d, snap, shrink_counter)
            back = s.compile('pool', page['view']['page']['controls']['previous'])
            self.assertEqual(back['view']['page']['start'], 2)
            s.receipt(back['request_id'], 'success')
            root = s.compile('pool', back['view']['page']['controls']['previous'])
            self.assertEqual(root['view']['page']['start'], 0)

    def test_metrics_distinguish_current_context_from_need_list(self):
        with TemporaryDirectory() as d:
            s = Session(d, synthetic(12), counter)
            p = s.compile('results')
            self.assertEqual(p['view']['progress']['needs_context_delivered'], 0)
            s.receipt(p['request_id'], 'success')
            q = s.compile('needs')
            self.assertEqual(q['view']['progress']['needs_context_delivered'], 1)
            self.assertEqual(q['view']['progress']['need_list_items_delivered'], 0)
            s.receipt(q['request_id'], 'success')
            r = s.compile('pool')
            self.assertEqual(r['view']['progress']['need_list_items_delivered'], 3)

    def test_prompt_tools_have_guidance_and_schema_bound_choices(self):
        with TemporaryDirectory() as d:
            p = Session(d, synthetic(12), counter).compile('pool')
            available = branches(p)
            for tool in p['view']['context_actions']:
                self.assertIn(tool['name'], available)
                for field in ('description', 'when', 'result'):
                    self.assertTrue(tool.get(field))
                self.assertEqual(tool['parameters']['additionalProperties'], False)
                for name, parameter in tool['parameters']['properties'].items():
                    if 'enum' in available[tool['name']][name]:
                        self.assertTrue(parameter.get('choices_from'))

    def test_shared_rules_safe_stages_and_noop_need_removed(self):
        handles = {'page': {'kind': 'page'}, 'same': {'kind': 'need', 'need_id': 'n'},
                   'other': {'kind': 'need', 'need_id': 'm'},
                   'b': {'kind': 'candidate', 'case_id': 'B', 'need_id': 'n', 'canonical': {'need_ids': ['n']}},
                   'c': {'kind': 'candidate', 'case_id': 'C', 'need_id': 'n', 'canonical': {'need_ids': ['n']}},
                   'foreign': {'kind': 'candidate', 'case_id': 'X', 'need_id': 'n', 'canonical': {'need_ids': ['m']}}}
        for stage in ('ready', 'missing_evidence', 'assessed', 'error', 'no_hit', 'reading'):
            allowed = Session.allowed_actions(handles, {'stage': stage, 'candidate_id': 'B', 'need_id': 'n'})
            self.assertEqual(allowed['read_case_passages'], ['b'] if stage == 'reading' else ['b', 'c'])
            self.assertNotIn('foreign', allowed['read_case_passages'])
            if stage == 'reading':
                self.assertNotIn('set_context_focus', allowed)
                self.assertIn('record_missing_evidence', allowed)
            else:
                self.assertEqual(allowed['set_context_focus'], ['other'])
                self.assertNotIn('record_missing_evidence', allowed)


if __name__ == '__main__':
    unittest.main()
