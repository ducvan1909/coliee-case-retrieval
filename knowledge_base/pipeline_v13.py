"""V13: examine each opened source group before deciding what to read next."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from . import schema_v12, schema_v13, schema_v14
from .pipeline_v10 import (_call, _candidate_selection_operations,
    _candidate_treatment_operations,
    _final_operations, _item_context_ids, _items, _nearby_source_ids,
    _opened_ids, _ordered_sources, _result, _scan_one_batch, _snapshot)
from .schema_v10 import schema_hash, validate
from .source import (compact_opened_sources, digest, guided_catalogue, load_source, opened_sources,
    save, source_handles, source_structure, structure_windows)
from .state_v9 import apply_operations_independently, initial_state

POLICY = "candidate-separated"


def _compatible_candidates(candidates: set[str], refs: list[dict],
                           source_map: dict) -> set[str]:
    """Offer only one address granularity within each paragraph."""
    by_parent = {}
    for ref in refs:
        unit = source_map[ref["source_id"]]
        parent = unit.get("parent_id") or unit["source_id"]
        by_parent[parent] = unit["unit_type"]
    return {source for source in candidates if source_map[source]["unit_type"] ==
            by_parent.get(source_map[source].get("parent_id") or source,
                          "paragraph")}


def _local_revision_candidates(supplied: set[str], refs: list[dict],
                               source_map: dict, paragraphs: list[dict]) -> set[str]:
    """Keep a revision focused on each selected paragraph and its neighbors."""
    positions = {paragraph["source_id"]: index
                 for index, paragraph in enumerate(paragraphs)}
    nearby_parents = set()
    for ref in refs:
        unit = source_map[ref["source_id"]]
        parent = unit.get("parent_id") or unit["source_id"]
        index = positions[parent]
        nearby_parents.update(paragraphs[number]["source_id"] for number in
            range(max(0, index - 1), min(len(paragraphs), index + 2)))
    return ({source for source in supplied if
             (source_map[source].get("parent_id") or source) in nearby_parents} |
            {ref["source_id"] for ref in refs})


def _extraction_manifest(checkpoint: dict, phase: str, row: dict,
                         source_map: dict, paragraphs: list[dict],
                         stable_to_handle: dict, policy: str = POLICY) -> dict:
    entries, _ = _items(checkpoint, stable_to_handle)
    pending = set(checkpoint["pending_source_ids"])
    opened = set(checkpoint["opened_source_ids"])
    if not pending or not pending <= opened:
        raise ValueError("extraction_requires_pending_opened_source")
    handle_to_stable = {handle: source for source, handle in stable_to_handle.items()}
    if policy == schema_v14.POLICY:
        pending_parents = {source_map[source].get("parent_id") or source
                           for source in pending}
        if phase == "reader_extract":
            entries = [entry for entry in entries if any(
                (source_map[handle_to_stable[handle]].get("parent_id") or
                 handle_to_stable[handle]) in pending_parents
                for handle in entry["source_ids"])]
            context = _item_context_ids(entries, source_map, paragraphs, opened,
                                        handle_to_stable)
        else:
            context = {handle_to_stable[handle] for entry in entries
                       for handle in entry["source_ids"]}
            context.update(source_map[source]["parent_id"] for source in
                           list(context) if source_map[source].get("parent_id"))
    else:
        context = _item_context_ids(entries, source_map, paragraphs, opened,
                                    handle_to_stable)
    supplied = pending | context
    handles = sorted(stable_to_handle[source] for source in supplied)
    if policy == schema_v14.POLICY:
        from .pipeline_v14 import available_scan_modes
        scan_modes = available_scan_modes(checkpoint, entries, supplied,
                                          source_map, paragraphs, stable_to_handle)
        shown = compact_opened_sources(source_map, supplied, stable_to_handle)
        pending_paragraphs = [paragraph for paragraph in shown
            if paragraph["source_id"] in {stable_to_handle[source]
                for source in pending if source_map[source]["unit_type"] == "paragraph"}]
        schema = schema_v14.extraction_schema(entries, pending_paragraphs, scan_modes)
    else:
        shown = opened_sources(source_map, supplied, stable_to_handle)
        pending_paragraphs = []
        schema = schema_v13.extraction_schema(entries, handles)
    return {"phase": phase, "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_hash(schema), "items": entries,
        "source_window_ids": checkpoint["pending_window_ids"],
        "pending_source_ids": sorted(stable_to_handle[source] for source in pending),
        "opened_sources": shown,
        **({"candidate_paragraph_ids": [p["source_id"] for p in pending_paragraphs],
            "scan_modes": {key: sorted(value) for key, value in scan_modes.items()}}
           if policy == schema_v14.POLICY else {}),
        "catalogue": None,
        "source_scope_note": "Select only fully supplied source. Examine this group before any reading decision."}


def _navigation_manifest(checkpoint: dict, phase: str, row: dict,
                         catalogue: dict, windows: list[dict],
                         stable_to_handle: dict, steps: int,
                         policy: str = POLICY) -> dict:
    entries, _ = _items(checkpoint, stable_to_handle)
    unread = [window["window_id"] for window in windows
              if window["window_id"] not in checkpoint["opened_window_ids"]]
    reader = phase == "reader_navigate"
    allowed = (checkpoint["read_actions"] < 7 and
               (not reader or checkpoint["read_expansions"] < steps))
    just_examined = set(checkpoint["last_extraction_supplied_ids"])
    readable = ([window["window_id"] for window in windows
                 if not set(window["source_ids"]) <= just_examined]
                if allowed else [])
    schema = (schema_v14.navigation_schema(readable) if policy == schema_v14.POLICY
              else schema_v13.navigation_schema(readable, unread))
    navigation_windows = ([{key: window[key] for key in (
        "window_id", "start", "end", "covering_heading", "heading_count",
        "marker_count", "start_preview", "middle_preview", "end_preview")}
        for window in catalogue["windows"] if window["window_id"] in readable]
        if policy == schema_v14.POLICY else catalogue["windows"])
    return {"phase": phase, "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_hash(schema),
        "items": [{key: entry[key] for key in (
            "handle", "id", "revision", "status", "collection", "source_ids")}
            for entry in entries],
        **({"last_batch_assessment": checkpoint["batch_assessments"][-1]}
           if policy != schema_v14.POLICY else {}),
        "catalogue": {**catalogue, "windows": [
            {**window, "reading_status": (
                "unread" if window["window_id"] in unread else
                "readable_again" if window["window_id"] in readable else
                "already_examined")}
            for window in navigation_windows]},
        "opened_window_ids": checkpoint["opened_window_ids"],
        "unread_window_ids": unread, "readable_window_ids": readable,
        "remaining_read_actions": max(0, 7 - checkpoint["read_actions"]),
        "reading_limit_reason": (None if readable else
            "reader_limit" if reader and checkpoint["read_expansions"] >= steps else
            "shared_limit" if checkpoint["read_actions"] >= 7 else
            "no_other_window"),
        "opened_sources": []}


def _late_manifest(checkpoint: dict, phase: str, row: dict,
                   source_map: dict, paragraphs: list[dict],
                   stable_to_handle: dict, policy: str = POLICY) -> dict:
    entries, _ = _items(checkpoint, stable_to_handle)
    handle_to_stable = {handle: source for source, handle in stable_to_handle.items()}
    supplied = (_item_context_ids(entries, source_map, paragraphs,
        set(checkpoint["opened_source_ids"]), handle_to_stable)
        if policy != schema_v14.POLICY else
        {source for entry in entries for handle in entry["source_ids"]
         for source in [handle_to_stable[handle]]})
    handles = sorted(stable_to_handle[source] for source in supplied)
    if policy == schema_v14.POLICY:
        schema = {"classification": schema_v14.classification_schema,
                  "treatment": schema_v14.treatment_schema,
                  "finalizer": schema_v14.finalizer_schema}[phase](entries)
        shown = compact_opened_sources(source_map, supplied | {
            source_map[source].get("parent_id") for source in supplied
            if source_map[source].get("parent_id")}, stable_to_handle)
    else:
        schema = (schema_v13.classification_schema(entries) if phase == "classification"
                  else schema_v12.build_schema(phase, entries, handles))
        shown = opened_sources(source_map, supplied, stable_to_handle)
    return {"phase": phase, "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_hash(schema), "items": entries,
        "opened_sources": shown,
        "catalogue": None}


def _classification_operations(response: dict, entries: list[dict]
                               ) -> tuple[list[dict], list[dict]]:
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
        refs = [{"source_id": source,
            "role": ("primary" if entry["collection"] == "brief" else
                     choice["roles"][source]),
            "attribution": choice["attribution"][source]}
            for source in entry["source_ids"]]
        changes = {"source_refs": refs}
        if entry["collection"] == "brief":
            changes["kind"] = choice["kind"]
        operations.append({"op": "update", "id": entry["id"],
            "revision": entry["revision"], "changes": changes,
            "reason": choice["reason"]})
    return operations, audit


def _classification_operations_v14(response: dict, entries: list[dict]
                                   ) -> tuple[list[dict], list[dict]]:
    operations, audit = [], []
    speakers = response["attribution_by_source"]
    for entry in entries:
        choice = response["decisions"][entry["handle"]]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice["choice"]})
        if choice["choice"] == "keep":
            continue
        if choice["choice"] == "defer":
            operations.append({"op": "defer", "id": entry["id"],
                "revision": entry["revision"], "reason": choice["reason"]})
            continue
        refs = [{"source_id": source,
            "role": ("primary" if entry["collection"] == "brief" else
                     choice["roles"][source]), "attribution": speakers[source]}
            for source in entry["source_ids"]]
        changes = {"source_refs": refs}
        if entry["collection"] == "brief":
            changes["kind"] = choice["kind"]
        operations.append({"op": "update", "id": entry["id"],
            "revision": entry["revision"], "changes": changes,
            "reason": "v14_classification"})
    return operations, audit


def _final_operations_v14(response: dict, entries: list[dict]
                          ) -> tuple[list[dict], list[dict]]:
    operations, audit = [], []
    for entry in entries:
        choice = response["decisions"][entry["handle"]]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice["choice"]})
        if choice["choice"] != "keep":
            operations.append({"op": choice["choice"], "id": entry["id"],
                "revision": entry["revision"], "reason": choice["reason"]})
    return operations, audit


def _treatment_operations_v14(response: dict, entries: list[dict]
                              ) -> tuple[list[dict], list[dict]]:
    operations, audit = [], []
    for entry in entries:
        if entry["collection"] != "aus" or entry["status"] != "active":
            continue
        choice = response["decisions"][entry["handle"]]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice["choice"]})
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
            "reason": choice.get("reason", "v14_no_authority_relation")})
    return operations, audit


def _supplied_ids(manifest: dict, alias_to_stable: dict) -> set[str]:
    return {alias_to_stable[unit["source_id"]]
            for paragraph in manifest["opened_sources"]
            for unit in [paragraph, *paragraph["sentences"]]}


def _queue_scans(checkpoint: dict, phase: str, turn: int, revisions: list[dict],
                 applied: list[dict], supplied: set[str], source_map: dict,
                 paragraphs: list[dict]) -> None:
    if checkpoint["source_scan_queue"]:
        raise ValueError("unfinished_source_scan_queue")
    for requested in revisions:
        item = checkpoint["state"]["items"][requested["item_id"]]
        candidates = _local_revision_candidates(supplied, item["source_refs"],
                                                source_map, paragraphs)
        candidates = _compatible_candidates(candidates, item["source_refs"],
                                             source_map)
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
        candidates = _nearby_source_ids(anchor, supplied, source_map, paragraphs)
        candidates = _compatible_candidates(candidates, item["source_refs"],
                                             source_map)
        if candidates:
            checkpoint["source_scan_queue"].append({
                "item_id": item["id"], "reason": event["reason"],
                "origin": {"phase": phase, "turn": turn, "kind": "new"},
                "candidates": _ordered_sources(candidates, source_map),
                "cursor": 0, "selected": [anchor]})


def _initial_checkpoint(row: dict, windows: list[dict], policy: str = POLICY) -> dict:
    initial_windows = {0, len(windows) - 1}
    opened = _opened_ids(windows, initial_windows)
    return {"schema_version": (schema_v14.SCHEMA_VERSION if policy == schema_v14.POLICY
                                else schema_v13.SCHEMA_VERSION),
        "prompt_version": (schema_v14.PROMPT_VERSION if policy == schema_v14.POLICY
                           else schema_v13.PROMPT_VERSION),
        "reading_policy": policy, "source_hash": row["source_hash"],
        "stage": "reader_extract", "turn": 0, "state": initial_state(),
        "opened_window_ids": sorted(initial_windows),
        "opened_source_ids": sorted(opened),
        "pending_window_ids": sorted(initial_windows),
        "pending_source_ids": sorted(opened),
        "pending_is_reused": False,
        "last_processed_window_ids": [], "last_processed_source_ids": [],
        "last_extraction_supplied_ids": [], "batch_assessments": [],
        "phase_source_ids": {}, "read_expansions": 0,
        "request_journal": {}, "protocol_errors": [], "trace": [],
        "snapshots": [], "stop_reason": None, "source_scan_queue": [],
        "source_scan_turn": 0, "read_actions": 0, "reread_actions": 0,
        "reading_history": [], "navigation_history": [],
        "unread_window_ids_final": [],
        **({"candidate_uncertain": [], "scan_seen": {}}
           if policy == schema_v14.POLICY else {})}


def build_case_v13(row: dict, endpoint, config: dict, size: int, steps: int,
                   output: Path, policy: str = POLICY) -> dict:
    text, source_hash = load_source(row["source"])
    if source_hash != row["source_hash"]:
        raise ValueError("source_changed_since_manifest")
    paragraphs, units = source_structure(text, source_hash)
    windows = structure_windows(paragraphs, size)
    if not windows:
        raise ValueError("empty_source")
    source_map = {unit["source_id"]: unit for unit in units}
    stable_to_handle, alias_to_stable = source_handles(units)
    catalogue, navigation = guided_catalogue(text, units, windows)
    save(output / "source_navigation.json", {"source_hash": source_hash,
                                              **navigation})
    checkpoint_path = output / "checkpoint.json"
    experiment = output.parents[1].name
    config_path = output.parents[1] / "config.json"
    if config_path.exists():
        experiment += ":" + digest(config_path.read_bytes())[:12]
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (checkpoint.get("schema_version") != (schema_v14.SCHEMA_VERSION if
                policy == schema_v14.POLICY else schema_v13.SCHEMA_VERSION) or
            checkpoint.get("prompt_version") != (schema_v14.PROMPT_VERSION if
                policy == schema_v14.POLICY else schema_v13.PROMPT_VERSION) or
            checkpoint.get("source_hash") != source_hash or
            checkpoint.get("reading_policy") != policy):
            raise ValueError("checkpoint_identity_mismatch")
    else:
        checkpoint = _initial_checkpoint(row, windows, policy)
        save(checkpoint_path, checkpoint)

    while checkpoint["stage"] not in {"complete", "incomplete"}:
        phase, turn = checkpoint["stage"], checkpoint["turn"]
        if policy == schema_v14.POLICY and phase in {
                "classification", "treatment", "finalizer"}:
            live = [item for item in checkpoint["state"]["items"].values()
                    if item["status"] != "deleted"]
            skip = (phase == "classification" and not any(
                item["status"] == "active" for item in live)) or (
                phase == "treatment" and not any(item["status"] == "active" and
                item["collection"] == "aus" for item in live)) or (
                phase == "finalizer" and not live)
            if skip:
                checkpoint["stage"] = {"classification": "treatment",
                    "treatment": "finalizer", "finalizer": "complete"}[phase]
                checkpoint["trace"].append({"phase": phase, "turn": 0,
                    "skipped_by_host": "no_applicable_items"})
                if phase == "finalizer":
                    checkpoint["stop_reason"] = "host_finalized_empty"
                save(checkpoint_path, checkpoint)
                continue
        if phase == "source_scan":
            if checkpoint["source_scan_turn"] >= config.get(
                    "max_source_scan_requests", 24):
                checkpoint["stage"] = "incomplete"
                checkpoint["stop_reason"] = "source_scan_request_limit"
                save(checkpoint_path, checkpoint)
                break
            if policy == schema_v14.POLICY:
                from .pipeline_v14 import scan_one_batch
                scan_one_batch(checkpoint, checkpoint_path, output, endpoint,
                    config, experiment, row, source_map, stable_to_handle,
                    alias_to_stable)
            else:
                _scan_one_batch(checkpoint, checkpoint_path, output, endpoint,
                    config, experiment, row, source_map, stable_to_handle,
                    alias_to_stable, POLICY)
            continue

        if phase in {"reader_extract", "selection_extract"}:
            manifest = _extraction_manifest(checkpoint, phase, row, source_map,
                                            paragraphs, stable_to_handle, policy)
        elif phase in {"reader_navigate", "selection_navigate"}:
            manifest = _navigation_manifest(checkpoint, phase, row, catalogue,
                                            windows, stable_to_handle, steps, policy)
        else:
            manifest = _late_manifest(checkpoint, phase, row, source_map,
                                      paragraphs, stable_to_handle, policy)
        response = _call(checkpoint, checkpoint_path, output, endpoint, config,
            experiment, row, phase, turn, manifest, policy)
        record = checkpoint["request_journal"][f"{phase}:{turn}"]
        if record["status"] == "applied":
            raise ValueError("applied_response_stage_not_advanced")
        saved = record["payload"]["manifest"]
        if saved["source_hash"] != source_hash or saved["phase"] != phase:
            raise ValueError("journal_manifest_mismatch")
        errors = validate(response, saved["schema"])
        entries = saved["items"]
        supplied = _supplied_ids(saved, alias_to_stable)
        if not errors and phase.endswith("_extract") and policy == schema_v14.POLICY:
            errors.extend(schema_v14.validate_extraction(response, [paragraph
                for paragraph in saved["opened_sources"] if paragraph["source_id"]
                in saved["candidate_paragraph_ids"]]))
        if not errors and phase.endswith("_navigate") and policy != schema_v14.POLICY:
            errors.extend(schema_v13.validate_reading_decision(
                response, saved["unread_window_ids"]))
        if not errors and phase == "treatment":
            errors.extend((schema_v14.validate_treatment(response, entries)
                if policy == schema_v14.POLICY else
                schema_v13.validate_treatment_evidence(response, entries)))
        if not errors and phase == "classification":
            errors.extend((schema_v14.validate_classification(response, entries)
                if policy == schema_v14.POLICY else
                schema_v13.validate_classification(response, entries)))
        operations, audit, revisions = [], [], []
        if not errors:
            if phase.endswith("_extract"):
                if policy == schema_v14.POLICY:
                    from .pipeline_v14 import extraction_operations
                    operations, audit, revisions, uncertain = extraction_operations(
                        response, entries, saved)
                else:
                    operations, audit, revisions = _candidate_selection_operations(
                        response, entries)
            elif phase == "classification":
                operations, audit = (_classification_operations_v14(response, entries)
                    if policy == schema_v14.POLICY else
                    _classification_operations(response, entries))
            elif phase == "treatment":
                operations, audit = (_treatment_operations_v14(response, entries)
                    if policy == schema_v14.POLICY else
                    _candidate_treatment_operations(response, entries))
            elif phase == "finalizer":
                operations, audit = (_final_operations_v14(response, entries)
                    if policy == schema_v14.POLICY else
                    _final_operations(response, entries))
        if not errors and operations:
            new_state, applied, rejected, noops = apply_operations_independently(
                checkpoint["state"], operations, supplied, source_map,
                source_hash, row["case_id"], aliases=alias_to_stable,
                stable_to_handle=stable_to_handle,
                allowed_target_ids={entry["id"] for entry in entries},
                phase="reader")
            if rejected:
                errors = [{"path": f"decisions_or_new_items[{item['index']}]",
                    "error_code": item["error_code"]} for item in rejected]
        else:
            new_state, applied, noops = checkpoint["state"], [], []
        checkpoint["phase_source_ids"][phase] = sorted(set(
            checkpoint["phase_source_ids"].get(phase, [])) | supplied)
        if errors:
            checkpoint["protocol_errors"].extend({"phase": phase,
                "turn": turn, **error} for error in errors)
            checkpoint["stage"] = "incomplete"
            checkpoint["stop_reason"] = "invalid_constrained_response"
        else:
            checkpoint["state"] = new_state
            if phase.endswith("_extract"):
                checkpoint["last_processed_source_ids"] = deepcopy(
                    checkpoint["pending_source_ids"])
                checkpoint["last_processed_window_ids"] = deepcopy(
                    checkpoint["pending_window_ids"])
                checkpoint["last_extraction_supplied_ids"] = sorted(supplied)
                checkpoint["batch_assessments"].append({"phase": phase,
                    "turn": turn, "window_ids": saved["source_window_ids"],
                    "source_ids": saved["pending_source_ids"],
                    "reused_last_group": checkpoint["pending_is_reused"],
                    "supplied_source_count": len(supplied),
                    "new_items_proposed": (len(response["new_items"]) if
                        policy != schema_v14.POLICY else sum(
                            item["op"] == "add" for item in operations)),
                    "assessment": (response["batch_assessment"] if
                        policy != schema_v14.POLICY else None)})
                if policy == schema_v14.POLICY:
                    checkpoint["candidate_uncertain"].extend(uncertain)
                checkpoint["stage"] = ("reader_navigate" if phase ==
                                       "reader_extract" else "selection_navigate")
                if policy == schema_v14.POLICY:
                    from .pipeline_v14 import queue_scans
                    queue_scans(checkpoint, phase, turn, revisions, applied,
                        supplied, source_map, paragraphs)
                else:
                    _queue_scans(checkpoint, phase, turn, revisions, applied,
                                 supplied, source_map, paragraphs)
                if checkpoint["source_scan_queue"]:
                    checkpoint["source_scan_resume"] = {"stage": checkpoint["stage"],
                        "turn": turn, "snapshot": None}
                    checkpoint["stage"] = "source_scan"
                    checkpoint["turn"] = checkpoint["source_scan_turn"]
            elif phase.endswith("_navigate"):
                decision = response["reading_decision"]
                chosen = decision["window_ids"] if decision["action"] == "read" else []
                prior_windows = set(checkpoint["opened_window_ids"])
                chosen_sources = _opened_ids(windows, set(chosen))
                checkpoint["opened_window_ids"] = sorted(prior_windows | set(chosen))
                checkpoint["opened_source_ids"] = sorted(set(
                    checkpoint["opened_source_ids"]) | chosen_sources)
                checkpoint["pending_window_ids"] = chosen
                checkpoint["pending_source_ids"] = sorted(chosen_sources)
                checkpoint["pending_is_reused"] = False
                reread = [number for number in chosen if number in prior_windows]
                checkpoint["read_actions"] += bool(chosen)
                checkpoint["reread_actions"] += bool(reread)
                history = {"phase": phase, "turn": turn, "decision": decision,
                    "opened_window_ids": chosen,
                    "new_window_ids": [number for number in chosen
                                       if number not in prior_windows],
                    "reread_window_ids": reread,
                    "remaining_actions": 7 - checkpoint["read_actions"],
                    "read_limit_reason": saved["reading_limit_reason"]}
                checkpoint["reading_history"].append(history)
                checkpoint["navigation_history"].append(history)
                if phase == "reader_navigate":
                    checkpoint["read_expansions"] += bool(chosen)
                    if chosen:
                        checkpoint["stage"], checkpoint["turn"] = (
                            "reader_extract", turn + 1)
                    else:
                        save(output / "snapshots/draft_after_reading.json",
                             _snapshot(checkpoint["state"]))
                        checkpoint["snapshots"].append("draft_after_reading")
                        checkpoint["pending_window_ids"] = deepcopy(
                            checkpoint["last_processed_window_ids"])
                        checkpoint["pending_source_ids"] = deepcopy(
                            checkpoint["last_processed_source_ids"])
                        checkpoint["pending_is_reused"] = True
                        checkpoint["stage"], checkpoint["turn"] = (
                            "selection_extract", 0)
                elif chosen:
                    checkpoint["stage"], checkpoint["turn"] = (
                        "selection_extract", turn + 1)
                else:
                    save(output / "snapshots/after_selection_repair.json",
                         _snapshot(checkpoint["state"]))
                    checkpoint["snapshots"].append("after_selection_repair")
                    checkpoint["unread_window_ids_final"] = [window["window_id"]
                        for window in windows if window["window_id"] not in
                        checkpoint["opened_window_ids"]]
                    checkpoint["pending_window_ids"] = []
                    checkpoint["pending_source_ids"] = []
                    checkpoint["stage"], checkpoint["turn"] = (
                        "classification", 0)
            else:
                next_phase, snapshot = {"classification": (
                    "treatment", "after_classification_repair"),
                    "treatment": ("finalizer", "after_treatment_repair"),
                    "finalizer": ("complete", "final")}[phase]
                checkpoint["stage"], checkpoint["turn"] = next_phase, 0
                if phase == "finalizer":
                    checkpoint["stop_reason"] = "finalization_complete"
                save(output / "snapshots" / f"{snapshot}.json",
                     _snapshot(checkpoint["state"]))
                checkpoint["snapshots"].append(snapshot)
            checkpoint["trace"].append({"phase": phase, "turn": turn,
                "schema_hash": record["schema_hash"], "decisions": audit,
                "batch_assessment": (response.get("batch_assessment")
                                     if phase.endswith("_extract") else None),
                "reading_decision": (response["reading_decision"]
                                     if phase.endswith("_navigate") else None),
                "applied": applied, "noop_duplicates": noops})
        record["status"] = "applied"
        record["post_request_snapshot"] = _snapshot(checkpoint["state"])
        save(checkpoint_path, checkpoint)

    if checkpoint["stage"] == "complete" and (
            checkpoint["protocol_errors"] or checkpoint["source_scan_queue"] or
            checkpoint["pending_source_ids"] or checkpoint["pending_window_ids"] or
            sum(not entry["reused_last_group"] for entry in
                checkpoint["batch_assessments"]) != 1 + checkpoint["read_actions"] or
            (checkpoint["request_journal"].get("finalizer:0", {}).get(
                "status") != "applied" and checkpoint.get("stop_reason") !=
                "host_finalized_empty")):
        raise ValueError("completed_without_finished_workflow")
    result = _result(row, text, units, checkpoint)
    save(output / "trace.json", checkpoint["trace"])
    save(output / "case.json", result)
    return result
