"""V14 constrained candidate, compact payload and grouped scan regressions."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from knowledge_base.pipeline_v10 import build_case
from knowledge_base.capability_v14 import _cases as capability_cases, probe
from knowledge_base.schema_v14 import (classification_schema, extraction_schema,
    navigation_schema, treatment_schema, validate, validate_extraction,
    validate_treatment)
from knowledge_base.source import compact_opened_sources, load_source, source_handles, source_structure


def skipped_choices(manifest):
    pending = set(manifest["candidate_paragraph_ids"])
    return {source: "skip" for paragraph in manifest["opened_sources"]
            if paragraph["source_id"] in pending
            for source in [paragraph["source_id"],
                           *(sentence["source_id"] for sentence in paragraph["sentences"])]}


class Endpoint:
    def __init__(self, fail_phase=None):
        self.calls = []
        self.fail_phase = fail_phase
        self.failed = False

    def complete(self, model, system, payload, *, response_format, **kwargs):
        manifest = payload["manifest"]
        phase = manifest["phase"]
        self.calls.append((phase, payload, response_format))
        if phase == self.fail_phase and not self.failed:
            self.failed = True
            raise RuntimeError("interrupted")
        if phase.endswith("_extract"):
            decisions = {item["handle"]: {"choice": "keep"}
                         for item in manifest["items"]}
            choices = skipped_choices(manifest)
            if phase == "reader_extract" and not manifest["items"]:
                choices[manifest["candidate_paragraph_ids"][0]] = "aus"
            return {"choices": choices, **({"decisions": decisions} if decisions else {})}
        if phase.endswith("_navigate"):
            return {"reading_decision": {"action": "finish_phase",
                                         "reason": "source group reviewed"}}
        if phase == "source_scan":
            return {"choices": {item: {source: "include" for source in sources}
                    for item, sources in manifest["scan_pairs"].items()}}
        if phase == "classification":
            return {"attribution_by_source": {source: "current_court"
                    for item in manifest["items"] for source in item["source_ids"]},
                "decisions": {item["handle"]: {"choice": "classify",
                    "roles": {source: ("primary" if number == 0 else "context")
                              for number, source in enumerate(item["source_ids"])}
                    } for item in manifest["items"]}}
        if phase == "treatment":
            return {"decisions": {item["handle"]: {"choice": "unknown"}
                    for item in manifest["items"] if item["collection"] == "aus"
                    and item["status"] == "active"}}
        return {"decisions": {item["handle"]: {"choice": "keep"}
                for item in manifest["items"]}}


def row(root):
    source = root / "source.txt"
    source.write_text("[1] The court states a notice rule. It applies to this case.\n\n"
                      "[2] The applicant was not given notice. The appeal is allowed.",
                      encoding="utf-8")
    return {"case_id": "sample", "source": str(source),
            "source_hash": load_source(source)[1]}


class V14Tests(unittest.TestCase):
    def test_sentence_probe_is_reused_by_full_gate_without_another_call(self):
        class ProbeEndpoint:
            def __init__(self):
                self.turns = []

            def complete(self, model, system, payload, *, metadata, **kwargs):
                turn = metadata["turn"]
                self.turns.append(turn)
                if turn == 0:
                    return {"choices": {"P0001": "sentences",
                        "S0001_0": "aus", "S0001_1": "brief"}}
                if turn == 1:
                    return {"choices": {**{
                        f"P{i:04d}": ("aus" if i == 45 else "skip")
                        for i in range(46)}, **{
                        f"S{i:04d}_0": "skip" for i in range(46)}}}
                if turn == 2:
                    return {"choices": {"P0002": "skip", "S0002_0": "skip"}}
                if turn == 3:
                    return {"reading_decision": {"action": "read",
                        "window_ids": [2], "purpose": "read condition"}}
                if turn == 4:
                    return {"reading_decision": {"action": "finish_phase",
                        "reason": "budget exhausted"}}
                if turn in {5, 6}:
                    return {"choices": {"I0000": {"P0001": "exclude",
                        "P0002": "include"}}}
                if turn == 7:
                    return {"attribution_by_source": {"S0001": "current_court",
                        "S0002": "current_court"}, "decisions": {"I0000": {
                            "choice": "classify", "roles": {"S0001": "primary",
                            "S0002": "context"}}}}
                if turn == 8:
                    return {"decisions": {"I0000": {"choice": "unknown"}}}
                if turn == 9:
                    return {"decisions": {"I0000": {"choice": "applies",
                        "reason": "court uses cited rule", "authority_witness": "S0001",
                        "response_witness": "S0002", "evidence": {"S0001": "authority",
                        "S0002": "response"}}}}
                return {"decisions": {"I0000": {"choice": "keep"}}}

        with tempfile.TemporaryDirectory() as directory:
            endpoint = ProbeEndpoint()
            config = {"reader": "mock"}
            fingerprint = {"schema_version": 14, "variant": "direct-keys"}
            experiment = Path(directory)
            partial = probe(endpoint, config, experiment, fingerprint,
                            sentence_only=True)
            self.assertEqual(partial["status"], "in_progress")
            self.assertEqual(endpoint.turns, [0])
            full = probe(endpoint, config, experiment, fingerprint)
            self.assertEqual(full["status"], "passed")
            self.assertEqual(endpoint.turns, list(range(11)))
            self.assertEqual(full["results"][2]["observations"][0]["observed"],
                             "skip")

    def test_capability_probe_covers_large_window_and_eleven_contracts(self):
        probes = capability_cases()
        self.assertEqual(len(probes), 11)
        self.assertEqual(probes[0][0], "extract_sentences")
        paragraphs = probes[1][2]["opened_sources"]
        self.assertGreaterEqual(sum(len(paragraph["text"]) for paragraph in
                                    paragraphs), 9500)
        self.assertLessEqual(sum(len(paragraph["text"]) for paragraph in
                                 paragraphs), 10000)
        self.assertEqual(len(paragraphs), 46)
        self.assertEqual(sum(1 + len(p["sentences"]) for p in paragraphs), 92)

    def test_invalid_grouped_scan_does_not_apply_any_item_update(self):
        class InvalidScan(Endpoint):
            def complete(self, model, system, payload, *, response_format, **kwargs):
                manifest = payload["manifest"]
                if manifest["phase"] == "reader_extract":
                    self.calls.append(("reader_extract", payload, response_format))
                    choices = skipped_choices(manifest)
                    for paragraph in manifest["candidate_paragraph_ids"]:
                        choices[paragraph] = "aus"
                    return {"choices": choices}
                if manifest["phase"] == "source_scan":
                    self.calls.append(("source_scan", payload, response_format))
                    pairs = manifest["scan_pairs"]
                    return {"choices": {item: {source: "include" for source in sources}
                        for item, sources in list(pairs.items())[:1]}}
                return super().complete(model, system, payload,
                                        response_format=response_format, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "pilot_v14/calibration/sample"
            endpoint = InvalidScan()
            # Two anchors are saved, then the scan omits one required item key.
            result = build_case(row(root), endpoint,
                {"reader": "mock", "repair": "mock"}, 200, 6,
                output, "audited-candidates")
            self.assertEqual(result["execution_status"], "incomplete")
            self.assertEqual(len(result["aus"]), 2)
            self.assertTrue(result["protocol_errors"])
            self.assertTrue(all(len(item["source_refs"]) == 1
                                for item in result["aus"]))

    def test_two_items_share_one_scan_request_and_reconsider_can_remove(self):
        class Grouped(Endpoint):
            def __init__(self):
                super().__init__()
                self.scan_turns = 0

            def complete(self, model, system, payload, *, response_format, **kwargs):
                manifest = payload["manifest"]
                phase = manifest["phase"]
                if phase == "reader_extract":
                    self.calls.append((phase, payload, response_format))
                    choices = skipped_choices(manifest)
                    for paragraph in manifest["candidate_paragraph_ids"]:
                        choices[paragraph] = "aus"
                    return {"choices": choices}
                if phase == "source_scan":
                    self.calls.append((phase, payload, response_format))
                    self.scan_turns += 1
                    return {"choices": {item: {source: "exclude" for source in sources}
                        for item, sources in manifest["scan_pairs"].items()}}
                return super().complete(model, system, payload,
                                        response_format=response_format, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            endpoint = Grouped()
            result = build_case(row(root), endpoint,
                {"reader": "mock", "repair": "mock"}, 200, 6,
                root / "pilot_v14/calibration/sample", "audited-candidates")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(len(result["aus"]), 2)
            self.assertEqual(endpoint.scan_turns, 1)
            scans = [payload["manifest"] for phase, payload, _ in endpoint.calls
                     if phase == "source_scan"]
            self.assertEqual(len(scans[0]["scan_pairs"]), 2)

        class Reconsider(Endpoint):
            def __init__(self):
                super().__init__()
                self.scans = 0

            def complete(self, model, system, payload, *, response_format, **kwargs):
                manifest = payload["manifest"]
                phase = manifest["phase"]
                if phase == "selection_extract":
                    self.calls.append((phase, payload, response_format))
                    return {"decisions": {item["handle"]: {"choice": "scan_reconsider",
                        "reason": "remove unrelated context"} for item in manifest["items"]},
                        "choices": skipped_choices(manifest)}
                if phase == "source_scan":
                    self.calls.append((phase, payload, response_format))
                    self.scans += 1
                    return {"choices": {item: {source: ("include" if self.scans == 1
                        or source == manifest["candidate_sources"][0]
                        else "exclude") for source in sources}
                        for item, sources in manifest["scan_pairs"].items()}}
                return super().complete(model, system, payload,
                                        response_format=response_format, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            endpoint = Reconsider()
            result = build_case(row(root), endpoint,
                {"reader": "mock", "repair": "mock"}, 200, 6,
                root / "pilot_v14/calibration/sample", "audited-candidates")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(endpoint.scans, 2)
            self.assertEqual(len(result["aus"][0]["source_refs"]), 1)

    def test_grouped_scan_keeps_sources_selected_in_earlier_batches(self):
        class IncludeAll(Endpoint):
            def complete(self, model, system, payload, *, response_format, **kwargs):
                manifest = payload["manifest"]
                phase = manifest["phase"]
                if phase == "reader_extract":
                    self.calls.append((phase, payload, response_format))
                    choices = skipped_choices(manifest)
                    for paragraph in manifest["candidate_paragraph_ids"]:
                        choices[paragraph] = "aus"
                    return {"choices": choices}
                if phase == "source_scan":
                    self.calls.append((phase, payload, response_format))
                    return {"choices": {item: {source: "include" for source in sources}
                        for item, sources in manifest["scan_pairs"].items()}}
                return super().complete(model, system, payload,
                                        response_format=response_format, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("\n\n".join(
                f"[{number}] The court applies condition {number} to this case."
                for number in range(1, 31)), encoding="utf-8")
            current = {"case_id": "sample", "source": str(source),
                       "source_hash": load_source(source)[1]}
            endpoint = IncludeAll()
            result = build_case(current, endpoint,
                {"reader": "mock", "repair": "mock", "max_source_scan_requests": 24},
                10000, 6, root / "pilot_v14/calibration/sample", "audited-candidates")
            scans = [phase for phase, _, _ in endpoint.calls if phase == "source_scan"]
            self.assertGreaterEqual(len(scans), 2)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["protocol_status"], "valid")
            self.assertTrue(any(len(item["source_refs"]) > 1 for item in result["aus"]))

    def test_source_text_is_sent_once_with_sentence_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            current = row(Path(directory))
            text, source_hash = load_source(Path(current["source"]))
            _, units = source_structure(text, source_hash)
            handles, _ = source_handles(units)
            compact = compact_opened_sources({unit["source_id"]: unit for unit in units},
                                             {unit["source_id"] for unit in units}, handles)
            self.assertTrue(compact)
            for paragraph in compact:
                for sentence in paragraph["sentences"]:
                    self.assertNotIn("text", sentence)
                    self.assertEqual(paragraph["text"][sentence["start_offset"]:
                        sentence["end_offset"]], text[sentence["start"]:sentence["end"]])

    def test_schema_requires_every_paragraph_and_sentence_key(self):
        paragraphs = [{"source_id": "P0001", "sentences": [{"source_id": "S0001"}]},
                      {"source_id": "P0002", "sentences": [{"source_id": "S0002"}]}]
        schema = extraction_schema([], paragraphs, {})
        answer = {"choices": {"P0001": "skip", "S0001": "skip",
                              "P0002": "sentences", "S0002": "aus"}}
        self.assertFalse(validate(answer, schema))
        self.assertFalse(validate_extraction(answer, paragraphs))
        del answer["choices"]["S0001"]
        self.assertTrue(validate(answer, schema))
        answer["choices"]["S0001"] = "skip"
        answer["choices"]["P0003"] = "skip"
        self.assertTrue(validate(answer, schema))

    def test_direct_sentence_contract_rejects_parent_child_overlap(self):
        paragraphs = [{"source_id": "P0001", "sentences": [
            {"source_id": "S0001"}, {"source_id": "S0002"}]}]
        schema = extraction_schema([], paragraphs, {})
        valid = {"choices": {"P0001": "sentences", "S0001": "aus",
                             "S0002": "brief"}}
        self.assertFalse(validate(valid, schema))
        self.assertFalse(validate_extraction(valid, paragraphs))
        for choices in (
                {"P0001": "sentences", "S0001": "skip", "S0002": "skip"},
                {"P0001": "aus", "S0001": "aus", "S0002": "skip"},
                {"P0001": "skip", "S0001": "skip", "S0002": "brief"}):
            response = {"choices": choices}
            self.assertFalse(validate(response, schema))
            self.assertTrue(validate_extraction(response, paragraphs))
        old = {"source_decisions": {"P0001": {"choice": "whole",
                "collection": "aus", "reason": "old contract"}}}
        self.assertTrue(validate(old, schema))

    def test_treatment_requires_both_witnesses_from_selected_sources(self):
        item = {"handle": "I0000", "collection": "aus", "status": "active",
                "source_ids": ["S0001", "S0002"]}
        schema = treatment_schema([item])
        bad = {"decisions": {"I0000": {"choice": "applies", "reason": "applied rule",
            "authority_witness": "S0001", "evidence": {"S0001": "authority",
                                                       "S0002": "none"}}}}
        self.assertTrue(validate(bad, schema))
        bad["decisions"]["I0000"]["response_witness"] = "S0002"
        self.assertFalse(validate(bad, schema))
        self.assertTrue(validate_treatment(bad, [item]))
        bad["decisions"]["I0000"]["evidence"]["S0002"] = "response"
        self.assertFalse(validate_treatment(bad, [item]))

    def test_end_to_end_exact_source_payload_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = row(root)
            output = root / "pilot_v14/calibration/sample"
            first = Endpoint(fail_phase="reader_navigate")
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                build_case(current, first, {"reader": "mock", "repair": "mock"},
                           200, 6, output, "audited-candidates")
            later = Endpoint()
            result = build_case(current, later, {"reader": "mock", "repair": "mock"},
                                200, 6, output, "audited-candidates")
            self.assertEqual(result["schema_version"], 14)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(len(result["aus"]), 1)
            self.assertEqual(len([call for call in later.calls
                                  if call[0] == "reader_extract"]), 0)
            for item in result["aus"]:
                for excerpt in item["excerpts"]:
                    text = load_source(Path(current["source"]))[0]
                    self.assertEqual(excerpt["text"], text[excerpt["start"]:excerpt["end"]])
            for phase, payload, format_spec in [*first.calls, *later.calls]:
                self.assertNotIn("schema", payload["manifest"])
                self.assertIn("schema", format_spec["json_schema"])
                for paragraph in payload["manifest"].get("opened_sources", []):
                    self.assertTrue(all("text" not in sentence
                                        for sentence in paragraph["sentences"]))
            checkpoint = json.loads((output / "checkpoint.json").read_text("utf-8"))
            self.assertEqual(checkpoint["stage"], "complete")

    def test_empty_output_skips_late_requests_and_does_not_certify_quality(self):
        class Empty(Endpoint):
            def complete(self, model, system, payload, *, response_format, **kwargs):
                if payload["manifest"]["phase"].endswith("_extract"):
                    manifest = payload["manifest"]
                    self.calls.append((manifest["phase"], payload, response_format))
                    decisions = {item["handle"]: {"choice": "keep"}
                                 for item in manifest["items"]}
                    return {"choices": skipped_choices(manifest),
                            **({"decisions": decisions} if decisions else {})}
                return super().complete(model, system, payload,
                                        response_format=response_format, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            endpoint = Empty()
            result = build_case(row(root), endpoint,
                {"reader": "mock", "repair": "mock"}, 200, 6,
                root / "pilot_v14/calibration/sample", "audited-candidates")
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["output_status"], "empty_output")
            self.assertEqual(result["quality_status"], "not_evaluated")
            self.assertFalse(any(phase in {"classification", "treatment", "finalizer"}
                                 for phase, _, _ in endpoint.calls))


if __name__ == "__main__":
    unittest.main()
