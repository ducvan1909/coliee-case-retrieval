"""V9 extractive KB pipeline with explicit control repair and final-only outputs."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from .endpoint import BudgetStop, ModelProtocolError, _cache_identity, _read_cache
from .prompts_v9 import (ATTRIBUTION_REPAIR, TREATMENT_REPAIR, FINALIZER,
                         FULL_RESPONSE_REPAIR, READER, SELECTION_REPAIR, VERSION,
                         protocol_repair_prompt)
from .schema_v9 import (PROTOCOL_REPAIR_SCHEMA, SCHEMA_VERSION,
                        validate_protocol_repair_response)
from .source import (alias_item_sources, digest, load_source, materialize_sources,
                     opened_sources, save, source_handles, source_interval_coverage,
                     source_structure, structure_catalogue, structure_windows)
from .state_v9 import (apply_operations_independently, independent_field_errors,
                       initial_state)

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


def _validate_control(response: object, phase: str, *, unread: set[int],
                      continuation: bool, require_read: bool = False) -> tuple[dict, list[dict], list]:
    errors, control = [], {}
    if not isinstance(response, dict):
        return {}, [{"path": "$", "error_code": "response_must_be_object"}], []
    expected = ({"operations", "open_questions", "reason", "item_checks"}
                if phase == "finalizer" else
                {"action", "reason", "read_window_ids", "operations", "open_questions"}
                | ({"item_checks"} if phase != "reader" else set()))
    for field in sorted(set(response) - expected):
        errors.append({"path": field, "error_code": "unexpected_response_field"})
    operations = response.get("operations")
    if not isinstance(operations, list):
        errors.append({"path": "operations", "error_code": "operations_must_be_list"})
        operations = []
    questions = response.get("open_questions")
    if not isinstance(questions, list) or any(not isinstance(value, str) for value in questions):
        errors.append({"path": "open_questions", "error_code": "invalid_open_questions"})
    else:
        control["open_questions"] = deepcopy(questions)
    reason = response.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append({"path": "reason", "error_code": "reason_required"})
    else:
        control["reason"] = reason
    if phase != "reader":
        checks = response.get("item_checks")
        if not isinstance(checks, list):
            errors.append({"path": "item_checks", "error_code": "item_checks_must_be_list"})
        else:
            control["item_checks"] = deepcopy(checks)
    if phase == "finalizer":
        return control, errors, operations
    allowed_actions = {"read", "finalize"} if phase == "reader" else {"read", "complete"}
    action = response.get("action")
    if not isinstance(action, str) or action not in allowed_actions:
        errors.append({"path": "action", "error_code": "invalid_action"})
    else:
        control["action"] = action
    requested = response.get("read_window_ids")
    if (not isinstance(requested, list) or len(requested) > REPAIR_EXTRA_WINDOWS or
            any(type(value) is not int for value in requested) or
            len(requested) != len(set(requested))):
        errors.append({"path": "read_window_ids", "error_code": "invalid_window_requests"})
    else:
        control["read_window_ids"] = deepcopy(requested)
    if action != "read" and isinstance(requested, list) and requested:
        errors.append({"path": "read_window_ids", "error_code": "non_read_action_has_windows"})
    if action == "read" and isinstance(requested, list) and (
            not requested or any(type(value) is not int for value in requested) or
            not set(requested).issubset(unread)):
        errors.append({"path": "read_window_ids", "error_code": "requested_window_not_unread"})
    if continuation and (action == "read" or requested):
        errors.append({"path": "read_window_ids", "error_code": "continuation_cannot_read"})
    if require_read and (action != "read" or not isinstance(requested, list) or
                         not requested):
        errors.append({"path": "read_window_ids", "error_code": "selection_read_required"})
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


def _check_item_checks(response: object, phase: str, state: dict,
                       operations: list, opened_handles: set[str]) -> list[dict]:
    if phase == "reader" or not isinstance(response, dict):
        return []
    checks = response.get("item_checks")
    if not isinstance(checks, list):
        return []  # _validate_control reports this field.
    targets = {item_id: item for item_id, item in state["items"].items()
               if item["status"] == "active" or
               (phase != "finalizer" and item["status"] == "deferred")}
    seen, errors = set(), []
    for index, check in enumerate(checks):
        path = f"item_checks[{index}]"
        if (not isinstance(check, dict) or set(check) != {
                "id", "revision", "decision", "reason", "source_ids"}):
            errors.append({"path": path, "error_code": "invalid_item_check"})
            continue
        item_id = check["id"]
        sources = check["source_ids"]
        if (not isinstance(item_id, str) or item_id not in targets or item_id in seen or
                check["revision"] != targets[item_id]["revision"] or
                not isinstance(check["decision"], str) or
                check["decision"] not in {"keep", "update", "defer", "remove", "restore"} or
                not isinstance(check["reason"], str) or not check["reason"].strip() or
                not isinstance(sources, list) or
                any(not isinstance(value, str) or value not in opened_handles
                    for value in sources) or len(sources) != len(set(sources))):
            errors.append({"path": path, "error_code": "invalid_item_check"})
            continue
        seen.add(item_id)
        matching = [op for op in operations if isinstance(op, dict) and
                    op.get("id") == item_id and op.get("op") in {
                        "update", "defer", "remove", "restore"}]
        if ((check["decision"] == "keep" and matching) or
                (check["decision"] != "keep" and
                 (len(matching) != 1 or matching[0].get("op") != check["decision"]))):
            errors.append({"path": path, "error_code": "item_check_operation_mismatch"})
    if seen != set(targets):
        errors.append({"path": "item_checks", "error_code": "item_checks_incomplete"})
    return errors


def _process_response(*, response: object, phase: str, turn: int, continuation: bool,
                      checkpoint: dict, checkpoint_path: Path, opened: set[str],
                      unread_windows: set[int], source_map: dict[str, dict],
                      stable_to_handle: dict[str, str], alias_to_stable: dict[str, str],
                      row: dict, endpoint, model: str, experiment: str,
                      output: Path) -> tuple[dict, list[dict], list[dict]]:
    key = f"{phase}:{turn}"
    validation_unread = (set() if phase == "reader" and
        checkpoint.get("read_expansions", 0) >= checkpoint.get(
            "max_read_expansions", 0) else unread_windows)
    require_read = phase == "selection_repair" and turn == 0 and bool(unread_windows)
    completed = checkpoint.setdefault("processed_responses", {}).get(key)
    if completed:
        return (deepcopy(completed["control"]), deepcopy(completed["applied"]),
                deepcopy(completed["rejections"]))
    full_replacement = (not isinstance(response, dict) or
        "__raw_invalid_json__" in response or
        not isinstance(response.get("operations"), list) or
        bool(set(response) - ({"operations", "open_questions", "reason", "item_checks"}
            if phase == "finalizer" else
            {"action", "reason", "read_window_ids", "operations", "open_questions"}
            | ({"item_checks"} if phase != "reader" else set()))))
    if full_replacement:
        repair_payload = {"mode": "replace_entire_response", "phase": phase,
            "invalid_response": response,
            "current_items": _public(checkpoint["state"], stable_to_handle, "active"),
            "unresolved_items": _public(checkpoint["state"], stable_to_handle, "deferred"),
            "opened_sources": opened_sources(source_map, opened, stable_to_handle),
            "unread_window_ids": sorted(unread_windows),
            "continuation": continuation,
            "expected_fields": (["operations", "open_questions", "reason", "item_checks"]
                if phase == "finalizer" else
                ["action", "reason", "read_window_ids", "operations", "open_questions"] +
                ([] if phase == "reader" else ["item_checks"]))}
        response = _agent_call(endpoint=endpoint, model=model,
            prompt=FULL_RESPONSE_REPAIR, payload=repair_payload,
            experiment=experiment, row=row, stage=f"{phase}_protocol_repair",
            turn=turn, output=output, checkpoint=checkpoint,
            checkpoint_path=checkpoint_path)
        replacement_control, replacement_errors, replacement_ops = _validate_control(
            response, phase, unread=validation_unread, continuation=continuation,
            require_read=require_read)
        replacement_errors += _check_item_checks(response, phase, checkpoint["state"],
            replacement_ops, set(stable_to_handle[value] for value in opened))
        if replacement_errors:
            for index, error in enumerate(replacement_errors):
                checkpoint["protocol_errors"].append({"error_id":
                    f"{row['case_id']}:{phase}:{turn}:replacement:{index}",
                    "stage": phase, "turn": turn, **error, "status": "unresolved"})
            checkpoint["protocol_repairs"].append({"stage": phase, "turn": turn,
                "mode": "replace_entire_response", "status": "failed",
                "errors": replacement_errors})
            checkpoint["processed_responses"][key] = {"control": {},
                "applied": [], "noops": [], "rejections": []}
            save(checkpoint_path, checkpoint)
            return {}, [], []
        if key not in checkpoint.get("full_replacements", []):
            checkpoint["protocol_errors"].append({"error_id":
                f"{row['case_id']}:{phase}:{turn}:original_response",
                "stage": phase, "turn": turn, "path": "$",
                "error_code": "malformed_response_replaced", "status": "resolved",
                "resolved_by": f"{phase}_protocol_repair"})
            checkpoint["protocol_repairs"].append({"stage": phase, "turn": turn,
                "mode": "replace_entire_response", "status": "completed", "errors": []})
        checkpoint["full_replacements"] = sorted(set(
            checkpoint.get("full_replacements", [])) | {key})
        save(checkpoint_path, checkpoint)
    pending = checkpoint.setdefault("response_processing", {}).get(key)
    if pending is None:
        control, control_errors, operations = _validate_control(
            response, phase, unread=validation_unread, continuation=continuation,
            require_read=require_read)
        control_errors += _check_item_checks(response, phase, checkpoint["state"],
            operations, {stable_to_handle[value] for value in opened})
        snapshot_ids = _all_target_ids(checkpoint["state"])
        working, applied, rejected, noops = apply_operations_independently(
            checkpoint["state"], operations, opened, source_map, row["source_hash"],
            row["case_id"], aliases=alias_to_stable,
            stable_to_handle=stable_to_handle, allowed_target_ids=snapshot_ids,
            phase=phase)
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
                "field_errors": independent_field_errors(rejected_entry["operation"]),
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
                   "pre_request_items": deepcopy(checkpoint["request_journal"][key]
                       ["pre_request_snapshot"]["items"]),
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
    if (rejection_records or control_records) and key not in checkpoint.get(
            "full_replacements", []):
        repair_payload = {"phase": phase, "invalid_response": pending["response"],
            "current_control": deepcopy(control),
            "unread_window_ids": sorted(unread_windows),
            "allowed_read_window_ids": sorted(validation_unread),
            "reading_allowed": bool(validation_unread) and not continuation,
            "remaining_read_actions": (max(0,
                checkpoint.get("max_read_expansions", 0) -
                checkpoint.get("read_expansions", 0)) if phase == "reader" else
                (0 if continuation or not validation_unread else 1)),
            "original_phase_response_contract": ({"operations": [], "open_questions": [],
                                   "reason": "non-empty process note", "item_checks": []}
                                  if phase == "finalizer" else
                                  {"action": "read|finalize" if phase == "reader" else "read|complete",
                                   "reason": "non-empty process note", "read_window_ids": [],
                                   "operations": [], "open_questions": [],
                                   **({} if phase == "reader" else {"item_checks": []})}),
            "expected_repair_response": deepcopy(PROTOCOL_REPAIR_SCHEMA),
            "control_errors": control_records,
            "allowed_control_patch_fields": sorted(
                {record["path"] for record in control_records if record["path"] != "$"}
                | ({"action"} if any(record["path"] == "read_window_ids" and
                    phase != "finalizer" for record in control_records) else set())),
            "rejected_operations": rejection_records,
            "valid_rejection_ids": [record["rejection_id"] for record in rejection_records],
            "valid_operations_already_applied": [event["operation"] for event in applied],
            "current_items": _public(checkpoint["state"], stable_to_handle, "active"),
            "unresolved_items": _public(checkpoint["state"], stable_to_handle, "deferred"),
            "opened_sources": opened_sources(source_map, opened, stable_to_handle)}
        repair_prompt = protocol_repair_prompt(phase, control_errors=control_records,
            rejected_operations=rejection_records,
            allowed_control_fields=repair_payload["allowed_control_patch_fields"])
        repair = _agent_call(endpoint=endpoint, model=model, prompt=repair_prompt,
            payload=repair_payload, experiment=experiment, row=row,
            stage=f"{phase}_protocol_repair", turn=turn, output=output,
            checkpoint=checkpoint, checkpoint_path=checkpoint_path)
        repair_log = {"stage": phase, "turn": turn, "status": "completed", "errors": []}
        repair_validation = validate_protocol_repair_response(repair)
        repair_log["errors"].extend(deepcopy(repair_validation["envelope_errors"]))
        if repair_validation["envelope_errors"]:
            repair_log.update({"status": "failed", "error_code": "invalid_protocol_repair"})
        else:
            allowed_fields = set(repair_payload["allowed_control_patch_fields"])
            invalid_fields = set(repair["control_patch"]) - allowed_fields
            for field in sorted(invalid_fields):
                repair_log["errors"].append({"path": f"control_patch.{field}",
                                             "error_code": "changed_valid_control"})
            candidate = {"operations": deepcopy(pending["response"].get("operations", [])),
                         **deepcopy(control),
                         **{field: deepcopy(value) for field, value in
                            repair["control_patch"].items() if field in allowed_fields}}
            candidate_control, candidate_errors, candidate_ops = _validate_control(
                candidate, phase, unread=validation_unread, continuation=continuation,
                require_read=require_read)
            candidate_errors += _check_item_checks(candidate, phase,
                {"items": pending["pre_request_items"]}, candidate_ops,
                {stable_to_handle[value] for value in opened})
            if candidate_errors:
                repair_log["errors"].extend(candidate_errors)
            elif not invalid_fields:
                control = candidate_control
                for record in control_records:
                    record.update({"status": "resolved",
                                   "resolved_by": f"{phase}_protocol_repair"})
            by_id = {record["rejection_id"]: record for record in rejection_records}
            seen = set()
            for entry_result in repair_validation["entries"]:
                index = entry_result["index"]
                entry = entry_result["value"]
                entry_errors = deepcopy(entry_result["errors"])
                repair_log["errors"].extend(entry_errors)
                if not isinstance(entry, dict):
                    continue
                rejection_id = entry.get("rejection_id")
                record = by_id.get(rejection_id)
                if record is None:
                    if not any(error["path"] == f"repairs[{index}].rejection_id"
                               for error in entry_errors):
                        repair_log["errors"].append({"path":
                            f"repairs[{index}].rejection_id",
                            "error_code": "invalid_rejection_id"})
                    continue
                if rejection_id in seen:
                    repair_log["errors"].append({"path":
                        f"repairs[{index}].rejection_id",
                        "error_code": "duplicate_rejection_id"})
                    record["repair_error_code"] = "invalid_replacement"
                    continue
                seen.add(rejection_id)
                if entry_errors:
                    record["repair_error_code"] = ("invalid_withdrawal" if
                        entry.get("resolution") == "withdraw" else "invalid_replacement")
                    record["repair_errors"] = entry_errors
                    continue
                if entry.get("resolution") == "withdraw":
                    handles = entry.get("source_ids")
                    reason = entry.get("reason")
                    unopened = [handle for handle in handles
                                if alias_to_stable.get(handle) not in opened]
                    if unopened:
                        record["repair_error_code"] = "invalid_withdrawal"
                        error = {"path": f"repairs[{index}].source_ids",
                                 "error_code": "source_not_supplied",
                                 "source_ids": unopened}
                        record["repair_errors"] = [error]
                        repair_log["errors"].append(error)
                        continue
                    record.update({"status": "resolved_withdrawn", "withdraw_reason": reason,
                        "withdraw_source_ids": [alias_to_stable[handle] for handle in handles],
                        "resolved_by": f"{phase}_protocol_repair",
                        "repair_response_path": f"responses/{phase}_protocol_repair_{turn}.json"})
                    continue
                if not _repair_target_matches(record["original_operation"], entry["operation"]):
                    record["repair_error_code"] = "repair_target_mismatch"
                    error = {"path": f"repairs[{index}].operation",
                             "error_code": "repair_target_mismatch"}
                    record["repair_errors"] = [error]
                    repair_log["errors"].append(error)
                    continue
                working, events, rejected, repair_noops = apply_operations_independently(
                    checkpoint["state"], [entry["operation"]], opened, source_map,
                    row["source_hash"], row["case_id"], aliases=alias_to_stable,
                    stable_to_handle=stable_to_handle,
                    allowed_target_ids=set(pending["snapshot_ids"]), phase=phase)
                if rejected:
                    record["repair_error_code"] = rejected[0]["error_code"]
                    field_errors = independent_field_errors(entry["operation"])
                    errors = ([{"path": f"repairs[{index}].operation",
                                "error_code": rejected[0]["error_code"]}] +
                              [{**error, "path": f"repairs[{index}].operation."
                                f"{error['path']}"} for error in field_errors])
                    record["repair_errors"] = errors
                    repair_log["errors"].extend(errors)
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
        if repair_log["errors"] or any(record["status"] == "unresolved"
                for record in rejection_records + control_records):
            repair_log["status"] = "failed"
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
               for record in checkpoint.get(key, [])) or any(
                   record.get("status") != "completed" or record.get("errors")
                   for record in checkpoint.get("protocol_repairs", []))


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


def output_status_for_checkpoint(checkpoint: dict, execution_status: str) -> str:
    """The item-derived status is meaningful only after a valid finalizer."""
    if (execution_status != "completed" or checkpoint.get("stage") != "complete" or
            "finalizer:0" not in checkpoint.get("processed_responses", {}) or
            _has_unresolved_protocol(checkpoint)):
        return "incomplete"
    items = checkpoint["state"]["items"].values()
    if any(item["status"] == "active" for item in items):
        return "nonempty"
    if any(item["status"] == "deferred" for item in items):
        return "unresolved_only"
    if (any(item["status"] == "deleted" for item in items) or
            any(event["op"] == "add" for event in checkpoint["state"]["history"])):
        return "all_items_removed"
    return "empty_output"


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
    output_status = output_status_for_checkpoint(checkpoint, execution_status)
    stable_to_handle, alias_to_stable = source_handles(units)
    del stable_to_handle
    phase_coverage = {phase: source_interval_coverage(
        units, set(source_ids), len(text), phase)
        for phase, source_ids in checkpoint.get("phase_source_ids", {}).items()}
    return {"schema_version": SCHEMA_VERSION,
        "representation": "extractive_paragraph_sentence_references",
        "workflow": "draft_selection_attribution_treatment_finalize",
        "case_id": row["case_id"], "source": row["source"],
        "source_hash": row["source_hash"], "prompt_version": VERSION,
        "source_handle_manifest": {"source_hash": row["source_hash"],
                                   "handles": alias_to_stable},
        "execution_status": execution_status, "protocol_status": protocol_status,
        "output_status": output_status,
        "empty_reason": ("all_proposals_withdrawn" if output_status == "empty_output" and
            any(record["status"] == "resolved_withdrawn" and
                isinstance(record.get("original_operation"), dict) and
                record["original_operation"].get("op") == "add"
                for record in checkpoint["operation_rejections"]) else None),
        "quality_status": "not_evaluated",
        "stop_reason": stop_reason,
        "brief": [item for item in active if item["collection"] == "brief"],
        "aus": [item for item in active if item["collection"] == "aus"],
        "unresolved_items": deferred, "deleted_items": deleted,
        "final_au_ids": ([item["id"] for item in active if item["collection"] == "aus"]
                         if output_status != "incomplete" else []),
        "history": checkpoint["state"]["history"],
        "open_questions": checkpoint["open_questions"],
        "operation_rejections": checkpoint["operation_rejections"],
        "unresolved_opportunities": [record["rejection_id"] for record in
            checkpoint["operation_rejections"] if record["stage"] == "finalizer" and
            record["status"] == "resolved_withdrawn"],
        "noop_operations": checkpoint.get("noop_operations", []),
        "protocol_errors": checkpoint["protocol_errors"],
        "protocol_repairs": checkpoint["protocol_repairs"],
        "reader_stop": checkpoint.get("reader_stop"),
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
                   "protocol_replaced": sum(record["status"] == "resolved" for record in
                       checkpoint["operation_rejections"]),
                   "protocol_withdrawn": sum(record["status"] == "resolved_withdrawn" for record in
                       checkpoint["operation_rejections"]),
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
            "read_expansions": 0, "max_read_expansions": steps, "stagnation": 0,
            "operation_rejections": [], "protocol_errors": [], "protocol_repairs": [],
            "noop_operations": [],
            "request_journal": {}, "response_processing": {}, "processed_responses": {},
            "repair_turn": 0, "classification_extra_used": False,
            "snapshots": []}
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
            if _has_unresolved_protocol(checkpoint):
                checkpoint["stage"] = "incomplete_protocol"
                save(checkpoint_path, checkpoint)
                break
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
                checkpoint["reader_stop"] = {"reason": control["reason"],
                    "unread_window_ids": sorted(set(range(len(windows))) - opened_windows),
                    "read_expansions": checkpoint["read_expansions"]}
                checkpoint["stage"] = "repair_selection"
            save(checkpoint_path, checkpoint)
        if checkpoint["stage"] == "reading":
            checkpoint["reader_stop"] = {"reason": "read_decision_limit",
                "unread_window_ids": sorted(set(range(len(windows))) -
                    set(checkpoint["opened_window_ids"])),
                "read_expansions": checkpoint["read_expansions"]}
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

        for stage, prompt, snapshot_name, next_stage, phase_name in (
                ("repair_selection", SELECTION_REPAIR, "after_selection_repair",
                 "repair_attribution", "selection_repair"),
                ("repair_attribution", ATTRIBUTION_REPAIR, "after_attribution_repair",
                 "repair_treatment", "attribution_repair"),
                ("repair_treatment", TREATMENT_REPAIR, "after_treatment_repair",
                 "finalizing", "treatment_repair")):
            while checkpoint["stage"] == stage:
                turn = checkpoint.get("repair_turn", 0)
                context = _context_ids(checkpoint["state"], paragraphs, source_map)
                checkpoint["opened_source_ids"] = sorted(set(checkpoint["opened_source_ids"]) | context)
                checkpoint["phase_source_ids"][phase_name] = sorted(
                    set(checkpoint["opened_source_ids"]) | context)
                payload = _base_payload(checkpoint, row, catalogue, source_map,
                                        stable_to_handle, windows)
                payload["continuation"] = turn == 1
                payload["classification_extra_window_available"] = (
                    not checkpoint.get("classification_extra_used", False))
                if stage in {"repair_attribution", "repair_treatment"}:
                    payload["source_label_matrix"] = _label_matrix(
                        checkpoint["state"], stable_to_handle)
                response = _agent_call(endpoint=endpoint, model=config["repair"], prompt=prompt,
                    payload=payload, experiment=experiment, row=row, stage=phase_name, turn=turn,
                    output=output, checkpoint=checkpoint, checkpoint_path=checkpoint_path)
                opened_windows = set(checkpoint["opened_window_ids"])
                unread = {window["window_id"] for window in windows} - opened_windows
                no_more_classification_read = (stage == "repair_treatment" and
                    checkpoint.get("classification_extra_used", False))
                control, applied, rejected = _process_response(
                    response=response, phase=phase_name,
                    turn=turn, continuation=turn == 1 or no_more_classification_read,
                    checkpoint=checkpoint,
                    checkpoint_path=checkpoint_path, opened=set(checkpoint["opened_source_ids"]),
                    unread_windows=set() if no_more_classification_read else unread,
                    source_map=source_map,
                    stable_to_handle=stable_to_handle, alias_to_stable=alias_to_stable,
                    row=row, endpoint=endpoint, model=config["repair"],
                    experiment=experiment, output=output)
                if _has_unresolved_protocol(checkpoint):
                    checkpoint["stage"] = "incomplete_protocol"
                    save(checkpoint_path, checkpoint)
                    break
                requested = control["read_window_ids"]
                new_windows = [value for value in requested if value not in opened_windows]
                opened_windows.update(new_windows)
                newly_opened = _opened_ids(windows, set(new_windows))
                checkpoint["opened_window_ids"] = sorted(opened_windows)
                if stage in {"repair_attribution", "repair_treatment"} and new_windows:
                    checkpoint["classification_extra_used"] = True
                checkpoint["opened_source_ids"] = sorted(
                    set(checkpoint["opened_source_ids"]) | newly_opened)
                checkpoint["phase_source_ids"][phase_name] = sorted(
                    set(checkpoint["phase_source_ids"][phase_name]) | newly_opened)
                checkpoint["open_questions"] = control["open_questions"]
                checkpoint["trace"].append({"stage": stage, "turn": turn,
                    "action": control["action"], "reason": control["reason"],
                    "item_checks": deepcopy(control["item_checks"]),
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
                    if next_stage == "repair_attribution":
                        next_context = _context_ids(checkpoint["state"], paragraphs, source_map)
                        checkpoint["opened_source_ids"] = sorted(
                            set(checkpoint["opened_source_ids"]) | next_context)
                        checkpoint["phase_source_ids"]["attribution_repair"] = sorted(
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
            if _has_unresolved_protocol(checkpoint):
                checkpoint["stage"] = "incomplete_protocol"
            else:
                checkpoint["open_questions"] = control["open_questions"]
                checkpoint["trace"].append({"stage": "finalizer", "turn": 0,
                    "reason": control["reason"], "applied": applied,
                    "item_checks": deepcopy(control["item_checks"]),
                    "noops": deepcopy(checkpoint["processed_responses"]["finalizer:0"].get("noops", [])),
                    "rejected": [value["rejection_id"] for value in rejected]})
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

