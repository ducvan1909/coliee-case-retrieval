"""Independent local invariants for the staged TARGET/context pilot.

These tests use only frozen local inputs and synthetic model responses. They do
not invoke inference, network transports, deployment, xgrammar, or transformers.
"""
from __future__ import annotations

import copy
import contextlib
import io
import json
import threading
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_target_context import (
    TargetContextError,
    build_stage1,
    build_stage2,
    validate_stage1,
    validate_stage2,
)
from knowledge_base.pipeline_v1.au_target_context import contracts
from knowledge_base.pipeline_v1.au_target_context import core
from knowledge_base.pipeline_v1.au_target_context.grammar import build_grammar
from knowledge_base.pipeline_v1.au_target_context import runner
from knowledge_base.pipeline_v1.au_target_context import __main__ as cli


def fixture_row():
    source = "PREFIX TARGET_ATOM_ONE TARGET_ATOM_TWO UNUSED_TARGET_ATOM CONTEXT_ONLY_SUFFIX"
    spans = {}
    for ref_id, atom_id, quote, role in (
        ("target-ref-1", "atom-one", "TARGET_ATOM_ONE", "target_body"),
        ("target-ref-2", "atom-two", "TARGET_ATOM_TWO", "target_body"),
        ("target-ref-3", "atom-unused", "UNUSED_TARGET_ATOM", "target_body"),
        ("context-ref-1", "atom-context", "CONTEXT_ONLY_SUFFIX", "context"),
    ):
        start = source.index(quote)
        end = start + len(quote)
        spans[ref_id] = {"ref_id": ref_id, "source_atom_id": atom_id,
                         "case_id": "fixture-case", "source_hash": "f" * 64,
                         "start_char": start, "end_char": end, "quote": source[start:end],
                         "role": role}
    return {
        "target_id": "target-a", "case_id": "fixture-case", "source_hash": "f" * 64,
        "target": {"start_char": source.index("TARGET_ATOM_ONE"),
                   "end_char": source.index("UNUSED_TARGET_ATOM") + len("UNUSED_TARGET_ATOM")},
        "request": {"request_id": "fixture-original", "expected_target_ids": ["target-a"]},
        "target_refs": {k: v for k, v in spans.items() if k.startswith("target-")},
        "context_refs": {k: v for k, v in spans.items() if k.startswith("context-")},
        "_fixture_source": source,
    }


def fixture_identity():
    return {"model": "fixture-model", "enable_thinking": False}


def stage1_reason(decision):
    return {
        "positive": "none",
        "negative": "no_legal_proposition",
        "needs_context": "insufficient_target",
        "unresolved": "unclear_attribution",
    }[decision]


def stage2_reason(decision):
    return {
        "complete": "none",
        "unresolved": "context_insufficient",
        "revisit_target": "revisit_target_required",
    }[decision]


def stage2_anchor_reason(decision):
    return {
        "keep": "none",
        "reject": "primary_not_supported",
        "unresolved": "context_insufficient",
    }[decision]


def stage1_job(row=None):
    return build_stage1(row or fixture_row(), fixture_identity())


def stage1_value(job, anchors=None, *, decision="positive"):
    return {
        "version": contracts.STAGE1,
        "request_id": job["request_id"],
        "target_id": job["target_id"],
        "decision": decision,
        "anchors": anchors if anchors is not None else [{
            "anchor_id": job["anchor_ids"][0],
            "kind": "holding",
            "primary_claim": "The court applied the stated test.",
            "target_ref_ids": ["target-ref-1"],
            "needs_context": ["exception"],
        }],
        "needs_context": ["exception"] if decision == "needs_context" else [],
        "reason": stage1_reason(decision),
    }


def stage2_job(anchors=None, row=None):
    row = row or fixture_row()
    locked = anchors if anchors is not None else [
        {"anchor_id": "anchor-a1", "primary_claim": "The court applied the stated test.",
         "target_ref_ids": ["target-ref-1"]},
        {"anchor_id": "anchor-a2", "primary_claim": "The court resolved a second issue.",
         "target_ref_ids": ["target-ref-2"]},
    ]
    return {
        "stage": 2,
        "request_id": "s2-req-target-a",
        "target_id": "target-a",
        "locked_anchors": copy.deepcopy(locked),
        "catalog": {"target_refs": row["target_refs"],
                    "context_refs": row["context_refs"]},
    }


def stage2_value(job, anchors=None, *, decision="complete"):
    if anchors is None:
        anchors = [{
            "anchor_id": locked["anchor_id"],
            "decision": "keep",
            "supplements": ([{
                "slot": "exception",
                "text": "The rule applies unless the stated exception is met.",
                "context_ref_ids": ["context-ref-1"],
            }] if index == 0 else []),
            "reason": stage2_anchor_reason("keep"),
        } for index, locked in enumerate(job["locked_anchors"])]
    return {
        "version": contracts.STAGE2,
        "request_id": job["request_id"],
        "target_id": job["target_id"],
        "decision": decision,
        "anchors": anchors,
        "reason": stage2_reason(decision),
    }


