"""V12 source choices: finite candidate decisions, no model-written ID lists."""

from __future__ import annotations

from copy import deepcopy

from .schema_v10 import TREATMENTS, note, obj, schema_hash, string_enum, validate
from .schema_v11 import build_schema as build_v11_schema
from .schema_v11 import validate_reading_decision

SCHEMA_VERSION = 12
PROMPT_VERSION = "kb-pilot-v12-batched-source-choice-1"
SOURCE_BATCH_SIZE = 12


def build_schema(phase: str, items: list[dict], handles: list[str],
                 readable_windows: list[int] | None = None,
                 unread_windows: list[int] | None = None) -> dict:
    schema = deepcopy(build_v11_schema(phase, items, handles,
                                      readable_windows, unread_windows))
    if phase in {"reader", "selection"}:
        for entry in items:
            branches = schema["properties"]["decisions"]["properties"][entry["handle"]]["oneOf"]
            for branch in branches:
                choice = branch["properties"]["choice"].get("const")
                if choice == "change_sources":
                    branch["properties"] = {"choice": {"const": "scan_sources"},
                                            "reason": note()}
                    branch["required"] = ["choice", "reason"]
        schema["properties"]["new_items"]["items"] = obj({
            "collection": string_enum(("brief", "aus")),
            "anchor_source_id": string_enum(handles), "reason": note()})
    elif phase == "treatment":
        decisions = schema["properties"]["decisions"]["properties"]
        for entry in items:
            if entry["collection"] != "aus" or entry["status"] != "active":
                continue
            evidence = obj({source: string_enum(("none", "authority", "response", "both"))
                            for source in entry["source_ids"]})
            decisions[entry["handle"]] = {"oneOf": [
                obj({"choice": {"const": "unknown"}, "reason": note()}),
                obj({"choice": string_enum(TREATMENTS), "reason": note(),
                     "evidence": evidence}),
                obj({"choice": {"const": "defer"}, "reason": note()}),
            ]}
    return schema


def build_source_scan_schema(candidate_count: int) -> dict:
    if not 1 <= candidate_count <= SOURCE_BATCH_SIZE:
        raise ValueError("source_scan_batch_size_out_of_range")
    return obj({"choices": obj({f"C{index}": string_enum(("include", "exclude"))
                                for index in range(candidate_count)})})


def response_format(schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {"name": "kb_v12_choices",
        "strict": True, "schema": schema}}


def validate_treatment_evidence(response: dict, entries: list[dict]) -> list[dict]:
    errors = []
    for entry in entries:
        if entry["collection"] != "aus" or entry["status"] != "active":
            continue
        decision = response["decisions"][entry["handle"]]
        if decision["choice"] in {"unknown", "defer"}:
            continue
        values = decision["evidence"].values()
        if not any(value in {"authority", "both"} for value in values):
            errors.append({"path": f"$.decisions.{entry['handle']}.evidence",
                           "error_code": "missing_authority_evidence"})
        if not any(value in {"response", "both"} for value in values):
            errors.append({"path": f"$.decisions.{entry['handle']}.evidence",
                           "error_code": "missing_court_response_evidence"})
    return errors
