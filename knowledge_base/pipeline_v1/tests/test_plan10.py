import copy,hashlib,io,json,re,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from knowledge_base.pipeline_v1.sentence_atoms.segmenter import canonical_hash
from knowledge_base.pipeline_v1.au_baseline.core import BaselineError,ProviderResponseError,_cache_path,_repeat,_warmup_payload,arm_spec,build_locked_requests,cache_key,call_modal,call_warmup,execute_remote,modal_config,modal_payload,paired_experiment,parse_model_json_content,plan10_budget,recovery_ledger,run_mock,run_warmup,run_warmup_probe,validate_response,warm_probe_config
from knowledge_base.pipeline_v1.au_baseline.__main__ import _account,_has_probe_proof,_paired_completion,_preflight

ROOT=Path(__file__).resolve().parents[1];PLAN07=ROOT/"reports/plan07_analysis_region_validation.latest.json"
def response(q,source="abc"):
    return {"schema_version":"plan10-au-model-output-v1","request_id":q["request_id"],"processed_target_ids":q["expected_target_ids"],"target_results":[{"target_id":x,"decision":"hard_negative","authority_units":[],"hard_negative_reason":"fact_only","unresolved_reason":None,"reason_detail":None} for x in q["expected_target_ids"]],"context_requests":[],"warnings":[]}
class FakeHTTP:
    def __init__(self,b):self.b=b
    def __enter__(self):return self
    def __exit__(self,*x):return False
    def read(self):return json.dumps(self.b).encode()
class FakeBytes:
 def __init__(self,b):self.b=b
 def __enter__(self):return self
 def __exit__(self,*x):return False
 def read(self):return self.b
