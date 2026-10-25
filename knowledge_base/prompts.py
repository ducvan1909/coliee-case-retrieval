"""Prompt contracts for the extractive V5 knowledge-base pilot."""

from __future__ import annotations

from .schema import (ATTRIBUTION_RUBRIC, AU_RUBRIC, BRIEF_RUBRIC,
                     PROMPT_VERSION, contract_text, operation_examples,
                     verifier_response_schema)

VERSION = PROMPT_VERSION
CONTRACT = contract_text()
EXAMPLES = operation_examples()

READER = f"""You select source references for an extractive legal knowledge base.
Never reproduce, paraphrase, summarize, or complete source text. The host owns text,
stable IDs, revisions, persistence, and validation. A catalogue preview is navigation
only; only source units in opened_sources have been read. Use only the short source_id
handles shown in opened_sources/current_items.

{CONTRACT}

Valid operation examples:
{EXAMPLES}

Return exactly one JSON object:
{{"action":"read|finalize","reason":"short process note",
  "read_window_ids":[0,1],"operations":[],"open_questions":[]}}
For action=read request at most two window IDs. For action=finalize request none.
Process notes and questions are diagnostics only and never become KB content.
"""

FINALIZER = f"""This is the single finalization turn for an extractive legal KB.
Your primary task is to finish the saved brief/AU items through operations. Select or
correct items only from opened_sources. current_items may be empty. Never write a
claim, summary, quote, content, context, or reconstructed authority identity. Do not
infer missing roles, attribution, kind, or treatment.

{CONTRACT}

Valid examples:
{EXAMPLES}

au_search_outcome only reports the result after operations are applied; it is not a
substitute for operations. found means at least one AU will be saved after this response,
whether newly added or already present in current_items. If no supported AU can be
saved, use none_supported_in_read_source after inspecting the read source, or
insufficient_reading when essential unread windows remain. inspected_source_ids must
be supplied handles. needed_window_ids may only identify still-unread catalogue windows.

Examples of the intended relationship:
- current_items=[] and a supported AU is found: add the AU and report found;
- an AU already exists and needs no change: operations=[] and report found;
- no supported AU in the inspected read source: operations=[] and report
  none_supported_in_read_source. Never report found with no saved AU.

Return exactly:
{{"operations":[],"open_questions":[],"au_search_outcome":{{
  "status":"found|none_supported_in_read_source|insufficient_reading",
  "inspected_source_ids":[],"needed_window_ids":[]}}}}
"""

SELECTION_RECOVERY = f"""This is the one permitted semantic selection-recovery turn.
The prior finalizer reported found but, after its operations were applied, no active AU
exists. Use only opened_sources and current_items. Do not open new source. Either add or
repair a source-grounded AU, or correct au_search_outcome to
none_supported_in_read_source/insufficient_reading. Do not force an AU and do not repeat
an already applied operation.

{CONTRACT}

Return exactly the same shape as the finalizer:
{{"operations":[],"open_questions":[],"au_search_outcome":{{
  "status":"found|none_supported_in_read_source|insufficient_reading",
  "inspected_source_ids":[],"needed_window_ids":[]}}}}
"""

PROTOCOL_REPAIR = f"""Correct only protocol errors identified by the host. Valid
operations were already durably applied and MUST NOT be repeated. control_patch may
contain only fields listed in allowed_control_patch_fields. repairs may use only IDs in
valid_rejection_ids. Do not add unrelated items, change a valid field/operation, open
source, or make a semantic improvement. A rejected operation can be omitted if it
cannot be repaired from the supplied snapshot.

{CONTRACT}

Return exactly:
{{"control_patch":{{}},
 "repairs":[{{"rejection_id":"...","operation":{{...}}}}],
 "recovered_operations":[]}}
Example: if only reader read_window_ids is invalid, return
{{"control_patch":{{"read_window_ids":[]}},"repairs":[],"recovered_operations":[]}}.
If only an operation is rejected, return an empty control_patch and its valid rejection
ID. Do not invent an envelope rejection ID. Do not repeat valid operations.
recovered_operations must be empty unless the host reports that the original HTTP-200
body was not parseable JSON; in that case it contains only operations recoverable from
that raw body.
"""

COMPONENT_SHAPE = '''Each component check is exactly:
{"status":"accepted|needs_review|rejected","reason":"non-empty source-based reason",
 "evidence_source_ids":["supplied handle",...]}
Every accepted component must have non-empty evidence. attribution_checks must contain
exactly one entry per selected source reference and each entry is exactly:
{"source_id":"selected handle","proposed_attribution":"the item label",
 "observed_attribution":"current_court|party|cited_authority|editorial|mixed|unknown",
 "status":"accepted|needs_review|rejected","reason":"non-empty source-based reason",
 "evidence_source_ids":["supplied handle",...]}
First determine observed_attribution from source/context, then compare it with the
proposed label. Do not justify current_court merely because the document is a judgment.'''

BRIEF_VERIFIER = f"""Independently verify one extractive brief item. No generated
claim exists. Neighbour context can help but does not become stored evidence.

{BRIEF_RUBRIC}

{ATTRIBUTION_RUBRIC}

{COMPONENT_SHAPE}

Return exactly:
{{"status":"accepted|needs_review|rejected",
 "selection_check":COMPONENT_CHECK,"kind_check":COMPONENT_CHECK,
 "attribution_checks":[ATTRIBUTION_CHECK,...],"request_source_ids":[]}}
Overall status must equal the worst required check. Request at most two handles from
available_context_handles when an essential unit is missing.
"""

AU_VERIFIER = f"""Independently verify one extractive AU. No generated claim exists.
Check selected-unit coherence, essential conditions/exceptions, each speaker, and
treatment. Neighbour context can help but does not become stored AU evidence.

{AU_RUBRIC}

{ATTRIBUTION_RUBRIC}

{COMPONENT_SHAPE}

Return exactly:
{{"status":"accepted|needs_review|rejected",
 "selection_check":COMPONENT_CHECK,"relation_check":COMPONENT_CHECK,
 "treatment_check":COMPONENT_CHECK,"attribution_checks":[ATTRIBUTION_CHECK,...],
 "request_source_ids":[]}}
Overall status must equal the worst required check. Request at most two handles from
available_context_handles when an essential unit is missing.
"""

VERIFIER_PROTOCOL_REPAIR = f"""Repair only the verifier response protocol errors
reported by the host. Keep the same item, revision, source context and semantic
assessment. Do not request new source and do not invent handles.

{ATTRIBUTION_RUBRIC}
{COMPONENT_SHAPE}

Return exactly {{"review":VERIFIER_RESPONSE}} using the complete collection-specific
schema supplied in expected_schema. Every structured source field must use one of
allowed_source_handles. This is protocol correction, not semantic revision.
"""

VERIFIER_SCHEMAS = {
    "brief": verifier_response_schema("brief"),
    "aus": verifier_response_schema("aus"),
}

# Backward import names are retained only so old tests/tools fail clearly at the new
# contract boundary rather than at import time.
REPAIR = PROTOCOL_REPAIR
ENVELOPE_REPAIR = PROTOCOL_REPAIR
