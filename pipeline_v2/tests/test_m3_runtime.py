import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from pipeline_v2.passages import PinnedTokenizer
from pipeline_v2.retrieval.cache import Cache
from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.retrieval.common import fingerprint
from pipeline_v2.retrieval.runtime import call_embedding, render_query, validate_response
from pipeline_v2.retrieval import runtime
from pipeline_v2.source.core import digest
class M3RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.profile = json.loads((cls.root / "pipeline_v2/configs/m3.json").read_bytes())
        cls.embedding = cls.profile["embedding"]
        cls.lock = "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json"
        cls.tokenizer = PinnedTokenizer(cls.root, cls.lock)
        cls.code = {
            "pipeline_v2/deployments/modal/engine.py": digest((cls.root / "pipeline_v2/deployments/modal/engine.py").read_bytes()),
            "pipeline_v2/deployments/modal/qwen3_embed.py": digest((cls.root / "pipeline_v2/deployments/modal/qwen3_embed.py").read_bytes()),
        }

    def response(self, texts, kind="document"):
        rendered = [render_query(x, self.profile) if kind == "query" else x for x in texts]
        ids = [self.tokenizer.backend.encode(x, add_special_tokens=True).ids for x in rendered]
        return {
            "descriptor": {
                "embedding_fingerprint": fingerprint(self.profile),
                "model": self.embedding["model"], "revision": self.embedding["revision"],
                "dimensions": self.embedding["dimensions"],
                "engine_sha256": self.code["pipeline_v2/deployments/modal/engine.py"],
                "wrapper_sha256": self.code["pipeline_v2/deployments/modal/qwen3_embed.py"],
                "package_versions": {**{name: self.embedding[name] for name in ("torch", "transformers", "tokenizers")}, "modal": "1.5.3"},
                "loaded_model_revision": self.embedding["revision"],
                "device_dtype": "torch.bfloat16",
            },
            "input_hashes": [digest(x.encode("utf-8")) for x in rendered],
            "token_ids": ids,
            "vectors": [[1.0] + [0.0] * (self.embedding["dimensions"] - 1) for _ in texts],
            "input_tokens": sum(map(len, ids)),
            "padded_tokens": len(ids) * max(map(len, ids)),
            "remote_elapsed_seconds": 0.25,
        }

    def test_document_input_remains_raw_and_response_must_match_local_tokenizer_and_code(self):
        text = "[1] Legal source text, with negation and 2024."
        response = self.response([text])
        vecs = validate_response(response, [text], "document", self.profile, self.tokenizer, self.code)
        self.assertEqual(vecs.shape, (1, self.embedding["dimensions"]))
        self.assertEqual(response["input_hashes"], [digest(text.encode("utf-8"))])
        response["input_hashes"] = [digest(("Instruct: " + text).encode("utf-8"))]
        with self.assertRaises(M3Error):
            validate_response(response, [text], "document", self.profile, self.tokenizer, self.code)

    def test_query_instruction_is_applied_only_to_query_inputs(self):
        query = "Does the tribunal have jurisdiction?"
        self.assertTrue(render_query(query, self.profile).startswith("Instruct: "))
        self.assertTrue(render_query(query, self.profile).endswith("\nQuery:" + query))
        response = self.response([query], "query")
        validate_response(response, [query], "query", self.profile, self.tokenizer, self.code)
        with self.assertRaises(M3Error):
            validate_response(response, [query], "document", self.profile, self.tokenizer, self.code)

    def test_profile_model_tokenizer_and_implementation_drift_are_rejected(self):
        for field, value in (("model", "wrong/model"), ("revision", "mutable"), ("dimensions", 7)):
            with self.subTest(field=field):
                response = self.response(["passage"])
                response["descriptor"][field] = value
                with self.assertRaises(M3Error):
                    validate_response(response, ["passage"], "document", self.profile, self.tokenizer, self.code)
        response = self.response(["passage"])
        response["descriptor"]["tokenizer_revision"] = "wrong"
        response["token_ids"][0][0] += 1
        with self.assertRaises(M3Error):
            validate_response(response, ["passage"], "document", self.profile, self.tokenizer, self.code)
        response = self.response(["passage"])
        with self.assertRaises(M3Error):
            validate_response(response, ["passage"], "document", self.profile, self.tokenizer, {**self.code, "pipeline_v2/deployments/modal/engine.py": "stale"})

    def test_runtime_token_padding_and_latency_receipts_are_validated(self):
        texts = ["short", "a longer legal passage"]
        for field, value in (("padded_tokens", 1), ("remote_elapsed_seconds", -1),
                             ("remote_elapsed_seconds", float("nan")),
                             ("remote_elapsed_seconds", "unknown")):
            with self.subTest(field=field, value=value):
                response = self.response(texts)
                response[field] = value
                with self.assertRaises(M3Error):
                    validate_response(response, texts, "document", self.profile, self.tokenizer, self.code)

    def test_call_embedding_records_valid_attempt_and_stops_on_profile_mismatch(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache = Cache(tmp, "profile", dimensions=self.embedding["dimensions"])
        self.addCleanup(cache.db.close)
        remote = Mock()
        remote.encode.return_value = self.response(["passage"])
        vectors, _ = call_embedding(remote, ["passage"], "document", self.profile,
                                    self.tokenizer, self.code, cache, "batch-1")
        self.assertEqual(vectors.shape, (1, self.embedding["dimensions"]))
        self.assertEqual(cache.usage()["model_requests"], 1)
        bad = self.response(["other"])
        bad["descriptor"]["revision"] = "stale"
        remote.encode.reset_mock()
        remote.encode.return_value = bad
        with self.assertRaises(M3Error):
            call_embedding(remote, ["other"], "document", self.profile,
                           self.tokenizer, self.code, cache, "batch-2")
        self.assertEqual(remote.encode.call_count, 1)
        usage = cache.usage()
        self.assertEqual(usage["model_requests"], 2)
        self.assertEqual(usage["attempts"][-1]["status"], "error")

    def test_call_embedding_retries_transport_errors_but_fails_permanent_errors_once(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache = Cache(tmp, "profile", dimensions=self.embedding["dimensions"])
        self.addCleanup(cache.db.close)
        remote = Mock()
        remote.encode.side_effect = [ConnectionError("temporary"), self.response(["passage"])]
        with patch.object(runtime.time, "sleep") as sleep:
            vectors, _ = call_embedding(remote, ["passage"], "document", self.profile,
                                        self.tokenizer, self.code, cache, "retry-batch")
        self.assertEqual(vectors.shape, (1, self.embedding["dimensions"]))
        self.assertEqual(remote.encode.call_count, 2)
        self.assertEqual(cache.usage()["model_requests"], 2)
        self.assertEqual([row["status"] for row in cache.usage()["attempts"]], ["error", "success"])
        sleep.assert_called_once()

        remote.reset_mock()
        remote.encode.side_effect = ValueError("permanent request error")
        with self.assertRaises(M3Error):
            call_embedding(remote, ["another passage"], "document", self.profile,
                           self.tokenizer, self.code, cache, "permanent-batch")
        self.assertEqual(remote.encode.call_count, 1)

    def test_over_cap_input_is_rejected_before_remote_request_or_attempt_record(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache = Cache(tmp, "profile", dimensions=self.embedding["dimensions"])
        self.addCleanup(cache.db.close)
        remote = Mock()
        too_long = "court " * 500
        with self.assertRaises(M3Error):
            call_embedding(remote, [too_long], "document", self.profile,
                           self.tokenizer, self.code, cache, "over-cap")
        remote.encode.assert_not_called()
        self.assertEqual(cache.usage()["model_requests"], 0)


if __name__ == "__main__":
    unittest.main()
