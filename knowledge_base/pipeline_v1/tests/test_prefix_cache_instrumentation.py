"""Independent receipt-level checks for prefix-cache observations.

These tests exercise the provider adapter locally with a fake HTTP response;
they never contact an inference endpoint.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import io

from knowledge_base.pipeline_v1.au_compact import runner
from knowledge_base.pipeline_v1.concurrency_benchmark import core as benchmark


class FakeHTTP:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class PrefixCacheInstrumentationTests(unittest.TestCase):
    def call(self, body):
        request = {
            "request_id": "cache-observation-test",
            "expected_target_ids": ["target-1"],
            "spec": {"caps": {"output_tokens": 64}},
        }
        cfg = {"url": "https://provider.invalid/v1/chat/completions",
               "token": "test-secret", "model": "test-model"}
        catalog = {"atoms": {"atom-1": {"target_intersecting": True}}}
        with patch.object(runner, "build_prompt", return_value="fixed prefix"), \
             patch.object(runner, "build_decoding", return_value={"ebnf": "fixed grammar"}):
            result, receipt = runner._call(
                cfg, request, "ignored rendered input",
                lambda *_args, **_kwargs: FakeHTTP(body), catalog=catalog,
            )
        return result, receipt

    def test_provider_cache_counter_does_not_change_three_token_usage(self):
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 7,
            "total_tokens": 107,
            "prompt_tokens_details": {"cached_tokens": 40},
        }
        result, receipt = self.call({
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            "usage": usage,
        })

        self.assertEqual(result, {})
        self.assertEqual(receipt["usage"], {
            "input_tokens": 100, "output_tokens": 7, "total_tokens": 107,
        })
        self.assertEqual(receipt["cache_observation"]["state"], "provider")
        self.assertEqual(receipt["cache_observation"]["cached_tokens"], 40)
        self.assertEqual(receipt["cache_observation"]["prompt_tokens"], 100)

    def test_missing_cache_counter_is_unknown_not_zero_and_keeps_usage(self):
        _, receipt = self.call({
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 7,
                      "total_tokens": 107},
        })

        self.assertEqual(receipt["usage"], {
            "input_tokens": 100, "output_tokens": 7, "total_tokens": 107,
        })
        observation = receipt["cache_observation"]
        self.assertEqual(observation["state"], "unavailable")
        self.assertIsNone(observation["cached_tokens"])
        self.assertIsNone(observation["cached_fraction"])

    def test_invalid_cache_counter_is_reported_without_rewriting_usage(self):
        _, receipt = self.call({
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 7,
                      "total_tokens": 17,
                      "prompt_tokens_details": {"cached_tokens": 11}},
        })

        self.assertEqual(receipt["usage"], {
            "input_tokens": 10, "output_tokens": 7, "total_tokens": 17,
        })
        observation = receipt["cache_observation"]
        self.assertEqual(observation["state"], "invalid")
        self.assertIsNone(observation["cached_tokens"])
        self.assertNotIn("test-secret", json.dumps(receipt))

    def test_cache_observation_helper_rejects_bool_and_negative_counters(self):
        for cached in (True, -1):
            with self.subTest(cached=cached):
                observation = runner._cache_observation({
                    "usage": {"prompt_tokens": 10,
                              "prompt_tokens_details": {"cached_tokens": cached}}
                })
                self.assertEqual(observation["state"], "invalid")
                self.assertIsNone(observation["cached_tokens"])

    def test_http_failure_receipt_keeps_provider_usage_and_cache_observation(self):
        body = {"usage": {"prompt_tokens": 12, "completion_tokens": 4,
                          "total_tokens": 16,
                          "prompt_tokens_details": {"cached_tokens": 5}}}
        error = HTTPError("https://provider.invalid", 503, "unavailable", {},
                          io.BytesIO(json.dumps(body).encode()))
        request = {"request_id": "http-failure", "expected_target_ids": ["t"],
                   "spec": {"caps": {"output_tokens": 64}}}
        cfg = {"url": "https://provider.invalid/v1/chat/completions",
               "token": "test-secret", "model": "test-model"}
        catalog = {"atoms": {"atom-1": {"target_intersecting": True}}}
        with patch.object(runner, "build_prompt", return_value="fixed prefix"), \
             patch.object(runner, "build_decoding", return_value={"ebnf": "fixed grammar"}):
            with self.assertRaises(runner.CompactRunError) as raised:
                runner._call(cfg, request, "ignored", lambda *_a, **_k: (_ for _ in ()).throw(error),
                             catalog=catalog)

        receipt = json.loads(str(raised.exception))
        self.assertEqual(receipt["usage"], {
            "input_tokens": 12, "output_tokens": 4, "total_tokens": 16,
        })
        self.assertEqual(receipt["cache_observation"]["state"], "provider")
        self.assertEqual(receipt["cache_observation"]["cached_tokens"], 5)
        self.assertEqual(receipt["failure_diagnostic"]["http_status"], 503)
        self.assertNotIn("test-secret", json.dumps(receipt))

    def test_default_benchmark_adapter_supplies_the_required_real_opener(self):
        cfg = {"url": "https://provider.invalid/v1/chat/completions", "token": "secret"}
        request = {"request_id": "adapter-regression"}
        rendered = "fixed rendered source"
        catalog = {"atoms": {"a": {}}}
        expected = ({"response": "ok"}, {"finish_reason": "stop"})
        with patch.object(runner, "_call", autospec=True, return_value=expected) as call:
            result = benchmark._default_call(cfg, request, rendered, catalog=catalog)

        self.assertEqual(result, expected)
        call.assert_called_once_with(cfg, request, rendered, runner.urlrequest.urlopen,
                                     catalog=catalog)


if __name__ == "__main__":
    unittest.main()
