"""V6 extractive KB pipeline: draft, two semantic repairs, then finalization."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from .endpoint import BudgetStop, ModelProtocolError, _cache_identity, _read_cache
from .prompts_v6 import (CLASSIFICATION_REPAIR, FINALIZER, PROTOCOL_REPAIR,
                         READER, SELECTION_REPAIR, VERSION)
from .schema_v6 import SCHEMA_VERSION
from .source import (alias_item_sources, digest, load_source, materialize_sources,
                     opened_sources, save, source_handles, source_interval_coverage,
                     source_structure, structure_catalogue, structure_windows)
from .state_v6 import apply_operations_independently, initial_state

REPAIR_EXTRA_WINDOWS = 2


def _opened_ids(windows: list[dict], window_ids: set[int]) -> set[str]:
    result: set[str] = set()
    for window in windows:
        if window["window_id"] in window_ids:
            result.update(window["source_ids"])
    return result


def _public(state: dict, stable_to_handle: dict[str, str], status: str) -> list[dict]:
    result = []
    for item in state["items"].values():
        if item["status"] != status:
            continue
        visible = {key: deepcopy(value) for key, value in item.items()
                   if key != "source_hash"}
        result.append(alias_item_sources(visible, stable_to_handle))
    return result


def _all_target_ids(state: dict) -> set[str]:
    return {item_id for item_id, item in state["items"].items()
            if item["status"] in {"active", "deferred"}}


def _snapshot_value(state: dict) -> dict:
    return {"items": deepcopy(state["items"]), "counters": deepcopy(state["counters"]),
            "history_length": len(state["history"])}


def _save_snapshot(output: Path, name: str, state: dict) -> None:
    path = output / "snapshots" / f"{name}.json"
    value = _snapshot_value(state)
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise ValueError(f"immutable_snapshot_changed:{name}")
        return
    save(path, value)


def _request_id(experiment: str, row: dict, stage: str, turn: str | int,
                payload: dict) -> tuple[str, str]:
    payload_hash = digest(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8"))
    identity = (f"{experiment}:s{SCHEMA_VERSION}:{VERSION}:{row['source_hash']}:"
                f"{stage}:{turn}:{payload_hash}")
    return f"{row['case_id']}:{stage}:{turn}:{digest(identity.encode())[:20]}", payload_hash


def _provided_handles(payload: dict) -> list[str]:
    handles = []
    for paragraph in payload.get("opened_sources", []):
        handles.append(paragraph["source_id"])
        handles.extend(sentence["source_id"] for sentence in paragraph.get("sentences", []))
    return sorted(set(handles))


def _agent_call(*, endpoint, model: str, prompt: str, payload: dict, experiment: str,
                row: dict, stage: str, turn: str | int, output: Path,
                checkpoint: dict, checkpoint_path: Path) -> object:
    key = f"{stage}:{turn}"
    journal = checkpoint.setdefault("request_journal", {})
    record = journal.get(key)
    cache_path = output / "responses" / f"{stage}_{str(turn).replace(':', '_')}.json"
    if record is None:
        request_id, payload_hash = _request_id(experiment, row, stage, turn, payload)
        record = {"stage": stage, "turn": turn, "request_id": request_id,
                  "payload_hash": payload_hash, "prompt": prompt,
                  "model": model,
                  "payload": deepcopy(payload),
                  "provided_source_handles": _provided_handles(payload),
                  "pre_request_snapshot": _snapshot_value(checkpoint["state"]),
                  "status": "request_pending"}
        journal[key] = record
        checkpoint.setdefault("request_prompt_versions", {})[key] = VERSION
        save(checkpoint_path, checkpoint)
    else:
        if record.get("model", model) != model and record.get("status") == "request_pending":
            model = record["model"]
        prompt, payload = record["prompt"], record["payload"]
        if _request_id(experiment, row, stage, turn, payload)[1] != record["payload_hash"]:
            raise ValueError("journal_payload_checksum_mismatch")
        if record["status"] in {"response_received", "applied"}:
            if record.get("response_checksum") != digest(json.dumps(
                    record["response"], ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")).encode("utf-8")):
                raise ValueError("journal_response_checksum_mismatch")
            if cache_path.exists():
                envelope = json.loads(cache_path.read_text(encoding="utf-8"))
                identity = envelope.get("identity", {})
                if (identity.get("request_id") != record["request_id"] or
                        identity.get("model") != record.get("model", model) or
                        identity.get("system_hash") != digest(prompt.encode("utf-8")) or
                        identity.get("payload_hash") != record["payload_hash"] or
                        identity.get("metadata", {}).get("source_hash") != row["source_hash"] or
                        identity.get("metadata", {}).get("case_id") != row["case_id"]):
                    raise ValueError("journal_cache_identity_mismatch")
                if _read_cache(cache_path, identity) != record["response"]:
                    raise ValueError("journal_cached_response_mismatch")
            return deepcopy(record["response"])
    metadata = record.get("metadata") or {"experiment": experiment, "schema_version": SCHEMA_VERSION,
        "prompt_version": VERSION, "source_hash": row["source_hash"],
        "payload_hash": record["payload_hash"], "prompt_hash": digest(prompt.encode("utf-8")),
        "case_id": row["case_id"], "stage": stage, "turn": turn}
    record["metadata"] = deepcopy(metadata)
    save(checkpoint_path, checkpoint)
    try:
        response = endpoint.complete(model, prompt, record["payload"],
            request_id=record["request_id"], metadata=metadata, cache_path=cache_path)
    except ModelProtocolError:
        raw_path = cache_path.with_suffix(".raw.json")
        if not raw_path.exists():
            raise
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        response = {"__raw_invalid_json__": raw.get("model_content", "")}
    record["response"] = deepcopy(response)
    record["response_checksum"] = digest(json.dumps(
        response, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    record["status"] = "response_received"
    save(checkpoint_path, checkpoint)
    return response


def _default_control(phase: str) -> dict:
    if phase == "reader":
        return {"action": "finalize", "reason": "protocol error", "read_window_ids": [],
                "open_questions": []}
    if phase in {"selection_repair", "classification_repair"}:
        return {"action": "complete", "reason": "protocol error", "read_window_ids": [],
                "open_questions": []}
    return {"reason": "protocol error", "open_questions": []}


def _validate_control(response: object, phase: str, *, unread: set[int],
                      continuation: bool) -> tuple[dict, list[dict], list]:
    default = _default_control(phase)
    errors, control = [], {}
    if not isinstance(response, dict):
        return default, [{"path": "$", "error_code": "response_must_be_object"}], []
    expected = ({"operations", "open_questions", "reason"} if phase == "finalizer" else
                {"action", "reason", "read_window_ids", "operations", "open_questions"})
    for field in sorted(set(response) - expected):
        errors.append({"path": field, "error_code": "unexpected_response_field"})
    operations = response.get("operations")
    if not isinstance(operations, list):
        errors.append({"path": "operations", "error_code": "operations_must_be_list"})
        operations = []
    questions = response.get("open_questions")
    if not isinstance(questions, list) or any(not isinstance(value, str) for value in questions):
        errors.append({"path": "open_questions", "error_code": "invalid_open_questions"})
        questions = []
    control["open_questions"] = deepcopy(questions)
    reason = response.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append({"path": "reason", "error_code": "reason_required"})
        reason = default["reason"]
    control["reason"] = reason
    if phase == "finalizer":
        return control, errors, operations
    allowed_actions = {"read", "finalize"} if phase == "reader" else {"read", "complete"}
    action = response.get("action")
    if action not in allowed_actions:
        errors.append({"path": "action", "error_code": "invalid_action"})
        action = default["action"]
    control["action"] = action
    requested = response.get("read_window_ids")
    if (not isinstance(requested, list) or len(requested) > REPAIR_EXTRA_WINDOWS or
            any(type(value) is not int for value in requested) or
            len(requested) != len(set(requested))):
        errors.append({"path": "read_window_ids", "error_code": "invalid_window_requests"})
        requested = []
    if action != "read" and requested:
        errors.append({"path": "read_window_ids", "error_code": "non_read_action_has_windows"})
        requested = []
    if action == "read" and (not requested or not set(requested).issubset(unread)):
        errors.append({"path": "read_window_ids", "error_code": "requested_window_not_unread"})
        requested = []
    if continuation and (action == "read" or requested):
        errors.append({"path": "read_window_ids", "error_code": "continuation_cannot_read"})
        requested = []
        control["action"] = "complete"
    control["read_window_ids"] = requested
    return control, errors, operations


def _repair_target_matches(original: object, repaired: object) -> bool:
    if not isinstance(original, dict) or not isinstance(repaired, dict):
        return False
    if original.get("op") != repaired.get("op"):
        return False
    if repaired.get("op") == "add":
        return original.get("collection") == repaired.get("collection")
    # Revision is precisely what a rejected operation may need to correct.
    # apply_operations_independently still checks the request snapshot and
    # current host revision, so a repair cannot redirect to another item.
    return original.get("id") == repaired.get("id")


def _process_response(*, response: object, phase: str, turn: int, continuation: bool,
                      checkpoint: dict, checkpoint_path: Path, opened: set[str],
                      unread_windows: set[int], source_map: dict[str, dict],
                      stable_to_handle: dict[str, str], alias_to_stable: dict[str, str],
                      row: dict, endpoint, model: str, experiment: str,
                      output: Path) -> tuple[dict, list[dict], list[dict]]:
    key = f"{phase}:{turn}"
    completed = checkpoint.setdefault("processed_responses", {}).get(key)
    if completed:
        return (deepcopy(completed["control"]), deepcopy(completed["applied"]),
                deepcopy(completed["rejections"]))
    pending = checkpoint.setdefault("response_processing", {}).get(key)
    if pending is None:
        control, control_errors, operations = _validate_control(
            response, phase, unread=unread_windows, continuation=continuation)
        snapshot_ids = _all_target_ids(checkpoint["state"])
        working, applied, rejected, noops = apply_operations_independently(
            checkpoint["state"], operations, opened, source_map, row["source_hash"],
            row["case_id"], aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids=snapshot_ids)
        checkpoint["state"] = working
        for noop in noops:
            noop.update({"stage": phase, "turn": turn,
                         "response_path": f"responses/{phase}_{turn}.json"})
        checkpoint.setdefault("noop_operations", []).extend(noops)
        rejection_records = []
        for rejected_entry in rejected:
            record = {"rejection_id": f"{row['case_id']}:{phase}:{turn}:op:{rejected_entry['index']}",
                "stage": phase, "turn": turn, "operation_index": rejected_entry["index"],
                "error_path": f"operations[{rejected_entry['index']}]",
                "error_code": rejected_entry["error_code"],
                "original_operation": rejected_entry["operation"],
                "response_path": f"responses/{phase}_{turn}.json",
                "status": "unresolved"}
            checkpoint["operation_rejections"].append(record)
            rejection_records.append(record)
        control_records = []
        for index, error in enumerate(control_errors):
            record = {"error_id": f"{row['case_id']}:{phase}:{turn}:control:{index}",
                      "stage": phase, "turn": turn, **error, "status": "unresolved"}
            checkpoint["protocol_errors"].append(record)
            control_records.append(record)
        pending = {"response": deepcopy(response), "control": deepcopy(control),
                   "snapshot_ids": sorted(snapshot_ids), "applied": deepcopy(applied),
                   "noops": deepcopy(noops),
                   "rejection_ids": [record["rejection_id"] for record in rejection_records],
                   "control_error_ids": [record["error_id"] for record in control_records]}
        checkpoint["response_processing"][key] = pending
        save(checkpoint_path, checkpoint)
    else:
        control = deepcopy(pending["control"])
        applied = deepcopy(pending["applied"])
        noops = deepcopy(pending.get("noops", []))
        rejection_records = [record for record in checkpoint["operation_rejections"]
            if record["rejection_id"] in set(pending["rejection_ids"])]
        control_records = [record for record in checkpoint["protocol_errors"]
            if record["error_id"] in set(pending["control_error_ids"])]
    if rejection_records or control_records:
        repair_payload = {"phase": phase, "invalid_response": pending["response"],
            "expected_response": ({"operations": [], "open_questions": [],
                                   "reason": "non-empty process note"}
                                  if phase == "finalizer" else
                                  {"action": "read|finalize" if phase == "reader" else "read|complete",
                                   "reason": "non-empty process note", "read_window_ids": [],
                                   "operations": [], "open_questions": []}),
            "control_errors": control_records,
            "allowed_control_patch_fields": sorted(
                {record["path"] for record in control_records if record["path"] != "$"}
                | ({"action"} if any(record["path"] == "read_window_ids" and
                    control.get("action") == "read" for record in control_records) else set())),
            "rejected_operations": rejection_records,
            "valid_rejection_ids": [record["rejection_id"] for record in rejection_records],
            "valid_operations_already_applied": [event["operation"] for event in applied],
            "current_items": _public(checkpoint["state"], stable_to_handle, "active"),
            "unresolved_items": _public(checkpoint["state"], stable_to_handle, "deferred"),
            "opened_sources": opened_sources(source_map, opened, stable_to_handle)}
        repair = _agent_call(endpoint=endpoint, model=model, prompt=PROTOCOL_REPAIR,
            payload=repair_payload, experiment=experiment, row=row,
            stage=f"{phase}_protocol_repair", turn=turn, output=output,
            checkpoint=checkpoint, checkpoint_path=checkpoint_path)
        repair_log = {"stage": phase, "turn": turn, "status": "completed", "errors": []}
        if (not isinstance(repair, dict) or set(repair) != {"control_patch", "repairs"} or
                not isinstance(repair.get("control_patch"), dict) or
                not isinstance(repair.get("repairs"), list)):
            repair_log.update({"status": "failed", "error_code": "invalid_protocol_repair"})
        else:
            allowed_fields = set(repair_payload["allowed_control_patch_fields"])
            invalid_fields = set(repair["control_patch"]) - allowed_fields
            for field in sorted(invalid_fields):
                repair_log["errors"].append({"path": f"control_patch.{field}",
                                             "error_code": "changed_valid_control"})
            candidate = {"operations": [], **deepcopy(control),
                         **{field: deepcopy(value) for field, value in
                            repair["control_patch"].items() if field in allowed_fields}}
            candidate_control, candidate_errors, _ = _validate_control(
                candidate, phase, unread=unread_windows, continuation=continuation)
            if candidate_control.get("read_window_ids"):
                candidate_errors.append({"path": "read_window_ids",
                                         "error_code": "protocol_repair_cannot_open_source"})
            if candidate_errors:
                repair_log["errors"].extend(candidate_errors)
            elif not invalid_fields:
                control = candidate_control
                for record in control_records:
                    record.update({"status": "resolved",
                                   "resolved_by": f"{phase}_protocol_repair"})
            by_id = {record["rejection_id"]: record for record in rejection_records}
            seen = set()
            for entry in repair["repairs"]:
                if (not isinstance(entry, dict) or set(entry) != {"rejection_id", "operation"}
                        or entry.get("rejection_id") not in by_id
                        or entry.get("rejection_id") in seen):
                    repair_log["errors"].append({"path": "repairs",
                                                 "error_code": "invalid_repair_entry"})
                    continue
                seen.add(entry["rejection_id"])
                record = by_id[entry["rejection_id"]]
                if not _repair_target_matches(record["original_operation"], entry["operation"]):
                    record["repair_error_code"] = "repair_target_mismatch"
                    continue
                working, events, rejected, repair_noops = apply_operations_independently(
                    checkpoint["state"], [entry["operation"]], opened, source_map,
                    row["source_hash"], row["case_id"], aliases=alias_to_stable,
                    stable_to_handle=stable_to_handle,
                    allowed_target_ids=set(pending["snapshot_ids"]))
                if rejected:
                    record["repair_error_code"] = rejected[0]["error_code"]
                elif repair_noops:
                    noop = repair_noops[0]
                    noop.update({"stage": phase, "turn": turn,
                        "operation_index": record["operation_index"],
                        "response_path": record["response_path"],
                        "repair_response_path": f"responses/{phase}_protocol_repair_{turn}.json",
                        "rejection_id": record["rejection_id"]})
                    checkpoint.setdefault("noop_operations", []).append(noop)
                    noops.append(noop)
                    record.update({"status": "resolved_noop_duplicate",
                        "duplicate_of": noop["duplicate_of"],
                        "duplicate_revision": noop["duplicate_revision"],
                        "resolved_by": f"{phase}_protocol_repair",
                        "repair_operation": deepcopy(entry["operation"])})
                else:
                    checkpoint["state"] = working
                    applied.extend(events)
                    record.update({"status": "resolved",
                                   "resolved_by": f"{phase}_protocol_repair",
                                   "repair_operation": deepcopy(entry["operation"])})
        repair_journal = checkpoint["request_journal"].get(
            f"{phase}_protocol_repair:{turn}")
        if repair_journal:
            repair_journal["status"] = "applied"
            repair_journal["post_request_snapshot"] = _snapshot_value(checkpoint["state"])
        checkpoint["protocol_repairs"].append(repair_log)
    checkpoint["processed_responses"][key] = {
        "control": deepcopy(control), "applied": deepcopy(applied),
        "noops": deepcopy(noops),
        "rejections": deepcopy(rejection_records)}
    checkpoint["response_processing"].pop(key, None)
    request_record = checkpoint["request_journal"].get(key)
    if request_record:
        request_record["status"] = "applied"
        request_record["applied_operation_ids"] = [event["id"] for event in applied]
        request_record["post_request_snapshot"] = _snapshot_value(checkpoint["state"])
    save(checkpoint_path, checkpoint)
    return control, applied, rejection_records


def _has_unresolved_protocol(checkpoint: dict) -> bool:
    return any(record["status"] == "unresolved" for key in
               ("operation_rejections", "protocol_errors")
               for record in checkpoint.get(key, []))


def _context_ids(state: dict, paragraphs: list[dict], source_map: dict[str, dict]) -> set[str]:
    paragraph_index = {paragraph["source_id"]: index for index, paragraph in enumerate(paragraphs)}
    selected_paragraphs = set()
    for item in state["items"].values():
        if item["status"] == "deleted":
            continue
        for ref in item["source_refs"]:
            unit = source_map[ref["source_id"]]
            selected_paragraphs.add(unit.get("parent_id") or unit["source_id"])
    result = set()
    for paragraph_id in selected_paragraphs:
        index = paragraph_index[paragraph_id]
        for neighbour in paragraphs[max(0, index - 1):min(len(paragraphs), index + 2)]:
            result.add(neighbour["source_id"])
            result.update(neighbour["sentence_ids"])
    return result


def _label_matrix(state: dict, stable_to_handle: dict[str, str]) -> list[dict]:
    rows = []
    for item in state["items"].values():
        if item["status"] == "deleted":
            continue
        for ref in item["source_refs"]:
            rows.append({"source_id": stable_to_handle[ref["source_id"]],
                         "item_id": item["id"], "item_status": item["status"],
                         "collection": item["collection"], "role": ref["role"],
                         "attribution": ref["attribution"],
                         "kind": item.get("kind"),
                         "treatment": item.get("treatment", {}).get("value")})
    return rows


def _base_payload(checkpoint: dict, row: dict, catalogue: dict,
                  source_map: dict[str, dict], stable_to_handle: dict[str, str],
                  windows: list[dict]) -> dict:
    opened = set(checkpoint["opened_source_ids"])
    opened_windows = set(checkpoint["opened_window_ids"])
    return {"catalogue": catalogue,
        "source_handle_scope": {"case_id": row["case_id"], "source_hash": row["source_hash"]},
        "opened_sources": opened_sources(source_map, opened, stable_to_handle),
        "opened_window_ids": sorted(opened_windows),
        "unread_window_ids": [window["window_id"] for window in windows
                              if window["window_id"] not in opened_windows],
        "current_items": _public(checkpoint["state"], stable_to_handle, "active"),
        "unresolved_items": _public(checkpoint["state"], stable_to_handle, "deferred"),
        "open_questions": checkpoint["open_questions"]}


def _materialized(item: dict, source_map: dict[str, dict], source_hash: str) -> dict:
    rendered = deepcopy(item)
    rendered["excerpts"] = materialize_sources(item["source_refs"], source_map, source_hash)
    return rendered


def _result(row: dict, text: str, units: list[dict], checkpoint: dict,
            execution_status: str, stop_reason: str) -> dict:
    source_map = {unit["source_id"]: unit for unit in units}
    active = [_materialized(item, source_map, row["source_hash"])
              for item in checkpoint["state"]["items"].values() if item["status"] == "active"]
    deferred = [_materialized(item, source_map, row["source_hash"])
                for item in checkpoint["state"]["items"].values() if item["status"] == "deferred"]
    deleted = [_materialized(item, source_map, row["source_hash"])
               for item in checkpoint["state"]["items"].values() if item["status"] == "deleted"]
    unresolved_protocol = _has_unresolved_protocol(checkpoint)
    protocol_status = "failure" if unresolved_protocol else "valid"
    if active:
        output_status = "nonempty"
    elif deferred:
        output_status = "unresolved_only"
    elif deleted or any(event["op"] == "add" for event in checkpoint["state"]["history"]):
        output_status = "all_items_removed"
    else:
        output_status = "empty_output"
    stable_to_handle, alias_to_stable = source_handles(units)
    del stable_to_handle
    phase_coverage = {phase: source_interval_coverage(
        units, set(source_ids), len(text), phase)
        for phase, source_ids in checkpoint.get("phase_source_ids", {}).items()}
    return {"schema_version": SCHEMA_VERSION,
        "representation": "extractive_paragraph_sentence_references",
        "workflow": "draft_then_two_repairs_then_finalize",
        "case_id": row["case_id"], "source": row["source"],
        "source_hash": row["source_hash"], "prompt_version": VERSION,
        "source_handle_manifest": {"source_hash": row["source_hash"],
                                   "handles": alias_to_stable},
        "execution_status": execution_status, "protocol_status": protocol_status,
        "output_status": output_status, "quality_status": "not_evaluated",
        "stop_reason": stop_reason,
        "brief": [item for item in active if item["collection"] == "brief"],
        "aus": [item for item in active if item["collection"] == "aus"],
        "unresolved_items": deferred, "deleted_items": deleted,
        "final_au_ids": [item["id"] for item in active if item["collection"] == "aus"],
        "history": checkpoint["state"]["history"],
        "open_questions": checkpoint["open_questions"],
        "operation_rejections": checkpoint["operation_rejections"],
        "noop_operations": checkpoint.get("noop_operations", []),
        "protocol_errors": checkpoint["protocol_errors"],
        "protocol_repairs": checkpoint["protocol_repairs"],
        "source_coverage": source_interval_coverage(
            units, set(checkpoint["opened_source_ids"]), len(text), "all_agent_phases"),
        "coverage_by_phase": phase_coverage,
        "snapshots": checkpoint.get("snapshots", []),
        "inherited_from": checkpoint.get("inherited_from"),
        "request_prompt_versions": checkpoint.get("request_prompt_versions", {}),
        "counts": {"brief": sum(item["collection"] == "brief" for item in active),
                   "aus": sum(item["collection"] == "aus" for item in active),
                   "unresolved": len(deferred), "deleted": len(deleted),
                   "technically_valid": len(active),
                   "noop_duplicates": len(checkpoint.get("noop_operations", [])),
                   "protocol_rejected_total": len(checkpoint["operation_rejections"]),
                   "protocol_rejected_unresolved": sum(record["status"] == "unresolved"
                       for record in checkpoint["operation_rejections"]),
                   "protocol_errors_unresolved": sum(record["status"] == "unresolved"
                       for record in checkpoint["protocol_errors"]),
                   "requests": len(checkpoint.get("request_journal", {}))}}


def build_case(row: dict, endpoint, config: dict, size: int, steps: int,
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
    catalogue = structure_catalogue(units, windows)
    experiment_root = output.parents[1]
    config_path = experiment_root / "config.json"
    experiment = experiment_root.name
    if config_path.exists():
        experiment += ":" + digest(config_path.read_bytes())[:12]
    checkpoint_path = output / "checkpoint.json"
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (checkpoint.get("schema_version") != SCHEMA_VERSION or
                checkpoint.get("source_hash") != source_hash or
                checkpoint.get("prompt_version") != VERSION):
            raise ValueError("checkpoint_identity_mismatch")
    else:
        initial_windows = {0, len(windows) - 1}
        opened = _opened_ids(windows, initial_windows)
        checkpoint = {"schema_version": SCHEMA_VERSION, "prompt_version": VERSION,
            "source_hash": source_hash, "stage": "reading", "state": initial_state(),
            "opened_window_ids": sorted(initial_windows),
            "opened_source_ids": sorted(opened),
            "phase_source_ids": {"reading": sorted(opened)},
            "open_questions": [], "trace": [], "next_reader_turn": 0,
            "read_expansions": 0, "stagnation": 0,
            "operation_rejections": [], "protocol_errors": [], "protocol_repairs": [],
            "noop_operations": [],
            "request_journal": {}, "response_processing": {}, "processed_responses": {},
            "repair_turn": 0, "snapshots": []}
        save(checkpoint_path, checkpoint)
    try:
        decision_limit = steps + 2
        while checkpoint["stage"] == "reading" and checkpoint["next_reader_turn"] < decision_limit:
            turn = checkpoint["next_reader_turn"]
            payload = _base_payload(checkpoint, row, catalogue, source_map,
                                    stable_to_handle, windows)
            payload["remaining_read_actions"] = max(0, steps - checkpoint["read_expansions"])
            response = _agent_call(endpoint=endpoint, model=config["reader"], prompt=READER,
                payload=payload, experiment=experiment, row=row, stage="reader", turn=turn,
                output=output, checkpoint=checkpoint, checkpoint_path=checkpoint_path)
            opened_windows = set(checkpoint["opened_window_ids"])
            unread = {window["window_id"] for window in windows} - opened_windows
            control, applied, rejected = _process_response(
                response=response, phase="reader", turn=turn, continuation=False,
                checkpoint=checkpoint, checkpoint_path=checkpoint_path,
                opened=set(checkpoint["opened_source_ids"]), unread_windows=unread,
                source_map=source_map, stable_to_handle=stable_to_handle,
                alias_to_stable=alias_to_stable, row=row, endpoint=endpoint,
                model=config["reader"], experiment=experiment, output=output)
            requested = control["read_window_ids"]
            if requested and checkpoint["read_expansions"] >= steps:
                raise ValueError("reader_exceeded_read_budget")
            new_windows = [value for value in requested if value not in opened_windows]
            opened_windows.update(new_windows)
            newly_opened = _opened_ids(windows, set(new_windows))
            checkpoint["opened_window_ids"] = sorted(opened_windows)
            checkpoint["opened_source_ids"] = sorted(
                set(checkpoint["opened_source_ids"]) | newly_opened)
            checkpoint["phase_source_ids"]["reading"] = sorted(
                set(checkpoint["phase_source_ids"]["reading"]) | newly_opened)
            checkpoint["open_questions"] = control["open_questions"]
            checkpoint["read_expansions"] += bool(new_windows)
            progress = bool(applied or new_windows)
            checkpoint["stagnation"] = 0 if progress else checkpoint["stagnation"] + 1
            checkpoint["trace"].append({"stage": "reader", "turn": turn,
                "action": control["action"], "reason": control["reason"],
                "requested": requested, "new_windows": new_windows,
                "applied": applied, "noops": deepcopy(checkpoint["processed_responses"][f"reader:{turn}"].get("noops", [])),
                "rejected": [value["rejection_id"] for value in rejected]})
            checkpoint["next_reader_turn"] += 1
            just_opened = bool(new_windows)
            no_unread = len(opened_windows) == len(windows)
            if _has_unresolved_protocol(checkpoint):
                checkpoint["stage"] = "incomplete_protocol"
            elif not just_opened and (control["action"] == "finalize" or no_unread or
                    checkpoint["stagnation"] >= 2 or
                    checkpoint["read_expansions"] >= steps or
                    checkpoint["next_reader_turn"] >= decision_limit):
                checkpoint["stage"] = "repair_selection"
            save(checkpoint_path, checkpoint)
        if checkpoint["stage"] == "reading":
            checkpoint["stage"] = "repair_selection"
            save(checkpoint_path, checkpoint)

        if checkpoint["stage"] == "repair_selection" and "draft_after_reading" not in checkpoint["snapshots"]:
            _save_snapshot(output, "draft_after_reading", checkpoint["state"])
            checkpoint["snapshots"].append("draft_after_reading")
            context = _context_ids(checkpoint["state"], paragraphs, source_map)
            checkpoint["opened_source_ids"] = sorted(set(checkpoint["opened_source_ids"]) | context)
            checkpoint["phase_source_ids"]["selection_repair"] = sorted(
                checkpoint["opened_source_ids"])
            save(checkpoint_path, checkpoint)

        for stage, prompt, snapshot_name, next_stage in (
                ("repair_selection", SELECTION_REPAIR, "after_selection_repair", "repair_classification"),
                ("repair_classification", CLASSIFICATION_REPAIR,
                 "after_classification_repair", "finalizing")):
            while checkpoint["stage"] == stage:
                turn = checkpoint.get("repair_turn", 0)
                context = _context_ids(checkpoint["state"], paragraphs, source_map)
                checkpoint["opened_source_ids"] = sorted(set(checkpoint["opened_source_ids"]) | context)
                phase_name = "selection_repair" if stage == "repair_selection" else "classification_repair"
                checkpoint["phase_source_ids"][phase_name] = sorted(
                    set(checkpoint["opened_source_ids"]) | context)
                payload = _base_payload(checkpoint, row, catalogue, source_map,
                                        stable_to_handle, windows)
                payload["continuation"] = turn == 1
                if stage == "repair_classification":
                    payload["source_label_matrix"] = _label_matrix(
                        checkpoint["state"], stable_to_handle)
                response = _agent_call(endpoint=endpoint, model=config["repair"], prompt=prompt,
                    payload=payload, experiment=experiment, row=row, stage=phase_name, turn=turn,
                    output=output, checkpoint=checkpoint, checkpoint_path=checkpoint_path)
                opened_windows = set(checkpoint["opened_window_ids"])
                unread = {window["window_id"] for window in windows} - opened_windows
                control, applied, rejected = _process_response(
                    response=response, phase=stage.removeprefix("repair_") + "_repair",
                    turn=turn, continuation=turn == 1, checkpoint=checkpoint,
                    checkpoint_path=checkpoint_path, opened=set(checkpoint["opened_source_ids"]),
                    unread_windows=unread, source_map=source_map,
                    stable_to_handle=stable_to_handle, alias_to_stable=alias_to_stable,
                    row=row, endpoint=endpoint, model=config["repair"],
                    experiment=experiment, output=output)
                requested = control["read_window_ids"]
                new_windows = [value for value in requested if value not in opened_windows]
                opened_windows.update(new_windows)
                newly_opened = _opened_ids(windows, set(new_windows))
                checkpoint["opened_window_ids"] = sorted(opened_windows)
                checkpoint["opened_source_ids"] = sorted(
                    set(checkpoint["opened_source_ids"]) | newly_opened)
                checkpoint["phase_source_ids"][phase_name] = sorted(
                    set(checkpoint["phase_source_ids"][phase_name]) | newly_opened)
                checkpoint["open_questions"] = control["open_questions"]
                checkpoint["trace"].append({"stage": stage, "turn": turn,
                    "action": control["action"], "reason": control["reason"],
                    "requested": requested, "new_windows": new_windows,
                    "applied": applied, "noops": deepcopy(checkpoint["processed_responses"][f"{phase_name}:{turn}"].get("noops", [])),
                    "rejected": [value["rejection_id"] for value in rejected]})
                if _has_unresolved_protocol(checkpoint):
                    checkpoint["stage"] = "incomplete_protocol"
                elif turn == 0 and new_windows:
                    checkpoint["repair_turn"] = 1
                else:
                    _save_snapshot(output, snapshot_name, checkpoint["state"])
                    checkpoint["snapshots"].append(snapshot_name)
                    checkpoint["stage"] = next_stage
                    checkpoint["repair_turn"] = 0
                    if next_stage == "repair_classification":
                        next_context = _context_ids(checkpoint["state"], paragraphs, source_map)
                        checkpoint["opened_source_ids"] = sorted(
                            set(checkpoint["opened_source_ids"]) | next_context)
                        checkpoint["phase_source_ids"]["classification_repair"] = sorted(
                            set(checkpoint["opened_source_ids"]) | next_context)
                save(checkpoint_path, checkpoint)

        if checkpoint["stage"] == "finalizing":
            checkpoint["phase_source_ids"]["finalizer"] = sorted(
                checkpoint["opened_source_ids"])
            payload = _base_payload(checkpoint, row, catalogue, source_map,
                                    stable_to_handle, windows)
            response = _agent_call(endpoint=endpoint, model=config["repair"], prompt=FINALIZER,
                payload=payload, experiment=experiment, row=row, stage="finalizer", turn=0,
                output=output, checkpoint=checkpoint, checkpoint_path=checkpoint_path)
            unread = {window["window_id"] for window in windows} - set(checkpoint["opened_window_ids"])
            control, applied, rejected = _process_response(
                response=response, phase="finalizer", turn=0, continuation=True,
                checkpoint=checkpoint, checkpoint_path=checkpoint_path,
                opened=set(checkpoint["opened_source_ids"]), unread_windows=unread,
                source_map=source_map, stable_to_handle=stable_to_handle,
                alias_to_stable=alias_to_stable, row=row, endpoint=endpoint,
                model=config["repair"], experiment=experiment, output=output)
            checkpoint["open_questions"] = control["open_questions"]
            checkpoint["trace"].append({"stage": "finalizer", "turn": 0,
                "reason": control["reason"], "applied": applied,
                "noops": deepcopy(checkpoint["processed_responses"]["finalizer:0"].get("noops", [])),
                "rejected": [value["rejection_id"] for value in rejected]})
            if _has_unresolved_protocol(checkpoint):
                checkpoint["stage"] = "incomplete_protocol"
            else:
                _save_snapshot(output, "final", checkpoint["state"])
                checkpoint["snapshots"].append("final")
                checkpoint["stage"] = "complete"
            save(checkpoint_path, checkpoint)

        if checkpoint["stage"] == "complete":
            result = _result(row, text, units, checkpoint, "completed", "finalization_complete")
        else:
            result = _result(row, text, units, checkpoint, "incomplete",
                             "unresolved_protocol_error")
    except BudgetStop:
        result = _result(row, text, units, checkpoint, "incomplete_budget",
                         "shared_budget_exhausted")
    save(output / "trace.json", checkpoint["trace"])
    save(output / "case.json", result)
    return result

