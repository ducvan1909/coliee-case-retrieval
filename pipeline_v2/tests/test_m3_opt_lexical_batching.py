"""Independent behavioral tests for the isolated M3 optimization primitives."""
from collections import Counter
import math
from pathlib import Path
import random
import re
import tempfile
import unittest

from pipeline_v2.optimization.batching import batches, padding_stats
from pipeline_v2.optimization.index import PersistentBM25
from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.retrieval.bm25 import fuse_case_ranks, rank_cases


def oracle_tokens(text):
    # Spell out the documented baseline contract instead of calling its analyzer.
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def oracle_bm25(documents, query, *, k1=1.5, b=.75, limit=1024, exclude_case=None):
    token_rows = [Counter(oracle_tokens(d["text"])) for d in documents]
    lengths = [sum(row.values()) for row in token_rows]
    avg = sum(lengths) / len(lengths) if lengths else 1
    df = Counter(term for row in token_rows for term in row)
    n = len(documents)
    qterms = set(oracle_tokens(query))
    scored = []
    for d, counts, length in zip(documents, token_rows, lengths):
        if d["case_id"] == exclude_case:
            continue
        score = 0.0
        for term in qterms:
            tf = counts[term]
            if tf:
                idf = math.log(1 + (n - df[term] + .5) / (df[term] + .5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (avg or 1)))
        if score > 0:
            ident = d.get("passage_id", d["case_id"])
            scored.append((score, ident, d))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [{**{k: v for k, v in d.items() if k != "text"}, "score": score}
            for score, _, d in scored[:limit]]


class PersistentBM25Tests(unittest.TestCase):
    def setUp(self):
        self.docs = [
            {"case_id": "000001.txt", "passage_id": "p01", "text": "The issue is not merely procedural: Café under s. 5(1)(c)."},
            {"case_id": "000001.txt", "passage_id": "p02", "text": "The same case repeats CAFÉ; it does not waive the claim."},
            {"case_id": "000002.txt", "passage_id": "p03", "text": "Café and the 5 1 c test were considered."},
            {"case_id": "000003.txt", "passage_id": "p04", "text": "No matching terms in this paragraph."},
            {"case_id": "000004.txt", "passage_id": "p05", "text": "5(1)(c) and not reasonable; café café."},
        ]
        self.channels = {"passage": self.docs,
                         "case": [
                             {"case_id": "000001.txt", "text": "Café: not procedural. 5(1)(c)."},
                             {"case_id": "000002.txt", "text": "Café 5(1)(c), reasonable."},
                             {"case_id": "000003.txt", "text": "Damages only."},
                         ]}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "lexical.sqlite3"
        self.db = PersistentBM25.create(self.path, self.channels)
        self.addCleanup(self.db.close)

    def test_unicode_digits_and_negation_match_independent_bm25_oracle(self):
        for query in ("Café", "CAFÉ not", "s. 5(1)(c)", "NOT reasonable 5 1 c", "reasonable"): 
            with self.subTest(query=query):
                actual = self.db.search(query, "passage", limit=20)
                expected = oracle_bm25(self.docs, query, limit=20)
                self.assertEqual([h["passage_id"] for h in actual], [h["passage_id"] for h in expected])
                self.assertEqual([h["case_id"] for h in actual], [h["case_id"] for h in expected])
                for got, want in zip(actual, expected):
                    self.assertAlmostEqual(got["score"], want["score"], delta=1e-12)
                    self.assertNotIn("text", got)

    def test_exclusion_precedes_limit_and_empty_matches_are_omitted(self):
        actual = self.db.search("café", "passage", limit=2, exclude_case="000001.txt")
        expected = oracle_bm25(self.docs, "café", limit=2, exclude_case="000001.txt")
        self.assertEqual([h["passage_id"] for h in actual], [h["passage_id"] for h in expected])
        self.assertNotIn("000001.txt", {h["case_id"] for h in actual})
        self.assertEqual(self.db.search("term_not_in_index", "passage"), [])

    def test_query_reads_matching_postings_without_full_document_reload(self):
        statements = []
        self.db.db.set_trace_callback(statements.append)
        self.db.search("not café 5(1)(c)", "passage", limit=3)
        joined = "\n".join(statements).lower()
        self.db.db.set_trace_callback(None)
        self.assertIn("from postings p join documents d", joined)
        self.assertNotIn("order by id", joined)
        for query in (line for line in joined.splitlines() if line.startswith("select metadata from documents")):
            self.assertIn("and id=", query)

    def test_equal_score_ties_are_stable_by_identifier(self):
        tie_docs = [
            {"case_id": "b.txt", "passage_id": "p-b", "text": "alpha"},
            {"case_id": "a.txt", "passage_id": "p-a", "text": "alpha"},
        ]
        path = Path(self.tmp.name) / "ties.sqlite3"
        tied = PersistentBM25.create(path, {"passage": tie_docs})
        self.addCleanup(tied.close)
        self.assertEqual([h["passage_id"] for h in tied.search("alpha", "passage")], ["p-a", "p-b"])

    def test_channel_scope_and_limit_validation(self):
        with self.assertRaises(M3Error):
            self.db.search("café", "unknown")
        for limit in (0, -1, 1.5, True):
            with self.subTest(limit=limit), self.assertRaises(M3Error):
                self.db.search("café", "passage", limit=limit)

    def test_database_is_opened_readonly_and_corruption_fails_closed(self):
        self.assertTrue(self.db.db.execute("PRAGMA query_only").fetchone()[0] == 0)  # SQLite URI mode=ro enforces write rejection.
        with self.assertRaises(Exception):
            self.db.db.execute("DELETE FROM documents")
        damaged = Path(self.tmp.name) / "broken.sqlite3"
        damaged.write_bytes(b"not a sqlite database")
        broken = PersistentBM25(damaged)
        with self.assertRaises(Exception):
            broken.search("café", "passage")
        broken.close()


