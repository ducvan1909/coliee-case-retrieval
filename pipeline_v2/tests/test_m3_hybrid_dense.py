"""Independent dense-path tests using only fake readers and fake responses."""
import unittest
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np

from pipeline_v2.full_search import hybrid
from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.retrieval.qdrant import point_id


FINGERPRINT = "fp-test"
QUERY_CASE = "000001.txt"
OTHER_CASE = "000002.txt"


def passage(case_id=OTHER_CASE, passage_id="p1"):
    return {
        "case_id": case_id,
        "passage_id": passage_id,
        "source_hash": "a" * 64,
        "exact_input_sha256": "b" * 64,
        "span_bytes": [10, 20],
        "parent_handle": "h1",
        "policy_hash": "c" * 64,
        "tokenizer_fingerprint": "tokenizer-test",
    }


def point(doc, score=1.0, fingerprint=FINGERPRINT):
    return {"id": point_id(doc["passage_id"], fingerprint), "score": score,
            "payload": {**doc, "embedding_fingerprint": fingerprint}}


class DenseHitValidationTests(unittest.TestCase):
    class Reader:
        def __init__(self, docs):
            self.docs = docs

        def get_many(self, kind, ids):
            if kind != "passage":
                raise AssertionError(kind)
            try:
                return [self.docs[ident] for ident in ids]
            except KeyError as exc:
                raise M3Error("Missing lexical hit metadata") from exc

    def test_payload_is_bound_to_reader_metadata_and_point_identity(self):
        doc = passage()
        rows = hybrid.validate_dense_hits([point(doc)], self.Reader({"p1": doc}), FINGERPRINT,
                                          QUERY_CASE)
        self.assertEqual(rows[0]["passage_id"], "p1")
        self.assertEqual(rows[0]["case_id"], OTHER_CASE)
        self.assertEqual(rows[0]["score"], 1.0)

    def test_rejects_duplicate_point_foreign_fingerprint_and_query_case(self):
        doc = passage()
        reader = self.Reader({"p1": doc})
        for points in (
            [point(doc), point(doc)],
            [point(doc, fingerprint="foreign")],
            [point(passage(QUERY_CASE))],
        ):
            with self.subTest(points=points), self.assertRaises(M3Error):
                hybrid.validate_dense_hits(points, reader, FINGERPRINT, QUERY_CASE)

    def test_rejects_mismatched_payload_score_order_and_unknown_hit(self):
        doc = passage()
        altered = point(doc)
        altered["payload"]["source_hash"] = "wrong"
        unknown = point(passage(passage_id="missing"))
        for points, reader in (
            ([altered], self.Reader({"p1": doc})),
            ([point(doc, .5), point(passage(passage_id="p2"), .9)],
             self.Reader({"p1": doc, "p2": passage(passage_id="p2")})),
            ([unknown], self.Reader({})),
        ):
            with self.subTest(points=points), self.assertRaises(M3Error):
                hybrid.validate_dense_hits(points, reader, FINGERPRINT, QUERY_CASE)


class DenseRequestTests(unittest.TestCase):
    class Reader:
        def __init__(self, doc):
            self.channels = {"passage": {"case_codes": {QUERY_CASE: 0},
                                         "cases": np.asarray([0, 1])}}
            self.doc = doc

        def get_many(self, kind, ids):
            return [self.doc for _ in ids]

    class DB:
        path = "/collections/full"

        def __init__(self, points):
            self.points = points
            self.calls = []

        def _request(self, method, path, body):
            self.calls.append((method, path, body))
            return {"points": self.points}

    def test_one_exact_dense_request_excludes_query_case_before_cap(self):
        doc = passage()
        db = self.DB([point(doc)])
        session = object.__new__(hybrid.HybridSession)
        session.fingerprint = FINGERPRINT
        session.dimensions = 2
        session.manifest = {"passages": 2}
        session.lexical = mock.Mock()
        session.lexical.reader = self.Reader(doc)
        session.db = db
        session.vectors = mock.Mock()
        session.vectors.select.return_value = {"p1": np.asarray([1.0, 0.0], dtype=np.float32)}

        hits, coverage, _ = session._dense(np.asarray([1.0, 0.0], dtype=np.float32), QUERY_CASE)

        self.assertEqual(len(db.calls), 1)
        method, path, body = db.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(body["limit"], 1)  # eligible points after query-case exclusion
        self.assertEqual(body["params"], {"exact": True})
        self.assertEqual(body["filter"]["must_not"][0]["key"], "case_id")
        self.assertEqual(body["filter"]["must_not"][0]["match"]["value"], QUERY_CASE)
        self.assertEqual([hit["passage_id"] for hit in hits], ["p1"])
        self.assertEqual(coverage["validated_cached_scores"], 1)


