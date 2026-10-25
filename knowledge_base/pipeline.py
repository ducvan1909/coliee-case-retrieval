"""V5 extractive reader with consistent selection and durable recovery."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from .endpoint import BudgetStop, ModelProtocolError
from .prompts import (AU_VERIFIER, BRIEF_VERIFIER, FINALIZER, PROTOCOL_REPAIR,
                      READER, SELECTION_RECOVERY, VERIFIER_PROTOCOL_REPAIR,
                      VERIFIER_SCHEMAS, VERSION)
from .schema import (AGENT_SCHEMA, ATTRIBUTIONS, AU_SEARCH_STATUSES, REVIEW_STATUSES,
                     SCHEMA_VERSION)
from .source import (alias_item_sources, digest, load_source, materialize_sources,
                     opened_sources, save, source_handles, source_interval_coverage,
                     source_structure, structure_catalogue, structure_windows)
from .state import apply_operations_independently, initial_state, public_items

STATUS_ORDER = {"accepted": 0, "needs_review": 1, "rejected": 2}


def _au_search_outcome(value: object) -> dict:
    required = {"status", "inspected_source_ids", "needed_window_ids"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("invalid_au_search_outcome")
    if value["status"] not in AU_SEARCH_STATUSES:
        raise ValueError("invalid_au_search_status")
    if (not isinstance(value["inspected_source_ids"], list) or
            len(value["inspected_source_ids"]) != len(set(value["inspected_source_ids"])) or
            any(not isinstance(source_id, str) for source_id in value["inspected_source_ids"])):
        raise ValueError("invalid_au_inspected_sources")
    if (not isinstance(value["needed_window_ids"], list) or
            len(value["needed_window_ids"]) != len(set(value["needed_window_ids"])) or
            any(type(window_id) is not int for window_id in value["needed_window_ids"])):
        raise ValueError("invalid_au_needed_windows")
    if value["status"] != "insufficient_reading" and value["needed_window_ids"]:
        raise ValueError("unexpected_au_needed_windows")
    return deepcopy(value)


def _reader_response(response: object, final: bool = False) -> dict:
    if not isinstance(response, dict):
        raise ValueError("reader_response_must_be_object")
    required = ({"operations", "open_questions", "au_search_outcome"} if final else
                {"action", "reason", "read_window_ids", "operations", "open_questions"})
    if set(response) != required:
        raise ValueError("invalid_reader_response_fields")
    if not isinstance(response["operations"], list) or not isinstance(response["open_questions"], list):
        raise ValueError("invalid_reader_lists")
    if any(not isinstance(question, str) for question in response["open_questions"]):
        raise ValueError("invalid_open_question")
    if final:
        _au_search_outcome(response["au_search_outcome"])
    else:
        if response["action"] not in {"read", "finalize"} or not isinstance(response["reason"], str):
            raise ValueError("invalid_reader_action")
        ids = response["read_window_ids"]
        if (not isinstance(ids, list) or len(ids) > 2 or
                any(type(value) is not int for value in ids) or len(ids) != len(set(ids))):
            raise ValueError("invalid_window_requests")
        if response["action"] == "finalize" and ids:
            raise ValueError("finalize_cannot_request_windows")
    return deepcopy(response)


def _control(response: dict, final: bool) -> dict:
    if final:
        return {"open_questions": deepcopy(response["open_questions"]),
                "au_search_outcome": deepcopy(response["au_search_outcome"])}
    return {key: deepcopy(response[key]) for key in
            ("action", "reason", "read_window_ids", "open_questions")}


def _control_to_response(control: object, final: bool) -> dict:
    if not isinstance(control, dict):
        raise ValueError("invalid_protocol_repair_control")
    required = ({"open_questions", "au_search_outcome"} if final else
                {"action", "reason", "read_window_ids", "open_questions", "au_search_outcome"})
    if set(control) != required:
        raise ValueError("invalid_protocol_repair_control")
    if final:
        return _reader_response({"operations": [], **control}, final=True)
    if control["au_search_outcome"] is not None:
        raise ValueError("reader_repair_has_au_outcome")
    return _reader_response({"operations": [], **{key: control[key] for key in
        ("action", "reason", "read_window_ids", "open_questions")}}, final=False)


def _protocol_repair_response(response: object, rejection_ids: set[str],
                              allow_recovery: bool,
                              allowed_control_fields: set[str]) -> dict:
    required = {"control_patch", "repairs", "recovered_operations"}
    if (not isinstance(response, dict) or set(response) != required or
            not isinstance(response["control_patch"], dict) or
            not isinstance(response["repairs"], list) or
            not isinstance(response["recovered_operations"], list)):
        raise ValueError("invalid_protocol_repair_response")
    if not set(response["control_patch"]).issubset(allowed_control_fields):
        raise ValueError("protocol_repair_changed_valid_control")
    if response["recovered_operations"] and not allow_recovery:
        raise ValueError("unexpected_recovered_operations")
    return deepcopy(response)


def _control_fields(response: object, final: bool, *, opened: set[str],
                    alias_to_stable: dict[str, str], unread_windows: set[int]) -> tuple[dict, list[dict]]:
    """Validate control fields independently so a bad field cannot erase valid ones."""
    defaults = _fallback_control(final, [])
    result, errors = {}, []
    if not isinstance(response, dict):
        return defaults, [{"path": "$", "error_code": "reader_response_must_be_object"}]
    expected = ({"operations", "open_questions", "au_search_outcome"} if final else
                {"action", "reason", "read_window_ids", "operations", "open_questions"})
    for field in sorted(set(response) - expected):
        errors.append({"path": field, "error_code": "unexpected_reader_response_field"})
    if not isinstance(response.get("operations"), list):
        errors.append({"path": "operations", "error_code": "operations_must_be_list"})
    questions = response.get("open_questions")
    if (not isinstance(questions, list) or
            any(not isinstance(question, str) for question in questions)):
        errors.append({"path": "open_questions", "error_code": "invalid_open_question"})
        result["open_questions"] = defaults["open_questions"]
    else:
        result["open_questions"] = deepcopy(questions)
    if final:
        try:
            result["au_search_outcome"] = _validate_au_outcome(
                response.get("au_search_outcome"), opened, alias_to_stable, unread_windows)
        except ValueError as exc:
            errors.append({"path": "au_search_outcome", "error_code": str(exc)})
            result["au_search_outcome"] = defaults["au_search_outcome"]
        return result, errors
    action = response.get("action")
    if action not in {"read", "finalize"}:
        errors.append({"path": "action", "error_code": "invalid_reader_action"})
        action = defaults["action"]
    result["action"] = action
    reason = response.get("reason")
    if not isinstance(reason, str):
        errors.append({"path": "reason", "error_code": "invalid_reader_reason"})
        reason = defaults["reason"]
    result["reason"] = reason
    ids = response.get("read_window_ids")
    if (not isinstance(ids, list) or len(ids) > 2 or
            any(type(value) is not int for value in ids) or len(ids) != len(set(ids))):
        errors.append({"path": "read_window_ids", "error_code": "invalid_window_requests"})
        ids = []
    if action == "finalize" and ids:
        errors.append({"path": "read_window_ids", "error_code": "finalize_cannot_request_windows"})
        ids = []
    result["read_window_ids"] = deepcopy(ids)
    return result, errors


def _repair_matches(original: object, repaired: dict) -> bool:
    if not isinstance(original, dict) or repaired.get("op") != original.get("op"):
        return False
    if repaired.get("op") == "add":
        return repaired.get("collection") == original.get("collection")
    if repaired.get("op") in {"update", "remove"}:
        return (repaired.get("id") == original.get("id") and
                repaired.get("revision") == original.get("revision"))
    return False


def _check_component(value: object, provided_ids: set[str],
                     alias_to_stable: dict[str, str]) -> dict:
    required = set(AGENT_SCHEMA["verifier"]["component_check"])
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("invalid_verifier_component_shape")
    if value["status"] not in REVIEW_STATUSES:
        raise ValueError("invalid_verifier_status")
    if not isinstance(value["reason"], str) or not value["reason"].strip():
        raise ValueError("verifier_reason_required")
    evidence = value["evidence_source_ids"]
    if (not isinstance(evidence, list) or not evidence or len(evidence) != len(set(evidence)) or
            any(source_id not in alias_to_stable for source_id in evidence)):
        raise ValueError("invalid_verifier_evidence")
    canonical = [alias_to_stable[source_id] for source_id in evidence]
    if any(source_id not in provided_ids for source_id in canonical):
        raise ValueError("verifier_evidence_not_provided")
    return {"status": value["status"], "reason": value["reason"],
            "evidence_source_ids": canonical}


def _verifier_response(response: object, collection: str, source_map: dict[str, dict],
                       provided_ids: set[str], item: dict | None = None,
                       alias_to_stable: dict[str, str] | None = None,
                       requestable_ids: set[str] | None = None) -> dict:
    aliases = alias_to_stable or {source_id: source_id for source_id in source_map}
    component_names = (["selection_check", "kind_check"] if collection == "brief" else
                       ["selection_check", "relation_check", "treatment_check"])
    required = {"status", *component_names, "attribution_checks", "request_source_ids"}
    if not isinstance(response, dict) or set(response) != required:
        raise ValueError("invalid_verifier_response_fields")
    if response["status"] not in REVIEW_STATUSES:
        raise ValueError("invalid_verifier_status")
    checks = {name: _check_component(response[name], provided_ids, aliases)
              for name in component_names}
    if not isinstance(response["attribution_checks"], list):
        raise ValueError("invalid_attribution_checks")
    proposed = ({ref["source_id"]: ref["attribution"] for ref in item["source_refs"]}
                if item is not None else {})
    attribution_checks = []
    seen = set()
    for value in response["attribution_checks"]:
        fields = set(AGENT_SCHEMA["verifier"]["attribution_check"])
        if not isinstance(value, dict) or set(value) != fields or value["source_id"] not in aliases:
            raise ValueError("invalid_attribution_check_shape")
        source_id = aliases[value["source_id"]]
        if source_id in seen:
            raise ValueError("duplicate_attribution_check")
        seen.add(source_id)
        if item is not None and (source_id not in proposed or
                                 value["proposed_attribution"] != proposed[source_id]):
            raise ValueError("attribution_check_does_not_match_item")
        if value["observed_attribution"] not in ATTRIBUTIONS:
            raise ValueError("invalid_observed_attribution")
        check = _check_component({key: value[key] for key in
                                  ("status", "reason", "evidence_source_ids")},
                                 provided_ids, aliases)
        if (value["observed_attribution"] != value["proposed_attribution"] and
                check["status"] == "accepted"):
            check["status"] = "needs_review"
            check["reason"] = (check["reason"] +
                " Host downgraded acceptance because observed attribution differs from proposed attribution.")
        attribution_checks.append({"source_id": source_id,
            "proposed_attribution": value["proposed_attribution"],
            "observed_attribution": value["observed_attribution"], **check})
    if item is not None and seen != set(proposed):
        raise ValueError("attribution_checks_must_cover_selected_refs")
    requested = response["request_source_ids"]
    if (not isinstance(requested, list) or len(requested) > 2 or
            len(requested) != len(set(requested)) or any(value not in aliases for value in requested)):
        raise ValueError("invalid_verifier_context_request")
    canonical_requested = [aliases[value] for value in requested]
    allowed = requestable_ids if requestable_ids is not None else set(source_map)
    if any(source_id not in allowed for source_id in canonical_requested):
        raise ValueError("verifier_context_not_offered")
    statuses = [check["status"] for check in checks.values()]
    statuses.extend(check["status"] for check in attribution_checks)
    derived = max(statuses, key=STATUS_ORDER.get)
    result = {"status": derived, **checks, "attribution_checks": attribution_checks,
              "request_source_ids": canonical_requested, "protocol_valid": True}
    if response["status"] != derived:
        result["reported_status"] = response["status"]
    return result


def _invalid_verifier_review(collection: str, response: object, error_code: str,
                             item: dict | None = None) -> dict:
    names = (["selection_check", "kind_check"] if collection == "brief" else
             ["selection_check", "relation_check", "treatment_check"])
    reason = f"Verifier response failed host validation: {error_code}"
    result = {name: {"status": "needs_review", "reason": reason,
                     "evidence_source_ids": []} for name in names}
    result.update({"status": "needs_review", "attribution_checks": [
        {"source_id": ref["source_id"], "proposed_attribution": ref["attribution"],
         "observed_attribution": "unknown", "status": "needs_review",
         "reason": reason, "evidence_source_ids": []}
        for ref in (item or {}).get("source_refs", [])],
        "request_source_ids": [], "protocol_valid": False,
        "reported_response": deepcopy(response)})
    return result


def _opened_ids(windows: list[dict], window_ids: set[int]) -> set[str]:
    result: set[str] = set()
    for window_id in window_ids:
        result.update(windows[window_id]["source_ids"])
    return result


def _review_context(item: dict, paragraphs: list[dict], source_map: dict[str, dict],
                    extra: set[str] | None = None) -> list[dict]:
    positions = {paragraph["source_id"]: index for index, paragraph in enumerate(paragraphs)}
    included = set(extra or ())
    selected = {ref["source_id"] for ref in item["source_refs"]}
    included.update(selected)
    parents = {source_map[source_id].get("parent_id") or source_id for source_id in selected}
    for parent_id in parents:
        included.add(parent_id)
        index = positions[parent_id]
        if index:
            included.add(paragraphs[index - 1]["source_id"])
        if index + 1 < len(paragraphs):
            included.add(paragraphs[index + 1]["source_id"])
    return [unit for unit in source_map.values() if unit["source_id"] in included]


def _requestable_context(item: dict, paragraphs: list[dict], source_map: dict[str, dict]) -> set[str]:
    positions = {paragraph["source_id"]: index for index, paragraph in enumerate(paragraphs)}
    result = set()
    for ref in item["source_refs"]:
        parent_id = source_map[ref["source_id"]].get("parent_id") or ref["source_id"]
        index = positions[parent_id]
        for neighbor in paragraphs[max(0, index - 2):min(len(paragraphs), index + 3)]:
            result.add(neighbor["source_id"])
            result.update(neighbor["sentence_ids"])
    return result


def _alias_unit(unit: dict, stable_to_handle: dict[str, str]) -> dict:
    result = deepcopy(unit)
    result["source_id"] = stable_to_handle[unit["source_id"]]
    if result.get("parent_id"):
        result["parent_id"] = stable_to_handle[result["parent_id"]]
    if "sentence_ids" in result:
        result["sentence_ids"] = [stable_to_handle[value] for value in result["sentence_ids"]]
    return result


def _public_items_for_prompt(state: dict, stable_to_handle: dict[str, str]) -> list[dict]:
    return [alias_item_sources(item, stable_to_handle) for item in public_items(state)]


def _alias_review_sources(review: dict, stable_to_handle: dict[str, str]) -> dict:
    """Convert every structured source address in a stored review to request handles."""
    result = deepcopy(review)
    for key in ("selection_check", "kind_check", "relation_check", "treatment_check"):
        if key in result:
            result[key]["evidence_source_ids"] = [stable_to_handle[value]
                for value in result[key].get("evidence_source_ids", [])]
    for check in result.get("attribution_checks", []):
        check["source_id"] = stable_to_handle[check["source_id"]]
        check["evidence_source_ids"] = [stable_to_handle[value]
            for value in check.get("evidence_source_ids", [])]
    result["request_source_ids"] = [stable_to_handle[value]
        for value in result.get("request_source_ids", [])]
    return result


def _request_id(experiment: str, row: dict, stage: str, turn: str | int,
                payload: dict) -> tuple[str, str]:
    payload_hash = digest(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8"))
    identity = f"{experiment}:s{SCHEMA_VERSION}:{VERSION}:{row['source_hash']}:{stage}:{turn}:{payload_hash}"
    return f"{row['case_id']}:{stage}:{turn}:{digest(identity.encode())[:20]}", payload_hash


def _complete(endpoint, model: str, prompt: str, payload: dict, *, experiment: str,
              row: dict, stage: str, turn: str | int, cache_path: Path,
              item_id: str | None = None) -> dict:
    request_id, payload_hash = _request_id(experiment, row, stage, turn, payload)
    metadata = {"experiment": experiment, "schema_version": SCHEMA_VERSION,
                "prompt_version": VERSION, "source_hash": row["source_hash"],
                "payload_hash": payload_hash, "prompt_hash": digest(prompt.encode("utf-8")),
                "case_id": row["case_id"], "stage": stage, "turn": turn}
    if item_id:
        metadata["item_id"] = item_id
    try:
        return endpoint.complete(model, prompt, payload, request_id=request_id,
                                 metadata=metadata, cache_path=cache_path)
    except ModelProtocolError:
        raw_path = Path(cache_path).with_suffix(".raw.json")
        if not raw_path.exists():
            raise
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        return {"__raw_invalid_json__": raw.get("model_content", "")}


def _operation_records(row: dict, stage: str, turn: int, operations: list,
                       rejected: list[dict]) -> list[dict]:
    return [{"rejection_id": f"{row['case_id']}:{stage}:{turn}:op:{entry['index']}",
             "stage": stage, "turn": turn, "operation_index": entry["index"],
             "error_code": entry["error_code"], "error_path": f"operations[{entry['index']}]",
             "original_operation": deepcopy(operations[entry["index"]]),
             "response_path": f"responses/{stage}_{turn:02d}.json", "status": "unresolved"}
            for entry in rejected]


def _fallback_control(final: bool, questions: list[str]) -> dict:
    if final:
        return {"open_questions": questions,
                "au_search_outcome": {"status": "insufficient_reading",
                    "inspected_source_ids": [], "needed_window_ids": []}}
    return {"action": "finalize", "reason": "protocol error remained unresolved",
            "read_window_ids": [], "open_questions": questions}


def _process_agent_response(*, response: object, final: bool, checkpoint: dict,
                            checkpoint_path: Path, opened: set[str],
                            opened_windows: set[int], source_map: dict[str, dict],
                            stable_to_handle: dict[str, str], alias_to_stable: dict[str, str],
                            row: dict, endpoint, model: str, experiment: str,
                            stage: str, turn: int, output: Path,
                            all_window_ids: set[int] | None = None) -> tuple[dict, list[dict], list[dict]]:
    response_key = f"{stage}:{turn}"
    pending = checkpoint.get("protocol_repair_pending")
    completed = checkpoint.get("processed_agent_responses", {}).get(response_key)
    if completed and not pending:
        records_by_id = {entry["rejection_id"]: entry
                         for entry in checkpoint["operation_rejections"]}
        return (deepcopy(completed["control"]), deepcopy(completed["applied_events"]),
                [records_by_id[value] for value in completed["rejection_ids"]])
    if pending and (pending["stage"], pending["turn"]) != (stage, turn):
        raise ValueError("protocol_repair_pending_for_other_turn")
    if pending:
        response = pending["original_response"]
        control = deepcopy(pending["control"])
        control_errors = deepcopy(pending["control_errors"])
        records = [entry for entry in checkpoint["operation_rejections"]
                   if entry["rejection_id"] in set(pending["rejection_ids"])]
        applied = deepcopy(pending.get("applied_events", []))
        snapshot_ids = set(pending["snapshot_ids"])
        allow_recovery = pending.get("allow_recovery", False)
        repair_payload = deepcopy(pending["repair_payload"])
    else:
        snapshot_ids = {item["id"] for item in public_items(checkpoint["state"])}
        allow_recovery = isinstance(response, dict) and set(response) == {"__raw_invalid_json__"}
        unread_windows = ((all_window_ids or set()) - opened_windows)
        control, control_errors = _control_fields(
            response, final, opened=opened, alias_to_stable=alias_to_stable,
            unread_windows=unread_windows)
        if not final and all_window_ids is not None:
            requested = control["read_window_ids"]
            if any(value not in all_window_ids for value in requested):
                control_errors.append({"path": "read_window_ids",
                                       "error_code": "requested_window_does_not_exist"})
                control["read_window_ids"] = []
        operations = (response.get("operations", []) if isinstance(response, dict) and
                      isinstance(response.get("operations"), list) else [])
        working, applied, rejected = apply_operations_independently(
            checkpoint["state"], operations, opened, source_map, row["source_hash"],
            row["case_id"], source_aliases=alias_to_stable,
            allowed_target_ids=snapshot_ids)
        records = _operation_records(row, stage, turn, operations, rejected)
        checkpoint["state"] = working
        checkpoint["operation_rejections"].extend(records)
        for number, error in enumerate(control_errors):
            error["error_id"] = f"{row['case_id']}:{stage}:{turn}:control:{number}"
            error.update({"stage": stage, "turn": turn,
                          "response_path": f"responses/{stage}_{turn:02d}.json",
                          "status": "unresolved"})
            checkpoint["protocol_errors"].append(error)
        if control_errors or records:
            repair_payload = {
                "expected_response": "finalizer" if final else "reader",
                "source_handle_scope": {"case_id": row["case_id"],
                                        "source_hash": row["source_hash"]},
                "invalid_response": deepcopy(response),
                "control_errors": deepcopy(control_errors),
                "allowed_control_patch_fields": sorted(
                    {error["path"] for error in control_errors if error["path"] != "$"}),
                "rejected_operations": deepcopy(records),
                "valid_rejection_ids": [record["rejection_id"] for record in records],
                "valid_operations_already_applied": [event["operation"] for event in applied],
                "current_items": _public_items_for_prompt(checkpoint["state"], stable_to_handle),
                "opened_sources": opened_sources(source_map, opened, stable_to_handle),
            }
            checkpoint["protocol_repair_pending"] = {
                "stage": stage, "turn": turn, "final": final,
                "phase": "request_pending", "original_response": deepcopy(response),
                "control": deepcopy(control), "control_errors": deepcopy(control_errors),
                "rejection_ids": [record["rejection_id"] for record in records],
                "snapshot_ids": sorted(snapshot_ids), "allow_recovery": allow_recovery,
                "applied_events": deepcopy(applied), "repair_payload": deepcopy(repair_payload)}
        save(checkpoint_path, checkpoint)
        if not control_errors and not records:
            checkpoint.setdefault("processed_agent_responses", {})[response_key] = {
                "control": deepcopy(control), "applied_events": deepcopy(applied),
                "rejection_ids": []}
            save(checkpoint_path, checkpoint)
            return control, applied, records

    repair = _complete(endpoint, model, PROTOCOL_REPAIR, repair_payload,
                       experiment=experiment, row=row, stage=f"{stage}_protocol_repair",
                       turn=turn, cache_path=output / "responses" / f"{stage}_{turn:02d}_repair.json")
    repair_record = {"stage": stage, "turn": turn,
        "response_path": f"responses/{stage}_{turn:02d}_repair.json",
        "status": "completed", "entry_errors": []}
    try:
        repair = _protocol_repair_response(
            repair, {record["rejection_id"] for record in records}, allow_recovery,
            set(repair_payload["allowed_control_patch_fields"]))
        patched = deepcopy(control)
        for field, value in repair["control_patch"].items():
            candidate = deepcopy(patched)
            candidate[field] = deepcopy(value)
            candidate_response = {"operations": [], **candidate}
            candidate_control, candidate_errors = _control_fields(
                candidate_response, final, opened=opened, alias_to_stable=alias_to_stable,
                unread_windows=(all_window_ids or set()) - opened_windows)
            field_errors = [error for error in candidate_errors if error["path"] == field]
            if (not final and field == "read_window_ids" and
                    not set(candidate_control[field]).issubset(opened_windows)):
                field_errors.append({"path": field,
                                     "error_code": "protocol_repair_requested_new_source"})
            if field_errors:
                repair_record["entry_errors"].append({"path": f"control_patch.{field}",
                    "error_code": field_errors[0]["error_code"]})
                continue
            patched[field] = candidate_control[field]
            for error in checkpoint["protocol_errors"]:
                if (error.get("stage"), error.get("turn"), error.get("path")) == (stage, turn, field):
                    error["status"] = "resolved"
                    error["resolved_by"] = f"{stage}_protocol_repair"
        control = patched
        by_id = {record["rejection_id"]: record for record in records}
        seen = set()
        for value in repair["repairs"]:
            if (not isinstance(value, dict) or set(value) != {"rejection_id", "operation"} or
                    value.get("rejection_id") not in by_id or value.get("rejection_id") in seen or
                    not isinstance(value.get("operation"), dict)):
                repair_record["entry_errors"].append({"path": "repairs",
                                                       "error_code": "invalid_protocol_repair_entry"})
                continue
            seen.add(value["rejection_id"])
            record = by_id[value["rejection_id"]]
            record["repair_operation"] = deepcopy(value["operation"])
            record["repair_response_path"] = f"responses/{stage}_{turn:02d}_repair.json"
            if not _repair_matches(record["original_operation"], value["operation"]):
                record["repair_error_code"] = "repair_target_mismatch"
                continue
            candidate, events, failed = apply_operations_independently(
                checkpoint["state"], [value["operation"]], opened, source_map,
                row["source_hash"], row["case_id"], source_aliases=alias_to_stable,
                allowed_target_ids=snapshot_ids)
            if failed:
                record["repair_error_code"] = failed[0]["error_code"]
            else:
                checkpoint["state"] = candidate
                applied.extend(events)
                record["status"] = "resolved"
                record["resolved_by"] = f"{stage}_protocol_repair"
        if repair["recovered_operations"]:
            candidate, events, failed = apply_operations_independently(
                checkpoint["state"], repair["recovered_operations"], opened, source_map,
                row["source_hash"], row["case_id"], source_aliases=alias_to_stable,
                allowed_target_ids=snapshot_ids)
            if failed:
                raise ValueError("invalid_recovered_operation:" + failed[0]["error_code"])
            checkpoint["state"] = candidate
            applied.extend(events)
    except ValueError as exc:
        for record in records:
            if record["status"] == "unresolved":
                record["repair_error_code"] = str(exc)
        repair_record.update({"status": "failed", "error_code": str(exc)})
    unresolved_control = [entry for entry in checkpoint["protocol_errors"]
                          if entry.get("stage") == stage and entry.get("turn") == turn and
                          entry.get("status") == "unresolved"]
    if unresolved_control:
        control["open_questions"] = list(control.get("open_questions", [])) + [
            "unresolved protocol error: " + entry["error_code"] for entry in unresolved_control]
    checkpoint["protocol_repairs"].append(repair_record)
    checkpoint["protocol_repair_pending"] = None
    checkpoint.setdefault("processed_agent_responses", {})[response_key] = {
        "control": deepcopy(control), "applied_events": deepcopy(applied),
        "rejection_ids": [record["rejection_id"] for record in records]}
    save(checkpoint_path, checkpoint)
    return control, applied, records


def _validate_au_outcome(value: dict, opened: set[str], alias_to_stable: dict[str, str],
                         unread_windows: set[int]) -> dict:
    result = _au_search_outcome(value)
    try:
        inspected = [alias_to_stable[source_id] for source_id in result["inspected_source_ids"]]
    except KeyError as exc:
        raise ValueError("au_outcome_unknown_source") from exc
    if any(source_id not in opened for source_id in inspected):
        raise ValueError("au_outcome_unread_source")
    if result["status"] != "insufficient_reading" and not inspected:
        raise ValueError("au_outcome_requires_inspected_sources")
    if not set(result["needed_window_ids"]).issubset(unread_windows):
        raise ValueError("au_outcome_invalid_needed_window")
    result["inspected_source_ids"] = inspected
    return result


def _active_aus(state: dict) -> list[dict]:
    return [item for item in state["items"].values()
            if item["collection"] == "aus" and not item["deleted"]]


def _has_unresolved_protocol(checkpoint: dict) -> bool:
    pending_recheck_ids = {error_id for values in checkpoint.get("recheck_error_ids", {}).values()
                           for error_id in values}
    return any(entry.get("status") == "unresolved" and
               entry.get("error_id") not in pending_recheck_ids for key in
               ("operation_rejections", "protocol_errors", "verifier_protocol_errors")
               for entry in checkpoint.get(key, []))


def _verify_with_protocol_repair(*, response: object, collection: str, item: dict,
                                 context: list[dict], provided: set[str],
                                 requestable: set[str], source_map: dict[str, dict],
                                 stable_to_handle: dict[str, str],
                                 alias_to_stable: dict[str, str], checkpoint: dict,
                                 checkpoint_path: Path, endpoint, model: str,
                                 experiment: str, row: dict, index: int, pass_index: int,
                                 output: Path, verification_run: int = 0) -> dict:
    pending = checkpoint.get("verifier_repair_pending")
    if pending and (pending["item_id"], pending["pass_index"], pending.get("verification_run", 0)) != (
            item["id"], pass_index, verification_run):
        raise ValueError("verifier_repair_pending_for_other_item")
    if pending:
        response = pending["invalid_response"]
        error_code = pending["error_code"]
        error_record = next(entry for entry in checkpoint["verifier_protocol_errors"]
                            if entry["error_id"] == pending["error_id"])
    else:
        try:
            return _verifier_response(response, collection, source_map, provided, item,
                                      alias_to_stable, requestable)
        except ValueError as exc:
            error_code = str(exc)
        error_record = {"error_id": f"{item['id']}:verifier:{verification_run}:{index}:{pass_index}",
            "item_id": item["id"], "pass": pass_index, "error_code": error_code,
            "error_path": "$", "verification_run": verification_run,
            "response_path": f"responses/verifier_r{verification_run}_{index:03d}_{pass_index}.json",
            "status": "unresolved"}
        checkpoint["verifier_protocol_errors"].append(error_record)
        checkpoint["verifier_repair_pending"] = {"error_id": error_record["error_id"],
            "item_id": item["id"], "pass_index": pass_index,
            "verification_run": verification_run,
            "invalid_response": deepcopy(response), "error_code": error_code}
        save(checkpoint_path, checkpoint)
    allowed_handles = sorted(stable_to_handle[source_id] for source_id in provided)
    payload = {"collection": collection,
        "source_handle_scope": {"case_id": row["case_id"], "source_hash": row["source_hash"]},
        "expected_schema": VERIFIER_SCHEMAS[collection],
        "errors": [{"path": error_record.get("error_path", "$"), "error_code": error_code}],
        "allowed_source_handles": allowed_handles,
        "invalid_response": deepcopy(response),
        "item": alias_item_sources({key: deepcopy(value) for key, value in item.items()
                                      if key not in {"review", "excerpts"}}, stable_to_handle),
        "source_context": [_alias_unit(unit, stable_to_handle) for unit in context]}
    repaired = _complete(endpoint, model, VERIFIER_PROTOCOL_REPAIR, payload,
        experiment=experiment, row=row, stage=f"{collection}_verifier_protocol_repair",
        turn=f"{verification_run}:{index}:{pass_index}", item_id=item["id"],
        cache_path=output / "responses" /
            f"verifier_r{verification_run}_{index:03d}_{pass_index}_repair.json")
    try:
        if not isinstance(repaired, dict) or set(repaired) != {"review"}:
            raise ValueError("invalid_verifier_repair_envelope")
        review = _verifier_response(repaired["review"], collection, source_map, provided,
                                    item, alias_to_stable, provided)
        error_record["status"] = "resolved"
        error_record["resolved_by"] = "verifier_protocol_repair"
        error_record["repair_response_path"] = (
            f"responses/verifier_r{verification_run}_{index:03d}_{pass_index}_repair.json")
    except ValueError as exc:
        error_record["repair_error_code"] = str(exc)
        review = _invalid_verifier_review(collection, response, str(exc), item)
    checkpoint["verifier_repair_pending"] = None
    save(checkpoint_path, checkpoint)
    return review


def _statuses(state: dict, rejections: list[dict], execution: str,
              verifier_errors: list[dict] | None = None,
              protocol_errors: list[dict] | None = None) -> tuple[str, str, str]:
    if execution != "completed":
        return "not_completed", "not_completed", "incomplete"
    active = [item for item in state["items"].values() if not item["deleted"]]
    unresolved = [entry for entry in rejections if entry["status"] == "unresolved"]
    unresolved.extend(entry for entry in (verifier_errors or [])
                      if entry.get("status") == "unresolved")
    unresolved.extend(entry for entry in (protocol_errors or [])
                      if entry.get("status") == "unresolved")
    protocol = "partial" if unresolved and active else "failure" if unresolved else "valid"
    ever_added = any(event["op"] == "add" for event in state["history"])
    unresolved_create = any(entry.get("original_operation", {}).get("op") in {"add", "update"}
                            for entry in unresolved)
    if not active:
        if unresolved_create or unresolved:
            verification = "protocol_failure"
        elif ever_added:
            verification = "all_items_removed"
        else:
            verification = "empty_output"
    else:
        reviews = [(item.get("review") or {}).get("status", "needs_review") for item in active]
        if all(status == "rejected" for status in reviews):
            verification = "all_items_rejected"
        elif any(status == "needs_review" for status in reviews):
            verification = "needs_review"
        elif any(status == "rejected" for status in reviews):
            verification = "reviewed_with_rejections"
        else:
            verification = "accepted"
    semantic = ("protocol_failure" if protocol == "failure" else
                "partial_protocol_failure" if protocol == "partial" else verification)
    return protocol, verification, semantic


def _result(row: dict, text: str, units: list[dict], checkpoint: dict,
            execution: str, stop_reason: str) -> dict:
    state = checkpoint["state"]
    source_map = {unit["source_id"]: unit for unit in units}
    active, deleted = [], []
    for item in state["items"].values():
        rendered = deepcopy(item)
        rendered["excerpts"] = materialize_sources(item["source_refs"], source_map,
                                                   row["source_hash"])
        (deleted if item["deleted"] else active).append(rendered)
    rejections = checkpoint.get("operation_rejections", [])
    verifier_errors = checkpoint.get("verifier_protocol_errors", [])
    protocol_errors = checkpoint.get("protocol_errors", [])
    protocol, verification, semantic = _statuses(
        state, rejections, execution, verifier_errors, protocol_errors)
    accepted_aus = [item["id"] for item in active if item["collection"] == "aus" and
                    (item.get("review") or {}).get("status") == "accepted"]
    reviews = [(item.get("review") or {}).get("status") for item in active]
    _, alias_to_stable = source_handles(units)
    return {"schema_version": SCHEMA_VERSION,
            "representation": "extractive_paragraph_sentence_references",
            "case_id": row["case_id"], "source": row["source"],
            "source_hash": row["source_hash"], "prompt_version": VERSION,
            "source_handle_manifest": {"source_hash": row["source_hash"],
                                       "handles": alias_to_stable},
            "execution_status": execution, "protocol_status": protocol,
            "verification_status": verification, "semantic_status": semantic,
            "acceptance_basis": "model_verifier_only_until_calibration_adjudication",
            "stop_reason": stop_reason,
            "brief": [item for item in active if item["collection"] == "brief"],
            "aus": [item for item in active if item["collection"] == "aus"],
            "deleted_items": deleted, "au_ids": accepted_aus,
            "history": state["history"], "open_questions": checkpoint["open_questions"],
            "au_search_outcome": checkpoint.get("au_search_outcome"),
            "selection_recovery_attempted": checkpoint.get(
                "selection_recovery_attempted", False),
            "operation_rejections": rejections, "protocol_errors": protocol_errors,
            "protocol_repairs": checkpoint.get("protocol_repairs", []),
            "verifier_protocol_errors": verifier_errors,
            "reader_coverage": source_interval_coverage(
                units, set(checkpoint["opened_source_ids"]), len(text), "reader"),
            "verifier_coverage": source_interval_coverage(
                units, set(checkpoint.get("verifier_source_ids", [])), len(text), "verifier"),
            "counts": {"draft": sum(value is None for value in reviews),
                       "accepted": reviews.count("accepted"),
                       "needs_review": reviews.count("needs_review"),
                       "verifier_rejected": reviews.count("rejected"),
                       "deleted": len(deleted), "technically_valid": len(active),
                       "protocol_rejected_total": len(rejections),
                       "protocol_rejected_unresolved": sum(entry["status"] == "unresolved"
                                                           for entry in rejections),
                       "protocol_rejected_resolved": sum(entry["status"] == "resolved"
                                                         for entry in rejections),
                       "protocol_repairs": len(checkpoint.get("protocol_repairs", [])),
                       "protocol_errors_unresolved": sum(entry["status"] == "unresolved"
                                                         for entry in protocol_errors),
                       "verifier_protocol_errors": len(verifier_errors),
                       "verifier_protocol_errors_unresolved": sum(
                           entry["status"] == "unresolved" for entry in verifier_errors)}}


def build_case(row: dict, endpoint, config: dict, size: int, steps: int, output: Path,
               *, recheck_verifier_errors: bool = False) -> dict:
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
        checkpoint = {"schema_version": SCHEMA_VERSION, "prompt_version": VERSION,
            "source_hash": source_hash, "stage": "reading", "state": initial_state(),
            "opened_window_ids": sorted(initial_windows),
            "opened_source_ids": sorted(_opened_ids(windows, initial_windows)),
            "verifier_source_ids": [], "open_questions": [], "trace": [],
            "next_reader_turn": 0, "operation_rejections": [], "protocol_errors": [],
            "protocol_repairs": [], "protocol_repair_pending": None,
            "verifier_protocol_errors": [], "verifier_repair_pending": None,
            "read_expansions": 0, "stagnation": 0, "finalized": False,
            "au_search_outcome": None, "selection_recovery_pending": None,
            "selection_recovery_attempted": False,
            "verification_queue": [], "next_verifier_index": 0,
            "verification_run": 0, "recheck_error_ids": {},
            "verifier_request_pending": None, "processed_agent_responses": {}}
        save(checkpoint_path, checkpoint)
    for key, default in (("protocol_errors", []), ("protocol_repairs", []),
                         ("protocol_repair_pending", None),
                         ("verifier_protocol_errors", []),
                         ("verifier_repair_pending", None),
                         ("selection_recovery_pending", None),
                         ("selection_recovery_attempted", False),
                         ("verification_run", 0), ("recheck_error_ids", {}),
                         ("verifier_request_pending", None),
                         ("processed_agent_responses", {})):
        checkpoint.setdefault(key, default)

    if recheck_verifier_errors and checkpoint["stage"] == "complete":
        unresolved_ids = {entry["item_id"] for entry in checkpoint["verifier_protocol_errors"]
                          if entry.get("status") == "unresolved"}
        checkpoint["verification_queue"] = sorted(item_id for item_id in unresolved_ids
            if item_id in checkpoint["state"]["items"] and
            not checkpoint["state"]["items"][item_id]["deleted"])
        checkpoint["verification_run"] += 1
        checkpoint["recheck_error_ids"] = {item_id: [entry["error_id"] for entry in
            checkpoint["verifier_protocol_errors"] if entry.get("status") == "unresolved" and
            entry["item_id"] == item_id] for item_id in checkpoint["verification_queue"]}
        for item_id in checkpoint["verification_queue"]:
            checkpoint["state"]["items"][item_id]["review"] = None
        checkpoint["next_verifier_index"] = 0
        checkpoint["stage"] = "verifying"
        save(checkpoint_path, checkpoint)

    try:
        decision_limit = steps + 2
        while checkpoint["stage"] == "reading" and checkpoint["next_reader_turn"] < decision_limit:
            turn = checkpoint["next_reader_turn"]
            opened_windows = set(checkpoint["opened_window_ids"])
            opened = set(checkpoint["opened_source_ids"])
            payload = {"catalogue": catalogue,
                "source_handle_scope": {"case_id": row["case_id"], "source_hash": row["source_hash"]},
                "opened_sources": opened_sources(source_map, opened, stable_to_handle),
                "opened_window_ids": sorted(opened_windows),
                "unread_window_ids": [window["window_id"] for window in windows
                                      if window["window_id"] not in opened_windows],
                "current_items": _public_items_for_prompt(checkpoint["state"], stable_to_handle),
                "open_questions": checkpoint["open_questions"],
                "remaining_read_actions": steps - checkpoint["read_expansions"]}
            response = _complete(endpoint, config["reader"], READER, payload,
                experiment=experiment, row=row, stage="reader", turn=turn,
                cache_path=output / "responses" / f"reader_{turn:02d}.json")
            control, applied, rejected = _process_agent_response(
                response=response, final=False, checkpoint=checkpoint,
                checkpoint_path=checkpoint_path, opened=opened,
                opened_windows=opened_windows, source_map=source_map,
                stable_to_handle=stable_to_handle, alias_to_stable=alias_to_stable,
                row=row, endpoint=endpoint, model=config["reader"], experiment=experiment,
                stage="reader", turn=turn, output=output,
                all_window_ids={window["window_id"] for window in windows})
            requested = control["read_window_ids"]
            if any(value < 0 or value >= len(windows) for value in requested):
                raise ValueError("requested_window_does_not_exist")
            new_windows = [value for value in requested if value not in opened_windows]
            if new_windows and checkpoint["read_expansions"] >= steps:
                raise ValueError("reader_exceeded_read_budget")
            opened_windows.update(new_windows)
            progress = bool(applied or new_windows)
            checkpoint["opened_window_ids"] = sorted(opened_windows)
            checkpoint["opened_source_ids"] = sorted(_opened_ids(windows, opened_windows))
            checkpoint["open_questions"] = control["open_questions"]
            checkpoint["read_expansions"] += bool(new_windows)
            checkpoint["stagnation"] = 0 if progress else checkpoint["stagnation"] + 1
            checkpoint["trace"].append({"stage": "reader", "turn": turn,
                "action": control["action"], "reason": control["reason"],
                "requested": requested, "new_windows": new_windows, "applied": applied,
                "protocol_rejected": [entry["rejection_id"] for entry in rejected],
                "stagnation": checkpoint["stagnation"]})
            checkpoint["next_reader_turn"] += 1
            no_unread = len(opened_windows) == len(windows)
            just_opened_last_source = bool(new_windows) and no_unread
            if _has_unresolved_protocol(checkpoint):
                checkpoint["stage"] = "incomplete_protocol"
            elif (control["action"] == "finalize" or
                    (no_unread and not just_opened_last_source) or
                    checkpoint["stagnation"] >= 2 or
                    checkpoint["read_expansions"] >= steps or
                    checkpoint["next_reader_turn"] >= decision_limit):
                checkpoint["stage"] = "finalizing"
            save(checkpoint_path, checkpoint)

        if checkpoint["stage"] == "reading":
            checkpoint["stage"] = "finalizing"
            save(checkpoint_path, checkpoint)

        if checkpoint["stage"] == "finalizing" and not checkpoint["finalized"]:
            opened = set(checkpoint["opened_source_ids"])
            payload = {"catalogue": catalogue,
                "source_handle_scope": {"case_id": row["case_id"], "source_hash": row["source_hash"]},
                "opened_sources": opened_sources(source_map, opened, stable_to_handle),
                "unread_window_ids": [window["window_id"] for window in windows
                    if window["window_id"] not in set(checkpoint["opened_window_ids"])],
                "current_items": _public_items_for_prompt(checkpoint["state"], stable_to_handle),
                "open_questions": checkpoint["open_questions"]}
            response = _complete(endpoint, config["reader"], FINALIZER, payload,
                experiment=experiment, row=row, stage="finalizer", turn=0,
                cache_path=output / "responses" / "finalizer_00.json")
            control, applied, rejected = _process_agent_response(
                response=response, final=True, checkpoint=checkpoint,
                checkpoint_path=checkpoint_path, opened=opened,
                opened_windows=set(checkpoint["opened_window_ids"]), source_map=source_map,
                stable_to_handle=stable_to_handle, alias_to_stable=alias_to_stable,
                row=row, endpoint=endpoint, model=config["reader"], experiment=experiment,
                stage="finalizer", turn=0, output=output,
                all_window_ids={window["window_id"] for window in windows})
            outcome = control["au_search_outcome"]
            checkpoint["open_questions"] = control["open_questions"]
            checkpoint["au_search_outcome"] = outcome
            checkpoint["trace"].append({"stage": "finalizer", "turn": 0,
                "applied": applied, "au_search_outcome": outcome,
                "protocol_rejected": [entry["rejection_id"] for entry in rejected]})
            checkpoint["finalized"] = True
            if _has_unresolved_protocol(checkpoint):
                checkpoint["stage"] = "incomplete_protocol"
            elif outcome["status"] == "found" and not _active_aus(checkpoint["state"]):
                checkpoint["stage"] = "selection_recovery"
            else:
                checkpoint["verification_queue"] = [item["id"] for item in
                    checkpoint["state"]["items"].values() if not item["deleted"]]
                checkpoint["stage"] = "verifying"
            save(checkpoint_path, checkpoint)

        if checkpoint["stage"] == "selection_recovery":
            opened = set(checkpoint["opened_source_ids"])
            pending = checkpoint.get("selection_recovery_pending")
            if pending:
                payload = deepcopy(pending["payload"])
            else:
                payload = {
                    "contradiction": "au_search_outcome is found but no active AU exists",
                    "catalogue": catalogue,
                    "source_handle_scope": {"case_id": row["case_id"],
                                            "source_hash": row["source_hash"]},
                    "opened_sources": opened_sources(source_map, opened, stable_to_handle),
                    "unread_window_ids": [window["window_id"] for window in windows
                        if window["window_id"] not in set(checkpoint["opened_window_ids"])],
                    "current_items": _public_items_for_prompt(
                        checkpoint["state"], stable_to_handle),
                    "open_questions": checkpoint["open_questions"],
                    "previous_au_search_outcome": {
                        **checkpoint["au_search_outcome"],
                        "inspected_source_ids": [stable_to_handle[value] for value in
                            checkpoint["au_search_outcome"]["inspected_source_ids"]],
                    },
                }
                checkpoint["selection_recovery_pending"] = {
                    "phase": "request_pending", "payload": deepcopy(payload)}
                checkpoint["selection_recovery_attempted"] = True
                save(checkpoint_path, checkpoint)
            response = _complete(endpoint, config["reader"], SELECTION_RECOVERY, payload,
                experiment=experiment, row=row, stage="selection_recovery", turn=0,
                cache_path=output / "responses" / "selection_recovery_00.json")
            control, applied, rejected = _process_agent_response(
                response=response, final=True, checkpoint=checkpoint,
                checkpoint_path=checkpoint_path, opened=opened,
                opened_windows=set(checkpoint["opened_window_ids"]), source_map=source_map,
                stable_to_handle=stable_to_handle, alias_to_stable=alias_to_stable,
                row=row, endpoint=endpoint, model=config["reader"], experiment=experiment,
                stage="selection_recovery", turn=0, output=output,
                all_window_ids={window["window_id"] for window in windows})
            checkpoint["open_questions"] = control["open_questions"]
            checkpoint["au_search_outcome"] = control["au_search_outcome"]
            checkpoint["trace"].append({"stage": "selection_recovery", "turn": 0,
                "applied": applied, "au_search_outcome": control["au_search_outcome"],
                "protocol_rejected": [entry["rejection_id"] for entry in rejected]})
            checkpoint["selection_recovery_pending"] = None
            if _has_unresolved_protocol(checkpoint):
                checkpoint["stage"] = "incomplete_protocol"
            elif (control["au_search_outcome"]["status"] == "found" and
                  not _active_aus(checkpoint["state"])):
                checkpoint["stage"] = "inconsistent_output"
            else:
                checkpoint["verification_queue"] = [item["id"] for item in
                    checkpoint["state"]["items"].values() if not item["deleted"]]
                checkpoint["stage"] = "verifying"
            save(checkpoint_path, checkpoint)

        while (checkpoint["stage"] == "verifying" and
               checkpoint["next_verifier_index"] < len(checkpoint["verification_queue"])):
            index = checkpoint["next_verifier_index"]
            item_id = checkpoint["verification_queue"][index]
            item = checkpoint["state"]["items"][item_id]
            context = _review_context(item, paragraphs, source_map)
            provided = {unit["source_id"] for unit in context}
            requestable = _requestable_context(item, paragraphs, source_map)
            checkpoint["verifier_source_ids"] = sorted(
                set(checkpoint["verifier_source_ids"]) | provided)
            prompt = BRIEF_VERIFIER if item["collection"] == "brief" else AU_VERIFIER
            verification_run = checkpoint["verification_run"]
            pending_request = checkpoint.get("verifier_request_pending")
            pending_second_pass = (deepcopy(pending_request) if pending_request and
                                   pending_request.get("pass_index") == 1 else None)
            if pending_second_pass:
                pending_request = None
            request_key = {"item_id": item_id, "pass_index": 0,
                           "verification_run": verification_run}
            payload = {"item": alias_item_sources({key: deepcopy(value) for key, value in item.items()
                                                    if key not in {"review", "excerpts"}}, stable_to_handle),
                "source_handle_scope": {"case_id": row["case_id"], "source_hash": row["source_hash"]},
                "source_context": [_alias_unit(unit, stable_to_handle) for unit in context],
                "available_context_handles": [stable_to_handle[source_id]
                    for source_id in sorted(requestable - provided)]}
            if pending_request:
                if any(pending_request.get(key) != value for key, value in request_key.items()):
                    raise ValueError("verifier_request_pending_for_other_item")
                payload = deepcopy(pending_request["payload"])
            else:
                checkpoint["verifier_request_pending"] = {**request_key,
                    "phase": "request_pending", "payload": deepcopy(payload)}
                save(checkpoint_path, checkpoint)
            response = _complete(endpoint, config["verifier"], prompt, payload,
                experiment=experiment, row=row, stage=f"{item['collection']}_verifier",
                turn=f"{verification_run}:{index}:0", item_id=item_id,
                cache_path=output / "responses" /
                    f"verifier_r{verification_run}_{index:03d}_0.json")
            review = _verify_with_protocol_repair(
                response=response, collection=item["collection"], item=item,
                context=context, provided=provided, requestable=requestable,
                source_map=source_map, stable_to_handle=stable_to_handle,
                alias_to_stable=alias_to_stable, checkpoint=checkpoint,
                checkpoint_path=checkpoint_path, endpoint=endpoint,
                model=config["verifier"], experiment=experiment, row=row,
                index=index, pass_index=0, output=output,
                verification_run=verification_run)
            if review["status"] == "needs_review" and review["request_source_ids"]:
                context = _review_context(item, paragraphs, source_map,
                                          set(review["request_source_ids"]))
                provided = {unit["source_id"] for unit in context}
                checkpoint["verifier_source_ids"] = sorted(
                    set(checkpoint["verifier_source_ids"]) | provided)
                payload = {"item": payload["item"],
                    "source_handle_scope": {"case_id": row["case_id"],
                                            "source_hash": row["source_hash"]},
                    "source_context": [_alias_unit(unit, stable_to_handle) for unit in context],
                    "available_context_handles": [],
                    "previous_review": _alias_review_sources(review, stable_to_handle)}
                if pending_second_pass:
                    payload = deepcopy(pending_second_pass["payload"])
                    checkpoint["verifier_request_pending"] = pending_second_pass
                else:
                    checkpoint["verifier_request_pending"] = {"item_id": item_id,
                        "pass_index": 1, "verification_run": verification_run,
                        "phase": "request_pending", "payload": deepcopy(payload)}
                save(checkpoint_path, checkpoint)
                response = _complete(endpoint, config["verifier"], prompt, payload,
                    experiment=experiment, row=row, stage=f"{item['collection']}_verifier",
                    turn=f"{verification_run}:{index}:1", item_id=item_id,
                    cache_path=output / "responses" /
                        f"verifier_r{verification_run}_{index:03d}_1.json")
                review = _verify_with_protocol_repair(
                    response=response, collection=item["collection"], item=item,
                    context=context, provided=provided, requestable=provided,
                    source_map=source_map, stable_to_handle=stable_to_handle,
                    alias_to_stable=alias_to_stable, checkpoint=checkpoint,
                    checkpoint_path=checkpoint_path, endpoint=endpoint,
                    model=config["verifier"], experiment=experiment, row=row,
                    index=index, pass_index=1, output=output,
                    verification_run=verification_run)
            review.update({"model": config["verifier"], "prompt_version": VERSION,
                           "checked_at": datetime.now(timezone.utc).isoformat()})
            item["review"] = review
            if review.get("protocol_valid"):
                old_ids = set(checkpoint.get("recheck_error_ids", {}).get(item_id, []))
                for error in checkpoint["verifier_protocol_errors"]:
                    if error["error_id"] in old_ids and error.get("status") == "unresolved":
                        error["status"] = "resolved"
                        error["resolved_by"] = f"verifier_recheck_{verification_run}"
            checkpoint["next_verifier_index"] += 1
            checkpoint["verifier_request_pending"] = None
            if _has_unresolved_protocol(checkpoint):
                checkpoint["stage"] = "incomplete_protocol"
            save(checkpoint_path, checkpoint)

        if checkpoint["stage"] == "verifying":
            checkpoint["stage"] = "complete"
            save(checkpoint_path, checkpoint)
        if checkpoint["stage"] == "inconsistent_output":
            result = _result(row, text, units, checkpoint, "incomplete",
                             "semantic_selection_inconsistent")
            result["semantic_status"] = "inconsistent_output"
        elif checkpoint["stage"] == "incomplete_protocol":
            result = _result(row, text, units, checkpoint, "incomplete",
                             "unresolved_protocol_error")
        else:
            result = _result(row, text, units, checkpoint, "completed",
                             "verification_complete")
    except BudgetStop:
        result = _result(row, text, units, checkpoint, "incomplete_budget",
                         "shared_budget_exhausted")
    save(output / "trace.json", checkpoint["trace"])
    save(output / "case.json", result)
    return result