class LengthBatchingTests(unittest.TestCase):
    @staticmethod
    def docs():
        rng = random.Random(90177)
        sizes = [rng.randint(2, 448) for _ in range(1024)]
        # Include a dense cluster plus long outliers to make padding behavior observable.
        sizes[:32] = [2, 3, 4, 5, 6, 7, 8, 9] * 4
        return [{"passage_id": f"id-{i:04d}", "full_input_tokens": size} for i, size in enumerate(sizes)]

    def test_bucketed_batches_are_deterministic_complete_and_reduce_padding(self):
        docs = self.docs()
        for size in (16, 32, 64, 128):
            with self.subTest(batch_size=size):
                first = batches(docs, size)
                second = batches(list(reversed(docs)), size)
                ids = [p["passage_id"] for group in first for p in group]
                self.assertEqual(first, second)
                self.assertEqual(len(ids), len(docs))
                self.assertEqual(set(ids), {p["passage_id"] for p in docs})
                self.assertEqual(len(ids), len(set(ids)))
                self.assertTrue(all(1 <= len(group) <= size for group in first))
                bucketed = padding_stats(first)
                baseline = padding_stats(batches(docs, size, ordered=False))
                self.assertEqual(bucketed["documents"], 1024)
                self.assertEqual(bucketed["input_tokens"], baseline["input_tokens"])
                self.assertLessEqual(bucketed["padded_tokens"], baseline["padded_tokens"])

    def test_invalid_and_duplicate_inputs_rejected(self):
        doc = {"passage_id": "same", "full_input_tokens": 3}
        for size in (0, 129, True, 1.5):
            with self.subTest(batch_size=size), self.assertRaises(M3Error):
                batches([doc], size)
        with self.assertRaises(M3Error):
            batches([doc, dict(doc)], 16)
        for invalid in (0, 449, True, 2.5):
            with self.subTest(tokens=invalid), self.assertRaises(M3Error):
                batches([{"passage_id": "p", "full_input_tokens": invalid}], 16)


class UniqueCaseFusionTests(unittest.TestCase):
    def test_multiple_passage_hits_count_once_per_channel(self):
        hits = [
            {"case_id": "A.txt", "passage_id": "a1", "score": 9.0},
            {"case_id": "A.txt", "passage_id": "a2", "score": 8.0},
            {"case_id": "B.txt", "passage_id": "b1", "score": 7.0},
        ]
        ranked = rank_cases(hits)
        self.assertEqual([(x["case_id"], x["rank"]) for x in ranked], [("A.txt", 1), ("B.txt", 2)])
        fused = fuse_case_ranks({"passage_bm25": hits, "case_bm25": [
            {"case_id": "B.txt", "score": 2.0},
            {"case_id": "A.txt", "score": 1.0},
        ]}, limit=10, k=60)
        by_case = {x["case_id"]: x for x in fused}
        self.assertAlmostEqual(by_case["A.txt"]["score"], 1 / 61 + 1 / 62, delta=1e-15)
        self.assertAlmostEqual(by_case["B.txt"]["score"], 1 / 62 + 1 / 61, delta=1e-15)
        self.assertEqual(len(fused), 2)


if __name__ == "__main__":
    unittest.main()
