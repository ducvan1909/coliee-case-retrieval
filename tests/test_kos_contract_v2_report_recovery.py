"""Independent offline recovery tests for KOS contract v2 reports."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib import request

from knowledge_base.pipeline_v1.kos_authoring_controls import execution
from knowledge_base.pipeline_v1.kos_authoring_controls_v2 import controls
from knowledge_base.pipeline_v1.experiments import recover_kos_contract_v2_report as recovery


class RecoveryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "run"
        self.root.mkdir()
        jobs = controls.balanced_jobs()
        self.identity = {
            "jobs_url": "https://offline.invalid/jobs",
            "model": jobs[0]["payload"]["model"],
            "enable_thinking": False,
            "transport": "jobs",
            "string_decoder": None,
            "expected_model_revision": None,
        }
        manifest = {
            "jobs": jobs,
            "identity": {"jobs_url": self.identity["jobs_url"], "model": self.identity["model"]},
            "sha256": "synthetic-test-manifest",
        }
        (self.root / "input").mkdir()
        (self.root / "input/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.root / "input/cpu_balanced.json").write_text("{}", encoding="utf-8")
        cfg = {"jobs_url": self.identity["jobs_url"], "model": self.identity["model"],
               "readiness_seconds": 600, "job_wait_seconds": 600,
               "job_poll_seconds": 2, "timeout": 60}
        # Establish the exact persisted v1 binding using its local dry-run path.
        execution.run_jobs(self.root / "live", cfg, jobs, execute=False)
        self.manifest = manifest
        self.jobs = jobs
        self.refresh_binding()

    def refresh_binding(self):
        self.binding = json.loads((self.root / "live/binding.json").read_text(encoding="utf-8"))
        self.binding_sha = execution.payload_digest(self.binding)
        ids = [execution.payload_digest(row["payload"]) for row in self.jobs]
        live = self.root / "live"
        (live / "intents").mkdir(exist_ok=True)
        for jid in ids:
            intent = execution._seal({"job_id": jid, "binding_sha256": self.binding_sha,
                                      "reserved_tokens": next(x["input_reservation"] for x in self.binding["jobs"]
                                                               if x["job_id"] == jid) + execution.MAX_OUTPUT,
                                      "started_at_unix": 1})
            (live / "intents" / f"{jid}.json").write_text(json.dumps(intent), encoding="utf-8")
            receipt_dir = live / "receipts" / jid
            receipt_dir.mkdir(parents=True, exist_ok=True)
            (receipt_dir / "1.json").write_text(json.dumps(execution._seal({
                "job_id": jid, "binding_sha256": self.binding_sha, "status": "partial",
                "usage": None, "observed_remote": True,
            })), encoding="utf-8")

    def call(self):
        # Synthetic location: skip only source/profile and native CPU checks.
        with patch.object(controls, "preflight"), \
             patch.object(recovery.cli, "require_cpu"), \
             patch.object(request, "urlopen", side_effect=AssertionError("network access")):
            return recovery.build_report(self.root)


class OfflineReportRecoveryTests(RecoveryFixture):
    def test_recovery_is_offline_preserves_inputs_and_keeps_incomplete_nonsemantic(self):
        files = [self.root / "input/manifest.json", self.root / "input/cpu_balanced.json",
                 self.root / "live/binding.json"]
        files += list((self.root / "live/intents").glob("*.json"))
        files += list((self.root / "live/receipts").rglob("*.json"))
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        report = self.call()
        self.assertTrue(report["offline"])
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(report["semantic_pass"])
        self.assertEqual(report["semantic_quality"], "semantic_review_pending")
        self.assertEqual(report["unknown_usage_count"], len(self.jobs))
        self.assertEqual(report["structural_control_pass_count"], 0)
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

    def test_integral_saved_caps_are_hashed_as_persisted_and_do_not_redispatch(self):
        # run_jobs normalizes these caps to floats. Model the valid historical JSON
        # binding with integer caps and reseal its dependent immutable records.
        binding_path = self.root / "live/binding.json"
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        for key in ("readiness_seconds", "job_wait_seconds", "timeout"):
            binding["config"][key] = int(binding["config"][key])
        binding_path.write_text(json.dumps(binding), encoding="utf-8")
        for folder in (self.root / "live/intents", self.root / "live/receipts"):
            for path in folder.rglob("*.json"):
                row = json.loads(path.read_text(encoding="utf-8"))
                row["binding_sha256"] = execution.payload_digest(binding)
                row.pop("record_sha256")
                path.write_text(json.dumps(execution._seal(row)), encoding="utf-8")
        report = self.call()
        self.assertEqual(report["binding_sha256"], execution.payload_digest(binding))
        self.assertEqual(report["POST_attempts"], len(self.jobs))

    def test_tampered_intent_and_receipt_are_rejected_by_record_digest(self):
        intent = next((self.root / "live/intents").glob("*.json"))
        row = json.loads(intent.read_text(encoding="utf-8"))
        row["reserved_tokens"] += 1
        intent.write_text(json.dumps(row), encoding="utf-8")
        with patch.object(controls, "preflight"), patch.object(recovery.cli, "require_cpu"):
            with self.assertRaisesRegex(ValueError, "immutable record digest"):
                recovery.build_report(self.root)

        # Restore this file and independently corrupt a receipt.
        original = execution._seal({"job_id": intent.stem, "binding_sha256": self.binding_sha,
                                    "reserved_tokens": next(x["input_reservation"] for x in self.binding["jobs"]
                                                             if x["job_id"] == intent.stem) + execution.MAX_OUTPUT,
                                    "started_at_unix": 1})
        intent.write_text(json.dumps(original), encoding="utf-8")
        receipt = next((self.root / "live/receipts").rglob("*.json"))
        row = json.loads(receipt.read_text(encoding="utf-8"))
        row["status"] = "completed"
        receipt.write_text(json.dumps(row), encoding="utf-8")
        with patch.object(controls, "preflight"), patch.object(recovery.cli, "require_cpu"):
            with self.assertRaisesRegex(ValueError, "immutable record digest"):
                recovery.build_report(self.root)

    def test_missing_receipt_does_not_count_as_complete(self):
        next((self.root / "live/receipts").rglob("*.json")).unlink()
        report = self.call()
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(report["semantic_pass"])


class ActualRunRecoveryTests(unittest.TestCase):
    """Exercise the actual nine-receipt run while keeping generated reports temporary."""

    @classmethod
    def setUpClass(cls):
        cls.source = Path(controls.DEFAULT_ROOT)
        if not cls.source.is_dir():
            raise unittest.SkipTest("actual KOS v2 run root is unavailable")
        receipts = list((cls.source / "live/receipts").rglob("*.json"))
        if len(receipts) != 9:
            raise unittest.SkipTest(f"expected nine source receipts, found {len(receipts)}")
        cls.receipt_bytes = {p.relative_to(cls.source): p.read_bytes() for p in receipts}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "actual-run-copy"
        # Copy only recovery inputs. Do not carry over derived ledgers/reports or
        # the larger CPU history directory.
        for rel in (Path("input/manifest.json"), Path("input/cpu_balanced.json"),
                    Path("cpu_balanced.json"), Path("live/binding.json")):
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.source / rel, target)
        for rel in (Path("live/intents"), Path("live/receipts")):
            shutil.copytree(self.source / rel, self.root / rel)
        self.source_inputs = [self.root / "input/manifest.json", self.root / "input/cpu_balanced.json",
                              self.root / "cpu_balanced.json", self.root / "live/binding.json"]
        self.source_inputs.extend((self.root / "live/intents").rglob("*.json"))
        self.source_inputs.extend((self.root / "live/receipts").rglob("*.json"))
        self.before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in self.source_inputs}

    def recover(self):
        with patch.object(controls, "preflight"), \
             patch.object(recovery.cli, "require_cpu"), \
             patch.object(request, "urlopen", side_effect=AssertionError("network access")):
            return recovery.build_report(self.root)

    def test_actual_nine_receipts_recover_offline_and_second_call_is_idempotent(self):
        first = self.recover()
        saved = (self.root / "recovered_report/report.json").read_bytes()
        second = self.recover()
        self.assertEqual(first["status"], "semantic_review_pending")
        self.assertEqual(first["protocol_valid_count"], 9)
        self.assertEqual(first["structural_control_pass_count"], 9)
        self.assertFalse(first["semantic_pass"])
        self.assertEqual(second["sha256"], first["sha256"])
        self.assertEqual((self.root / "recovered_report/report.json").read_bytes(), saved)
        self.assertEqual(self.before, {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                       for path in self.source_inputs})

    def test_actual_report_history_preserves_partial_before_complete_recovery(self):
        receipt = next((self.root / "live/receipts").rglob("*.json"))
        completed_bytes = receipt.read_bytes()
        row = json.loads(completed_bytes)
        row["status"] = "partial"
        row.pop("record_sha256")
        receipt.write_text(json.dumps(execution._seal(row)), encoding="utf-8")
        partial = self.recover()
        self.assertEqual(partial["status"], "incomplete")

        receipt.write_bytes(completed_bytes)
        complete = self.recover()
        self.assertEqual(complete["status"], "semantic_review_pending")
        history = self.root / "recovered_report/history" / f"{partial['sha256']}.json"
        self.assertTrue(history.is_file())
        self.assertEqual(json.loads(history.read_text(encoding="utf-8"))["sha256"], partial["sha256"])
        self.assertEqual(json.loads((self.root / "recovered_report/report.json").read_text(encoding="utf-8"))[
                         "sha256"], complete["sha256"])
        self.assertFalse(complete["semantic_pass"])

    def test_report_only_wrapper_runs_with_network_opener_blocked(self):
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell is unavailable")
        guard = Path(self.temp.name) / "network_guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(
            "import urllib.request\n"
            "def blocked(*args, **kwargs):\n"
            "    raise AssertionError('ReportOnly attempted network access')\n"
            "urllib.request.urlopen = blocked\n", encoding="utf-8")
        script = Path(__file__).resolve().parents[1] / "knowledge_base/pipeline_v1/experiments/run_kos_contract_v2.ps1"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(guard)
        result = subprocess.run(
            [powershell, "-NoProfile", "-File", str(script), "-ReportOnly", "-OutputRoot", str(self.root)],
            cwd=Path(__file__).resolve().parents[1], env=env, text=True,
            capture_output=True, timeout=90, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Report recovered offline", result.stdout)
        report = json.loads((self.root / "recovered_report/report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["POST_attempts"], 9)
        self.assertEqual(self.before, {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                       for path in self.source_inputs})


if __name__ == "__main__":
    unittest.main()
