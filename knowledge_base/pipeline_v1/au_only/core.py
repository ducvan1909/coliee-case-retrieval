"""Independent AU-only runner; deliberately no paired/P2 imports."""
from __future__ import annotations
import hashlib,json,os,time
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError,URLError
from jsonschema import Draft202012Validator
from ..source_contract import open_source
ROOT=Path(__file__).resolve().parents[1]; RUN_SCHEMA="au-only-runtime-v1"
RESPONSE_FORMAT_VERSION="au-only-strict-json-schema-v1"
PROMPT_VERSION="au-only-compact-v1"
MANIFEST_SCHEMA=ROOT/"contracts"/"au_only_manifest.v1.json"; OUTPUT_SCHEMA=ROOT/"contracts"/"plan10_au_model_output.v1.json"
VALIDATOR=Draft202012Validator(json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))); OUTPUT_VALIDATOR=Draft202012Validator(json.loads(OUTPUT_SCHEMA.read_text(encoding="utf-8")))
class AUOnlyError(ValueError): pass
def canonical_hash(v): return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _atomic(path,v):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");os.replace(tmp,path)
def _path(root,key): return Path(root)/key[:2]/key/"response.json"
def _retryable_outage(row):
 d=row.get("receipt",{}).get("failure_diagnostic",{});kind=d.get("kind")
 if kind=="transport": return True
 if kind!="http": return False
 try: code=int(str(d.get("detail",d.get("http_status",""))).strip())
 except ValueError: return False
 return code==429 or 500<=code<=599
def _key(q,mh): return canonical_hash({"manifest":mh,"request":q,"prompt_version":PROMPT_VERSION,"response_format":RESPONSE_FORMAT_VERSION,"schema_sha256":hashlib.sha256(OUTPUT_SCHEMA.read_bytes()).hexdigest()})
def _unresolved(q,reason): return {"schema_version":"plan10-au-model-output-v1","request_id":q["request_id"],"processed_target_ids":q["expected_target_ids"],"target_results":[{"target_id":x,"decision":"unresolved","authority_units":[],"hard_negative_reason":None,"unresolved_reason":"other","reason_detail":reason} for x in q["expected_target_ids"]],"context_requests":[],"warnings":[]}
def _render(source,q):
 out=[f"<AU_ONLY_REGION case={q['case_id']} region={q['region_id']}>\n"]
 for r in q["source_refs"]:
  a,b=r["start_char"],r["end_char"]; tag="TARGET" if r["role"]=="target" else "CONTEXT";out.extend((f"<{tag} span={a}:{b}>\n",source[a:b],f"\n</{tag}>\n"))
 return "".join(out)+"</AU_ONLY_REGION>\n"
def _validate_response(q,r,source):
 errors=sorted(OUTPUT_VALIDATOR.iter_errors(r),key=lambda e:list(e.absolute_path))
 if errors: raise AUOnlyError("output schema: "+errors[0].message)
 if r.get("request_id")!=q["request_id"] or set(r.get("processed_target_ids",[]))!=set(q["expected_target_ids"]): raise AUOnlyError("target coverage")
 rows=r.get("target_results",[])
 if len(rows)!=len(q["expected_target_ids"]) or {x.get("target_id") for x in rows}!=set(q["expected_target_ids"]): raise AUOnlyError("target ownership")
 for row in rows:
  for au in row.get("authority_units",[]):
   for e in [*au.get("evidence_spans",[]),*[x.get("evidence_span",{}) for x in au.get("attributions",[])],*au.get("condition_spans",[]),*au.get("exception_spans",[]),*au.get("limit_spans",[])]:
    if not(isinstance(e.get("start_char"),int) and 0<=e["start_char"]<e.get("end_char",-1)<=len(source) and source[e["start_char"]:e["end_char"]]==e.get("quote")): raise AUOnlyError("exact evidence span/quote")
