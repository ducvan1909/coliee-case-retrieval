"""Authoritative V9 contract for repair-based extractive KB construction."""

from __future__ import annotations

import json

SCHEMA_VERSION = 9
PROMPT_VERSION = "kb-pilot-v9-operation-repair-2"

ATTRIBUTIONS = {"current_court", "party", "cited_authority", "editorial", "mixed", "unknown"}
TREATMENTS = {"adopts", "applies", "distinguishes", "rejects", "reports", "unknown"}
SOURCE_ROLES = {"primary", "context", "qualification", "court_response"}
BRIEF_KINDS = {"facts", "posture", "issues", "disposition"}
FORBIDDEN_KEYS = {"content", "context", "quote", "excerpt", "text", "summary", "title", "claim"}

AGENT_SCHEMA = {
    "source_ref": {
        "required": ["source_id", "role", "attribution"],
        "source_id": "a P#### or S#### handle supplied in this request",
        "role": sorted(SOURCE_ROLES),
        "attribution": sorted(ATTRIBUTIONS),
    },
    "brief": {"required": ["kind", "source_refs"], "kind": sorted(BRIEF_KINDS)},
    "au": {"required": ["source_refs", "treatment"], "treatment": {
        "required": ["value", "authority_source_ids", "response_source_ids"],
        "value": sorted(TREATMENTS),
    }},
    "operations": {
        "add": ["op", "collection", "item", "reason"],
        "update": ["op", "id", "revision", "changes", "reason"],
        "remove": ["op", "id", "revision", "reason"],
        "defer": ["op", "id", "revision", "reason"],
        "restore": ["op", "id", "revision", "reason"],
    },
}

PROTOCOL_REPAIR_SCHEMA = {
    "type": "object",
    "required": ["control_patch", "repairs"],
    "additionalProperties": False,
    "properties": {
        "control_patch": {
            "type": "object",
            "description": "Only fields named by allowed_control_patch_fields.",
        },
        "repairs": {
            "type": "array",
            "items": {
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["rejection_id", "resolution", "operation"],
                        "additionalProperties": False,
                        "properties": {
                            "rejection_id": {"type": "string"},
                            "resolution": {"const": "replace"},
                            "operation": {"type": "object"},
                        },
                    },
                    {
                        "type": "object",
                        "required": ["rejection_id", "resolution", "reason", "source_ids"],
                        "additionalProperties": False,
                        "properties": {
                            "rejection_id": {"type": "string"},
                            "resolution": {"const": "withdraw"},
                            "reason": {"type": "string", "minLength": 1},
                            "source_ids": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                ]
            },
        },
    },
}

ATTRIBUTION_RUBRIC = """Attribution identifies the speaker of the selected proposition,
not the physical author of the judgment. current_court is the present court's own
finding or its narration of a procedural event as fact. party is a party's argument,
assertion, or requested relief even when the court reports it. cited_authority is a
proposition attributed to case law or legislation. editorial is identifiable headnote
or editorial material. mixed is only for inseparable multiple speakers; prefer a
narrower sentence. unknown is for genuinely insufficient source evidence. A citation
does not by itself make the present court's own sentence cited_authority. A translator
note does not change the original speaker of translated material."""

BRIEF_RUBRIC = """Brief categories:
- facts: case events or evidence, not legislation or a legal rule;
- posture: procedural stage, challenged decision, or requested relief;
- issues: a question the present court must decide, not its answer;
- disposition: the present court's final decision or remedy.
A legal finding that fits no brief category must not be forced into brief."""

