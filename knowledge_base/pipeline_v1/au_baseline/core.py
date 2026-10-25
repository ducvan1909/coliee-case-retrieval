"""Plan 10 zero-shot AU baseline. Remote execution is explicit and receipt-backed."""
from __future__ import annotations
import hashlib, json, math, os, re, time
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from jsonschema import Draft202012Validator

from ..analysis_regions.renderer import render_base_region, render_region
from ..execution_ledger.build import load_plan07_workloads
from ..sentence_atoms.segmenter import canonical_hash
from ..source_contract import open_source

PROMPT_VERSION="plan10-au-zero-shot-v1"
SCHEMA_VERSION="plan10-au-model-output-v1"
RUN_SCHEMA_VERSION="plan10-au-runtime-v1"
SCHEMA_PATH=Path(__file__).resolve().parents[1]/"contracts"/"plan10_au_model_output.v1.json"
SCHEMA_VALIDATOR=Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
class BaselineError(ValueError): pass
class ProviderResponseError(BaselineError):
    def __init__(self,message,diagnostic): super().__init__(message);self.diagnostic=diagnostic

def arm_spec(model="mock-local-v1",examples=(),caps=None,enable_thinking=False):
    return {"model":model,"enable_thinking":enable_thinking,"prompt":PROMPT_VERSION,"schema":SCHEMA_VERSION,"schema_sha256":hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),"examples":list(examples),"caps":caps or {"targets":4,"output_tokens":1200,"au_candidates":8}}
def assert_equivalent(a,b):
    if a!=b: raise BaselineError("P2a/P2b control mismatch")
def _boundary(v):
    if v.get("evaluation_against")!="model_silver" or v.get("semantic_gold") is not False or v.get("retrieval_quality_claim") is not False: raise BaselineError("Plan 10 boundary violation")
def _hint_payload(q): return q.get("hint_payload",{"version":"context-hint-payload-v1","hint_ids":[]})
def _hint_payload_sha256(q): return q.get("hint_payload_sha256",canonical_hash(_hint_payload(q)))
def _rid(q): return "p10-"+canonical_hash({**{k:q[k] for k in ("arm","source_hash","region_id","render_sha256","spec")},"hint_payload_sha256":_hint_payload_sha256(q)})[:24]
def cache_key(q): return canonical_hash({**{k:q[k] for k in ("arm","source_hash","region_id","region_fingerprint","render_sha256","spec")},"hint_payload_sha256":_hint_payload_sha256(q),"input_tokens":q.get("input_tokens")})
def _atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");os.replace(tmp,path)
def _cache_path(root,key): return Path(root)/key[:2]/key/"response.json"
def _spans(r): return [(x["span"]["start_char"],x["span"]["end_char"]) for x in r["render_items"]]
def _repeat(intervals,seen):
    """Count overlap with a union of previously rendered intervals, then merge."""
    def merge(parts):
        out=[]
        for a,b in sorted((a,b) for a,b in parts):
            if not out or a>out[-1][1]: out.append([a,b])
            else: out[-1][1]=max(out[-1][1],b)
        return out
    incoming=merge(intervals);prior=merge(seen)
    n=sum(max(0,min(b,d)-max(a,c)) for a,b in incoming for c,d in prior)
    seen[:]=merge([*prior,*incoming]);return n

def build_locked_requests(plan07_report,*,arm,spec,source_store=None):
    if arm not in {"P2a","P2b"}: raise BaselineError("unknown arm")
    workload,report,build=load_plan07_workloads(str(plan07_report));store=Path(source_store or report["inputs"]["source_store"]);rows=[];seen={};context_seen={};assigned_targets=set()
    for work in sorted(workload,key=lambda x:x["case_id"]):
        text=open_source(store,work["case_id"],work["source_hash"])
        if hashlib.sha256(text.encode()).hexdigest()!=work["source_hash"]: raise BaselineError("locked source hash mismatch")
        batches={b["batch_id"]:sorted({x["target_id"] for x in b["work_items"]}) for b in work["batches"]}
        for r in sorted((x for x in work["regions"] if x["arm"]==arm),key=lambda x:x["region_id"]):
            expected=batches.get(r["batch_id"])
            if not expected or expected!=sorted(r["target_ids"]): raise BaselineError("region/batch target identity mismatch")
            duplicate={(work["case_id"],target_id) for target_id in expected}&assigned_targets
            if duplicate: raise BaselineError("duplicate AnalysisTarget across Plan 10 requests: "+repr(sorted(duplicate)))
            assigned_targets.update((work["case_id"],target_id) for target_id in expected)
            rendered=render_base_region(text,r);hints={"version":"context-hint-payload-v1","hint_ids":r["included_hint_ids"] if arm=="P2b" else []}; spans=_spans(r); context_spans=[(x["span"]["start_char"],x["span"]["end_char"]) for x in r["render_items"] if x["role"]=="context"]
            q={"case_id":work["case_id"],"source_hash":work["source_hash"],"arm":arm,"region_id":r["region_id"],"batch_id":r["batch_id"],"region_fingerprint":r["fingerprint"],"expected_target_ids":expected,"spec":spec,"render_sha256":hashlib.sha256(rendered.encode()).hexdigest(),"base_render_sha256":hashlib.sha256(rendered.encode()).hexdigest(),"hint_payload":hints,"hint_payload_sha256":canonical_hash(hints),"rendered_chars":len(rendered),"rendered_spans":[{"start":a,"end":b} for a,b in spans],"repeated_source_chars":_repeat(spans,seen.setdefault(work["case_id"],[])),"repeated_context_chars":_repeat(context_spans,context_seen.setdefault(work["case_id"],[])),"rendered_input_tokens":math.ceil(len(rendered)/r["token_estimator"]["chars_per_token"])};q["request_id"]=_rid(q);q["estimated_prompt_input_tokens"]=estimate_prompt_input_tokens(q,rendered,r["token_estimator"]["chars_per_token"]);q["input_tokens"]=q["estimated_prompt_input_tokens"];rows.append(q)
    out={"artifact_type":"Plan10InputManifest","schema_version":RUN_SCHEMA_VERSION,"evaluation_against":"model_silver","semantic_gold":False,"retrieval_quality_claim":False,"workload":"KOS-5","plan07_build_manifest_sha256":canonical_hash(build),"arm":arm,"spec":spec,"requests":rows};_boundary(out);return out

