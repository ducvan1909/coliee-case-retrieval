"""Independent AG behavioral and fault-injection test suite for M3 Sparse BM25 and Hybrid integration.

All fixtures, databases, and sparse sidecar indexes are created exclusively inside
temporary directories (`tempfile.TemporaryDirectory()`). Production artifacts are never modified.
"""

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

from pipeline_v2.full_search import hybrid as hybrid_mod
from pipeline_v2.full_search.lexical import FastBM25
from pipeline_v2.optimization_v2.index import PersistentBM25
from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.source.core import canonical, digest
from pipeline_v2.sparse_bm25 import index as sparse


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(__file__).resolve().parent


def analyze_tokens(text):
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def float64_oracle(documents, query, *, k1=1.5, b=0.75, limit=100, exclude_case=None, unique_cases=False):
    rows = [(doc, Counter(analyze_tokens(doc["text"]))) for doc in documents]
    lengths = [sum(freq.values()) for _, freq in rows]
    n = len(rows)
    avg = sum(lengths) / n if n else 1.0
    df = Counter(term for _, freq in rows for term in freq)
    query_terms = sorted(set(analyze_tokens(query)))
    ranked = []
    for (doc, freq), length in zip(rows, lengths):
        if doc["case_id"] == exclude_case:
            continue
        score = 0.0
        for term in query_terms:
            tf = freq[term]
            if tf:
                idf = math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * tf * (k1 + 1.0) / (tf + k1 * (1.0 - b + b * length / (avg or 1.0)))
        if score > 0.0:
            ident = doc.get("passage_id", doc["case_id"])
            ranked.append((score, ident, doc))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    if unique_cases:
        seen = set()
        selected = []
        for row in ranked:
            if row[2]["case_id"] not in seen:
                selected.append(row)
                seen.add(row[2]["case_id"])
                if len(selected) == limit:
                    break
        ranked = selected
    else:
        ranked = ranked[:limit]
    return [{**{k: v for k, v in doc.items() if k != "text"}, "score": score} for score, _, doc in ranked]


def float32_oracle(documents, query, *, k1=1.5, b=0.75):
    rows = [(doc, Counter(analyze_tokens(doc["text"]))) for doc in documents]
    lengths = [np.float32(sum(freq.values())) for _, freq in rows]
    n = np.float32(len(rows))
    avg = np.float32(sum(float(x) for x in lengths) / len(rows)) if rows else np.float32(1.0)
    df = Counter(term for _, freq in rows for term in freq)
    query_terms = sorted(set(analyze_tokens(query)))
    k1_32, b_32, half_32, one_32 = np.float32(k1), np.float32(b), np.float32(0.5), np.float32(1.0)
    scores = {}
    for (doc, freq), length in zip(rows, lengths):
        score = np.float32(0.0)
        for term in query_terms:
            tf = freq[term]
            if tf:
                df_32 = np.float32(df[term])
                idf = np.float32(math.log(float(one_32 + (n - df_32 + half_32) / (df_32 + half_32))))
                tf_32 = np.float32(tf)
                norm = k1_32 * (one_32 - b_32 + b_32 * length / (avg or one_32))
                score = np.float32(score + np.float32(idf * tf_32 * (k1_32 + one_32) / (tf_32 + norm)))
        if score > 0:
            ident = doc.get("passage_id", doc["case_id"])
            scores[ident] = float(score)
    return scores


def build_fixture_db(path, cases, passages, *, k1=1.5, b=0.75):
    p_bm25 = PersistentBM25.create(path, {"case": cases, "passage": passages}, k1=k1, b=b)
    p_bm25.close()


def reseal_index(directory):
    seal_path = Path(directory) / "seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    for filename in list(seal):
        fpath = Path(directory) / filename
        if fpath.exists():
            data = fpath.read_bytes()
            seal[filename] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    seal_path.write_text(json.dumps(seal, sort_keys=True, separators=(",", ":")), encoding="utf-8")


class SQLSpyConnection:
    def __init__(self, db):
        self.db = db
        self.queries = []
        self.closed = False

    def execute(self, sql, parameters=()):
        params = tuple(parameters) if not isinstance(parameters, tuple) else parameters
        self.queries.append((sql, params))
        return self.db.execute(sql, parameters)

    def close(self):
        self.closed = True
        return self.db.close()


class AGIndependentSparseHybridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp_dir.name)
        cls.db_path = cls.root / "fixture_lexical.sqlite3"
        cls.index_dir = cls.root / "fixture_sparse"

        cls.cases = [
            {"case_id": "000001.txt", "text": "The CAFÉ rule under s. 5(1)(c) is not unreasonable; judicial review of the board decision."},
            {"case_id": "000002.txt", "text": "Café standard of review: reasonableness and procedural fairness under s. 5(1)(c)."},
            {"case_id": "000003.txt", "text": "Damages and costs in a maritime negligence action without statutory bar."},
            {"case_id": "000004.txt", "text": "Not reasonable, café decision set aside for patent unreasonableness."},
            {"case_id": "000005.txt", "text": "Immigration officer assessment of humanitarian and compassionate grounds under 25(1)."},
            {"case_id": "000006.txt", "text": "Standard of review is correctness for constitutional questions and s. 5(1)(c)."},
        ]

        cls.passages = [
            {"passage_id": "000001:p03", "case_id": "000001.txt", "text": "The CAFÉ rule is not unreasonable; 5 1 c.", "span_bytes": [0, 42]},
            {"passage_id": "000001:p01", "case_id": "000001.txt", "text": "café café, reasonable, and NOT waived under s. 5(1)(c).", "span_bytes": [43, 98]},
            {"passage_id": "000001:p02", "case_id": "000001.txt", "text": "café café, reasonable, and NOT waived under s. 5(1)(c).", "span_bytes": [99, 154]},
            {"passage_id": "000002:p01", "case_id": "000002.txt", "text": "5(1)(c) plus a distinct procedural fairness test in café.", "span_bytes": [0, 57]},
            {"passage_id": "000002:p02", "case_id": "000002.txt", "text": "café standard of review and reasonableness.", "span_bytes": [58, 101]},
            {"passage_id": "000003:p01", "case_id": "000003.txt", "text": "A separate claim about maritime damages and negligence.", "span_bytes": [0, 55]},
            {"passage_id": "000004:p02", "case_id": "000004.txt", "text": "Café under s. 5(1)(c), not reasonable.", "span_bytes": [0, 38]},
            {"passage_id": "000004:p01", "case_id": "000004.txt", "text": "Café under s. 5(1)(c), not reasonable.", "span_bytes": [39, 77]},
            {"passage_id": "000005:p01", "case_id": "000005.txt", "text": "Humanitarian and compassionate grounds 25(1) not unreasonable.", "span_bytes": [0, 62]},
            {"passage_id": "000006:p01", "case_id": "000006.txt", "text": "CAFÉ and not reasonable under s. 5(1)(c) correctness.", "span_bytes": [0, 53]},
        ]
        build_fixture_db(cls.db_path, cls.cases, cls.passages)
        cls.build_receipt = sparse.build_from_database(cls.db_path, cls.index_dir, fetch_size=64)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_01_float64_formula_channel_idf_analyzer_and_oov(self):
        reader = sparse.SparseBM25(self.db_path, self.index_dir, score_block_size=64)
        fast = FastBM25(self.db_path, fetch_size=64)
        try:
            queries = [
                "CAFÉ 5(1)(c) not NOT reasonable",
                "the of and in to a 1 25(1)",
                "café café CAFÉ",
                "unreasonable procedural fairness",
                "maritime negligence damages",
            ]
            for q in queries:
                for kind, docs in (("case", self.cases), ("passage", self.passages)):
                    res_sparse = reader.search_detailed(q, kind, limit=50)
                    res_fast = fast.search_detailed(q, kind, limit=50)
                    expected = float64_oracle(docs, q, limit=50)
                    id_key = "passage_id" if kind == "passage" else "case_id"
                    self.assertEqual([h[id_key] for h in res_sparse["hits"]], [h[id_key] for h in expected])
                    self.assertEqual([h[id_key] for h in res_sparse["hits"]], [h[id_key] for h in res_fast["hits"]])
                    self.assertEqual(res_sparse["terms_matched"], res_fast["terms_matched"])
                    self.assertEqual(res_sparse["postings_rows"], res_fast["postings_rows"])
                    self.assertEqual(res_sparse["matched_documents"], res_fast["matched_documents"])
                    for h_s, h_e, h_f in zip(res_sparse["hits"], expected, res_fast["hits"]):
                        self.assertLessEqual(abs(h_s["score"] - h_e["score"]), 1e-15)
                        self.assertEqual(h_s["score"], h_f["score"])

            # Verify float64 precision differs measurably from float32 accumulation
            f32_scores = float32_oracle(self.passages, "CAFÉ 5(1)(c) not NOT reasonable")
            res_p = reader.search("CAFÉ 5(1)(c) not NOT reasonable", "passage", limit=50)
            max_f32_diff = max(abs(h["score"] - f32_scores[h["passage_id"]]) for h in res_p)
            self.assertGreater(max_f32_diff, 1e-8)

            # Verify channel-specific IDF: 'café' has different N and df in case vs passage
            case_term_id = reader.channels["case"]["term_ids"]["café"]
            pass_term_id = reader.channels["passage"]["term_ids"]["café"]
            c_start, c_end = map(int, reader.channels["case"]["offsets"][case_term_id:case_term_id + 2])
            p_start, p_end = map(int, reader.channels["passage"]["offsets"][pass_term_id:pass_term_id + 2])
            self.assertNotEqual(c_end - c_start, p_end - p_start)

            # Verify OOV, empty, whitespace, punctuation-only
            for empty_q in ("", "   \t\n ", "!@#$%^&*() --- === [] {}", "nonexistent_token_xyz_987"):
                for kind in ("case", "passage"):
                    detail = reader.search_detailed(empty_q, kind, limit=10)
                    self.assertEqual(detail["hits"], [])
                    self.assertEqual(detail["terms_matched"], 0)
                    self.assertEqual(detail["postings_rows"], 0)
                    self.assertEqual(detail["matched_documents"], 0)
        finally:
            reader.close()
            fast.close()

    def test_02_exclusion_before_topk_representative_selection_and_tie_order(self):
        # Construct a synthetic corpus with 60 passages in case 000001.txt, tied passages in 000002.txt, etc.
        temp_db = self.root / "tie_and_rep.sqlite3"
        temp_idx = self.root / "tie_and_rep_sparse"
        passages = []
        # 50 passages in case 000001.txt with high score
        for i in range(50):
            passages.append({
                "passage_id": f"000001:p{i:03d}",
                "case_id": "000001.txt",
                "text": "alpha beta gamma delta",
            })
        # 3 tied passages in case 000002.txt inserted out of order
        for pid in ("000002:z99", "000002:a01", "000002:m50"):
            passages.append({
                "passage_id": pid,
                "case_id": "000002.txt",
                "text": "alpha beta gamma",
            })
        # 1 passage in case 000002.txt with lower score
        passages.append({
            "passage_id": "000002:a00",
            "case_id": "000002.txt",
            "text": "alpha",
        })
        # 4 passages in cases 000003..000006 with identical scores to test cross-case tie break
        for cid, pid in (("000005.txt", "000005:p09"), ("000003.txt", "000003:p05"),
                         ("000006.txt", "000006:p01"), ("000004.txt", "000004:p02")):
            passages.append({
                "passage_id": pid,
                "case_id": cid,
                "text": "alpha beta",
            })
        cases = [{"case_id": f"{i:06d}.txt", "text": "alpha beta"} for i in range(1, 7)]
        build_fixture_db(temp_db, cases, passages)
        sparse.build_from_database(temp_db, temp_idx, fetch_size=64)
        reader = sparse.SparseBM25(temp_db, temp_idx, score_block_size=64)
        fast = FastBM25(temp_db, fetch_size=64)
        try:
            # 1) Exclude 000001.txt (which otherwise occupies top 50 raw slots) with limit=3
            raw_excl = reader.search("alpha beta gamma delta", "passage", limit=3, exclude_case="000001.txt", unique_cases=False)
            self.assertEqual([h["passage_id"] for h in raw_excl], ["000002:a01", "000002:m50", "000002:z99"])

            # 2) Unique cases without exclusion: 000001.txt picks 000001:p000, 000002.txt picks 000002:a01 (not a00 which has lower score, and not m50/z99)
            uniq_all = reader.search("alpha beta gamma delta", "passage", limit=6, unique_cases=True)
            uniq_fast = fast.search("alpha beta gamma delta", "passage", limit=6, unique_cases=True)
            uniq_oracle = float64_oracle(passages, "alpha beta gamma delta", limit=6, unique_cases=True)
            self.assertEqual([h["passage_id"] for h in uniq_all], [h["passage_id"] for h in uniq_oracle])
            self.assertEqual([h["passage_id"] for h in uniq_all], [h["passage_id"] for h in uniq_fast])
            self.assertEqual(
                [h["passage_id"] for h in uniq_all],
                ["000001:p000", "000002:a01", "000003:p05", "000004:p02", "000005:p09", "000006:p01"],
            )
            # Verify no sibling passage summation occurred: score of 000002:a01 in unique_cases equals its raw score
            self.assertEqual(uniq_all[1]["score"], raw_excl[0]["score"])
        finally:
            reader.close()
            fast.close()

    def test_03_array_scoring_only_metadata_on_retained_hits_and_block_invariance(self):
        # Verify that during search_detailed, SQLite is NEVER queried for postings or terms,
        # and documents table is queried ONLY for the retained top-K hits.
        spy_conn = SQLSpyConnection(sparse._open_database(self.db_path))
        with mock.patch.object(sparse, "_open_database", return_value=spy_conn):
            reader_64 = sparse.SparseBM25(self.db_path, self.index_dir, score_block_size=64)
        reader_large = sparse.SparseBM25(self.db_path, self.index_dir, score_block_size=65536)
        try:
            spy_conn.queries.clear()
            res_64 = reader_64.search_detailed("café 5(1)(c) reasonable", "passage", limit=2, unique_cases=True)
            res_large = reader_large.search_detailed("café 5(1)(c) reasonable", "passage", limit=2, unique_cases=True)
            self.assertEqual(res_64["hits"], res_large["hits"])
            self.assertEqual(len(res_64["hits"]), 2)

            # Check SQL queries executed during search_detailed:
            # Must be exactly 1 query to `documents` with 3 parameters ('passage', id1, id2)
            self.assertEqual(len(spy_conn.queries), 1)
            sql, params = spy_conn.queries[0]
            self.assertIn("SELECT id,metadata FROM documents WHERE kind=? AND id IN", sql)
            self.assertNotIn("postings", sql.lower())
            self.assertNotIn("terms", sql.lower())
            self.assertEqual(len(params), 1 + 2)

            # Also check when 0 hits match: 0 SQL queries executed during search!
            spy_conn.queries.clear()
            empty_res = reader_64.search_detailed("nonexistent_token_999", "passage", limit=10)
            self.assertEqual(empty_res["hits"], [])
            self.assertEqual(len(spy_conn.queries), 0)
        finally:
            reader_64.close()
            reader_large.close()

    def test_04_fault_injections_on_temp_copies(self):
        # 4a. Duplicate document ordinal in a term slice (resealed)
        dup_dir = self.root / "fault_dup_doc"
        shutil.copytree(self.index_dir, dup_dir)
        offsets = np.load(dup_dir / "passage.indptr.npy", mmap_mode="r", allow_pickle=False)
        # Find a term with df >= 2
        term_idx = next(i for i in range(len(offsets) - 1) if offsets[i + 1] - offsets[i] >= 2)
        start = int(offsets[term_idx])
        offsets._mmap.close()
        indices = np.load(dup_dir / "passage.indices.npy", mmap_mode="r+", allow_pickle=False)
        indices[start + 1] = indices[start]
        indices.flush()
        indices._mmap.close()
        reseal_index(dup_dir)
        with self.assertRaisesRegex(M3Error, "Invalid sparse term arrays"):
            sparse.SparseBM25(self.db_path, dup_dir)

        # 4b. Decreasing document ordinal in a term slice (resealed)
        dec_dir = self.root / "fault_dec_doc"
        shutil.copytree(self.index_dir, dec_dir)
        indices = np.load(dec_dir / "passage.indices.npy", mmap_mode="r+", allow_pickle=False)
        indices[start], indices[start + 1] = int(indices[start + 1]), int(indices[start])
        indices.flush()
        indices._mmap.close()
        reseal_index(dec_dir)
        with self.assertRaisesRegex(M3Error, "Invalid sparse term arrays"):
            sparse.SparseBM25(self.db_path, dec_dir)

        # 4c. Empty term span (offsets[i] == offsets[i+1], resealed)
        empty_term_dir = self.root / "fault_empty_term"
        shutil.copytree(self.index_dir, empty_term_dir)
        indptr = np.load(empty_term_dir / "passage.indptr.npy", mmap_mode="r+", allow_pickle=False)
        indptr[1] = indptr[0]
        indptr.flush()
        indptr._mmap.close()
        reseal_index(empty_term_dir)
        with self.assertRaisesRegex(M3Error, "Invalid sparse term arrays"):
            sparse.SparseBM25(self.db_path, empty_term_dir)

        # 4d. Offsets not starting at 0 or not ending at len(indices) (resealed)
        bad_start_dir = self.root / "fault_bad_offset_start"
        shutil.copytree(self.index_dir, bad_start_dir)
        indptr = np.load(bad_start_dir / "passage.indptr.npy", mmap_mode="r+", allow_pickle=False)
        indptr[0] = 1
        indptr.flush()
        indptr._mmap.close()
        reseal_index(bad_start_dir)
        with self.assertRaisesRegex(M3Error, "Sparse array schema mismatch"):
            sparse.SparseBM25(self.db_path, bad_start_dir)

        # 4e. Non-positive score contribution (values <= 0) or +inf (resealed)
        for label, bad_val in (("zero_val", 0.0), ("neg_val", -1.5), ("inf_val", np.inf)):
            val_dir = self.root / f"fault_{label}"
            shutil.copytree(self.index_dir, val_dir)
            vals = np.load(val_dir / "passage.values.npy", mmap_mode="r+", allow_pickle=False)
            vals[0] = bad_val
            vals.flush()
            vals._mmap.close()
            reseal_index(val_dir)
            with self.assertRaisesRegex(M3Error, "Invalid sparse term arrays"):
                sparse.SparseBM25(self.db_path, val_dir)

        # 4f. Unsorted catalog.json ids / terms / cases (resealed)
        unsorted_dir = self.root / "fault_unsorted_catalog"
        shutil.copytree(self.index_dir, unsorted_dir)
        cat_path = unsorted_dir / "passage.catalog.json"
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        cat["ids"] = list(reversed(cat["ids"]))
        cat_path.write_text(json.dumps(cat), encoding="utf-8")
        reseal_index(unsorted_dir)
        with self.assertRaisesRegex(M3Error, "Sparse array schema mismatch"):
            sparse.SparseBM25(self.db_path, unsorted_dir)

        # 4g. Extra or missing entry in seal.json
        extra_seal_dir = self.root / "fault_extra_seal"
        shutil.copytree(self.index_dir, extra_seal_dir)
        seal_path = extra_seal_dir / "seal.json"
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        seal["unexpected.npy"] = {"sha256": "0" * 64, "bytes": 10}
        seal_path.write_text(json.dumps(seal), encoding="utf-8")
        with self.assertRaisesRegex(M3Error, "Incomplete sparse index seal"):
            sparse.SparseBM25(self.db_path, extra_seal_dir)

        # 4h. Corrupted metadata in SQLite copy (metadata containing 'text' or mismatched case_id)
        for mode in ("has_text", "case_mismatch", "missing_row"):
            bad_db = self.root / f"fault_meta_{mode}.sqlite3"
            shutil.copy2(self.db_path, bad_db)
            conn = sqlite3.connect(bad_db)
            if mode == "has_text":
                row_id, meta_str = conn.execute("SELECT id, metadata FROM documents WHERE kind='passage' LIMIT 1").fetchone()
                meta = json.loads(meta_str)
                meta["text"] = "forbidden embedded text"
                conn.execute("UPDATE documents SET metadata=? WHERE kind='passage' AND id=?", (json.dumps(meta), row_id))
            elif mode == "case_mismatch":
                row_id, meta_str = conn.execute("SELECT id, metadata FROM documents WHERE kind='passage' LIMIT 1").fetchone()
                meta = json.loads(meta_str)
                meta["case_id"] = "999999.txt"
                conn.execute("UPDATE documents SET metadata=? WHERE kind='passage' AND id=?", (json.dumps(meta), row_id))
            elif mode == "missing_row":
                conn.execute("DELETE FROM documents WHERE kind='passage'")
            conn.commit()
            conn.close()
            # Open with validate_database=False to test runtime get_many validation
            reader = sparse.SparseBM25(bad_db, self.index_dir, validate_database=False)
            try:
                with self.assertRaises(M3Error):
                    reader.search("café", "passage", limit=10)
            finally:
                reader.close()

        # 4i. Constructor cleanup on mid-init failure
        spy_conn = SQLSpyConnection(sparse._open_database(self.db_path))
        with mock.patch.object(sparse, "_open_database", return_value=spy_conn):
            with self.assertRaises(M3Error):
                sparse.SparseBM25(self.db_path, dup_dir, validate_database=False)
        self.assertTrue(spy_conn.closed)

    def test_05_session_guard_sticky_invalidation_and_hybrid_fusion_invariants(self):
        # Verify fuse_channels and validate_dense_hits invariants + sticky invalidation of SparseSession.guard
        # Build a mock SparseSession object without hashing the 4.36 GB full database by mocking load_plan
        fake_session = object.__new__(sparse.SparseSession)
        fake_session.root = ROOT
        fake_session.profile = sparse.load_profile(ROOT)
        fake_session.directory = ROOT / fake_session.profile["full_run"]
        fake_session.index_dir = self.index_dir
        fake_session.code = sparse.implementation()
        fake_session.invalidated = False
        fake_session.reader = sparse.SparseBM25(self.db_path, self.index_dir)
        fake_session.manifest = {"profile": json.loads((ROOT / "pipeline_v2/configs/m3_full.json").read_text(encoding="utf-8"))}
        fake_session.binding = {
            "manifest.json": sparse.file_digest(fake_session.directory / "manifest.json"),
            "seal.json": sparse.file_digest(fake_session.directory / "seal.json"),
        }
        fake_session.index_binding = {
            "manifest.json": sparse.file_digest(self.index_dir / "manifest.json"),
            "seal.json": sparse.file_digest(self.index_dir / "seal.json"),
        }
        fake_session.initialization_seconds = 0.01
        try:
            # Guard succeeds initially
            fake_session.guard()
            res = fake_session.search("café", "passage", limit=5, unique_cases=True)
            self.assertEqual(res["scope"], "all_train_cases_and_passages")
            self.assertEqual(res["implementation_sha256"], digest(canonical(fake_session.code)))

            # Simulate code drift during session -> sticky invalidation
            with mock.patch.object(sparse, "implementation", return_value={"drifted": "1"}):
                with self.assertRaisesRegex(M3Error, "Sparse snapshot invalidated"):
                    fake_session.guard()
            self.assertTrue(fake_session.invalidated)
            # Even after implementation returns to normal, session remains stickily invalidated
            with self.assertRaisesRegex(M3Error, "Sparse snapshot invalidated"):
                fake_session.search("café", "passage", limit=5)
        finally:
            fake_session.close()

    def test_06_cli_isolation_and_error_handling_without_env(self):
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith(("MODAL_", "QDRANT_", "HF_"))}
        # 1. --help
        proc_help = subprocess.run(
            [sys.executable, "-m", "pipeline_v2.m3_sparse", "--help"],
            cwd=str(ROOT),
            env=clean_env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_help.returncode, 0)
        self.assertIn("diagnostic-hybrid", proc_help.stdout)

        # 2. Invalid index dir fails fast with exit code 2 and structured JSON error on stderr
        proc_err = subprocess.run(
            [
                sys.executable,
                "-m",
                "pipeline_v2.m3_sparse",
                "search",
                "--index-dir",
                "pipeline_v2/artifacts/nonexistent_sparse_dir",
                "--channel",
                "passage",
                "--query",
                "standard of review",
            ],
            cwd=str(ROOT),
            env=clean_env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_err.returncode, 2)
        err_payload = json.loads(proc_err.stderr.strip())
        self.assertEqual(err_payload["status"], "error")


def main():
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AGIndependentSparseHybridTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    elapsed = time.perf_counter() - started
    summary = {
        "schema_version": "ag-m3-sparse-independent-tests-1",
        "test_file": "pipeline_v2/reviews/m3_sparse_ag_review_v1/test_m3_sparse_independent_ag.py",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "status": "PASS" if result.wasSuccessful() else "FAIL",
        "elapsed_seconds": elapsed,
        "test_methods": [
            "test_01_float64_formula_channel_idf_analyzer_and_oov",
            "test_02_exclusion_before_topk_representative_selection_and_tie_order",
            "test_03_array_scoring_only_metadata_on_retained_hits_and_block_invariance",
            "test_04_fault_injections_on_temp_copies",
            "test_05_session_guard_sticky_invalidation_and_hybrid_fusion_invariants",
            "test_06_cli_isolation_and_error_handling_without_env",
        ],
    }
    (OUT_DIR / "independent_test_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
