"""Host-owned cumulative state and strict V5 contract validation."""

from __future__ import annotations

from copy import deepcopy

from .schema import (AGENT_SCHEMA, ATTRIBUTIONS, BRIEF_KINDS, FORBIDDEN_KEYS, SOURCE_ROLES,
                     TREATMENTS)


def initial_state() -> dict:
    return {"items": {}, "counters": {"brief": 0, "aus": 0}, "history": []}


def public_items(state: dict) -> list[dict]:
    return [{key: deepcopy(value) for key, value in item.items()
             if key not in {"excerpts", "review"}}
            for item in state["items"].values() if not item["deleted"]]


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


def _resolve_source(value: object, source_map: dict[str, dict],
                    source_aliases: dict[str, str] | None) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_source_handle")
    if source_aliases is not None and value not in source_aliases:
        raise ValueError("source_unknown_or_unread")
    source_id = (source_aliases or {}).get(value, value)
    if source_id not in source_map:
        raise ValueError("source_unknown_or_unread")
    return source_id


def _source_refs(value: object, opened: set[str], source_map: dict[str, dict],
                 require_primary: bool,
                 source_aliases: dict[str, str] | None = None) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ValueError("invalid_source_refs")
    selected, clean = set(), []
    for ref in value:
        if not isinstance(ref, dict) or set(ref) != set(AGENT_SCHEMA["source_ref"]["required"]):
            raise ValueError("invalid_source_ref_shape")
        source_id = _resolve_source(ref["source_id"], source_map, source_aliases)
        role, attribution = ref["role"], ref["attribution"]
        if source_id not in opened:
            raise ValueError("source_unknown_or_unread")
        if role not in SOURCE_ROLES:
            raise ValueError("invalid_source_role")
        if attribution not in ATTRIBUTIONS:
            raise ValueError("invalid_attribution")
        if source_id in selected:
            raise ValueError("duplicate_source_ref")
        selected.add(source_id)
        clean.append({"source_id": source_id, "role": role, "attribution": attribution})
    for source_id in selected:
        unit = source_map[source_id]
        if unit["unit_type"] == "sentence" and unit.get("parent_id") in selected:
            raise ValueError("parent_child_overlap")
        if unit["unit_type"] == "paragraph" and any(
                source_map[other].get("parent_id") == source_id for other in selected):
            raise ValueError("parent_child_overlap")
    if require_primary and not any(ref["role"] == "primary" for ref in clean):
        raise ValueError("au_requires_primary")
    return clean


