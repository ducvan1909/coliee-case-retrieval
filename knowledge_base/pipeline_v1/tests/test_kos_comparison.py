"""Implementer regressions; independent tester owns a separate test module."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from knowledge_base.pipeline_v1.kos_comparison import ComparisonError, align_evidence, compare


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = "Rule <script>alert(1)</script>. Other rule."
        self.digest = hashlib.sha256(self.source.encode()).hexdigest()
        self.store = self.root / "source_store"
        version = self.store / "cases/000001/versions" / self.digest
        version.mkdir(parents=True)
        (version / "source.txt").write_bytes(self.source.encode())
        record = {"record_type": "CaseSource", "contract_version": "case-source-v1", "case_id": "000001",
                  "source_version": "src-" + self.digest[:16], "source_hash": self.digest,
                  "text_ref": "cases/000001/versions/" + self.digest + "/source.txt",
                  "byte_length": len(self.source.encode()), "char_length": len(self.source),
                  "encoding": "utf-8-sig", "offset_unit": "unicode_codepoint", "metadata": {"corpus_split": "train", "kos_role": "query", "input_source_path": "fixture.txt"}}
        self.write(version / "case_source.json", record)
        self.write(self.store / "cases/000001/index.json", {"current_source_hash": self.digest})
        self.kos_root = self.root / "kos"
        self.case_dir = self.kos_root / "cases/000001"
        self.case_dir.mkdir(parents=True)
        self.kos_manifest = self.root / "kos_manifest.json"
        self.run_path = self.root / "run_inputs/run.json"
        self.request = {"case_id": "000001", "source_hash": self.digest, "request_id": "r1", "expected_target_ids": ["t1"],
                        "source_refs": [{"role": "target", "start_char": 0, "end_char": len(self.source), "target_ids": ["t1"]}]}
        self.span = {"start_char": 0, "end_char": 30, "quote": self.source[:30]}
        self.au = {"local_au_id": "au1", "claim_text": "Rule.", "kind": "holding", "other_kind": None,
                   "evidence_spans": [self.span], "attributions": [{"role": "proposition", "speaker": "current_court", "evidence_span": self.span}],
                   "condition_spans": [], "exception_spans": [], "limit_spans": [], "candidate_status": "complete", "uncertainty_reasons": []}
        response = {"schema_version": "plan10-au-model-output-v1", "request_id": "r1", "processed_target_ids": ["t1"],
                    "target_results": [{"target_id": "t1", "decision": "positive", "authority_units": [self.au], "hard_negative_reason": None, "unresolved_reason": None, "reason_detail": None}],
                    "context_requests": [], "warnings": []}
        self.run = {"artifact_type": "AUCompactRun", "status": "complete", "selection_request_ids": ["r1"],
                    "request_ledger": [{"request": self.request, "response": response, "compact_response": {"coverage_status": "complete"}, "status": "protocol_verified",
                                        "receipt": {"latency_ms": 10, "usage_state": "provider", "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}}}],
                    "runtime_ledger": {"requests": 2, "provider_attempts": 2, "actual_total_tokens": 30, "usage_unavailable": 1}}
        self.kos("k1", self.source[:30])
        self.freeze_kos()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def kos(self, uid, evidence, kind="holding"):
        (self.case_dir / (uid + ".md")).write_text(
            "---\ntype: authority_unit\nid: " + uid + "\ncase_id: 000001.txt\nkind: " + kind
            + "\npara_idxs: [1]\nissue_ids:\n- reference-only\n---\n\n## Claim\n\nReference claim.\n\n## Evidence span\n\n> " + evidence + "\n", encoding="utf-8")

    def freeze_kos(self):
        files = [{"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "byte_length": len(p.read_bytes())} for p in sorted(self.case_dir.iterdir())]
        digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.write(self.kos_manifest, {"cases": [{"case_id": "000001", "kos_role": "query", "case_path": "cases/000001", "file_count": len(files), "total_bytes": sum(f["byte_length"] for f in files), "tree_sha256": digest}]})

    def report(self, **kwargs):
        self.write(self.run_path, self.run)
        return compare(self.run_path, source_store=self.store, kos_root=self.kos_root, kos_manifest=self.kos_manifest, **kwargs)

    def bind_atoms(self):
        atom_root = self.root / "atoms"
        path = atom_root / "map.json"
        value = {"case_id": "000001", "source_hash": self.digest, "segmenter_version": "test-v1", "policy_sha256": "a" * 64, "cache_key": "test-key",
                 "atoms": [{"atom_id": "read", "case_id": "000001", "source_hash": self.digest, "span": {"start_char": 0, "end_char": 30}},
                           {"atom_id": "unread", "case_id": "000001", "source_hash": self.digest, "span": {"start_char": 31, "end_char": len(self.source)}}]}
        self.write(path, value)
        self.request["atom_binding"] = {"case_id": "000001", "source_hash": self.digest, "segmenter_version": "test-v1", "policy_sha256": "a" * 64,
                                        "atom_map_relative_path": "map.json", "atom_map_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "atom_map_cache_key": "test-key"}
        self.request["source_refs"][0]["end_char"] = 5
        return atom_root

    def test_alignment_repeated_and_whitespace_preserves_offsets(self):
        self.assertEqual(align_evidence("Rule", "Rule Rule")["status"], "ambiguous")
        self.assertEqual(align_evidence("Rule other", "Rule other / Rule\nother")["status"], "ambiguous")
        match = align_evidence("Rule other", "xx Rule\n\tother yy")
        self.assertEqual(match["status"], "whitespace_normalized")
        self.assertEqual(match["spans"], [{"start_char": 3, "end_char": 14, "quote": "Rule\n\tother"}])
        self.assertEqual(align_evidence("missing", "Rule")["spans"], [])
        self.assertEqual(align_evidence("  ", "Rule")["status"], "empty_evidence")

    def test_query_au_kind_difference_and_escaped_html(self):
        self.kos("k1", self.source[:30], "statutory_interpretation")
        self.freeze_kos()
        report = self.report(output_root=self.root / "report")
        self.assertEqual(report["counts"]["kos_au_count"], 1)
        self.assertTrue(report["heuristic_matches"][0]["differences"]["kind"]["different"])
        self.assertFalse(report["semantic_gold"])
        self.assertFalse(report["coverage"]["expected_workload_complete"])
        page = (self.root / "report/comparison.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertEqual(json.loads((self.root / "report/comparison.json").read_text())["counts"], report["counts"])

    def test_raw_hash_tampering_fails_closed(self):
        (self.case_dir / "k1.md").write_text("mutated", encoding="utf-8")
        with self.assertRaisesRegex(ComparisonError, "mismatch"):
            self.report()

    def test_source_hash_tampering_fails(self):
        source_file = next(self.store.glob("cases/*/versions/*/source.txt"))
        source_file.write_bytes(b"mutated")
        with self.assertRaises(ValueError):
            self.report()

    def test_raw_or_invalid_normalized_au_not_promoted(self):
        self.run["request_ledger"][0]["response"]["target_results"][0]["authority_units"][0]["evidence_spans"][0]["quote"] = "invented"
        self.run["request_ledger"][0]["compact_response"]["aus"] = [{"claim": "raw claim"}]
        report = self.report()
        self.assertEqual(report["counts"]["validated_model_au_count"], 0)
        self.assertEqual(report["targets"][0]["status"], "invalid_or_unresolved")
        self.assertEqual(report["kos_units"][0]["comparison_status"], "not_assessable_partial_or_unresolved_coverage")

    def test_malformed_raw_list_and_normalized_payload_preserve_other_valid_rows(self):
        valid = self.run["request_ledger"][0]
        valid["compact_response"] = ["malformed raw transport output"]
        invalid = copy.deepcopy(valid)
        invalid["request"].update(request_id="r2", expected_target_ids=["t2"])
        invalid["request"]["source_refs"][0]["target_ids"] = ["t2"]
        self.run["request_ledger"].append(invalid)
        self.run["selection_request_ids"].append("r2")
        malformed_responses = [
            {"target_results": ["malformed normalized target"]},
            {**copy.deepcopy(valid["response"]), "target_results": ["malformed normalized target"]},
            ["malformed normalized envelope"],
        ]
        for payload in malformed_responses:
            with self.subTest(payload=payload):
                invalid["response"] = payload
                report = self.report()
                self.assertEqual(report["counts"]["validated_model_au_count"], 1)
                self.assertEqual(report["model_units"][0]["request_id"], "r1")
                self.assertFalse(report["request_states"][0]["needs_split"])
                self.assertTrue(report["request_states"][1]["validation_errors"])
                self.assertEqual(report["targets"][1]["status"], "invalid_or_unresolved")

    def test_context_only_au_not_validated(self):
        self.request["source_refs"] = [{"role": "target", "start_char": 31, "end_char": len(self.source), "target_ids": ["t1"]}, {"role": "context", "start_char": 0, "end_char": 30, "target_ids": []}]
        report = self.report()
        self.assertEqual(report["counts"]["validated_model_au_count"], 0)
        self.assertIn("normalized_au_evidence_is_context_only_or_wrong_target", report["request_states"][0]["validation_errors"])

    def test_needs_split_and_unresolved_do_not_become_missing(self):
        self.kos("k1", self.source[31:])
        self.freeze_kos()
        self.run["request_ledger"][0]["compact_response"]["coverage_status"] = "needs_split"
        report = self.report()
        self.assertEqual(report["targets"][0]["status"], "needs_split")
        self.assertEqual(report["kos_units"][0]["comparison_status"], "not_assessable_partial_or_unresolved_coverage")
        self.run["request_ledger"][0]["response"]["target_results"][0].update(decision="unresolved", authority_units=[], unresolved_reason="other")
        self.run["request_ledger"][0]["compact_response"]["coverage_status"] = "complete"
        self.assertEqual(self.report()["targets"][0]["status"], "unresolved")

    def test_missing_is_only_reference_difference_after_covered_evidence(self):
        self.kos("k1", self.source[31:])
        self.freeze_kos()
        self.assertEqual(self.report()["kos_units"][0]["comparison_status"], "missing_reference_in_covered_evidence")

    def test_expected_workload_and_unrun_target(self):
        self.request["source_refs"][0]["end_char"] = 30
        second = {**copy.deepcopy(self.request), "request_id": "r2", "expected_target_ids": ["t2"],
                  "source_refs": [{"role": "target", "start_char": 31, "end_char": len(self.source), "target_ids": ["t2"]}]}
        workload = self.root / "workload.json"
        self.write(workload, {"requests": [self.request, second], "milestone1": {"policy": "test"}})
        report = self.report(workload_manifest=workload)
        self.assertEqual(report["coverage"]["expected_target_count"], 2)
        self.assertEqual(report["coverage"]["pending_or_unrun_request_ids"], ["r2"])
        self.assertFalse(report["coverage"]["expected_workload_complete"])
        self.assertEqual(report["coverage"]["target_status_counts"], {"covered": 1, "unrun": 1})
        self.write(workload, {"requests": [self.request]})
        self.assertTrue(self.report(workload_manifest=workload)["coverage"]["expected_workload_complete"])
        second["request_id"] = "r1"
        self.write(workload, {"requests": [second]})
        with self.assertRaisesRegex(ComparisonError, "does not match"):
            self.report(workload_manifest=workload)

    def test_split_merge_candidates_preserve_individual_aus(self):
        second = {**copy.deepcopy(self.au), "local_au_id": "au2"}
        self.run["request_ledger"][0]["response"]["target_results"][0]["authority_units"].append(second)
        self.assertEqual(self.report()["split_merge_candidates"][0]["relation"], "possible_split")
        self.kos("k2", self.source[:30])
        self.freeze_kos()
        report = self.report()
        self.assertEqual(report["split_merge_candidates"][0]["relation"], "many_to_many")
        self.assertEqual(report["counts"]["heuristic_candidate_pair_count"], 4)

    def test_historic_pilot_namespace_not_credited_as_full_workload(self):
        expected = copy.deepcopy(self.request)
        expected.update(request_id="m1-r1", expected_target_ids=["m1-t1"])
        expected["source_refs"][0]["target_ids"] = ["m1-t1"]
        workload = self.root / "workload.json"
        self.write(workload, {"requests": [expected]})
        report = self.report(workload_manifest=workload)
        self.assertEqual(report["coverage"]["unexpected_actual_request_ids"], ["r1"])
        self.assertEqual(report["coverage"]["expected_target_status_counts"], {"unrun": 1})
        self.assertFalse(report["coverage"]["expected_workload_complete"])
        self.assertEqual(report["counts"]["validated_model_au_count"], 1)

    def test_duplicate_target_and_response_ownership_rejected(self):
        row = copy.deepcopy(self.run["request_ledger"][0])
        row["request"]["request_id"] = "r2"
        self.run["request_ledger"].append(row)
        with self.assertRaisesRegex(ComparisonError, "duplicate actual target"):
            self.report()
        self.run["request_ledger"].pop()
        self.run["request_ledger"][0]["response"]["request_id"] = "wrong"
        self.assertEqual(self.report()["counts"]["validated_model_au_count"], 0)

    def test_cost_retains_failure_resume_history_without_double_count(self):
        history = self.run_path.parent / "cache/prefix/job-key/attempt_history/failure.json"
        self.write(history, {"prior": {"request": self.request, "status": "unresolved", "receipt": {"usage_state": "unavailable", "latency_ms": 12}}})
        report = self.report()
        self.assertEqual(report["cost"]["runtime_ledger"]["actual_total_tokens"], 30)
        self.assertEqual(report["cost"]["observed_receipt_latency_ms"], 22)
        self.assertEqual(len(report["cost"]["superseded_attempts"]), 1)

    def test_exact_same_case_quote_outside_request_is_not_promoted(self):
        self.request["source_refs"][0]["end_char"] = 5
        report = self.report()
        self.assertEqual(report["counts"]["validated_model_au_count"], 0)
        self.assertIn("normalized_evidence_outside_supplied_catalog", report["request_states"][0]["validation_errors"])

    def test_absent_query_reference_is_not_false_positive(self):
        (self.case_dir / "k1.md").unlink()
        (self.case_dir / "CASE.md").write_text("---\ntype: case\nrole: query\n---\n", encoding="utf-8")
        self.freeze_kos()
        report = self.report()
        self.assertEqual(report["model_units"][0]["comparison_status"], "no_reference_annotation")

    def test_optional_binding_or_reference_identity_tamper_rejected(self):
        self.request["atom_binding"] = {"case_id": "000002"}
        report = self.report()
        self.assertEqual(report["counts"]["validated_model_au_count"], 0)
        self.assertIn("atom binding case/hash", report["request_states"][0]["validation_errors"][0])
        self.request.pop("atom_binding")
        self.request["source_refs"][0]["source_hash"] = "f" * 64
        with self.assertRaisesRegex(ComparisonError, "source ref case/hash"):
            self.report()

    def test_bound_whole_atom_expansion_accepted_without_free_expansion(self):
        atom_root = self.bind_atoms()
        report = self.report(atom_root=atom_root)
        self.assertEqual(report["counts"]["validated_model_au_count"], 1)
        scope = report["request_states"][0]["evidence_scope"]
        self.assertTrue(scope["expansion_verified"])
        self.assertEqual([s["atom_id"] for s in scope["atom_spans"]], ["read"])
        unread = {"start_char": 31, "end_char": len(self.source), "quote": self.source[31:]}
        self.au["attributions"][0]["evidence_span"] = unread
        report = self.report(atom_root=atom_root)
        self.assertEqual(report["counts"]["validated_model_au_count"], 0)
        self.assertIn("normalized_evidence_outside_supplied_catalog", report["request_states"][0]["validation_errors"])

    def test_catalog_binding_failure_does_not_fallback_or_abort_report(self):
        atom_root = self.bind_atoms()
        self.request["atom_binding"]["atom_map_sha256"] = "f" * 64
        report = self.report(atom_root=atom_root)
        self.assertEqual(report["counts"]["validated_model_au_count"], 0)
        self.assertEqual(report["request_states"][0]["evidence_scope"]["status"], "invalid_binding")
        self.assertIn("atom map sha mismatch", report["request_states"][0]["validation_errors"][0])

    def test_all_auxiliary_spans_and_context_anchors_use_catalog(self):
        atom_root = self.bind_atoms()
        unread = {"start_char": 31, "end_char": len(self.source), "quote": self.source[31:]}
        for field in ("condition_spans", "exception_spans", "limit_spans"):
            with self.subTest(field=field):
                self.au[field] = [unread]
                self.assertEqual(self.report(atom_root=atom_root)["counts"]["validated_model_au_count"], 0)
                self.au[field] = []
        self.run["request_ledger"][0]["response"]["context_requests"] = [{"target_id": "t1", "au_local_id": "au1", "obligation_type": "condition", "direction": "after", "anchor_span": unread, "reason": "Missing condition"}]
        self.assertIn("context_anchor_outside_supplied_catalog", self.report(atom_root=atom_root)["request_states"][0]["validation_errors"])

    def test_legacy_no_binding_expansion_is_explicitly_unproven(self):
        report = self.report()
        self.assertEqual(report["request_states"][0]["evidence_scope"]["status"], "legacy_raw_refs_fallback")
        self.assertFalse(report["request_states"][0]["evidence_scope"]["expansion_verified"])

    def test_real_positive_compact_smoke_reconstructs_catalog(self):
        pipeline = Path(__file__).resolve().parents[1]
        report = compare(pipeline / "outputs/au_compact_kos5_20261010_233056/run.json",
                         source_store=pipeline / "evaluation/runtime/source_store_plan02",
                         kos_root="G:/Legal-AI/kos_sample", kos_manifest=pipeline / "manifests/selected_kos_manifest.v1.json")
        self.assertGreater(report["counts"]["validated_model_au_count"], 0)
        self.assertEqual(report["counts"]["validated_model_au_count"], 5)
        self.assertTrue(all(m["evidence_scope_status"] == "bound_atom_catalog_verified" for m in report["model_units"]))

    def test_named_semantic_smoke_has_no_positive_au_to_invent(self):
        pipeline = Path(__file__).resolve().parents[1]
        report = compare(pipeline / "outputs/au_semantic_20261011_095645/run.json",
                         source_store=pipeline / "evaluation/runtime/source_store_plan02",
                         kos_root="G:/Legal-AI/kos_sample", kos_manifest=pipeline / "manifests/selected_kos_manifest.v1.json")
        self.assertEqual(report["targets"][0]["decision"], "hard_negative")
        self.assertEqual(report["request_states"][0]["validation_errors"], [])
        self.assertEqual(report["counts"]["validated_model_au_count"], 0)

    def test_refuses_history_or_kos_output_and_existing_directory(self):
        for path in (self.kos_root / "report", self.run_path.parent / "comparison", self.store / "comparison"):
            with self.assertRaisesRegex(ComparisonError, "protected"):
                self.report(output_root=path)
        self.report(output_root=self.root / "new_report")
        with self.assertRaisesRegex(ComparisonError, "new directory"):
            self.report(output_root=self.root / "new_report")

    def test_unsupported_yaml_explicit_parse_error(self):
        path = self.case_dir / "k1.md"
        path.write_text(path.read_text().replace("kind: holding", "kind: holding\nattribution:\n  speaker: party"), encoding="utf-8")
        self.freeze_kos()
        report = self.report()
        self.assertEqual(report["counts"]["kos_parse_error_count"], 1)
        self.assertEqual(report["counts"]["kos_au_count"], 0)
        self.assertIn("unsupported nested YAML", report["kos_parse_errors"][0]["error"])

    def test_cli_materializes_new_reports(self):
        self.write(self.run_path, self.run)
        output = self.root / "cli_report"
        process = subprocess.run([sys.executable, "-m", "knowledge_base.pipeline_v1.kos_comparison", "compare", "--run", str(self.run_path), "--source-store", str(self.store), "--kos-root", str(self.kos_root), "--kos-manifest", str(self.kos_manifest), "--output-root", str(output)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["status"], "materialized")
        self.assertTrue((output / "comparison.html").is_file())


if __name__ == "__main__":
    unittest.main()
