"""Independent local contract tests for incremental AU prompt profiles.

These tests use a synthetic TARGET and local CLI argument validation only. They
do not call a provider, network transport, deployment, or infer semantic quality.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_target_context import core, runner
from knowledge_base.pipeline_v1.au_target_context import __main__ as cli
from knowledge_base.pipeline_v1.au_target_context import contracts, prompts
from knowledge_base.pipeline_v1.au_context_paired.build import fingerprint


def synthetic_row(prompt_profile=None):
    source = "TARGET says the court applied Rule A unless Exception B. CONTEXT confirms speaker."
    target = source[:source.index(" CONTEXT")]
    target_ref = {
        "ref_id": "target-ref", "source_atom_id": "target-atom",
        "case_id": "synthetic-case", "source_hash": "a" * 64,
        "start_char": 0, "end_char": len(target), "quote": target,
        "role": "target_body",
    }
    context_quote = source[len(target) + 1:]
    context_ref = {
        "ref_id": "context-ref", "source_atom_id": "context-atom",
        "case_id": "synthetic-case", "source_hash": "a" * 64,
        "start_char": len(target) + 1, "end_char": len(source),
        "quote": context_quote, "role": "context",
    }
    row = {
        "target_id": "synthetic-target", "case_id": "synthetic-case",
        "source_hash": "a" * 64,
        "target": {"start_char": 0, "end_char": len(target)},
        "request": {"request_id": "synthetic-request"},
        "target_refs": {"target-ref": target_ref},
        "context_refs": {"context-ref": context_ref},
        "_fixture_source": source,
    }
    if prompt_profile is not None:
        row.update(prompts.prompt_metadata(prompt_profile))
    return row


def identity():
    return {"model": "synthetic-model", "enable_thinking": False}


def input_data(job):
    text = job["payload"]["messages"][0]["content"]
    return json.loads(text.split("\nINPUT:\n", 1)[1])


def normalized_payload(job):
    payload = copy.deepcopy(job["payload"])
    content = payload["messages"][0]["content"]
    # The profile's instruction delta is tested separately. Compare its wire
    # object and model-facing constraints after dropping only that prefix.
    data = input_data(job)
    data["request_id"] = "<request-id>"
    payload["messages"][0]["content"] = json.dumps(data, ensure_ascii=False)
    grammar = payload["ebnf"]
    payload["ebnf"] = grammar.replace(job["request_id"], "<request-id>")
    return payload


class PromptProfileContractTests(unittest.TestCase):
    def test_default_and_explicit_baseline_v2_build_identical_jobs(self):
        row = synthetic_row()
        default = core.build_stage1(row, identity())
        explicit = core.build_stage1(synthetic_row("baseline_v2"), identity())
        self.assertEqual(default, explicit)

    def test_exact_original_instruction_strings_match_main_snapshot(self):
        snapshot_path = Path("knowledge_base/pipeline_v1/outputs/au_incremental_20261014/baseline_prompt_snapshot.json")
        self.assertTrue(snapshot_path.is_file(), f"required Main-owned baseline snapshot missing: {snapshot_path}")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["profile"], "baseline_v2")
        for key, actual in (
            ("INSTRUCTIONS", prompts.INSTRUCTIONS),
            ("TARGET_INSTRUCTIONS", prompts.TARGET_INSTRUCTIONS),
            ("CONTEXT_INSTRUCTIONS", prompts.CONTEXT_INSTRUCTIONS),
        ):
            self.assertEqual(snapshot[key], actual, f"baseline string changed: {key}")

    def test_profile_deltas_are_cumulative_and_do_not_change_stage2_instructions(self):
        _, base_target, base_context = prompts.instructions_for("baseline_v2")
        _, attribution, attribution_context = prompts.instructions_for("attribution_v1")
        _, grouped, grouped_context = prompts.instructions_for("legal_point_v1")
        self.assertEqual(attribution, base_target + "\n" + prompts.ATTRIBUTION_ADDITION)
        self.assertEqual(grouped, attribution + "\n" + prompts.LEGAL_POINT_ADDITION)
        self.assertEqual((attribution_context, grouped_context), (base_context, base_context))
        self.assertNotIn(prompts.LEGAL_POINT_ADDITION, attribution)

    def test_stage2_guidance_is_common_but_historical_baseline_constant_stays_frozen(self):
        snapshot_path = Path("knowledge_base/pipeline_v1/outputs/au_incremental_20261014/baseline_prompt_snapshot.json")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(prompts.CONTEXT_INSTRUCTIONS, snapshot["CONTEXT_INSTRUCTIONS"])
        addition = prompts.CONTEXT_EVIDENCE_ADDITION
        self.assertTrue(addition.strip())
        legacy_profiles = ("baseline_v2", "attribution_v1", "legal_point_v1")
        contexts = [prompts.instructions_for(name)[2] for name in legacy_profiles]
        expected = prompts.CONTEXT_INSTRUCTIONS + "\n" + addition
        self.assertEqual(contexts, [expected] * len(legacy_profiles))
        self.assertNotEqual(contexts[0], snapshot["CONTEXT_INSTRUCTIONS"])
        _, _, evidence_first_context = prompts.instructions_for("evidence_first_v1")
        self.assertIn("primary_representation labels host-derived extractive evidence", evidence_first_context)
        self.assertIn("primary_gaps lists omitted source intervals", evidence_first_context)
        self.assertIn(addition, evidence_first_context)
        for guidance in (
                "scope states the applicability domain",
                "Every new fact in supplement text MUST be supported by its cited context quote(s)",
                "a valid context ID is not semantic proof",
                "A party argument is not court endorsement"):
            self.assertIn(guidance, addition)

    def test_stage1_and_stage2_wire_constraints_source_refs_and_model_are_profile_invariant(self):
        jobs = {}
        stage2_jobs = {}
        # The three historical profiles intentionally share the v2 wire.
        # evidence_first_v1 is a separate selection-only protocol by design.
        legacy_profiles = ("baseline_v2", "attribution_v1", "legal_point_v1")
        for name in legacy_profiles:
            row = synthetic_row(name)
            one = core.build_stage1(row, identity())
            jobs[name] = one
            self.assertEqual(one["catalog"]["target_refs"], row["target_refs"])
            self.assertEqual(one["catalog"]["context_refs"], {})
            self.assertEqual(one["payload"]["model"], identity()["model"])
            self.assertEqual(one["payload"]["max_tokens"], contracts.OUTPUT_CAP)
            self.assertEqual(input_data(one)["output_keys"], list(contracts.STAGE1_KEYS))
            self.assertEqual(input_data(one)["anchor_keys"], list(contracts.ANCHOR_KEYS))

            response = {
                "version": contracts.STAGE1, "request_id": one["request_id"],
                "target_id": one["target_id"], "decision": "positive",
                "anchors": [{"anchor_id": one["anchor_ids"][0], "kind": "holding",
                             "primary_claim": "The court applied Rule A.",
                             "target_ref_ids": ["target-ref"],
                             "needs_context": ["exception"]}],
                "needs_context": [], "reason": "none",
            }
            checked = core.validate_stage1(response, one)
            two = core.build_stage2(row, checked, identity())[0]
            stage2_jobs[name] = two
            self.assertEqual(two["catalog"]["target_refs"], one["catalog"]["target_refs"])
            self.assertEqual(two["catalog"]["context_refs"], row["context_refs"])
            self.assertEqual(two["payload"]["model"], identity()["model"])
            self.assertEqual(two["payload"]["max_tokens"], contracts.OUTPUT_CAP)
            self.assertEqual(input_data(two)["output_keys"], list(contracts.STAGE2_KEYS))
            self.assertEqual(input_data(two)["anchor_keys"], list(contracts.STAGE2_ANCHOR_KEYS))

        for table in (jobs, stage2_jobs):
            baseline = table["baseline_v2"]
            for name in ("attribution_v1", "legal_point_v1"):
                self.assertEqual(normalized_payload(table[name]), normalized_payload(baseline))
                self.assertEqual(table[name]["catalog"], baseline["catalog"])
        # Stage 2 carries one shared addition, so its full prefix is profile-invariant.
        prefixes = [job["payload"]["messages"][0]["content"].split("\nINPUT:\n", 1)[0]
                    for job in stage2_jobs.values()]
        self.assertEqual(prefixes[0], prefixes[1])
        self.assertEqual(prefixes[1], prefixes[2])
        expected_context = prompts.INSTRUCTIONS + "\n" + prompts.CONTEXT_INSTRUCTIONS + "\n" + prompts.CONTEXT_EVIDENCE_ADDITION
        self.assertEqual(prefixes[0], expected_context)

        ef_row = synthetic_row("evidence_first_v1")
        ef_one = core.build_stage1(ef_row, identity())
        self.assertEqual(input_data(ef_one)["version"], contracts.STAGE1_EVIDENCE_FIRST)
        self.assertEqual(input_data(ef_one)["anchor_keys"], list(contracts.EVIDENCE_FIRST_ANCHOR_KEYS))
        self.assertNotIn("primary_claim", input_data(ef_one)["anchor_keys"])
        self.assertNotEqual(normalized_payload(ef_one), normalized_payload(jobs["baseline_v2"]))

    def test_profile_and_prompt_hash_are_explicit_cache_request_bindings_without_collisions(self):
        jobs = [core.build_stage1(synthetic_row(name), identity()) for name in prompts.PROMPT_PROFILES]
        self.assertEqual([job["prompt_profile"] for job in jobs], list(prompts.PROMPT_PROFILES))
        self.assertEqual([job["prompt_sha"] for job in jobs],
                         [prompts.prompt_metadata(name)["prompt_sha"] for name in prompts.PROMPT_PROFILES])
        self.assertEqual(len({job["prompt_sha"] for job in jobs}), len(jobs))
        self.assertEqual(len({job["request_id"] for job in jobs}), len(jobs))
        self.assertEqual(len({job["payload_sha256"] for job in jobs}), len(jobs))
        for job in jobs:
            self.assertEqual(job["prompt_profile"],
                             prompts.prompt_metadata(job["prompt_profile"])["prompt_profile"])
            self.assertIn(job["prompt_sha"], {value["prompt_sha"] for value in jobs})
            self.assertTrue(job["request_id"].startswith("atc-"))

    def test_local_runner_ledger_binding_carries_each_profile_and_hash(self):
        runtime_identity = {
            "model": "Qwen/Qwen3.5-9B",
            "url": "https://unit.invalid/v1/chat/completions",
            "enable_thinking": False,
            "transport": "jobs",
            "string_decoder": "host_validated",
            "expected_model_revision": "synthetic-revision",
        }
        cfg = {**runtime_identity, "jobs_url": "https://unit.invalid/v1/jobs"}
        with tempfile.TemporaryDirectory() as tmp:
            for name in prompts.PROMPT_PROFILES:
                metadata = prompts.prompt_metadata(name)
                row = synthetic_row(name)
                row.update(metadata)
                workload = {
                    "workload_sha256": f"synthetic-{name}",
                    "identity": runtime_identity,
                    "parent_workload": {"identity": runtime_identity},
                    "source_store": str(Path(tmp) / "source-store"),
                    "atom_root": str(Path(tmp) / "atom-root"),
                    "budget": dict(contracts.BUDGET),
                    "prompt_profile": name,
                    "prompt_sha": metadata["prompt_sha"],
                    "rows": [row],
                }
                out = Path(tmp) / ("run-" + name)
                with self.subTest(profile=name), patch.object(
                        runner, "preflight", return_value={
                            "status": "pass",
                            "stage1_baseline_input_reservation_utf8_bytes": 0,
                            "stage1_added_input_utf8_bytes": 0,
                            "stage1_max_added_input_utf8_bytes_per_target": 0,
                        }):
                    result = runner.run(workload, output_root=out, cfg=cfg, mock=True, concurrency=1)
                binding = json.loads((out / "runtime_ledger.json").read_text(encoding="utf-8"))["binding"]
                self.assertEqual(result["prompt_profile"], name)
                self.assertEqual(binding["prompt_profile"], name)
                self.assertEqual(binding["prompt_sha"], metadata["prompt_sha"])
                self.assertFalse(result["network_executed"])

    def test_instructions_add_no_wire_fields_or_exact_synthetic_source(self):
        row = synthetic_row()
        for name in prompts.PROMPT_PROFILES:
            _, target, _ = prompts.instructions_for(name)
            self.assertNotIn(row["_fixture_source"], target)
            self.assertNotIn(row["target_refs"]["target-ref"]["quote"], target)
            job = core.build_stage1(synthetic_row(name), identity())
            data = input_data(job)
            self.assertEqual(set(data["output_keys"]), set(contracts.STAGE1_KEYS))
            self.assertEqual(set(data["anchor_keys"]), set(contracts.stage1_anchor_keys(name)))


class ProfileGuardsAndCliTests(unittest.TestCase):
    @staticmethod
    def minimal_workload(code_sha, profile_sha=None):
        ident = {"model": "Qwen/Qwen3.5-9B", "url": "https://unit.invalid/v1/chat/completions",
                 "enable_thinking": False, "transport": "jobs", "string_decoder": "host_validated",
                 "expected_model_revision": "rev"}
        parent = {"workload_sha256": "parent-hash", "identity": ident,
                  "source_store": "source-store", "atom_root": "atom-root"}
        manifest = {"manifest_sha256": "manifest-hash"}
        value = {"artifact_type": "AUTargetContextWorkload", "version": contracts.VERSION,
                 "prompt_profile": "baseline_v2",
                 "prompt_sha": profile_sha or prompts.prompt_metadata()["prompt_sha"],
                 "presentation_manifest_sha256": manifest["manifest_sha256"],
                 "parent_workload_sha256": parent["workload_sha256"],
                 "presentation_manifest": manifest, "parent_workload": parent,
                 "identity": ident, "source_store": parent["source_store"],
                 "atom_root": parent["atom_root"], "budget": dict(contracts.BUDGET),
                 "output_cap": contracts.OUTPUT_CAP, "code_sha256": code_sha, "rows": []}
        value["workload_sha256"] = fingerprint(value)
        return value

    def test_code_and_runtime_config_tamper_stop_before_opener(self):
        invoked = []
        identity = {"model": "Qwen/Qwen3.5-9B", "url": "https://unit.invalid/v1/chat/completions",
                    "enable_thinking": False, "transport": "jobs", "string_decoder": "host_validated",
                    "expected_model_revision": "rev"}
        cfg = {**identity, "jobs_url": "https://unit.invalid/v1/jobs"}
        with tempfile.TemporaryDirectory() as tmp:
            for label, value, config in (
                ("code", self.minimal_workload("tampered-code"), cfg),
                ("config", self.minimal_workload(core.code_hash()), {**cfg, "model": "tampered-model"}),
            ):
                with self.subTest(tamper=label), patch.object(core, "validate_manifest"), \
                        patch.object(runner.urlrequest, "urlopen", side_effect=lambda *a, **k: invoked.append(1)), \
                        self.assertRaises((ValueError, TypeError, KeyError)):
                    runner.run(value, output_root=Path(tmp) / label, cfg=config, execute=True,
                               opener=lambda *a, **k: invoked.append(1))
        self.assertEqual(invoked, [], "preflight must reject tampering before transport opener")

    def test_unknown_profile_is_rejected_locally_before_prepare_or_transport(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(core, "prepare", side_effect=AssertionError("prepare reached")) as prepare, \
                patch.object(runner.urlrequest, "urlopen", side_effect=AssertionError("network reached")) as opener, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["prepare", "--output-root", tmp, "--prompt-profile", "unknown-profile"])
        self.assertNotEqual(raised.exception.code, 0)
        prepare.assert_not_called()
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