def validate_manifest(v,*,source_store=None):
 errors=sorted(VALIDATOR.iter_errors(v),key=lambda e:list(e.absolute_path))
 if errors: raise AUOnlyError("invalid AU-only manifest: "+errors[0].message)
 rows=v["requests"]
 if not 10<=len(rows)<=20: raise AUOnlyError("AU-only manifest requires 10-20 locked regions")
 if len({x["request_id"] for x in rows})!=len(rows) or len({(x["case_id"],x["region_id"]) for x in rows})!=len(rows): raise AUOnlyError("duplicate AU-only request identity")
 all_targets=[]
 for q in rows:
  if q["arm"]!="AU-only" or q["hint_payload"]!={"version":"context-hint-payload-v1","hint_ids":[]}: raise AUOnlyError("AU-only manifest cannot contain P2/ContextHint payload")
  if not isinstance(q["spec"].get("model"),str) or not q["spec"]["model"] or not isinstance(q["spec"].get("enable_thinking"),bool): raise AUOnlyError("locked spec requires model and enable_thinking")
  if not q["source_refs"]: raise AUOnlyError("empty source_refs")
  if any(not(isinstance(r["start_char"],int) and isinstance(r["end_char"],int) and r["start_char"]<r["end_char"]) for r in q["source_refs"]): raise AUOnlyError("invalid source reference span")
  owned=[t for r in q["source_refs"] if r["role"]=="target" for t in r["target_ids"]]
  if set(owned)!=set(q["expected_target_ids"]) or len(owned)!=len(set(owned)): raise AUOnlyError("AU-only target ownership must be exact")
  all_targets.extend(q["expected_target_ids"])
  if source_store is not None:
   source=open_source(source_store,q["case_id"],q["source_hash"]); prior=-1
   for r in q["source_refs"]:
    a,b=r["start_char"],r["end_char"]
    if not(0<=a<b<=len(source)) or a<prior: raise AUOnlyError("invalid or unordered source reference")
    prior=b
 if len(all_targets)!=len(set(all_targets)): raise AUOnlyError("duplicate target across AU-only requests")
 return v
def preflight(v,budget,*,source_store):
 failures=[]
 try: validate_manifest(v,source_store=source_store)
 except Exception as e: failures.append(str(e))
 rows=v.get("requests",[]);inp=sum(x.get("input_tokens",0) for x in rows);out=sum(x.get("spec",{}).get("caps",{}).get("output_tokens",0) for x in rows);limits={k:budget.get(k) for k in ("max_requests","max_provider_attempts","max_total_input_tokens","max_total_output_tokens")}
 if len(rows)>limits["max_requests"]:failures.append("request_cap")
 if limits["max_provider_attempts"] is None or len(rows)>limits["max_provider_attempts"]:failures.append("provider_attempt_cap")
 if limits["max_total_input_tokens"] is None or inp>limits["max_total_input_tokens"]:failures.append("total_input_cap")
 if limits["max_total_output_tokens"] is None or out>limits["max_total_output_tokens"]:failures.append("total_output_cap")
 return {"artifact_type":"AUOnlyPreflight","schema_version":RUN_SCHEMA,"semantic_gold":False,"semantic_quality_claim":False,"usd_limit_enforced":False,"request_count":len(rows),"reserved_input_tokens":inp,"reserved_output_tokens":out,"limits":limits,"status":"pass" if not failures else "fail","failures":failures}

