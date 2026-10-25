"""Phase-scoped choices for the V10 extractive knowledge-base pilot."""

from __future__ import annotations

import json

SCHEMA_VERSION = 10
PROMPT_VERSION = "kb-pilot-v10-scoped-source-2"
ATTRIBUTIONS = ("current_court", "party", "cited_authority", "editorial", "mixed", "unknown")
ROLES = ("primary", "context", "qualification", "court_response")
KINDS = ("facts", "posture", "issues", "disposition")
TREATMENTS = ("adopts", "applies", "distinguishes", "rejects", "reports")


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def string_enum(values) -> dict:
    return {"type": "string", "enum": list(values)}


def note() -> dict:
    return {"type": "string", "minLength": 1}


def source_list(handles: list[str], *, minimum: int = 1) -> dict:
    return {"type": "array", "items": string_enum(handles), "minItems": minimum,
            "uniqueItems": True}


def _selection_decision(status: str, handles: list[str]) -> dict:
    choices = [obj({"choice": {"const": "keep"}, "reason": note()})]
    if status == "active":
        choices.extend([
            obj({"choice": {"const": "change_sources"}, "reason": note(),
                 "source_ids": source_list(handles)}),
            obj({"choice": {"const": "defer"}, "reason": note()}),
        ])
    else:
        choices.append(obj({"choice": {"const": "restore"}, "reason": note()}))
    choices.append(obj({"choice": {"const": "remove"}, "reason": note()}))
    return {"oneOf": choices}


def build_schema(phase: str, items: list[dict], handles: list[str],
                 windows: list[int] | None = None) -> dict:
    """Generate exactly the choices available at this request's start."""
    decisions = {}
    for entry in items:
        handle, status, sources = entry["handle"], entry["status"], entry["source_ids"]
        if phase in {"reader", "selection"}:
            decisions[handle] = _selection_decision(status, handles)
        elif phase == "classification":
            if status == "deferred":
                decisions[handle] = obj({"choice": {"const": "keep"}, "reason": note()})
                continue
            classify = {"choice": {"const": "classify"}, "reason": note()}
            if entry["collection"] == "brief":
                classify["kind"] = string_enum(KINDS)
                classify["attribution"] = obj({source: string_enum(ATTRIBUTIONS)
                                               for source in sources})
                decisions[handle] = {"oneOf": [obj(classify),
                    obj({"choice": {"const": "defer"}, "reason": note()})]}
            else:
                classify["attribution"] = obj({source: string_enum(ATTRIBUTIONS)
                                               for source in sources})
                branches = []
                for primary in sources:
                    branch = dict(classify)
                    branch["primary_source_id"] = {"const": primary}
                    branch["roles"] = obj({source: string_enum(
                        ("context", "qualification", "court_response"))
                        for source in sources if source != primary})
                    branches.append(obj(branch))
                decisions[handle] = {"oneOf": branches + [
                    obj({"choice": {"const": "defer"}, "reason": note()})]}
        elif phase == "treatment":
            if entry["collection"] != "aus" or status != "active":
                continue
            decisions[handle] = {"oneOf": [
                obj({"choice": {"const": "unknown"}, "reason": note()}),
                obj({"choice": string_enum(TREATMENTS), "reason": note(),
                     "authority_source_ids": source_list(sources),
                     "response_source_ids": source_list(sources)}),
                obj({"choice": {"const": "defer"}, "reason": note()}),
            ]}
        elif phase == "finalizer":
            choices = [obj({"choice": {"const": "keep"}, "reason": note()}),
                       obj({"choice": {"const": "remove"}, "reason": note()})]
            if status == "active":
                choices.append(obj({"choice": {"const": "defer"}, "reason": note()}))
            decisions[handle] = {"oneOf": choices}
        else:
            raise ValueError("unknown_phase")
    fields = {"decisions": obj(decisions)}
    if phase in {"reader", "selection"}:
        fields["new_items"] = {"type": "array", "items": obj({
            "collection": string_enum(("brief", "aus")),
            "source_ids": source_list(handles), "reason": note()}), "maxItems": 20}
    if windows is not None and phase in {"reader", "selection"} and windows:
        fields["read_window_ids"] = {"type": "array",
            "items": {"type": "integer", "enum": windows},
            "maxItems": 2, "uniqueItems": True}
    schema = obj(fields)
    return schema


def response_format(schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {"name": "kb_v10_choices",
        "strict": True, "schema": schema}}


def validate(value: object, schema: dict) -> list[dict]:
    """Validate the exact JSON Schema vocabulary emitted by build_schema."""
    errors = []

    def check(instance: object, rule: dict, path: str) -> None:
        if "oneOf" in rule:
            if sum(not validate(instance, branch) for branch in rule["oneOf"]) != 1:
                errors.append({"path": path, "error_code": "one_of_violation"})
            return
        kind = rule.get("type")
        if kind == "object":
            if not isinstance(instance, dict):
                errors.append({"path": path, "error_code": "expected_object"})
                return
            for key in rule.get("required", []):
                if key not in instance:
                    errors.append({"path": f"{path}.{key}",
                                   "error_code": "missing_required_field"})
            for key, child in instance.items():
                if key not in rule.get("properties", {}):
                    if rule.get("additionalProperties") is False:
                        errors.append({"path": f"{path}.{key}",
                                       "error_code": "unexpected_field"})
                else:
                    check(child, rule["properties"][key], f"{path}.{key}")
        elif kind == "array":
            if not isinstance(instance, list):
                errors.append({"path": path, "error_code": "expected_array"})
                return
            if len(instance) < rule.get("minItems", 0) or len(instance) > rule.get(
                    "maxItems", float("inf")):
                errors.append({"path": path, "error_code": "array_size_out_of_range"})
            if rule.get("uniqueItems") and len({json.dumps(item, sort_keys=True)
                                                 for item in instance}) != len(instance):
                errors.append({"path": path, "error_code": "duplicate_array_item"})
            for index, child in enumerate(instance):
                check(child, rule["items"], f"{path}[{index}]")
        elif kind == "string":
            if not isinstance(instance, str):
                errors.append({"path": path, "error_code": "expected_string"})
                return
            if len(instance) < rule.get("minLength", 0):
                errors.append({"path": path, "error_code": "string_too_short"})
            if len(instance) > rule.get("maxLength", float("inf")):
                errors.append({"path": path, "error_code": "string_too_long"})
        elif kind == "integer" and (not isinstance(instance, int) or
                                    isinstance(instance, bool)):
            errors.append({"path": path, "error_code": "expected_integer"})
            return
        if "const" in rule and instance != rule["const"]:
            errors.append({"path": path, "error_code": "invalid_constant"})
        if "enum" in rule and instance not in rule["enum"]:
            errors.append({"path": path, "error_code": "invalid_enum"})

    check(value, schema, "$")
    return errors


def schema_hash(schema: dict) -> str:
    from .source import digest
    return digest(json.dumps(schema, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8"))
