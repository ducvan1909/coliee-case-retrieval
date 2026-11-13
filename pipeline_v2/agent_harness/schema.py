"""Model response schema shared by structured decoding and the M4 host."""

from copy import deepcopy
from functools import lru_cache
import json

from jsonschema import Draft202012Validator

from .contracts import HarnessError, encode, fingerprint


ASSESSMENT_SCHEMA_VERSION = "m4-assessment-v2"
ASSESSMENT_VALIDATOR_VERSION = "m4-assessment-validator-v2"
RESPONSE_SCHEMA_VERSION = "m4-response-v2"
LEGACY_RESPONSE_SCHEMA_VERSION = "m4-response-v1"
SEARCH_ACTIONS = frozenset({"search_corpus", "search_case", "search_phrase", "search_identity"})
TOOL_ACTIONS = SEARCH_ACTIONS | {"open_source", "expand_source", "open_query"}
CASE_RELATIONS = ("supported", "plausible", "similarity_only", "contradicted", "unknown")
PASSAGE_LOCATIONS = ("pinpoint", "bounded", "unresolved")
SPEAKER_TYPES = {
    "court": ("own_reasoning", "adopted_reasoning"),
    "party": ("submission",),
    "quoted_source": ("quotation",),
}
REF_FIELDS = ("a_context_refs", "b_passage_refs", "identity_support_refs",
              "speaker_evidence_refs", "quote_chain_refs", "container_refs")
TEXT = {"type": "string", "minLength": 1}
REFS = {"type": "array", "items": TEXT}


class ResponseSchemaError(HarnessError):
    """The controller reply violates the pinned JSON response schema."""


def _object(properties, required):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


def _enum(values):
    return {"type": "string", "enum": list(values)}


def _tag(value):
    return {"type": "string", "const": value}


def assessment_schema():
    speaker = [_object({"role": _tag("unknown")}, ("role",))]
    speaker.extend(_object({"role": _tag(role), "type": _enum(types), "side": _enum(("A", "B"))},
                           ("role", "type")) for role, types in SPEAKER_TYPES.items())
    return deepcopy(_object({
        "source_need_id": TEXT, "candidate_id": TEXT, "case_relation": _enum(CASE_RELATIONS),
        "passage_location": _enum(PASSAGE_LOCATIONS), "reason": TEXT,
        **dict.fromkeys(REF_FIELDS, REFS),
        "speaker": {"type": "object", "anyOf": speaker},
        "counterevidence": {"anyOf": [TEXT, REFS]},
        "missing_evidence": {"anyOf": [TEXT, REFS]},
    }, ("source_need_id", "candidate_id", "case_relation", "passage_location", "reason", *REF_FIELDS[:2])))


def _action(name, args):
    return _object({"action": _tag(name), "args": args}, ("action", "args"))


@lru_cache
def _schema(tool_actions):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": RESPONSE_SCHEMA_VERSION,
        "type": "object",
        "anyOf": [
            _action("assess_links", _object({
                "assessments": {"type": "array", "minItems": 1, "items": assessment_schema()},
            }, ("assessments",))),
            _action("reload_source", _object({"refs": {**REFS, "minItems": 1}}, ("refs",))),
            _action("stop", _object({"reason": _tag("complete"), "prediction": REFS, "assessment_ids": REFS},
                                    ("reason", "prediction"))),
            _action("stop", _object({"reason": _enum(("budget", "no_progress", "failure"))}, ("reason",))),
            *(_action(name, {"type": "object"}) for name in tool_actions),
        ],
    }


def _tools(tool_actions):
    names = TOOL_ACTIONS if tool_actions is None else set(tool_actions)
    if not names <= TOOL_ACTIONS:
        raise HarnessError("Unknown tool action in response schema")
    return tuple(sorted(names))


def response_schema(tool_actions=None):
    """Return a JSON Schema document for the configured controller actions."""
    return deepcopy(_schema(_tools(tool_actions)))


def response_schema_fingerprint(tool_actions=None):
    return fingerprint(_schema(_tools(tool_actions)))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ResponseSchemaError("duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ResponseSchemaError("nonfinite_json_number")


def parse_model_response(value):
    try:
        if isinstance(value, str):
            value = json.loads(value, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        encode(value)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ResponseSchemaError("invalid_json") from exc
    return value


@lru_cache
def _validator(tool_actions):
    return Draft202012Validator(_schema(tool_actions))


def validate_model_response(value, tool_actions=None):
    """Parse a model reply and validate it against the exported JSON Schema."""
    value = parse_model_response(value)
    if isinstance(value, dict) and isinstance(value.get("action"), str):
        # Select the disjoint action branches to report an actionable JSON path.
        schema = _schema(_tools(tool_actions))
        branches = [row for row in schema["anyOf"] if row["properties"]["action"]["const"] == value["action"]]
        if len(branches) == 1:
            error = next(Draft202012Validator(branches[0]).iter_errors(value), None)
        else:
            error = next(_validator(_tools(tool_actions)).iter_errors(value), None)
    else:
        error = next(_validator(_tools(tool_actions)).iter_errors(value), None)
    if error is not None:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ResponseSchemaError(f"{path}:{error.validator}")
    return value
