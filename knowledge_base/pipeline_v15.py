"""V15: bounded paragraph triage followed by sentence refinement when needed."""

from __future__ import annotations

import json
from pathlib import Path

from . import schema_v15
from .pipeline_v10 import (_call, _items, _opened_ids, _result, _snapshot)
from .pipeline_v13 import (_classification_operations_v14,
    _final_operations_v14, _treatment_operations_v14)
from .pipeline_v14 import (available_scan_modes, queue_scans, scan_one_batch)
from .source import (compact_opened_sources, digest, guided_catalogue,
    load_source, save, source_handles, source_structure, structure_windows)
from .state_v9 import apply_operations_independently, initial_state


def _paragraphs_for_windows(windows: list[dict], selected: set[int],
                            already_triaged: set[str]) -> list[str]:
    values = {source for window in windows if window["window_id"] in selected
              for source in window["paragraph_ids"] if source not in already_triaged}
    ordered = []
    for window in windows:
        if window["window_id"] not in selected:
            continue
        for source in window["paragraph_ids"]:
            if source in values and source not in ordered:
                ordered.append(source)
    return ordered


def _initial_checkpoint(row: dict, windows: list[dict]) -> dict:
    initial_windows = {0, len(windows) - 1}
    opened = _opened_ids(windows, initial_windows)
    paragraph_ids = _paragraphs_for_windows(windows, initial_windows, set())
    return {"schema_version": schema_v15.SCHEMA_VERSION,
        "prompt_version": schema_v15.PROMPT_VERSION,
        "reading_policy": schema_v15.POLICY, "source_hash": row["source_hash"],
        "stage": "reader_triage", "turn": 0, "state": initial_state(),
        "opened_window_ids": sorted(initial_windows),
        "opened_source_ids": sorted(opened),
        "pending_window_ids": sorted(initial_windows),
        "pending_source_ids": sorted(opened),
        "triage_queue": paragraph_ids, "refinement_queue": [],
        "triaged_paragraph_ids": [], "refined_paragraph_ids": [],
        "triage_history": [], "refinement_history": [],
        "candidate_uncertain": [], "phase_source_ids": {},
        "read_expansions": 0, "read_actions": 0, "reread_actions": 0,
        "reading_history": [], "navigation_history": [],
        "unread_window_ids_final": [], "request_journal": {},
        "protocol_errors": [], "trace": [], "snapshots": [],
        "stop_reason": None, "source_scan_queue": [], "source_scan_turn": 0,
        "source_scan_resume": None, "scan_seen": {}, "reconsider_done": []}


def _triage_manifest(checkpoint: dict, phase: str, row: dict,
                     source_map: dict, stable_to_handle: dict) -> dict:
    batch = checkpoint["triage_queue"][:schema_v15.TRIAGE_BATCH_SIZE]
    if not batch:
        raise ValueError("empty_triage_batch")
    paragraphs = [{"source_id": stable_to_handle[source],
        "unit_type": "paragraph", "start": source_map[source]["start"],
        "end": source_map[source]["end"], "text": source_map[source]["text"]}
        for source in batch]
    schema = schema_v15.triage_schema(paragraphs)
    return {"phase": phase, "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_v15.schema_hash(schema), "items": [],
        "candidate_paragraph_ids": [paragraph["source_id"] for paragraph in paragraphs],
        "opened_sources": paragraphs, "catalogue": None}


def _refinement_manifest(checkpoint: dict, phase: str, row: dict,
                         source_map: dict, stable_to_handle: dict) -> dict:
    batch = checkpoint["refinement_queue"][:schema_v15.REFINEMENT_BATCH_SIZE]
    if not batch:
        raise ValueError("empty_refinement_batch")
    supplied = set(batch)
    for source in batch:
        supplied.update(source_map[source]["sentence_ids"])
    shown = compact_opened_sources(source_map, supplied, stable_to_handle)
    schema = schema_v15.refinement_schema(shown)
    return {"phase": phase, "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_v15.schema_hash(schema), "items": [],
        "parent_paragraph_ids": [stable_to_handle[source] for source in batch],
        "opened_sources": shown, "catalogue": None}


