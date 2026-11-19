"""Regressions for CM4's compact model-facing projection."""
from copy import deepcopy
import json
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator

from pipeline_v2.experiments.context_manager_v2.tests import test_engine
from pipeline_v2.experiments.context_manager_v2.model_view import project, restore_action


class ModelViewTests(unittest.TestCase):
    @staticmethod
    def short_ref(aliases, canonical):
        return next(short for short, full in aliases.items() if full == canonical)

    def fixture(self):
        full_ref = 'a' * 64
        pair_ref = 'b' * 64
        lead_ref = 'qn-' + 'c' * 32
        need_ref = 'need-' + 'd' * 24
        excerpt = {
            'case_id': 'A.txt', 'ref': full_ref, 'span_bytes': [0, 46],
            'text': 'The court considered the notice requirement.\n',
            'text_sha256': 'e' * 64,
            'provenance': {'components': [{
                'unit_id': 'f' * 40, 'span_bytes': [0, 46], 'unit_kind': 'paragraph',
                'paragraph_role': 'current_case', 'handle': 'paragraph-000001',
                'role_evidence_refs': [],
            }]},
        }
        payload = {
            'query_id': 'Q.txt', 'query_source_hash': '1' * 64,
            'excerpts': [excerpt],
            'current_payload_source_refs': [full_ref],
            'm6': {
                'source_needs': {need_ref: {'source_need_id': need_ref, 'intent': 'notice',
                    'route': 'case_search', 'source_proposition': 'The query raises notice.',
                    'a_refs': [full_ref], 'private_host_note': 'do not expose'}},
                'a_paragraphs': {'A:paragraph-000001': {'case_id': 'A.txt',
                    'paragraph_handle': 'paragraph-000001', 'paragraph_coverage': 'complete',
                    'preview': 'The court considered notice.', 'source_ref': full_ref,
                    'binding': {'raw_path': 'private'}}},
                'candidates': {'B.txt': {'case_id': 'B.txt', 'open_ref': '2' * 64,
                    'leads': [{'description': {'candidate_ref': '2' * 64,
                        'lead_ref': lead_ref, 'text': 'Relevant passage'},
                        'binding': {'raw_path': 'private'}, 'channel_ranks': {'dense': 1}}]}},
                'retrieved_passages': {lead_ref: {'description': {'candidate_ref': '2' * 64,
                    'lead_ref': lead_ref, 'text': 'Relevant passage'},
                    'binding': {'raw_path': 'private'}}},
                'pair_refs': {pair_ref: {'candidate_id': 'B.txt', 'source_need_id': need_ref,
                    'a_context_refs': [full_ref], 'b_passage_refs': [lead_ref]}},
                'cm_page': {'controls': {'page': '3' * 64}, 'candidates': []},
                'private_host_field': {'source_hash': '4' * 64},
            },
        }
        schema = {'type': 'object', 'properties': {'action': {'const': 'assess_case_link'},
            'args': {'type': 'object', 'properties': {
                'pair_ref': {'type': 'string', 'enum': [pair_ref]},
                'identity_support_refs': {'type': 'array', 'uniqueItems': True,
                    'items': {'type': 'string', 'enum': [full_ref]}},
                'reason': {'type': 'string'},
                'speaker_evidence_refs': {'type': 'array', 'uniqueItems': True,
                    'items': {'type': 'string', 'enum': [full_ref]}},
            }, 'required': ['pair_ref', 'reason']}}}
        return payload, schema, {'excerpt': full_ref, 'pair': pair_ref, 'lead': lead_ref,
                                 'need': need_ref, 'page': '3' * 64}

    def test_projection_keeps_raw_text_and_host_canonical_objects_unchanged(self):
        payload, schema, refs = self.fixture()
        before_payload, before_schema = deepcopy(payload), deepcopy(schema)
        wire, wire_schema, aliases = project(payload, schema)

        self.assertEqual(payload, before_payload)
        self.assertEqual(schema, before_schema)
        self.assertEqual(wire['excerpts'][0]['text'].encode('utf-8'),
                         before_payload['excerpts'][0]['text'].encode('utf-8'))
        pair_short = self.short_ref(aliases, refs['pair'])
        excerpt_short = self.short_ref(aliases, refs['excerpt'])
        self.assertEqual(wire_schema['properties']['args']['properties']['pair_ref']['enum'], [pair_short])
        self.assertEqual(wire['m6']['pair_refs'][pair_short]['a_context_refs'], [excerpt_short])
        # Provenance remains canonical in the host copy, while the model sees only
        # compact structural cues and no hashes/raw host bindings.
        self.assertEqual(payload['excerpts'][0]['provenance']['components'][0]['unit_id'], 'f' * 40)
        visible = json.dumps(wire, ensure_ascii=False)
        self.assertNotIn('text_sha256', visible)
        self.assertNotIn('source_hash', visible)
        self.assertNotIn('raw_path', visible)
        self.assertNotIn('binding', visible)
        self.assertNotIn('provenance', visible)
        self.assertNotIn('private_host_note', visible)

    def test_restore_only_reference_arguments_not_free_text_that_matches_alias(self):
        payload, schema, refs = self.fixture()
        wire, wire_schema, aliases = project(payload, schema)
        marker = self.short_ref(aliases, refs['excerpt'])
        action = {'action': 'assess_case_link', 'args': {
            'pair_ref': self.short_ref(aliases, refs['pair']),
            'identity_support_refs': [marker],
            'speaker_evidence_refs': [marker],
            'reason': f'The opaque reference text {marker} is quoted here.',
        }}
        restored = restore_action(action, aliases)
        self.assertEqual(restored['args']['pair_ref'], refs['pair'])
        self.assertEqual(restored['args']['identity_support_refs'], [refs['excerpt']])
        self.assertEqual(restored['args']['speaker_evidence_refs'], [refs['excerpt']])
        self.assertEqual(restored['args']['reason'], action['args']['reason'])
        self.assertTrue(Draft202012Validator(wire_schema).is_valid(action))

    def test_duplicate_and_cross_side_refs_are_rejected_before_restore(self):
        payload, schema, refs = self.fixture()
        _, wire_schema, aliases = project(payload, schema)
        invalid = {'action': 'assess_case_link', 'args': {
            'pair_ref': self.short_ref(aliases, refs['pair']), 'reason': 'A reason.',
            'identity_support_refs': [self.short_ref(aliases, refs['excerpt']),
                                      self.short_ref(aliases, refs['excerpt'])],
        }}
        # restore_action is not a validator; it cannot make a malformed or duplicate
        # reference valid. The issued schema rejects the duplicate before restore.
        self.assertFalse(Draft202012Validator(wire_schema).is_valid(invalid))
        invalid_side = {'action': 'assess_case_link', 'args': {
            'pair_ref': self.short_ref(aliases, refs['pair']), 'reason': 'A reason.',
            'identity_support_refs': [self.short_ref(aliases, refs['lead'])],
        }}
        self.assertFalse(Draft202012Validator(wire_schema).is_valid(invalid_side))
        restored = restore_action({'action': 'read_query_passages', 'args': {'query_ref': 'invented-ref'}}, aliases)
        self.assertEqual(restored['args']['query_ref'], 'invented-ref')

    def test_compact_wire_runs_search_assessment_and_navigation_with_canonical_host_refs(self):
        helper = test_engine.EngineTests()
        with TemporaryDirectory() as directory:
            engine, raw = helper.make(directory)
            searched = engine.step(lambda prepared: helper.action(prepared, 'search_cases_by_issue'))
            self.assertEqual(searched['status'], 'ready')
            search_start = next(row for row in reversed(engine.events()) if row['kind'] == 'action_started')
            self.assertTrue(search_start['action']['args']['_m6_need']['a_refs'])

            read = engine.step(lambda prepared: helper.action(prepared, 'read_case_passages'))
            self.assertEqual(read['status'], 'ready')
            assessed = engine.prepare()
            source_admission = engine.state().requests[assessed['request_id']]
            canonical_rows = source_admission['excerpts']
            self.assertTrue(any('text_sha256' in row and 'provenance' in row for row in canonical_rows))
            for row in canonical_rows:
                left, right = row['span_bytes']
                self.assertEqual(row['text'].encode('utf-8'), raw[row['case_id']][left:right])

            wire_text = source_admission['payload']
            self.assertNotIn('text_sha256', wire_text)
            self.assertNotIn('"provenance"', wire_text)
            manifest = assessed['manifest']
            dispatch = manifest['dispatch_m6']
            self.assertTrue(dispatch.get('pair_refs'))
            canonical_pair = next(iter(dispatch['pair_refs']))
            short_pair = next(short for short, full in manifest['wire_aliases'].items()
                              if full == canonical_pair)
            self.assertIn(short_pair, json.loads(wire_text)['m6']['pair_refs'])

            self.assertEqual(assessed['status'], 'ready')
            sides = assessed['payload']['m6']['assessment_ref_sides']
            self.assertEqual(set(sides), {'query case', 'candidate case'})
            tool = next(tool for tool in assessed['payload']['available_tools'] if tool['name'] == 'assess_case_link')
            self.assertIn('Set speaker.side to "query case"', tool['when'])
            action = helper.action(assessed, 'assess_case_link')
            action['args']['identity_support_choice'] = 'query case'
            validator = Draft202012Validator(manifest['schema'])
            self.assertTrue(validator.is_valid(action))
            old_action = deepcopy(action)
            old_action['args']['identity_support_choice'] = 'A'
            self.assertFalse(validator.is_valid(old_action))
            engine.reply(assessed['request_id'], action)
            assessment = engine.state().pending_action['action']
            self.assertEqual(assessment['action'], 'assess_links')
            for field in ('a_context_refs', 'b_passage_refs'):
                self.assertEqual(assessment['args']['assessments'][0][field],
                                 dispatch['pair_refs'][canonical_pair][field])
            self.assertEqual(assessment['args']['assessments'][0]['identity_support_refs'],
                             dispatch['pair_refs'][canonical_pair]['a_context_refs'])
            self.assertEqual(engine.state().last_receipt['schema_validation'], 'passed')

            # Commit the assessment, then exercise an ordinary page-navigation
            # choice through the compact schema and verify its host handle resolves.
            engine.execute_pending()
            navigation = engine.prepare()
            branches = navigation['manifest']['schema']['anyOf']
            names = {branch['properties']['action']['const'] for branch in branches}
            self.assertIn('show_context_page', names)
            page_action = helper.action(navigation, 'show_context_page')
            page_short = page_action['args']['page_ref']
            page_manifest = navigation['manifest']
            self.assertIn(page_short, page_manifest['wire_aliases'])
            engine.reply(navigation['request_id'], page_action)
            restored_page = engine.state().pending_action['action']['args']['page_ref']
            self.assertEqual(restored_page, page_manifest['wire_aliases'][page_short])
            engine.execute_pending()
            self.assertEqual(engine.context()['mode'], page_manifest['handles'][restored_page]['mode'])


if __name__ == '__main__':
    unittest.main()
