import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from knowledge_base.pipeline_v1.k0_authoring import token_budget as tb


class TokenBudgetTests(unittest.TestCase):
    def test_full_payload_and_template_are_both_reserved(self):
        identity = tb.counter_identity()
        if 'fallback' in identity['method']:
            self.skipTest('optional local tokenizer unavailable; fallback is tested separately')
        payload = {'model': 'Qwen/Qwen3.5-9B', 'messages': [{'role': 'user', 'content': 'A court said: é 😀.'}],
                   'max_tokens': 800, 'chat_template_kwargs': {'enable_thinking': False}, 'ebnf': 'root ::= "x"'}
        tokenizer, template, cfg = tb._load()
        rendered = template.render(messages=payload['messages'], tools=None, add_generation_prompt=True,
                                   enable_thinking=False, add_vision_id=False,
                                   eos_token=cfg.get('eos_token'), bos_token=cfg.get('bos_token'))
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        expected = max(len(tokenizer.encode(rendered, add_special_tokens=False).ids),
                       len(tokenizer.encode(raw, add_special_tokens=False).ids)) + 128
        self.assertEqual(tb.input_reservation(payload), expected)
        self.assertFalse(identity['provider_usage'])
        self.assertEqual(identity['revision'], tb.REVISION)

    def test_missing_assets_falls_back_explicitly_to_full_bytes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(tb, 'ASSETS', Path(tmp)):
            payload = {'messages': [{'role': 'user', 'content': 'Unicode é 😀'}], 'ebnf': 'large grammar'}
            self.assertIn('fallback', tb.counter_identity()['method'])
            self.assertEqual(tb.input_reservation(payload), len(json.dumps(payload, sort_keys=True,
                ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + 128)

    def test_tampered_assets_fail_instead_of_silently_changing_counter(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(tb, 'ASSETS', Path(tmp)):
            for name in tb.EXPECTED:
                (Path(tmp) / name).write_text('{}', encoding='utf-8')
            try:
                import tokenizers, jinja2
            except ImportError:
                self.skipTest('optional tokenizer libs missing')
            with self.assertRaises(ValueError):
                tb.counter_identity()


if __name__ == '__main__':
    unittest.main()
