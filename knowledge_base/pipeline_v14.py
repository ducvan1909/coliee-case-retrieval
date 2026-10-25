"""V14 candidate compilation and grouped, revision-aware source scans."""

from __future__ import annotations

from copy import deepcopy

from . import schema_v12, schema_v14
from .pipeline_v10 import (_call, _items, _nearby_source_ids, _ordered_sources,
                           _snapshot)
from .pipeline_v13 import _compatible_candidates, _local_revision_candidates
from .source import compact_opened_sources, save
from .state_v9 import apply_operations_independently


def build_case_v14(row, endpoint, config, size, steps, output):
    from .pipeline_v13 import build_case_v13
    return build_case_v13(row, endpoint, config, size, steps, output,
                          schema_v14.POLICY)


def available_scan_modes(checkpoint, entries, supplied, source_map, paragraphs,
                         stable_to_handle):
    result = {}
    group = tuple(checkpoint["pending_source_ids"])
    for entry in entries:
        if entry["status"] != "active":
            continue
        item = checkpoint["state"]["items"][entry["id"]]
        pool = _compatible_candidates(_local_revision_candidates(
            supplied, item["source_refs"], source_map, paragraphs),
            item["source_refs"], source_map)
        seen = set(checkpoint.get("scan_seen", {}).get(entry["id"], []))
        selected = {ref["source_id"] for ref in item["source_refs"]}
        modes = set()
        if pool - seen - selected:
            modes.add("scan_extend")
        if pool and [entry["id"], list(group)] not in checkpoint.get(
                "reconsider_done", []):
            modes.add("scan_reconsider")
        result[entry["handle"]] = modes
    return result


def extraction_operations(response, entries, manifest):
    operations, audit, revisions, uncertain = [], [], [], []
    for entry in entries:
        choice = response["decisions"][entry["handle"]]
        action = choice["choice"]
        audit.append({"item_id": entry["id"], "revision": entry["revision"],
                      "choice": action})
        if action in {"scan_extend", "scan_reconsider"}:
            revisions.append({"item_id": entry["id"], "mode": action,
                              "reason": choice["reason"]})
        elif action != "keep":
            operations.append({"op": action, "id": entry["id"],
                "revision": entry["revision"], "reason": choice["reason"]})
    paragraphs = {p["source_id"]: p for p in manifest["opened_sources"]}

    def add(anchor, collection, reason):
        for target in (("brief", "aus") if collection == "both" else (collection,)):
            item = {"source_refs": [{"source_id": anchor, "role": "primary",
                                      "attribution": "unknown"}]}
            if target == "brief":
                item["kind"] = "facts"
            else:
                item["treatment"] = {"value": "unknown",
                    "authority_source_ids": [], "response_source_ids": []}
            operations.append({"op": "add", "collection": target,
                               "item": item, "reason": reason})

    for paragraph_id in manifest["candidate_paragraph_ids"]:
        action = response["choices"][paragraph_id]
        audit.append({"source_id": paragraph_id, "choice": action})
        if action == "uncertain":
            uncertain.append({"source_id": paragraph_id,
                              "reason": "model_marked_uncertain"})
        elif action in {"brief", "aus", "both"}:
            add(paragraph_id, action, "model_selected_paragraph")
        elif action == "sentences":
            for sentence in paragraphs[paragraph_id]["sentences"]:
                sentence_id = sentence["source_id"]
                label = response["choices"][sentence_id]
                if label == "uncertain":
                    uncertain.append({"source_id": sentence_id,
                                      "reason": "model_marked_uncertain"})
                elif label != "skip":
                    add(sentence_id, label, "model_selected_sentence")
    return operations, audit, revisions, uncertain