def paired_experiment(a,b):
    _boundary(a);_boundary(b);assert_equivalent(a["spec"],b["spec"]);am={(x["case_id"],x["batch_id"]):x for x in a["requests"]};bm={(x["case_id"],x["batch_id"]):x for x in b["requests"]}
    if len(am)!=len(a["requests"]) or len(bm)!=len(b["requests"]) or len({x["request_id"] for x in a["requests"]})!=len(a["requests"]) or len({x["request_id"] for x in b["requests"]})!=len(b["requests"]): raise BaselineError("duplicate P2a/P2b request identity")
    empty={"version":"context-hint-payload-v1","hint_ids":[]}
    if set(am)!=set(bm) or any(am[k]["expected_target_ids"]!=bm[k]["expected_target_ids"] or am[k]["base_render_sha256"]!=bm[k]["base_render_sha256"] or am[k]["hint_payload"]!=empty or am[k]["hint_payload_sha256"]!=canonical_hash(empty) or bm[k]["hint_payload"].get("version")!="context-hint-payload-v1" or bm[k]["hint_payload_sha256"]!=canonical_hash(bm[k]["hint_payload"]) for k in am): raise BaselineError("P2a/P2b base pairing mismatch")
    return {"artifact_type":"Plan10PairedExperiment","schema_version":RUN_SCHEMA_VERSION,"evaluation_against":"model_silver","semantic_gold":False,"retrieval_quality_claim":False,"control":{"same_model_prompt_schema_examples_caps":True,"same_case_batch_target_base_render_pairs":True,"same_source_context":True,"p2b_separate_context_hint_payload":True},"p2a_input_manifest_sha256":canonical_hash(a),"p2b_input_manifest_sha256":canonical_hash(b),"pair_count":len(am)}

def prompt_for(q,rendered):
    schema=SCHEMA_PATH.read_text(encoding="utf-8")
    lead="Return ONLY one complete JSON object conforming to the supplied Plan 10 schema; no prose, explanation, or thinking text." if q["spec"].get("structural_repair",False) else "Return ONLY JSON conforming to the supplied Plan 10 schema. Extract evidence-backed candidate Authority Units from this region only. Use global raw source offsets and exact quotes. Each expected target must be exactly once: positive, hard_negative, or unresolved."
    hint="\nCONTEXT_HINT_PAYLOAD="+json.dumps(_hint_payload(q),sort_keys=True,separators=(",",":"))
    return lead+"\nREQUEST_ID="+q["request_id"]+"\nEXPECTED_TARGET_IDS="+json.dumps(q["expected_target_ids"])+hint+"\nSCHEMA="+schema+"\nREGION:\n"+rendered
def modal_payload(q,rendered):
    return {"model":q["spec"]["model"],"messages":[{"role":"user","content":prompt_for(q,rendered)}],"temperature":0,"max_tokens":q["spec"]["caps"]["output_tokens"],"response_format":{"type":"json_object"},"chat_template_kwargs":{"enable_thinking":q["spec"]["enable_thinking"]}}
def estimate_prompt_input_tokens(q,rendered,chars_per_token=4):
    """Estimate the exact JSON request body sent to chat/completions, not just region text."""
    return math.ceil(len(json.dumps(modal_payload(q,rendered)))/chars_per_token)
def parse_model_json_content(content):
    """Accept only raw JSON, an initial complete thinking block, and one JSON fence."""
    if not isinstance(content,str): raise ValueError("message content is not text")
    value=content.strip()
    if value.startswith("<think>"):
        close=value.find("</think>")
        if close<0: raise ValueError("unclosed thinking block")
        value=value[close+len("</think>"):].strip()
    match=re.fullmatch(r"```json\s*\n?(.*?)\n?```",value,flags=re.DOTALL)
    if match: value=match.group(1).strip()
    return json.loads(value)
def _span(x,source): return isinstance(x,dict) and isinstance(x.get("start_char"),int) and isinstance(x.get("end_char"),int) and 0<=x["start_char"]<x["end_char"]<=len(source) and source[x["start_char"]:x["end_char"]]==x.get("quote")
def validate_response(q,r,source_text):
    errors=sorted(SCHEMA_VALIDATOR.iter_errors(r),key=lambda e:list(e.absolute_path))
    if errors: raise BaselineError("schema validation failed: "+errors[0].message)
    req={"schema_version","request_id","processed_target_ids","target_results","context_requests","warnings"}
    if not isinstance(r,dict) or set(r)!=req or r["schema_version"]!=SCHEMA_VERSION or r["request_id"]!=q["request_id"]: raise BaselineError("invalid response envelope")
    expected=set(q["expected_target_ids"]);processed=r["processed_target_ids"]
    if len(processed)!=len(set(processed)) or set(processed)!=expected: raise BaselineError("missing/foreign target")
    results=r["target_results"]
    if len(results)!=len(expected) or {x.get("target_id") for x in results}!=expected: raise BaselineError("target result uniqueness/coverage")
    known={}
    for row in results:
        decision=row.get("decision");units=row.get("authority_units")
        if decision not in {"positive","hard_negative","unresolved"} or not isinstance(units,list) or ((decision=="positive")!=bool(units)): raise BaselineError("invalid target decision")
        if decision=="hard_negative" and (row.get("hard_negative_reason") is None or row.get("unresolved_reason") is not None): raise BaselineError("invalid hard negative")
        if decision=="unresolved" and (row.get("unresolved_reason") is None or row.get("hard_negative_reason") is not None): raise BaselineError("invalid unresolved")
        ids=set()
        if len(units)>q.get("spec",{}).get("caps",{}).get("au_candidates",8): raise BaselineError("AU candidate cap exceeded")
        for au in units:
            aid=au.get("local_au_id");sp=au.get("evidence_spans",[]);attrs=au.get("attributions",[])
            if not isinstance(aid,str) or aid in ids or any(aid in x for x in known.values()) or not sp or not all(_span(s,source_text) for s in sp) or not attrs or not all(_span(a.get("evidence_span"),source_text) for a in attrs): raise BaselineError("invalid AU")
            for name in ("condition_spans","exception_spans","limit_spans"):
                if not isinstance(au.get(name),list) or not all(_span(s,source_text) for s in au[name]): raise BaselineError("invalid qualifier span")
            ids.add(aid)
        known[row["target_id"]]=ids
    for c in r["context_requests"]:
        if c.get("target_id") not in expected or (c.get("au_local_id") is not None and c["au_local_id"] not in known[c["target_id"]]) or (c.get("anchor_span") is not None and not _span(c["anchor_span"],source_text)): raise BaselineError("invalid context reference")
    return True

