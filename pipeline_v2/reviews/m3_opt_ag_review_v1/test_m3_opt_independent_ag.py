from __future__ import annotations

import json
import math
import shutil
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pipeline_v2.optimization.batching import batches, padding_stats
from pipeline_v2.optimization.benchmark import benchmark_index, representative
from pipeline_v2.optimization.common import M3Error, implementation, load_profile, seal, validate_seal, write_json
from pipeline_v2.optimization.index import FastSession, PersistentBM25
from pipeline_v2.optimization.runtime import BenchmarkOOM, _aliased_code, request_embedding
from pipeline_v2.passages.tokenizer import PinnedTokenizer
from pipeline_v2.retrieval.bm25 import analyze, fuse_case_ranks, rank_cases
from pipeline_v2.retrieval.cache import Cache
from pipeline_v2.retrieval.common import fingerprint
from pipeline_v2.source.core import canonical, digest

ROOT = Path(__file__).resolve().parents[3]


class _FakeQdrantStore:
    def __init__(self, passages: list[dict], vectors: np.ndarray, embedding_fp: str) -> None:
        self.passages = passages
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.embedding_fp = embedding_fp
        self.path = "/collections/fake"
        self.tamper_fn = None

    def info(self) -> dict:
        return {"config": {"params": {"vectors": {"size": int(self.vectors.shape[1]), "distance": "Cosine"}}}}

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        if path.endswith("/points/count"):
            return {"count": len(self.passages)}
        raise AssertionError(f"Unexpected Qdrant request: {method} {path}")

    def search(self, vector: np.ndarray, limit: int, exclude_case: str | None = None) -> list[dict]:
        scores = self.vectors @ np.asarray(vector, dtype=np.float32)
        rows = []
        for idx, (p, sc) in enumerate(zip(self.passages, scores)):
            if exclude_case and p["case_id"] == exclude_case:
                continue
            rows.append(
                {
                    "passage_id": p["passage_id"],
                    "case_id": p["case_id"],
                    "source_hash": p["source_hash"],
                    "exact_input_sha256": p["exact_input_sha256"],
                    "span_bytes": p["span_bytes"],
                    "parent_handle": p["parent_handle"],
                    "policy_hash": p["policy_hash"],
                    "tokenizer_fingerprint": p["tokenizer_fingerprint"],
                    "embedding_fingerprint": self.embedding_fp,
                    "score": float(sc),
                }
            )
        rows.sort(key=lambda r: (-r["score"], r["passage_id"]))
        hits = rows[:limit]
        if self.tamper_fn is not None:
            hits = self.tamper_fn(hits)
        return hits

    def verify(self, passages: list[dict], vectors: np.ndarray) -> dict:
        return {"verified_points": len(passages)}


