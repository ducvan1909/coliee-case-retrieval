import json
import tempfile
import unittest

from knowledge_base.pipeline_v1.au_compact.schema_ablation_probe import schema_ablation_probe


class FakeHTTP:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.body).encode()


class SchemaAblationProbeTests(unittest.TestCase):
    def test_stops_at_first_supported_variant(self):
        calls = []
        def opener(request, **_):
            payload = json.loads(request.data); calls.append(payload)
            content = json.dumps({"request_id":"p","target_id":"p","decision":"hard_negative","coverage_status":"complete","aus":[],"hard_negative_reason":"other","unresolved_reason":None})
            return FakeHTTP({"choices":[{"finish_reason":"stop","message":{"content":content}}],"usage":{}})
        with tempfile.TemporaryDirectory() as folder:
            report = schema_ablation_probe({"url":"https://fake","token":"secret","model":"qwen"}, folder, opener)
        self.assertEqual(report["diagnosis"], "conditional_schema_keywords_incompatible")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("allOf", json.dumps(calls[0]["response_format"]))


if __name__ == "__main__":
    unittest.main()
