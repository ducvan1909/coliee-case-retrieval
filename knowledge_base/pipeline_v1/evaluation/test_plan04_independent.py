from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.sentence_atoms import (
    SentenceAtomError,
    build_sentence_atoms,
    segment_case,
    validate_sentence_atom_map,
)
from knowledge_base.pipeline_v1.sentence_atoms.segmenter import canonical_hash
from knowledge_base.pipeline_v1.source_contract import open_source
from knowledge_base.pipeline_v1.structural_prepass import load_and_validate_block_map, parse_source


PIPELINE_DIR = Path(__file__).resolve().parents[1]
REPORT_PATH = PIPELINE_DIR / "reports/plan04_sentence_atom_validation.latest.json"
PLAN03_REPORT_PATH = PIPELINE_DIR / "reports/plan03_structural_validation.latest.json"
PLAN03_INDEPENDENT = PIPELINE_DIR / "evaluation/plan03_independent_evaluation.md"
SA_POLICY_PATH = PIPELINE_DIR / "policies/sentence_atom_policy.v1.json"
SB_POLICY_PATH = PIPELINE_DIR / "policies/sourceblock_policy.v1.json"


class Plan04IndependentEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        cls.plan03 = json.loads(PLAN03_REPORT_PATH.read_text(encoding="utf-8"))
        cls.output = Path(cls.report["outputs"]["output_root"])
        cls.source_store = Path(cls.report["inputs"]["source_store"])
        cls.sa_policy = json.loads(SA_POLICY_PATH.read_text(encoding="utf-8"))
        cls.sb_policy = json.loads(SB_POLICY_PATH.read_text(encoding="utf-8"))

    def _rows(self):
        plan03_by_case = {row["case_id"]: row for row in self.plan03["cases"]}
        for row in self.report["cases"]:
            sourceblock_row = plan03_by_case[row["case_id"]]
            sourceblock_path = Path(self.plan03["outputs"]["output_root"]) / sourceblock_row["artifact_ref"]
            text = open_source(self.source_store, row["case_id"], row["source_hash"])
            sourceblock_map, _ = load_and_validate_block_map(sourceblock_path, text, self.source_store)
            atom_path = self.output / row["artifact_ref"]
            atom_map = json.loads(atom_path.read_text(encoding="utf-8"))
            yield row, text, sourceblock_map, atom_path, atom_map

    def _synthetic(self, text: str, sa_policy: dict | None = None):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        sourceblock_map = parse_source(
            text=text,
            case_id="000001",
            source_hash=digest,
            policy=self.sb_policy,
        )
        policy = sa_policy or self.sa_policy
        atom_map = segment_case(text, sourceblock_map, policy)
        return sourceblock_map, atom_map, policy

    def test_kos5_recomputed_counts_parent_identity_and_exact_round_trip(self):
        counts = {"atoms": 0, "protected": 0, "plans": 0, "slices": 0, "reviews": 0, "errors": 0}
        for row, text, sourceblock_map, atom_path, atom_map in self._rows():
            checks = validate_sentence_atom_map(
                atom_map, text, sourceblock_map, self.sa_policy, artifact_path=atom_path
            )
            self.assertTrue(all(checks.values()))
            self.assertEqual(atom_map["sourceblock_parser_version"], "sourceblock-rules-v1.3")
            self.assertEqual(atom_map["sourceblock_map_cache_key"], sourceblock_map["cache_key"])
            self.assertEqual(atom_map["parent_block_refs"], [
                {
                    "record_type": "SentenceAtomParentBlockRef",
                    "block_id": block["block_id"],
                    "block_order": block["order"],
                    "span": block["span"],
                    "content_span": block["content_span"],
                    "marker_span": block["marker_span"],
                    "parser_version": block["parser_version"],
                    "policy_sha256": block["policy_sha256"],
                }
                for block in sourceblock_map["blocks"]
            ])
            self.assertEqual(
                "".join(text[a["span"]["start_char"]:a["span"]["end_char"]] for a in atom_map["atoms"]),
                text,
            )
            counts["atoms"] += len(atom_map["atoms"])
            counts["protected"] += len(atom_map["protected_spans"])
            counts["plans"] += len(atom_map["slice_plans"])
            counts["slices"] += sum(len(plan["slices"]) for plan in atom_map["slice_plans"])
            counts["reviews"] += sum(e["severity"] == "review" for e in atom_map["segmenter_events"])
            counts["errors"] += sum(e["severity"] == "error" for e in atom_map["segmenter_events"])
        self.assertEqual(counts, {"atoms": 1240, "protected": 2754, "plans": 5, "slices": 10, "reviews": 10, "errors": 0})

    def test_no_atom_boundary_cuts_boundary_forbidden_spans(self):
        for _, _, _, _, atom_map in self._rows():
            boundaries = {atom["span"]["end_char"] for atom in atom_map["atoms"]}
            for protected in atom_map["protected_spans"]:
                ref = protected["span"]
                if protected["boundary_forbidden"]:
                    self.assertFalse(any(ref["start_char"] < point < ref["end_char"] for point in boundaries))
                    self.assertEqual(protected["protection_mode"], "boundary_forbidden")
                else:
                    self.assertEqual(protected["protection_mode"], "context_only")

    def test_legal_punctuation_markers_quotes_lists_and_layout_adversarial(self):
        text = (
            "\ufeff\r\n[12]\r\n"
            "Smith v. Jones. Brown J. considered A. Smith, No. 3, s. 2, para. 4, "
            "12 F.C. 10, 3.14 and [1987] 1 S.C.R. 2. Next sentence.\n"
            "(a) First item. Second item.\n"
            "The court asked, \"Really?! Another question?\" Final sentence.\n"
            "The witness said \"unfinished. Still quoted.\n"
        )
        blocks, atom_map, policy = self._synthetic(text)
        self.assertTrue(all(validate_sentence_atom_map(atom_map, text, blocks, policy).values()))
        forbidden_types = {p["span_type"] for p in atom_map["protected_spans"] if p["boundary_forbidden"]}
        self.assertTrue({"case_name", "abbreviation", "initial", "section_reference", "reporter_citation", "decimal_reference", "citation_year", "paragraph_marker", "list_marker"} <= forbidden_types)
        quote_modes = {p["span_type"]: p["protection_mode"] for p in atom_map["protected_spans"] if "quotation" in p["span_type"]}
        self.assertEqual(quote_modes["balanced_quotation"], "context_only")
        self.assertEqual(quote_modes["unbalanced_quotation"], "context_only")
        self.assertTrue(any(e["event_type"] == "unbalanced_quotation" and e["severity"] == "review" for e in atom_map["segmenter_events"]))

    def test_heading_editorial_table_whitespace_and_very_long_slice_are_structural_only(self):
        policy = copy.deepcopy(self.sa_policy)
        policy["slice_policy"]["max_chars"] = 80
        text = "ANALYSIS\n<FRAGMENT_SUPPRESSED>\nDate   Court   Citation\n\r\n[1]\n" + ("Long proposition. " * 30)
        blocks, atom_map, policy = self._synthetic(text, policy)
        self.assertTrue(all(validate_sentence_atom_map(atom_map, text, blocks, policy).values()))
        self.assertGreaterEqual(len(atom_map["slice_plans"]), 1)
        serialized = json.dumps(atom_map, ensure_ascii=False)
        for forbidden in ("LegalUnit", "semantic_role", "AuthorityUnit", "Issue", "NoticeNeed", "retrieval", "LLM"):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("source_text", atom_map)
        for plan in atom_map["slice_plans"]:
            self.assertFalse(plan["model_specific"])
            for item in plan["slices"]:
                self.assertNotIn("text", item)
                self.assertIn(item["first_atom_id"], {a["atom_id"] for a in atom_map["atoms"]})
                self.assertIn(item["last_atom_id"], {a["atom_id"] for a in atom_map["atoms"]})

    def test_each_persisted_contract_area_rejects_independent_mutation(self):
        _, text, sourceblock_map, atom_path, original = next(self._rows())
        mutations = {
            "cache_key": lambda value: value.update(cache_key="0" * 64),
            "case_id": lambda value: value.update(case_id="999999"),
            "source_hash": lambda value: value.update(source_hash="0" * 64),
            "sourceblock_cache": lambda value: value.update(sourceblock_map_cache_key="0" * 64),
            "sourceblock_version": lambda value: value.update(sourceblock_parser_version="forged"),
            "segmenter_version": lambda value: value.update(segmenter_version="forged"),
            "policy_hash": lambda value: value.update(policy_sha256="0" * 64),
            "parent_ref": lambda value: value["parent_block_refs"][0].update(block_id="sb-" + "0" * 24),
            "atom_id": lambda value: value["atoms"][0].update(atom_id="sa-" + "0" * 24),
            "atom_parent": lambda value: value["atoms"][0].update(parent_block_id="sb-" + "0" * 24),
            "atom_order": lambda value: value["atoms"][0].update(global_order=999999),
            "atom_span": lambda value: value["atoms"][0]["span"].update(end_char=value["atoms"][0]["span"]["end_char"] + 1),
            "protected_id": lambda value: value["protected_spans"][0].update(protected_span_id="ps-" + "0" * 24),
            "protected_mode": lambda value: value["protected_spans"][0].update(boundary_forbidden=not value["protected_spans"][0]["boundary_forbidden"]),
            "protected_duplicate": lambda value: value["protected_spans"].append(copy.deepcopy(value["protected_spans"][0])),
        }
        plan_index = next((i for i, plan in enumerate(original["slice_plans"]) if plan["slices"]), None)
        if plan_index is not None:
            mutations.update({
                "plan_id": lambda value: value["slice_plans"][plan_index].update(plan_id="sp-" + "0" * 24),
                "slice_id": lambda value: value["slice_plans"][plan_index]["slices"][0].update(slice_id="sl-" + "0" * 24),
                "slice_order": lambda value: value["slice_plans"][plan_index]["slices"][0].update(slice_order=99),
                "slice_atom_link": lambda value: value["slice_plans"][plan_index]["slices"][0].update(first_atom_id="sa-" + "0" * 24),
            })
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original)
                mutate(changed)
                with self.assertRaises(SentenceAtomError):
                    validate_sentence_atom_map(changed, text, sourceblock_map, self.sa_policy, artifact_path=atom_path)

        slice_row, slice_text, slice_blocks, slice_path, slice_original = next(
            item for item in self._rows() if item[0]["slice_plan_count"]
        )
        for name, mutate in {
            "plan_id": lambda value: value["slice_plans"][0].update(plan_id="sp-" + "0" * 24),
            "plan_parent": lambda value: value["slice_plans"][0].update(parent_block_id="sb-" + "0" * 24),
            "slice_id": lambda value: value["slice_plans"][0]["slices"][0].update(slice_id="sl-" + "0" * 24),
            "slice_order": lambda value: value["slice_plans"][0]["slices"][0].update(slice_order=99),
            "slice_atom_link": lambda value: value["slice_plans"][0]["slices"][0].update(first_atom_id="sa-" + "0" * 24),
            "slice_span": lambda value: value["slice_plans"][0]["slices"][0]["span"].update(end_char=value["slice_plans"][0]["slices"][0]["span"]["end_char"] - 1),
        }.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(slice_original); mutate(changed)
                with self.assertRaises(SentenceAtomError):
                    validate_sentence_atom_map(changed, slice_text, slice_blocks, self.sa_policy, artifact_path=slice_path)
        wrong_path = slice_path.parent.parent / "wrong-version" / "sentence_atom_map.json"
        with self.assertRaises(SentenceAtomError):
            validate_sentence_atom_map(slice_original, slice_text, slice_blocks, self.sa_policy, artifact_path=wrong_path)

    def test_review_event_and_malformed_partial_corrupt_artifacts_are_rejected(self):
        row = next(item for item in self.report["cases"] if item["review_event_count"])
        _, text, sourceblock_map, atom_path, original = next(item for item in self._rows() if item[0]["case_id"] == row["case_id"])
        event_index = next(i for i, event in enumerate(original["segmenter_events"]) if event["severity"] == "review")
        for name, mutate in {
            "severity": lambda value: value["segmenter_events"][event_index].update(severity="error"),
            "message": lambda value: value["segmenter_events"][event_index].update(message="tampered"),
            "event_id": lambda value: value["segmenter_events"][event_index].update(event_id="se-" + "0" * 20),
            "missing_atoms": lambda value: value.pop("atoms"),
            "extra": lambda value: value.update(extra=True),
        }.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original); mutate(changed)
                with self.assertRaises(SentenceAtomError):
                    validate_sentence_atom_map(changed, text, sourceblock_map, self.sa_policy, artifact_path=atom_path)
        with tempfile.TemporaryDirectory() as temporary:
            corrupt = Path(temporary) / "sentence_atom_map.json"
            corrupt.write_text("{partial", encoding="utf-8")
            from knowledge_base.pipeline_v1.sentence_atoms import load_and_validate_sentence_atom_map
            with self.assertRaises(SentenceAtomError):
                load_and_validate_sentence_atom_map(corrupt, text, sourceblock_map, self.sa_policy)

    def test_cache_resume_and_dependency_changes_create_new_identity(self):
        text = "[1]\nOne sentence. Next sentence.\n"
        blocks, original, policy = self._synthetic(text)
        changed_policy = copy.deepcopy(policy)
        changed_policy["segmenter_version"] = "legal-sentence-rules-independent-change"
        changed_segmenter = segment_case(text, blocks, changed_policy)
        changed_text = text + "Added.\n"
        changed_hash = hashlib.sha256(changed_text.encode("utf-8")).hexdigest()
        changed_blocks = parse_source(text=changed_text, case_id="000001", source_hash=changed_hash, policy=self.sb_policy)
        changed_source = segment_case(changed_text, changed_blocks, policy)
        changed_parent = copy.deepcopy(blocks)
        changed_parent["cache_key"] = "0" * 64
        changed_parent_map = segment_case(text, changed_parent, policy)
        self.assertNotEqual(original["cache_key"], changed_segmenter["cache_key"])
        self.assertNotEqual(original["cache_key"], changed_source["cache_key"])
        self.assertNotEqual(original["cache_key"], changed_parent_map["cache_key"])
        self.assertNotEqual(original["atoms"][0]["atom_id"], changed_segmenter["atoms"][0]["atom_id"])


if __name__ == "__main__":
    unittest.main()
