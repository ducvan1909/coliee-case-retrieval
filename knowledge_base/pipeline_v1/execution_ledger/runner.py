"""Deterministic offline request ledger, cache, checkpoint, and resume.

The snapshot is canonical; JSONL is a derived projection. A successful state
means mock protocol acknowledgement, never semantic completion or AU/no-AU.
"""
from __future__ import annotations
from collections import Counter
import json
from pathlib import Path
from typing import Any
from ..sentence_atoms.segmenter import canonical_hash
from .mock_provider import call_mock

ALLOWED={"pending":{"in_progress","budget_exhausted"},"in_progress":{"pending","mock_protocol_verified","error","unresolved"},"mock_protocol_verified":set(),"unresolved":set(),"error":set(),"budget_exhausted":set()}

class ExecutionError(ValueError):
    def __init__(self,detail:str,*,code="execution_contract",location="<root>"):
        self.code,self.location,self.detail=code,location,detail
        super().__init__(f"[{code}] {location}: {detail}")

def transition(entry,new_state,reason,order):
    old=entry["state"]
    if new_state not in ALLOWED.get(old,set()): raise ExecutionError(f"illegal transition {old}->{new_state}",code="illegal_transition",location=entry["target_id"])
    entry["state"]=new_state;entry["transition_events"].append({"event_order":order,"from_state":old,"to_state":new_state,"reason":reason,"protocol_only":True})

def request_fingerprint(region,workload,policy,settings):
    return canonical_hash({"source_hash":region["source_hash"],"arm":region["arm"],"region_fingerprint":region["fingerprint"],"render_items":region["render_items"],"render_order":region["render_order"],"scheduler_version":workload["scheduler_version"],"target_ids":region["target_ids"],"primary_spans":region["primary_spans"],"context_refs":region["context_refs"],"task_id":policy["task_id"],"provider_id":policy["provider"]["provider_id"],"provider_settings_version":policy["provider"]["settings_version"],"request_schema_version":policy["request_schema_version"],"region_policy_sha256":workload["policy_sha256"],"region_dependencies":region["dependencies"],"mock_settings":settings})

def atomic_write(path:Path,value):
    data=(json.dumps(value,ensure_ascii=False,indent=2)+"\n").encode("utf-8");path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp");tmp.write_bytes(data);tmp.replace(path)

def cache_path(root:Path,fingerprint:str): return root/fingerprint[:2]/fingerprint/"cache_entry.json"

def build_requests(workloads,policy,settings):
    requests=[]
    for workload in workloads:
        batches={b["batch_id"]:b["work_items"] for b in workload["batches"]}
        for region in sorted((r for r in workload["regions"] if r["arm"]==policy["region_arm"]),key=lambda r:r["region_id"]):
            work=batches[region["batch_id"]];fp=request_fingerprint(region,workload,policy,settings)
            requests.append({"request_id":"req-"+fp[:24],"case_id":workload["case_id"],"source_hash":workload["source_hash"],"workload_cache_key":workload["cache_key"],"region_id":region["region_id"],"region_fingerprint":region["fingerprint"],"batch_id":region["batch_id"],"expected_work_item_ids":[x["work_item_id"] for x in work],"expected_target_ids":sorted({x["target_id"] for x in work}),"input_fingerprint":fp,"estimated_input_tokens":region["metrics"]["estimated_input_tokens"],"rendered_chars":region["metrics"]["rendered_chars"],"status":"pending","attempt_ids":[],"stop_reason":None,"protocol_only":True})
    return sorted(requests,key=lambda r:(r["case_id"],r["region_id"]))

def _new_snapshot(run_id,scenario,workloads,policy,settings):
    entries=[]
    for workload in workloads:
        by_target={t["target_id"]:[] for t in workload["targets"]}
        for batch in workload["batches"]:
            for item in batch["work_items"]: by_target[item["target_id"]].append(item["work_item_id"])
        for target in workload["targets"]:
            entries.append({"target_id":target["target_id"],"case_id":workload["case_id"],"source_hash":workload["source_hash"],"parent_block_id":target["parent_block_id"],"target_span":target["content_span"],"work_item_ids":sorted(by_target[target["target_id"]]),"verified_work_item_ids":[],"state":"pending","protocol_only":True,"request_ids":[],"attempt_ids":[],"retry_count":0,"stop_reason":None,"transition_events":[]})
    return {"artifact_type":"ExecutionRunSnapshot","schema_version":policy["schema_version"],"run_id":run_id,"scenario":scenario,"runner_version":policy["runner_version"],"policy_sha256":canonical_hash(policy),"settings":settings,"workload_cache_keys":sorted(w["cache_key"] for w in workloads),"run_status":"initialized","protocol_only":True,"logical_clock":0,"coverage_entries":sorted(entries,key=lambda e:(e["case_id"],e["target_id"])),"requests":[],"attempts":[],"cache_refs":[],"invocations":[],"summary":{}}