class RootedFiniteGrammarTests(unittest.TestCase):
    def test_stage1_root_binds_request_target_and_finite_anchor_and_target_ref_ids(self):
        job = stage1_job()
        grammar = build_grammar(job)
        self.assertRegex(grammar, r"(?m)^root ::=")
        for value in (job["request_id"], job["target_id"], *job["anchor_ids"],
                      *job["catalog"]["target_refs"]):
            self.assertIn(json.dumps(json.dumps(value)), grammar)
        self.assertNotIn(json.dumps(json.dumps("foreign-anchor")), grammar)
        self.assertNotIn(json.dumps(json.dumps("context-ref-1")), grammar,
                         "stage1 grammar must not authorize evidence from context")
        self.assertIn(json.dumps(json.dumps("anchors") + ":"), grammar)

    def test_stage2_root_contains_each_locked_anchor_once_and_no_creation_slot(self):
        job = stage2_job()
        grammar = build_grammar(job)
        self.assertRegex(grammar, r"(?m)^root ::=")
        root = next(line for line in grammar.splitlines() if line.startswith("root ::="))
        anchors_rule = next(line for line in grammar.splitlines()
                            if line.startswith("anchors ::= "))
        outcomes = root.split(" | ")
        self.assertEqual(len(outcomes), 3)
        for decision in ("complete", "unresolved", "revisit_target"):
            outcome = next(part for part in outcomes
                           if json.dumps(json.dumps(decision)) in part)
            self.assertIn("anchors-" + decision, outcome,
                          "each global decision must use its cross-field-constrained anchor rule")
        for name in ("anchors-complete", "anchors-unresolved", "anchors-revisit_target"):
            rule = next(line for line in grammar.splitlines()
                        if line.startswith(name + " ::= "))
            choices = rule.split(" ::= ", 1)[1].split(" | ")
            self.assertTrue(choices)
            if name == "anchors-complete":
                self.assertTrue(all("-unresolved" not in choice for choice in choices))
            elif name == "anchors-unresolved":
                self.assertTrue(all("-unresolved" in choice for choice in choices))
        for index, locked in enumerate(job["locked_anchors"]):
            literal = json.dumps(json.dumps(locked["anchor_id"]))
            self.assertEqual(anchors_rule.count("locked-" + str(index)), 1)
            anchor_rule = next(line for line in grammar.splitlines()
                               if line.startswith("locked-" + str(index) + " ::= "))
            branches = anchor_rule.split(" | ")
            self.assertEqual(len(branches), 3)
            self.assertTrue(all(branch.count(literal) == 1 for branch in branches),
                            "each anchor decision branch must bind the locked ID once")
        for ref_id in job["catalog"]["context_refs"]:
            self.assertIn(json.dumps(json.dumps(ref_id)), grammar)
        self.assertNotIn(json.dumps(json.dumps("anchor-new-from-context")), grammar)
        self.assertNotIn('"primary_claim"', grammar,
                         "stage2 output must not receive a writable primary-claim field")

    def test_stage1_decision_branches_bound_reason_and_negative_has_literal_empty_anchors(self):
        job = stage1_job()
        grammar = build_grammar(job)
        root = next(line for line in grammar.splitlines() if line.startswith("root ::="))
        self.assertNotIn("reason :: text", root)
        self.assertIn("positive", root)
        self.assertIn("negative", root)
        anchors_field = json.dumps(json.dumps("anchors") + ":")
        negative = next(branch for branch in root.split(" | ")
                        if json.dumps(json.dumps("negative")) in branch)
        self.assertIn(anchors_field + " " + json.dumps("[]"), negative,
                      "negative grammar branch must encode anchors=[] literally")
        self.assertIn("positive-anchors ::=", grammar)
        self.assertNotIn("positive-anchors ::= \"[\" (", grammar,
                         "positive branch requires at least one anchor")
        reason_field = json.dumps(json.dumps("reason") + ":")
        for index, (decision, reasons) in enumerate(contracts.STAGE1_REASON_BY_DECISION.items()):
            branch = next(branch for branch in root.split(" | ")
                          if json.dumps(json.dumps(decision)) in branch)
            self.assertIn(reason_field + " stage1-reason-" + str(index), branch)
            reason_rule = next(line for line in grammar.splitlines()
                               if line.startswith("stage1-reason-" + str(index) + " ::= "))
            for reason in reasons:
                self.assertIn(json.dumps(json.dumps(reason)), reason_rule)

    def test_stage2_global_and_anchor_reason_codes_are_finite_and_decision_bound(self):
        grammar = build_grammar(stage2_job())
        root = next(line for line in grammar.splitlines() if line.startswith("root ::="))
        reason_field = json.dumps(json.dumps("reason") + ":")
        self.assertNotIn("reason :: text", root)
        for decision in contracts.STAGE2_REASON_BY_DECISION:
            branch = next(branch for branch in root.split(" | ")
                          if json.dumps(json.dumps(decision)) in branch)
            self.assertIn(reason_field + " stage2-reason-" + decision, branch)
            reason_rule = next(line for line in grammar.splitlines()
                               if line.startswith("stage2-reason-" + decision + " ::= "))
            for reason in contracts.STAGE2_REASON_BY_DECISION[decision]:
                self.assertIn(json.dumps(json.dumps(reason)), reason_rule)
        anchor_rule = next(line for line in grammar.splitlines()
                           if line.startswith("locked-0 ::= "))
        self.assertNotIn(json.dumps(json.dumps("anchor-new-from-context")), grammar)
        for decision, reasons in contracts.STAGE2_ANCHOR_REASON_BY_DECISION.items():
            branch = next(branch for branch in anchor_rule.split(" | ")
                          if json.dumps(json.dumps(decision)) in branch)
            self.assertIn(reason_field + " anchor-reason-" + decision, branch)
            reason_rule = next(line for line in grammar.splitlines()
                               if line.startswith("anchor-reason-" + decision + " ::= "))
            for reason in reasons:
                self.assertIn(json.dumps(json.dumps(reason)), reason_rule)
        for reason_text in contracts.REASON_TEXT_VI.values():
            self.assertNotIn(json.dumps(json.dumps(reason_text)), grammar)

    def test_root_is_fixed_json_contract_and_strings_are_json_escaped(self):
        job = stage1_job()
        job["request_id"] = 'req"\n雪'
        grammar = build_grammar(job)
        self.assertIn(json.dumps(json.dumps(job["request_id"])), grammar)
        self.assertIn("json-char", grammar)
        self.assertIn(json.dumps(json.dumps("request_id") + ":"), grammar)


