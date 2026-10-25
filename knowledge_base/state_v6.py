"""Host-owned V6 state with active, deferred and deleted item lifecycles."""

from __future__ import annotations

from copy import deepcopy

from .schema_v6 import (AGENT_SCHEMA, ATTRIBUTIONS, BRIEF_KINDS, FORBIDDEN_KEYS,
                        SOURCE_ROLES, TREATMENTS)


def initial_state() -> dict:
    return {"items": {}, "counters": {"brief": 0, "aus": 0}, "history": []}


def public_items(state: dict, status: str | None = None) -> list[dict]:
    values = []
    for item in state["items"].values():
        if status is not None and item["status"] != status:
            continue
        values.append({key: deepcopy(value) for key, value in item.items()
                       if key not in {"source_hash"}})
    return values


def _reject_forbidden(value: object) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_KEYS.intersection(value)
        if forbidden:
            raise ValueError("forbidden_field:" + sorted(forbidden)[0])
        for child in value.values():
            _reject_forbidden(child)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden(child)


def _resolve_source(value: object, source_map: dict[str, dict], aliases: dict[str, str]) -> str:
    if not isinstance(value, str) or value not in aliases:
        raise ValueError("source_unknown_or_unread")
    stable = aliases[value]
    if stable not in source_map:
        raise ValueError("source_unknown_or_unread")
    return stable


def _source_refs(value: object, opened: set[str], source_map: dict[str, dict],
                 aliases: dict[str, str], require_primary: bool) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ValueError("invalid_source_refs")
    result, selected = [], set()
    for ref in value:
        if not isinstance(ref, dict) or set(ref) != set(AGENT_SCHEMA["source_ref"]["required"]):
            raise ValueError("invalid_source_ref_shape")
        stable = _resolve_source(ref["source_id"], source_map, aliases)
        if stable not in opened:
            raise ValueError("source_unknown_or_unread")
        if ref["role"] not in SOURCE_ROLES:
            raise ValueError("invalid_source_role")
        if ref["attribution"] not in ATTRIBUTIONS:
            raise ValueError("invalid_attribution")
        if stable in selected:
            raise ValueError("duplicate_source_ref")
        selected.add(stable)
        result.append({"source_id": stable, "role": ref["role"],
                       "attribution": ref["attribution"]})
    for source_id in selected:
        unit = source_map[source_id]
        if unit["unit_type"] == "sentence" and unit.get("parent_id") in selected:
            raise ValueError("parent_child_overlap")
        if unit["unit_type"] == "paragraph" and any(
                source_map[other].get("parent_id") == source_id for other in selected):
            raise ValueError("parent_child_overlap")
    if require_primary and not any(ref["role"] == "primary" for ref in result):
        raise ValueError("au_requires_primary")
    return result


def _treatment(value: object, selected: set[str], source_map: dict[str, dict],
               aliases: dict[str, str]) -> dict:
    required = set(AGENT_SCHEMA["au"]["treatment"]["required"])
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("invalid_treatment_shape")
    label = value["value"]
    if label not in TREATMENTS:
        raise ValueError("invalid_treatment")
    authority, response = value["authority_source_ids"], value["response_source_ids"]
    if (not isinstance(authority, list) or not isinstance(response, list) or
            any(not isinstance(source_id, str) for source_id in authority + response)):
        raise ValueError("invalid_treatment_sources")
    authority = [_resolve_source(source_id, source_map, aliases) for source_id in authority]
    response = [_resolve_source(source_id, source_map, aliases) for source_id in response]
    if len(authority) != len(set(authority)) or len(response) != len(set(response)):
        raise ValueError("duplicate_treatment_source")
    if not set(authority + response).issubset(selected):
        raise ValueError("treatment_source_not_selected")
    if label == "unknown" and (authority or response):
        raise ValueError("unknown_treatment_has_evidence")
    if label != "unknown" and (not authority or not response):
        raise ValueError("treatment_requires_authority_and_response")
    return {"value": label, "authority_source_ids": authority,
            "response_source_ids": response}


