"""Offline checks for the isolated V14 whole-versus-sentence experiment."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from knowledge_base.choice_diagnostic_v14 import SOURCE, cases, probe
from knowledge_base.endpoint import ModelProtocolError
from knowledge_base.schema_v10 import validate


class ChoiceDiagnosticTests(unittest.TestCase):
    def test_both_probes_use_identical_source_and_exact_dynamic_keys(self):
        whole, sentences = cases()
        self.assertEqual(whole["payload"], sentences["payload"])
        self.assertEqual(set(whole["schema"]["properties"]["choices"][
            "properties"]), {"P0001"})
        self.assertEqual(set(sentences["schema"]["properties"]["choices"][
            "properties"]), {"S0001", "S0002"})
        text = SOURCE["text"]
        self.assertEqual([text[s["start_offset"]:s["end_offset"]]
            for s in SOURCE["sentences"]], [
            "The Court holds that a party must receive notice before removal.",
            "The applicant received no notice."])
        self.assertFalse(validate({"choices": {"P0001": "both"}}, whole["schema"]))
        self.assertFalse(validate({"choices": {"S0001": "aus", "S0002": "brief"}},
                                  sentences["schema"]))
        self.assertTrue(validate({"choices": {"S0001": "aus", "S9999": "brief"}},
                                 sentences["schema"]))

    def test_success_is_cached_in_diagnostic_and_not_replayed(self):
        class Endpoint:
            def __init__(self):
                self.calls = []

            def complete(self, model, system, payload, *, metadata, response_format,
                         **kwargs):
                self.calls.append((model, system, payload, response_format,
                                   metadata["turn"]))
                return ({"choices": {"P0001": "both"}} if metadata["turn"] == 0
                        else {"choices": {"S0001": "aus", "S0002": "brief"}})

        with tempfile.TemporaryDirectory() as directory:
            endpoint = Endpoint()
            root = Path(directory)
            fingerprint = {"diagnostic": "test-v1"}
            self.assertEqual(probe(endpoint, {"reader": "mock"}, root,
                                   fingerprint)["status"], "passed")
            self.assertEqual(probe(endpoint, {"reader": "mock"}, root,
                                   fingerprint)["status"], "passed")
            self.assertEqual(len(endpoint.calls), 2)
            self.assertEqual(endpoint.calls[0][:3], endpoint.calls[1][:3])
            with self.assertRaisesRegex(ValueError, "fingerprint_mismatch"):
                probe(endpoint, {"reader": "mock"}, root, {"diagnostic": "other"})

    def test_truncated_sentence_response_stops_without_replay(self):
        class Endpoint:
            def __init__(self):
                self.turns = []

            def complete(self, model, system, payload, *, metadata, **kwargs):
                self.turns.append(metadata["turn"])
                if metadata["turn"] == 1:
                    raise ModelProtocolError("Model response was truncated")
                return {"choices": {"P0001": "aus"}}

        with tempfile.TemporaryDirectory() as directory:
            endpoint = Endpoint()
            root = Path(directory)
            fingerprint = {"diagnostic": "test-v1"}
            result = probe(endpoint, {"reader": "mock"}, root, fingerprint)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failure"]["probe"], "sentences")
            self.assertEqual(len(result["results"]), 1)
            self.assertEqual(probe(endpoint, {"reader": "mock"}, root,
                                   fingerprint)["status"], "failed")
            self.assertEqual(endpoint.turns, [0, 1])


if __name__ == "__main__":
    unittest.main()
