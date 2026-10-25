"""Audited, offline inheritance of the interrupted V6 calibration case."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

from .endpoint import _read_cache
from .pipeline_v6 import _result, _save_snapshot, _snapshot_value, _repair_target_matches
from .prompts_v6 import VERSION
from .schema_v6 import SCHEMA_VERSION
from .source import digest, load_source, save, source_handles, source_structure
from .state_v6 import apply_operations_independently

EXPECTED_CASE = "013948"
EXPECTED_REJECTION = "013948:selection_repair:0:op:6"
EXPECTED_DUPLICATE = "013948:aus:001"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def inspect_inheritance(source_experiment: Path, target_experiment: Path,
                        manifest: dict, fingerprint: dict, ledger_path: Path) -> dict:
    source_experiment, target_experiment = Path(source_experiment), Path(target_experiment)
    old_config = _read(source_experiment / "config.json")
    if (old_config.get("schema_version") != SCHEMA_VERSION or
            old_config.get("prompt_version") != "kb-pilot-v6-repair-loops"):
        raise ValueError("legacy_experiment_version_mismatch")
    for key in ("manifest_hash", "reader", "repair", "endpoint_hash", "window_chars",
                "read_steps", "max_tokens", "temperature", "top_p", "reasoning_effort",
                "reserve_usd", "budget_usd", "timeout_seconds", "startup_wait_seconds"):
        if old_config.get(key) != fingerprint.get(key):
            raise ValueError(f"legacy_experiment_config_mismatch:{key}")
    if fingerprint.get("prompt_version") != VERSION:
        raise ValueError("target_prompt_version_mismatch")
    row = next((value for value in manifest["cases"]
                if value["case_id"] == EXPECTED_CASE), None)
    if row is None or EXPECTED_CASE not in manifest["splits"]["calibration"]:
        raise ValueError("case_missing_from_calibration_manifest")
    text, source_hash = load_source(row["source"])
    if source_hash != row["source_hash"]:
        raise ValueError("source_changed_since_manifest")
    source_case = source_experiment / "calibration" / EXPECTED_CASE
    checkpoint_path = source_case / "checkpoint.json"
    case_path = source_case / "case.json"
    checkpoint, case = _read(checkpoint_path), _read(case_path)
    if (checkpoint.get("stage") != "incomplete_protocol" or
            checkpoint.get("schema_version") != 6 or
            checkpoint.get("source_hash") != source_hash or
            case.get("execution_status") != "incomplete"):
        raise ValueError("legacy_checkpoint_not_expected_incomplete_case")
    unresolved = [entry for entry in checkpoint["operation_rejections"]
                  if entry["status"] == "unresolved"]
    if (len(unresolved) != 1 or unresolved[0]["rejection_id"] != EXPECTED_REJECTION or
            unresolved[0].get("repair_error_code") != "duplicate_active_item" or
            any(entry["status"] == "unresolved" for entry in checkpoint["protocol_errors"])):
        raise ValueError("legacy_protocol_state_changed")
    if checkpoint.get("response_processing"):
        raise ValueError("legacy_response_processing_not_empty")
    if len(checkpoint["state"]["history"]) != len(case["history"]):
        raise ValueError("legacy_history_count_mismatch")
    original_hashes = {}
    ledger = _read(ledger_path)
    ledger_calls = ledger.get("calls", [])
    for key, record in checkpoint["request_journal"].items():
        stage, turn = key.rsplit(":", 1)
        cache_path = source_case / "responses" / f"{stage}_{turn}.json"
        if record["status"] != "applied" or not cache_path.exists():
            raise ValueError(f"legacy_request_not_cached:{key}")
        envelope = _read(cache_path)
        identity = envelope.get("identity", {})
        if (identity.get("request_id") != record["request_id"] or
                identity.get("payload_hash") != record["payload_hash"] or
                identity.get("system_hash") != digest(record["prompt"].encode("utf-8")) or
                identity.get("metadata", {}).get("source_hash") != source_hash or
                identity.get("metadata", {}).get("prompt_version") != old_config["prompt_version"] or
                identity.get("metadata", {}).get("case_id") != EXPECTED_CASE or
                not any(call.get("logical_request_id") == record["request_id"] and
                            call.get("status", "").startswith("completed") for call in ledger_calls)):
            raise ValueError(f"legacy_request_identity_mismatch:{key}")
        if _read_cache(cache_path, identity) != record["response"]:
            raise ValueError(f"legacy_response_mismatch:{key}")
        original_hashes[key] = digest(cache_path.read_bytes())
    repair = checkpoint["request_journal"]["selection_repair_protocol_repair:0"]["response"]
    matching = [entry for entry in repair["repairs"]
                if entry["rejection_id"] == EXPECTED_REJECTION]
    if len(matching) != 1 or matching[0]["operation"]["op"] != "add":
        raise ValueError("legacy_duplicate_repair_missing")
    paragraphs, units = source_structure(text, source_hash)
    del paragraphs
    source_map = {unit["source_id"]: unit for unit in units}
    stable_to_handle, alias_to_stable = source_handles(units)
    operation = matching[0]["operation"]
    state, events, rejected, noops = apply_operations_independently(
        checkpoint["state"], [operation], set(checkpoint["opened_source_ids"]),
        source_map, source_hash, EXPECTED_CASE, aliases=alias_to_stable,
        stable_to_handle=stable_to_handle,
        allowed_target_ids=set(checkpoint["state"]["items"]))
    if (events or rejected or len(noops) != 1 or state != checkpoint["state"] or
            noops[0]["duplicate_of"] != EXPECTED_DUPLICATE):
        raise ValueError("legacy_repair_not_exact_active_duplicate")
    target_case = target_experiment / "calibration" / EXPECTED_CASE
    if target_experiment.exists():
        target_config = target_experiment / "config.json"
        if not target_config.exists() or _read(target_config) != fingerprint:
            raise ValueError("target_experiment_fingerprint_mismatch")
        if target_case.exists():
            migration = target_case / "migration.json"
            if not migration.exists() or _read(migration).get("source_checkpoint_hash") != digest(checkpoint_path.read_bytes()):
                raise ValueError("existing_target_has_different_migration")
            return {"status": "already_migrated", "source_case": str(source_case),
                    "target_case": str(target_case), "duplicate_of": EXPECTED_DUPLICATE,
                    "ledger_reserved_usd": ledger.get("reserved_usd")}
    return {"status": "ready", "source_case": str(source_case),
        "target_case": str(target_case), "duplicate_of": EXPECTED_DUPLICATE,
        "duplicate_revision": noops[0]["duplicate_revision"],
        "source_checkpoint_hash": digest(checkpoint_path.read_bytes()),
        "source_config_hash": digest((source_experiment / "config.json").read_bytes()),
        "source_case_hash": digest(case_path.read_bytes()),
        "cache_hashes": original_hashes,
        "ledger_reserved_usd": ledger.get("reserved_usd")}


def inherit_case(source_experiment: Path, target_experiment: Path, manifest: dict,
                 fingerprint: dict, ledger_path: Path, *, execute: bool = False) -> dict:
    audit = inspect_inheritance(source_experiment, target_experiment, manifest,
                                fingerprint, ledger_path)
    if not execute or audit["status"] == "already_migrated":
        return audit
    source_case = Path(audit["source_case"])
    target_case = Path(audit["target_case"])
    target_experiment = Path(target_experiment)
    target_experiment.mkdir(parents=True, exist_ok=False)
    save(target_experiment / "config.json", fingerprint)
    shutil.copytree(source_case, target_case)
    checkpoint_path = target_case / "checkpoint.json"
    checkpoint = _read(checkpoint_path)
    record = next(entry for entry in checkpoint["operation_rejections"]
                  if entry["rejection_id"] == EXPECTED_REJECTION)
    repair = checkpoint["request_journal"]["selection_repair_protocol_repair:0"]["response"]
    operation = next(entry["operation"] for entry in repair["repairs"]
                     if entry["rejection_id"] == EXPECTED_REJECTION)
    noop = {"op": "resolved_noop_duplicate", "duplicate_of": EXPECTED_DUPLICATE,
        "duplicate_revision": audit["duplicate_revision"], "operation_index": 6,
        "operation": operation, "reason": operation["reason"],
        "stage": "selection_repair", "turn": 0,
        "response_path": record["response_path"],
        "repair_response_path": "responses/selection_repair_protocol_repair_0.json",
        "rejection_id": EXPECTED_REJECTION}
    record.update({"status": "resolved_noop_duplicate", "duplicate_of": EXPECTED_DUPLICATE,
                   "duplicate_revision": audit["duplicate_revision"],
                   "resolved_by": "offline_v6_protocol_fix",
                   "repair_operation": operation})
    checkpoint.setdefault("noop_operations", []).append(noop)
    processed = checkpoint["processed_responses"]["selection_repair:0"]
    processed.setdefault("noops", []).append(deepcopy(noop))
    for entry in processed["rejections"]:
        if entry["rejection_id"] == EXPECTED_REJECTION:
            entry.update(deepcopy(record))
    trace = next(entry for entry in checkpoint["trace"]
                 if entry["stage"] == "repair_selection" and entry["turn"] == 0)
    trace.setdefault("noops", []).append(deepcopy(noop))
    trace["protocol_rejected_unresolved"] = []
    checkpoint["prompt_version"] = VERSION
    checkpoint["inherited_from"] = {"experiment": Path(source_experiment).name,
        "case_id": EXPECTED_CASE, "source_checkpoint_hash": audit["source_checkpoint_hash"],
        "old_prompt_version": "kb-pilot-v6-repair-loops",
        "note": "Mixed-prompt calibration: old reader/selection requests; new classification/finalizer requests."}
    checkpoint["request_prompt_versions"] = {key: "kb-pilot-v6-repair-loops"
                                             for key in checkpoint["request_journal"]}
    for key, journal in checkpoint["request_journal"].items():
        cache = _read(target_case / "responses" / f"{key.replace(':', '_')}.json")
        journal["model"] = cache["identity"]["model"]
        journal["metadata"] = cache["identity"]["metadata"]
        journal["response_checksum"] = digest(json.dumps(
            journal["response"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8"))
    checkpoint["stage"] = "repair_classification"
    checkpoint["repair_turn"] = 0
    _save_snapshot(target_case, "after_selection_repair", checkpoint["state"])
    checkpoint["snapshots"].append("after_selection_repair")
    old_failure = target_case / "failure.json"
    if old_failure.exists():
        historical = target_case / "history"
        historical.mkdir(exist_ok=True)
        old_failure.rename(historical / "inherited_failure.json")
    save(checkpoint_path, checkpoint)
    save(target_case / "trace.json", checkpoint["trace"])
    row = next(value for value in manifest["cases"] if value["case_id"] == EXPECTED_CASE)
    text, source_hash = load_source(row["source"])
    _, units = source_structure(text, source_hash)
    save(target_case / "case.json", _result(row, text, units, checkpoint,
        "incomplete", "inherited_before_classification_repair"))
    save(target_case / "migration.json", {**audit,
        "status": "migrated", "target_prompt_version": VERSION,
        "old_request_count": len(checkpoint["request_journal"])})
    return {**audit, "status": "migrated", "new_requests": 0,
            "ledger_unchanged": True}


def recover_revision_repair(experiment: Path, manifest: dict, fingerprint: dict,
                            ledger_path: Path, *, execute: bool = False) -> dict:
    """Finish a cached, valid revision correction without another model request."""
    experiment = Path(experiment)
    case_dir = experiment / "calibration" / "045155"
    old_config_path = experiment / "config.json"
    checkpoint_path = case_dir / "checkpoint.json"
    old_config = _read(old_config_path)
    comparable_old = {key: value for key, value in old_config.items()
                      if key != "implementation_hashes"}
    comparable_new = {key: value for key, value in fingerprint.items()
                      if key != "implementation_hashes"}
    if comparable_old != comparable_new:
        raise ValueError("recovery_configuration_changed_beyond_implementation")
    checkpoint = _read(checkpoint_path)
    if checkpoint.get("schema_version") != 6 or checkpoint.get("prompt_version") != VERSION:
        raise ValueError("recovery_checkpoint_identity_mismatch")
    row = next((item for item in manifest["cases"] if item["case_id"] == "045155"), None)
    if row is None or "045155" not in manifest["splits"]["calibration"]:
        raise ValueError("recovery_case_not_in_calibration")
    text, source_hash = load_source(row["source"])
    if source_hash != row["source_hash"] or checkpoint["source_hash"] != source_hash:
        raise ValueError("recovery_source_changed")
    rejection_id = "045155:classification_repair:0:op:4"
    receipt_path = case_dir / "revision_recovery.json"
    marker = checkpoint.get("offline_revision_recovery")
    if marker:
        if (marker.get("rejection_id") != rejection_id or
                marker.get("old_config_hash") != digest((experiment / "config_history" /
                    "before_revision_repair.json").read_bytes())):
            raise ValueError("existing_recovery_marker_mismatch")
        if execute and old_config != fingerprint:
            save(old_config_path, fingerprint)
        if execute and not receipt_path.exists():
            save(receipt_path, marker)
        return {"status": "already_recovered", "case_id": "045155",
                "next_stage": checkpoint["stage"], "new_requests": 0}
    if checkpoint.get("stage") != "incomplete_protocol" or checkpoint.get("response_processing"):
        raise ValueError("recovery_stage_mismatch")
    unresolved = [entry for entry in checkpoint["operation_rejections"]
                  if entry["status"] == "unresolved"]
    if (len(unresolved) != 1 or unresolved[0]["rejection_id"] != rejection_id or
            unresolved[0].get("repair_error_code") != "repair_target_mismatch" or
            any(entry["status"] == "unresolved" for entry in checkpoint["protocol_errors"])):
        raise ValueError("recovery_rejection_mismatch")
    record = unresolved[0]
    if (record["original_operation"].get("op") != "defer" or
            record["original_operation"].get("id") != "045155:aus:004" or
            record["original_operation"].get("revision") != 2):
        raise ValueError("recovery_original_operation_changed")
    repair_key = "classification_repair_protocol_repair:0"
    repair_journal = checkpoint["request_journal"][repair_key]
    response_path = case_dir / "responses" / "classification_repair_protocol_repair_0.json"
    cache = _read(response_path)
    identity = cache.get("identity", {})
    if (identity.get("request_id") != repair_journal["request_id"] or
            identity.get("payload_hash") != repair_journal["payload_hash"] or
            identity.get("system_hash") != digest(repair_journal["prompt"].encode("utf-8")) or
            identity.get("metadata", {}).get("source_hash") != source_hash or
            _read_cache(response_path, identity) != repair_journal["response"]):
        raise ValueError("recovery_cached_response_identity_mismatch")
    ledger = _read(ledger_path)
    if not any(call.get("logical_request_id") == repair_journal["request_id"] and
               call.get("status", "").startswith("completed") for call in ledger["calls"]):
        raise ValueError("recovery_cached_request_missing_from_ledger")
    matching = [entry for entry in repair_journal["response"]["repairs"]
                if entry["rejection_id"] == rejection_id]
    if len(matching) != 1:
        raise ValueError("recovery_repair_entry_missing")
    operation = matching[0]["operation"]
    if (not _repair_target_matches(record["original_operation"], operation) or
            operation.get("revision") != 1 or
            operation.get("id") != "045155:aus:004"):
        raise ValueError("recovery_repair_not_valid_revision_correction")
    request_snapshot = checkpoint["request_journal"]["classification_repair:0"]["pre_request_snapshot"]
    if request_snapshot["items"]["045155:aus:004"]["revision"] != 1:
        raise ValueError("recovery_request_snapshot_revision_mismatch")
    _, units = source_structure(text, source_hash)
    source_map = {unit["source_id"]: unit for unit in units}
    stable_to_handle, aliases = source_handles(units)
    candidate, events, rejected, noops = apply_operations_independently(
        checkpoint["state"], [operation], set(checkpoint["opened_source_ids"]),
        source_map, source_hash, "045155", aliases=aliases,
        stable_to_handle=stable_to_handle,
        allowed_target_ids=set(request_snapshot["items"]))
    if rejected or noops or len(events) != 1 or events[0]["op"] != "defer":
        raise ValueError("recovery_corrected_operation_not_applicable")
    if candidate["items"]["045155:aus:004"]["status"] != "deferred":
        raise ValueError("recovery_target_not_deferred")
    if old_config != fingerprint and (experiment / "config_history" /
                                      "before_revision_repair.json").exists():
        raise ValueError("recovery_config_history_already_exists")
    audit = {"status": "ready", "case_id": "045155", "rejection_id": rejection_id,
        "target_id": "045155:aus:004", "from_revision": 1, "to_revision": 2,
        "old_config_hash": digest(old_config_path.read_bytes()),
        "new_config_hash": digest(json.dumps(fingerprint, ensure_ascii=False,
            indent=2).encode("utf-8")),
        "cached_response_hash": digest(response_path.read_bytes()),
        "ledger_reserved_usd": ledger.get("reserved_usd"), "next_stage": "finalizing"}
    if not execute:
        return audit
    history_dir = experiment / "config_history"
    history_dir.mkdir(exist_ok=True)
    save(history_dir / "before_revision_repair.json", old_config)
    case_history = case_dir / "history"
    case_history.mkdir(exist_ok=True)
    shutil.copy2(case_dir / "case.json", case_history / "before_revision_recovery.json")
    event = events[0]
    event["operation_index"] = record["operation_index"]
    candidate["history"][-1]["operation_index"] = record["operation_index"]
    checkpoint["state"] = candidate
    record.update({"status": "resolved", "resolved_by": "offline_revision_repair",
                   "repair_operation": operation})
    processed = checkpoint["processed_responses"]["classification_repair:0"]
    processed["applied"].append(deepcopy(event))
    for entry in processed["rejections"]:
        if entry["rejection_id"] == rejection_id:
            entry.update(deepcopy(record))
    trace = next(entry for entry in checkpoint["trace"]
                 if entry["stage"] == "repair_classification" and entry["turn"] == 0)
    trace["applied"].append(deepcopy(event))
    trace["protocol_rejected_unresolved"] = []
    for journal_key in ("classification_repair:0", repair_key):
        checkpoint["request_journal"][journal_key]["post_request_snapshot"] = _snapshot_value(candidate)
    _save_snapshot(case_dir, "after_classification_repair", candidate)
    checkpoint["snapshots"].append("after_classification_repair")
    checkpoint["stage"] = "finalizing"
    checkpoint["repair_turn"] = 0
    checkpoint["offline_revision_recovery"] = audit
    save(checkpoint_path, checkpoint)
    save(case_dir / "trace.json", checkpoint["trace"])
    save(case_dir / "case.json", _result(row, text, units, checkpoint,
        "incomplete", "revision_repair_recovered_before_finalizer"))
    save(old_config_path, fingerprint)
    save(receipt_path, audit)
    return {**audit, "status": "recovered", "new_requests": 0,
            "ledger_unchanged": True}
