import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from knowledge_base.pipeline_v1.au_compact.adversarial_probe import adversarial_schema_probe
from knowledge_base.pipeline_v1.au_compact.core import COMPACT_SCHEMA


class FakeHTTP:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.body).encode()


class AdversarialCompactSchemaProbeTests(unittest.TestCase):
    cfg = {"url": "https://fake", "token": "test-token", "model": "test-model", "enable_thinking": False}

    @staticmethod
    def valid_result():
        return {"request_id": "probe", "target_id": "probe", "decision": "hard_negative", "coverage_status": "complete", "aus": [], "hard_negative_reason": "other", "unresolved_reason": None}

    def test_valid_constrained_result_is_supported_and_sends_exact_schema(self):
        seen = []
        def opener(request, **_):
            seen.append(json.loads(request.data))
            return FakeHTTP({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.valid_result())}}], "usage": {"prompt_tokens": 4}})
        with tempfile.TemporaryDirectory() as folder:
            result = adversarial_schema_probe(self.cfg, folder, opener)
            saved = json.loads((Path(folder) / "adversarial_schema_probe.json").read_text(encoding="utf-8"))
        self.assertEqual((result["status"], saved["status"]), ("supported", "supported"))
        self.assertIn('{"status":"positive","AUs":["sa-invalid"]}', seen[0]["messages"][0]["content"])
        self.assertEqual(seen[0]["response_format"]["json_schema"]["schema"], json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8")))
        self.assertTrue(seen[0]["response_format"]["json_schema"]["strict"])

    def test_invalid_status_and_aus_is_invalid_result_with_safe_diagnostics(self):
        bad = '{"status":"positive","AUs":["sa-invalid"]}'
        with tempfile.TemporaryDirectory() as folder:
            result = adversarial_schema_probe(self.cfg, folder, lambda *_a, **_k: FakeHTTP({"choices": [{"finish_reason": "stop", "message": {"content": bad}}], "usage": {"total_tokens": 7}}))
        self.assertEqual(result["status"], "invalid_result")
        self.assertEqual(result["content_preview"], bad)
        self.assertEqual(result["provider_usage"], {"total_tokens": 7})
        self.assertEqual(result["finish_reason"], "stop")
        self.assertNotIn(self.cfg["token"], json.dumps(result))

    def test_malformed_and_http_are_non_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            malformed = adversarial_schema_probe(self.cfg, folder, lambda *_a, **_k: FakeHTTP({"choices": [{"finish_reason": "length", "message": {"content": "not-json"}}], "usage": {}}))
            http = adversarial_schema_probe(self.cfg, folder, lambda *_a, **_k: (_ for _ in ()).throw(HTTPError("https://fake", 503, "bad", None, None)))
        self.assertEqual((malformed["status"], malformed["content_preview"]), ("invalid_result", "not-json"))
        self.assertEqual((http["status"], http["http_status"]), ("http_error", 503))
