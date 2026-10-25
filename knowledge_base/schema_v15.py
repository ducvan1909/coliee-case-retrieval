"""V15 two-stage source triage with phase-scoped constrained choices."""

from __future__ import annotations

from .schema_v10 import obj, schema_hash, string_enum, validate
from .schema_v14 import (
    classification_schema,
    finalizer_schema,
    navigation_schema,
    scan_schema,
    treatment_schema,
    validate_classification,
    validate_treatment,
)

SCHEMA_VERSION = 15
PROMPT_VERSION = "kb-pilot-v15-two-stage-triage-1"
POLICY = "two-stage-candidates"
TRIAGE_BATCH_SIZE = 4
REFINEMENT_BATCH_SIZE = 4

TRIAGE_CHOICES = ("skip", "uncertain", "brief", "aus", "both",
                  "refine_sentences")
REFINEMENT_CHOICES = ("skip", "uncertain", "brief", "aus", "both")


def reason() -> dict:
    return {"type": "string", "minLength": 1, "maxLength": 160}


def triage_schema(paragraphs: list[dict]) -> dict:
    if not 1 <= len(paragraphs) <= TRIAGE_BATCH_SIZE:
        raise ValueError("triage_batch_size_out_of_range")
    return obj({"choices": obj({paragraph["source_id"]: string_enum(
        TRIAGE_CHOICES) for paragraph in paragraphs})})


def refinement_schema(paragraphs: list[dict]) -> dict:
    if not 1 <= len(paragraphs) <= REFINEMENT_BATCH_SIZE:
        raise ValueError("refinement_batch_size_out_of_range")
    choices = {}
    for paragraph in paragraphs:
        sentences = paragraph.get("sentences", [])
        if not sentences:
            raise ValueError("refinement_requires_sentences")
        for sentence in sentences:
            choices[sentence["source_id"]] = string_enum(REFINEMENT_CHOICES)
    return obj({"choices": obj(choices)})


def validate_refinement(response: dict, paragraphs: list[dict]) -> list[dict]:
    """Every paragraph explicitly sent for refinement must yield one selection."""
    errors = []
    for paragraph in paragraphs:
        sentence_ids = [sentence["source_id"] for sentence in
                        paragraph.get("sentences", [])]
        if not sentence_ids or not any(
                response["choices"][source_id] != "skip"
                for source_id in sentence_ids):
            errors.append({"path": f"$.choices.{paragraph['source_id']}",
                           "error_code": "empty_sentence_selection"})
    return errors


def selection_review_schema(items: list[dict],
                            scan_modes: dict[str, set[str]]) -> dict:
    decisions = {}
    for entry in items:
        branches = [obj({"choice": {"const": "keep"}})]
        if entry["status"] == "active":
            for mode in sorted(scan_modes.get(entry["handle"], set())):
                branches.append(obj({"choice": {"const": mode},
                                     "reason": reason()}))
            branches.extend([
                obj({"choice": {"const": "defer"}, "reason": reason()}),
                obj({"choice": {"const": "remove"}, "reason": reason()}),
            ])
        else:
            branches.extend([
                obj({"choice": {"const": "restore"}, "reason": reason()}),
                obj({"choice": {"const": "remove"}, "reason": reason()}),
            ])
        decisions[entry["handle"]] = {"oneOf": branches}
    return obj({"decisions": obj(decisions)})


def response_format(schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {
        "name": "kb_v15_choices", "strict": True, "schema": schema}}

