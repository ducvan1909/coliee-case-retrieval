"""Compatibility receipt gate tests. Every runtime is synthetic; no Modal call."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from pipeline_v2.optimization_v2 import runtime
from pipeline_v2.optimization_v2.common import write_json
from pipeline_v2.optimization_v2.runtime import BenchmarkOOM
from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.source.core import digest


class CompatibilityGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "pipeline_v2" / "artifacts"
        self.run = self.artifacts / "fixture"
        self.run.mkdir(parents=True)
        self.index = self.run / "index"
        self.index.mkdir()
        (self.index / "manifest.json").write_text("{}\n", encoding="utf-8")
        self.receipt_path = self.run / "compatibility" / "compatibility.json"
        self.receipt_path.parent.mkdir()
        self.session = type("Session", (), {})()
        self.session.root = self.root
        self.session.directory = self.index
        self.session.manifest = {"profile": {"compatibility": {"cosine_atol": .001}}}
        self.session.base = {}
        self.bindings = {
            "embedding_fingerprint": "new-embed-fp",
            "baseline_embedding_fingerprint": "baseline-embed-fp",
            "index_manifest_sha256": digest((self.index / "manifest.json").read_bytes()),
            "optimization_implementation": {"pipeline_v2/m3_opt_v2.py": "code-hash"},
        }
        self.runtime_dir = self.run / "index_runtime"
        self.runtime_dir.mkdir()

    def put_receipt(self, status="PASS", execution_mode="real", *, pointer_status=None, checks=None):
        receipt = {
            **self.bindings,
            "status": status,
            "execution_mode": execution_mode,
            "document_checks": checks or {"count": 8, "max_cosine_deviation": .0001, "max_singleton_batch_deviation": .0002},
            "query_checks": [
                {"cosine_deviation": .0001, "baseline_descriptor": {"engine": "baseline"}, "v2_descriptor": {"engine": "v2"}}
                for _ in range(3)
            ],
        }
        write_json(self.receipt_path, receipt, replace=self.receipt_path.exists())
        receipt_hash = digest(self.receipt_path.read_bytes())
        checksum_path = self.receipt_path.with_name("compatibility.sha256.json")
        write_json(checksum_path, {"sha256": receipt_hash}, replace=checksum_path.exists())
        pointer_path = self.runtime_dir / "compatibility_current.json"
        write_json(pointer_path, {
            "status": pointer_status or status,
            "receipt": self.receipt_path.relative_to(self.root).as_posix(),
            "receipt_sha256": receipt_hash,
        }, replace=pointer_path.exists())
        return receipt

    def require(self, allow_simulated=False):
        return runtime.require_compatibility(self.session, self.receipt_path, allow_simulated=allow_simulated)

    def test_real_receipt_requires_all_document_and_query_parity_checks(self):
        self.put_receipt()
        with patch("pipeline_v2.optimization_v2.runtime._bindings", return_value=self.bindings), \
             patch("pipeline_v2.optimization_v2.runtime.runtime_dir", return_value=self.runtime_dir), \
             patch("pipeline_v2.optimization_v2.runtime.artifact", side_effect=lambda root, path: Path(path)):
            result = self.require()
        self.assertEqual(result["execution_mode"], "real")

    def test_simulated_receipt_cannot_unlock_real_search(self):
        self.put_receipt("simulated", "simulated")
        with patch("pipeline_v2.optimization_v2.runtime._bindings", return_value=self.bindings), \
             patch("pipeline_v2.optimization_v2.runtime.runtime_dir", return_value=self.runtime_dir), \
             patch("pipeline_v2.optimization_v2.runtime.artifact", side_effect=lambda root, path: Path(path)):
            with self.assertRaisesRegex(M3Error, "Latest V2 preflight"):
                self.require(allow_simulated=False)
            self.assertEqual(self.require(allow_simulated=True)["status"], "simulated")

    def test_real_search_rejects_stale_pointer_changed_receipt_or_incomplete_parity(self):
        self.put_receipt()
        with patch("pipeline_v2.optimization_v2.runtime._bindings", return_value=self.bindings), \
             patch("pipeline_v2.optimization_v2.runtime.runtime_dir", return_value=self.runtime_dir), \
             patch("pipeline_v2.optimization_v2.runtime.artifact", side_effect=lambda root, path: Path(path)):
            write_json(self.runtime_dir / "compatibility_current.json", {"status": "in_progress"}, replace=True)
            with self.assertRaises(M3Error):
                self.require()
            self.put_receipt()
            self.receipt_path.write_text(self.receipt_path.read_text(encoding="utf-8").replace("PASS", "FAIL"), encoding="utf-8")
            with self.assertRaisesRegex(M3Error, "changed"):
                self.require()
            self.put_receipt(checks={"count": 2, "max_cosine_deviation": 0, "max_singleton_batch_deviation": 0})
            with self.assertRaisesRegex(M3Error, "Incomplete"):
                self.require()


class PreflightLifecycleTests(unittest.TestCase):
    def test_first_preflight_creates_runtime_dir_and_failed_retry_invalidates_old_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_dir = root / "pipeline_v2" / "artifacts" / "index"
            index_dir.mkdir(parents=True)
            ids = [f"p{i}" for i in range(8)]
            profile = {"compatibility": {"query_fixtures": ["query A", "query B", "query C"]}}
            base = {"profile": {}, "implementation": {}}

            class Session:
                def __init__(self, root_arg, index_arg):
                    self.root = Path(root_arg)
                    self.directory = self.root / index_arg
                    self.manifest = {"profile": profile}
                    self.base = base
                    self.ids = ids
                    self.byid = {ident: i for i, ident in enumerate(ids)}
                    self.vectors = np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (8, 1))
                    self.closed = False

                def guard(self):
                    return None

                def cheap_db_check(self):
                    return None

                def passage_metadata(self, requested):
                    return [{"passage_id": ident, "full_input_tokens": i + 1} for i, ident in enumerate(requested)]

                def full_passages(self, requested):
                    return [{"passage_id": ident, "text": f"body {ident}"} for ident in requested]

                def close(self):
                    self.closed = True

            class Ledger:
                def __init__(self, *args):
                    self.db = type("DB", (), {"close": lambda self: None})()

                def usage(self):
                    return {"requests": None, "known_input_tokens": None}

            runtime_dir = index_dir.parent / "index_runtime"
            self.assertFalse(runtime_dir.exists(), "first-run regression requires a missing runtime directory")
            outputs = ["pipeline_v2/artifacts/preflight-failure-1", "pipeline_v2/artifacts/preflight-failure-2"]
            with patch("pipeline_v2.optimization_v2.index.FastSession", side_effect=Session), \
                 patch("pipeline_v2.optimization_v2.runtime.Cache", Ledger), \
                 patch("pipeline_v2.optimization_v2.runtime.PinnedTokenizer", return_value=object()), \
                 patch("pipeline_v2.optimization_v2.runtime._bindings", return_value={
                     "embedding_fingerprint": "v2", "baseline_embedding_fingerprint": "base",
                     "index_manifest_sha256": "index-hash", "optimization_implementation": {"code": "hash"}}), \
                 patch("pipeline_v2.optimization_v2.runtime.fingerprint", return_value="v2"), \
                 patch("pipeline_v2.optimization_v2.runtime.request_embedding", side_effect=RuntimeError("mock outage")) as request:
                with self.assertRaisesRegex(RuntimeError, "mock outage"):
                    runtime.preflight_compatibility(root, "pipeline_v2/artifacts/index", outputs[0],
                                                    embedder=object(), baseline_embedder=object())
                pointer_path = runtime_dir / "compatibility_current.json"
                self.assertTrue(pointer_path.exists(), f"expected pointer under {runtime_dir}; files={list(root.rglob('*'))}")
                self.assertEqual(runtime.read(pointer_path)["status"], "failed")
                # Simulate an old success pointer; a failed retry must replace it.
                from pipeline_v2.retrieval.common import write_json
                write_json(pointer_path, {"status": "PASS", "receipt": "stale", "receipt_sha256": "stale"}, replace=True)
                with self.assertRaisesRegex(RuntimeError, "mock outage"):
                    runtime.preflight_compatibility(root, "pipeline_v2/artifacts/index", outputs[1],
                                                    embedder=object(), baseline_embedder=object())
                self.assertEqual(runtime.read(pointer_path)["status"], "failed")
                self.assertEqual(request.call_count, 2)

    def test_oom_preserves_unknown_usage_as_null_in_ledger(self):
        class Backend:
            def encode(self, text, add_special_tokens):
                self.assert_special = add_special_tokens
                return type("Encoded", (), {"ids": [101, 151643]})()

        class Tokenizer:
            backend = Backend()

        class Embedder:
            def encode(self, texts, kind):
                return {"status": "oom", "descriptor": {"embedding_fingerprint": "fp", "engine_sha256": "engine-hash"},
                        "token_consumption": None, "padded_tokens": None, "remote_elapsed_seconds": .4}

        class Ledger:
            def __init__(self):
                self.record = None

            def begin(self, label, kind):
                return "attempt"

            def finish(self, attempt, status, elapsed, tokens, error, receipt=None):
                self.record = {"status": status, "elapsed": elapsed, "tokens": tokens, "error": error, "receipt": receipt}

        profile = {"embedding": {"max_tokens": 448}}
        code = {"pipeline_v2/deployments/modal_opt_v2/engine.py": "engine-hash",
                "pipeline_v2/deployments/modal_opt_v2/qwen3_embed.py": "wrapper-hash"}
        ledger = Ledger()
        with patch("pipeline_v2.optimization_v2.runtime.fingerprint", return_value="fp"):
            with self.assertRaises(BenchmarkOOM):
                runtime.request_embedding(Embedder(), ["synthetic"], "document", profile, Tokenizer(), code, ledger, "oom-test")
        self.assertEqual(ledger.record["status"], "oom")
        self.assertIsNone(ledger.record["tokens"], "OOM did not establish consumed-token count")
        self.assertIsNone(ledger.record["receipt"]["token_consumption"])


if __name__ == "__main__":
    unittest.main()
