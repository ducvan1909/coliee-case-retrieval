"""Offline acceptance-path checks for M4's Modal canary runner."""

import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pipeline_v2.agent_harness.contracts import ModelReply
from pipeline_v2.agent_harness.contracts import HarnessError, TransportError
from pipeline_v2.agent_harness.schema import validate_model_response, ResponseSchemaError
from pipeline_v2 import m4_live
from pipeline_v2.agent_harness import modal_qwen


class FixtureTransport:
    def __init__(self, tokenizer_dir, *, instructions):
        self.instructions = instructions
        self.prompt_fingerprint = "fixture-prompt-v1"
        self.tokenizer_fingerprint = "fixture-tokenizer-v1"
        self.requests = []
        self.receipts = []

    def count_tokens(self, payload):
        return len(payload)

    def send_structured(self, payload, request_id, schema):
        body = json.loads(payload)
        self.requests.append((request_id, body, schema))
        raw_ref = body["current_payload_source_refs"][0]
        reply = {
            "action": "assess_links",
            "args": {"assessments": [{
                "source_need_id": m4_live.PROBE_NEED,
                "candidate_id": m4_live.PROBE_CANDIDATE,
                "a_context_refs": [raw_ref],
                "b_passage_refs": [],
                "case_relation": "unknown",
                "passage_location": "unresolved",
                "reason": "No candidate passage is present in this synthetic probe.",
                "speaker": {"role": "unknown"},
            }]},
        }
        return ModelReply(reply, input_tokens=len(payload), output_tokens=36, latency_ms=50.0)


class M4ModalProbeRunnerTests(unittest.TestCase):
    def test_probe_runs_actual_harness_with_branch_schema_and_holds_missing_evidence(self):
        created = []

        def transport_factory(tokenizer_dir, *, instructions):
            transport = FixtureTransport(tokenizer_dir, instructions=instructions)
            created.append(transport)
            return transport

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "probe"
            with patch.object(m4_live, "ModalQwenTransport", transport_factory):
                result, checks = m4_live.probe(run_dir, Path(tmp) / "tokenizer")

        self.assertTrue(all(checks.values()), checks)
        self.assertEqual(len(created), 1)
        transport = created[0]
        self.assertEqual(len(transport.requests), 1)
        request_id, payload, schema = transport.requests[0]
        self.assertTrue(request_id)
        self.assertEqual(len(payload["current_payload_source_refs"]), 1)

        invalid = {
            "action": "assess_links",
            "args": {"assessments": [{
                "source_need_id": m4_live.PROBE_NEED,
                "candidate_id": m4_live.PROBE_CANDIDATE,
                "a_context_refs": payload["current_payload_source_refs"],
                "b_passage_refs": [],
                "case_relation": "unknown",
                "passage_location": "unresolved",
                "reason": "missing passage",
                "speaker": {"role": "unknown", "type": "own_reasoning"},
            }]},
        }
        with self.assertRaises(ResponseSchemaError):
            validate_model_response(invalid, tool_actions=())
        valid = {
            "action": "assess_links",
            "args": {"assessments": [{
                "source_need_id": m4_live.PROBE_NEED,
                "candidate_id": m4_live.PROBE_CANDIDATE,
                "a_context_refs": payload["current_payload_source_refs"],
                "b_passage_refs": [],
                "case_relation": "unknown",
                "passage_location": "unresolved",
                "reason": "missing passage",
                "speaker": {"role": "unknown"},
            }]},
        }
        self.assertTrue(validate_model_response(valid, tool_actions=()))
        speaker_branches = schema["anyOf"][0]["properties"]["args"]["properties"]["assessments"][
            "items"
        ]["properties"]["speaker"]["anyOf"]
        unknown_branch = next(branch for branch in speaker_branches
                              if branch["properties"]["role"]["const"] == "unknown")
        self.assertNotIn("type", unknown_branch["properties"])

        pending = result["pending_assessments"]
        self.assertEqual(result["assessment_validation"]["schema_passed_responses"], 1)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["speaker"], {"role": "unknown"})
        self.assertEqual(pending[0]["case_relation"], "unknown")
        self.assertFalse(pending[0]["b_passage_refs"])
        self.assertEqual(pending[0]["status"], "pending_evidence")
        self.assertEqual(result["active_assessment_ids"], [])
        self.assertEqual(result["usage"]["requests"], 1)
        self.assertEqual(result["usage"]["retries"], 0)
        self.assertEqual(result["usage"]["admitted_input_tokens"],
                         result["usage"]["reported_input_tokens"])
        self.assertEqual(result["usage"]["reported_output_tokens"], 36)

    def test_probe_uses_fresh_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "probe"
            run_dir.mkdir()
            with patch.object(m4_live, "ModalQwenTransport", FixtureTransport):
                with patch("sys.argv", ["m4_live", "probe", "--run-dir", str(run_dir),
                                        "--tokenizer-dir", str(Path(tmp) / "tokenizer")]):
                    with self.assertRaises(FileExistsError):
                        m4_live.main()