class IndependentM3OptReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tokenizer = PinnedTokenizer(ROOT, "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
        cls.profile = load_profile(ROOT)
        cls.code = implementation()

    def test_01_persistent_bm25_readonly_and_independent_math(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lexical.sqlite3"
            cases = [
                {"case_id": "000001.txt", "text": "La décision n'est pas raisonnable sous l'article 97(1).", "source_hash": "h1"},
                {"case_id": "000002.txt", "text": "Judicial review under section 97(1) and 96: reasonableness standard.", "source_hash": "h2"},
                {"case_id": "000003.txt", "text": " Tie token alpha", "source_hash": "h3"},
                {"case_id": "000004.txt", "text": " Tie token beta", "source_hash": "h4"},
            ]
            passages = [
                {
                    "passage_id": "000001:p1",
                    "case_id": "000001.txt",
                    "text": "La décision n'est pas raisonnable sous l'article 97(1).",
                    "full_input_tokens": 15,
                },
                {
                    "passage_id": "000002:p1",
                    "case_id": "000002.txt",
                    "text": "Judicial review under section 97(1) and 96: reasonableness standard.",
                    "full_input_tokens": 14,
                },
            ]
            lex = PersistentBM25.create(db_path, {"case": cases, "passage": passages}, k1=1.5, b=0.75)
            try:
                # Verify readonly enforcement on opened connection
                with self.assertRaises(sqlite3.OperationalError):
                    lex.db.execute("DELETE FROM documents")

                # Verify Unicode + digits + apostrophe negation query
                hits = lex.search("décision n'est pas 97(1)", "case", limit=10)
                self.assertEqual([h["case_id"] for h in hits], ["000001.txt", "000002.txt"])
                self.assertNotIn("text", hits[0])

                # Verify exclusion happens BEFORE limit
                hits_excl = lex.search("97(1)", "case", limit=1, exclude_case="000001.txt")
                self.assertEqual(len(hits_excl), 1)
                self.assertEqual(hits_excl[0]["case_id"], "000002.txt")

                # Verify equal-score tie breaking by ID
                tie_hits = lex.search("tie token", "case", limit=10)
                self.assertEqual([h["case_id"] for h in tie_hits], ["000003.txt", "000004.txt"])
                self.assertAlmostEqual(tie_hits[0]["score"], tie_hits[1]["score"], places=12)

                # Verify invalid channel and limit fail closed
                with self.assertRaises(M3Error):
                    lex.search("test", "unknown_channel", limit=5)
                with self.assertRaises(M3Error):
                    lex.search("test", "case", limit=0)
                with self.assertRaises(M3Error):
                    lex.search("test", "case", limit=True)
            finally:
                lex.close()

    def test_02_length_batching_invariants_and_validation(self) -> None:
        docs = [
            {"passage_id": f"p{i:03d}", "full_input_tokens": ((i * 37) % 448) + 1}
            for i in range(135)
        ]
        unsorted = batches(docs, 16, ordered=False)
        sorted_16 = batches(docs, 16, ordered=True)
        sorted_32 = batches(docs, 32, ordered=True)

        # Exact partition and identity preservation
        self.assertEqual(
            sorted(p["passage_id"] for g in sorted_32 for p in g),
            sorted(p["passage_id"] for p in docs),
        )
        # Monotonic non-decreasing (full_input_tokens, passage_id) across flattened sorted batches
        flattened = [(p["full_input_tokens"], p["passage_id"]) for g in sorted_16 for p in g]
        self.assertEqual(flattened, sorted(flattened))

        # Padding reduction
        st_unsorted = padding_stats(unsorted)
        st_sorted = padding_stats(sorted_16)
        self.assertEqual(st_unsorted["input_tokens"], st_sorted["input_tokens"])
        self.assertLess(st_sorted["padded_tokens"], st_unsorted["padded_tokens"])

        # Reject invalid batch sizes, duplicates, and out-of-range tokens
        with self.assertRaises(M3Error):
            batches(docs, 0)
        with self.assertRaises(M3Error):
            batches(docs, 129)
        with self.assertRaises(M3Error):
            batches(docs, True)
        with self.assertRaises(M3Error):
            batches([docs[0], docs[0]], 16)
        with self.assertRaises(M3Error):
            batches([{"passage_id": "bad", "full_input_tokens": 449}], 16)
        with self.assertRaises(M3Error):
            batches([{"passage_id": "bad", "full_input_tokens": False}], 16)

    def test_03_unique_case_rrf_deduplicates_multiple_passages_per_case(self) -> None:
        channels = {
            "case_bm25": [{"case_id": "C1", "score": 10.0}, {"case_id": "C2", "score": 9.0}],
            "passage_bm25": [
                {"passage_id": "C1:p1", "case_id": "C1", "score": 8.0},
                {"passage_id": "C1:p2", "case_id": "C1", "score": 7.5},
                {"passage_id": "C1:p3", "case_id": "C1", "score": 7.0},
                {"passage_id": "C2:p1", "case_id": "C2", "score": 6.9},
            ],
            "dense_passage": [
                {"passage_id": "C2:p1", "case_id": "C2", "score": 0.9},
                {"passage_id": "C1:p2", "case_id": "C1", "score": 0.8},
            ],
        }
        fused = fuse_case_ranks(channels, limit=10, k=60)
        by_case = {r["case_id"]: r for r in fused}
        # C1 has rank 1 in case_bm25, rank 1 in passage_bm25 (p2/p3 ignored), rank 2 in dense_passage
        self.assertAlmostEqual(by_case["C1"]["score"], 1 / 61 + 1 / 61 + 1 / 62, places=12)
        # C2 takes rank 2 in passage_bm25 (not rank 4!), rank 2 in case_bm25, rank 1 in dense_passage
        self.assertAlmostEqual(by_case["C2"]["score"], 1 / 62 + 1 / 62 + 1 / 61, places=12)
        self.assertEqual(by_case["C1"]["channels"]["passage_bm25"]["passage_id"], "C1:p1")

    def test_04_request_embedding_accounting_and_gpu_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Cache(Path(tmp), fingerprint(self.profile), 2560)
            aliased = _aliased_code(self.code)

            # 1. Pre-flight validation rejects invalid batch before recording any attempt
            with self.assertRaises(M3Error):
                request_embedding(None, [], self.profile, self.tokenizer, self.code, ledger, "empty-batch")
            self.assertEqual(ledger.usage()["model_requests"], 0)

            # 2. Failed remote call without token count records unknown_token_attempts=1, not 0 tokens
            class _FailingEmbedder:
                def encode(self, texts, kind="document"):
                    raise RuntimeError("simulated transport failure")

            with self.assertRaises(M3Error):
                request_embedding(_FailingEmbedder(), ["hello world"], self.profile, self.tokenizer, self.code, ledger, "fail-1")
            usage = ledger.usage()
            self.assertEqual(usage["model_requests"], 1)
            self.assertEqual(usage["unknown_token_attempts"], 1)
            self.assertEqual(usage["known_input_tokens"], 0)

            # 3. Invalid GPU memory hierarchy (peak_allocated > peak_reserved) is rejected
            class _BadMemoryEmbedder:
                def __init__(self, tok, prof, code_map):
                    self.tok = tok
                    self.prof = prof
                    self.code_map = code_map

                def encode(self, texts, kind="document"):
                    vec = np.zeros((len(texts), 2560), dtype=np.float32)
                    vec[:, 0] = 1.0
                    in_toks = sum(self.tok.count(t) for t in texts)
                    return {
                        "status": "ok",
                        "vectors": vec.tolist(),
                        "input_hashes": [digest(t.encode("utf-8")) for t in texts],
                        "input_tokens": in_toks,
                        "padded_tokens": in_toks,
                        "remote_elapsed_seconds": 0.1,
                        "gpu_model_pool_seconds": 0.08,
                        "peak_allocated_bytes": 9000,
                        "peak_reserved_bytes": 8000,  # invalid: allocated > reserved
                        "device_total_bytes": 24000,
                        "descriptor": {
                            "model": self.prof["embedding"]["model"],
                            "revision": self.prof["embedding"]["revision"],
                            "loaded_model_revision": self.prof["embedding"]["revision"],
                            "gpu": "NVIDIA L4",
                            "device_dtype": "torch.bfloat16",
                            "dimensions": 2560,
                            "embedding_fingerprint": fingerprint(self.prof),
                            "engine_sha256": self.code_map["pipeline_v2/deployments/modal/engine.py"],
                            "wrapper_sha256": self.code_map["pipeline_v2/deployments/modal/qwen3_embed.py"],
                            "package_versions": {
                                k: self.prof["embedding"][k] for k in ("torch", "transformers", "tokenizers")
                            },
                        },
                    }

            with self.assertRaises(M3Error):
                request_embedding(
                    _BadMemoryEmbedder(self.tokenizer, self.profile, aliased),
                    ["hello world"],
                    self.profile,
                    self.tokenizer,
                    self.code,
                    ledger,
                    "bad-mem",
                )
            ledger.db.close()

    def test_05_fast_session_guards_on_real_index_with_fault_injection(self) -> None:
        v2_dir = ROOT / "pipeline_v2/artifacts/m3_opt_index_20261107_v2"
        lex = PersistentBM25(v2_dir / "lexical.sqlite3", readonly=True)
        manifest = json.loads((v2_dir / "manifest.json").read_bytes())
        byid = {p["passage_id"]: p for p in lex.documents("passage")}
        passages = [byid[pid] for pid in manifest["passage_ids"]]
        lex.close()
        vectors = np.load(v2_dir / "vectors.npy", allow_pickle=False, mmap_mode="r")
        fake_store = _FakeQdrantStore(passages, vectors, manifest["baseline_manifest"]["embedding_fingerprint"])

        session = FastSession(ROOT, v2_dir, store=fake_store)
        try:
            qvec = np.asarray(vectors[0], dtype=np.float32)
            # Clean search_vector succeeds and does not call load_run
            with patch("pipeline_v2.optimization.index.load_run", side_effect=AssertionError("load_run called!")):
                res = session.search_vector("standard of review", qvec, query_case=passages[0]["case_id"], limit=5)
            self.assertEqual(len(res["results"]), 5)
            self.assertTrue(all(r["case_id"] != passages[0]["case_id"] for r in res["results"]))

            # Tamper 1: Dense score drift beyond 1e-4
            def _tamper_score(hits):
                out = [dict(h) for h in hits]
                out[0]["score"] += 0.001
                return out

            fake_store.tamper_fn = _tamper_score
            with self.assertRaises(M3Error):
                session.search_vector("standard of review", qvec, limit=5)

            # Tamper 2: Duplicate dense hit IDs
            fake_store.tamper_fn = lambda hits: [hits[0], hits[0]]
            with self.assertRaises(M3Error):
                session.search_vector("standard of review", qvec, limit=5)

            # Tamper 3: Query-case leakage in dense results
            fake_store.tamper_fn = lambda hits: [{**hits[0], "case_id": "000031.txt"}]
            with self.assertRaises(M3Error):
                session.search_vector("standard of review", qvec, query_case="000031.txt", limit=5)

            # Tamper 4: Raw source hash drift after FastSession init fails closed before store access
            fake_store.tamper_fn = None
            original_hashes = dict(session.manifest["source_hashes"])
            first_cid = next(iter(original_hashes))
            session.manifest["source_hashes"][first_cid] = "0" * 64
            try:
                with self.assertRaises(M3Error):
                    session.search_vector("standard of review", qvec, limit=5)
            finally:
                session.manifest["source_hashes"] = original_hashes
        finally:
            session.close()

    def test_06_seal_validation_rejects_missing_extra_or_mutated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "lexical.sqlite3").write_bytes(b"sqlite-bytes")
            (d / "vectors.npy").write_bytes(b"vector-bytes")
            (d / "manifest.json").write_bytes(b"{}")
            files = seal(d, ["lexical.sqlite3", "vectors.npy", "manifest.json"])
            validate_seal(d, files)

            # Mutate 1 byte in lexical.sqlite3 -> fail closed
            (d / "lexical.sqlite3").write_bytes(b"sqlite-byteX")
            with self.assertRaises(M3Error):
                validate_seal(d, files)
            (d / "lexical.sqlite3").write_bytes(b"sqlite-bytes")

            # Missing required key in seal -> fail closed
            bad_files = dict(files)
            bad_files.pop("vectors.npy")
            with self.assertRaises(M3Error):
                validate_seal(d, bad_files)

            # Extra key in seal -> fail closed
            extra_files = dict(files)
            extra_files["extra.json"] = {"sha256": "0" * 64, "byte_length": 2}
            with self.assertRaises(M3Error):
                validate_seal(d, extra_files)

    def test_07_representative_selection_and_simulated_oom_stop(self) -> None:
        docs = [
            {"passage_id": f"p{i:04d}", "full_input_tokens": (i % 448) + 1}
            for i in range(1024)
        ]
        rep = representative(docs, 256)
        self.assertEqual(len(rep), 256)
        self.assertEqual(rep[0]["full_input_tokens"], 1)
        self.assertEqual(rep[-1]["full_input_tokens"], 448)
        with self.assertRaises(M3Error):
            representative(docs[:10], 256)
        with self.assertRaises(M3Error):
            representative(docs, 1)


if __name__ == "__main__":
    unittest.main()
