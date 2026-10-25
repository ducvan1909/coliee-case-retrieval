"""Independent offline tests for the selective same-source recovery CLI path."""
from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_target_context import core
from knowledge_base.pipeline_v1.au_target_context import recovery
from knowledge_base.pipeline_v1.au_context_paired.build import fingerprint
from knowledge_base.pipeline_v1.au_target_context.contracts import BUDGET
from knowledge_base.pipeline_v1.au_compact.jobs_client import payload_digest
from knowledge_base.pipeline_v1.au_target_context.runner import Accounting, BudgetError


REPO = Path(__file__).resolve().parents[1]
OLD_ROOT = REPO / "knowledge_base/pipeline_v1/outputs/kos_same_source_20261018_ready"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _tree_digests(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _copy_old_root(destination):
    shutil.copytree(OLD_ROOT, destination)
    return destination


def _runtime_matching_cfg(root):
    workload = _read(root / "input/workload.json")
    ledger = _read(root / "live/runtime_ledger.json")
    cfg = recovery._cfg_from_binding(workload, ledger["binding"])
    if not ledger["binding"]["run_profile"]["runtime_revision_setting_present"]:
        cfg.pop("expected_model_revision", None)
    return cfg


class SelectiveSameSourceRecoveryTests(unittest.TestCase):
    def test_imports_verified_receipts_requeues_only_zero_post_pending_and_preserves_costs(self):
        before = _tree_digests(OLD_ROOT)
        with tempfile.TemporaryDirectory(prefix="au-same-source-recovery-") as temp:
            output = Path(temp) / "recovered"
            stdout = io.StringIO()
            with patch("knowledge_base.pipeline_v1.au_context_paired.__main__.study_config",
                       return_value=(None, None, None)), contextlib.redirect_stdout(stdout):
                result_code = recovery.main(["--old-root", str(OLD_ROOT), "--output-root", str(output)])
            cli_result = json.loads(stdout.getvalue())
            manifest = _read(output / "recovery_manifest.json")

            old_workload = _read(OLD_ROOT / "input/workload.json")
            new_workload = _read(output / "input/workload.json")
            old_ledger = _read(OLD_ROOT / "live/runtime_ledger.json")
            new_ledger = _read(output / "live/runtime_ledger.json")
            counts = {state: sum(e["status"] == state for e in old_ledger["jobs"].values())
                      for state in ("verified", "pending", "invalid")}

            self.assertEqual(counts, {"verified": 24, "pending": 2, "invalid": 1})
            self.assertEqual(result_code, 0)
            self.assertEqual(cli_result["status"], "prepared")
            self.assertEqual(cli_result["network_executed"], False)
            self.assertEqual(cli_result["imported_verified"], 24)
            self.assertEqual(cli_result["pending_requeued"], 2)
            self.assertEqual(cli_result["invalid_retry"], 1)
            self.assertEqual(manifest["imported_verified_count"], 24)
            self.assertEqual(len(manifest["requeued"]), 2)
            self.assertEqual({row["reason"] for row in manifest["requeued"]}, {"no_POST_attempt"})
            self.assertEqual(len(manifest["retry_invalid"]), 1)
            self.assertEqual(manifest["network_requests"], 0)
            self.assertEqual(len(new_ledger["jobs"]), 24)
            self.assertEqual({e["status"] for e in new_ledger["jobs"].values()}, {"verified"})
            self.assertEqual(new_ledger["attempts"], [])
            self.assertEqual(new_ledger["provider_attempts"], 0)
            self.assertEqual(new_ledger["reserved_input_tokens"], 0)
            self.assertEqual(new_ledger["reserved_output_tokens"], 0)
            self.assertEqual(new_ledger["recovery_prior_accounting"]["provider_attempts"],
                             old_ledger["provider_attempts"])
            self.assertEqual(new_ledger["recovery_prior_accounting"]["reserved_input_tokens"],
                             old_ledger["reserved_input_tokens"])
            self.assertEqual(new_ledger["recovery_prior_accounting"]["reserved_output_tokens"],
                             old_ledger["reserved_output_tokens"])
            self.assertEqual(new_workload["prompt_profile"], old_workload["prompt_profile"])
            self.assertEqual(new_workload["prompt_sha"], old_workload["prompt_sha"])
            self.assertEqual(new_workload["identity"], old_workload["identity"])
            self.assertEqual(new_workload["rows"], old_workload["rows"])
            self.assertEqual(new_workload["source_store"], old_workload["source_store"])
            self.assertEqual(new_workload["atom_root"], old_workload["atom_root"])
            self.assertEqual(new_ledger["binding"]["code_sha256"], core.code_hash())
            self.assertNotEqual(new_workload["code_sha256"], old_workload["code_sha256"])

            retried = manifest["retry_invalid"][0]
            old_entry = old_ledger["jobs"][retried["request_id"]]
            old_job = old_entry["job"]
            row = next(r for r in new_workload["rows"] if r["target_id"] == retried["target_id"])
            stage1_job = core.build_stage1(row, new_workload["identity"])
            stage1_receipt = _read(output / "live/receipts" / f"{stage1_job['request_id']}.json")
            stage1 = core.validate_stage1(stage1_receipt["model_output"], stage1_job)
            new_job = core.build_stage2(row, stage1, new_workload["identity"])[0]
            self.assertNotIn(retried["request_id"], new_ledger["jobs"],
                             "invalid generation is retried only after normal runner reservation")
            self.assertNotEqual(retried["old_payload_sha256"], retried["new_payload_sha256"])
            self.assertEqual(retried["new_payload_sha256"], new_job["payload_sha256"])
            old_semantics, new_semantics = copy.deepcopy(old_job), copy.deepcopy(new_job)
            old_semantics.pop("payload_sha256")
            new_semantics.pop("payload_sha256")
            old_semantics["payload"].pop("ebnf")
            new_semantics["payload"].pop("ebnf")
            self.assertEqual(old_semantics, new_semantics)
            self.assertEqual(_tree_digests(OLD_ROOT), before, "recovery must not alter its old run")

    def test_tampered_source_receipt_or_attempt_is_rejected_before_import(self):
        cases = ("source", "receipt", "attempt")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="au-recovery-tamper-") as temp:
                root = _copy_old_root(Path(temp) / "old")
                output = Path(temp) / "new"
                if case == "source":
                    path = root / "input/workload.json"
                    value = _read(path)
                    value["rows"][0]["source_hash"] = "0" * 64
                    _write(path, value)
                elif case == "receipt":
                    ledger = _read(root / "live/runtime_ledger.json")
                    rid = next(rid for rid, e in ledger["jobs"].items() if e["status"] == "verified")
                    path = root / "live/receipts" / f"{rid}.json"
                    receipt = _read(path)
                    receipt["normalized"]["decision"] = "forged"
                    _write(path, receipt)
                else:
                    path = root / "live/attempt_receipts/001.json"
                    attempt = _read(path)
                    attempt["reserved_input_tokens"] += 1
                    _write(path, attempt)
                with self.assertRaises((ValueError, KeyError, TypeError, OSError)):
                    recovery.recover(root, output, cfg=_runtime_matching_cfg(root))
                self.assertFalse(output.exists(), "rejected import must not leave an output tree")

    def test_pending_job_with_unacknowledged_post_is_not_requeued(self):
        with tempfile.TemporaryDirectory(prefix="au-recovery-unknown-post-") as temp:
            root = _copy_old_root(Path(temp) / "old")
            ledger_path = root / "live/runtime_ledger.json"
            ledger = _read(ledger_path)
            rid, entry = next((rid, e) for rid, e in ledger["jobs"].items()
                              if e["status"] == "pending")
            jid = entry["job"]["payload_sha256"]
            attempt = {"ordinal": len(ledger["attempts"]) + 1, "job_id": jid,
                       "payload_sha256": jid, "reserved_input_tokens": 10,
                       "reserved_output_tokens": 10, "usage": None, "usage_state": "unknown",
                       "acknowledgement": "unknown", "started_at_unix": 1.0,
                       "phase": "extraction", "input_estimate_method": "fixture"}
            ledger["attempts"].append(attempt)
            ledger["provider_attempts"] += 1
            ledger["reserved_input_tokens"] += 10
            ledger["reserved_output_tokens"] += 10
            _write(root / "live/attempt_receipts" / f"{attempt['ordinal']:03d}.json", attempt)
            ledger["ledger_sha256"] = fingerprint({k: v for k, v in ledger.items() if k != "ledger_sha256"})
            _write(ledger_path, ledger)

            with self.assertRaisesRegex(ValueError, "pending job may have executed"):
                recovery.recover(root, Path(temp) / "new", cfg=_runtime_matching_cfg(root))
            self.assertFalse((Path(temp) / "new").exists())

    def test_prior_and_new_attempt_or_token_reservations_share_the_original_caps(self):
        payload = {"model": "fixture", "messages": [{"role": "user", "content": "x"}],
                   "max_tokens": 1}
        jid = payload_digest(payload)
        job = {"request_id": "fixture-request", "payload_sha256": jid}
        endpoint = "https://fixture.invalid/jobs"
        proof = {"job_id": jid, "gateway_url": endpoint, "backoff_seconds": 1,
                 "observations": [
                     {"http_status": 404, "detail": "Unknown job", "health": {"ready": True},
                      "job_url": endpoint + "/" + jid, "observed_monotonic": 0},
                     {"http_status": 404, "detail": "Unknown job", "health": {"ready": True},
                      "job_url": endpoint + "/" + jid, "observed_monotonic": 1},
                 ]}
        request = Request(endpoint, data=json.dumps({"job_id": jid, "payload": payload}).encode(), method="POST")

        for exhausted, prior in (
                ("provider_attempts", {"provider_attempts": BUDGET["max_provider_attempts"]}),
                ("reserved_input_tokens", {"reserved_input_tokens": BUDGET["max_total_input_tokens"]}),
                ("reserved_output_tokens", {"reserved_output_tokens": BUDGET["max_total_output_tokens"]})):
            with self.subTest(cap=exhausted), tempfile.TemporaryDirectory(prefix="au-prior-budget-") as temp:
                dispatched = []
                ledger = {"jobs": {job["request_id"]: {"job": job, "status": "reserved"}},
                          "attempts": [], "provider_attempts": 0, "get_polls": 0,
                          "reserved_input_tokens": 0, "reserved_output_tokens": 0,
                          "job_recovery": {}, "observed_jobs": {},
                          "recovery_prior_accounting": prior}
                accounting = Accounting(Path(temp), ledger, BUDGET,
                                        lambda req, **kwargs: dispatched.append(req))
                with self.assertRaises(BudgetError):
                    accounting.dispatch(request, proof)
                self.assertEqual(dispatched, [], "aggregate cap must reject before the POST opener")
                self.assertEqual(ledger["attempts"], [])


if __name__ == "__main__":
    unittest.main()
