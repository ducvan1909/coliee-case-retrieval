"""Capacity gating before dispatch; no provider or source/corpus calls."""
import tempfile
import unittest
from unittest.mock import patch

from knowledge_base.pipeline_v1.repair_agent.formal_probe import synthetic_task
from knowledge_base.pipeline_v1.repair_agent.runtime import MockAdapter, preflight, run_arm


def manifest(count):
    task = synthetic_task(count)
    return {"tasks": [task], "manifest_sha256": "synthetic-capacity",
            "source_workload": [{"case_id": task["case_id"]}],
            "task_case_ids": [task["case_id"]], "task_workload": "synthetic"}


class RelationPreflightTests(unittest.TestCase):
    def test_preflight_flags_capacity_independently_from_token_budget(self):
        for arm in ("R1", "R2"):
            with self.subTest(arm=arm), patch(
                    "knowledge_base.pipeline_v1.repair_agent.runtime.verify_manifest", return_value=True):
                report = preflight(manifest(7), arm)
                self.assertEqual("unsupported_workload", report["status"])
                self.assertEqual("decision_relation_limit_exceeded", report["decoder_errors"][0]["status"])
                self.assertEqual(7, report["decoder_errors"][0]["proposal_count"])
                self.assertEqual("not_dispatchable", report["decoder_errors"][0]["execution"])

    def test_run_without_cli_preflight_cannot_dispatch_overflow(self):
        for arm in ("R1", "R2"):
            adapter = MockAdapter()
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as root, patch(
                    "knowledge_base.pipeline_v1.repair_agent.runtime.verify_manifest", return_value=True):
                with self.assertRaisesRegex(ValueError, "^decision_relation_limit_exceeded$"):
                    run_arm(manifest(7), arm, root, adapter)
            self.assertEqual(0, adapter.calls)

    def test_zero_and_six_proposals_and_non_model_baseline_are_not_blocked(self):
        with patch("knowledge_base.pipeline_v1.repair_agent.runtime.verify_manifest", return_value=True):
            for count, arm in ((0, "R2"), (6, "R1"), (7, "R0")):
                with self.subTest(count=count, arm=arm):
                    report = preflight(manifest(count), arm)
                    self.assertFalse(report["decoder_errors"])
                    self.assertEqual("pass", report["status"])


if __name__ == "__main__":
    unittest.main()
