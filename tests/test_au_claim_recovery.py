"""Independent offline tests for AU claim length-recovery fixtures and core.

The historical parent is treated as immutable input.  These tests exercise
protocol recovery only; they make no semantic AU-quality or gold claim and do
not invoke a provider, network transport, or deployment.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.au_claim.contracts import OUTPUT_CAP
from knowledge_base.pipeline_v1.au_claim_recovery import core
from knowledge_base.pipeline_v1.au_claim_recovery import runner


REPO = Path(__file__).resolve().parents[1]
PARENT_ROOT = REPO / "knowledge_base/pipeline_v1/outputs/au_claim_a_local_ready_20261020"
LIVE_ROOT = PARENT_ROOT / "live"
EXPECTED_SHA256 = {
    "input/workload.json": "97cc009bca905f0c482b32c0f56d3599709be6bfb5405d7099b5095505568672",
    "live/run.json": "cc7a27d83e6becbdb4a6ad2fb5128cc67adb1b7825e673bc86cf1e45c03bd884",
    "live/runtime_ledger.json": "0a1018202566447297ef6a2de6e93182ccef1f36733e41c3edac0e97f1710a97",
    "live/receipts/auc-621f4ef0ea66a5e3734aeb5d.json":
        "30098c7590350ba874ea7451496f1f0c18de13f92d20b20c6652ca2bd8b80b92",
    "live/receipts/auc-a9d02f74a3d246e3af135acb.json":
        "eb31878ee9beac4c4c8cb77c0705d6bd8950b2d11e614ec892900d643786e40e",
}
EXPECTED_INVALID = {
    "auc-621f4ef0ea66a5e3734aeb5d": (("aus", 0, "limits"), 250, 476),
    "auc-a9d02f74a3d246e3af135acb": (("context_request", "question"), 200, 258),
}
USAGE_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def historical_fixtures(parent_root: Path = PARENT_ROOT):
    """Load exact invalid originals and their bound ledger jobs, without edits."""
    live = parent_root / "live"
    ledger = _read_json(live / "runtime_ledger.json")
    fixtures = {}
    for request_id in EXPECTED_INVALID:
        entry = ledger["jobs"][request_id]
        receipt = _read_json(live / "receipts" / f"{request_id}.json")
        original = json.loads(
            receipt["raw_response"]["choices"][0]["message"]["content"]
        )
        fixtures[request_id] = {
            "entry": entry,
            "receipt": receipt,
            "original": original,
        }
    return ledger, fixtures


def usage_subtotal(receipts):
    """Sum reported usage only; absent usage remains unknown to the caller."""
    known = [r.get("usage") for r in receipts if r.get("usage") is not None]
    return {key: sum(item.get(key, 0) for item in known) for key in USAGE_FIELDS}


class HistoricalRecoveryFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger, cls.fixtures = historical_fixtures()
        cls.historical_run = _read_json(LIVE_ROOT / "run.json")

    def test_checkpoint_hashes_and_14_verified_2_invalid_are_frozen(self):
        for rel, expected in EXPECTED_SHA256.items():
            with self.subTest(path=rel):
                self.assertEqual(
                    hashlib.sha256((PARENT_ROOT / rel).read_bytes()).hexdigest(),
                    expected,
                )
        counts = {
            status: sum(entry["status"] == status for entry in self.ledger["jobs"].values())
            for status in ("verified", "invalid")
        }
        self.assertEqual(counts, {"verified": 14, "invalid": 2})
        self.assertEqual(self.ledger["provider_attempts"], 16)
        self.assertEqual(self.historical_run["protocol_counts"]["verified"], 14)
        self.assertEqual(self.historical_run["protocol_counts"]["invalid"], 2)

    def test_historical_invalids_are_single_field_length_failures(self):
        for request_id, (expected_path, cap, length) in EXPECTED_INVALID.items():
            with self.subTest(request_id=request_id):
                fixture = self.fixtures[request_id]
                choice = fixture["receipt"]["raw_response"]["choices"][0]
                self.assertEqual(choice["finish_reason"], "stop")
                violations = core.offending_fields(fixture["original"], fixture["entry"]["job"])
                self.assertEqual(len(violations), 1)
                self.assertEqual(tuple(violations[0]["path"]), expected_path)
                self.assertEqual(violations[0]["cap"], cap)
                self.assertEqual(violations[0]["original_length"], length)

    def test_non_length_protocol_failures_and_mixed_failures_are_ineligible(self):
        for request_id, (path, _cap, _length) in EXPECTED_INVALID.items():
            fixture = self.fixtures[request_id]
            job = fixture["entry"]["job"]

            unrelated = copy.deepcopy(fixture["original"])
            target = unrelated
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = "short and valid"
            if unrelated["aus"]:
                unrelated["aus"][0]["kind"] = "not-a-kind"
            else:
                unrelated["unexpected"] = True
            with self.subTest(request_id=request_id, failure="unrelated"):
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    core.offending_fields(unrelated, job)

            mixed = copy.deepcopy(fixture["original"])
            if mixed["aus"]:
                mixed["aus"][0]["extra"] = "protocol error"
            else:
                mixed["extra"] = "protocol error"
            with self.subTest(request_id=request_id, failure="mixed"):
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    core.offending_fields(mixed, job)

    def test_repairs_freeze_every_nonoffending_field_and_keep_multiple_aus(self):
        for request_id, (path, cap, _length) in EXPECTED_INVALID.items():
            fixture = self.fixtures[request_id]
            recovery_job = core.build_repair(fixture["entry"], fixture["receipt"])
            self.assertEqual(recovery_job["offending_fields"][0]["path"], list(path))
            self.assertEqual(recovery_job["offending_fields"][0]["cap"], cap)

            repaired = copy.deepcopy(fixture["original"])
            target = repaired
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = "r" * cap
            normalized = core.validate_repair(repaired, recovery_job)
            self.assertEqual(len(normalized["aus"]), len(fixture["original"]["aus"]))
            self.assertEqual(
                [a["claim"] for a in normalized["aus"]],
                [a["claim"] for a in fixture["original"]["aus"]],
            )

            changed = copy.deepcopy(repaired)
            if changed["aus"]:
                changed["aus"][0]["claim"] += " altered"
            else:
                target_id = next(iter(recovery_job["catalog"]["target_refs"]))
                changed["aus"].append({
                    "claim": "A newly added claim.",
                    "kind": None,
                    "evidence_ids": [target_id],
                    "limits": None,
                })
            with self.subTest(request_id=request_id, changed="frozen-field"):
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    core.validate_repair(changed, recovery_job)

    def test_repair_payload_preserves_original_caps_grammar_and_nonmessage_fields(self):
        for request_id, fixture in self.fixtures.items():
            old_job = fixture["entry"]["job"]
            new_job = core.build_repair(fixture["entry"], fixture["receipt"])
            with self.subTest(request_id=request_id):
                self.assertEqual(new_job["payload"]["max_tokens"], OUTPUT_CAP)
                self.assertEqual(new_job["payload"]["max_tokens"], 800)
                self.assertEqual(new_job["payload"]["ebnf"], old_job["payload"]["ebnf"])
                for key in set(old_job["payload"]) - {"messages"}:
                    self.assertEqual(new_job["payload"][key], old_job["payload"][key])
                self.assertEqual(new_job["original_request_id"], request_id)
                self.assertEqual(new_job["original_payload_sha256"], old_job["payload_sha256"])
                self.assertEqual(new_job["original_output"], fixture["original"])

    def test_historical_cost_subtotal_matches_run_and_ledgers(self):
        receipts = [
            _read_json(path)
            for path in (LIVE_ROOT / "receipts").glob("*.json")
        ]
        subtotal = usage_subtotal(receipts)
        expected = {
            "input_tokens": 17722,
            "output_tokens": 1950,
            "total_tokens": 19672,
        }
        self.assertEqual(subtotal, expected)
        self.assertEqual(self.historical_run["known_provider_usage_observed_subtotal"], expected)
        self.assertEqual(self.historical_run["total_provider_usage"], expected)
        self.assertEqual(self.historical_run["provider_POST_attempts"], 16)
        self.assertEqual(self.historical_run["reserved_input_utf8_bytes"], 76842)
        self.assertEqual(self.historical_run["reserved_output_tokens"], 12800)

    def test_prepare_and_preflight_bind_the_immutable_historical_parent(self):
        with tempfile.TemporaryDirectory(prefix="au-claim-recovery-tests-") as tmp:
            output = Path(tmp) / "prepared"
            workload = core.prepare(PARENT_ROOT, output)
            checked = core.preflight(output / "workload.json")
            self.assertEqual(checked, workload)
            self.assertEqual(len(workload["jobs"]), 2)
            self.assertEqual(len(workload["excluded_invalid_request_ids"]), 0)
            self.assertEqual(workload["inherited_accounting"]["provider_POST_attempts"], 16)
            self.assertEqual(workload["budget"]["max_total_input_tokens"], 800000)
            self.assertEqual(workload["budget"]["max_total_output_tokens"], 4 * 2 * OUTPUT_CAP)
            self.assertEqual(workload["semantic_quality"], "not_assessed")


class RecoveryRunnerTests(unittest.TestCase):
    @staticmethod
    def _prepare(output):
        core.prepare(PARENT_ROOT, output)
        return output

    def test_mock_run_resumes_without_replaying_any_historical_request(self):
        with tempfile.TemporaryDirectory(prefix="au-claim-recovery-resume-") as tmp:
            output = self._prepare(Path(tmp) / "prepared")
            first = runner.run(output, mock=True)
            ledger_path = output / "mock/runtime_ledger.json"
            before = _read_json(ledger_path)
            first_get_polls = before["get_polls"]
            parent_hashes = {
                rel: hashlib.sha256((PARENT_ROOT / rel).read_bytes()).hexdigest()
                for rel in EXPECTED_SHA256
            }

            def must_not_dispatch(_job):
                raise AssertionError("terminal resume dispatched a provider job")

            resumed = runner.run(output, mock=True, response_factory=must_not_dispatch)
            after = _read_json(ledger_path)

            self.assertEqual(before["attempts"], after["attempts"])
            self.assertEqual(before["provider_attempts"], after["provider_attempts"])
            self.assertEqual(before["get_polls"], after["get_polls"])
            self.assertEqual(before["jobs"], after["jobs"])
            self.assertEqual(resumed["new_accounting"]["transport_POST_attempts"],
                             first["new_accounting"]["transport_POST_attempts"])
            self.assertEqual(resumed["network_requests"], 0)
            self.assertFalse(resumed["network_executed"])
            self.assertEqual(first["repair_requests"], 2)
            self.assertEqual(first["stage2_requests"], 1)
            self.assertEqual(len(first["merged_results"]), 16)
            self.assertEqual(len(first["inherited_targets"]), 16)
            self.assertEqual(first["new_accounting"]["logical_requests"], 3)
            self.assertEqual(first["new_accounting"]["transport_POST_attempts"], 3)
            self.assertEqual(first_get_polls, 16)

            recovery_stage1 = [entry["job"] for entry in after["jobs"].values()
                               if entry["job"].get("original_request_id")]
            original_ids = {request_id for request_id in EXPECTED_INVALID}
            self.assertEqual(len(recovery_stage1), 2)
            self.assertEqual({job["original_request_id"] for job in recovery_stage1}, original_ids)
            self.assertTrue(all(job["stage"] == 1 for job in recovery_stage1))
            self.assertEqual(len([job for job in recovery_stage1
                                  if job["original_request_id"] == next(iter(original_ids))]), 1)
            self.assertEqual(len(first["inherited_targets"]), 16)
            self.assertEqual(first["inherited_accounting"]["provider_POST_attempts"], 16)
            self.assertEqual(
                {rel: hashlib.sha256((PARENT_ROOT / rel).read_bytes()).hexdigest()
                 for rel in EXPECTED_SHA256},
                parent_hashes,
            )

            historical = first["inherited_accounting"]["known_usage_observed_subtotal"]
            new = first["new_accounting"]["known_usage_observed_subtotal"]
            self.assertEqual(first["aggregate_known_usage_observed_subtotal"],
                             {key: historical[key] + new[key] for key in USAGE_FIELDS})
            self.assertEqual(historical, {
                "input_tokens": 17722, "output_tokens": 1950, "total_tokens": 19672,
            })
            self.assertIsNone(first["total_provider_usage"],
                              "synthetic mock usage cannot complete provider accounting")
            self.assertEqual(first["new_accounting"]["unknown_provider_attempts"], 3)

    def test_runner_rejects_valid_but_non_length_changes_in_mock_response(self):
        request_id = "auc-621f4ef0ea66a5e3734aeb5d"
        target_id = self.ledger_target_id(request_id)
        with tempfile.TemporaryDirectory(prefix="au-claim-recovery-gate-") as tmp:
            output = self._prepare(Path(tmp) / "prepared")

            def mutate_nonoffending(job):
                value = runner.mock_response(job)
                if job.get("original_request_id") != request_id:
                    return value
                value = copy.deepcopy(job["original_output"])
                for field in job["offending_fields"]:
                    parent = value
                    for key in field["path"][:-1]:
                        parent = parent[key]
                    parent[field["path"][-1]] = "A shortened valid value."
                value["aus"][0]["claim"] = "A different but protocol-valid claim."
                return value

            report = runner.run(output, mock=True, response_factory=mutate_nonoffending)
            rows = {item["target_id"]: item for item in report["results"]}
            self.assertEqual(rows[target_id]["repair_status"], "invalid")
            other = next(target for target in rows if target != target_id)
            self.assertEqual(rows[other]["repair_status"], "verified")
            self.assertEqual(report["new_accounting"]["provider_POST_attempts"], 0)
            self.assertEqual(report["network_requests"], 0)
            ledger_path = output / "mock/runtime_ledger.json"
            before = _read_json(ledger_path)

            def must_not_retry(_job):
                raise AssertionError("terminal invalid repair was retried on resume")

            resumed = runner.run(output, mock=True, response_factory=must_not_retry)
            after = _read_json(ledger_path)
            self.assertEqual(after["attempts"], before["attempts"])
            self.assertEqual(after["provider_attempts"], before["provider_attempts"])
            self.assertEqual(after["get_polls"], before["get_polls"])
            self.assertEqual(resumed["new_accounting"]["transport_POST_attempts"],
                             report["new_accounting"]["transport_POST_attempts"])
            self.assertEqual(resumed["network_requests"], 0)

    def test_repaired_context_question_gets_one_normal_followup_and_no_recursion(self):
        request_id = "auc-a9d02f74a3d246e3af135acb"
        target_id = self.ledger_target_id(request_id)
        seen = []
        with tempfile.TemporaryDirectory(prefix="au-claim-recovery-context-") as tmp:
            output = self._prepare(Path(tmp) / "prepared")

            def observe(job):
                if job.get("original_request_id") == request_id:
                    value = copy.deepcopy(job["original_output"])
                    for field in job["offending_fields"]:
                        parent = value
                        for key in field["path"][:-1]:
                            parent = parent[key]
                        parent[field["path"][-1]] = "What qualification applies nearby?"
                    return value
                if job["target_id"] == target_id:
                    seen.append(job["stage"])
                    if job["stage"] == 2:
                        self.assertTrue(job["draft"]["context_request"])
                return runner.mock_response(job)

            report = runner.run(output, mock=True, response_factory=observe)
            target = next(item for item in report["results"] if item["target_id"] == target_id)
            ledger = _read_json(output / "mock/runtime_ledger.json")
            target_jobs = [entry["job"] for entry in ledger["jobs"].values()
                           if entry["job"]["target_id"] == target_id]

            self.assertEqual(seen, [2])
            self.assertEqual(target["repair_status"], "verified")
            self.assertEqual(target["stage2_status"], "verified")
            self.assertEqual(sum(job["stage"] == 1 for job in target_jobs), 1)
            self.assertEqual(sum(job["stage"] == 2 for job in target_jobs), 1)
            self.assertLessEqual(len(target_jobs), 2)
            self.assertEqual(report["stage2_requests"], 1)

    @classmethod
    def ledger_target_id(cls, request_id):
        _ledger, fixtures = historical_fixtures()
        return fixtures[request_id]["entry"]["job"]["target_id"]


class RecoveryCostAccountingTests(unittest.TestCase):
    @staticmethod
    def _store_receipt(root, request_id, payload_hash, usage):
        receipt = {
            "request_id": request_id,
            "payload_sha256": payload_hash,
            "usage": usage,
            "raw_response": {"id": "durable-job-response"},
        }
        receipt["receipt_sha256"] = core.fingerprint(receipt)
        path = root / "receipts" / f"{request_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt), encoding="utf-8")
        return {
            "job": {"request_id": request_id, "payload_sha256": payload_hash},
            "status": "verified",
            "receipt_sha256": receipt["receipt_sha256"],
        }

    @staticmethod
    def _ledger(jobs, attempts):
        return {
            "jobs": jobs,
            "attempts": attempts,
            "get_polls": 5,
            "reserved_input_tokens": sum(a["reserved_input_tokens"] for a in attempts),
            "reserved_output_tokens": sum(a["reserved_output_tokens"] for a in attempts),
        }

    def test_durable_get_receipt_usage_counts_with_zero_local_posts(self):
        usage = {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10}
        with tempfile.TemporaryDirectory(prefix="au-claim-recovery-get-cost-") as tmp:
            root = Path(tmp)
            entry = self._store_receipt(root, "retrieved-only", "payload-get-only", usage)
            ledger = self._ledger({"retrieved-only": entry}, attempts=[])

            costs = runner._cost(root, ledger, execute=True)

        self.assertEqual(costs["known_usage_observed_subtotal"], usage)
        self.assertEqual(costs["retrieved_jobs_without_local_POST"], 1)
        self.assertEqual(costs["retrieved_usage_observed_subtotal"], usage)
        self.assertEqual(costs["transport_POST_attempts"], 0)
        self.assertEqual(costs["provider_POST_attempts"], 0)
        self.assertEqual(costs["unknown_provider_attempts"], 0)
        self.assertTrue(costs["usage_is_complete"])

    def test_mixed_prior_attempt_and_get_usage_are_counted_once_each(self):
        final_receipt_usage = {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10}
        get_receipt_usage = {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}
        prior_attempt_usage = {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
        with tempfile.TemporaryDirectory(prefix="au-claim-recovery-mixed-cost-") as tmp:
            root = Path(tmp)
            attempted = self._store_receipt(root, "retried-job", "payload-retried", final_receipt_usage)
            retrieved = self._store_receipt(root, "get-job", "payload-get", get_receipt_usage)
            attempts = [
                {"job_id": "payload-retried", "usage": prior_attempt_usage,
                 "provably_not_accepted": False, "latency_ms": 1,
                 "reserved_input_tokens": 100, "reserved_output_tokens": 800},
                {"job_id": "payload-retried", "usage": None,
                 "provably_not_accepted": False, "latency_ms": 2,
                 "reserved_input_tokens": 100, "reserved_output_tokens": 800},
            ]
            ledger = self._ledger({"retried-job": attempted, "get-job": retrieved}, attempts)

            costs = runner._cost(root, ledger, execute=True)

        expected = {
            key: prior_attempt_usage[key] + final_receipt_usage[key] + get_receipt_usage[key]
            for key in USAGE_FIELDS
        }
        self.assertEqual(costs["known_usage_observed_subtotal"], expected)
        self.assertEqual(costs["retrieved_jobs_without_local_POST"], 1)
        self.assertEqual(costs["retrieved_usage_observed_subtotal"], get_receipt_usage)
        self.assertEqual(costs["transport_POST_attempts"], 2)
        self.assertEqual(costs["provider_POST_attempts"], 2)
        self.assertEqual(costs["unknown_provider_attempts"], 0)
        self.assertTrue(costs["usage_is_complete"])


if __name__ == "__main__":
    unittest.main()
