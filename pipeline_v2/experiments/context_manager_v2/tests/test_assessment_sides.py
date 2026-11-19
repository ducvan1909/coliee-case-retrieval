"""Exercise the assessment options issued by the CM4 engine."""
from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator

from pipeline_v2.agent_harness import RunIdentity
from pipeline_v2.agent_harness.selection import select_supported_cases, selector_fingerprint
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.engine import Engine
from pipeline_v2.experiments.context_manager_v2.tests.test_source_gate import screen
from pipeline_v2.m6 import AdaptiveConfig
from pipeline_v2.tests.test_m6_adaptive import Tools


class AssessmentSideTests(unittest.TestCase):
    def test_model_attribution_and_supported_label_drive_current_cm4_prediction(self):
        with TemporaryDirectory() as directory:
            tools = Tools()
            tools.query_paragraphs = ({'handle': 'p000001', 'span_bytes': tools.a.span_bytes},)
            sources = {row.case_id: row for row in (tools.a, tools.b)}
            engine = Engine(directory, identity=RunIdentity('model-judgments', 'A', tools.a.source_hash,
                'cases', 'index', 'profile', 'model', 'prompt', 'tools', 'tokenizer'),
                tools=tools, config=AdaptiveConfig(channel='case_bm25'), count_tokens=lambda body: len(body) // 6 + 100,
                raw_reader=lambda case: sources[case].text.encode(), gate_enabled=True,
                selector=select_supported_cases, selector_fingerprint=selector_fingerprint())
            engine.step(lambda p: screen(p, tools.a.text))
            engine.step(lambda p: choose(p, 'search_cases_by_issue', issue='procedural fairness',
                                         source_proposition='The model considers procedural fairness.'))
            engine.step(lambda p: choose(p, 'open_retrieved_passage'))
            prepared = engine.prepare()
            refs = {row['case_id']: row['ref'] for row in prepared['payload']['excerpts']}
            validator = Draft202012Validator(prepared['manifest']['schema'])
            speaker = {'role': 'quoted_source', 'type': 'quotation', 'side': 'query case'}
            action = choose(prepared, 'assess_case_link', case_relation='supported', passage_location='bounded',
                            reason='The model identifies the candidate as a source.', speaker=speaker)
            self.assertTrue(validator.is_valid(action))
            action['args']['speaker_evidence_refs'] = [refs['B']]
            self.assertFalse(validator.is_valid(action))
            action['args']['speaker_evidence_refs'] = [refs['A']]
            self.assertTrue(validator.is_valid(action))
            engine.reply(prepared['request_id'], action)
            engine.execute_pending()
            assessment, = engine.state().assessments.values()
            self.assertEqual(assessment['speaker']['role'], 'quoted_source')
            self.assertEqual(assessment['case_relation'], 'supported')
            self.assertEqual(assessment['identity_support_refs'], [])
            engine.step(lambda p: choose(p, 'finish_case_review', reason='complete_policy'))
            self.assertEqual(engine.state().final['prediction'], ['B'])
            self.assertEqual(engine.state().final['prediction_assessment_ids'], [assessment['assessment_id']])

    def test_schema_and_host_agree_for_side_specific_fields(self):
        with TemporaryDirectory() as directory:
            tools = Tools()
            for side in ('a', 'b'):
                row = getattr(tools, side)
                setattr(tools, side, replace(row, provenance={'components': [{
                    'unit_id': side, 'span_bytes': list(row.span_bytes), 'unit_kind': 'paragraph', 'paragraph_role': 'current_case'
                }]}))
            sources = {row.case_id: row for row in (tools.a, tools.b)}
            engine = Engine(directory, identity=RunIdentity('side-test', 'A', tools.a.source_hash,
                'cases', 'index', 'profile', 'model', 'prompt', 'tools', 'tokenizer'),
                tools=tools, config=AdaptiveConfig(channel='case_bm25'), count_tokens=lambda body: len(body) // 6 + 100,
                raw_reader=lambda case: sources[case].text.encode())
            engine.step(lambda p: choose(p, 'search_cases_by_issue', issue='procedural fairness',
                                         source_proposition='A asks about a procedural rule.'))
            engine.step(lambda p: choose(p, 'open_retrieved_passage'))
            prepared = engine.prepare()
            schema = prepared['manifest']['schema']
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            refs = {row['case_id']: row['ref'] for row in prepared['payload']['excerpts']}
            base = {'pair_ref': next(iter(prepared['payload']['m6']['pair_refs'])),
                    'case_relation': 'unknown', 'passage_location': 'bounded', 'reason': 'Assess the current pair.'}

            def action(**args):
                return {'action': 'assess_case_link', 'args': {**base, **args}}

            pair_ref = base['pair_ref']
            options = prepared['payload']['m6']['assessment_attribution_options'][pair_ref]
            self.assertTrue(any(row['role'] == 'unknown' for row in options))
            self.assertFalse(any(row['role'] == 'court' and row.get('type') == 'adopted_reasoning'
                                 for row in options))
            self.assertFalse(any(row['role'] == 'quoted_source' for row in options))

            own = next(row for row in options if row['role'] == 'court' and row['type'] == 'own_reasoning')
            own_action = action(speaker={'role': 'court', 'type': 'own_reasoning', 'side': own['side']},
                                speaker_evidence_refs=own['speaker_refs'])
            self.assertTrue(validator.is_valid(own_action))
            self.assertFalse(validator.is_valid(action(
                speaker={'role': 'court', 'type': 'adopted_reasoning', 'side': 'candidate case'},
                speaker_evidence_refs=[refs['B']], container_refs=[refs['B']], quote_chain_refs=[refs['B']])))
            for field in ('identity_support_choice', 'counterevidence_choice'):
                for choice in ('query case', 'candidate case', 'both cases'):
                    self.assertTrue(validator.is_valid(action(**{field: choice})))
                self.assertFalse(validator.is_valid(action(**{field: ['A', 'A']})))
            self.assertFalse(validator.is_valid(action(identity_support_refs=[refs['A'], refs['A']])))
            self.assertFalse(validator.is_valid(action(counterevidence=[refs['B'], refs['B']])))
            engine.reply(prepared['request_id'], action(container_refs=[refs['A'], refs['B']]))
            self.assertEqual(engine.state().last_receipt['status'], 'malformed')
            self.assertIsNone(engine.state().pending_action)
            self.assertEqual(engine.events()[-1]['kind'], 'run_stopped')


if __name__ == '__main__':
    unittest.main()
