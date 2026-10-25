"""Independent contract tests for the selective-reading H/P comparator.

All predictions below are synthetic. The locked historical outputs are only
comparison references and are deliberately not loaded for selection.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.selective_comparison.core import compare
from knowledge_base.pipeline_v1.milestone1.core import digest


def _compact(request_id: str, *, positive: bool, quote: str = "Exact synthetic evidence."):
    if not positive:
        return {
            "request_id": request_id,
            "decision": "hard_negative",
            "coverage_status": "complete",
            "aus": [],
        }
    return {
        "request_id": request_id,
        "decision": "positive",
        "coverage_status": "complete",
        "aus": [{"claim": "Synthetic legal proposition.", "evidence_quote": quote}],
    }


def _wire_unresolved(request_id: str):
    return {"request_id": request_id, "decision": "unresolved",
            "coverage_status": "needs_split", "aus": [],
            "hard_negative_reason": None, "unresolved_reason": "other"}


def _normalized(positive: bool, *, claim: str = "Synthetic legal proposition.", span=(1, 8)):
    return {"target_results": [{"authority_units": ([{
        "local_au_id": "new-id",
        "claim": claim,
        "evidence_spans": [{"start_char": span[0], "end_char": span[1]}],
        "status": "semantic_review_pending",
    }] if positive else [])}]}


def _inputs():
    originals = [
        {"request_id": f"orig-{i:02d}", "case_id": f"case-{i // 6}",
         "source_hash": f"source-hash-{i // 6}",
         "expected_target_ids": [f"target-{i:02d}"],
         "source_refs": [{"role": "target", "start_char": i * 20,
                          "end_char": i * 20 + 10, "target_ids": [f"target-{i:02d}"]}]}
        for i in range(30)
    ]
    parent_bulk = {"version": "bulk-au-execution-v1", "workload_id": "reference-lock",
                   "parent": {"requests": originals}}
    # The comparator accepts the actual bulk parent envelope; in this
    # synthetic fixture the parent must also be canonical for its digest.
    from knowledge_base.pipeline_v1.bulk_execution.core import build_manifest as build_bulk_manifest
    parent_bulk = build_bulk_manifest(parent_bulk["parent"], workload_id="reference-lock")
    manifest = {"parent": parent_bulk, "parent_sha256": digest(parent_bulk),
                "model": "Qwen/Qwen3.5-9B"}
    baseline_rows = []
    for i, original in enumerate(originals):
        baseline_rows.append({
            "original_request": original,
            "status": "protocol_verified",
            "compact_response": _compact(original["request_id"], positive=i in {0, 7, 14, 21, 28}),
            "response": _normalized(i in {0, 7, 14, 21, 28}),
            "receipt": {"usage": {"input_tokens": 100, "output_tokens": 12}},
        })
    baseline = {"identity": {"manifest_sha256": digest(parent_bulk)}, "status": "complete",
                "performance_eligible": True, "usage_unavailable": 0,
                "request_ledger": baseline_rows,
                "tokens": {"input_tokens": 3000, "output_tokens": 360, "total_tokens": 3360},
                "warmup": {"attempts": [{"usage": {"total_tokens": 11}}]}}

    def arm(name: str):
        ids = [f"orig-{i:02d}" for i in range(0, 30, 2)]
        rows = []
        for i, rid in enumerate(ids):
            original = originals[int(rid[-2:])]
            # A selected request with a provider failure has no assessment.
            status = "unresolved" if i == 2 else "protocol_verified"
            wire_unresolved = i == 3
            rows.append({
                "original_request": original,
                "status": status,
                "compact_response": (None if status != "protocol_verified" else
                                     _wire_unresolved(rid) if wire_unresolved else
                                     _compact(rid, positive=int(rid[-2:]) == 0)),
                "response": None if status != "protocol_verified" else
                    _normalized(int(rid[-2:]) == 0),
                "receipt": {"usage": {"input_tokens": 80, "output_tokens": 9},
                            "failure_diagnostic": ({"kind": "provider_error"}
                                                   if status != "protocol_verified" else None)},
            })
        return {
            "arm": name,
            "manifest_sha256": digest(manifest),
            "model": manifest["model"],
            "status": "incomplete",
            "original_request_ids": [r["request_id"] for r in originals],
            "selected_request_ids": ids,
            "assessed_request_ids": [r["original_request"]["request_id"] for r in rows
                                     if r["status"] == "protocol_verified" and
                                     not (r["compact_response"] or {}).get("decision") == "unresolved"],
            "protocol_verified_request_ids": [r["original_request"]["request_id"] for r in rows
                                              if r["status"] == "protocol_verified"],
            "unselected_request_ids": [f"orig-{i:02d}" for i in range(1, 30, 2)],
            "universe_sha256": digest(originals),
            "tokens": {"input_tokens": 1200, "output_tokens": 135,
                       "total_tokens": 1335,
                       "planner_input_tokens": 400, "planner_output_tokens": 45,
                       "extraction_input_tokens": 800, "extraction_output_tokens": 90},
            "usage_unavailable": 1,
            "request_ledger": rows,
            "performance_eligible": False,
            "resume_or_recovered_receipt": True,
            "execution_status": "incomplete",
            "selective_pass": False,
            "semantic_quality_claim": False,
            "warmup": {"attempts": [{"usage": {"total_tokens": 7}}]},
        }

    return manifest, baseline, {"H": arm("H"), "P": arm("P")}, originals


class SelectiveComparisonTests(unittest.TestCase):
    def test_uses_locked_30_target_universe_and_reports_reference_omissions(self):
        manifest, baseline, arms, originals = _inputs()
        with tempfile.TemporaryDirectory() as temp:
            report = compare(manifest, baseline, arms, Path(temp))

        self.assertEqual(report["universe_sha256"], digest(originals))
        self.assertEqual(report["targets"], 30)
        self.assertFalse(report["reference_is_gold"])
        for arm_name in ("H", "P"):
            arm_report = report["arms"][arm_name]
            omitted = arm_report["reference_positive_targets_unselected"]
            # The unselected positive reference at 7 is an omission signal,
            # never a claim about true AU recall or gold.
            self.assertEqual(omitted, 2)
            self.assertFalse(arm_report["semantic_quality_claim"])
            self.assertFalse(arm_report["quality_equivalence_claim"])
            self.assertIn("NOT true AU recall", arm_report["retention_note"])
        self.assertFalse(report["semantic_quality_claim"])

    def test_selected_failure_is_not_assessed_and_unknown_resume_is_no_savings(self):
        manifest, baseline, arms, _ = _inputs()
        with tempfile.TemporaryDirectory() as temp:
            report = compare(manifest, baseline, arms, Path(temp))

        for arm in ("H", "P"):
            arm_report = report["arms"][arm]
            self.assertEqual(arm_report["targets_assessed"], 13)
            self.assertFalse(arm_report["fresh_operational_comparison_eligible"])
            self.assertIsNone(arm_report["observed_token_reduction_percent"])
            row = next(row for row in report["pairs"][arm]
                       if row["original_request_id"] == "orig-04")
            self.assertEqual(row["state"], "unresolved")
            self.assertFalse(row["assessed"])
            semantic_unresolved = next(r for r in report["pairs"][arm]
                                       if r["original_request_id"] == "orig-06")
            self.assertEqual(semantic_unresolved["state"], "unresolved")
            self.assertFalse(semantic_unresolved["assessed"])

    def test_combined_planner_and_extraction_tokens_are_counted(self):
        manifest, baseline, arms, _ = _inputs()
        p = arms["P"]
        p["tokens"]["input_tokens"] = 1200
        p["tokens"]["planner_input_tokens"] = 400
        p["tokens"]["extraction_input_tokens"] = 800
        with tempfile.TemporaryDirectory() as temp:
            report = compare(manifest, baseline, arms, Path(temp))

        p_report = report["arms"]["P"]
        self.assertEqual(p_report["tokens_including_planner"]["total_tokens"], 1335)
        self.assertEqual(p_report["reported_tokens_including_client_warmup"], 1342)
        self.assertEqual(p_report["tokens_including_planner"]["planner_input_tokens"] +
                         p_report["tokens_including_planner"]["extraction_input_tokens"], 1200)

    def test_complete_but_reused_arm_cannot_claim_token_reduction(self):
        manifest, baseline, arms, _ = _inputs()
        for arm in arms.values():
            for row in arm["request_ledger"]:
                rid = row["original_request"]["request_id"]
                row["status"] = "protocol_verified"
                row["compact_response"] = _compact(rid, positive=False)
                row["response"] = _normalized(False)
                row["receipt"].pop("failure_diagnostic", None)
            arm["assessed_request_ids"] = list(arm["selected_request_ids"])
            arm["protocol_verified_request_ids"] = list(arm["selected_request_ids"])
            arm["status"] = "complete"
            arm["performance_eligible"] = False  # Cached/resumed receipt, not fresh speed evidence.
            arm["usage_unavailable"] = 0
        with tempfile.TemporaryDirectory() as temp:
            report = compare(manifest, baseline, arms, Path(temp))

        for arm_report in report["arms"].values():
            self.assertEqual(arm_report["targets_assessed"], 15)
            self.assertFalse(arm_report["fresh_operational_comparison_eligible"])
            self.assertIsNone(arm_report["observed_token_reduction_percent"])

    def test_exact_evidence_and_exact_content_are_distinct_nonsemantic_signals(self):
        manifest, baseline, arms, _ = _inputs()
        for arm in arms.values():
            row = next(r for r in arm["request_ledger"]
                       if r["original_request"]["request_id"] == "orig-00")
            row["response"]["target_results"][0]["authority_units"][0]["claim"] = "Changed wording."
        with tempfile.TemporaryDirectory() as temp:
            report = compare(manifest, baseline, arms, Path(temp))

        for arm in ("H", "P"):
            row = next(r for r in report["pairs"][arm]
                       if r["original_request_id"] == "orig-00")
            self.assertEqual(row["exact_evidence_matches"], 1)
            self.assertEqual(row["exact_content_matches"], 0)
        self.assertFalse(report["semantic_quality_claim"])

    def test_local_au_ids_do_not_change_exact_content_signature(self):
        manifest, baseline, arms, _ = _inputs()
        for arm in arms.values():
            au = next(r for r in arm["request_ledger"]
                      if r["original_request"]["request_id"] == "orig-00")["response"][
                          "target_results"][0]["authority_units"][0]
            au["local_au_id"] = "different-per-arm-id"
        with tempfile.TemporaryDirectory() as temp:
            report = compare(manifest, baseline, arms, Path(temp))

        for arm in ("H", "P"):
            row = next(r for r in report["pairs"][arm]
                       if r["original_request_id"] == "orig-00")
            self.assertEqual(row["exact_content_matches"], 1)

    def test_rejects_source_mismatch_duplicate_selected_and_failure_marked_assessed(self):
        manifest, baseline, arms, _ = _inputs()
        variants = []

        wrong_source = copy.deepcopy(arms)
        wrong_source["H"]["request_ledger"][0]["original_request"]["source_hash"] = "other-source"
        variants.append((wrong_source, "comparison_source_request_mismatch"))

        duplicate_selected = copy.deepcopy(arms)
        duplicate_selected["P"]["selected_request_ids"].append(
            duplicate_selected["P"]["selected_request_ids"][0])
        variants.append((duplicate_selected, "comparison_selection_invalid"))

        failed_marked_assessed = copy.deepcopy(arms)
        failed_marked_assessed["H"]["assessed_request_ids"].append("orig-04")
        variants.append((failed_marked_assessed, "comparison_assessment_ledger_mismatch"))

        duplicate_ledger = copy.deepcopy(arms)
        duplicate_ledger["H"]["request_ledger"].append(
            copy.deepcopy(duplicate_ledger["H"]["request_ledger"][0]))
        variants.append((duplicate_ledger, "comparison_duplicate_assessment"))

        for broken, expected in variants:
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as temp:
                    with self.assertRaisesRegex(ValueError, expected):
                        compare(manifest, baseline, broken, Path(temp))

    def test_rejects_universe_targetset_and_stale_parent_mismatch(self):
        mutations = []

        manifest, baseline, arms, _ = _inputs()
        bad = copy.deepcopy(arms)
        bad["P"]["original_request_ids"].pop()
        mutations.append((manifest, baseline, bad))

        manifest2, baseline2, arms2, _ = _inputs()
        bad2 = copy.deepcopy(arms2)
        bad2["H"]["universe_sha256"] = "0" * 64
        mutations.append((manifest2, baseline2, bad2))

        manifest3, baseline3, arms3, _ = _inputs()
        bad_manifest = copy.deepcopy(manifest3)
        bad_manifest["parent"]["parent"]["requests"][0]["request_id"] = "changed"
        mutations.append((bad_manifest, baseline3, arms3))

        for manifest, baseline, arms in mutations:
            with self.subTest(manifest=manifest["parent"]["parent"]["requests"][0]["request_id"]):
                with tempfile.TemporaryDirectory() as temp:
                    with self.assertRaises((ValueError, KeyError)):
                        compare(manifest, baseline, arms, Path(temp))

    def test_rejects_wrong_manifest_fingerprint_and_wrong_model(self):
        manifest, baseline, arms, _ = _inputs()
        wrong_manifest = copy.deepcopy(arms)
        wrong_manifest["P"]["manifest_sha256"] = "0" * 64
        wrong_model = copy.deepcopy(arms)
        wrong_model["H"]["model"] = "different/model"

        for broken in (wrong_manifest, wrong_model):
            with self.subTest(report=broken["H" if broken is wrong_model else "P"]):
                with tempfile.TemporaryDirectory() as temp:
                    with self.assertRaisesRegex(ValueError, "comparison_run_identity_mismatch"):
                        compare(manifest, baseline, broken, Path(temp))


if __name__ == "__main__":
    unittest.main()
