"""Independent offline tests for the AU claim soft-length policy.

The historical receipts are immutable protocol inputs. Passing these tests says
nothing about semantic AU quality or human gold, and no inference is performed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.au_claim_soft import core


REPO = Path(__file__).resolve().parents[1]
PARENT_ROOT = REPO / "knowledge_base/pipeline_v1/outputs/au_claim_a_local_ready_20261020"
INVALID = {
    "auc-621f4ef0ea66a5e3734aeb5d": (("aus", 0, "limits"), 250, 476),
    "auc-a9d02f74a3d246e3af135acb": (("context_request", "question"), 200, 258),
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def tree_hashes(root: Path):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


class SoftLengthValidatorTests(unittest.TestCase):
    def setUp(self):
        self.target_ref = {
            "ref_id": "ref-target", "case_id": "case-1", "source_hash": "a" * 64,
            "start_char": 10, "end_char": 30, "quote": "target evidence", "role": "target_body",
        }
        self.context_ref = {
            "ref_id": "ref-context", "case_id": "case-1", "source_hash": "a" * 64,
            "start_char": 40, "end_char": 60, "quote": "context evidence", "role": "context",
        }
        self.job = {
            "target_id": "target-1",
            "catalog": {"target_refs": {"s1": self.target_ref},
                        "context_refs": {"c1": self.context_ref}},
        }

    def response(self, claim="A claim.", limits=None, question=None, evidence=None):
        return {
            "aus": [{"claim": claim, "kind": "holding",
                     "evidence_ids": evidence or ["s1"], "limits": limits}],
            "context_request": None if question is None else {"question": question},
        }

    def test_threshold_boundaries_warn_once_and_preserve_all_text_and_evidence(self):
        for field, cap, make in (
            ("claim", 500, lambda n: self.response(claim="x" * n)),
            ("limits", 250, lambda n: self.response(limits="l" * n)),
            ("question", 200, lambda n: self.response(question="q" * n)),
        ):
            for length, expected_warnings in ((cap, 0), (cap + 1, 1)):
                with self.subTest(field=field, length=length):
                    value = make(length)
                    before = copy.deepcopy(value)
                    normalized = core.validate_response(value, self.job)
                    self.assertEqual(value, before, "validation must not mutate caller input")
                    self.assertEqual(len(normalized["warnings"]), expected_warnings)
                    if field == "claim":
                        self.assertEqual(normalized["aus"][0]["claim"], "x" * length)
                    elif field == "limits":
                        self.assertEqual(normalized["aus"][0]["limits"], "l" * length)
                    else:
                        self.assertEqual(normalized["context_request"]["question"], "q" * length)
                    self.assertEqual(normalized["aus"][0]["evidence_ids"], ["s1"])
                    self.assertEqual(normalized["aus"][0]["evidence"], [self.target_ref])
                    if expected_warnings:
                        warning = normalized["warnings"][0]
                        self.assertEqual(warning["threshold"], cap)
                        self.assertEqual(warning["actual_length"], length)
                        expected_path = {
                            "claim": ["aus", 0, "claim"],
                            "limits": ["aus", 0, "limits"],
                            "question": ["context_request", "question"],
                        }[field]
                        self.assertEqual(warning["path"], expected_path)

    def test_whitespace_is_not_truncated_and_legacy_normalization_is_explicit(self):
        raw_claim = "  " + ("word  " * 83) + "tail  "
        value = self.response(claim=raw_claim)
        raw_len = len(raw_claim)
        normalized = core.validate_response(value, self.job)
        self.assertEqual(value["aus"][0]["claim"], raw_claim)
        self.assertEqual(normalized["warnings"][0]["actual_length"], raw_len)
        self.assertEqual(normalized["aus"][0]["claim"], " ".join(raw_claim.split()))
        self.assertEqual(len(normalized["aus"][0]["claim"]), len(" ".join(raw_claim.split())))

    def test_original_protocol_gates_remain_hard_failures(self):
        invalid_values = [
            ("claim type", self.response(claim=123)),
            ("blank claim", self.response(claim=" \t\r\n")),
            ("claim surrogate", self.response(claim="bad\ud800text")),
            ("limits type", self.response(limits=12)),
            ("blank limits", self.response(limits="  ")),
            ("question type", self.response(question=12)),
            ("blank question", self.response(question=" \n")),
            ("question surrogate", self.response(question="bad\udffftext")),
            ("wrong kind", self.response()),
            ("bad evidence id", self.response(evidence=["s-does-not-exist"])),
            ("context-only evidence", self.response(evidence=["c1"])),
            ("wrong top-level shape", {"aus": [], "context_request": None, "extra": True}),
        ]
        invalid_values[8][1]["aus"][0]["kind"] = "made_up"
        for label, value in invalid_values:
            with self.subTest(failure=label), self.assertRaises((ValueError, TypeError, KeyError)):
                core.validate_response(value, self.job)


class HistoricalImportTests(unittest.TestCase):
    def test_import_revalidates_original_a16_and_writes_complete_offline_report(self):
        original_hashes = tree_hashes(PARENT_ROOT)
        with tempfile.TemporaryDirectory(prefix="au-claim-soft-import-") as tmp:
            output_root = Path(tmp) / "new-import"
            report = core.import_run(PARENT_ROOT, output_root)
            saved = read_json(output_root / "report.json")

            self.assertEqual(report, saved)
            self.assertEqual(report["target_count"], 16)
            self.assertEqual(report["receipt_count"], 16)
            self.assertEqual(report["protocol_verified"], 16)
            self.assertEqual(report["protocol_invalid"], 0)
            self.assertTrue(report["protocol_complete"])
            self.assertEqual(report["warning_count"], 2)
            self.assertEqual(len(report["warnings"]), 2)
            self.assertEqual(report["needs_context"], 1)
            self.assertEqual(report["context_continuation"], "separate_workflow_pending")
            self.assertEqual(report["new_accounting"]["logical_requests"], 0)
            self.assertEqual(report["new_accounting"]["provider_POST_attempts"], 0)
            self.assertEqual(report["new_accounting"]["transport_POST_attempts"], 0)
            self.assertEqual(report["network_requests"], 0)
            self.assertFalse(report["network_executed"])
            self.assertEqual(report["semantic_quality"], "not_assessed")

            by_id = {row["original_request_id"]: row for row in report["results"]}
            self.assertEqual(len(by_id), 16)
            self.assertEqual(sum(not row["warnings"] for row in report["results"]), 14)
            self.assertEqual(sum(bool(row["warnings"]) for row in report["results"]), 2)
            for request_id, (path, threshold, actual) in INVALID.items():
                with self.subTest(request_id=request_id):
                    row = by_id[request_id]
                    self.assertEqual(row["protocol_status"], "verified")
                    self.assertEqual(row["status"],
                                     "needs_context" if row["needs_context"] else "draft_ready")
                    self.assertEqual(len(row["warnings"]), 1)
                    self.assertEqual(row["warnings"][0], {
                        "code": "length_threshold_exceeded", "severity": "warning",
                        "path": list(path), "threshold": threshold, "actual_length": actual,
                    })
                    # Receipt/model output retain the complete original generation,
                    # including its whitespace; normalization lives in output.
                    receipt_path = PARENT_ROOT / "live/receipts" / f"{request_id}.json"
                    receipt = read_json(receipt_path)
                    self.assertEqual(row["raw_response"], receipt["raw_response"])
                    original_value = json.loads(
                        receipt["raw_response"]["choices"][0]["message"]["content"]
                    )
                    self.assertEqual(row["model_output"], original_value)
                    self.assertEqual(row["output"]["warnings"], row["warnings"])

            needs_rows = [row for row in report["results"] if row["needs_context"]]
            self.assertEqual(len(needs_rows), 1)
            self.assertEqual(needs_rows[0]["context_status"], "pending")
            self.assertEqual(tree_hashes(PARENT_ROOT), original_hashes,
                             "historical source, ledger, receipts and report must remain unchanged")

    def test_import_refuses_existing_output_root_without_overwriting_it(self):
        with tempfile.TemporaryDirectory(prefix="au-claim-soft-no-overwrite-") as tmp:
            output_root = Path(tmp) / "already-exists"
            output_root.mkdir()
            marker = output_root / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            before = tree_hashes(output_root)
            with self.assertRaises((ValueError, TypeError, KeyError)):
                core.import_run(PARENT_ROOT, output_root)
            self.assertEqual(tree_hashes(output_root), before)
            self.assertFalse((output_root / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
