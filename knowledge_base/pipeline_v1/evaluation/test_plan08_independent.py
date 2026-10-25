from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.execution_ledger import ExecutionError, validate_snapshot
from knowledge_base.pipeline_v1.execution_ledger.build import load_plan07_workloads, validate_build_history, validate_current_pointer


P = Path(__file__).resolve().parents[1]


class Plan08IndependentEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((P / "reports/plan08_execution_validation.latest.json").read_text(encoding="utf-8"))
        cls.root = Path(cls.report["outputs"]["output_root"])
        cls.manifest = json.loads(Path(cls.report["outputs"]["build_manifest"]).read_text(encoding="utf-8"))
        cls.policy = json.loads((P / "policies/execution_policy.v1.json").read_text(encoding="utf-8"))
        cls.workloads, _, _ = load_plan07_workloads(P / "reports/plan07_analysis_region_validation.latest.json")

    def test_recompute_inventory_terminal_states_and_projection(self):
        cold = self.manifest["scenarios"]["cold_success_and_exact_resume"]
        snapshot = json.loads((self.root / cold["snapshot_ref"]).read_text(encoding="utf-8"))
        checks = validate_snapshot(snapshot, self.workloads, self.policy, attempt_log_path=self.root / cold["attempt_log_ref"], cache_root=self.root / "scenarios/cold_success/cache")
        self.assertEqual((checks["target_count"], checks["request_inventory_count"], checks["attempt_count"]), (369, 96, 96))
        self.assertEqual({e["state"] for e in snapshot["coverage_entries"]}, {"mock_protocol_verified"})
        self.assertTrue(all(e["protocol_only"] is True for e in snapshot["coverage_entries"]))
        serialized = json.dumps(snapshot)
        for forbidden in ('"complete"', '"no_au"', '"semantic_complete"'):
            self.assertNotIn(forbidden, serialized)
        projection = [json.loads(x) for x in (self.root / cold["attempt_log_ref"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(projection, snapshot["attempts"])

    def test_recompute_cold_resume_retry_failure_budget_metrics(self):
        rows = self.manifest["scenarios"]
        cold = rows["cold_success_and_exact_resume"]
        self.assertEqual((cold["cold_invocation"]["provider_calls"], cold["exact_resume_invocation"]["provider_calls"], cold["exact_resume_invocation"]["skipped_verified_requests"]), (96, 0, 96))
        self.assertEqual((cold["summary"]["rendered_chars_avoided"], cold["summary"]["estimated_input_tokens_avoided"]), (342095, 85559))
        interrupted = rows["interrupt_resume"]
        self.assertEqual((interrupted["interrupted_invocation"]["provider_calls"], interrupted["resume_invocation"]["provider_calls"], interrupted["resume_invocation"]["skipped_verified_requests"]), (7, 89, 7))
        self.assertEqual(rows["transient_retry"]["summary"]["attempt_count"], 97)
        self.assertEqual(rows["transient_retry"]["summary"]["useful_retry_count"], 1)
        self.assertEqual(rows["permanent_failure"]["summary"]["status_counts"], {"error": 4, "mock_protocol_verified": 365})
        self.assertEqual(rows["budget_stop"]["summary"]["status_counts"], {"budget_exhausted": 349, "mock_protocol_verified": 20})

    def test_snapshot_reader_fails_closed_on_state_metric_and_projection_tamper(self):
        row = self.manifest["scenarios"]["cold_success_and_exact_resume"]
        snapshot = json.loads((self.root / row["snapshot_ref"]).read_text(encoding="utf-8"))
        for mutation in ("coverage", "transition", "summary", "fingerprint"):
            bad = copy.deepcopy(snapshot)
            if mutation == "coverage": bad["coverage_entries"].pop()
            elif mutation == "transition": bad["coverage_entries"][0]["transition_events"][0]["from_state"] = "error"
            elif mutation == "summary": bad["summary"]["provider_calls"] += 1
            else: bad["requests"][0]["input_fingerprint"] = "0" * 64
            with self.subTest(mutation=mutation), self.assertRaises(ExecutionError): validate_snapshot(bad, self.workloads, self.policy)
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "attempts.jsonl"; log.write_text("{\"truncated\":\n", encoding="utf-8")
            with self.assertRaises(ExecutionError): validate_snapshot(snapshot, self.workloads, self.policy, attempt_log_path=log)

    def test_current_pointer_and_history_manifest_are_current(self):
        current = validate_current_pointer(self.root)
        history = validate_build_history(self.root)
        self.assertEqual(current["current_build_id"], self.report["summary"]["current_build_id"])
        self.assertEqual(history, {"history_count": 1, "history_valid": True})

    def test_archived_history_rejects_missing_or_modified_scenario_artifacts(self):
        index = json.loads((self.root / "history/index.json").read_text(encoding="utf-8"))
        build = index["builds"][0]; archived_root = self.root / "history" / build["build_id"]
        archived_manifest = json.loads((archived_root / "execution_suite_manifest.json").read_text(encoding="utf-8"))
        scenario = next(iter(archived_manifest["scenarios"].values()))
        for kind, ref, mutation in (("snapshot", scenario["snapshot_ref"], "missing"), ("snapshot", scenario["snapshot_ref"], "modified"),
                                    ("snapshot", scenario["snapshot_ref"], "truncated"), ("attempt_log", scenario["attempt_log_ref"], "missing"),
                                    ("attempt_log", scenario["attempt_log_ref"], "modified")):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d); shutil.copytree(self.root / "history", root / "history")
                copied = root / "history" / build["build_id"] / ref
                if mutation == "missing": copied.unlink()
                elif mutation == "truncated": copied.write_bytes(copied.read_bytes()[:-1])
                else: copied.write_text('{"tampered":true}\n', encoding="utf-8")
                with self.subTest(kind=kind, mutation=mutation), self.assertRaises(ValueError):
                    validate_build_history(root)

    def test_archive_inventory_exact_and_legacy_provenance_is_not_sealed_current(self):
        index = json.loads((self.root / "history/index.json").read_text(encoding="utf-8")); self.assertEqual(len(index["builds"]), 1)
        row = index["builds"][0]; archive = self.root / "history" / row["build_id"]
        record = json.loads((archive / "archive_record.json").read_text(encoding="utf-8"))
        refs = [x["path"] for x in record["payload_inventory"]]
        actual = sorted(p.relative_to(archive).as_posix() for p in archive.rglob("*") if p.is_file() and p.name != "archive_record.json")
        self.assertEqual(len(refs), 594); self.assertEqual(sorted(refs), actual); self.assertEqual(len(refs), len(set(refs)))
        self.assertEqual(record["provenance"]["mode"], "legacy-payload-inventory-migration-v1")
        self.assertTrue(record["provenance"]["tamper_detection_begins_at_migration"])
        legacy = self.root / "history" / record["provenance"]["preinventory_evidence_ref"]
        self.assertTrue(legacy.is_dir())
        pointer = json.loads((self.root / "current.json").read_text(encoding="utf-8"))
        self.assertNotIn("history/", pointer["build_manifest_ref"])
        self.assertNotEqual(legacy.resolve(), (self.root / pointer["build_manifest_ref"]).resolve())

        for mutation in ("unexpected_file", "duplicate_inventory", "path_escape", "ref_current"):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d); shutil.copytree(self.root / "history", root / "history"); a = root / "history" / row["build_id"]
                rec_path = a / "archive_record.json"; rec = json.loads(rec_path.read_text(encoding="utf-8")); idx_path = root / "history/index.json"; idx = json.loads(idx_path.read_text(encoding="utf-8"))
                if mutation == "unexpected_file": (a / "unexpected.json").write_text("{}", encoding="utf-8")
                else:
                    if mutation == "duplicate_inventory": rec["payload_inventory"].append(copy.deepcopy(rec["payload_inventory"][0]))
                    elif mutation == "path_escape": rec["payload_inventory"][0]["path"] = "../escape.json"
                    else: rec["manifest_ref"] = "../../execution_suite_manifest.json"
                    rec_path.write_text(json.dumps(rec), encoding="utf-8")
                    import hashlib
                    idx["builds"][0]["archive_record_sha256"] = hashlib.sha256(rec_path.read_bytes()).hexdigest(); idx_path.write_text(json.dumps(idx), encoding="utf-8")
                with self.subTest(mutation=mutation), self.assertRaises(ValueError): validate_build_history(root)


if __name__ == "__main__":
    unittest.main()
