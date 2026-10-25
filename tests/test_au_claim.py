"""Independent behavior tests for the claim-first AU pilot.

Preparation uses frozen local same-source inputs and all model replies are
synthetic. These tests do not call inference, network transports, or deploy.
Protocol validation is not a semantic AU quality assessment.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_claim import compare, core, runner
from knowledge_base.pipeline_v1.au_claim.contracts import (
    KINDS, MAX_AUS, OUTPUT_CAP, PROMPT_PROFILE, VERSION,
)
from knowledge_base.pipeline_v1.au_target_context import core as old_core
from knowledge_base.pipeline_v1.au_target_context.readiness import ReadinessDeadlineError
from knowledge_base.pipeline_v1.au_context_paired.build import read_json


REPO = Path(__file__).resolve().parents[1]
READY_INPUT = (REPO / "knowledge_base/pipeline_v1/outputs/"
               "kos_same_source_20261018_ready/input")
V1_WORKLOADS = (
    REPO / "knowledge_base/pipeline_v1/outputs/au_claim_check_20261019/input/workload.json",
    REPO / "knowledge_base/pipeline_v1/outputs/au_claim_kos16_20261019_ready/input/workload.json",
)
V2_WORKLOAD = (REPO / "knowledge_base/pipeline_v1/outputs/"
               "au_claim_v2_local_ready_20261019/input/workload.json")
V2_LIVE_LEDGER = (REPO / "knowledge_base/pipeline_v1/outputs/"
                  "au_claim_v2_local_ready_20261019/live/runtime_ledger.json")
EXPECTED_INPUT_SHA256 = {
    "workload.json": "fc828c65ffdd280db9596e668f65e0c57d270bc0512c963a3cf5780c25325691",
    "reference_checklist.json": "3d165650a91ba75e5cd1bcd320648fbda12ce817dd58b63640ebb7dd71f216ad",
}
EXPECTED_PARENT_WORKLOAD_SHA256 = "dd71eb21efb6be0472071278313722a99e3ad61aa949302930368748b9c00243"
EXPECTED_OLD_CODE_SHA256 = "c8a1ad4081a09a51c905142792e0169843fe7903431c4f18890dcaa3eb5d897c"
EXPECTED_SOURCE_HASHES = {
    "013009": "fb67079c6df4e7f19a02eb9712124f191f15bc4b51a293b71af07aaa77a1f7a3",
    "013948": "1571876439f11252edacb5b893c7538e1f7a29c2b47245ded2633f3de1114352",
    "011904": "c2bc7c0944a5ee103368055f7d2f0e3c260d4bb8336d406c3d01733304c96b12",
    "045155": "93d2b91c8a6c01ef4c8d7fd08543035b0d0a400e103c668c828407f99ee2d6eb",
    "099980": "49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319",
}


class ClaimFirstCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="au-claim-independent-")
        cls.root = Path(cls.temp.name)
        cls.workload = core.prepare(cls.root / "prepared")
        cls.preflight = core.preflight(cls.workload)
        cls.rows = {row["target_id"]: row for row in cls.workload["rows"]}
        cls.row = cls.workload["rows"][0]
        cls.job = core.build_job(cls.row, cls.workload["identity"])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def response(self, aus=(), context_request=None):
        return {"aus": copy.deepcopy(list(aus)), "context_request": copy.deepcopy(context_request)}

    def au(self, *, claim="The court applied the rule.", kind="holding",
           evidence_ids=None, limits=None):
        return {"claim": claim, "kind": kind,
                "evidence_ids": list(evidence_ids or [next(iter(self.job["catalog"]["target_refs"]))]),
                "limits": limits}

    def test_preparation_binds_same_16_targets_18_refs_and_exact_source_hashes(self):
        for name, expected in EXPECTED_INPUT_SHA256.items():
            actual = hashlib.sha256((READY_INPUT / name).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, name)
        parent = read_json(core.DEFAULT_PARENT_WORKLOAD)
        self.assertEqual(parent["workload_sha256"], EXPECTED_PARENT_WORKLOAD_SHA256)
        self.assertEqual(old_core.code_hash(), EXPECTED_OLD_CODE_SHA256,
                         "the legacy au_target_context execution fingerprint changed")

        self.assertEqual(self.workload["artifact_type"], "AUClaimWorkload")
        self.assertEqual(self.workload["version"], VERSION)
        self.assertFalse(self.workload["semantic_gold"])
        self.assertEqual(self.workload["parent_workload_sha256"], EXPECTED_PARENT_WORKLOAD_SHA256)
        self.assertEqual(self.preflight["status"], "pass")
        self.assertEqual(self.preflight["target_count"], 16)
        self.assertEqual(self.preflight["reference_count"], 18)
        self.assertEqual(self.preflight["max_logical_requests"], 32)
        self.assertEqual(self.preflight["network_requests"], 0)
        self.assertEqual(len(self.workload["rows"]), 16)

        parent_sources = {item["case_id"]: item["source_hash"] for item in parent["sources"]}
        self.assertEqual(parent_sources, EXPECTED_SOURCE_HASHES)
        self.assertEqual(self.workload["rows"], [
            {key: copy.deepcopy(row[key]) for key in core.ROW_KEYS} for row in parent["rows"]
        ])
        checklist = read_json(self.workload["reference_checklist_path"])
        self.assertEqual(len(checklist["references"]), 18)
        self.assertEqual(len({item["kos_id"] for item in checklist["references"]}), 18)

    def test_aliases_are_source_bound_and_first_prompt_exposes_target_only(self):
        content = self.job["payload"]["messages"][0]["content"]
        source_payload = json.loads(content.split("\nINPUT:\n", 1)[1])
        self.assertEqual(set(self.job["catalog"]["target_refs"]),
                         {f"s{i}" for i in range(1, len(self.row["target_refs"]) + 1)})
        self.assertEqual(self.job["catalog"]["context_refs"], {})
        self.assertIn("Use only TARGET", content)
        self.assertNotIn("CONTEXT", source_payload)
        for alias, ref in self.job["catalog"]["target_refs"].items():
            self.assertIn({"id": alias, "text": ref["quote"]}, source_payload["TARGET"])
            self.assertEqual(ref["quote"], self.row["target_refs"][ref["ref_id"]]["quote"])
        for forbidden in ("kos_id", "issue_ids", "claim_text", "alignment", "start_char",
                          "end_char", "source_hash", "case_id", "request_id", "target_id",
                          "global_status", "speaker"):
            self.assertNotIn(forbidden, json.dumps(source_payload, ensure_ascii=False))
        for ref in read_json(self.workload["reference_checklist_path"])["references"]:
            self.assertNotIn(ref["kos_id"], json.dumps(source_payload, ensure_ascii=False))
            for field in ("claim_text", "limits_text"):
                if ref.get(field):
                    self.assertNotIn(ref[field], json.dumps(source_payload, ensure_ascii=False))

    @staticmethod
    def _response_examples(prompt):
        decoder = json.JSONDecoder()
        found = []
        for index, char in enumerate(prompt):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(prompt[index:])
            except json.JSONDecodeError:
                continue
            if (isinstance(value, dict)
                    and set(value) == {"aus", "context_request"}
                    and isinstance(value["aus"], list)):
                found.append(value)
        # Preserve order while avoiding an object being found again when a
        # later opening brace occurs inside the same JSON value.
        unique = []
        seen = set()
        for value in found:
            encoded = json.dumps(value, sort_keys=True, ensure_ascii=False)
            if encoded not in seen:
                seen.add(encoded)
                unique.append(value)
        return unique

    def test_prompt_identity_changes_without_changing_wire_version_or_caps(self):
        content = self.job["payload"]["messages"][0]["content"]
        self.assertEqual(VERSION, "au-claim-v1")
        self.assertEqual(PROMPT_PROFILE, "claim_first_v3_source_close")
        self.assertEqual(MAX_AUS, 3)
        self.assertEqual(OUTPUT_CAP, 800)
        self.assertEqual(self.job["payload"]["max_tokens"], 800)
        self.assertEqual(self.job["prompt_profile"], PROMPT_PROFILE)
        self.assertEqual(self.job["prompt_sha"], core.prompt_metadata()["prompt_sha"])
        self.assertEqual(self.workload["prompt_profile"], PROMPT_PROFILE)
        self.assertEqual(self.workload["prompt_sha"], core.prompt_metadata()["prompt_sha"])
        self.assertGreater(self.preflight["stage1_input_reservation_utf8_bytes"], 0)
        self.assertEqual(self.preflight["budget"]["max_total_input_tokens"], 800000)
        self.assertIn("standard_of_review", content.lower())
        self.assertIn("burden", content.lower())

    def test_v1_and_v2_saved_workloads_are_rejected_without_mutation(self):
        for path in (*V1_WORKLOADS, V2_WORKLOAD):
            with self.subTest(workload=path.name, parent=path.parent.parent.name):
                before = path.read_bytes()
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    core.preflight(path)
                self.assertEqual(path.read_bytes(), before)

    def test_v3_preserves_v2_wire_model_grammar_and_source_payload_but_changes_identity(self):
        ledger = read_json(V2_LIVE_LEDGER)
        old_entries = [entry["job"] for entry in ledger["jobs"].values()
                       if entry.get("job", {}).get("prompt_profile") == "claim_first_v2"]
        self.assertTrue(old_entries, "saved v2 live ledger must contain full jobs")
        cases = []
        for old_job in old_entries:
            row = self.rows.get(old_job["target_id"])
            if row is not None and old_job["stage"] == 1:
                cases.append((old_job, core.build_job(row, self.workload["identity"])))
                break
        for old_job in old_entries:
            row = self.rows.get(old_job["target_id"])
            if row is not None and old_job["stage"] == 2:
                cases.append((old_job, core.build_job(
                    row, self.workload["identity"], stage=2, draft=old_job["draft"])))
                break
        self.assertEqual({old["stage"] for old, _ in cases}, {1, 2})

        for old_job, new_job in cases:
            with self.subTest(stage=old_job["stage"], target=old_job["target_id"]):
                self.assertEqual(old_job["target_id"], new_job["target_id"])
                self.assertEqual(old_job["case_id"], new_job["case_id"])
                self.assertEqual(old_job["source_hash"], new_job["source_hash"])
                self.assertEqual(old_job["catalog"]["target_refs"],
                                 new_job["catalog"]["target_refs"])
                self.assertEqual(old_job["catalog"]["context_refs"],
                                 new_job["catalog"]["context_refs"])
                self.assertNotEqual(old_job["request_id"], new_job["request_id"])
                old_payload, new_payload = old_job["payload"], new_job["payload"]
                for key in ("model", "temperature", "max_tokens", "chat_template_kwargs", "ebnf"):
                    self.assertEqual(old_payload[key], new_payload[key], key)
                self.assertEqual(old_payload["max_tokens"], OUTPUT_CAP)
                old_input = json.loads(old_payload["messages"][0]["content"].split("\nINPUT:\n", 1)[1])
                new_input = json.loads(new_payload["messages"][0]["content"].split("\nINPUT:\n", 1)[1])
                self.assertEqual(old_input["TARGET"], new_input["TARGET"])
                if old_job["stage"] == 1:
                    self.assertNotIn("CONTEXT", old_input)
                    self.assertNotIn("CONTEXT", new_input)
                else:
                    self.assertEqual(old_input["CONTEXT"], new_input["CONTEXT"])
                    self.assertEqual(old_input["draft"], new_input["draft"])

    def test_prompt_examples_are_json_validatable_with_synthetic_aliases_and_not_kos_derived(self):
        examples = self._response_examples(core.INSTRUCTIONS)
        self.assertTrue(examples, "prompt must contain parseable response examples")
        self.assertEqual(len(examples), 5, "keep the five compact calibration examples")
        self.assertTrue(any(len(item["aus"]) == 2 for item in examples),
                        "include an example with two distinct AUs")
        self.assertTrue(any(item["aus"] == [] for item in examples),
                        "include a valid empty-AU example")
        self.assertTrue(any(item["context_request"] is not None for item in examples),
                        "include a neutral context-question example")

        aliases = sorted({evidence_id for example in examples for au in example["aus"]
                          for evidence_id in au.get("evidence_ids", [])})
        self.assertTrue(aliases)
        synthetic_job = {"target_id": "synthetic-target", "catalog": {
            "target_refs": {alias: {
                "ref_id": alias, "case_id": "synthetic", "source_hash": "0" * 64,
                "start_char": index, "end_char": index + 1,
                "quote": f"Synthetic source fragment {index}.", "role": "target_body",
            } for index, alias in enumerate(aliases)},
            "context_refs": {},
        }}
        for example in examples:
            with self.subTest(example=example):
                normalized = core.validate_response(example, synthetic_job)
                self.assertLessEqual(len(normalized["aus"]), 3)
        pair = next(item for item in examples if len(item["aus"]) == 2)
        self.assertNotEqual(pair["aus"][0]["claim"], pair["aus"][1]["claim"])

        # One example should keep a rule, its rationale, and its exception in
        # the same AU, supported across TARGET spans.
        grouped = [au for example in examples for au in example["aus"]
                   if len(au["evidence_ids"]) > 1]
        self.assertTrue(any(
            any(marker in au["claim"].casefold() for marker in ("because", "to ", "so that"))
            and any(marker in au["claim"].casefold()
                    for marker in ("except", "exempt", "unless", "subject to"))
            for au in grouped
        ), "include one grouped rule+rationale+exception example")

        # At least one example claim should retain most of the wording in a
        # quoted synthetic source sentence; this checks example shape only.
        def words(text):
            return {word for word in re.findall(r"[a-z0-9]+", text.casefold()) if len(word) > 2}
        quoted_sources = re.findall(r'"([^"\n]+)"', core.INSTRUCTIONS)
        close_claims = [au["claim"] for example in examples for au in example["aus"]]
        self.assertTrue(any(
            len(words(claim)) >= 5 and any(
                len(words(claim) & words(source)) / len(words(claim)) >= 0.8
                for source in quoted_sources if len(words(source)) >= 5
            ) for claim in close_claims
        ), "include an example claim close to its synthetic source wording")

        checklist = read_json(self.workload["reference_checklist_path"])
        example_text = json.dumps(examples, ensure_ascii=False).casefold()
        for reference in checklist["references"]:
            values = [reference.get(field) for field in
                      ("kos_id", "claim_text", "limits_text", "file")]
            metadata = reference.get("metadata")
            if isinstance(metadata, dict):
                values.append(metadata.get("id"))
            for value in values:
                if value:
                    self.assertNotIn(str(value).casefold(), example_text,
                                     "prompt example copied a KOS name or claim")

    def test_stale_prompt_workload_is_rejected_without_being_rewritten(self):
        stale = copy.deepcopy(self.workload)
        stale["prompt_profile"] = "claim_first_v1"
        stale["prompt_sha"] = "0" * 64
        stale["workload_sha256"] = core.fingerprint(
            {key: value for key, value in stale.items() if key != "workload_sha256"}
        )
        path = self.root / "stale-prompt-workload.json"
        path.write_text(json.dumps(stale), encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "prompt metadata changed"):
            core.preflight(path)
        self.assertEqual(path.read_bytes(), before)

    def test_wire_accepts_zero_through_three_aus_and_null_kind(self):
        refs = list(self.job["catalog"]["target_refs"])
        for count in range(4):
            aus = [self.au(claim=f"Distinct legal point number {i}.",
                           evidence_ids=[refs[i % len(refs)]], kind=None if i == 0 else "other")
                   for i in range(count)]
            normalized = core.validate_response(self.response(aus), self.job)
            self.assertEqual(len(normalized["aus"]), count)
            self.assertFalse(normalized["needs_context"])
            self.assertEqual(normalized["semantic_quality"], "not_assessed")
        with self.assertRaises((ValueError, TypeError, KeyError)):
            core.validate_response(self.response([
                self.au(claim=f"AU {i} distinct.", evidence_ids=[refs[i % len(refs)]])
                for i in range(4)
            ]), self.job)
        truncated = {"model": self.workload["identity"]["model"], "choices": [{
            "finish_reason": "length", "message": {"content": json.dumps(
                self.response([self.au(claim=f"Distinct legal point {i}.",
                                       evidence_ids=[refs[i % len(refs)]]) for i in range(3)])
            )}
        }]}
        with self.assertRaises(ValueError):
            runner._normalize_body(truncated, self.job,
                                   core.runtime_config(self.workload["identity"]))

    def test_formally_valid_wrong_duty_bearer_and_missing_exception_remain_unassessed(self):
        refs = list(self.job["catalog"]["target_refs"])
        examples = [
            self.response([self.au(
                claim="The tenant must perform the repair.", evidence_ids=[refs[0]],
                kind="statutory_hook",
            )]),
            self.response([self.au(
                claim="The permit may be revoked for any breach.", evidence_ids=[refs[-1]],
                kind="statutory_hook",
            )]),
        ]
        for value in examples:
            with self.subTest(claim=value["aus"][0]["claim"]):
                accepted = core.validate_response(value, self.job)
                self.assertEqual(len(accepted["aus"]), 1)
                self.assertEqual(accepted["semantic_quality"], "not_assessed")
                self.assertEqual(accepted["semantic_status"], "unknown")

    def test_foreign_and_context_only_evidence_are_rejected_but_repeated_valid_ids_normalize(self):
        with self.assertRaises((ValueError, TypeError, KeyError)):
            core.validate_response(self.response([self.au(evidence_ids=["foreign-id"])]), self.job)
        target_id = next(iter(self.job["catalog"]["target_refs"]))
        repeated = core.validate_response(self.response([self.au(evidence_ids=[target_id, target_id])]), self.job)
        self.assertEqual(repeated["aus"][0]["evidence_ids"], [target_id])

        # No arbitrary evidence-count ceiling: every distinct ID present in the
        # supplied target catalog remains usable by the wire validator.
        expanded_job = copy.deepcopy(self.job)
        template = next(iter(expanded_job["catalog"]["target_refs"].values()))
        for i in range(20):
            alias = f"s-extra-{i}"
            expanded_job["catalog"]["target_refs"][alias] = {
                **copy.deepcopy(template), "ref_id": alias, "quote": f"extra evidence {i}"
            }
        all_refs = list(expanded_job["catalog"]["target_refs"])
        many = core.validate_response(self.response([self.au(evidence_ids=all_refs)]), expanded_job)
        self.assertEqual(set(many["aus"][0]["evidence_ids"]), set(all_refs))
        self.assertEqual(len(many["aus"][0]["evidence_ids"]), len(all_refs))

        row = copy.deepcopy(self.row)
        # Stage two is permitted to cite context only as an addition to at least one TARGET ID.
        draft = self.response([self.au()], {"question": "Does the nearby passage qualify this rule?"})
        context_job = core.build_job(row, self.workload["identity"], stage=2, draft=draft)
        context_id = next(iter(context_job["catalog"]["context_refs"]), None)
        if context_id is None:
            self.skipTest("selected fixture TARGET has no bounded neighboring context")
        with self.assertRaises((ValueError, TypeError, KeyError)):
            core.validate_response(self.response([self.au(evidence_ids=[context_id])]), context_job)
        valid_pair = core.validate_response(self.response([
            self.au(evidence_ids=[target_id, context_id])
        ]), context_job)
        self.assertEqual(set(valid_pair["aus"][0]["evidence_ids"]), {target_id, context_id})

    def test_exact_duplicates_are_removed_but_distinct_and_negated_claims_survive(self):
        ref = next(iter(self.job["catalog"]["target_refs"]))
        duplicate = self.au(claim="The court applied the rule.", evidence_ids=[ref])
        near_duplicate = self.au(claim="The court applied this rule.", evidence_ids=[ref])
        negated = self.au(claim="The court did not apply the rule.", evidence_ids=[ref])
        result = core.validate_response(self.response(
            [duplicate, copy.deepcopy(duplicate), near_duplicate]
        ), self.job)
        self.assertEqual(result["exact_duplicates_removed"], 1)
        self.assertEqual(len(result["aus"]), 2)
        self.assertEqual({item["claim"] for item in result["aus"]},
                         {"The court applied the rule.", "The court applied this rule."})
        result = core.validate_response(self.response([duplicate, negated]), self.job)
        self.assertEqual(len(result["aus"]), 2)
        self.assertEqual({item["claim"] for item in result["aus"]}, {duplicate["claim"], negated["claim"]})

    def test_second_prompt_rewrites_full_draft_with_all_target_and_bounded_context(self):
        draft = self.response([self.au(claim="Initial short claim.")],
                              {"question": "Is there a limiting qualification nearby?"})
        job = core.build_job(self.row, self.workload["identity"], stage=2, draft=draft)
        prompt = job["payload"]["messages"][0]["content"]
        source_payload = json.loads(prompt.split("\nINPUT:\n", 1)[1])
        self.assertIn("all original TARGET", prompt)
        for alias, ref in self.job["catalog"]["target_refs"].items():
            self.assertIn({"id": alias, "text": ref["quote"]}, source_payload["TARGET"])
        self.assertIn("draft", source_payload)
        self.assertEqual(source_payload["draft"]["aus"][0]["claim"], draft["aus"][0]["claim"])
        self.assertTrue(job["catalog"]["context_refs"])
        for alias, ref in job["catalog"]["context_refs"].items():
            self.assertTrue(alias.startswith("c"))
            self.assertIn({"id": alias, "text": ref["quote"]}, source_payload["CONTEXT"])
        changed = self.response([self.au(claim="Rewritten claim.", kind=None,
                                          evidence_ids=[next(iter(job["catalog"]["target_refs"]))],
                                          limits="Qualified by the nearby passage.")])
        validated = core.validate_response(changed, job)
        self.assertEqual(validated["aus"][0]["claim"], "Rewritten claim.")
        self.assertIsNone(validated["aus"][0]["kind"])
        self.assertEqual(validated["aus"][0]["limits"], "Qualified by the nearby passage.")
        self.assertFalse(validated["needs_context"])

    def test_second_context_request_is_recorded_without_a_third_stage(self):
        draft = self.response([], {"question": "Need nearby source to resolve attribution."})
        job = core.build_job(self.row, self.workload["identity"], stage=2, draft=draft)
        result = core.validate_response(self.response([], {"question": "Still unresolved."}), job)
        self.assertTrue(result["needs_context"])
        self.assertEqual(result["context_request"]["question"], "Still unresolved.")
        self.assertEqual(job["stage"], 2)

    def test_full_16_target_mock_and_resume_add_no_verified_provider_posts(self):
        root = self.root / "mock-full16"
        real_opener_calls = []
        def forbidden_real_opener(*args, **kwargs):
            real_opener_calls.append((args, kwargs))
            raise AssertionError("mock mode must not invoke the real opener")
        first = runner.run(self.workload, root, mock=True, concurrency=2,
                           opener=forbidden_real_opener)
        self.assertEqual(first["selected_target_count"], 16)
        self.assertEqual(first["stage1_requests"], 16)
        self.assertLessEqual(first["stage2_requests"], 16)
        self.assertLessEqual(first["logical_requests"], 32)
        self.assertEqual(first["provider_POST_attempts"], 0)
        self.assertEqual(first["network_requests"], 0)
        self.assertFalse(first["network_executed"])
        self.assertEqual(real_opener_calls, [])
        self.assertEqual(first["semantic_quality"], "not_assessed")
        for row in first["results"]:
            self.assertLessEqual(row["logical_requests"], 2)
            self.assertEqual(row["provider_POST_attempts"], 0)
        ledger_before = read_json(root / "runtime_ledger.json")

        original_warmup = runner.ReadinessGate.warmup
        observed = []
        def no_health_for_terminal_cache(gate, needed):
            observed.append(needed)
            return original_warmup(gate, needed)
        with patch.object(runner, "mock_response", side_effect=AssertionError("resume dispatched work")), \
             patch.object(runner.ReadinessGate, "warmup", new=no_health_for_terminal_cache):
            resumed = runner.run(self.workload, root, mock=True, concurrency=2,
                                 opener=forbidden_real_opener)
        ledger_after = read_json(root / "runtime_ledger.json")
        self.assertEqual(observed, [False])
        self.assertEqual(ledger_after["attempts"], ledger_before["attempts"])
        self.assertEqual(ledger_after["provider_attempts"], ledger_before["provider_attempts"])
        self.assertEqual(resumed["logical_requests"], first["logical_requests"])
        self.assertEqual(resumed["provider_POST_attempts"], 0)
        self.assertEqual(resumed["network_requests"], 0)
        self.assertEqual(real_opener_calls, [])

    def test_comparison_is_source_bound_read_only_and_does_not_claim_accuracy(self):
        run_root = self.root / "compare-mock-run"
        report = runner.run(self.workload, run_root, mock=True, concurrency=2)
        run_path = run_root / "run.json"
        old_run_path = compare.DEFAULT_BASELINE_RUN
        old_ledger_path = old_run_path.parent / "runtime_ledger.json"
        tracked = [run_path, run_root / "runtime_ledger.json", old_run_path, old_ledger_path]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
        old_ledger = read_json(old_ledger_path)
        result = compare.compare(self.root / "prepared" / "workload.json", run_path,
                                 self.root / "comparison")
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
        self.assertEqual(after, before, "comparison must not rewrite either run or baseline artifacts")
        self.assertEqual(old_ledger["provider_attempts"], read_json(old_ledger_path)["provider_attempts"])
        self.assertEqual(result["status"], "semantic_review_pending")
        self.assertEqual(result["reference_count"], 18)
        self.assertEqual(len(result["references"]), 18)
        self.assertEqual(result["claim_first_summary"]["logical_requests"], report["logical_requests"])
        self.assertTrue(result["comparison_conditions"]["same_source_target_context"])
        self.assertEqual(result["semantic_quality"], "not_assessed")
        self.assertEqual(result["token_savings_claim"], "not_established")
        self.assertEqual(result["claim_first_summary"]["usage_is_complete"], False)
        self.assertEqual(result["baseline_summary"]["completed_workload_usage"]["total_tokens"], 57462)
        for item in result["references"]:
            ref = item["reference"]
            self.assertIn(ref["case_id"], EXPECTED_SOURCE_HASHES)
            self.assertEqual(ref["source_hash"], EXPECTED_SOURCE_HASHES[ref["case_id"]])
            self.assertEqual(item["semantic_review_status"], "pending")
        self.assertTrue((self.root / "comparison" / "REVIEW.md").is_file())

    def test_readiness_deadline_leaves_zero_posts_and_resumable_pending_jobs(self):
        target = self.row["target_id"]
        cfg = core.runtime_config(self.workload["identity"])
        cfg["token"] = "local-test-token"
        def forbidden_transport(*args, **kwargs):
            raise AssertionError("test transport must not be reached")
        root = self.root / "readiness-timeout"
        with patch.object(runner.ReadinessGate, "warmup", side_effect=ReadinessDeadlineError()), \
             patch.object(runner.ReadinessGate, "check", side_effect=ReadinessDeadlineError()):
            report = runner.run(self.workload, root, cfg=cfg, execute=True, target_ids=[target],
                                opener=forbidden_transport)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["provider_POST_attempts"], 0)
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(report["pending"], 1)
        self.assertEqual(read_json(root / "runtime_ledger.json")["attempts"], [])

    def test_usage_totals_remain_unknown_for_synthetic_mock_calls(self):
        report = runner.run(self.workload, self.root / "mock-costs", mock=True, target_ids=[self.row["target_id"]])
        self.assertIsNone(report["total_provider_usage"])
        self.assertGreaterEqual(report["unknown_usage_jobs"], 1)
        self.assertFalse(report["usage"]["usage_is_complete"])
        result = report["results"][0]
        self.assertEqual(len(result["request_ids"]), result["logical_requests"])
        self.assertEqual(result["transport_POST_attempts"], result["logical_requests"])
        self.assertEqual(result["provider_POST_attempts"], 0)
