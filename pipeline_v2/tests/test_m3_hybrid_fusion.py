"""Independent tests for unique-case reciprocal-rank fusion.

These cases exercise only the pure fusion helper. They deliberately create
synthetic channel rankings, with no corpus, labels, DB, or remote service.
"""
import unittest

from pipeline_v2.full_search.hybrid import _best_cases, fuse_channels


class FusionTests(unittest.TestCase):
    def test_sibling_passages_and_repeated_case_get_one_channel_vote(self):
        channels = {
            "dense": [
                {"case_id": "000001.txt", "passage_id": "p1", "score": .99},
                {"case_id": "000001.txt", "passage_id": "p2", "score": .98},
                {"case_id": "000002.txt", "passage_id": "p3", "score": .97},
            ],
            "case": [],
            "passage": [],
        }

        rows = fuse_channels(channels, limit=10)
        by_id = {row["case_id"]: row for row in rows}

        # The repeated case is retained once at its first rank; its sibling
        # passage cannot move it ahead of the rank-3 case or add another vote.
        self.assertEqual(list(by_id), ["000001.txt", "000002.txt"])
        self.assertAlmostEqual(by_id["000001.txt"]["score"], 1 / 61)
        self.assertAlmostEqual(by_id["000002.txt"]["score"], 1 / 62)
        self.assertEqual(by_id["000001.txt"]["channels"]["dense"]["rank"], 1)

    def test_channel_cap_counts_unique_cases_not_raw_passage_leads(self):
        # 100 sibling hits for one case must not consume 100 candidate slots.
        dense = [{"case_id": "000001.txt", "passage_id": f"p{i:03d}", "score": 100-i}
                 for i in range(100)]
        dense.extend({"case_id": f"{i:06d}.txt", "passage_id": f"q{i:03d}", "score": 1}
                     for i in range(2, 102))

        rows = _best_cases(dense)
        ids = [row["case_id"] for row in rows]

        self.assertEqual(len(ids), 100)
        self.assertEqual(ids[0], "000001.txt")
        self.assertEqual(ids[-1], "000100.txt")
        self.assertNotIn("000101.txt", ids)

    def test_equal_fusion_scores_have_stable_case_id_order(self):
        channels = {
            "dense": [
                {"case_id": "000002.txt", "passage_id": "a", "score": 1},
                {"case_id": "000001.txt", "passage_id": "b", "score": 1},
            ],
            "case_bm25": [
                {"case_id": "000001.txt", "score": 1},
                {"case_id": "000002.txt", "score": 1},
            ],
        }
        rows = fuse_channels(channels, limit=10)
        self.assertEqual([row["case_id"] for row in rows], ["000001.txt", "000002.txt"])

    def test_result_limit_is_applied_after_fusion(self):
        channels = {
            "dense": [{"case_id": f"{i:06d}.txt", "passage_id": f"p{i}", "score": 10-i}
                      for i in range(1, 5)],
            "case": [{"case_id": f"{i:06d}.txt", "score": 10-i}
                     for i in range(2, 6)],
        }
        rows = fuse_channels(channels, limit=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["case_id"] for row in rows], ["000002.txt", "000003.txt"])


if __name__ == "__main__":
    unittest.main()
