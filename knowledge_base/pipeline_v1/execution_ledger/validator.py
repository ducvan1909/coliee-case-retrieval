"""Fail-closed validation for Plan 08 snapshots and derived attempt logs."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator
from ..sentence_atoms.segmenter import canonical_hash
from .runner import ALLOWED, ExecutionError, build_requests, cache_path, summarize

def _load(path:Path):
    try:return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:raise ExecutionError("invalid JSON",code="snapshot_validation_failed",location=str(path)) from exc

def validate_snapshot(snapshot,workloads,policy,*,snapshot_path=None,attempt_log_path=None,cache_root=None):
    schema_path=Path(__file__).resolve().parents[1]/"contracts"/"execution_ledger.v1.json"
    schema=_load(schema_path);errors=sorted(Draft202012Validator(schema).iter_errors(snapshot),key=lambda e:list(e.path))
    if errors:raise ExecutionError(errors[0].message,code="schema_validation_failed",location="/"+"/".join(map(str,errors[0].path)))
    if snapshot["policy_sha256"]!=canonical_hash(policy) or snapshot["workload_cache_keys"]!=sorted(w["cache_key"] for w in workloads):raise ExecutionError("dependency identity mismatch",code="dependency_mismatch")
    targets={t["target_id"] for w in workloads for t in w["targets"]};entries=snapshot["coverage_entries"]
    if len(entries)!=len(targets) or {e["target_id"] for e in entries}!=targets:raise ExecutionError("coverage ledger must contain every target exactly once",code="coverage_mismatch")
    orders=[]
    for entry in entries:
        state="pending"
        if entry["protocol_only"] is not True:raise ExecutionError("semantic claim in protocol ledger",code="semantic_leak",location=entry["target_id"])
        for event in entry["transition_events"]:
            orders.append(event["event_order"])
            if event["from_state"]!=state or event["to_state"] not in ALLOWED[state]:raise ExecutionError("illegal or non-replayable state transition",code="illegal_transition",location=entry["target_id"])
            state=event["to_state"]
        if state!=entry["state"]:raise ExecutionError("stored state differs from replay",code="state_replay_mismatch",location=entry["target_id"])
        if entry["state"]=="mock_protocol_verified" and set(entry["verified_work_item_ids"])!=set(entry["work_item_ids"]):raise ExecutionError("verified state without exact work-item coverage",code="false_completion",location=entry["target_id"])
        if entry["state"]!="mock_protocol_verified" and set(entry["verified_work_item_ids"])==set(entry["work_item_ids"]):raise ExecutionError("complete coverage has inconsistent state",code="state_replay_mismatch",location=entry["target_id"])
    if len(orders)!=len(set(orders)) or (orders and (min(orders)<1 or max(orders)!=snapshot["logical_clock"])):raise ExecutionError("transition event order is duplicate or inconsistent",code="attempt_order_violation")
    attempts=snapshot["attempts"]
    if [a["attempt_order"] for a in attempts]!=list(range(len(attempts))) or len({a["attempt_id"] for a in attempts})!=len(attempts):raise ExecutionError("attempt order/identity invalid",code="attempt_order_violation")
    per_request={}
    for attempt in attempts:per_request.setdefault(attempt["request_id"],[]).append(attempt["attempt_number"])
    if any(numbers!=sorted(numbers) or len(numbers)!=len(set(numbers)) for numbers in per_request.values()):raise ExecutionError("attempt numbers are duplicate or out of order",code="attempt_order_violation")
    expected={r["request_id"]:r for r in build_requests(workloads,policy,snapshot["settings"])}
    for request in snapshot["requests"]:
        exp=expected.get(request["request_id"])
        if not exp or request["input_fingerprint"]!=exp["input_fingerprint"] or request["expected_work_item_ids"]!=exp["expected_work_item_ids"] or request["expected_target_ids"]!=exp["expected_target_ids"]:raise ExecutionError("request fingerprint or membership mismatch",code="request_mismatch",location=request["request_id"])
    if snapshot["summary"]!=summarize(snapshot):raise ExecutionError("summary is not recomputable",code="summary_mismatch")
    states={e["state"] for e in entries};expected_status="protocol_complete" if states=={"mock_protocol_verified"} else ("budget_exhausted" if "budget_exhausted" in states else ("interrupted" if snapshot["run_status"]=="interrupted" else "protocol_error"))
    if snapshot["run_status"]!=expected_status:raise ExecutionError("run status inconsistent with ledger",code="false_completion")
    if attempt_log_path is not None:
        try:lines=[json.loads(x) for x in Path(attempt_log_path).read_text(encoding="utf-8").splitlines() if x]
        except Exception as exc:raise ExecutionError("invalid attempt projection",code="projection_mismatch",location=str(attempt_log_path)) from exc
        if lines!=attempts:raise ExecutionError("JSONL projection differs from canonical snapshot",code="projection_mismatch",location=str(attempt_log_path))
    if cache_root is not None:
        for request in snapshot["requests"]:
            if request["status"] in {"protocol_verified","cache_hit"}:
                path=cache_path(Path(cache_root),request["input_fingerprint"])
                if not path.is_file():raise ExecutionError("referenced cache entry missing",code="cache_validation_failed",location=str(path))
                value=_load(path)
                if value.get("fingerprint")!=request["input_fingerprint"] or value.get("processed_work_item_ids")!=request["expected_work_item_ids"] or value.get("processed_target_ids")!=request["expected_target_ids"]:raise ExecutionError("cache entry mismatch",code="cache_validation_failed",location=str(path))
    return {"target_count":len(entries),"attempt_count":len(attempts),"request_inventory_count":len(expected),"status":snapshot["run_status"]}

def load_and_validate_snapshot(path,workloads,policy,**kwargs):
    value=_load(Path(path));return value,validate_snapshot(value,workloads,policy,snapshot_path=path,**kwargs)