def modal_config(env=None,*,require_credentials=True):
    e=os.environ if env is None else env;url=str(e.get("PLX_ENDPOINT_URL","")).strip().rstrip("/");token=str(e.get("PLX_PROXY_TOKEN","")).strip() or (str(e.get("PLX_MODAL_KEY","")).strip()+":"+str(e.get("PLX_MODAL_SECRET","")).strip()).strip(":")
    if not url.startswith("https://"): raise BaselineError("PLX_ENDPOINT_URL must be HTTPS")
    if require_credentials and not token: raise BaselineError("missing Plan 10 Modal credentials")
    model=str(e.get("PLX_MODEL") or "Qwen/Qwen3.5-9B").strip()
    if not model: raise BaselineError("PLX_MODEL must not be blank")
    raw_thinking=str(e.get("PLX_ENABLE_THINKING","false")).strip().lower()
    if raw_thinking not in {"true","false"}: raise BaselineError("PLX_ENABLE_THINKING must be true or false")
    return {"url":url if url.endswith("/chat/completions") else url+"/chat/completions","token":token,"model":model,"enable_thinking":raw_thinking=="true","timeout":int(e.get("PLX_COLD_START_WAIT_SECONDS",600))}
def _limit(env,key,default,*,allow_none=False):
    raw=str(env.get(key,default)).strip().lower()
    if allow_none and raw in {"","none","unlimited","off"}: return None
    try: value=int(raw)
    except ValueError as exc: raise BaselineError(f"{key} must be an integer") from exc
    if value<=0: raise BaselineError(f"{key} must be positive")
    return value
def _nonnegative(env,key,default=0):
    try: value=int(str(env.get(key,default)).strip())
    except ValueError as exc: raise BaselineError(f"{key} must be a non-negative integer") from exc
    if value<0: raise BaselineError(f"{key} must be non-negative")
    return value
def _optional_limit(env,key):
    raw=str(env.get(key,"")).strip().lower()
    if raw in {"","none","unlimited","off"}: return None
    return _limit(env,key,1)
def plan10_budget(env=None):
    """Dedicated limits only; no KB_* cost assumptions are reused."""
    e=os.environ if env is None else env
    hard=_limit(e,"PLX_MAX_OUTPUT_TOKENS",2400);baseline=_limit(e,"PLX_BASELINE_OUTPUT_TOKENS",1200);repair=_limit(e,"PLX_STRUCTURAL_REPAIR_OUTPUT_TOKENS",2400)
    if baseline>hard or repair>hard: raise BaselineError("baseline/structural repair output cap exceeds PLX_MAX_OUTPUT_TOKENS hard ceiling")
    budget={"max_requests":_limit(e,"PLX_MAX_REQUESTS",1),"max_provider_attempts":_limit(e,"PLX_MAX_PROVIDER_ATTEMPTS",200),"max_input_tokens":_limit(e,"PLX_MAX_INPUT_TOKENS",12000),"max_output_tokens":hard,"max_total_input_tokens":_optional_limit(e,"PLX_MAX_TOTAL_INPUT_TOKENS"),"max_total_output_tokens":_optional_limit(e,"PLX_MAX_TOTAL_OUTPUT_TOKENS"),"baseline_output_tokens":baseline,"structural_repair_output_tokens":repair,"max_usd_micros":_limit(e,"PLX_MAX_USD_MICROS","none",allow_none=True),"input_usd_micros_per_1k":_nonnegative(e,"PLX_INPUT_USD_MICROS_PER_1K"),"output_usd_micros_per_1k":_nonnegative(e,"PLX_OUTPUT_USD_MICROS_PER_1K")}
    if budget["max_usd_micros"] is not None and not (budget["input_usd_micros_per_1k"] or budget["output_usd_micros_per_1k"]): raise BaselineError("USD cap requires Plan 10 endpoint prices")
    return budget
def recovery_config(env=None):
    e=os.environ if env is None else env;cycles=_limit(e,"PLX_MAX_RECOVERY_CYCLES",1);retries=_nonnegative(e,"PLX_RECOVERY_SOURCE_RETRIES",1)
    if cycles>3 or retries>1: raise BaselineError("recovery limits exceed the bounded paired-run contract")
    return {"max_recovery_cycles":cycles,"max_source_retries":retries}
def _usd_micros(tokens,rate): return math.ceil(tokens*rate/1000)
def _failure_diagnostic(error_class,*,http_status=None,response_bytes=None,retryable=False,kind="transport"):
    """Receipt-safe provider diagnostic: no headers, credentials, prompt, or body."""
    return {"error_class":error_class,"kind":kind,"http_status":http_status,"retryable":retryable,"response_sha256":hashlib.sha256(response_bytes).hexdigest() if response_bytes is not None else None,"response_byte_length":len(response_bytes) if response_bytes is not None else None,"diagnostic":("http_status_"+str(http_status) if http_status is not None else kind)}
def _shape_diagnostic(error_class,body,raw_bytes):
    """Values may contain prompts/secrets; retain only top-level names and types."""
    diagnostic=_failure_diagnostic(error_class,response_bytes=raw_bytes,retryable=False,kind="invalid_envelope")
    diagnostic["top_level"]={str(k):type(v).__name__ for k,v in sorted(body.items(),key=lambda x:str(x[0]))[:16]} if isinstance(body,dict) else {"<root>":type(body).__name__}
    return diagnostic
def warmup_config(env=None):
    """Bounded cold-start controls; this is separate from AU/P2 request budgets."""
    e=os.environ if env is None else env
    initial=_limit(e,"PLX_WARMUP_INITIAL_BACKOFF_SECONDS",2)
    maximum=_limit(e,"PLX_WARMUP_MAX_BACKOFF_SECONDS",30)
    if maximum>60 or initial>maximum: raise BaselineError("warmup backoff must satisfy 0 < initial <= max <= 60")
    return {"max_attempts":_limit(e,"PLX_WARMUP_MAX_ATTEMPTS",3),"max_seconds":_limit(e,"PLX_WARMUP_MAX_SECONDS",120),"initial_backoff_seconds":initial,"max_backoff_seconds":maximum}
