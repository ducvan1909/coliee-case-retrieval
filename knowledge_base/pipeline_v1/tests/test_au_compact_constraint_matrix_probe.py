import json
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.au_compact.constraint_matrix_probe import constraint_matrix_probe


class FakeHTTP:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.body).encode()


class ConstraintMatrixProbeTests(unittest.TestCase):
    def test_isolates_no_thinking_and_tests_compact_schema(self):
        seen = []
        def opener(request, **_):
            payload = json.loads(request.data); seen.append(payload)
            thinking = payload.get("chat_template_kwargs", {}).get("enable_thinking")
            if payload["response_format"]["json_schema"]["name"] == "au_compact_response":
                content = json.dumps({"request_id":"p","target_id":"p","decision":"hard_negative","coverage_status":"complete","aus":[],"hard_negative_reason":"other","unresolved_reason":None})
            elif thinking is False:
                content = '{"kind":"exception"}'
            else:
                content = '{"kind":"holding"}'
            return FakeHTTP({"choices":[{"finish_reason":"stop","message":{"content":content}}],"usage":{"total_tokens":9}})
        cfg = {"url":"https://fake","token":"secret","model":"qwen","timeout":1}
        with tempfile.TemporaryDirectory() as folder:
            report = constraint_matrix_probe(cfg, folder, opener)
            saved = json.loads((Path(folder)/"constraint_matrix_probe.json").read_text(encoding="utf-8"))
        self.assertEqual(report["diagnosis"], "thinking_false_incompatible")
        self.assertEqual(report["requests_sent"], 4)
        self.assertEqual(saved["results"][-1]["status"], "supported")
        self.assertNotIn("secret", json.dumps(saved))


if __name__ == "__main__":
    unittest.main()
