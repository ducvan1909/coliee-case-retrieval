"""Independent regressions for source-free warmup HTTP conflict handling."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from knowledge_base.pipeline_v1.au_only.core import warmup


TOKEN = "warmup-token-must-not-persist"
PRIVATE_BODY = "PRIVATE_PROVIDER_BODY_must_not_persist"


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return json.dumps(self.body).encode("utf-8")


def _busy(detail="Inference busy"):
    body = json.dumps({"detail": detail, "provider_debug": PRIVATE_BODY}).encode()
    return HTTPError("https://provider.invalid", 409, "Conflict", {}, io.BytesIO(body))


def _success():
    return _Response({"choices": [{"finish_reason": "stop"}], "usage": {"total_tokens": 1}})


def _config():
    return {"url": "https://provider.invalid", "token": TOKEN,
            "model": "local-test", "enable_thinking": False}


def _policy(**overrides):
    return {"max_attempts": 4, "max_wait_seconds": 20,
            "initial_backoff_seconds": 1, "max_backoff_seconds": 4,
            **overrides}


class WarmupBusyRegressionTests(unittest.TestCase):
    def run_warmup(self, opener, policy=None, *, clock=None, sleeps=None, root=None):
        if root is None:
            self.temp = tempfile.TemporaryDirectory()
            root = self.temp.name
        clock = clock if clock is not None else [0.0]
        sleeps = sleeps if sleeps is not None else []

        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        result = warmup(_config(), policy or _policy(), root, opener=opener,
                        sleep_fn=sleep, time_fn=lambda: clock[0])
        artifact = Path(root) / "warmup.json"
        persisted = artifact.read_text(encoding="utf-8")
        self.addCleanup(self.temp.cleanup) if hasattr(self, "temp") else None
        return result, persisted, sleeps

    def test_busy_409_with_prefixed_detail_retries_then_succeeds(self):
        for detail in ("Inference busy", "Inference busy; poll jobs or try probe later"):
            with self.subTest(detail=detail):
                calls = []

                def opener(*_args, **_kwargs):
                    calls.append(True)
                    if len(calls) == 1:
                        raise _busy(detail)
                    return _success()

                result, persisted, sleeps = self.run_warmup(opener)

                self.assertEqual(result["status"], "success")
                self.assertEqual(len(calls), 2)
                self.assertEqual(sleeps, [1])
                busy_attempt = result["attempts"][0]
                self.assertEqual(busy_attempt["code"], 409)
                self.assertTrue(busy_attempt["retryable"])
                self.assertEqual(busy_attempt["diagnostic"], "inference_busy")
                self.assertNotIn(TOKEN, persisted)
                self.assertNotIn(PRIVATE_BODY, persisted)

    def test_other_409_json_detail_is_terminal_and_body_is_not_logged_or_saved(self):
        calls = []

        def opener(*_args, **_kwargs):
            calls.append(True)
            body = json.dumps({"detail": "Payload conflict", "debug": PRIVATE_BODY}).encode()
            raise HTTPError("https://provider.invalid", 409, "Conflict", {}, io.BytesIO(body))

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            result, persisted, _sleeps = self.run_warmup(opener)
        finally:
            root_logger.removeHandler(handler)
            handler.close()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(calls), 1)
        self.assertFalse(result["attempts"][0]["retryable"])
        self.assertEqual(result["attempts"][0]["diagnostic"], "http_error")
        self.assertNotIn(TOKEN, persisted + stream.getvalue())
        self.assertNotIn(PRIVATE_BODY, persisted + stream.getvalue())

    def test_409_detail_with_unapproved_busy_prefix_is_terminal(self):
        calls = []

        def opener(*_args, **_kwargs):
            calls.append(True)
            raise _busy("Inference busy; backend is still starting")

        result, _persisted, sleeps = self.run_warmup(opener)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])
        self.assertFalse(result["attempts"][0]["retryable"])
        self.assertEqual(result["attempts"][0]["diagnostic"], "http_error")

    def test_busy_retry_obeys_attempt_cap(self):
        calls = []

        def opener(*_args, **_kwargs):
            calls.append(True)
            raise _busy()

        result, _persisted, sleeps = self.run_warmup(opener, _policy(max_attempts=2))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(sleeps, [1])

    def test_busy_retry_does_not_start_an_attempt_after_deadline(self):
        calls = []

        def opener(*_args, **_kwargs):
            calls.append(True)
            raise _busy()

        result, _persisted, sleeps = self.run_warmup(
            opener, _policy(max_attempts=4, max_wait_seconds=1))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(sleeps, [1])

    def test_each_provider_timeout_is_capped_by_remaining_deadline(self):
        calls = []
        clock = [0.0]

        def opener(_request, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                clock[0] = 0.4
                raise _busy("Inference busy")
            return _success()

        result, _persisted, _sleeps = self.run_warmup(
            opener,
            _policy(max_wait_seconds=1, initial_backoff_seconds=0),
            clock=clock,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], 1)
        self.assertAlmostEqual(calls[1], 0.6)

    def test_milestone1_cli_maps_warmup_and_probe_failures_to_static_codes(self):
        import contextlib
        import io as text_io
        import sys
        from unittest.mock import patch

        from knowledge_base.pipeline_v1.milestone1 import __main__ as cli

        manifest = {"requests": [], "milestone1": {}}
        for runtime_error, safe_code in (
            ("compact warmup failed before source dispatch", "warmup_failed_before_source_dispatch"),
            ("compact schema probe failed before source dispatch", "schema_probe_failed_before_source_dispatch"),
        ):
            with self.subTest(safe_code=safe_code):
                stream = text_io.StringIO()
                with patch.object(sys, "argv", ["milestone1", "run", "--execute", "--preflight", "unused"]), \
                     patch.object(cli, "load", return_value=manifest), \
                     patch.object(cli, "settings", return_value={}), \
                     patch.object(cli, "load_au_runtime_config", return_value=(
                         {"url": "https://provider.invalid", "token": TOKEN, "model": "local"}, {}, {})), \
                     patch("knowledge_base.pipeline_v1.milestone1.runtime.run",
                           side_effect=RuntimeError(runtime_error)), \
                     contextlib.redirect_stdout(stream):
                    code = cli.main()

                output = stream.getvalue()
                self.assertEqual(code, 2)
                self.assertIn(f"MILESTONE1 ERROR {safe_code}", output)
                if safe_code == "warmup_failed_before_source_dispatch":
                    self.assertIn("Warmup report:", output)
                self.assertNotIn(runtime_error, output)
                self.assertNotIn(TOKEN, output)

    def test_oversized_409_body_is_not_classified_as_busy(self):
        calls = []

        def opener(*_args, **_kwargs):
            calls.append(True)
            body = json.dumps({"detail": "Inference busy"}).encode() + b" " * 5000
            raise HTTPError("https://provider.invalid", 409, "Conflict", {}, io.BytesIO(body))

        result, persisted, _sleeps = self.run_warmup(opener)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(calls), 1)
        self.assertFalse(result["attempts"][0]["retryable"])
        self.assertNotIn(TOKEN, persisted)
        self.assertNotIn(PRIVATE_BODY, persisted)


if __name__ == "__main__":
    unittest.main()
