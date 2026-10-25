"""Eleven resumable, phase-specific structured-output probes for V14."""

from __future__ import annotations

import json
from pathlib import Path

from . import schema_v14
from .source import digest, save


def _paragraph(index: int, text: str, sentences: int = 1) -> dict:
    key = f"P{index:04d}"
    pieces = text.split(" | ") if sentences > 1 else [text]
    offsets = []
    cursor = 0
    for piece in pieces:
        start = text.index(piece, cursor)
        offsets.append((start, start + len(piece)))
        cursor = start + len(piece)
    return {"source_id": key, "start": index * 1000,
        "end": index * 1000 + len(text), "text": text,
        "sentences": [{"source_id": f"S{index:04d}_{part}",
            "start_offset": offsets[part][0], "end_offset": offsets[part][1]}
            for part, _ in enumerate(pieces)]}


def _cases():
    item = {"handle": "I0000", "id": "probe:aus:000", "revision": 1,
        "status": "active", "collection": "aus", "source_ids": ["S0001", "S0002"]}
    filler = "The court records a procedural fact. " * 5 + "This passage adds no legal rule."
    long_group = [_paragraph(i, filler) for i in range(45)] + [_paragraph(45,
                  "The court holds that notice is required before removal.")]
    one = [_paragraph(1, "The court applies the notice rule. | Notice was missing.", 2)]
    incomplete = [_paragraph(2, "The Court held that the statutory exception applies only if")]
    return [
        ("extract_sentences", schema_v14.extraction_schema([], one, {}),
         {"phase": "reader_extract", "opened_sources": one, "items": []},
         "For P0001 choose sentences; make S0001_0 an AU and S0001_1 a brief."),
        ("extract_whole", schema_v14.extraction_schema([], long_group, {}),
         {"phase": "reader_extract", "opened_sources": long_group, "items": []},
         "Choose P0045 as aus. Set every other P and every S key to skip."),
        ("extract_uncertain", schema_v14.extraction_schema([], incomplete, {}),
         {"phase": "reader_extract", "opened_sources": incomplete, "items": []},
         "P0002 ends before the condition is stated. Mark it uncertain rather than inventing the missing condition; set its S key to skip."),
        ("navigate_read", schema_v14.navigation_schema([2, 3]),
         {"phase": "reader_navigate", "catalogue": [{"window_id": 2},
             {"window_id": 3}]}, "Read window 2 for a legal condition."),
        ("navigate_finish", schema_v14.navigation_schema([]),
         {"phase": "reader_navigate", "catalogue": []},
         "Finish the reading phase briefly."),
        ("scan_extend", schema_v14.scan_schema({"I0000": ["P0001", "P0002"]}),
         {"phase": "source_scan", "scan_pairs": {"I0000": ["P0001", "P0002"]},
          "opened_sources": [_paragraph(1, "The court states a rule."),
                             _paragraph(2, "The condition limits that rule.")]},
         "Include P0002 and exclude P0001 for I0000."),
        ("scan_reconsider", schema_v14.scan_schema({"I0000": ["P0001", "P0002"]}),
         {"phase": "source_scan", "scan_mode": "reconsider",
          "scan_pairs": {"I0000": ["P0001", "P0002"]},
          "opened_sources": [_paragraph(1, "This is a heading."),
                             _paragraph(2, "The court states the rule.")]},
         "Exclude P0001, the mistaken heading, and include P0002."),
        ("classification", schema_v14.classification_schema([item]),
         {"phase": "classification", "items": [item],
          "opened_sources": [_paragraph(1, "The court applies the rule.")]},
         "Classify I0000 with S0001 primary, S0002 context, both current_court."),
        ("treatment_unknown", schema_v14.treatment_schema([item]),
         {"phase": "treatment", "items": [item]},
         "Choose unknown because no external authority relation is shown."),
        ("treatment_applies", schema_v14.treatment_schema([item]),
         {"phase": "treatment", "items": [item],
          "source_context": {"S0001": "The cited authority requires notice.",
                             "S0002": "The court applies that rule here."}},
         "Choose applies, S0001 as authority witness and S0002 as response witness; assign matching evidence roles."),
        ("finalizer", schema_v14.finalizer_schema([item]),
         {"phase": "finalizer", "items": [item]},
         "Keep I0000."),
    ]


