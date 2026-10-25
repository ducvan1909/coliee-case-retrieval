"""V12 candidate decisions are bounded per response, not per KB item."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from knowledge_base.capability_v12 import probe
from knowledge_base.pipeline_v10 import build_case
from knowledge_base.schema_v12 import (SOURCE_BATCH_SIZE, build_schema,
    build_source_scan_schema, validate, validate_treatment_evidence)
from knowledge_base.source import load_source


def finish(manifest):
    unread = manifest["unread_window_ids"]
    return {"action": "finish_phase", "reason": "legal sections reviewed",
        "unresolved_needs": [], "unread_assessment": (
            [{"window_ids": unread, "reason": "not needed for this item"}]
            if unread else [])}


class CandidateEndpoint:
    def __init__(self, *, invalid_scan=False, fail_scan_at=None):
        self.calls = []
        self.selected_sentences = 0
        self.invalid_scan = invalid_scan
        self.fail_scan_at = fail_scan_at
        self.scan_calls = 0

    def complete(self, model, system, payload, *, response_format, **kwargs):
        manifest = payload["manifest"]
        phase = manifest["phase"]
        self.calls.append((phase, manifest))
        assert response_format["json_schema"]["schema"] == manifest["schema"]
        if phase == "source_scan":
            self.scan_calls += 1
            if self.fail_scan_at == self.scan_calls:
                raise RuntimeError("simulated interruption")
            choices = {}
            for candidate in manifest["candidate_sources"]:
                include = (candidate["unit_type"] == "sentence" and
                           self.selected_sentences < 5)
                choices[candidate["key"]] = "include" if include else "exclude"
                self.selected_sentences += include
            if self.invalid_scan:
                choices["P0029"] = "include"
            return {"choices": choices}
        response = {"decisions": {}}
        if phase in {"reader", "selection"}:
            response["new_items"] = []
            response["reading_decision"] = finish(manifest)
            if phase == "reader":
                paragraphs = manifest["opened_sources"]
                anchor = paragraphs[len(paragraphs) // 2]["sentences"][0]["source_id"]
                response["new_items"] = [{"collection": "aus",
                    "anchor_source_id": anchor, "reason": "legal rule"}]
            for entry in manifest["items"]:
                response["decisions"][entry["handle"]] = {
                    "choice": "keep", "reason": "supported"}
        elif phase == "classification":
            for entry in manifest["items"]:
                primary = entry["source_ids"][0]
                response["decisions"][entry["handle"]] = {"choice": "classify",
                    "reason": "court rule", "primary_source_id": primary,
                    "roles": {source: "context" for source in entry["source_ids"]
                              if source != primary},
                    "attribution": {source: "current_court"
                                    for source in entry["source_ids"]}}
        elif phase == "treatment":
            for entry in manifest["items"]:
                response["decisions"][entry["handle"]] = {
                    "choice": "unknown", "reason": "no authority treatment asserted"}
        elif phase == "finalizer":
            for entry in manifest["items"]:
                response["decisions"][entry["handle"]] = {
                    "choice": "keep", "reason": "grounded"}
        return response


class V12Tests(unittest.TestCase):
    def _case(self, root: Path):
        source = root / "case.txt"
        source.write_text("\n\n".join(
            f"[{index}] Rule {index}. Condition {index}. Court applies rule {index}."
            for index in range(16)), encoding="utf-8")
        return {"case_id": "sample", "source": str(source),
                "source_hash": load_source(source)[1]}

    def test_schema_does_not_ask_model_to_write_source_id_lists(self):
        item = {"handle": "I0000", "status": "active", "collection": "aus",
                "source_ids": ["S0001", "S0002"]}
        reader = build_schema("reader", [item], ["S0001", "S0002"], [], [])
        branches = reader["properties"]["decisions"]["properties"]["I0000"]["oneOf"]
        scan = next(branch for branch in branches
                    if branch["properties"]["choice"].get("const") == "scan_sources")
        self.assertEqual(set(scan["properties"]), {"choice", "reason"})
        self.assertEqual(set(reader["properties"]["new_items"]["items"]["properties"]),
                         {"collection", "anchor_source_id", "reason"})
        treatment = build_schema("treatment", [item], ["S0001", "S0002"])
        apply = treatment["properties"]["decisions"]["properties"]["I0000"]["oneOf"][1]
        self.assertEqual(set(apply["properties"]), {"choice", "reason", "evidence"})
        response = {"decisions": {"I0000": {"choice": "applies", "reason": "used",
            "evidence": {"S0001": "authority", "S0002": "response"}}}}
        self.assertFalse(validate(response, treatment))
        self.assertFalse(validate_treatment_evidence(response, [item]))
        response["decisions"]["I0000"]["evidence"]["S0002"] = "none"
        self.assertTrue(validate_treatment_evidence(response, [item]))

    def test_scan_schema_is_fixed_to_host_keys(self):
        schema = build_source_scan_schema(SOURCE_BATCH_SIZE)
        valid = {"choices": {f"C{index}": "exclude"
                             for index in range(SOURCE_BATCH_SIZE)}}
        self.assertFalse(validate(valid, schema))
        valid["choices"]["P0029"] = "include"
        self.assertTrue(validate(valid, schema))
        valid["choices"].pop("P0029")
        valid["choices"].pop("C11")
        self.assertTrue(validate(valid, schema))

    def test_capability_probe_resumes_without_repeating_completed_probe(self):
        class ProbeEndpoint:
            def __init__(self, fail_at=None):
                self.calls = []
                self.fail_at = fail_at

            def complete(self, model, system, payload, **kwargs):
                self.calls.append(payload["phase"])
                if len(self.calls) == self.fail_at:
                    raise RuntimeError("interrupted probe")
                phase = payload["phase"]
                if phase == "source_scan":
                    return {"choices": {f"C{index}": (
                        "include" if index in {0, 11} else "exclude")
                        for index in range(SOURCE_BATCH_SIZE)}}
                if phase == "reader":
                    readable = payload["readable_window_ids"]
                    decision = ({"action": "read", "window_ids": [2],
                        "purpose": "inspect legal rule"} if readable else
                        {"action": "finish_phase", "reason": "source reviewed",
                         "unresolved_needs": [], "unread_assessment": [
                            {"window_ids": [2], "reason": "not needed"}]})
                    return {"decisions": {}, "new_items": [],
                            "reading_decision": decision}
                if phase == "selection":
                    return {"decisions": {"I0000": {"choice": "scan_sources",
                        "reason": "inspect evidence"}}, "new_items": [],
                        "reading_decision": {"action": "finish_phase",
                            "reason": "enough", "unresolved_needs": [],
                            "unread_assessment": [{"window_ids": [2],
                                                   "reason": "not needed"}]}}
                if phase == "treatment":
                    return {"decisions": {"I0000": {"choice": "applies",
                        "reason": "supported", "evidence": {
                            "S0001": "authority", "S0002": "response"}}}}
                if phase == "classification":
                    return {"decisions": {"I0000": {"choice": "defer",
                        "reason": "uncertain"}}}
                return {"decisions": {"I0000": {"choice": "keep",
                    "reason": "supported"}}}

        with tempfile.TemporaryDirectory() as directory:
            experiment = Path(directory)
            first = ProbeEndpoint(fail_at=2)
            with self.assertRaisesRegex(RuntimeError, "interrupted probe"):
                probe(first, {"reader": "mock"}, experiment, {"version": 12})
            self.assertEqual(len(first.calls), 2)
            second = ProbeEndpoint()
            result = probe(second, {"reader": "mock"}, experiment,
                           {"version": 12})
            self.assertEqual(result["status"], "passed")
            self.assertEqual(len(second.calls), 6)

    def test_more_than_four_sources_are_accumulated_across_scan_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self._case(root)
            endpoint = CandidateEndpoint()
            output = root / "pilot_v12/calibration/sample"
            result = build_case(row, endpoint, {"reader": "mock", "repair": "mock"},
                                10000, 6, output, "candidate")
            self.assertEqual(result["schema_version"], 12)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["protocol_status"], "valid")
            self.assertEqual(len(result["aus"]), 1)
            self.assertEqual(len(result["aus"][0]["source_refs"]), 6)
            self.assertEqual(len({ref["source_id"] for ref in
                                  result["aus"][0]["source_refs"]}), 6)
            self.assertGreaterEqual(result["counts"]["source_scan_requests"], 2)
            text = load_source(Path(row["source"]))[0]
            for excerpt in result["aus"][0]["excerpts"]:
                self.assertEqual(excerpt["text"], text[excerpt["start"]:excerpt["end"]])
            call_count = len(endpoint.calls)
            resumed = build_case(row, endpoint, {"reader": "mock", "repair": "mock"},
                                 10000, 6, output, "candidate")
            self.assertEqual(len(endpoint.calls), call_count)
            self.assertEqual(resumed["history"], result["history"])

    def test_invalid_scan_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self._case(root)
            output = root / "pilot_v12/calibration/sample"
            result = build_case(row, CandidateEndpoint(invalid_scan=True),
                {"reader": "mock", "repair": "mock"}, 10000, 6, output, "candidate")
            self.assertEqual(result["execution_status"], "incomplete")
            self.assertEqual(result["aus"][0]["revision"], 1)
            self.assertEqual(len(result["aus"][0]["source_refs"]), 1)
            self.assertTrue(result["protocol_errors"])

    def test_resume_continues_after_applied_scan_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self._case(root)
            output = root / "pilot_v12/calibration/sample"
            first = CandidateEndpoint(fail_scan_at=2)
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                build_case(row, first, {"reader": "mock", "repair": "mock"},
                           10000, 6, output, "candidate")
            checkpoint = json.loads((output / "checkpoint.json").read_text("utf-8"))
            self.assertEqual(checkpoint["stage"], "source_scan")
            self.assertEqual(checkpoint["source_scan_turn"], 1)
            second = CandidateEndpoint()
            second.selected_sentences = first.selected_sentences
            result = build_case(row, second, {"reader": "mock", "repair": "mock"},
                                10000, 6, output, "candidate")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(len(result["aus"]), 1)
            self.assertEqual(len(result["aus"][0]["source_refs"]), 6)
            self.assertEqual(result["counts"]["source_scan_requests"],
                             len([phase for phase, _ in first.calls if phase == "source_scan"])
                             - 1 + len([phase for phase, _ in second.calls
                                        if phase == "source_scan"]))

    def test_scan_request_limit_does_not_silently_truncate_item(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self._case(root)
            output = root / "pilot_v12/calibration/sample"
            result = build_case(row, CandidateEndpoint(),
                {"reader": "mock", "repair": "mock", "max_source_scan_requests": 1},
                10000, 6, output, "candidate")
            self.assertEqual(result["execution_status"], "incomplete")
            self.assertEqual(result["stop_reason"], "source_scan_request_limit")
            self.assertEqual(result["counts"]["source_scan_requests"], 1)
            self.assertEqual(len(result["aus"][0]["source_refs"]), 1)

    def test_existing_item_source_revision_uses_candidate_batches(self):
        class RevisionEndpoint(CandidateEndpoint):
            def __init__(self):
                super().__init__()
                self.extra_added = False

            def complete(self, model, system, payload, **kwargs):
                manifest = payload["manifest"]
                phase = manifest["phase"]
                if phase == "source_scan" and manifest["selection_origin"]["kind"] == "revision":
                    self.calls.append((phase, manifest))
                    old = {ref["source_id"] for ref in manifest["item"]["source_refs"]}
                    choices = {}
                    for candidate in manifest["candidate_sources"]:
                        include = candidate["source_id"] in old
                        if (not include and not self.extra_added and
                                candidate["unit_type"] == "sentence"):
                            include = self.extra_added = True
                        choices[candidate["key"]] = "include" if include else "exclude"
                    return {"choices": choices}
                response = super().complete(model, system, payload, **kwargs)
                if phase == "selection":
                    handle = manifest["items"][0]["handle"]
                    response["decisions"][handle] = {"choice": "scan_sources",
                        "reason": "add a missing condition"}
                return response

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self._case(root)
            output = root / "pilot_v12/calibration/sample"
            result = build_case(row, RevisionEndpoint(),
                {"reader": "mock", "repair": "mock"},
                10000, 6, output, "candidate")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(len(result["aus"][0]["source_refs"]), 7)
            self.assertEqual(result["aus"][0]["revision"], 5)
            self.assertEqual(len({ref["source_id"] for ref in
                                  result["aus"][0]["source_refs"]}), 7)