class SourcePackingTests(unittest.TestCase):
    def test_stage1_payload_contains_exact_target_fragments_and_no_context_padding(self):
        source = "PRELUDE|TARGET-ONE|TARGET-TWO|TAIL-CONTEXT"
        lo = source.index("TARGET-ONE") + 3
        hi = source.index("TARGET-TWO") + 5
        cuts = [0, source.index("|TARGET-ONE") + 5,
                source.index("|TARGET-TWO") + 4, len(source)]
        atoms = {
            f"atom-{i}": {"atom_id": f"atom-{i}", "start_char": a, "end_char": b,
                          "quote": source[a:b], "target_intersecting": a < hi and lo < b}
            for i, (a, b) in enumerate(zip(cuts, cuts[1:]))
        }
        request = {"case_id": "synthetic-crossing", "source_hash": "a" * 64,
                   "expected_target_ids": ["target-crossing"],
                   "request_id": "original", "source_refs": [
                       {"role": "target", "start_char": lo, "end_char": hi,
                        "target_ids": ["target-crossing"]}]}
        with patch.object(core, "render_request", return_value={"catalog": {"atoms": atoms}}), \
             patch.object(core, "open_source", return_value=source):
            row = core.clipped_row(request, "fixture-store", "fixture-atoms")

        target_refs = sorted(row["target_refs"].values(), key=lambda ref: ref["start_char"])
        self.assertTrue(target_refs)
        self.assertEqual(target_refs[0]["start_char"], lo)
        self.assertEqual(target_refs[-1]["end_char"], hi)
        for previous, current in zip(target_refs, target_refs[1:]):
            self.assertEqual(previous["end_char"], current["start_char"],
                             "TARGET clipping must have no gaps or duplicate boundary chars")
        for ref in target_refs:
            self.assertGreaterEqual(ref["start_char"], lo)
            self.assertLessEqual(ref["end_char"], hi)
            self.assertEqual(ref["quote"], source[ref["start_char"]:ref["end_char"]])

        job = build_stage1(row, fixture_identity())
        packed = job["payload"]["messages"][0]["content"]
        for ref in target_refs:
            self.assertIn(ref["quote"], packed)
        self.assertNotIn("PRELUDE", packed)
        self.assertNotIn("TAIL-CONTEXT", packed)
        self.assertIn("|", packed, "literal source punctuation inside TARGET is retained")
        self.assertEqual(job["catalog"]["context_refs"], {})

    def test_no_anchor_uncertain_stage1_outcomes_do_not_create_stage2_jobs(self):
        row = fixture_row()
        identity = fixture_identity()
        first_job = stage1_job(row)
        cases = (("needs_context", ["exception"]),
                 ("unresolved", []),
                 ("unresolved", ["exception"]))
        for decision, needs in cases:
            with self.subTest(decision=decision, needs=needs):
                response = stage1_value(first_job, [], decision=decision)
                response["needs_context"] = needs
                normalized = validate_stage1(response, first_job)
                self.assertEqual(build_stage2(row, normalized, identity), [])
                self.assertNotEqual(normalized["decision"], "negative")


