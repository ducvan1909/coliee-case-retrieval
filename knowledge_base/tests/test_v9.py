"""V9 regressions for control repair and final-only output status."""

import json
from pathlib import Path
import tempfile
import unittest

from knowledge_base.__main__ import _report
from knowledge_base.pipeline_v9 import build_case, output_status_for_checkpoint
from knowledge_base.prompts_v9 import (ATTRIBUTION_REPAIR, FINALIZER, READER,
    REPLACE_REPAIR_EXAMPLE, SELECTION_REPAIR, TREATMENT_REPAIR,
    WITHDRAW_REPAIR_EXAMPLE, protocol_repair_prompt)
from knowledge_base.schema_v9 import validate_protocol_repair_response
from knowledge_base.source import (load_source, source_handles, source_structure)
from knowledge_base.state_v9 import (apply_operations_independently,
                                     independent_field_errors, initial_state)


TEXT = "\n\n".join(f"Paragraph {number}: The court considers a legal question."
                  for number in range(8))


def repair_response(payload):
    return {"action": ("read" if payload["unread_window_ids"] and
            not payload.get("continuation") else "complete"),
        "reason": "checked supplied sources",
        "read_window_ids": ([payload["unread_window_ids"][0]]
            if payload["unread_window_ids"] and not payload.get("continuation") else []),
        "operations": [], "open_questions": [], "item_checks": []}