class ReadinessOrderingTests(unittest.TestCase):
    def test_failed_readiness_stops_before_opening_remote_database(self):
        fake_lexical = mock.Mock()
        fake_lexical.manifest = {
            "profile": {"embedding": {"dimensions": 2}, "qdrant": {"url": "unused"}},
            "embedding_fingerprint": FINGERPRINT,
        }
        fake_lexical.close = mock.Mock()
        with mock.patch.object(hybrid, "LexicalSession", return_value=fake_lexical), \
                mock.patch.object(hybrid, "_readiness", side_effect=M3Error("stale receipt")), \
                mock.patch.object(hybrid, "FullQdrant") as qdrant:
            with self.assertRaisesRegex(M3Error, "stale receipt"):
                hybrid.HybridSession(".")
        qdrant.assert_not_called()
        fake_lexical.close.assert_called_once()

    def test_wrong_live_count_stops_before_query_embedding(self):
        session = object.__new__(hybrid.HybridSession)
        session.manifest = {"source_hashes": {QUERY_CASE: "source"}, "passages": 2}
        session._guard = mock.Mock()
        session._lexical = mock.Mock(return_value=({}, {}, {}))
        session.db = mock.Mock()
        session.db.count.return_value = 1
        session._query_embedding = mock.Mock()

        with self.assertRaisesRegex(M3Error, "count differs"):
            session.search("some query", QUERY_CASE)

        session.db.check_schema.assert_called_once()
        session._query_embedding.assert_not_called()


class CachedDiagnosticTests(unittest.TestCase):
    def test_cached_vector_diagnostic_never_requests_a_model_vector(self):
        doc = passage(QUERY_CASE, "query-passage")
        session = object.__new__(hybrid.HybridSession)
        session.root = Path(".").resolve()
        session.last_request_id = None
        session.manifest = {"source_hashes": {QUERY_CASE: "source"}, "passages": 2,
                            "cases": 2, "collection": "fake"}
        session.profile = {"embedding": {"dimensions": 2}}
        session.fingerprint = FINGERPRINT
        session.dimensions = 2
        session.code_sha256 = "code"
        session.initialization_seconds = 0.0
        session.lexical = mock.Mock()
        session.lexical.binding = {"manifest.json": "manifest"}
        session.lexical.reader.get_many.return_value = [doc]
        session.lexical.search.return_value = {"hits": [], "matched_documents": 0}
        session._guard = mock.Mock()
        session._check_db = mock.Mock()
        session._query_embedding = mock.Mock(side_effect=AssertionError("model must not be called"))
        session._dense = mock.Mock(return_value=([], {"raw_hits": 0}, {"dense_query_seconds": 0.0}))
        session._compatibility = mock.Mock(side_effect=AssertionError("cached diagnostic must not require inference compatibility"))
        session.vectors = mock.Mock()
        session.vectors.select.return_value = {"query-passage": np.asarray([1.0, 0.0], dtype=np.float32)}

        result = session.search_cached("some query", QUERY_CASE, "query-passage")

        self.assertEqual(result["execution_mode"], "cached_vector_diagnostic")
        self.assertEqual(result["model_requests"], 0)
        self.assertEqual(result["query_vector"]["kind"], "cached_document_vector_diagnostic")
        self.assertEqual(result["query_vector"]["input_sha256"], doc["exact_input_sha256"])
        session._query_embedding.assert_not_called()
        session._dense.assert_called_once()
        session._compatibility.assert_not_called()

    def test_embedding_failure_leaves_request_with_unknown_tokens_in_ledger(self):
        class TokenizerBackend:
            def encode(self, rendered, add_special_tokens=True):
                return mock.Mock(ids=[101, 151643])

        class Tokenizer:
            backend = TokenizerBackend()

        class FailingEmbedder:
            def encode(self, texts, kind):
                raise TimeoutError("simulated transport timeout")

        with tempfile.TemporaryDirectory() as temp:
            request_id = "a" * 32
            session = object.__new__(hybrid.HybridSession)
            session.root = Path(temp)
            session.profile = {"embedding": {"query_instruction": "retrieve", "max_tokens": 448}}
            session.fingerprint = FINGERPRINT
            session.dimensions = 2
            session._compatibility = mock.Mock()
            with mock.patch.object(hybrid, "PinnedTokenizer", return_value=Tokenizer()), \
                    mock.patch.object(hybrid, "OptModalEmbedder", return_value=FailingEmbedder()):
                with self.assertRaises(M3Error):
                    session._query_embedding("question", QUERY_CASE, request_id)

            ledger_path = Path(temp) / hybrid.RUNTIME_DIR / request_id / "ledger.sqlite3"
            import sqlite3
            db = sqlite3.connect(ledger_path)
            try:
                row = db.execute("SELECT status,requests,tokens,error FROM attempts").fetchone()
            finally:
                db.close()
            self.assertEqual(row[0], "error")
            self.assertEqual(row[1], 1)
            self.assertIsNone(row[2])
            self.assertEqual(row[3], "TimeoutError")


if __name__ == "__main__":
    unittest.main()