def probe(endpoint, config: dict, experiment: Path, fingerprint: dict,
          *, sentence_only: bool = False) -> dict:
    path = experiment / "capability_probe.json"
    results = []
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous.get("fingerprint") != fingerprint or previous.get(
                "status") not in {"passed", "in_progress"}:
            raise ValueError("capability_probe_not_reusable")
        if previous["status"] == "passed":
            return previous
        results = previous["results"]
    cases = _cases()
    target = cases[:1] if sentence_only else cases
    for index, (name, schema, payload, instruction) in enumerate(target):
        signature = schema_v14.schema_hash(schema)
        if index < len(results):
            if results[index]["name"] != name or results[index][
                    "schema_hash"] != signature or results[index]["errors"]:
                raise ValueError("capability_probe_identity_mismatch")
            continue
        identity = {"experiment": str(experiment.resolve()),
                    "fingerprint": fingerprint, "index": index,
                    "schema_hash": signature}
        request_id = "v14:capability:" + str(index) + ":" + digest(json.dumps(
            identity, sort_keys=True).encode("utf-8"))[:20]
        answer = endpoint.complete(config["reader"],
            "Return one valid JSON object matching response_format. " + instruction,
            payload, request_id=request_id,
            metadata={"experiment": experiment.name, "stage": "capability_probe",
                "schema_version": schema_v14.SCHEMA_VERSION,
                "prompt_version": schema_v14.PROMPT_VERSION,
                "schema_hash": signature, "turn": index},
            cache_path=experiment / "capability" / f"probe_{index}.json",
            response_format=schema_v14.response_format(schema))
        errors = schema_v14.validate(answer, schema)
        if not errors and name.startswith("extract"):
            errors.extend(schema_v14.validate_extraction(answer, payload["opened_sources"]))
        if not errors and name == "classification":
            errors.extend(schema_v14.validate_classification(answer, [payload["items"][0]]))
        if not errors and name.startswith("treatment"):
            errors.extend(schema_v14.validate_treatment(answer, [payload["items"][0]]))
        observations = []
        if not errors and name.startswith("extract"):
            choices = answer["choices"]
            expected = {"extract_whole": ("P0045", "aus"),
                        "extract_sentences": ("P0001", "sentences"),
                        "extract_uncertain": ("P0002", "uncertain")}[name]
            if choices[expected[0]] != expected[1]:
                observations.append({"path": "$.choices." + expected[0],
                    "requested": expected[1], "observed": choices[expected[0]],
                    "note": "semantic_prompt_deviation_not_schema_failure"})
            if name == "extract_sentences" and {
                    key: choices[key] for key in ("S0001_0", "S0001_1")} != {
                    "S0001_0": "aus", "S0001_1": "brief"}:
                observations.append({"path": "$.choices", "requested": {
                    "S0001_0": "aus", "S0001_1": "brief"},
                    "observed": {key: choices[key] for key in ("S0001_0", "S0001_1")},
                    "note": "semantic_prompt_deviation_not_schema_failure"})
        if not errors and name == "navigate_read" and answer[
                "reading_decision"]["action"] != "read":
            observations.append({"path": "$.reading_decision.action",
                "requested": "read", "observed": answer["reading_decision"]["action"],
                "note": "semantic_prompt_deviation_not_schema_failure"})
        if not errors and name == "treatment_applies" and answer[
                "decisions"]["I0000"]["choice"] != "applies":
            observations.append({"path": "$.decisions.I0000.choice",
                "requested": "applies",
                "observed": answer["decisions"]["I0000"]["choice"],
                "note": "semantic_prompt_deviation_not_schema_failure"})
        results.append({"name": name, "schema_hash": signature,
                        "response": answer, "errors": errors,
                        "observations": observations})
        save(path, {"status": "failed" if errors else "in_progress",
                    "fingerprint": fingerprint, "results": results})
        if errors:
            raise ValueError(f"endpoint_did_not_enforce_v14_schema:{name}:{index}")
    result = {"status": "in_progress" if sentence_only else "passed",
              "fingerprint": fingerprint, "results": results}
    save(path, result)
    return result
