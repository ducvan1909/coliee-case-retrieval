from __future__ import annotations

import hashlib
import json
import copy
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.structural_prepass import (
    EVENT_SPECS,
    StructuralPrepassError,
    parser_event_for,
    parse_source,
    validate_block_map,
)


PIPELINE_DIR = Path(__file__).resolve().parents[1]
POLICY_PATH = PIPELINE_DIR / "policies/sourceblock_policy.v1.json"


class Plan03StructuralPrepassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def parse(self, text: str, *, case_id: str = "000001", parser_version: str | None = None):
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return parse_source(
            text=text,
            case_id=case_id,
            source_hash=source_hash,
            policy=self.policy,
            parser_version=parser_version,
        )

    def test_bracket_year_and_citation_are_not_paragraph_markers(self):
        text = "Temp. Cite: [1987] 1 S.C.R. 2\n[1234]\n[12] Actual paragraph.\n"
        block_map = self.parse(text)
        numbered = [block for block in block_map["blocks"] if block["block_type"] == "numbered_paragraph"]
        self.assertEqual(len(numbered), 1)
        self.assertEqual(text[numbered[0]["marker_span"]["start_char"] : numbered[0]["marker_span"]["end_char"]], "[12]")
        self.assertTrue(any(nested["span_type"] == "citation_year" for block in block_map["blocks"] for nested in block["nested_spans"]))

    def test_heading_is_candidate_and_complete_short_sentence_is_not(self):
        block_map = self.parse("I. STANDARD OF REVIEW\nThis is a short sentence.\n")
        self.assertEqual(block_map["blocks"][0]["block_type"], "heading_candidate")
        self.assertTrue(block_map["blocks"][0]["heading_candidate"])
        self.assertNotEqual(block_map["blocks"][1]["block_type"], "heading_candidate")
        self.assertFalse(block_map["blocks"][1]["heading_candidate"])

    def test_quote_and_list_inside_numbered_paragraph_are_nested_not_children(self):
        text = '[7]\nThe court stated "the governing test".\n(a) first factor\nContinuation.\n[8]\nNext.\n'
        block_map = self.parse(text)
        first = block_map["blocks"][0]
        self.assertEqual(first["block_type"], "numbered_paragraph")
        self.assertEqual(block_map["blocks"][1]["block_type"], "numbered_paragraph")
        self.assertIn("list_marker", {item["span_type"] for item in first["nested_spans"]})
        self.assertIn("quotation_candidate", {item["span_type"] for item in first["nested_spans"]})
        self.assertEqual(len(block_map["blocks"]), 2)

    def test_bom_whitespace_and_mixed_newlines_round_trip_exactly(self):
        text = "\ufeff  \r\n\r\n[1]\rBody\n\n"
        block_map = self.parse(text)
        checks = validate_block_map(block_map, text)
        self.assertTrue(all(checks.values()))
        reconstructed = "".join(text[b["span"]["start_char"] : b["span"]["end_char"]] for b in block_map["blocks"])
        self.assertEqual(reconstructed, text)

    def test_parse_and_ids_are_stable(self):
        text = "INTRODUCTION\n[1]\nText.\n"
        self.assertEqual(self.parse(text), self.parse(text))

    def test_source_or_parser_version_changes_cache_and_ids(self):
        original = self.parse("[1]\nText.\n", parser_version="parser-a")
        changed_source = self.parse("[1]\nText changed.\n", parser_version="parser-a")
        changed_parser = self.parse("[1]\nText.\n", parser_version="parser-b")
        self.assertNotEqual(original["cache_key"], changed_source["cache_key"])
        self.assertNotEqual(original["cache_key"], changed_parser["cache_key"])
        self.assertNotEqual(original["blocks"][0]["block_id"], changed_source["blocks"][0]["block_id"])
        self.assertNotEqual(original["blocks"][0]["block_id"], changed_parser["blocks"][0]["block_id"])

    def test_each_cache_block_and_span_identity_mutation_is_rejected(self):
        text = "[1]\nText.\n"
        original = self.parse(text)
        mutations = {
            "cache_key": lambda value: value.update(cache_key="0" * 64),
            "block_id": lambda value: value["blocks"][0].update(block_id="sb-" + "0" * 24),
            "block_parser_version": lambda value: value["blocks"][0].update(parser_version="forged"),
            "block_policy_sha256": lambda value: value["blocks"][0].update(policy_sha256="0" * 64),
            "span_case_id": lambda value: value["blocks"][0]["span"].update(case_id="999999"),
            "content_source_hash": lambda value: value["blocks"][0]["content_span"].update(source_hash="0" * 64),
            "nested_producer_version": lambda value: value["blocks"][0]["nested_spans"].append({
                "span_type": "citation_candidate",
                "span": copy.deepcopy(value["blocks"][0]["content_span"]),
                "status": "observed_candidate",
                "producer_version": "forged",
            }),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original)
                mutate(changed)
                with self.assertRaises(StructuralPrepassError):
                    validate_block_map(changed, text)

    def test_event_identity_and_artifact_path_mutation_are_rejected(self):
        text = "ANALYSIS\n"
        original = self.parse(text)
        changed = copy.deepcopy(original)
        changed["parser_events"][0]["event_id"] = "evt-" + "0" * 20
        with self.assertRaises(StructuralPrepassError):
            validate_block_map(changed, text)
        wrong_path = Path("cases") / original["case_id"] / original["source_hash"] / "wrong" / "block_map.json"
        with self.assertRaises(StructuralPrepassError):
            validate_block_map(original, text, artifact_path=wrong_path)

    def test_every_event_type_rejects_independent_severity_and_message_mutation(self):
        text = "Ordinary text.\n"
        original = self.parse(text)
        block = original["blocks"][0]
        span = block["span"]
        alternate_severity = {"info": "review", "review": "info", "error": "review"}
        for event_type, spec in EVENT_SPECS.items():
            with self.subTest(event_type=event_type, field="severity"):
                event_map = copy.deepcopy(original)
                event_map["parser_events"] = [
                    parser_event_for(
                        original["case_id"],
                        original["source_hash"],
                        original["parser_version"],
                        original["policy_sha256"],
                        block["block_id"],
                        block["order"],
                        event_type,
                        span["start_char"],
                        span["end_char"],
                    )
                ]
                self.assertTrue(all(validate_block_map(event_map, text).values()))
                event_map["parser_events"][0]["severity"] = alternate_severity[spec["severity"]]
                with self.assertRaises(StructuralPrepassError):
                    validate_block_map(event_map, text)
            with self.subTest(event_type=event_type, field="message"):
                event_map = copy.deepcopy(original)
                event_map["parser_events"] = [
                    parser_event_for(
                        original["case_id"],
                        original["source_hash"],
                        original["parser_version"],
                        original["policy_sha256"],
                        block["block_id"],
                        block["order"],
                        event_type,
                        span["start_char"],
                        span["end_char"],
                    )
                ]
                event_map["parser_events"][0]["message"] = "tampered audit detail"
                with self.assertRaises(StructuralPrepassError):
                    validate_block_map(event_map, text)

    def test_malformed_missing_wrong_type_and_extra_data_are_controlled_errors(self):
        text = "[1]\nText.\n"
        original = self.parse(text)
        malformed_values = [None, [], {"extra": True}]
        wrong_type = copy.deepcopy(original)
        wrong_type["blocks"] = "not-an-array"
        extra = copy.deepcopy(original)
        extra["unexpected"] = True
        for value in [*malformed_values, wrong_type, extra]:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(StructuralPrepassError) as context:
                    validate_block_map(value, text)  # type: ignore[arg-type]
                self.assertTrue(context.exception.code)
                self.assertTrue(context.exception.location)

    def test_checked_in_kos5_report_and_maps_pass_schema_and_gate(self):
        report = json.loads((PIPELINE_DIR / "reports/plan03_structural_validation.latest.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["case_count"], 5)
        self.assertEqual(report["summary"]["coverage_rate"], 1.0)
        self.assertEqual(report["summary"]["error_event_count"], 0)
        output_root = Path(report["outputs"]["output_root"])
        for case in report["cases"]:
            block_map = json.loads((output_root / case["artifact_ref"]).read_text(encoding="utf-8"))
            self.assertEqual(block_map["relations"], [])
            self.assertNotIn("source_text", block_map)


if __name__ == "__main__":
    unittest.main()