def _add_operation(source_handle: str, collection: str, reason: str) -> list[dict]:
    operations = []
    targets = ("brief", "aus") if collection == "both" else (collection,)
    for target in targets:
        item = {"source_refs": [{"source_id": source_handle, "role": "primary",
                                  "attribution": "unknown"}]}
        if target == "brief":
            item["kind"] = "facts"
        else:
            item["treatment"] = {"value": "unknown",
                "authority_source_ids": [], "response_source_ids": []}
        operations.append({"op": "add", "collection": target, "item": item,
                           "reason": reason})
    return operations


def _triage_operations(response: dict, manifest: dict
                       ) -> tuple[list[dict], list[dict], list[str], list[dict]]:
    operations, audit, refine, uncertain = [], [], [], []
    for source in manifest["candidate_paragraph_ids"]:
        choice = response["choices"][source]
        audit.append({"source_id": source, "choice": choice})
        if choice == "refine_sentences":
            refine.append(source)
        elif choice == "uncertain":
            uncertain.append({"source_id": source,
                              "reason": "model_marked_uncertain_at_triage"})
        elif choice in {"brief", "aus", "both"}:
            operations.extend(_add_operation(source, choice,
                                              "v15_paragraph_triage"))
    return operations, audit, refine, uncertain


def _refinement_operations(response: dict, manifest: dict
                           ) -> tuple[list[dict], list[dict], list[dict]]:
    operations, audit, uncertain = [], [], []
    for paragraph in manifest["opened_sources"]:
        for sentence in paragraph["sentences"]:
            source = sentence["source_id"]
            choice = response["choices"][source]
            audit.append({"source_id": source, "parent_id": paragraph["source_id"],
                          "choice": choice})
            if choice == "uncertain":
                uncertain.append({"source_id": source,
                                  "reason": "model_marked_uncertain_at_refinement"})
            elif choice in {"brief", "aus", "both"}:
                operations.extend(_add_operation(source, choice,
                                                  "v15_sentence_refinement"))
    return operations, audit, uncertain


def _navigation_manifest(checkpoint: dict, phase: str, row: dict,
                         catalogue: dict, windows: list[dict], steps: int) -> dict:
    unread = [window["window_id"] for window in windows
              if window["window_id"] not in checkpoint["opened_window_ids"]]
    triaged = set(checkpoint["triaged_paragraph_ids"]) | set(
        checkpoint["triage_queue"])
    reader = phase == "reader_navigate"
    allowed = checkpoint["read_actions"] < 7 and (
        not reader or checkpoint["read_expansions"] < steps)
    readable = [window["window_id"] for window in windows
        if window["window_id"] in unread and any(
            source not in triaged for source in window["paragraph_ids"])] if allowed else []
    schema = schema_v15.navigation_schema(readable)
    compact = [{key: window.get(key) for key in (
        "window_id", "start", "end", "covering_heading", "heading_count",
        "marker_count", "start_preview", "middle_preview", "end_preview")}
        for window in catalogue["windows"] if window["window_id"] in readable]
    return {"phase": phase, "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_v15.schema_hash(schema), "items": [],
        "catalogue": {"windows": compact, "preview_is_not_read": True},
        "unread_window_ids": unread, "readable_window_ids": readable,
        "remaining_read_actions": max(0, 7 - checkpoint["read_actions"]),
        "reading_limit_reason": (None if readable else "reader_limit"
            if reader and checkpoint["read_expansions"] >= steps else "shared_limit"
            if checkpoint["read_actions"] >= 7 else "no_unread_unique_source"),
        "opened_sources": []}


def _selection_context(checkpoint: dict, source_map: dict, paragraphs: list[dict]
                       ) -> set[str]:
    opened = set(checkpoint["opened_source_ids"])
    positions = {paragraph["source_id"]: index for index, paragraph in
                 enumerate(paragraphs)}
    selected = set()
    for item in checkpoint["state"]["items"].values():
        if item["status"] == "deleted":
            continue
        for ref in item["source_refs"]:
            source = ref["source_id"]
            parent = source_map[source].get("parent_id") or source
            selected.add(source)
            selected.add(parent)
            index = positions[parent]
            for offset in range(max(0, index - 1), min(len(paragraphs), index + 2)):
                candidate_parent = paragraphs[offset]["source_id"]
                if candidate_parent in opened:
                    selected.add(candidate_parent)
                    selected.update(sentence for sentence in
                        paragraphs[offset]["sentence_ids"] if sentence in opened)
    return selected


