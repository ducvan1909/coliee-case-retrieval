"""Prompts for V9 repair-loop KB construction."""

from __future__ import annotations

import json

from .schema_v9 import (CONTRASTIVE_EXAMPLES, PROMPT_VERSION, contract_text,
                        protocol_repair_schema_text)

VERSION = PROMPT_VERSION
CONTRACT = contract_text()
PROTOCOL_REPAIR_CONTRACT = protocol_repair_schema_text()

EXAMPLES = '''Complete operation examples (illustrative handles only):
add brief: {"op":"add","collection":"brief","item":{"kind":"issues","source_refs":[{"source_id":"S0003","role":"primary","attribution":"current_court"}]},"reason":"issue is expressly stated"}
add AU: {"op":"add","collection":"aus","item":{"source_refs":[{"source_id":"S0010","role":"primary","attribution":"current_court"}],"treatment":{"value":"unknown","authority_source_ids":[],"response_source_ids":[]}},"reason":"court states a legal principle"}
update: {"op":"update","id":"013948:brief:000","revision":1,"changes":{"kind":"posture"},"reason":"source describes the procedural stage"}
keep existing item: "operations":[]; omission does not delete or defer it.
The host alone creates item IDs and revisions. Never put id or revision inside add.item.'''

AU_PRIORITY_EXAMPLES = '''Synthetic examples, never copy this text into the KB:
"The appeal is allowed and the order set aside." is brief disposition.
"Because notice was withheld, the hearing was unfair." has legal reasoning suitable
for AU primary; the separate final order remains brief disposition.
"A party must receive notice of evidence used against it." can be AU primary with
unknown treatment and empty evidence lists when no cited authority is treated.
"Applying Smith's notice rule, we set aside the decision." may use the sentence once
in source_refs and the same handle in both treatment evidence lists if the text
actually supplies both Smith's rule and the court's application.
"The application is granted." alone does not establish applies treatment.
Find reusable legal propositions for future NN searches. Preserve facts, posture,
issues and disposition in brief for Case comparison.'''

CONTROL_EXAMPLES = '''Reader: {"action":"read","reason":"inspect the legal analysis","read_window_ids":[2],"operations":[],"open_questions":[]}
Reader done: {"action":"finalize","reason":"draft ready","read_window_ids":[],"operations":[],"open_questions":[]}
Repair read: {"action":"read","reason":"inspect missing qualification","read_window_ids":[3],"operations":[],"open_questions":[],"item_checks":[]}
Repair done: {"action":"complete","reason":"selection checked","read_window_ids":[],"operations":[],"open_questions":[],"item_checks":[]}
Only read may request windows. A continuation must use complete with read_window_ids=[].'''

CHECK_EXAMPLE = '''For every item supplied at request start, include exactly one
item_checks entry: {"id":"case:aus:000","revision":1,"decision":"keep",
"reason":"the selected sentence states the needed rule","source_ids":["S0010"]}.
Decisions are keep, update, defer, remove or restore; every non-keep decision
must have a matching operation on that item. Use handles supplied in this request.
An empty current_items and unresolved_items list requires item_checks=[].'''

REPLACE_REPAIR_EXAMPLE = {"rejection_id": "000001:selection_repair:0:op:2",
    "resolution": "replace", "operation": {"op": "add", "collection": "aus",
    "item": {"source_refs": [
        {"source_id": "S0010", "role": "primary", "attribution": "current_court"},
        {"source_id": "S0011", "role": "court_response",
         "attribution": "current_court"}],
        "treatment": {"value": "applies", "authority_source_ids": ["S0010"],
                      "response_source_ids": ["S0011"]}},
    "reason": "select both authority and court-response evidence"}}
WITHDRAW_REPAIR_EXAMPLE = {"rejection_id": "000001:selection_repair:0:op:3",
    "resolution": "withdraw",
    "reason": "the supplied source does not support the proposed authority treatment",
    "source_ids": ["S0012"]}
MIXED_REPAIR_RESPONSE_EXAMPLE = {"control_patch": {"action": "complete"},
    "repairs": [WITHDRAW_REPAIR_EXAMPLE]}
