"""Independent offline regressions for source-bound Plan 11 review sidecars."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.au_candidate_store import build_store
from knowledge_base.pipeline_v1.au_candidate_store.reviews import (
    canonical_sha256,
    run_sha256,
)


class AUCandidateReviewTests(unittest.TestCase):
    case_id = "013948"
    target_id = "at-review-1"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_store = self.root / "source-store"
        self.atom_root = self.root / "atoms"
        self.source = "[12] The court must give reasons. Counsel disputes the outcome."
        self.source_hash = hashlib.sha256(self.source.encode("utf-8")).hexdigest()
        self.target_start = self.source.index("The court")
        self.target_end = self.source.index(".") + 1
        self.binding = self._install_case()
        self.report = self._report([self.au()])

    def _install_case(self, source=None, target_start=None, target_end=None):
        if source is not None:
            self.source = source
            self.source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if target_start is not None:
            self.target_start = target_start
        if target_end is not None:
            self.target_end = target_end
        source_relative = f"cases/{self.case_id}/versions/{self.source_hash}"
        source_dir = self.source_store / source_relative
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "source.txt").write_text(self.source, encoding="utf-8")
        source_record = {
            "record_type": "CaseSource", "contract_version": "case-source-v1",
            "case_id": self.case_id, "source_version": f"src-{self.source_hash[:16]}",
            "source_hash": self.source_hash, "text_ref": f"{source_relative}/source.txt",
            "byte_length": len(self.source.encode("utf-8")), "char_length": len(self.source),
            "encoding": "utf-8-sig", "offset_unit": "unicode_codepoint",
            "metadata": {"corpus_split": "calibration", "kos_role": "source",
                         "input_source_path": "synthetic-review.txt"},
        }
        (source_dir / "case_source.json").write_text(json.dumps(source_record), encoding="utf-8")

        # The first atom starts before the raw TARGET so the leading marker is
        # selected evidence but cannot itself establish proposition ownership.
        context_start = min(self.target_end + 1, len(self.source))
        atom_rows = [{"atom_id": "sa-target", "case_id": self.case_id,
                      "source_hash": self.source_hash,
                      "span": {"start_char": 0, "end_char": self.target_end}},
                     {"atom_id": "sa-context", "case_id": self.case_id,
                      "source_hash": self.source_hash,
                      "span": {"start_char": context_start, "end_char": len(self.source)}}]
        atom_relative = f"cases/{self.case_id}/atoms.json"
        atom_path = self.atom_root / atom_relative
        atom_path.parent.mkdir(parents=True, exist_ok=True)
        atom_map = {"case_id": self.case_id, "source_hash": self.source_hash,
                    "cache_key": "c" * 64, "segmenter_version": "synthetic-v1",
                    "policy_sha256": "p" * 64, "atoms": atom_rows}
        atom_bytes = json.dumps(atom_map, separators=(",", ":")).encode("utf-8")
        atom_path.write_bytes(atom_bytes)
        return {"atom_map_relative_path": atom_relative,
                "atom_map_sha256": hashlib.sha256(atom_bytes).hexdigest(),
                "atom_map_cache_key": atom_map["cache_key"], "case_id": self.case_id,
                "source_hash": self.source_hash, "segmenter_version": "synthetic-v1",
                "policy_sha256": "p" * 64}

    def _request(self, request_id="request-1", *, target_start=None, target_end=None):
        target_start = self.target_start if target_start is None else target_start
        target_end = self.target_end if target_end is None else target_end
        refs = [{"role": "target", "start_char": target_start, "end_char": target_end,
                 "target_ids": [self.target_id]}]
        if target_end < len(self.source):
            context_start = min(target_end + 1, len(self.source) - 1)
            refs.append({"role": "context", "start_char": context_start,
                         "end_char": len(self.source), "target_ids": []})
        return {"case_id": self.case_id, "source_hash": self.source_hash,
                "request_id": request_id, "expected_target_ids": [self.target_id],
                "source_refs": refs, "atom_binding": copy.deepcopy(self.binding)}

    def au(self, *, evidence=("sa-target",), claim="The court must give reasons."):
        return {"kind": "holding", "other_kind": None, "claim": claim,
                "evidence_ref_ids": list(evidence), "speaker": "current_court",
                "attribution_role": "proposition", "needs_context": []}

    def _row(self, aus, *, decision="positive", request_id="request-1"):
        response = {"request_id": request_id, "target_id": self.target_id,
                    "decision": decision, "coverage_status": "complete", "aus": list(aus),
                    "hard_negative_reason": "fact_only" if decision == "hard_negative" else None,
                    "unresolved_reason": None}
        return {"request": self._request(request_id), "status": "protocol_verified",
                "compact_response": response}

    def _report(self, aus, *, decision="positive", request_id="request-1"):
        return {"artifact_type": "AUCompactRun", "schema_version": "au-compact-runtime-v1",
                "request_ledger": [self._row(aus, decision=decision, request_id=request_id)]}

    def _store(self, report=None, reviews=None):
        return build_store(report or self.report, self.source_store, self.atom_root, reviews=reviews)

    @staticmethod
    def _reviewer(reviewer_id="reviewer-a"):
        return {"reviewer_id": reviewer_id, "reviewer_type": "agent",
                "producer": "independent-test-fixture", "version": "1",
                "provenance": {"method": "synthetic source review",
                               "input_artifacts": ["synthetic-run"]}}

    def _au_review(self, report=None, *, entry_overrides=None, reviewer_id="reviewer-a",
                   field_witnesses=None, checks=None, primary=None):
        report = report or self.report
        au = report["request_ledger"][0]["compact_response"]["aus"][0]
        entry = {"review_type": "au", "run_sha256": run_sha256(report),
                 "request_id": report["request_ledger"][0]["request"]["request_id"],
                 "au_index": 0, "proposal_sha256": canonical_sha256(au),
                 "reason": "Each assertion checked against the exact source span.",
                 "primary_proposition": primary or {"atom_id": "sa-target",
                                                      "quote": "The court must give reasons."},
                 "field_witnesses": field_witnesses or self._field_witnesses(),
                 "material_conditions": {"status": "absent", "witnesses": []},
                 "checks": checks or self._passing_checks()}
        entry.update(entry_overrides or {})
        return {"artifact_type": "AUCandidateReview", "schema_version": "au-candidate-review-v1",
                "reviewer": self._reviewer(reviewer_id), "reviews": [entry]}

    @staticmethod
    def _passing_checks():
        return {name: "pass" for name in (
            "authority_qualification", "target_contribution", "claim_support",
            "attribution", "qualification", "duplicate")}

    @staticmethod
    def _field_witnesses():
        return {"claim": [{"atom_id": "sa-target", "quote": "The court must give reasons."}],
                "kind": [{"atom_id": "sa-target", "quote": "must"}],
                "speaker": [{"atom_id": "sa-target", "quote": "The court"}],
                "attribution_role": [{"atom_id": "sa-target", "quote": "court must"}]}

    def _candidate(self, store):
        self.assertEqual(len(store["candidates"]), 1)
        return store["candidates"][0]

    def test_primary_quote_inside_raw_target_is_accepted_even_when_marker_is_outside(self):
        review = self._au_review()
        candidate = self._candidate(self._store(reviews=[review]))
        self.assertEqual(candidate["status"], "accepted_agent_reviewed")
        self.assertTrue(candidate["ownership"]["ownership_verified"])
        primary = candidate["ownership"]["primary_proposition_span"]
        self.assertEqual(primary["quote"], "The court must give reasons.")
        self.assertGreater(primary["start_char"], 0)  # “[12] ” remains outside TARGET.
        self.assertTrue(candidate["accepted_semantic"])
        self.assertFalse(candidate["semantic_gold"])

    def test_primary_proposition_in_context_is_blocked_despite_target_evidence_padding(self):
        context_start = self.source.index("Counsel")
        target_end = self.source.index(".") + 1
        report = self._report([self.au(evidence=("sa-target", "sa-context"))])
        review = self._au_review(report, primary={"atom_id": "sa-context",
                                                  "quote": "Counsel disputes the outcome."})
        candidate = self._candidate(self._store(report, [review]))
        self.assertEqual(candidate["status"], "unresolved")
        self.assertFalse(candidate["ownership"]["ownership_verified"])
        self.assertIn("primary_quote_outside_raw_target", candidate["reasons"])
        self.assertLess(target_end, context_start + 1)

    def test_wrong_or_ambiguous_primary_quote_never_verifies_ownership(self):
        wrong = self._au_review(primary={"atom_id": "sa-target", "quote": "invented proposition"})
        wrong_candidate = self._candidate(self._store(reviews=[wrong]))
        self.assertEqual(wrong_candidate["status"], "unresolved")
        self.assertFalse(wrong_candidate["ownership"]["ownership_verified"])

        source = "[12] The court must give reasons. The court must give reasons. Counsel disputes it."
        self.binding = self._install_case(source, source.index("The court"), source.index(". Counsel") + 1)
        report = self._report([self.au()])
        ambiguous = self._au_review(report, primary={"atom_id": "sa-target",
                                                      "quote": "The court must give reasons."})
        ambiguous_candidate = self._candidate(self._store(report, [ambiguous]))
        self.assertEqual(ambiguous_candidate["status"], "unresolved")
        self.assertFalse(ambiguous_candidate["ownership"]["ownership_verified"])
        self.assertIn("witness_quote_missing_or_nonunique", ambiguous_candidate["reasons"])

    def test_each_required_field_witness_is_mandatory(self):
        fields = self._field_witnesses()
        fields.pop("speaker")
        review = self._au_review(field_witnesses=fields)
        candidate = self._candidate(self._store(reviews=[review]))
        self.assertEqual(candidate["status"], "unresolved")
        self.assertIn("field_witness_required:speaker", candidate["reasons"])
        self.assertFalse(candidate["ownership"]["ownership_verified"])

    def test_fail_in_crossfield_or_target_contribution_check_rejects_candidate(self):
        checks = self._passing_checks()
        checks["target_contribution"] = "fail"
        review = self._au_review(checks=checks,
                                 entry_overrides={"reason": "The TARGET does not contribute."})
        candidate = self._candidate(self._store(reviews=[review]))
        self.assertEqual(candidate["status"], "rejected")
        self.assertIn("target_contribution: The TARGET does not contribute.", candidate["reasons"])
        self.assertFalse(candidate["ownership"]["ownership_verified"])

    def test_stale_run_and_proposal_hash_reviews_are_not_applied(self):
        stale_run = self._au_review(entry_overrides={"run_sha256": "0" * 64})
        candidate = self._candidate(self._store(reviews=[stale_run]))
        self.assertEqual(candidate["status"], "unresolved")
        self.assertIn("stale_run_sha256", candidate["reasons"])
        self.assertFalse(candidate["ownership"]["ownership_verified"])

        stale_proposal = self._au_review(entry_overrides={"proposal_sha256": "1" * 64})
        candidate = self._candidate(self._store(reviews=[stale_proposal]))
        self.assertEqual(candidate["status"], "unresolved")
        self.assertIn("stale_proposal_sha256", candidate["reasons"])
        self.assertFalse(candidate["ownership"]["ownership_verified"])

    def test_conflicting_reviews_are_order_independent_and_never_latest_wins(self):
        passed = self._au_review(reviewer_id="reviewer-pass")
        fail_checks = self._passing_checks()
        fail_checks["claim_support"] = "fail"
        failed = self._au_review(reviewer_id="reviewer-fail", checks=fail_checks,
                                 entry_overrides={"reason": "The claim is not supported."})
        forward = self._candidate(self._store(reviews=[passed, failed]))
        reverse = self._candidate(self._store(reviews=[failed, passed]))
        self.assertEqual(forward["status"], "unresolved")
        self.assertIn("conflicting_reviews", forward["reasons"])
        self.assertEqual(forward["status"], reverse["status"])
        self.assertEqual(forward["reasons"], reverse["reasons"])
        self.assertFalse(forward["accepted_semantic"])
        self.assertFalse(reverse["accepted_semantic"])

    def test_equal_checks_and_witnesses_with_different_reasons_are_consensus(self):
        first = self._au_review(reviewer_id="reviewer-one")
        second = self._au_review(reviewer_id="reviewer-two", entry_overrides={
            "reason": "A second reviewer reached the same decision from the same quotes."})
        candidate = self._candidate(self._store(reviews=[first, second]))
        self.assertEqual(candidate["status"], "accepted_agent_reviewed")
        self.assertNotIn("conflicting_reviews", candidate["reasons"])
        self.assertEqual(len(candidate["review_provenance"]), 2)

    def test_known_other_run_with_same_request_and_au_index_does_not_bind_to_this_row(self):
        first_run = copy.deepcopy(self.report)
        second_run = copy.deepcopy(self.report)
        second_run["run_note"] = "distinct immutable run with the same request locator"
        second_run["request_ledger"][0]["compact_response"]["aus"][0]["claim"] = (
            "A different assertion shares the same request and AU index.")
        first_hash = run_sha256(first_run)
        second_hash = run_sha256(second_run)
        self.assertNotEqual(first_hash, second_hash)
        self.assertEqual(first_run["request_ledger"][0]["request"]["request_id"],
                         second_run["request_ledger"][0]["request"]["request_id"])

        first_review = self._au_review(first_run)
        store = self._store([first_run, second_run], [first_review])
        by_run = {row["provenance"]["run_sha256"][0]: row for row in store["candidates"]}
        self.assertEqual(len(by_run), 2)
        self.assertEqual(by_run[first_hash]["status"], "accepted_agent_reviewed")
        self.assertEqual(by_run[second_hash]["status"], "unresolved")
        self.assertNotIn("stale_run_sha256", by_run[second_hash]["reasons"])
        self.assertFalse(by_run[second_hash]["ownership"]["ownership_verified"])

    def test_target_negative_omission_review_is_recorded_in_ledger(self):
        source = "[12] The witness said the parcel arrived on Tuesday. Counsel disputes the outcome."
        self.binding = self._install_case(source, source.index("The witness"), source.index(".") + 1)
        report = self._report([], decision="hard_negative")
        compact = report["request_ledger"][0]["compact_response"]
        omission = {"review_type": "target_omission", "run_sha256": run_sha256(report),
                    "request_id": "request-1", "proposal_sha256": canonical_sha256(compact),
                    "reason": "No Authority Unit was omitted; the TARGET states a factual event only.",
                    "checks": {"omission": "pass"},
                    "witnesses": [{"atom_id": "sa-target", "quote": "The witness said the parcel arrived on Tuesday."}]}
        review = {"artifact_type": "AUCandidateReview", "schema_version": "au-candidate-review-v1",
                  "reviewer": self._reviewer(), "reviews": [omission]}
        store = self._store(report, [review])
        self.assertEqual(store["candidates"], [])
        ledger = store["target_ledger"][0]
        self.assertEqual(ledger["target_omission_review"], "accepted_agent_reviewed")
        self.assertEqual(ledger["omission_witnesses"][0]["quote"], "The witness said the parcel arrived on Tuesday.")
        self.assertFalse(ledger["semantic_gold"])

    def test_target_omission_fail_records_the_missed_authority_unit(self):
        report = self._report([], decision="hard_negative")
        compact = report["request_ledger"][0]["compact_response"]
        omission = {"review_type": "target_omission", "run_sha256": run_sha256(report),
                    "request_id": "request-1", "proposal_sha256": canonical_sha256(compact),
                    "reason": "The hard-negative response omitted a legal proposition in TARGET.",
                    "checks": {"omission": "fail"},
                    "witnesses": [{"atom_id": "sa-target", "quote": "The court must give reasons."}]}
        review = {"artifact_type": "AUCandidateReview", "schema_version": "au-candidate-review-v1",
                  "reviewer": self._reviewer(), "reviews": [omission]}
        store = self._store(report, [review])
        self.assertEqual(store["candidates"], [])
        ledger = store["target_ledger"][0]
        self.assertEqual(ledger["target_omission_review"], "rejected")
        self.assertIn("omission: The hard-negative response omitted a legal proposition in TARGET.",
                      ledger["omission_review_reasons"])

    def test_agent_review_never_claims_human_gold_or_host_semantic_validation(self):
        review = self._au_review()
        store = self._store(reviews=[review])
        candidate = self._candidate(store)
        self.assertEqual(candidate["status"], "accepted_agent_reviewed")
        self.assertEqual(candidate["evidence_grade"], "agent_reviewed")
        self.assertFalse(candidate["semantic_gold"])
        self.assertFalse(candidate["field_witnesses"]["claim"]["entailment_validated"])
        self.assertFalse(store["audit"]["semantic_quality_claim"])
        self.assertFalse(store["audit"]["semantic_gold"])
        encoded = json.dumps(store, ensure_ascii=False).casefold()
        self.assertNotIn('"reviewer_type": "human"', encoded)
        self.assertNotIn('"semantic_quality_claim": true', encoded)

    def test_exact_file_bytes_bind_path_run_reviews(self):
        run_path = self.root / "run.json"
        raw = json.dumps(self.report, ensure_ascii=False, indent=2).encode("utf-8")
        run_path.write_bytes(raw)
        self.assertEqual(run_sha256(run_path), hashlib.sha256(raw).hexdigest())
        review = self._au_review(entry_overrides={"run_sha256": hashlib.sha256(raw).hexdigest()})
        store = build_store(run_path, self.source_store, self.atom_root, reviews=[review])
        self.assertEqual(store["candidates"][0]["status"], "accepted_agent_reviewed")


if __name__ == "__main__":
    unittest.main()
