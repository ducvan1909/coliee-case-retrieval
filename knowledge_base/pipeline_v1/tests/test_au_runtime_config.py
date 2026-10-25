import unittest

from knowledge_base.pipeline_v1.au_runtime_config import AURuntimeConfigError, load_au_runtime_config


class AURuntimeConfigTests(unittest.TestCase):
    def test_canonical_values_take_precedence_over_legacy_values(self):
        env = {
            "AU_URL": "https://canonical.example/v1/chat/completions",
            "AU_TOKEN": "canonical-token",
            "AU_MODEL": "canonical-model",
            "AU_ENABLE_THINKING": "true",
            "AU_TIMEOUT": "61",
            "AU_MAX_REQUESTS": "7",
            "AU_ONLY_URL": "https://legacy.example",
            "AU_ONLY_TOKEN": "legacy-token",
            "AU_ONLY_MODEL": "legacy-model",
            "AU_ONLY_ENABLE_THINKING": "false",
            "AU_ONLY_TIMEOUT": "12",
            "AU_ONLY_MAX_REQUESTS": "3",
        }
        cfg, budget, _ = load_au_runtime_config(env, "AU_ONLY_")
        self.assertEqual(cfg["url"], "https://canonical.example/v1/chat/completions")
        self.assertEqual(cfg["model"], "canonical-model")
        self.assertTrue(cfg["enable_thinking"])
        self.assertEqual(cfg["timeout"], 61)
        self.assertEqual(budget["max_requests"], 7)

    def test_runner_specific_legacy_values_remain_a_fallback(self):
        env = {
            "AU_COMPACT_URL": "https://legacy.example/v1/chat/completions",
            "AU_COMPACT_TOKEN": "legacy-token",
            "AU_COMPACT_MODEL": "legacy-model",
            "AU_COMPACT_ENABLE_THINKING": "false",
            "AU_COMPACT_TIMEOUT": "45",
            "AU_COMPACT_MAX_TOTAL_INPUT_TOKENS": "456",
            "AU_COMPACT_WARMUP_MAX_ATTEMPTS": "4",
        }
        cfg, budget, policy = load_au_runtime_config(env, "AU_COMPACT_")
        self.assertEqual(cfg["url"], "https://legacy.example/v1/chat/completions")
        self.assertEqual(cfg["model"], "legacy-model")
        self.assertFalse(cfg["enable_thinking"])
        self.assertEqual(cfg["timeout"], 45)
        self.assertEqual(budget["max_total_input_tokens"], 456)
        self.assertEqual(policy["max_attempts"], 4)

    def test_invalid_canonical_boolean_is_rejected(self):
        with self.assertRaisesRegex(AURuntimeConfigError, "AU_ENABLE_THINKING"):
            load_au_runtime_config({"AU_ENABLE_THINKING": "sometimes"}, "AU_ONLY_")