def queue_scans(checkpoint, phase, turn, revisions, applied, supplied,
                source_map, paragraphs):
    if checkpoint["source_scan_queue"]:
        raise ValueError("unfinished_source_scan_queue")
    queue = []
    for requested in revisions:
        item = checkpoint["state"]["items"][requested["item_id"]]
        pool = _compatible_candidates(_local_revision_candidates(
            supplied, item["source_refs"], source_map, paragraphs),
            item["source_refs"], source_map)
        if requested["mode"] == "scan_extend":
            pool -= set(checkpoint["scan_seen"].get(item["id"], []))
            pool -= {ref["source_id"] for ref in item["source_refs"]}
        if pool:
            queue.append({"item_id": item["id"], "mode": requested["mode"],
                "reason": requested["reason"], "origin": [phase, turn],
                "group": checkpoint["pending_source_ids"],
                "candidates": _ordered_sources(pool, source_map),
                "cursor": 0, "selected": ([ref["source_id"] for ref in
                    item["source_refs"]] if requested["mode"] == "scan_extend" else [])})
    for event in applied:
        if event["op"] != "add":
            continue
        item = checkpoint["state"]["items"][event["id"]]
        anchor = item["source_refs"][0]["source_id"]
        pool = _compatible_candidates(_nearby_source_ids(
            anchor, supplied, source_map, paragraphs), item["source_refs"], source_map)
        if pool:
            queue.append({"item_id": item["id"], "mode": "scan_extend",
                "reason": event["reason"], "origin": [phase, turn],
                "group": checkpoint["pending_source_ids"],
                "candidates": _ordered_sources(pool, source_map),
                "cursor": 0, "selected": [anchor]})
    checkpoint["source_scan_queue"] = queue


def _batch(checkpoint, source_map, stable_to_handle):
    item_handles = {entry["id"]: entry["handle"] for entry in
        _items(checkpoint, stable_to_handle)[0]}
    chosen, pairs, task_indexes = [], {}, {}
    for index, task in enumerate(checkpoint["source_scan_queue"]):
        values = []
        for source in task["candidates"][task["cursor"]:]:
            if source not in chosen and len(chosen) >= schema_v12.SOURCE_BATCH_SIZE:
                break
            if source not in chosen:
                chosen.append(source)
            values.append(source)
        if values:
            handle = item_handles[task["item_id"]]
            pairs[handle] = [stable_to_handle[source] for source in values]
            task_indexes[handle] = index
    if not chosen:
        raise ValueError("empty_source_scan_batch")
    shown = set(chosen)
    for task in checkpoint["source_scan_queue"]:
        if task["item_id"] in {checkpoint["source_scan_queue"][i]["item_id"]
                              for i in task_indexes.values()}:
            shown.update(ref["source_id"] for ref in checkpoint["state"]["items"][
                task["item_id"]]["source_refs"])
    shown.update(source_map[source]["parent_id"] for source in list(shown)
                 if source_map[source].get("parent_id"))
    return chosen, pairs, task_indexes, shown


