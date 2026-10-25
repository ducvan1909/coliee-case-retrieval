"""Eleven resumable structured-output probes for the V15 workflow."""

from __future__ import annotations

import json
from pathlib import Path

from . import schema_v15
from .source import digest, save


def _paragraph(index: int, text: str, pieces: list[str] | None = None) -> dict:
    pieces = pieces or [text]
    cursor, sentences = 0, []
    for part, piece in enumerate(pieces):
        start = text.index(piece, cursor)
        sentences.append({"source_id": f"S{index:04d}_{part}",
            "start_offset": start, "end_offset": start + len(piece)})
        cursor = start + len(piece)
    return {"source_id": f"P{index:04d}", "start": index * 1000,
        "end": index * 1000 + len(text), "text": text,
        "sentences": sentences}


def _cases():
    triage_with_sentences = [
        _paragraph(0, "REASONS FOR JUDGMENT"),
        _paragraph(1, "A claimant must give notice before seeking the remedy."),
        _paragraph(2, "The applicant filed the claim on time."),
        _paragraph(3, "The appeal is dismissed."),
    ]
    triage = [{key: value for key, value in paragraph.items()
               if key != "sentences"} for paragraph in triage_with_sentences]
    refine = [
        _paragraph(4, "Background. The notice rule applies only after service.",
                   ["Background.", "The notice rule applies only after service."]),
        _paragraph(5, "The party disputes notice. The court rejects that argument.",
                   ["The party disputes notice.", "The court rejects that argument."]),
    ]
    item = {"handle": "I0000", "id": "probe:aus:000", "revision": 1,
        "status": "active", "collection": "aus", "source_ids": ["S0001", "S0002"]}
    return [
        ("triage_four", schema_v15.triage_schema(triage),
         {"phase": "reader_triage", "opened_sources": triage},
         "Choose P0000 skip, P0001 aus, P0002 brief, and P0003 brief."),
        ("refinement", schema_v15.refinement_schema(refine),
         {"phase": "reader_refine", "opened_sources": refine},
         "For each parent retain at least one sentence. Choose the legal rule sentence as aus and the court-response sentence as aus; skip the other sentences."),
        ("triage_all_skip", schema_v15.triage_schema(triage),
         {"phase": "reader_triage", "opened_sources": triage},
         "For this schema capability observation, choose skip for every paragraph."),
        ("navigate_read", schema_v15.navigation_schema([2, 3]),
         {"phase": "reader_navigate", "catalogue": [{"window_id": 2},
             {"window_id": 3}]}, "Read window 2 for a missing condition."),
        ("navigate_finish", schema_v15.navigation_schema([]),
         {"phase": "reader_navigate", "catalogue": []}, "Finish the phase."),
        ("scan_extend", schema_v15.scan_schema({"I0000": ["P0001", "P0002"]}),
         {"phase": "source_scan", "scan_mode": "scan_extend",
          "scan_pairs": {"I0000": ["P0001", "P0002"]}},
         "Include P0002 and exclude P0001 for I0000."),
        ("scan_reconsider", schema_v15.scan_schema({"I0000": ["P0001", "P0002"]}),
         {"phase": "source_scan", "scan_mode": "scan_reconsider",
          "scan_pairs": {"I0000": ["P0001", "P0002"]}},
         "Exclude P0001 and include P0002 for I0000."),
        ("classification", schema_v15.classification_schema([item]),
         {"phase": "classification", "items": [item]},
         "Classify I0000 with S0001 primary, S0002 context, both current_court."),
        ("treatment_unknown", schema_v15.treatment_schema([item]),
         {"phase": "treatment", "items": [item]},
         "Choose unknown because no external authority relation is established."),
        ("treatment_authority", schema_v15.treatment_schema([item]),
         {"phase": "treatment", "items": [item], "source_context": {
             "S0001": "The cited authority requires notice.",
             "S0002": "The court applies that requirement here."}},
         "Choose applies with S0001 authority and S0002 response witnesses and matching evidence roles."),
        ("finalizer", schema_v15.finalizer_schema([item]),
         {"phase": "finalizer", "items": [item]}, "Keep I0000."),
    ]


def probe(endpoint, config: dict, experiment: Path, fingerprint: dict) -> dict:
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
    for index, (name, schema, payload, instruction) in enumerate(_cases()):
        signature = schema_v15.schema_hash(schema)
        if index < len(results):
            saved = results[index]
            if (saved["name"] != name or saved["schema_hash"] != signature or
                    saved["errors"]):
                raise ValueError("capability_probe_identity_mismatch")
            continue
        identity = {"experiment": str(experiment.resolve()),
                    "fingerprint": fingerprint, "index": index,
                    "schema_hash": signature}
        request_id = "v15:capability:" + str(index) + ":" + digest(json.dumps(
            identity, sort_keys=True).encode("utf-8"))[:20]
        answer = endpoint.complete(config["reader"],
            "Return exactly one JSON object matching response_format. " + instruction,
            payload, request_id=request_id,
            metadata={"experiment": experiment.name, "stage": "capability_probe",
                "schema_version": schema_v15.SCHEMA_VERSION,
                "prompt_version": schema_v15.PROMPT_VERSION,
                "schema_hash": signature, "turn": index},
            cache_path=experiment / "capability" / f"probe_{index}.json",
            response_format=schema_v15.response_format(schema))
        errors = schema_v15.validate(answer, schema)
        if not errors and name == "refinement":
            errors.extend(schema_v15.validate_refinement(
                answer, payload["opened_sources"]))
        if not errors and name == "classification":
            errors.extend(schema_v15.validate_classification(answer,
                [payload["items"][0]]))
        if not errors and name.startswith("treatment"):
            errors.extend(schema_v15.validate_treatment(answer,
                [payload["items"][0]]))
        observations = []
        expected = {"navigate_read": ("$.reading_decision.action", "read"),
                    "navigate_finish": ("$.reading_decision.action", "finish_phase")}
        if not errors and name in expected:
            observed = answer["reading_decision"]["action"]
            if observed != expected[name][1]:
                observations.append({"path": expected[name][0],
                    "requested": expected[name][1], "observed": observed,
                    "note": "semantic_prompt_deviation_not_schema_failure"})
        results.append({"name": name, "schema_hash": signature,
                        "response": answer, "errors": errors,
                        "observations": observations})
        save(path, {"status": "failed" if errors else "in_progress",
                    "fingerprint": fingerprint, "results": results})
        if errors:
            raise ValueError(f"endpoint_did_not_enforce_v15_schema:{name}:{index}")
    result = {"status": "passed", "fingerprint": fingerprint,
              "results": results}
    save(path, result)
    return result

