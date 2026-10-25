"""V10: phase-scoped model choices compiled into host-owned KB changes."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from .endpoint import BudgetStop, ModelProtocolError, _read_cache
from .schema_v10 import (PROMPT_VERSION, SCHEMA_VERSION, build_schema,
                         response_format, schema_hash, validate)
from . import schema_v11, schema_v12, schema_v13, schema_v14, schema_v15
from .source import (alias_item_sources, digest, load_source, materialize_sources,
                     opened_sources, save, source_handles, source_interval_coverage,
                     source_structure, structure_catalogue, structure_windows,
                     guided_catalogue)
from .state_v9 import apply_operations_independently, initial_state


PROMPTS = {
    "reader": "Read the supplied judgment source. Select source handles for a draft Case brief and legal AUs. AUs should preserve legal rules, conditions, exceptions, applications or evidence reasoning useful to future case retrieval. Choose further unread windows only if needed. The host supplies exact text and manages IDs. Return only the phase-specific choices in the JSON Schema. Every existing item requires one decision.",
    "selection": "Review selected source for omissions, misplaced headings, bare outcomes and missing legal reasoning. Select sources for useful new items; change, defer, restore or remove existing selections when warranted. A continuation must process newly opened source. Return only the choices allowed by this request's schema.",
    "classification": "Classify the speaker and function of each selected source. A citation alone does not make the court's own proposition cited_authority. A party request remains party even when the court reports it. A headnote is editorial. Brief issues must state a question for the court; disposition records its order. For each AU choose its central primary source. Defer when supplied evidence is insufficient.",
    "treatment": "For each active AU, classify how the present court treats a cited authority. applies needs an authority proposition and the court's use of it in this case; a citation or remedy alone is insufficient. If the AU does not assert a supported authority relation, choose unknown. Evidence lists may only reference sources already selected for that AU. Defer an item when its legal content lacks essential evidence.",
    "finalizer": "Decide explicitly whether each active item remains in the final KB or should be deferred or removed. For deferred items decide keep or remove. Do not add or relabel content. Completion indicates workflow completion, not semantic quality.",
}

GUIDED_PROMPTS = {**PROMPTS,
    "reader": "Read the supplied judgment source and build source-grounded brief/AU drafts. Before ending reader, consider missing legal rules, conditions, exceptions, court responses and distinct AU opportunities. Navigation headings and marker previews are hints, never fully read evidence. Choose reading_decision=read with a concrete purpose, or finish_phase with reasons for every unread window and unresolved needs. Current items being supported does not establish that all useful AUs were found. Select source handles only from opened_sources.",
    "selection": "Review the newly supplied source and current item context for omitted legal reasoning, conditions and AU opportunities. You may request a new or previously read but currently absent window while shared reading actions remain; state a concrete purpose. Do not assume an item with supporting source means all useful content was found. Finish only with a reason, unresolved needs, and reasons covering every unread window. Preview and markers are navigation hints, not AU evidence. Every existing item requires one decision.",
}

CANDIDATE_PROMPTS = {**GUIDED_PROMPTS,
    "reader": "Read the supplied judgment source. Create a new brief or AU with one anchor_source_id, never a source ID list. Existing items may request scan_sources. The host will supply each source candidate in bounded batches and accumulate include/exclude decisions; do not enumerate source IDs. Decide whether to read another window or finish with the required unread-window assessment.",
    "selection": "Find omitted legal reasoning and assess current items. New items use one anchor_source_id. For an existing item needing changed evidence choose scan_sources; the host will present candidate sources in batches. Do not enumerate source IDs or force unrelated paragraphs into one item. Decide whether to read another window or finish with the required unread-window assessment.",
    "source_scan": "For this one item, decide include or exclude for every code-provided candidate. The candidate key is the only output key; never write a source ID list. Include only a source needed to support this item's legal content, conditions or court response. The host accumulates decisions across batches and preserves exact source text.",
    "treatment": "For each active AU, choose unknown, defer, or a supported treatment. For a non-unknown treatment classify every selected source as none, authority, response, or both. Citation alone is not applies; a remedy alone is not an authority treatment. Do not write source ID lists.",
}

SEPARATED_PROMPTS = {**CANDIDATE_PROMPTS,
    "reader_extract": "Examine the exact source supplied in this request before any reading decision. Select anchored brief and legal AU drafts supported by it. A useful AU may state a rule, condition, exception, application, evidence assessment or procedural reasoning; it need not cite another authority. Each new item has one anchor_source_id. For existing items, scan_sources asks the host to present candidate evidence in bounded batches. Complete batch_assessment even when new_items is empty; explain which legal opportunities were considered and what remains unresolved. Do not choose a reading window here.",
    "selection_extract": "Review the supplied source and current items for omitted legal content, conditions and mistaken selections. Add anchored brief/AU drafts, request scan_sources for an existing item, or keep, defer, restore or remove it as supported. Complete batch_assessment even if no item changes. Do not choose a reading window here.",
    "reader_navigate": "Choose the next reading action from the catalogue, the source batch just examined and its batch_assessment. Read at most two permitted windows for a concrete missing need, or finish reader and assess each unread window exactly once. This request cannot create or edit KB items. A window preview is only a navigation hint.",
    "selection_navigate": "After reviewing source choices, read at most two permitted windows if a legal opportunity or missing condition needs examination; otherwise finish selection and assess every unread window exactly once. This request cannot create or edit KB items.",
    "classification": "For each selected source, assign its speaker and role. In an AU exactly one source must be primary; other sources may be context, qualification or court_response. A citation alone does not make the court's own statement cited_authority. A party statement reported by the court remains party; a headnote is editorial. Brief issues are questions for decision and disposition is the court's order. Defer an item when attribution or function lacks evidence.",
}

AUDITED_PROMPTS = {**SEPARATED_PROMPTS,
    "reader_extract": "Examine every supplied pending paragraph. Return one choice for every code-provided P and S key in choices. P may be skip, uncertain, brief, aus, both, or sentences. If P is sentences, choose one or more of its S keys as brief, aus, both or uncertain; otherwise every child S must be skip. No source ID list or generated quote. A legal AU anchor must contain a rule, condition, exception, application, evidence assessment or procedural reasoning; a heading, mere issue or bare order is not an AU. Never infer unseen source. Keep existing items unless evidence requires a specific change. Do not navigate in this response.",
    "selection_extract": "Reconsider the supplied pending group and relevant items. Return one choice for every P and S key in choices. P=sentences requires one or more non-skip child S choices; otherwise every child S must be skip. Do not describe legal opportunities without choosing their source. For an existing item, scan_extend examines new local candidates; scan_reconsider may remove mistaken selected source. Distant conditions require a later reading decision. Do not navigate here.",
    "reader_navigate": "Choose one or two allowed windows to read for a concrete unresolved legal need, or finish with a brief reason. Previews are not evidence; never assert that an unread window has no legal content. No KB changes in this response.",
    "selection_navigate": "Choose allowed windows for a missing condition or legal opportunity, or finish with a brief reason. Unread source remains unknown; do not infer its content from previews. No KB changes in this response.",
    "source_scan": "For each item-candidate key supplied by the host, choose include only if that exact source supports the item's legal proposition, condition or court response; otherwise exclude. Extend adds new evidence; reconsider can remove old evidence. Do not write source ID lists.",
    "classification": "Choose attribution once per precise source span, then choose brief kind or AU source roles for each item. A party's submission reported by the court remains party; the court's own rule with a citation is not automatically cited_authority. An issues list is brief/issues, not AU legal reasoning. Exactly one AU source is primary. Defer an item with insufficient source.",
    "treatment": "A legal AU need not cite another authority: choose unknown when no supported authority relation is asserted. A non-unknown choice needs an actual authority proposition and the present court's treatment of that authority. Choose both witnesses and evidence roles from this AU's sources; the same source may prove both only if its text actually does. A bare citation or remedy is insufficient. Defer if essential evidence is missing.",
    "finalizer": "Review the selected excerpts, not unselected source. Keep only source-grounded legal AUs; defer or remove a heading, issues list, bare outcome or unsupported duplicate. Brief can preserve facts, posture, issues and disposition. Completion is not a quality certification.",
}

TWO_STAGE_PROMPTS = {**AUDITED_PROMPTS,
    "reader_triage": "For every supplied paragraph key, choose exactly one triage value. Select brief for facts, posture, issues or a final disposition. Select aus for a legal rule, condition, exception, application, evidence assessment or procedural reasoning useful to future retrieval. Select both only when the whole paragraph independently serves both functions. Select refine_sentences when only narrower sentences should be retained. A heading, label, bare question or bare order is not an AU. Use uncertain when the paragraph may matter but cannot be safely classified from this text. Do not navigate or discuss prior items.",
    "selection_triage": "For every newly supplied paragraph key, choose exactly one triage value. Look especially for omitted legal rules, conditions, exceptions, applications and evidence reasoning. Use refine_sentences when the useful content is narrower than the paragraph. This response cannot navigate or edit an existing item.",
    "reader_refine": "For every supplied sentence key, choose skip, uncertain, brief, aus or both. Each parent paragraph was explicitly sent for sentence refinement, so retain at least one sentence from each parent. Do not choose the parent paragraph, navigate, or write source lists.",
    "selection_refine": "For every supplied sentence key, choose skip, uncertain, brief, aus or both. Each parent paragraph was explicitly sent for sentence refinement, so retain at least one sentence from each parent. Do not navigate or edit an existing item.",
    "selection_review": "Review each existing item using only its supplied excerpts and bounded local candidates. Keep it, defer or remove it; request scan_extend or scan_reconsider only when the supplied candidate pool can improve that item. This response cannot create an item or navigate.",
    "reader_navigate": "Choose one or two unread allowed windows for a concrete unresolved legal need, or finish reader. Previews and headings are navigation hints, not evidence. This response cannot create or edit KB items.",
    "selection_navigate": "Choose one or two unread allowed windows for an omitted legal opportunity, or finish selection. Previously read windows cannot be requested in this pilot. This response cannot create or edit KB items.",
}

SOURCE_SCOPE_NOTE = (
    "This request contains newly opened source and relevant previously read "
    "context for the listed items, not every source opened in earlier turns. "
    "Only handles present in this request may be selected. Catalogue previews "
    "are navigation hints, not fully read source."
)


def _opened_ids(windows: list[dict], selected: set[int]) -> set[str]:
    return {source for window in windows if window["window_id"] in selected
            for source in window["source_ids"]}


def _snapshot(state: dict) -> dict:
    return {"items": deepcopy(state["items"]), "counters": deepcopy(state["counters"]),
            "history_length": len(state["history"])}


def _items(checkpoint: dict, handles: dict[str, str]) -> tuple[list[dict], dict[str, str]]:
    entries, item_handles = [], {}
    for number, item in enumerate(checkpoint["state"]["items"].values()):
        if item["status"] == "deleted":
            continue
        item_handle = f"I{number:04d}"
        item_handles[item_handle] = item["id"]
        entries.append({"handle": item_handle, "id": item["id"],
            "revision": item["revision"], "status": item["status"],
            "collection": item["collection"],
            "source_ids": [handles[ref["source_id"]] for ref in item["source_refs"]],
            "current": alias_item_sources({key: deepcopy(value) for key, value in
                item.items() if key != "source_hash"}, handles)})
    return entries, item_handles


def _item_context_ids(entries: list[dict], source_map: dict,
                      paragraphs: list[dict], opened: set[str],
                      handle_to_stable: dict[str, str]) -> set[str]:
    """Include selected paragraphs and their already-opened immediate neighbors."""
    paragraph_index = {paragraph["source_id"]: index
                       for index, paragraph in enumerate(paragraphs)}
    context = set()
    for entry in entries:
        for handle in entry["source_ids"]:
            unit = source_map[handle_to_stable[handle]]
            parent_id = unit.get("parent_id") or unit["source_id"]
            index = paragraph_index[parent_id]
            for neighbor in range(max(0, index - 1),
                                  min(len(paragraphs), index + 2)):
                paragraph = paragraphs[neighbor]
                if paragraph["source_id"] in opened:
                    context.add(paragraph["source_id"])
                    context.update(set(paragraph["sentence_ids"]) & opened)
    return context


def _manifest(checkpoint: dict, phase: str, row: dict, catalogue: dict,
              source_map: dict, paragraphs: list[dict],
              stable_to_handle: dict, windows: list[dict],
              read_choices: list[int] | None,
              policy: str = "v10", reading_allowed: bool = False,
              reading_limit_reason: str | None = None) -> dict:
    entries, _ = _items(checkpoint, stable_to_handle)
    opened = set(checkpoint["opened_source_ids"])
    handle_to_stable = {handle: source for source, handle in stable_to_handle.items()}
    newly_opened = set(checkpoint["pending_source_ids"])
    if not newly_opened <= opened:
        raise ValueError("pending_source_not_opened")
    context = _item_context_ids(entries, source_map, paragraphs, opened,
                                handle_to_stable)
    supplied = newly_opened | context
    available = sorted(stable_to_handle[source] for source in supplied)
    unread = [window["window_id"] for window in windows
              if window["window_id"] not in checkpoint["opened_window_ids"]]
    if policy in {"guided", "candidate"}:
        readable = ([window["window_id"] for window in windows
                     if not set(window["source_ids"]) <= supplied]
                    if reading_allowed and phase in {"reader", "selection"} else [])
        schema = (schema_v12.build_schema(phase, entries, available, readable, unread)
                  if policy == "candidate" else
                  schema_v11.build_schema(phase, entries, available, readable, unread))
    else:
        readable = []
        schema = build_schema(phase, entries, available, read_choices)
    return {"phase": phase, "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_hash(schema), "items": entries,
        "source_scope_note": SOURCE_SCOPE_NOTE,
        "newly_opened_window_ids": checkpoint["pending_window_ids"],
        "opened_sources": opened_sources(source_map, supplied, stable_to_handle),
        "catalogue": ({**catalogue, "windows": [
            ({**window, "reading_status": (
                "unread" if window["window_id"] in unread else "read_not_supplied"
                if window["window_id"] in readable else "previously_read")}
             if policy in {"guided", "candidate"} else window)
            for window in catalogue["windows"]
            if policy in {"guided", "candidate"} or window["window_id"] in unread]}
            if phase in {"reader", "selection"} else None),
        "opened_window_ids": checkpoint["opened_window_ids"],
        "unread_window_ids": unread,
        **({"readable_window_ids": readable,
            "remaining_read_actions": max(0, 7 - checkpoint["read_actions"]),
            "reading_limit_reason": (None if readable else
                reading_limit_reason or "no_readable_window")}
           if policy in {"guided", "candidate"} and phase in {"reader", "selection"} else {})}


def _call(checkpoint: dict, checkpoint_path: Path, output: Path, endpoint,
          config: dict, experiment: str, row: dict, phase: str, turn: int,
          manifest: dict, policy: str = "v10") -> dict:
    key = f"{phase}:{turn}"
    journal = checkpoint["request_journal"]
    record = journal.get(key)
    if record is None:
        prompt = (TWO_STAGE_PROMPTS if policy == schema_v15.POLICY else
                  AUDITED_PROMPTS if policy == schema_v14.POLICY else
                  SEPARATED_PROMPTS if policy == "candidate-separated" else
                  CANDIDATE_PROMPTS if policy == "candidate" else
                  GUIDED_PROMPTS if policy == "guided" else PROMPTS)[phase]
        payload = {"manifest": manifest}
        encoded = json.dumps({"experiment": experiment, "prompt": prompt, "payload": payload,
            "schema_hash": manifest["schema_hash"]}, sort_keys=True,
            ensure_ascii=False).encode("utf-8")
        request_id = f"{row['case_id']}:{phase}:{turn}:{digest(encoded)[:20]}"
        if policy in {schema_v14.POLICY, schema_v15.POLICY}:
            wire_manifest = {key: deepcopy(value) for key, value in manifest.items()
                if key not in {"schema", "schema_hash", "pending_source_ids",
                    "scan_task_indexes", "opened_window_ids", "unread_window_ids",
                    "readable_window_ids"}}
            wire_manifest["items"] = [{key: entry[key] for key in (
                "handle", "id", "revision", "status", "collection", "source_ids")}
                | {"kind": entry.get("current", {}).get("kind"),
                   "treatment": entry.get("current", {}).get("treatment")}
                for entry in manifest.get("items", [])]
            wire_payload = {"manifest": wire_manifest}
        else:
            wire_payload = payload
        record = {"request_id": request_id, "prompt": prompt, "payload": payload,
            "wire_payload": wire_payload,
            "schema_hash": manifest["schema_hash"], "model": config[
                "reader" if phase in {"reader", "reader_extract", "reader_navigate"}
                else "repair"],
            "pre_request_snapshot": _snapshot(checkpoint["state"]),
            "status": "pending"}
        record["model"] = config[
            "reader" if phase == "reader" or phase.startswith("reader_")
            else "repair"]
        journal[key] = record
        save(checkpoint_path, checkpoint)
    else:
        if record["schema_hash"] != schema_hash(record["payload"]["manifest"]["schema"]):
            raise ValueError("journal_schema_checksum_mismatch")
        if record["status"] == "applied":
            return deepcopy(record["response"])
    cache_path = output / "responses" / f"{phase}_{turn}.json"
    schema = record["payload"]["manifest"]["schema"]
    version = (schema_v15.SCHEMA_VERSION if policy == schema_v15.POLICY else
               schema_v14.SCHEMA_VERSION if policy == schema_v14.POLICY else
               schema_v13.SCHEMA_VERSION if policy == "candidate-separated" else
               schema_v12.SCHEMA_VERSION if policy == "candidate" else
               schema_v11.SCHEMA_VERSION if policy == "guided" else SCHEMA_VERSION)
    prompt_version = (schema_v15.PROMPT_VERSION if policy == schema_v15.POLICY else
                      schema_v14.PROMPT_VERSION if policy == schema_v14.POLICY else
                      schema_v13.PROMPT_VERSION if policy == "candidate-separated" else
                      schema_v12.PROMPT_VERSION if policy == "candidate" else
                      schema_v11.PROMPT_VERSION if policy == "guided" else PROMPT_VERSION)
    format_schema = (schema_v15.response_format if policy == schema_v15.POLICY else
                     schema_v14.response_format if policy == schema_v14.POLICY else
                     schema_v13.response_format if policy == "candidate-separated" else
                     schema_v12.response_format if policy == "candidate" else
                     schema_v11.response_format if policy == "guided" else response_format)
    metadata = {"experiment": experiment, "schema_version": version,
        "prompt_version": prompt_version, "source_hash": row["source_hash"],
        "schema_hash": record["schema_hash"], "case_id": row["case_id"],
        "stage": phase, "turn": turn}
    if record["status"] == "received":
        response = record["response"]
        if record["response_hash"] != digest(json.dumps(response, sort_keys=True,
                ensure_ascii=False).encode("utf-8")):
            raise ValueError("journal_response_checksum_mismatch")
        if cache_path.exists():
            from .endpoint import _cache_identity
            identity = _cache_identity(record["request_id"], record["model"],
                record["prompt"], record.get("wire_payload", record["payload"]), metadata,
                format_schema(schema))
            if _read_cache(cache_path, identity) != response:
                raise ValueError("journal_cache_identity_mismatch")
        return deepcopy(response)
    try:
        response = endpoint.complete(record["model"], record["prompt"],
            record.get("wire_payload", record["payload"]), request_id=record["request_id"], metadata=metadata,
            cache_path=cache_path, response_format=format_schema(schema))
    except ModelProtocolError:
        raw_path = cache_path.with_suffix(".raw.json")
        if not raw_path.exists():
            raise
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        response = {"__invalid_model_content__": raw.get("model_content", ""),
                    "finish_reason": raw.get("finish_reason")}
    record["response"] = response
    record["response_hash"] = digest(json.dumps(response, sort_keys=True,
        ensure_ascii=False).encode("utf-8"))
    record["status"] = "received"
    save(checkpoint_path, checkpoint)
    return response


def _selection_operations(response: dict, entries: list[dict], state: dict,
                          phase: str) -> tuple[list[dict], list[dict]]:
    operations, audit = [], []
    for entry in entries:
        decision = response["decisions"][entry["handle"]]
        choice, reason = decision["choice"], decision["reason"]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice, "reason": reason})
        if choice == "keep":
            continue
        if choice == "change_sources":
            old = {ref["source_id"]: ref for ref in entry["current"]["source_refs"]}
            refs = [{"source_id": source_id,
                "role": old.get(source_id, {}).get("role", "context"),
                "attribution": old.get(source_id, {}).get("attribution", "unknown")}
                for source_id in decision["source_ids"]]
            if entry["collection"] == "aus" and not any(ref["role"] == "primary" for ref in refs):
                refs[0]["role"] = "primary"
            changes = {"source_refs": refs}
            if entry["collection"] == "aus":
                changes["treatment"] = {"value": "unknown",
                    "authority_source_ids": [], "response_source_ids": []}
            operations.append({"op": "update", "id": entry["id"],
                "revision": entry["revision"], "changes": changes, "reason": reason})
        else:
            operations.append({"op": choice, "id": entry["id"],
                "revision": entry["revision"], "reason": reason})
    for created in response.get("new_items", []):
        sources = created["source_ids"]
        refs = [{"source_id": source, "role": "primary" if index == 0 else "context",
                 "attribution": "unknown"} for index, source in enumerate(sources)]
        item = {"source_refs": refs}
        if created["collection"] == "brief":
            item["kind"] = "facts"  # Provisional until classification.
        else:
            item["treatment"] = {"value": "unknown", "authority_source_ids": [],
                                 "response_source_ids": []}
        operations.append({"op": "add", "collection": created["collection"],
                           "item": item, "reason": created["reason"]})
    return operations, audit


def _candidate_selection_operations(response: dict, entries: list[dict]
                                    ) -> tuple[list[dict], list[dict], list[dict]]:
    """Compile scalar anchors; defer source replacement to host-owned batches."""
    operations, audit, revisions = [], [], []
    for entry in entries:
        decision = response["decisions"][entry["handle"]]
        choice, reason = decision["choice"], decision["reason"]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice, "reason": reason})
        if choice == "keep":
            continue
        if choice == "scan_sources":
            revisions.append({"item_id": entry["id"], "reason": reason})
        else:
            operations.append({"op": choice, "id": entry["id"],
                "revision": entry["revision"], "reason": reason})
    for created in response["new_items"]:
        ref = {"source_id": created["anchor_source_id"], "role": "primary",
               "attribution": "unknown"}
        item = {"source_refs": [ref]}
        if created["collection"] == "brief":
            item["kind"] = "facts"  # Provisional until classification.
        else:
            item["treatment"] = {"value": "unknown", "authority_source_ids": [],
                                 "response_source_ids": []}
        operations.append({"op": "add", "collection": created["collection"],
                           "item": item, "reason": created["reason"]})
    return operations, audit, revisions


def _classification_operations(response: dict, entries: list[dict]) -> tuple[list[dict], list[dict]]:
    operations, audit = [], []
    for entry in entries:
        choice = response["decisions"][entry["handle"]]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice["choice"], "reason": choice["reason"]})
        if choice["choice"] == "keep":
            continue
        if choice["choice"] == "defer":
            operations.append({"op": "defer", "id": entry["id"],
                "revision": entry["revision"], "reason": choice["reason"]})
            continue
        if entry["collection"] == "brief":
            refs = [{"source_id": source, "role": "primary",
                     "attribution": choice["attribution"][source]}
                    for source in entry["source_ids"]]
            changes = {"kind": choice["kind"], "source_refs": refs}
        else:
            refs = [{"source_id": source,
                "role": ("primary" if source == choice["primary_source_id"] else
                         choice["roles"][source]),
                "attribution": choice["attribution"][source]}
                for source in entry["source_ids"]]
            if any(ref["role"] == "primary" and ref["source_id"] !=
                   choice["primary_source_id"] for ref in refs):
                raise ValueError("non_primary_source_labeled_primary")
            changes = {"source_refs": refs}
        operations.append({"op": "update", "id": entry["id"],
            "revision": entry["revision"], "changes": changes,
            "reason": choice["reason"]})
    return operations, audit


def _treatment_operations(response: dict, entries: list[dict]) -> tuple[list[dict], list[dict]]:
    operations, audit = [], []
    for entry in entries:
        if entry["collection"] != "aus" or entry["status"] != "active":
            continue
        choice = response["decisions"][entry["handle"]]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice["choice"], "reason": choice["reason"]})
        if choice["choice"] == "defer":
            operations.append({"op": "defer", "id": entry["id"],
                "revision": entry["revision"], "reason": choice["reason"]})
            continue
        treatment = {"value": choice["choice"],
            "authority_source_ids": choice.get("authority_source_ids", []),
            "response_source_ids": choice.get("response_source_ids", [])}
        operations.append({"op": "update", "id": entry["id"],
            "revision": entry["revision"], "changes": {"treatment": treatment},
            "reason": choice["reason"]})
    return operations, audit


def _candidate_treatment_operations(response: dict, entries: list[dict]
                                    ) -> tuple[list[dict], list[dict]]:
    operations, audit = [], []
    for entry in entries:
        if entry["collection"] != "aus" or entry["status"] != "active":
            continue
        choice = response["decisions"][entry["handle"]]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice["choice"], "reason": choice["reason"]})
        if choice["choice"] == "defer":
            operations.append({"op": "defer", "id": entry["id"],
                "revision": entry["revision"], "reason": choice["reason"]})
            continue
        evidence = choice.get("evidence", {})
        treatment = {"value": choice["choice"],
            "authority_source_ids": [source for source, role in evidence.items()
                                     if role in {"authority", "both"}],
            "response_source_ids": [source for source, role in evidence.items()
                                    if role in {"response", "both"}]}
        operations.append({"op": "update", "id": entry["id"],
            "revision": entry["revision"], "changes": {"treatment": treatment},
            "reason": choice["reason"]})
    return operations, audit


def _ordered_sources(ids: set[str], source_map: dict) -> list[str]:
    return sorted(ids, key=lambda source: (source_map[source]["start"],
        source_map[source]["end"], source_map[source]["unit_type"] != "paragraph"))


def _nearby_source_ids(anchor: str, supplied: set[str], source_map: dict,
                       paragraphs: list[dict]) -> set[str]:
    """Offer nearby fully supplied source for a new one-anchor item."""
    parent = source_map[anchor].get("parent_id") or anchor
    positions = {paragraph["source_id"]: index for index, paragraph in
                 enumerate(paragraphs)}
    index = positions[parent]
    neighborhood = {paragraphs[number]["source_id"] for number in range(
        max(0, index - 2), min(len(paragraphs), index + 3))}
    return {source for source in supplied if source != anchor and
            (source_map[source].get("parent_id") or source) in neighborhood}


def _source_scan_manifest(checkpoint: dict, row: dict, source_map: dict,
                          stable_to_handle: dict[str, str]) -> dict:
    task = checkpoint["source_scan_queue"][0]
    batch = task["candidates"][task["cursor"]:
                               task["cursor"] + schema_v12.SOURCE_BATCH_SIZE]
    schema = schema_v12.build_source_scan_schema(len(batch))
    shown = set(batch)
    shown.update(source_map[source].get("parent_id") for source in batch
                 if source_map[source].get("parent_id"))
    item = checkpoint["state"]["items"][task["item_id"]]
    return {"phase": "source_scan", "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_hash(schema), "items": [],
        "item": alias_item_sources(item, stable_to_handle),
        "selection_reason": task["reason"], "selection_origin": task["origin"],
        "batch_index": task["cursor"] // schema_v12.SOURCE_BATCH_SIZE,
        "candidate_sources": [{"key": f"C{index}",
            "source_id": stable_to_handle[source],
            "unit_type": source_map[source]["unit_type"],
            "start": source_map[source]["start"], "end": source_map[source]["end"],
            "text": source_map[source]["text"]}
            for index, source in enumerate(batch)],
        "opened_sources": opened_sources(source_map, shown, stable_to_handle)}


def _scan_one_batch(checkpoint: dict, checkpoint_path: Path, output: Path,
                    endpoint, config: dict, experiment: str, row: dict,
                    source_map: dict, stable_to_handle: dict[str, str],
                    alias_to_stable: dict[str, str],
                    policy: str = "candidate") -> None:
    """Persist one bounded candidate decision and resume the interrupted phase."""
    task = checkpoint["source_scan_queue"][0]
    turn = checkpoint["source_scan_turn"]
    manifest = _source_scan_manifest(checkpoint, row, source_map, stable_to_handle)
    response = _call(checkpoint, checkpoint_path, output, endpoint, config,
        experiment, row, "source_scan", turn, manifest, policy)
    record = checkpoint["request_journal"][f"source_scan:{turn}"]
    if record["status"] == "applied":
        raise ValueError("applied_source_scan_not_advanced")
    saved = record["payload"]["manifest"]
    if saved["source_hash"] != row["source_hash"] or saved["phase"] != "source_scan":
        raise ValueError("source_scan_manifest_mismatch")
    errors = validate(response, saved["schema"])
    candidates = saved["candidate_sources"]
    if not errors:
        task["selected"].extend(alias_to_stable[candidate["source_id"]]
            for candidate in candidates if response["choices"][candidate["key"]] == "include")
        task["cursor"] += len(candidates)
        if task["cursor"] == len(task["candidates"]):
            selected = list(dict.fromkeys(task["selected"]))
            if not selected:
                errors.append({"path": "$.choices", "error_code": "empty_source_selection"})
            else:
                item = checkpoint["state"]["items"][task["item_id"]]
                old = {ref["source_id"]: ref for ref in item["source_refs"]}
                refs = [{"source_id": stable_to_handle[source],
                    "role": old.get(source, {}).get("role", "context"),
                    "attribution": old.get(source, {}).get("attribution", "unknown")}
                    for source in selected]
                if item["collection"] == "aus" and not any(
                        ref["role"] == "primary" for ref in refs):
                    refs[0]["role"] = "primary"
                unchanged = ([alias_to_stable[ref["source_id"]] for ref in refs] ==
                             [ref["source_id"] for ref in item["source_refs"]])
                applied, noops = [], []
                if not unchanged:
                    changes = {"source_refs": refs}
                    if item["collection"] == "aus":
                        changes["treatment"] = {"value": "unknown",
                            "authority_source_ids": [], "response_source_ids": []}
                    new_state, applied, rejected, noops = apply_operations_independently(
                        checkpoint["state"], [{"op": "update", "id": item["id"],
                            "revision": item["revision"], "changes": changes,
                            "reason": task["reason"]}], set(task["candidates"]) |
                        {ref["source_id"] for ref in item["source_refs"]},
                        source_map, row["source_hash"], row["case_id"],
                        aliases=alias_to_stable, stable_to_handle=stable_to_handle,
                        allowed_target_ids={item["id"]}, phase="reader")
                    if rejected:
                        errors.extend({"path": "$.choices", "error_code":
                            rejection["error_code"]} for rejection in rejected)
                    else:
                        checkpoint["state"] = new_state
                checkpoint["trace"].append({"phase": "source_scan", "turn": turn,
                    "item_id": task["item_id"], "candidate_count": len(task["candidates"]),
                    "selected_source_ids": selected, "applied": applied,
                    "noop_duplicates": noops})
                if not errors:
                    checkpoint["source_scan_queue"].pop(0)
    if errors:
        checkpoint["protocol_errors"].extend({"phase": "source_scan", "turn": turn,
            **error} for error in errors)
        checkpoint["stage"] = "incomplete"
        checkpoint["stop_reason"] = "invalid_constrained_response"
    elif not checkpoint["source_scan_queue"]:
        resume = checkpoint.pop("source_scan_resume")
        checkpoint["stage"], checkpoint["turn"] = resume["stage"], resume["turn"]
        if resume["snapshot"]:
            save(output / "snapshots" / f"{resume['snapshot']}.json",
                 _snapshot(checkpoint["state"]))
            checkpoint["snapshots"].append(resume["snapshot"])
    shown = {alias_to_stable[unit["source_id"]]
             for paragraph in saved["opened_sources"]
             for unit in [paragraph, *paragraph["sentences"]]}
    checkpoint["phase_source_ids"]["source_scan"] = sorted(set(
        checkpoint["phase_source_ids"].get("source_scan", [])) | shown)
    checkpoint["source_scan_turn"] += 1
    record["status"] = "applied"
    record["post_request_snapshot"] = _snapshot(checkpoint["state"])
    save(checkpoint_path, checkpoint)


def _final_operations(response: dict, entries: list[dict]) -> tuple[list[dict], list[dict]]:
    operations, audit = [], []
    for entry in entries:
        choice = response["decisions"][entry["handle"]]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice["choice"], "reason": choice["reason"]})
        if choice["choice"] != "keep":
            operations.append({"op": choice["choice"], "id": entry["id"],
                "revision": entry["revision"], "reason": choice["reason"]})
    return operations, audit


def _result(row: dict, text: str, units: list[dict], checkpoint: dict) -> dict:
    source_map = {unit["source_id"]: unit for unit in units}
    policy = checkpoint.get("reading_policy", "v10")
    status = "completed" if checkpoint["stage"] == "complete" else "incomplete"
    by_status = {kind: [] for kind in ("active", "deferred", "deleted")}
    for item in checkpoint["state"]["items"].values():
        rendered = deepcopy(item)
        rendered["excerpts"] = materialize_sources(item["source_refs"], source_map,
                                                     row["source_hash"])
        by_status[item["status"]].append(rendered)
    active = by_status["active"]
    if status != "completed":
        output_status = "incomplete"
    elif active:
        output_status = "nonempty"
    elif by_status["deferred"] or (checkpoint.get("candidate_uncertain") and
                                   policy != schema_v15.POLICY):
        output_status = "unresolved_only"
    elif by_status["deleted"]:
        output_status = "all_items_removed"
    else:
        output_status = "empty_output"
    stable_to_handle, alias_to_stable = source_handles(units)
    del stable_to_handle
    guided = policy in {"guided", "candidate", "candidate-separated",
                        schema_v14.POLICY, schema_v15.POLICY}
    return {"schema_version": (schema_v15.SCHEMA_VERSION if policy == schema_v15.POLICY else
                               schema_v14.SCHEMA_VERSION if policy == schema_v14.POLICY else
                               schema_v13.SCHEMA_VERSION if policy == "candidate-separated" else
                               schema_v12.SCHEMA_VERSION if policy == "candidate" else
                               schema_v11.SCHEMA_VERSION if guided else SCHEMA_VERSION),
        "representation": "extractive_paragraph_sentence_references",
        "workflow": "constrained_selection_classification_treatment_finalize",
        "case_id": row["case_id"], "source": row["source"],
        "source_hash": row["source_hash"],
        "prompt_version": (schema_v15.PROMPT_VERSION if policy == schema_v15.POLICY else
                           schema_v14.PROMPT_VERSION if policy == schema_v14.POLICY else
                           schema_v13.PROMPT_VERSION if policy == "candidate-separated" else
                           schema_v12.PROMPT_VERSION if policy == "candidate" else
                           schema_v11.PROMPT_VERSION if guided else PROMPT_VERSION),
        **({"reading_policy": policy, "reading_history": checkpoint["reading_history"],
            "unread_window_ids": checkpoint["unread_window_ids_final"]}
           if guided else {}),
        **({"batch_assessments": checkpoint["batch_assessments"]}
           if policy in {"candidate-separated", schema_v14.POLICY} else {}),
        **({"candidate_uncertain": checkpoint["candidate_uncertain"]}
           if policy in {schema_v14.POLICY, schema_v15.POLICY} else {}),
        "source_handle_manifest": {"source_hash": row["source_hash"],
                                   "handles": alias_to_stable},
        "execution_status": status,
        "protocol_status": "valid" if status == "completed" else "failure",
        "output_status": output_status, "quality_status": "not_evaluated",
        "stop_reason": checkpoint.get("stop_reason"),
        "empty_reason": ("no_selected_items_after_triage"
                         if policy == schema_v15.POLICY and
                         output_status == "empty_output" else None),
        **({"empty_with_unread": bool(checkpoint["unread_window_ids_final"])
            and not active, "candidate_uncertain_count": len(
                checkpoint["candidate_uncertain"])} if policy == schema_v14.POLICY else {}),
        **({"omission_review_required": output_status == "empty_output",
            "empty_with_unread": bool(checkpoint["unread_window_ids_final"])
                and not active,
            "paragraphs_triaged": len(checkpoint.get("triaged_paragraph_ids", [])),
            "refined_paragraphs": len(checkpoint.get("refined_paragraph_ids", [])),
            "candidate_uncertain_count": len(checkpoint.get(
                "candidate_uncertain", []))} if policy == schema_v15.POLICY else {}),
        "brief": [item for item in active if item["collection"] == "brief"],
        "aus": [item for item in active if item["collection"] == "aus"],
        "unresolved_items": by_status["deferred"],
        "deleted_items": by_status["deleted"],
        "final_au_ids": ([item["id"] for item in active if item["collection"] == "aus"]
                         if status == "completed" else []),
        "history": checkpoint["state"]["history"],
        "protocol_errors": checkpoint["protocol_errors"],
        "source_coverage": source_interval_coverage(units,
            {source for sources in checkpoint["phase_source_ids"].values()
             for source in sources}, len(text), "all_agent_phases"),
        "coverage_by_phase": {phase: source_interval_coverage(units, set(sources),
            len(text), phase) for phase, sources in checkpoint["phase_source_ids"].items()},
        "snapshots": checkpoint["snapshots"],
        "counts": {"brief": sum(item["collection"] == "brief" for item in active),
                   "aus": sum(item["collection"] == "aus" for item in active),
                   "unresolved": len(by_status["deferred"]),
                   "deleted": len(by_status["deleted"]),
                   "requests": len(checkpoint["request_journal"]),
                   **({"read_actions": checkpoint["read_actions"],
                       "reread_actions": checkpoint["reread_actions"]}
                      if guided else {}),
                    **({"source_scan_requests": checkpoint["source_scan_turn"]}
                       if policy in {"candidate", "candidate-separated", schema_v14.POLICY,
                                     schema_v15.POLICY} else {}),
                    **({"source_groups_provided": 1 + checkpoint["read_actions"],
                        "source_groups_processed": sum(not entry["reused_last_group"]
                            for entry in checkpoint["batch_assessments"]),
                        "extraction_requests": len(checkpoint["batch_assessments"]),
                        "navigation_requests": len(checkpoint["navigation_history"])}
                       if policy in {"candidate-separated", schema_v14.POLICY} else {}),
                    **({"triage_requests": len(checkpoint.get("triage_history", [])),
                        "refinement_requests": len(checkpoint.get(
                            "refinement_history", [])),
                        "navigation_requests": len(checkpoint.get(
                            "navigation_history", [])),
                        "paragraphs_triaged": len(checkpoint.get(
                            "triaged_paragraph_ids", []))}
                       if policy == schema_v15.POLICY else {}),
                   "protocol_errors_unresolved": len(checkpoint["protocol_errors"])}}


def build_case(row: dict, endpoint, config: dict, size: int, steps: int,
               output: Path, reading_policy: str = "v10") -> dict:
    if reading_policy == schema_v15.POLICY:
        from .pipeline_v15 import build_case_v15
        return build_case_v15(row, endpoint, config, size, steps, output)
    if reading_policy == schema_v14.POLICY:
        from .pipeline_v14 import build_case_v14
        return build_case_v14(row, endpoint, config, size, steps, output)
    if reading_policy == "candidate-separated":
        from .pipeline_v13 import build_case_v13
        return build_case_v13(row, endpoint, config, size, steps, output)
    if reading_policy not in {"v10", "guided", "candidate"}:
        raise ValueError("unknown_reading_policy")
    guided = reading_policy in {"guided", "candidate"}
    text, source_hash = load_source(row["source"])
    if source_hash != row["source_hash"]:
        raise ValueError("source_changed_since_manifest")
    paragraphs, units = source_structure(text, source_hash)
    windows = structure_windows(paragraphs, size)
    if not windows:
        raise ValueError("empty_source")
    source_map = {unit["source_id"]: unit for unit in units}
    stable_to_handle, alias_to_stable = source_handles(units)
    if guided:
        catalogue, navigation = guided_catalogue(text, units, windows)
        save(output / "source_navigation.json", {
            "source_hash": source_hash, **navigation})
    else:
        catalogue = structure_catalogue(units, windows)
    version = (schema_v12.SCHEMA_VERSION if reading_policy == "candidate" else
               schema_v11.SCHEMA_VERSION if guided else SCHEMA_VERSION)
    prompt_version = (schema_v12.PROMPT_VERSION if reading_policy == "candidate" else
                      schema_v11.PROMPT_VERSION if guided else PROMPT_VERSION)
    checkpoint_path = output / "checkpoint.json"
    experiment = output.parents[1].name
    config_path = output.parents[1] / "config.json"
    if config_path.exists():
        experiment += ":" + digest(config_path.read_bytes())[:12]
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (checkpoint.get("schema_version") != version or
            checkpoint.get("source_hash") != source_hash or
            checkpoint.get("prompt_version") != prompt_version or
            checkpoint.get("reading_policy", "v10") != reading_policy):
            raise ValueError("checkpoint_identity_mismatch")
    else:
        initial_windows = {0, len(windows) - 1}
        opened = _opened_ids(windows, initial_windows)
        checkpoint = {"schema_version": version,
            "prompt_version": prompt_version, "source_hash": source_hash,
            "stage": "reader", "turn": 0, "state": initial_state(),
            "opened_window_ids": sorted(initial_windows),
            "opened_source_ids": sorted(opened),
            "pending_window_ids": sorted(initial_windows),
            "pending_source_ids": sorted(opened),
            "phase_source_ids": {},
            "read_expansions": 0, "selection_extra_used": False,
            "request_journal": {}, "protocol_errors": [], "trace": [],
            "snapshots": [], "stop_reason": None}
        if guided:
            checkpoint.update(reading_policy=reading_policy, read_actions=0,
                reread_actions=0, reading_history=[], unread_window_ids_final=[])
        if reading_policy == "candidate":
            checkpoint.update(source_scan_queue=[], source_scan_turn=0)
        save(checkpoint_path, checkpoint)
    while checkpoint["stage"] not in {"complete", "incomplete"}:
        if reading_policy == "candidate" and checkpoint["stage"] == "source_scan":
            if checkpoint["source_scan_turn"] >= config.get("max_source_scan_requests", 24):
                checkpoint["stage"] = "incomplete"
                checkpoint["stop_reason"] = "source_scan_request_limit"
                save(checkpoint_path, checkpoint)
                break
            _scan_one_batch(checkpoint, checkpoint_path, output, endpoint, config,
                experiment, row, source_map, stable_to_handle, alias_to_stable)
            continue
        phase, turn = checkpoint["stage"], checkpoint["turn"]
        unread = [window["window_id"] for window in windows
                  if window["window_id"] not in checkpoint["opened_window_ids"]]
        read_choices = None
        if phase == "reader" and checkpoint["read_expansions"] < steps and turn < steps + 1:
            read_choices = unread
        if phase == "selection" and turn == 0 and not checkpoint["selection_extra_used"]:
            read_choices = unread
        reading_allowed = (guided and phase in {"reader", "selection"} and
            checkpoint["read_actions"] < 7 and
            (phase != "reader" or checkpoint["read_expansions"] < steps))
        limit_reason = ("reader_limit" if guided and phase == "reader" and
                        checkpoint["read_expansions"] >= steps else
                        "shared_limit" if guided and checkpoint["read_actions"] >= 7
                        else None)
        manifest = _manifest(checkpoint, phase, row, catalogue, source_map,
            paragraphs, stable_to_handle, windows, read_choices,
            reading_policy, reading_allowed, limit_reason)
        key = f"{phase}:{turn}"
        response = _call(checkpoint, checkpoint_path, output, endpoint, config,
            experiment, row, phase, turn, manifest, reading_policy)
        record = checkpoint["request_journal"][key]
        if record["status"] == "applied":
            raise ValueError("applied_response_stage_not_advanced")
        saved_manifest = record["payload"]["manifest"]
        if saved_manifest["source_hash"] != source_hash or saved_manifest["phase"] != phase:
            raise ValueError("journal_manifest_mismatch")
        supplied = {alias_to_stable[unit["source_id"]]
                    for paragraph in saved_manifest["opened_sources"]
                    for unit in [paragraph, *paragraph["sentences"]]}
        checkpoint["phase_source_ids"][phase] = sorted(set(
            checkpoint["phase_source_ids"].get(phase, [])) | supplied)
        errors = validate(response, saved_manifest["schema"])
        if guided and not errors and phase in {"reader", "selection"}:
            errors.extend(schema_v11.validate_reading_decision(
                response, saved_manifest["unread_window_ids"]))
        entries = saved_manifest["items"]
        if reading_policy == "candidate" and phase == "treatment" and not errors:
            errors.extend(schema_v12.validate_treatment_evidence(response, entries))
        revisions = []
        if errors:
            operations, audit = [], []
        elif phase in {"reader", "selection"} and reading_policy == "candidate":
            operations, audit, revisions = _candidate_selection_operations(response, entries)
        elif phase in {"reader", "selection"}:
            operations, audit = _selection_operations(response, entries,
                                                      checkpoint["state"], phase)
        elif phase == "classification":
            operations, audit = _classification_operations(response, entries)
        elif phase == "treatment" and reading_policy == "candidate":
            operations, audit = _candidate_treatment_operations(response, entries)
        elif phase == "treatment":
            operations, audit = _treatment_operations(response, entries)
        else:
            operations, audit = _final_operations(response, entries)
        if not errors:
            target_ids = {entry["id"] for entry in entries}
            new_state, applied, rejected, noops = apply_operations_independently(
                checkpoint["state"], operations, supplied, source_map, source_hash,
                row["case_id"], aliases=alias_to_stable,
                stable_to_handle=stable_to_handle, allowed_target_ids=target_ids,
                phase="reader")
            if rejected:
                errors = [{"path": f"decisions_or_new_items[{entry['index']}]",
                    "error_code": entry["error_code"]} for entry in rejected]
        if errors:
            checkpoint["protocol_errors"].extend({"phase": phase, "turn": turn, **error}
                                                 for error in errors)
            checkpoint["stage"] = "incomplete"
            checkpoint["stop_reason"] = "invalid_constrained_response"
        else:
            checkpoint["state"] = new_state
            if reading_policy == "candidate" and phase in {"reader", "selection"}:
                if checkpoint["source_scan_queue"]:
                    raise ValueError("unfinished_source_scan_queue")
                for requested in revisions:
                    item = checkpoint["state"]["items"][requested["item_id"]]
                    candidates = set(supplied) | {ref["source_id"]
                                                  for ref in item["source_refs"]}
                    checkpoint["source_scan_queue"].append({
                        "item_id": item["id"], "reason": requested["reason"],
                        "origin": {"phase": phase, "turn": turn, "kind": "revision"},
                        "candidates": _ordered_sources(candidates, source_map),
                        "cursor": 0, "selected": []})
                for event in applied:
                    if event["op"] != "add":
                        continue
                    item = checkpoint["state"]["items"][event["id"]]
                    anchor = item["source_refs"][0]["source_id"]
                    candidates = _nearby_source_ids(anchor, supplied, source_map,
                                                     paragraphs)
                    if candidates:
                        checkpoint["source_scan_queue"].append({
                            "item_id": item["id"], "reason": event["reason"],
                            "origin": {"phase": phase, "turn": turn, "kind": "new"},
                            "candidates": _ordered_sources(candidates, source_map),
                            "cursor": 0, "selected": [anchor]})
            decision = response.get("reading_decision") if guided and phase in {
                "reader", "selection"} else None
            chosen = (decision["window_ids"] if decision and decision["action"] == "read"
                      else response.get("read_window_ids", []))
            previously_opened = set(checkpoint["opened_source_ids"])
            prior_windows = set(checkpoint["opened_window_ids"])
            chosen_sources = _opened_ids(windows, set(chosen))
            checkpoint["opened_window_ids"] = sorted(set(checkpoint["opened_window_ids"]) |
                                                     set(chosen))
            checkpoint["opened_source_ids"] = sorted(previously_opened | chosen_sources)
            checkpoint["pending_window_ids"] = chosen
            checkpoint["pending_source_ids"] = sorted(
                chosen_sources if guided else chosen_sources - previously_opened)
            if guided and decision:
                reread = [window_id for window_id in chosen if window_id in prior_windows]
                checkpoint["read_actions"] += bool(chosen)
                checkpoint["reread_actions"] += bool(reread)
                checkpoint["reading_history"].append({"phase": phase, "turn": turn,
                    "decision": decision, "opened_window_ids": chosen,
                    "new_window_ids": [number for number in chosen
                                       if number not in prior_windows],
                    "reread_window_ids": reread,
                    "remaining_actions": 7 - checkpoint["read_actions"],
                    "read_limit_reason": saved_manifest.get("reading_limit_reason")})
            if phase == "reader":
                checkpoint["read_expansions"] += bool(chosen)
                checkpoint["stage"] = "reader" if chosen else "selection"
                checkpoint["turn"] = turn + 1 if chosen else 0
            elif phase == "selection":
                checkpoint["selection_extra_used"] = checkpoint["selection_extra_used"] or bool(chosen)
                checkpoint["stage"] = "selection" if chosen else "classification"
                checkpoint["turn"] = (turn + 1 if guided else 1) if chosen else 0
                if guided and not chosen:
                    checkpoint["unread_window_ids_final"] = [
                        window["window_id"] for window in windows
                        if window["window_id"] not in checkpoint["opened_window_ids"]]
            elif phase == "classification":
                checkpoint["stage"], checkpoint["turn"] = "treatment", 0
            elif phase == "treatment":
                checkpoint["stage"], checkpoint["turn"] = "finalizer", 0
            else:
                checkpoint["stage"] = "complete"
                checkpoint["stop_reason"] = "finalization_complete"
            checkpoint["trace"].append({"phase": phase, "turn": turn,
                "schema_hash": record["schema_hash"], "decisions": audit,
                "applied": applied, "noop_duplicates": noops,
                "opened_window_ids": chosen})
            name = ({"reader": "draft_after_reading",
                     "selection": "after_selection_repair",
                     "classification": "after_classification_repair",
                     "treatment": "after_treatment_repair", "finalizer": "final"}[phase]
                    if checkpoint["stage"] != phase else None)
            if reading_policy == "candidate" and checkpoint["source_scan_queue"]:
                checkpoint["source_scan_resume"] = {"stage": checkpoint["stage"],
                    "turn": checkpoint["turn"], "snapshot": name}
                checkpoint["stage"] = "source_scan"
                checkpoint["turn"] = checkpoint["source_scan_turn"]
            elif name:
                save(output / "snapshots" / f"{name}.json", _snapshot(checkpoint["state"]))
                checkpoint["snapshots"].append(name)
        record["status"] = "applied"
        record["post_request_snapshot"] = _snapshot(checkpoint["state"])
        save(checkpoint_path, checkpoint)
    result = _result(row, text, units, checkpoint)
    save(output / "trace.json", checkpoint["trace"])
    save(output / "case.json", result)
    return result
