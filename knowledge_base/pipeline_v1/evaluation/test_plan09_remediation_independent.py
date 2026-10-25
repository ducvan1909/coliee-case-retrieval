from __future__ import annotations

import copy
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, load_json, lock_silver, verify_span
from knowledge_base.pipeline_v1.au_gold.progress import build_progress
from knowledge_base.pipeline_v1.au_gold.remediation import (
    ROOT,
    assert_lockable,
    dependencies,
    digest,
    effective_proposals,
    amendment_heads,
    scan_attribution_risks,
    validate_amendment,
)


PIPELINE = Path(__file__).resolve().parents[1]


class Plan09RemediationIndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_json(ROOT / "semantic_defect_registry.json")
        cls.finding = next(x for x in cls.registry["findings"] if x["finding_id"] == "P09-S01")
        cls.amendment = load_json(ROOT / "model_amendments" / "p09-s01-gpt6-unresolved-v1.json")
        manifest = load_json(ROOT / "terra_proposal_manifest.json")
        record = next(x for x in manifest["proposals"] if x["proposal_id"] == cls.finding["proposal_id"])
        cls.original_path = ROOT / record["proposal_ref"]
        cls.historical = load_json(PIPELINE / "evaluation/plan09_remediation_independent_summary.json")

    def test_r1_registry_exact_evidence_original_immutable_and_lock_blocked(self):
        self.assertEqual(self.historical["p09_s01"]["finding_status"], "quarantined_pending_review")
        self.assertEqual(self.finding["status"], "closed")
        assert_lockable(self.registry, ROOT)
        self.assertEqual(self.finding["severity"], "severe")
        self.assertEqual(digest(self.original_path), self.finding["proposal_sha256"])
        packet, source, policy = dependencies(ROOT, self.finding["case_id"])
        verify_span(self.finding["evidence_span"], source, self.finding["case_id"], self.finding["source_hash"])
        with self.assertRaises(AnnotationError) as caught:
            lock_silver([], [], {}, {}, semantic_registry=load_json(
                ROOT / "registry_history/p09-r3-before-final-acceptance-v1.json"))
        self.assertEqual(caught.exception.code, "silver_semantic_quarantine")

        # A fabricated closure reference must not bypass the severe-finding gate.
        fake = copy.deepcopy(self.registry)
        fake["findings"][0]["status"] = "closed"
        fake["findings"][0]["independent_review_ref"] = "reports/does-not-exist.md"
        fake["findings"][0]["resolution_amendment_id"] = "does-not-exist"
        with self.assertRaises(AnnotationError) as caught:
            assert_lockable(fake)
        self.assertEqual(caught.exception.code, "silver_semantic_closure_unverified")

    def test_r2_scanner_reproduces_49_item_artifact_without_mutation(self):
        paths = sorted((ROOT / "model_proposals").rglob("*.json"))
        before = {str(path): digest(path) for path in paths}
        generated = scan_attribution_risks(ROOT)
        checked_in = load_json(ROOT / "attribution_risk_queue.json")
        self.assertEqual(generated, checked_in)
        self.assertEqual(generated["item_count"], 49)
        self.assertFalse(generated["labels_changed"])
        self.assertEqual(before, {str(path): digest(path) for path in paths})
        self.assertTrue(any(x["target_id"] == self.finding["target_id"] for x in generated["items"]))
        for item in generated["items"]:
            packet, source, policy = dependencies(ROOT, item["case_id"])
            for span in item["cue_spans"]:
                verify_span(span, source, item["case_id"], item["source_hash"])

    def test_r3_historical_unresolved_preserved_and_current_head_accepted(self):
        checks = validate_amendment(self.amendment, ROOT)
        self.assertFalse(checks["semantic_gold"])
        self.assertEqual(digest(self.original_path), self.amendment["supersedes_proposal_sha256"])
        original = load_json(self.original_path)
        original_review = next(x for x in original["target_reviews"] if x["target_id"] == self.finding["target_id"])
        self.assertEqual(original_review["model_outcome"], "positive")

        effective = next(x for x in effective_proposals(ROOT) if x["proposal_id"] == self.finding["proposal_id"])
        replacement = next(x for x in effective["target_reviews"] if x["target_id"] == self.finding["target_id"])
        historical = self.amendment["replacement_review"]
        self.assertEqual(historical["model_outcome"], "unresolved")
        self.assertEqual(historical["authority_units"], [])
        self.assertIsNone(historical["hard_negative"])
        head = next(x for x in amendment_heads(ROOT) if
                    (x["supersedes_proposal_id"], x["target_id"]) ==
                    (self.finding["proposal_id"], self.finding["target_id"]))
        self.assertEqual(replacement, head["replacement_review"])
        self.assertEqual(replacement["model_outcome"], "positive")
        self.assertEqual(head["amendment_id"], self.finding["resolution_amendment_id"])
        self.assertEqual(self.finding["status"], "closed")
        assert_lockable(self.registry, ROOT)

        # Even with real record paths, an unresolved amendment cannot close a severe finding.
        fake = copy.deepcopy(self.registry)
        fake["findings"][0].update(
            status="closed",
            resolution_amendment_id=self.amendment["amendment_id"],
            independent_review_ref="reports/plan09_remediation_independent_review.md",
        )
        with self.assertRaises(AnnotationError) as caught:
            assert_lockable(fake, ROOT)
        self.assertEqual(caught.exception.code, "silver_semantic_closure_unverified")

    def test_historical_partial_and_current_complete_counts_are_distinct(self):
        report = load_json(PIPELINE / "reports" / "plan09_model_silver_progress.latest.json")
        rebuilt = build_progress(ROOT, report["blocker"])
        self.assertEqual(rebuilt, report)
        old = self.historical["effective_progress"]
        self.assertEqual(tuple(old[k] for k in ("reviewed_target_count", "missing_target_count",
                         "authority_unit_count", "hard_negative_count", "unresolved_target_count",
                         "open_severe_finding_count")), (212, 157, 98, 112, 2, 1))
        self.assertFalse(old["plan10_allowed"])
        self.assertEqual(tuple(rebuilt[k] for k in ("reviewed_target_count", "missing_target_count",
                         "authority_unit_count", "hard_negative_count", "unresolved_target_count")),
                         (369, 0, 188, 186, 8))
        self.assertEqual(rebuilt["semantic_remediation"]["open_severe_finding_count"], 0)
        self.assertEqual(rebuilt["canonical_duplicate_target_count"], 0)
        self.assertFalse(rebuilt["semantic_gold"])
        from knowledge_base.pipeline_v1.au_gold.r4_amendments import effective_count_delta
        self.assertEqual(effective_count_delta(ROOT), {"authority_units": 1, "hard_negatives": 1, "unresolved": -2})
        # This frozen structural progress predates the separate revisioned R5/R6 gate.
        self.assertFalse(rebuilt["semantic_remediation"]["plan10_allowed"])


if __name__ == "__main__":
    unittest.main()
