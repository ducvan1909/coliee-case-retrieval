"""Independent regression tests for positional Stage 1 anchor grammar.

All rows and model responses are synthetic. Tests exercise the emitted grammar,
the host validator, and the local probe only; they do not call a provider or
establish AU semantic quality.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_target_context import contracts, core, prompts
from knowledge_base.pipeline_v1.au_target_context import __main__ as cli
from knowledge_base.pipeline_v1.au_target_context import anchor_order_probe
from knowledge_base.pipeline_v1.au_target_context.grammar import build_grammar
from knowledge_base.pipeline_v1.au_target_context import runner as target_runner
from knowledge_base.pipeline_v1.au_compact.jobs_client import payload_digest


IDENTITY = {"model": "fixture-model", "enable_thinking": False}
PROBE_CFG = {
    "model": "fixture-model",
    "url": "https://jobs.invalid/chat/completions",
    "jobs_url": "https://jobs.invalid/jobs",
    "token": "fixture-only-token",
    "job_poll_seconds": 0.001,
    "job_wait_seconds": 10,
}
PROFILE_NAMES = prompts.PROMPT_PROFILES


def stage1_job(profile="baseline_v2"):
    source = "Point one. Point two. Point three."
    refs = {}
    for index, quote in enumerate(("Point one.", "Point two.", "Point three.")):
        start = source.index(quote)
        ref_id = f"target-{index + 1}"
        refs[ref_id] = {
            "ref_id": ref_id,
            "source_atom_id": f"atom-{index + 1}",
            "case_id": "anchor-order-fixture",
            "source_hash": "a" * 64,
            "start_char": start,
            "end_char": start + len(quote),
            "quote": quote,
            "role": "target_body",
        }
    row = {
        "target_id": "anchor-order-target",
        "case_id": "anchor-order-fixture",
        "source_hash": "a" * 64,
        "target": {"start_char": 0, "end_char": len(source)},
        "request": {"request_id": "anchor-order-request"},
        "target_refs": refs,
        "context_refs": {},
        "_source": source,
        "prompt_profile": profile,
    }
    row.update(core.prompt_metadata(profile))
    return core.build_stage1(row, IDENTITY)


def stage1_response(job, anchor_ids, *, decision="positive", needs=()):
    anchors = []
    for index, anchor_id in enumerate(anchor_ids):
        ref_id = f"target-{index + 1}"
        anchor = {"anchor_id": anchor_id, "kind": "holding", "needs_context": []}
        if job.get("prompt_profile") == "primary_support_v1":
            anchor.update(primary_ref_id=ref_id, supporting_ref_ids=[])
        else:
            anchor["target_ref_ids"] = [ref_id]
        if job.get("prompt_profile") not in ("evidence_first_v1", "primary_support_v1"):
            anchor["primary_claim"] = f"Synthetic claim {index + 1}."
        anchors.append(anchor)
    reason = {
        "positive": "none",
        "negative": "no_legal_proposition",
        "needs_context": "insufficient_target",
        "unresolved": "unclear_attribution",
    }[decision]
    return {
        "version": contracts.stage1_version(job.get("prompt_profile")),
        "request_id": job["request_id"],
        "target_id": job["target_id"],
        "decision": decision,
        "anchors": anchors,
        "needs_context": list(needs),
        "reason": reason,
    }


def production(grammar, name):
    prefix = name + " ::= "
    return next(line[len(prefix):] for line in grammar.splitlines() if line.startswith(prefix))


class Stage1AnchorGrammarTests(unittest.TestCase):
    def test_all_stage1_profiles_emit_only_fixed_contiguous_anchor_slots(self):
        for profile in PROFILE_NAMES:
            with self.subTest(profile=profile):
                job = stage1_job(profile)
                grammar = build_grammar(job)
                self.assertIn("anchor-slot-1 ::=", grammar)
                self.assertIn("anchor-slot-2 ::=", grammar)
                self.assertIn("anchor-slot-3 ::=", grammar)
                self.assertNotIn("anchor-id ::=", grammar)
                for index, anchor_id in enumerate(job["anchor_ids"][:3], 1):
                    slot = production(grammar, f"anchor-slot-{index}")
                    self.assertEqual(slot.count(json.dumps(json.dumps(anchor_id))), 1)
                    for other_index, other_id in enumerate(job["anchor_ids"][:3], 1):
                        if other_index != index:
                            self.assertNotIn(json.dumps(json.dumps(other_id)), slot)

                expected_prefixes = ["\"[]\""]
                for size in range(1, 4):
                    slots = ' "," '.join(f"anchor-slot-{i}" for i in range(1, size + 1))
                    expected_prefixes.append(f'"[" {slots} "]"')
                self.assertEqual(production(grammar, "anchors").split(" | "), expected_prefixes)
                self.assertEqual(
                    production(grammar, "positive-anchors").split(" | "),
                    expected_prefixes[1:],
                )

    def test_host_accepts_positive_prefixes_of_one_two_and_three(self):
        job = stage1_job()
        for count in (1, 2, 3):
            with self.subTest(count=count):
                raw = stage1_response(job, job["anchor_ids"][:count])
                normalized = core.validate_stage1(raw, job)
                self.assertEqual(
                    [item["anchor_id"] for item in normalized["anchors"]],
                    job["anchor_ids"][:count],
                )
                self.assertEqual(len(normalized["anchors"]), count)
                self.assertEqual(normalized["semantic_quality"], "not_assessed")

    def test_host_rejects_permutation_duplicate_skip_first_and_unknown_ids(self):
        job = stage1_job()
        valid = job["anchor_ids"][:3]
        invalid_sets = (
            (valid[1], valid[0]),
            (valid[0], valid[0]),
            (valid[1],),
            ("foreign-anchor",),
            (valid[0], valid[2]),
        )
        for anchor_ids in invalid_sets:
            with self.subTest(anchor_ids=anchor_ids), self.assertRaises(
                (core.TargetContextError, ValueError)
            ):
                core.validate_stage1(stage1_response(job, anchor_ids), job)

    def test_host_emits_allowlisted_order_diagnostic_and_generic_validation_code(self):
        job = stage1_job()
        invalid_order = stage1_response(job, (job["anchor_ids"][1], job["anchor_ids"][0]))
        with self.assertRaises(core.TargetContextError) as caught:
            core.validate_stage1(invalid_order, job)
        self.assertEqual(caught.exception.error_code, "anchor_slot_order")

        invalid_kind = stage1_response(job, job["anchor_ids"][:1])
        invalid_kind["anchors"][0]["kind"] = "unrecognized-kind"
        with self.assertRaises(core.TargetContextError) as caught:
            core.validate_stage1(invalid_kind, job)
        self.assertEqual(caught.exception.error_code, "output_protocol_validation")

    def test_empty_and_uncertain_decisions_preserve_their_existing_host_rules(self):
        job = stage1_job()
        negative = stage1_response(job, (), decision="negative")
        self.assertEqual(core.validate_stage1(negative, job)["anchors"], [])
        with self.assertRaises((core.TargetContextError, ValueError)):
            core.validate_stage1(stage1_response(job, job["anchor_ids"][:1], decision="negative"), job)

        for decision in ("needs_context", "unresolved"):
            with self.subTest(decision=decision):
                for count in range(4):
                    raw = stage1_response(
                        job,
                        job["anchor_ids"][:count],
                        decision=decision,
                        needs=("speaker",) if decision == "needs_context" and count == 0 else (),
                    )
                    if decision == "needs_context" and count > 0:
                        raw["anchors"][0]["needs_context"] = ["speaker"]
                    checked = core.validate_stage1(raw, job)
                    self.assertEqual(len(checked["anchors"]), count)
                    self.assertEqual(checked["decision"], decision)

    def test_multiple_aus_keep_distinct_target_evidence_in_host_slot_order(self):
        job = stage1_job()
        checked = core.validate_stage1(stage1_response(job, job["anchor_ids"][:3]), job)
        self.assertEqual(
            [[span["ref_id"] for span in anchor["primary_evidence"]] for anchor in checked["anchors"]],
            [["target-1"], ["target-2"], ["target-3"]],
        )
        self.assertEqual([a["primary_claim"] for a in checked["anchors"]],
                         ["Synthetic claim 1.", "Synthetic claim 2.", "Synthetic claim 3."])

    def test_evidence_first_powershell_entrypoint_has_bom_and_parses(self):
        script = (Path(__file__).resolve().parents[1] /
                  "knowledge_base/pipeline_v1/experiments/run_evidence_first.ps1")
        self.assertTrue(script.is_file(), f"missing runner: {script}")
        self.assertTrue(script.read_bytes().startswith(b"\xef\xbb\xbf"),
                        "PowerShell runner must retain its UTF-8 BOM")
        shell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if not shell:
            self.skipTest("PowerShell parser is not installed")
        escaped = str(script).replace("'", "''")
        parse = (
            "$tokens=$null;$parseErrors=$null;"
            f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',"
            "[ref]$tokens,[ref]$parseErrors) > $null;"
            "if($parseErrors.Count -gt 0){"
            "$parseErrors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
        )
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", parse],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        source = script.read_text(encoding="utf-8-sig")
        self.assertIn("protocol_invalid", source)
        self.assertIn("error_code", source)


class AnchorOrderProbeTests(unittest.TestCase):
    def test_default_prepare_is_local_and_binds_six_synthetic_stage1_jobs(self):
        with tempfile.TemporaryDirectory(prefix="anchor-order-prepare-") as folder:
            report = anchor_order_probe.run_probe(folder, cfg=PROBE_CFG)
            saved = json.loads((Path(folder) / "probe.json").read_text(encoding="utf-8"))
            workload = json.loads((Path(folder) / "workload.json").read_text(encoding="utf-8"))

        self.assertEqual(report, saved)
        self.assertEqual(report["status"], "prepared")
        self.assertFalse(report["network_executed"])
        self.assertEqual(report["provider_POST_attempts"], 0)
        self.assertEqual(report["endpoint_constraint_status"], "not_executed")
        self.assertEqual(len(workload["jobs"]), 6)
        self.assertEqual({job["probe_case"] for job in workload["jobs"]},
                         set(anchor_order_probe.CASES))
        self.assertTrue(all(job["stage"] == 1 for job in workload["jobs"]))
        self.assertEqual(report["budget"]["max_requests"], 6)
        self.assertEqual(report["budget"]["max_provider_attempts"], 12)
        self.assertEqual(report["semantic_quality"], "not_assessed")

    def test_mock_uses_stage1_accounting_without_claiming_constraint_or_provider_pass(self):
        with tempfile.TemporaryDirectory(prefix="anchor-order-mock-") as folder:
            report = anchor_order_probe.run_probe(
                folder, cfg=PROBE_CFG, mock=True, concurrency=1,
            )
            ledger = json.loads((Path(folder) / "runtime_ledger.json").read_text(encoding="utf-8"))
            workload = json.loads((Path(folder) / "workload.json").read_text(encoding="utf-8"))
            receipts = [json.loads(path.read_text(encoding="utf-8"))
                        for path in (Path(folder) / "receipts").glob("*.json")]

        self.assertEqual(report["status"], "complete")
        self.assertFalse(report["network_executed"])
        self.assertEqual(report["logical_requests"], 6)
        self.assertEqual(report["transport_POST_attempts"], 6)
        self.assertEqual(report["provider_POST_attempts"], 0)
        self.assertIsNone(report["total_provider_usage"])
        self.assertEqual(report["unknown_provider_attempts"], 0)
        self.assertEqual(report["endpoint_constraint_status"], "not_assessed_mock")
        self.assertEqual(len(receipts), 6)
        self.assertTrue(all(job["stage"] == 1 for job in workload["jobs"]))
        self.assertEqual(len(ledger["jobs"]), 6)
        self.assertTrue(all(row["status"] == "verified" for row in report["results"]))
        self.assertTrue(all(row["constraint_status"] == "not_assessed_mock"
                            for row in report["results"]))
        for receipt in receipts:
            digest = receipt.pop("receipt_sha256")
            self.assertEqual(digest, core.fingerprint(receipt))

    def test_empty_negative_protocol_response_is_not_a_constraint_success(self):
        valid_response = anchor_order_probe._mock_response

        def negative_empty(job):
            value = valid_response(job)
            value.update(decision="negative", anchors=[], reason="no_legal_proposition")
            return value

        with tempfile.TemporaryDirectory(prefix="anchor-order-negative-") as folder:
            with patch.object(anchor_order_probe, "_mock_response", side_effect=negative_empty):
                report = anchor_order_probe.run_probe(
                    folder, cfg=PROBE_CFG, mock=True, concurrency=1,
                )

        self.assertEqual(report["status"], "complete")  # protocol completion only
        self.assertEqual(report["endpoint_constraint_status"], "not_assessed_mock")
        self.assertTrue(all(row["status"] == "verified" for row in report["results"]))
        self.assertTrue(all(row["actual_count"] == 0 for row in report["results"]))
        self.assertTrue(all(row["constraint_status"] != "observed_valid_positive"
                            for row in report["results"]))

    def test_valid_positive_count_mismatch_is_instruction_mismatch_not_grammar_failure(self):
        valid_response = anchor_order_probe._mock_response

        def one_anchor(job):
            value = valid_response(job)
            value["anchors"] = value["anchors"][:1]
            return value

        with tempfile.TemporaryDirectory(prefix="anchor-order-count-") as folder:
            with patch.object(anchor_order_probe, "_mock_response", side_effect=one_anchor):
                report = anchor_order_probe.run_probe(
                    folder, cfg=PROBE_CFG, mock=True, concurrency=1,
                )

        self.assertEqual(report["status"], "complete")
        by_case = {row["case"]: row for row in report["results"]}
        for case in ("compliant2", "compliant3"):
            self.assertEqual(by_case[case]["status"], "verified")
            self.assertEqual(by_case[case]["actual_count"], 1)
            self.assertFalse(by_case[case]["count_match"])
            self.assertEqual(by_case[case]["instruction_status"], "mismatch")
            self.assertIsNone(by_case[case]["error_code"])
            self.assertEqual(by_case[case]["constraint_status"], "not_assessed_mock")

    def test_truncated_mock_responses_remain_invalid_and_cannot_pass_probe_gate(self):
        class TruncatedJobs(target_runner.MockJobs):
            def __call__(self, req, **kwargs):
                response = super().__call__(req, **kwargs)
                value = json.loads(response.read().decode("utf-8"))
                body = value.get("response")
                if isinstance(body, dict) and body.get("choices"):
                    body["choices"][0]["finish_reason"] = "length"
                    value["response_sha256"] = payload_digest(body)
                    with self.lock:
                        self.finished[value["job_id"]] = value
                return target_runner.Response(json.dumps(value).encode("utf-8"))

        with tempfile.TemporaryDirectory(prefix="anchor-order-truncated-") as folder:
            with patch.object(anchor_order_probe, "MockJobs", TruncatedJobs):
                report = anchor_order_probe.run_probe(
                    folder, cfg=PROBE_CFG, mock=True, concurrency=1,
                )

        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(report["network_executed"])
        self.assertEqual(report["endpoint_constraint_status"], "not_assessed_mock")
        self.assertTrue(all(row["status"] == "invalid" for row in report["results"]))
        self.assertTrue(all(row["error_code"] == "incomplete_generation"
                            for row in report["results"]))
        self.assertTrue(all(row["constraint_status"] != "observed_valid_positive"
                            for row in report["results"]))

    def test_execute_cli_returns_failure_for_complete_but_inconclusive_report(self):
        report = {"status": "complete", "endpoint_constraint_status": "inconclusive",
                  "network_executed": True, "prompt_profile": "evidence_first_v1",
                  "prompt_sha": "fixture", "semantic_quality": "not_assessed"}
        with tempfile.TemporaryDirectory(prefix="anchor-order-cli-") as folder:
            with patch.object(cli, "study_config", return_value=({"model": "fixture"}, None, None)), \
                    patch.object(anchor_order_probe, "run_probe", return_value=report):
                exit_code = cli.main(["anchor-order-probe", "--execute", "--output-root", folder])
        self.assertNotEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
