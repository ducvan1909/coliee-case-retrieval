"""Regression tests for source navigation and the shared reading budget."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from knowledge_base.pipeline_v10 import build_case
from knowledge_base.schema_v11 import build_schema, validate, validate_reading_decision
from knowledge_base.source import (guided_catalogue, load_source, source_structure,
                                   structure_windows)


def finish(manifest):
    unread = manifest["unread_window_ids"]
    return {"action": "finish_phase", "reason": "phase review complete",
            "unresolved_needs": (["Court reasoning not yet checked"] if unread else []),
            "unread_assessment": ([{"window_ids": unread,
                                    "reason": "Lower priority in this pass"}]
                                  if unread else [])}


class GuidedEndpoint:
    def __init__(self, *, invalid=False):
        self.calls = []
        self.invalid = invalid

    def complete(self, model, system, payload, *, response_format, **kwargs):
        manifest = payload["manifest"]
        phase = manifest["phase"]
        self.calls.append((phase, manifest))
        response = {"decisions": {}, **({"new_items": []}
                                       if phase in {"reader", "selection"} else {})}
        for entry in manifest["items"]:
            if phase == "classification":
                if entry["collection"] == "brief":
                    response["decisions"][entry["handle"]] = {"choice": "classify",
                        "reason": "issue", "kind": "issues",
                        "attribution": {source: "current_court"
                                        for source in entry["source_ids"]}}
                else:
                    primary = entry["source_ids"][0]
                    response["decisions"][entry["handle"]] = {"choice": "classify",
                        "reason": "rule", "primary_source_id": primary,
                        "roles": {source: "context" for source in entry["source_ids"]
                                  if source != primary},
                        "attribution": {source: "current_court"
                                        for source in entry["source_ids"]}}
            elif phase == "treatment":
                response["decisions"][entry["handle"]] = {
                    "choice": "unknown", "reason": "no authority relation"}
            else:
                response["decisions"][entry["handle"]] = {
                    "choice": "keep", "reason": "supported"}
        if phase == "reader":
            response["reading_decision"] = finish(manifest)
        elif phase == "selection":
            turn = len([name for name, _ in self.calls if name == "selection"])
            if turn == 1:
                chosen = manifest["unread_window_ids"][0]
                response["reading_decision"] = {"action": "read",
                    "window_ids": [chosen], "purpose": "check omitted court reasoning"}
            elif turn == 2:
                prior = manifest["opened_window_ids"][0]
                response["reading_decision"] = {"action": "read",
                    "window_ids": [prior], "purpose": "revisit unselected legal rule"}
            else:
                response["reading_decision"] = finish(manifest)
            if turn == 2:
                source = manifest["opened_sources"][0]["sentences"][0]["source_id"]
                response["new_items"] = [{"collection": "aus", "source_ids": [source],
                                          "reason": "legal rule"}]
            if self.invalid and turn == 3:
                response["reading_decision"]["unread_assessment"] = []
        assert response_format["json_schema"]["schema"] == manifest["schema"]
        return response


class V11Tests(unittest.TestCase):
    def test_catalogue_preserves_marker_heading_and_source_coordinates(self):
        text = "I. INTRODUCTION\r\n[1] Règle <FRAGMENT_SUPPRESSED> applies.\r\n\r\n"
        text += "II. REASONS\r\n[2] A legal conclusion follows."
        source_hash = "a" * 64
        paragraphs, units = source_structure(text, source_hash)
        windows = structure_windows(paragraphs, 80)
        catalogue, full = guided_catalogue(text, units, windows)
        self.assertEqual(len(full["markers"]), 1)
        marker = full["markers"][0]
        self.assertEqual(text[marker["start"]:marker["end"]], "<FRAGMENT_SUPPRESSED>")
        self.assertTrue(any(heading["text"] == "II. REASONS"
                            for heading in full["headings"]))
        self.assertEqual(sum(window["marker_count"] for window in
                             catalogue["windows"]), 1)
        self.assertTrue(catalogue["preview_is_not_read"])

    def test_schema_restricts_reading_and_requires_complete_stop_assessment(self):
        schema = build_schema("reader", [], ["S0001"], [2, 3], [2, 3])
        response = {"decisions": {}, "new_items": [], "reading_decision":
            {"action": "read", "window_ids": [2], "purpose": "read rule"}}
        self.assertFalse(validate(response, schema))
        response["reading_decision"]["window_ids"] = [9]
        self.assertTrue(validate(response, schema))
        forced = build_schema("reader", [], ["S0001"], [], [2, 3])
        response["reading_decision"] = {"action": "read", "window_ids": [2],
                                         "purpose": "read rule"}
        self.assertTrue(validate(response, forced))
        response["reading_decision"] = {"action": "finish_phase", "reason": "done",
            "unresolved_needs": [], "unread_assessment": [
                {"window_ids": [2], "reason": "not needed"}]}
        self.assertFalse(validate(response, forced))
        self.assertTrue(validate_reading_decision(response, [2, 3]))

    def test_selection_uses_remaining_budget_and_rereads_only_requested_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("\n\n".join(
                f"[{index}] Court legal reasoning {index}." for index in range(12)),
                encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            endpoint = GuidedEndpoint()
            output = root / "pilot_v11/calibration/099980"
            result = build_case(row, endpoint, {"reader": "mock", "repair": "mock"},
                                80, 6, output, "guided")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["schema_version"], 11)
            self.assertEqual(result["counts"]["read_actions"], 2)
            self.assertEqual(result["counts"]["reread_actions"], 1)
            self.assertEqual([call[0] for call in endpoint.calls].count("selection"), 3)
            reread_manifest = endpoint.calls[3][1]
            self.assertEqual(reread_manifest["phase"], "selection")
            self.assertFalse(set(reread_manifest["newly_opened_window_ids"]) &
                             set(reread_manifest["unread_window_ids"]))
            self.assertTrue(reread_manifest["opened_sources"])
            self.assertEqual(len(result["aus"]), 1)
            self.assertEqual(result["source_coverage"]["provided_not_proven_understood"],
                             True)
            checkpoint = json.loads((output / "checkpoint.json").read_text("utf-8"))
            self.assertEqual(checkpoint["stage"], "complete")
            self.assertEqual(checkpoint["read_actions"], 2)
            self.assertEqual(len(checkpoint["reading_history"]), 4)
            self.assertEqual((output / "source_navigation.json").is_file(), True)
            call_count = len(endpoint.calls)
            resumed = build_case(row, endpoint, {"reader": "mock", "repair": "mock"},
                                 80, 6, output, "guided")
            self.assertEqual(len(endpoint.calls), call_count)
            self.assertEqual(resumed["history"], result["history"])

    def test_v10_manifest_and_prompt_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("[1] A legal rule.\n\n[2] Another rule.", encoding="utf-8")
            row = {"case_id": "case", "source": str(source),
                   "source_hash": load_source(source)[1]}
            class InspectEndpoint:
                def __init__(self):
                    self.manifests = []

                def complete(self, model, system, payload, **kwargs):
                    self.manifests.append((system, payload["manifest"]))
                    manifest = payload["manifest"]
                    response = {"decisions": {entry["handle"]:
                        {"choice": "keep", "reason": "supported"}
                        for entry in manifest["items"]}}
                    if manifest["phase"] in {"reader", "selection"}:
                        response["new_items"] = []
                    if "read_window_ids" in manifest["schema"]["properties"]:
                        response["read_window_ids"] = []
                    return response
            endpoint = InspectEndpoint()
            build_case(row, endpoint, {"reader": "mock", "repair": "mock"},
                       80, 6, root / "control/calibration/case", "v10")
            from knowledge_base.pipeline_v10 import PROMPTS
            self.assertEqual(endpoint.manifests[0][0], PROMPTS["reader"])
            catalogue = endpoint.manifests[0][1]["catalogue"]["windows"]
            self.assertTrue(all("reading_status" not in window and
                                "marker_count" not in window for window in catalogue))

    def test_case_request_identity_is_experiment_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("[1] A legal rule.", encoding="utf-8")
            row = {"case_id": "case", "source": str(source),
                   "source_hash": load_source(source)[1]}
            class CaptureEndpoint:
                def __init__(self):
                    self.ids = []

                def complete(self, model, system, payload, *, request_id, **kwargs):
                    self.ids.append(request_id)
                    manifest = payload["manifest"]
                    response = {"decisions": {}, **({"new_items": []}
                        if manifest["phase"] in {"reader", "selection"} else {})}
                    if "read_window_ids" in manifest["schema"]["properties"]:
                        response["read_window_ids"] = []
                    return response
            endpoint = CaptureEndpoint()
            for name in ("first", "second"):
                build_case(row, endpoint, {"reader": "mock", "repair": "mock"},
                           100, 6, root / name / "calibration/case", "v10")
            self.assertEqual(len(endpoint.ids), 10)
            self.assertNotEqual(endpoint.ids[0], endpoint.ids[5])

    def test_invalid_stop_assessment_applies_nothing_from_that_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("\n\n".join(
                f"[{index}] Legal analysis {index}." for index in range(12)),
                encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            output = root / "pilot_v11/calibration/099980"
            result = build_case(row, GuidedEndpoint(invalid=True),
                                {"reader": "mock", "repair": "mock"},
                                70, 6, output, "guided")
            self.assertEqual(result["execution_status"], "incomplete")
            self.assertEqual(result["output_status"], "incomplete")
            self.assertEqual(result["counts"]["protocol_errors_unresolved"], 1)
            self.assertEqual(len(result["aus"]), 1)

    def test_shared_budget_processes_the_last_opened_source(self):
        class UseBudget(GuidedEndpoint):
            def complete(self, model, system, payload, **kwargs):
                response = super().complete(model, system, payload, **kwargs)
                manifest = payload["manifest"]
                if manifest["phase"] == "selection":
                    readable = manifest["readable_window_ids"]
                    response["reading_decision"] = (
                        {"action": "read", "window_ids": [readable[0]],
                         "purpose": "inspect next legal section"}
                        if readable else finish(manifest))
                return response
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("\n\n".join(
                f"[{index}] Court analysis of legal test number {index}."
                for index in range(40)), encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            endpoint = UseBudget()
            result = build_case(row, endpoint, {"reader": "mock", "repair": "mock"},
                80, 6, root / "pilot_v11/calibration/099980", "guided")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["counts"]["read_actions"], 7)
            self.assertEqual(result["counts"]["requests"], 12)
            selection_calls = [manifest for phase, manifest in endpoint.calls
                               if phase == "selection"]
            self.assertEqual(len(selection_calls), 8)
            self.assertTrue(selection_calls[-1]["opened_sources"])
            self.assertEqual(selection_calls[-1]["remaining_read_actions"], 0)
            self.assertEqual(selection_calls[-1]["reading_limit_reason"],
                             "shared_limit")