REPAIR_EXAMPLES = f'''Complete protocol-repair examples (illustrative IDs and handles):
replace:
{json.dumps(REPLACE_REPAIR_EXAMPLE, ensure_ascii=False, separators=(",", ":"))}
withdraw:
{json.dumps(WITHDRAW_REPAIR_EXAMPLE, ensure_ascii=False, separators=(",", ":"))}
Every repair entry MUST include resolution. replace contains exactly rejection_id,
resolution and operation. withdraw contains exactly rejection_id, resolution, reason
and source_ids. Every treatment evidence handle must also occur in source_refs.'''

MIXED_REPAIR_EXAMPLE = f'''Combined control and operation repair example:
{json.dumps(MIXED_REPAIR_RESPONSE_EXAMPLE, ensure_ascii=False, separators=(",", ":"))}'''

READER = f"""Build an extractive legal KB by selecting source handles and labels.
Never write legal content. Catalogue previews are navigation only; only opened_sources
have been read. Save useful draft items cumulatively through operations.

{AU_PRIORITY_EXAMPLES}

{CONTRACT}
{EXAMPLES}
{CONTROL_EXAMPLES}

Return exactly:
{{"action":"read|finalize","reason":"short process note",
  "read_window_ids":[0,1],"operations":[],"open_questions":[]}}
For read, request at most two unread windows. For finalize, request none. A source just
opened will be supplied in a later turn and cannot be selected in this response.
When unread_window_ids is empty or remaining_read_actions is zero, process the
opened sources in this turn and use action=finalize with read_window_ids=[].
"""

SELECTION_REPAIR = f"""Repair source selection in the complete current draft. Inspect
every active and deferred item, selected sources, supplied parent/neighbour context and
the catalogue. Add omitted source-grounded brief/AU opportunities; add missing
conditions, qualifications and court responses; replace headings, bare citations or
irrelevant units; split, merge, defer or remove unsupported/duplicate items. Do not
perform a cosmetic rewrite and do not generate legal content.

{AU_PRIORITY_EXAMPLES}

{CONTRACT}
{EXAMPLES}
{CONTROL_EXAMPLES}
{CHECK_EXAMPLE}

Return exactly:
{{"action":"read|complete","reason":"short process note",
  "read_window_ids":[0,1],"operations":[],"open_questions":[],"item_checks":[]}}
Request at most two unread windows and only when you state a concrete purpose. You may
not select source from a requested window until the continuation turn supplies it. The
continuation must complete and cannot request more source.
If unread_window_ids is nonempty on the first selection repair turn, request one or
two windows whose catalogue preview suggests omitted legal reasoning. The host will
provide them in the continuation. Check every item in item_checks.
"""

ATTRIBUTION_REPAIR = f"""Inspect every item and the host source_label_matrix. Correct
brief kind, source role and attribution. Do not change treatment. A conflict is a
signal to read the source, not proof that either label is correct. Distinguish a
court's own legal statement, quoted authority, reported party request and headnote.
Prefer a narrower sentence to an inseparable mixed paragraph. Check every item in
item_checks even when it remains unchanged.

{AU_PRIORITY_EXAMPLES}

{CONTRASTIVE_EXAMPLES}

{CONTRACT}
{EXAMPLES}
{CONTROL_EXAMPLES}
{CHECK_EXAMPLE}

Return exactly one JSON object:
{{"action":"complete","reason":"short process note",
  "read_window_ids":[],"operations":[],"open_questions":[],"item_checks":[]}}
Request at most two unread windows. The continuation must complete and cannot request
more source.
"""

TREATMENT_REPAIR = f"""Inspect every AU's authority treatment on the current state.
Do not change brief kind, source role or attribution. The authority evidence must
contain the actual authority proposition; a bare citation or party argument is not
authority evidence. The court-response evidence must show how the present court
treats that authority. An AU without a supported relation may retain unknown treatment.
Check every item in item_checks, including brief items, and record why it stays or
changes. Do not claim that a conclusion or remedy alone is applies.

{AU_PRIORITY_EXAMPLES}
{CONTRASTIVE_EXAMPLES}
{CONTRACT}
{EXAMPLES}
{CONTROL_EXAMPLES}
{CHECK_EXAMPLE}

Return exactly one JSON object with action, reason, read_window_ids, operations,
open_questions and item_checks. A continuation must complete with no new windows.
"""

