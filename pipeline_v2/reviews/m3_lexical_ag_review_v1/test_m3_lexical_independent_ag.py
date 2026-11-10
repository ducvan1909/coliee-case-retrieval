"""Independent AG verification suite for M3 optimized lexical reader (FastBM25 & LexicalSession).

All tests run on temporary SQLite databases and mocked/temporary snapshots in
temporary directories. No production code, config, sealed run, gold labels,
credentials, Qdrant service, or Modal service is accessed or mutated.
"""
from collections import Counter
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

from pipeline_v2.full_search import lexical
from pipeline_v2.optimization_v2.common import M3Error
from pipeline_v2.optimization_v2.index import PersistentBM25


def independent_analyze(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def independent_bm25_oracle(
    documents: list[dict],
    query: str,
    *,
    k1: float = 1.5,
    b: float = 0.75,
    limit: int = 100,
    exclude_case: str | None = None,
    unique_cases: bool = False,
    dtype: type = float,
) -> list[dict]:
    """Pure-Python reference BM25 oracle (supports float64 vs float32 comparison)."""
    rows = [(doc, Counter(independent_analyze(doc["text"]))) for doc in documents]
    lengths = [sum(tf.values()) for _, tf in rows]
    n = len(rows)
    avg = (sum(lengths) / n) if n else 1.0
    df = Counter(term for _, tf in rows for term in tf)
    qterms = sorted(set(independent_analyze(query)))

    scored = []
    for (doc, tf), length in zip(rows, lengths):
        if doc["case_id"] == exclude_case:
            continue
        if dtype is np.float32:
            score = np.float32(0.0)
            k1_t = np.float32(k1)
            b_t = np.float32(b)
            avg_t = np.float32(avg or 1.0)
            len_t = np.float32(length)
            norm_t = k1_t * (np.float32(1.0) - b_t + b_t * len_t / avg_t)
            for term in qterms:
                freq = tf[term]
                if freq:
                    idf_t = np.float32(math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5)))
                    tf_t = np.float32(freq)
                    score = np.float32(score + idf_t * tf_t * (k1_t + np.float32(1.0)) / (tf_t + norm_t))
            score_val = float(score)
        else:
            score_val = 0.0
            norm = k1 * (1.0 - b + b * length / (avg or 1.0))
            for term in qterms:
                freq = tf[term]
                if freq:
                    idf = math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5))
                    score_val += idf * freq * (k1 + 1.0) / (freq + norm)
        if score_val > 0.0:
            ident = doc.get("passage_id", doc["case_id"])
            scored.append((score_val, ident, doc))

    scored.sort(key=lambda r: (-r[0], r[1]))
    if unique_cases:
        selected, seen = [], set()
        for row in scored:
            cid = row[2]["case_id"]
            if cid not in seen:
                seen.add(cid)
                selected.append(row)
                if len(selected) == limit:
                    break
        scored = selected
    else:
        scored = scored[:limit]

    return [
        {**{k: v for k, v in doc.items() if k != "text"}, "score": score_val}
        for score_val, _, doc in scored
    ]


class SQLSpyConnection:
    """Spy wrapper around sqlite3.Connection to inspect SQL statements and cursor calls."""
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.sql_log: list[tuple[str, tuple]] = []
        self.postings_fetchmany_calls: list[tuple[int | None, int]] = []
        self.postings_fetchall_calls: int = 0
        self.metadata_batch_sizes: list[int] = []

    def execute(self, sql: str, parameters=()):
        params_tuple = tuple(parameters)
        self.sql_log.append((sql, params_tuple))
        cursor = self._conn.execute(sql, parameters)
        if "FROM postings" in sql:
            return SQLSpyCursor(cursor, self)
        if "SELECT id,metadata FROM documents" in sql:
            # First parameter is kind, remaining parameters are IDs in the batch
            self.metadata_batch_sizes.append(len(params_tuple) - 1)
        return cursor

    def __getattr__(self, name):
        return getattr(self._conn, name)


