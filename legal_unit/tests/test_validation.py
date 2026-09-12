from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from legal_unit.cli import _review_queue, artifact_risk_metrics, validate_artifact
from legal_unit.segmenter import segment_case
from legal_unit.validation import validate_candidates


class ValidationTests(unittest.TestCase):
    def test_rejects_marker_split(self) -> None:
        text = "A <REFERENCE_SUPPRESSED> B"
        units = segment_case("marker.txt", text, "fixture")
        units[0]["source_span"]["end_char"] = 5
        units[0]["text"] = text[:5]
        self.assertTrue(any("marker split" in issue for issue in validate_candidates(text, units, "marker.txt")))

    def test_rejects_redundant_source_span_text(self) -> None:
        text = "A complete source slice."
        units = segment_case("duplicate.txt", text, "fixture")
        units[0]["source_span"]["text"] = units[0]["text"]
        self.assertTrue(any("redundant source_span.text" in issue for issue in validate_candidates(text, units, "duplicate.txt")))

    def test_review_queue_marks_marker_and_long_structural_block_without_claiming_error(self) -> None:
        text = "<CITATION_SUPPRESSED> " + "word " * 1200
        units = segment_case("review.txt", text, "fixture")
        queue = _review_queue("review.txt", text, units)
        self.assertEqual("pending_manual_review", queue[0]["finding_status"])
        self.assertIn("contains_suppression_marker", queue[0]["review_reasons"])
        self.assertIn("very_long_structural_block", queue[0]["review_reasons"])

    def test_risk_metrics_count_only_standalone_paragraph_markers(self) -> None:
        rows = [
            {"text": "[1]\r\nParagraph.\r\n[1987] 1 S.C.R. 313"},
            {"text": "Editor: Person"},
        ]
        metrics = artifact_risk_metrics(rows)
        self.assertEqual(0, metrics["units_at_least_5_paragraph_markers"])
        self.assertEqual(1, metrics["max_paragraph_markers_in_unit"])
        self.assertEqual(1, metrics["units_containing_editor"])
        self.assertEqual(0, metrics["units_where_editor_does_not_start_block"])

    def test_artifact_validator_rejects_a_missing_manifest_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = root / "samples"
            samples.mkdir()
            (samples / "manifest.json").write_text(
                json.dumps({"samples": [{"case_id": "missing.txt"}]}), encoding="utf-8"
            )
            artifact = root / "candidates.jsonl"
            artifact.write_text("", encoding="utf-8")
            self.assertEqual(
                ["missing sample case in artifact: missing.txt"],
                validate_artifact(samples, artifact),
            )