def _call(cfg,q,rendered,opener):
 prompt="Return ONLY JSON. For the one expected target, emit exactly one target_result; at most one AU. Keep claim_text one proposition under 300 chars and quotes to minimal exact spans. Use no context_requests/warnings unless essential. If evidence cannot fit, emit unresolved with all required fields. No prose.\nREQUEST_ID="+q["request_id"]+"\nEXPECTED_TARGET_IDS="+json.dumps(q["expected_target_ids"])+"\nREGION:\n"+rendered
 schema=json.loads(OUTPUT_SCHEMA.read_text(encoding="utf-8"));payload={"model":cfg["model"],"messages":[{"role":"user","content":prompt}],"temperature":0,"max_tokens":q["spec"]["caps"]["output_tokens"],"response_format":{"type":"json_schema","json_schema":{"name":"au_only_response","strict":True,"schema":schema}},"chat_template_kwargs":{"enable_thinking":cfg.get("enable_thinking",False)}};req=urlrequest.Request(cfg["url"],data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+cfg["token"],"Content-Type":"application/json"},method="POST");started=time.time()
 try:
  with opener(req,timeout=cfg.get("timeout",60)) as res: body=json.loads(res.read().decode())
 except HTTPError as e: raise AUOnlyError(json.dumps({"usage":None,"usage_state":"unavailable","finish_reason":"host_unresolved","latency_ms":0,"failure_diagnostic":{"kind":"http","detail":str(e.code),"http_status":e.code,"retryable":e.code in {429,500,502,503,504}}}))
 except (URLError,TimeoutError,OSError) as e: raise AUOnlyError(json.dumps({"usage":None,"usage_state":"unavailable","finish_reason":"host_unresolved","latency_ms":0,"failure_diagnostic":{"kind":"transport","detail":type(e).__name__,"retryable":True}}))
 raw=body.get("usage");usage=None if not isinstance(raw,dict) or not all(isinstance(raw.get(k),int) for k in ("prompt_tokens","completion_tokens","total_tokens")) else {"input_tokens":raw["prompt_tokens"],"output_tokens":raw["completion_tokens"],"total_tokens":raw["total_tokens"]};receipt={"usage":usage,"usage_state":"provider" if usage else "unavailable","finish_reason":body.get("choices",[{}])[0].get("finish_reason","unknown"),"latency_ms":round((time.time()-started)*1000,3)}
 try:return json.loads(body["choices"][0]["message"]["content"]),receipt
 except Exception as e:
  raw_content=locals().get("content","");raise AUOnlyError(json.dumps({**receipt,"failure_diagnostic":{"kind":"malformed_response","detail":type(e).__name__,"content_sha256":hashlib.sha256(raw_content.encode()).hexdigest() if isinstance(raw_content,str) else None,"content_length":len(raw_content) if isinstance(raw_content,str) else 0,"content_preview":raw_content[:2000] if isinstance(raw_content,str) else None}}))

def _warmup_busy(error):
 """Recognize gateway busy conflicts without persisting arbitrary provider bodies."""
 if error.code != 409: return False
 try:
  raw=error.read(4097)
  if len(raw)>4096: return False
  detail=json.loads(raw).get("detail")
  return detail in {"Inference busy", "Inference busy; poll jobs or try probe later"}
 except (ValueError,TypeError,AttributeError,OSError): return False

def warmup(cfg,policy,root,opener=urlrequest.urlopen,sleep_fn=time.sleep,time_fn=time.monotonic):
 """Source-free bounded availability probe; never sends corpus text."""
 attempts=[];limit=policy["max_attempts"];started_all=time_fn();max_wait=policy.get("max_wait_seconds",600);delay=policy.get("initial_backoff_seconds",1)
 for ordinal in range(1,limit+1):
  remaining=max_wait-(time_fn()-started_all)
  if remaining<=0:break
  started=time.time();req=urlrequest.Request(cfg["url"],data=json.dumps({"model":cfg["model"],"messages":[{"role":"user","content":"Respond with {} only."}],"max_tokens":1,"chat_template_kwargs":{"enable_thinking":cfg.get("enable_thinking",False)}}).encode(),headers={"Authorization":"Bearer "+cfg["token"],"Content-Type":"application/json"},method="POST")
  try:
   with opener(req,timeout=min(cfg.get("timeout",60),remaining)) as r: body=json.loads(r.read().decode())
   attempts.append({"ordinal":ordinal,"status":"success","latency_ms":round((time.time()-started)*1000,3),"usage":body.get("usage")});state={"status":"success","attempts":attempts};_atomic(Path(root)/"warmup.json",state);return state
  except HTTPError as e:
   try: busy=_warmup_busy(e)
   finally: e.close()
   retry=e.code in {429,503} or busy
   attempts.append({"ordinal":ordinal,"status":"http","code":e.code,"latency_ms":round((time.time()-started)*1000,3),"retryable":retry,"diagnostic":"inference_busy" if busy else "http_error"})
  except (URLError,TimeoutError,OSError) as e:
   attempts.append({"ordinal":ordinal,"status":"transport","detail":type(e).__name__,"latency_ms":round((time.time()-started)*1000,3)});retry=True
  if not retry:break
  remaining=max_wait-(time_fn()-started_all)
  if ordinal>=limit or remaining<=0:break
  wait=min(delay,remaining);attempts[-1]["backoff_seconds"]=wait;sleep_fn(wait);delay=min(delay*2,policy.get("max_backoff_seconds",30))
 state={"status":"failed","attempts":attempts};_atomic(Path(root)/"warmup.json",state);return state

