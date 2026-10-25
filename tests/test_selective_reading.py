"""Independent behavior tests for bounded selective-reading navigation.

Synthetic tasks only: no old AU predictions or KOS labels participate in
region choice. Runtime and end-to-end tests are added against the public core
API as it lands.
"""
from __future__ import annotations

import unittest
import json
import copy
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.selective_reading.catalog import (
    expand_context,
    find_source,
    get_case_overview,
    get_reading_state,
    list_blocks,
    previews,
)
from knowledge_base.pipeline_v1.selective_reading.core import (
    build_manifest,
    discovery,
    fingerprints,
    host_selection,
    normalize_planner,
    prepare,
    planner_task,
)
from knowledge_base.pipeline_v1.selective_reading.runtime import (
    _budget,
    _commit,
    _report,
    run as run_selective,
)
from knowledge_base.pipeline_v1.bulk_execution.transport import (
    GroupTransport,
    GroupTransportError,
    group_id,
)
from knowledge_base.pipeline_v1.au_compact.jobs_client import payload_digest
from knowledge_base.pipeline_v1.milestone1.core import digest, load


_ROOT = Path(__file__).resolve().parents[1] / "knowledge_base/pipeline_v1"


def _locked_pilot_inputs():
    parent = load(_ROOT / "outputs/bulk_trial30_20261013/manifest.json")
    manifest = build_manifest(parent, "selective-test", seed=20261013)
    return manifest, parent


def _valid_local_capability(*, ready=True, **overrides):
    value = {
        "experiment": "au-bulk-v1",
        "app": "coliee-qwen35-9b-bulk",
        "gateway_concurrency": 4,
        "server_concurrency": 4,
        "model": "Qwen/Qwen3.5-9B",
        "context_length": 12288,
        "max_total_tokens": 12288,
        "backend_retry": False,
        "exclusive_probes": True,
        "max_containers": 1,
        "ready": ready,
        "poisoned": False,
        "stopping": False,
        "backend_outcome_unknown": False,
        "capabilities": {"bulk_submit": True},
    }
    value.update(overrides)
    return value


class _LocalSelectiveTransport:
    """Local deterministic BULK transport; it never opens a network socket."""

    def __init__(self, *, lose_first_ack=False):
        self.lose_first_ack = lose_first_ack
        self.groups = {}
        self.posted = []
        self.gets = []
        self.stats = {"local_simulation": True}

    @staticmethod
    def _receipt(job):
        prompt = job["payload"]["messages"][0]["content"]
        request_id = re.search(r"REQUEST_ID=([^\r\n]+)", prompt).group(1)
        target_id = re.search(r"TARGET_ID=([^\r\n]+)", prompt).group(1)
        content = json.dumps({
            "request_id": request_id,
            "target_id": target_id,
            "decision": "hard_negative",
            "coverage_status": "complete",
            "aus": [],
            "hard_negative_reason": "other",
            "unresolved_reason": None,
        }, separators=(",", ":"))
        response = {
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        }
        return {
            "job_id": job["job_id"], "payload_sha256": job["job_id"],
            "status": "completed", "response": response,
            "response_sha256": payload_digest(response),
        }

    def _envelope(self, gid, jobs):
        results = [self._receipt(job) for job in jobs]
        return {
            "group_id": gid, "mode": "bulk", "cursor": 0,
            "next_cursor": len(results), "results": results,
            "counts": {"total": len(results), "queued": 0, "running": 0,
                       "completed": len(results), "failed": 0, "interrupted": 0},
        }

    def admit(self, mode, jobs, *, resume=False):
        gid = group_id(mode, jobs)
        self.posted.append(gid)
        self.groups[gid] = list(jobs)
        if self.lose_first_ack and len(self.posted) == 1:
            raise GroupTransportError("group_transport", outcome_unknown=True)
        return self._envelope(gid, jobs), False

    def progress(self, mode, gid, after, *, remaining=None):
        self.gets.append(gid)
        jobs = self.groups[gid]
        value = self._envelope(gid, jobs)
        value["cursor"] = after
        value["next_cursor"] = after + len(value["results"])
        return value


