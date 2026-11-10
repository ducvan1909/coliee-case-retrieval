import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pipeline_v2.retrieval import pilot
from pipeline_v2.retrieval.common import M3Error, write_json
from pipeline_v2.source.core import digest


class M3PilotTests(unittest.TestCase):
    @staticmethod
    def passage(i):
        return {"passage_id": f"00000{i+1}:p000001", "case_id": f"00000{i+1}.txt",
                "full_input_tokens": 100 + i, "paragraph_role": "current_case", "unit_kind": "paragraph",
                "split_count": 1, "split_order": 0,
                "text": "Unicode café" if i % 2 else "plain legal text"}

    def test_seeded_sample_is_order_independent_unique_and_fixed_size(self):
        rows = [self.passage(i) for i in range(12)]
        a = pilot.sample_passages(rows, size=5, seed=17)
        b = pilot.sample_passages(list(reversed(rows)), size=5, seed=17)
        self.assertEqual([x["passage_id"] for x in a], [x["passage_id"] for x in b])
        self.assertEqual(len(a), 5)
        self.assertEqual(len({x["passage_id"] for x in a}), 5)
        with self.assertRaises(M3Error):
            pilot.sample_passages(rows[:4], size=5, seed=17)

    def test_load_run_rejects_duplicate_ids_in_sealed_pilot_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "pipeline_v2/artifacts/duplicate-run"
            run.mkdir(parents=True)
            profile = {"pilot_size": 2, "passages_bundle": "pipeline_v2/artifacts/m2",
                       "accepted_m2_seal_sha256": "accepted-seal"}
            implementation = {"code.py": "sha"}
            manifest = {"scope": "pilot_only", "profile": profile, "implementation": implementation,
                        "passage_ids": ["000001:p1", "000001:p1"], "m2_seal_sha256": "accepted-seal",
                        "input_hashes": ["h1", "h1"], "source_hashes": {}}
            write_json(run / "pilot_manifest.json", manifest)
            write_json(run / "manifest.sha256.json", {"sha256": digest((run / "pilot_manifest.json").read_bytes())})
            with patch.object(pilot, "load_profile", return_value=profile), \
                 patch.object(pilot, "implementation", return_value=implementation):
                with self.assertRaisesRegex(M3Error, "duplicate pilot universe"):
                    pilot.load_run(root, "pipeline_v2/artifacts/duplicate-run")

    def test_dense_verification_rejects_duplicate_point_ids_even_when_count_and_scores_match(self):
        passages = [self.passage(i) for i in range(4)]
        vectors = np.asarray([[1., 0., 0.], [.9, (1 - .9**2) ** .5, 0.],
                              [0., 1., 0.], [0., 0., 1.]], dtype=np.float32)
        profile = {"embedding": {"dimensions": 3}, "numerics": {"search_score_atol": 1e-4}}
        manifest = {"embedding_fingerprint": "fp", "profile": profile}

        class DuplicateStore:
            def verify(self, rows, cached):
                return {"status": "PASS", "points": len(rows)}

            def search(self, query, limit, exclude_case):
                valid = [i for i, row in enumerate(passages) if row["case_id"] != exclude_case]
                scores = vectors @ query
                ranked = sorted(valid, key=lambda i: (-float(scores[i]), passages[i]["passage_id"]))
                top = ranked[0]
                return [{"passage_id": passages[top]["passage_id"],
                         "case_id": passages[top]["case_id"], "score": float(scores[top])}
                        for _ in ranked]

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pilot, "load_run", return_value=(Path(tmp), Path(tmp), manifest, None, passages)), \
                 patch.object(pilot, "Cache"), patch.object(pilot, "load_vectors", return_value=vectors):
                with self.assertRaisesRegex(M3Error, "duplicate|membership|exact|reference"):
                    pilot.verify_pilot(tmp, "pipeline_v2/artifacts/fake", store=DuplicateStore())

    def test_case_and_passage_bm25_both_use_the_frozen_profile_parameters(self):
        profile = {"bm25": {"k1": 1.2, "b": .4}, "fusion": {"scan_cap": 16, "k": 60},
                   "embedding": {"dimensions": 3}, "batch_size": 16}
        manifest = {"profile": profile, "embedding_fingerprint": "fp",
                    "implementation": {"code": "sha"}, "m2_seal_sha256": "seal"}
        passage = {"passage_id": "000001:p1", "case_id": "000001.txt", "text": "body"}

        class Corpus:
            class Reader:
                class Nav:
                    class Source:
                        @staticmethod
                        def _source(case_id):
                            return b"raw source", None
                    source = Source()
                nav = Nav()
            reader = Reader()

        class Cache:
            @staticmethod
            def usage():
                return {"model_requests": 1}

        class Store:
            @staticmethod
            def verify(passages, vectors):
                return {"status": "PASS"}

            @staticmethod
            def search(vector, limit, exclude_case):
                return []

        observed = []

        class CapturingBM25:
            def __init__(self, documents, k1=1.5, b=.75):
                observed.append((k1, b))
                self.documents = documents

            def search(self, query, limit, exclude_case):
                return [{"case_id": row["case_id"], "passage_id": row.get("passage_id", "case"), "score": 1.0}
                        for row in self.documents if row["case_id"] != exclude_case][:limit]

        with patch.object(pilot, "load_run", return_value=(Path("."), Path("."), manifest, Corpus(), [passage])), \
             patch.object(pilot, "resources", return_value=(None, Cache(), None, Store())), \
             patch.object(pilot, "Cache", return_value=Cache()), \
             patch.object(pilot, "load_vectors", return_value=np.ones((1, 3), dtype=np.float32)), \
             patch.object(pilot, "call_embedding", return_value=(np.ones((1, 3), dtype=np.float32), {})), \
             patch.object(pilot, "read_json", return_value={"embedding_fingerprint": "fp",
                       "implementation": {"code": "sha"}, "m2_seal_sha256": "seal", "status": "PASS"}), \
             patch.object(pilot, "BM25", CapturingBM25), \
             patch.object(pilot, "run_lock", return_value=nullcontext()):
            pilot.search_pilot(".", "pipeline_v2/artifacts/fake", "query", limit=1)
        self.assertEqual(observed, [(1.2, .4), (1.2, .4)])


if __name__ == "__main__":
    unittest.main()
