"""Authoritative V6 contract for repair-based extractive KB construction."""

from __future__ import annotations

import json

SCHEMA_VERSION = 6
PROMPT_VERSION = "kb-pilot-v6-protocol-fix-2"

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
primary reference. unknown treatment is valid when no authority-treatment relation is
asserted; both treatment evidence lists must then be empty. Any other treatment needs
selected authority and court-response evidence. Citation alone does not prove applies.
distinguishes contrasts an authority with the present case. Rejecting a party argument
does not by itself reject an authority. One source unit may contain both authority and
response only when its text actually supplies both."""

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
   and the response addresses that authority."""


def schema_text() -> str:
    return json.dumps(AGENT_SCHEMA, ensure_ascii=False, sort_keys=True, indent=2)


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

