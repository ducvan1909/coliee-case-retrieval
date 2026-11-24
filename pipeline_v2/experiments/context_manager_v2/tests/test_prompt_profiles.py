"""Exact prompt/spec accounting and phase selection, without remote execution."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from pipeline_v2.agent_harness.contracts import encode, HarnessError, TransportError
from pipeline_v2.experiments.context_manager_v2.prompt_profiles import InputPolicy, phase_for, registry, RECOVERY
from pipeline_v2.experiments.context_manager_v2.tests.test_catalog_descriptor import survey_payload
from pipeline_v2.tests import test_m4_modal_qwen as transport_fixtures


class PromptProfileTests(unittest.TestCase):
    def test_frozen_prompt_is_used_after_global_instructions_change_and_rejects_tampering(self):
        with TemporaryDirectory() as directory:
            call = transport_fixtures.FakeModalCall()
            spawn = Mock(return_value=call)
            helper = transport_fixtures.ModalQwenTransportTests()
            transport = helper.build_transport(Path(directory), lambda: SimpleNamespace(generate=SimpleNamespace(spawn=spawn)))
            body, schema = helper.payload('original legal source'), {'type': 'object'}
            spec = transport.freeze_request(body, schema, instructions='Frozen phase rules.', profile_id='identity_only')
            expected_prompt, tokens = transport.verify_frozen_request(body, schema, spec)
            transport._instructions = 'A different phase must not replace admitted instructions.'
            call.result = {**helper.result(transport, body), 'input_tokens': tokens}
            reply = transport.send_frozen(body, 'frozen-request', schema, spec)
            self.assertEqual(reply.input_tokens, tokens)
            self.assertEqual(spawn.call_args.args[0], expected_prompt)
            self.assertEqual(transport.receipts[-1]['prompt_profile_id'], 'identity_only')
            broken = deepcopy(spec)
            broken['instructions'] = 'Changed after admission.'
            with self.assertRaises(TransportError):
                transport.send_frozen(body, 'bad-request', schema, broken)
            self.assertEqual(spawn.call_count, 1)
            self.assertFalse(transport.receipts[-1]['submission_attempted'])

    def test_input_policy_preserves_packet_schema_and_adds_real_batch_recovery_guidance(self):
        with TemporaryDirectory() as directory:
            transport = transport_fixtures.ModalQwenTransportTests().build_transport(Path(directory), lambda: self.fail('No remote'))
            payload = survey_payload(limit=1)
            schema = deepcopy(payload['available_tools'][1]['parameters'])
            original = encode(payload), encode(schema)
            policy = InputPolicy(transport, catalog_profile='compact_catalog_v1',
                                 instruction_profile='phase_instructions_v1', frozen_registry=registry())
            rendered, tokens, spec = policy.prepare(payload, schema, max_payload_tokens=20000)
            self.assertEqual((encode(payload), encode(schema)), original)
            self.assertEqual(rendered['excerpts'], payload['excerpts'])
            self.assertEqual(rendered['m6'], payload['m6'])
            self.assertIn(RECOVERY, spec['instructions'])
            self.assertEqual(tokens, transport.verify_frozen_request(encode(rendered), schema, spec)[1])
            detached = policy.registry
            detached['templates']['source_survey'] = 'mutated'
            self.assertNotEqual(policy.registry, detached)
            with self.assertRaises(HarnessError):
                InputPolicy(transport, frozen_registry=detached)
            with self.assertRaises(HarnessError):
                policy.prepare(payload, schema, max_payload_tokens=1)

    def test_identity_phase_only_for_a_single_frozen_conclusion_tool(self):
        p = {'m6': {'cm_context': {'mode': 'identity_check'}},
             'available_tools': [{'name': 'conclude_candidate'}]}
        self.assertEqual(phase_for(p), 'identity_only')
        p['available_tools'].append({'name': 'unknown_navigation'})
        self.assertEqual(phase_for(p), 'full')
        self.assertEqual(phase_for(survey_payload()), 'source_survey')
        p = {'m6': {'cm_context': {'mode': 'results'}},
             'available_tools': [{'name': 'show_context_page'}]}
        self.assertEqual(phase_for(p), 'candidate_list')