class V9Tests(unittest.TestCase):
    def _run(self, fake):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.txt"
            source.write_text(TEXT, encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                "source_hash": load_source(source)[1]}
            output = root / "pilot_v9/calibration/099980"
            result = build_case(row, fake, {"reader": "reader", "repair": "repair"},
                                90, 1, output)
            checkpoint = json.loads((output / "checkpoint.json").read_text(
                encoding="utf-8"))
            report = _report(output.parents[1])
            return result, checkpoint, report

    def test_control_only_prompt_uses_patch_and_excludes_operation_examples(self):
        prompt = protocol_repair_prompt("reader", control_errors=[{
            "error_id": "099980:reader:6:control:0",
            "error_code": "requested_window_not_unread"}],
            rejected_operations=[], allowed_control_fields=["action", "read_window_ids"])
        self.assertIn('"control_patch":{"action":"finalize"}', prompt)
        self.assertIn('"repairs":[]', prompt)
        self.assertIn("control error_id", prompt)
        self.assertNotIn("add AU:", prompt)

    def test_operation_and_mixed_prompts_keep_rejection_ids_separate(self):
        rejected = [{"rejection_id": "099980:reader:0:op:0"}]
        operation_only = protocol_repair_prompt("reader", control_errors=[],
            rejected_operations=rejected, allowed_control_fields=[])
        self.assertIn("control_patch MUST be {}", operation_only)
        self.assertIn("valid_rejection_ids", operation_only)
        mixed = protocol_repair_prompt("reader", control_errors=[{
            "error_id": "099980:reader:0:control:0"}],
            rejected_operations=rejected, allowed_control_fields=["action"])
        self.assertIn("Both control and operations have errors", mixed)
        self.assertIn("never a control error_id", mixed)
        self.assertIn('"resolution":"replace"', operation_only)
        self.assertIn('"resolution":"withdraw"', operation_only)

    def test_prompt_repair_examples_use_runtime_structure_validator(self):
        for response in ({"control_patch": {}, "repairs": [REPLACE_REPAIR_EXAMPLE]},
                         {"control_patch": {}, "repairs": [WITHDRAW_REPAIR_EXAMPLE]},
                         {"control_patch": {"action": "complete"},
                          "repairs": [WITHDRAW_REPAIR_EXAMPLE]}):
            validation = validate_protocol_repair_response(response)
            self.assertFalse(validation["envelope_errors"])
            self.assertTrue(all(not entry["errors"] for entry in
                                validation["entries"]))

    def test_repair_structure_reports_exact_paths_without_autofill(self):
        cases = [
            ({"rejection_id": "r", "operation": {}},
             "repairs[0].resolution", "missing_required_field"),
            ({"rejection_id": "r", "resolution": "retry", "operation": {}},
             "repairs[0].resolution", "invalid_enum_value"),
            ({"rejection_id": "r", "resolution": "replace", "operation": {},
              "reason": "extra"}, "repairs[0].reason", "unexpected_field"),
            ({"rejection_id": "r", "resolution": "withdraw", "reason": "x",
              "source_ids": ["S0001", "S0001"]}, "repairs[0].source_ids",
             "duplicate_source_id"),
        ]
        for entry, path, code in cases:
            validation = validate_protocol_repair_response(
                {"control_patch": {}, "repairs": [entry]})
            self.assertIn({"path": path, "error_code": code},
                          validation["entries"][0]["errors"])

    def test_read_empty_repaired_by_control_patch_reaches_valid_finalizer(self):
        class Fake:
            reader_calls = 0
            protocol_calls = 0

            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    self.reader_calls += 1
                    if self.reader_calls == 1:
                        return {"action": "read", "reason": "inspect analysis",
                            "read_window_ids": [payload["unread_window_ids"][0]],
                            "operations": [], "open_questions": []}
                    return {"action": "read", "reason": "no unread windows remaining",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if "Only control fields are wrong." in system:
                    self.protocol_calls += 1
                    self.assert_payload = payload
                    return {"control_patch": {"action": "finalize"}, "repairs": []}
                if system == SELECTION_REPAIR:
                    return repair_response(payload)
                if system in {ATTRIBUTION_REPAIR, TREATMENT_REPAIR}:
                    return {"action": "complete", "reason": "checked",
                        "read_window_ids": [], "operations": [],
                        "open_questions": [], "item_checks": []}
                if system == FINALIZER:
                    return {"reason": "no supported item", "operations": [],
                        "open_questions": [], "item_checks": []}
                raise AssertionError(system)

        fake = Fake()
        result, checkpoint, report = self._run(fake)
        self.assertEqual(fake.protocol_calls, 1)
        self.assertFalse(fake.assert_payload["reading_allowed"])
        self.assertEqual(fake.assert_payload["remaining_read_actions"], 0)
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["output_status"], "empty_output")
        self.assertEqual(checkpoint["stage"], "complete")
        self.assertEqual(report["groups"]["extractive_v9"][0]["output_status"],
                         "empty_output")

    def test_empty_patch_and_control_id_in_repairs_leave_draft_incomplete(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return {"action": "read", "reason": "no more source",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if "Only control fields are wrong." in system:
                    return {"control_patch": {}, "repairs": [{"rejection_id":
                        "099980:reader:0:control:0", "resolution": "replace",
                        "operation": {"action": "finalize"}}]}
                raise AssertionError(system)

        result, checkpoint, report = self._run(Fake())
        self.assertEqual(result["execution_status"], "incomplete")
        self.assertEqual(result["output_status"], "incomplete")
        self.assertIsNone(result["empty_reason"])
        self.assertFalse(result["final_au_ids"])
        self.assertEqual(checkpoint["stage"], "incomplete_protocol")
        self.assertEqual(report["groups"]["extractive_v9"][0]["output_status"],
                         "incomplete")

    def test_empty_patch_alone_cannot_resolve_control_error(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return {"action": "read", "reason": "no more source",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if "Only control fields are wrong." in system:
                    return {"control_patch": {}, "repairs": []}
                raise AssertionError(system)

        result, _, _ = self._run(Fake())
        self.assertEqual(result["output_status"], "incomplete")
        self.assertEqual(result["protocol_status"], "failure")

    def test_applied_operation_survives_bad_control_repair_without_replay(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    handle = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    return {"action": "read", "reason": "no more source",
                        "read_window_ids": [], "open_questions": [], "operations": [{
                            "op": "add", "collection": "brief", "item": {
                                "kind": "facts", "source_refs": [{"source_id": handle,
                                    "role": "primary", "attribution": "current_court"}]},
                            "reason": "source fact"}]}
                if "Only control fields are wrong." in system:
                    self.already_applied = payload["valid_operations_already_applied"]
                    return {"control_patch": {"action": "finalize"},
                        "repairs": [{"rejection_id": "099980:reader:0:control:0",
                            "resolution": "withdraw", "reason": "wrong place",
                            "source_ids": []}]}
                raise AssertionError(system)

        fake = Fake()
        result, checkpoint, _ = self._run(fake)
        self.assertEqual(len(fake.already_applied), 1)
        self.assertEqual(len(result["brief"]), 1)
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["output_status"], "incomplete")
        self.assertEqual(checkpoint["protocol_repairs"][0]["status"], "failed")

    def test_missing_resolution_in_operation_repair_is_rejected(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return {"action": "finalize", "reason": "draft ready",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if system == SELECTION_REPAIR:
                    first = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    other = payload["opened_sources"][0]["source_id"]
                    return {"action": "read", "reason": "inspect another window",
                        "read_window_ids": [payload["unread_window_ids"][0]],
                        "open_questions": [], "item_checks": [], "operations": [{
                            "op": "add", "collection": "aus", "item": {
                                "source_refs": [{"source_id": first, "role": "primary",
                                    "attribution": "current_court"}],
                                "treatment": {"value": "applies",
                                    "authority_source_ids": [first],
                                    "response_source_ids": [other]}},
                            "reason": "missing selected response"}]}
                if "Only operations were rejected." in system:
                    self.repair_payload = payload
                    original = payload["rejected_operations"][0]
                    operation = json.loads(json.dumps(original["original_operation"]))
                    operation["item"]["source_refs"].append({"source_id":
                        operation["item"]["treatment"]["response_source_ids"][0],
                        "role": "court_response", "attribution": "current_court"})
                    return {"control_patch": {}, "repairs": [{"rejection_id":
                        original["rejection_id"], "operation": operation}]}
                raise AssertionError(system)

        fake = Fake()
        result, checkpoint, _ = self._run(fake)
        self.assertEqual(result["output_status"], "incomplete")
        self.assertEqual(result["operation_rejections"][0]["repair_error_code"],
                         "invalid_replacement")
        self.assertIn("expected_repair_response", fake.repair_payload)
        self.assertIn("original_phase_response_contract", fake.repair_payload)
        self.assertNotIn("expected_response", fake.repair_payload)
        field_error = fake.repair_payload["rejected_operations"][0]["field_errors"][0]
        self.assertEqual(field_error["path"],
                         "item.treatment.response_source_ids")
        self.assertIn({"path": "repairs[0].resolution",
                       "error_code": "missing_required_field"},
                      checkpoint["protocol_repairs"][0]["errors"])
        self.assertEqual(checkpoint["stage"], "incomplete_protocol")

    def test_valid_repair_is_applied_when_sibling_entry_is_invalid(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return {"action": "finalize", "reason": "draft ready",
                        "read_window_ids": [], "operations": [], "open_questions": []}
                if system == SELECTION_REPAIR:
                    handles = [sentence["source_id"] for paragraph in
                        payload["opened_sources"] for sentence in paragraph["sentences"]]
                    first, second = handles[:2]
                    def invalid(primary, response):
                        return {"op": "add", "collection": "aus", "item": {
                            "source_refs": [{"source_id": primary, "role": "primary",
                                "attribution": "current_court"}],
                            "treatment": {"value": "applies",
                                "authority_source_ids": [primary],
                                "response_source_ids": [response]}},
                            "reason": "proposed application"}
                    self.operations = [invalid(first, second), invalid(second, first)]
                    return {"action": "read", "reason": "inspect another window",
                        "read_window_ids": [payload["unread_window_ids"][0]],
                        "open_questions": [], "item_checks": [],
                        "operations": self.operations}
                if "Only operations were rejected." in system:
                    entries = []
                    for index, record in enumerate(payload["rejected_operations"]):
                        operation = json.loads(json.dumps(record["original_operation"]))
                        response = operation["item"]["treatment"]["response_source_ids"][0]
                        operation["item"]["source_refs"].append({"source_id": response,
                            "role": "court_response", "attribution": "current_court"})
                        entry = {"rejection_id": record["rejection_id"],
                                 "operation": operation}
                        if index == 0:
                            entry["resolution"] = "replace"
                        entries.append(entry)
                    return {"control_patch": {}, "repairs": entries}
                raise AssertionError(system)

        result, checkpoint, _ = self._run(Fake())
        self.assertEqual(result["output_status"], "incomplete")
        statuses = [record["status"] for record in
                    result["operation_rejections"]]
        self.assertEqual(statuses, ["resolved", "unresolved"])
        self.assertEqual(len(result["aus"]), 1)
        self.assertEqual(checkpoint["protocol_repairs"][0]["status"], "failed")

    def test_real_099980_fixture_replays_six_valid_and_three_rejected_operations(self):
        fixture_path = (Path(__file__).parent /
                        "fixtures/v9/099980_operation_repair.json")
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        text = "\n\n".join(f"Synthetic proposition {index}." for index in range(400))
        source_hash = "a" * 64
        _, units = source_structure(text, source_hash)
        source_map = {unit["source_id"]: unit for unit in units}
        stable_to_handle, alias_to_stable = source_handles(units)
        state, applied, rejected, noops = apply_operations_independently(initial_state(),
            fixture["original_response"]["operations"], set(source_map), source_map,
            source_hash, "099980", aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids=set(),
            phase="selection_repair")
        self.assertEqual(len(applied), 6)
        self.assertEqual(len(rejected), 3)
        self.assertFalse(noops)
        self.assertTrue(all(entry["error_code"] == "treatment_source_not_selected"
                            for entry in rejected))
        diagnostics = [independent_field_errors(entry["operation"])
                       for entry in rejected]
        self.assertEqual([entry[0]["path"] for entry in diagnostics],
                         ["item.treatment.response_source_ids"] * 3)
        self.assertEqual([entry[0]["missing_source_ids"] for entry in diagnostics],
                         [["S0298"], ["S0089"], ["S0354"]])

        repaired = json.loads(json.dumps(fixture["repair_response"]))
        for entry in repaired["repairs"]:
            entry["resolution"] = "replace"
        validation = validate_protocol_repair_response(repaired)
        self.assertFalse(validation["envelope_errors"])
        self.assertTrue(all(not entry["errors"] for entry in validation["entries"]))
        for entry in repaired["repairs"]:
            state, fixed, rejected_again, noops = apply_operations_independently(state,
                [entry["operation"]], set(source_map), source_map, source_hash,
                "099980", aliases=alias_to_stable,
                stable_to_handle=stable_to_handle,
                allowed_target_ids=set(state["items"]), phase="selection_repair")
            self.assertEqual(len(fixed), 1)
            self.assertFalse(rejected_again)
            self.assertFalse(noops)
        self.assertEqual(sum(item["collection"] == "aus" for item in
                             state["items"].values()), 5)

    def test_incomplete_draft_with_item_is_not_final_nonempty(self):
        checkpoint = {"stage": "incomplete_protocol", "processed_responses": {},
            "state": {"items": {"x": {"status": "active"}}, "history": []},
            "operation_rejections": [], "protocol_errors": [], "protocol_repairs": []}
        self.assertEqual(output_status_for_checkpoint(checkpoint, "incomplete"),
                         "incomplete")
        checkpoint["stage"] = "complete"
        checkpoint["processed_responses"]["finalizer:0"] = {}
        self.assertEqual(output_status_for_checkpoint(checkpoint, "completed"),
                         "nonempty")

    def test_report_recovers_checkpoint_or_failure_without_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint_dir = root / "calibration/099980"
            checkpoint_dir.mkdir(parents=True)
            (checkpoint_dir / "checkpoint.json").write_text(json.dumps({
                "schema_version": 9, "stage": "reading", "protocol_errors": [],
                "operation_rejections": [], "protocol_repairs": []}), encoding="utf-8")
            failure_dir = root / "calibration/013948"
            failure_dir.mkdir(parents=True)
            (failure_dir / "failure.json").write_text('{"type":"Timeout"}',
                encoding="utf-8")
            report = _report(root)
            self.assertEqual({row["case_id"] for row in report["incomplete_without_case"]},
                             {"099980", "013948"})
            self.assertTrue(all(row["output_status"] == "incomplete" for row in
                                report["incomplete_without_case"]))

    def test_report_preserves_v8_original_status_while_correcting_display(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "calibration/099980"
            case_dir.mkdir(parents=True)
            (case_dir / "case.json").write_text(json.dumps({
                "schema_version": 8, "case_id": "099980",
                "execution_status": "incomplete", "protocol_status": "failure",
                "output_status": "empty_output", "quality_status": "not_evaluated",
                "counts": {}, "source_coverage": {}}), encoding="utf-8")
            (case_dir / "checkpoint.json").write_text(json.dumps({
                "stage": "incomplete_protocol", "protocol_errors": [],
                "operation_rejections": [], "protocol_repairs": []}), encoding="utf-8")
            row = _report(root)["groups"]["extractive_v8"][0]
            self.assertEqual(row["output_status"], "incomplete")
            self.assertEqual(row["original_output_status"], "empty_output")


if __name__ == "__main__":
    unittest.main()
