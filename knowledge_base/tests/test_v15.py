"""V15 two-stage triage and pipeline regressions."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from knowledge_base.capability_v15 import _cases as capability_cases
from knowledge_base.pipeline_v10 import build_case
from knowledge_base.schema_v15 import (refinement_schema, triage_schema,
    validate, validate_refinement)
from knowledge_base.source import load_source


def _row(root: Path) -> dict:
    source = root / "case.txt"
    source.write_text("REASONS FOR JUDGMENT\n\n"
        "[1] Background facts. A claimant must give notice before seeking relief.\n\n"
        "[2] The notice condition applies only after service.\n\n"
        "[3] The court applies that condition to the missing notice.\n\n"
        "[4] The appeal is allowed.", encoding="utf-8")
    return {"case_id": "sample", "source": str(source),
            "source_hash": load_source(source)[1]}


class Endpoint:
    def __init__(self, *, invalid_refinement=False, fail_once=None):
        self.calls = []
        self.invalid_refinement = invalid_refinement
        self.fail_once = fail_once
        self.failed = False

    def complete(self, model, system, payload, *, response_format, **kwargs):
        manifest = payload["manifest"]
        phase = manifest["phase"]
        self.calls.append((phase, manifest, response_format))
        self.assert_contract(manifest, response_format)
        if phase == self.fail_once and not self.failed:
            self.failed = True
            raise RuntimeError("interrupted")
        if phase.endswith("_triage"):
            choices = {}
            for source in manifest["candidate_paragraph_ids"]:
                paragraph = next(value for value in manifest["opened_sources"]
                                 if value["source_id"] == source)
                if "Background facts" in paragraph["text"]:
                    choices[source] = "refine_sentences"
                elif "condition applies" in paragraph["text"] or "court applies" in paragraph["text"]:
                    choices[source] = "aus"
                elif "appeal is allowed" in paragraph["text"]:
                    choices[source] = "brief"
                else:
                    choices[source] = "skip"
            return {"choices": choices}
        if phase.endswith("_refine"):
            choices = {sentence["source_id"]: "skip"
                for paragraph in manifest["opened_sources"]
                for sentence in paragraph["sentences"]}
            if not self.invalid_refinement:
                for paragraph in manifest["opened_sources"]:
                    choices[paragraph["sentences"][-1]["source_id"]] = "aus"
            return {"choices": choices}
        if phase.endswith("_navigate"):
            return {"reading_decision": {"action": "finish_phase",
                                         "reason": "opened source was triaged"}}
        if phase == "selection_review":
            return {"decisions": {item["handle"]: {"choice": "keep"}
                    for item in manifest["items"]}}
        if phase == "source_scan":
            raise AssertionError("V15 must not scan newly added items automatically")
        if phase == "classification":
            decisions = {}
            attribution = {}
            for item in manifest["items"]:
                attribution.update({source: "current_court"
                                    for source in item["source_ids"]})
                if item["status"] == "deferred":
                    decisions[item["handle"]] = {"choice": "keep"}
                elif item["collection"] == "brief":
                    decisions[item["handle"]] = {"choice": "classify",
                                                  "kind": "disposition"}
                else:
                    decisions[item["handle"]] = {"choice": "classify",
                        "roles": {source: ("primary" if index == 0 else "context")
                                  for index, source in enumerate(item["source_ids"])}}
            return {"attribution_by_source": attribution, "decisions": decisions}
        if phase == "treatment":
            return {"decisions": {item["handle"]: {"choice": "unknown"}
                    for item in manifest["items"] if item["collection"] == "aus"
                    and item["status"] == "active"}}
        return {"decisions": {item["handle"]: {"choice": "keep"}
                for item in manifest["items"]}}

    @staticmethod
    def assert_contract(manifest, response_format):
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True


class V15Tests(unittest.TestCase):
    def test_stage_schemas_never_mix_parent_and_sentence_keys(self):
        paragraphs = [{"source_id": f"P{index:04d}", "sentences": [
            {"source_id": f"S{index:04d}_0"}, {"source_id": f"S{index:04d}_1"}]}
            for index in range(4)]
        triage = triage_schema(paragraphs)
        self.assertEqual(set(triage["properties"]["choices"]["properties"]),
                         {f"P{index:04d}" for index in range(4)})
        refine = refinement_schema(paragraphs)
        self.assertTrue(all(key.startswith("S") for key in
                            refine["properties"]["choices"]["properties"]))
        self.assertFalse(any(key.startswith("P") for key in
                             refine["properties"]["choices"]["properties"]))
        invalid = {"choices": {f"P{index:04d}": "skip" for index in range(5)}}
        self.assertTrue(validate(invalid, triage))

    def test_refinement_requires_a_selection_for_every_parent(self):
        paragraphs = [{"source_id": "P0001", "sentences": [
            {"source_id": "S0001_0"}, {"source_id": "S0001_1"}]},
            {"source_id": "P0002", "sentences": [
                {"source_id": "S0002_0"}]}]
        schema = refinement_schema(paragraphs)
        response = {"choices": {"S0001_0": "aus", "S0001_1": "skip",
                                  "S0002_0": "skip"}}
        self.assertFalse(validate(response, schema))
        self.assertEqual(validate_refinement(response, paragraphs)[0][
                         "error_code"], "empty_sentence_selection")

    def test_pipeline_batches_four_and_materializes_exact_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = _row(root)
            endpoint = Endpoint()
            result = build_case(current, endpoint,
                {"reader": "mock", "repair": "mock", "max_source_scan_requests": 24},
                10000, 6, root / "pilot_v15/calibration/sample",
                "two-stage-candidates")
            self.assertEqual(result["schema_version"], 15)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["output_status"], "nonempty")
            self.assertEqual(result["counts"]["source_scan_requests"], 0)
            triage = [manifest for phase, manifest, _ in endpoint.calls
                      if phase.endswith("_triage")]
            self.assertGreaterEqual(len(triage), 2)
            self.assertTrue(all(len(batch["candidate_paragraph_ids"]) <= 4
                                for batch in triage))
            text = load_source(current["source"])[0]
            for item in [*result["brief"], *result["aus"]]:
                for excerpt in item["excerpts"]:
                    self.assertEqual(excerpt["text"],
                                     text[excerpt["start"]:excerpt["end"]])
            self.assertEqual(len(result["history"]),
                             len({(event["id"], event["revision"])
                                  for event in result["history"]}))

    def test_invalid_refinement_is_atomic_and_output_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build_case(_row(root), Endpoint(invalid_refinement=True),
                {"reader": "mock", "repair": "mock", "max_source_scan_requests": 24},
                10000, 6, root / "pilot_v15/calibration/sample",
                "two-stage-candidates")
            self.assertEqual(result["execution_status"], "incomplete")
            self.assertEqual(result["output_status"], "incomplete")
            self.assertTrue(result["protocol_errors"])
            self.assertFalse(any(event["reason"] == "v15_sentence_refinement"
                                 for event in result["history"]))

    def test_empty_output_requires_omission_review_and_keeps_uncertain_count(self):
        class AllSkip(Endpoint):
            def complete(self, model, system, payload, *, response_format, **kwargs):
                manifest = payload["manifest"]
                phase = manifest["phase"]
                self.calls.append((phase, manifest, response_format))
                if phase.endswith("_triage"):
                    choices = {source: "skip" for source in
                               manifest["candidate_paragraph_ids"]}
                    choices[manifest["candidate_paragraph_ids"][-1]] = "uncertain"
                    return {"choices": choices}
                if phase.endswith("_navigate"):
                    return {"reading_decision": {"action": "finish_phase",
                                                  "reason": "triage complete"}}
                return super().complete(model, system, payload,
                                        response_format=response_format, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build_case(_row(root), AllSkip(),
                {"reader": "mock", "repair": "mock", "max_source_scan_requests": 24},
                10000, 6, root / "pilot_v15/calibration/sample",
                "two-stage-candidates")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["output_status"], "empty_output")
            self.assertTrue(result["omission_review_required"])
            self.assertGreater(result["candidate_uncertain_count"], 0)

    def test_resume_reuses_applied_triage_without_duplicate_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "pilot_v15/calibration/sample"
            endpoint = Endpoint(fail_once="reader_refine")
            with self.assertRaises(RuntimeError):
                build_case(_row(root), endpoint,
                    {"reader": "mock", "repair": "mock",
                     "max_source_scan_requests": 24}, 10000, 6, output,
                    "two-stage-candidates")
            triage_calls = sum(phase.endswith("_triage")
                               for phase, _, _ in endpoint.calls)
            result = build_case(_row(root), endpoint,
                {"reader": "mock", "repair": "mock", "max_source_scan_requests": 24},
                10000, 6, output, "two-stage-candidates")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(sum(phase.endswith("_triage")
                                 for phase, _, _ in endpoint.calls), triage_calls)
            signatures = [(event["id"], event["revision"])
                          for event in result["history"]]
            self.assertEqual(len(signatures), len(set(signatures)))

    def test_capability_gate_has_exact_eleven_phase_contracts(self):
        cases = capability_cases()
        self.assertEqual(len(cases), 11)
        self.assertEqual([case[0] for case in cases[:3]],
                         ["triage_four", "refinement", "triage_all_skip"])


if __name__ == "__main__":
    unittest.main()