def warm_probe_config(env=None):
    e=os.environ if env is None else env
    attempts=_limit(e,"PLX_WARM_PROBE_MAX_PROBE_ATTEMPTS",2)
    if not 1<=attempts<=2: raise BaselineError("PLX_WARM_PROBE_MAX_PROBE_ATTEMPTS must be in [1, 2]")
    return {"max_probe_attempts":attempts}
def _warmup_payload(cfg): return {"model":cfg["model"],"messages":[{"role":"user","content":"Reply exactly OK."}],"temperature":0,"max_tokens":4,"chat_template_kwargs":{"enable_thinking":cfg.get("enable_thinking",False)}}
def call_warmup(cfg,*,opener=urlrequest.urlopen):
    """One source-free availability request. Never return or persist the body itself."""
    payload=_warmup_payload(cfg);req=urlrequest.Request(cfg["url"],data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+cfg["token"],"Content-Type":"application/json"},method="POST");started=time.perf_counter();raw_bytes=None
    try:
        with opener(req,timeout=cfg["timeout"]) as h: raw_bytes=h.read();body=json.loads(raw_bytes.decode())
        if not isinstance(body,dict) or "error" in body or not isinstance(body.get("choices"),list) or not body["choices"] or not isinstance(body["choices"][0],dict): raise ProviderResponseError("warmup invalid OpenAI envelope",_shape_diagnostic("EnvelopeShapeError",body,raw_bytes))
        choice=body["choices"][0];usage=body.get("usage",{})
        if not isinstance(usage,dict): raise ProviderResponseError("warmup invalid usage shape",_shape_diagnostic("EnvelopeShapeError",body,raw_bytes))
    except HTTPError as exc:
        try: body_bytes=exc.read()
        except Exception: body_bytes=None
        raise ProviderResponseError("warmup HTTP failure",_failure_diagnostic(type(exc).__name__,http_status=exc.code,response_bytes=body_bytes,retryable=exc.code in {429,502,503,504},kind="http")) from exc
    except (URLError,TimeoutError) as exc: raise ProviderResponseError("warmup transport failure",_failure_diagnostic(type(exc).__name__,retryable=True,kind="transport")) from exc
    except (KeyError,TypeError,json.JSONDecodeError) as exc: raise ProviderResponseError("warmup response malformed",_failure_diagnostic(type(exc).__name__,response_bytes=raw_bytes,retryable=False,kind="malformed_response")) from exc
    return {"status":"success","finish_reason":choice.get("finish_reason"),"usage":{"input_tokens":int(usage.get("prompt_tokens",0)),"output_tokens":int(usage.get("completion_tokens",0)),"total_tokens":int(usage.get("total_tokens",0))},"latency_ms":max(1,int((time.perf_counter()-started)*1000))}
def run_warmup(*,output_root,cfg,warmup,opener=urlrequest.urlopen,sleep_fn=time.sleep,time_fn=time.time):
    """Persisted, resumable warmup with a hard attempt/time bound and no AU state."""
    root=Path(output_root)/"warmup";state_path=root/"current.json";state=json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {"artifact_type":"Plan10WarmupLedger","schema_version":"plan10-warmup-v1","model":cfg["model"],"enable_thinking":cfg.get("enable_thinking",False),"started_unix":time_fn(),"attempts":[],"status":"pending"}
    if state.get("model")!=cfg["model"] or state.get("enable_thinking")!=cfg.get("enable_thinking",False): raise BaselineError("warmup ledger model/thinking mismatch")
    if state.get("status") in {"success","stopped"}: return state
    while len(state["attempts"])<warmup["max_attempts"]:
        elapsed=max(0,time_fn()-state["started_unix"])
        if elapsed>=warmup["max_seconds"]: state["status"]="stopped";state["stop_reason"]="time_cap";_atomic(state_path,state);return state
        attempt={"ordinal":len(state["attempts"])+1,"started_elapsed_seconds":elapsed}
        try:
            result=call_warmup(cfg,opener=opener);attempt.update(result);state["attempts"].append(attempt);state["status"]="success";state["stop_reason"]=None;_atomic(state_path,state);return state
        except ProviderResponseError as exc:
            attempt.update({"status":"failed","failure_diagnostic":exc.diagnostic});state["attempts"].append(attempt);_atomic(state_path,state)
            if not exc.diagnostic["retryable"]: state["status"]="stopped";state["stop_reason"]="nonretryable_failure";_atomic(state_path,state);return state
        except Exception as exc:
            attempt.update({"status":"failed","failure_diagnostic":_failure_diagnostic(type(exc).__name__,retryable=False,kind="unexpected")});state["attempts"].append(attempt);state["status"]="stopped";state["stop_reason"]="unexpected_failure";_atomic(state_path,state);return state
        if len(state["attempts"])>=warmup["max_attempts"]: break
        delay=min(warmup["initial_backoff_seconds"]*(2**(len(state["attempts"])-1)),warmup["max_backoff_seconds"],60)
        if time_fn()-state["started_unix"]+delay>warmup["max_seconds"]: state["status"]="stopped";state["stop_reason"]="time_cap";_atomic(state_path,state);return state
        attempt["next_backoff_seconds"]=delay;_atomic(state_path,state);sleep_fn(delay)
    state["status"]="stopped";state["stop_reason"]="attempt_cap";_atomic(state_path,state);return state
def _safe_probe_receipt(row):
    receipt={k:v for k,v in row["receipt"].items() if k!="raw_provider_response"}
    return {"request_id":row["request"]["request_id"],"request_sha256":canonical_hash(row["request"]),"cache_key":row["cache_key"],"status":row["status"],"receipt":receipt}
def _probe_retryable(row):
    return row["status"]=="unresolved" and bool(row["receipt"].get("failure_diagnostic",{}).get("retryable"))
