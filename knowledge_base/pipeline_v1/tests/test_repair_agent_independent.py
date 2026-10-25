"""Independent protocol probes for Plan12 task construction, tools, and runtime.

Fixtures are bounded agent-reviewed development evidence, not semantic gold.
Direct v1 tool-guard tests explicitly use legacy_offline; runtime fixtures use v2.
"""
from __future__ import annotations

import copy
import contextlib
import io
import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from knowledge_base.pipeline_v1.repair_agent.core import build_tasks
from knowledge_base.pipeline_v1.repair_agent import runtime
from knowledge_base.pipeline_v1.repair_agent.runtime import MockAdapter, fingerprint, run_arm
from knowledge_base.pipeline_v1.repair_agent.tools import RepairSession
from knowledge_base.pipeline_v1.au_candidate_store.core import _catalog
from knowledge_base.pipeline_v1.repair_agent.__main__ import main as repair_cli_main


ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "knowledge_base" / "pipeline_v1"
V6_RUN = PIPELINE / "outputs" / "plan11_semantic_v6_gate_20261011" / "run" / "run.json"
V6_REVIEW = PIPELINE / "outputs" / "plan11_semantic_v6_gate_20261011" / "run" / "review.bound.json"
EXACT_REVIEW = PIPELINE / "outputs" / "plan12_agent_repair_20261011" / "inputs" / "review.source_exact.v2.json"
WITNESS_AUDIT = PIPELINE / "outputs" / "plan12_agent_repair_20261011" / "inputs" / "witness_correction.audit.json"
SOURCE_STORE = PIPELINE / "outputs" / "source_store_v1"
ATOM_ROOT = PIPELINE / "outputs" / "plan04_sentence_atoms_v1"


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _canonical_hash(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _unique_target_quote(atom, target):
    start = max(atom["start_char"], target["start_char"])
    end = min(atom["end_char"], target["end_char"])
    text = atom["quote"][start - atom["start_char"]:end - atom["start_char"]]
    for size in range(1, len(text) + 1):
        for offset in range(0, len(text) - size + 1):
            quote = text[offset:offset + size]
            if quote.strip() and atom["quote"].count(quote) == 1:
                return quote
    raise AssertionError("fixture has no unique quote inside target intersection")


def _build(run, review):
    return build_tasks(run, review, SOURCE_STORE, ATOM_ROOT)


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_mutated_pair(folder, run, review):
    """Write a temporary synthetic pair and bind its sidecar to exact run bytes."""
    folder = Path(folder)
    run_path, review_path = folder / "mutated_run.json", folder / "mutated_review.json"
    _write_json(run_path, run)
    digest = hashlib.sha256(run_path.read_bytes()).hexdigest()
    rebound = copy.deepcopy(review)
    for entry in rebound["reviews"]:
        entry["run_sha256"] = digest
    _write_json(review_path, rebound)
    return build_tasks(run_path, review_path, SOURCE_STORE, ATOM_ROOT)


class _Plan12FixtureBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = (V6_RUN, V6_REVIEW, EXACT_REVIEW, WITNESS_AUDIT,
                    SOURCE_STORE / "source_store_manifest.json",
                    ATOM_ROOT / "sentence_atom_build_manifest.json")
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError("Plan11 v6 fixture prerequisites missing: " + ", ".join(missing))
        cls.run_data = _read_json(V6_RUN)
        cls.review = _read_json(V6_REVIEW)
        cls.valid_review = _read_json(EXACT_REVIEW)
        cls.witness_audit = _read_json(WITNESS_AUDIT)
        cls.fixture_temp = TemporaryDirectory()
        cls.valid_review_path = EXACT_REVIEW
        cls.manifest = _build(V6_RUN, EXACT_REVIEW)
        cls.tasks = {task["case_id"]: task for task in cls.manifest["tasks"]}

    @classmethod
    def tearDownClass(cls):
        cls.fixture_temp.cleanup()

    def task(self, case_id="013948"):
        return copy.deepcopy(self.tasks[case_id])


class Plan12IndependentTaskBuildTests(_Plan12FixtureBase):
    def test_groups_p2a_p2b_by_case_source_target_and_keeps_v6_subset_label(self):
        manifest = self.manifest

        self.assertEqual(manifest["task_count"], 4)
        self.assertEqual(manifest["task_case_ids"], ["011904", "013948", "045155", "099980"])
        self.assertEqual(manifest["task_workload"], "v6 output subset; not full KOS-5")
        self.assertIs(manifest["semantic_gold"], False)
        keys = [(task["case_id"], task["source_hash"], task["target_id"])
                for task in manifest["tasks"]]
        self.assertEqual(len(keys), len(set(keys)))

        by_case = {task["case_id"]: task for task in manifest["tasks"]}
        for case_id, task in by_case.items():
            self.assertTrue(task["raw_targets"])
            self.assertTrue(all(ref["case_id"] == case_id for ref in task["raw_targets"]))
            self.assertTrue(all(ref["source_hash"] == task["source_hash"]
                                for ref in task["raw_targets"]))
            arms = {alias["arm"] for proposal in task["original_proposals"]
                    for alias in proposal["aliases"]}
            if task["original_proposals"]:
                self.assertEqual(arms, {"P2a", "P2b"})

    def test_agent_review_errors_are_labeled_as_oracle_evidence(self):
        manifest = self.manifest
        errored = [task for task in manifest["tasks"] if task["semantic_errors"]]
        self.assertEqual({task["case_id"] for task in errored}, {"013948"})
        for task in errored:
            self.assertEqual(task["error_origin"], "agent_review")
            self.assertIs(task["semantic_gold"], False)

        controls = [task for task in manifest["tasks"] if not task["semantic_errors"]]
        self.assertEqual({task["case_id"] for task in controls},
                         {"011904", "045155", "099980"})
        self.assertEqual(self.tasks["011904"]["selection"], "correct_control")
        self.assertEqual(self.tasks["099980"]["selection"], "correct_control")
        self.assertEqual(self.tasks["045155"]["selection"], "correct_control")
        self.assertTrue(self.tasks["045155"]["review_oracle"])

    def test_original_v6_review_fails_closed_on_two_non_exact_source_quotes(self):
        with self.assertRaisesRegex(ValueError, "witness_quote_missing_or_nonunique"):
            _build(V6_RUN, V6_REVIEW)

    def test_corrected_sidecar_changes_only_the_two_witness_quotes(self):
        audit = self.witness_audit
        self.assertFalse(audit["historical_artifacts_modified"])
        self.assertFalse(audit["semantic_verdicts_changed"])
        self.assertEqual(len(audit["changes"]), 2)
        old = {item["request_id"]: item for item in self.review["reviews"]}
        new = {item["request_id"]: item for item in self.valid_review["reviews"]}
        self.assertEqual(set(old), set(new))
        for change in audit["changes"]:
            request_id = change["request_id"]
            before, after = copy.deepcopy(old[request_id]), copy.deepcopy(new[request_id])
            self.assertEqual(before["witnesses"], [change["old_witness"], old[request_id]["witnesses"][1]])
            self.assertEqual(after["witnesses"][0], change["new_witness"])
            before["witnesses"] = after["witnesses"]
            self.assertEqual(before, after)
            self.assertEqual(after["checks"], {"omission": "pass"})

    def test_task_build_does_not_mutate_v6_run_or_bound_review(self):
        run_bytes = V6_RUN.read_bytes()
        review_bytes = self.valid_review_path.read_bytes()

        self.assertIsNotNone(_build(V6_RUN, self.valid_review_path))

        self.assertEqual(V6_RUN.read_bytes(), run_bytes)
        self.assertEqual(self.valid_review_path.read_bytes(), review_bytes)

    def test_stale_review_run_hash_fails_closed(self):
        review = copy.deepcopy(self.valid_review)
        review["reviews"][0]["run_sha256"] = "0" * 64
        review_path = Path(self.fixture_temp.name) / "stale_review.json"
        _write_json(review_path, review)

        with self.assertRaisesRegex(ValueError, "stale_review_binding"):
            _build(V6_RUN, review_path)

    def test_foreign_case_source_ref_fails_even_when_review_is_rebound(self):
        run = copy.deepcopy(self.run_data)
        review = copy.deepcopy(self.valid_review)
        request = run["request_ledger"][0]["request"]
        request["source_refs"][0]["case_id"] = "013948" if request["case_id"] != "013948" else "011904"

        with self.assertRaisesRegex(ValueError, "span_identity_mismatch"):
            with TemporaryDirectory() as folder:
                _build_mutated_pair(folder, run, review)

    def test_nonunique_source_witness_quote_fails_closed(self):
        run = copy.deepcopy(self.run_data)
        review = copy.deepcopy(self.valid_review)
        entry = next(item for item in review["reviews"]
                     if item["review_type"] == "au" and item.get("primary_proposition"))
        request = next(row["request"] for row in run["request_ledger"]
                       if row["request"]["request_id"] == entry["request_id"])
        atoms, invalid, _ = _catalog(request, SOURCE_STORE, ATOM_ROOT)
        self.assertFalse(invalid)
        atom = atoms[entry["primary_proposition"]["atom_id"]]
        repeated = next(char for char in atom["quote"] if char.isalnum() and atom["quote"].count(char) > 1)
        entry["primary_proposition"]["quote"] = repeated

        with self.assertRaisesRegex(ValueError, "witness_quote_missing_or_nonunique"):
            review_path = Path(self.fixture_temp.name) / "nonunique_review.json"
            _write_json(review_path, review)
            _build(V6_RUN, review_path)

class Plan12IndependentToolTests(_Plan12FixtureBase):
    def _target_atom_and_primary(self, task):
        target = task["raw_targets"][0]
        atom = next(a for a in task["supplied_atom_catalog"]
                    if a["start_char"] < target["end_char"]
                    and target["start_char"] < a["end_char"])
        return atom, {"atom_id": atom["atom_id"],
                      "quote": _unique_target_quote(atom, target)}

    def _submit_args(self, task, *, replacement=None):
        target_atom, primary = self._target_atom_and_primary(task)
        decisions = []
        for proposal in task["original_proposals"]:
            if proposal["proposal_id"] != replacement:
                decisions.append({"proposal_id": proposal["proposal_id"], "action": "unresolved",
                                  "reason": "independent protocol probe", "replacements": [],
                                  "primary_proposition": None})
                continue
            au = copy.deepcopy(proposal["proposal"])
            au["evidence_ref_ids"] = [target_atom["atom_id"]]
            replacements = []
            for suffix in ("one", "two"):
                candidate = copy.deepcopy(au)
                candidate["claim"] = "Synthetic bounded replacement " + suffix
                replacements.append({"au": candidate, "primary_proposition": primary})
            decisions.append({"proposal_id": proposal["proposal_id"], "action": "replace",
                              "reason": "independent one-to-many protocol probe",
                              "replacements": replacements, "primary_proposition": None})
        return {"task_id": task["task_id"], "decisions": decisions}, target_atom, primary

    def test_open_span_is_exact_and_rejects_out_of_atom_offsets(self):
        task = self.task()
        session = RepairSession(task, "R2", legacy_offline=True)
        atom = task["supplied_atom_catalog"][0]
        valid = session.call_tool("open_span", {"atom_id": atom["atom_id"]})
        self.assertTrue(valid["ok"])
        self.assertEqual(valid["result"]["quote"], atom["quote"])
        self.assertEqual(valid["result"]["source_hash"], task["source_hash"])
        self.assertEqual(valid["result"]["case_id"], task["case_id"])

        invalid = session.call_tool("open_span", {
            "atom_id": atom["atom_id"], "start_char": atom["start_char"],
            "end_char": atom["end_char"] + 1})
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error"]["code"], "span_outside_allowed_atom")

    def test_context_only_primary_is_rejected_even_when_atom_was_read(self):
        task = self.task()
        session = RepairSession(task, "R2", legacy_offline=True)
        proposal = task["original_proposals"][0]
        target = task["raw_targets"][0]
        context_atom = next(a for a in task["supplied_atom_catalog"]
                            if not a["target_intersecting"]
                            and a["end_char"] <= target["start_char"])
        quote = context_atom["quote"]
        au = copy.deepcopy(proposal["proposal"])
        au["evidence_ref_ids"] = [context_atom["atom_id"]]
        decision = {"proposal_id": proposal["proposal_id"], "action": "replace",
                    "reason": "context-only ownership negative control",
                    "replacements": [{"au": au, "primary_proposition": {
                        "atom_id": context_atom["atom_id"], "quote": quote}}],
                    "primary_proposition": None}
        args = {"task_id": task["task_id"], "decisions": [
            decision if p["proposal_id"] == proposal["proposal_id"] else {
                "proposal_id": p["proposal_id"], "action": "unresolved",
                "reason": "preserve unrelated proposal", "replacements": [],
                "primary_proposition": None}
            for p in task["original_proposals"]]}

        event = session.call_tool("submit_revision", args)
        self.assertFalse(event["ok"])
        self.assertEqual(event["error"]["code"], "primary_quote_outside_raw_target")
        self.assertIsNone(session.state["revision"])

    def test_one_original_proposal_can_be_replaced_by_two_pending_aus(self):
        task = self.task()
        session = RepairSession(task, "R2", legacy_offline=True)
        proposal_id = task["original_proposals"][0]["proposal_id"]
        args, _, _ = self._submit_args(task, replacement=proposal_id)

        event = session.call_tool("submit_revision", args)

        self.assertTrue(event["ok"], event.get("error"))
        revision = event["result"]
        verified = [item for item in revision["verified_replacements"]
                    if item["original_proposal_id"] == proposal_id]
        self.assertEqual(len(verified), 2)
        self.assertEqual(revision["semantic_status"], "semantic_review_pending")
        self.assertFalse(any(item["accepted_semantic"] for item in verified))
        self.assertTrue(all("start_char" not in item["au"] and "end_char" not in item["au"]
                            for item in verified))

    def test_reads_and_revision_do_not_satisfy_context_obligation_automatically(self):
        task = self.task("011904")
        obligation = {"obligation_id": "obligation-independent-probe",
                      "task_id": task["task_id"], "target_id": task["target_id"],
                      "obligation_type": "condition", "requested_direction_or_ref": "after",
                      "reason": "synthetic protocol fixture", "producer": "independent_test",
                      "run_id": "independent-run", "status": "pending", "searched_spans": [],
                      "stop_reason": None, "review_confirmation": None}
        task["obligations"].append(obligation)
        session = RepairSession(task, "R2", legacy_offline=True)
        atom = task["supplied_atom_catalog"][0]

        read_event = session.call_tool("open_span", {"atom_id": atom["atom_id"]})
        args, _, _ = self._submit_args(task)
        revision_event = session.call_tool("submit_revision", args)

        self.assertTrue(read_event["ok"])
        self.assertTrue(revision_event["ok"], revision_event.get("error"))
        current = session.state["obligations"][0]
        self.assertEqual(current["status"], "pending")
        self.assertTrue(current["searched_spans"])
        self.assertIsNone(current["review_confirmation"])

    def test_obligation_requires_fresh_explicit_review_and_witness(self):
        task = self.task("011904")
        task["obligations"].append({"obligation_id": "obligation-independent-probe",
            "task_id": task["task_id"], "target_id": task["target_id"],
            "obligation_type": "condition", "requested_direction_or_ref": "after",
            "reason": "synthetic protocol fixture", "producer": "independent_test",
            "run_id": "independent-run", "status": "pending", "searched_spans": [],
            "stop_reason": None, "review_confirmation": None})
        session = RepairSession(task, "R2", legacy_offline=True)
        args, atom, primary = self._submit_args(task)
        revision_event = session.call_tool("submit_revision", args)
        self.assertTrue(revision_event["ok"], revision_event.get("error"))
        revision_digest = _canonical_hash(revision_event["result"])
        base = {"obligation_id": "obligation-independent-probe",
                "revision_sha256": revision_digest, "reviewer_id": "independent-test-reviewer",
                "reviewed": True, "witnesses": [primary], "reason": "explicit protocol fixture review"}

        stale = dict(base, revision_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "stale_obligation_review"):
            session.confirm_obligation(stale)
        no_witness = dict(base, witnesses=[])
        with self.assertRaisesRegex(ValueError, "obligation_review_witness_required"):
            session.confirm_obligation(no_witness)

        session.confirm_obligation(base)
        self.assertEqual(session.state["obligations"][0]["status"], "satisfied")
        self.assertEqual(session.state["obligations"][0]["review_confirmation"], base)

    def test_failed_tool_call_is_isolated_and_consumes_tool_budget(self):
        first, second = RepairSession(self.task(), "R2", legacy_offline=True), RepairSession(self.task("011904"), "R2", legacy_offline=True)
        failed = first.call_tool("open_span", {"atom_id": "foreign-or-unknown-atom"})
        atom = second.task["supplied_atom_catalog"][0]
        succeeded = second.call_tool("open_span", {"atom_id": atom["atom_id"]})

        self.assertFalse(failed["ok"])
        self.assertEqual(first.state["tool_count"], 1)
        self.assertTrue(succeeded["ok"])
        self.assertEqual(second.state["tool_count"], 1)

    def test_r0_cannot_submit_revision(self):
        session = RepairSession(self.task(), "R0", legacy_offline=True)
        event = session.call_tool("submit_revision", {})

        self.assertFalse(event["ok"])
        self.assertEqual(event["error"]["code"], "task_closed")
        self.assertIsNone(session.state["revision"])

    def test_expansion_and_failed_tool_calls_obey_per_task_caps(self):
        session = RepairSession(self.task(), "R2", legacy_offline=True)
        first = session.call_tool("expand_context", {"direction": "before", "reason": "bounded probe"})
        second = session.call_tool("expand_context", {"direction": "after", "reason": "second expansion probe"})
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(second["error"]["code"], "expansion_budget_exhausted")
        self.assertEqual(session.state["expansion_count"], 1)

        quota = RepairSession(self.task(), "R2", legacy_offline=True)
        for index in range(8):
            event = quota.call_tool("unknown_tool", {"probe": index})
            self.assertFalse(event["ok"])
        exhausted = quota.call_tool("get_related_aus", {})
        self.assertFalse(exhausted["ok"])
        self.assertEqual(exhausted["error"]["code"], "tool_budget_exhausted")
        self.assertEqual(quota.state["tool_count"], 8)
        self.assertEqual(len(quota.state["events"]), 9)


class Plan12IndependentRuntimeTests(_Plan12FixtureBase):
    def _unresolved_submit_output(self, task):
        decisions = [{"proposal_id": proposal["proposal_id"], "verdict": "uncertain",
                      "reason": "offline provider-cap test"}
                     for proposal in task["original_proposals"]]
        return {"tool_calls": [{"name": "submit_revision", "arguments": {
            "task_id": task["task_id"], "decisions": decisions}}]}

    def test_mock_r0_is_baseline_only_and_never_calls_adapter(self):
        adapter = MockAdapter()
        with TemporaryDirectory() as folder:
            report = run_arm(self.manifest, "R0", folder, adapter)

        self.assertEqual(adapter.calls, 0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["attempts"], [])
        self.assertTrue(all(task["status"] == "baseline_no_repair" for task in report["tasks"]))
        self.assertIsNone(report["semantic_metrics"])

    def test_task_selection_rejects_unknown_duplicate_and_empty_ids(self):
        valid_id = self.manifest["tasks"][0]["task_id"]
        for task_ids in ([], ["unknown-task"], [valid_id, valid_id]):
            with self.subTest(task_ids=task_ids):
                with self.assertRaisesRegex(ValueError, "invalid_task_selection"):
                    runtime.preflight(self.manifest, "R2", task_ids)
                adapter = MockAdapter()
                with TemporaryDirectory() as folder:
                    with self.assertRaisesRegex(ValueError, "invalid_task_selection"):
                        run_arm(self.manifest, "R1", folder, adapter, task_ids)
                self.assertEqual(adapter.calls, 0)

    def test_selection_scopes_preflight_budget_run_key_and_report(self):
        task_ids = [task["task_id"] for task in self.manifest["tasks"][:2]]
        full_preflight = runtime.preflight(self.manifest, "R2")
        selected_preflight = runtime.preflight(self.manifest, "R2", [task_ids[0]])
        # Revised preflight reserves both R2 turns, not just the first.
        self.assertEqual(full_preflight["status"], "budget_risk")
        self.assertGreater(full_preflight["worst_case_reserved_tokens"], runtime.POLICY["total_tokens"])
        self.assertEqual(full_preflight["max_attempts_required"], 2 * sum(bool(task["original_proposals"]) for task in self.manifest["tasks"]))
        self.assertEqual(selected_preflight["status"], "pass")
        self.assertEqual(selected_preflight["max_attempts_required"], 2)
        self.assertEqual(selected_preflight["selected_task_ids"], [task_ids[0]])
        self.assertEqual([row["task_id"] for row in selected_preflight["tasks"]], [task_ids[0]])

        with TemporaryDirectory() as folder:
            one_adapter = MockAdapter()
            one = run_arm(self.manifest, "R1", folder, one_adapter, [task_ids[0]])
            two_adapter = MockAdapter()
            two = run_arm(self.manifest, "R1", folder, two_adapter, task_ids)
            cached_adapter = MockAdapter()
            cached = run_arm(self.manifest, "R1", folder, cached_adapter, [task_ids[0]])

        expected_cases = sorted(task["case_id"] for task in self.manifest["tasks"][:2])
        self.assertEqual(one["selected_task_ids"], [task_ids[0]])
        self.assertEqual(one["task_case_ids"], [self.manifest["tasks"][0]["case_id"]])
        self.assertEqual(two["selected_task_ids"], task_ids)
        self.assertEqual(two["task_case_ids"], expected_cases)
        self.assertEqual({row["task_id"] for row in two["tasks"]}, set(task_ids))
        self.assertEqual({attempt["task_id"] for attempt in two["attempts"]}, set(task_ids))
        self.assertEqual(two["cost_summary"]["source_model_attempts"], len(two["attempts"]))
        self.assertNotEqual(one["run_key"], two["run_key"])
        self.assertNotEqual(one["task_selection_sha256"], two["task_selection_sha256"])
        self.assertEqual(cached["run_key"], one["run_key"])
        self.assertEqual(cached_adapter.calls, 0)

    def test_cli_task_id_selection_preflight_report_and_invalid_ids(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            manifest_path = folder / "manifest.json"
            _write_json(manifest_path, self.manifest)
            task = self.manifest["tasks"][0]
            task_id = task["task_id"]

            preflight_root = folder / "preflight"
            args = ["repair-agent", "preflight", "--manifest", str(manifest_path),
                    "--output-root", str(preflight_root), "--arm", "R2", "--task-id", task_id]
            with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(repair_cli_main(), 0)
            preflight_report = _read_json(preflight_root / "preflight-R2.json")
            self.assertEqual(preflight_report["status"], "pass")
            self.assertEqual(preflight_report["max_attempts_required"], 2)
            self.assertEqual(preflight_report["selected_task_ids"], [task_id])

            run_root = folder / "run"
            args = ["repair-agent", "offline-run", "--manifest", str(manifest_path),
                    "--output-root", str(run_root), "--arm", "R0", "--task-id", task_id]
            with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(repair_cli_main(), 0)
            summary = _read_json(run_root / "summary-R0.json")
            run_report = _read_json(Path(summary["reports"][0]["output_root"]) / "run.json")
            self.assertEqual(run_report["selected_task_ids"], [task_id])
            self.assertEqual(run_report["task_case_ids"], [task["case_id"]])
            self.assertEqual([row["task_id"] for row in run_report["tasks"]], [task_id])

            for name, selected_ids in (("unknown", ["unknown-task"]),
                                       ("duplicate", [task_id, task_id])):
                error_root = folder / name
                args = ["repair-agent", "offline-run", "--manifest", str(manifest_path),
                        "--output-root", str(error_root), "--arm", "R0"]
                for selected_id in selected_ids:
                    args.extend(["--task-id", selected_id])
                with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(repair_cli_main(), 2)
                self.assertEqual(_read_json(error_root / "error.json")["code"], "invalid_task_selection")

    def test_mock_r2_obeys_attempt_and_tool_caps_and_caches_task_results(self):
        with TemporaryDirectory() as folder:
            adapter = MockAdapter()
            first = run_arm(self.manifest, "R2", folder, adapter)
            self.assertLessEqual(len(first["attempts"]), 8)
            self.assertTrue(all(record["model_turns"] <= 2 for record in first["tasks"]))
            self.assertTrue(all(record["session"]["tool_count"] <= 8 for record in first["tasks"]))
            self.assertTrue(all(record["session"]["expansion_count"] <= 1 for record in first["tasks"]))
            self.assertEqual(first["semantic_status"], "semantic_review_pending")
            self.assertGreater(adapter.calls, 0)

            replay_adapter = MockAdapter()
            replay = run_arm(self.manifest, "R2", folder, replay_adapter)

        self.assertEqual(replay_adapter.calls, 0)
        self.assertEqual(replay["attempts"], first["attempts"])
        self.assertEqual(replay["status"], first["status"])

    def test_mock_provider_failure_is_counted_without_claiming_provider_usage(self):
        task_id = self.manifest["tasks"][0]["task_id"]
        adapter = MockAdapter({task_id: [{"fault": "synthetic transport failure"}]})
        with TemporaryDirectory() as folder:
            report = run_arm(self.manifest, "R1", folder, adapter)

        attempt = next(item for item in report["attempts"] if item["task_id"] == task_id)
        self.assertEqual(attempt["status"], "provider_error")
        self.assertGreater(attempt["charged_tokens"], 0)
        self.assertEqual(attempt["usage_state"], "mock_not_provider")
        self.assertIsNone(attempt["provider_usage"])
        self.assertIn(report["tasks"][0]["status"], {"provider_error", "provider_stopped"})

    def test_known_per_request_usage_violation_stops_before_tools_and_next_call(self):
        task = self.manifest["tasks"][0]
        cases = (
            {"prompt_tokens": runtime.POLICY["input_tokens"] + 1,
             "completion_tokens": 1,
             "total_tokens": runtime.POLICY["input_tokens"] + 2},
            {"prompt_tokens": 1,
             "completion_tokens": runtime.POLICY["output_tokens"] + 1,
             "total_tokens": runtime.POLICY["output_tokens"] + 2},
        )
        for usage in cases:
            with self.subTest(usage=usage), TemporaryDirectory() as folder:
                class UsageAdapter:
                    is_mock = False
                    identity = {"kind": "offline_usage_stub", "scenario": str(usage)}

                    def __init__(self):
                        self.calls = []

                    def __call__(self, messages, *, task, turn, arm, attempt_id):
                        self.calls.append((task["task_id"], turn))
                        return {"output": {"schema_version": "repair-selection-v1", **self_outer._unresolved_submit_output(task)},
                                "provider_usage": usage}

                self_outer = self
                adapter = UsageAdapter()
                report = run_arm(self.manifest, "R1", folder, adapter)

                self.assertEqual(report["status"], "incomplete")
                self.assertEqual(adapter.calls, [(task["task_id"], 1)])
                record = next(item for item in report["tasks"] if item["task_id"] == task["task_id"])
                self.assertIsNone(record["session"]["revision"])
                self.assertEqual(record["session"]["events"], [])

    def test_actual_total_usage_over_arm_budget_stops_before_next_submission(self):
        usage = {"prompt_tokens": 5900, "completion_tokens": 1100, "total_tokens": 7000}
        owner = self

        class UsageAdapter:
            is_mock = False
            identity = {"kind": "offline_usage_stub", "scenario": "cumulative_total_cap"}

            def __init__(self):
                self.calls = []

            def __call__(self, messages, *, task, turn, arm, attempt_id):
                self.calls.append((task["task_id"], turn))
                return {"output": {"schema_version": "repair-selection-v1", **owner._unresolved_submit_output(task)},
                        "provider_usage": usage}

        adapter = UsageAdapter()
        # Lower only the arm-wide test ceiling so two valid per-request usage
        # receipts cross it; no provider or endpoint is involved.
        # Selection catalog increases reservation: admit the second request,
        # then its actual 7000-token receipt must cross this test-only ceiling.
        with patch.dict(runtime.POLICY, {"total_tokens": 13900}):
            manifest = build_tasks(V6_RUN, EXACT_REVIEW, SOURCE_STORE, ATOM_ROOT)
            with TemporaryDirectory() as folder:
                report = run_arm(manifest, "R1", folder, adapter)

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(len(adapter.calls), 2)
        self.assertEqual(report["attempts"][-1]["provider_usage"], usage)
        overrun_task = next(item for item in report["tasks"]
                            if item["task_id"] == adapter.calls[-1][0])
        self.assertIsNone(overrun_task["session"]["revision"])

    def test_raw_returned_inflight_checkpoint_resumes_incomplete_without_redispatch(self):
        first_task = self.manifest["tasks"][0]
        interrupted_adapter = MockAdapter()
        persist = runtime._persist

        def crash_after_raw_return(path, state):
            persist(path, state)
            if state.get("attempts") and state["attempts"][-1].get("status") == "returned":
                raise RuntimeError("synthetic crash after raw response checkpoint")

        with TemporaryDirectory() as folder:
            with patch.object(runtime, "_persist", side_effect=crash_after_raw_return):
                with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
                    run_arm(self.manifest, "R1", folder, interrupted_adapter)

            resume_adapter = MockAdapter()
            report = run_arm(self.manifest, "R1", folder, resume_adapter)

        self.assertEqual(report["status"], "incomplete")
        first_record = next(item for item in report["tasks"] if item["task_id"] == first_task["task_id"])
        self.assertEqual(first_record["status"], "interrupted_requires_recovery")
        first_attempts = [item for item in report["attempts"] if item["task_id"] == first_task["task_id"]]
        self.assertEqual(len(first_attempts), 1)
        self.assertEqual(first_attempts[0]["status"], "returned")
        self.assertLessEqual(resume_adapter.calls, len(self.manifest["tasks"]) - 1)

    def test_technical_failure_in_one_task_does_not_skip_later_tasks(self):
        first_id = self.manifest["tasks"][0]["task_id"]
        adapter = MockAdapter({first_id: [{"tool_calls": [{"name": "not_a_tool", "arguments": {}}]}]})
        with TemporaryDirectory() as folder:
            # Isolate task-local failure from full-workload budget exhaustion.
            selected = [task["task_id"] for task in self.manifest["tasks"][:2]]
            report = run_arm(self.manifest, "R1", folder, adapter, selected)

        by_id = {task["task_id"]: task for task in report["tasks"]}
        self.assertEqual(by_id[first_id]["status"], "technical_invalid")
        later = [task for task in report["tasks"] if task["task_id"] != first_id]
        self.assertTrue(later)
        self.assertTrue(all(task["status"] == "revision_submitted" for task in later))

    def test_fingerprint_changes_with_context_arm_prompt_model_and_adapter(self):
        task = self.task()
        identity = {"kind": "mock", "script_sha256": "a" * 64}
        baseline = fingerprint(task, "R2", identity)

        changed_context = copy.deepcopy(task)
        changed_context["supplied_atom_catalog"][0]["quote"] += " context-change"
        self.assertNotEqual(baseline, fingerprint(changed_context, "R2", identity))
        self.assertNotEqual(baseline, fingerprint(task, "R1", identity))
        self.assertNotEqual(baseline, fingerprint(task, "R2", {"kind": "mock", "script_sha256": "b" * 64}))
        with patch.object(runtime, "PROMPT", runtime.PROMPT + " prompt-version-change"):
            self.assertNotEqual(baseline, fingerprint(task, "R2", identity))
        with patch.object(runtime, "MODEL", runtime.MODEL + "-test"):
            self.assertNotEqual(baseline, fingerprint(task, "R2", identity))


if __name__ == "__main__":
    unittest.main()
