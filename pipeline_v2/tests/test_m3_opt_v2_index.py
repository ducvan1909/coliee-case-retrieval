"""Independent behavioral tests for the M3 v2 persisted lexical index."""
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unittest

from pipeline_v2.optimization_v2.index import PersistentBM25


def oracle_tokens(text):
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def oracle_bm25(documents, query, *, k1=1.5, b=.75, limit=1024, exclude_case=None):
    rows = [Counter(oracle_tokens(doc["text"])) for doc in documents]
    lengths = [sum(row.values()) for row in rows]
    avg = sum(lengths) / len(lengths) if lengths else 1
    df = Counter(term for row in rows for term in row)
    qterms = set(oracle_tokens(query))
    scored = []
    for doc, counts, length in zip(documents, rows, lengths):
        if doc["case_id"] == exclude_case:
            continue
        score = 0.0
        for term in qterms:
            tf = counts[term]
            if tf:
                idf = math.log(1 + (len(documents) - df[term] + .5) / (df[term] + .5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (avg or 1)))
        if score:
            ident = doc.get("passage_id", doc["case_id"])
            scored.append((score, ident, doc))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{**{k: v for k, v in doc.items() if k != "text"}, "score": score}
            for score, _, doc in scored[:limit]]


class OneShotDocs:
    """Fails if the builder consumes a document source more than once."""
    def __init__(self, rows):
        self.rows = rows
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        if self.iterations > 1:
            raise AssertionError("document stream consumed more than once")
        yield from self.rows


class PersistentBM25V2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docs = [
            {"case_id": "000001.txt", "passage_id": "p01", "text": "The issue is not merely procedural: Café under s. 5(1)(c).", "parent_handle": "p1"},
            {"case_id": "000001.txt", "passage_id": "p02", "text": "The same case repeats CAFÉ; it does not waive the claim.", "parent_handle": "p2"},
            {"case_id": "000002.txt", "passage_id": "p03", "text": "Café and the 5 1 c test were considered.", "parent_handle": "p3"},
            {"case_id": "000003.txt", "passage_id": "p04", "text": "No matching terms in this paragraph.", "parent_handle": "p4"},
            {"case_id": "000004.txt", "passage_id": "p05", "text": "5(1)(c) and not reasonable; café café.", "parent_handle": "p5"},
        ]

    def test_streamed_build_preserves_refs_and_never_persists_raw_text(self):
        rows = OneShotDocs(self.docs)
        index = PersistentBM25.create(self.root / "lexical.sqlite3", {"passage": rows})
        self.addCleanup(index.close)
        self.assertEqual(rows.iterations, 1)
        metadata = index.get_many("passage", ["p03", "p01"])
        self.assertEqual([item["passage_id"] for item in metadata], ["p03", "p01"])
        self.assertEqual(metadata[0]["parent_handle"], "p3")
        self.assertTrue(all("text" not in item for item in metadata))
        raw_metadata = [row[0] for row in index.db.execute("SELECT metadata FROM documents")]
        self.assertTrue(all("text" not in json.loads(raw) for raw in raw_metadata))
        self.assertFalse(any(doc["text"] in raw for doc in self.docs for raw in raw_metadata))

    def test_search_matches_independent_bm25_oracle_for_unicode_citations_and_negation(self):
        index = PersistentBM25.create(self.root / "oracle.sqlite3", {"passage": iter(self.docs)})
        self.addCleanup(index.close)
        for query in ("Café", "CAFÉ not", "s. 5(1)(c)", "NOT reasonable 5 1 c", "reasonable"):
            with self.subTest(query=query):
                actual = index.search(query, "passage", limit=20)
                expected = oracle_bm25(self.docs, query, limit=20)
                self.assertEqual([h["passage_id"] for h in actual], [h["passage_id"] for h in expected])
                for got, want in zip(actual, expected):
                    self.assertAlmostEqual(got["score"], want["score"], delta=1e-12)
                    self.assertNotIn("text", got)

    def test_exclude_case_precedes_limit_and_ties_use_identifier(self):
        docs = [
            {"case_id": "z.txt", "passage_id": "z", "text": "alpha alpha"},
            {"case_id": "a.txt", "passage_id": "a", "text": "alpha alpha"},
            {"case_id": "b.txt", "passage_id": "b", "text": "alpha"},
        ]
        index = PersistentBM25.create(self.root / "ties.sqlite3", {"passage": iter(docs)})
        self.addCleanup(index.close)
        actual = index.search("alpha", "passage", limit=1, exclude_case="a.txt")
        expected = oracle_bm25(docs, "alpha", limit=1, exclude_case="a.txt")
        self.assertEqual(actual, expected)
        self.assertEqual(actual[0]["passage_id"], "z")

    def test_query_metadata_fetch_is_batched_not_one_select_per_hit(self):
        docs = [{"case_id": f"{i:06}.txt", "passage_id": f"p{i:04}", "text": "common repeated legal words"}
                for i in range(80)]
        index = PersistentBM25.create(self.root / "batch.sqlite3", {"passage": iter(docs)})
        self.addCleanup(index.close)
        statements = []
        index.db.set_trace_callback(statements.append)
        result = index.search("common legal", "passage", limit=70)
        index.db.set_trace_callback(None)
        metadata_selects = [sql for sql in statements if re.match(r"\s*SELECT\s+(?:[^;]*,\s*)?metadata\b", sql, re.I)]
        self.assertEqual(len(result), 70)
        self.assertLessEqual(len(metadata_selects), 2, f"metadata queries should be bounded, got {len(metadata_selects)}")

    def test_relative_and_absolute_database_paths_open(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            relative = Path("nested/relative.sqlite3")
            relative.parent.mkdir()
            index = PersistentBM25.create(relative, {"passage": iter(self.docs)})
            index.close()
            reopened = PersistentBM25(relative)
            self.assertTrue(reopened.search("café", "passage"))
            reopened.close()
        finally:
            os.chdir(previous)
        absolute = self.root / "absolute.sqlite3"
        index = PersistentBM25.create(absolute, {"passage": iter(self.docs)})
        self.addCleanup(index.close)
        self.assertTrue(index.search("reasonable", "passage"))


if __name__ == "__main__":
    unittest.main()
