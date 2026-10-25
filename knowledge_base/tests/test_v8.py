"""V8 regressions for fail-closed protocol repair and item audits."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from knowledge_base.pipeline_v8 import build_case, _validate_control
from knowledge_base import pipeline_v8
from knowledge_base.prompts_v8 import (ATTRIBUTION_REPAIR, FINALIZER,
    FULL_RESPONSE_REPAIR, PROTOCOL_REPAIR, READER, SELECTION_REPAIR,
    TREATMENT_REPAIR)
from knowledge_base.source import load_source
from knowledge_base.source import source_handles, source_structure
from knowledge_base.state_v8 import apply_operations_independently, initial_state


TEXT = "\n\n".join(f"Paragraph {index}: The court considers a legal question here."
                  for index in range(8))


def response(action="complete", operations=None, checks=None, windows=None):
    return {"action": action, "reason": "checked this source",
        "read_window_ids": windows or [], "operations": operations or [],
        "open_questions": [], "item_checks": checks or []}


def checks(payload, decision="keep", operation_id=None):
    items = payload["current_items"] + payload["unresolved_items"]
    return [{"id": item["id"], "revision": item["revision"],
        "decision": decision if item["id"] == operation_id else "keep",
        "reason": "selected text supports this item",
        "source_ids": [payload["opened_sources"][0]["source_id"]]}
        for item in items]


class V8Tests(unittest.TestCase):
    def run_case(self, fake):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.txt"
            source.write_text(TEXT, encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                "source_hash": load_source(source)[1]}
            output = root / "pilot_v8/calibration/099980"
            result = build_case(row, fake, {"reader": "reader", "repair": "repair"},
                                90, 1, output)
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            return result, checkpoint

    def test_missing_control_is_not_replaced_with_executable_defaults(self):
        control, errors, _ = _validate_control({"operations": []}, "selection_repair",
            unread={1}, continuation=False, require_read=True)
        self.assertNotIn("action", control)
        self.assertNotIn("read_window_ids", control)
        self.assertNotIn("reason", control)
        self.assertIn("selection_read_required", {error["error_code"] for error in errors})

    def test_real_double_json_and_wrong_rejection_cannot_complete(self):
        raw = (Path(__file__).parent / "fixtures/v8/099980_double_json.txt").read_text(
            encoding="utf-8").strip()

        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return {"action": "finalize", "reason": "draft ready",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if system == SELECTION_REPAIR:
                    return {"__raw_invalid_json__": raw}
                if system == FULL_RESPONSE_REPAIR:
                    return {"control_patch": {}, "repairs": [{"rejection_id":
                        "099980:selection_repair:0:control:0", "resolution": "replace",
                        "operation": {"action": "complete", "operations": []}}]}
                raise AssertionError(system)

        result, checkpoint = self.run_case(Fake())
        self.assertEqual(result["execution_status"], "incomplete")
        self.assertEqual(result["protocol_status"], "failure")
        self.assertEqual(checkpoint["stage"], "incomplete_protocol")
        self.assertEqual(len(checkpoint["opened_window_ids"]), 2)
        self.assertFalse(any(event["stage"] == "finalizer" for event in checkpoint["trace"]))

    def test_full_replacement_can_read_then_continue_without_replay(self):
        class Fake:
            calls = 0

            def complete(self, model, system, payload, **kwargs):
                self.calls += 1
                if system == READER:
                    return {"action": "finalize", "reason": "draft ready",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if system == SELECTION_REPAIR:
                    if payload["continuation"]:
                        return response()
                    return {"__raw_invalid_json__": "{}{}"}
                if system == FULL_RESPONSE_REPAIR:
                    self.assert_read = payload["unread_window_ids"][0]
                    return response("read", windows=[self.assert_read])
                if system in {ATTRIBUTION_REPAIR, TREATMENT_REPAIR}:
                    return response()
                if system == FINALIZER:
                    return {"operations": [], "reason": "final state checked",
                        "open_questions": [], "item_checks": []}
                raise AssertionError(system)

        fake = Fake()
        result, checkpoint = self.run_case(fake)
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["protocol_status"], "valid")
        self.assertIn(fake.assert_read, checkpoint["opened_window_ids"])
        self.assertEqual(len(checkpoint["protocol_repairs"]), 1)
        self.assertEqual(checkpoint["protocol_repairs"][0]["mode"],
                         "replace_entire_response")

    def test_item_checks_are_required_even_when_operations_empty(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return {"action": "finalize", "reason": "draft ready",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if system == SELECTION_REPAIR:
                    return (response() if payload["continuation"] else
                        response("read", windows=[payload["unread_window_ids"][0]]))
                if system == ATTRIBUTION_REPAIR:
                    return {"action": "complete", "reason": "reviewed",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if system == PROTOCOL_REPAIR:
                    return {"control_patch": {}, "repairs": []}
                raise AssertionError(system)

        result, _ = self.run_case(Fake())
        self.assertEqual(result["execution_status"], "incomplete")
        self.assertEqual(result["protocol_status"], "failure")
        self.assertIn("item_checks_must_be_list",
            {record["error_code"] for record in result["protocol_errors"]})

    def test_invalid_entry_in_parsed_protocol_repair_stops_case(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return {"action": "finalize", "reason": "draft ready",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if system == SELECTION_REPAIR:
                    return response("read", windows=[payload["unread_window_ids"][0]])
                if system == PROTOCOL_REPAIR:
                    return {"control_patch": {"item_checks": []}, "repairs": [{
                        "rejection_id": "invented", "resolution": "withdraw",
                        "reason": "invalid", "source_ids": []}]}
                raise AssertionError(system)

        result, checkpoint = self.run_case(Fake())
        self.assertEqual(result["execution_status"], "incomplete")
        self.assertEqual(result["protocol_status"], "failure")
        self.assertEqual(checkpoint["protocol_repairs"][0]["status"], "failed")

    def test_attribution_and_treatment_are_separate_and_not_semantic_gold(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    handle = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    return {"action": "finalize", "reason": "draft ready",
                        "read_window_ids": [], "open_questions": [], "operations": [{
                            "op": "add", "collection": "aus", "item": {"source_refs": [{
                                "source_id": handle, "role": "primary",
                                "attribution": "current_court"}], "treatment": {
                                "value": "unknown", "authority_source_ids": [],
                                "response_source_ids": []}}, "reason": "draft AU"}]}
                if system == SELECTION_REPAIR:
                    return (response(checks=checks(payload)) if payload["continuation"]
                        else response("read", checks=checks(payload),
                                      windows=[payload["unread_window_ids"][0]]))
                if system == ATTRIBUTION_REPAIR:
                    item = payload["current_items"][0]
                    refs = json.loads(json.dumps(item["source_refs"]))
                    refs[0]["attribution"] = "party"
                    op = {"op": "update", "id": item["id"],
                          "revision": item["revision"],
                          "changes": {"source_refs": refs},
                          "reason": "speaker identified from source"}
                    return response(operations=[op],
                        checks=checks(payload, "update", item["id"]))
                if system == TREATMENT_REPAIR:
                    item = payload["current_items"][0]
                    handle = item["source_refs"][0]["source_id"]
                    op = {"op": "update", "id": item["id"],
                          "revision": item["revision"],
                          "changes": {"treatment": {"value": "applies",
                            "authority_source_ids": [handle],
                            "response_source_ids": [handle]}},
                          "reason": "model claims application"}
                    return response(operations=[op],
                        checks=checks(payload, "update", item["id"]))
                if system == FINALIZER:
                    return {"operations": [], "reason": "checked final items",
                            "open_questions": [], "item_checks": checks(payload)}
                raise AssertionError(system)

        result, checkpoint = self.run_case(Fake())
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["aus"][0]["revision"], 3)
        self.assertEqual(result["aus"][0]["source_refs"][0]["attribution"], "party")
        self.assertEqual(result["aus"][0]["treatment"]["value"], "applies")
        self.assertEqual(result["quality_status"], "not_evaluated")
        self.assertEqual(len([entry for entry in checkpoint["trace"]
                              if entry["stage"] == "repair_attribution"]), 1)

    def test_treatment_turn_cannot_relabel_existing_source(self):
        source_hash = "a" * 64
        _, units = source_structure("The court states a rule.", source_hash)
        source_map = {unit["source_id"]: unit for unit in units}
        stable_to_handle, aliases = source_handles(units)
        handle = next(stable_to_handle[unit["source_id"]] for unit in units
                      if unit["unit_type"] == "sentence")
        add = {"op": "add", "collection": "aus", "item": {"source_refs": [{
            "source_id": handle, "role": "primary", "attribution": "current_court"}],
            "treatment": {"value": "unknown", "authority_source_ids": [],
                          "response_source_ids": []}}, "reason": "source proposition"}
        state, events, _, _ = apply_operations_independently(initial_state(), [add],
            set(source_map), source_map, source_hash, "099980", aliases=aliases,
            stable_to_handle=stable_to_handle, allowed_target_ids=set())
        item_id = events[0]["id"]
        changed = {"op": "update", "id": item_id, "revision": 1,
            "changes": {"source_refs": [{"source_id": handle, "role": "primary",
                "attribution": "cited_authority"}]}, "reason": "bad relabel"}
        _, _, rejected, _ = apply_operations_independently(state, [changed],
            set(source_map), source_map, source_hash, "099980", aliases=aliases,
            stable_to_handle=stable_to_handle, allowed_target_ids={item_id},
            phase="treatment_repair")
        self.assertEqual(rejected[0]["error_code"],
                         "treatment_phase_changed_existing_source_label")

    def test_resume_after_applied_replacement_does_not_replay(self):
        class Fake:
            calls = 0

            def complete(self, model, system, payload, **kwargs):
                self.calls += 1
                if system == READER:
                    return {"action": "finalize", "reason": "draft ready",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if system == SELECTION_REPAIR:
                    return (response() if payload["continuation"] else
                            {"__raw_invalid_json__": "{}{}"})
                if system == FULL_RESPONSE_REPAIR:
                    return response("read", windows=[payload["unread_window_ids"][0]])
                if system in {ATTRIBUTION_REPAIR, TREATMENT_REPAIR}:
                    return response()
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [],
                            "reason": "final checked", "item_checks": []}
                raise AssertionError(system)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.txt"
            source.write_text(TEXT, encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            output = root / "pilot_v8/calibration/099980"
            fake = Fake()
            original = pipeline_v8._save_snapshot
            crashed = False

            def once(path, name, state):
                nonlocal crashed
                if name == "after_selection_repair" and not crashed:
                    crashed = True
                    raise RuntimeError("simulated crash")
                return original(path, name, state)

            with patch.object(pipeline_v8, "_save_snapshot", side_effect=once):
                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    build_case(row, fake, {"reader": "reader", "repair": "repair"},
                               90, 1, output)
            result = build_case(row, fake, {"reader": "reader", "repair": "repair"},
                                90, 1, output)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["counts"]["requests"], fake.calls)
            self.assertEqual(len(result["protocol_repairs"]), 1)


if __name__ == "__main__":
    unittest.main()
