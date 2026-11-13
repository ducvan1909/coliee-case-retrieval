"""Runner safety: preparation, drift and recovery without a provider call."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2 import m6_live


class M6RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "run"
        self.settings = {
            "query_id": "A.txt", "tokenizer_dir": "tokenizer", "byte_budget": 2048,
            "map_limit": 5, "adaptive_config": {}, "budget": {
                "max_requests": 8, "max_actions": 8, "max_input_tokens": 32000,
                "max_payload_tokens": 4096, "max_output_tokens": 512,
                "max_total_tokens": 36096, "max_retries": 0,
            },
        }

    def runtime(self, harness=None, binding=None):
        @contextmanager
        def fake(*args):
            yield harness or SimpleNamespace(prepare=lambda: {"status": "ready", "input_tokens": 10}), SimpleNamespace(receipts=[]), binding or {"identity": "frozen"}
        return fake

    def test_prepare_freezes_plan_without_executing_harness(self):
        class NoSend:
            def prepare(self):
                return {"status": "ready", "input_tokens": 10}
            def run(self):
                raise AssertionError("prepare must never execute")
        with patch.object(m6_live, "_runtime", self.runtime(NoSend())):
            plan = m6_live.prepare(self.root, self.run_dir, self.settings)
        self.assertEqual(plan["model_requests"], 0)
        self.assertFalse(plan["baseline_available"])
        self.assertEqual(plan["selection_status"], "pending_selection")
        self.assertTrue((self.run_dir / "plan.json").is_file())
        with self.assertRaises(HarnessError):
            m6_live.prepare(self.root, self.run_dir, self.settings)

    def test_missing_budget_field_is_rejected_before_opening_runtime(self):
        del self.settings["budget"]["max_retries"]
        with patch.object(m6_live, "_runtime") as runtime:
            with self.assertRaises(HarnessError):
                m6_live.prepare(self.root, self.run_dir, self.settings)
            runtime.assert_not_called()

    def test_binding_drift_blocks_send(self):
        with patch.object(m6_live, "_runtime", self.runtime()):
            m6_live.prepare(self.root, self.run_dir, self.settings)
        harness = SimpleNamespace(run=lambda: self.fail("must reject drift before send"))
        with patch.object(m6_live, "_runtime", self.runtime(harness, {"identity": "changed"})):
            with self.assertRaises(HarnessError):
                m6_live.run(self.root, self.run_dir)

    def test_unfit_or_modified_preview_blocks_send(self):
        unfit = SimpleNamespace(prepare=lambda: {"status": "unfit", "input_tokens": None})
        with patch.object(m6_live, "_runtime", self.runtime(unfit)):
            m6_live.prepare(self.root, self.run_dir, self.settings)
        with patch.object(m6_live, "_runtime") as runtime:
            with self.assertRaises(HarnessError):
                m6_live.run(self.root, self.run_dir)
            runtime.assert_not_called()
        second = self.root / "second"
        with patch.object(m6_live, "_runtime", self.runtime()):
            m6_live.prepare(self.root, second, self.settings)
        (second / "first_payload.json").write_text('{}', encoding="utf-8")
        with patch.object(m6_live, "_runtime") as runtime:
            with self.assertRaises(HarnessError):
                m6_live.run(self.root, second)
            runtime.assert_not_called()

    def test_reports_append_and_failure_preserves_inspected_usage(self):
        with patch.object(m6_live, "_runtime", self.runtime()):
            m6_live.prepare(self.root, self.run_dir, self.settings)
        snapshot = {"usage": {"requests": 1, "unknown_receipts": 1}, "prediction": None}
        def fail():
            raise RuntimeError("interrupted")
        harness = SimpleNamespace(run=fail, inspect=lambda: snapshot)
        with patch.object(m6_live, "_runtime", self.runtime(harness)):
            with self.assertRaises(RuntimeError):
                m6_live.run(self.root, self.run_dir)
        first = list(self.run_dir.glob("report_*.json"))
        self.assertEqual(len(first), 1)
        self.assertEqual(m6_live._load(first[0])["result"], snapshot)
        harness.run = lambda: snapshot
        with patch.object(m6_live, "_runtime", self.runtime(harness)):
            m6_live.run(self.root, self.run_dir)
        self.assertEqual(len(list(self.run_dir.glob("report_*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
