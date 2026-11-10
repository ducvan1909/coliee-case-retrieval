"""Independent behavioral tests for the sparse eager BM25 sidecar.

All databases and indexes are built in temporary directories.  The scalar
oracle below is computed from fixture text, independently of the sparse
builder and reader.
"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

from pipeline_v2.sparse_bm25 import index as sparse
from pipeline_v2.retrieval.common import M3Error


def tokens(text):
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def scalar_oracle(documents, query, *, k1=1.5, b=.75, limit=100,
                  exclude_case=None, unique_cases=False):
    rows = [(doc, Counter(tokens(doc["text"]))) for doc in documents]
    lengths = [sum(freq.values()) for _, freq in rows]
    n = len(rows)
    avg = sum(lengths) / n if n else 1.0
    df = Counter(term for _, freq in rows for term in freq)
    query_terms = sorted(set(tokens(query)))
    ranked = []
    for (doc, freq), length in zip(rows, lengths):
        if doc["case_id"] == exclude_case:
            continue
        score = 0.0
        for term in query_terms:
            tf = freq[term]
            if tf:
                idf = math.log(1 + (n - df[term] + .5) / (df[term] + .5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (avg or 1)))
        if score > 0:
            ident = doc.get("passage_id", doc["case_id"])
            ranked.append((score, ident, doc))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    if unique_cases:
        seen, selected = set(), []
        for row in ranked:
            if row[2]["case_id"] not in seen:
                selected.append(row)
                seen.add(row[2]["case_id"])
                if len(selected) == limit:
                    break
        ranked = selected
    else:
        ranked = ranked[:limit]
    return [{**{key: value for key, value in doc.items() if key != "text"}, "score": score}
            for score, _, doc in ranked]


def make_database(path, channels, *, k1=1.5, b=.75, bad=None):
    """Materialize frozen lexical schema with intentionally shuffled postings."""
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE documents(kind TEXT,id TEXT,case_id TEXT,length INTEGER,metadata TEXT,PRIMARY KEY(kind,id));"
        "CREATE TABLE postings(kind TEXT,term TEXT,id TEXT,tf INTEGER,PRIMARY KEY(kind,term,id));"
        "CREATE TABLE stats(kind TEXT PRIMARY KEY,n INTEGER,avg REAL,k1 REAL,b REAL);"
        "CREATE TABLE terms(kind TEXT,term TEXT,df INTEGER,PRIMARY KEY(kind,term));")
    for kind, docs in channels.items():
        rows = [(doc, Counter(tokens(doc["text"]))) for doc in docs]
        lengths = [sum(freq.values()) for _, freq in rows]
        n = len(docs)
        avg = sum(lengths) / n if n else 1.0
        db.execute("INSERT INTO stats VALUES(?,?,?,?,?)", (kind, n, avg, k1, b))
        for (doc, freq), length in zip(rows, lengths):
            ident = doc.get("passage_id", doc["case_id"])
            metadata = {key: value for key, value in doc.items() if key != "text"}
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?)",
                       (kind, ident, doc["case_id"], length, json.dumps(metadata, ensure_ascii=False)))
        postings = [(kind, term, doc.get("passage_id", doc["case_id"]), count)
                    for doc, freq in rows for term, count in freq.items()]
        # Reverse order makes the builder demonstrate that it sorts by document ordinal.
        if bad == "unknown_doc" and postings:
            kind0, term, _, count = postings[-1]
            postings[-1] = (kind0, term, "missing-id", count)
        elif bad == "zero_tf" and postings:
            kind0, term, ident, _ = postings[-1]
            postings[-1] = (kind0, term, ident, 0)
        elif bad == "bad_df" and postings:
            kind0, term, ident, _ = postings[-1]
            postings[-1] = (kind0, term, ident, 1)
        db.executemany("INSERT INTO postings VALUES(?,?,?,?)", reversed(postings))
        db.execute("INSERT INTO terms SELECT kind,term,COUNT(*) FROM postings WHERE kind=? GROUP BY kind,term", (kind,))
        if bad == "bad_df" and db.execute("SELECT COUNT(*) FROM terms WHERE kind=?", (kind,)).fetchone()[0]:
            term = db.execute("SELECT term FROM terms WHERE kind=? ORDER BY term LIMIT 1", (kind,)).fetchone()[0]
            db.execute("UPDATE terms SET df=df+1 WHERE kind=? AND term=?", (kind, term))
    db.commit()
    db.close()


class PostingCursorProbe:
    def __init__(self, cursor, requested):
        self.cursor, self.requested = cursor, requested

    def fetchmany(self, size=None):
        self.requested.append(size)
        if size is None or size > 64:
            raise AssertionError(f"builder requested unbounded posting fetch: {size}")
        return self.cursor.fetchmany(size)

    def fetchall(self):
        raise AssertionError("builder attempted fetchall on the postings cursor")


class DatabaseProbe:
    def __init__(self, db, requested):
        self.db, self.requested = db, requested

    def execute(self, sql, parameters=()):
        cursor = self.db.execute(sql, parameters)
        if "FROM postings" in sql:
            return PostingCursorProbe(cursor, self.requested)
        return cursor

    def close(self):
        self.db.close()


class SparseIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "lexical.sqlite3"
        self.index_dir = self.root / "sparse"
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
        make_database(self.db_path, {"case": self.cases, "passage": self.passages})
        sparse.build_from_database(self.db_path, self.index_dir, fetch_size=64)
        self.reader = sparse.SparseBM25(self.db_path, self.index_dir, score_block_size=64)
        self.addCleanup(self.reader.close)

    def assert_matches_oracle(self, kind, documents, query, **kwargs):
        actual = self.reader.search(query, kind, **kwargs)
        expected = scalar_oracle(documents, query, **kwargs)
        ident = lambda row: row.get("passage_id", row["case_id"])
        self.assertEqual([ident(row) for row in actual], [ident(row) for row in expected])
        self.assertEqual([row["case_id"] for row in actual], [row["case_id"] for row in expected])
        for got, want in zip(actual, expected):
            self.assertAlmostEqual(got["score"], want["score"], delta=1e-12)

    def test_query_semantics_and_scores_match_independent_scalar_oracle(self):
        for query in ("CAFÉ 5(1)(c) not NOT reasonable", "café café café", "not reasonable"):
            for kind, docs in (("case", self.cases), ("passage", self.passages)):
                with self.subTest(query=query, kind=kind):
                    self.assert_matches_oracle(kind, docs, query, limit=20)

    def test_oov_empty_and_duplicate_terms(self):
        for query in ("", "   ", "qzxv_nonexistent_999"):
            with self.subTest(query=query):
                self.assertEqual(self.reader.search(query, "passage"), [])
                self.assertEqual(self.reader.search(query, "case"), [])
        once = self.reader.search("café", "passage", limit=20)
        repeated = self.reader.search("CAFÉ café café", "passage", limit=20)
        self.assertEqual(once, repeated)

    def test_exclusion_precedes_limit_and_unique_case_cap(self):
        self.assert_matches_oracle("passage", self.passages, "café", limit=1,
                                   exclude_case="000001.txt")
        raw = self.reader.search("café", "passage", limit=1, exclude_case="000001.txt")
        self.assertTrue(raw)
        self.assertNotEqual(raw[0]["case_id"], "000001.txt")
        self.assert_matches_oracle("passage", self.passages, "café", limit=2, unique_cases=True)
        unique = self.reader.search("café", "passage", limit=2, unique_cases=True)
        self.assertEqual(len({row["case_id"] for row in unique}), len(unique))

    def test_ties_are_stable_and_score_state_resets_between_queries(self):
        tied_docs = [
            {"passage_id": "z", "case_id": "000001.txt", "text": "alpha beta"},
            {"passage_id": "a", "case_id": "000002.txt", "text": "alpha beta"},
            {"passage_id": "m", "case_id": "000003.txt", "text": "alpha beta"},
        ]
        db_path, index_dir = self.root / "ties.sqlite3", self.root / "ties"
        make_database(db_path, {"case": self.cases, "passage": tied_docs})
        sparse.build_from_database(db_path, index_dir, fetch_size=64)
        reader = sparse.SparseBM25(db_path, index_dir, score_block_size=64)
        try:
            first = reader.search("alpha", "passage", limit=2)
            self.assertEqual([row["passage_id"] for row in first], ["a", "m"])
            reader.search("beta alpha alpha", "passage", limit=3)
            self.assertEqual(reader.search("alpha", "passage", limit=2), first)
        finally:
            reader.close()

    def test_layout_is_sorted_unique_typed_and_readonly_mmap(self):
        for kind in ("case", "passage"):
            channel = self.reader.channels[kind]
            self.assertIsInstance(channel["indices"], np.memmap)
            self.assertIsInstance(channel["values"], np.memmap)
            self.assertIsInstance(channel["offsets"], np.memmap)
            self.assertFalse(channel["indices"].flags.writeable)
            self.assertFalse(channel["values"].flags.writeable)
            self.assertFalse(channel["offsets"].flags.writeable)
            self.assertEqual(channel["indices"].dtype, np.dtype(np.uint32))
            self.assertEqual(channel["values"].dtype, np.dtype(np.float64))
            self.assertEqual(channel["offsets"].dtype, np.dtype(np.uint64))
            self.assertEqual(channel["ids"], sorted(set(channel["ids"])))
            self.assertEqual(channel["terms"], sorted(set(channel["terms"])))
            self.assertEqual(int(channel["offsets"][0]), 0)
            self.assertEqual(int(channel["offsets"][-1]), len(channel["indices"]))
            for start, end in zip(channel["offsets"][:-1], channel["offsets"][1:]):
                docs = channel["indices"][int(start):int(end)]
                self.assertTrue(np.all(docs[1:] > docs[:-1]))

    def test_database_and_sidecar_are_readonly_for_search(self):
        before = self.db_path.read_bytes()
        with self.assertRaises(sqlite3.OperationalError):
            self.reader.db.execute("CREATE TABLE forbidden(x)")
        with self.assertRaises(ValueError):
            self.reader.channels["passage"]["values"][0] = 0
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_builder_streams_postings_with_bounded_fetchmany(self):
        docs = [{"passage_id": f"p-{i:04d}", "case_id": f"{i + 1:06d}.txt",
                 "text": "ubiquitous marker"} for i in range(140)]
        cases = [{"case_id": f"{i + 1:06d}.txt", "text": "ubiquitous marker"}
                 for i in range(140)]
        db_path, output = self.root / "stream.sqlite3", self.root / "stream"
        make_database(db_path, {"case": cases, "passage": docs})
        requests = []
        connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
        probe = DatabaseProbe(connection, requests)
        with mock.patch.object(sparse, "_open_database", return_value=probe):
            sparse.build_from_database(db_path, output, fetch_size=64)
        self.assertTrue(requests)
        self.assertTrue(all(size == 64 for size in requests))
        self.assertGreaterEqual(len(requests), 5)

    def test_source_hash_and_sidecar_hash_drift_are_rejected(self):
        self.reader.close()
        self.reader = None
        with (self.index_dir / "manifest.json").open("a", encoding="utf-8") as stream:
            stream.write(" ")
        with self.assertRaises(M3Error):
            sparse.SparseBM25(self.db_path, self.index_dir)

        other_db = self.root / "other.sqlite3"
        make_database(other_db, {"case": self.cases, "passage": self.passages})
        with self.assertRaises(M3Error):
            sparse.SparseBM25(other_db, self.index_dir)

    def test_incomplete_or_corrupt_builder_output_is_not_accepted(self):
        partial = self.root / "partial"
        make_database(self.root / "bad.sqlite3", {"case": self.cases, "passage": self.passages}, bad="unknown_doc")
        with self.assertRaises(M3Error):
            sparse.build_from_database(self.root / "bad.sqlite3", partial, fetch_size=64)
        self.assertTrue(partial.exists())
        self.assertFalse((partial / "seal.json").exists())
        with self.assertRaises((M3Error, FileNotFoundError)):
            sparse.SparseBM25(self.db_path, partial)

    def test_malformed_df_and_nonpositive_tf_fail_without_seal(self):
        for corruption in ("bad_df", "zero_tf"):
            with self.subTest(corruption=corruption):
                db_path, output = self.root / f"{corruption}.sqlite3", self.root / corruption
                make_database(db_path, {"case": self.cases, "passage": self.passages}, bad=corruption)
                with self.assertRaises(M3Error):
                    sparse.build_from_database(db_path, output, fetch_size=64)
                self.assertFalse((output / "seal.json").exists())

    def test_reader_rejects_semantic_array_corruption_even_with_recomputed_seal(self):
        """A self-consistent hash list must not legitimize malformed arrays."""
        corruptions = ("nonmonotone_pointer", "out_of_range_doc", "nonfinite_score", "out_of_range_case")
        for corruption in corruptions:
            with self.subTest(corruption=corruption):
                directory = self.root / f"forged-{corruption}"
                shutil.copytree(self.index_dir, directory)
                if corruption == "nonmonotone_pointer":
                    offsets = np.load(directory / "passage.indptr.npy", mmap_mode="r+", allow_pickle=False)
                    offsets[1] = offsets[2] + 1
                    offsets.flush()
                    offsets._mmap.close()
                elif corruption == "out_of_range_doc":
                    indices = np.load(directory / "passage.indices.npy", mmap_mode="r+", allow_pickle=False)
                    indices[0] = len(self.passages) + 5
                    indices.flush()
                    indices._mmap.close()
                elif corruption == "nonfinite_score":
                    values = np.load(directory / "passage.values.npy", mmap_mode="r+", allow_pickle=False)
                    values[0] = np.nan
                    values.flush()
                    values._mmap.close()
                else:
                    codes = np.load(directory / "passage.cases.npy", mmap_mode="r+", allow_pickle=False)
                    codes[0] = 2**32 - 1
                    codes.flush()
                    codes._mmap.close()
                seal_path = directory / "seal.json"
                seal = json.loads(seal_path.read_text(encoding="utf-8"))
                for filename in seal:
                    data = (directory / filename).read_bytes()
                    seal[filename] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                seal_path.write_text(json.dumps(seal, sort_keys=True, separators=(",", ":")), encoding="utf-8")
                with self.assertRaises(M3Error):
                    sparse.SparseBM25(self.db_path, directory)


if __name__ == "__main__":
    unittest.main()
