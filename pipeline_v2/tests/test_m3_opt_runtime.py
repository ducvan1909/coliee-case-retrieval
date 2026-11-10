"""Accounting and failure-path tests for optimized inference requests (mock only)."""
import unittest
from unittest.mock import patch

import numpy as np

from pipeline_v2.optimization import runtime
from pipeline_v2.retrieval.common import fingerprint
from pipeline_v2.retrieval.common import M3Error


class TinyTokenizer:
    class Backend:
        @staticmethod
        def encode(text, add_special_tokens=True):
            return type("Encoded", (), {"ids": [1, 2, 3]})()
    backend = Backend()


class RecordingLedger:
    def __init__(self):
        self.calls = []

    def begin(self, batch_id, operation):
        self.calls.append(("begin", batch_id, operation))
        return "attempt-1"

    def finish(self, attempt, status, elapsed, tokens, error=None, receipt=None):
        self.calls.append(("finish", attempt, status, tokens, error, receipt))


class MockEmbedder:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.calls = []

    def encode(self, texts, kind):
        self.calls.append((list(texts), kind))
        if self.error:
            raise self.error
        return self.response


class OptimizedRequestTests(unittest.TestCase):
    def setUp(self):
        self.profile = {"embedding": {"max_tokens": 448}}
        self.code = {
            "pipeline_v2/deployments/modal_opt/engine.py": "engine-hash",
            "pipeline_v2/deployments/modal_opt/qwen3_embed.py": "embed-hash",
        }
        self.ledger = RecordingLedger()
        self.tokenizer = TinyTokenizer()

    def test_oom_is_recorded_before_larger_batch_stop(self):
        response = {
            "status": "oom",
            "descriptor": {"embedding_fingerprint": fingerprint(self.profile), "engine_sha256": "engine-hash"},
            "input_tokens": 21, "padded_tokens": 30, "remote_elapsed_seconds": 4.5,
            "peak_allocated_bytes": 90, "peak_reserved_bytes": 100, "token_consumption": "known",
        }
        embedder = MockEmbedder(response)
        with self.assertRaises(runtime.BenchmarkOOM):
            runtime.request_embedding(embedder, ["long enough text"], self.profile, self.tokenizer,
                                      self.code, self.ledger, "stress-128")
        self.assertEqual(embedder.calls, [(["long enough text"], "document")])
        self.assertEqual(self.ledger.calls[0], ("begin", "stress-128", "optimization_document"))
        finish = self.ledger.calls[1]
        self.assertEqual(finish[2:5], ("oom", None, "CUDAOutOfMemory"))
        self.assertEqual(finish[5]["input_tokens"], 21)

    def test_failed_request_records_unknown_usage_instead_of_zero(self):
        embedder = MockEmbedder(error=TimeoutError("simulated"))
        with self.assertRaisesRegex(M3Error, "Optimization request failed: TimeoutError"):
            runtime.request_embedding(embedder, ["text"], self.profile, self.tokenizer,
                                      self.code, self.ledger, "size-16-repeat-0-batch-0")
        self.assertIsNone(self.ledger.calls[1][3])
        self.assertEqual(self.ledger.calls[1][2], "error")
        self.assertEqual(self.ledger.calls[1][4], "TimeoutError")

    def test_invalid_batch_is_rejected_before_attempt_or_inference(self):
        embedder = MockEmbedder()
        for texts in ([], [""], ["ok"] * 129, "not-a-list"):
            with self.subTest(texts=type(texts).__name__, n=len(texts) if isinstance(texts, (list, str)) else None):
                with self.assertRaises(M3Error):
                    runtime.request_embedding(embedder, texts, self.profile, self.tokenizer,
                                              self.code, self.ledger, "invalid")
        self.assertEqual(self.ledger.calls, [])
        self.assertEqual(embedder.calls, [])

    def test_invalid_gpu_memory_metrics_are_not_accepted(self):
        response = {
            "status": "ok", "input_tokens": 3, "padded_tokens": 3, "remote_elapsed_seconds": 1.0,
            "gpu_model_pool_seconds": 0.5, "peak_allocated_bytes": 20, "peak_reserved_bytes": 10,
            "device_total_bytes": 30,
        }
        embedder = MockEmbedder(response)
        with patch.object(runtime, "validate_response", return_value=np.ones((1, 3), dtype=np.float32)):
            with self.assertRaisesRegex(M3Error, "Inconsistent GPU memory metrics"):
                runtime.request_embedding(embedder, ["text"], self.profile, self.tokenizer,
                                          self.code, self.ledger, "size-16-repeat-0-batch-0")
        self.assertEqual(self.ledger.calls[1][2:5], ("error", 3, "M3Error"))


if __name__ == "__main__":
    unittest.main()
