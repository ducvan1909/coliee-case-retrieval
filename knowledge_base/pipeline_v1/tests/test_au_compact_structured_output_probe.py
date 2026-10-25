import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

from knowledge_base.pipeline_v1.au_compact.core import COMPACT_SCHEMA
from knowledge_base.pipeline_v1.au_compact.structured_output_probe import structured_output_probe


class FakeHTTP:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.body).encode()


class StructuredOutputProbeTests(unittest.TestCase):
    cfg = {"url": "https://fake", "token": "test-token", "model": "test-model", "enable_thinking": False}

    @staticmethod
    def valid_result():
        return {"request_id": "probe", "target_id": "probe", "decision": "hard_negative", "coverage_status": "complete", "aus": [], "hard_negative_reason": "other", "unresolved_reason": None}

    def run_probe(self, opener):
        with tempfile.TemporaryDirectory() as folder:
            result = structured_output_probe(self.cfg, folder, opener)
            persisted = json.loads((Path(folder) / "structured_output_probe.json").read_text(encoding="utf-8"))
        self.assertEqual(result, persisted)
        self.assertNotIn(self.cfg["token"], json.dumps(result))
        return result

    def test_valid_result_is_supported_and_uses_structured_outputs_without_response_format(self):
        seen = []
        def opener(request, **_):
            seen.append(json.loads(request.data))
            return FakeHTTP({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.valid_result())}}], "usage": {"total_tokens": 4}})
        self.assertEqual(self.run_probe(opener)["status"], "supported")
        self.assertNotIn("response_format", seen[0])
        self.assertEqual(seen[0]["structured_outputs"], {"json": json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8"))})
        self.assertEqual((seen[0]["temperature"], seen[0]["max_tokens"]), (0, 256))
        self.assertIn('{"status":"positive","AUs":["sa-invalid"]}', seen[0]["messages"][0]["content"])

    def test_http_200_schema_invalid_is_constraint_not_enforced(self):
        bad = '{"status":"positive","AUs":["sa-invalid"]}'
        result = self.run_probe(lambda *_a, **_k: FakeHTTP({"choices": [{"finish_reason": "stop", "message": {"content": bad}}], "usage": {"total_tokens": 7}}))
        self.assertEqual((result["status"], result["body_preview"], result["provider_usage"]), ("constraint_not_enforced", bad, {"total_tokens": 7}))

    def test_http_400_and_422_are_request_rejected_with_safe_body(self):
        for code in (400, 422):
            with self.subTest(code=code):
                error = HTTPError("https://fake", code, "bad", None, io.BytesIO(b'{"error":"unknown structured_outputs"}'))
                result = self.run_probe(lambda *_a, **_k: (_ for _ in ()).throw(error))
                self.assertEqual((result["status"], result["http_status"], result["body_preview"]), ("request_rejected", code, '{"error":"unknown structured_outputs"}'))

    def test_http_503_is_provider_error(self):
        error = HTTPError("https://fake", 503, "bad", None, io.BytesIO(b"unavailable"))
        result = self.run_probe(lambda *_a, **_k: (_ for _ in ()).throw(error))
        self.assertEqual((result["status"], result["http_status"]), ("provider_error", 503))

    def test_malformed_and_transport_are_non_supported(self):
        malformed = self.run_probe(lambda *_a, **_k: FakeHTTP({"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}], "usage": {}}))
        transport = self.run_probe(lambda *_a, **_k: (_ for _ in ()).throw(URLError("offline")))
        self.assertEqual((malformed["status"], malformed["body_preview"]), ("invalid_result", "not-json"))
        self.assertEqual(transport["status"], "transport_error")
