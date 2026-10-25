"""Independent local checks for KOS comparison boundaries and failure paths."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.kos_comparison import ComparisonError, align_evidence, compare
from knowledge_base.pipeline_v1.kos_comparison.comparison import _render_html
from knowledge_base.pipeline_v1.source_contract.store import open_source


PIPELINE = Path(__file__).resolve().parents[1]
FULL_MANIFEST = PIPELINE / "manifests/au_compact_kos5_full_m1.v1.json"
KOS_MANIFEST = PIPELINE / "manifests/selected_kos_manifest.v1.json"
SOURCE_STORE = PIPELINE / "outputs/source_store_v1"
KOS_ROOT = Path("G:/Legal-AI/kos_sample")
LEGACY_RUN = PIPELINE / "outputs/au_compact_kos5_20261010_231423/run.json"
ATOM_ROOT = PIPELINE / "outputs/plan04_sentence_atoms_v1"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class KOSComparisonIndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = (FULL_MANIFEST, KOS_MANIFEST,
                    SOURCE_STORE / "source_store_manifest.json", KOS_ROOT / "cases")
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise RuntimeError("KOS comparison real fixture inputs missing: " + ", ".join(missing))
        cls.workload = read_json(FULL_MANIFEST)

    def compare_single_legacy_row(self, row, temporary):
        root = Path(temporary)
        input_root = root / "input"
        input_root.mkdir()
        run_path = input_root / "run.json"
        write_json(run_path, {"artifact_type": "AUCompactRun", "status": "incomplete",
                             "request_ledger": [row]})
        return compare(run_path, source_store=SOURCE_STORE, kos_root=KOS_ROOT,
            kos_manifest=KOS_MANIFEST, atom_root=ATOM_ROOT,
            output_root=root / "comparison")

    def test_repeated_exact_quote_is_ambiguous_and_whitespace_alignment_is_explicit(self):
        repeated = align_evidence("same phrase", "same phrase. other. same phrase")
        self.assertEqual(repeated["status"], "ambiguous")
        self.assertEqual([s["start_char"] for s in repeated["spans"]], [0, 20])
        normalized = align_evidence("one\t two", "prefix one  two suffix")
        self.assertEqual(normalized["status"], "whitespace_normalized")
        self.assertEqual(len(normalized["spans"]), 1)
        self.assertEqual(normalized["spans"][0]["quote"], "one  two")
        entity = align_evidence("<tag>", "&lt;tag&gt;")
        self.assertEqual(entity["status"], "no_match",
                         "comparison must not silently HTML-decode source evidence")

    def test_partial_failed_run_is_unresolved_and_preserves_receipt_without_gold_fn(self):
        request = copy.deepcopy(self.workload["requests"][0])
        one_request_workload = {**self.workload, "requests": [request]}
        run = {
            "artifact_type": "AUCompactRun",
            "status": "incomplete",
            "pending_request_ids": [request["request_id"]],
            "selection_request_ids": [request["request_id"]],
            "runtime_ledger": {"provider_attempts": 1, "input_tokens": 17,
                               "output_tokens": 3, "latency_ms": 41},
            "request_ledger": [{
                "request": request,
                "status": "provider_error",
                "response": None,
                "receipt": {"usage": {"input_tokens": 17, "output_tokens": 3,
                                        "total_tokens": 20},
                            "usage_state": "provider", "latency_ms": 41},
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "inputs"
            root.mkdir()
            run_path = root / "run.json"
            workload_path = root / "workload.json"
            output_root = Path(temporary) / "comparison"
            write_json(run_path, run)
            write_json(workload_path, one_request_workload)
            report = compare(run_path, source_store=SOURCE_STORE, kos_root=KOS_ROOT,
                kos_manifest=KOS_MANIFEST, output_root=output_root,
                workload_manifest=workload_path)
            self.assertFalse(report["semantic_gold"])
            self.assertFalse(report["semantic_quality_claim"])
            self.assertFalse(report["equivalence_claim"])
            self.assertFalse(report["coverage"]["expected_workload_complete"])
            self.assertEqual(report["coverage"]["target_status_counts"],
                             {"invalid_or_unresolved": 1})
            self.assertIsNone(report["targets"][0]["decision"])
            self.assertEqual(report["cost"]["current_receipts"][0]["receipt"]["usage"]["total_tokens"], 20)
            self.assertEqual(report["cost"]["observed_receipt_latency_ms"], 41)
            self.assertIsNone(report["cost"]["currency_cost"])
            self.assertEqual(report["cost"]["currency_cost_status"], "pricing_not_supplied")
            self.assertNotIn("missing_reference_in_covered_evidence",
                             [row["comparison_status"] for row in report["kos_units"]])
            self.assertTrue((output_root / "comparison.json").is_file())
            self.assertTrue((output_root / "comparison.html").is_file())

    def test_bound_atom_catalog_accepts_legacy_three_au_smoke_and_rejects_out_of_catalog_evidence(self):
        legacy = read_json(LEGACY_RUN)
        row = next(row for row in legacy["request_ledger"]
                   if row.get("status") == "protocol_verified"
                   and sum(len(target["authority_units"])
                           for target in row["response"]["target_results"]) == 3)
        request = row["request"]
        run = {**legacy, "request_ledger": [copy.deepcopy(row)]}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_root = root / "input"
            input_root.mkdir()
            run_path = input_root / "legacy-three-au.json"
            write_json(run_path, run)
            accepted = compare(run_path, source_store=SOURCE_STORE, kos_root=KOS_ROOT,
                kos_manifest=KOS_MANIFEST, atom_root=ATOM_ROOT,
                output_root=root / "accepted")
            self.assertEqual(accepted["counts"]["validated_model_au_count"], 3)
            self.assertEqual(len(accepted["model_units"]), 3)
            self.assertEqual(accepted["request_states"][0]["validation_errors"], [])
            self.assertEqual(accepted["request_states"][0]["evidence_scope"]["status"],
                             "bound_atom_catalog_verified")

            # Extend one valid, target-overlapping quote by one character beyond
            # the independently reconstructed whole-atom read catalog.
            atom_path = ATOM_ROOT / request["atom_binding"]["atom_map_relative_path"]
            atom_map = read_json(atom_path)
            refs = request["source_refs"]
            catalog_atoms = [atom["span"] for atom in atom_map["atoms"]
                if any(atom["span"]["start_char"] < ref["end_char"]
                       and ref["start_char"] < atom["span"]["end_char"] for ref in refs)]
            catalog_end = max(span["end_char"] for span in catalog_atoms)
            source = open_source(SOURCE_STORE, request["case_id"], request["source_hash"])
            target_ref = next(ref for ref in refs if ref["role"] == "target")
            first_au = run["request_ledger"][0]["response"]["target_results"][0]["authority_units"][0]
            old_span = first_au["evidence_spans"][0]
            outside_span = {"start_char": old_span["start_char"],
                "end_char": catalog_end + 1,
                "quote": source[old_span["start_char"]:catalog_end + 1]}
            self.assertLess(outside_span["start_char"], target_ref["end_char"])
            self.assertGreater(outside_span["end_char"], catalog_end)
            first_au["evidence_spans"][0] = outside_span
            write_json(run_path, run)

            rejected = compare(run_path, source_store=SOURCE_STORE, kos_root=KOS_ROOT,
                kos_manifest=KOS_MANIFEST, atom_root=ATOM_ROOT,
                output_root=root / "rejected")
            errors = rejected["request_states"][0]["validation_errors"]
            self.assertIn("normalized_evidence_outside_supplied_catalog", errors)
            self.assertNotIn("normalized_au_evidence_is_context_only_or_wrong_target", errors,
                "the rejected evidence still overlaps its target-owned raw span")
            self.assertEqual(rejected["counts"]["validated_model_au_count"], 0)

    def test_nonempty_list_compact_response_does_not_crash_needs_split_inspection(self):
        legacy = read_json(LEGACY_RUN)
        row = next(copy.deepcopy(row) for row in legacy["request_ledger"]
                   if row.get("status") == "protocol_verified"
                   and sum(len(target["authority_units"])
                           for target in row["response"]["target_results"]) == 3)
        row["compact_response"] = ["unparsed raw payload"]
        with tempfile.TemporaryDirectory() as temporary:
            report = self.compare_single_legacy_row(row, temporary)
        self.assertEqual(report["request_states"][0]["validation_errors"], [])
        self.assertFalse(report["request_states"][0]["needs_split"])
        self.assertEqual(report["counts"]["validated_model_au_count"], 3)

    def test_invalid_normalized_target_results_are_reported_per_row_not_crash_compare(self):
        legacy = read_json(LEGACY_RUN)
        row = next(copy.deepcopy(row) for row in legacy["request_ledger"]
                   if row.get("status") == "protocol_verified"
                   and sum(len(target["authority_units"])
                           for target in row["response"]["target_results"]) == 3)
        row["response"]["target_results"] = [{}]
        with tempfile.TemporaryDirectory() as temporary:
            report = self.compare_single_legacy_row(row, temporary)
        errors = report["request_states"][0]["validation_errors"]
        self.assertTrue(errors, "malformed normalized output must carry protocol/schema errors")
        self.assertEqual(report["coverage"]["target_status_counts"],
                         {"invalid_or_unresolved": 1})
        self.assertEqual(report["counts"]["validated_model_au_count"], 0)

    def test_duplicate_run_request_identity_is_rejected(self):
        request = copy.deepcopy(self.workload["requests"][0])
        run = {"artifact_type": "AUCompactRun", "request_ledger": [
            {"request": request, "status": "failed"},
            {"request": request, "status": "failed"},
        ]}
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run.json"
            write_json(run_path, run)
            with self.assertRaisesRegex(ComparisonError, "duplicate run request ID"):
                compare(run_path, source_store=SOURCE_STORE, kos_root=KOS_ROOT,
                        kos_manifest=KOS_MANIFEST)

    def test_html_report_escapes_untrusted_kos_content(self):
        payload = '<script>alert("x")</script> & "quoted"'
        report = {
            "counts": {}, "coverage": {}, "sources": [], "inputs": {}, "cost": {},
            "kos_parse_errors": [{"error": payload}], "request_states": [],
            "split_merge_candidates": [], "kos_units": [], "model_units": [],
            "targets": [], "limitations": [payload],
        }
        rendered = _render_html(report)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&amp;", rendered)
        self.assertIn("&quot;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn(payload, rendered)


if __name__ == "__main__":
    unittest.main()
