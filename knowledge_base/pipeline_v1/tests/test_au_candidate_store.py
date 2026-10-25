"""Independent offline regressions for the Plan 11 AU candidate store."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from knowledge_base.pipeline_v1.au_candidate_store.__main__ import main as candidate_store_main

from knowledge_base.pipeline_v1.au_candidate_store import build_store


class AUCandidateStoreTests(unittest.TestCase):
    source = "A court must give reasons. Here, it gave reasons. The appeal is dismissed."
    case_id = "013948"
    target_id = "at-1"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_store = self.root / "source-store"
        self.atom_root = self.root / "atoms"
        self.source_hash = hashlib.sha256(self.source.encode("utf-8")).hexdigest()
        self.binding = self._install_case(self.case_id)

    def _install_case(self, case_id):
        source_relative = f"cases/{case_id}/versions/{self.source_hash}"
        source_dir = self.source_store / source_relative
        source_dir.mkdir(parents=True)
        (source_dir / "source.txt").write_text(self.source, encoding="utf-8")
        source_record = {
            "record_type": "CaseSource", "contract_version": "case-source-v1",
            "case_id": case_id, "source_version": f"src-{self.source_hash[:16]}",
            "source_hash": self.source_hash, "text_ref": f"{source_relative}/source.txt",
            "byte_length": len(self.source.encode("utf-8")), "char_length": len(self.source),
            "encoding": "utf-8-sig", "offset_unit": "unicode_codepoint",
            "metadata": {"corpus_split": "calibration", "kos_role": "source", "input_source_path": "synthetic.txt"},
        }
        (source_dir / "case_source.json").write_text(json.dumps(source_record), encoding="utf-8")
        spans = []
        start = 0
        for atom_id, quote in (
            ("sa-rule", "A court must give reasons."),
            ("sa-fact", "Here, it gave reasons."),
            ("sa-disposition", "The appeal is dismissed."),
        ):
            end = start + len(quote)
            spans.append({"atom_id": atom_id, "case_id": case_id, "source_hash": self.source_hash,
                          "span": {"start_char": start, "end_char": end}})
            start = end + 1
        atom_relative = f"cases/{case_id}/atoms.json"
        atom_path = self.atom_root / atom_relative
        atom_path.parent.mkdir(parents=True)
        atom_map = {"case_id": case_id, "source_hash": self.source_hash, "cache_key": "c" * 64,
                    "segmenter_version": "synthetic-v1", "policy_sha256": "p" * 64, "atoms": spans}
        atom_bytes = json.dumps(atom_map, separators=(",", ":")).encode("utf-8")
        atom_path.write_bytes(atom_bytes)
        return {
            "atom_map_relative_path": atom_relative,
            "atom_map_sha256": hashlib.sha256(atom_bytes).hexdigest(),
            "atom_map_cache_key": atom_map["cache_key"], "case_id": case_id,
            "source_hash": self.source_hash, "segmenter_version": "synthetic-v1", "policy_sha256": "p" * 64,
        }

    def request(self, request_id="request-1", source_hash=None, *, case_id=None, binding=None):
        case_id = case_id or self.case_id
        return {
            "case_id": case_id, "source_hash": source_hash or self.source_hash,
            "request_id": request_id, "expected_target_ids": [self.target_id],
            "source_refs": [{"role": "target", "start_char": 0, "end_char": len(self.source),
                             "target_ids": [self.target_id]}],
            "atom_binding": dict(binding or self.binding),
        }

    def au(self, claim="The court must give reasons.", evidence=("sa-rule",), **overrides):
        value = {"kind": "holding", "other_kind": None, "claim": claim,
                 "evidence_ref_ids": list(evidence), "speaker": "current_court",
                 "attribution_role": "proposition", "needs_context": []}
        value.update(overrides)
        return value

    def row(self, request_id="request-1", aus=None, *, decision="positive", source_hash=None,
            case_id=None, binding=None):
        request = self.request(request_id, source_hash, case_id=case_id, binding=binding)
        response = {
            "request_id": request_id, "target_id": self.target_id, "decision": decision,
            "coverage_status": "complete", "aus": list(aus or []),
            "hard_negative_reason": "fact_only" if decision == "hard_negative" else None,
            "unresolved_reason": None,
        }
        return {"request": request, "status": "protocol_verified", "compact_response": response}

    @staticmethod
    def candidates(store):
        for key in ("candidates", "authority_units", "records"):
            value = store.get(key) if isinstance(store, dict) else None
            if isinstance(value, list):
                return value
        raise AssertionError("candidate store result must expose candidate rows")

    def build(self, *reports):
        normalized = []
        for report in reports:
            if "artifact_type" not in report:
                report = {"artifact_type": "AUCompactRun", "schema_version": "au-compact-runtime-v1", **report}
            normalized.append(report)
        return build_store(normalized, self.source_store, self.atom_root)

    def test_source_hash_mismatch_is_rejected(self):
        bad = self.row(source_hash="0" * 64, aus=[self.au()])
        result = self.build({"request_ledger": [bad]})
        self.assertEqual(self.candidates(result)[0]["status"], "rejected")
        self.assertTrue(any("source_or_binding" in error for error in result["target_ledger"][0]["errors"]))
        self.assertEqual(result["audit"]["accepted_count"], 0)

    def test_forged_quote_and_normalized_span_are_rebuilt_from_source(self):
        row = self.row(aus=[self.au(evidence=("sa-rule",))])
        row["normalized_output"] = {"authority_units": [{
            "claim_text": "A court must give reasons.",
            "evidence_spans": [{"start_char": 1, "end_char": 8, "quote": "FORGED QUOTE"}],
        }]}
        result = self.build({"request_ledger": [row]})
        candidate = self.candidates(result)[0]
        evidence = candidate["evidence_spans"]
        self.assertEqual(evidence, [{"case_id": self.case_id, "source_hash": self.source_hash,
                                     "start_char": 0, "end_char": len("A court must give reasons."),
                                     "quote": "A court must give reasons."}])
        self.assertNotIn("FORGED QUOTE", json.dumps(evidence, ensure_ascii=False))

    def test_invalid_evidence_id_is_local_and_does_not_drop_valid_candidate(self):
        good = self.au(claim="The court must give reasons.", evidence=("sa-rule",))
        bad = self.au(claim="Unsupported proposition.", evidence=("made-up-id",))
        candidates = self.candidates(self.build({"request_ledger": [self.row(aus=[bad, good])]}))
        by_claim = {row["proposal"]["claim"]: row for row in candidates if "claim" in row.get("proposal", {})}
        self.assertIn("The court must give reasons.", by_claim)
        self.assertNotIn("made-up-id", json.dumps(by_claim["The court must give reasons."], ensure_ascii=False))
        invalid_candidates = [row for row in candidates if "made-up-id" in json.dumps(row.get("proposal", {}))]
        self.assertEqual(len(invalid_candidates), 1)
        self.assertEqual(invalid_candidates[0]["status"], "rejected")

    def test_unknown_speaker_or_unresolved_context_never_becomes_supported(self):
        unknown_speaker = self.au(claim="Unknown speaker proposition.", speaker="unknown")
        context_needed = self.au(claim="Conditional proposition.", needs_context=["condition"])
        rows = self.candidates(self.build({"request_ledger": [self.row(aus=[unknown_speaker, context_needed])]}))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.get("status", row.get("candidate_status")) == "unresolved" for row in rows))

    def test_no_candidate_or_store_semantic_state_is_ever_accepted(self):
        result = self.build({"request_ledger": [self.row(aus=[self.au()])]})
        serialized = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn('"semantic_verdict": "accepted"', serialized)
        self.assertNotIn('"semantic_status": "accepted"', serialized)
        self.assertNotIn('"status": "accepted"', serialized)
        self.assertIsNot(result.get("semantic_gold"), True)

    def test_exact_duplicates_are_order_independent_superseded_and_keep_provenance(self):
        first = {"request_ledger": [self.row("request-a", [self.au()])]}
        second = {"request_ledger": [self.row("request-b", [self.au()])]}
        forward = self.candidates(self.build(first, second))
        reverse = self.candidates(self.build(second, first))
        self.assertEqual(forward, reverse)
        self.assertEqual(len(forward), 2)
        superseded = [candidate for candidate in forward if candidate["status"] == "superseded"]
        canonical = [candidate for candidate in forward if candidate["status"] != "superseded"]
        self.assertEqual((len(superseded), len(canonical)), (1, 1))
        self.assertEqual(superseded[0]["superseded_by"], canonical[0]["candidate_id"])
        request_ids = {candidate["provenance"]["request_id"] for candidate in forward}
        self.assertEqual(request_ids, {"request-a", "request-b"})

    def test_same_claim_with_different_evidence_remains_distinct(self):
        claim = "A legal proposition stated by the court."
        rows = [self.au(claim=claim, evidence=("sa-rule",)), self.au(claim=claim, evidence=("sa-disposition",))]
        candidates = self.candidates(self.build({"request_ledger": [self.row(aus=rows)]}))
        matching = [candidate for candidate in candidates if candidate["proposal"]["claim"] == claim]
        self.assertEqual(len(matching), 2)
        evidence_spans = {tuple((item["start_char"], item["end_char"], item["quote"])
                                for item in candidate["evidence_spans"]) for candidate in matching}
        self.assertEqual(evidence_spans, {
            ((0, len("A court must give reasons."), "A court must give reasons."),),
            ((len("A court must give reasons.") + 1 + len("Here, it gave reasons.") + 1,
              len(self.source), "The appeal is dismissed."),),
        })

    def test_identical_source_hash_does_not_deduplicate_or_relate_across_case_ids(self):
        second_case_id = "045155"
        second_binding = self._install_case(second_case_id)
        first_case_row = self.row("same-source-case-a", [
            self.au(claim="The court must give reasons.", evidence=("sa-rule",)),
            self.au(claim="The disposition relies on reasons.", evidence=("sa-rule",)),
        ])
        second_case_row = self.row("same-source-case-b", [
            self.au(claim="The court must give reasons.", evidence=("sa-rule",)),
            self.au(claim="The disposition relies on reasons.", evidence=("sa-rule",)),
        ], case_id=second_case_id, binding=second_binding)
        result = self.build({"request_ledger": [first_case_row, second_case_row]})
        candidates = self.candidates(result)

        self.assertEqual(self.source_hash, second_case_row["request"]["source_hash"])
        self.assertEqual(len(candidates), 4)
        self.assertEqual(result["audit"]["superseded_count"], 0)
        self.assertTrue(all(candidate["status"] == "candidate" for candidate in candidates))
        by_case = {case_id: [candidate for candidate in candidates if candidate["case_id"] == case_id]
                   for case_id in (self.case_id, second_case_id)}
        self.assertEqual({case_id: len(rows) for case_id, rows in by_case.items()},
                         {self.case_id: 2, second_case_id: 2})

        for case_id, rows in by_case.items():
            row_ids = {candidate["candidate_id"] for candidate in rows}
            for candidate in rows:
                self.assertEqual(set(candidate["related_candidate_ids"]), row_ids - {candidate["candidate_id"]})
                self.assertTrue(all(next(other for other in candidates if other["candidate_id"] == related)["case_id"] == case_id
                                    for related in candidate["related_candidate_ids"]))

    def test_target_without_au_stays_pending_for_omission_review(self):
        result = self.build({"request_ledger": [self.row(aus=[], decision="hard_negative")]})
        encoded = json.dumps(result, ensure_ascii=False).casefold()
        self.assertIn(self.target_id, encoded)
        self.assertIn("pending", encoded)
        self.assertIsNot(result.get("semantic_gold"), True)

    def test_region_intersection_does_not_claim_a_legal_start_anchor(self):
        result = self.build({"request_ledger": [self.row(aus=[self.au()])]})
        candidate = self.candidates(result)[0]
        encoded = json.dumps(candidate, ensure_ascii=False).casefold()
        self.assertNotIn('"legal_start_status": "verified"', encoded)
        ownership = candidate["ownership"]
        self.assertEqual(ownership["status"], "structural_owner_candidate")
        self.assertFalse(ownership["ownership_verified"])
        self.assertIsNone(ownership["primary_proposition_start"])
        self.assertFalse(ownership["primary_proposition_start_available"])
        self.assertEqual(ownership["ownership_review"], "pending")
        required = {"claim", "kind", "speaker", "attribution_role"}
        witnesses = candidate["field_witnesses"]
        if required.issubset(witnesses):
            for field in required:
                with self.subTest(field=field):
                    self.assertEqual(witnesses[field]["status"], "MODEL_ASSERTED")
                    self.assertEqual(witnesses[field]["semantic_review"], "pending")
                    self.assertIsNone(witnesses[field]["precise_field_span"])
        else:
            self.assertEqual(candidate["status"], "unresolved")

    def test_cli_accepts_repeatable_run_inputs_and_rebuilds_deterministically(self):
        first = {"artifact_type": "AUCompactRun", "schema_version": "au-compact-runtime-v1",
                 "request_ledger": [self.row("request-cli-a", [self.au()])]}
        second = {"artifact_type": "AUCompactRun", "schema_version": "au-compact-runtime-v1",
                  "request_ledger": [self.row("request-cli-b", [self.au()])]}
        runs = [self.root / "run-a.json", self.root / "run-b.json"]
        for path, value in zip(runs, (first, second)):
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        output = self.root / "candidate-output"
        common = ["build", "--source-store", str(self.source_store), "--atom-root", str(self.atom_root),
                  "--output-root", str(output)]
        self.assertEqual(candidate_store_main(common + ["--run", str(runs[0]), "--run", str(runs[1])]), 0)
        first_bytes = ((output / "candidates.json").read_bytes(), (output / "audit.json").read_bytes())
        self.assertEqual(candidate_store_main(common + ["--run", str(runs[1]), "--run", str(runs[0])]), 0)
        second_bytes = ((output / "candidates.json").read_bytes(), (output / "audit.json").read_bytes())
        self.assertEqual(first_bytes, second_bytes)


if __name__ == "__main__":
    unittest.main()