class SQLSpyCursor:
    def __init__(self, cursor: sqlite3.Cursor, spy: SQLSpyConnection):
        self._cursor = cursor
        self._spy = spy

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size)
        self._spy.postings_fetchmany_calls.append((size, len(rows)))
        return rows

    def fetchall(self):
        self._spy.postings_fetchall_calls += 1
        return self._cursor.fetchall()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class AGIndependentLexicalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

    def _build_fixture_db(self, name: str, cases: list[dict], passages: list[dict], k1=1.5, b=0.75) -> Path:
        db_path = self.tmp_path / name
        idx = PersistentBM25.create(db_path, {"case": cases, "passage": passages}, k1=k1, b=b)
        idx.close()
        return db_path

    def test_01_formula_float64_precision_stopwords_unicode_negation_oov(self):
        """Verify float64 precision (distinguishable from float32), stopword retention, Unicode, negation, OOV."""
        # Construct documents with lengths and TFs where float64 vs float32 diverges > 1e-7
        cases = [
            {"case_id": f"{i:06d}.txt", "text": "the of in to a not café 5(1)(c) " + ("word " * (i * 37 + 3))}
            for i in range(1, 25)
        ]
        passages = []
        for i in range(1, 25):
            passages.append({
                "passage_id": f"{i:06d}:p01",
                "case_id": f"{i:06d}.txt",
                "text": ("the " * (i % 7 + 1)) + ("of " * (i % 5 + 1)) + ("not " * (i % 3 + 1))
                        + "CAFÉ 5(1)(c) Décision raisonnable " + ("filler " * (i * 19)),
            })
            passages.append({
                "passage_id": f"{i:06d}:p02",
                "case_id": f"{i:06d}.txt",
                "text": "the of not unreasonable 131(1) " + ("other " * (i * 11 + 2)),
            })

        db_path = self._build_fixture_db("t01.sqlite3", cases, passages)
        reader = lexical.FastBM25(db_path, cache_mib=16, mmap_mib=0, fetch_size=64)
        old_reader = PersistentBM25(db_path)
        self.addCleanup(reader.close)
        self.addCleanup(old_reader.close)

        queries = [
            "the of in to a not",  # Pure stopwords + negation
            "CAFÉ café Café 5(1)(c) décision",  # Duplicate terms + Unicode + statutory citation
            "not unreasonable 131(1) the",
        ]
        for q in queries:
            for kind, docs in (("case", cases), ("passage", passages)):
                fast_hits = reader.search(q, kind, limit=100)
                old_hits = old_reader.search(q, kind, limit=100)
                oracle_f64 = independent_bm25_oracle(docs, q, limit=100, dtype=float)
                oracle_f32 = independent_bm25_oracle(docs, q, limit=100, dtype=np.float32)

                id_key = "passage_id" if kind == "passage" else "case_id"
                self.assertEqual([h[id_key] for h in fast_hits], [h[id_key] for h in oracle_f64])
                self.assertEqual([h[id_key] for h in fast_hits], [h[id_key] for h in old_hits])

                max_diff_f64 = max(abs(a["score"] - b["score"]) for a, b in zip(fast_hits, oracle_f64))
                max_diff_old = max(abs(a["score"] - b["score"]) for a, b in zip(fast_hits, old_hits))
                max_diff_f32 = max(abs(a["score"] - b["score"]) for a, b in zip(fast_hits, oracle_f32))

                self.assertLessEqual(max_diff_f64, 1e-15, f"Expected exact float64 match, got {max_diff_f64}")
                self.assertLessEqual(max_diff_old, 1e-15, f"Expected exact match with PersistentBM25, got {max_diff_old}")
                # Float32 oracle diverges by ~6e-9 to 1e-6 (millions of times larger than float64 1e-15 tolerance)
                self.assertGreater(max_diff_f32, 1e-9, "Float32 oracle must measurably diverge from float64")

        # Verify stopwords alone produce matches and positive scores
        stop_detail = reader.search_detailed("the of not", "passage", limit=10)
        self.assertEqual(stop_detail["terms_matched"], 3)
        self.assertGreater(len(stop_detail["hits"]), 0)
        stop_case_detail = reader.search_detailed("the of a", "case", limit=10)
        self.assertEqual(stop_case_detail["terms_matched"], 3)
        self.assertGreater(len(stop_case_detail["hits"]), 0)

        # Verify empty, punctuation-only, and OOV queries
        for empty_q in ("", "   \t\r\n  ", "--- ... () [] !@#", "nonexistent_token_xyz_999"):
            det = reader.search_detailed(empty_q, "passage", limit=10)
            self.assertEqual(det["hits"], [])
            self.assertEqual(det["terms_matched"], 0)
            self.assertEqual(det["postings_rows"], 0)
            self.assertEqual(det["matched_documents"], 0)

    def test_02_no_sql_join_and_bounded_fetchmany_across_multi_chunk_terms(self):
        """Verify SQL never JOINs documents during term scan and uses bounded fetchmany without fetchall."""
        cases = [{"case_id": f"{i:06d}.txt", "text": "common rare"} for i in range(1, 11)]
        # 150 passages with 'common', 128 passages with 'medium', 5 with 'rare'
        passages = []
        for i in range(150):
            cid = f"{(i % 10) + 1:06d}.txt"
            terms = ["common"] * ((i % 4) + 1)
            if i < 128:
                terms.extend(["medium"] * ((i % 3) + 1))
            if i in (3, 17, 64, 127, 149):
                terms.append("rare")
            passages.append({
                "passage_id": f"{cid[:6]}:p{i:04d}",
                "case_id": cid,
                "text": " ".join(terms) + " " + ("pad " * (i % 13)),
            })

        db_path = self._build_fixture_db("t02.sqlite3", cases, passages)
        reader = lexical.FastBM25(db_path, fetch_size=64)
        self.addCleanup(reader.close)

        spy = SQLSpyConnection(reader.db)
        reader.db = spy
        try:
            detail = reader.search_detailed("common medium rare", "passage", limit=50, exclude_case="000001.txt")
        finally:
            reader.db = spy._conn

        # 1. Verify no SQL statement contains JOIN
        for sql, _ in spy.sql_log:
            self.assertNotIn("JOIN", sql.upper(), f"Forbidden JOIN found in SQL: {sql}")

        # 2. Verify fetchall was never called on postings
        self.assertEqual(spy.postings_fetchall_calls, 0)

        # 3. Verify exact fetchmany(64) sequence:
        # Sorted terms: 'common' (df=150 -> 64, 64, 22, 0), 'medium' (df=128 -> 64, 64, 0), 'rare' (df=5 -> 5, 0)
        expected_fetchmany = [
            (64, 64), (64, 64), (64, 22), (64, 0),
            (64, 64), (64, 64), (64, 0),
            (64, 5), (64, 0),
        ]
        self.assertEqual(spy.postings_fetchmany_calls, expected_fetchmany)
        self.assertEqual(detail["postings_rows"], 150 + 128 + 5)
        self.assertEqual(detail["terms_matched"], 3)

        # 4. Verify scores and IDs match oracle 100%
        expected_hits = independent_bm25_oracle(passages, "common medium rare", limit=50, exclude_case="000001.txt")
        self.assertEqual([h["passage_id"] for h in detail["hits"]], [h["passage_id"] for h in expected_hits])
        for got, want in zip(detail["hits"], expected_hits):
            self.assertAlmostEqual(got["score"], want["score"], delta=1e-15)

    def test_03_top_k_partition_boundary_ties_and_ordinal_tie_breaking(self):
        """Verify _top retains all boundary ties before slicing in ascending lexical ID order."""
        cases = [{"case_id": f"{i:06d}.txt", "text": "alpha beta"} for i in range(1, 5)]
        # Create 20 passages in scrambled insertion order:
        # - 3 high-scoring passages (tf=3,2,1 on 'high' + 'tie')
        # - 9 identically scoring boundary-tie passages (tf=1 on 'tie', identical length=2)
        # - 8 lower-scoring passages (tf=1 on 'tie', longer length=10)
        passages = [
            {"passage_id": "000002:tie_z", "case_id": "000002.txt", "text": "tie pad"},
            {"passage_id": "000001:tie_b", "case_id": "000001.txt", "text": "tie pad"},
            {"passage_id": "000003:high_1", "case_id": "000003.txt", "text": "tie high high high"},
            {"passage_id": "000004:low_3", "case_id": "000004.txt", "text": "tie " + "pad " * 9},
            {"passage_id": "000001:tie_a", "case_id": "000001.txt", "text": "tie pad"},
            {"passage_id": "000003:tie_m", "case_id": "000003.txt", "text": "tie pad"},
            {"passage_id": "000002:high_2", "case_id": "000002.txt", "text": "tie high high"},
            {"passage_id": "000004:tie_d", "case_id": "000004.txt", "text": "tie pad"},
            {"passage_id": "000001:low_1", "case_id": "000001.txt", "text": "tie " + "pad " * 9},
            {"passage_id": "000002:tie_c", "case_id": "000002.txt", "text": "tie pad"},
            {"passage_id": "000001:high_3", "case_id": "000001.txt", "text": "tie high"},
            {"passage_id": "000003:tie_k", "case_id": "000003.txt", "text": "tie pad"},
            {"passage_id": "000004:tie_f", "case_id": "000004.txt", "text": "tie pad"},
            {"passage_id": "000002:tie_e", "case_id": "000002.txt", "text": "tie pad"},
            {"passage_id": "000002:low_2", "case_id": "000002.txt", "text": "tie " + "pad " * 9},
            {"passage_id": "000003:low_4", "case_id": "000003.txt", "text": "tie " + "pad " * 9},
        ]
        db_path = self._build_fixture_db("t03.sqlite3", cases, passages)
        reader = lexical.FastBM25(db_path)
        self.addCleanup(reader.close)

        for lim in range(1, len(passages) + 3):
            with self.subTest(limit=lim):
                got = reader.search("tie high", "passage", limit=lim)
                want = independent_bm25_oracle(passages, "tie high", limit=lim)
                self.assertEqual([h["passage_id"] for h in got], [h["passage_id"] for h in want])
                for a, b in zip(got, want):
                    self.assertAlmostEqual(a["score"], b["score"], delta=1e-15)

    def test_04_unique_cases_mode_selects_best_hit_channel_wide_without_vote_summing(self):
        """Verify unique_cases=True scans past raw limit, picks best single passage per case, no sibling summing."""
        cases = [{"case_id": f"{i:06d}.txt", "text": "target token"} for i in range(1, 6)]
        passages = []
        # Case 1 has 40 passages all with high TF on 'target' (ranks 1..40 in raw passage ranking)
        for j in range(40):
            passages.append({
                "passage_id": f"000001:p{j:03d}",
                "case_id": "000001.txt",
                "text": ("target " * 5) + ("other " * (j + 1)),
            })
        # Case 2 has 30 passages with medium TF on 'target' (ranks 41..70 in raw passage ranking)
        for j in range(30):
            passages.append({
                "passage_id": f"000002:p{j:03d}",
                "case_id": "000002.txt",
                "text": ("target " * 3) + ("other " * (j + 5)),
            })
        # Case 3 has only 1 passage with low TF=1 on 'target', but very short length=1 (high single-passage BM25!)
        passages.append({
            "passage_id": "000003:p000",
            "case_id": "000003.txt",
            "text": "target",
        })
        # Case 4 has 1 passage with TF=1 and long length (rank 72 in raw passage ranking!)
        passages.append({
            "passage_id": "000004:p000",
            "case_id": "000004.txt",
            "text": "target " + ("other " * 100),
        })
        # Case 5 has no match
        passages.append({
            "passage_id": "000005:p000",
            "case_id": "000005.txt",
            "text": "unrelated",
        })

        db_path = self._build_fixture_db("t04.sqlite3", cases, passages)
        reader = lexical.FastBM25(db_path)
        self.addCleanup(reader.close)

        # Raw search with limit=4 returns 4 passages (mostly from 000001.txt and 000003.txt)
        raw_top4 = reader.search("target", "passage", limit=4, unique_cases=False)
        self.assertEqual(len(raw_top4), 4)
        self.assertLess(len({h["case_id"] for h in raw_top4}), 4)

        # Unique-cases search with limit=4 must find all 4 matching cases (even though Case 4 is at raw rank 72!)
        uniq_top4 = reader.search("target", "passage", limit=4, unique_cases=True)
        want_uniq4 = independent_bm25_oracle(passages, "target", limit=4, unique_cases=True)
        self.assertEqual(len(uniq_top4), 4)
        self.assertEqual([h["passage_id"] for h in uniq_top4], [h["passage_id"] for h in want_uniq4])
        self.assertEqual([h["case_id"] for h in uniq_top4], [h["case_id"] for h in want_uniq4])
        for got, want in zip(uniq_top4, want_uniq4):
            self.assertAlmostEqual(got["score"], want["score"], delta=1e-15)

        # Verify well-formed external exclude_case is a safe no-op
        uniq_ext = reader.search("target", "passage", limit=4, exclude_case="999999.txt", unique_cases=True)
        self.assertEqual(uniq_ext, uniq_top4)

    def test_05_metadata_batching_256_and_immutable_column_crosschecks(self):
        """Verify get_many batches by 256 for selected IDs only and rejects metadata vs column tampering."""
        cases = [{"case_id": f"{i:06d}.txt", "text": "marker"} for i in range(1, 11)]
        passages = [
            {"passage_id": f"{(i % 10) + 1:06d}:p{i:04d}", "case_id": f"{(i % 10) + 1:06d}.txt", "text": "marker"}
            for i in range(600)
        ]
        db_path = self._build_fixture_db("t05.sqlite3", cases, passages)
        reader = lexical.FastBM25(db_path)
        self.addCleanup(reader.close)

        spy = SQLSpyConnection(reader.db)
        reader.db = spy
        try:
            hits = reader.search("marker", "passage", limit=600)
            self.assertEqual(len(hits), 600)
            self.assertEqual(spy.metadata_batch_sizes, [256, 256, 88])

            spy.metadata_batch_sizes.clear()
            hits_u = reader.search("marker", "passage", limit=5, unique_cases=True)
            self.assertEqual(len(hits_u), 5)
            self.assertEqual(spy.metadata_batch_sizes, [5])
        finally:
            reader.db = spy._conn

        # Fault injections on temporary DB copies
        for label, mutator_sql in [
            ("text_in_metadata",
             """UPDATE documents SET metadata='{"passage_id":"000001:p0000","case_id":"000001.txt","text":"leaked"}'
                WHERE kind='passage' AND id='000001:p0000'"""),
            ("id_mismatch_in_metadata",
             """UPDATE documents SET metadata='{"passage_id":"000001:wrong","case_id":"000001.txt"}'
                WHERE kind='passage' AND id='000001:p0000'"""),
            ("case_id_mismatch_in_metadata",
             """UPDATE documents SET metadata='{"passage_id":"000001:p0000","case_id":"000002.txt"}'
                WHERE kind='passage' AND id='000001:p0000'"""),
        ]:
            with self.subTest(fault=label):
                copy_path = self.tmp_path / f"t05_{label}.sqlite3"
                shutil.copyfile(db_path, copy_path)
                wdb = sqlite3.connect(copy_path)
                wdb.execute(mutator_sql)
                wdb.commit()
                wdb.close()

                fault_reader = lexical.FastBM25(copy_path)
                try:
                    with self.assertRaisesRegex(M3Error, "Lexical hit metadata differs from immutable columns"):
                        fault_reader.search("marker", "passage", limit=10)
                finally:
                    fault_reader.close()

        # Missing row in get_many direct call
        with self.assertRaisesRegex(M3Error, "Missing lexical hit metadata"):
            reader.get_many("passage", ["000001:p0000", "000001:nonexistent"])

    def test_06_preload_and_postings_fault_injection_and_constructor_cleanup(self):
        """Verify FastBM25 rejects corrupted stats/documents/terms/postings and closes DB on init failure."""
        cases = [{"case_id": "000001.txt", "text": "alpha beta"}]
        passages = [{"passage_id": "000001:p01", "case_id": "000001.txt", "text": "alpha beta"}]
        base_db = self._build_fixture_db("t06_base.sqlite3", cases, passages)

        init_faults = [
            ("missing_channel", "DELETE FROM stats WHERE kind='passage'", "Missing lexical channel: passage"),
            ("bad_stats_k1", "UPDATE stats SET k1=0 WHERE kind='case'", "Invalid BM25 statistics"),
            ("bad_stats_b", "UPDATE stats SET b=1.5 WHERE kind='case'", "Invalid BM25 statistics"),
            ("bad_stats_avg", "UPDATE stats SET avg=-1.0 WHERE kind='case'", "Invalid BM25 statistics"),
            ("bad_doc_case_id", "UPDATE documents SET case_id='bad.txt' WHERE kind='passage'", "Invalid lexical document columns"),
            ("bad_doc_length", "UPDATE documents SET length=-5 WHERE kind='passage'", "Invalid lexical document columns"),
            ("count_mismatch", "UPDATE stats SET n=99 WHERE kind='passage'", "Lexical statistics/document count mismatch"),
            ("avg_mismatch", "UPDATE stats SET avg=999.0 WHERE kind='passage'", "Lexical average length mismatch"),
        ]

        for label, sql, expected_msg in init_faults:
            with self.subTest(init_fault=label):
                copy_path = self.tmp_path / f"t06_{label}.sqlite3"
                shutil.copyfile(base_db, copy_path)
                wdb = sqlite3.connect(copy_path)
                wdb.execute(sql)
                wdb.commit()
                wdb.close()

                closed_holder = []
                real_connect = sqlite3.connect

                def tracking_connect(*args, **kwargs):
                    conn = real_connect(*args, **kwargs)
                    closed_holder.append(conn)
                    return conn

                with mock.patch("pipeline_v2.full_search.lexical.sqlite3.connect", side_effect=tracking_connect):
                    with self.assertRaisesRegex(M3Error, expected_msg):
                        lexical.FastBM25(copy_path)

                self.assertEqual(len(closed_holder), 1)
                # Verify connection was closed by attempting a query on it
                with self.assertRaises(sqlite3.ProgrammingError):
                    closed_holder[0].execute("SELECT 1")

        # Search-time postings/terms faults
        search_faults = [
            ("bad_df", "UPDATE terms SET df=999 WHERE kind='passage' AND term='alpha'", "Invalid lexical document frequency"),
            ("df_count_mismatch", "UPDATE terms SET df=1 WHERE kind='passage' AND term='alpha'; DELETE FROM postings WHERE kind='passage' AND term='alpha'", "Posting count differs from frozen document frequency"),
            ("orphan_posting", "UPDATE postings SET id='000001:orphan' WHERE kind='passage' AND term='alpha'", "Posting points outside immutable document universe"),
            ("bad_tf", "UPDATE postings SET tf=0 WHERE kind='passage' AND term='alpha'", "Invalid posting frequency"),
        ]

        for label, sql_script, expected_msg in search_faults:
            with self.subTest(search_fault=label):
                copy_path = self.tmp_path / f"t06_search_{label}.sqlite3"
                shutil.copyfile(base_db, copy_path)
                wdb = sqlite3.connect(copy_path)
                wdb.executescript(sql_script)
                wdb.commit()
                wdb.close()

                f_reader = lexical.FastBM25(copy_path)
                try:
                    with self.assertRaisesRegex(M3Error, expected_msg):
                        f_reader.search("alpha", "passage")
                finally:
                    f_reader.close()

    def test_07_session_lifecycle_cleanup_sticky_guard_revalidate_and_live_mutation_contract(self):
        """Verify LexicalSession init cleanup, sticky guard on binding drift, revalidate, and live SQLite contract."""
        cases = [{"case_id": "000001.txt", "text": "alpha beta"}]
        passages = [{"passage_id": "000001:p01", "case_id": "000001.txt", "text": "alpha beta"}]
        run_dir = self.tmp_path / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
        run_dir.mkdir(parents=True, exist_ok=True)
        db_path = run_dir / "lexical.sqlite3"
        idx = PersistentBM25.create(db_path, {"case": cases, "passage": passages})
        idx.close()

        manifest_data = {"implementation": {"full": "ok"}, "profile": {"schema": "ok"}}
        (run_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
        seal_data = {
            "manifest.json": {"sha256": lexical.file_digest(run_dir / "manifest.json"), "bytes": (run_dir / "manifest.json").stat().st_size},
            "lexical.sqlite3": {"sha256": lexical.file_digest(db_path), "bytes": db_path.stat().st_size},
        }
        (run_dir / "seal.json").write_text(json.dumps(seal_data), encoding="utf-8")

        fake_profile = {
            "schema_version": "pipeline-v2-m3-lexical-1",
            "full_run": "pipeline_v2/artifacts/m3_full_train_20261108_v1",
            "analyzer": "unicode_word_casefold_no_stopwords_v1",
            "cache_mib": 16,
            "mmap_mib": 0,
            "fetch_size": 64,
            "max_limit": 100,
        }

        def fake_load_plan(root, rdir):
            # Validate seal like real load_plan does
            s = json.loads((run_dir / "seal.json").read_text(encoding="utf-8"))
            for fname, entry in s.items():
                p = run_dir / fname
                if {"sha256": lexical.file_digest(p), "bytes": p.stat().st_size} != entry:
                    raise M3Error("Full plan file drift: " + fname)
            m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            return root, run_dir, m, PersistentBM25(db_path)

        with mock.patch.object(lexical, "load_profile", return_value=fake_profile), \
             mock.patch.object(lexical, "implementation", return_value={"lex": "v1"}), \
             mock.patch("pipeline_v2.full_corpus.runner.load_plan", side_effect=fake_load_plan), \
             mock.patch("pipeline_v2.full_corpus.common.implementation", return_value={"full": "ok"}), \
             mock.patch("pipeline_v2.full_corpus.common.load_profile", return_value={"schema": "ok"}):

            session = lexical.LexicalSession(self.tmp_path)
            try:
                res = session.search("alpha", "passage", limit=10)
                self.assertEqual(len(res["hits"]), 1)
                self.assertEqual(res["model_requests"], 0)
                self.assertEqual(res["sqlite_pragmas"]["query_only"], 1)

                # Limit exceeding profile['max_limit'] (100) raises M3Error without invalidating session
                with self.assertRaisesRegex(M3Error, "Limit exceeds lexical profile"):
                    session.search("alpha", "passage", limit=101)
                self.assertFalse(session.invalidated)

                # Revalidate succeeds when snapshot is intact
                rev = session.revalidate()
                self.assertEqual(rev, {"status": "immutable_snapshot_revalidated", "model_requests": 0})

                # Live SQLite mutation contract:
                # If SQLite file is mutated in-place without changing manifest.json/seal.json,
                # hot guard() does NOT re-hash the multi-GB SQLite file, whereas revalidate() DOES!
                wdb = sqlite3.connect(db_path)
                wdb.execute("PRAGMA user_version = 999")
                wdb.commit()
                wdb.close()

                # Hot guard() only checks config/code/manifest/seal bindings
                session.guard()
                self.assertFalse(session.invalidated)

                # Explicit revalidate() runs load_plan -> validate_seal -> catches lexical.sqlite3 SHA-256 drift and stickily invalidates!
                with self.assertRaisesRegex(M3Error, "Full plan file drift: lexical.sqlite3"):
                    session.revalidate()
                self.assertTrue(session.invalidated)

                # Subsequent search() is blocked by sticky invalidation
                with self.assertRaisesRegex(M3Error, "invalidated"):
                    session.search("alpha", "passage", limit=10)
            finally:
                session.close()

        # Verify constructor cleanup if guard() fails during LexicalSession.__init__
        closed_readers = []
        orig_fast_close = lexical.FastBM25.close

        def spy_close(self_reader):
            closed_readers.append(self_reader)
            return orig_fast_close(self_reader)

        # Restore seal so load_plan succeeds, then fail inside guard()
        seal_data["lexical.sqlite3"] = {"sha256": lexical.file_digest(db_path), "bytes": db_path.stat().st_size}
        (run_dir / "seal.json").write_text(json.dumps(seal_data), encoding="utf-8")

        with mock.patch.object(lexical, "load_profile", return_value=fake_profile), \
             mock.patch.object(lexical, "implementation", return_value={"lex": "v1"}), \
             mock.patch("pipeline_v2.full_corpus.runner.load_plan", side_effect=fake_load_plan), \
             mock.patch("pipeline_v2.full_corpus.common.implementation", return_value={"full": "DRIFTED"}), \
             mock.patch("pipeline_v2.full_corpus.common.load_profile", return_value={"schema": "ok"}), \
             mock.patch.object(lexical.FastBM25, "close", spy_close):
            with self.assertRaisesRegex(M3Error, "invalidated"):
                lexical.LexicalSession(self.tmp_path)
            self.assertEqual(len(closed_readers), 1, "FastBM25.close() must be called when LexicalSession.__init__ fails")

    def test_08_cli_error_handling_and_env_isolation(self):
        """Verify CLI returns exit code 2 with JSON error on invalid --run-dir without importing Modal."""
        env = os.environ.copy()
        for k in list(env):
            if k.upper().startswith("MODAL_") or k.upper().startswith("QDRANT_"):
                env.pop(k)
        repo_root = str(Path(__file__).resolve().parents[3])
        proc = subprocess.run(
            [sys.executable, "-m", "pipeline_v2.m3_lexical", "revalidate", "--run-dir", "pipeline_v2/artifacts/wrong_run"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 2)
        err_payload = json.loads(proc.stderr.strip())
        self.assertEqual(err_payload["status"], "error")
        self.assertIn("Lexical session requires the frozen full run", err_payload["error"])
        self.assertGreater(err_payload["internal_cli_seconds"], 0.0)


if __name__ == "__main__":
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AGIndependentLexicalTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    elapsed = time.perf_counter() - started
    out_path = Path(__file__).resolve().parent / "independent_test_results.json"
    summary = {
        "schema_version": "ag-m3-lexical-independent-tests-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "successful": result.wasSuccessful(),
        "elapsed_seconds": elapsed,
        "test_methods": sorted(
            name for name in dir(AGIndependentLexicalTests) if name.startswith("test_")
        ),
    }
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)

