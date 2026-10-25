"""V10 constrained-choice contract and transactional host behavior."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge_base.pipeline_v10 as pipeline_v10
from knowledge_base.capability_v10 import _probe_request_id, probe
from knowledge_base.comparison import export_review
from knowledge_base.pipeline_v10 import build_case
from knowledge_base.schema_v10 import build_schema, validate
from knowledge_base.source import (load_source, source_handles, source_structure,
                                   structure_catalogue, structure_windows)
from knowledge_base.state_v9 import initial_state


class FakeEndpoint:
    def __init__(self, bad=False):
        self.bad = bad
        self.calls = []

    def complete(self, model, system, payload, *, response_format, **kwargs):
        manifest = payload["manifest"]
        phase, entries = manifest["phase"], manifest["items"]
        schema = response_format["json_schema"]["schema"]
        assert schema == manifest["schema"]
        self.calls.append(phase)
        decisions = {}
        for entry in entries:
            handle = entry["handle"]
            if phase == "classification":
                if entry["collection"] == "brief":
                    decisions[handle] = {"choice": "classify", "reason": "issue stated",
                        "kind": "issues", "attribution": {source: "current_court"
                            for source in entry["source_ids"]}}
                else:
                    first = entry["source_ids"][0]
                    decisions[handle] = {"choice": "classify", "reason": "legal rule",
                        "primary_source_id": first,
                        "roles": {source: "context" for source in entry["source_ids"]
                                  if source != first},
                        "attribution": {source: "current_court"
                            for source in entry["source_ids"]}}
            elif phase == "treatment":
                if entry["collection"] == "aus" and entry["status"] == "active":
                    decisions[handle] = {"choice": "unknown", "reason": "no authority"}
            else:
                decisions[handle] = {"choice": "keep", "reason": "supported"}
        response = {"decisions": decisions}
        if phase == "reader":
            source = manifest["opened_sources"][0]["sentences"][0]["source_id"]
            response["new_items"] = [{"collection": "brief", "source_ids": [source],
                "reason": "issue candidate"}, {"collection": "aus",
                "source_ids": [source], "reason": "legal reasoning candidate"}]
            if self.bad:
                response["new_items"][1]["source_ids"] = ["S9999"]
        elif phase == "selection":
            response["new_items"] = []
        if "read_window_ids" in schema["properties"]:
            response["read_window_ids"] = []
        return response


class V10Tests(unittest.TestCase):
    def _case(self, fake):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.txt"
            source.write_text("A legal question is before this court.\n\n"
                "A legal principle is discussed by this court.", encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            output = root / "pilot_v10" / "calibration" / "099980"
            result = build_case(row, fake, {"reader": "mock", "repair": "mock"},
                                60, 2, output)
            checkpoint = json.loads((output / "checkpoint.json").read_text("utf-8"))
            return result, checkpoint

    def test_phase_schemas_exclude_forbidden_actions_and_wrong_handles(self):
        item = [{"handle": "I0000", "status": "active", "collection": "aus",
                 "source_ids": ["S0001", "S0002"]}]
        continuation = build_schema("selection", item, ["S0001", "S0002"], None)
        self.assertNotIn("read_window_ids", continuation["properties"])
        finalizer = build_schema("finalizer", item, ["S0001", "S0002"])
        self.assertNotIn("new_items", finalizer["properties"])
        self.assertTrue(validate({"decisions": {}}, finalizer))
        self.assertTrue(validate({"decisions": {"I0000": {"choice": "keep",
            "reason": "x"}, "I9999": {"choice": "keep", "reason": "x"}}}, finalizer))
        treatment = build_schema("treatment", item, ["S0001", "S0002"])
        self.assertFalse(validate({"decisions": {"I0000": {"choice": "applies",
            "reason": "both stated", "authority_source_ids": ["S0001"],
            "response_source_ids": ["S0001"]}}}, treatment))
        self.assertTrue(validate({"decisions": {"I0000": {"choice": "applies",
            "reason": "x", "authority_source_ids": ["S0001"],
            "response_source_ids": ["S9999"]}}}, treatment))

    def test_end_to_end_compiles_choices_and_preserves_exact_source(self):
        result, checkpoint = self._case(FakeEndpoint())
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["quality_status"], "not_evaluated")
        self.assertEqual((len(result["brief"]), len(result["aus"])), (1, 1))
        self.assertEqual(result["brief"][0]["kind"], "issues")
        self.assertEqual(len(result["history"]), 5)
        self.assertEqual(checkpoint["stage"], "complete")
        self.assertEqual(set(checkpoint["request_journal"]),
                         {"reader:0", "selection:0", "classification:0",
                          "treatment:0", "finalizer:0"})
        for item in result["brief"] + result["aus"]:
            self.assertEqual(item["excerpts"][0]["text"],
                             "A legal question is before this court.")
            self.assertEqual(item["excerpts"][0]["start"], 0)

    def test_invalid_response_applies_nothing_and_stops(self):
        result, checkpoint = self._case(FakeEndpoint(bad=True))
        self.assertEqual(result["output_status"], "incomplete")
        self.assertEqual(result["history"], [])
        self.assertEqual(checkpoint["stage"], "incomplete")
        self.assertEqual(len(checkpoint["request_journal"]), 1)

    def test_manifest_sends_new_source_and_current_item_context_only(self):
        text = "\n\n".join(f"Paragraph {index}. Legal sentence {index}."
                           for index in range(12))
        source_hash = pipeline_v10.digest(text.encode("utf-8"))
        paragraphs, units = source_structure(text, source_hash)
        windows = structure_windows(paragraphs, 40)
        source_map = {unit["source_id"]: unit for unit in units}
        handles, inverse = source_handles(units)
        catalogue = structure_catalogue(units, windows)
        older = {0, 1, 2, 3, 4}
        new = {5}
        opened_before = pipeline_v10._opened_ids(windows, older)
        newly_opened = pipeline_v10._opened_ids(windows, new) - opened_before
        opened = opened_before | newly_opened
        selected = paragraphs[1]["source_id"]
        state = initial_state()
        state["items"]["case:aus:000"] = {
            "id": "case:aus:000", "collection": "aus", "revision": 1,
            "status": "active", "source_hash": source_hash,
            "source_refs": [{"source_id": selected, "role": "primary",
                             "attribution": "unknown"}],
            "treatment": {"value": "unknown", "authority_source_ids": [],
                          "response_source_ids": []}}
        checkpoint = {"state": state, "opened_source_ids": sorted(opened),
            "opened_window_ids": sorted(older | new),
            "pending_source_ids": sorted(newly_opened),
            "pending_window_ids": sorted(new)}
        manifest = pipeline_v10._manifest(checkpoint, "selection",
            {"case_id": "case", "source_hash": source_hash}, catalogue,
            source_map, paragraphs, handles, windows, None)
        supplied = {inverse[paragraph["source_id"]]
                    for paragraph in manifest["opened_sources"]}
        self.assertIn(selected, supplied)
        self.assertTrue(newly_opened & supplied)
        unrelated = paragraphs[4]["source_id"]
        self.assertIn(unrelated, opened)
        self.assertNotIn(unrelated, supplied)
        source_options = manifest["schema"]["properties"]["new_items"][
            "items"]["properties"]["source_ids"]["items"]["enum"]
        self.assertNotIn(handles[unrelated], source_options)
        self.assertFalse(validate({"decisions": {"I0000": {
            "choice": "keep", "reason": "selected source remains relevant"}},
            "new_items": [{"collection": "aus", "source_ids": [handles[selected]],
                           "reason": "supported"}]}, manifest["schema"]))
        self.assertTrue(validate({"decisions": {"I0000": {
            "choice": "keep", "reason": "selected source remains relevant"}},
            "new_items": [{"collection": "aus", "source_ids": [handles[unrelated]],
                           "reason": "not supplied"}]}, manifest["schema"]))
        self.assertEqual({window["window_id"] for window in
            manifest["catalogue"]["windows"]},
            {window["window_id"] for window in windows} - (older | new))

    def test_new_window_is_sent_once_and_coverage_tracks_supplied_source(self):
        class ReadingEndpoint(FakeEndpoint):
            def __init__(self):
                super().__init__()
                self.manifests = []

            def complete(self, model, system, payload, **kwargs):
                manifest = payload["manifest"]
                self.manifests.append(manifest)
                response = super().complete(model, system, payload, **kwargs)
                if manifest["phase"] == "reader":
                    if self.calls.count("reader") == 1:
                        response["read_window_ids"] = [manifest["unread_window_ids"][0]]
                    else:
                        response["new_items"] = []
                return response

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.txt"
            source.write_text("\n\n".join(f"Paragraph {number}. Rule {number}."
                                         for number in range(12)), encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            endpoint = ReadingEndpoint()
            result = build_case(row, endpoint, {"reader": "mock", "repair": "mock"},
                                40, 2, root / "pilot_v10/calibration/099980")
            self.assertEqual(result["execution_status"], "completed")
            first, second, selection = endpoint.manifests[:3]
            first_ids = {paragraph["source_id"] for paragraph in first["opened_sources"]}
            second_ids = {paragraph["source_id"] for paragraph in second["opened_sources"]}
            selection_ids = {paragraph["source_id"]
                             for paragraph in selection["opened_sources"]}
            self.assertTrue(second_ids - first_ids)
            self.assertTrue(first_ids - second_ids)
            self.assertFalse((second_ids - first_ids) & selection_ids)
            all_supplied_handles = {
                unit["source_id"] for manifest in endpoint.manifests
                for paragraph in manifest["opened_sources"]
                for unit in [paragraph, *paragraph["sentences"]]}
            self.assertEqual(result["source_coverage"]["provided_source_count"],
                             len(all_supplied_handles))

    def test_capability_probe_request_ids_are_experiment_scoped(self):
        class ProbeEndpoint:
            def __init__(self):
                self.ids = []

            def complete(self, model, system, payload, *, request_id, **kwargs):
                self.ids.append(request_id)
                phase = payload["phase"]
                if phase == "reader":
                    return {"decisions": {}, "new_items": [], "read_window_ids": []}
                if phase == "classification":
                    return {"decisions": {"I0000": {"choice": "defer",
                        "reason": "insufficient source"}}}
                return {"decisions": {"I0000": {"choice": "unknown",
                    "reason": "no authority relation"}}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "experiment_one", root / "experiment_two"
            fingerprint = {"schema_version": 10, "prompt_version": "test"}
            endpoint = ProbeEndpoint()
            self.assertEqual(probe(endpoint, {"reader": "mock"}, first,
                                   fingerprint)["status"], "passed")
            self.assertEqual(probe(endpoint, {"reader": "mock"}, second,
                                   fingerprint)["status"], "passed")
            self.assertEqual(len(endpoint.ids), 6)
            self.assertEqual(len(set(endpoint.ids)), 6)
            self.assertNotEqual(_probe_request_id(first, fingerprint, 0,
                build_schema("reader", [], ["S0001", "S0002"], [2])),
                "v10:capability:0:e227aaea75c3d2085e20")
            probe(endpoint, {"reader": "mock"}, first, fingerprint)
            self.assertEqual(len(endpoint.ids), 6)

    def test_v10_comparison_exports_stable_source_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.txt"
            source.write_text("The Court applies a legal rule.", encoding="utf-8")
            text, source_hash = load_source(source)
            _, units = source_structure(text, source_hash)
            sentence = next(unit for unit in units if unit["unit_type"] == "sentence")
            experiment = root / "experiment"
            case_dir = experiment / "calibration" / "099980"
            case_dir.mkdir(parents=True)
            (case_dir / "case.json").write_text(json.dumps({
                "schema_version": 10, "case_id": "099980", "source": str(source),
                "source_hash": source_hash, "brief": [], "aus": [{"id": "au-1",
                    "collection": "aus", "excerpts": [{"source_id": sentence["source_id"],
                        "start": sentence["start"], "end": sentence["end"]}]}]
            }), encoding="utf-8")
            kos_dir = root / "kos" / "cases" / "099980"
            (kos_dir / "authority_units").mkdir(parents=True)
            (kos_dir / "CASE.md").write_text("role: candidate\n", encoding="utf-8")
            (kos_dir / "authority_units" / "au.md").write_text(
                "## Evidence span\n> The Court applies a legal rule.\n",
                encoding="utf-8")
            bundle = json.loads(export_review(experiment, root / "kos").read_text(
                encoding="utf-8"))
            self.assertEqual(bundle["schema_version"], 10)
            self.assertEqual(bundle["cases"][0]["final_source_locations"][0][
                "sources"][0]["source_id"], sentence["source_id"])
            self.assertIn(sentence["source_id"], bundle["cases"][0][
                "legacy_aus"][0]["source_location"]["source_ids"])

    def test_resume_after_response_receipt_does_not_call_reader_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.txt"
            source.write_text("The court addresses a legal rule.", encoding="utf-8")
            row = {"case_id": "099980", "source": str(source),
                   "source_hash": load_source(source)[1]}
            output = root / "pilot_v10/calibration/099980"
            fake = FakeEndpoint()
            original_save = pipeline_v10.save
            interrupted = False

            def save_then_interrupt(path, value):
                nonlocal interrupted
                original_save(path, value)
                if (not interrupted and Path(path) == output / "checkpoint.json" and
                        value.get("request_journal", {}).get("reader:0", {}).get(
                            "status") == "received"):
                    interrupted = True
                    raise RuntimeError("simulated crash after response receipt")

            with patch.object(pipeline_v10, "save", side_effect=save_then_interrupt):
                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    build_case(row, fake, {"reader": "mock", "repair": "mock"},
                               100, 2, output)
            self.assertEqual(fake.calls, ["reader"])
            result = build_case(row, fake, {"reader": "mock", "repair": "mock"},
                                100, 2, output)
            self.assertEqual(fake.calls.count("reader"), 1)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(len(result["history"]), 5)


if __name__ == "__main__":
    unittest.main()