def _item(collection: str, value: object, opened: set[str], source_map: dict[str, dict],
          aliases: dict[str, str], source_hash: str, *, partial: bool = False,
          base: dict | None = None, stable_to_handle: dict[str, str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise ValueError("item_must_be_object")
    _reject_forbidden(value)
    contract = "brief" if collection == "brief" else "au"
    allowed = set(AGENT_SCHEMA[contract]["required"])
    if not set(value).issubset(allowed) or (not partial and set(value) != allowed):
        raise ValueError("unexpected_or_missing_item_fields")
    merged = {}
    if base:
        merged = {key: deepcopy(base[key]) for key in allowed}
        if stable_to_handle:
            for ref in merged["source_refs"]:
                ref["source_id"] = stable_to_handle[ref["source_id"]]
            if "treatment" in merged:
                for key in ("authority_source_ids", "response_source_ids"):
                    merged["treatment"][key] = [stable_to_handle[source_id]
                        for source_id in merged["treatment"][key]]
    merged.update(deepcopy(value))
    if set(merged) != allowed:
        raise ValueError("incomplete_update")
    refs = _source_refs(merged["source_refs"], opened, source_map, aliases,
                        require_primary=collection == "aus")
    clean = {"source_refs": refs, "source_hash": source_hash}
    if collection == "brief":
        if merged["kind"] not in BRIEF_KINDS:
            raise ValueError("invalid_brief_kind")
        clean["kind"] = merged["kind"]
    else:
        clean["treatment"] = _treatment(
            merged["treatment"], {ref["source_id"] for ref in refs}, source_map, aliases)
    return clean


def _signature(collection: str, item: dict) -> tuple:
    treatment = item.get("treatment", {})
    return (collection, item["source_hash"], item.get("kind"),
            tuple((ref["source_id"], ref["role"], ref["attribution"])
                  for ref in item["source_refs"]), treatment.get("value"),
            tuple(treatment.get("authority_source_ids", [])),
            tuple(treatment.get("response_source_ids", [])))


def apply_operations_independently(state: dict, operations: object, opened: set[str],
                                   source_map: dict[str, dict], source_hash: str,
                                   case_id: str, *, aliases: dict[str, str],
                                   stable_to_handle: dict[str, str],
                                   allowed_target_ids: set[str]) -> tuple[dict, list[dict], list[dict]]:
    if not isinstance(operations, list):
        raise ValueError("operations_must_be_list")
    working, applied, rejected, noops = deepcopy(state), [], [], []
    added_ids, removed_ids = [], []
    for index, operation in enumerate(operations):
        try:
            if not isinstance(operation, dict) or operation.get("op") not in AGENT_SCHEMA["operations"]:
                raise ValueError("invalid_operation")
            op = operation["op"]
            if set(operation) != set(AGENT_SCHEMA["operations"][op]):
                raise ValueError(f"invalid_{op}_operation")
            if not isinstance(operation["reason"], str) or not operation["reason"].strip():
                raise ValueError("operation_reason_required")
            if op == "add":
                if operation["collection"] not in {"brief", "aus"}:
                    raise ValueError("invalid_collection")
                collection = operation["collection"]
                clean = _item(collection, operation["item"], opened, source_map, aliases,
                              source_hash)
                duplicate = next((item for item in working["items"].values()
                    if item["status"] == "active" and
                    _signature(item["collection"], item) == _signature(collection, clean)), None)
                if duplicate is not None:
                    noops.append({"op": "resolved_noop_duplicate", "duplicate_of": duplicate["id"],
                        "duplicate_revision": duplicate["revision"],
                        "operation_index": index, "operation": deepcopy(operation),
                        "reason": operation["reason"]})
                    continue
                serial = working["counters"][collection]
                working["counters"][collection] += 1
                item_id = f"{case_id}:{collection}:{serial:03d}"
                record = {"id": item_id, "collection": collection, "revision": 1,
                          "status": "active", **clean}
                working["items"][item_id] = record
                added_ids.append(item_id)
                event = {"op": op, "id": item_id, "revision": 1,
                         "reason": operation["reason"], "operation_index": index,
                         "operation": deepcopy(operation), "result": deepcopy(record)}
            else:
                if operation["id"] not in allowed_target_ids:
                    raise ValueError("target_not_in_request_snapshot")
                current = working["items"].get(operation["id"])
                if not current or operation["revision"] != current["revision"]:
                    raise ValueError("stale_or_unknown_target")
                before = deepcopy(current)
                if op == "update":
                    if current["status"] == "deleted":
                        raise ValueError("cannot_update_deleted_item")
                    keys = {"kind", "source_refs"} if current["collection"] == "brief" else {
                        "source_refs", "treatment"}
                    clean = _item(current["collection"], operation["changes"], opened,
                                  source_map, aliases, source_hash, partial=True,
                                  base={key: current[key] for key in keys},
                                  stable_to_handle=stable_to_handle)
                    current.update(clean)
                elif op == "remove":
                    if current["status"] == "deleted":
                        raise ValueError("item_already_deleted")
                    current["status"] = "deleted"
                    removed_ids.append(current["id"])
                elif op == "defer":
                    if current["status"] != "active":
                        raise ValueError("only_active_item_can_be_deferred")
                    current["status"] = "deferred"
                else:
                    if current["status"] != "deferred":
                        raise ValueError("only_deferred_item_can_be_restored")
                    current["status"] = "active"
                current["revision"] += 1
                event = {"op": op, "id": current["id"], "revision": current["revision"],
                         "reason": operation["reason"], "operation_index": index,
                         "operation": deepcopy(operation), "previous": before,
                         "result": deepcopy(current)}
            working["history"].append(event)
            applied.append(event)
        except ValueError as exc:
            rejected.append({"index": index, "error_code": str(exc),
                             "operation": deepcopy(operation)})
    if added_ids and removed_ids:
        lineage = {"added_ids": added_ids, "removed_ids": removed_ids,
                   "operation_indexes": [event["operation_index"] for event in applied
                                          if event["id"] in set(added_ids + removed_ids)]}
        for event in applied:
            if event["id"] in set(added_ids + removed_ids):
                event["lineage"] = deepcopy(lineage)
        for event in working["history"][-len(applied):]:
            if event["id"] in set(added_ids + removed_ids):
                event["lineage"] = deepcopy(lineage)
    return working, applied, rejected, noops

