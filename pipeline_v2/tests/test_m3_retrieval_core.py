import unittest

from pipeline_v2.retrieval.bm25 import BM25, analyze, fuse_case_ranks, rank_cases


class M3BM25Tests(unittest.TestCase):
    def setUp(self):
        self.docs = [
            {"case_id":"000001.txt","passage_id":"p1","text":"The issue is not merely procedural: Café under s. 5(1)(c)."},
            {"case_id":"000001.txt","passage_id":"p2","text":"The same case repeats the café point in French: café."},
            {"case_id":"000002.txt","passage_id":"p3","text":"The appeal was procedurally reasonable under section 5(1)(c)."},
            {"case_id":"000003.txt","passage_id":"p4","text":"A separate claim addresses damages."},
        ]

    def test_unicode_digits_negation_and_punctuation_survive_analyzer(self):
        terms=analyze(self.docs[0]["text"])
        self.assertIn("café",terms)
        self.assertIn("not",terms)
        self.assertIn("5",terms)
        self.assertIn("1",terms)
        self.assertIn("c",terms)
        self.assertIn("s",terms)

    def test_rare_legal_terms_rank_and_exclude_case(self):
        index=BM25(self.docs)
        hits=index.search("not café 5(1)(c)",limit=3)
        self.assertEqual(hits[0]["passage_id"],"p1")
        self.assertEqual({h["case_id"] for h in index.search("procedurally",exclude_case="000001.txt")},{"000002.txt"})
        self.assertFalse(index.search("damages",exclude_case="000003.txt"))

    def test_case_ranking_keeps_best_passage_without_extra_votes(self):
        hits=BM25(self.docs).search("café",limit=4)
        ranked=rank_cases(hits)
        self.assertEqual([h["case_id"] for h in ranked], ["000001.txt"])
        self.assertEqual(ranked[0]["passage_id"], hits[0]["passage_id"])

    def test_fusion_votes_once_per_case_per_channel(self):
        dense=[{"case_id":"000001.txt","passage_id":"a","score":10},
               {"case_id":"000001.txt","passage_id":"b","score":9},
               {"case_id":"000002.txt","passage_id":"c","score":8}]
        bm25=[{"case_id":"000002.txt","passage_id":"d","score":12},
              {"case_id":"000001.txt","passage_id":"e","score":11}]
        fused=fuse_case_ranks({"dense":dense,"bm25":bm25},limit=3,k=60)
        by_id={x["case_id"]:x for x in fused}
        self.assertEqual(set(by_id),{"000001.txt","000002.txt"})
        self.assertAlmostEqual(by_id["000001.txt"]["score"],1/61+1/62)
        self.assertAlmostEqual(by_id["000002.txt"]["score"],1/62+1/61)
        self.assertEqual(set(by_id["000001.txt"]["channels"]),{"dense","bm25"})
        self.assertEqual(by_id["000001.txt"]["channels"]["dense"]["passage_id"],"a")

    def test_fusion_is_stable_for_channel_input_order(self):
        channels={"x":[{"case_id":"z"},{"case_id":"a"}],
                  "y":[{"case_id":"a"},{"case_id":"z"}]}
        self.assertEqual(fuse_case_ranks(channels),fuse_case_ranks(dict(reversed(list(channels.items())))))


if __name__=="__main__":
    unittest.main()
