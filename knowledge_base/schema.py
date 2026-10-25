"""Authoritative V5 contract shared by prompts and host validators."""

from __future__ import annotations

import json

SCHEMA_VERSION = 5
PROMPT_VERSION = "kb-pilot-v5-consistent-selection"

ATTRIBUTIONS = {"current_court", "party", "cited_authority", "editorial", "mixed", "unknown"}
TREATMENTS = {"adopts", "applies", "distinguishes", "rejects", "reports", "unknown"}
SOURCE_ROLES = {"primary", "context", "qualification", "court_response"}
BRIEF_KINDS = {"facts", "posture", "issues", "disposition"}
REVIEW_STATUSES = {"accepted", "needs_review", "rejected"}
AU_SEARCH_STATUSES = {"found", "none_supported_in_read_source", "insufficient_reading"}
FORBIDDEN_KEYS = {"content", "context", "quote", "excerpt", "text", "summary", "title", "claim"}

# JSON-compatible structural source of truth. Prompts and host validation import the
# same enum sets and field declarations instead of maintaining separate contracts.
AGENT_SCHEMA = {
    "source_ref": {
        "required": ["source_id", "role", "attribution"],
        "source_id": "a supplied P#### or S#### handle",
        "role": sorted(SOURCE_ROLES),
        "attribution": sorted(ATTRIBUTIONS),
    },
    "brief": {"required": ["kind", "source_refs"], "kind": sorted(BRIEF_KINDS)},
    "au": {"required": ["source_refs", "treatment"], "treatment": {
        "required": ["value", "authority_source_ids", "response_source_ids"],
        "value": sorted(TREATMENTS),
    }},
    "operations": {
        "add": ["op", "collection", "item"],
        "update": ["op", "id", "revision", "changes"],
        "remove": ["op", "id", "revision"],
    },
    "verifier": {
        "component_check": ["status", "reason", "evidence_source_ids"],
        "attribution_check": ["source_id", "proposed_attribution", "observed_attribution",
                              "status", "reason", "evidence_source_ids"],
    },
}

ATTRIBUTION_RUBRIC = """Attribution is the speaker or source of the proposition in the
selected unit, not the physical author of the judgment. current_court is the present
court's own finding or its narration of a procedural event as fact. party is a party's
argument, assertion, or requested relief. cited_authority includes quoted or reported
case law and legislation. editorial is identifiable headnote/editorial material. mixed
is for inseparable multiple speakers; prefer a narrower sentence when it remains
meaningful. unknown is for insufficient evidence or an uncovered embedded source such
as some witness/document material. A word such as applicant is not by itself decisive.
Neither mixed nor unknown is automatically correct, and neither implies court adoption.
Neither a translator's note nor wording such as "Translation by the Court" changes the
speaker of quoted material: attribute the proposition to the original quoted speaker
when the source makes that speaker identifiable."""

BRIEF_RUBRIC = """Brief categories and exclusions:
- facts: case events or evidence; legislation and legal rules are not facts;
- posture: procedural stage, challenged decision, or requested relief; the present
  court's final order is not posture;
- issues: a question the present court must decide; its answer/finding is not an issue;
- disposition: the present court's final decision or remedy.
A legal finding that fits no brief category must not be forced into brief; consider AU
or omit it with a diagnostic reason."""

AU_RUBRIC = """An AU may preserve a legal principle, qualification/exception,
application, evidence assessment, or procedural reasoning. It need not cite another
case. It requires a primary reference. unknown treatment is valid for an AU that does
not establish one of the listed authority-treatment relations and then both treatment
ID lists are empty. A non-unknown treatment needs selected authority and court-response
references. Citation alone does not prove applies; distinguishes must contrast an
authority with the present case, not merely contrast two concepts. Treatment always
describes how the current court handles an authority. Rejecting a party's argument does
not by itself mean that the court rejects an authority. One sentence may contain both
the authority and the current court's response, so identical authority/response source
IDs are permitted only when the sentence itself supplies both pieces of evidence. An AU
may also use several separate source references; do not reject it merely because its
authority and court response are in different units. Instead, decide whether their
content and available context establish the claimed relation."""


