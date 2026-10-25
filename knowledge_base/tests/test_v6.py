import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from knowledge_base.pipeline_v6 import build_case, _repair_target_matches
from knowledge_base.prompts_v6 import (CLASSIFICATION_REPAIR, FINALIZER, READER,
                                       SELECTION_REPAIR, PROTOCOL_REPAIR)
from knowledge_base.source import load_source, source_handles, source_structure
from knowledge_base.state_v6 import apply_operations_independently, initial_state


def config():
    return {"reader": "reader", "repair": "repair"}


def source_ref(source_id, attribution="current_court", role="primary"):
    return {"source_id": source_id, "role": role, "attribution": attribution}


def brief_item(source_id, kind="facts", attribution="current_court"):
    return {"kind": kind, "source_refs": [source_ref(source_id, attribution)]}


def add_brief(source_id, *, kind="facts", attribution="current_court", reason="grounded"):
    return {"op": "add", "collection": "brief",
            "item": brief_item(source_id, kind, attribution), "reason": reason}


def reader_response(operations=None):
    return {"action": "finalize", "reason": "draft ready", "read_window_ids": [],
            "operations": operations or [], "open_questions": []}


def repair_response(operations=None):
    return {"action": "complete", "reason": "repair complete", "read_window_ids": [],
            "operations": operations or [], "open_questions": []}


def final_response(operations=None):
    return {"reason": "final state ready", "operations": operations or [],
            "open_questions": []}


class V6StateTests(unittest.TestCase):
    def test_protocol_repair_may_correct_revision_but_not_item_identity(self):
        original = {"op": "defer", "id": "045155:aus:004", "revision": 2,
                    "reason": "duplicate"}
        corrected = {**original, "revision": 1}
        self.assertTrue(_repair_target_matches(original, corrected))
        self.assertFalse(_repair_target_matches(original, {**corrected,
            "id": "045155:aus:000"}))
        self.assertFalse(_repair_target_matches(original, {**corrected,
            "op": "remove"}))

    def test_exact_duplicate_is_audited_noop_after_full_validation(self):
        _, units = source_structure("Court decides.", "a" * 64)
        source_map = {unit["source_id"]: unit for unit in units}
        stable_to_handle, alias_to_stable = source_handles(units)
        handle = stable_to_handle[next(unit["source_id"] for unit in units
                                       if unit["unit_type"] == "sentence")]
        state, applied, rejected, noops = apply_operations_independently(
            initial_state(), [add_brief(handle)], set(source_map), source_map, "a" * 64,
            "1", aliases=alias_to_stable, stable_to_handle=stable_to_handle,
            allowed_target_ids=set())
        self.assertEqual((len(applied), len(rejected), len(noops)), (1, 0, 0))
        original = json.loads(json.dumps(state))
        state, applied, rejected, noops = apply_operations_independently(
            state, [add_brief(handle)], set(source_map), source_map, "a" * 64,
            "1", aliases=alias_to_stable, stable_to_handle=stable_to_handle,
            allowed_target_ids=set(state["items"]))
        self.assertEqual(state, original)
        self.assertFalse(applied or rejected)
        self.assertEqual(noops[0]["duplicate_of"], "1:brief:000")
        self.assertEqual(noops[0]["duplicate_revision"], 1)
        _, _, rejected, noops = apply_operations_independently(
            state, [add_brief(handle) | {"item": brief_item(handle) | {"id": "invented"}}],
            set(source_map), source_map, "a" * 64, "1", aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids=set(state["items"]))
        self.assertEqual(rejected[0]["error_code"], "unexpected_or_missing_item_fields")
        self.assertFalse(noops)
        _, applied, rejected, noops = apply_operations_independently(
            state, [add_brief(handle, attribution="party")], set(source_map),
            source_map, "a" * 64, "1", aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids=set(state["items"]))
        self.assertEqual((len(applied), len(rejected), len(noops)), (1, 0, 0))

    def test_defer_restore_remove_and_revision_history(self):
        text = "Court decides."
        _, units = source_structure(text, "a" * 64)
        source_map = {unit["source_id"]: unit for unit in units}
        stable_to_handle, alias_to_stable = source_handles(units)
        sentence = next(unit for unit in units if unit["unit_type"] == "sentence")
        handle = stable_to_handle[sentence["source_id"]]
        state, events, rejected, _ = apply_operations_independently(
            initial_state(), [add_brief(handle)], set(source_map), source_map, "a" * 64,
            "1", aliases=alias_to_stable, stable_to_handle=stable_to_handle,
            allowed_target_ids=set())
        self.assertFalse(rejected)
        item_id = events[0]["id"]
        state, _, rejected, _ = apply_operations_independently(state, [
            {"op": "defer", "id": item_id, "revision": 1, "reason": "speaker unclear"}],
            set(source_map), source_map, "a" * 64, "1", aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids={item_id})
        self.assertFalse(rejected)
        self.assertEqual(state["items"][item_id]["status"], "deferred")
        state, _, rejected, _ = apply_operations_independently(state, [
            {"op": "restore", "id": item_id, "revision": 2, "reason": "source resolves it"}],
            set(source_map), source_map, "a" * 64, "1", aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids={item_id})
        self.assertFalse(rejected)
        state, _, rejected, _ = apply_operations_independently(state, [
            {"op": "remove", "id": item_id, "revision": 3, "reason": "duplicate"}],
            set(source_map), source_map, "a" * 64, "1", aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids={item_id})
        self.assertFalse(rejected)
        self.assertEqual(state["items"][item_id]["status"], "deleted")
        self.assertEqual([event["op"] for event in state["history"]],
                         ["add", "defer", "restore", "remove"])

    def test_empty_operations_do_not_drop_items_and_stale_revision_is_rejected(self):
        text = "Court decides."
        _, units = source_structure(text, "b" * 64)
        source_map = {unit["source_id"]: unit for unit in units}
        stable_to_handle, alias_to_stable = source_handles(units)
        handle = stable_to_handle[next(unit["source_id"] for unit in units
                                       if unit["unit_type"] == "sentence")]
        state, events, _, _ = apply_operations_independently(
            initial_state(), [add_brief(handle)], set(source_map), source_map, "b" * 64,
            "1", aliases=alias_to_stable, stable_to_handle=stable_to_handle,
            allowed_target_ids=set())
        item_id = events[0]["id"]
        unchanged, _, rejected, _ = apply_operations_independently(
            state, [], set(source_map), source_map, "b" * 64, "1",
            aliases=alias_to_stable, stable_to_handle=stable_to_handle,
            allowed_target_ids={item_id})
        self.assertFalse(rejected)
        self.assertEqual(unchanged, state)
        _, _, rejected, _ = apply_operations_independently(state, [{"op": "defer",
            "id": item_id, "revision": 99, "reason": "wrong revision"}], set(source_map),
            source_map, "b" * 64, "1", aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids={item_id})
        self.assertEqual(rejected[0]["error_code"], "stale_or_unknown_target")


