from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from knowledge_base.pipeline_v1.scripts.validate_plan01 import (
    DEFAULT_REPO_ROOT,
    PIPELINE_DIR,
    build_report,
    inventory_case,
    validate_annotation_schema,
    validate_hard_cases,
    validate_kos_manifest,
    validate_raw_source_manifest,
    validate_split_registry,
    write_report,
)


KOS_ROOT = Path("G:/Legal-AI/kos_sample")


class Plan01GateTests(unittest.TestCase):
    def test_selected_kos_snapshot_passes(self):
        if not KOS_ROOT.is_dir():
            self.skipTest(f"KOS snapshot unavailable: {KOS_ROOT}")
        report = build_report(KOS_ROOT)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["summary"]["selected_cases"], 5)
        self.assertEqual(report["summary"]["selected_files"], 61)
        self.assertEqual(report["checks"]["raw_source_hashes"]["status"], "pass")
        self.assertEqual(len(report["checks"]["raw_source_hashes"]["cases"]), 5)

    def test_kos_file_mutation_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "cases/013009"
            case_dir.mkdir(parents=True)
            source = case_dir / "CASE.md"
            source.write_text("role: query\n", encoding="utf-8")
            files, digest = inventory_case(case_dir)
            manifest = {
                "input_contract": {"allowed_suffixes": [".md"]},
                "cases": [
                    {
                        "case_id": "013009",
                        "kos_role": "query",
                        "case_path": "cases/013009",
                        "file_count": len(files),
                        "total_bytes": sum(item["byte_length"] for item in files),
                        "tree_sha256": digest,
                    }
                ],
            }
            source.write_text("role: changed\n", encoding="utf-8")
            errors, _ = validate_kos_manifest(root, manifest)
            self.assertTrue(any("tree_sha256_mismatch" in error for error in errors))

    def test_overlap_is_detected(self):
        registry = json.loads(
            (PIPELINE_DIR / "manifests/split_registry.v1.json").read_text(encoding="utf-8")
        )
        broken = copy.deepcopy(registry)
        broken["calibration"][0] = broken["pilot"]["train"]["short"]["development"][0]
        errors, _ = validate_split_registry(broken)
        self.assertTrue(any("leakage:" in error for error in errors))

    def test_non_reproducible_and_malformed_split_is_detected(self):
        registry = json.loads(
            (PIPELINE_DIR / "manifests/split_registry.v1.json").read_text(encoding="utf-8")
        )
        broken = copy.deepcopy(registry)
        broken["pilot"]["train"]["short"]["development"][0] = "not-a-case"
        errors, details = validate_split_registry(broken)
        self.assertTrue(any("malformed case IDs" in error for error in errors))
        self.assertTrue(any("provenance mismatch" in error for error in errors))
        self.assertFalse(details["reproduced_from_policy"])

    def test_non_string_case_id_returns_structured_failure(self):
        registry = json.loads(
            (PIPELINE_DIR / "manifests/split_registry.v1.json").read_text(encoding="utf-8")
        )
        broken = copy.deepcopy(registry)
        broken["pilot"]["train"]["short"]["development"][0] = 123
        errors, details = validate_split_registry(broken)
        self.assertTrue(any("malformed case IDs" in error for error in errors))
        self.assertEqual(details["status"], "fail")

    def test_raw_source_hash_mutation_is_detected(self):
        manifest = json.loads(
            (PIPELINE_DIR / "manifests/calibration_manifest.v1.json").read_text(encoding="utf-8")
        )
        broken = copy.deepcopy(manifest)
        broken["cases"][0]["sha256"] = "0" * 64
        errors, details = validate_raw_source_manifest(DEFAULT_REPO_ROOT, broken)
        self.assertTrue(any("sha256_mismatch" in error for error in errors))
        self.assertEqual(next(row for row in details if row["case_id"] == "013009")["status"], "fail")

    def test_schema_gate_requires_condition_and_context(self):
        schema = json.loads(
            (PIPELINE_DIR / "contracts/annotation_schema.v1.json").read_text(encoding="utf-8")
        )
        broken = copy.deepcopy(schema)
        broken["$defs"]["authorityUnit"]["required"].remove("condition_spans")
        errors = validate_annotation_schema(broken)
        self.assertTrue(any("AuthorityUnit cannot represent" in error for error in errors))

    def test_schema_gate_rejects_invalid_draft_2020_12_schema(self):
        schema = json.loads(
            (PIPELINE_DIR / "contracts/annotation_schema.v1.json").read_text(encoding="utf-8")
        )
        broken = copy.deepcopy(schema)
        broken["$defs"]["spanRef"]["type"] = "not-a-json-schema-type"
        errors = validate_annotation_schema(broken)
        self.assertTrue(any("invalid Draft 2020-12 schema" in error for error in errors))

    def test_missing_mandatory_hard_case_is_detected(self):
        catalog = json.loads((PIPELINE_DIR / "hard_cases.v1.json").read_text(encoding="utf-8"))
        broken = copy.deepcopy(catalog)
        broken["situations"] = [
            row for row in broken["situations"]
            if row["situation_id"] != "struct-bracket-year-vs-marker"
        ]
        errors = validate_hard_cases(broken)
        self.assertTrue(any("missing mandatory hard-case" in error for error in errors))

    def test_schema_and_minimal_annotation_are_draft_2020_12_valid(self):
        schema = json.loads(
            (PIPELINE_DIR / "contracts/annotation_schema.v1.json").read_text(encoding="utf-8")
        )
        example = json.loads(
            (PIPELINE_DIR / "examples/minimal_annotation.v1.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(example)

    def test_report_is_written_as_json(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested/report.json"
            report = {"status": "pass", "errors": []}
            write_report(target, report)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), report)


if __name__ == "__main__":
    unittest.main()

