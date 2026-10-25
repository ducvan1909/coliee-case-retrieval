"""Exercise the guided schema branches against the configured endpoint."""

from __future__ import annotations

import json
from pathlib import Path

from .schema_v11 import (PROMPT_VERSION, SCHEMA_VERSION, build_schema,
                         response_format, schema_hash, validate,
                         validate_reading_decision)
from .source import digest, save


def probe(endpoint, config: dict, experiment: Path, fingerprint: dict) -> dict:
    path = experiment / "capability_probe.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous.get("fingerprint") != fingerprint or previous.get("status") != "passed":
            raise ValueError("capability_probe_not_reusable")
        return previous
    item = {"handle": "I0000", "status": "active", "collection": "aus",
            "source_ids": ["S0001", "S0002"]}
    cases = [
        ("reader", [], ["S0001"], [2], [2],
         "Select read window 2 with purpose 'inspect a legal rule'."),
        ("reader", [], ["S0001"], [], [2],
         "Finish reader. Assess unread window 2 and list any unresolved needs."),
        ("selection", [], ["S0001"], [2, 3], [3],
         "Select read window 2 with purpose 'revisit a prior legal rule'."),
        ("classification", [item], ["S0001", "S0002"], None, None,
         "Defer the item with a short reason."),
        ("treatment", [item], ["S0001", "S0002"], None, None,
         "Choose unknown with a short reason."),
    ]
    results = []
    for index, (phase, items, handles, readable, unread, instruction) in enumerate(cases):
        schema = build_schema(phase, items, handles, readable, unread)
        payload = {"phase": phase, "items": items, "schema": schema,
                   "readable_window_ids": readable, "unread_window_ids": unread,
                   "instruction": instruction}
        identity = {"experiment": str(experiment.resolve()),
                    "fingerprint": fingerprint, "index": index,
                    "schema_hash": schema_hash(schema)}
        request_id = ("v11:capability:" + str(index) + ":" + digest(json.dumps(
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
            expected = "finish_phase" if index == 1 else "read"
            if answer["reading_decision"]["action"] != expected:
                errors.append({"path": "$.reading_decision.action",
                               "error_code": "probe_branch_not_exercised"})
            elif index in {0, 2} and answer["reading_decision"]["window_ids"] != [2]:
                errors.append({"path": "$.reading_decision.window_ids",
                               "error_code": "probe_window_not_selected"})
        results.append({"phase": phase, "schema_hash": schema_hash(schema),
                        "response": answer, "errors": errors})
        save(path, {"status": "failed" if errors else "in_progress",
                    "fingerprint": fingerprint, "results": results})
        if errors:
            raise ValueError(f"endpoint_did_not_enforce_v11_schema:{phase}:{index}")
    result = {"status": "passed", "fingerprint": fingerprint, "results": results}
    save(path, result)
    return result
