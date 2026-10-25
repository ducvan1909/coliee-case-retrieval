"""Probe the endpoint with V12's actual scalar and batched choices."""

from __future__ import annotations

import json
from pathlib import Path

from .schema_v12 import (PROMPT_VERSION, SCHEMA_VERSION, SOURCE_BATCH_SIZE,
                         build_schema, build_source_scan_schema, response_format,
                         schema_hash, validate, validate_reading_decision,
                         validate_treatment_evidence)
from .source import digest, save


def probe(endpoint, config: dict, experiment: Path, fingerprint: dict) -> dict:
    path = experiment / "capability_probe.json"
    results = []
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous.get("fingerprint") != fingerprint or previous.get("status") not in {
                "passed", "in_progress"}:
            raise ValueError("capability_probe_not_reusable")
        if previous["status"] == "passed":
            return previous
        results = previous["results"]
    item = {"handle": "I0000", "status": "active", "collection": "aus",
            "source_ids": ["S0001", "S0002"]}
    cases = [
        ("reader", [], ["S0001"], [2], [2],
         "Return no new items and read window 2 to inspect the legal rule."),
        ("reader", [], ["S0001"], [], [2],
         "Return no new items and finish reader; assess unread window 2."),
        ("selection", [item], ["S0001", "S0002"], [2], [2],
         "Choose scan_sources for I0000 and finish selection, assessing window 2."),
        ("source_scan", [item], [f"S{n:04d}" for n in range(SOURCE_BATCH_SIZE)],
         None, None, "Include C0 and C11, exclude every other candidate."),
        ("treatment", [item], ["S0001", "S0002"], None, None,
         "Choose applies; label S0001 authority and S0002 response."),
        ("classification", [item], ["S0001", "S0002"], None, None,
         "Defer I0000 with a short reason."),
        ("finalizer", [item], ["S0001", "S0002"], None, None,
         "Keep I0000 with a short reason."),
    ]
    for index, (phase, items, handles, readable, unread, instruction) in enumerate(cases):
        schema = (build_source_scan_schema(len(handles)) if phase == "source_scan"
                  else build_schema(phase, items, handles, readable, unread))
        if index < len(results):
            saved = results[index]
            if (saved["phase"] != phase or saved["schema_hash"] != schema_hash(schema)
                    or saved["errors"]):
                raise ValueError("capability_probe_identity_mismatch")
            continue
        payload = {"phase": phase, "items": items, "schema": schema,
                   "instruction": instruction}
        if phase == "source_scan":
            payload["candidate_sources"] = [{"key": f"C{number}",
                "source_id": handle, "text": f"Legal proposition {number}."}
                for number, handle in enumerate(handles)]
        else:
            payload.update(readable_window_ids=readable, unread_window_ids=unread)
            if phase == "treatment":
                payload["source_context"] = {
                    "S0001": "The cited authority states that notice is required.",
                    "S0002": "The court applies that notice rule to this case."}
        identity = {"experiment": str(experiment.resolve()),
                    "fingerprint": fingerprint, "index": index,
                    "schema_hash": schema_hash(schema)}
        request_id = ("v12:capability:" + str(index) + ":" + digest(json.dumps(
            identity, sort_keys=True).encode("utf-8"))[:20])
        answer = endpoint.complete(config["reader"],
            "Return one valid JSON object matching the supplied schema. " + instruction,
            payload, request_id=request_id,
            metadata={"experiment": experiment.name, "stage": "capability_probe",
                "schema_version": SCHEMA_VERSION, "prompt_version": PROMPT_VERSION,
                "schema_hash": schema_hash(schema), "turn": index},
            cache_path=experiment / "capability" / f"probe_{index}.json",
            response_format=response_format(schema))
        errors = validate(answer, schema)
        if not errors and unread is not None:
            errors.extend(validate_reading_decision(answer, unread))
        if not errors and phase == "treatment":
            errors.extend(validate_treatment_evidence(answer, items))
        if not errors:
            if phase == "reader":
                expected = "read" if index == 0 else "finish_phase"
                if answer["reading_decision"]["action"] != expected:
                    errors.append({"path": "$.reading_decision.action",
                                   "error_code": "probe_branch_not_exercised"})
            elif phase == "selection" and answer["decisions"]["I0000"]["choice"] != "scan_sources":
                errors.append({"path": "$.decisions.I0000.choice",
                               "error_code": "probe_branch_not_exercised"})
            elif phase == "source_scan" and (answer["choices"].get("C0") != "include" or
                    answer["choices"].get("C11") != "include"):
                errors.append({"path": "$.choices",
                               "error_code": "probe_candidate_choice_not_exercised"})
            elif phase == "treatment" and answer["decisions"]["I0000"]["choice"] != "applies":
                errors.append({"path": "$.decisions.I0000.choice",
                               "error_code": "probe_branch_not_exercised"})
        results.append({"phase": phase, "schema_hash": schema_hash(schema),
                        "response": answer, "errors": errors})
        save(path, {"status": "failed" if errors else "in_progress",
                    "fingerprint": fingerprint, "results": results})
        if errors:
            raise ValueError(f"endpoint_did_not_enforce_v12_schema:{phase}:{index}")
    result = {"status": "passed", "fingerprint": fingerprint, "results": results}
    save(path, result)
    return result