def schema_probe(cfg,root,opener=urlrequest.urlopen):
 schema={"name":"au_only_capability_probe","strict":True,"schema":{"type":"object","additionalProperties":False,"required":["kind"],"properties":{"kind":{"type":"string","enum":["holding","procedural_rule"]}}}}
 # The deliberately conflicting instruction distinguishes an endpoint that merely
 # accepts `response_format` from one that actively constrains the decoded value.
 payload={"model":cfg["model"],"messages":[{"role":"user","content":"Capability test: return exactly {\"kind\":\"exception\"}. The response schema permits only holding or procedural_rule."}],"max_tokens":16,"response_format":{"type":"json_schema","json_schema":schema},"chat_template_kwargs":{"enable_thinking":cfg.get("enable_thinking",False)}}
 identity={"url":cfg["url"],"model":cfg["model"],"enable_thinking":cfg.get("enable_thinking",False),"request_sha256":canonical_hash(payload)};req=urlrequest.Request(cfg["url"],data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+cfg["token"],"Content-Type":"application/json"},method="POST")
 try:
  with opener(req,timeout=cfg.get("timeout",60)) as r: body=json.loads(r.read().decode())
  usage=body.get("usage");content=json.loads(body["choices"][0]["message"]["content"]);ok=content.get("kind") in {"holding","procedural_rule"};out={"artifact_type":"AUOnlySchemaProbe","status":"supported" if ok else "invalid_result","config_identity":identity,"provider_usage":usage,"result":content}
 except HTTPError as e: out={"artifact_type":"AUOnlySchemaProbe","status":"http_error","config_identity":identity,"provider_usage":None,"http_status":e.code}
 except (URLError,TimeoutError,OSError) as e: out={"artifact_type":"AUOnlySchemaProbe","status":"transport_error","config_identity":identity,"provider_usage":None,"error":type(e).__name__}
 except Exception as e: out={"artifact_type":"AUOnlySchemaProbe","status":"invalid_result","config_identity":identity,"provider_usage":None,"error":type(e).__name__}
 _atomic(Path(root)/"schema_probe.json",out);return out