class FakeTokenizer:
    def no_truncation(self):
        pass

    def no_padding(self):
        pass

    def encode(self, text, *, add_special_tokens):
        return SimpleNamespace(ids=list(text.encode("utf-8")))


class FakeModalCall:
    object_id = "fc-test"

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.cancelled = False

    def get(self, *, timeout):
        if self.error is not None:
            raise self.error
        return self.result

    def cancel(self):
        self.cancelled = True


class ModalQwenTransportTests(unittest.TestCase):
    def test_lookup_hydrates_named_function_before_any_submission(self):
        method = unittest.mock.Mock()
        method.hydrate.return_value = method
        method.object_id = modal_qwen.MODAL_FUNCTION_ID
        remote = SimpleNamespace(generate=method)
        with patch.object(modal_qwen.modal.Cls, "from_name", return_value=lambda: remote) as lookup:
            self.assertIs(modal_qwen._load_qwen(), remote)
            lookup.assert_called_once_with(modal_qwen.APP_NAME, "Qwen")
            method.hydrate.assert_called_once_with()
            method.object_id = "fu-unexpected"
            with self.assertRaisesRegex(TransportError, "modal_function_mismatch"):
                modal_qwen._load_qwen()
        method.spawn.assert_not_called()

    def build_transport(self, temp_path, remote_factory, *, wait_seconds=30):
        values = {
            "tokenizer.json": b'{"fixture":true}',
            "chat_template.jinja": (
                b"{{ messages[0].content }}{% if add_generation_prompt %} "
                b"<|im_start|>assistant{% endif %}"
            ),
        }
        for name, raw in values.items():
            (temp_path / name).write_bytes(raw)
        hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in values.items()}
        with patch.object(modal_qwen, "ASSET_SHA256", hashes), patch.object(
            modal_qwen.Tokenizer, "from_str", return_value=FakeTokenizer()
        ):
            return modal_qwen.ModalQwenTransport(
                temp_path, instructions="fixture rules", remote_factory=remote_factory,
                wait_seconds=wait_seconds,
            )

    @staticmethod
    def payload(text="ok", cap=64):
        return json.dumps({"max_output_tokens": cap, "text": text}).encode()

    def result(self, transport, payload, *, text='{"action":"stop"}', output=4,
               finish="stop", gpu="NVIDIA L40S", revision=None):
        return {
            "text": text,
            "input_tokens": transport.count_tokens(payload),
            "output_tokens": output,
            "finish_reason": finish,
            "model": modal_qwen.MODEL,
            "revision": revision or modal_qwen.MODEL_REVISION,
            "vllm_version": modal_qwen.VLLM_VERSION,
            "gpu": gpu,
            "latency_seconds": 0.25,
        }

    def test_counts_exact_rendered_prompt_and_passes_schema_and_payload_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self.payload("naïve legal cue")
            call = FakeModalCall()
            remote = SimpleNamespace(generate=SimpleNamespace(spawn=unittest.mock.Mock(
                return_value=call,
            )))
            transport = self.build_transport(root, lambda: remote)
            call.result = self.result(transport, payload, text='{"action":"stop"}')
            prompt = transport.render_prompt(payload)
            self.assertIn("fixture rules", prompt)
            self.assertIn("na\\u00efve legal cue", prompt)
            self.assertEqual(transport.count_tokens(payload), len(
                (prompt + " <|im_start|>assistant").encode("utf-8")
            ))
            schema = {"type": "object", "properties": {"role": {"enum": ["unknown"]}}}
            reply = transport.send_structured(payload, "request-1", schema)
            remote.generate.spawn.assert_called_once_with(prompt, schema, 64)
            self.assertEqual(reply.input_tokens, transport.count_tokens(payload))
            self.assertEqual(reply.output_tokens, 4)
            self.assertEqual(reply.latency_ms, 250.0)
            self.assertEqual(reply.action, '{"action":"stop"}')
            self.assertEqual(transport.last_call_id, "fc-test")

    def test_rejects_oversize_prompt_or_output_cap_before_modal_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spawn = unittest.mock.Mock()
            remote = SimpleNamespace(generate=SimpleNamespace(spawn=spawn))
            transport = self.build_transport(root, lambda: remote)
            with self.assertRaises(HarnessError):
                transport.count_tokens(self.payload(cap=513))
            oversized = self.payload("x" * 8200, cap=512)
            with self.assertRaises(TransportError) as error:
                transport.send_structured(oversized, "request-2", {"type": "object"})
            self.assertEqual(str(error.exception), "modal_context_limit")
            spawn.assert_not_called()

    def test_failed_remote_result_is_not_retried_and_is_marked_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self.payload()
            call = FakeModalCall(error=TimeoutError("local wait ended"))
            spawn = unittest.mock.Mock(return_value=call)
            remote = SimpleNamespace(generate=SimpleNamespace(spawn=spawn))
            transport = self.build_transport(root, lambda: remote)
            with self.assertRaises(TransportError) as error:
                transport.send_structured(payload, "request-3", {"type": "object"})
            self.assertTrue(error.exception.unknown)
            spawn.assert_called_once()
            self.assertTrue(call.cancelled)
            self.assertEqual(transport.last_call_id, "fc-test")

    def test_modal_execution_timeout_is_terminal_and_keeps_unknown_usage_unestimated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self.payload()
            call = FakeModalCall(error=modal_qwen.modal.exception.FunctionTimeoutError(
                "remote function exceeded its time limit",
            ))
            spawn = unittest.mock.Mock(return_value=call)
            remote = SimpleNamespace(generate=SimpleNamespace(spawn=spawn))
            transport = self.build_transport(root, lambda: remote)

            with self.assertRaises(TransportError) as error:
                transport.send_structured(payload, "request-timeout", {"type": "object"})

            self.assertFalse(error.exception.unknown)
            spawn.assert_called_once()
            self.assertFalse(call.cancelled)
            receipt = transport.receipts[0]
            self.assertEqual(receipt["status"], "error")
            self.assertEqual(receipt["expected_input_tokens"], transport.count_tokens(payload))
            self.assertNotIn("output_tokens", receipt)
            self.assertNotIn("latency_ms", receipt)

    def test_truncation_and_runtime_mismatch_fail_closed_with_observed_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self.payload()
            transport = self.build_transport(root, lambda: None)
            for result in (
                self.result(transport, payload, finish="length"),
                self.result(transport, payload, gpu="NVIDIA L4"),
                self.result(transport, payload, revision="wrong-revision"),
            ):
                with self.subTest(result=result):
                    with self.assertRaises(TransportError) as error:
                        modal_qwen.ModalQwenTransport._model_reply(
                            result, transport.count_tokens(payload), 64, {},
                        )
                    self.assertEqual(error.exception.input_tokens,
                                     transport.count_tokens(payload))
                    self.assertEqual(error.exception.output_tokens, 4)


if __name__ == "__main__":
    unittest.main()