class V6PipelineTests(unittest.TestCase):
    def _row(self, root, text="Court decides the appeal."):
        source = root / "source.txt"
        source.write_text(text, encoding="utf-8")
        return {"case_id": "013948", "source": str(source),
                "source_hash": load_source(source)[1]}

    def test_v6_runs_repairs_without_verifier_and_marks_quality_not_evaluated(self):
        calls = []

        class Fake:
            def complete(self, model, system, payload, **kwargs):
                calls.append(system)
                if system == READER:
                    sentence = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    return reader_response([add_brief(sentence, kind="disposition")])
                if system in {SELECTION_REPAIR, CLASSIFICATION_REPAIR}:
                    return repair_response()
                if system == FINALIZER:
                    return final_response()
                raise AssertionError("unexpected prompt")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "pilot_v6/calibration/013948"
            result = build_case(self._row(root), Fake(), config(), 100, 1, output)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["protocol_status"], "valid")
            self.assertEqual(result["quality_status"], "not_evaluated")
            self.assertEqual(result["output_status"], "nonempty")
            self.assertEqual(len(result["brief"]), 1)
            self.assertEqual(result["brief"][0]["excerpts"][0]["text"],
                             "Court decides the appeal.")
            self.assertEqual(calls, [READER, SELECTION_REPAIR,
                                     CLASSIFICATION_REPAIR, FINALIZER])
            self.assertEqual(result["snapshots"], ["draft_after_reading",
                "after_selection_repair", "after_classification_repair", "final"])

    def test_selection_repair_reads_before_selecting_and_has_one_continuation(self):
        selection_calls = 0

        class Fake:
            def complete(self, model, system, payload, **kwargs):
                nonlocal selection_calls
                if system == READER:
                    return reader_response()
                if system == SELECTION_REPAIR:
                    selection_calls += 1
                    if selection_calls == 1:
                        return {"action": "read", "reason": "inspect middle reasoning",
                                "read_window_ids": payload["unread_window_ids"][:1],
                                "operations": [], "open_questions": []}
                    middle = next(sentence for paragraph in payload["opened_sources"]
                                  for sentence in paragraph["sentences"]
                                  if "Middle" in sentence["text"])
                    return repair_response([add_brief(middle["source_id"], kind="issues")])
                if system == CLASSIFICATION_REPAIR:
                    return repair_response()
                if system == FINALIZER:
                    return final_response()
                raise AssertionError("unexpected prompt")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self._row(root, "Start.\n\nMiddle issue?\n\nEnd.")
            result = build_case(row, Fake(), config(), 8, 1,
                                root / "pilot_v6/calibration/013948")
            self.assertEqual(selection_calls, 2)
            self.assertEqual(result["brief"][0]["kind"], "issues")

    def test_protocol_repair_can_change_coupled_action_and_window_fields(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return reader_response()
                if system == SELECTION_REPAIR:
                    return {"action": "read", "reason": "revisit source",
                            "read_window_ids": [0], "operations": [],
                            "open_questions": []}
                if system == PROTOCOL_REPAIR:
                    self.allowed = payload["allowed_control_patch_fields"]
                    return {"control_patch": {"action": "complete",
                                              "read_window_ids": []}, "repairs": []}
                if system == CLASSIFICATION_REPAIR:
                    return repair_response()
                if system == FINALIZER:
                    return final_response()
                raise AssertionError("unexpected prompt")

        fake = Fake()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build_case(self._row(root), fake, config(), 100, 1,
                                root / "pilot_v6/calibration/013948")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["protocol_status"], "valid")
            self.assertEqual(fake.allowed, ["action", "read_window_ids"])
            self.assertEqual(result["protocol_errors"][0]["status"], "resolved")

    def test_classification_repair_receives_conflict_matrix_and_can_fix_it(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    sentence = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    return reader_response([
                        add_brief(sentence, attribution="current_court", reason="first reading"),
                        add_brief(sentence, kind="posture", attribution="party",
                                  reason="conflicting reading")])
                if system == SELECTION_REPAIR:
                    return repair_response()
                if system == CLASSIFICATION_REPAIR:
                    self.matrix = payload["source_label_matrix"]
                    party = next(item for item in payload["current_items"]
                                 if item["source_refs"][0]["attribution"] == "party")
                    return repair_response([{"op": "remove", "id": party["id"],
                        "revision": party["revision"], "reason": "duplicate wrong speaker"}])
                if system == FINALIZER:
                    return final_response()
                raise AssertionError("unexpected prompt")

        fake = Fake()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build_case(self._row(root), fake, config(), 100, 1,
                                root / "pilot_v6/calibration/013948")
            self.assertEqual({row["attribution"] for row in fake.matrix},
                             {"current_court", "party"})
            self.assertEqual(len(result["brief"]), 1)
            self.assertEqual(len(result["deleted_items"]), 1)

    def test_semantically_bad_mock_is_not_reported_as_accepted(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    sentence = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    return reader_response([add_brief(sentence, attribution="party",
                        reason="intentionally questionable")])
                if system in {SELECTION_REPAIR, CLASSIFICATION_REPAIR}:
                    return repair_response()
                return final_response()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build_case(self._row(root), Fake(), config(), 100, 1,
                                root / "pilot_v6/calibration/013948")
            self.assertEqual(result["quality_status"], "not_evaluated")
            self.assertNotIn("verification_status", result)
            self.assertNotIn("accepted", result["counts"])
            self.assertEqual(result["brief"][0]["source_refs"][0]["attribution"], "party")

    def test_deferred_only_output_is_distinct(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    sentence = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    return reader_response([add_brief(sentence)])
                if system == SELECTION_REPAIR:
                    item = payload["current_items"][0]
                    return repair_response([{"op": "defer", "id": item["id"],
                        "revision": item["revision"], "reason": "speaker unresolved"}])
                if system == CLASSIFICATION_REPAIR:
                    return repair_response()
                return final_response()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build_case(self._row(root), Fake(), config(), 100, 1,
                                root / "pilot_v6/calibration/013948")
            self.assertEqual(result["output_status"], "unresolved_only")
            self.assertFalse(result["brief"])
            self.assertEqual(len(result["unresolved_items"]), 1)

    def test_request_journal_keeps_payload_and_applied_marker(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return reader_response()
                if system in {SELECTION_REPAIR, CLASSIFICATION_REPAIR}:
                    return repair_response()
                return final_response()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "pilot_v6/calibration/013948"
            build_case(self._row(root), Fake(), config(), 100, 1, output)
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(set(checkpoint["request_journal"]),
                {"reader:0", "selection_repair:0", "classification_repair:0", "finalizer:0"})
            for record in checkpoint["request_journal"].values():
                self.assertEqual(record["status"], "applied")
                self.assertIn("payload", record)
                self.assertIn("prompt", record)
                self.assertIn("pre_request_snapshot", record)
                self.assertIn("post_request_snapshot", record)

    def test_resume_after_operations_before_stage_transition_does_not_replay(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    sentence = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    return reader_response([add_brief(sentence)])
                if system in {SELECTION_REPAIR, CLASSIFICATION_REPAIR}:
                    return repair_response()
                return final_response()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "pilot_v6/calibration/013948"
            row = self._row(root)
            from knowledge_base import pipeline_v6
            real_snapshot = pipeline_v6._save_snapshot
            failed = {"value": False}

            def crash_once(output_path, name, state):
                if name == "after_selection_repair" and not failed["value"]:
                    failed["value"] = True
                    raise RuntimeError("simulated crash after applied repair")
                return real_snapshot(output_path, name, state)

            with patch.object(pipeline_v6, "_save_snapshot", side_effect=crash_once):
                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    build_case(row, Fake(), config(), 100, 1, output)
            result = build_case(row, Fake(), config(), 100, 1, output)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(sum(event["op"] == "add" for event in result["history"]), 1)


if __name__ == "__main__":
    unittest.main()

