"""Independent local contract tests for au-target-primary-support-v1.

Synthetic spans and model replies only. These tests do not invoke inference,
network access, deployment, or semantic AU evaluation.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_target_context import contracts, core, prompts, runner
from knowledge_base.pipeline_v1.au_target_context import anchor_order_probe
from knowledge_base.pipeline_v1.au_target_context.grammar import build_grammar


PROFILE = "primary_support_v1"
IDENTITY = {"model": "synthetic-model", "enable_thinking": False}


def row_with_refs(count=10):
    quotes = [f"TARGET_REF_{index:02d}_" + chr(65 + index) * (index + 3)
              for index in range(count)]
    quotes.append("CONTEXT_ONLY_REF")
    source = " | ".join(quotes)
    refs = {}
    cursor = 0
    for index, quote in enumerate(quotes):
        start = source.index(quote, cursor)
        refs[f"target-{index}"] = {
            "ref_id": f"target-{index}", "source_atom_id": f"atom-{index}",
            "case_id": "primary-support-fixture", "source_hash": "b" * 64,
            "start_char": start, "end_char": start + len(quote), "quote": quote,
            "role": "target_body",
        }
        cursor = start + len(quote)
    context = refs.pop(f"target-{count}")
    context["ref_id"] = "context-only"
    context["role"] = "context"
    return {
        "target_id": "target-primary-support", "case_id": "primary-support-fixture",
        "source_hash": "b" * 64,
        "target": {"start_char": 0, "end_char": context["start_char"]},
        "request": {"request_id": "source-request"},
        "target_refs": refs, "context_refs": {"context-only": context},
        "_source": source, **prompts.prompt_metadata(PROFILE),
    }


def stage1_job(row=None):
    return core.build_stage1(row or row_with_refs(), IDENTITY)


def selection(job, anchors=None, *, decision="positive", needs=()):
    if anchors is None:
        anchors = [{"anchor_id": job["anchor_ids"][0], "kind": "holding",
                    "primary_ref_id": "target-0", "supporting_ref_ids": ["target-1"],
                    "needs_context": ["exception"]}]
    reason = {"positive": "none", "negative": "no_legal_proposition",
              "needs_context": "insufficient_target", "unresolved": "unclear_attribution"}[decision]
    return {"version": contracts.stage1_version(PROFILE), "request_id": job["request_id"],
            "target_id": job["target_id"], "decision": decision,
            "anchors": copy.deepcopy(anchors), "needs_context": list(needs), "reason": reason}


def input_data(job):
    content = job["payload"]["messages"][0]["content"]
    return json.loads(content.split("\nINPUT:\n", 1)[1])


class PrimarySupportWireAndGrammarTests(unittest.TestCase):
    def test_profile_uses_new_wire_keys_and_fixed_slot_ids(self):
        job = stage1_job()
        data = input_data(job)
        self.assertEqual(data["version"], "au-target-primary-support-v1")
        self.assertEqual(data["anchor_keys"], ["anchor_id", "kind", "primary_ref_id",
                                               "supporting_ref_ids", "needs_context"])
        self.assertEqual(contracts.stage1_version(PROFILE), "au-target-primary-support-v1")
        grammar = build_grammar(job)
        for index, anchor_id in enumerate(job["anchor_ids"][:3], 1):
            line = next(value for value in grammar.splitlines()
                        if value.startswith(f"anchor-slot-{index} ::= "))
            self.assertIn(json.dumps(json.dumps(anchor_id)), line)
            for other in job["anchor_ids"][:3]:
                if other != anchor_id:
                    self.assertNotIn(json.dumps(json.dumps(other)), line)
        self.assertIn("primary_ref_id", grammar)
        self.assertIn("supporting_ref_ids", grammar)
        self.assertNotIn("target_ref_ids", grammar)
        support_rules = {line.split(" ::= ", 1)[0]: line for line in grammar.splitlines()
                         if line.startswith("supporting-refs-") and "-id ::=" in line}
        for index, primary_id in enumerate(job["catalog"]["target_refs"]):
            allowed = [ref_id for ref_id in job["catalog"]["target_refs"] if ref_id != primary_id]
            rule = support_rules[f"supporting-refs-{index}-id"]
            self.assertNotIn(json.dumps(json.dumps(primary_id)), rule)
            self.assertIn(json.dumps(json.dumps(allowed[0])), rule,
                          "each primary branch must permit nonempty support when another TARGET ref exists")

    def test_empty_and_single_reference_catalogs_have_safe_grammar_and_validation(self):
        empty = row_with_refs(0)
        job = stage1_job(empty)
        grammar = build_grammar(job)
        self.assertIn('"[]"', grammar)
        negative = selection(job, [], decision="negative")
        self.assertEqual(core.validate_stage1(negative, job)["anchors"], [])
        with self.assertRaises((core.TargetContextError, ValueError)):
            core.validate_stage1(selection(job), job)

        one = row_with_refs(1)
        job = stage1_job(one)
        accepted = selection(job, [{"anchor_id": job["anchor_ids"][0], "kind": "holding",
                                    "primary_ref_id": "target-0", "supporting_ref_ids": [],
                                    "needs_context": []}])
        normalized = core.validate_stage1(accepted, job)
        self.assertEqual(normalized["anchors"][0]["supporting_ref_ids"], [])
        self.assertNotIn(json.dumps(json.dumps("context-only")), build_grammar(job))

    def test_primary_support_caps_duplicates_and_foreign_ids_are_rejected(self):
        job = stage1_job()
        valid = selection(job)
        max_support = copy.deepcopy(valid)
        max_support["anchors"][0]["supporting_ref_ids"] = [f"target-{i}" for i in range(1, 8)]
        accepted = core.validate_stage1(max_support, job)["anchors"][0]
        self.assertEqual(len(accepted["supporting_evidence"]), 7)
        self.assertEqual(len(accepted["target_ref_ids"]), 8)
        bads = []
        bad = copy.deepcopy(valid); bad["anchors"][0]["supporting_ref_ids"] = ["target-1"] * 2; bads.append(bad)
        bad = copy.deepcopy(valid); bad["anchors"][0]["supporting_ref_ids"] = [f"target-{i}" for i in range(8)]; bads.append(bad)
        bad = copy.deepcopy(valid); bad["anchors"][0]["primary_ref_id"] = "foreign"; bads.append(bad)
        bad = copy.deepcopy(valid); bad["anchors"][0]["primary_ref_id"] = "context-only"; bads.append(bad)
        bad = copy.deepcopy(valid); bad["anchors"][0]["supporting_ref_ids"] = ["target-0"]; bads.append(bad)
        bad = copy.deepcopy(valid); bad["anchors"][0]["supporting_ref_ids"] = ["context-only"]; bads.append(bad)
        for response in bads:
            with self.subTest(response=response), self.assertRaises((core.TargetContextError, ValueError)):
                core.validate_stage1(response, job)

    def test_support_order_is_irrelevant_but_host_evidence_is_offset_sorted_and_role_separate(self):
        row = row_with_refs()
        job = stage1_job(row)
        raw = selection(job)
        raw["anchors"][0]["supporting_ref_ids"] = ["target-4", "target-2", "target-3"]
        normalized = core.validate_stage1(raw, job)
        anchor = normalized["anchors"][0]
        expected_support = ["target-2", "target-3", "target-4"]
        self.assertEqual(anchor["primary_ref_id"], "target-0")
        self.assertEqual(anchor["supporting_ref_ids"], expected_support)
        self.assertEqual(anchor["primary_evidence"], [row["target_refs"]["target-0"]])
        self.assertEqual(anchor["supporting_evidence"], [row["target_refs"][ref] for ref in expected_support])
        self.assertEqual(anchor["target_ref_ids"], ["target-0", *expected_support])
        self.assertEqual(anchor["primary_claim"], row["target_refs"]["target-0"]["quote"])
        self.assertNotIn(row["target_refs"]["target-2"]["quote"], anchor["primary_claim"])
        self.assertEqual(anchor["primary_claim"], row["_source"][
            row["target_refs"]["target-0"]["start_char"]:row["target_refs"]["target-0"]["end_char"]])

    def test_long_primary_quote_is_exact_and_never_truncated(self):
        row = row_with_refs(1)
        source = "P" * 421 + "|support"
        row["_source"] = source
        row["target_refs"] = {
            "primary-long": {"ref_id": "primary-long", "source_atom_id": "a", "case_id": row["case_id"],
                             "source_hash": row["source_hash"], "start_char": 0, "end_char": 421,
                             "quote": source[:421], "role": "target_body"},
            "support-short": {"ref_id": "support-short", "source_atom_id": "b", "case_id": row["case_id"],
                              "source_hash": row["source_hash"], "start_char": 422, "end_char": len(source),
                              "quote": source[422:], "role": "target_body"},
        }
        job = stage1_job(row)
        raw = selection(job, [{"anchor_id": job["anchor_ids"][0], "kind": "holding",
                               "primary_ref_id": "primary-long", "supporting_ref_ids": ["support-short"],
                               "needs_context": []}])
        anchor = core.validate_stage1(raw, job)["anchors"][0]
        self.assertEqual(anchor["primary_claim"], "P" * 421)
        self.assertEqual(anchor["primary_evidence"][0]["quote"], "P" * 421)
        self.assertEqual(anchor["supporting_evidence"][0]["quote"], "support")
        self.assertGreater(len(anchor["primary_claim"]), 300)

    def test_distinct_points_may_share_primary_ref_without_hard_deduplication(self):
        job = stage1_job()
        answers = [
            {"anchor_id": job["anchor_ids"][0], "kind": "holding", "primary_ref_id": "target-0",
             "supporting_ref_ids": ["target-1"], "needs_context": []},
            {"anchor_id": job["anchor_ids"][1], "kind": "procedural_rule", "primary_ref_id": "target-0",
             "supporting_ref_ids": ["target-2"], "needs_context": []},
        ]
        normalized = core.validate_stage1(selection(job, answers), job)
        self.assertEqual(len(normalized["anchors"]), 2)
        self.assertEqual([a["primary_ref_id"] for a in normalized["anchors"]], ["target-0", "target-0"])
        self.assertNotEqual(normalized["anchors"][0]["target_ref_ids"], normalized["anchors"][1]["target_ref_ids"])

    def test_negative_and_uncertain_empty_outputs_remain_empty_and_queue_behavior_unchanged(self):
        job = stage1_job()
        cases = (("negative", (), "no_legal_proposition"),
                 ("needs_context", ("speaker",), "insufficient_target"),
                 ("unresolved", (), "unclear_attribution"))
        for decision, needs, reason in cases:
            with self.subTest(decision=decision):
                checked = core.validate_stage1(selection(job, [], decision=decision, needs=needs), job)
                self.assertEqual(checked["anchors"], [])
                self.assertEqual(checked["decision"], decision)
                self.assertEqual(checked["reason"], reason)
                self.assertEqual(core.build_stage2(row_with_refs(), checked, IDENTITY), [])


class PrimarySupportTamperingAndStage2Tests(unittest.TestCase):
    def _checked(self):
        row = row_with_refs()
        job = stage1_job(row)
        raw = selection(job)
        return row, job, raw, core.validate_stage1(raw, job)

    def test_raw_and_normalized_role_tampering_is_rejected_on_stage2_revalidation(self):
        row, _, raw, normalized = self._checked()
        # Raw model data is the source selection, so changing it to another
        # valid TARGET selection is not detectable as tampering. It must,
        # however, reject foreign/context IDs; normalized host output is frozen.
        for role, value in (("primary_ref_id", "foreign-primary"),
                            ("supporting_ref_ids", ["context-only"])):
            changed = copy.deepcopy(raw); changed["anchors"][0][role] = value
            with self.subTest(form="raw", role=role), self.assertRaises((core.TargetContextError, ValueError)):
                core.build_stage2(row, changed, IDENTITY)
        for role, value in (("primary_ref_id", "target-2"),
                            ("supporting_ref_ids", ["target-5"])):
            changed = copy.deepcopy(normalized); changed["anchors"][0][role] = value
            with self.subTest(form="normalized", role=role), self.assertRaises((core.TargetContextError, ValueError)):
                core.build_stage2(row, changed, IDENTITY)
        for field, value in (("primary_claim", "forged"),
                             ("primary_evidence", []), ("supporting_evidence", []),
                             ("target_ref_ids", ["target-9"])):
            changed = copy.deepcopy(normalized); changed["anchors"][0][field] = value
            with self.subTest(field=field), self.assertRaises((core.TargetContextError, ValueError)):
                core.build_stage2(row, changed, IDENTITY)

    def test_stage2_locks_both_roles_once_and_cannot_rewrite_or_create_primary(self):
        row, _, raw, normalized = self._checked()
        raw["anchors"].append({"anchor_id": stage1_job(row)["anchor_ids"][1], "kind": "procedural_rule",
                               "primary_ref_id": "target-0", "supporting_ref_ids": ["target-2"],
                               "needs_context": ["exception"]})
        normalized = core.validate_stage1(raw, stage1_job(row))
        job = core.build_stage2(row, normalized, IDENTITY)[0]
        data = input_data(job)
        locked_anchors = data["locked_anchors"]
        self.assertEqual(len(locked_anchors), 2)
        self.assertEqual([a["primary_ref_id"] for a in locked_anchors], ["target-0", "target-0"])
        self.assertEqual([a["supporting_ref_ids"] for a in locked_anchors], [["target-1"], ["target-2"]])
        for locked in locked_anchors:
            self.assertEqual(locked["target_ref_ids"], ["target-0", *locked["supporting_ref_ids"]])
            self.assertEqual(locked["primary_representation"], "extractive_primary_ref_with_separate_support")
        evidence = {item["ref_id"]: item["text"] for item in data["SELECTED_TARGET_EVIDENCE"]}
        self.assertEqual(set(evidence), {"target-0", "target-1", "target-2"})
        self.assertEqual(len(data["SELECTED_TARGET_EVIDENCE"]), 3,
                         "a primary shared across AUs must occur once in the shared catalog")
        for locked, host_anchor in zip(locked_anchors, normalized["anchors"]):
            self.assertEqual(evidence[locked["primary_ref_id"]], host_anchor["primary_evidence"][0]["quote"])
            self.assertEqual([evidence[ref] for ref in locked["supporting_ref_ids"]],
                             [item["quote"] for item in host_anchor["supporting_evidence"]])
        content = job["payload"]["messages"][0]["content"]
        for quote in evidence.values():
            self.assertEqual(content.count(quote), 1, "each selected source quote must appear once in model payload")
        self.assertNotIn('"primary_claim"', job["payload"]["ebnf"])
        self.assertNotIn("primary_claim", locked)
        self.assertNotIn('"context-only"', job["payload"]["ebnf"])

        valid = {"version": contracts.STAGE2, "request_id": job["request_id"],
                 "target_id": job["target_id"], "decision": "complete",
                 "anchors": [{"anchor_id": locked["anchor_id"], "decision": "keep",
                              "supplements": [], "reason": "none"} for locked in locked_anchors], "reason": "none"}
        results = core.validate_stage2(valid, job)["anchors"]
        for result, host_anchor in zip(results, normalized["anchors"]):
            self.assertEqual(result["primary_claim"], host_anchor["primary_claim"])
            self.assertEqual(result["supporting_evidence"], host_anchor["supporting_evidence"])
        injected = copy.deepcopy(valid)
        injected["anchors"][0]["primary_claim"] = "model rewrite"
        with self.assertRaises((core.TargetContextError, ValueError)):
            core.validate_stage2(injected, job)


class PrimarySupportIdentityAndLocalMockTests(unittest.TestCase):
    def test_six_case_probe_uses_two_refs_and_nonempty_valid_support_without_extra_cases(self):
        jobs = anchor_order_probe.build_jobs({"model": IDENTITY["model"]}, PROFILE)
        self.assertEqual(len(jobs), 6)
        self.assertEqual({job["probe_case"] for job in jobs}, set(anchor_order_probe.CASES))
        for job in jobs:
            with self.subTest(case=job["probe_case"]):
                self.assertGreaterEqual(len(job["catalog"]["target_refs"]), 2)
                response = anchor_order_probe._mock_response(job)
                checked = core.validate_stage1(response, job)
                self.assertEqual(len(checked["anchors"]), job["expected_count"])
                for anchor in checked["anchors"]:
                    self.assertEqual(anchor["primary_ref_id"], "t-synthetic")
                    self.assertEqual(anchor["supporting_ref_ids"], ["t-support"])
                    self.assertEqual(len(anchor["supporting_evidence"]), 1)

        with tempfile.TemporaryDirectory(prefix="au-primary-support-probe-") as folder:
            root = Path(folder)
            cfg = {"model": IDENTITY["model"], "url": "https://jobs.invalid/chat/completions",
                   "jobs_url": "https://jobs.invalid/jobs"}
            prepared = anchor_order_probe.run_probe(root / "prepared", cfg=cfg,
                                                    prompt_profile=PROFILE)
            self.assertEqual(prepared["status"], "prepared")
            self.assertIsNone(prepared["nonempty_support_observed"])
            self.assertEqual(prepared["logical_requests"], 0)
            self.assertFalse(prepared["network_executed"])

            mocked = anchor_order_probe.run_probe(root / "mock", cfg=cfg, mock=True,
                                                  prompt_profile=PROFILE, concurrency=1)
            self.assertEqual(mocked["logical_requests"], 6)
            self.assertEqual(mocked["provider_POST_attempts"], 0)
            self.assertFalse(mocked["network_executed"])
            self.assertEqual(mocked["endpoint_constraint_status"], "not_assessed_mock")
            self.assertTrue(mocked["nonempty_support_observed"])
            self.assertTrue(all(item["nonempty_support_observed"] is True
                                for item in mocked["results"]))
            self.assertIn("not a constraint or exit gate", mocked["exit_gate"])

    def test_profile_hash_request_and_payload_bindings_are_distinct(self):
        primary = core.build_stage1(row_with_refs(), IDENTITY)
        legacy_row = row_with_refs()
        legacy_row.update(prompts.prompt_metadata("baseline_v2"))
        legacy = core.build_stage1(legacy_row, IDENTITY)
        self.assertEqual(primary["prompt_profile"], PROFILE)
        self.assertNotEqual(primary["prompt_sha"], legacy["prompt_sha"])
        self.assertNotEqual(primary["request_id"], legacy["request_id"])
        self.assertNotEqual(primary["payload_sha256"], legacy["payload_sha256"])

    def test_profile_is_bound_in_local_mock_ledger_and_completed_resume_does_not_dispatch(self):
        with tempfile.TemporaryDirectory(prefix="au-primary-support-") as folder:
            root = Path(folder)
            prepared = root / "prepared"
            # Keep the identity stable within this test even if implementation
            # files are being edited concurrently during an early checkpoint.
            with patch.object(core, "code_hash", return_value="synthetic-test-code-hash"):
                workload = core.prepare(prepared, manifest=core.DEFAULT_MANIFEST,
                                        parent=core.DEFAULT_PARENT, cfg=None, prompt_profile=PROFILE)
                target_id = workload["rows"][0]["target_id"]
                output = root / "local-mock"
                first = runner.run(prepared / "workload.json", output_root=output, mock=True,
                                   concurrency=1, target_ids=[target_id])
                self.assertFalse(first["network_executed"])
                self.assertEqual(first["prompt_profile"], PROFILE)
                ledger_before = json.loads((output / "runtime_ledger.json").read_text(encoding="utf-8"))
                self.assertEqual(ledger_before["binding"]["prompt_profile"], PROFILE)
                self.assertEqual(ledger_before["binding"]["prompt_sha"], workload["prompt_sha"])
                with patch.object(runner.MockJobs, "__call__", side_effect=AssertionError("resume dispatched a job")):
                    resumed = runner.run(prepared / "workload.json", output_root=output, mock=True,
                                         concurrency=1, target_ids=[target_id])
            ledger_after = json.loads((output / "runtime_ledger.json").read_text(encoding="utf-8"))
            self.assertFalse(resumed["network_executed"])
            self.assertEqual(ledger_after["attempts"], ledger_before["attempts"])
            self.assertEqual(ledger_after["provider_attempts"], ledger_before["provider_attempts"])


if __name__ == "__main__":
    unittest.main()
