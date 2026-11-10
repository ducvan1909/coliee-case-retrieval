import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from pipeline_v2.retrieval import pilot
from pipeline_v2.retrieval.cache import Cache, run_lock
from pipeline_v2.retrieval.common import M3Error


class M3ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.run = Path(self.tmp) / "run"
        self.run.mkdir()
        self.root = Path(self.tmp)
        self.profile = {"pilot_size": 32, "batch_size": 16, "max_attempts": 3,
                        "embedding": {"dimensions": 3},
                        "numerics": {"norm_atol": .002}}
        self.manifest = {"profile": self.profile, "embedding_fingerprint": "fp",
                         "implementation": {"code.py": "sha"}, "m2_seal_sha256": "seal"}
        self.passages = [{"passage_id": f"{i:06}:p1", "case_id": f"{i:06}.txt",
                          "exact_input_sha256": f"hash-{i}", "text": f"source text {i}"}
                         for i in range(32)]
        (self.run / "preflight.json").write_text(json.dumps({
            "embedding_fingerprint": "fp", "implementation": {"code.py": "sha"},
            "status": "PASS", "m2_seal_sha256": "seal"
        }))
        self.cache = Cache(self.run, "fp", dimensions=3)
        self.addCleanup(self.cache.db.close)
        self.embedder = Mock()
        self.db = Mock()
        self.db.verify.return_value = {"status": "PASS", "points": 32}
        self.db.search.return_value = []

        def encode(embedder, texts, kind, profile, tokenizer, code, cache, batch_id):
            return np.tile(np.asarray([[1., 0., 0.]], dtype=np.float32), (len(texts), 1)), {"input_tokens": len(texts)}

        self.call_embedding = Mock(side_effect=encode)
        self.patches = [
            patch.object(pilot, "load_run", side_effect=lambda *args: (self.root, self.run, self.manifest, None, self.passages)),
            patch.object(pilot, "resources", return_value=(None, self.cache, self.embedder, self.db)),
            patch.object(pilot, "call_embedding", self.call_embedding),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_batch_boundary_resume_reuses_committed_vectors_and_upserts_idempotently(self):
        first = pilot.run_pilot(self.root, "pipeline_v2/artifacts/fake", stop_after_batches=1)
        self.assertEqual(first["status"], "stopped_at_batch_boundary")
        self.assertEqual(self.call_embedding.call_count, 1)
        second = pilot.run_pilot(self.root, "pipeline_v2/artifacts/fake", stop_after_batches=2)
        self.assertEqual(second["status"], "stopped_at_batch_boundary")
        self.assertEqual(self.call_embedding.call_count, 2)
        self.assertEqual(self.db.upsert.call_count, 3)  # first batch is safely re-upserted on resume
        self.assertEqual(len(self.cache.get_batch([p["passage_id"] for p in self.passages[:16]],
                                                 [p["exact_input_sha256"] for p in self.passages[:16]])), 16)

    def test_corrupt_committed_batch_stops_resume_before_embedding_or_database_write(self):
        pilot.run_pilot(self.root, "pipeline_v2/artifacts/fake", stop_after_batches=1)
        self.call_embedding.reset_mock()
        self.db.upsert.reset_mock()
        ids = [p["passage_id"] for p in self.passages[:16]]
        base = self.cache._base(ids)
        base.with_suffix(".npz").write_bytes(b"partial-or-corrupt")
        with self.assertRaises(M3Error):
            pilot.run_pilot(self.root, "pipeline_v2/artifacts/fake", stop_after_batches=2)
        self.call_embedding.assert_not_called()
        self.db.upsert.assert_not_called()

    def test_orphan_vector_shard_is_identity_checked_before_recovery(self):
        ids = ["orphan:p1", "orphan:p2"]
        hashes = ["a", "b"]
        vectors = np.asarray([[1., 0., 0.], [0., 1., 0.]], dtype=np.float32)
        base = self.cache._base(ids)
        base.parent.mkdir(parents=True, exist_ok=True)
        with base.with_suffix(".npz").open("wb") as stream:
            np.savez(stream, vectors=vectors, ids=np.asarray(ids), input_hashes=np.asarray(hashes), fingerprint=np.asarray("fp"))
        self.assertTrue(np.array_equal(self.cache.get_batch(ids, hashes), vectors))
        wrong = ["different", "hash"]
        with self.assertRaises(M3Error):
            self.cache.get_batch(ids, wrong)

    def test_same_run_lock_rejects_concurrent_owner(self):
        with run_lock(self.run):
            with self.assertRaises(M3Error):
                with run_lock(self.run):
                    pass


if __name__ == "__main__":
    unittest.main()
