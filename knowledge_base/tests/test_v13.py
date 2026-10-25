"""V13 regression for separated extraction, navigation, and resume."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from knowledge_base.pipeline_v10 import build_case
from knowledge_base.pipeline_v13 import (_compatible_candidates,
                                          _local_revision_candidates)
from knowledge_base.schema_v13 import (classification_schema, extraction_schema,
    navigation_schema, validate, validate_classification)
from knowledge_base.source import load_source, save, source_structure


def _row(root: Path) -> dict:
    source = root / "case.txt"
    source.write_text("\n\n".join(
        f"[{number}] The court applies rule {number}. Notice condition {number}."
        for number in range(7)), encoding="utf-8")
    return {"case_id": "sample", "source": str(source),
            "source_hash": load_source(source)[1]}


def _finish(manifest: dict) -> dict:
    unread = manifest["unread_window_ids"]
    return {"reading_decision": {"action": "finish_phase",
        "reason": "source considered", "unresolved_needs": [],
        "unread_assessment": ([{"window_ids": unread,
            "reason": "no relevant rule expected"}] if unread else [])}}


class Endpoint:
    def __init__(self, *, create_in_selection=True, fail_phase=None,
                 invalid_extract=False, reread=False):
        self.calls = []
        self.create_in_selection = create_in_selection
        self.fail_phase = fail_phase
        self.invalid_extract = invalid_extract
        self.reread = reread
        self.failed = False
        self.reread_done = False

    def complete(self, model, system, payload, *, response_format, **kwargs):
        manifest = payload["manifest"]
        phase = manifest["phase"]
        self.calls.append((phase, manifest))
        assert response_format["json_schema"]["schema"] == manifest["schema"]
        if phase == self.fail_phase and not self.failed:
            self.failed = True
            raise RuntimeError("interrupted")
        if phase.endswith("_extract"):
            if self.invalid_extract:
                return {"decisions": {}, "new_items": [],
                    "reading_decision": {"action": "finish_phase"}}
            created = []
            if phase == "selection_extract" and self.create_in_selection:
                anchor = manifest["opened_sources"][0]["sentences"][0]["source_id"]
                created = [{"collection": "aus", "anchor_source_id": anchor,
                            "reason": "legal condition"}]
                self.create_in_selection = False
            return {"decisions": {entry["handle"]: {"choice": "keep",
                        "reason": "supported"} for entry in manifest["items"]},
                    "new_items": created,
                    "batch_assessment": {"reason": "examined legal conditions",
                                         "unresolved_needs": []}}
        if phase.endswith("_navigate"):
            unread = manifest["unread_window_ids"]
            if phase == "reader_navigate" and unread:
                return {"reading_decision": {"action": "read",
                    "window_ids": [unread[0]], "purpose": "inspect middle rule"}}
            if (phase == "selection_navigate" and self.reread and
                    not self.reread_done and manifest["readable_window_ids"]):
                self.reread_done = True
                return {"reading_decision": {"action": "read",
                    "window_ids": [manifest["readable_window_ids"][0]],
                    "purpose": "recheck a condition"}}
            return _finish(manifest)
        if phase == "source_scan":
            return {"choices": {candidate["key"]: "exclude"
                    for candidate in manifest["candidate_sources"]}}
        if phase == "classification":
            return {"decisions": {entry["handle"]: {
                "choice": "classify", "reason": "court reasoning",
                "roles": {source: ("primary" if source == entry["source_ids"][0]
                                  else "context") for source in entry["source_ids"]},
                "attribution": {source: "current_court"
                                for source in entry["source_ids"]}}
                for entry in manifest["items"]}}
        if phase == "treatment":
            return {"decisions": {entry["handle"]: {"choice": "unknown",
                "reason": "no authority relation"} for entry in manifest["items"]}}
        return {"decisions": {entry["handle"]: {"choice": "keep",
            "reason": "grounded"} for entry in manifest["items"]}}


class V13Tests(unittest.TestCase):
    def test_revision_scan_does_not_offer_unrelated_opened_paragraphs(self):
        with tempfile.TemporaryDirectory() as directory:
            row = _row(Path(directory))
            text = load_source(Path(row["source"]))[0]
            paragraphs, units = source_structure(text, row["source_hash"])
            source_map = {unit["source_id"]: unit for unit in units}
            old = paragraphs[0]["source_id"]
            pool = _local_revision_candidates(set(source_map),
                [{"source_id": old, "role": "primary"}], source_map, paragraphs)
            self.assertIn(old, pool)
            self.assertIn(paragraphs[1]["source_id"], pool)
            self.assertNotIn(paragraphs[-1]["source_id"], pool)

    def test_large_classification_schema_is_linear_and_primary_is_checked(self):
        ids = [f"S{number:04d}" for number in range(40)]
        item = {"handle": "I0000", "status": "active", "collection": "aus",
                "source_ids": ids}
        schema = classification_schema([item])
        self.assertLess(len(json.dumps(schema)), 15000)
        decision = {"choice": "classify", "reason": "court reasoning",
            "roles": {source: "context" for source in ids},
            "attribution": {source: "current_court" for source in ids}}
        decision["roles"][ids[0]] = "primary"
        response = {"decisions": {"I0000": decision}}
        self.assertFalse(validate(response, schema))
        self.assertFalse(validate_classification(response, [item]))
        decision["roles"][ids[1]] = "primary"
        self.assertTrue(validate_classification(response, [item]))

    def test_atomic_save_recovers_from_transient_windows_replace_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "checkpoint.json"
            original = Path.replace
            attempts = []

            def transient_denial(path, destination):
                attempts.append(destination)
                if len(attempts) == 1:
                    raise PermissionError("transient file lock")
                return original(path, destination)

            with patch.object(Path, "replace", transient_denial), patch(
                    "knowledge_base.source.time.sleep") as delay:
                save(target, {"revision": 2})
            self.assertEqual(len(attempts), 2)
            delay.assert_called_once()
            self.assertEqual(json.loads(target.read_text("utf-8")), {"revision": 2})

    def test_candidate_pool_cannot_offer_parent_and_child_together(self):
        with tempfile.TemporaryDirectory() as directory:
            row = _row(Path(directory))
            text = load_source(Path(row["source"]))[0]
            paragraphs, units = source_structure(text, row["source_hash"])
            source_map = {unit["source_id"]: unit for unit in units}
            all_ids = set(source_map)
            paragraph_anchor = paragraphs[2]["source_id"]
            paragraph_pool = _compatible_candidates(all_ids,
                [{"source_id": paragraph_anchor, "role": "primary"}], source_map)
            self.assertTrue(paragraph_pool)
            self.assertTrue(all(source_map[source]["unit_type"] == "paragraph"
                                for source in paragraph_pool))
            sentence_anchor = paragraphs[2]["sentence_ids"][0]
            sentence_pool = _compatible_candidates(all_ids,
                [{"source_id": sentence_anchor, "role": "primary"}], source_map)
            self.assertTrue(sentence_pool)
            parent = source_map[sentence_anchor]["parent_id"]
            self.assertTrue(all(source_map[source]["unit_type"] ==
                ("sentence" if (source_map[source].get("parent_id") or source)
                 == parent else "paragraph") for source in sentence_pool))

    def test_phase_schemas_do_not_mix_source_and_reading_choices(self):
        extraction = extraction_schema([], ["S0001"])
        self.assertNotIn("reading_decision", extraction["properties"])
        self.assertEqual(set(extraction["properties"]),
                         {"decisions", "new_items", "batch_assessment"})
        navigation = navigation_schema([2], [2])
        self.assertEqual(set(navigation["properties"]), {"reading_decision"})
        self.assertTrue(validate({"decisions": {}, "new_items": [],
            "reading_decision": {"action": "finish_phase"}}, extraction))
        self.assertFalse(validate({"decisions": {}, "new_items": [],
            "batch_assessment": {"reason": "no supported item",
                                 "unresolved_needs": []}}, extraction))

    def test_empty_reader_still_gives_selection_exact_source_and_scans(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = _row(root)
            endpoint = Endpoint()
            output = root / "pilot_v13/calibration/sample"
            result = build_case(row, endpoint, {"reader": "mock", "repair": "mock"},
                                70, 6, output, "candidate-separated")
            self.assertEqual(result["schema_version"], 13)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(len(result["aus"]), 1)
            self.assertGreater(result["counts"]["source_scan_requests"], 0)
            self.assertEqual(result["counts"]["source_groups_provided"],
                             result["counts"]["source_groups_processed"])
            selection = next(manifest for phase, manifest in endpoint.calls
                             if phase == "selection_extract")
            self.assertGreater(len(selection["opened_sources"]), 0)
            self.assertGreater(len(selection["schema"]["properties"]["new_items"]
                                   ["items"]["properties"]["anchor_source_id"]["enum"]), 0)
            for excerpt in result["aus"][0]["excerpts"]:
                text = load_source(Path(row["source"]))[0]
                self.assertEqual(excerpt["text"], text[excerpt["start"]:excerpt["end"]])
            count = len(endpoint.calls)
            self.assertEqual(build_case(row, endpoint, {"reader": "mock",
                "repair": "mock"}, 70, 6, output,
                "candidate-separated")["history"], result["history"])
            self.assertEqual(len(endpoint.calls), count)

    def test_considered_empty_output_keeps_assessments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build_case(_row(root), Endpoint(create_in_selection=False),
                {"reader": "mock", "repair": "mock"}, 70, 6,
                root / "pilot_v13/calibration/sample", "candidate-separated")
            self.assertEqual(result["output_status"], "empty_output")
            self.assertEqual(result["quality_status"], "not_evaluated")
            self.assertGreater(len(result["batch_assessments"]), 0)
            self.assertEqual(result["counts"]["source_groups_provided"],
                             result["counts"]["source_groups_processed"])

    def test_invalid_extraction_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            endpoint = Endpoint(invalid_extract=True)
            result = build_case(_row(root), endpoint,
                {"reader": "mock", "repair": "mock"}, 70, 6,
                root / "pilot_v13/calibration/sample", "candidate-separated")
            self.assertEqual(result["execution_status"], "incomplete")
            self.assertTrue(result["protocol_errors"])
            self.assertEqual(len(endpoint.calls), 1)
            self.assertEqual(result["counts"]["source_groups_processed"], 0)

    def test_reread_is_examined_and_does_not_raise_unique_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build_case(_row(root), Endpoint(reread=True),
                {"reader": "mock", "repair": "mock"}, 70, 6,
                root / "pilot_v13/calibration/sample", "candidate-separated")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["counts"]["reread_actions"], 1)
            self.assertEqual(result["counts"]["source_groups_provided"],
                             result["counts"]["source_groups_processed"])
            self.assertEqual(result["source_coverage"]["provided_source_count"],
                             result["source_coverage"]["total_source_count"])

    def test_resume_at_navigation_does_not_repeat_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = _row(root)
            output = root / "pilot_v13/calibration/sample"
            first = Endpoint(fail_phase="reader_navigate")
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                build_case(row, first, {"reader": "mock", "repair": "mock"},
                           70, 6, output, "candidate-separated")
            checkpoint = json.loads((output / "checkpoint.json").read_text("utf-8"))
            self.assertEqual(checkpoint["stage"], "reader_navigate")
            self.assertEqual(len(checkpoint["batch_assessments"]), 1)
            second = Endpoint()
            result = build_case(row, second, {"reader": "mock", "repair": "mock"},
                                70, 6, output, "candidate-separated")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(len([phase for phase, _ in first.calls
                                  if phase == "reader_extract"]), 1)
            self.assertEqual(len([phase for phase, _ in second.calls
                                  if phase == "reader_extract"]),
                             result["counts"]["source_groups_processed"] - 1)
