from __future__ import annotations

import copy
import hashlib
import json
import unittest
import tempfile
from pathlib import Path

from knowledge_base.pipeline_v1.sentence_atoms import SentenceAtomError, load_and_validate_sentence_atom_map, segment_case, validate_sentence_atom_map
from knowledge_base.pipeline_v1.structural_prepass import parse_source


PIPELINE_DIR = Path(__file__).resolve().parents[1]
SB_POLICY = json.loads((PIPELINE_DIR / "policies/sourceblock_policy.v1.json").read_text(encoding="utf-8"))
SA_POLICY = json.loads((PIPELINE_DIR / "policies/sentence_atom_policy.v1.json").read_text(encoding="utf-8"))


class Plan04SentenceAtomTests(unittest.TestCase):
    def make(self, text: str, policy: dict | None = None):
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        blocks = parse_source(text=text, case_id="000001", source_hash=source_hash, policy=SB_POLICY)
        atom_policy = policy or SA_POLICY
        return blocks, segment_case(text, blocks, atom_policy)

    def atom_texts(self, text: str, atom_map: dict) -> list[str]:
        return [text[item["span"]["start_char"]:item["span"]["end_char"]] for item in atom_map["atoms"]]

    def test_legal_abbreviations_initials_sections_and_case_names_do_not_split(self):
        text = "Smith v. Jones. Brown J. considered No. 3 under s. 2, para. 4 and 12 F.C. 10. Next sentence."
        blocks, atom_map = self.make(text)
        texts = self.atom_texts(text, atom_map)
        self.assertEqual(len(texts), 3)
        self.assertIn("Smith v. Jones.", texts[0])
        self.assertFalse(any(item.rstrip().endswith("v.") for item in texts))
        protected_types = {item["span_type"] for item in atom_map["protected_spans"] if item["boundary_forbidden"]}
        self.assertTrue({"case_name", "abbreviation", "section_reference", "reporter_citation"} <= protected_types)
        self.assertTrue(all(validate_sentence_atom_map(atom_map, text, blocks, SA_POLICY).values()))

    def test_citation_year_and_paragraph_marker_are_exact_inherited_protected_spans(self):
        text = "[12]\nThe result in [1987] 1 S.C.R. 2 applies. Next.\n"
        blocks, atom_map = self.make(text)
        marker = next(item for item in atom_map["protected_spans"] if item["span_type"] == "paragraph_marker")
        year = next(item for item in atom_map["protected_spans"] if item["span_type"] == "citation_year")
        self.assertEqual(text[marker["span"]["start_char"]:marker["span"]["end_char"]], "[12]")
        self.assertEqual(text[year["span"]["start_char"]:year["span"]["end_char"]], "[1987]")
        self.assertTrue(marker["boundary_forbidden"] and year["boundary_forbidden"])
        parent = blocks["blocks"][0]
        self.assertEqual(marker["span"], parent["marker_span"])
        parent_ref = atom_map["parent_block_refs"][0]
        self.assertEqual(parent_ref["block_id"], parent["block_id"])
        self.assertEqual(parent_ref["content_span"], parent["content_span"])
        self.assertEqual(parent_ref["marker_span"], parent["marker_span"])

    def test_quoted_multiple_punctuation_is_context_only_and_sentence_boundary_survives(self):
        text = 'The court asked, "Really?!" Next sentence.\n'
        blocks, atom_map = self.make(text)
        self.assertEqual(len(atom_map["atoms"]), 2)
        quote = next(item for item in atom_map["protected_spans"] if item["span_type"] == "balanced_quotation")
        self.assertEqual(quote["protection_mode"], "context_only")
        self.assertFalse(quote["boundary_forbidden"])

    def test_unbalanced_quote_is_context_only_review_not_error(self):
        text = 'The witness said "unfinished. Next sentence.\n'
        _, atom_map = self.make(text)
        quote = next(item for item in atom_map["protected_spans"] if item["span_type"] == "unbalanced_quotation")
        self.assertFalse(quote["boundary_forbidden"])
        event = next(item for item in atom_map["segmenter_events"] if item["event_type"] == "unbalanced_quotation")
        self.assertEqual(event["severity"], "review")

    def test_list_marker_is_forbidden_but_does_not_create_child_structure(self):
        text = "[1]\n(a) First factor. Second sentence.\n"
        blocks, atom_map = self.make(text)
        marker = next(item for item in atom_map["protected_spans"] if item["span_type"] == "list_marker")
        self.assertTrue(marker["boundary_forbidden"])
        self.assertEqual({item["parent_block_id"] for item in atom_map["atoms"]}, {blocks["blocks"][0]["block_id"]})

    def test_long_block_slice_plan_uses_atom_boundaries_and_no_text(self):
        policy = copy.deepcopy(SA_POLICY)
        policy["slice_policy"]["max_chars"] = 60
        text = "[1]\n" + "First proposition with enough words. " * 3 + "Second proposition ends here."
        blocks, atom_map = self.make(text, policy)
        self.assertEqual(len(atom_map["slice_plans"]), 1)
        plan = atom_map["slice_plans"][0]
        atom_ends = {item["span"]["end_char"] for item in atom_map["atoms"]}
        self.assertTrue(all(item["span"]["end_char"] in atom_ends for item in plan["slices"]))
        self.assertNotIn("text", atom_map)
        self.assertTrue(all("text" not in item for item in atom_map["atoms"]))
        self.assertTrue(all("text" not in item for item in plan["slices"]))
        self.assertEqual(plan["parent_block_id"], blocks["blocks"][0]["block_id"])

    def test_cache_version_provenance_and_path_mutations_are_rejected(self):
        text = "[1]\nOne sentence. Next.\n"
        blocks, original = self.make(text)
        mutations = {
            "cache": lambda value: value.update(cache_key="0" * 64),
            "atom_parent": lambda value: value["atoms"][0].update(parent_block_id="sb-" + "0" * 24),
            "atom_span_case": lambda value: value["atoms"][0]["span"].update(case_id="999999"),
            "protected_mode": lambda value: value["protected_spans"][0].update(boundary_forbidden=False),
            "segmenter": lambda value: value.update(segmenter_version="forged"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original); mutate(changed)
                with self.assertRaises(SentenceAtomError):
                    validate_sentence_atom_map(changed, text, blocks, SA_POLICY)
        wrong = Path("cases") / original["case_id"] / original["source_hash"] / original["sourceblock_map_cache_key"] / "wrong" / "sentence_atom_map.json"
        with self.assertRaises(SentenceAtomError):
            validate_sentence_atom_map(original, text, blocks, SA_POLICY, artifact_path=wrong)

    def test_policy_or_segmenter_change_invalidates_cache_and_atom_ids(self):
        text = "[1]\nOne sentence.\n"
        _, original = self.make(text)
        changed_policy = copy.deepcopy(SA_POLICY); changed_policy["segmenter_version"] = "legal-sentence-rules-v2"
        _, changed = self.make(text, changed_policy)
        self.assertNotEqual(original["cache_key"], changed["cache_key"])
        self.assertNotEqual(original["atoms"][0]["atom_id"], changed["atoms"][0]["atom_id"])

    def test_malformed_and_extra_data_are_controlled_errors(self):
        text = "One sentence."
        blocks, original = self.make(text)
        for changed in (None, [], {"bad": True}, {**original, "extra": True}):
            with self.subTest(kind=type(changed).__name__):
                with self.assertRaises(SentenceAtomError):
                    validate_sentence_atom_map(changed, text, blocks, SA_POLICY)  # type: ignore[arg-type]

    def test_corrupt_read_artifact_is_rejected_without_crash(self):
        text = "One sentence."
        blocks, _ = self.make(text)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sentence_atom_map.json"
            path.write_text("{corrupt", encoding="utf-8")
            with self.assertRaises(SentenceAtomError) as context:
                load_and_validate_sentence_atom_map(path, text, blocks, SA_POLICY)
            self.assertEqual(context.exception.code, "malformed_artifact")

    def test_checked_in_kos5_report_has_exact_gate_and_no_forbidden_outputs(self):
        report = json.loads((PIPELINE_DIR / "reports/plan04_sentence_atom_validation.latest.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["case_count"], 5)
        self.assertEqual(report["summary"]["error_event_count"], 0)
        self.assertTrue(report["gates"]["zero_forbidden_boundary_cuts"])
        output = Path(report["outputs"]["output_root"])
        for row in report["cases"]:
            serialized = (output / row["artifact_ref"]).read_text(encoding="utf-8")
            for forbidden in ("LegalUnit", "AnalysisRegion", "AuthorityUnit", "LLM"):
                self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