class _ScenarioSelectiveTransport(_LocalSelectiveTransport):
    """Inject one deterministic terminal condition into the first matching job."""

    def __init__(self, scenario):
        super().__init__()
        self.scenario = scenario
        self.injected = False

    @staticmethod
    def _receipt(job):
        prompt = job["payload"]["messages"][0]["content"]
        if "Choose exactly" not in prompt:
            return _LocalSelectiveTransport._receipt(job)
        grammar = job["payload"]["ebnf"].split("root ::= ", 1)[1]
        content = json.loads(re.findall(r'"(?:\\.|[^"\\])*"', grammar)[0])
        response = {"choices": [{"finish_reason": "stop", "message": {"content": content}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}
        return {"job_id": job["job_id"], "payload_sha256": job["job_id"],
                "status": "completed", "response": response,
                "response_sha256": payload_digest(response)}

    def _envelope(self, gid, jobs):
        value = super()._envelope(gid, jobs)
        if self.injected:
            return value
        for receipt, job in zip(value["results"], jobs):
            prompt = job["payload"]["messages"][0]["content"]
            is_planner = "Choose exactly" in prompt
            matches = ((self.scenario == "invalid_planner" and is_planner)
                       or (self.scenario != "invalid_planner" and not is_planner))
            if not matches:
                continue
            self.injected = True
            if self.scenario == "invalid_planner":
                receipt["response"]["choices"][0]["message"]["content"] = "{}"
            elif self.scenario == "host_invalid":
                request_id = re.search(r"REQUEST_ID=([^\r\n]+)", prompt).group(1)
                target_id = re.search(r"TARGET_ID=([^\r\n]+)", prompt).group(1)
                response = {"request_id": request_id, "target_id": target_id,
                    "decision": "positive", "coverage_status": "complete",
                    "aus": [{"kind": "holding", "other_kind": None,
                        "claim": "x" * 301, "evidence_ref_ids": ["sa-invalid"],
                        "speaker": "current_court", "attribution_role": "proposition",
                        "needs_context": []}],
                    "hard_negative_reason": None, "unresolved_reason": None}
                receipt["response"]["choices"][0]["message"]["content"] = json.dumps(
                    response, separators=(",", ":"))
            elif self.scenario == "unknown_usage":
                receipt["response"]["usage"] = None
            elif self.scenario == "unknown_outcome":
                receipt["status"] = "interrupted"
                value["counts"]["completed"] -= 1
                value["counts"]["interrupted"] += 1
            else:
                raise AssertionError(f"unknown scenario: {self.scenario}")
            receipt["response_sha256"] = payload_digest(receipt["response"])
            break
        return value


def _task(case_id: str, ordinal: int, start: int, text: str):
    source = " " * start + text + " " * 3000
    end = start + len(text)
    request = {
        "case_id": case_id,
        "source_hash": "a" * 64,
        "source_refs": [{"role": "target", "start_char": start,
                         "end_char": end, "target_ids": [f"target-{ordinal}"]}],
    }
    atoms = []
    for i, atom_text in enumerate(("background", "Counsel submits an argument.",
                                   "The court rejects that submission unless condition X applies.",
                                   "A later exception applies only if condition Y is met.")):
        a = 100 + i * 500
        atoms.append({"atom_id": f"atom-{i}", "span": {"start_char": a,
                                                         "end_char": a + len(atom_text)}})
        source = source[:a] + atom_text + source[a + len(atom_text):]
    return {
        "request": request,
        "source": source,
        "navigation": {"navigation_id": f"nav-{ordinal}", "ordinal": ordinal,
                       "case_id": case_id, "source_hash": "a" * 64,
                       "start_char": start, "end_char": end,
                       "previews": []},
        "catalog": {"atoms": {}, "atom_map": {"atoms": atoms}},
    }


class SelectiveReadingNavigationTests(unittest.TestCase):
    def _run_scenario(self, scenario, arm="H"):
        manifest, _ = _locked_pilot_inputs()
        transport = _ScenarioSelectiveTransport(scenario)
        cfg = {
            "url": "https://g38180254--coliee-qwen35-9b-bulk-server.us-west.modal.direct/v1/chat/completions",
            "token": "local-test-token", "model": "Qwen/Qwen3.5-9B",
            "enable_thinking": False, "job_wait_seconds": 5,
        }
        with tempfile.TemporaryDirectory() as temp:
            report = run_selective(
                manifest, cfg, arm, Path(temp) / "pilot", execute=True,
                source_store=_ROOT / "outputs/source_store_v1",
                atom_root=_ROOT / "outputs/plan04_sentence_atoms_v1",
                transport=transport,
                capability_fetch=lambda _cfg: _valid_local_capability(),
                warmup_fn=lambda *_args: {"status": "success", "usage": {
                    "input_tokens": 10, "output_tokens": 5, "total_tokens": 15}},
                policy={"max_attempts": 1, "max_wait_seconds": 5},
            )
        return report, transport

    def test_known_host_invalid_extraction_keeps_unresolved_cost_and_continues(self):
        report, transport = self._run_scenario("host_invalid")

        self.assertEqual(report["status"], "complete")
        self.assertTrue(report["selective_pass"] is False)
        self.assertEqual(len(report["selected_request_ids"]), 15)
        self.assertEqual(report["cost_ledger"]["requests"], 15)
        self.assertEqual(report["cost_ledger"]["usage_unavailable"], 0)
        self.assertEqual(report["cost_ledger"]["tokens"]["total_tokens"], 15 * 110)
        self.assertEqual(len(transport.posted), 4)
        unresolved = [row for row in report["request_ledger"] if row["status"] == "unresolved"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["publication_status"], "semantic_review_pending")
        self.assertEqual(unresolved[0]["receipt"]["failure_diagnostic"]["kind"], "host_validation")
        self.assertEqual(len(json.loads(unresolved[0]["receipt"]["raw_response"])["aus"][0]["claim"]), 301)
        self.assertIn(unresolved[0]["original_request"]["request_id"], report["selected_request_ids"])

    def test_invalid_planner_skips_only_that_case_without_fallback_and_blocks_pass(self):
        report, transport = self._run_scenario("invalid_planner", arm="P")

        self.assertEqual(report["status"], "complete")
        self.assertFalse(report["selective_pass"])
        self.assertEqual(len(report["selections"]), 5)
        failed = [case for case, selection in report["selections"].items()
                  if selection.get("planning_status") == "unresolved"]
        self.assertEqual(len(failed), 1, report["selections"])
        self.assertEqual(report["selections"][failed[0]]["initial"], [])
        self.assertEqual(len(report["selected_request_ids"]), 12)
        self.assertEqual(report["cost_ledger"]["requests"], 17)
        self.assertEqual(len(transport.posted), 5)

    def test_unknown_usage_and_outcome_still_halt_all_new_admissions(self):
        for scenario, stop_reason in (("unknown_usage", "unknown_usage_fail_closed"),
                                      ("unknown_outcome", "provider_outcome_unknown")):
            with self.subTest(scenario=scenario):
                report, transport = self._run_scenario(scenario)
                self.assertEqual(report["status"], "incomplete")
                self.assertEqual(report["stop_reason"], stop_reason)
                self.assertEqual(len(transport.posted), 1)
                self.assertEqual(report["cost_ledger"]["requests"], 4)
                if scenario == "unknown_usage":
                    self.assertGreater(report["cost_ledger"]["usage_unavailable"], 0)
                else:
                    self.assertEqual(report["cost_ledger"]["tokens"]["total_tokens"], 4 * 110)

    def test_estimated_large_initial_batch_is_adaptively_chunked_and_mock_is_not_perf_evidence(self):
        manifest, _ = _locked_pilot_inputs()
        transport = _LocalSelectiveTransport()
        cfg = {
            "url": "https://g38180254--coliee-qwen35-9b-bulk-server.us-west.modal.direct/v1/chat/completions",
            "token": "local-test-token", "model": "Qwen/Qwen3.5-9B",
            "enable_thinking": False, "job_wait_seconds": 5,
        }
        capability = lambda _cfg: _valid_local_capability()
        warmup = lambda *_args: {"status": "success", "usage": {
            "input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}

        with tempfile.TemporaryDirectory() as temp:
            report = run_selective(
                manifest, cfg, "H", Path(temp) / "pilot", execute=True,
                source_store=_ROOT / "outputs/source_store_v1",
                atom_root=_ROOT / "outputs/plan04_sentence_atoms_v1",
                transport=transport, capability_fetch=capability, warmup_fn=warmup,
                policy={"max_attempts": 1, "max_wait_seconds": 5},
            )

        self.assertEqual(report["status"], "complete")
        self.assertTrue(report["selective_pass"])
        self.assertEqual(len(report["selected_request_ids"]), 15)
        self.assertEqual(report["cost_ledger"]["requests"], 15)
        self.assertLess(report["cost_ledger"]["tokens"]["input_tokens"], 100000)
        self.assertGreaterEqual(len(transport.posted), 4)
        self.assertTrue(all(len(transport.groups[gid]) <= 4 for gid in transport.posted))
        self.assertEqual(report["execution_evidence"], "mock/injected")
        self.assertFalse(report["performance_eligible"])

    def test_unhealthy_resume_recovers_pending_group_without_posting_new_groups(self):
        manifest, _ = _locked_pilot_inputs()
        cfg = {
            "url": "https://g38180254--coliee-qwen35-9b-bulk-server.us-west.modal.direct/v1/chat/completions",
            "token": "local-test-token", "model": "Qwen/Qwen3.5-9B",
            "enable_thinking": False, "job_wait_seconds": 5,
        }
        ready = lambda _cfg: _valid_local_capability()
        warmup = lambda *_args: {"status": "success", "usage": {
            "input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
        first = _LocalSelectiveTransport(lose_first_ack=True)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "pilot"
            first_report = run_selective(
                manifest, cfg, "H", root, execute=True,
                source_store=_ROOT / "outputs/source_store_v1",
                atom_root=_ROOT / "outputs/plan04_sentence_atoms_v1",
                transport=first, capability_fetch=ready, warmup_fn=warmup,
                policy={"max_attempts": 1, "max_wait_seconds": 5},
            )
            self.assertEqual(first_report["status"], "incomplete")
            self.assertEqual(len(first.posted), 1)

            recovery = _LocalSelectiveTransport()
            recovery.groups = copy.deepcopy(first.groups)
            unhealthy = lambda _cfg: _valid_local_capability(
                ready=False, poisoned=True, backend_outcome_unknown=True)
            second_report = run_selective(
                manifest, cfg, "H", root, execute=True,
                source_store=_ROOT / "outputs/source_store_v1",
                atom_root=_ROOT / "outputs/plan04_sentence_atoms_v1",
                transport=recovery, capability_fetch=unhealthy, warmup_fn=warmup,
                policy={"max_attempts": 1, "max_wait_seconds": 5},
            )

        self.assertTrue(recovery.gets, "pending reservation should be recovered by GET")
        self.assertEqual(recovery.posted, [], "recovery must not admit fresh inference groups")
        self.assertEqual(len(second_report["groups"]), 1)
        self.assertFalse(second_report["performance_eligible"])

    def test_manifest_locks_only_exact_30_parent_requests_and_six_per_case(self):
        manifest, parent = _locked_pilot_inputs()
        original = parent["parent"]["requests"]

        self.assertEqual(len(original), 30)
        self.assertEqual(len(manifest["parent"]["parent"]["requests"]), 30)
        self.assertEqual(manifest["universe_sha256"], digest(original))
        self.assertEqual({case: sum(q["case_id"] == case for q in original)
                          for case in {q["case_id"] for q in original}},
                         {case: 6 for case in {q["case_id"] for q in original}})
        self.assertFalse(manifest["semantic_quality_claim"])

    def test_manifest_rejects_duplicate_original_target(self):
        _, parent = _locked_pilot_inputs()
        parent["parent"]["requests"][1]["expected_target_ids"] = copy.deepcopy(
            parent["parent"]["requests"][0]["expected_target_ids"])
        # Recompute the parent manifest's own integrity envelope so this tests
        # duplicate target validation, not merely stale-parent detection.
        from knowledge_base.pipeline_v1.bulk_execution.core import build_manifest as build_bulk_manifest
        parent = build_bulk_manifest(parent["parent"], workload_id=parent["workload_id"])
        with self.assertRaisesRegex(ValueError, "duplicate_universe_identity"):
            build_manifest(parent, "duplicate-test")

    def test_prepare_uses_exact_locked_sources_and_keeps_navigation_ids_separate(self):
        manifest, parent = _locked_pilot_inputs()
        tasks = prepare(manifest, _ROOT / "outputs/source_store_v1",
                        _ROOT / "outputs/plan04_sentence_atoms_v1")
        originals = {q["request_id"]: q for q in parent["parent"]["requests"]}

        self.assertEqual(len(tasks), 30)
        for task in tasks:
            original = originals[task["request"]["request_id"]]
            self.assertEqual(task["request"]["source_hash"], original["source_hash"])
            self.assertEqual(task["request"]["source_refs"], original["source_refs"])
            nav = task["navigation"]
            self.assertEqual(nav["original_request_id"], original["request_id"])
            self.assertEqual(nav["source_hash"], original["source_hash"])
            self.assertNotIn(nav["navigation_id"], task["catalog"]["atoms"])
            self.assertLessEqual(len(nav["previews"]), 3)
            self.assertTrue(all(len(p["quote"]) <= 120 for p in nav["previews"]))
            for preview in nav["previews"]:
                a, b = preview["start_char"], preview["end_char"]
                self.assertEqual(preview["quote"], task["source"][a:b])
                self.assertEqual(preview["source_hash"], original["source_hash"])

    def test_host_priority_and_discovery_are_distinct_and_seed_deterministic(self):
        tasks = [_task("same-case", i, i * 4000,
                       ("The court held that a rule applies. " if i in (0, 1) else "Facts only."))
                 for i in range(6)]
        for i, task in enumerate(tasks):
            task["navigation"]["navigation_id"] = f"nav-{i}"
            task["navigation"]["ordinal"] = i
            task["navigation"]["previews"] = previews(task)
        priority = host_selection(tasks, 42, "same-case")
        self.assertEqual(len(priority), 3)
        self.assertEqual(len(set(priority)), 3)
        self.assertEqual(set(priority[:2]), {"nav-0", "nav-1"})
        self.assertNotIn(priority[2], priority[:2])
        self.assertEqual(discovery(tasks, priority[:2], 42, "same-case"), priority[2])
        self.assertNotIn(discovery(tasks, priority[:2], 42, "same-case"), priority[:2])

    def test_planner_output_is_a_finite_closed_id_set_and_invalid_output_fails_closed(self):
        options = [{"navigation_id": f"nav-{i}", "previews": [{"quote": "raw excerpt"}]}
                   for i in range(6)]
        task = planner_task({"test": "manifest"}, "case-x",
                            {"case_id": "case-x", "source_hash": "a" * 64,
                             "options": options})
        self.assertEqual(len(task["allowed_outputs"]), 15)
        self.assertTrue(all(output in task["allowed_outputs"] for output in task["allowed_outputs"]))
        self.assertTrue(all(set(json.loads(output)["selected_ids"]) <= set(task["options"])
                            for output in task["allowed_outputs"]))
        good = {"job_id": "job-plan", "status": "completed", "response": {
            "choices": [{"finish_reason": "stop", "message": {"content": task["allowed_outputs"][0]}}]}}
        accepted = normalize_planner(good, task)
        self.assertEqual(accepted["status"], "protocol_verified")

        bad = copy.deepcopy(good)
        invalid = json.loads(task["allowed_outputs"][0])
        invalid["selected_ids"][0] = "not-offered"
        bad["response"]["choices"][0]["message"]["content"] = json.dumps(invalid, separators=(",", ":"))
        rejected = normalize_planner(bad, task)
        self.assertEqual(rejected["status"], "unresolved")
        self.assertIsNone(rejected["response"])

        truncated = copy.deepcopy(good)
        truncated["response"]["choices"][0]["finish_reason"] = "length"
        self.assertEqual(normalize_planner(truncated, task)["status"], "unresolved")

        chosen = json.loads(task["allowed_outputs"][0])["selected_ids"]
        replan = planner_task({"test": "manifest"}, "case-x",
                              {"case_id": "case-x", "source_hash": "a" * 64,
                               "options": options}, phase="replan", excluded=chosen,
                              trigger={"needs_context": True})
        self.assertEqual(len(replan["allowed_outputs"]), 4)
        self.assertTrue(all(len(json.loads(output)["selected_ids"]) == 1
                            for output in replan["allowed_outputs"]))
        self.assertTrue(all(set(json.loads(output)["selected_ids"]).isdisjoint(chosen)
                            for output in replan["allowed_outputs"]))

    def test_request_fingerprint_changes_when_rendered_catalog_changes(self):
        manifest = {"universe_sha256": "a" * 64, "seed": 1}
        task = _task("case-x", 0, 0, "A source target.")
        task["catalog"]["atoms"] = {"ev-1": {"start_char": 0, "end_char": 10}}
        task["request"]["atom_binding"] = {"atom_map_sha256": "binding-one"}
        task["rendered"] = "render-one"
        cfg = {"url": "https://private.example/v1/chat/completions"}
        before = fingerprints(manifest, [task], "H", cfg)
        changed = copy.deepcopy(task)
        changed["rendered"] = "render-two"
        after = fingerprints(manifest, [changed], "H", cfg)
        self.assertNotEqual(before["catalog_sha256"], after["catalog_sha256"])

    def test_previews_are_raw_bounded_source_excerpts_and_deduplicated(self):
        task = _task("synthetic", 0, 3500,
                     "Background. " * 50 + "The court holds unless condition Z applies. " + "Tail. " * 50)
        got = previews(task)

        self.assertLessEqual(len(got), 3)
        self.assertEqual(len({(p["start_char"], p["end_char"]) for p in got}), len(got))
        for preview in got:
            self.assertLessEqual(preview["end_char"] - preview["start_char"], 120)
            self.assertEqual(preview["quote"], task["source"][preview["start_char"]:preview["end_char"]])
            self.assertEqual(preview["source_hash"], task["request"]["source_hash"])
            self.assertIn(preview["selector"], {"first", "last", "salient"})

    def test_navigation_pagination_is_finite_and_exposure_is_not_assessment(self):
        prepared = [_task("same-case", i, i * 4000, f"target region {i}") for i in range(6)]
        overview = get_case_overview(prepared, "same-case")
        first = list_blocks(prepared, "same-case", cursor=0, limit=6)

        self.assertEqual(overview["universe_regions"], 6)
        self.assertEqual(overview["scope"], "six_workload_regions_not_whole_case_overview")
        self.assertEqual(len(first["items"]), 6)
        self.assertIsNone(first["next_cursor"])
        self.assertFalse(first["source_assessed"])
        self.assertEqual([item["navigation_id"] for item in first["items"]],
                         [f"nav-{i}" for i in range(6)])
        with self.assertRaises(ValueError):
            list_blocks(prepared, "same-case", cursor=0, limit=7)

    def test_find_source_can_navigate_to_far_context_without_assessing_it(self):
        task = _task("same-case", 2, 9000, "An unrelated target region.")
        result = find_source(task, ["attribution", "current_court_response", "exception"])

        self.assertTrue(result["hits"])
        self.assertLessEqual(result["chars"], 1200)
        self.assertLessEqual(len(result["hits"]), 3)
        self.assertFalse(result["source_assessed"])
        self.assertEqual(result["search_calls"], 1)
        for hit in result["hits"]:
            self.assertEqual(hit["case_id"], "same-case")
            self.assertEqual(hit["source_hash"], task["request"]["source_hash"])
            self.assertEqual(hit["role"], "context")
            self.assertTrue(hit["navigation_id"].startswith("find-"))
            self.assertNotIn(hit["navigation_id"], task["catalog"]["atoms"])
        with self.assertRaises(ValueError):
            find_source(task, ["exception"], max_chars=1201)

    def test_context_expansion_keeps_same_source_and_adds_only_bounded_context_refs(self):
        manifest, _ = _locked_pilot_inputs()
        tasks = prepare(manifest, _ROOT / "outputs/source_store_v1",
                        _ROOT / "outputs/plan04_sentence_atoms_v1")
        candidate = None
        search = None
        for task in tasks:
            result = find_source(task, ["attribution", "current_court_response", "exception", "condition"])
            if result["hits"]:
                candidate, search = task, result
                break
        self.assertIsNotNone(candidate, "locked sources should provide at least one bounded context-search fixture")
        before = candidate["request"]
        expanded = expand_context(candidate, search["hits"])

        self.assertEqual(expanded["request"]["case_id"], before["case_id"])
        self.assertEqual(expanded["request"]["source_hash"], before["source_hash"])
        self.assertEqual([r for r in expanded["request"]["source_refs"] if r["role"] == "target"],
                         [r for r in before["source_refs"] if r["role"] == "target"])
        added = expanded["request"]["source_refs"][len(before["source_refs"]):]
        self.assertTrue(added)
        self.assertTrue(all(r["role"] == "context" and r["target_ids"] == [] for r in added))
        self.assertLessEqual(sum(r["end_char"]-r["start_char"] for r in added), 1200)
        self.assertEqual(len(expanded["catalog"]["atoms"]), len(set(expanded["catalog"]["atoms"])))

    def test_reading_state_is_a_copy_and_keeps_exact_interval_axes_separate(self):
        state = {
            "exposure_intervals": [{"start_char": 2, "end_char": 5}],
            "delivery_intervals": [{"start_char": 4, "end_char": 8, "role": "context"}],
            "assessment_intervals": [{"start_char": 6, "end_char": 8, "status": "assessed_without_AU"}],
            "unresolved_obligations": ["exception"],
        }
        snapshot = get_reading_state(state)
        snapshot["assessment_intervals"].clear()

        self.assertEqual(len(state["assessment_intervals"]), 1)
        self.assertEqual(state["delivery_intervals"][0]["role"], "context")
        self.assertEqual(state["exposure_intervals"][0], {"start_char": 2, "end_char": 5})
        self.assertEqual(state["unresolved_obligations"], ["exception"])

    def test_default_group_transport_recovers_lost_post_ack_without_redispatch(self):
        calls = {"post": 0, "get": 0, "jobs": None, "group_id": None}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _json(self, value):
                raw = json.dumps(value).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                calls["post"] += 1
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls["group_id"] = body["batch_id"]
                calls["jobs"] = body["jobs"]
                # Simulate a completed server admission whose ACK was lost.
                self.close_connection = True
                self.connection.shutdown(2)
                self.connection.close()

            def do_GET(self):
                calls["get"] += 1
                gid = urlsplit(self.path).path.rsplit("/", 1)[-1]
                self._json({
                    "group_id": gid,
                    "mode": "bulk",
                    "cursor": 0,
                    "next_cursor": 0,
                    "results": [],
                    "counts": {"total": len(calls["jobs"] or []), "queued": len(calls["jobs"] or []),
                               "running": 0, "completed": 0, "failed": 0, "interrupted": 0},
                })

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            cfg = {"url": f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                   "token": "synthetic-token", "timeout": 2}
            transport = GroupTransport(cfg)
            jobs = [{"job_id": "job-1", "payload": {"messages": []}}]
            ack, recovered = transport.admit("bulk", jobs)

            self.assertTrue(recovered)
            self.assertEqual(ack["group_id"], calls["group_id"])
            self.assertEqual(calls["post"], 1)
            self.assertEqual(calls["get"], 1)
            self.assertEqual(transport.stats["post_attempts"], 1)
            self.assertEqual(transport.stats["get_attempts"], 1)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_assessment_commits_exact_target_interval_and_keeps_context_delivered_only(self):
        manifest, _ = _locked_pilot_inputs()
        original = manifest["parent"]["parent"]["requests"][0]
        target = next(r for r in original["source_refs"] if r["role"] == "target")
        context = {"role": "context", "start_char": target["end_char"] + 35,
                   "end_char": target["end_char"] + 45,
                   "target_ids": []}
        effective = {**copy.deepcopy(original), "request_id": "selective-request-1",
                     "source_refs": [target, context], "atom_binding": {"atom_map_sha256": "b" * 64}}
        task = {"kind": "extraction", "phase": "initial", "effective": effective,
                "original_request": original, "estimate": 500,
                "capsule": {"job_id": "job-1"},
                "catalog": {"atoms": {
                    "evidence-target": {"atom_id": "evidence-target", "start_char": 8,
                                        "end_char": 22, "target_intersecting": True},
                    "evidence-context": {"atom_id": "evidence-context", "start_char": 35,
                                         "end_char": 45, "target_intersecting": False},
                }}}
        compact = {"coverage_status": "complete", "decision": "hard_negative",
                   "aus": [], "unresolved_reason": None}
        normalized = {"request": effective, "original_request": original,
                      "status": "protocol_verified", "compact_response": compact,
                      "response": {"target_results": []}, "receipt": {"usage": {
                          "input_tokens": 50, "output_tokens": 4, "total_tokens": 54}}}
        state = {"identity": {"run": "synthetic"}, "finished": False,
                 "stop_reason": None, "rows": {}, "delivery_intervals": [], "assessment_intervals": [],
                 "unresolved_obligations": [], "exposure_intervals": [{
                     "case_id": original["case_id"], "source_hash": original["source_hash"],
                     "start_char": target["start_char"], "end_char": target["end_char"],
                     "exposure_kind": "host_local_preview",
                     "source_assessed": False}], "groups": {}, "context_searches": {},
                 "warmup": None, "transport_history": [], "selections": {
                     original["case_id"]: {"initial": ["nav-"+digest(
                         [manifest["universe_sha256"], original["request_id"]])[:24]],
                         "replanned": []}}}
        job = {"job_id": "job-1", "status": "completed", "response": {
            "choices": [{"message": {"content": "synthetic raw response"}}]}}
        with patch("knowledge_base.pipeline_v1.selective_reading.runtime.normalize_receipt",
                   return_value=normalized):
            _commit(state, job, task)

        report = _report(manifest, "H", state, False, 1.0, 0.1, 1.1)
        self.assertEqual(state["assessment_intervals"], [{**target, "case_id": original["case_id"],
            "source_hash": original["source_hash"], "request_id": "selective-request-1",
            "original_request_id": original["request_id"], "state": "assessed_without_AU",
            "publication_status": "semantic_review_pending"}])
        self.assertTrue(any(x["role"] == "context" and x["assessment_implied"] is False
                            for x in state["delivery_intervals"]))
        self.assertEqual(report["selected_request_ids"], [original["request_id"]])
        self.assertEqual(report["assessed_request_ids"], [original["request_id"]])
        self.assertTrue(all(t["state"] == "not_assessed" for t in report["unselected_targets"]))
        self.assertFalse(report["selective_pass"])
        self.assertEqual(state["rows"]["job-1"]["provider_response"], job["response"])

    def test_budget_keeps_unknown_usage_visible_and_counts_reservations_and_planner(self):
        state = {
            "groups": {"g": {"reservations": [
                {"job_id": "p", "estimate": 400, "kind": "planner"},
                {"job_id": "e", "estimate": 600, "kind": "extraction"},
            ]}},
            "rows": {
                "p": {"receipt": {"usage": {"input_tokens": 30, "output_tokens": 5,
                                               "total_tokens": 35}}},
                "e": {"receipt": {"usage": None}},
            },
        }
        cost = _budget(state)
        self.assertEqual(cost["requests"], 2)
        self.assertEqual(cost["provider_attempts_reserved"], 2)
        self.assertEqual(cost["input_estimate_bytes"], 1000)
        self.assertEqual(cost["tokens"], {"input_tokens": 30, "output_tokens": 5,
                                            "total_tokens": 35})
        self.assertEqual(cost["usage_unavailable"], 1)
        self.assertEqual(cost["pending_or_unknown_requests"], 0)

    def test_protocol_verified_needs_split_is_reported_but_not_assessed(self):
        manifest, _ = _locked_pilot_inputs()
        original = manifest["parent"]["parent"]["requests"][0]
        rid = original["request_id"]
        nav = "nav-"+digest([manifest["universe_sha256"], rid])[:24]
        row = {"kind": "extraction", "original_request": original,
               "status": "protocol_verified", "compact_response": {
                   "coverage_status": "needs_split", "decision": "unresolved",
                   "unresolved_reason": "other", "aus": []},
               "response": {"target_results": [{"decision": "unresolved",
                                                  "authority_units": []}]},
               "receipt": {"usage": {"input_tokens": 9, "output_tokens": 3,
                                      "total_tokens": 12}}}
        state = {"identity": {}, "finished": False, "stop_reason": "partial",
                 "rows": {"job": row}, "groups": {},
                 "selections": {original["case_id"]: {"initial": [nav], "replanned": []}},
                 "exposure_intervals": [], "delivery_intervals": [],
                 "assessment_intervals": [], "unresolved_obligations": [{
                     "original_request_id": rid, "case_id": original["case_id"],
                     "flags": ["condition"], "status": "unresolved"}],
                 "context_searches": {}, "warmup": None, "transport_history": []}

        report = _report(manifest, "H", state, False, 1.0, 0.2, 1.2)
        self.assertEqual(report["protocol_verified_request_ids"], [rid])
        self.assertEqual(report["assessed_request_ids"], [])
        self.assertEqual(report["unselected_request_ids"], [
            q["request_id"] for q in manifest["parent"]["parent"]["requests"][1:]])
        self.assertFalse(report["selective_pass"])
        self.assertFalse(report["semantic_quality_claim"])

    def test_context_flag_stays_unresolved_and_public_ledger_keeps_only_latest_receipt(self):
        manifest, _ = _locked_pilot_inputs()
        original = manifest["parent"]["parent"]["requests"][0]
        rid = original["request_id"]
        nav = "nav-"+digest([manifest["universe_sha256"], rid])[:24]

        def extraction(request_id, phase, input_tokens):
            return {"kind": "extraction", "phase": phase,
                    "original_request": original, "request": {"request_id": request_id},
                    "status": "protocol_verified", "publication_status": "semantic_review_pending",
                    "compact_response": {"decision": "positive", "coverage_status": "complete",
                                         "aus": [{"needs_context": ["condition"]}]},
                    "response": {"target_results": []},
                    "receipt": {"usage": {"input_tokens": input_tokens, "output_tokens": 2,
                                           "total_tokens": input_tokens+2}}}

        state = {"identity": {}, "finished": False, "stop_reason": "partial",
                 "rows": {"job-1": extraction("initial-request", "initial", 10),
                          "job-2": extraction("context-request", "context", 20)},
                 "groups": {"g1": {"reservations": [{"job_id": "job-1", "estimate": 100}]},
                            "g2": {"reservations": [{"job_id": "job-2", "estimate": 200}]}},
                 "selections": {original["case_id"]: {"initial": [nav], "replanned": []}},
                 "exposure_intervals": [], "delivery_intervals": [],
                 "assessment_intervals": [], "unresolved_obligations": [{
                     "original_request_id": rid, "case_id": original["case_id"],
                     "flags": ["condition"], "status": "unresolved"}],
                 "context_searches": {}, "warmup": None, "transport_history": []}

        report = _report(manifest, "H", state, False, 1.0, 0.2, 1.2)
        self.assertEqual(report["protocol_verified_request_ids"], [rid])
        self.assertEqual(report["assessed_request_ids"], [])
        self.assertEqual(len(report["request_ledger"]), 1)
        self.assertEqual(report["request_ledger"][0]["phase"], "context")
        self.assertEqual(report["cost_ledger"]["requests"], 2)
        self.assertEqual(report["cost_ledger"]["tokens"]["total_tokens"], 34)
        self.assertEqual(report["unresolved_obligations"][0]["flags"], ["condition"])


if __name__ == "__main__":
    unittest.main()
