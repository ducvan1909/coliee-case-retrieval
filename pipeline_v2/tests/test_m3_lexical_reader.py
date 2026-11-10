"""Independent behavioral tests for the new full-corpus lexical reader.

The fixture database is created in a temporary directory. No sealed run, labels,
network service, or production database is opened or modified by these tests.
"""
from collections import Counter
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import os

import numpy as np

from pipeline_v2.full_search import lexical
from pipeline_v2.optimization_v2.common import M3Error


def oracle_tokens(text):
    # Independent restatement of the frozen analyzer contract.
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def oracle(documents, query, *, k1=1.5, b=.75, limit=100, exclude_case=None,
           unique_cases=False):
    rows = [(doc, Counter(oracle_tokens(doc["text"]))) for doc in documents]
    lengths = [sum(tf.values()) for _, tf in rows]
    n = len(rows)
    avg = sum(lengths) / n if n else 1
    df = Counter(term for _, tf in rows for term in tf)
    qterms = set(oracle_tokens(query))
    scored = []
    for (doc, tf), length in zip(rows, lengths):
        case_id = doc["case_id"]
        if case_id == exclude_case:
            continue
        score = 0.0
        for term in sorted(qterms):
            freq = tf[term]
            if freq:
                idf = math.log(1 + (n - df[term] + .5) / (df[term] + .5))
                score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * length / (avg or 1)))
        if score > 0:
            ident = doc.get("passage_id", doc["case_id"])
            scored.append((score, ident, doc))
    scored.sort(key=lambda row: (-row[0], row[1]))
    if unique_cases:
        selected, seen = [], set()
        for row in scored:
            if row[2]["case_id"] not in seen:
                seen.add(row[2]["case_id"])
                selected.append(row)
                if len(selected) == limit:
                    break
        scored = selected
    else:
        scored = scored[:limit]
    return [{**{k: v for k, v in doc.items() if k != "text"}, "score": score}
            for score, _, doc in scored]


def create_db(path, channels, k1=1.5, b=.75):
    """Create the existing immutable lexical schema from text-bearing fixtures."""
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE documents(kind TEXT,id TEXT,case_id TEXT,length INTEGER,metadata TEXT,PRIMARY KEY(kind,id));"
        "CREATE TABLE postings(kind TEXT,term TEXT,id TEXT,tf INTEGER,PRIMARY KEY(kind,term,id));"
        "CREATE TABLE stats(kind TEXT PRIMARY KEY,n INTEGER,avg REAL,k1 REAL,b REAL);"
        "CREATE TABLE terms(kind TEXT,term TEXT,df INTEGER,PRIMARY KEY(kind,term));")
    for kind, docs in channels.items():
        token_rows = [(doc, Counter(oracle_tokens(doc["text"]))) for doc in docs]
        lengths = [sum(counts.values()) for _, counts in token_rows]
        n = len(docs)
        avg = sum(lengths) / n if n else 1
        for (doc, counts), length in zip(token_rows, lengths):
            ident = doc.get("passage_id", doc["case_id"])
            metadata = {key: value for key, value in doc.items() if key != "text"}
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?)",
                       (kind, ident, doc["case_id"], length,
                        json.dumps(metadata, ensure_ascii=False)))
            db.executemany("INSERT INTO postings VALUES(?,?,?,?)",
                           [(kind, term, ident, freq) for term, freq in counts.items()])
        db.execute("INSERT INTO stats VALUES(?,?,?,?,?)", (kind, n, avg, k1, b))
        db.execute("INSERT INTO terms SELECT kind,term,COUNT(*) FROM postings WHERE kind=? GROUP BY kind,term", (kind,))
    db.commit()
    db.close()


class RecordingConnection:
    """Observe fetchmany request and block sizes without changing SQLite results."""
    def __init__(self, connection):
        self.connection = connection
        self.fetchmany_sizes = []

    def execute(self, sql, parameters=()):
        cursor = self.connection.execute(sql, parameters)
        if "FROM postings" in sql:
            return RecordingCursor(cursor, self.fetchmany_sizes)
        return cursor

    def __getattr__(self, name):
        return getattr(self.connection, name)


class RecordingCursor:
    def __init__(self, cursor, sizes):
        self.cursor, self.sizes = cursor, sizes

    def fetchmany(self, size=None):
        rows = self.cursor.fetchmany(size)
        self.sizes.append((size, len(rows)))
        return rows