def full_schema_probe(cfg,root,opener=urlrequest.urlopen):
 schema=json.loads(OUTPUT_SCHEMA.read_text(encoding="utf-8"));minimal={"schema_version":"plan10-au-model-output-v1","request_id":"probe","processed_target_ids":["probe"],"target_results":[{"target_id":"probe","decision":"unresolved","authority_units":[],"hard_negative_reason":None,"unresolved_reason":"other","reason_detail":"probe"}],"context_requests":[],"warnings":[]};payload={"model":cfg["model"],"messages":[{"role":"user","content":"Return exactly this minimal valid JSON object, with no prose:\n"+json.dumps(minimal,separators=(",",":"))}],"max_tokens":512,"response_format":{"type":"json_schema","json_schema":{"name":"au_only_response","strict":True,"schema":schema}},"chat_template_kwargs":{"enable_thinking":cfg.get("enable_thinking",False)}};identity={"url":cfg["url"],"model":cfg["model"],"enable_thinking":cfg.get("enable_thinking",False),"response_format_version":RESPONSE_FORMAT_VERSION,"output_schema_sha256":hashlib.sha256(OUTPUT_SCHEMA.read_bytes()).hexdigest(),"request_sha256":canonical_hash(payload)}
 req=urlrequest.Request(cfg["url"],data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+cfg["token"],"Content-Type":"application/json"},method="POST")
 try:
  with opener(req,timeout=cfg.get("timeout",60)) as r: body=json.loads(r.read().decode())
  choice=body["choices"][0];content=choice["message"]["content"];result=json.loads(content);errors=list(OUTPUT_VALIDATOR.iter_errors(result));out={"artifact_type":"AUOnlyFullSchemaProbe","status":"supported" if not errors else "invalid_result","config_identity":identity,"provider_usage":body.get("usage"),"finish_reason":choice.get("finish_reason"),"content_sha256":hashlib.sha256(content.encode()).hexdigest(),"content_length":len(content),"content_preview":content[:500] if errors else None}
 except HTTPError as e:out={"artifact_type":"AUOnlyFullSchemaProbe","status":"http_error","config_identity":identity,"provider_usage":None,"http_status":e.code}
 except Exception as e:
  content=locals().get("content","");choice=locals().get("choice",{});out={"artifact_type":"AUOnlyFullSchemaProbe","status":"invalid_result","config_identity":identity,"provider_usage":locals().get("body",{}).get("usage"),"finish_reason":choice.get("finish_reason"),"error":type(e).__name__,"content_sha256":hashlib.sha256(content.encode()).hexdigest() if isinstance(content,str) else None,"content_length":len(content) if isinstance(content,str) else 0,"content_preview":content[:500] if isinstance(content,str) else None}
 _atomic(Path(root)/"full_schema_probe.json",out);return out
