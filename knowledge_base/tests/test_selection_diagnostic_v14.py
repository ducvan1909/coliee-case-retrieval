"""Real-source V14 selection diagnostic stays separate from KB construction."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from knowledge_base.config import ROOT
from knowledge_base.selection_diagnostic_v14 import (CASE_ID, LARGE_IDS,
    SMALL_IDS, SYSTEM, cases, probe)


def case_row():
    manifest = json.loads((ROOT / "outputs/manifest.json").read_text("utf-8"))
    return next(row for row in manifest["cases"] if row["case_id"] == CASE_ID)


class Endpoint:
    def __init__(self, invalid=False):
        self.calls = []
        self.invalid = invalid

    def complete(self, model, system, payload, *, metadata, response_format, **kwargs):
        self.calls.append((system, payload, response_format, metadata))
        if self.invalid:
            return {"choices": {"P9999": "aus"}}
        paragraphs = payload["opened_sources"]
        choices = {paragraph["source_id"]: "skip" for paragraph in paragraphs}
        schema_choices = response_format["json_schema"]["schema"]["properties"][
            "choices"]["properties"]
        for source in schema_choices:
            if source.startswith("S"):
                choices[source] = "skip"
        return {"choices": choices}


class SelectionDiagnosticTests(unittest.TestCase):
    def test_predeclared_real_source_is_not_in_model_payload(self):
        inventory, arms = cases(case_row())
        self.assertEqual(len(arms), 4)
        self.assertEqual([arm["name"] for arm in arms], [
            "small_paragraph", "small_paragraph_sentence",
            "large_paragraph", "large_paragraph_sentence"])
        self.assertEqual(arms[0]["payload"], arms[1]["payload"])
        self.assertEqual(arms[2]["payload"], arms[3]["payload"])
        self.assertEqual([entry["source_id"] for entry in
                          arms[0]["payload"]["opened_sources"]], list(SMALL_IDS))
        self.assertEqual([entry["source_id"] for entry in
                          arms[2]["payload"]["opened_sources"]], list(LARGE_IDS))
        self.assertFalse(set(SMALL_IDS) - set(LARGE_IDS))
        self.assertNotIn("opportunities", json.dumps(arms))
        self.assertIn("do not select a parent and its children together", SYSTEM)
        self.assertEqual(len(inventory["opportunities"]), 4)
        self.assertTrue(all(arm["schema"]["additionalProperties"] is False
                            for arm in arms))
        self.assertEqual(arms[0]["schema"]["properties"]["choices"]["required"],
                         list(SMALL_IDS))

    def test_all_skip_is_recorded_as_semantic_omission_not_protocol_error(self):
        with tempfile.TemporaryDirectory() as directory:
            endpoint = Endpoint()
            experiment = Path(directory)
            fingerprint = {"diagnostic": "test"}
            result = probe(endpoint, {"reader": "mock"}, experiment,
                           fingerprint, case_row())
            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(endpoint.calls), 4)
            self.assertTrue(all(call[0] == SYSTEM for call in endpoint.calls))
            self.assertTrue(all(not arm["protocol_errors"] and
                                arm["assessment"]["positive_hits"] == 0
                                for arm in result["results"]))
            self.assertEqual(probe(endpoint, {"reader": "mock"}, experiment,
                                   fingerprint, case_row()), result)
            self.assertEqual(len(endpoint.calls), 4)

    def test_invalid_schema_stops_without_calling_other_arms(self):
        with tempfile.TemporaryDirectory() as directory:
            endpoint = Endpoint(invalid=True)
            result = probe(endpoint, {"reader": "mock"}, Path(directory),
                           {"diagnostic": "bad"}, case_row())
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(endpoint.calls), 1)
            self.assertTrue(result["results"][0]["protocol_errors"])

    def test_large_only_uses_original_large_arms_without_repeating_small(self):
        with tempfile.TemporaryDirectory() as directory:
            endpoint = Endpoint()
            result = probe(endpoint, {"reader": "mock"}, Path(directory),
                           {"diagnostic": "large"}, case_row(), large_only=True)
            self.assertEqual(result["status"], "complete")
            self.assertEqual([entry["arm_index"] for entry in result["results"]],
                             [2, 3])
            self.assertEqual(len(endpoint.calls), 2)


if __name__ == "__main__":
    unittest.main()
