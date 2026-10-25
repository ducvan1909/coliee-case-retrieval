"""V14 phase-scoped, host-keyed choices for audited source candidates."""

from __future__ import annotations

from .schema_v10 import ATTRIBUTIONS, KINDS, ROLES, TREATMENTS, obj, string_enum
from .schema_v11 import validate_reading_decision
from .schema_v10 import schema_hash, validate

SCHEMA_VERSION = 14
PROMPT_VERSION = "kb-pilot-v14-anchored-triage-3"
POLICY = "audited-candidates"


def reason() -> dict:
    return {"type": "string", "minLength": 1, "maxLength": 160}


def extraction_schema(items: list[dict], paragraphs: list[dict],
                      scan_modes: dict[str, set[str]]) -> dict:
    decisions = {}
    for entry in items:
        choices = [obj({"choice": {"const": "keep"}})]
        if entry["status"] == "active":
            for mode in sorted(scan_modes.get(entry["handle"], set())):
                choices.append(obj({"choice": {"const": mode}, "reason": reason()}))
            for action in ("defer", "remove"):
                choices.append(obj({"choice": {"const": action}, "reason": reason()}))
        else:
            for action in ("restore", "remove"):
                choices.append(obj({"choice": {"const": action}, "reason": reason()}))
        decisions[entry["handle"]] = {"oneOf": choices}
    sources = {}
    for paragraph in paragraphs:
        sentences = paragraph["sentences"]
        choices = ["skip", "uncertain", "brief", "aus", "both"]
        if sentences:
            choices.append("sentences")
        sources[paragraph["source_id"]] = string_enum(choices)
        for sentence in sentences:
            sources[sentence["source_id"]] = string_enum(
                ("skip", "uncertain", "brief", "aus", "both"))
    fields = {"choices": obj(sources)}
    if decisions:
        fields["decisions"] = obj(decisions)
    return obj(fields)


def validate_extraction(response: dict, paragraphs: list[dict]) -> list[dict]:
    """Forbid selecting both a paragraph and any of its sentence addresses."""
    errors = []
    for paragraph in paragraphs:
        source_id = paragraph["source_id"]
        choice = response["choices"][source_id]
        children = [response["choices"][sentence["source_id"]]
                    for sentence in paragraph["sentences"]]
        if choice == "sentences" and not any(value != "skip" for value in children):
            errors.append({"path": f"$.choices.{source_id}",
                           "error_code": "empty_sentence_selection"})
        if choice != "sentences" and any(value != "skip" for value in children):
            errors.append({"path": f"$.choices.{source_id}",
                           "error_code": "parent_child_overlap"})
    return errors


def navigation_schema(readable: list[int]) -> dict:
    branches = [obj({"action": {"const": "finish_phase"},
                     "reason": reason()})]
    if readable:
        branches.insert(0, obj({"action": {"const": "read"},
            "window_ids": {"type": "array", "items": {"type": "integer",
                "enum": readable}, "minItems": 1, "maxItems": 2,
                "uniqueItems": True}, "purpose": reason()}))
    return obj({"reading_decision": {"oneOf": branches}})


def classification_schema(items: list[dict]) -> dict:
    sources = sorted({source for entry in items if entry["status"] == "active"
                      for source in entry["source_ids"]})
    decisions = {}
    for entry in items:
        if entry["status"] == "deferred":
            decisions[entry["handle"]] = obj({"choice": {"const": "keep"}})
            continue
        fields = {"choice": {"const": "classify"}}
        if entry["collection"] == "brief":
            fields["kind"] = string_enum(KINDS)
        else:
            fields["roles"] = obj({source: string_enum(ROLES)
                                   for source in entry["source_ids"]})
        decisions[entry["handle"]] = {"oneOf": [obj(fields),
            obj({"choice": {"const": "defer"}, "reason": reason()})]}
    return obj({"attribution_by_source": obj({source: string_enum(ATTRIBUTIONS)
        for source in sources}), "decisions": obj(decisions)})


def validate_classification(response: dict, items: list[dict]) -> list[dict]:
    errors = []
    for entry in items:
        if entry["collection"] != "aus" or entry["status"] != "active":
            continue
        decision = response["decisions"][entry["handle"]]
        if decision["choice"] == "classify" and sum(
                role == "primary" for role in decision["roles"].values()) != 1:
            errors.append({"path": f"$.decisions.{entry['handle']}.roles",
                           "error_code": "exactly_one_primary_required"})
    return errors


def treatment_schema(items: list[dict]) -> dict:
    decisions = {}
    for entry in items:
        if entry["collection"] != "aus" or entry["status"] != "active":
            continue
        sources = entry["source_ids"]
        evidence = obj({source: string_enum(("none", "authority", "response", "both"))
                        for source in sources})
        decisions[entry["handle"]] = {"oneOf": [
            obj({"choice": {"const": "unknown"}}),
            obj({"choice": {"const": "defer"}, "reason": reason()}),
            obj({"choice": string_enum(TREATMENTS), "reason": reason(),
                 "authority_witness": string_enum(sources),
                 "response_witness": string_enum(sources), "evidence": evidence})]}
    return obj({"decisions": obj(decisions)})


def validate_treatment(response: dict, items: list[dict]) -> list[dict]:
    errors = []
    for entry in items:
        if entry["collection"] != "aus" or entry["status"] != "active":
            continue
        decision = response["decisions"][entry["handle"]]
        if decision["choice"] in {"unknown", "defer"}:
            continue
        evidence = decision["evidence"]
        for field, accepted in (("authority_witness", {"authority", "both"}),
                                ("response_witness", {"response", "both"})):
            if evidence[decision[field]] not in accepted:
                errors.append({"path": f"$.decisions.{entry['handle']}.{field}",
                               "error_code": "witness_role_mismatch"})
    return errors


def finalizer_schema(items: list[dict]) -> dict:
    choices = {}
    for entry in items:
        branches = [obj({"choice": {"const": "keep"}})]
        if entry["status"] == "active":
            branches.append(obj({"choice": {"const": "defer"}, "reason": reason()}))
        branches.append(obj({"choice": {"const": "remove"}, "reason": reason()}))
        choices[entry["handle"]] = {"oneOf": branches}
    return obj({"decisions": obj(choices)})


def scan_schema(pairs: dict[str, list[str]]) -> dict:
    return obj({"choices": obj({item: obj({source: string_enum((
        "include", "exclude")) for source in sources})
        for item, sources in pairs.items()})})


def response_format(schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {
        "name": "kb_v14_choices", "strict": True, "schema": schema}}