def run(v,*,source_store,cfg,budget,cache_dir,execute=False,opener=urlrequest.urlopen,warmup_policy=None,retry_provider_unavailable=False):
 if not execute: raise AUOnlyError("AU-only remote execution requires --execute")
 if any(q["spec"]["model"]!=cfg.get("model") or q["spec"]["enable_thinking"]!=cfg.get("enable_thinking",False) for q in v.get("requests",[])): raise AUOnlyError("runtime modal config does not match locked manifest spec")
 pre=preflight(v,budget,source_store=source_store)
 if pre["status"]!="pass":raise AUOnlyError("AU-only preflight failed: "+";".join(pre["failures"]))
 warm=warmup(cfg,warmup_policy or {"max_attempts":10},Path(cache_dir).parent,opener)
 if warm["status"]!="success": raise AUOnlyError("AU-only warmup failed before source dispatch")
 probe=full_schema_probe(cfg,Path(cache_dir).parent,opener)
 if probe["status"]!="supported": raise AUOnlyError("AU-only full schema probe failed before source dispatch")
 mh=canonical_hash(v);ledger_path=Path(cache_dir).parent/"runtime_ledger.json";ledger={"manifest_sha256":mh,"requests":0,"provider_attempts":0,"reserved_input_tokens":0,"reserved_output_tokens":0,"actual_input_tokens":0,"actual_output_tokens":0,"actual_total_tokens":0,"usage_unavailable":0,"circuit_open":False}
 if ledger_path.is_file():
  prior=json.loads(ledger_path.read_text(encoding="utf-8"))
  if prior.get("manifest_sha256")!=mh: raise AUOnlyError("runtime ledger manifest identity mismatch")
  ledger=prior
 if retry_provider_unavailable and ledger.get("circuit_open"):
  ledger["circuit_open"]=False;_atomic(ledger_path,ledger)
 rows=[]
 for q in v["requests"]:
  key=_key(q,mh);path=_path(cache_dir,key);source=open_source(source_store,q["case_id"],q["source_hash"])
  if path.is_file():
   row=json.loads(path.read_text(encoding="utf-8"))
   if row.get("cache_key")!=key or row.get("request")!=q or row.get("status") not in {"protocol_verified","unresolved","budget_stopped"}:raise AUOnlyError("stale/corrupt AU-only cache")
   diagnostic=row.get("receipt",{}).get("failure_diagnostic",{})
   retryable=row.get("status")=="unresolved" and row.get("receipt",{}).get("usage_state")=="unavailable" and _retryable_outage(row)
   if retry_provider_unavailable and retryable:
    archive=path.parent/"attempt_history";archive.mkdir(exist_ok=True);_atomic(archive/(canonical_hash(row)[:16]+".json"),{"superseded_reason":"retry_provider_unavailable","prior":row});path.unlink()
   elif row["status"]!="budget_stopped":
    if not isinstance(row.get("receipt"),dict) or row["receipt"].get("usage_state") not in {"provider","unavailable"}:raise AUOnlyError("corrupt AU-only cached receipt")
    _validate_response(q,row.get("response"),source)
   if not (retry_provider_unavailable and retryable): rows.append(row);continue
  if ledger.get("circuit_open"):
   row={"cache_key":key,"request":q,"status":"budget_stopped","response":None,"receipt":{"usage":None,"usage_state":"not_called","finish_reason":"host_unresolved","stop_reason":"provider_unavailable"}};_atomic(path,row);rows.append(row);continue
  ri,ro=q["input_tokens"],q["spec"]["caps"]["output_tokens"]
  blocked=ledger["requests"]+1>budget["max_requests"] or ledger["provider_attempts"]+1>budget.get("max_provider_attempts",budget["max_requests"]) or ledger["reserved_input_tokens"]+ri>budget["max_total_input_tokens"] or ledger["reserved_output_tokens"]+ro>budget["max_total_output_tokens"]
  if blocked:
   row={"cache_key":key,"request":q,"status":"budget_stopped","response":None,"receipt":{"usage":None,"usage_state":"not_called","finish_reason":"host_unresolved","stop_reason":"aggregate_budget"}};_atomic(path,row);rows.append(row);continue
  ledger["requests"]+=1;ledger["provider_attempts"]+=1;ledger["reserved_input_tokens"]+=ri;ledger["reserved_output_tokens"]+=ro;_atomic(ledger_path,ledger)
  try:
   result,receipt=_call(cfg,q,_render(source,q),opener)
   if receipt["finish_reason"] in {"length","content_filter"}:result=_unresolved(q,"output_truncated");receipt["failure_diagnostic"]={"kind":"output_truncated"};status="unresolved"
   else:
    try:_validate_response(q,result,source);status="protocol_verified"
    except AUOnlyError as e:result=_unresolved(q,"provider_or_protocol_failure");receipt["failure_diagnostic"]={"kind":"host_validation","detail":str(e)};status="unresolved"
  except AUOnlyError as e:
   try:receipt=json.loads(str(e))
   except json.JSONDecodeError:receipt={"usage":None,"usage_state":"unavailable","finish_reason":"host_unresolved","latency_ms":0,"failure_diagnostic":{"kind":"adapter"}}
   result=_unresolved(q,"provider_or_protocol_failure");status="unresolved"
   if receipt.get("failure_diagnostic",{}).get("retryable") is True: ledger["circuit_open"]=True
  if receipt.get("usage_state")!="provider":ledger["usage_unavailable"]+=1
  else:
   for name,usage_field in (("actual_input_tokens","input_tokens"),("actual_output_tokens","output_tokens"),("actual_total_tokens","total_tokens")):ledger[name]+=receipt["usage"][usage_field]
  row={"cache_key":key,"request":q,"response":result,"receipt":receipt,"status":status};_atomic(path,row);rows.append(row)
  _atomic(ledger_path,ledger)
 return {"artifact_type":"AUOnlyRun","schema_version":RUN_SCHEMA,"semantic_gold":False,"semantic_quality_claim":False,"status":"complete" if all(x["status"]=="protocol_verified" for x in rows) else "incomplete","manifest_sha256":mh,"preflight":pre,"warmup":warm,"runtime_ledger":ledger,"request_ledger":rows}