class Plan10Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.spec=arm_spec();cls.a=build_locked_requests(PLAN07,arm="P2a",spec=cls.spec);cls.b=build_locked_requests(PLAN07,arm="P2b",spec=cls.spec)
 def test_locked_paired_workload(self):
  target_ids=[target for q in self.a["requests"] for target in q["expected_target_ids"]]
  self.assertEqual(len(self.a["requests"]),len(self.b["requests"]));self.assertEqual(len(target_ids),len(set(target_ids)));self.assertEqual(len(target_ids),369)
  pair=paired_experiment(self.a,self.b);self.assertEqual(pair["pair_count"],len(self.a["requests"]));self.assertTrue(pair["control"]["same_source_context"])
  by_b={(q["case_id"],q["batch_id"]):q for q in self.b["requests"]}
  for q in self.a["requests"]:
   other=by_b[(q["case_id"],q["batch_id"])];self.assertEqual(q["base_render_sha256"],other["base_render_sha256"]);self.assertEqual(q["hint_payload"]["hint_ids"],[]);self.assertEqual(other["hint_payload"]["version"],"context-hint-payload-v1")
  bad=copy.deepcopy(self.b);bad["requests"][0]["expected_target_ids"]=[]
  with self.assertRaises(BaselineError):paired_experiment(self.a,bad)
  bad=copy.deepcopy(self.b);bad["requests"][0]["base_render_sha256"]="0"*64
  with self.assertRaises(BaselineError):paired_experiment(self.a,bad)
  bad=copy.deepcopy(self.b);bad["requests"].append(copy.deepcopy(bad["requests"][0]))
  with self.assertRaises(BaselineError):paired_experiment(self.a,bad)
 def test_locked_requests_reject_duplicate_target_before_provider(self):
  source="abc";source_hash=hashlib.sha256(source.encode()).hexdigest();work_item={"target_id":"at-boundary","span":{"start_char":0,"end_char":1}}
  workload=[{"case_id":"045155","source_hash":source_hash,"batches":[{"batch_id":"first","work_items":[work_item]},{"batch_id":"second","work_items":[copy.deepcopy(work_item)]}],"regions":[{"arm":"P2a","region_id":"first-region","batch_id":"first","target_ids":["at-boundary"],"fingerprint":"first","render_items":[{"role":"target","span":{"start_char":0,"end_char":1}}],"token_estimator":{"chars_per_token":4}},{"arm":"P2a","region_id":"second-region","batch_id":"second","target_ids":["at-boundary"],"fingerprint":"second","render_items":[{"role":"target","span":{"start_char":0,"end_char":1}}],"token_estimator":{"chars_per_token":4}}]}]
  with patch("knowledge_base.pipeline_v1.au_baseline.core.load_plan07_workloads",return_value=(workload,{"inputs":{"source_store":"unused"}},{})),patch("knowledge_base.pipeline_v1.au_baseline.core.open_source",return_value=source),patch("knowledge_base.pipeline_v1.au_baseline.core.render_base_region",return_value="rendered"):
   with self.assertRaisesRegex(BaselineError,"duplicate AnalysisTarget"):build_locked_requests("unused",arm="P2a",spec=arm_spec())
 def test_response_target_and_span_validation(self):
  q={"request_id":"r","expected_target_ids":["a","b"]};good=response(q);self.assertTrue(validate_response(q,good,"abc"))
  bad=copy.deepcopy(good);bad["target_results"]=bad["target_results"][:1]
  with self.assertRaises(BaselineError):validate_response(q,bad,"abc")
 def test_official_schema_rejects_audit_reproductions(self):
  q={"request_id":"r","expected_target_ids":["a","b"],"spec":arm_spec()};good=response(q)
  variants=[]
  x=copy.deepcopy(good);del x["target_results"][0]["reason_detail"];variants.append(x)
  x=copy.deepcopy(good);x["target_results"][0]["hard_negative_reason"]="NOT_IN_CONTRACT";variants.append(x)
  x=copy.deepcopy(good);x["warnings"]=[{"not":"schema-shaped"}];variants.append(x)
  x=copy.deepcopy(good);x["target_results"][0]["extra"]=True;variants.append(x)
  x=copy.deepcopy(good);x["target_results"][0]["decision"]="positive";x["target_results"][0]["hard_negative_reason"]="fact_only";x["target_results"][0]["unresolved_reason"]="other";x["target_results"][0]["authority_units"]=[];variants.append(x)
  for value in variants:
   with self.assertRaises(BaselineError):validate_response(q,value,"abc")
  bad=response(q);bad["target_results"][0]={"target_id":"a","decision":"positive","authority_units":[{"local_au_id":"u","evidence_spans":[{"start_char":0,"end_char":2,"quote":"NO"}],"attributions":[{"evidence_span":{"start_char":0,"end_char":1,"quote":"a"}}],"condition_spans":[],"exception_spans":[],"limit_spans":[]}],"hard_negative_reason":None,"unresolved_reason":None,"reason_detail":None}
  with self.assertRaises(BaselineError):validate_response(q,bad,"abc")
 def test_atomic_mock_cache_and_invalidation(self):
  q=copy.deepcopy(self.a["requests"][0])
  with tempfile.TemporaryDirectory() as d:
   _,one=run_mock([q],d);_,two=run_mock([q],d,resume=True);self.assertEqual(one["cache_hits"],0);self.assertEqual(two["cache_hits"],1)
   other=copy.deepcopy(q);other["spec"]=arm_spec(caps={"targets":4,"output_tokens":513,"au_candidates":8});self.assertNotEqual(cache_key(q),cache_key(other))
 def test_modal_adapter_uses_bearer_and_receipt(self):
  q={"request_id":"r","expected_target_ids":["a"],"spec":arm_spec(model="m")};out=response(q);seen={}
  def opener(req,timeout):seen["auth"]=req.get_header("Authorization");return FakeHTTP({"choices":[{"message":{"content":json.dumps(out)},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}})
  parsed,receipt=call_modal({"url":"https://x/chat/completions","token":"key:secret","model":"m","timeout":1},q,"region",opener=opener);self.assertEqual(parsed,out);self.assertEqual(seen["auth"],"Bearer key:secret");self.assertEqual(receipt["usage"]["total_tokens"],5)
 def test_modal_config_combines_key_secret(self):
  c=modal_config({"PLX_ENDPOINT_URL":"https://modal.example","PLX_MODAL_KEY":"k","PLX_MODAL_SECRET":"s"});self.assertEqual(c["url"],"https://modal.example/chat/completions");self.assertEqual(c["token"],"k:s")
 def test_thinking_is_disabled_in_config_payload_and_request_identity(self):
  env={"PLX_ENDPOINT_URL":"https://modal.example","PLX_PROXY_TOKEN":"x"};self.assertFalse(modal_config(env)["enable_thinking"])
  with self.assertRaises(BaselineError):modal_config({**env,"PLX_ENABLE_THINKING":"maybe"})
  off=arm_spec(model="m",enable_thinking=False);on=arm_spec(model="m",enable_thinking=True);self.assertNotEqual(off,on)
  q={"request_id":"r","expected_target_ids":["a"],"spec":off};self.assertFalse(modal_payload(q,"text")["chat_template_kwargs"]["enable_thinking"]);self.assertFalse(_warmup_payload({"model":"m","enable_thinking":False})["chat_template_kwargs"]["enable_thinking"])
 def test_model_json_content_allows_only_bounded_thinking_or_json_fence(self):
  expected={"x":1};self.assertEqual(parse_model_json_content('{"x":1}'),expected);self.assertEqual(parse_model_json_content('<think>private source</think>\n{"x":1}'),expected);self.assertEqual(parse_model_json_content('<think>x</think>\n```json\n{"x":1}\n```'),expected)
  with self.assertRaises(ValueError):parse_model_json_content('prose before {"x":1}')
 def test_output_cap_default_lower_override_identity_and_parse_metadata(self):
  self.assertEqual(arm_spec()["caps"]["output_tokens"],1200);self.assertEqual(plan10_budget({})["max_output_tokens"],2400);self.assertEqual(plan10_budget({})["baseline_output_tokens"],1200);self.assertEqual(plan10_budget({"PLX_MAX_OUTPUT_TOKENS":"400","PLX_BASELINE_OUTPUT_TOKENS":"400","PLX_STRUCTURAL_REPAIR_OUTPUT_TOKENS":"400"})["max_output_tokens"],400)
  q={"request_id":"r","expected_target_ids":["a"],"spec":arm_spec(model="m")};self.assertNotEqual(cache_key({"arm":"P2a","source_hash":"s","region_id":"r","region_fingerprint":"f","render_sha256":"h","input_tokens":1,"spec":arm_spec(model="m")}),cache_key({"arm":"P2a","source_hash":"s","region_id":"r","region_fingerprint":"f","render_sha256":"h","input_tokens":1,"spec":arm_spec(model="m",caps={"targets":4,"output_tokens":400,"au_candidates":8})}))
  cfg={"url":"https://x","token":"secret","model":"m","enable_thinking":False,"timeout":1}
  bad={"choices":[{"message":{"content":"prose {\"not\":\"accepted\"}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":8,"total_tokens":15}}
  with self.assertRaises(ProviderResponseError) as raised:call_modal(cfg,q,"region",opener=lambda *args,**kwargs:FakeHTTP(bad))
  d=raised.exception.diagnostic;self.assertEqual(d["finish_reason"],"stop");self.assertEqual(d["provider_usage"]["total_tokens"],15);self.assertNotIn("not",json.dumps(d));self.assertNotIn("secret",json.dumps(d))
  truncated={"choices":[{"message":{"content":"{}"},"finish_reason":"length"}],"usage":{"prompt_tokens":7,"completion_tokens":1200,"total_tokens":1207}}
  with self.assertRaises(ProviderResponseError) as raised:call_modal(cfg,q,"region",opener=lambda *args,**kwargs:FakeHTTP(truncated))
  d=raised.exception.diagnostic;self.assertEqual(d["kind"],"output_truncated");self.assertEqual(d["provider_usage"]["output_tokens"],1200);self.assertNotIn("secret",json.dumps(d))
 def test_paired_preflight_requires_distinct_total_caps(self):
  manifests=({"requests":[self.a["requests"][0]]},{"requests":[self.b["requests"][0]]})
  missing=plan10_budget({"PLX_MAX_REQUESTS":"2"});report=_preflight(manifests,missing);self.assertEqual(report["status"],"fail");self.assertIn("missing_PLX_MAX_TOTAL_OUTPUT_TOKENS",report["failures"]);self.assertEqual(report["limits"]["per_request_output_tokens"],2400)
  set_totals=plan10_budget({"PLX_MAX_REQUESTS":"2","PLX_MAX_TOTAL_INPUT_TOKENS":"999999","PLX_MAX_TOTAL_OUTPUT_TOKENS":"999999"});self.assertEqual(_preflight(manifests,set_totals)["status"],"pass")
  bounded=plan10_budget({"PLX_MAX_REQUESTS":"2","PLX_MAX_PROVIDER_ATTEMPTS":"2","PLX_MAX_TOTAL_INPUT_TOKENS":"999999","PLX_MAX_TOTAL_OUTPUT_TOKENS":"999999"});self.assertIn("provider_attempt_cap",_preflight(manifests,bounded,{"max_recovery_cycles":1,"max_source_retries":1},{"max_attempts":1})["failures"])
 def test_warmup_probe_proof_binds_successful_attempt_to_locked_request(self):
  request=self.a["requests"][0];base={"status":"success","input_manifest_sha256":canonical_hash(self.a),"request_sha256":canonical_hash(request),"spec_sha256":canonical_hash(self.spec),"model":self.spec["model"],"enable_thinking":self.spec["enable_thinking"]}
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/"warmup_probe/current.json";path.parent.mkdir();path.write_text(json.dumps({**base,"probe_attempts":[{"status":"protocol_verified","request_id":"WRONG","request_sha256":"WRONG","cache_key":"WRONG"}]}),encoding="utf-8");self.assertFalse(_has_probe_proof(Path(folder),self.a,self.spec,plan07_report=PLAN07))
   attempt={"ordinal":1,"status":"protocol_verified","request_id":request["request_id"],"request_sha256":base["request_sha256"],"cache_key":cache_key(request)};path.write_text(json.dumps({**base,"probe_attempts":[attempt]}),encoding="utf-8");self.assertFalse(_has_probe_proof(Path(folder),self.a,self.spec,plan07_report=PLAN07))
   cache=Path(folder)/"warmup_probe/source_probe_cache/attempt-1"/cache_key(request)[:2]/cache_key(request)/"response.json";cache.parent.mkdir(parents=True);cache.write_text(json.dumps({"status":"protocol_verified","cache_key":cache_key(request),"request":request,"response":{}}),encoding="utf-8");self.assertFalse(_has_probe_proof(Path(folder),self.a,self.spec,plan07_report=PLAN07))
   missing=response(request);missing["target_results"]=missing["target_results"][:-1];cache.write_text(json.dumps({"status":"protocol_verified","cache_key":cache_key(request),"request":request,"response":missing}),encoding="utf-8");self.assertFalse(_has_probe_proof(Path(folder),self.a,self.spec,plan07_report=PLAN07))
   bad_span=response(request);target=bad_span["target_results"][0];target.update({"decision":"positive","hard_negative_reason":None,"authority_units":[{"local_au_id":"u","claim_text":"x","kind":"holding","other_kind":None,"evidence_spans":[{"start_char":0,"end_char":1,"quote":"BAD"}],"attributions":[{"role":"authority","speaker":"current_court","evidence_span":{"start_char":0,"end_char":1,"quote":"BAD"}}],"condition_spans":[],"exception_spans":[],"limit_spans":[],"candidate_status":"complete","uncertainty_reasons":[]} ]});cache.write_text(json.dumps({"status":"protocol_verified","cache_key":cache_key(request),"request":request,"response":bad_span}),encoding="utf-8");self.assertFalse(_has_probe_proof(Path(folder),self.a,self.spec,plan07_report=PLAN07))
   cache.write_text(json.dumps({"status":"protocol_verified","cache_key":cache_key(request),"request":request,"response":response(request)}),encoding="utf-8");self.assertTrue(_has_probe_proof(Path(folder),self.a,self.spec,plan07_report=PLAN07))
 def test_provider_failure_diagnostic_is_safe_for_http_and_malformed_body(self):
  q={"request_id":"r","expected_target_ids":["a"],"spec":arm_spec(model="m")};cfg={"url":"https://x","token":"never-persist","model":"m","timeout":1}
  def http(req,timeout):raise HTTPError("https://x",503,"service unavailable",None,io.BytesIO(b"server-body-with-never-persist"))
  with self.assertRaises(ProviderResponseError) as raised:call_modal(cfg,q,"region",opener=http)
  d=raised.exception.diagnostic;self.assertEqual(d["http_status"],503);self.assertTrue(d["retryable"]);self.assertEqual(d["response_byte_length"],30);self.assertNotIn("server-body",json.dumps(d));self.assertNotIn("never-persist",json.dumps(d))
  with self.assertRaises(ProviderResponseError) as raised:call_modal(cfg,q,"region",opener=lambda *args,**kwargs:FakeBytes(b"malformed-body-with-source"))
  d=raised.exception.diagnostic;self.assertEqual(d["kind"],"malformed_response");self.assertEqual(d["response_byte_length"],26);self.assertIsNotNone(d["response_sha256"]);self.assertNotIn("malformed-body",json.dumps(d))
  request=self.a["requests"][0]
  with tempfile.TemporaryDirectory() as folder:
   rows=execute_remote({**self.a,"requests":[request]},plan07_report=PLAN07,source_store=None,cache_dir=folder,cfg={**cfg,"model":request["spec"]["model"]},max_requests=1,budget={"max_requests":1,"max_input_tokens":999999,"max_output_tokens":999999,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0},opener=http)
  saved=json.dumps(rows[0]);self.assertEqual(rows[0]["status"],"unresolved");self.assertEqual(rows[0]["receipt"]["failure_diagnostic"]["http_status"],503);self.assertNotIn("server-body",saved);self.assertNotIn("never-persist",saved)
 def test_warmup_retries_only_retryable_and_never_sends_source(self):
  calls=[];clock=[0];delays=[];cfg={"url":"https://x","token":"never-persist","model":"m","timeout":1};warm={"max_attempts":3,"max_seconds":30,"initial_backoff_seconds":2,"max_backoff_seconds":30}
  def opener(req,timeout):
   calls.append(req.data.decode())
   if len(calls)<3:raise HTTPError("https://x",503,"busy",None,io.BytesIO(b"service unavailable"))
   return FakeHTTP({"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}})
  def sleep(seconds):delays.append(seconds);clock[0]+=seconds
  with tempfile.TemporaryDirectory() as folder:
   state=run_warmup(output_root=folder,cfg=cfg,warmup=warm,opener=opener,sleep_fn=sleep,time_fn=lambda:clock[0]);saved=(Path(folder)/"warmup/current.json").read_text(encoding="utf-8")
   again=run_warmup(output_root=folder,cfg=cfg,warmup=warm,opener=lambda *_:self.fail("successful warmup must resume"),sleep_fn=sleep,time_fn=lambda:clock[0])
  self.assertEqual(state["status"],"success");self.assertEqual(len(state["attempts"]),3);self.assertEqual(delays,[2,4]);self.assertEqual(len(calls),3);self.assertTrue(all("Reply exactly OK." in x and "REGION" not in x and "source" not in x.lower() for x in calls));self.assertNotIn("never-persist",saved);self.assertNotIn("service unavailable",saved);self.assertEqual(again["status"],"success")
 def test_warmup_accepts_reasoning_only_envelope_and_rejects_error_or_bad_shape_safely(self):
  cfg={"url":"https://x","token":"never-persist","model":"m","timeout":1}
  ready=call_warmup(cfg,opener=lambda *args,**kwargs:FakeHTTP({"choices":[{"message":{"reasoning_content":"private text"},"finish_reason":"stop"}],"usage":{}}));self.assertEqual(ready["status"],"success")
  for payload in ({"error":{"message":"private failure"}},{"choices":[]},["not","an","object"]):
   with self.assertRaises(ProviderResponseError) as raised:call_warmup(cfg,opener=lambda *args,**kwargs:FakeHTTP(payload))
   d=raised.exception.diagnostic;self.assertFalse(d["retryable"]);self.assertIn(d["kind"],{"invalid_envelope","malformed_response"});self.assertNotIn("private",json.dumps(d));self.assertNotIn("never-persist",json.dumps(d))
 def test_warmup_stops_immediately_on_nonretryable_http(self):
  cfg={"url":"https://x","token":"secret","model":"m","timeout":1};calls=[]
  def opener(req,timeout):calls.append(1);raise HTTPError("https://x",401,"no",None,io.BytesIO(b"do-not-save"))
  with tempfile.TemporaryDirectory() as folder:
   state=run_warmup(output_root=folder,cfg=cfg,warmup={"max_attempts":3,"max_seconds":30,"initial_backoff_seconds":2,"max_backoff_seconds":30},opener=opener,sleep_fn=lambda _:self.fail("must not sleep"),time_fn=lambda:0)
   resumed=run_warmup(output_root=folder,cfg=cfg,warmup={"max_attempts":3,"max_seconds":30,"initial_backoff_seconds":2,"max_backoff_seconds":30},opener=lambda *_:self.fail("terminal warmup must not call provider"),sleep_fn=lambda _:self.fail("terminal warmup must not sleep"),time_fn=lambda:0)
  self.assertEqual(len(calls),1);self.assertEqual(state["stop_reason"],"nonretryable_failure");self.assertEqual(resumed["status"],"stopped");self.assertFalse(state["attempts"][0]["failure_diagnostic"]["retryable"])
 def test_warmup_probe_success_and_resume_have_one_source_probe(self):
  manifest={**self.a,"requests":self.a["requests"][:1]};cfg={"url":"https://x","token":"never-persist","model":manifest["spec"]["model"],"enable_thinking":False,"timeout":1};calls=[]
  def opener(req,timeout):
   body=req.data.decode();calls.append(body)
   return FakeHTTP({"choices":[{"message":{"content":"OK" if "Reply exactly OK." in body else json.dumps(response(manifest["requests"][0]))},"finish_reason":"stop"}],"usage":{}})
  kw={"warmup":{"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1},"warm_probe":{"max_probe_attempts":2},"manifest":manifest,"plan07_report":PLAN07,"source_store":None,"budget":{"max_requests":1,"max_input_tokens":999999,"max_output_tokens":999999,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0},"opener":opener,"sleep_fn":lambda _:None,"time_fn":lambda:0}
  with tempfile.TemporaryDirectory() as folder:
   state=run_warmup_probe(output_root=folder,cfg=cfg,**kw);saved=(Path(folder)/"warmup_probe/current.json").read_text(encoding="utf-8");again=run_warmup_probe(output_root=folder,cfg=cfg,**{**kw,"opener":lambda *_:self.fail("successful checkpoint must not replay")})
  self.assertEqual(state["status"],"success");self.assertEqual(len(state["probe_attempts"]),1);self.assertEqual(len(calls),2);self.assertEqual(again["status"],"success");self.assertNotIn("never-persist",saved);self.assertNotIn("REGION",saved);self.assertNotIn("Reply exactly OK.",saved)
 def test_warmup_probe_retries_only_retryable_source_and_stops_otherwise(self):
  manifest={**self.a,"requests":self.a["requests"][:1]};cfg={"url":"https://x","token":"secret","model":manifest["spec"]["model"],"enable_thinking":False,"timeout":1};count=[0]
  def retry_then_success(req,timeout):
   warm="Reply exactly OK." in req.data.decode();count[0]+=1
   if count[0]==2:raise HTTPError("https://x",503,"busy",None,io.BytesIO(b"no-save"))
   content="OK" if warm else json.dumps(response(manifest["requests"][0]));return FakeHTTP({"choices":[{"message":{"content":content},"finish_reason":"stop"}],"usage":{}})
  common={"warmup":{"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1},"warm_probe":{"max_probe_attempts":2},"manifest":manifest,"plan07_report":PLAN07,"source_store":None,"budget":{"max_requests":1,"max_input_tokens":999999,"max_output_tokens":999999,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0},"sleep_fn":lambda _:None,"time_fn":lambda:0}
  with tempfile.TemporaryDirectory() as folder:state=run_warmup_probe(output_root=folder,cfg=cfg,opener=retry_then_success,**common)
  self.assertEqual(state["status"],"success");self.assertEqual(len(state["probe_attempts"]),2);self.assertEqual(len(state["warmup_cycles"]),2)
  def bad(req,timeout):
   if "Reply exactly OK." in req.data.decode():return FakeHTTP({"choices":[{"message":{"content":"OK"}}],"usage":{}})
   raise HTTPError("https://x",400,"bad",None,io.BytesIO(b"no-save"))
  with tempfile.TemporaryDirectory() as folder:stopped=run_warmup_probe(output_root=folder,cfg=cfg,opener=bad,**common)
  self.assertEqual(stopped["stop_reason"],"probe_nonretryable")
  with tempfile.TemporaryDirectory() as folder: capped=run_warmup_probe(output_root=folder,cfg=cfg,opener=lambda req,timeout: (FakeHTTP({"choices":[{"message":{"content":"OK"}}],"usage":{}}) if "Reply exactly OK." in req.data.decode() else (_ for _ in ()).throw(HTTPError("https://x",503,"busy",None,io.BytesIO(b"no-save")))),**{**common,"warm_probe":{"max_probe_attempts":1}})
  self.assertEqual(capped["stop_reason"],"probe_attempt_cap")
 def test_warm_probe_attempt_cap_is_strict_in_config_and_runtime(self):
  for value in ("0","3","not-an-integer"):
   with self.assertRaises(BaselineError):warm_probe_config({"PLX_WARM_PROBE_MAX_PROBE_ATTEMPTS":value})
  manifest={**self.a,"requests":self.a["requests"][:1]};calls=[]
  with tempfile.TemporaryDirectory() as folder:
   with self.assertRaises(BaselineError):run_warmup_probe(output_root=folder,cfg={"url":"https://x","token":"secret","model":manifest["spec"]["model"],"enable_thinking":False,"timeout":1},warmup={"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1},warm_probe={"max_probe_attempts":3},manifest=manifest,plan07_report=PLAN07,source_store=None,budget={"max_requests":1,"max_input_tokens":999999,"max_output_tokens":999999,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0},opener=lambda *args,**kwargs:calls.append(1))
  self.assertEqual(calls,[])
 def test_output_truncation_gets_one_immediate_structural_repair_only(self):
  manifest={**self.a,"requests":self.a["requests"][:1]};cfg={"url":"https://x","token":"secret","model":manifest["spec"]["model"],"enable_thinking":False,"timeout":1};calls=[]
  def valid(req_id):return {"schema_version":"plan10-au-model-output-v1","request_id":req_id,"processed_target_ids":manifest["requests"][0]["expected_target_ids"],"target_results":[{"target_id":x,"decision":"hard_negative","authority_units":[],"hard_negative_reason":"fact_only","unresolved_reason":None,"reason_detail":None} for x in manifest["requests"][0]["expected_target_ids"]],"context_requests":[],"warnings":[]}
  def opener(req,timeout):
   payload=json.loads(req.data);content=payload["messages"][0]["content"];calls.append(content)
   if "Reply exactly OK." in content:return FakeHTTP({"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}],"usage":{}})
   if len(calls)==2:return FakeHTTP({"choices":[{"message":{"content":"{}"},"finish_reason":"length"}],"usage":{"prompt_tokens":1,"completion_tokens":1200,"total_tokens":1201}})
   rid=re.search(r"REQUEST_ID=([^\n]+)",content).group(1);return FakeHTTP({"choices":[{"message":{"content":json.dumps(valid(rid))},"finish_reason":"stop"}],"usage":{}})
  common={"warmup":{"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1},"warm_probe":{"max_probe_attempts":2},"manifest":manifest,"plan07_report":PLAN07,"source_store":None,"budget":{"max_requests":1,"max_input_tokens":999999,"max_output_tokens":2400,"structural_repair_output_tokens":2400,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0},"opener":opener,"sleep_fn":lambda _:None,"time_fn":lambda:0}
  with tempfile.TemporaryDirectory() as folder:state=run_warmup_probe(output_root=folder,cfg=cfg,**common)
  self.assertEqual(state["status"],"success");self.assertEqual(len(calls),3);self.assertEqual(len(state["probe_attempts"]),2);self.assertEqual(state["probe_attempts"][1]["trigger"],"output_truncated");self.assertGreater(state["probe_attempts"][1]["repeated_source_chars"],0)
  calls2=[]
  def opener2(req,timeout):
   content=json.loads(req.data)["messages"][0]["content"];calls2.append(content)
   return FakeHTTP({"choices":[{"message":{"content":"OK" if "Reply exactly OK." in content else "{}"},"finish_reason":"stop" if "Reply exactly OK." in content else "length"}],"usage":{}})
  with tempfile.TemporaryDirectory() as folder:blocked=run_warmup_probe(output_root=folder,cfg=cfg,**{**common,"budget":{**common["budget"],"max_output_tokens":1200},"opener":opener2})
  self.assertEqual(blocked["stop_reason"],"structural_repair_blocked")
  calls3=[]
  def opener3(req,timeout):
   content=json.loads(req.data)["messages"][0]["content"];calls3.append(content);warm="Reply exactly OK." in content
   return FakeHTTP({"choices":[{"message":{"content":"OK" if warm else "{}"},"finish_reason":"stop" if warm else "length"}],"usage":{}})
  with tempfile.TemporaryDirectory() as folder:failed=run_warmup_probe(output_root=folder,cfg=cfg,**{**common,"opener":opener3})
  self.assertEqual(failed["stop_reason"],"structural_repair_failed");self.assertEqual(len(calls3),3)
 def test_remote_invalid_schema_and_unexpected_error_are_unresolved_and_continue(self):
  manifest={**self.a,"requests":self.a["requests"][:2]};calls=[]
  def opener(req,timeout):
   calls.append(1)
   if len(calls)==1: raise RuntimeError("boom token_should_not_appear")
   q=manifest["requests"][1];return FakeHTTP({"choices":[{"message":{"content":json.dumps(response(q))},"finish_reason":"stop"}],"usage":{}})
  budget={"max_requests":2,"max_input_tokens":999999,"max_output_tokens":999999,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0}
  with tempfile.TemporaryDirectory() as d:
   rows=execute_remote(manifest,plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":manifest["spec"]["model"],"timeout":1},max_requests=2,budget=budget,opener=opener)
  self.assertEqual([x["status"] for x in rows],["unresolved","protocol_verified"]);self.assertNotIn("token_should_not_appear",json.dumps(rows[0]))
 def test_target_cap_and_merged_repeat_accounting(self):
  seen=[];self.assertEqual(_repeat([(0,4)],seen),0);self.assertEqual(_repeat([(2,6)],seen),2);self.assertEqual(_repeat([(3,5)],seen),2)
  q=copy.deepcopy(next(q for q in self.a["requests"] if len(q["expected_target_ids"])>1));q["spec"]["caps"]["targets"]=1
  with tempfile.TemporaryDirectory() as d:
   rows=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":q["spec"]["model"],"timeout":1},max_requests=1,budget={"max_requests":1,"max_input_tokens":999999,"max_output_tokens":999999,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0},opener=lambda *_:self.fail("provider must not be called"))
  self.assertEqual(rows[0]["status"],"budget_stopped")
 def test_runtime_uses_aggregate_caps_and_cache_hits_are_free(self):
  requests=[copy.deepcopy(q) for q in self.a["requests"][:3]];calls=[]
  def opener(req,timeout):
   q=requests[len(calls)];calls.append(q["request_id"]);return FakeHTTP({"choices":[{"message":{"content":json.dumps(response(q))},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}})
  budget={"max_requests":3,"max_input_tokens":12000,"max_output_tokens":2400,"max_total_input_tokens":999999,"max_total_output_tokens":3600,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0}
  with tempfile.TemporaryDirectory() as d:
   rows=execute_remote({**self.a,"requests":requests},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":requests[0]["spec"]["model"],"timeout":1},max_requests=3,budget=budget,opener=opener)
   self.assertEqual([row["status"] for row in rows],["protocol_verified"]*3);self.assertEqual(len(calls),3)
   calls.clear();rows=execute_remote({**self.a,"requests":requests},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":requests[0]["spec"]["model"],"timeout":1},max_requests=3,budget={**budget,"max_total_output_tokens":2400},opener=lambda *_:self.fail("cache hit must not call provider"))
   self.assertEqual([row["status"] for row in rows],["protocol_verified"]*3)
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   rows=execute_remote({**self.a,"requests":requests},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":requests[0]["spec"]["model"],"timeout":1},max_requests=3,budget={**budget,"max_total_output_tokens":2400},opener=opener)
  self.assertEqual([row["status"] for row in rows],["protocol_verified","protocol_verified","budget_stopped"]);self.assertEqual(len(calls),2)
 def test_resume_archives_budget_stopped_attempt_before_retry(self):
  q=copy.deepcopy(self.a["requests"][0]);manifest={**self.a,"requests":[q]};cfg={"url":"https://x","token":"secret","model":q["spec"]["model"],"timeout":1};base={"max_requests":1,"max_input_tokens":12000,"max_output_tokens":2400,"max_total_input_tokens":999999,"max_total_output_tokens":0,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0}
  with tempfile.TemporaryDirectory() as d:
   stopped=execute_remote(manifest,plan07_report=PLAN07,source_store=None,cache_dir=d,cfg=cfg,max_requests=1,budget=base,opener=lambda *_:self.fail("budget stop must not dispatch"))[0]
   resumed=execute_remote(manifest,plan07_report=PLAN07,source_store=None,cache_dir=d,cfg=cfg,max_requests=1,budget={**base,"max_total_output_tokens":1200},opener=lambda *args,**kwargs:FakeHTTP({"choices":[{"message":{"content":json.dumps(response(q))},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}))[0]
   history=list((_cache_path(Path(d),cache_key(q)).parent/"attempt_history").glob("*.json"));self.assertEqual((stopped["status"],resumed["status"],len(history)),("budget_stopped","protocol_verified",1))
   archived=json.loads(history[0].read_text(encoding="utf-8"));self.assertEqual(archived["prior_row_sha256"],canonical_hash(stopped));self.assertEqual(archived["request_sha256"],canonical_hash(q));self.assertEqual(archived["prior_row"]["status"],"budget_stopped")
 def test_retryable_503_warms_then_retries_once(self):
  q=copy.deepcopy(self.a["requests"][0]);calls=[];budget={"max_requests":1,"max_provider_attempts":3,"max_input_tokens":12000,"max_output_tokens":2400,"max_total_input_tokens":999999,"max_total_output_tokens":2400,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0}
  def opener(req,timeout):
   body=req.data.decode();calls.append("warmup" if "Reply exactly OK." in body else "source")
   if calls==["source"]:raise HTTPError("https://x",503,"busy",None,None)
   if calls[-1]=="warmup":return FakeHTTP({"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}],"usage":{}})
   return FakeHTTP({"choices":[{"message":{"content":json.dumps(response(q))},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}})
  with tempfile.TemporaryDirectory() as d:row=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":q["spec"]["model"],"timeout":1},max_requests=1,budget=budget,recovery={"max_recovery_cycles":1,"max_source_retries":1},warmup={"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1},opener=opener)[0]
  self.assertEqual((row["status"],calls),("protocol_verified",["source","warmup","source"]));self.assertEqual(row["recovery"]["receipts"][0]["status"],"success")
 def test_repeated_retryable_outage_opens_circuit_without_fanout(self):
  requests=[copy.deepcopy(q) for q in self.a["requests"][:3]];calls=[];budget={"max_requests":3,"max_provider_attempts":4,"max_input_tokens":12000,"max_output_tokens":2400,"max_total_input_tokens":999999,"max_total_output_tokens":3600,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0}
  def opener(req,timeout):
   body=req.data.decode();calls.append("warmup" if "Reply exactly OK." in body else "source")
   if calls[-1]=="warmup":return FakeHTTP({"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}],"usage":{}})
   raise HTTPError("https://x",503,"busy",None,None)
  with tempfile.TemporaryDirectory() as d:rows=execute_remote({**self.a,"requests":requests},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":requests[0]["spec"]["model"],"timeout":1},max_requests=3,budget=budget,recovery={"max_recovery_cycles":1,"max_source_retries":1},warmup={"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1},opener=opener)
  self.assertEqual([row["status"] for row in rows],["unresolved","budget_stopped","budget_stopped"]);self.assertEqual([row["receipt"].get("stop_reason") for row in rows[1:]],["provider_unavailable","provider_unavailable"]);self.assertEqual(calls,["source","warmup","source"])
 def test_global_recovery_cycle_is_consumed_after_intermittent_503(self):
  requests=[copy.deepcopy(q) for q in self.a["requests"][:3]];calls=[];used={"requests":0,"reserved_input_tokens":0,"reserved_output_tokens":0,"reserved_usd_micros":0};state={"cycles_used":0,"provider_attempts":0,"source_attempts":0,"warmup_attempts":0,"circuit_open":False,"events":[]};budget={"max_requests":3,"max_provider_attempts":4,"max_input_tokens":12000,"max_output_tokens":2400,"max_total_input_tokens":999999,"max_total_output_tokens":4800,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0}
  def opener(req,timeout):
   body=req.data.decode();calls.append("warmup" if "Reply exactly OK." in body else "source")
   if calls[-1]=="warmup":return FakeHTTP({"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}],"usage":{}})
   if calls==["source"] or calls==["source","warmup","source","source"]:raise HTTPError("https://x",503,"busy",None,None)
   q=requests[0];return FakeHTTP({"choices":[{"message":{"content":json.dumps(response(q))},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}})
  with tempfile.TemporaryDirectory() as d:rows=execute_remote({**self.a,"requests":requests},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":requests[0]["spec"]["model"],"timeout":1},max_requests=3,budget=budget,usage_state=used,recovery={"max_recovery_cycles":1,"max_source_retries":1},recovery_state=state,warmup={"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1},opener=opener)
  self.assertEqual(([row["status"] for row in rows],calls,state["cycles_used"],state["provider_attempts"],used["reserved_output_tokens"]),(["protocol_verified","unresolved","budget_stopped"],["source","warmup","source","source"],1,4,3600))
 def test_resume_retries_cached_503_but_never_length(self):
  q=copy.deepcopy(self.a["requests"][0]);base={"max_requests":1,"max_provider_attempts":3,"max_input_tokens":12000,"max_output_tokens":2400,"max_total_input_tokens":999999,"max_total_output_tokens":2400,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0};cfg={"url":"https://x","token":"secret","model":q["spec"]["model"],"timeout":1}
  with tempfile.TemporaryDirectory() as d:
   recovery={"max_recovery_cycles":1,"max_source_retries":1};ledger=Path(d)/"recovery.json"
   first=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg=cfg,max_requests=1,budget=base,opener=lambda *args,**kwargs: (_ for _ in ()).throw(HTTPError("https://x",503,"busy",None,None)))[0]
   calls=[]
   def recovered(req,timeout):
    body=req.data.decode();calls.append("warmup" if "Reply exactly OK." in body else "source");return FakeHTTP({"choices":[{"message":{"content":"OK" if calls[-1]=="warmup" else json.dumps(response(q))},"finish_reason":"stop"}],"usage":{}})
   resumed=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg=cfg,max_requests=1,budget=base,recovery=recovery,recovery_state=recovery_ledger(ledger,identity="resume-test",budget=base,recovery=recovery),recovery_ledger_path=ledger,warmup={"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1},opener=recovered)[0]
   self.assertEqual((first["status"],resumed["status"],calls,json.loads(ledger.read_text())["cycles_used"]),("unresolved","protocol_verified",["warmup","source"],1))
 def test_failed_resume_warmup_durably_consumes_global_cycle(self):
  q=copy.deepcopy(self.a["requests"][0]);base={"max_requests":1,"max_provider_attempts":3,"max_input_tokens":12000,"max_output_tokens":2400,"max_total_input_tokens":999999,"max_total_output_tokens":2400,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0};cfg={"url":"https://x","token":"secret","model":q["spec"]["model"],"timeout":1};recovery={"max_recovery_cycles":1,"max_source_retries":1};warmup={"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1}
  with tempfile.TemporaryDirectory() as d:
   first=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg=cfg,max_requests=1,budget=base,opener=lambda *args,**kwargs: (_ for _ in ()).throw(HTTPError("https://x",503,"busy",None,None)))[0]
   ledger=Path(d)/"recovery.json";calls=[]
   def warmup_fails(req,timeout):calls.append("warmup" if "Reply exactly OK." in req.data.decode() else "source");raise HTTPError("https://x",503,"busy",None,None)
   state=recovery_ledger(ledger,identity="durable-resume",budget=base,recovery=recovery)
   failed=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg=cfg,max_requests=1,budget=base,recovery=recovery,recovery_state=state,recovery_ledger_path=ledger,warmup=warmup,opener=warmup_fails)[0]
   durable=json.loads(ledger.read_text(encoding="utf-8"));self.assertEqual((first["status"],failed["status"],calls,durable["cycles_used"],durable["provider_attempts"],durable["warmup_attempts"]),("unresolved","unresolved",["warmup"],1,1,1))
   calls.clear();restarted=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg=cfg,max_requests=1,budget=base,recovery=recovery,recovery_state=recovery_ledger(ledger,identity="durable-resume",budget=base,recovery=recovery),recovery_ledger_path=ledger,warmup=warmup,opener=lambda *args,**kwargs:self.fail("restart must not reuse recovery cycle"))[0]
   self.assertEqual((restarted["status"],restarted["receipt"]["stop_reason"],calls),("budget_stopped","provider_unavailable",[]))
 def test_length_is_terminal_and_never_retried_by_paired_recovery(self):
  q=copy.deepcopy(self.a["requests"][0]);calls=[];budget={"max_requests":1,"max_provider_attempts":3,"max_input_tokens":12000,"max_output_tokens":2400,"max_total_input_tokens":999999,"max_total_output_tokens":1200,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0}
  def opener(req,timeout):calls.append(1);return FakeHTTP({"choices":[{"message":{"content":"{}"},"finish_reason":"length"}],"usage":{"prompt_tokens":1,"completion_tokens":1200,"total_tokens":1201}})
  with tempfile.TemporaryDirectory() as d:row=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":q["spec"]["model"],"timeout":1},max_requests=1,budget=budget,recovery={"max_recovery_cycles":1,"max_source_retries":1},warmup={"max_attempts":1,"max_seconds":30,"initial_backoff_seconds":1,"max_backoff_seconds":1},opener=opener)[0]
  self.assertEqual((row["status"],row["receipt"]["failure_diagnostic"]["kind"],len(calls)),("unresolved","output_truncated",1));self.assertNotIn("recovery",row)
 def test_paired_completion_requires_every_locked_row_protocol_verified(self):
  def arms(status,finish_reason="stop",failure_kind=None):
   rows=[{"request_id":str(i),"status":status,"finish_reason":finish_reason,"failure_kind":failure_kind} for i in range(2)];return {"P2a":{"request_ledger":rows[:1]},"P2b":{"request_ledger":rows[1:]}}
  self.assertEqual(_paired_completion(arms("protocol_verified"),expected_requests=2),("complete","all_locked_requests_protocol_verified","complete"))
  self.assertEqual(_paired_completion(arms("budget_stopped"),expected_requests=2),("incomplete","budget_stopped","incomplete_budget_stopped"))
  self.assertEqual(_paired_completion(arms("unresolved","length"),expected_requests=2),("incomplete","output_truncated","incomplete_output_truncated"))
  self.assertEqual(_paired_completion(arms("unresolved",failure_kind="http"),expected_requests=2),("incomplete","provider_failure","incomplete_provider_failure"))
  self.assertEqual(_paired_completion(arms("unresolved"),expected_requests=2),("incomplete","unresolved","incomplete_unresolved"))
 def test_remote_schema_invalid_model_output_becomes_unresolved(self):
  q=self.a["requests"][0];bad=response(q);del bad["target_results"][0]["reason_detail"]
  def opener(req,timeout):return FakeHTTP({"choices":[{"message":{"content":json.dumps(bad)},"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":8,"total_tokens":15}})
  with tempfile.TemporaryDirectory() as d:
   rows=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":q["spec"]["model"],"timeout":1},max_requests=1,budget={"max_requests":1,"max_input_tokens":999999,"max_output_tokens":999999,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0},opener=opener)
  self.assertEqual(rows[0]["status"],"unresolved");self.assertEqual(rows[0]["receipt"]["usage"],{"input_tokens":7,"output_tokens":8,"total_tokens":15});self.assertEqual(rows[0]["receipt"]["finish_reason"],"stop");self.assertEqual(rows[0]["receipt"]["failure_diagnostic"]["kind"],"host_validation")
 def test_prompt_body_token_cap_blocks_provider_before_dispatch(self):
  q=self.a["requests"][0];self.assertGreater(q["estimated_prompt_input_tokens"],q["rendered_input_tokens"])
  budget={"max_requests":1,"max_input_tokens":q["rendered_input_tokens"],"max_output_tokens":999999,"max_usd_micros":None,"input_usd_micros_per_1k":0,"output_usd_micros_per_1k":0}
  with tempfile.TemporaryDirectory() as d:
   rows=execute_remote({**self.a,"requests":[q]},plan07_report=PLAN07,source_store=None,cache_dir=d,cfg={"url":"https://x","token":"secret","model":q["spec"]["model"],"timeout":1},max_requests=1,budget=budget,opener=lambda *_:self.fail("input cap must prevent dispatch"))
  self.assertEqual(rows[0]["status"],"budget_stopped");self.assertEqual(rows[0]["receipt"]["stop_reason"],"per_request_cap_exceeded")