FINALIZER = f"""This is the single V9 finalization turn. Use only supplied source.
Make final operations, keeping supported items active and moving doubtful items to the
deferred set with a concrete reason. Do not force an AU, do not force unknown merely to
retain an item, and do not use item counts as a target. unknown treatment is valid when
no authority relation is asserted. unknown attribution is valid only when the supplied
source truly cannot identify the speaker. An empty final KB is permitted.

{AU_PRIORITY_EXAMPLES}

{CONTRACT}
{EXAMPLES}
{CHECK_EXAMPLE}

Return exactly one JSON object:
{{"operations":[],"open_questions":[],"reason":"short process note","item_checks":[]}}
item_checks must record a keep, update, defer or remove decision for every active
item present at request start, with its id, revision, short reason and supplied
source_ids. Keep is a decision, not an operation. update/defer/remove decisions
must correspond to an operation in this response.
"""

def protocol_repair_prompt(phase: str, *, control_errors: list[dict],
                           rejected_operations: list[dict],
                           allowed_control_fields: list[str]) -> str:
    """Give the model only the branch of the repair contract it needs."""
    header = ("Repair the listed protocol errors. Return one JSON object with exactly "
              'two fields: {"control_patch":{},"repairs":[]}. '
              "The host already applied valid operations. Do not repeat them or "
              "open source during this request. A corrected read request may be "
              "opened by the host only after validation. The payload field "
              "expected_repair_response is the contract for this answer; "
              "original_phase_response_contract only describes the response that "
              "was being repaired.\n")
    if control_errors and not rejected_operations:
        example = ""
        if ("action" in allowed_control_fields and
                any(error.get("error_code") == "requested_window_not_unread"
                    for error in control_errors)):
            action = "finalize" if phase == "reader" else "complete"
            example = (f'For action=read with read_window_ids=[] and no reading '
                       f'available, return exactly '
                       f'{{"control_patch":{{"action":"{action}"}},"repairs":[]}}.\n')
        return (header + "Only control fields are wrong. Put corrections in "
            "control_patch, using only allowed_control_patch_fields. "
            "repairs MUST be []. A control error_id identifies an error in the log; "
            "it is NEVER a rejection_id and must not appear in repairs. "
            "An empty patch does not resolve an incorrect field.\n" + example)
    if rejected_operations and not control_errors:
        return (header + "Only operations were rejected. control_patch MUST be {}. "
            "Each repairs entry uses one ID from valid_rejection_ids, never a "
            "control error_id. Include resolution explicitly. Replace with a corrected "
            "operation or withdraw "
            "with a non-empty reason and supplied source_ids. Omitting a rejected "
            "operation leaves it unresolved.\nProtocol repair response schema:\n" +
            PROTOCOL_REPAIR_CONTRACT + "\n" + REPAIR_EXAMPLES + "\n" + CONTRACT +
            "\n" + EXAMPLES)
    return (header + "Both control and operations have errors. Correct only "
        "allowed_control_patch_fields in control_patch. Each repairs entry uses "
        "an ID from valid_rejection_ids, never a control error_id, and explicitly "
        "includes resolution. Resolve every "
        "rejected operation by replacement or explicit withdrawal; omission "
        "leaves it unresolved.\nProtocol repair response schema:\n" +
        PROTOCOL_REPAIR_CONTRACT + "\n" + REPAIR_EXAMPLES + "\n" +
        MIXED_REPAIR_EXAMPLE + "\n" + CONTRACT + "\n" + EXAMPLES)

FULL_RESPONSE_REPAIR = f"""The previous answer was not one valid JSON object.
No operation from it was applied. Return one complete replacement response for
the current phase, using the supplied source and current item snapshot. Do not
concatenate objects or wrap the response in markdown. The replacement must obey:

{CONTRACT}
{EXAMPLES}
{CONTROL_EXAMPLES}
{CHECK_EXAMPLE}

If the phase is finalizer, return operations, reason, open_questions and item_checks.
Otherwise return action, reason, read_window_ids, operations and open_questions;
repair phases also require item_checks. An allowed read request may be preserved.
"""

