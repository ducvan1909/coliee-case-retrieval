"""Implementer FORMAL smoke; mock transport is never decoder evidence."""
import copy
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.repair_agent.core import MODEL, POLICY
from knowledge_base.pipeline_v1.repair_agent.formal_probe import (
    fixtures, remote_cases, run_formal_probe, aggregate_reports, synthetic_task,
    envelope, validate_output, selection_fixture,
)

CFG = dict(model=MODEL, jobs_url="https://example.invalid/v1/jobs", token="synthetic")
ADAPTER = "knowledge_base.pipeline_v1.repair_agent.adapter.JobsAdapter"


def _selection(out):
    count = len(out['tool_calls'][0]['arguments'].get('decisions', [])) or 1
    return selection_fixture(dict(output=out, task=synthetic_task(count),
        target_path=['tool_calls', 0, 'name'], case_id='test'))['output']


class FormalProbeTests(unittest.TestCase):
    def test_all_fixtures_expected_host_results(self):
        ids = set()
        for fixture in fixtures():
            with self.subTest(case_id=fixture["case_id"]):
                self.assertNotIn(fixture["case_id"], ids); ids.add(fixture["case_id"])
                check = validate_output(fixture["output"], fixture["task"], fixture["arm"], fixture["turn"])
                self.assertEqual(fixture["expected_valid"], check["valid"], check)
        self.assertEqual(ids, {r["case_id"] for r in remote_cases()})

    def test_offline_no_dispatch_diagnostics_and_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(ADAPTER, side_effect=AssertionError("offline dispatch")):
                report = run_formal_probe(Path(tmp), case_ids=["reason_length_121"])
            self.assertEqual("prepared", report["status"])
            self.assertEqual(0, report["cost_summary"]["attempts"])
            self.assertEqual("pass", report["host_check_status"])
            self.assertTrue((Path(tmp) / "formal-suite-probe.json").exists())
            check = next(r for r in report["host_checks"] if r["case_id"] == "reason_length_121")
            errors = check["schema_errors"]
            self.assertTrue(any(e["validator"] == "maxLength" and e["path"][-1] == "reason" for e in errors))
            self.assertTrue(all("message" in e and "schema_path" in e for e in errors))
            self.assertEqual("unverified", report["backend_compilation"])

    def test_invalid_selection_and_cap_before_adapter(self):
        with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
            for ids, cap in [(["unknown"], 8), ([], 8), (["uncertain_reject"] * 2, 8), (None, 9), (None, 0)]:
                with self.assertRaises(ValueError): run_formal_probe(tmp, CFG, ids, cap)
            adapter.assert_not_called()

    def test_remote_invalid_request_still_requires_full_host_validation(self):
        out = envelope(synthetic_task())
        out["tool_calls"][0]["arguments"]["decisions"][0]["reason"] = "x" * 121
        response = dict(output=_selection(out), provider_usage=dict(total_tokens=20, prompt_tokens=10, completion_tokens=10))
        with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
            adapter.return_value.return_value = response
            report = run_formal_probe(tmp, CFG, ["reason_length_121"])
            self.assertEqual("failed", report["cases"][0]["status"])
            self.assertTrue(report["cases"][0]["validation"]["schema_errors"])
            self.assertEqual(1, report["cost_summary"]["attempts"])
            self.assertEqual(20, report["cost_summary"]["charged_or_reserved_tokens"])

    def test_valid_uncertain_cannot_cover_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
            adapter.return_value.return_value = dict(output=_selection(envelope(synthetic_task(2))), provider_usage=None)
            report = run_formal_probe(tmp, CFG, ["duplicate_2_anchor"])
            self.assertEqual("protocol_valid", report["cases"][0]["status"])
            self.assertEqual("uncovered", report["cases"][0]["branch_status"])
            self.assertEqual("incomplete", aggregate_reports([report])["status"])

    def test_caps_failure_accounting_and_unique_attempt_binding(self):
        ids = ["reason_length_1", "reason_length_120"]
        reports = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
                adapter.return_value.return_value = dict(output=None, provider_usage=None)
                report = run_formal_probe(tmp, CFG, ids, max_requests=1)
                self.assertEqual(1, adapter.return_value.call_count)
                self.assertEqual(1, report["cost_summary"]["attempts"])
                self.assertEqual(1, report["cost_summary"]["provider_usage_unknown_attempts"])
                self.assertLessEqual(report["cost_summary"]["charged_or_reserved_tokens"], POLICY["total_tokens"])
                self.assertIn(ids[1], report["unrun_case_ids"])
                reports.append(report)
        self.assertNotEqual(reports[0]["cases"][0]["attempt_id"], reports[1]["cases"][0]["attempt_id"])
        self.assertEqual(2, aggregate_reports(reports)["remote_attempts"])

    def test_forced_action_checked_even_with_mock_valid_output(self):
        out = envelope(synthetic_task(), "defect_found", "reject")
        with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
            adapter.return_value.return_value = dict(output=_selection(out), provider_usage=None)
            report = run_formal_probe(tmp, CFG, ["claim_length_1"])
            self.assertEqual("failed", report["cases"][0]["status"])
            self.assertEqual("probe_branch_mismatch", report["cases"][0]["validation"]["forced_branch_error"])

    def test_actual_usage_cap_stops_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
            adapter.return_value.return_value = dict(output=_selection(envelope(synthetic_task())), provider_usage=dict(total_tokens=22000, prompt_tokens=21000, completion_tokens=1000))
            report = run_formal_probe(tmp, CFG, ["uncertain_reject", "reason_length_1"])
            self.assertTrue(report["cases"][0]["actual_usage_cap_violation"])
            self.assertEqual(1, adapter.return_value.call_count)
            self.assertEqual(22000, report["cost_summary"]["charged_or_reserved_tokens"])

    def test_synthetic_offsets_quotes_use_existing_tools(self):
        by_id = {f["case_id"]: f for f in fixtures()}
        for cid in ("offset_outside_end", "offset_wrong_quote", "supported_wrong_quote"):
            f = by_id[cid]
            check = validate_output(f["output"], f["task"], f["arm"], f["turn"])
            self.assertFalse(check["valid"])
            self.assertEqual([], check["schema_errors"])
            self.assertIsNotNone(check["host_error"])

    def test_selected_complete_global_incomplete_and_unique_host_count(self):
        with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
            adapter.return_value.return_value = dict(output=_selection(envelope(synthetic_task())), provider_usage=None)
            report = run_formal_probe(tmp, CFG, ["uncertain_reject"])
            self.assertEqual("complete", report["selected_batch_status"])
            self.assertEqual("complete", report["status"])
            self.assertEqual("incomplete", report["global_suite_status"])
            aggregate = aggregate_reports([report, report])
            self.assertEqual("incomplete", aggregate["status"])
            self.assertEqual(len(fixtures()), aggregate["host_check_count"])
            self.assertEqual(2 * len(fixtures()), aggregate["host_check_executions"])

    def test_invalid_one_anchor_duplicate_is_challenge_not_impossible_answer(self):
        with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
            adapter.return_value.return_value = dict(output=_selection(envelope(synthetic_task())), provider_usage=None)
            report = run_formal_probe(tmp, CFG, ["duplicate_1_anchor"])
            row = report["cases"][0]
            self.assertEqual("complete", report["status"])
            self.assertEqual("covered", row["branch_status"])
            self.assertEqual("uncovered", row["target_branch_status"])
            self.assertEqual("unverified", row["grammar_enforcement"])

    def test_aggregate_cli_prepared_only_returns_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_formal_probe(root / "local", case_ids=["uncertain_reject"])
            result = subprocess.run([sys.executable, "-m", "knowledge_base.pipeline_v1.repair_agent",
                                     "formal-suite-aggregate", "--report", str(root / "local" / "formal-suite-probe.json"),
                                     "--output-root", str(root / "aggregate")], capture_output=True, text=True)
            self.assertEqual(3, result.returncode, result.stdout + result.stderr)
            self.assertTrue((root / "aggregate" / "formal-suite-aggregate.json").exists())


if __name__ == "__main__":
    unittest.main()