class Locked32LocalPreparationTests(unittest.TestCase):
    def test_prepare_and_preflight_cover_exact_32_targets_without_network_or_semantic_claim(self):
        with tempfile.TemporaryDirectory(prefix="au-target-context-test-") as folder:
            output = Path(folder) / "local-pilot"
            workload = core.prepare(output, manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
            checked = core.preflight(workload, cfg=None)
            target_ids = [row["target_id"] for row in workload["rows"]]
            self.assertEqual(len(target_ids), 32)
            self.assertEqual(len(set(target_ids)), 32)
            self.assertEqual(checked["status"], "pass")
            self.assertEqual(checked["target_count"], 32)
            self.assertEqual(checked["stage1_requests"], 32)
            self.assertEqual(checked["max_logical_requests"], 64)
            self.assertEqual(checked["network_requests"], 0)
            self.assertEqual(checked["grammar_compile"], "not_checked")
            self.assertEqual(checked["semantic_quality"], "not_assessed")
            self.assertTrue((output / "workload.json").is_file())
            self.assertTrue((output / "preflight.json").is_file())

    def test_preflight_rejects_source_row_config_and_code_fingerprint_mutations(self):
        with tempfile.TemporaryDirectory(prefix="au-target-context-invalidation-") as folder:
            workload = core.prepare(Path(folder) / "pilot", manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
        mutations = []
        changed_source = copy.deepcopy(workload)
        first_ref = next(iter(changed_source["rows"][0]["target_refs"].values()))
        first_ref["quote"] += "tampered"
        mutations.append(("source quote", changed_source))

        changed_config = copy.deepcopy(workload)
        changed_config["identity"]["model"] = "different-model"
        mutations.append(("runtime config", changed_config))

        changed_code = copy.deepcopy(workload)
        changed_code["code_sha256"] = "0" * 64
        mutations.append(("code fingerprint", changed_code))

        for label, changed in mutations:
            changed.pop("workload_sha256", None)
            changed["workload_sha256"] = core.fingerprint(changed)
            with self.subTest(label=label), self.assertRaises((TargetContextError, ValueError)):
                core.preflight(changed, cfg=None)


class Locked32LocalCliTests(unittest.TestCase):
    def test_prepare_preflight_and_dryrun_cli_cover_32_targets_without_remote_execution(self):
        with tempfile.TemporaryDirectory(prefix="au-target-context-cli-") as folder:
            base = Path(folder)
            prepared, checked, dryrun = base / "prepared", base / "checked", base / "dryrun"
            stdout = io.StringIO()
            with patch.object(cli, "study_config", return_value=(None, {}, {})), \
                 contextlib.redirect_stdout(stdout):
                prepare_code = cli.main(["prepare", "--output-root", str(prepared)])
                preflight_code = cli.main(["preflight", "--workload", str(prepared / "workload.json"),
                                           "--output-root", str(checked)])
                dryrun_code = cli.main(["run", "--workload", str(prepared / "workload.json"),
                                        "--output-root", str(dryrun), "--concurrency", "4"])

            self.assertEqual((prepare_code, preflight_code, dryrun_code), (0, 0, 0))
            preflight_result = json.loads((checked / "preflight.json").read_text(encoding="utf-8"))
            dryrun_result = json.loads((dryrun / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(preflight_result["target_count"], 32)
            self.assertEqual(preflight_result["stage1_requests"], 32)
            self.assertEqual(preflight_result["max_logical_requests"], 64)
            self.assertEqual(preflight_result["network_requests"], 0)
            self.assertEqual(dryrun_result["selected_target_count"], 32)
            self.assertEqual(dryrun_result["status"], "not_executed")
            self.assertEqual(dryrun_result["network_requests"], 0)
            self.assertEqual(dryrun_result["semantic_quality"], "not_assessed")
            self.assertIn('"network_executed": false', stdout.getvalue())

class LocalRunnerConcurrencyAndResumeTests(unittest.TestCase):
    @staticmethod
    def _negative_protocol_response(job):
        return {"version": contracts.STAGE1, "request_id": job["request_id"],
                "target_id": job["target_id"], "decision": "negative", "anchors": [],
                "needs_context": [], "reason": "no_legal_proposition"}

    def test_corrupt_terminal_receipt_is_rejected_before_provider_client_creation(self):
        with tempfile.TemporaryDirectory(prefix="au-target-context-corrupt-receipt-") as folder:
            root = Path(folder)
            workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
            target = workload["rows"][0]["target_id"]
            job = build_stage1(workload["rows"][0], workload["identity"])
            output_root = root / "run"
            with patch.object(runner, "mock_response", side_effect=self._negative_protocol_response):
                runner.run(workload, output_root=output_root, mock=True, concurrency=1,
                           target_ids=[target])

            receipt_path = output_root / "receipts" / f"{job['request_id']}.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            ledger = json.loads((output_root / "runtime_ledger.json").read_text(encoding="utf-8"))
            self.assertIn(ledger["jobs"][job["request_id"]]["status"],
                          {"verified", "invalid", "failed"})
            receipt["receipt_sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with patch.object(runner, "MockJobs") as provider_client:
                with self.assertRaisesRegex(ValueError, "corrupt receipt"):
                    runner.run(workload, output_root=output_root, mock=True, concurrency=1,
                               target_ids=[target])
            provider_client.assert_not_called()

    def test_changed_selection_resume_identity_rejects_before_provider_client_creation(self):
        with tempfile.TemporaryDirectory(prefix="au-target-context-stale-identity-") as folder:
            root = Path(folder)
            workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
            first_target = workload["rows"][0]["target_id"]
            changed_target = workload["rows"][1]["target_id"]
            output_root = root / "run"
            with patch.object(runner, "mock_response", side_effect=self._negative_protocol_response):
                runner.run(workload, output_root=output_root, mock=True, concurrency=1,
                           target_ids=[first_target])

            with patch.object(runner, "MockJobs") as provider_client:
                with self.assertRaisesRegex(ValueError, "stale run/selection identity"):
                    runner.run(workload, output_root=output_root, mock=True, concurrency=1,
                               target_ids=[changed_target])
            provider_client.assert_not_called()

    def test_rehashed_ledger_with_foreign_job_digest_is_rejected_before_provider_client_creation(self):
        with tempfile.TemporaryDirectory(prefix="au-target-context-foreign-ledger-") as folder:
            root = Path(folder)
            workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
            target = workload["rows"][0]["target_id"]
            output_root = root / "run"
            with patch.object(runner, "mock_response", side_effect=self._negative_protocol_response):
                runner.run(workload, output_root=output_root, mock=True, concurrency=1,
                           target_ids=[target])

            ledger_path = output_root / "runtime_ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            entry = next(iter(ledger["jobs"].values()))
            entry["job"]["payload_sha256"] = "0" * 64
            ledger["ledger_sha256"] = core.fingerprint(
                {key: value for key, value in ledger.items() if key != "ledger_sha256"})
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

            with patch.object(runner, "MockJobs") as provider_client:
                with self.assertRaisesRegex(ValueError, "stage1 job changed before dispatch"):
                    runner.run(workload, output_root=output_root, mock=True, concurrency=1,
                               target_ids=[target])
            provider_client.assert_not_called()

    def test_host_budget_and_proof_gates_remain_pending_without_provider_post(self):
        for gate in ("budget", "proof"):
            with self.subTest(gate=gate), tempfile.TemporaryDirectory(
                    prefix=f"au-target-context-{gate}-gate-") as folder:
                root = Path(folder)
                workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                        parent=core.DEFAULT_PARENT, cfg=None)
                target = workload["rows"][0]["target_id"]
                provider_posts = []
                real_mock_jobs = runner.MockJobs

                class CountingMockJobs:
                    def __init__(self, jobs):
                        self.client = real_mock_jobs(jobs, delay=0)

                    def add(self, jobs):
                        self.client.add(jobs)

                    @property
                    def max_inflight(self):
                        return self.client.max_inflight

                    def __call__(self, req, **kwargs):
                        if req.get_method() == "POST":
                            provider_posts.append(req.full_url)
                        return self.client(req, **kwargs)

                real_dispatch = runner.Accounting.dispatch

                def block_host_post(accounting, req, proof=None, **kwargs):
                    if req.get_method() == "POST":
                        if gate == "budget":
                            raise runner.BudgetError("synthetic local aggregate budget gate")
                        return real_dispatch(accounting, req, None, **kwargs)
                    return real_dispatch(accounting, req, proof, **kwargs)

                with patch.object(runner, "MockJobs", CountingMockJobs), \
                     patch.object(runner.Accounting, "dispatch", new=block_host_post):
                    report = runner.run(workload, output_root=root / "run", mock=True,
                                        target_ids=[target], concurrency=1)

                receipt = json.loads((root / "run" / "receipts" /
                                      f"{build_stage1(workload['rows'][0], workload['identity'])['request_id']}.json"
                                      ).read_text(encoding="utf-8"))
                self.assertEqual(report["protocol_counts"]["pending"], 1)
                self.assertEqual(report["protocol_counts"]["failed"], 0)
                self.assertEqual(report["transport_POST_attempts"], 0)
                self.assertEqual(report["provider_POST_attempts"], 0)
                self.assertEqual(provider_posts, [], "local host gates must stop before fake provider POST")
                self.assertEqual(receipt["status"], "pending")
                self.assertEqual(receipt["error"],
                                 "BudgetError" if gate == "budget" else "HostPolicyError")

    def test_malformed_model_json_is_invalid_protocol_output_not_local_pending(self):
        with tempfile.TemporaryDirectory(prefix="au-target-context-malformed-model-json-") as folder:
            root = Path(folder)
            workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
            target = workload["rows"][0]["target_id"]
            posts = []

            class MalformedModelJobs:
                def __init__(self, jobs):
                    self.jobs = {job["payload_sha256"]: job for job in jobs}
                    self.finished = {}

                def add(self, jobs):
                    self.jobs.update({job["payload_sha256"]: job for job in jobs})

                @property
                def max_inflight(self):
                    return 1

                def __call__(self, req, **_kwargs):
                    if req.full_url.endswith("/health"):
                        return runner.Response(b'{"ready":true}')
                    if req.get_method() == "GET":
                        jid = req.full_url.rsplit("/", 1)[-1]
                        if jid not in self.finished:
                            raise HTTPError(req.full_url, 404, "Unknown job", {},
                                            BytesIO(b'{"detail":"Unknown job"}'))
                        return runner.Response(json.dumps(self.finished[jid]).encode())

                    wire = json.loads(req.data)
                    jid = wire["job_id"]
                    posts.append(jid)
                    response = {"model": wire["payload"]["model"],
                                "choices": [{"finish_reason": "stop",
                                             "message": {"content": "{malformed model JSON"}}]}
                    envelope = {"job_id": jid, "payload_sha256": jid, "status": "completed",
                                "response": response,
                                "response_sha256": runner.payload_digest(response)}
                    self.finished[jid] = envelope
                    return runner.Response(json.dumps(envelope).encode())

            with patch.object(runner, "MockJobs", MalformedModelJobs):
                report = runner.run(workload, output_root=root / "run", mock=True,
                                    target_ids=[target], concurrency=1)

            self.assertEqual(len(posts), 1)
            self.assertEqual(report["protocol_counts"]["invalid"], 1)
            self.assertEqual(report["protocol_counts"]["failed"], 0)
            self.assertEqual(report["protocol_counts"]["pending"], 0)
            self.assertEqual(report["transport_POST_attempts"], 1)

    def test_four_jobs_reserve_before_post_isolate_failure_and_resume_without_post(self):
        with tempfile.TemporaryDirectory(prefix="au-target-context-runner-") as folder:
            root = Path(folder)
            workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
            run_root = root / "run"
            selected = [row["target_id"] for row in workload["rows"][:4]]
            failing_target = selected[0]
            barrier = threading.Barrier(4)
            submitted = []
            checkpoints_seen = []
            RealMockJobs = runner.MockJobs

            class BarrierJobs:
                def __init__(self, jobs):
                    self.client = RealMockJobs(jobs, delay=0.02)

                def add(self, jobs):
                    self.client.add(jobs)

                @property
                def max_inflight(self):
                    return self.client.max_inflight

                def __call__(self, req, **kwargs):
                    if req.get_method() == "POST":
                        wire = json.loads(req.data)
                        ledger = json.loads((run_root / "runtime_ledger.json").read_text(encoding="utf-8"))
                        entry = next(value for value in ledger["jobs"].values()
                                     if value["job"]["payload_sha256"] == wire["job_id"])
                        attempt = next(value for value in ledger["attempts"]
                                       if value["job_id"] == wire["job_id"])
                        self_check = (entry["status"] == "reserved"
                                      and attempt["usage"] is None
                                      and attempt["usage_state"] == "unknown"
                                      and ledger["reserved_output_tokens"] >= wire["payload"]["max_tokens"])
                        checkpoints_seen.append(self_check)
                        submitted.append(wire["job_id"])
                        barrier.wait(timeout=10)
                    return self.client(req, **kwargs)

            def protocol_response(job):
                value = {"version": contracts.STAGE1, "request_id": job["request_id"],
                         "target_id": job["target_id"], "decision": "negative", "anchors": [],
                         "needs_context": [], "reason": "no_legal_proposition"}
                if job["target_id"] == failing_target:
                    value["request_id"] = "wrong-request-id"
                return value

            with patch.object(runner, "MockJobs", BarrierJobs), \
                 patch.object(runner, "mock_response", side_effect=protocol_response):
                first = runner.run(workload, output_root=run_root, mock=True,
                                   concurrency=4, target_ids=selected, cfg=None)
                post_count_after_first = len(submitted)
                second = runner.run(workload, output_root=run_root, mock=True,
                                    concurrency=4, target_ids=selected, cfg=None)

            self.assertEqual(first["mode"], "mock")
            self.assertFalse(first["network_executed"])
            self.assertEqual(first["selected_target_count"], 4)
            self.assertEqual(first["stage1_requests"], 4)
            self.assertEqual(first["stage2_requests"], 0)
            self.assertEqual(first["mock_max_inflight"], 4)
            self.assertEqual(first["transport_POST_attempts"], 4)
            self.assertEqual(first["provider_POST_attempts"], 0)
            self.assertTrue(all(checkpoints_seen), "each fake POST must observe a durable pre-POST reservation")
            self.assertEqual(len(submitted), 4)
            statuses = {row["target_id"]: row["stage1_status"] for row in first["results"]}
            self.assertEqual(statuses[failing_target], "invalid")
            self.assertEqual(sum(status == "verified" for status in statuses.values()), 3,
                             "one invalid job must not discard sibling outputs")
            self.assertEqual(first["unknown_usage_jobs"], 4)
            self.assertEqual(first["status"], "incomplete",
                             "a completed batch with protocol-invalid output is not a complete run")
            self.assertEqual(first["protocol_counts"].get("invalid"), 1,
                             "run summary must count invalid outputs explicitly")
            self.assertEqual(post_count_after_first, 4)
            self.assertEqual(second["transport_POST_attempts"], 4)
            self.assertEqual(len(submitted), post_count_after_first,
                             "terminal receipts must resume without another POST")

    def test_shared_readiness_budget_is_600_seconds_with_bounded_worker_wait(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
            target = workload["rows"][0]["target_id"]
            observed = []
            real_transport = runner.PairedTransport

            def record_transport(*args, **kwargs):
                observed.append(kwargs.get("readiness_seconds"))
                return real_transport(*args, **kwargs)

            with patch.object(runner, "PairedTransport", side_effect=record_transport):
                report = runner.run(workload, output_root=root / "run", mock=True,
                                    target_ids=[target], concurrency=1)
            readiness = json.loads((root / "run" / "readiness.json").read_text(encoding="utf-8"))
            self.assertTrue(observed)
            self.assertEqual(readiness["deadline_seconds"], 600,
                             "shared warmup must retain its approved 600s deadline")
            self.assertGreater(readiness["retrieval_deadline_seconds"], 0)
            self.assertLessEqual(readiness["retrieval_deadline_seconds"], 30,
                                 "worker retrieval must remain bounded independently")
            self.assertLessEqual(max(observed), 30,
                                 "each worker receives only the bounded retrieval timeout")
            self.assertEqual(report["status"], "complete" if all(
                result["status"] == "verified" for result in report["results"]) else "incomplete")

    def test_latency_report_names_post_ack_scope_and_wall_duration_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
            target = workload["rows"][0]["target_id"]
            report = runner.run(workload, output_root=root / "run", mock=True,
                                target_ids=[target], concurrency=1)
            self.assertIn("POST_ack_latency_ms", report,
                          "sum of POST acknowledgement durations must be labeled as such")
            self.assertIn("elapsed_wall_ms", report,
                          "run wall-clock duration must be reported separately")
            self.assertGreaterEqual(report["elapsed_wall_ms"],
                                    report["POST_ack_latency_ms"])

    def test_unknown_first_attempt_remains_accounted_after_same_job_retry_has_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                    parent=core.DEFAULT_PARENT, cfg=None)
            target = workload["rows"][0]["target_id"]
            post_ids = []

            class AdvancingClock:
                value = 0.0

                def __call__(self):
                    return self.value

                def sleep(self, seconds):
                    self.value += seconds

            class LostAckJobs:
                def __init__(self, jobs):
                    self.jobs = {job["payload_sha256"]: job for job in jobs}
                    self.post_counts = {}
                    self.completed = {}

                def add(self, jobs):
                    self.jobs.update({job["payload_sha256"]: job for job in jobs})

                @property
                def max_inflight(self):
                    return 1

                def __call__(self, req, **_kwargs):
                    if req.full_url.endswith("/health"):
                        return runner.Response(b'{"ready":true}')
                    if req.get_method() == "GET":
                        jid = req.full_url.rsplit("/", 1)[-1]
                        if jid not in self.completed:
                            raise HTTPError(req.full_url, 404, "Unknown job", {},
                                            BytesIO(b'{"detail":"Unknown job"}'))
                        return runner.Response(json.dumps(self.completed[jid]).encode())

                    wire = json.loads(req.data)
                    jid = wire["job_id"]
                    post_ids.append(jid)
                    self.post_counts[jid] = self.post_counts.get(jid, 0) + 1
                    if self.post_counts[jid] == 1:
                        raise HTTPError(req.full_url, 503, "unknown acknowledgement", {},
                                        BytesIO(b'{"error":"busy"}'))
                    job = self.jobs[jid]
                    value = {"version": contracts.STAGE1, "request_id": job["request_id"],
                             "target_id": job["target_id"], "decision": "negative",
                             "anchors": [], "needs_context": [],
                             "reason": "no_legal_proposition"}
                    response = {"model": wire["payload"]["model"], "usage": {
                                    "prompt_tokens": 11, "completion_tokens": 3,
                                    "total_tokens": 14},
                                "choices": [{"finish_reason": "stop",
                                             "message": {"content": json.dumps(value)}}]}
                    envelope = {"job_id": jid, "payload_sha256": jid, "status": "completed",
                                "response": response,
                                "usage": response["usage"],
                                "response_sha256": runner.payload_digest(response)}
                    self.completed[jid] = envelope
                    return runner.Response(json.dumps(envelope).encode())

            fake_clock = AdvancingClock()
            with patch.object(runner, "MockJobs", LostAckJobs):
                report = runner.run(workload, output_root=root / "run", mock=True,
                                    target_ids=[target], concurrency=1, clock=fake_clock,
                                    sleep=fake_clock.sleep)

            self.assertEqual(len(post_ids), 2)
            self.assertEqual(post_ids[0], post_ids[1], "recovery retries the identical job ID")
            ledger = json.loads((root / "run" / "runtime_ledger.json").read_text(encoding="utf-8"))
            attempts = [attempt for attempt in ledger["attempts"]
                        if attempt["job_id"] == post_ids[0]]
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0]["usage_state"], "unknown")
            self.assertEqual(attempts[1]["usage_state"], "provider")
            self.assertEqual(report["unknown_provider_attempts"], 1,
                             "known retry usage must not erase an earlier unknown attempt")


class SourcePackingIntegrationTests(unittest.TestCase):
    def test_stage1_prompt_has_synthetic_holding_and_party_assertion_examples_without_source_quotes(self):
        row = fixture_row()
        content = build_stage1(row, fixture_identity())["payload"]["messages"][0]["content"]
        self.assertIn('"The court held this notice insufficient."', content)
        self.assertIn('"The applicant argues the notice is invalid."', content)
        self.assertIn("Short synthetic examples", content)
        examples = content.split("INPUT:\n", 1)[0]
        for source_quote in ("TARGET_ATOM_ONE", "TARGET_ATOM_TWO", "UNUSED_TARGET_ATOM",
                             "CONTEXT_ONLY_SUFFIX"):
            self.assertNotIn(source_quote, examples,
                             "few-shot examples must not leak current or gold source text")
        self.assertTrue(all(text not in content for text in contracts.REASON_TEXT_VI.values()),
                        "human-readable reason_text must remain host-only")

    def test_stage1_no_anchor_needs_and_unresolved_results_enter_manual_queue_without_stage2(self):
        cases = (("needs_context", ["exception"], "insufficient_target", True),
                 ("unresolved", [], "unclear_attribution", True),
                 ("unresolved", ["exception"], "missing_qualification", True),
                 ("negative", [], "no_legal_proposition", False))
        for decision, needs, reason, revisit_expected in cases:
            with self.subTest(decision=decision, needs=needs), \
                    tempfile.TemporaryDirectory(prefix="au-target-context-manual-revisit-") as folder:
                root = Path(folder)
                workload = core.prepare(root / "prepared", manifest=core.DEFAULT_MANIFEST,
                                        parent=core.DEFAULT_PARENT, cfg=None)
                row = workload["rows"][0]

                def response(job):
                    return {"version": contracts.STAGE1, "request_id": job["request_id"],
                            "target_id": job["target_id"], "decision": decision,
                            "anchors": [], "needs_context": needs, "reason": reason}

                with patch.object(runner, "mock_response", side_effect=response):
                    report = runner.run(workload, output_root=root / "run", mock=True,
                                        target_ids=[row["target_id"]], concurrency=1, cfg=None)

                self.assertEqual(report["stage2_requests"], 0)
                if revisit_expected:
                    self.assertEqual(report["revisit_queue"], [{
                        "target_id": row["target_id"], "reason": reason,
                        "reason_text": contracts.REASON_TEXT_VI[reason],
                        "status": "target_review_required", "auto_dispatch": False,
                    }])
                else:
                    self.assertEqual(report["revisit_queue"], [])

    def test_stage2_packs_only_anchor_evidence_and_context_not_unselected_target_atoms(self):
        row = fixture_row()
        first_job = stage1_job(row)
        anchors = [
            {"anchor_id": first_job["anchor_ids"][0], "kind": "holding",
             "primary_claim": "First target proposition.", "target_ref_ids": ["target-ref-1"],
             "needs_context": ["exception"]},
            {"anchor_id": first_job["anchor_ids"][1], "kind": "holding",
             "primary_claim": "Second target proposition.", "target_ref_ids": ["target-ref-2"],
             "needs_context": ["scope"]},
        ]
        stage1 = validate_stage1(stage1_value(first_job, anchors), first_job)
        jobs = build_stage2(row, stage1, fixture_identity())
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        data = json.loads(job["payload"]["messages"][0]["content"].split("INPUT:\n", 1)[1])
        packed_target = {evidence["ref_id"]: evidence["text"]
                         for anchor in data["locked_anchors"]
                         for evidence in anchor["primary_evidence"]}
        self.assertEqual(set(packed_target), {"target-ref-1", "target-ref-2"})
        self.assertNotIn("UNUSED_TARGET_ATOM", job["payload"]["messages"][0]["content"])
        self.assertIn("CONTEXT_ONLY_SUFFIX", job["payload"]["messages"][0]["content"])
        self.assertNotIn("TARGET_BODY", data,
                         "stage2 must carry only locked-anchor evidence, not the whole TARGET packet")
        stage2_content = job["payload"]["messages"][0]["content"]
        self.assertNotIn("reason_text", stage2_content)
        self.assertTrue(all(text not in stage2_content for text in contracts.REASON_TEXT_VI.values()))

    def test_stage1_has_no_context_payload_even_when_context_catalog_is_present(self):
        row = fixture_row()
        job = build_stage1(row, fixture_identity())
        content = job["payload"]["messages"][0]["content"]
        self.assertNotIn("CONTEXT_ONLY_SUFFIX", content)
        self.assertNotIn('"CONTEXT"', content)
        self.assertEqual(job["catalog"]["context_refs"], {})


class HostResponseBoundaryTests(unittest.TestCase):
    def test_stage1_accepts_only_reason_codes_allowed_for_each_decision(self):
        job = stage1_job()
        for decision, allowed in contracts.STAGE1_REASON_BY_DECISION.items():
            for reason in allowed:
                anchors = [] if decision != "positive" else None
                needs = ["exception"] if decision == "needs_context" else []
                response = stage1_value(job, anchors, decision=decision)
                response["needs_context"] = needs
                response["reason"] = reason
                with self.subTest(decision=decision, reason=reason):
                    self.assertEqual(validate_stage1(response, job)["reason"], reason)

    def test_stage1_rejects_wrong_decision_reason_unknown_reason_and_long_free_text(self):
        job = stage1_job()
        invalid_reasons = (
            ("positive", "no_legal_proposition"),
            ("negative", "none"),
            ("needs_context", "revisit_target_required"),
            ("unresolved", "primary_not_supported"),
            ("positive", "reason_outside_v2_enums"),
            ("positive", "x" * 538),
        )
        for decision, reason in invalid_reasons:
            response = stage1_value(job, [], decision=decision)
            if decision == "positive":
                response = stage1_value(job, decision=decision)
            response["needs_context"] = ["exception"] if decision == "needs_context" else []
            response["reason"] = reason
            with self.subTest(decision=decision, reason=reason[:32]), self.assertRaises(
                    (TargetContextError, ValueError, TypeError)):
                validate_stage1(response, job)

    def test_stage2_accepts_reason_codes_only_on_their_global_and_anchor_decisions(self):
        for decision, allowed in contracts.STAGE2_REASON_BY_DECISION.items():
            for reason in allowed:
                job = stage2_job(anchors=stage2_job().get("locked_anchors"))
                value = stage2_value(job, decision=decision)
                if decision == "unresolved":
                    for anchor in value["anchors"]:
                        anchor["decision"] = "unresolved"
                        anchor["supplements"] = []
                        anchor["reason"] = "context_insufficient"
                value["reason"] = reason
                with self.subTest(scope="global", decision=decision, reason=reason):
                    self.assertEqual(validate_stage2(value, job)["reason"], reason)

        for decision, allowed in contracts.STAGE2_ANCHOR_REASON_BY_DECISION.items():
            job = stage2_job(anchors=[stage2_job().get("locked_anchors")[0]])
            for reason in allowed:
                value = stage2_value(job)
                answer = value["anchors"][0]
                answer["decision"] = decision
                answer["supplements"] = []
                answer["reason"] = reason
                if decision == "reject":
                    value["decision"] = "complete"
                elif decision == "unresolved":
                    value["decision"] = "unresolved"
                    value["reason"] = "context_insufficient"
                with self.subTest(scope="anchor", decision=decision, reason=reason):
                    self.assertEqual(validate_stage2(value, job)["anchors"][0]["reason"], reason)

    def test_stage2_rejects_wrong_decision_reasons_unknown_reason_and_long_free_text(self):
        job = stage2_job(anchors=[stage2_job().get("locked_anchors")[0]])
        global_bad = stage2_value(job)
        global_bad["reason"] = "revisit_target_required"
        with self.assertRaises((TargetContextError, ValueError, TypeError)):
            validate_stage2(global_bad, job)

        anchor_bad = stage2_value(job)
        anchor_bad["anchors"][0]["reason"] = "primary_not_supported"
        with self.assertRaises((TargetContextError, ValueError, TypeError)):
            validate_stage2(anchor_bad, job)

        for scope, reason in (("global", "unknown_reason"),
                              ("global", "x" * 538),
                              ("anchor", "unknown_reason"),
                              ("anchor", "x" * 538)):
            value = stage2_value(job)
            if scope == "global":
                value["reason"] = reason
            else:
                value["anchors"][0]["reason"] = reason
            with self.subTest(scope=scope, length=len(reason)), self.assertRaises(
                    (TargetContextError, ValueError, TypeError)):
                validate_stage2(value, job)

    def test_v1_stage1_and_stage2_responses_are_rejected(self):
        one = stage1_job()
        old_one = stage1_value(one)
        old_one["version"] = "au-target-only-v1"
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage1(old_one, one)

        two = stage2_job(anchors=[stage2_job().get("locked_anchors")[0]])
        old_two = stage2_value(two)
        old_two["version"] = "au-context-supplement-v1"
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage2(old_two, two)

    def test_stage1_attaches_primary_evidence_only_from_target_catalog(self):
        job = stage1_job()
        checked = validate_stage1(stage1_value(job), job)
        self.assertEqual(checked["anchors"][0]["anchor_id"], job["anchor_ids"][0])
        self.assertEqual(checked["anchors"][0]["primary_claim"],
                         "The court applied the stated test.")
        evidence = checked["anchors"][0]["primary_evidence"]
        self.assertTrue(evidence)
        self.assertTrue(all(ref["ref_id"] in job["catalog"]["target_refs"]
                            for ref in evidence))
        self.assertFalse(any(ref["ref_id"] in job["catalog"]["context_refs"]
                             for ref in evidence))

    def test_stage1_rejects_duplicate_or_unissued_anchor_ids_and_foreign_target_refs(self):
        job = stage1_job()
        one = stage1_value(job)["anchors"][0]
        duplicate = [copy.deepcopy(one), copy.deepcopy(one)]
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage1(stage1_value(job, duplicate), job)

        foreign_anchor = copy.deepcopy(one)
        foreign_anchor["anchor_id"] = "anchor-not-issued"
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage1(stage1_value(job, [foreign_anchor]), job)

        context_as_primary = copy.deepcopy(one)
        context_as_primary["target_ref_ids"] = ["context-ref-1"]
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage1(stage1_value(job, [context_as_primary]), job)

    def test_stage1_rejects_malformed_types_and_wrong_request_binding(self):
        job = stage1_job()
        wrong_type = stage1_value(job)
        wrong_type["anchors"][0]["primary_claim"] = {"claim": "object is not a string"}
        with self.assertRaises((TargetContextError, ValueError, TypeError)):
            validate_stage1(wrong_type, job)

        wrong_needs = stage1_value(job)
        wrong_needs["anchors"][0]["needs_context"] = "exception"
        with self.assertRaises((TargetContextError, ValueError, TypeError)):
            validate_stage1(wrong_needs, job)

        wrong_request = stage1_value(job)
        wrong_request["request_id"] = "another-job"
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage1(wrong_request, job)

    def test_stage1_keeps_missing_or_ambiguous_anchor_unresolved_instead_of_negative(self):
        job = stage1_job()
        unresolved = stage1_value(job, [], decision="needs_context")
        checked = validate_stage1(unresolved, job)
        self.assertIn(checked["decision"], {"needs_context", "unresolved"})
        self.assertEqual(checked["anchors"], [])

    def test_stage2_uses_one_job_for_all_locked_anchors_and_preserves_primary_claims(self):
        row = fixture_row()
        identity = fixture_identity()
        first_job = stage1_job(row)
        primary = validate_stage1(stage1_value(first_job, [
            {"anchor_id": first_job["anchor_ids"][0], "kind": "holding",
             "primary_claim": "The court applied the stated test.",
             "target_ref_ids": ["target-ref-1"], "needs_context": ["exception"]},
            {"anchor_id": first_job["anchor_ids"][1], "kind": "holding",
             "primary_claim": "The court resolved a second issue.",
             "target_ref_ids": ["target-ref-2"], "needs_context": ["scope"]},
        ]), first_job)
        built = build_stage2(row, primary, identity)
        self.assertEqual(len(built), 1)
        job = built[0]
        self.assertEqual(job["stage"], 2)
        self.assertEqual([a["anchor_id"] for a in job["locked_anchors"]],
                         first_job["anchor_ids"][:2])
        self.assertEqual(len(job["locked_anchors"]), 2,
                         "both context-needing anchors belong in one stage2 job")

        checked = validate_stage2(stage2_value(job), job)
        self.assertEqual([a["anchor_id"] for a in checked["anchors"]],
                         first_job["anchor_ids"][:2])
        for locked in job["locked_anchors"]:
            result = next(a for a in checked["anchors"] if a["anchor_id"] == locked["anchor_id"])
            self.assertEqual(result["primary_claim"], locked["primary_claim"])
        self.assertEqual(checked["anchors"][0]["supplements"][0]["context_evidence"][0]["ref_id"],
                         "context-ref-1")

    def test_stage2_rejects_anchor_replacement_duplication_and_attempted_primary_rewrite(self):
        job = stage2_job()
        good = stage2_value(job)
        wrong_id = copy.deepcopy(good)
        wrong_id["anchors"][0]["anchor_id"] = "anchor-new-from-context"
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage2(wrong_id, job)

        duplicate = copy.deepcopy(good)
        duplicate["anchors"][1] = copy.deepcopy(duplicate["anchors"][0])
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage2(duplicate, job)

        rewrite = copy.deepcopy(good)
        rewrite["anchors"][0]["primary_claim"] = "A new proposition found only in context."
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage2(rewrite, job)

        extra_creation_field = copy.deepcopy(good)
        extra_creation_field["new_anchors"] = [{"primary_claim": "from context"}]
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage2(extra_creation_field, job)

        foreign_context_ref = copy.deepcopy(good)
        foreign_context_ref["anchors"][0]["supplements"][0]["context_ref_ids"] = [
            "not-in-this-packet"
        ]
        with self.assertRaises((TargetContextError, ValueError)):
            validate_stage2(foreign_context_ref, job)

    def test_stage2_context_only_new_proposition_remains_supplement_not_primary_au(self):
        job = stage2_job(anchors=[{
            "anchor_id": "anchor-a1",
            "primary_claim": "The court applied the stated test.",
            "target_ref_ids": ["target-ref-1"],
        }])
        attack = stage2_value(job, anchors=[{
            "anchor_id": "anchor-a1",
            "decision": "keep",
            "supplements": [{"slot": "scope",
                             "text": "Context states a separate proposition not present in TARGET.",
                             "context_ref_ids": ["context-ref-1"]}],
            "reason": "none",
        }])
        result = validate_stage2(attack, job)
        self.assertEqual(len(result["anchors"]), 1)
        self.assertEqual(result["anchors"][0]["anchor_id"], "anchor-a1")
        self.assertEqual(result["anchors"][0]["primary_claim"],
                         "The court applied the stated test.")
        self.assertEqual(len(result["anchors"][0]["supplements"]), 1)
        self.assertNotIn("new_anchors", result)
        self.assertNotIn("context_primary", result)


if __name__ == "__main__":
    unittest.main()