def _treatment(value: object, selected: set[str], source_map: dict[str, dict],
               source_aliases: dict[str, str] | None = None) -> dict:
    fields = set(AGENT_SCHEMA["au"]["treatment"]["required"])
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid_treatment_shape")
    label = value["value"]
    authority = value["authority_source_ids"]
    response = value["response_source_ids"]
    if label not in TREATMENTS:
        raise ValueError("invalid_treatment")
    if (not isinstance(authority, list) or not isinstance(response, list) or
            any(not isinstance(source_id, str) for source_id in authority + response)):
        raise ValueError("invalid_treatment_sources")
    authority = [_resolve_source(source_id, source_map, source_aliases)
                 for source_id in authority]
    response = [_resolve_source(source_id, source_map, source_aliases)
                for source_id in response]
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
          source_hash: str, partial: bool = False, base: dict | None = None,
          source_aliases: dict[str, str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise ValueError("item_must_be_object")
    _reject_forbidden(value)
    allowed = set(AGENT_SCHEMA[collection if collection == "brief" else "au"]["required"])
    if not set(value).issubset(allowed) or (not partial and set(value) != allowed):
        raise ValueError("unexpected_or_missing_item_fields")
    base_value = ({key: deepcopy(base[key]) for key in allowed} if base else {})
    if base_value and source_aliases is not None:
        stable_to_alias = {stable: alias for alias, stable in source_aliases.items()}
        for ref in base_value["source_refs"]:
            ref["source_id"] = stable_to_alias[ref["source_id"]]
        if "treatment" in base_value:
            for key in ("authority_source_ids", "response_source_ids"):
                base_value["treatment"][key] = [stable_to_alias[source_id]
                    for source_id in base_value["treatment"][key]]
    merged = base_value | deepcopy(value)
    if set(merged) != allowed:
        raise ValueError("incomplete_update")
    refs = _source_refs(merged["source_refs"], opened, source_map,
                        require_primary=collection == "aus",
                        source_aliases=source_aliases)
    clean = {"source_refs": refs, "source_hash": source_hash}
    if collection == "brief":
        if merged["kind"] not in BRIEF_KINDS:
            raise ValueError("invalid_brief_kind")
        clean["kind"] = merged["kind"]
    else:
        clean["treatment"] = _treatment(
            merged["treatment"], {ref["source_id"] for ref in refs}, source_map,
            source_aliases)
    return clean


def _signature(collection: str, item: dict) -> tuple:
    treatment = item.get("treatment", {})
    return (collection, item.get("kind"),
            tuple((ref["source_id"], ref["role"], ref["attribution"])
                  for ref in item["source_refs"]),
            treatment.get("value"), tuple(treatment.get("authority_source_ids", [])),
            tuple(treatment.get("response_source_ids", [])))


def apply_operations(state: dict, operations: object, opened: set[str],
                     source_map: dict[str, dict], source_hash: str,
                     case_id: str, *, source_aliases: dict[str, str] | None = None,
                     allowed_target_ids: set[str] | None = None) -> tuple[dict, list[dict]]:
    if not isinstance(operations, list):
        raise ValueError("operations_must_be_list")
    working, applied = deepcopy(state), []
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("op") not in {"add", "update", "remove"}:
            raise ValueError("invalid_operation")
        kind = operation["op"]
        if kind == "add":
            if (set(operation) != set(AGENT_SCHEMA["operations"]["add"]) or
                    operation["collection"] not in {"brief", "aus"}):
                raise ValueError("invalid_add_operation")
            collection = operation["collection"]
            clean = _item(collection, operation["item"], opened, source_map, source_hash,
                          source_aliases=source_aliases)
            if any(not existing["deleted"] and _signature(existing["collection"], existing) == _signature(collection, clean)
                   for existing in working["items"].values()):
                raise ValueError("duplicate_active_item")
            serial = working["counters"][collection]
            working["counters"][collection] += 1
            item_id = f"{case_id}:{collection}:{serial:03d}"
            record = {"id": item_id, "collection": collection, "revision": 1,
                      "deleted": False, "review": None, **clean}
            working["items"][item_id] = record
            event = {"op": "add", "id": item_id, "revision": 1,
                     "operation": deepcopy(operation), "result": deepcopy(record)}
        elif kind == "update":
            if set(operation) != set(AGENT_SCHEMA["operations"]["update"]):
                raise ValueError("invalid_update_operation")
            if allowed_target_ids is not None and operation["id"] not in allowed_target_ids:
                raise ValueError("target_not_in_request_snapshot")
            current = working["items"].get(operation["id"])
            if not current or current["deleted"] or operation["revision"] != current["revision"]:
                raise ValueError("stale_or_unknown_update")
            collection = current["collection"]
            keys = {"kind", "source_refs"} if collection == "brief" else {"source_refs", "treatment"}
            clean = _item(collection, operation["changes"], opened, source_map, source_hash,
                          partial=True, base={key: current[key] for key in keys},
                          source_aliases=source_aliases)
            before = deepcopy(current)
            current.update(clean)
            current["revision"] += 1
            current["review"] = None
            event = {"op": "update", "id": current["id"], "revision": current["revision"],
                     "operation": deepcopy(operation), "previous": before,
                     "result": deepcopy(current)}
        else:
            if set(operation) != set(AGENT_SCHEMA["operations"]["remove"]):
                raise ValueError("invalid_remove_operation")
            if allowed_target_ids is not None and operation["id"] not in allowed_target_ids:
                raise ValueError("target_not_in_request_snapshot")
            current = working["items"].get(operation["id"])
            if not current or current["deleted"] or operation["revision"] != current["revision"]:
                raise ValueError("stale_or_unknown_remove")
            current["deleted"] = True
            current["revision"] += 1
            current["review"] = None
            event = {"op": "remove", "id": current["id"], "revision": current["revision"],
                     "operation": deepcopy(operation), "result": deepcopy(current)}
        working["history"].append(event)
        applied.append(event)
    return working, applied


def apply_operations_independently(state: dict, operations: object, opened: set[str],
                                   source_map: dict[str, dict], source_hash: str,
                                   case_id: str, *,
                                   source_aliases: dict[str, str] | None = None,
                                   allowed_target_ids: set[str] | None = None) -> tuple[dict, list[dict], list[dict]]:
    if not isinstance(operations, list):
        raise ValueError("operations_must_be_list")
    working, applied, rejected = deepcopy(state), [], []
    for index, operation in enumerate(operations):
        try:
            candidate, events = apply_operations(
                working, [operation], opened, source_map, source_hash, case_id,
                source_aliases=source_aliases,
                allowed_target_ids=allowed_target_ids)
        except ValueError as exc:
            rejected.append({"index": index, "error_code": str(exc)})
        else:
            working = candidate
            applied.extend(events)
    return working, applied, rejected