def _validate_response(response,request):
    if not isinstance(response,dict) or set(response)!={"processed_work_item_ids","processed_target_ids","protocol_only"} or response.get("protocol_only") is not True:return "protocol_failure"
    work,targets=response["processed_work_item_ids"],response["processed_target_ids"]
    if not isinstance(work,list) or not isinstance(targets,list) or len(work)!=len(set(work)) or len(targets)!=len(set(targets)):return "protocol_failure"
    return "valid" if set(work)==set(request["expected_work_item_ids"]) and set(targets)==set(request["expected_target_ids"]) else "protocol_failure"

def _load_cache(path,request):
    try:value=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:raise ExecutionError("corrupt current cache entry",code="cache_validation_failed",location=str(path)) from exc
    checks=(value.get("artifact_type")=="MockCacheEntry",value.get("schema_version")=="mock-cache-entry-v1",value.get("fingerprint")==request["input_fingerprint"],value.get("request_id")==request["request_id"],value.get("processed_work_item_ids")==request["expected_work_item_ids"],value.get("processed_target_ids")==request["expected_target_ids"],value.get("protocol_only") is True)
    if not all(checks):raise ExecutionError("stale/corrupt cache entry",code="cache_validation_failed",location=str(path))
    return value

FAULT_BY_SCENARIO={"transient_retry":"transient","permanent_failure":"permanent","timeout":"timeout","protocol_malformed":"malformed","protocol_missing":"missing","protocol_duplicate":"duplicate","protocol_foreign":"foreign","partial_batch":"partial"}