AU_RUBRIC = """An AU preserves a source-grounded legal principle, qualification,
exception, application, evidence assessment, or procedural reasoning and requires a
primary reference containing the central legal reasoning. Prefer reusable legal
propositions over bare outcomes. A sentence that only announces the final order belongs
in brief disposition; reasoning beside an order may still be an AU. An AU need not cite
another authority. unknown treatment is valid when no authority-treatment relation is
asserted; both treatment evidence lists must then be empty. Any other treatment needs
selected authority and court-response evidence. Citation alone does not prove applies.
distinguishes contrasts an authority with the present case. Rejecting a party argument
does not by itself reject an authority. Issuing a remedy is not applies treatment.
Each source ID appears once in source_refs; the same selected ID may appear in both
treatment evidence lists only if its text actually supplies authority and response.
Every ID in authority_source_ids and response_source_ids MUST also appear exactly once
in source_refs. Evidence lists point to selected sources; they do not select sources."""

CONTRASTIVE_EXAMPLES = """Synthetic classification contrasts (examples are not case
facts and must never be copied into the KB):
1. "Applying Smith, we conclude the appeal fails." The court's conclusion is
   current_court; the embedded Smith proposition is cited_authority only if separately
   addressable. A citation does not turn the whole sentence into cited_authority.
2. "The applicant asks this Court to set aside the order." The requested relief is
   party attribution and brief kind posture.
3. "The tribunal dismissed the first application." When narrated as a procedural
   event, this is current_court attribution and posture/facts according to its function.
4. A publisher-written case synopsis or headnote is editorial, not current_court.
5. "Translation by the Court" identifies who translated, not who originally spoke.
6. "Counsel argued X, but we reject it." Prefer separate sentence units; if inseparable,
   the full unit is mixed. Rejecting X is not rejects treatment unless X is an authority
   and the response addresses that authority.
7. "Section 4 requires notice." If this is a direct quotation of a statute, attribute
   the selected proposition to cited_authority; a court's own paraphrase is
   current_court even when followed by a citation.
8. "The court found the hearing unfair." This is an answer or finding, not the
   issue question itself. Select the question separately for brief issues."""


def schema_text() -> str:
    return json.dumps(AGENT_SCHEMA, ensure_ascii=False, sort_keys=True, indent=2)


def protocol_repair_schema_text() -> str:
    return json.dumps(PROTOCOL_REPAIR_SCHEMA, ensure_ascii=False, sort_keys=True,
                      indent=2)