def _selection_manifest(checkpoint: dict, row: dict, source_map: dict,
                        paragraphs: list[dict], stable_to_handle: dict) -> dict:
    entries, _ = _items(checkpoint, stable_to_handle)
    supplied = _selection_context(checkpoint, source_map, paragraphs)
    scan_modes = available_scan_modes(checkpoint, entries, supplied, source_map,
                                      paragraphs, stable_to_handle)
    shown = compact_opened_sources(source_map, supplied, stable_to_handle)
    schema = schema_v15.selection_review_schema(entries, scan_modes)
    return {"phase": "selection_review", "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_v15.schema_hash(schema), "items": entries,
        "scan_modes": {key: sorted(value) for key, value in scan_modes.items()},
        "opened_sources": shown, "catalogue": None}


def _selection_operations(response: dict, entries: list[dict]
                          ) -> tuple[list[dict], list[dict], list[dict]]:
    operations, audit, revisions = [], [], []
    for entry in entries:
        decision = response["decisions"][entry["handle"]]
        choice = decision["choice"]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": choice})
        if choice == "keep":
            continue
        if choice in {"scan_extend", "scan_reconsider"}:
            revisions.append({"item_id": entry["id"], "mode": choice,
                              "reason": decision["reason"]})
        else:
            operations.append({"op": choice, "id": entry["id"],
                "revision": entry["revision"], "reason": decision["reason"]})
    return operations, audit, revisions


def _late_manifest(checkpoint: dict, phase: str, row: dict,
                   source_map: dict, stable_to_handle: dict) -> dict:
    entries, _ = _items(checkpoint, stable_to_handle)
    supplied = {ref["source_id"] for item in checkpoint["state"]["items"].values()
                if item["status"] != "deleted" for ref in item["source_refs"]}
    shown = [{"source_id": stable_to_handle[source],
        "unit_type": source_map[source]["unit_type"],
        "start": source_map[source]["start"], "end": source_map[source]["end"],
        "text": source_map[source]["text"]} for source in sorted(supplied,
            key=lambda value: (source_map[value]["start"], source_map[value]["end"]))]
    schema = {"classification": schema_v15.classification_schema,
              "treatment": schema_v15.treatment_schema,
              "finalizer": schema_v15.finalizer_schema}[phase](entries)
    return {"phase": phase, "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_v15.schema_hash(schema), "items": entries,
        "opened_sources": shown, "catalogue": None}


def _manifest_supplied(manifest: dict, alias_to_stable: dict) -> set[str]:
    supplied = set()
    for source in manifest.get("opened_sources", []):
        if source["source_id"] in alias_to_stable:
            supplied.add(alias_to_stable[source["source_id"]])
        for sentence in source.get("sentences", []):
            supplied.add(alias_to_stable[sentence["source_id"]])
    return supplied


def _apply_operations(checkpoint: dict, operations: list[dict], supplied: set[str],
                      source_map: dict, row: dict, alias_to_stable: dict,
                      stable_to_handle: dict, allowed: set[str], phase: str
                      ) -> tuple[list[dict], list[dict], list[dict]]:
    if not operations:
        return [], [], []
    new_state, applied, rejected, noops = apply_operations_independently(
        checkpoint["state"], operations, supplied, source_map, row["source_hash"],
        row["case_id"], aliases=alias_to_stable,
        stable_to_handle=stable_to_handle, allowed_target_ids=allowed, phase=phase)
    if not rejected:
        checkpoint["state"] = new_state
    return applied if not rejected else [], rejected, noops if not rejected else []


def _next_turn(checkpoint: dict, phase: str) -> int:
    prefix = phase + ":"
    return sum(key.startswith(prefix) for key in checkpoint["request_journal"])


