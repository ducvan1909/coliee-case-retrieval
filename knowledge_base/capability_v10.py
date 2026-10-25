"""Audited, bounded structured-output capability gate for V10."""

from __future__ import annotations

import json
from pathlib import Path

from .schema_v10 import (PROMPT_VERSION, SCHEMA_VERSION, build_schema,
                         response_format, schema_hash, validate)
from .source import digest, save


def _probe_request_id(experiment: Path, fingerprint: dict, index: int,
                      schema: dict) -> str:
    """Scope a probe to its experiment, not just its reusable schema."""
    identity = {"experiment": str(experiment.resolve()),
                "fingerprint": fingerprint, "index": index,
                "schema_hash": schema_hash(schema)}
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return f"v10:capability:{index}:{digest(encoded)[:20]}"


def probe(endpoint, config: dict, experiment: Path, fingerprint: dict) -> dict:
    path = experiment / "capability_probe.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous.get("fingerprint") != fingerprint or previous.get("status") != "passed":
            raise ValueError("capability_probe_not_reusable")
        return previous
    cases = [
        ("reader", [], ["S0001", "S0002"], [2]),
        ("classification", [{"handle": "I0000", "status": "active",
            "collection": "aus", "source_ids": ["S0001", "S0002"]}],
            ["S0001", "S0002"], None),
        ("treatment", [{"handle": "I0000", "status": "active",
            "collection": "aus", "source_ids": ["S0001", "S0002"]}],
            ["S0001", "S0002"], None),
    ]
    results = []
    for index, (phase, items, handles, windows) in enumerate(cases):
        schema = build_schema(phase, items, handles, windows)
        payload = {"purpose": "Test JSON Schema constrained output; these are synthetic handles",
            "phase": phase, "items": items, "schema": schema}
        request_id = _probe_request_id(experiment, fingerprint, index, schema)
        answer = endpoint.complete(config["reader"],
            "Return one valid JSON object matching the supplied schema. Use synthetic handles only.",
            payload, request_id=request_id,
            metadata={"experiment": experiment.name, "stage": "capability_probe",
                "schema_version": SCHEMA_VERSION, "prompt_version": PROMPT_VERSION,
                "schema_hash": schema_hash(schema), "turn": index},
            cache_path=experiment / "capability" / f"probe_{index}.json",
            response_format=response_format(schema))
        errors = validate(answer, schema)
        results.append({"phase": phase, "schema_hash": schema_hash(schema),
                        "response": answer, "errors": errors})
        save(path, {"status": "failed" if errors else "in_progress",
                    "fingerprint": fingerprint, "results": results})
        if errors:
            raise ValueError(f"endpoint_did_not_enforce_v10_schema:{phase}")
    result = {"status": "passed", "fingerprint": fingerprint, "results": results}
    save(path, result)
    return result
