"""V7 regression tests for AU selection and explicit protocol withdrawals."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from knowledge_base.pipeline_v7 import build_case
from knowledge_base.prompts_v7 import (CLASSIFICATION_REPAIR, FINALIZER,
                                        PROTOCOL_REPAIR, READER, SELECTION_REPAIR)
from knowledge_base.source import load_source, source_handles, source_structure
from knowledge_base.state_v7 import (apply_operations_independently,
                                      independent_field_errors, initial_state)


def _response(action="complete", operations=None):
    return {"action": action, "reason": "checked supplied source",
            "read_window_ids": [], "operations": operations or [], "open_questions": []}


class V7ProtocolTests(unittest.TestCase):
    def _run(self, source_text, fake):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.txt"
            source.write_text(source_text, encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            output = root / "pilot_v7_au_priority/calibration/099980"
            result = build_case(row, fake, {"reader": "reader", "repair": "repair"},
                                10000, 1, output)
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            return result, checkpoint

    def test_withdrawn_bad_au_has_both_field_errors_and_no_item(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return _response("finalize")
                if system == SELECTION_REPAIR:
                    handle = payload["opened_sources"][0]["source_id"]
                    return _response(operations=[{"op": "add", "collection": "aus",
                        "item": {"source_refs": [{"source_id": handle,
                            "role": "court_response", "attribution": "current_court"}],
                            "treatment": {"value": "applies", "authority_source_ids": [],
                                          "response_source_ids": [handle]}},
                        "reason": "mistook final order for authority application"}])
                if system == PROTOCOL_REPAIR:
                    self.errors = payload["rejected_operations"][0]["field_errors"]
                    return {"control_patch": {}, "repairs": [{"rejection_id":
                        payload["valid_rejection_ids"][0], "resolution": "withdraw",
                        "reason": "this only states the order", "source_ids": []}]}
                if system == CLASSIFICATION_REPAIR:
                    return _response()
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [], "reason": "no supported AU"}
                raise AssertionError(system)

        fake = Fake()
        result, checkpoint = self._run("The court allows the application.", fake)
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["protocol_status"], "valid")
        self.assertEqual(result["output_status"], "empty_output")
        self.assertEqual(result["empty_reason"], "all_proposals_withdrawn")
        self.assertEqual(result["counts"]["protocol_withdrawn"], 1)
        self.assertEqual({error["error_code"] for error in fake.errors},
            {"au_requires_primary", "treatment_requires_authority_and_response"})
        self.assertFalse(checkpoint["state"]["items"])

    def test_missing_repair_is_not_withdrawal(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return _response("finalize")
                if system == SELECTION_REPAIR:
                    handle = payload["opened_sources"][0]["source_id"]
                    return _response(operations=[{"op": "add", "collection": "aus",
                        "item": {"source_refs": [{"source_id": handle, "role": "context",
                            "attribution": "current_court"}], "treatment": {"value": "unknown",
                            "authority_source_ids": [], "response_source_ids": []}},
                        "reason": "test invalid AU"}])
                if system == PROTOCOL_REPAIR:
                    return {"control_patch": {}, "repairs": []}
                raise AssertionError(system)

        result, _ = self._run("The court gives reasons.", Fake())
        self.assertEqual(result["execution_status"], "incomplete")
        self.assertEqual(result["operation_rejections"][0]["status"], "unresolved")

    def test_replacement_and_withdrawal_are_independent(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    return _response("finalize")
                if system == SELECTION_REPAIR:
                    handle = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    self.handle = handle
                    ref = {"source_id": handle, "role": "context",
                           "attribution": "current_court"}
                    item = {"source_refs": [ref], "treatment": {"value": "unknown",
                            "authority_source_ids": [], "response_source_ids": []}}
                    return _response(operations=[{"op": "add", "collection": "aus",
                        "item": item, "reason": "first"}, {"op": "add", "collection": "aus",
                        "item": item, "reason": "second"}])
                if system == PROTOCOL_REPAIR:
                    first, second = payload["valid_rejection_ids"]
                    return {"control_patch": {}, "repairs": [{"rejection_id": first,
                        "resolution": "withdraw", "reason": "bare outcome", "source_ids": []},
                        {"rejection_id": second, "resolution": "replace", "operation": {
                            "op": "add", "collection": "aus", "item": {"source_refs": [{
                                "source_id": self.handle, "role": "primary",
                                "attribution": "current_court"}], "treatment": {
                                "value": "unknown", "authority_source_ids": [],
                                "response_source_ids": []}}, "reason": "legal reasoning"}}]}
                if system == CLASSIFICATION_REPAIR:
                    return _response()
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [], "reason": "done"}
                raise AssertionError(system)

        result, _ = self._run("The court explains a legal rule.", Fake())
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(len(result["aus"]), 1)
        self.assertEqual(result["counts"]["protocol_withdrawn"], 1)
        self.assertEqual(result["counts"]["protocol_replaced"], 1)

    def test_withdrawn_update_preserves_existing_item_revision(self):
        class Fake:
            def complete(self, model, system, payload, **kwargs):
                if system == READER:
                    handle = payload["opened_sources"][0]["sentences"][0]["source_id"]
                    return _response("finalize", [{"op": "add", "collection": "brief",
                        "item": {"kind": "facts", "source_refs": [{"source_id": handle,
                            "role": "primary", "attribution": "current_court"}]},
                        "reason": "source fact"}])
                if system == SELECTION_REPAIR:
                    item = payload["current_items"][0]
                    return _response(operations=[{"op": "update", "id": item["id"],
                        "revision": 99, "changes": {"kind": "issues"},
                        "reason": "stale revision"}])
                if system == PROTOCOL_REPAIR:
                    return {"control_patch": {}, "repairs": [{"rejection_id":
                        payload["valid_rejection_ids"][0], "resolution": "withdraw",
                        "reason": "update based on stale state", "source_ids": []}]}
                if system == CLASSIFICATION_REPAIR:
                    return _response()
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [], "reason": "done"}
                raise AssertionError(system)

        result, _ = self._run("The court records a fact.", Fake())
        self.assertEqual(result["brief"][0]["revision"], 1)
        self.assertEqual(result["brief"][0]["kind"], "facts")
        self.assertEqual([entry["op"] for entry in result["history"]], ["add"])
        self.assertEqual(result["counts"]["protocol_withdrawn"], 1)

    def test_resume_after_withdrawal_does_not_repeat_request_or_event(self):
        from knowledge_base import pipeline_v7

        class Fake:
            calls = 0

            def complete(self, model, system, payload, **kwargs):
                self.calls += 1
                if system == READER:
                    return _response("finalize")
                if system == SELECTION_REPAIR:
                    handle = payload["opened_sources"][0]["source_id"]
                    return _response(operations=[{"op": "add", "collection": "aus",
                        "item": {"source_refs": [{"source_id": handle, "role": "context",
                            "attribution": "current_court"}], "treatment": {"value":
                            "unknown", "authority_source_ids": [],
                            "response_source_ids": []}}, "reason": "bad item"}])
                if system == PROTOCOL_REPAIR:
                    return {"control_patch": {}, "repairs": [{"rejection_id":
                        payload["valid_rejection_ids"][0], "resolution": "withdraw",
                        "reason": "no primary proposition", "source_ids": []}]}
                if system == CLASSIFICATION_REPAIR:
                    return _response()
                if system == FINALIZER:
                    return {"operations": [], "open_questions": [], "reason": "done"}
                raise AssertionError(system)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.txt"
            source.write_text("The court allows the application.", encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            output = root / "pilot_v7_au_priority/calibration/099980"
            fake = Fake()
            real_snapshot = pipeline_v7._save_snapshot
            interrupted = {"done": False}

            def crash_once(path, name, state):
                if name == "after_selection_repair" and not interrupted["done"]:
                    interrupted["done"] = True
                    raise RuntimeError("crash before phase transition")
                return real_snapshot(path, name, state)

            with patch.object(pipeline_v7, "_save_snapshot", side_effect=crash_once):
                with self.assertRaisesRegex(RuntimeError, "crash before phase transition"):
                    build_case(row, fake, {"reader": "reader", "repair": "repair"},
                               10000, 1, output)
            result = build_case(row, fake, {"reader": "reader", "repair": "repair"},
                                10000, 1, output)
            self.assertEqual(result["counts"]["protocol_withdrawn"], 1)
            self.assertEqual(result["counts"]["requests"], fake.calls)
            self.assertEqual(result["execution_status"], "completed")

    def test_same_ref_in_both_treatment_lists_does_not_duplicate_source_ref(self):
        _, units = source_structure("Applying Smith, we allow the appeal.", "a" * 64)
        source_map = {unit["source_id"]: unit for unit in units}
        stable_to_handle, alias_to_stable = source_handles(units)
        source_id = next(unit["source_id"] for unit in units
                         if unit["unit_type"] == "sentence")
        handle = stable_to_handle[source_id]
        op = {"op": "add", "collection": "aus", "item": {"source_refs": [{
            "source_id": handle, "role": "primary", "attribution": "current_court"}],
            "treatment": {"value": "applies", "authority_source_ids": [handle],
                          "response_source_ids": [handle]}}, "reason": "source has both"}
        state, applied, rejected, _ = apply_operations_independently(initial_state(),
            [op], set(source_map), source_map, "a" * 64, "099980",
            aliases=alias_to_stable, stable_to_handle=stable_to_handle,
            allowed_target_ids=set())
        self.assertFalse(rejected)
        self.assertEqual(len(applied), 1)
        bad = json.loads(json.dumps(op))
        bad["item"]["source_refs"].append(dict(bad["item"]["source_refs"][0]))
        _, _, rejected, _ = apply_operations_independently(state, [bad], set(source_map),
            source_map, "a" * 64, "099980", aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids=set(state["items"]))
        self.assertEqual(rejected[0]["error_code"], "duplicate_source_ref")

    def test_independent_diagnostics_do_not_claim_semantic_validity(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/v7/099980_invalid_au.json")
                             .read_text(encoding="utf-8"))
        op = fixture["original_operation"]
        self.assertEqual({entry["error_code"] for entry in independent_field_errors(op)},
            {"au_requires_primary", "treatment_requires_authority_and_response"})
        self.assertIn("duplicate_source_ref", {entry["error_code"] for entry in
            independent_field_errors(fixture["invalid_repair_operation"])})


if __name__ == "__main__":
    unittest.main()
