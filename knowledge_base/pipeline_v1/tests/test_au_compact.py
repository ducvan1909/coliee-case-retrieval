import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.au_compact.core import CompactAUError, build_evidence_catalog, build_needs_split_sidecar, normalize_positive, validate_compact


def request(source):
    return {"case_id": "000001", "source_hash": hashlib.sha256(source.encode()).hexdigest(), "request_id": "r-1", "expected_target_ids": ["at-1"], "source_refs": [{"role": "target", "start_char": 0, "end_char": 4, "target_ids": ["at-1"]}, {"role": "context", "start_char": 5, "end_char": len(source), "target_ids": []}]}


def compact(**overrides):
    value = {"request_id": "r-1", "target_id": "at-1", "decision": "positive", "coverage_status": "complete", "hard_negative_reason": None, "unresolved_reason": None, "aus": [{"kind": "holding", "other_kind": None, "claim": "Rule.", "evidence_ref_ids": ["sa-target"], "speaker": "current_court", "attribution_role": "proposition", "needs_context": ["condition"]}]}
    return {**value, **overrides}


class CompactAUTests(unittest.TestCase):
    def binding(self, folder, source, atoms):
        value = {"case_id": "000001", "source_hash": hashlib.sha256(source.encode()).hexdigest(), "segmenter_version": "s1", "policy_sha256": "b" * 64, "atoms": atoms}
        path = Path(folder) / "atoms.json"; path.write_text(json.dumps(value), encoding="utf-8")
        return {"atom_map_path": str(path), "atom_map_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "case_id": value["case_id"], "source_hash": value["source_hash"], "segmenter_version": "s1", "policy_sha256": "b" * 64}

    def test_catalog_expands_target_fragment_to_whole_overlapping_atom(self):
        source = "Rule more context"
        atoms = [{"atom_id": "sa-target", "case_id": "000001", "source_hash": hashlib.sha256(source.encode()).hexdigest(), "span": {"start_char": 0, "end_char": 4}}, {"atom_id": "sa-crosses-gap", "case_id": "000001", "source_hash": hashlib.sha256(source.encode()).hexdigest(), "span": {"start_char": 3, "end_char": 6}}]
        with tempfile.TemporaryDirectory() as folder:
            fragment = {**request(source), "source_refs": [{"role": "target", "start_char": 3, "end_char": 4, "target_ids": ["at-1"]}]}
            expanded = build_evidence_catalog(fragment, self.binding(folder, source, atoms), source)
            catalog = expanded["atoms"]
            self.assertEqual(set(catalog), {"sa-target", "sa-crosses-gap"}); self.assertTrue(catalog["sa-crosses-gap"]["target_intersecting"]); self.assertEqual(expanded["metrics"]["requested_char_union"], 1); self.assertEqual(expanded["metrics"]["rendered_atom_char_union"], 6); self.assertEqual(expanded["metrics"]["expansion_chars"], 5)

    def test_normalizes_one_to_three_aus_from_exact_source_slices(self):
        source = "Rule more context"; digest = hashlib.sha256(source.encode()).hexdigest()
        atoms = [{"atom_id": "sa-target", "case_id": "000001", "source_hash": digest, "span": {"start_char": 0, "end_char": 4}}, {"atom_id": "sa-context", "case_id": "000001", "source_hash": digest, "span": {"start_char": 5, "end_char": 9}}]
        value = compact(coverage_status="needs_split", aus=[compact()["aus"][0], {**compact()["aus"][0], "claim": "Second.", "evidence_ref_ids": ["sa-target", "sa-context"]}])
        with tempfile.TemporaryDirectory() as folder:
            normalized = normalize_positive(value, request(source), self.binding(folder, source, atoms), source)
        aus = normalized["target_results"][0]["authority_units"]
        self.assertEqual(len(aus), 2); self.assertEqual(aus[1]["evidence_spans"][1]["quote"], "more"); self.assertEqual(aus[0]["uncertainty_reasons"], ["missing_condition"])
        sidecar = build_needs_split_sidecar(value, normalized); self.assertEqual(sidecar["normalized_authority_units"], aus)

    def test_rejects_out_of_region_or_context_only_evidence(self):
        source = "Rule more context"; digest = hashlib.sha256(source.encode()).hexdigest()
        atoms = [{"atom_id": "sa-context", "case_id": "000001", "source_hash": digest, "span": {"start_char": 5, "end_char": 9}}]
        with tempfile.TemporaryDirectory() as folder:
            binding = self.binding(folder, source, atoms)
            with self.assertRaises(CompactAUError): normalize_positive(compact(aus=[{**compact()["aus"][0], "evidence_ref_ids": ["sa-missing"]}]), request(source), binding, source)
            with self.assertRaises(CompactAUError): normalize_positive(compact(aus=[{**compact()["aus"][0], "evidence_ref_ids": ["sa-context"]}]), request(source), binding, source)

    def test_unresolved_and_hard_negative_are_validated_but_not_normalized(self):
        source = "Rule more context"
        unresolved = compact(decision="unresolved", coverage_status="needs_split", aus=[], hard_negative_reason=None, unresolved_reason="needs_split")
        hard = compact(decision="hard_negative", coverage_status="complete", aus=[], hard_negative_reason="fact_only", unresolved_reason=None)
        self.assertEqual(validate_compact(unresolved, request(source))["decision"], "unresolved")
        self.assertEqual(validate_compact(hard, request(source))["decision"], "hard_negative")
        with self.assertRaises(CompactAUError): normalize_positive(unresolved, request(source), {}, source)
        self.assertEqual(build_needs_split_sidecar(unresolved)["normalized_authority_units"], [])