def execute_scenario(*,workloads,policy,cache_root,snapshot_path,scenario="cold_success",settings=None,fault_request_ordinal=None,interrupt_after=None,budget_request_limit=None,resume=False,crash_point=None):
    settings=settings or {"mode":scenario};cache_root,snapshot_path=Path(cache_root),Path(snapshot_path)
    run_id="run-"+canonical_hash({"scenario":scenario,"settings":settings,"policy":canonical_hash(policy),"workloads":[w["cache_key"] for w in workloads]})[:24]
    if resume and snapshot_path.exists():
        try:snapshot=json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception as exc:raise ExecutionError("snapshot cannot be resumed",code="snapshot_validation_failed",location=str(snapshot_path)) from exc
        if snapshot.get("run_id")!=run_id or snapshot.get("policy_sha256")!=canonical_hash(policy):raise ExecutionError("resume identity mismatch",code="resume_identity_mismatch",location=str(snapshot_path))
    else:snapshot=_new_snapshot(run_id,scenario,workloads,policy,settings)
    invocation={"invocation_order":len(snapshot["invocations"]),"resume":resume,"provider_calls":0,"cache_hits":0,"cache_misses":0,"skipped_verified_requests":0,"rendered_chars_avoided":0,"estimated_input_tokens_avoided":0,"interrupted":False};snapshot["invocations"].append(invocation)
    entries={e["target_id"]:e for e in snapshot["coverage_entries"]}
    if len(entries)!=len(snapshot["coverage_entries"]):raise ExecutionError("duplicate target ledger entry",code="snapshot_validation_failed")
    for entry in entries.values():
        if resume and entry["state"]=="in_progress":snapshot["logical_clock"]+=1;transition(entry,"pending","resume_recovered_uncommitted",snapshot["logical_clock"])
    for ordinal,request in enumerate(build_requests(workloads,policy,settings)):
        if all(entries[t]["state"]=="mock_protocol_verified" for t in request["expected_target_ids"]):
            invocation["skipped_verified_requests"]+=1;invocation["rendered_chars_avoided"]+=request["rendered_chars"];invocation["estimated_input_tokens_avoided"]+=request["estimated_input_tokens"];continue
        if interrupt_after is not None and invocation["provider_calls"]>=interrupt_after:
            invocation["interrupted"]=True;snapshot["run_status"]="interrupted";snapshot["summary"]=summarize(snapshot);atomic_write(snapshot_path,snapshot);break
        if budget_request_limit is not None and invocation["provider_calls"]>=budget_request_limit:
            request["status"],request["stop_reason"]="budget_exhausted","request_budget_exhausted";snapshot["requests"].append(request)
            for tid in request["expected_target_ids"]:
                e=entries[tid]
                if request["request_id"] not in e["request_ids"]:e["request_ids"].append(request["request_id"])
                if e["state"]=="pending":snapshot["logical_clock"]+=1;transition(e,"budget_exhausted","request_budget_exhausted",snapshot["logical_clock"]);e["stop_reason"]="request_budget_exhausted"
            continue
        for tid in request["expected_target_ids"]:
            if request["request_id"] not in entries[tid]["request_ids"]:entries[tid]["request_ids"].append(request["request_id"])
        path=cache_path(cache_root,request["input_fingerprint"]);successful=set()
        if path.exists():
            _load_cache(path,request);invocation["cache_hits"]+=1;invocation["rendered_chars_avoided"]+=request["rendered_chars"];invocation["estimated_input_tokens_avoided"]+=request["estimated_input_tokens"];request["status"]="cache_hit";successful=set(request["expected_work_item_ids"]);snapshot["requests"].append(request)
            if path.as_posix() not in snapshot["cache_refs"]:snapshot["cache_refs"].append(path.as_posix())
        else:
            invocation["cache_misses"]+=1
            for tid in request["expected_target_ids"]:
                if entries[tid]["state"]=="pending":snapshot["logical_clock"]+=1;transition(entries[tid],"in_progress","request_dispatched",snapshot["logical_clock"])
            if crash_point=="after_dispatch":snapshot["run_status"]="interrupted";snapshot["summary"]=summarize(snapshot);atomic_write(snapshot_path,snapshot);return snapshot
            prior=[a["attempt_number"] for a in snapshot["attempts"] if a["request_id"]==request["request_id"]];start=max(prior,default=0)+1;max_new=1+policy["retry"]["max_transient_retries"]
            for offset in range(max_new):
                number=start+offset;fault=FAULT_BY_SCENARIO.get(scenario,"success") if ordinal==fault_request_ordinal else "success";result=call_mock(request,number,policy,fault);invocation["provider_calls"]+=1;aid="att-"+canonical_hash({"request_id":request["request_id"],"attempt_number":number,"input_fingerprint":request["input_fingerprint"],"outcome":result["transport_outcome"]})[:24]
                if any(a["attempt_id"]==aid for a in snapshot["attempts"]):raise ExecutionError("duplicate attempt identity",code="attempt_order_violation",location=aid)
                attempt={"attempt_id":aid,"request_id":request["request_id"],"attempt_number":number,"attempt_order":len(snapshot["attempts"]),"input_fingerprint":request["input_fingerprint"],"transport_outcome":result["transport_outcome"],"protocol_outcome":"not_checked","latency_ms":result["latency_ms"],"stop_reason":None,"protocol_only":True};snapshot["attempts"].append(attempt);request["attempt_ids"].append(aid)
                for tid in request["expected_target_ids"]:entries[tid]["attempt_ids"].append(aid)
                if crash_point=="after_attempt_before_commit":snapshot["run_status"]="interrupted";snapshot["summary"]=summarize(snapshot);atomic_write(snapshot_path,snapshot);return snapshot
                if result["transport_outcome"]=="transient_failure" and offset<max_new-1:attempt["stop_reason"]="retry_transient";continue
                if result["transport_outcome"]!="success":attempt["stop_reason"]="provider_failure";request["status"],request["stop_reason"]="error",result["transport_outcome"];break
                attempt["protocol_outcome"]=_validate_response(result["response"],request)
                if attempt["protocol_outcome"]!="valid":attempt["stop_reason"]="atomic_batch_rejected";request["status"],request["stop_reason"]="error","protocol_failure";break
                successful=set(result["response"]["processed_work_item_ids"]);request["status"]="protocol_verified"
                cache={"artifact_type":"MockCacheEntry","schema_version":"mock-cache-entry-v1","fingerprint":request["input_fingerprint"],"request_id":request["request_id"],"case_id":request["case_id"],"source_hash":request["source_hash"],"region_id":request["region_id"],"region_fingerprint":request["region_fingerprint"],"workload_cache_key":request["workload_cache_key"],"processed_work_item_ids":request["expected_work_item_ids"],"processed_target_ids":request["expected_target_ids"],"protocol_only":True,"provider_id":policy["provider"]["provider_id"],"request_schema_version":policy["request_schema_version"],"settings":settings,"rendered_chars":request["rendered_chars"],"estimated_input_tokens":request["estimated_input_tokens"]};atomic_write(path,cache)
                if path.as_posix() not in snapshot["cache_refs"]:snapshot["cache_refs"].append(path.as_posix())
                break
            snapshot["requests"].append(request)
        for tid in request["expected_target_ids"]:
            e=entries[tid];e["verified_work_item_ids"]=sorted(set(e["verified_work_item_ids"])|(set(e["work_item_ids"])&successful));e["retry_count"]=max(0,len(e["attempt_ids"])-len(e["request_ids"]))
            if set(e["verified_work_item_ids"])==set(e["work_item_ids"]):
                if e["state"]=="pending":snapshot["logical_clock"]+=1;transition(e,"in_progress","cache_replay",snapshot["logical_clock"])
                if e["state"]=="in_progress":snapshot["logical_clock"]+=1;transition(e,"mock_protocol_verified","all_work_items_protocol_verified",snapshot["logical_clock"])
            elif request["status"]=="error" and e["state"]=="in_progress":snapshot["logical_clock"]+=1;transition(e,"error",request["stop_reason"],snapshot["logical_clock"]);e["stop_reason"]=request["stop_reason"]
        snapshot["cache_refs"]=sorted(set(snapshot["cache_refs"]));snapshot["summary"]=summarize(snapshot);atomic_write(snapshot_path,snapshot)
    else:
        states={e["state"] for e in entries.values()};snapshot["run_status"]="protocol_complete" if states=={"mock_protocol_verified"} else ("budget_exhausted" if "budget_exhausted" in states else "protocol_error")
    snapshot["summary"]=summarize(snapshot);atomic_write(snapshot_path,snapshot);return snapshot