def schema_text() -> str:
    return json.dumps(AGENT_SCHEMA, ensure_ascii=False, sort_keys=True, indent=2)


def contract_text() -> str:
    """Render the complete contract independently into every model request."""
    return f'''SCHEMA VERSION {SCHEMA_VERSION}. Return source handles only; never copy,
paraphrase, summarize, or generate legal content. A source_id in a model response is
exactly a P#### or S#### handle supplied in that request. The host resolves it to a
stable source ID; never invent or reconstruct a handle.

Machine-readable structure:
{schema_text()}

Operations:
- add: {{"op":"add","collection":"brief|aus","item":ITEM}}
- update: {{"op":"update","id":"host id from current_items","revision":1,"changes":PARTIAL_ITEM}}
- remove: {{"op":"remove","id":"host id from current_items","revision":1}}
Update/remove may target only an item shown in current_items at the start of this
request. A newly added item can be changed only in a later request.

SOURCE_REF is exactly:
{{"source_id":"P#### or S####","role":"{'|'.join(sorted(SOURCE_ROLES))}",
 "attribution":"{'|'.join(sorted(ATTRIBUTIONS))}"}}

BRIEF_ITEM is exactly:
{{"kind":"{'|'.join(sorted(BRIEF_KINDS))}","source_refs":[SOURCE_REF,...]}}
Brief has no treatment.

AU_ITEM is exactly:
{{"source_refs":[SOURCE_REF,...],"treatment":{{"value":"{'|'.join(sorted(TREATMENTS))}",
 "authority_source_ids":["handle",...],"response_source_ids":["handle",...]}}}}

{BRIEF_RUBRIC}

{ATTRIBUTION_RUBRIC}

{AU_RUBRIC}

Never include content, context, quote, excerpt, text, summary, title, claim, id,
revision, deleted, source_hash, review, or excerpts inside ITEM. Never select a
paragraph together with a child sentence in one item. Do not restore an authority
identity hidden by <FRAGMENT_SUPPRESSED>.'''


OPERATION_EXAMPLES = [
    {"op": "add", "collection": "brief", "item": {"kind": "issues", "source_refs": [
        {"source_id": "S0003", "role": "primary", "attribution": "current_court"}]}},
    {"op": "add", "collection": "aus", "item": {"source_refs": [
        {"source_id": "S0010", "role": "primary", "attribution": "current_court"}],
        "treatment": {"value": "unknown", "authority_source_ids": [],
                      "response_source_ids": []}}},
    {"op": "add", "collection": "aus", "item": {"source_refs": [
        {"source_id": "S0020", "role": "primary", "attribution": "cited_authority"},
        {"source_id": "S0021", "role": "court_response", "attribution": "current_court"}],
        "treatment": {"value": "applies", "authority_source_ids": ["S0020"],
                      "response_source_ids": ["S0021"]}}},
    {"op": "update", "id": "000001:brief:000", "revision": 1,
     "changes": {"kind": "facts"}},
]


def operation_examples() -> str:
    rendered = [json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                for value in OPERATION_EXAMPLES]
    return "Valid examples:\n" + "\n".join(rendered) + \
        '\nno change: {"operations":[],"open_questions":[]}'


def verifier_response_schema(collection: str) -> dict:
    """Return the complete collection-specific verifier response description."""
    component = {
        "status": sorted(REVIEW_STATUSES),
        "reason": "non-empty source-based reason",
        "evidence_source_ids": ["supplied handle"],
    }
    result = {
        "status": sorted(REVIEW_STATUSES),
        "selection_check": component,
        "attribution_checks": [{
            "source_id": "selected handle",
            "proposed_attribution": sorted(ATTRIBUTIONS),
            "observed_attribution": sorted(ATTRIBUTIONS),
            **component,
        }],
        "request_source_ids": ["offered context handle; at most two"],
    }
    if collection == "brief":
        result["kind_check"] = component
    elif collection == "aus":
        result["relation_check"] = component
        result["treatment_check"] = component
    else:
        raise ValueError("unknown_collection")
    return result