def run_warmup_probe(*,output_root,cfg,warmup,warm_probe,manifest,plan07_report,source_store,budget,opener=urlrequest.urlopen,sleep_fn=time.sleep,time_fn=time.time):
    """Bounded warmup -> one source probe, with at most one retryable source retry."""
    if len(manifest["requests"])<1: raise BaselineError("warmup-probe needs a locked P2a request")
    if not isinstance(warm_probe.get("max_probe_attempts"),int) or not 1<=warm_probe["max_probe_attempts"]<=2: raise BaselineError("warmup-probe max_probe_attempts must be in [1, 2]")
    root=Path(output_root)/"warmup_probe";state_path=root/"current.json";request=manifest["requests"][0]
    identity={"input_manifest_sha256":canonical_hash(manifest),"request_sha256":canonical_hash(request),"spec_sha256":canonical_hash(manifest["spec"]),"model":cfg["model"],"enable_thinking":cfg.get("enable_thinking",False)}
    state=json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {"artifact_type":"Plan10WarmupProbeLedger","schema_version":"plan10-warmup-probe-v1","status":"pending","stop_reason":None,**identity,"warmup_cycles":[],"probe_attempts":[]}
    if any(state.get(k)!=v for k,v in identity.items()): raise BaselineError("warmup-probe identity mismatch")
    if state.get("status") in {"success","stopped"}: return state
    while len(state["probe_attempts"])<warm_probe["max_probe_attempts"]:
        cycle=len(state["warmup_cycles"])+1;cycle_root=root/"warmup_cycles"/f"cycle-{cycle}"
        warm_state=run_warmup(output_root=cycle_root,cfg=cfg,warmup=warmup,opener=opener,sleep_fn=sleep_fn,time_fn=time_fn)
        state["warmup_cycles"].append({"cycle":cycle,"ref":str((cycle_root/"warmup/current.json").relative_to(root)),"status":warm_state["status"],"stop_reason":warm_state.get("stop_reason")});_atomic(state_path,state)
        if warm_state["status"]!="success": state["status"]="stopped";state["stop_reason"]="warmup_"+str(warm_state.get("stop_reason") or "failed");_atomic(state_path,state);return state
        probe_manifest={**manifest,"requests":[request]};rows=execute_remote(probe_manifest,plan07_report=plan07_report,source_store=source_store,cache_dir=root/"source_probe_cache"/f"attempt-{cycle}",cfg=cfg,max_requests=1,budget={**budget,"max_requests":1},opener=opener);row=rows[0];state["probe_attempts"].append({"ordinal":cycle,**_safe_probe_receipt(row)});_atomic(state_path,state)
        if row["status"]=="protocol_verified": state["status"]="success";state["stop_reason"]=None;_atomic(state_path,state);return state
        if row["receipt"].get("failure_diagnostic",{}).get("kind")=="output_truncated":
            repair_cap=budget.get("structural_repair_output_tokens",2400)
            if repair_cap>budget.get("max_output_tokens",repair_cap):
                state["probe_attempts"].append({"ordinal":cycle,"trigger":"output_truncated","status":"budget_stopped","stop_reason":"structural_repair_cap_exceeds_hard_ceiling"});state["status"]="stopped";state["stop_reason"]="structural_repair_blocked";_atomic(state_path,state);return state
            lookup,_=_region_map(plan07_report,source_store);source,region=lookup[(request["case_id"],request["region_id"])];repair=structural_repair_request(request,source,region,repair_cap);repair_manifest={**manifest,"spec":repair["spec"],"requests":[repair]};repair_row=execute_remote(repair_manifest,plan07_report=plan07_report,source_store=source_store,cache_dir=root/"source_probe_cache"/f"attempt-{cycle}-structural-repair",cfg=cfg,max_requests=1,budget={**budget,"max_requests":1},opener=opener)[0]
            state["probe_attempts"].append({"ordinal":cycle,"trigger":"output_truncated","first_request_id":request["request_id"],"repeated_source_chars":repair["repeated_source_chars"],"input_token_delta":repair["input_tokens"]-request["input_tokens"],**_safe_probe_receipt(repair_row)});_atomic(state_path,state)
            if repair_row["status"]=="protocol_verified": state["status"]="success";state["stop_reason"]=None;_atomic(state_path,state);return state
            state["status"]="stopped";state["stop_reason"]="structural_repair_failed";_atomic(state_path,state);return state
        if not _probe_retryable(row): state["status"]="stopped";state["stop_reason"]="probe_nonretryable";_atomic(state_path,state);return state
    state["status"]="stopped";state["stop_reason"]="probe_attempt_cap";_atomic(state_path,state);return state
def call_modal(cfg,q,rendered,*,opener=urlrequest.urlopen):
    if cfg["model"]!=q["spec"]["model"] or cfg.get("enable_thinking",False)!=q["spec"]["enable_thinking"]: raise BaselineError("configured model/thinking differs from frozen request spec")
    payload=modal_payload(q,rendered)
    req=urlrequest.Request(cfg["url"],data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+cfg["token"],"Content-Type":"application/json"},method="POST");started=time.perf_counter()
    raw_bytes=None
    try:
        with opener(req,timeout=cfg["timeout"]) as h: raw_bytes=h.read();body=json.loads(raw_bytes.decode())
        choice=body["choices"][0];usage=body.get("usage",{});safe_usage={"input_tokens":int(usage.get("prompt_tokens",0)),"output_tokens":int(usage.get("completion_tokens",0)),"total_tokens":int(usage.get("total_tokens",0))};finish_reason=choice.get("finish_reason");safe={"finish_reason":finish_reason,"provider_usage":safe_usage,"provider_latency_ms":max(1,int((time.perf_counter()-started)*1000))}
        if finish_reason=="length": raise ProviderResponseError("provider output truncated",{**_failure_diagnostic("OutputTruncated",response_bytes=raw_bytes,retryable=False,kind="output_truncated"),**safe})
        answer=parse_model_json_content(choice["message"]["content"])
    except HTTPError as exc:
        try: body_bytes=exc.read()
        except Exception: body_bytes=None
        raise ProviderResponseError("provider HTTP failure",_failure_diagnostic(type(exc).__name__,http_status=exc.code,response_bytes=body_bytes,retryable=exc.code in {408,429,500,502,503,504},kind="http")) from exc
    except (URLError,TimeoutError) as exc: raise ProviderResponseError("provider transport failure",_failure_diagnostic(type(exc).__name__,retryable=True,kind="transport")) from exc
    except ProviderResponseError: raise
    except (KeyError,TypeError,ValueError,json.JSONDecodeError) as exc:
        diagnostic=_failure_diagnostic(type(exc).__name__,response_bytes=raw_bytes,retryable=False,kind="malformed_response")
        if "safe" in locals(): diagnostic.update(safe)
        raise ProviderResponseError("provider response malformed",diagnostic) from exc
    return answer,{"provider":"modal_dedicated_openai_compatible","model":cfg["model"],"enable_thinking":cfg.get("enable_thinking",False),"finish_reason":finish_reason,"usage":safe_usage,"latency_ms":safe["provider_latency_ms"],"raw_provider_response":body}
