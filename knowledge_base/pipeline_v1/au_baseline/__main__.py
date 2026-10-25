"""CLI: remote execution is explicit, budgeted, and probe-bound."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from knowledge_base.config import settings
from ..sentence_atoms.segmenter import canonical_hash
from ..execution_ledger.build import load_plan07_workloads
from ..source_contract import open_source
from .core import BaselineError,arm_spec,build_locked_requests,cache_key,execute_remote,modal_config,paired_experiment,persist_json,plan10_budget,recovery_config,recovery_ledger,run_offline_experiment,run_warmup,run_warmup_probe,validate_response,warmup_config,warm_probe_config
ROOT=Path(__file__).resolve().parents[1]
def _receipt_hash(v): return canonical_hash({k:v[k] for k in sorted(v) if k!="receipt_sha256"})
def _account(rows):
    out={"requests":len(rows),"protocol_verified":0,"unresolved":0,"budget_stopped":0,"output_truncated_unresolved":0,"input_tokens":0,"output_tokens":0,"total_tokens":0,"latency_ms":0}
    for row in rows:
        out[row["status"]]=out.get(row["status"],0)+1;u=row["receipt"]["usage"]
        if row["receipt"].get("failure_diagnostic",{}).get("kind")=="output_truncated":out["output_truncated_unresolved"]+=1
        for key in ("input_tokens","output_tokens","total_tokens"):out[key]+=u[key]
        out["latency_ms"]+=row["receipt"]["latency_ms"]
    return out
def _paired_completion(arms,*,expected_requests):
    ledger=[row for value in arms.values() for row in value["request_ledger"]]
    if len(ledger)!=expected_requests:return ("incomplete","locked_request_count_mismatch","incomplete_locked_request_count_mismatch")
    bad=[row for row in ledger if row["status"]!="protocol_verified"]
    if not bad:return ("complete","all_locked_requests_protocol_verified","complete")
    if any(row["status"]=="budget_stopped" for row in bad):return ("incomplete","budget_stopped","incomplete_budget_stopped")
    if any(row.get("finish_reason") in {"length","content_filter"} for row in bad):return ("incomplete","output_truncated","incomplete_output_truncated")
    if any(row.get("failure_kind") in {"http","transport","malformed_response"} for row in bad):return ("incomplete","provider_failure","incomplete_provider_failure")
    if any(row["status"]=="unresolved" for row in bad):return ("incomplete","unresolved","incomplete_unresolved")
    return ("incomplete","non_protocol_status","incomplete_non_protocol_status")
def _preflight(manifests,budget,recovery=None,warmup=None):
    requests=[q for m in manifests for q in m["requests"]];reserved_input=sum(q["input_tokens"] for q in requests);reserved_output=sum(q["spec"]["caps"]["output_tokens"] for q in requests)
    price_known=bool(budget["input_usd_micros_per_1k"] or budget["output_usd_micros_per_1k"]);reserve_usd=(reserved_input*budget["input_usd_micros_per_1k"]+reserved_output*budget["output_usd_micros_per_1k"]+999)//1000 if price_known else None
    recovery=recovery or {"max_recovery_cycles":0,"max_source_retries":0};warmup=warmup or {"max_attempts":0};provider_bound=len(requests)+recovery["max_recovery_cycles"]*(warmup["max_attempts"]+recovery["max_source_retries"])
    limits={"max_requests":budget["max_requests"],"max_provider_attempts":budget.get("max_provider_attempts",budget["max_requests"]),"max_total_input_tokens":budget["max_total_input_tokens"],"max_total_output_tokens":budget["max_total_output_tokens"],"max_usd_micros":budget["max_usd_micros"],"per_request_input_tokens":budget["max_input_tokens"],"per_request_output_tokens":budget["max_output_tokens"]}
    retry_slots=recovery["max_recovery_cycles"]*recovery["max_source_retries"];retry_input=(max((q["input_tokens"] for q in requests),default=0)*retry_slots);retry_output=(max((q["spec"]["caps"]["output_tokens"] for q in requests),default=0)*retry_slots);reserved_input+=retry_input;reserved_output+=retry_output;reserve_usd=(reserved_input*budget["input_usd_micros_per_1k"]+reserved_output*budget["output_usd_micros_per_1k"]+999)//1000 if price_known else None
    failures=[]
    if budget["max_total_input_tokens"] is None:failures.append("missing_PLX_MAX_TOTAL_INPUT_TOKENS")
    elif reserved_input>budget["max_total_input_tokens"]:failures.append("total_input_cap")
    if budget["max_total_output_tokens"] is None:failures.append("missing_PLX_MAX_TOTAL_OUTPUT_TOKENS")
    elif reserved_output>budget["max_total_output_tokens"]:failures.append("total_output_cap")
    if len(requests)>budget["max_requests"]:failures.append("request_cap")
    if provider_bound>limits["max_provider_attempts"]:failures.append("provider_attempt_cap")
    if budget["max_usd_micros"] is not None and reserve_usd>budget["max_usd_micros"]:failures.append("usd_cap")
    return {"requests":len(requests),"provider_attempt_upper_bound":provider_bound,"recovery_reserved_input_tokens":retry_input,"recovery_reserved_output_tokens":retry_output,"reserved_input_tokens":reserved_input,"reserved_output_tokens":reserved_output,"reserved_usd_micros":reserve_usd,"usd_price_known":price_known,"limits":limits,"status":"pass" if not failures else "fail","failures":failures}
def _require_preflight(value):
    if value["status"]!="pass":raise BaselineError("paired-run preflight failed: "+",".join(value["failures"]))
def _valid_direct_receipt(value,a,spec):
    return value.get("receipt_sha256")==_receipt_hash(value) and value.get("success") and value.get("p2a_input_manifest_sha256")==canonical_hash(a) and value.get("plan07_build_manifest_sha256")==a["plan07_build_manifest_sha256"] and value.get("spec_sha256")==canonical_hash(spec) and value.get("request_sha256")==canonical_hash(a["requests"][0])
def _has_probe_proof(root,a,spec,*,plan07_report,source_store=None):
    direct=root/"probe_receipt.json"
    if direct.is_file() and _valid_direct_receipt(json.loads(direct.read_text(encoding="utf-8")),a,spec):return True
    warm=root/"warmup_probe/current.json"
    if not warm.is_file():return False
    value=json.loads(warm.read_text(encoding="utf-8"));request=a["requests"][0]
    if not (value.get("status")=="success" and value.get("input_manifest_sha256")==canonical_hash(a) and value.get("request_sha256")==canonical_hash(request) and value.get("spec_sha256")==canonical_hash(spec) and value.get("model")==spec["model"] and value.get("enable_thinking")==spec["enable_thinking"]): return False
    expected_key=cache_key(request);cache_base=(root/"warmup_probe"/"source_probe_cache").resolve()
    for attempt in value.get("probe_attempts",[]):
        if not (attempt.get("status")=="protocol_verified" and attempt.get("request_id")==request["request_id"] and attempt.get("request_sha256")==canonical_hash(request) and attempt.get("cache_key")==expected_key): continue
        ordinal=attempt.get("ordinal")
        if not isinstance(ordinal,int) or ordinal<1: continue
        candidate=(cache_base/f"attempt-{ordinal}"/expected_key[:2]/expected_key/"response.json").resolve()
        if cache_base not in candidate.parents or not candidate.is_file(): continue
        try: row=json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): continue
        if row.get("status")!="protocol_verified" or row.get("cache_key")!=expected_key or canonical_hash(row.get("request"))!=canonical_hash(request) or row.get("request",{}).get("request_id")!=request["request_id"] or not isinstance(row.get("response"),dict): continue
        try:
            _,report,_=load_plan07_workloads(str(plan07_report));source=open_source(source_store or report["inputs"]["source_store"],request["case_id"],request["source_hash"]);validate_response(request,row["response"],source)
        except Exception: continue
        return True
    return False
def main():
    p=argparse.ArgumentParser();p.add_argument("command",choices=["offline-run","preflight","warmup","warmup-probe","probe","paired-run"]);p.add_argument("--plan07-report",default=str(ROOT/"reports/plan07_analysis_region_validation.latest.json"));p.add_argument("--output-root",default=str(ROOT/"outputs/plan10_au_baseline_v1"));p.add_argument("--source-store");p.add_argument("--execute",action="store_true");p.add_argument("--max-requests",type=int);args=p.parse_args()
    if args.command=="offline-run":run_offline_experiment(plan07_report=args.plan07_report,output_root=args.output_root,source_store=args.source_store);print(f"PLAN10 OFFLINE PASS — output: {Path(args.output_root).resolve()}");return
    if args.command in {"warmup","warmup-probe"} and not args.execute:p.error(f"{args.command} requires --execute")
    if args.command not in {"preflight","warmup","warmup-probe"} and (not args.execute or not args.max_requests or args.max_requests<1):p.error("remote commands require --execute and explicit --max-requests")
    env=settings();cfg=modal_config(env,require_credentials=args.command!="preflight");budget=plan10_budget(env);recovery=recovery_config(env);warmup=warmup_config(env);root=Path(args.output_root)
    if args.command=="warmup":
        state=run_warmup(output_root=root,cfg=cfg,warmup=warmup);print(f"PLAN10 WARMUP {state['status'].upper()} — output: {(root/'warmup').resolve()}");return
    spec=arm_spec(model=cfg["model"],enable_thinking=cfg["enable_thinking"],caps={"targets":4,"output_tokens":budget["baseline_output_tokens"],"au_candidates":8})
    if args.command=="preflight":
        a=build_locked_requests(args.plan07_report,arm="P2a",spec=spec,source_store=args.source_store);b=build_locked_requests(args.plan07_report,arm="P2b",spec=spec,source_store=args.source_store);value={"artifact_type":"Plan10Preflight","schema_version":"plan10-au-runtime-v1","evaluation_against":"model_silver","semantic_gold":False,"retrieval_quality_claim":False,"p2a_input_manifest_sha256":canonical_hash(a),"p2b_input_manifest_sha256":canonical_hash(b),"arms":{"P2a":{"request_count":len(a["requests"])},"P2b":{"request_count":len(b["requests"])}},"preflight":_preflight((a,b),budget,recovery,warmup)};persist_json(root/"preflight.json",value);print(f"PLAN10 PREFLIGHT {value['preflight']['status'].upper()} — output: {(root/'preflight.json').resolve()}");return
    if args.command=="warmup-probe":
        manifest=build_locked_requests(args.plan07_report,arm="P2a",spec=spec,source_store=args.source_store);state=run_warmup_probe(output_root=root,cfg=cfg,warmup=warmup_config(env),warm_probe=warm_probe_config(env),manifest=manifest,plan07_report=args.plan07_report,source_store=args.source_store,budget=budget);print(f"PLAN10 WARMUP-PROBE {state['status'].upper()} — output: {(root/'warmup_probe').resolve()}");return
    budget["max_requests"]=min(budget["max_requests"],args.max_requests)
    a=build_locked_requests(args.plan07_report,arm="P2a",spec=spec,source_store=args.source_store)
    if args.command=="probe":
        m={**a,"requests":a["requests"][:1]};rows=execute_remote(m,plan07_report=args.plan07_report,source_store=args.source_store,cache_dir=root/"remote_cache/P2a",cfg=cfg,max_requests=budget["max_requests"],budget=budget);row=rows[0]
        receipt={"artifact_type":"Plan10ProbeReceipt","schema_version":"plan10-au-runtime-v1","evaluation_against":"model_silver","semantic_gold":False,"retrieval_quality_claim":False,"success":row["status"]=="protocol_verified","p2a_input_manifest_sha256":canonical_hash(a),"plan07_build_manifest_sha256":a["plan07_build_manifest_sha256"],"spec_sha256":canonical_hash(spec),"request_id":row["request"]["request_id"],"request_sha256":canonical_hash(row["request"]),"cache_key":row["cache_key"],"status":row["status"]};receipt["receipt_sha256"]=_receipt_hash(receipt);persist_json(root/"probe_receipt.json",receipt);print(f"PLAN10 PROBE {'PASS' if receipt['success'] else 'UNRESOLVED'} — output: {root.resolve()}");return
    b=build_locked_requests(args.plan07_report,arm="P2b",spec=spec,source_store=args.source_store);paired=paired_experiment(a,b)
    if not _has_probe_proof(root,a,spec,plan07_report=args.plan07_report,source_store=args.source_store):raise BaselineError("paired-run requires a matching direct probe or warmup-probe receipt")
    needed=len(a["requests"])+len(b["requests"])
    if budget["max_requests"]<needed:raise BaselineError(f"paired-run needs configured/request cap >= {needed}")
    preflight=_preflight((a,b),budget,recovery,warmup);_require_preflight(preflight)
    persist_json(root/"remote_paired_experiment.json",paired)
    arms={};runtime_usage={"requests":0,"reserved_input_tokens":0,"reserved_output_tokens":0,"reserved_usd_micros":0};recovery_identity=canonical_hash({"paired":canonical_hash(paired),"model":cfg["model"],"recovery":recovery,"warmup":warmup});recovery_path=root/"recovery_ledger.json";recovery_state=recovery_ledger(recovery_path,identity=recovery_identity,budget=budget,recovery=recovery)
    for arm,m in (("P2a",a),("P2b",b)):
        rows=execute_remote(m,plan07_report=args.plan07_report,source_store=args.source_store,cache_dir=root/"remote_cache"/arm,cfg=cfg,max_requests=budget["max_requests"],budget=budget,usage_state=runtime_usage,recovery=recovery,recovery_state=recovery_state,recovery_ledger_path=recovery_path,warmup=warmup);arms[arm]={"input_manifest_sha256":canonical_hash(m),"request_ledger":[{"request_id":x["request"]["request_id"],"cache_key":x["cache_key"],"status":x["status"],"finish_reason":x["receipt"].get("finish_reason"),"failure_kind":x["receipt"].get("failure_diagnostic",{}).get("kind"),"failure_class":x["receipt"].get("failure_class"),"recovery":x.get("recovery")} for x in rows],"accounting":_account(rows)};persist_json(root/f"remote_runs/{arm}.json",{"artifact_type":"Plan10RemoteRun","schema_version":"plan10-au-runtime-v1","evaluation_against":"model_silver","semantic_gold":False,"retrieval_quality_claim":False,"arm":arm,**arms[arm]})
    status,reason,completion_status=_paired_completion(arms,expected_requests=paired["pair_count"]*2)
    comparison={"artifact_type":"Plan10RemoteComparison","schema_version":"plan10-au-runtime-v1","evaluation_against":"model_silver","semantic_gold":False,"retrieval_quality_claim":False,"status":status,"completion_status":completion_status,"completion_reason":reason,"paired_experiment_sha256":canonical_hash(paired),"preflight_reservation":preflight,"runtime_reservation":runtime_usage,"recovery":{"config":recovery,"provider_attempts":recovery_state,"warmup_config":warmup},"arms":arms};persist_json(root/"remote_comparison.json",comparison)
    print(f"PLAN10 PAIRED RUN {'COMPLETE' if status=='complete' else 'INCOMPLETE'} — output: {root.resolve()}")
if __name__=="__main__":main()
