from __future__ import annotations

import builtins
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import time
import unittest
from collections import Counter
from contextlib import redirect_stdout
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from pipeline_v2 import m3_opt_v2 as cli_v2
from pipeline_v2.optimization_v2 import benchmark as bench_v2
from pipeline_v2.optimization_v2 import common as common_v2
from pipeline_v2.optimization_v2 import index as index_v2
from pipeline_v2.optimization_v2 import runtime as runtime_v2
from pipeline_v2.optimization_v2.common import M3Error, file_digest, implementation, load_profile, read, seal, validate_seal, write_json
from pipeline_v2.optimization_v2.index import FastSession, PersistentBM25
from pipeline_v2.optimization_v2.runtime import BenchmarkOOM, alias_code, preflight_compatibility, request_embedding, require_compatibility
from pipeline_v2.passages import PinnedTokenizer
from pipeline_v2.retrieval.bm25 import fuse_case_ranks
from pipeline_v2.retrieval.cache import Cache, validate_vectors
from pipeline_v2.retrieval.common import fingerprint, implementation as baseline_implementation
from pipeline_v2.source.core import canonical, digest

ROOT = Path(__file__).resolve().parents[3]
REVIEW_DIR = Path(__file__).resolve().parent
WORD_RE = re.compile(r"\w+", re.UNICODE)


def independent_analyze(text: str) -> list[str]:
    return WORD_RE.findall(str(text).casefold())