def validate_protocol_repair_response(value: object) -> dict:
    """Validate repair-response structure without applying host authorization rules.

    Rejection membership, source access, operation revisions and operation targets are
    deliberately checked by the pipeline. Structural entry results are separate so a
    valid sibling can still be applied while an invalid entry blocks phase completion.
    """
    result = {"envelope_errors": [], "entries": []}
    if not isinstance(value, dict):
        result["envelope_errors"].append({"path": "$", "error_code":
                                          "response_must_be_object"})
        return result
    required = {"control_patch", "repairs"}
    for field in sorted(required - set(value)):
        result["envelope_errors"].append({"path": field, "error_code":
                                          "missing_required_field"})
    for field in sorted(set(value) - required):
        result["envelope_errors"].append({"path": field, "error_code":
                                          "unexpected_field"})
    if "control_patch" in value and not isinstance(value["control_patch"], dict):
        result["envelope_errors"].append({"path": "control_patch", "error_code":
                                          "invalid_type"})
    repairs = value.get("repairs")
    if "repairs" in value and not isinstance(repairs, list):
        result["envelope_errors"].append({"path": "repairs", "error_code":
                                          "invalid_type"})
        return result
    if not isinstance(repairs, list):
        return result
    for index, entry in enumerate(repairs):
        prefix = f"repairs[{index}]"
        errors = []
        if not isinstance(entry, dict):
            errors.append({"path": prefix, "error_code": "invalid_type"})
            result["entries"].append({"index": index, "value": entry,
                                      "errors": errors})
            continue
        for field in ("rejection_id", "resolution"):
            if field not in entry:
                errors.append({"path": f"{prefix}.{field}", "error_code":
                               "missing_required_field"})
        rejection_id = entry.get("rejection_id")
        if "rejection_id" in entry and (not isinstance(rejection_id, str) or
                                          not rejection_id.strip()):
            errors.append({"path": f"{prefix}.rejection_id", "error_code":
                           "invalid_type"})
        resolution = entry.get("resolution")
        if "resolution" in entry and resolution not in {"replace", "withdraw"}:
            errors.append({"path": f"{prefix}.resolution", "error_code":
                           "invalid_enum_value"})
        expected = None
        if resolution == "replace":
            expected = {"rejection_id", "resolution", "operation"}
            if "operation" in entry and not isinstance(entry["operation"], dict):
                errors.append({"path": f"{prefix}.operation", "error_code":
                               "invalid_type"})
        elif resolution == "withdraw":
            expected = {"rejection_id", "resolution", "reason", "source_ids"}
            if "reason" in entry and (not isinstance(entry["reason"], str) or
                                       not entry["reason"].strip()):
                errors.append({"path": f"{prefix}.reason", "error_code":
                               "invalid_nonempty_string"})
            source_ids = entry.get("source_ids")
            if "source_ids" in entry and (not isinstance(source_ids, list) or
                    any(not isinstance(source_id, str) for source_id in source_ids)):
                errors.append({"path": f"{prefix}.source_ids", "error_code":
                               "invalid_type"})
            elif isinstance(source_ids, list) and len(source_ids) != len(set(source_ids)):
                errors.append({"path": f"{prefix}.source_ids", "error_code":
                               "duplicate_source_id"})
        if expected is not None:
            for field in sorted(expected - set(entry)):
                if field not in {"rejection_id", "resolution"}:
                    errors.append({"path": f"{prefix}.{field}", "error_code":
                                   "missing_required_field"})
            for field in sorted(set(entry) - expected):
                errors.append({"path": f"{prefix}.{field}", "error_code":
                               "unexpected_field"})
        result["entries"].append({"index": index, "value": entry,
                                  "errors": errors})
    return result


def contract_text() -> str:
    return f'''SCHEMA VERSION {SCHEMA_VERSION}. Return source handles only. Never copy,
paraphrase, summarize, or generate legal content. The host owns exact source text,
stable IDs, revisions, persistence and materialization.

Machine-readable structure:
{schema_text()}

SOURCE_REF is exactly:
{{"source_id":"P#### or S####","role":"{'|'.join(sorted(SOURCE_ROLES))}",
 "attribution":"{'|'.join(sorted(ATTRIBUTIONS))}"}}

BRIEF_ITEM is exactly:
{{"kind":"{'|'.join(sorted(BRIEF_KINDS))}","source_refs":[SOURCE_REF,...]}}

AU_ITEM is exactly:
{{"source_refs":[SOURCE_REF,...],"treatment":{{"value":"{'|'.join(sorted(TREATMENTS))}",
 "authority_source_ids":["handle",...],"response_source_ids":["handle",...]}}}}

Operations require a non-empty process reason:
- add: {{"op":"add","collection":"brief|aus","item":ITEM,"reason":"..."}}
- update: {{"op":"update","id":"host id","revision":1,"changes":PARTIAL_ITEM,"reason":"..."}}
- remove: {{"op":"remove","id":"host id","revision":1,"reason":"..."}}
- defer: {{"op":"defer","id":"host id","revision":1,"reason":"..."}}
- restore: {{"op":"restore","id":"host id","revision":2,"reason":"..."}}

Update/remove/defer/restore may target only an item shown at request start. defer moves
an item to unresolved_items; restore returns it to the active KB. remove is an explicit
deletion. A newly added item can be changed only in a later request.

{BRIEF_RUBRIC}

{ATTRIBUTION_RUBRIC}

{AU_RUBRIC}

Never place generated content, context, quote, excerpt, text, summary, title, claim,
review or materialized excerpts inside an item. Never select a paragraph with one of
its child sentences in the same item. Do not reconstruct identities hidden by
<FRAGMENT_SUPPRESSED>.'''