def _unresolved(q,reason): return {"schema_version":SCHEMA_VERSION,"request_id":q["request_id"],"processed_target_ids":q["expected_target_ids"],"target_results":[{"target_id":t,"decision":"unresolved","authority_units":[],"hard_negative_reason":None,"unresolved_reason":"other","reason_detail":reason} for t in q["expected_target_ids"]],"context_requests":[],"warnings":[{"code":"other","target_id":None,"detail":reason}]}
def _region_map(plan07_report,source_store):
    works,report,_=load_plan07_workloads(str(plan07_report));store=Path(source_store or report["inputs"]["source_store"]);return {(w["case_id"],r["region_id"]):(open_source(store,w["case_id"],w["source_hash"]),r) for w in works for r in w["regions"]},store
def structural_repair_request(q,source,region,output_tokens):
    """Distinct frozen request after a length stop; no source expansion or semantic repair."""
    repair=json.loads(json.dumps(q));repair["spec"]={**q["spec"],"prompt":"plan10-au-structural-repair-v1","structural_repair":True,"caps":{**q["spec"]["caps"],"output_tokens":output_tokens}}
    repair["repair_of_request_id"]=q["request_id"];repair["repair_trigger"]="output_truncated";repair["request_id"]=_rid(repair)
    rendered=render_region(source,region);repair["estimated_prompt_input_tokens"]=estimate_prompt_input_tokens(repair,rendered,region["token_estimator"]["chars_per_token"]);repair["input_tokens"]=repair["estimated_prompt_input_tokens"]
    repair["repeated_source_chars"]=sum(x["end"]-x["start"] for x in repair["rendered_spans"]);repair["repeated_context_chars"]=repair.get("repeated_context_chars",0)
    return repair
def _stopped_row(q,reason,model):
    return {"cache_key":cache_key(q),"request":q,"response":_unresolved(q,reason),"receipt":{"provider":"modal_dedicated_openai_compatible","model":model,"finish_reason":"host_unresolved","usage":{"input_tokens":0,"output_tokens":0,"total_tokens":0},"latency_ms":0,"stop_reason":reason},"status":"budget_stopped"}
def _archive_attempt(path,row,reason):
    """Preserve an immutable prior row before a budget or provider retry."""
    history=path.parent/"attempt_history";prior_sha256=canonical_hash(row);entries=sorted(history.glob("*.json"))
    archived={"artifact_type":"Plan10RemoteAttemptHistory","schema_version":RUN_SCHEMA_VERSION,"archive_reason":reason,"cache_key":row["cache_key"],"request_id":row["request"]["request_id"],"request_sha256":canonical_hash(row["request"]),"prior_row_sha256":prior_sha256,"prior_row":row}
    _atomic(history/f"{len(entries)+1:04d}-{prior_sha256[:16]}.json",archived)
def _retryable_provider_row(row):
    diagnostic=row.get("receipt",{}).get("failure_diagnostic",{})
    return row.get("status")=="unresolved" and diagnostic.get("retryable") is True and diagnostic.get("kind") in {"http","transport"}
def _provider_unavailable_row(row): return row.get("status")=="budget_stopped" and row.get("receipt",{}).get("stop_reason")=="provider_unavailable"
def recovery_ledger(path,*,identity,budget,recovery):
    path=Path(path);policy_hash=canonical_hash(recovery);budget_hash=canonical_hash(budget)
    if path.is_file():
        state=json.loads(path.read_text(encoding="utf-8"))
        if state.get("identity")!=identity or state.get("policy_sha256")!=policy_hash or state.get("budget_sha256")!=budget_hash: raise BaselineError("recovery ledger identity/policy/budget mismatch")
        return state
    state={"artifact_type":"Plan10RecoveryLedger","schema_version":RUN_SCHEMA_VERSION,"identity":identity,"policy_sha256":policy_hash,"budget_sha256":budget_hash,"cycles_used":0,"provider_attempts":0,"source_attempts":0,"warmup_attempts":0,"circuit_open":False,"events":[]};_atomic(path,state);return state
def _provider_attempt(state,budget,kind,checkpoint=lambda:None):
    if state["provider_attempts"]>=budget["max_provider_attempts"]: return False
    state["provider_attempts"]+=1;state[kind+"_attempts"]+=1;checkpoint();return True
def _recovery_warmup(*,root,cfg,warmup,budget,state,opener,checkpoint=lambda:None):
    before=state["provider_attempts"]
    def bounded_opener(*args,**kwargs):
        if not _provider_attempt(state,budget,"warmup",checkpoint): raise BaselineError("provider attempt budget exhausted during warmup")
        return opener(*args,**kwargs)
    value=run_warmup(output_root=root,cfg=cfg,warmup=warmup,opener=bounded_opener,sleep_fn=lambda _:None)
    return {"status":value["status"],"stop_reason":value.get("stop_reason"),"provider_attempts":state["provider_attempts"]-before}