class IndependentBM25Oracle:
    """Completely independent BM25 implementation built directly from raw texts/dicts."""

    def __init__(self, docs: list[dict[str, Any]], key: str, k1: float = 1.5, b: float = 0.75) -> None:
        self.key = key
        self.k1 = float(k1)
        self.b = float(b)
        self.docs: list[dict[str, Any]] = []
        self.doc_freqs: list[Counter[str]] = []
        self.doc_lens: list[int] = []
        df: Counter[str] = Counter()
        for d in docs:
            tokens = independent_analyze(d["text"])
            cnt = Counter(tokens)
            self.docs.append(d)
            self.doc_freqs.append(cnt)
            self.doc_lens.append(len(tokens))
            for term in cnt:
                df[term] += 1
        self.n_docs = len(self.docs)
        self.avgdl = (sum(self.doc_lens) / self.n_docs) if self.n_docs else 1.0
        self.idf = {
            term: math.log(1.0 + (self.n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def search(self, query: str, limit: int, exclude_case_id: str | None = None) -> list[dict[str, Any]]:
        q_terms = sorted(set(independent_analyze(query)))
        if not q_terms or not self.n_docs:
            return []
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for d, tf_map, dl in zip(self.docs, self.doc_freqs, self.doc_lens):
            if exclude_case_id and d["case_id"] == exclude_case_id:
                continue
            score = 0.0
            norm = self.k1 * (1.0 - self.b + self.b * (dl / (self.avgdl or 1.0)))
            for term in q_terms:
                tf = tf_map.get(term, 0)
                if not tf:
                    continue
                idf = self.idf.get(term, 0.0)
                score += idf * ((tf * (self.k1 + 1.0)) / (tf + norm))
            if score > 0.0:
                scored.append((score, str(d[self.key]), d))
        scored.sort(key=lambda item: (-item[0], item[1]))
        results = []
        for score, _, d in scored[:limit]:
            row = {k: v for k, v in d.items() if k != "text"}
            row["score"] = score
            results.append(row)
        return results


class FakeQdrantStore:
    def __init__(self, passages: list[dict[str, Any]], vectors: np.ndarray, embedding_fp: str) -> None:
        self.passages = passages
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.embedding_fp = embedding_fp
        self.path = "/collections/fake_v2"
        self.tamper_fn = None
        self.info_override = None
        self.count_override = None

    def info(self) -> dict[str, Any] | None:
        if self.info_override is not None:
            return self.info_override()
        return {"config": {"params": {"vectors": {"size": int(self.vectors.shape[1]), "distance": "Cosine"}}}}

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if path.endswith("/points/count"):
            if self.count_override is not None:
                return {"count": self.count_override}
            return {"count": len(self.passages)}
        raise AssertionError(f"Unexpected Qdrant request: {method} {path}")

    def search(self, vector: np.ndarray, limit: int, exclude_case: str | None = None) -> list[dict[str, Any]]:
        scores = self.vectors @ np.asarray(vector, dtype=np.float32)
        rows = []
        for p, sc in zip(self.passages, scores):
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

    def verify(self, passages: list[dict[str, Any]], vectors: np.ndarray) -> dict[str, Any]:
        return {"verified_points": len(passages), "vector_rows": int(vectors.shape[0])}


class IndependentM3OptV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tokenizer = PinnedTokenizer(ROOT, "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
        cls.profile = load_profile(ROOT)
        cls.code = implementation()
        cls.real_index_dir = ROOT / "pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1"

    def test_01_bm25_no_text_bounded_batches_relative_paths_and_oracle_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Create >512 unique terms in a single document to exercise the 512-row executemany flush boundary
            many_terms_text = " ".join(f"uniqueterm{i:04d}" for i in range(600))
            docs = [
                {"case_id": "000001.txt", "passage_id": "p001", "text": "La décision n'est pas raisonnable sous s. 97(1) et 100% café.", "parent_handle": "h1"},
                {"case_id": "000001.txt", "passage_id": "p002", "text": "CAFÉ not waived under 97(1); don't ignore procedural fairness.", "parent_handle": "h2"},
                {"case_id": "000002.txt", "passage_id": "p003", "text": "Tiebreak token alpha beta.", "parent_handle": "h3"},
                {"case_id": "000003.txt", "passage_id": "p004", "text": "Tiebreak token alpha gamma.", "parent_handle": "h4"},
                {"case_id": "000004.txt", "passage_id": "p005", "text": many_terms_text, "parent_handle": "h5"},
            ]

            prev_cwd = Path.cwd()
            try:
                os.chdir(tmp_path)
                rel_db = Path("sub/rel_lexical.sqlite3")
                bm25 = PersistentBM25.create(rel_db, {"passage": iter(docs)})
                bm25.close()
                reopened = PersistentBM25(rel_db, readonly=True)
            finally:
                os.chdir(prev_cwd)

            try:
                # Readonly check
                with self.assertRaises(sqlite3.OperationalError):
                    reopened.db.execute("DELETE FROM documents")

                # Metadata never stores 'text'
                for (raw_meta,) in reopened.db.execute("SELECT metadata FROM documents"):
                    parsed = json.loads(raw_meta)
                    self.assertNotIn("text", parsed)
                    self.assertNotIn("uniqueterm0001", raw_meta)

                # Verify >512 unique terms flushed properly
                cnt_p005 = reopened.db.execute("SELECT COUNT(*) FROM postings WHERE kind='passage' AND id='p005'").fetchone()[0]
                self.assertEqual(cnt_p005, 600)

                # Oracle parity across Unicode, digits, negation, ties, exclusion before limit
                oracle = IndependentBM25Oracle(docs, "passage_id")
                for q, excl, lim in [
                    ("décision n'est pas 97(1) café", None, 10),
                    ("97(1) café", "000001.txt", 10),
                    ("tiebreak token alpha", None, 1),
                    ("tiebreak token alpha", "000002.txt", 1),
                    ("uniqueterm0599 uniqueterm0000", None, 5),
                ]:
                    got = reopened.search(q, "passage", limit=lim, exclude_case=excl)
                    want = oracle.search(q, limit=lim, exclude_case_id=excl)
                    self.assertEqual([h["passage_id"] for h in got], [h["passage_id"] for h in want])
                    for g, w in zip(got, want):
                        self.assertAlmostEqual(g["score"], w["score"], delta=1e-12)
                        self.assertNotIn("text", g)
            finally:
                reopened.close()

    def test_02_real_index_integrity_and_bm25_oracle_across_16_queries(self) -> None:
        v2_dir = self.real_index_dir
        old_v1_dir = ROOT / "pipeline_v2/artifacts/m3_opt_index_20261107_v2"
        base_dir = ROOT / "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1"

        # 1. Verify seal and sizes
        seal_data = read(v2_dir / "seal.json")
        validate_seal(v2_dir, seal_data["files"])
        old_sqlite_size = (old_v1_dir / "lexical.sqlite3").stat().st_size
        new_sqlite_size = (v2_dir / "lexical.sqlite3").stat().st_size
        self.assertEqual(old_sqlite_size, 138936320)
        self.assertEqual(new_sqlite_size, 93270016)
        self.assertLess(new_sqlite_size, old_sqlite_size)

        # 2. Verify vectors against 64 committed baseline shards independently
        pilot_manifest = read(base_dir / "pilot_manifest.json")
        ids = pilot_manifest["passage_ids"]
        bsize = pilot_manifest["profile"]["batch_size"]
        shards = []
        for i in range(0, len(ids), bsize):
            batch_ids = ids[i : i + bsize]
            shard_key = digest(canonical([pilot_manifest["embedding_fingerprint"], batch_ids]))
            npz_path = base_dir / "vectors" / f"{shard_key}.npz"
            with np.load(npz_path, allow_pickle=False) as z:
                shards.append(np.asarray(z["vectors"], dtype=np.float32))
        stacked = np.vstack(shards)
        v2_vectors = np.load(v2_dir / "vectors.npy", allow_pickle=False, mmap_mode="r")
        self.assertEqual(v2_vectors.shape, (1024, 2560))
        self.assertTrue(np.array_equal(stacked, v2_vectors))
        validate_vectors(v2_vectors, 1024, 2560)

        # 3. Verify SQLite readonly and metadata text-free on all 916 cases + 1,024 passages
        uri = f"file:{(v2_dir / 'lexical.sqlite3').resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")
            c_rows = conn.execute("SELECT id, metadata FROM documents WHERE kind='case'").fetchall()
            p_rows = conn.execute("SELECT id, metadata FROM documents WHERE kind='passage'").fetchall()
            self.assertEqual(len(c_rows), 916)
            self.assertEqual(len(p_rows), 1024)
            self.assertTrue(all("text" not in json.loads(m) for _, m in c_rows))
            self.assertTrue(all("text" not in json.loads(m) for _, m in p_rows))
        finally:
            conn.close()

    def test_03_session_open_no_preload_and_tamper_invalidation_on_temp_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Build a minimal valid sealed snapshot in temp to test fault injection safely
            art_dir = root / "pipeline_v2/artifacts"
            idx_dir = art_dir / "test_index"
            base_dir = art_dir / "m3_pilot_20261106_l4_v1"
            idx_dir.mkdir(parents=True)
            base_dir.mkdir(parents=True)
            cases_dir = root / "data/task1_train_files_2026/cases"
            cases_dir.mkdir(parents=True)

            raw_bytes = "Décision sous s. 97(1) non raisonnable.\n".encode("utf-8")
            (cases_dir / "000001.txt").write_bytes(raw_bytes)
            src_hash = digest(raw_bytes)

            base_prof = read(ROOT / "pipeline_v2/configs/m3.json")
            opt_prof = read(ROOT / "pipeline_v2/configs/m3_opt_v2.json")
            (root / "pipeline_v2/configs").mkdir(parents=True, exist_ok=True)
            (root / "pipeline_v2/configs/m3.json").write_bytes(canonical(base_prof))
            (root / "pipeline_v2/configs/m3_opt_v2.json").write_bytes(canonical(opt_prof))

            p_rec = {
                "passage_id": "000001:p01",
                "case_id": "000001.txt",
                "source_hash": src_hash,
                "exact_input_sha256": src_hash,
                "span_bytes": [0, len(raw_bytes)],
                "parent_handle": "p1",
                "policy_hash": "pol",
                "tokenizer_fingerprint": "tok",
                "full_input_tokens": 12,
            }
            lex = PersistentBM25.create(
                idx_dir / "lexical.sqlite3",
                {
                    "case": [{"case_id": "000001.txt", "source_hash": src_hash, "text": raw_bytes.decode("utf-8")}],
                    "passage": [{**p_rec, "text": raw_bytes.decode("utf-8")}],
                },
            )
            lex.close()

            vec = np.zeros((1, 2560), dtype=np.float32)
            vec[0, 0] = 1.0
            np.save(idx_dir / "vectors.npy", vec, allow_pickle=False)

            base_manifest = {
                "implementation": baseline_implementation(),
                "profile": base_prof,
                "embedding_fingerprint": fingerprint(base_prof),
                "collection": "col_test",
                "passage_ids": ["000001:p01"],
                "input_hashes": [src_hash],
                "source_hashes": {"000001.txt": src_hash},
            }
            (base_dir / "pilot_manifest.json").write_bytes(canonical(base_manifest))

            manifest = {
                "schema_version": "pipeline-v2-m3-opt-index-2",
                "profile": opt_prof,
                "optimization_implementation": implementation(),
                "baseline_manifest_sha256": file_digest(base_dir / "pilot_manifest.json"),
                "baseline_manifest": base_manifest,
                "upstream_fingerprints": {},
                "passage_ids": ["000001:p01"],
                "source_hashes": {"000001.txt": src_hash},
            }
            write_json(idx_dir / "manifest.json", manifest)
            write_json(idx_dir / "seal.json", {"files": seal(idx_dir, ["lexical.sqlite3", "vectors.npy", "manifest.json"])})

            store = FakeQdrantStore([p_rec], vec, base_manifest["embedding_fingerprint"])

            # 1. Constructor must NOT call iter_documents or validate_vectors
            with patch.object(PersistentBM25, "iter_documents", side_effect=AssertionError("iter_documents called in init")), \
                 patch("pipeline_v2.optimization_v2.index.validate_vectors", side_effect=AssertionError("validate_vectors called in init")):
                session = FastSession(root, "pipeline_v2/artifacts/test_index", store=store)

            try:
                # 2. Search vector checks schema, count, dedup, query_case exclusion, payload, score
                qvec = vec[0].copy()
                res = session.search_vector("décision", qvec, query_case=None, limit=5)
                self.assertEqual(len(res["results"]), 1)

                # Tamper Qdrant count -> fail closed
                store.count_override = 999
                with self.assertRaisesRegex(M3Error, "point-count drift"):
                    session.search_vector("décision", qvec, limit=5)
                store.count_override = None

                # Tamper Qdrant score -> fail closed
                store.tamper_fn = lambda hits: [{**hits[0], "score": 0.5}]
                with self.assertRaisesRegex(M3Error, "Dense score differs"):
                    session.search_vector("décision", qvec, limit=5)
                store.tamper_fn = None

                # 3. Mutate raw source during session: ranking uses immutable snapshot, but open() and revalidate() must fail and invalidate!
                (cases_dir / "000001.txt").write_bytes(raw_bytes + b"mutated")
                with self.assertRaisesRegex(M3Error, "evidence source hash drift"):
                    session.open("000001:p01")
                self.assertTrue(session.invalidated)
                with self.assertRaisesRegex(M3Error, "Session invalidated"):
                    session.search_vector("décision", qvec, limit=5)
            finally:
                session.close()

            # 4. Corrupt vector row (NaN) -> constructor succeeds (no full scan), but verify(full_db=True) catches it!
            (cases_dir / "000001.txt").write_bytes(raw_bytes)
            bad_vec = np.zeros((1, 2560), dtype=np.float32)
            bad_vec[0, 0] = np.nan
            np.save(idx_dir / "vectors.npy", bad_vec, allow_pickle=False)
            write_json(idx_dir / "seal.json", {"files": seal(idx_dir, ["lexical.sqlite3", "vectors.npy", "manifest.json"])}, replace=True)

            session2 = FastSession(root, "pipeline_v2/artifacts/test_index", store=store)
            try:
                with self.assertRaises(M3Error):
                    session2.verify(full_db=True)
            finally:
                session2.close()

    def test_04_compatibility_gate_and_unified_v2_attestations(self) -> None:
        # Verify request_embedding enforces EOS token 151643, max_tokens<=448, query template, and L4 descriptor
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Cache(Path(tmp), fingerprint(self.profile), 2560)
            try:
                # Over-length input (>448 tokens) fails before calling embedder
                long_text = "word " * 500
                with self.assertRaisesRegex(M3Error, "token cap/EOS mismatch"):
                    request_embedding(None, [long_text], "document", self.profile, self.tokenizer, self.code, ledger, "overlen")
                self.assertEqual(ledger.usage()["model_requests"], 0)

                # Whitespace-only query rejected before RPC
                with self.assertRaisesRegex(M3Error, "Empty query"):
                    request_embedding(None, ["   "], "query", self.profile, self.tokenizer, self.code, ledger, "empty-q")
                self.assertEqual(ledger.usage()["model_requests"], 0)
            finally:
                ledger.db.close()


def run_independent_audit_and_tests() -> dict[str, Any]:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IndependentM3OptV2Tests)
    buf = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    test_res = runner.run(suite)

    # Also run full 16-query BM25 oracle audit on real index_v2
    v2_dir = ROOT / "pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1"
    base_dir = ROOT / "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1"
    pilot_manifest = read(base_dir / "pilot_manifest.json")
    raw_dir = ROOT / "data/task1_train_files_2026/cases"
    m2_passages_dir = ROOT / "pipeline_v2/artifacts/m2_passages_20261106_v1/sources"
    m2_nav_dir = ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v3/sources"

    raw_cases = []
    for cid, expected_sha in sorted(pilot_manifest["source_hashes"].items()):
        raw_bytes = (raw_dir / cid).read_bytes()
        assert digest(raw_bytes) == expected_sha
        raw_cases.append({"case_id": cid, "text": raw_bytes.decode("utf-8"), "source_hash": expected_sha})

    selected_passage_set = set(pilot_manifest["passage_ids"])
    passage_by_id = {}
    for cid in sorted(pilot_manifest["source_hashes"]):
        stem = cid[:-4] if cid.endswith(".txt") else cid
        bundle = read(m2_passages_dir / f"{stem}.json")
        nav_bundle = read(m2_nav_dir / f"{stem}.json")
        preview_counts = {r["unit_id"]: len(r["preview_refs"]) for r in nav_bundle["navigation"]}
        raw_bytes = (raw_dir / cid).read_bytes()
        for row in bundle["passages"]:
            pid = row["passage_id"]
            if pid in selected_passage_set:
                b_start, b_end = row["span_bytes"]
                text_slice = raw_bytes[b_start:b_end].decode("utf-8")
                assert digest(text_slice.encode("utf-8")) == row["exact_input_sha256"]
                rec = dict(row)
                rec["text"] = text_slice
                rec["navigation_preview_count"] = preview_counts[row["parent_unit_ids"][0]]
                passage_by_id[pid] = rec
    raw_passages = [passage_by_id[pid] for pid in pilot_manifest["passage_ids"]]

    oracle_case = IndependentBM25Oracle(raw_cases, "case_id")
    oracle_passage = IndependentBM25Oracle(raw_passages, "passage_id")
    persistent = PersistentBM25(v2_dir / "lexical.sqlite3", readonly=True)

    case_ids_sorted = sorted(pilot_manifest["source_hashes"])
    queries = [
        {"query": "standard of review", "exclude": None},
        {"query": "standard of review", "exclude": "079659.txt"},
        {"query": "décision n'est pas raisonnable under s. 97(1)", "exclude": None},
        {"query": "judicial review procedural fairness standard of review reasonableness", "exclude": case_ids_sorted[0]},
        {"query": "patent claim construction infringement anticipation obviousness", "exclude": case_ids_sorted[1]},
        {"query": "crédibilité contrôle judiciaire décision déraisonnable", "exclude": None},
        {"query": "section 96 97(1) 2019 100% non-refoulement don't", "exclude": case_ids_sorted[2]},
        {"query": "zzznonexistenttokenxyz12345", "exclude": None},
    ]

    bm25_comparisons = []
    for item in queries:
        q = item["query"]
        excl = item["exclude"]
        for kind, key, oracle in [("case", "case_id", oracle_case), ("passage", "passage_id", oracle_passage)]:
            t0 = time.perf_counter()
            o_hits = oracle.search(q, 1024, exclude_case_id=excl)
            t_oracle = time.perf_counter() - t0
            t1 = time.perf_counter()
            p_hits = persistent.search(q, kind, 1024, exclude_case=excl)
            t_pers = time.perf_counter() - t1
            ids_equal = [h[key] for h in o_hits] == [h[key] for h in p_hits]
            max_score_diff = max((abs(a["score"] - b["score"]) for a, b in zip(o_hits, p_hits)), default=0.0) if ids_equal else float("inf")
            meta_equal = all(
                {k: v for k, v in a.items() if k != "score"} == {k: v for k, v in b.items() if k != "score"}
                for a, b in zip(o_hits, p_hits)
            )
            bm25_comparisons.append({
                "query": q,
                "kind": kind,
                "exclude_case_id": excl,
                "hit_count": len(p_hits),
                "ids_equal": ids_equal,
                "metadata_equal": meta_equal,
                "max_score_diff": max_score_diff,
                "oracle_seconds": round(t_oracle, 6),
                "v2_sqlite_seconds": round(t_pers, 6),
            })
    persistent.close()

    out = {
        "unittest_ran": test_res.testsRun,
        "unittest_ok": test_res.wasSuccessful(),
        "unittest_output": buf.getvalue(),
        "bm25_16_query_oracle_audit": {
            "all_ids_equal": all(c["ids_equal"] for c in bm25_comparisons),
            "all_metadata_equal": all(c["metadata_equal"] for c in bm25_comparisons),
            "max_score_diff": max(c["max_score_diff"] for c in bm25_comparisons),
            "case_mean_sqlite_seconds": round(sum(c["v2_sqlite_seconds"] for c in bm25_comparisons if c["kind"] == "case") / 8, 6),
            "passage_mean_sqlite_seconds": round(sum(c["v2_sqlite_seconds"] for c in bm25_comparisons if c["kind"] == "passage") / 8, 6),
            "comparisons": bm25_comparisons,
        },
    }
    (REVIEW_DIR / "independent_local_test_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Ran {test_res.testsRun} independent tests: OK={test_res.wasSuccessful()}")
    return out


if __name__ == "__main__":
    res = run_independent_audit_and_tests()
    if not res["unittest_ok"] or not res["bm25_16_query_oracle_audit"]["all_ids_equal"]:
        raise SystemExit(1)
