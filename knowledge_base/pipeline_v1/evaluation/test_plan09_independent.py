from __future__ import annotations

import json
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.au_gold import validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.build import _terra_batches
from knowledge_base.pipeline_v1.au_gold.core import load_json
from knowledge_base.pipeline_v1.au_gold.progress import build_progress
from knowledge_base.pipeline_v1.source_contract import open_source


PIPELINE = Path(__file__).resolve().parents[1]
POLICY = load_json(PIPELINE / "policies" / "au_annotation_policy.v1.json")
PROGRESS_PATH = PIPELINE / "reports" / "plan09_model_silver_progress.latest.json"
READINESS_PATH = PIPELINE / "reports" / "plan09_au_gold_readiness.latest.json"


class Plan09IndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.progress = load_json(PROGRESS_PATH)
        cls.readiness = load_json(READINESS_PATH)
        cls.root = Path(cls.readiness["outputs"]["output_root"])
        cls.build = load_json(cls.root / "au_annotation_build_manifest.json")
        cls.proposal_manifest = load_json(cls.root / "terra_proposal_manifest.json")
        cls.packets = {}
        for row in cls.build["cases"]:
            packet = load_json(cls.root / row["packet_ref"])
            cls.packets[packet["case_id"]] = packet

    def test_canonical_proposals_validate_and_have_exact_model_identity(self):
        seen = set()
        counts = {"reviewed": 0, "authority_units": 0, "hard_negatives": 0, "unresolved": 0}
        for record in self.proposal_manifest["proposals"]:
            proposal = load_json(self.root / record["proposal_ref"])
            packet = self.packets[proposal["case_id"]]
            text = open_source(self.build["source_store"], packet["case_id"], packet["source_hash"])
            validate_model_proposal(proposal, packet, text, POLICY)
            self.assertEqual(
                proposal["producer"],
                {
                    "source_type": "model",
                    "producer_id": "model:gpt-5.6-terra",
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "low",
                },
            )
            for review in proposal["target_reviews"]:
                key = (proposal["case_id"], review["target_id"])
                self.assertNotIn(key, seen)
                seen.add(key)
                self.assertEqual(review["review_trace"]["target_id"], review["target_id"])
                counts["reviewed"] += 1
                counts["authority_units"] += len(review["authority_units"])
                counts["hard_negatives"] += review["hard_negative"] is not None
                counts["unresolved"] += review["model_outcome"] == "unresolved"
        self.assertEqual(counts, {"reviewed": 212, "authority_units": 99, "hard_negatives": 112, "unresolved": 1})

    def test_progress_report_is_exactly_reproducible(self):
        rebuilt = build_progress(self.root, self.progress["blocker"])
        self.assertEqual(rebuilt, self.progress)
        self.assertEqual(
            (rebuilt["expected_target_count"], rebuilt["reviewed_target_count"], rebuilt["missing_target_count"]),
            (369, 369, 0),
        )
        self.assertEqual(rebuilt["canonical_duplicate_target_count"], 0)
        incomplete = [row for row in rebuilt["cases"] if not row["coverage_complete"]]
        self.assertEqual(incomplete, [])
        historical = load_json(PIPELINE / "evaluation/plan09_independent_summary.json")
        self.assertEqual(tuple(historical["counts"][k] for k in
                         ("expected_targets", "reviewed_targets", "missing_targets")), (369, 212, 157))
        self.assertEqual(historical["incomplete_cases"], [{"case_id": "099980", "missing_target_count": 157}])
        self.assertFalse(historical["plan10_allowed"])

    def test_batch_builder_deduplicates_overlapping_target_deterministically(self):
        packet = self.packets["011904"]
        target_id = packet["tasks"][0]["target_id"]
        shared = {"arm": "P2a", "target_ids": [target_id]}
        workload = {
            "case_id": packet["case_id"],
            "source_hash": packet["source_hash"],
            "regions": [
                {**shared, "region_id": "region-z", "fingerprint": "f" * 64},
                {**shared, "region_id": "region-a", "fingerprint": "0" * 64},
            ],
        }
        result = _terra_batches([workload], [packet], POLICY)
        owners = [batch for batch in result["batches"] if target_id in batch["target_ids"]]
        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0]["region_id"], "region-a")
        self.assertEqual(
            result["excluded_duplicate_assignments"],
            [{"case_id": "011904", "target_id": target_id, "owner_region_id": "region-a", "excluded_region_id": "region-z"}],
        )

    def test_plan10_remains_locked_without_human_gold(self):
        gates = self.readiness["gates"]
        self.assertFalse(gates["plan10_allowed"])
        self.assertFalse(gates["locked_gold_valid"])
        self.assertFalse(gates["two_independent_human_submissions"])
        self.assertFalse(gates["human_adjudication_complete"])
        self.assertEqual(self.readiness["overall_status"], "gold_awaiting_independent_adjudication")
        self.assertFalse(self.readiness["human_annotation_progress"]["semantic_gold_available"])
        self.assertIsNone(self.readiness["gold_lock_status"]["locked_gold_snapshot"])
        self.assertFalse(self.progress["semantic_gold"])
        self.assertEqual(self.progress["evaluation_against"], "model_silver")


if __name__ == "__main__":
    unittest.main()