def summarize(snapshot):
    states=Counter(e["state"] for e in snapshot["coverage_entries"]);outcomes=Counter(a["transport_outcome"] for a in snapshot["attempts"]);requests={r["request_id"]:r for r in snapshot["requests"]};transient=[a for a in snapshot["attempts"] if a["transport_outcome"]=="transient_failure"];successful={r["request_id"] for r in snapshot["requests"] if r["status"] in {"protocol_verified","cache_hit"}}
    return {"primary_target_count":len(snapshot["coverage_entries"]),"request_count":len(snapshot["requests"]),"attempt_count":len(snapshot["attempts"]),"provider_calls":sum(i["provider_calls"] for i in snapshot["invocations"]),"cache_hits":sum(i["cache_hits"] for i in snapshot["invocations"]),"cache_misses":sum(i["cache_misses"] for i in snapshot["invocations"]),"skipped_verified_requests":sum(i["skipped_verified_requests"] for i in snapshot["invocations"]),"status_counts":dict(sorted(states.items())),"attempt_outcome_counts":dict(sorted(outcomes.items())),"retry_count":len(transient),"useful_retry_count":sum(a["request_id"] in successful for a in transient),"useless_retry_count":sum(a["request_id"] not in successful for a in transient),"rendered_chars_sent":sum(requests[a["request_id"]]["rendered_chars"] for a in snapshot["attempts"] if a["request_id"] in requests),"estimated_input_tokens_sent":sum(requests[a["request_id"]]["estimated_input_tokens"] for a in snapshot["attempts"] if a["request_id"] in requests),"rendered_chars_avoided":sum(i["rendered_chars_avoided"] for i in snapshot["invocations"]),"estimated_input_tokens_avoided":sum(i["estimated_input_tokens_avoided"] for i in snapshot["invocations"]),"mock_latency_ms":sum(a["latency_ms"] for a in snapshot["attempts"]),"protocol_only":True}

def write_attempt_projection(snapshot,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text("".join(json.dumps(a,ensure_ascii=False,sort_keys=True)+"\n" for a in snapshot["attempts"]),encoding="utf-8");tmp.replace(path)

def invalidation_scope(old_requests,new_requests):
    old={(r["case_id"],r["region_id"]):r["input_fingerprint"] for r in old_requests};new={(r["case_id"],r["region_id"]):r["input_fingerprint"] for r in new_requests};keys=sorted(set(old)|set(new));invalidated=[list(k) for k in keys if old.get(k)!=new.get(k)];retained=[list(k) for k in keys if k in old and old[k]==new.get(k)];return {"invalidated":invalidated,"retained":retained,"invalidated_count":len(invalidated),"retained_count":len(retained)}