def execute_remote(manifest,*,plan07_report,source_store,cache_dir,cfg,max_requests,budget=None,usage_state=None,recovery=None,recovery_state=None,recovery_ledger_path=None,warmup=None,opener=urlrequest.urlopen):
    qs=manifest["requests"]
    if len(qs)>max_requests: raise BaselineError("request cap would be exceeded")
    lookup,_=_region_map(plan07_report,source_store);rows=[]
    budget=budget or {"max_requests":max_requests,"max_provider_attempts":max_requests,"max_input_tokens":max(q["input_tokens"] for q in qs),"max_output_tokens":max(q["spec"]["caps"]["output_tokens"] for q in qs),"max_total_input_tokens":sum(q["input_tokens"] for q in qs),"max_total_output_tokens":sum(q["spec"]["caps"]["output_tokens"] for q in qs),"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0}
    budget={**budget,"max_provider_attempts":budget.get("max_provider_attempts",budget["max_requests"]),"max_total_input_tokens":budget.get("max_total_input_tokens",budget["max_input_tokens"]),"max_total_output_tokens":budget.get("max_total_output_tokens",budget["max_output_tokens"])}
    used=usage_state if usage_state is not None else {"requests":0,"reserved_input_tokens":0,"reserved_output_tokens":0,"reserved_usd_micros":0}
    for key in ("requests","reserved_input_tokens","reserved_output_tokens","reserved_usd_micros"): used.setdefault(key,0)
    recovery=recovery or {"max_recovery_cycles":0,"max_source_retries":0};warmup=warmup or {"max_attempts":1,"max_seconds":1,"initial_backoff_seconds":1,"max_backoff_seconds":1}
    state=recovery_state if recovery_state is not None else {"cycles_used":0,"provider_attempts":0,"source_attempts":0,"warmup_attempts":0,"circuit_open":False,"events":[]}
    for key in ("cycles_used","provider_attempts","source_attempts","warmup_attempts"): state.setdefault(key,0)
    state.setdefault("circuit_open",False)
    checkpoint=lambda: _atomic(recovery_ledger_path,state) if recovery_ledger_path else None
    def dispatch(q,source,region,*,logical=True):
        if not logical and (used["reserved_input_tokens"]+q["input_tokens"]>budget["max_total_input_tokens"] or used["reserved_output_tokens"]+q["spec"]["caps"]["output_tokens"]>budget["max_total_output_tokens"]): return _stopped_row(q,"budget_reservation_exceeded",cfg["model"])
        if not _provider_attempt(state,budget,"source",checkpoint): return _stopped_row(q,"provider_attempt_budget_exceeded",cfg["model"])
        rendered=render_region(source,region)
        try:
            result,receipt=call_modal(cfg,q,rendered,opener=opener)
            receipt.pop("raw_provider_response",None)
            if receipt["finish_reason"] in {"length","content_filter"}: raise ProviderResponseError("truncated finish_reason",{"kind":"output_truncated","finish_reason":receipt["finish_reason"],"provider_usage":receipt["usage"],"provider_latency_ms":receipt["latency_ms"],"retryable":False})
            try: validate_response(q,result,source);status="protocol_verified"
            except BaselineError as exc:
                result=_unresolved(q,"provider_or_protocol_failure");receipt.update({"failure_class":type(exc).__name__,"failure_diagnostic":_failure_diagnostic(type(exc).__name__,retryable=False,kind="host_validation")});status="unresolved"
        except BaselineError as exc:
            result=_unresolved(q,"provider_or_protocol_failure");diagnostic=getattr(exc,"diagnostic",_failure_diagnostic(type(exc).__name__,retryable=False,kind="protocol"));receipt={"provider":"modal_dedicated_openai_compatible","model":cfg["model"],"enable_thinking":cfg.get("enable_thinking",False),"finish_reason":diagnostic.get("finish_reason","host_unresolved"),"usage":diagnostic.get("provider_usage",{"input_tokens":0,"output_tokens":0,"total_tokens":0}),"latency_ms":diagnostic.get("provider_latency_ms",0),"failure_class":type(exc).__name__,"failure_diagnostic":diagnostic};status="unresolved"
        except Exception as exc:
            result=_unresolved(q,"adapter_failure");receipt={"provider":"modal_dedicated_openai_compatible","model":cfg["model"],"finish_reason":"host_unresolved","usage":{"input_tokens":0,"output_tokens":0,"total_tokens":0},"latency_ms":0,"failure_class":"unexpected_"+type(exc).__name__};status="unresolved"
        if logical: used["requests"]+=1
        used["reserved_input_tokens"]+=q["input_tokens"];used["reserved_output_tokens"]+=q["spec"]["caps"]["output_tokens"];used["reserved_usd_micros"]+=_usd_micros(q["input_tokens"],budget["input_usd_micros_per_1k"])+_usd_micros(q["spec"]["caps"]["output_tokens"],budget["output_usd_micros_per_1k"])
        return {"cache_key":cache_key(q),"request":q,"response":result,"receipt":receipt,"status":status}
    for q in qs:
        source,region=lookup[(q["case_id"],q["region_id"])]
        path=_cache_path(cache_dir,cache_key(q))
        cached_retryable=False
        if path.is_file():
            cached=json.loads(path.read_text(encoding="utf-8"))
            if cached.get("cache_key")!=cache_key(q) or cached.get("request",{}).get("request_id")!=q["request_id"]: raise BaselineError("stale/corrupt cache entry")
            if cached.get("status") not in {"protocol_verified","unresolved","budget_stopped"}: raise BaselineError("unknown cached request status")
            if cached.get("status")!="budget_stopped" and not _retryable_provider_row(cached):
                validate_response(q,cached.get("response"),source)
                rows.append(cached);continue
            cached_retryable=_retryable_provider_row(cached) or _provider_unavailable_row(cached);_archive_attempt(path,cached,"resume_retryable_provider" if cached_retryable else "resume_budget_stopped")
        if state["circuit_open"]:
            row=_stopped_row(q,"provider_unavailable",cfg["model"]);_atomic(path,row);rows.append(row)
            if recovery_ledger_path:_atomic(recovery_ledger_path,state)
            continue
        if len(q["expected_target_ids"])>q["spec"]["caps"]["targets"]: row=_stopped_row(q,"target_cap_exceeded",cfg["model"]);_atomic(path,row);rows.append(row);continue
        if q["input_tokens"]>budget["max_input_tokens"] or q["spec"]["caps"]["output_tokens"]>budget["max_output_tokens"]: row=_stopped_row(q,"per_request_cap_exceeded",cfg["model"]);_atomic(path,row);rows.append(row);continue
        reserve_output=q["spec"]["caps"]["output_tokens"]
        reserve_usd=_usd_micros(q["input_tokens"],budget["input_usd_micros_per_1k"])+_usd_micros(reserve_output,budget["output_usd_micros_per_1k"])
        if used["requests"]+1>budget["max_requests"] or used["reserved_input_tokens"]+q["input_tokens"]>budget["max_total_input_tokens"] or used["reserved_output_tokens"]+reserve_output>budget["max_total_output_tokens"] or (budget["max_usd_micros"] is not None and used["reserved_usd_micros"]+reserve_usd>budget["max_usd_micros"]):
            row=_stopped_row(q,"budget_reservation_exceeded",cfg["model"]);_atomic(path,row);rows.append(row);continue
        recovery_receipts=[]
        if cached_retryable:
            if state["cycles_used"]>=recovery["max_recovery_cycles"]:
                state["circuit_open"]=True;row=_stopped_row(q,"provider_unavailable",cfg["model"]);_atomic(path,row);rows.append(row)
                if recovery_ledger_path:_atomic(recovery_ledger_path,state)
                continue
            state["cycles_used"]+=1;state.setdefault("events",[]).append({"cycle":state["cycles_used"],"request_id":q["request_id"],"trigger":"resume"});checkpoint();warm_receipt=_recovery_warmup(root=path.parent/"recovery"/f"attempt-{state['cycles_used']}",cfg=cfg,warmup=warmup,budget=budget,state=state,opener=opener,checkpoint=checkpoint);recovery_receipts.append(warm_receipt)
            if warm_receipt["status"]!="success":
                row=cached;row["recovery"]={"receipts":recovery_receipts,"cycles_used":state["cycles_used"]};_atomic(path,row);rows.append(row);continue
        row=dispatch(q,source,region,logical=not cached_retryable)
        if _retryable_provider_row(row):
            if state["cycles_used"]>=recovery["max_recovery_cycles"]: state["circuit_open"]=True
            elif recovery["max_source_retries"] and not cached_retryable:
                _archive_attempt(path,row,"retryable_provider_recovery");state["cycles_used"]+=1;state.setdefault("events",[]).append({"cycle":state["cycles_used"],"request_id":q["request_id"],"trigger":"retryable_source_failure"});checkpoint();warm_receipt=_recovery_warmup(root=path.parent/"recovery"/f"attempt-{state['cycles_used']}",cfg=cfg,warmup=warmup,budget=budget,state=state,opener=opener,checkpoint=checkpoint);recovery_receipts.append(warm_receipt)
                if warm_receipt["status"]=="success":
                    row=dispatch(q,source,region,logical=False);recovery_receipts.append({"status":"source_retry","provider_attempts":1})
                    if _retryable_provider_row(row): state["circuit_open"]=True
        if recovery_receipts: row["recovery"]={"receipts":recovery_receipts,"cycles_used":state["cycles_used"]}
        _atomic(path,row);rows.append(row)
        if recovery_ledger_path:_atomic(recovery_ledger_path,state)
    return rows

def run_mock(requests,cache_dir=None,*,resume=False):
    rows=[];total={k:0 for k in ("requests","cache_hits","input_tokens","output_tokens","total_tokens","latency_ms","rendered_context_chars","repeated_source_chars","repeated_context_chars")}
    for q in requests:
        p=_cache_path(cache_dir,cache_key(q)) if cache_dir else None
        if p and p.is_file():
            row=json.loads(p.read_text(encoding="utf-8"))
            if row.get("cache_key")!=cache_key(q) or row.get("request",{}).get("request_id")!=q["request_id"]: raise BaselineError("stale/corrupt cache entry")
            total["cache_hits"]+=1
        else:
            row={"cache_key":cache_key(q),"request":q,"response":_unresolved(q,"mock_no_semantic_extraction"),"receipt":{"provider":"mock_local","paid_provider_called":False,"finish_reason":"stop","usage":{"input_tokens":q["input_tokens"],"output_tokens":1,"total_tokens":q["input_tokens"]+1},"latency_ms":1},"status":"mock_protocol_verified"}
            if p:_atomic(p,row)
        u=row["receipt"]["usage"];total["requests"]+=1;total["input_tokens"]+=u["input_tokens"];total["output_tokens"]+=u["output_tokens"];total["total_tokens"]+=u["total_tokens"];total["latency_ms"]+=row["receipt"]["latency_ms"];total["rendered_context_chars"]+=q["rendered_chars"];total["repeated_source_chars"]+=q["repeated_source_chars"];total["repeated_context_chars"]+=q["repeated_context_chars"];rows.append(row)
    return rows,total
def rule_baseline(requests): return [{"request_id":q["request_id"],"decision":"unresolved","method":"deterministic_no_au"} for q in requests]
def comparison_report(rule,model): return {"evaluation_against":"model_silver","semantic_gold":False,"retrieval_quality_claim":False,"rule_protocol":rule,"model_protocol":model,"semantic_score":None}
def persist_json(path,v): _boundary(v);_atomic(path,v);return v
def persist_manifest(path,requests,accounting): return persist_json(path,{"artifact_type":"Plan10MockRun","schema_version":RUN_SCHEMA_VERSION,"evaluation_against":"model_silver","semantic_gold":False,"retrieval_quality_claim":False,"request_ids":[q["request_id"] for q in requests],"accounting":accounting})
def run_offline_experiment(*,plan07_report,output_root,source_store=None,spec=None):
    spec=spec or arm_spec();root=Path(output_root);a=build_locked_requests(plan07_report,arm="P2a",spec=spec,source_store=source_store);b=build_locked_requests(plan07_report,arm="P2b",spec=spec,source_store=source_store);pair=paired_experiment(a,b);persist_json(root/"inputs/p2a.json",a);persist_json(root/"inputs/p2b.json",b);persist_json(root/"paired_experiment.json",pair);runs={}
    for arm,m in (("P2a",a),("P2b",b)):
        rows,acct=run_mock(m["requests"],root/"cache"/arm);run={"artifact_type":"Plan10OfflineRun","schema_version":RUN_SCHEMA_VERSION,"evaluation_against":"model_silver","semantic_gold":False,"retrieval_quality_claim":False,"arm":arm,"input_manifest_sha256":canonical_hash(m),"request_ledger":[{"request_id":x["request"]["request_id"],"cache_key":x["cache_key"],"status":x["status"]} for x in rows],"accounting":acct,"rule_baseline":rule_baseline(m["requests"]),"limitations":["Mock unresolved responses are protocol fixtures, not semantic results."]};persist_json(root/f"runs/{arm}.json",run);runs[arm]=run
    c=comparison_report(runs["P2a"]["rule_baseline"]+runs["P2b"]["rule_baseline"],{a:runs[a]["accounting"] for a in runs});c.update({"artifact_type":"Plan10OfflineComparison","schema_version":RUN_SCHEMA_VERSION,"paired_experiment_sha256":canonical_hash(pair),"arms":{a:{"input_manifest_sha256":runs[a]["input_manifest_sha256"],"request_count":len(runs[a]["request_ledger"])} for a in runs}});persist_json(root/"comparison.json",c);return {"p2a":a,"p2b":b,"paired":pair,"runs":runs,"comparison":c}
