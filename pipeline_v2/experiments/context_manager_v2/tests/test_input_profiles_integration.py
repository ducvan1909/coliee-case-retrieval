"""Engine-level experimental profiles: same packets, frozen prompts, durable navigation."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pipeline_v2.agent_harness.contracts import encode
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.prompt_profiles import InputPolicy
from pipeline_v2.experiments.context_manager_v2 import query_review
from pipeline_v2.experiments.context_manager_v2.tests import test_passage_review as fixtures
from pipeline_v2.tests import test_m4_modal_qwen as transport_fixtures


class InputProfilesIntegrationTests(unittest.TestCase):
    def test_compact_profile_keeps_legacy_packet_decoder_and_freezes_admission(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            transport = transport_fixtures.ModalQwenTransportTests().build_transport(
                root, lambda: self.fail('No remote calls'))
            # Deliberate lightweight counter for protocol tests; production-token
            # gains are separately measured with the actual pinned tokenizer.
            transport._count_prompt = lambda prompt: len(prompt.encode('utf-8')) // 8 + 1
            engine, _ = fixtures.PassageReviewTests().make_engine(root / 'session')
            engine.survey_first = True
            engine.harness.count_tokens = transport.count_tokens
            baseline = engine.prepare(admit=False)
            before = engine.state().snapshot()
            engine.input_policy = InputPolicy(transport, catalog_profile='compact_catalog_v1',
                                              instruction_profile='phase_instructions_v1')
            preview = engine.prepare(admit=False)
            for key in ('excerpts', 'coverage', 'dispatch_m6', 'wire_aliases', 'schema'):
                self.assertEqual(preview['manifest'][key], baseline['manifest'][key], key)
            self.assertEqual(before, engine.state().snapshot())
            spec = preview['manifest']['cm_prompt_spec']
            self.assertEqual(spec['profile_id'], 'source_survey')
            self.assertEqual(spec['input_tokens'], preview['input_tokens'])
            transport.verify_frozen_request(encode(preview['payload']), preview['manifest']['schema'], spec)
            admitted = engine.prepare()
            self.assertEqual(admitted['payload'], preview['payload'])
            event = engine._events()[-1]
            self.assertEqual(event['cm_prompt_spec'], spec)
            self.assertTrue(event['cm_scripted_offline'])

    def test_auto_candidate_page_is_preview_only_until_real_admission_and_receipt(self):
        fixture = fixtures.PassageReviewTests()
        with TemporaryDirectory() as directory:
            engine, _ = fixture.make_engine(directory, page_size=1)
            engine.identity_check_enabled = True
            fixture.start(engine)
            engine.survey_first = True
            opened, _ = fixture.survey_then_open(engine, 'B_A')
            engine.step({'action': 'conclude_candidate', 'args': fixture.conclusion(opened, 'not_select')})
            before = engine.state().usage()
            engine.deterministic_candidate_paging = True
            preview = engine.prepare(admit=False)
            self.assertEqual(engine.context()['passage_session']['survey_offset'], 0)
            self.assertEqual(engine.state().usage(), before)
            self.assertEqual(preview['payload']['m6']['cm_page']['candidates'][0]['case_id'], 'B_B')
            admitted = engine.prepare()
            self.assertEqual(admitted['payload'], preview['payload'])
            self.assertEqual(engine.context()['passage_session']['survey_offset'], 1)
            self.assertIn('cm_auto_candidate_view', engine._events()[-1])
            query = query_review.active(engine._events(), engine.context())
            self.assertNotIn('B_B', query['survey_exposed'])
            engine.reply(admitted['request_id'], choose(admitted, 'open_candidate_passages'))
            query = query_review.active(engine._events(), engine.context())
            self.assertIn('B_B', query['survey_exposed'])
            actions = [e['action']['action'] for e in engine._events() if e['kind'] == 'action_started']
            self.assertNotIn('show_context_page', actions)
