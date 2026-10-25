"""Independent behavioral checks for the source-complete Mốc1 builder/preflight.

These tests validate protocol, raw-source coverage, and provenance. They do not
score AU meaning and never invoke a provider.
"""
from __future__ import annotations

import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.milestone1.core import build_manifest, digest, preflight
from knowledge_base.pipeline_v1.milestone1 import runtime as m1_runtime
from knowledge_base.pipeline_v1.milestone1 import __main__ as m1_cli
from knowledge_base.pipeline_v1.au_compact.prompting import prompt_identity
from knowledge_base.pipeline_v1.au_compact.runner import RESPONSE_FORMAT_VERSION
from knowledge_base.pipeline_v1.source_contract.store import open_source


PIPELINE = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = PIPELINE / "manifests/calibration_manifest.v1.json"
FULL_MANIFEST = PIPELINE / "manifests/au_compact_kos5_full_m1.v1.json"
SOURCE_STORE = PIPELINE / "outputs/source_store_v1"
BLOCK_ROOT = PIPELINE / "outputs/plan03_source_blocks_v1"
ATOM_ROOT = PIPELINE / "outputs/plan04_sentence_atoms_v1"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class Milestone1IndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = (SOURCE_MANIFEST, FULL_MANIFEST,
                    SOURCE_STORE / "source_store_manifest.json",
                    BLOCK_ROOT / "sourceblock_build_manifest.json",
                    ATOM_ROOT / "sentence_atom_build_manifest.json")
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError("Mốc1 real fixture inputs missing: " + ", ".join(missing))
        cls.manifest = read_json(FULL_MANIFEST)
        cls.block_build = read_json(BLOCK_ROOT / "sourceblock_build_manifest.json")
        cls.atom_build = read_json(ATOM_ROOT / "sentence_atom_build_manifest.json")
        cls.blocks = {}
        cls.atoms = {}
        for row in cls.block_build["cases"]:
            cls.blocks[row["case_id"]] = read_json(BLOCK_ROOT / row["artifact_ref"])
        for row in cls.atom_build["cases"]:
            cls.atoms[row["case_id"]] = read_json(ATOM_ROOT / row["artifact_ref"])

    def test_full_manifest_is_reproducible_and_not_the_filtered_pilot(self):
        rebuilt = build_manifest(source_manifest=SOURCE_MANIFEST,
            source_store=SOURCE_STORE, atom_root=ATOM_ROOT, block_root=BLOCK_ROOT)
        self.assertEqual(self.manifest, rebuilt)
        self.assertEqual(self.manifest["artifact_type"], "AUCompactLockedManifest")
        self.assertEqual(set(self.manifest["milestone1"]["cases"][i]["case_id"]
                             for i in range(5)),
                         {"011904", "013009", "013948", "045155", "099980"})
        self.assertEqual(sum(row["block_count"] for row in self.block_build["cases"]), 431)
        self.assertGreater(len(self.manifest["requests"]), 431)  # Plan04 slices add work items.
        self.assertNotEqual(len(self.manifest["requests"]), 10)
        self.assertNotEqual(len(self.manifest["requests"]), 369)
        self.assertFalse(self.manifest["milestone1"]["kos_annotations_used"])
        self.assertIs(self.manifest["milestone1"]["semantic_quality_claim"], False)

    def test_each_non_whitespace_sourceblock_is_covered_once_including_headings_and_editorial(self):
        requests = self.manifest["requests"]
        requests_by_owner = {}
        for request in requests:
            key = (request["case_id"], request["provenance"]["parent_block_id"])
            requests_by_owner.setdefault(key, []).append(request)

        observed_types = set()
        for case_id, block_map in self.blocks.items():
            source_hash = block_map["source_hash"]
            source = open_source(SOURCE_STORE, case_id, source_hash)
            atom_map = self.atoms[case_id]
            slice_plans = {p["parent_block_id"]: p for p in atom_map["slice_plans"]}
            cursor = 0
            for block in block_map["blocks"]:
                span = block["span"]
                start, end = span["start_char"], span["end_char"]
                self.assertEqual(span["case_id"], case_id)
                self.assertEqual(span["source_hash"], source_hash)
                self.assertEqual(start, cursor, f"source gap/overlap in {case_id}")
                cursor = end
                owner = (case_id, block["block_id"])
                owned = requests_by_owner.get(owner, [])
                if not source[start:end].strip():
                    self.assertFalse(owned, f"whitespace-only block became target: {owner}")
                    continue
                observed_types.add(block.get("block_type"))
                target_spans = sorted(
                    (ref["start_char"], ref["end_char"])
                    for request in owned
                    for ref in request["source_refs"]
                    if ref["role"] == "target"
                )
                self.assertTrue(target_spans, f"non-whitespace block omitted: {owner}")
                plan = slice_plans.get(block["block_id"])
                expected_spans = [
                    (s["span"]["start_char"], s["span"]["end_char"])
                    for s in (plan["slices"] if plan else [{"span": span}])
                    if source[s["span"]["start_char"]:s["span"]["end_char"]].strip()
                ]
                self.assertEqual(target_spans, expected_spans,
                                 f"targets differ from full block/slice coverage: {owner}")
                self.assertEqual(target_spans[0][0], start, f"block start omitted: {owner}")
                self.assertEqual(target_spans[-1][1], end, f"block tail omitted: {owner}")
            self.assertEqual(cursor, len(source), f"source tail omitted: {case_id}")

        self.assertIn("heading_candidate", observed_types)
        self.assertIn("editorial", observed_types)
        self.assertEqual({r["case_id"] for r in requests},
                         {"011904", "013009", "013948", "045155", "099980"})
        for case in self.manifest["milestone1"]["cases"]:
            self.assertEqual(case["source_addressable_rate"], 1.0)
            self.assertEqual(case["non_whitespace_target_coverage"], 1.0)

    def test_context_is_whole_adjacent_plan04_atoms_within_character_cap(self):
        for request in self.manifest["requests"]:
            case_id = request["case_id"]
            atom_map = self.atoms[case_id]
            atoms = sorted(atom_map["atoms"], key=lambda a: (a["span"]["start_char"],
                                                               a["span"]["end_char"]))
            target = next(ref for ref in request["source_refs"] if ref["role"] == "target")
            before = [a for a in atoms if a["span"]["end_char"] <= target["start_char"]]
            after = [a for a in atoms if a["span"]["start_char"] >= target["end_char"]]
            allowed = {(a["span"]["start_char"], a["span"]["end_char"])
                       for a in ([before[-1]] if before else []) + ([after[0]] if after else [])}
            contexts = [r for r in request["source_refs"] if r["role"] == "context"]
            self.assertLessEqual(len(contexts), 2)
            self.assertLessEqual(sum(r["end_char"] - r["start_char"] for r in contexts), 800)
            for ref in contexts:
                self.assertIn((ref["start_char"], ref["end_char"]), allowed,
                              "context must be a whole immediate neighboring atom")
                self.assertEqual(ref["target_ids"], [])

    def test_omission_hash_offset_owner_model_and_prompt_tampering_fail_closed(self):
        mutations = {
            "omitted_request": lambda m: m["requests"].pop(),
            "source_hash": lambda m: m["requests"][0].update(source_hash="0" * 64),
            "offset": lambda m: m["requests"][0]["source_refs"][0].update(
                start_char=m["requests"][0]["source_refs"][0]["start_char"] + 1),
            "owner": lambda m: m["requests"][0]["provenance"].update(parent_block_id="sb-" + "0" * 24),
            "model": lambda m: m["requests"][0]["spec"].update(model="different-model"),
            "prompt": lambda m: m["milestone1"]["prompt_identity"].update(content_sha256="0" * 64),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                changed = copy.deepcopy(self.manifest)
                mutate(changed)
                # Exercise the canonical full-object gate without rebuilding 436 prompts
                # six times; the real dependency rebuild is exercised by the PASS test.
                with patch("knowledge_base.pipeline_v1.milestone1.core.build_manifest",
                           return_value=self.manifest), \
                     patch("knowledge_base.pipeline_v1.milestone1.core.compact_preflight",
                           return_value={"failures": []}):
                    result = preflight(changed, source_store=SOURCE_STORE, atom_root=ATOM_ROOT)
                self.assertEqual(result["status"], "fail")
                self.assertTrue(result["failures"])

    def test_raw_source_tampering_is_detected_without_touching_canonical_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_store = Path(temporary) / "source_store"
            shutil.copytree(SOURCE_STORE, copied_store)
            index = read_json(copied_store / "cases/011904/index.json")
            source_ref = index["versions"][0]["case_source_ref"]
            source_path = copied_store / source_ref.replace("case_source.json", "source.txt")
            original = source_path.read_bytes()
            source_path.write_bytes(original + b" ")
            # Rebuild must open the changed raw source and reject it. The compact
            # AU validator is orthogonal here and is stubbed to keep this adversary
            # focused and bounded.
            with patch("knowledge_base.pipeline_v1.milestone1.core.compact_preflight",
                       return_value={"failures": []}):
                result = preflight(self.manifest, source_store=copied_store, atom_root=ATOM_ROOT)
            self.assertEqual(result["status"], "fail")
            self.assertTrue(result["failures"])
            self.assertEqual(source_path.read_bytes(), original + b" ")

    def test_preflight_recomputes_full_prompt_bytes_and_enforces_aggregate_budget(self):
        result = preflight(self.manifest, source_store=SOURCE_STORE, atom_root=ATOM_ROOT)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["budget_mode"], "explicit_planned_budget")
        self.assertEqual(result["approved_budget"], result["planned_budget"])
        by_id = {r["request_id"]: r for r in self.manifest["requests"]}
        self.assertEqual(len(result["costs"]), len(by_id))
        for cost in result["costs"]:
            self.assertEqual(cost["full_prompt_bytes"], by_id[cost["request_id"]]["input_tokens"])
            self.assertEqual(cost["framing_reserve"], 128)
            self.assertEqual(cost["estimated_input_tokens"],
                             cost["full_prompt_bytes"] + cost["framing_reserve"])
        self.assertEqual(result["input_estimate_method"],
                         "full_prompt_utf8_bytes_plus128_framing_not_provider_usage")

        insufficient = {key: 0 for key in result["planned_budget"]}
        # Keep the real successful end-to-end preflight above; isolate the two
        # rejection gates here to avoid repeating 436 source/prompt renders.
        with patch("knowledge_base.pipeline_v1.milestone1.core.build_manifest",
                   return_value=self.manifest), \
             patch("knowledge_base.pipeline_v1.milestone1.core.compact_preflight",
                   return_value={"failures": []}), \
             patch("knowledge_base.pipeline_v1.milestone1.core.build_evidence_catalog",
                   return_value={}), \
             patch("knowledge_base.pipeline_v1.milestone1.core._render", return_value="x"), \
             patch("knowledge_base.pipeline_v1.milestone1.core.build_prompt", return_value="longer"):
            rejected = preflight(self.manifest, source_store=SOURCE_STORE,
                atom_root=ATOM_ROOT, budget=insufficient, max_input_tokens=1)
        self.assertEqual(rejected["status"], "fail")
        self.assertTrue(any(f.get("stage") == "aggregate_budget"
                            and f.get("field") == "max_total_input_tokens"
                            for f in rejected["failures"]))
        self.assertTrue(any(f.get("stage") == "per_request_input"
                            for f in rejected["failures"]))

    def test_runtime_requires_current_approval_and_forces_local_testable_transport_policy(self):
        request = self.manifest["requests"][0]
        approved = {
            "status": "pass", "manifest_sha256": digest(self.manifest),
            "approved_budget": {"max_requests": len(self.manifest["requests"]),
                "max_provider_attempts": len(self.manifest["requests"]),
                "max_total_input_tokens": 10**9,
                "max_total_output_tokens": len(self.manifest["requests"]) * 800},
            "per_request_input_ceiling": 11488,
            "prompt_identity": prompt_identity(),
            "decoder_version": RESPONSE_FORMAT_VERSION,
            "version": self.manifest["milestone1"]["version"],
            "request_count": len(self.manifest["requests"]),
            "cases": self.manifest["milestone1"]["cases"],
            "costs": [{"request_id": request["request_id"], "estimated_input_tokens": 1000}],
            "planned_budget": {"max_requests": len(self.manifest["requests"])},
            "compact_preflight": {"status": "pass", "failures": []},
        }
        preflight_check = {key: approved[key] for key in (
            "approved_budget", "per_request_input_ceiling", "prompt_identity", "decoder_version",
            "version", "request_count", "cases", "costs", "planned_budget", "compact_preflight")}
        preflight_check.update(status="pass")
        fake_result = {"status": "complete", "request_ledger": [{
            "request": request, "status": "protocol_verified",
            "compact_response": {"coverage_status": "needs_split"},
            "response": {"target_results": [{"decision": "unresolved"}]},
        }]}
        cfg = {"url": "https://local.invalid/v1/chat/completions",
               "model": self.manifest["milestone1"]["model"], "enable_thinking": False,
               "transport": "direct", "string_decoder": "bounded"}
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(m1_runtime, "preflight", return_value=preflight_check), \
             patch.object(m1_runtime.runner, "run", return_value=fake_result) as runner:
            result = m1_runtime.run(self.manifest, preflight_report=approved,
                source_store=SOURCE_STORE, atom_root=ATOM_ROOT, cfg=cfg,
                output_root=temporary, warmup_policy={}, execute=True)

        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["milestone1"]["protocol_status"], "complete")
        self.assertEqual(result["milestone1"]["needs_split_request_ids"],
                         [request["request_id"]])
        self.assertEqual(result["milestone1"]["unresolved_request_ids"],
                         [request["request_id"]])
        self.assertFalse(result["milestone1"]["semantic_accepted"])
        self.assertFalse(result["milestone1"]["kos_annotations_used_for_extraction"])
        kwargs = runner.call_args.kwargs
        self.assertTrue(kwargs["execute"])
        self.assertEqual(kwargs["cfg"]["transport"], "jobs")
        self.assertEqual(kwargs["cfg"]["string_decoder"], "host_validated")
        self.assertEqual(kwargs["cfg"]["jobs_url"], "https://local.invalid/v1/jobs")
        self.assertEqual(cfg["transport"], "direct", "wrapper must not mutate caller config")
        self.assertFalse((Path(temporary) / "milestone1_run.lock").exists(),
                         "exclusive run lock must be released after completion")

        # Every persisted approval detail must still match a freshly rebuilt
        # preflight before the compact runner can be reached.
        for field in ("version", "request_count", "cases", "costs", "planned_budget",
                      "compact_preflight"):
            with self.subTest(stale_preflight_field=field), tempfile.TemporaryDirectory() as temp:
                changed_approval = copy.deepcopy(approved)
                if isinstance(changed_approval[field], list):
                    changed_approval[field].append({"tampered": True})
                elif isinstance(changed_approval[field], dict):
                    changed_approval[field]["tampered"] = True
                else:
                    changed_approval[field] = "tampered"
                with patch.object(m1_runtime, "preflight", return_value=preflight_check), \
                     patch.object(m1_runtime.runner, "run") as blocked_runner:
                    with self.assertRaisesRegex(ValueError, "preflight_content_differs"):
                        m1_runtime.run(self.manifest, preflight_report=changed_approval,
                            source_store=SOURCE_STORE, atom_root=ATOM_ROOT, cfg=cfg,
                            output_root=temp, warmup_policy={}, execute=True)
                    blocked_runner.assert_not_called()

    def test_runtime_rejects_missing_execute_stale_approval_and_runtime_binding(self):
        approved = {"status": "pass", "manifest_sha256": digest(self.manifest),
                    "approved_budget": {}, "per_request_input_ceiling": 11488,
                    "prompt_identity": prompt_identity(),
                    "decoder_version": RESPONSE_FORMAT_VERSION,
                    "version": self.manifest["milestone1"]["version"],
                    "request_count": len(self.manifest["requests"]),
                    "cases": self.manifest["milestone1"]["cases"], "costs": [],
                    "planned_budget": {}, "compact_preflight": {}}
        args = dict(preflight_report=approved, source_store=SOURCE_STORE,
                    atom_root=ATOM_ROOT,
                    cfg={"url": "https://local.invalid/v1/chat/completions",
                         "model": self.manifest["milestone1"]["model"],
                         "enable_thinking": False}, output_root="unused",
                    warmup_policy={})
        with self.assertRaisesRegex(ValueError, "requires_execute"):
            m1_runtime.run(self.manifest, **args, execute=False)
        stale = {**approved, "manifest_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "stale"):
            m1_runtime.run(self.manifest, **{**args, "preflight_report": stale}, execute=True)
        wrong_cfg = {**args["cfg"], "enable_thinking": True}
        with self.assertRaisesRegex(ValueError, "model_or_thinking"):
            m1_runtime.run(self.manifest, **{**args, "cfg": wrong_cfg}, execute=True)

        check = {key: approved[key] for key in (
            "approved_budget", "per_request_input_ceiling", "prompt_identity", "decoder_version",
            "version", "request_count", "cases", "costs", "planned_budget", "compact_preflight")}
        check["status"] = "pass"
        with tempfile.TemporaryDirectory() as temporary:
            locked_root = Path(temporary)
            (locked_root / "milestone1_run.lock").write_text("held", encoding="utf-8")
            with patch.object(m1_runtime, "preflight", return_value=check):
                with self.assertRaisesRegex(ValueError, "run_locked"):
                    m1_runtime.run(self.manifest, **{**args, "output_root": locked_root}, execute=True)

        with patch.object(m1_runtime, "preflight", return_value=check):
            with self.assertRaisesRegex(ValueError, "output_overlaps_source_dependency"):
                m1_runtime.run(self.manifest, **{**args, "output_root": SOURCE_STORE / "illegal"}, execute=True)

    def test_runtime_downgrades_runner_complete_with_435_workload_requests_unrun(self):
        requests = self.manifest["requests"]
        first = requests[0]
        approved = {
            "status": "pass", "manifest_sha256": digest(self.manifest),
            "approved_budget": {"max_requests": len(requests),
                "max_provider_attempts": len(requests),
                "max_total_input_tokens": 10**9,
                "max_total_output_tokens": len(requests) * 800},
            "per_request_input_ceiling": 11488,
            "prompt_identity": prompt_identity(),
            "decoder_version": RESPONSE_FORMAT_VERSION,
            "version": self.manifest["milestone1"]["version"],
            "request_count": len(requests),
            "cases": self.manifest["milestone1"]["cases"],
            "costs": [], "planned_budget": {}, "compact_preflight": {"status": "pass"},
        }
        check = {key: approved[key] for key in (
            "approved_budget", "per_request_input_ceiling", "prompt_identity", "decoder_version",
            "version", "request_count", "cases", "costs", "planned_budget", "compact_preflight")}
        check["status"] = "pass"
        fake_result = {"status": "complete", "request_ledger": [{
            "request": first, "status": "protocol_verified",
            "response": {"target_results": [{"decision": "covered"}]},
        }]}
        cfg = {"url": "https://local.invalid/v1/chat/completions",
               "model": self.manifest["milestone1"]["model"], "enable_thinking": False}
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(m1_runtime, "preflight", return_value=check), \
             patch.object(m1_runtime.runner, "run", return_value=fake_result):
            result = m1_runtime.run(self.manifest, preflight_report=approved,
                source_store=SOURCE_STORE, atom_root=ATOM_ROOT, cfg=cfg,
                output_root=temporary, warmup_policy={}, execute=True)

        milestone = result["milestone1"]
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(milestone["protocol_status"], "complete")
        self.assertEqual(milestone["expected_requests"], 436)
        self.assertEqual(milestone["unrun_request_ids"], sorted(q["request_id"] for q in requests[1:]))
        self.assertEqual(len(milestone["unrun_request_ids"]), 435)
        self.assertEqual(milestone["unexpected_request_ids"], [])
        self.assertFalse(milestone["runner_request_identity_invalid"])
        self.assertEqual(milestone["needs_split_request_ids"], [])
        self.assertEqual(milestone["unresolved_request_ids"], [])

    def test_cli_uses_environment_caps_by_default_and_planned_budget_only_when_requested(self):
        configured_budget = {"max_requests": 2, "max_provider_attempts": 2,
                             "max_total_input_tokens": 100,
                             "max_total_output_tokens": 100}
        for planned, expected in ((False, configured_budget), (True, None)):
            with self.subTest(planned_budget=planned), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "preflight.json"
                argv = ["milestone1", "preflight", "--manifest", str(FULL_MANIFEST),
                    "--source-store", str(SOURCE_STORE), "--atom-root", str(ATOM_ROOT),
                    "--block-root", str(BLOCK_ROOT), "--output", str(output)]
                if planned:
                    argv.append("--planned-budget")
                with patch.object(sys, "argv", argv), \
                     patch.object(m1_cli, "settings", return_value={}) as settings, \
                     patch.object(m1_cli, "load_au_runtime_config",
                                  return_value=({}, configured_budget, {})) as load_config, \
                     patch.object(m1_cli, "preflight", return_value={
                         "status": "pass", "request_count": len(self.manifest["requests"]),
                     }) as cli_preflight:
                    self.assertEqual(m1_cli.main(), 0)
                self.assertEqual(cli_preflight.call_args.kwargs["budget"], expected)
                self.assertEqual(load_config.call_count, 0 if planned else 1)
                self.assertEqual(settings.call_count, 0 if planned else 1)
                self.assertTrue(output.is_file())

    def test_cli_writes_new_preflight_ready_path_without_overwriting_legacy_preflight(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "m1-output"
            output_root.mkdir()
            legacy_path = output_root / "preflight.json"
            legacy_path.write_text('{"historical":"keep"}\n', encoding="utf-8")
            legacy_before = legacy_path.read_bytes()
            argv = ["milestone1", "preflight", "--planned-budget",
                "--manifest", str(FULL_MANIFEST), "--source-store", str(SOURCE_STORE),
                "--atom-root", str(ATOM_ROOT), "--block-root", str(BLOCK_ROOT),
                "--output-root", str(output_root)]
            with patch.object(sys, "argv", argv), \
                 patch.object(m1_cli, "preflight", return_value={
                     "status": "pass", "request_count": len(self.manifest["requests"])}):
                code = m1_cli.main()
            self.assertEqual(code, 0)
            self.assertEqual(legacy_path.read_bytes(), legacy_before)
            self.assertTrue((output_root / "preflight_ready.json").is_file())

    def test_cli_run_requires_explicit_execute_and_preflight_and_never_runs_in_this_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight_path = root / "approved.json"
            preflight_path.write_text("{}", encoding="utf-8")
            common = ["milestone1", "run", "--manifest", str(FULL_MANIFEST),
                "--source-store", str(SOURCE_STORE), "--atom-root", str(ATOM_ROOT),
                "--block-root", str(BLOCK_ROOT), "--preflight", str(preflight_path),
                "--output-root", str(root / "run")]
            with patch.object(sys, "argv", common), \
                 patch.object(m1_cli, "settings", return_value={}), \
                 patch.object(m1_cli, "load_au_runtime_config", return_value=({}, {}, {})), \
                 patch.object(m1_runtime, "run") as runner:
                with self.assertRaises(SystemExit) as missing_execute:
                    m1_cli.main()
                self.assertEqual(missing_execute.exception.code, 2)
                runner.assert_not_called()

            argv = common + ["--execute"]
            missing_token_cfg = {"url": "https://must-not-be-echoed.invalid/v1/chat/completions",
                                 "token": "", "model": "must-not-be-echoed"}
            captured = io.StringIO()
            with patch.object(sys, "argv", argv), \
                 patch.object(m1_cli, "settings", return_value={}), \
                 patch.object(m1_cli, "load_au_runtime_config",
                              return_value=(missing_token_cfg, {}, {})), \
                 patch.object(m1_runtime, "run") as runner, \
                 redirect_stdout(captured):
                self.assertEqual(m1_cli.main(), 2)
            self.assertIn("MILESTONE1 ERROR runtime_endpoint_credentials_missing", captured.getvalue())
            self.assertNotIn("must-not-be-echoed", captured.getvalue())
            runner.assert_not_called()

            cfg = {"url": "https://local.invalid/v1/chat/completions", "token": "unit-test-token",
                   "model": "local-test", "enable_thinking": False}
            with patch.object(sys, "argv", argv), \
                 patch.object(m1_cli, "settings", return_value={}), \
                 patch.object(m1_cli, "load_au_runtime_config", return_value=(cfg, {}, {})), \
                 patch.object(m1_runtime, "run", return_value={"status": "incomplete"}) as runner:
                self.assertEqual(m1_cli.main(), 3)
            runner.assert_called_once()
            self.assertTrue((root / "run/run.json").is_file())


if __name__ == "__main__":
    unittest.main()
