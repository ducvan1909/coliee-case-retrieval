from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.source_contract import open_source
from knowledge_base.pipeline_v1.structural_prepass import (
    EVENT_SPECS,
    StructuralPrepassError,
    build_source_blocks,
    parse_source,
    validate_block_map,
)
from knowledge_base.pipeline_v1.structural_prepass.parser import parser_event_for


PIPELINE_DIR = Path(__file__).resolve().parents[1]
REPORT_PATH = PIPELINE_DIR / "reports/plan03_structural_validation.latest.json"
POLICY_PATH = PIPELINE_DIR / "policies/sourceblock_policy.v1.json"


class Plan03IndependentEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        cls.output_root = Path(cls.report["outputs"]["output_root"])
        cls.store_root = Path(cls.report["inputs"]["source_store"])
        cls.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def _maps(self):
        for row in self.report["cases"]:
            path = self.output_root / row["artifact_ref"]
            yield row, json.loads(path.read_text(encoding="utf-8"))

    def test_kos5_exact_partition_round_trip_ids_and_event_ledger(self):
        total_events = 0
        total_errors = 0
        for row, block_map in self._maps():
            text = open_source(self.store_root, row["case_id"], row["source_hash"])
            checks = validate_block_map(block_map, text, self.store_root)
            self.assertTrue(all(checks.values()))
            self.assertEqual([block["order"] for block in block_map["blocks"]], list(range(len(block_map["blocks"]))))
            self.assertEqual(len({block["block_id"] for block in block_map["blocks"]}), len(block_map["blocks"]))
            total_events += len(block_map["parser_events"])
            total_errors += sum(event["severity"] == "error" for event in block_map["parser_events"])
        self.assertEqual(total_events, 76)
        self.assertEqual(total_errors, 0)

    def test_marker_heading_quote_list_whitespace_and_unknown_synthetic_cases(self):
        text = (
            "\ufeff  \r\n[1987] 1 S.C.R. 2\r\n"
            "This Is Not A Heading.\n"
            "[7]\nThe court stated \"test\".\n(a) factor\nContinuation.\n"
            "ANALYSIS\n[8]\nNext.\n"
        )
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        block_map = parse_source(text=text, case_id="000001", source_hash=source_hash, policy=self.policy)
        self.assertTrue(all(validate_block_map(block_map, text).values()))
        numbered = [block for block in block_map["blocks"] if block["block_type"] == "numbered_paragraph"]
        self.assertEqual(len(numbered), 2)
        self.assertEqual(text[numbered[0]["marker_span"]["start_char"]:numbered[0]["marker_span"]["end_char"]], "[7]")
        self.assertIn("list_marker", {nested["span_type"] for nested in numbered[0]["nested_spans"]})
        self.assertIn("quotation_candidate", {nested["span_type"] for nested in numbered[0]["nested_spans"]})
        headings = [block for block in block_map["blocks"] if block["heading_candidate"]]
        self.assertEqual(len(headings), 1)
        self.assertEqual(text[headings[0]["content_span"]["start_char"]:headings[0]["content_span"]["end_char"]], "ANALYSIS")
        self.assertTrue(any(event["event_type"] == "bracket_year_protected" for event in block_map["parser_events"]))

    def test_empty_all_whitespace_long_and_unclosed_quote_are_auditable(self):
        for text in ("", " \t\r\n\n"):
            source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            block_map = parse_source(text=text, case_id="000001", source_hash=source_hash, policy=self.policy)
            self.assertTrue(all(validate_block_map(block_map, text).values()))
        text = '[1]\n"' + ("x" * 5100) + "\n"
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        block_map = parse_source(text=text, case_id="000001", source_hash=source_hash, policy=self.policy)
        event_types = {event["event_type"] for event in block_map["parser_events"]}
        self.assertIn("very_long_block", event_types)
        self.assertIn("unclosed_quotation", event_types)
        self.assertEqual(sum(event["severity"] == "error" for event in block_map["parser_events"]), 0)

    def test_parser_and_source_versions_change_cache_and_block_ids(self):
        text = "[1]\nText.\n"
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        original = parse_source(text=text, case_id="000001", source_hash=source_hash, policy=self.policy, parser_version="parser-a")
        changed_parser = parse_source(text=text, case_id="000001", source_hash=source_hash, policy=self.policy, parser_version="parser-b")
        changed_text = text + "More.\n"
        changed_hash = hashlib.sha256(changed_text.encode("utf-8")).hexdigest()
        changed_source = parse_source(text=changed_text, case_id="000001", source_hash=changed_hash, policy=self.policy, parser_version="parser-a")
        self.assertNotEqual(original["cache_key"], changed_parser["cache_key"])
        self.assertNotEqual(original["cache_key"], changed_source["cache_key"])
        self.assertNotEqual(original["blocks"][0]["block_id"], changed_parser["blocks"][0]["block_id"])
        self.assertNotEqual(original["blocks"][0]["block_id"], changed_source["blocks"][0]["block_id"])

    def test_corrupt_cached_block_map_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            kwargs = {
                "store_root": self.store_root,
                "store_manifest_path": self.report["inputs"]["source_store_manifest"],
                "plan02_report_path": self.report["inputs"]["plan02_report"],
                "policy_path": POLICY_PATH,
                "output_root": output,
            }
            first = build_source_blocks(**kwargs)
            artifact = output / first["cases"][0]["artifact_ref"]
            artifact.write_text("{corrupt", encoding="utf-8")
            with self.assertRaises(StructuralPrepassError):
                build_source_blocks(**kwargs)

    def test_forbidden_plan04_plus_outputs_are_absent(self):
        forbidden = {"SentenceAtom", "LegalUnit", "AuthorityUnit", "AnalysisRegion", "LLM"}
        for _, block_map in self._maps():
            serialized = json.dumps(block_map, ensure_ascii=False)
            for term in forbidden:
                self.assertNotIn(term, serialized)
            self.assertEqual(block_map["relations"], [])

    def test_tampered_cache_and_block_provenance_are_rejected(self):
        row, original = next(self._maps())
        text = open_source(self.store_root, row["case_id"], row["source_hash"])
        mutations = {
            "cache_key": lambda value: value.update(cache_key="0" * 64),
            "block_id": lambda value: value["blocks"][0].update(block_id="sb-forged"),
            "block_parser_version": lambda value: value["blocks"][0].update(parser_version="forged-parser"),
            "block_policy_sha256": lambda value: value["blocks"][0].update(policy_sha256="0" * 64),
            "nested_case_id": lambda value: value["blocks"][0]["span"].update(case_id="999999"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original)
                mutate(changed)
                with self.assertRaises(StructuralPrepassError):
                    validate_block_map(changed, text)

    def test_tampered_event_severity_cannot_hide_review_event(self):
        row, original = next(self._maps())
        text = open_source(self.store_root, row["case_id"], row["source_hash"])
        event_index = next(
            index
            for index, event in enumerate(original["parser_events"])
            if event["severity"] == "review"
        )
        changed = copy.deepcopy(original)
        changed["parser_events"][event_index]["severity"] = "info"
        changed["parser_events"][event_index]["message"] = "tampered audit classification"
        with self.assertRaises(StructuralPrepassError):
            validate_block_map(changed, text)

    def test_every_event_type_rejects_each_contract_and_link_mutation(self):
        text = "ANALYSIS\n[1]\nText.\n"
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        base = parse_source(
            text=text,
            case_id="000001",
            source_hash=source_hash,
            policy=self.policy,
        )
        block = base["blocks"][0]
        span = block["span"]
        for event_type in EVENT_SPECS:
            canonical = parser_event_for(
                base["case_id"],
                base["source_hash"],
                base["parser_version"],
                base["policy_sha256"],
                block["block_id"],
                block["order"],
                event_type,
                span["start_char"],
                span["end_char"],
            )
            fixture = copy.deepcopy(base)
            fixture["parser_events"] = [canonical]
            self.assertTrue(all(validate_block_map(fixture, text).values()))
            mutations = {
                "severity": lambda event: event.update(severity="info" if event["severity"] != "info" else "review"),
                "message": lambda event: event.update(message="tampered"),
                "message_code": lambda event: event.update(message_code="tampered_code"),
                "event_type": lambda event: event.update(event_type=next(value for value in EVENT_SPECS if value != event_type)),
                "event_contract_version": lambda event: event.update(event_contract_version="sourceblock-event-v1"),
                "block_id": lambda event: event.update(block_id="sb-" + "0" * 24),
                "block_order": lambda event: event.update(block_order=1),
                "span_case_id": lambda event: event["span"].update(case_id="999999"),
                "span_source_hash": lambda event: event["span"].update(source_hash="0" * 64),
                "span_bounds": lambda event: event["span"].update(start_char=span["start_char"] + 1),
                "parser_version": lambda event: event.update(parser_version="forged-parser"),
                "policy_sha256": lambda event: event.update(policy_sha256="0" * 64),
                "event_id": lambda event: event.update(event_id="evt-" + "0" * 20),
            }
            for field, mutate in mutations.items():
                with self.subTest(event_type=event_type, field=field):
                    changed = copy.deepcopy(fixture)
                    mutate(changed["parser_events"][0])
                    with self.assertRaises(StructuralPrepassError):
                        validate_block_map(changed, text)


if __name__ == "__main__":
    unittest.main()
