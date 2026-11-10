"""Synthetic snapshot tests; no Modal, labels, or corpus data are accessed."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from pipeline_v2.optimization_v2 import index as opt_index
from pipeline_v2.optimization_v2.common import seal
from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.source.core import canonical, digest


class FastSessionSnapshotTests(unittest.TestCase):
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
        self.raw = "Café not a waiver.\n".encode("utf-8")
        (self.source_dir / "000001.txt").write_bytes(self.raw)
        self.source_hash = digest(self.raw)

        self.opt_profile = {"schema_version": "pipeline-v2-m3-opt-2", "baseline_run": "pipeline_v2/artifacts/baseline",
                            "embedding": {"gpu": "L4"}, "search": {"score_atol": 1e-4}}
        self.base_profile = {
            "batch_size": 16,
            "embedding": {"dimensions": 3},
            "fusion": {"scan_cap": 10, "k": 60},
            "qdrant": {"url": "http://unused.invalid", "collection": "fixture", "embedding_fingerprint": "embed-fixture", "dimensions": 3},
            "passages_bundle": "fixture-passages",
        }
        (self.root / "pipeline_v2" / "configs").mkdir(parents=True)
        (self.root / "pipeline_v2" / "configs" / "m3.json").write_bytes(canonical(self.base_profile))
        self.passage = {
            "passage_id": "p000024:fixture", "case_id": "000001.txt", "source_hash": self.source_hash,
            "exact_input_sha256": digest(self.raw), "span_bytes": [0, len(self.raw)], "parent_handle": "p000024",
            "policy_hash": "policy", "tokenizer_fingerprint": "tokenizer",
        }
        lexical = opt_index.PersistentBM25.create(self.directory / "lexical.sqlite3", {
            "passage": [{**self.passage, "text": self.raw.decode("utf-8")}],
            "case": [{"case_id": "000001.txt", "source_hash": self.source_hash, "text": self.raw.decode("utf-8")}],
        })
        lexical.close()
        np.save(self.directory / "vectors.npy", np.array([[1.0, 0.0, 0.0]], dtype=np.float32), allow_pickle=False)

        self.base = {
            "implementation": {"frozen": "baseline-implementation"},
            "profile": self.base_profile,
            "embedding_fingerprint": "embed-fixture",
            "collection": "fixture",
            "passage_ids": [self.passage["passage_id"]],
            "input_hashes": [self.passage["exact_input_sha256"]],
            "source_hashes": {"000001.txt": self.source_hash},
        }
        baseline_bytes = canonical(self.base)
        (self.baseline / "pilot_manifest.json").write_bytes(baseline_bytes)
        self.manifest = {
            "schema_version": "pipeline-v2-m3-opt-index-2",
            "profile": self.opt_profile,
            "optimization_implementation": {"frozen": "opt-implementation"},
            "baseline_manifest_sha256": digest(baseline_bytes),
            "baseline_manifest": self.base,
            "passage_ids": [self.passage["passage_id"]],
            "source_hashes": self.base["source_hashes"],
            "upstream_fingerprints": {},
        }
        (self.directory / "manifest.json").write_bytes(canonical(self.manifest))
        (self.directory / "seal.json").write_bytes(canonical({"files": seal(
            self.directory, ["lexical.sqlite3", "vectors.npy", "manifest.json"])}))
        self.hit = {**self.passage, "embedding_fingerprint": "embed-fixture", "score": 1.0}
        self.store = FakeStore(self.hit)
        self.patches = [
            patch("pipeline_v2.optimization_v2.index.load_profile", return_value=self.opt_profile),
            patch("pipeline_v2.optimization_v2.index.implementation", return_value={"frozen": "opt-implementation"}),
            patch("pipeline_v2.optimization_v2.index.baseline_implementation", return_value={"frozen": "baseline-implementation"}),
            patch("pipeline_v2.optimization_v2.index.artifact", side_effect=self.fake_artifact),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def fake_artifact(self, root, name):
        return self.baseline if Path(name).name == "baseline" else self.directory

    def open_session(self):
        return opt_index.FastSession(self.root, self.directory, self.store)

    def test_open_does_not_preload_passage_metadata_or_scan_all_vector_norms(self):
        with patch.object(opt_index.PersistentBM25, "iter_documents", side_effect=AssertionError("full metadata iteration")), \
             patch.object(opt_index, "validate_vectors", side_effect=AssertionError("full vector scan")):
            session = self.open_session()
        self.addCleanup(session.close)
        self.assertEqual(session.ids, [self.passage["passage_id"]])
        self.assertEqual(session.vectors.shape, (1, 3))
        self.assertEqual(session.passage_metadata([self.passage["passage_id"]])[0]["parent_handle"], "p000024")

    def test_evidence_open_rechecks_raw_hash_before_reading_context(self):
        session = self.open_session()
        self.addCleanup(session.close)
        (self.source_dir / "000001.txt").write_bytes(self.raw + b"tamper")
        with patch("pipeline_v2.passages.PassageReader", side_effect=AssertionError("reader called before source verification")):
            with self.assertRaisesRegex(M3Error, "evidence source hash drift"):
                session.open(self.passage["passage_id"])

    def test_session_contract_requires_explicit_revalidation_after_workspace_changes(self):
        session = self.open_session()
        self.addCleanup(session.close)
        # The hot-path guard is deliberately cheap; explicit revalidation hashes source.
        (self.source_dir / "000001.txt").write_bytes(self.raw + b"changed")
        session.guard()
        with self.assertRaisesRegex(M3Error, "evidence source hash drift"):
            session.revalidate()
        with self.assertRaisesRegex(M3Error, "invalidated"):
            session.guard()

    def test_external_but_well_formed_query_case_is_noop_filter_and_bad_id_fails_before_store(self):
        session = self.open_session()
        self.addCleanup(session.close)
        self.store.calls.clear()
        expected = session.search_vector("café", [1.0, 0.0, 0.0], query_case=None, limit=3)
        self.store.calls.clear()
        actual = session.search_vector("café", [1.0, 0.0, 0.0], query_case="123456.txt", limit=3)
        self.assertEqual(actual["results"], expected["results"])
        self.assertIn(("search", 10, "123456.txt"), self.store.calls)
        self.store.calls.clear()
        with self.assertRaises(M3Error):
            session.search_vector("café", [1.0, 0.0, 0.0], query_case="outside.txt", limit=3)
        self.assertEqual(self.store.calls, [])


class FakeStore:
    path = "/collections/fixture"

    def __init__(self, hit):
        self.hit = hit
        self.calls = []

    def info(self):
        self.calls.append(("info",))
        return {"config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}}}

    def _request(self, method, path, body):
        self.calls.append((method, path, body))
        return {"count": 1}

    def search(self, vector, limit, exclude_case):
        self.calls.append(("search", limit, exclude_case))
        return [self.hit]


if __name__ == "__main__":
    unittest.main()
