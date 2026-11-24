"""Descriptor contract checks, including the decision-specific selector sets."""
from copy import deepcopy
import unittest

from jsonschema import Draft202012Validator

from pipeline_v2.agent_harness.contracts import encode
from pipeline_v2.experiments.context_manager_v2 import source_gate
from pipeline_v2.experiments.context_manager_v2.catalog_descriptor import compact


def survey_payload(limit=3):
    segments = {'positive': {'proposition_selectable': True},
                'remaining': {'proposition_selectable': False, 'negative_only': True}}
    variants = [{'type': 'object', 'properties': fields, 'required': required,
                 'additionalProperties': False}
                for fields, required in source_gate.bound_assessment_variants(['p1'], segments)]
    fields = {'items': {'type': 'array', 'minItems': 1, 'maxItems': limit, 'items': {'anyOf': variants}}}
    tools = [{'name': 'assess_source_need', 'description': 'Existing single-item route.',
              'parameters': deepcopy(variants[0])},
             {'name': 'assess_source_needs', 'parameters': {'type': 'object', 'properties': fields,
              'required': ['items'], 'additionalProperties': False}}]
    return {'max_output_tokens': 1024, 'available_tools': tools,
            'excerpts': [{'ref': 'source', 'text': 'Original evidence is preserved.'}],
            'm6': {'source_gate_segments': segments, 'cm_context': {'mode': 'query_leaf'}}}


class CatalogDescriptorTests(unittest.TestCase):
    def test_all_seven_branches_keep_their_selector_and_ref_scope(self):
        before = survey_payload()
        saved = encode(before)
        result = compact(before, 'compact_catalog_v1')
        self.assertEqual(encode(before), saved)
        self.assertEqual(result['excerpts'], before['excerpts'])
        self.assertEqual(result['m6'], before['m6'])
        self.assertEqual(result['available_tools'][0], before['available_tools'][0])
        original = before['available_tools'][1]['parameters']['properties']['items']['items']['anyOf']
        self.assertEqual(len(original), 7)
        item = result['available_tools'][1]['parameters']['properties']['items']['items']
        self.assertNotIn('anyOf', item)
        for branch in original:
            props = branch['properties']
            rule = item['decision_rules'][props['decision']['enum'][0]]
            selector = [key for key in ('proposition_ref', 'proposition_quote') if key in props]
            self.assertIn(selector, rule['selector_options'])
            if selector == ['proposition_ref']:
                self.assertEqual(rule['proposition_ref_choices'], props['proposition_ref']['enum'])
        self.assertNotIn('remaining', item['decision_rules']['search_needed']['proposition_ref_choices'])
        self.assertIn('remaining', item['decision_rules']['no_search_needed']['proposition_ref_choices'])
        self.assertIn([], item['decision_rules']['need_more_context']['selector_options'])

    def test_batch_recovery_limits_and_original_decoder_reject_invalid_selectors(self):
        for limit in (3, 2, 1):
            payload = survey_payload(limit)
            result = compact(payload, 'compact_catalog_v1')
            self.assertEqual(result['available_tools'][1]['parameters']['properties']['items']['maxItems'], limit)
            validator = Draft202012Validator(payload['available_tools'][1]['parameters'])
            args = {'paragraph_ref': 'p1', 'decision': 'no_search_needed', 'attribution': 'court',
                    'reason_code': 'facts', 'reason': 'The exact displayed source span is assessed.',
                    'context_complete': True, 'proposition_ref': 'remaining'}
            self.assertTrue(validator.is_valid({'items': [args]}))
            self.assertFalse(validator.is_valid({'items': [{**args, 'proposition_quote': 'literal'}]}))
            self.assertFalse(validator.is_valid({'items': [{**args, 'decision': 'search_needed'}]}))
            self.assertFalse(validator.is_valid({'items': [args] * (limit + 1)}))

    def test_full_and_non_batch_payloads_keep_the_existing_api(self):
        payload = survey_payload()
        self.assertIs(compact(payload), payload)
        payload['available_tools'] = [{'name': 'conclude_candidate'}]
        self.assertEqual(compact(payload, 'compact_catalog_v1'), payload)
        with self.assertRaises(ValueError):
            compact(payload, 'unknown')
