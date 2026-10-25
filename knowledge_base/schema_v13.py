"""V13 separates source extraction from the decision to open more source."""

from __future__ import annotations

from copy import deepcopy

from .schema_v10 import (ATTRIBUTIONS, KINDS, ROLES, note, obj, schema_hash,
                         string_enum, validate)
from .schema_v11 import build_schema as build_guided_schema
from .schema_v11 import validate_reading_decision
from .schema_v12 import build_schema as build_candidate_schema
from .schema_v12 import build_source_scan_schema, validate_treatment_evidence

SCHEMA_VERSION = 13
PROMPT_VERSION = "kb-pilot-v13-extract-before-navigate-1"


def extraction_schema(items: list[dict], handles: list[str]) -> dict:
    if not handles:
        raise ValueError("extraction_requires_supplied_source")
    schema = deepcopy(build_candidate_schema("reader", items, handles, [], []))
    del schema["properties"]["reading_decision"]
    schema["required"].remove("reading_decision")
    schema["properties"]["batch_assessment"] = obj({
        "reason": note(),
        "unresolved_needs": {"type": "array", "items": note()},
    })
    schema["required"].append("batch_assessment")
    return schema


def navigation_schema(readable_windows: list[int],
                      unread_windows: list[int]) -> dict:
    schema = build_guided_schema("reader", [], [], readable_windows,
                                 unread_windows)
    return obj({"reading_decision": schema["properties"]["reading_decision"]})


def classification_schema(items: list[dict]) -> dict:
    decisions = {}
    for entry in items:
        handle, sources = entry["handle"], entry["source_ids"]
        if entry["status"] == "deferred":
            decisions[handle] = obj({"choice": {"const": "keep"}, "reason": note()})
            continue
        fields = {"choice": {"const": "classify"}, "reason": note(),
            "attribution": obj({source: string_enum(ATTRIBUTIONS)
                                for source in sources})}
        if entry["collection"] == "brief":
            fields["kind"] = string_enum(KINDS)
        else:
            fields["roles"] = obj({source: string_enum(ROLES)
                                   for source in sources})
        decisions[handle] = {"oneOf": [obj(fields),
            obj({"choice": {"const": "defer"}, "reason": note()})]}
    return obj({"decisions": obj(decisions)})


def validate_classification(response: dict, items: list[dict]) -> list[dict]:
    errors = []
    for entry in items:
        if entry["collection"] != "aus" or entry["status"] != "active":
            continue
        choice = response["decisions"][entry["handle"]]
        if choice["choice"] != "classify":
            continue
        if sum(role == "primary" for role in choice["roles"].values()) != 1:
            errors.append({"path": f"$.decisions.{entry['handle']}.roles",
                           "error_code": "exactly_one_primary_required"})
    return errors


def response_format(schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {
        "name": "kb_v13_choices", "strict": True, "schema": schema}}
