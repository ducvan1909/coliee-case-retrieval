"""Prompts for V6 repair-loop KB construction."""

from __future__ import annotations

from .schema_v6 import (CONTRASTIVE_EXAMPLES, PROMPT_VERSION, contract_text)

VERSION = PROMPT_VERSION
CONTRACT = contract_text()

EXAMPLES = '''Complete operation examples (illustrative handles only):
add brief: {"op":"add","collection":"brief","item":{"kind":"issues","source_refs":[{"source_id":"S0003","role":"primary","attribution":"current_court"}]},"reason":"issue is expressly stated"}
add AU: {"op":"add","collection":"aus","item":{"source_refs":[{"source_id":"S0010","role":"primary","attribution":"current_court"}],"treatment":{"value":"unknown","authority_source_ids":[],"response_source_ids":[]}},"reason":"court states a legal principle"}
update: {"op":"update","id":"013948:brief:000","revision":1,"changes":{"kind":"posture"},"reason":"source describes the procedural stage"}
keep existing item: "operations":[]; omission does not delete or defer it.
The host alone creates item IDs and revisions. Never put id or revision inside add.item.'''

CONTROL_EXAMPLES = '''Reader: {"action":"read","reason":"inspect the legal analysis","read_window_ids":[2],"operations":[],"open_questions":[]}
Reader done: {"action":"finalize","reason":"draft ready","read_window_ids":[],"operations":[],"open_questions":[]}
Repair read: {"action":"read","reason":"inspect missing qualification","read_window_ids":[3],"operations":[],"open_questions":[]}
Repair done: {"action":"complete","reason":"selection checked","read_window_ids":[],"operations":[],"open_questions":[]}
Only read may request windows. A continuation must use complete with read_window_ids=[].'''

READER = f"""Build an extractive legal KB by selecting source handles and labels.
Never write legal content. Catalogue previews are navigation only; only opened_sources
have been read. Save useful draft items cumulatively through operations.

{CONTRACT}
{EXAMPLES}
{CONTROL_EXAMPLES}

Return exactly:
{{"action":"read|finalize","reason":"short process note",
  "read_window_ids":[0,1],"operations":[],"open_questions":[]}}
For read, request at most two unread windows. For finalize, request none. A source just
opened will be supplied in a later turn and cannot be selected in this response.
"""

SELECTION_REPAIR = f"""Repair source selection in the complete current draft. Inspect
every active and deferred item, selected sources, supplied parent/neighbour context and
the catalogue. Add omitted source-grounded brief/AU opportunities; add missing
conditions, qualifications and court responses; replace headings, bare citations or
irrelevant units; split, merge, defer or remove unsupported/duplicate items. Do not
perform a cosmetic rewrite and do not generate legal content.

{CONTRACT}
{EXAMPLES}
{CONTROL_EXAMPLES}

Return exactly:
{{"action":"read|complete","reason":"short process note",
  "read_window_ids":[0,1],"operations":[],"open_questions":[]}}
Request at most two unread windows and only when you state a concrete purpose. You may
not select source from a requested window until the continuation turn supplies it. The
continuation must complete and cannot request more source.
"""

CLASSIFICATION_REPAIR = f"""Repair classification and cross-item consistency after
source selection. Inspect every item and the host source_label_matrix. Correct brief
kind, source role, attribution and authority treatment. A conflict is a signal to read
the source and resolve it, not proof that either label is correct. Confirm that
authority proposition and court response actually establish the treatment. Defer an
item whose essential classification cannot be supported.

{CONTRASTIVE_EXAMPLES}

{CONTRACT}
{EXAMPLES}
{CONTROL_EXAMPLES}

Return exactly:
{{"action":"read|complete","reason":"short process note",
  "read_window_ids":[0,1],"operations":[],"open_questions":[]}}
Request at most two unread windows. The continuation must complete and cannot request
more source.
"""

FINALIZER = f"""This is the single V6 finalization turn. Use only supplied source.
Make final operations, keeping supported items active and moving doubtful items to the
deferred set with a concrete reason. Do not force an AU, do not force unknown merely to
retain an item, and do not use item counts as a target. unknown treatment is valid when
no authority relation is asserted. unknown attribution is valid only when the supplied
source truly cannot identify the speaker. An empty final KB is permitted.

{CONTRACT}
{EXAMPLES}

Return exactly:
{{"operations":[],"open_questions":[],"reason":"short process note"}}
"""

PROTOCOL_REPAIR = f"""Repair only protocol errors listed by the host. Valid operations
were already durably applied and must not be repeated. Do not open source and do not
make unrelated semantic changes. Each repair must use a valid rejection_id; a rejected
operation may be omitted when it cannot be repaired from the supplied snapshot.

{CONTRACT}
{EXAMPLES}
The payload gives expected_response with all required fields for this phase,
control_errors with exact field paths, and valid_rejection_ids. Check action and
read_window_ids together after patching; complete/finalize cannot request windows.
If a requested window was already read and no new source may be opened, patch
both action to complete (or finalize for a reader) and read_window_ids to [].
Do not leave action=read with an empty window list.

Return exactly:
{{"control_patch":{{}},
  "repairs":[{{"rejection_id":"...","operation":{{...}}}}]}}
control_patch may contain only allowed_control_patch_fields.
"""

