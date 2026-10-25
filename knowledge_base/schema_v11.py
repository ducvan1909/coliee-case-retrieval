"""Constrained, phase-specific reading decisions for the guided pilot."""

from __future__ import annotations

from .schema_v10 import (obj, note, schema_hash, validate)
from .schema_v10 import build_schema as build_v10_schema

SCHEMA_VERSION = 11
PROMPT_VERSION = "kb-pilot-v11-guided-reading-1"


def build_schema(phase: str, items: list[dict], handles: list[str],
                 readable_windows: list[int] | None = None,
                 unread_windows: list[int] | None = None) -> dict:
    schema = build_v10_schema(phase, items, handles)
    if phase not in {"reader", "selection"}:
        return schema
    readable = readable_windows or []
    unread = unread_windows or []
    group = obj({"window_ids": {"type": "array",
                                 "items": {"type": "integer", "enum": unread},
                                 "minItems": 1, "uniqueItems": True},
                 "reason": note()})
    finish = obj({"action": {"const": "finish_phase"},
                  "reason": note(),
                  "unresolved_needs": {"type": "array", "items": note()},
                  "unread_assessment": {"type": "array", "items": group,
                                        "maxItems": len(unread)}})
    branches = [finish]
    if readable:
        branches.insert(0, obj({"action": {"const": "read"},
                                "window_ids": {"type": "array",
                                    "items": {"type": "integer", "enum": readable},
                                    "minItems": 1, "maxItems": 2,
                                    "uniqueItems": True},
                                "purpose": note()}))
    schema["properties"]["reading_decision"] = {"oneOf": branches}
    schema["required"].append("reading_decision")
    return schema


def validate_reading_decision(value: dict, unread: list[int]) -> list[dict]:
    """Check the cross-group coverage that JSON Schema cannot express."""
    decision = value.get("reading_decision", {})
    if decision.get("action") != "finish_phase":
        return []
    listed = [number for group in decision["unread_assessment"]
              for number in group["window_ids"]]
    return ([] if len(listed) == len(set(listed)) and set(listed) == set(unread)
            else [{"path": "$.reading_decision.unread_assessment",
                   "error_code": "unread_windows_not_assessed_exactly_once"}])


def response_format(schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {"name": "kb_v11_choices",
        "strict": True, "schema": schema}}