class FastBM25Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "lexical.sqlite3"
        self.passages = [
            {"passage_id": "p-04", "case_id": "000004.txt", "text": "Café under s. 5(1)(c), not reasonable."},
            {"passage_id": "p-01", "case_id": "000001.txt", "text": "The CAFÉ rule is not unreasonable; 5 1 c."},
            {"passage_id": "p-02", "case_id": "000001.txt", "text": "café café, reasonable, and NOT waived."},
            {"passage_id": "p-03", "case_id": "000002.txt", "text": "5(1)(c) plus a distinct procedural test."},
            {"passage_id": "p-05", "case_id": "000005.txt", "text": "A separate claim about damages."},
            {"passage_id": "p-06", "case_id": "000006.txt", "text": "CAFÉ and not reasonable."},
        ]
        self.cases = [
            {"case_id": "000001.txt", "text": "Café not reasonable 5(1)(c)."},
            {"case_id": "000002.txt", "text": "Café reasonable; 5(1)(c)."},
            {"case_id": "000003.txt", "text": "A damages-only decision."},
            {"case_id": "000004.txt", "text": "Not procedural, café."},
        ]
        create_db(self.path, {"case": self.cases, "passage": self.passages})
        self.reader = lexical.FastBM25(self.path, fetch_size=4096)
        self.addCleanup(self.reader.close)

    def assert_hits_match_oracle(self, kind, docs, query, **kwargs):
        result = self.reader.search(query, kind, **kwargs)
        expected = oracle(docs, query, **kwargs)
        self.assertEqual([h.get("passage_id", h["case_id"]) for h in result],
                         [h.get("passage_id", h["case_id"]) for h in expected])
        self.assertEqual([h["case_id"] for h in result], [h["case_id"] for h in expected])
        for actual, wanted in zip(result, expected):
            self.assertAlmostEqual(actual["score"], wanted["score"], delta=1e-12)

    def test_unicode_digits_negation_duplicates_and_exact_scores(self):
        for query in ("CAFÉ 5(1)(c) not NOT reasonable", "café café café", "not reasonable"):
            with self.subTest(query=query):
                self.assert_hits_match_oracle("passage", self.passages, query, limit=20)
                self.assert_hits_match_oracle("case", self.cases, query, limit=20)

    def test_empty_oov_and_zero_match_return_no_hits(self):
        for query in ("", "   ", "qzxv_nonexistent_999"):
            with self.subTest(query=query):
                self.assertEqual(self.reader.search(query, "passage"), [])
                self.assertEqual(self.reader.search(query, "case"), [])
        self.assertEqual(self.reader.search_detailed("qzxv", "passage")["terms_matched"], 0)

    def test_exclusion_happens_before_limit_and_matches_oracle(self):
        self.assert_hits_match_oracle("passage", self.passages, "café", limit=1,
                                      exclude_case="000001.txt")
        hits = self.reader.search("café", "passage", limit=1, exclude_case="000001.txt")
        self.assertTrue(hits)
        self.assertNotEqual(hits[0]["case_id"], "000001.txt")

    def test_ties_are_deterministic_and_large_limit_returns_all_matches(self):
        # Equal-length/equal-tf documents tie on score; lexical ID resolves the tie.
        docs = [
            {"passage_id": "z", "case_id": "000001.txt", "text": "alpha beta"},
            {"passage_id": "a", "case_id": "000002.txt", "text": "alpha beta"},
            {"passage_id": "m", "case_id": "000003.txt", "text": "alpha beta"},
        ]
        path = Path(self.tmp.name) / "ties.sqlite3"
        create_db(path, {"case": self.cases, "passage": docs})
        reader = lexical.FastBM25(path)
        try:
            for _ in range(3):
                self.assertEqual([h["passage_id"] for h in reader.search("alpha", "passage", limit=999)],
                                 ["a", "m", "z"])
        finally:
            reader.close()

    def test_unique_case_mode_deduplicates_before_result_cap(self):
        expected = oracle(self.passages, "café", limit=2, unique_cases=True)
        actual = self.reader.search("café", "passage", limit=2, unique_cases=True)
        self.assertEqual([x["case_id"] for x in actual], [x["case_id"] for x in expected])
        self.assertEqual(len({x["case_id"] for x in actual}), len(actual))
        for got, want in zip(actual, expected):
            self.assertAlmostEqual(got["score"], want["score"], delta=1e-12)

    def test_each_request_starts_with_fresh_score_accumulator(self):
        first = self.reader.search("café", "passage", limit=20)
        self.reader.search("reasonable reasonable", "passage", limit=20)
        again = self.reader.search("café", "passage", limit=20)
        self.assertEqual(first, again)
        self.assert_hits_match_oracle("passage", self.passages, "café", limit=20)

    def test_posting_scan_uses_bounded_4096_fetchmany_chunks(self):
        docs = [{"passage_id": f"p-{i:05d}", "case_id": f"{i % 10 + 1:06d}.txt",
                 "text": "ubiquitous marker"} for i in range(4097)]
        # Case channel must contain the same ten cases, each with its own canonical ID.
        cases = [{"case_id": f"{i:06d}.txt", "text": "ubiquitous marker"}
                 for i in range(1, 11)]
        path = Path(self.tmp.name) / "chunks.sqlite3"
        create_db(path, {"case": cases, "passage": docs})
        reader = lexical.FastBM25(path)
        recorder = RecordingConnection(reader.db)
        reader.db = recorder
        try:
            detailed = reader.search_detailed("ubiquitous", "passage", limit=2)
            self.assertEqual(detailed["postings_rows"], 4097)
            self.assertEqual([n for requested, n in recorder.fetchmany_sizes if requested == 4096], [4096, 1, 0])
        finally:
            reader.db = recorder.connection
            reader.close()

    def test_invalid_channels_limits_exclusion_and_modes_are_rejected(self):
        for query, kind, limit, excluded, unique in (
                (None, "passage", 1, None, False), ("alpha", "unknown", 1, None, False),
                ("alpha", "passage", 0, None, False), ("alpha", "passage", 16385, None, False),
                ("alpha", "passage", True, None, False), ("alpha", "passage", 1.0, None, False),
                ("alpha", "passage", 1, "not-a-case", False), ("alpha", "passage", 1, None, 1)):
            with self.subTest(args=(query, kind, limit, excluded, unique)), self.assertRaises(M3Error):
                self.reader.search(query, kind, limit, excluded, unique)

    def test_reader_opens_database_readonly_and_does_not_mutate_it(self):
        before = self.path.read_bytes()
        self.assertEqual(self.reader.db.execute("PRAGMA query_only").fetchone()[0], 1)
        with self.assertRaises(sqlite3.OperationalError):
            self.reader.db.execute("CREATE TABLE forbidden(x)")
        self.assertEqual(self.path.read_bytes(), before)


class SnapshotGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        (self.directory / "manifest.json").write_text("{}", encoding="utf-8")
        (self.directory / "seal.json").write_text("{}", encoding="utf-8")
        self.profile = {"schema_version": "test-profile"}
        self.full_profile = {"schema_version": "full-profile"}
        self.full_code = {"full-runner.py": "fingerprint"}
        self.session = object.__new__(lexical.LexicalSession)
        self.session.root = self.directory
        self.session.profile = self.profile
        self.session.code = {"lexical.py": "fingerprint"}
        self.session.invalidated = False
        self.session.manifest = {"implementation": self.full_code, "profile": self.full_profile}
        self.session.directory = self.directory
        self.session.binding = {name: lexical.file_digest(self.directory / name)
                                for name in ("manifest.json", "seal.json")}

    def guard_with_mocks(self, profile_loader=None, code_loader=None, full_profile_loader=None,
                         full_code_loader=None):
        with mock.patch.object(lexical, "load_profile", profile_loader or (lambda _root: self.profile)), \
             mock.patch.object(lexical, "implementation", code_loader or (lambda: self.session.code)), \
             mock.patch("pipeline_v2.full_corpus.common.load_profile",
                        full_profile_loader or (lambda _root: self.full_profile)), \
             mock.patch("pipeline_v2.full_corpus.common.implementation",
                        full_code_loader or (lambda: self.full_code)):
            self.session.guard()

    def test_profile_drift_invalidates_session_stickily(self):
        with self.assertRaisesRegex(M3Error, "invalidated"):
            self.guard_with_mocks(profile_loader=lambda _root: {"schema_version": "changed"})
        self.assertTrue(self.session.invalidated)
        with self.assertRaisesRegex(M3Error, "invalidated"):
            self.guard_with_mocks()

    def test_implementation_drift_invalidates_session_stickily(self):
        with self.assertRaisesRegex(M3Error, "invalidated"):
            self.guard_with_mocks(code_loader=lambda: {"lexical.py": "changed"})
        self.assertTrue(self.session.invalidated)
        with self.assertRaisesRegex(M3Error, "invalidated"):
            self.guard_with_mocks()

    def test_full_runner_profile_and_implementation_drift_invalidate(self):
        for kwargs in (
                {"full_profile_loader": lambda _root: {"schema_version": "changed"}},
                {"full_code_loader": lambda: {"runner.py": "changed"}}):
            with self.subTest(kwargs=tuple(kwargs)), self.assertRaisesRegex(M3Error, "invalidated"):
                self.guard_with_mocks(**kwargs)
            self.session.invalidated = False


class CliIsolationTests(unittest.TestCase):
    def test_help_and_import_work_without_modal_credentials_or_service(self):
        env = os.environ.copy()
        for key in list(env):
            if key.upper().startswith("MODAL_") or key.upper() in {"QDRANT_URL", "QDRANT_API_KEY"}:
                env.pop(key)
        root = str(Path(__file__).resolve().parents[2])
        help_result = subprocess.run([sys.executable, "-m", "pipeline_v2.m3_lexical", "--help"],
                                      cwd=root, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("search", help_result.stdout)
        import_result = subprocess.run(
            [sys.executable, "-c", "import sys; import pipeline_v2.m3_lexical; print('modal' in sys.modules)"],
            cwd=root, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(import_result.returncode, 0, import_result.stderr)
        self.assertEqual(import_result.stdout.strip(), "False")

    def test_reader_module_has_no_vector_or_modal_loading_path(self):
        source = Path(lexical.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import modal", source)
        self.assertNotIn("from modal", source)
        self.assertNotIn("np.load", source)
        self.assertNotIn("QdrantStore", source)


if __name__ == "__main__":
    unittest.main()