def _finish_group(checkpoint: dict, phase: str) -> None:
    next_phase = ("reader_navigate" if phase.startswith("reader_")
                  else "selection_review")
    checkpoint["stage"] = next_phase
    checkpoint["turn"] = _next_turn(checkpoint, next_phase)


def build_case_v15(row: dict, endpoint, config: dict, size: int, steps: int,
                   output: Path) -> dict:
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
    save(output / "source_navigation.json", {"source_hash": source_hash, **navigation})
    checkpoint_path = output / "checkpoint.json"
    experiment = output.parents[1].name
    config_path = output.parents[1] / "config.json"
    if config_path.exists():
        experiment += ":" + digest(config_path.read_bytes())[:12]
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (checkpoint.get("schema_version") != schema_v15.SCHEMA_VERSION or
            checkpoint.get("prompt_version") != schema_v15.PROMPT_VERSION or
            checkpoint.get("source_hash") != source_hash or
            checkpoint.get("reading_policy") != schema_v15.POLICY):
            raise ValueError("checkpoint_identity_mismatch")
    else:
        checkpoint = _initial_checkpoint(row, windows)
        save(checkpoint_path, checkpoint)

    while checkpoint["stage"] not in {"complete", "incomplete"}:
        phase, turn = checkpoint["stage"], checkpoint["turn"]
        if phase in {"classification", "treatment", "finalizer"}:
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
                checkpoint["turn"] = 0
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
            scan_one_batch(checkpoint, checkpoint_path, output, endpoint, config,
                experiment, row, source_map, stable_to_handle, alias_to_stable,
                policy=schema_v15.POLICY, schema_module=schema_v15)
            continue

        if phase in {"reader_triage", "selection_triage"}:
            if not checkpoint["triage_queue"]:
                if checkpoint["refinement_queue"]:
                    checkpoint["stage"] = phase.replace("triage", "refine")
                    checkpoint["turn"] = _next_turn(checkpoint,
                                                     checkpoint["stage"])
                else:
                    _finish_group(checkpoint, phase)
                save(checkpoint_path, checkpoint)
                continue
            manifest = _triage_manifest(checkpoint, phase, row, source_map,
                                        stable_to_handle)
        elif phase in {"reader_refine", "selection_refine"}:
            if not checkpoint["refinement_queue"]:
                _finish_group(checkpoint, phase)
                save(checkpoint_path, checkpoint)
                continue
            manifest = _refinement_manifest(checkpoint, phase, row, source_map,
                                            stable_to_handle)
        elif phase in {"reader_navigate", "selection_navigate"}:
            manifest = _navigation_manifest(checkpoint, phase, row, catalogue,
                                            windows, steps)
        elif phase == "selection_review":
            entries, _ = _items(checkpoint, stable_to_handle)
            if not entries:
                checkpoint["stage"] = "selection_navigate"
                checkpoint["turn"] = _next_turn(checkpoint, "selection_navigate")
                checkpoint["trace"].append({"phase": phase, "turn": turn,
                    "skipped_by_host": "no_items_to_review"})
                save(checkpoint_path, checkpoint)
                continue
            manifest = _selection_manifest(checkpoint, row, source_map, paragraphs,
                                           stable_to_handle)
        else:
            manifest = _late_manifest(checkpoint, phase, row, source_map,
                                      stable_to_handle)

        response = _call(checkpoint, checkpoint_path, output, endpoint, config,
            experiment, row, phase, turn, manifest, schema_v15.POLICY)
        record = checkpoint["request_journal"][f"{phase}:{turn}"]
        if record["status"] == "applied":
            raise ValueError("applied_response_stage_not_advanced")
        saved = record["payload"]["manifest"]
        if saved["source_hash"] != source_hash or saved["phase"] != phase:
            raise ValueError("journal_manifest_mismatch")
        errors = schema_v15.validate(response, saved["schema"])
        if not errors and phase.endswith("_refine"):
            errors.extend(schema_v15.validate_refinement(
                response, saved["opened_sources"]))
        entries = saved["items"]
        supplied = _manifest_supplied(saved, alias_to_stable)
        if not errors and phase == "classification":
            errors.extend(schema_v15.validate_classification(response, entries))
        if not errors and phase == "treatment":
            errors.extend(schema_v15.validate_treatment(response, entries))
        operations, audit, revisions, uncertain = [], [], [], []
        refine_handles = []
        if not errors:
            if phase.endswith("_triage"):
                operations, audit, refine_handles, uncertain = _triage_operations(
                    response, saved)
            elif phase.endswith("_refine"):
                operations, audit, uncertain = _refinement_operations(response, saved)
            elif phase == "selection_review":
                operations, audit, revisions = _selection_operations(response, entries)
            elif phase == "classification":
                operations, audit = _classification_operations_v14(response, entries)
            elif phase == "treatment":
                operations, audit = _treatment_operations_v14(response, entries)
            elif phase == "finalizer":
                operations, audit = _final_operations_v14(response, entries)

        applied, rejected, noops = [], [], []
        if not errors and operations:
            apply_phase = ("reader" if phase.endswith(("_triage", "_refine")) or
                           phase == "selection_review" else "reader")
            applied, rejected, noops = _apply_operations(checkpoint, operations,
                supplied, source_map, row, alias_to_stable, stable_to_handle,
                {entry["id"] for entry in entries}, apply_phase)
            errors.extend({"path": f"$.decisions[{item['index']}]",
                           "error_code": item["error_code"]} for item in rejected)

        checkpoint["phase_source_ids"][phase] = sorted(set(
            checkpoint["phase_source_ids"].get(phase, [])) | supplied)
        if errors:
            checkpoint["protocol_errors"].extend({"phase": phase, "turn": turn,
                **error} for error in errors)
            checkpoint["stage"] = "incomplete"
            checkpoint["stop_reason"] = "invalid_constrained_response"
        elif phase.endswith("_triage"):
            batch_handles = saved["candidate_paragraph_ids"]
            batch = [alias_to_stable[handle] for handle in batch_handles]
            checkpoint["triage_queue"] = checkpoint["triage_queue"][len(batch):]
            checkpoint["triaged_paragraph_ids"].extend(source for source in batch
                if source not in checkpoint["triaged_paragraph_ids"])
            checkpoint["refinement_queue"].extend(alias_to_stable[handle]
                for handle in refine_handles if alias_to_stable[handle] not in
                checkpoint["refinement_queue"])
            checkpoint["candidate_uncertain"].extend(uncertain)
            checkpoint["triage_history"].append({"phase": phase, "turn": turn,
                "paragraph_ids": batch_handles, "decisions": audit})
            if checkpoint["triage_queue"]:
                checkpoint["turn"] = turn + 1
            elif checkpoint["refinement_queue"]:
                checkpoint["stage"], checkpoint["turn"] = (
                    phase.replace("triage", "refine"), _next_turn(
                        checkpoint, phase.replace("triage", "refine")))
            else:
                _finish_group(checkpoint, phase)
        elif phase.endswith("_refine"):
            parent_handles = saved["parent_paragraph_ids"]
            batch = [alias_to_stable[handle] for handle in parent_handles]
            checkpoint["refinement_queue"] = checkpoint["refinement_queue"][len(batch):]
            checkpoint["refined_paragraph_ids"].extend(source for source in batch
                if source not in checkpoint["refined_paragraph_ids"])
            checkpoint["candidate_uncertain"].extend(uncertain)
            checkpoint["refinement_history"].append({"phase": phase, "turn": turn,
                "paragraph_ids": parent_handles, "decisions": audit})
            if checkpoint["refinement_queue"]:
                checkpoint["turn"] = turn + 1
            else:
                _finish_group(checkpoint, phase)
        elif phase.endswith("_navigate"):
            decision = response["reading_decision"]
            chosen = decision.get("window_ids", []) if decision["action"] == "read" else []
            prior = set(checkpoint["opened_window_ids"])
            if set(chosen) & prior:
                errors.append({"path": "$.reading_decision.window_ids",
                               "error_code": "reread_not_allowed"})
                checkpoint["protocol_errors"].extend({"phase": phase,
                    "turn": turn, **error} for error in errors)
                checkpoint["stage"] = "incomplete"
                checkpoint["stop_reason"] = "invalid_constrained_response"
            else:
                new_sources = _opened_ids(windows, set(chosen))
                checkpoint["opened_window_ids"] = sorted(prior | set(chosen))
                checkpoint["opened_source_ids"] = sorted(set(
                    checkpoint["opened_source_ids"]) | new_sources)
                checkpoint["pending_window_ids"] = chosen
                checkpoint["pending_source_ids"] = sorted(new_sources)
                checkpoint["read_actions"] += bool(chosen)
                history = {"phase": phase, "turn": turn, "decision": decision,
                    "opened_window_ids": chosen, "new_window_ids": chosen,
                    "reread_window_ids": [],
                    "remaining_actions": 7 - checkpoint["read_actions"],
                    "read_limit_reason": saved["reading_limit_reason"]}
                checkpoint["reading_history"].append(history)
                checkpoint["navigation_history"].append(history)
                if chosen:
                    if phase == "reader_navigate":
                        checkpoint["read_expansions"] += 1
                    queue = _paragraphs_for_windows(windows, set(chosen), set(
                        checkpoint["triaged_paragraph_ids"]))
                    if not queue:
                        checkpoint["stage"] = "incomplete"
                        checkpoint["stop_reason"] = "opened_window_without_new_paragraph"
                    else:
                        checkpoint["triage_queue"] = queue
                        checkpoint["stage"] = phase.replace("navigate", "triage")
                        checkpoint["turn"] = _next_turn(checkpoint,
                                                         checkpoint["stage"])
                elif phase == "reader_navigate":
                    save(output / "snapshots/draft_after_reading.json",
                         _snapshot(checkpoint["state"]))
                    checkpoint["snapshots"].append("draft_after_reading")
                    checkpoint["stage"] = "selection_review"
                    checkpoint["turn"] = _next_turn(checkpoint, "selection_review")
                else:
                    save(output / "snapshots/after_selection_repair.json",
                         _snapshot(checkpoint["state"]))
                    checkpoint["snapshots"].append("after_selection_repair")
                    checkpoint["unread_window_ids_final"] = [window["window_id"]
                        for window in windows if window["window_id"] not in
                        checkpoint["opened_window_ids"]]
                    checkpoint["pending_window_ids"] = []
                    checkpoint["pending_source_ids"] = []
                    checkpoint["stage"], checkpoint["turn"] = "classification", 0
        elif phase == "selection_review":
            next_navigation_turn = _next_turn(checkpoint, "selection_navigate")
            checkpoint["stage"], checkpoint["turn"] = (
                "selection_navigate", next_navigation_turn)
            queue_scans(checkpoint, phase, turn, revisions, [], supplied,
                        source_map, paragraphs)
            if checkpoint["source_scan_queue"]:
                checkpoint["source_scan_resume"] = {"stage": "selection_navigate",
                    "turn": next_navigation_turn, "snapshot": None}
                checkpoint["stage"] = "source_scan"
                checkpoint["turn"] = checkpoint["source_scan_turn"]
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
            "applied": applied, "noop_duplicates": noops})
        record["status"] = "applied"
        record["post_request_snapshot"] = _snapshot(checkpoint["state"])
        save(checkpoint_path, checkpoint)

    if checkpoint["stage"] == "complete" and (
            checkpoint["protocol_errors"] or checkpoint["source_scan_queue"] or
            checkpoint["triage_queue"] or checkpoint["refinement_queue"] or
            checkpoint["pending_source_ids"] or checkpoint["pending_window_ids"] or
            (checkpoint["request_journal"].get("finalizer:0", {}).get(
                "status") != "applied" and checkpoint.get("stop_reason") !=
                "host_finalized_empty")):
        raise ValueError("completed_without_finished_workflow")
    result = _result(row, text, units, checkpoint)
    save(output / "trace.json", checkpoint["trace"])
    save(output / "case.json", result)
    return result

