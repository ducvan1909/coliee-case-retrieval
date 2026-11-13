"""Regression tests for M6's long-running Modal wait policy.

These are transport-level mocked tests. They do not make a Modal request.
"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pipeline_v2.agent_harness import modal_qwen
from pipeline_v2.agent_harness.contracts import TransportError


class _Tokenizer:
    def no_truncation(self):
        pass

    def no_padding(self):
        pass

    def encode(self, text, *, add_special_tokens):
        return SimpleNamespace(ids=list(text.encode("utf-8")))


class _Call:
    object_id = "fc-m6-wait-test"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.timeouts = []
        self.cancelled = False

    def get(self, *, timeout):
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def cancel(self):
        self.cancelled = True


class M6ModalWaitPolicyTests(unittest.TestCase):
    @staticmethod
    def _payload():
        return json.dumps({"max_output_tokens": 64, "text": "fixture"}).encode()

    def _transport(self, root, call, spawn):
        assets = {
            "tokenizer.json": b'{"fixture":true}',
            "chat_template.jinja": (
                b"{{ messages[0].content }}{% if add_generation_prompt %} "
                b"<|im_start|>assistant{% endif %}"
            ),
        }
        for name, raw in assets.items():
            (root / name).write_bytes(raw)
        hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in assets.items()}
        remote = SimpleNamespace(generate=SimpleNamespace(spawn=spawn))
        with patch.object(modal_qwen, "ASSET_SHA256", hashes), patch.object(
            modal_qwen.Tokenizer, "from_str", return_value=_Tokenizer()
        ):
            return modal_qwen.ModalQwenTransport(
                root,
                instructions="fixture rules",
                remote_factory=lambda: remote,
                wait_seconds=None,
            )

    def _success_result(self, transport):
        payload = self._payload()
        return {
            "text": '{"action":"stop"}',
            "input_tokens": transport.count_tokens(payload),
            "output_tokens": 4,
            "finish_reason": "stop",
            "model": modal_qwen.MODEL,
            "revision": modal_qwen.MODEL_REVISION,
            "vllm_version": modal_qwen.VLLM_VERSION,
            "gpu": "NVIDIA L40S",
            "latency_seconds": 0.25,
        }

    def test_pending_poll_timeout_continues_same_call_then_returns_result(self):
        with tempfile.TemporaryDirectory() as temp:
            call = _Call([TimeoutError("poll window elapsed"), None])
            spawn = Mock(return_value=call)
            transport = self._transport(Path(temp), call, spawn)
            call.outcomes[1] = self._success_result(transport)

            reply = transport.send_structured(
                self._payload(), "m6-request-1", {"type": "object"},
            )

            self.assertEqual(reply.action, '{"action":"stop"}')
            self.assertEqual(call.timeouts, [30, 30])
            spawn.assert_called_once()
            self.assertFalse(call.cancelled)
            self.assertEqual(transport.receipts[0]["call_id"], call.object_id)
            self.assertEqual(transport.receipts[0]["status"], "received")

    def test_remote_execution_timeout_is_terminal_without_resubmission(self):
        with tempfile.TemporaryDirectory() as temp:
            error = modal_qwen.modal.exception.FunctionTimeoutError(
                "remote function exceeded its execution limit",
            )
            call = _Call([error])
            spawn = Mock(return_value=call)
            transport = self._transport(Path(temp), call, spawn)

            with self.assertRaises(TransportError) as caught:
                transport.send_structured(
                    self._payload(), "m6-request-2", {"type": "object"},
                )

            self.assertEqual(str(caught.exception), "modal_execution_timeout")
            spawn.assert_called_once()
            self.assertEqual(call.timeouts, [30])
            self.assertFalse(call.cancelled)
            self.assertEqual(transport.receipts[0]["status"], "error")
            self.assertEqual(transport.receipts[0]["call_id"], call.object_id)

    def test_transient_result_connection_loss_reconnects_same_call(self):
        with tempfile.TemporaryDirectory() as temp:
            call = _Call([ConnectionError("temporary result connection loss"), None])
            spawn = Mock(return_value=call)
            transport = self._transport(Path(temp), call, spawn)
            call.outcomes[1] = self._success_result(transport)

            with patch.object(modal_qwen, "sleep") as sleep:
                reply = transport.send_structured(
                    self._payload(), "m6-request-reconnect", {"type": "object"},
                )

            self.assertEqual(reply.action, '{"action":"stop"}')
            self.assertEqual(call.timeouts, [30, 30])
            sleep.assert_called_once_with(modal_qwen.RESULT_RECONNECT_SECONDS)
            spawn.assert_called_once()
            self.assertFalse(call.cancelled)
            receipt = transport.receipts[0]
            self.assertEqual(receipt["connection_errors"], 1)
            self.assertEqual(receipt["call_id"], call.object_id)

    def test_keyboard_interrupt_stops_wait_without_cancel_or_duplicate_submission(self):
        with tempfile.TemporaryDirectory() as temp:
            call = _Call([KeyboardInterrupt()])
            spawn = Mock(return_value=call)
            transport = self._transport(Path(temp), call, spawn)

            with self.assertRaises(KeyboardInterrupt):
                transport.send_structured(
                    self._payload(), "m6-request-3", {"type": "object"},
                )

            spawn.assert_called_once()
            self.assertEqual(call.timeouts, [30])
            self.assertFalse(call.cancelled)
            self.assertEqual(transport.receipts[0]["status"], "unknown")
            self.assertEqual(transport.receipts[0]["call_id"], call.object_id)


if __name__ == "__main__":
    unittest.main()
