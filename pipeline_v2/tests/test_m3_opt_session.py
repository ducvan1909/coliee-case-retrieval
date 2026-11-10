"""FastSession tests using synthetic artifacts only; no baseline corpus or service."""
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from pipeline_v2.optimization import index as opt_index
from pipeline_v2.optimization.common import seal, write_json
from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.source.core import digest


class FakeStore:
    def __init__(self, hit):
        self.hit = hit
        self.calls = []
        self.full_verify_calls = 0
        self.path = "/collections/fixture"

    def info(self):
        return {"config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}}}

    def _request(self, method, path, body):
        self.calls.append((method, path, body))
        if path.endswith("/points/count"):
            return {"count": 1}
        raise AssertionError(f"Unexpected database operation: {method} {path}")

    def search(self, vector, limit, exclude_case):
        self.calls.append(("search", limit, exclude_case))
        return [self.hit]

    def verify(self, *args, **kwargs):
        self.full_verify_calls += 1
        raise AssertionError("per-query path must not run full collection verification")

    def scroll(self, *args, **kwargs):
        raise AssertionError("per-query path must not scroll the full collection")


class FastSessionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "index"
        self.directory.mkdir()
        self.baseline = self.root / "baseline"
        self.baseline.mkdir()
        self.source_dir = self.root / "data" / "task1_train_files_2026" / "cases"
        self.source_dir.mkdir(parents=True)
        self.raw = b"\xef\xbb\xbfnot Caf\xc3\xa9 under s. 5(1)(c).\r\n"
        (self.source_dir / "000001.txt").write_bytes(self.raw)
        self.source_hash = digest(self.raw)

        self.opt_profile = {
            "schema_version": "pipeline-v2-m3-opt-1",
            "baseline_run": "pipeline_v2/artifacts/baseline",
            "baseline_code_sha256": "irrelevant-in-stubbed-loader",
            "embedding": {"gpu": "L4"},
            "benchmark": {"batch_sizes": [16, 32, 64, 128], "repeats": 2},
            "search": {"score_atol": 1e-4},
        }
        self.base_profile = {
            "batch_size": 16,
            "embedding": {"dimensions": 3},
            "fusion": {"scan_cap": 10, "k": 60},
            "qdrant": {"url": "http://unused.invalid", "collection": "fixture", "embedding_fingerprint": "embed-fixture", "dimensions": 3},
        }
        (self.root / "pipeline_v2" / "configs").mkdir(parents=True)
        config_bytes = (json.dumps(self.base_profile) + "\n").encode("utf-8")
        (self.root / "pipeline_v2" / "configs" / "m3.json").write_bytes(config_bytes)
        tokenizer_path = self.root / "pipeline_v2" / "configs" / "qwen3_embedding_4b_tokenizer.lock.json"
        tokenizer_path.write_text("{}\n", encoding="utf-8")

        self.passage = {
            "passage_id": "p000024:fixture", "case_id": "000001.txt", "source_hash": self.source_hash,
            "exact_input_sha256": "input-hash", "span_bytes": [3, len(self.raw) - 2], "parent_handle": "p000024",
            "policy_hash": "policy", "tokenizer_fingerprint": "tokenizer", "text": self.raw[3:-2].decode("utf-8"),
        }
        lexical_path = self.directory / "lexical.sqlite3"
        lexical = opt_index.PersistentBM25.create(lexical_path, {
            "case": [{"case_id": "000001.txt", "text": "not Café under 5(1)(c)"}],
            "passage": [self.passage],
        })
        lexical.close()
        np.save(self.directory / "vectors.npy", np.array([[1.0, 0.0, 0.0]], dtype=np.float32), allow_pickle=False)

        (self.baseline / "pilot_manifest.json").write_text("{}\n", encoding="utf-8")
        self.base = {
            "implementation": {"frozen": "baseline-implementation"},
            "profile": self.base_profile,
            "embedding_fingerprint": "embed-fixture",
            "collection": "fixture",
            "passage_ids": [self.passage["passage_id"]],
            "input_hashes": ["input-hash"],
            "source_hashes": {"000001.txt": self.source_hash},
        }
        self.manifest = {
            "profile": self.opt_profile,
            "optimization_implementation": {"frozen": "opt-implementation"},
            "baseline_manifest_sha256": digest((self.baseline / "pilot_manifest.json").read_bytes()),
            "baseline_manifest": self.base,
            "passage_ids": [self.passage["passage_id"]],
            "source_hashes": self.base["source_hashes"],
            "upstream_fingerprints": {
                "pipeline_v2/configs/m3.json": digest(config_bytes),
                "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json": digest(tokenizer_path.read_bytes()),
            },
        }
        write_json(self.directory / "manifest.json", self.manifest)
        write_json(self.directory / "seal.json", {"files": seal(self.directory, ["lexical.sqlite3", "vectors.npy", "manifest.json"])})

        self.hit = {k: self.passage[k] for k in ("passage_id", "case_id", "source_hash", "exact_input_sha256", "span_bytes", "parent_handle", "policy_hash", "tokenizer_fingerprint")}
        self.hit.update({"embedding_fingerprint": "embed-fixture", "score": 1.0})
        self.store = FakeStore(self.hit)
        self.patches = [
            patch("pipeline_v2.optimization.index.load_profile", side_effect=lambda root: self.opt_profile),
            patch("pipeline_v2.optimization.index.implementation", side_effect=lambda: {"frozen": "opt-implementation"}),
            patch("pipeline_v2.optimization.index.baseline_implementation", side_effect=lambda: {"frozen": "baseline-implementation"}),
            patch("pipeline_v2.optimization.index.artifact", side_effect=self.fake_artifact),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.session = opt_index.FastSession(self.root, self.directory, self.store)
        def close_session():
            self.session.close()
            self.session.vectors = None  # release the Windows mmap before temp cleanup
        self.addCleanup(close_session)

    def fake_artifact(self, root, path):
        if Path(path).name == "baseline":
            return self.baseline
        return self.directory

    def test_query_checks_raw_hashes_and_only_targeted_database_results(self):
        self.assertEqual(self.raw[self.passage["span_bytes"][0]:self.passage["span_bytes"][1]].decode("utf-8"), self.passage["text"])
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in self.raw)
        result = self.session.search_vector("not Café under 5(1)(c)", [1.0, 0.0, 0.0], query_case="000002.txt", limit=5)
        self.assertEqual(result["scope"], "accepted_pilot_snapshot_only")
        self.assertEqual(result["query_case_excluded"], "000002.txt")
        self.assertEqual(result["guards"]["raw_content_hashes"], "all_selected_cases")
        self.assertFalse(result["guards"]["database"].startswith("full"))
        self.assertTrue(self.store.calls[0][1].endswith("/points/count"))
        self.assertEqual(self.store.calls[1], ("search", 10, "000002.txt"))
        self.assertEqual(self.store.full_verify_calls, 0)
        self.assertTrue(all("text" not in ch[0] for ch in result["channels"].values() if ch))

    def test_raw_hash_drift_rejected_before_database_search(self):
        (self.source_dir / "000001.txt").write_bytes(self.raw + b"tampered")
        with self.assertRaisesRegex(M3Error, "Raw source content drift"):
            self.session.search_vector("café", [1.0, 0.0, 0.0])
        self.assertEqual(self.store.calls, [])

    def test_dense_payload_drift_rejected(self):
        self.store.hit = {**self.hit, "span_bytes": [12, 31]}
        with self.assertRaisesRegex(M3Error, "payload mismatch"):
            self.session.search_vector("café", [1.0, 0.0, 0.0])

    def test_readonly_index_seal_detects_lexical_database_mutation(self):
        self.session.close()
        db = opt_index.sqlite3.connect(self.directory / "lexical.sqlite3")
        with db:
            db.execute("UPDATE documents SET metadata='{}' WHERE kind='passage'")
        db.close()
        with self.assertRaisesRegex(M3Error, "integrity failure"):
            self.session.guard()

    def test_code_and_profile_drift_are_rejected(self):
        with patch("pipeline_v2.optimization.index.implementation", return_value={"changed": "code"}):
            with self.assertRaisesRegex(M3Error, "code/profile drift"):
                self.session.guard()
        with patch("pipeline_v2.optimization.index.load_profile", return_value={**self.opt_profile, "schema_version": "changed"}):
            with self.assertRaisesRegex(M3Error, "code/profile drift"):
                self.session.guard()

    def test_bad_vector_is_rejected_before_store_access(self):
        with self.assertRaises(M3Error):
            self.session.search_vector("café", [float("nan"), 0.0, 0.0])
        self.assertEqual(self.store.calls, [])


if __name__ == "__main__":
    unittest.main()
