from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.sentence_atoms import segment_case
from knowledge_base.pipeline_v1.sentence_atoms.segmenter import canonical_hash
from knowledge_base.pipeline_v1.sidecars import SidecarAPI, SidecarError, SidecarQueryError, run_sidecar_workers, validate_sidecar_map
from knowledge_base.pipeline_v1.structural_prepass import parse_source


PIPELINE_DIR = Path(__file__).resolve().parents[1]
SB_POLICY = json.loads((PIPELINE_DIR / "policies/sourceblock_policy.v1.json").read_text(encoding="utf-8"))
SA_POLICY = json.loads((PIPELINE_DIR / "policies/sentence_atom_policy.v1.json").read_text(encoding="utf-8"))
SC_POLICY = json.loads((PIPELINE_DIR / "policies/sidecar_policy.v1.json").read_text(encoding="utf-8"))


class Plan05SidecarTests(unittest.TestCase):
    def make(self, text: str, faults: set[str] | None = None):
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        blocks = parse_source(text=text, case_id="000001", source_hash=source_hash, policy=SB_POLICY)
        atoms = segment_case(text, blocks, SA_POLICY)
        sidecars = run_sidecar_workers(text, blocks, atoms, SC_POLICY, canonical_hash(SC_POLICY), faults)
        return blocks, atoms, sidecars

    def test_suppression_and_paragraph_markers_are_observed_not_citations(self):
        text = "<FRAGMENT_SUPPRESSED> [REFERENCE_SUPPRESSED]\n[12]\nActual paragraph.\n"
        _, _, sidecars = self.make(text)
        markers = [item for item in sidecars["annotations"] if item["worker_type"] == "marker_rule"]
        self.assertEqual(sum(item["annotation_type"] == "suppression_marker" for item in markers), 2)
        paragraph = next(item for item in markers if item["annotation_type"] == "paragraph_marker")
        self.assertEqual(text[paragraph["span"]["start_char"]:paragraph["span"]["end_char"]], "[12]")
        self.assertFalse(any(item["annotation_type"] == "citation_year" and text[item["span"]["start_char"]:item["span"]["end_char"]] == "[12]" for item in sidecars["annotations"]))

    def test_citation_reference_rules_and_punctuation_false_positive(self):
        text = "[1]\nSmith v. Jones, 2010 SCC 2, [1987] 1 S.C.R. 10 considered s. 7 and para. 4. Ordinary 123. Next.\n"
        _, _, sidecars = self.make(text)
        types = {item["annotation_type"] for item in sidecars["annotations"] if item["worker_type"] == "citation_reference_rule"}
        self.assertTrue({"case_reference", "neutral_citation", "citation_year", "reporter_citation", "section_reference"} <= types)
        citation_texts = [text[item["span"]["start_char"]:item["span"]["end_char"]] for item in sidecars["annotations"] if item["worker_type"] == "citation_reference_rule"]
        self.assertNotIn("123.", citation_texts)

    def test_nested_quote_list_and_quote_balance_lineage(self):
        text = '[1]\nThe Court stated "a rule".\n(a) factor\nThe witness said "unfinished.\n'
        _, _, sidecars = self.make(text)
        nested = [item for item in sidecars["annotations"] if item["worker_type"] == "nested_structure_inheritance"]
        self.assertTrue(any(item["annotation_type"] == "nested_list" for item in nested))
        self.assertTrue(any(item["value_code"] == "balanced_quotation" for item in nested))
        self.assertTrue(any(item["value_code"] == "unbalanced_quotation" and item["status"] == "review" for item in nested))
        balances = [item for item in sidecars["annotations"] if item["annotation_type"] == "quote_balance"]
        self.assertEqual({item["value_code"] for item in balances}, {"balanced", "unbalanced"})

    def test_speaker_cues_are_candidates_without_speaker_or_attribution(self):
        text = "[1]\nThe applicant submits that relief is due. The Court finds otherwise. I conclude the appeal fails.\n"
        _, _, sidecars = self.make(text)
        cues = [item for item in sidecars["annotations"] if item["annotation_type"] == "speaker_cue"]
        self.assertEqual(len(cues), 3)
        self.assertTrue(all(item["status"] == "candidate" for item in cues))
        serialized = json.dumps(cues)
        self.assertNotIn('"speaker"', serialized)
        self.assertNotIn('"attribution"', serialized)

    def test_heading_false_positive_has_no_governance_and_formal_heading_is_candidate_only(self):
        text = "IMPORTANT NOTICE\nOrdinary paragraph.\nANALYSIS\n[1]\nLegal discussion.\n"
        blocks, _, sidecars = self.make(text)
        relations = [item for item in sidecars["relations"] if item["relation_type"] == "governed_by_heading"]
        false_heading = next(block for block in blocks["blocks"] if text[block["content_span"]["start_char"]:block["content_span"]["end_char"]].strip() == "IMPORTANT NOTICE")
        self.assertFalse(any(item["target_ref"] == false_heading["block_id"] for item in relations))
        self.assertTrue(relations)
        self.assertTrue(all(item["status"] == "candidate" for item in relations))

    def test_continuation_requires_observed_cue(self):
        text = "[1]\nClosed sentence.\n[2]\nAnother closed sentence.\n"
        _, _, sidecars = self.make(text)
        self.assertFalse(any(item["relation_type"] == "continuation" for item in sidecars["relations"]))

    def test_open_quote_at_block_end_creates_candidate_continuation(self):
        text = '[1]\nThe witness said "unfinished\n[2]\nContinuation follows.\n'
        blocks, _, sidecars = self.make(text)
        relations = [item for item in sidecars["relations"] if item["relation_type"] == "continuation"]
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["relation_subtype"], "open_quote_to_next_block")
        self.assertEqual(relations[0]["status"], "candidate")
        self.assertEqual(relations[0]["source_ref"], blocks["blocks"][0]["block_id"])

    def test_query_api_uses_half_open_spans_and_derived_adjacency(self):
        text = "[1]\nFirst.\n[2]\nSecond.\n"
        blocks, atoms, sidecars = self.make(text)
        api = SidecarAPI(text, blocks, atoms, sidecars)
        marker = next(item for item in sidecars["annotations"] if item["annotation_type"] == "paragraph_marker")
        end = marker["span"]["end_char"]
        self.assertIn(marker, api.query_annotations(start_char=end - 1, end_char=end))
        self.assertNotIn(marker, api.query_annotations(start_char=end, end_char=end + 1))
        opened = api.open_annotation(marker["annotation_id"])
        self.assertEqual(opened["exact_source"], "[1]")
        adjacency = api.query_relations(block_id=blocks["blocks"][0]["block_id"], relation_type="adjacency", direction="outgoing", status="derived")
        self.assertEqual(len(adjacency), 1)
        self.assertTrue(adjacency[0]["reconstructable"])
        self.assertFalse(any(item["relation_type"] == "adjacency" for item in sidecars["relations"]))

    def test_half_open_query_boundaries_empty_spans_and_invalid_identity(self):
        text = '[1]\nThe Court finds "a rule". Next.\n'
        blocks, atoms, sidecars = self.make(text)
        api = SidecarAPI(text, blocks, atoms, sidecars)
        annotation = next(item for item in sidecars["annotations"] if item["annotation_type"] == "speaker_cue")
        start, end = annotation["span"]["start_char"], annotation["span"]["end_char"]
        self.assertIn(annotation, api.query_annotations(case_id=sidecars["case_id"], source_hash=sidecars["source_hash"], start_char=start, end_char=end))
        self.assertIn(annotation, api.query_annotations(start_char=start + 1, end_char=start + 2))
        self.assertEqual(api.query_annotations(start_char=start, end_char=start), [])
        self.assertEqual(api.query_annotations(start_char=end, end_char=end), [])
        self.assertEqual(api.query_annotations(start_char=0, end_char=0), [])
        self.assertEqual(api.query_annotations(start_char=len(text), end_char=len(text)), [])
        if start > 0:
            self.assertEqual(api.query_annotations(start_char=start - 1, end_char=start), [])
        if end < len(text):
            self.assertEqual(api.query_annotations(start_char=end, end_char=end + 1, worker_type=annotation["worker_type"]), [])

        relation = next(item for item in sidecars["relations"] if item["relation_type"] == "containment")
        evidence = relation["evidence_spans"][0]
        self.assertIn(relation, api.query_relations(start_char=evidence["start_char"], end_char=evidence["end_char"], relation_type="containment"))
        self.assertEqual(api.query_relations(start_char=evidence["start_char"], end_char=evidence["start_char"]), [])
        self.assertEqual(api.query_relations(start_char=evidence["end_char"], end_char=evidence["end_char"]), [])
        if evidence["end_char"] < len(text):
            self.assertEqual(api.query_relations(start_char=evidence["end_char"], end_char=evidence["end_char"] + 1, relation_type="containment"), [])

        invalid_queries = [
            {"start_char": -1, "end_char": 0},
            {"start_char": 2, "end_char": 1},
            {"start_char": 0, "end_char": len(text) + 1},
            {"start_char": 0},
            {"case_id": "999999"},
            {"source_hash": "0" * 64},
        ]
        for kwargs in invalid_queries:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(SidecarQueryError) as context:
                    api.query_annotations(**kwargs)
                self.assertTrue(context.exception.code)
                self.assertTrue(context.exception.location)
                with self.assertRaises(SidecarQueryError):
                    api.query_relations(**kwargs)

    def test_worker_failure_isolated_and_partial_does_not_hide_other_outputs(self):
        text = "[1]\nSmith v. Jones, 2010 SCC 2. The Court finds otherwise.\n"
        blocks, atoms, partial = self.make(text, {"marker_rule"})
        self.assertEqual(partial["run_status"], "partial")
        self.assertEqual(partial["failed_workers"], ["marker_rule"])
        self.assertTrue(any(item["worker_type"] == "citation_reference_rule" for item in partial["annotations"]))
        self.assertTrue(any(item["worker_type"] == "speaker_cue_rule" for item in partial["annotations"]))
        self.assertEqual(len(partial["worker_events"]), 1)
        self.assertTrue(all(validate_sidecar_map(partial, text, blocks, atoms, SC_POLICY, SA_POLICY).values()))
        complete = run_sidecar_workers(text, blocks, atoms, SC_POLICY, canonical_hash(SC_POLICY))
        self.assertEqual(complete["run_status"], "complete")
        self.assertNotEqual(partial, complete)

    def test_tamper_malformed_path_cache_and_version_are_rejected(self):
        text = "ANALYSIS\n[1]\nThe Court finds Smith v. Jones applies.\n"
        blocks, atoms, original = self.make(text)
        mutations = {
            "cache": lambda value: value.update(cache_key="0" * 64),
            "annotation_id": lambda value: value["annotations"][0].update(annotation_id="an-" + "0" * 24),
            "span": lambda value: value["annotations"][0]["span"].update(case_id="999999"),
            "version": lambda value: value.update(worker_bundle_version="forged"),
            "relation_status": lambda value: next((item for item in value["relations"] if item["relation_type"] == "governed_by_heading"), value["relations"][0]).update(status="error"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original); mutate(changed)
                with self.assertRaises(SidecarError): validate_sidecar_map(changed, text, blocks, atoms, SC_POLICY, SA_POLICY)
        for malformed in (None, [], {"bad": True}, {**original, "extra": True}):
            with self.assertRaises(SidecarError): validate_sidecar_map(malformed, text, blocks, atoms, SC_POLICY, SA_POLICY)  # type: ignore[arg-type]
        wrong = Path("cases") / original["case_id"] / original["source_hash"] / original["sourceblock_cache_key"] / original["sentence_atom_cache_key"] / "wrong" / "sidecar_map.json"
        with self.assertRaises(SidecarError): validate_sidecar_map(original, text, blocks, atoms, SC_POLICY, SA_POLICY, artifact_path=wrong)

    def test_source_parent_or_policy_change_invalidates_artifact(self):
        text = "[1]\nThe Court finds otherwise.\n"
        blocks, atoms, original = self.make(text)
        changed_blocks = copy.deepcopy(blocks); changed_blocks["cache_key"] = "0" * 64
        with self.assertRaises(SidecarError): validate_sidecar_map(original, text, changed_blocks, atoms, SC_POLICY, SA_POLICY)
        changed_policy = copy.deepcopy(SC_POLICY); changed_policy["worker_bundle_version"] = "sidecar-rules-v2"
        changed = run_sidecar_workers(text, blocks, atoms, changed_policy, canonical_hash(changed_policy))
        self.assertNotEqual(original["cache_key"], changed["cache_key"])
        self.assertNotEqual(original["annotations"][0]["annotation_id"], changed["annotations"][0]["annotation_id"])

    def test_checked_in_report_uses_counts_not_unjustified_quality_metrics(self):
        report = json.loads((PIPELINE_DIR / "reports/plan05_sidecar_validation.latest.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["case_count"], 5)
        self.assertEqual(report["metrics_not_reported"], ["precision", "recall", "F1"])
        self.assertEqual(report["summary"]["error_event_count"], 0)


if __name__ == "__main__": unittest.main()
