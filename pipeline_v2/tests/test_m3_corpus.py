import unittest

from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.retrieval.corpus import Corpus
from pipeline_v2.tests import test_m2_passages_store as fixture


class M3CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PassageStoreTests.setUpClass()
        cls.fixture_class=fixture.PassageStoreTests
        cls.root=cls.fixture_class.root
        cls.bundle=cls.fixture_class.bundle
        cls.case=fixture.nav_tests.M2NavigationStoreTests.ids[0]

    @classmethod
    def tearDownClass(cls):
        cls.fixture_class.tearDownClass()

    def test_selected_passages_keep_requested_order_and_exact_source_mapping(self):
        corpus=Corpus(self.root,self.bundle)
        first=list(corpus.iter_passages())
        chosen=[first[-1]["passage_id"],first[0]["passage_id"]]
        selected=corpus.selected(chosen)
        self.assertEqual([p["passage_id"] for p in selected],chosen)
        for passage in selected:
            opened=corpus.open(passage["passage_id"])
            self.assertEqual(opened["hit_text"],passage["text"])
            self.assertEqual(opened["hit_span_bytes"],passage["span_bytes"])
            self.assertTrue(opened["diagnostic_only"])
            self.assertFalse(opened["M4_delivery_recorded"])

    def test_pilot_selection_rejects_missing_passage_id(self):
        with self.assertRaises(M3Error):
            Corpus(self.root,self.bundle).selected(["999999:missing"])

    def test_passage_corpus_detects_raw_source_drift(self):
        corpus=Corpus(self.root,self.bundle)
        source=self.root/"data/task1_train_files_2026/cases"/self.case
        original=source.read_bytes()
        try:
            source.write_bytes(original+b"changed")
            with self.assertRaises((M3Error,ValueError)):
                next(corpus.iter_passages())
        finally:
            source.write_bytes(original)


if __name__=="__main__":
    unittest.main()