def scan_one_batch(checkpoint, checkpoint_path, output, endpoint, config,
                   experiment, row, source_map, stable_to_handle, alias_to_stable,
                   policy=schema_v14.POLICY, schema_module=schema_v14):
    from .pipeline_v10 import _call
    chosen, pairs, indexes, shown = _batch(checkpoint, source_map, stable_to_handle)
    schema = schema_module.scan_schema(pairs)
    manifest = {"phase": "source_scan", "case_id": row["case_id"],
        "source_hash": row["source_hash"], "schema": schema,
        "schema_hash": schema_module.schema_hash(schema), "items": [],
        "candidate_sources": [stable_to_handle[source] for source in chosen],
        "scan_pairs": pairs, "scan_task_indexes": indexes,
        "opened_sources": compact_opened_sources(source_map, shown, stable_to_handle)}
    turn = checkpoint["source_scan_turn"]
    response = _call(checkpoint, checkpoint_path, output, endpoint, config,
        experiment, row, "source_scan", turn, manifest, policy)
    record = checkpoint["request_journal"][f"source_scan:{turn}"]
    if record["status"] == "applied":
        raise ValueError("applied_source_scan_not_advanced")
    saved = record["payload"]["manifest"]
    if saved["schema_hash"] != schema_module.schema_hash(saved["schema"]):
        raise ValueError("journal_schema_checksum_mismatch")
    errors = schema_module.validate(response, saved["schema"])
    applied, noops = [], []
    if not errors:
        queue = deepcopy(checkpoint["source_scan_queue"])
        seen = deepcopy(checkpoint["scan_seen"])
        reconsider_done = deepcopy(checkpoint.get("reconsider_done", []))
        completed = []
        for handle, source_handles in saved["scan_pairs"].items():
            task = queue[saved["scan_task_indexes"][handle]]
            candidates = [alias_to_stable[source] for source in source_handles]
            task["selected"].extend(source for source in candidates
                if response["choices"][handle][stable_to_handle[source]] == "include")
            task["cursor"] += len(candidates)
            seen[task["item_id"]] = sorted(set(seen.get(task["item_id"], [])) |
                                            set(candidates))
            if task["cursor"] == len(task["candidates"]):
                completed.append(task)
                if task["mode"] == "scan_reconsider":
                    marker = [task["item_id"], task["group"]]
                    if marker not in reconsider_done:
                        reconsider_done.append(marker)
        operations = []
        for task in completed:
            item = checkpoint["state"]["items"][task["item_id"]]
            selected = list(dict.fromkeys(task["selected"]))
            if not selected:
                errors.append({"path": "$.choices", "error_code": "empty_source_selection"})
                break
            previously_selected = {ref["source_id"] for ref in item["source_refs"]}
            if not set(selected) <= previously_selected | set(seen[task["item_id"]]):
                errors.append({"path": "$.choices",
                               "error_code": "scan_selection_not_previously_provided"})
                break
            selected = _ordered_sources(set(selected), source_map)
            old = {ref["source_id"]: ref for ref in item["source_refs"]}
            if selected == [ref["source_id"] for ref in item["source_refs"]]:
                continue
            refs = [{"source_id": stable_to_handle[source],
                "role": old.get(source, {}).get("role", "context"),
                "attribution": old.get(source, {}).get("attribution", "unknown")}
                for source in selected]
            if item["collection"] == "aus" and not any(
                    ref["role"] == "primary" for ref in refs):
                refs[0]["role"] = "primary"
            changes = {"source_refs": refs}
            if item["collection"] == "aus":
                changes["treatment"] = {"value": "unknown",
                    "authority_source_ids": [], "response_source_ids": []}
            operations.append({"op": "update", "id": item["id"],
                "revision": item["revision"], "changes": changes,
                "reason": task["reason"]})
        if not errors:
            supplied = set(shown) | {source for task in completed
                for source in task["selected"]} | {ref["source_id"] for task in completed
                for ref in checkpoint["state"]["items"][task["item_id"]]["source_refs"]}
            new_state, applied, rejected, noops = apply_operations_independently(
                checkpoint["state"], operations, supplied, source_map,
                row["source_hash"], row["case_id"], aliases=alias_to_stable,
                stable_to_handle=stable_to_handle,
                allowed_target_ids={task["item_id"] for task in completed},
                phase="reader")
            if rejected:
                errors.extend({"path": "$.choices", "error_code": item["error_code"]}
                              for item in rejected)
            else:
                checkpoint["state"] = new_state
                checkpoint["scan_seen"] = seen
                checkpoint["reconsider_done"] = reconsider_done
                checkpoint["source_scan_queue"] = [task for task in queue
                    if task not in completed]
                checkpoint["trace"].append({"phase": "source_scan", "turn": turn,
                    "item_count": len(saved["scan_pairs"]),
                    "candidate_count": len(saved["candidate_sources"]),
                    "applied": applied, "noop_duplicates": noops})
    if errors:
        checkpoint["protocol_errors"].extend({"phase": "source_scan", "turn": turn,
            **error} for error in errors)
        checkpoint["stage"] = "incomplete"
        checkpoint["stop_reason"] = "invalid_constrained_response"
    elif not checkpoint["source_scan_queue"]:
        resume = checkpoint.pop("source_scan_resume")
        checkpoint["stage"], checkpoint["turn"] = resume["stage"], resume["turn"]
    checkpoint["phase_source_ids"]["source_scan"] = sorted(set(
        checkpoint["phase_source_ids"].get("source_scan", [])) | shown)
    checkpoint["source_scan_turn"] += 1
    record["status"] = "applied"
    record["post_request_snapshot"] = _snapshot(checkpoint["state"])
    save(checkpoint_path, checkpoint)
