from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from knowledge_base.pipeline_v1.scripts.validate_plan01 import (
    PIPELINE_DIR,
    build_report,
    validate_annotation_schema,
    validate_hard_cases,
    validate_split_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
KOS_ROOT = Path("G:/Legal-AI/kos_sample")


def _load(relative: str) -> dict:
    return json.loads((PIPELINE_DIR / relative).read_text(encoding="utf-8"))


class Plan01IndependentEvaluation(unittest.TestCase):
    """Independent contract and fault-injection checks for Plan 01.

    A failure in a negative check means the production gate accepted a state
    that violates the locked Plan 01 contract.
    """

    def test_current_raw_kos5_sources_match_calibration_manifest(self):
        manifest = _load("manifests/calibration_manifest.v1.json")
        self.assertEqual(manifest["workload"], "KOS-5")
        self.assertEqual(len(manifest["cases"]), 5)
        for row in manifest["cases"]:
            source = REPO_ROOT / row["source_path"]
            raw = source.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"])
            self.assertEqual(len(raw), row["byte_length"])
            self.assertEqual(len(raw.decode("utf-8-sig")), row["char_length"])

    def test_current_annotation_schema_and_fixture_are_valid(self):
        schema = _load("contracts/annotation_schema.v1.json")
        fixture = _load("examples/minimal_annotation.v1.json")
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(fixture)

    def test_plan01_gate_must_report_raw_source_hash_check(self):
        report = build_report(KOS_ROOT)
        self.assertEqual(report["status"], "pass")
        inputs = report.get("inputs", {})
        checks = report.get("checks", {})
        self.assertIn(
            "calibration_manifest",
            inputs,
            "Plan 01 gate never loads the canonical raw-source manifest",
        )
        self.assertIn(
            "raw_source_hashes",
            checks,
            "Plan 01 PASS does not establish that the five raw sources match their hashes",
        )

    def test_split_gate_rejects_assignment_not_derived_from_locked_policy(self):
        registry = _load("manifests/split_registry.v1.json")
        broken = copy.deepcopy(registry)
        broken["pilot"]["train"]["short"]["development"][0] = "888888"
        errors, _ = validate_split_registry(broken)
        self.assertTrue(
            errors,
            "A same-size, non-overlapping but non-reproducible split assignment was accepted",
        )

    def test_split_gate_rejects_malformed_case_id(self):
        registry = _load("manifests/split_registry.v1.json")
        broken = copy.deepcopy(registry)
        broken["pilot"]["train"]["short"]["development"][0] = "not-a-case"
        errors, _ = validate_split_registry(broken)
        self.assertTrue(errors, "Malformed case IDs were accepted by the split gate")

    def test_schema_gate_rejects_invalid_json_schema(self):
        schema = _load("contracts/annotation_schema.v1.json")
        broken = copy.deepcopy(schema)
        broken["$defs"]["spanRef"]["type"] = "not-a-json-schema-type"
        with self.assertRaises(Exception):
            Draft202012Validator.check_schema(broken)
        errors = validate_annotation_schema(broken)
        self.assertTrue(errors, "The Plan 01 gate accepted an invalid Draft 2020-12 schema")

    def test_hard_case_gate_rejects_missing_mandatory_scenario(self):
        catalog = _load("hard_cases.v1.json")
        broken = copy.deepcopy(catalog)
        broken["situations"] = [
            row
            for row in broken["situations"]
            if row["situation_id"] != "struct-bracket-year-vs-marker"
        ]
        broken["situations"].append(
            {
                "situation_id": "placeholder-not-a-mandatory-scenario",
                "class": "structure",
                "description": "Count-preserving placeholder.",
                "candidate_cases": [],
                "basis": "fault injection",
                "required_labels": [],
            }
        )
        errors = validate_hard_cases(broken)
        self.assertTrue(errors, "A mandatory hard-case scenario can be silently replaced")


if __name__ == "__main__":
    unittest.main()
