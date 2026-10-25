import copy,hashlib,json,os,tempfile,unittest
from pathlib import Path
from urllib.error import HTTPError,URLError
from unittest.mock import patch
from knowledge_base.pipeline_v1.au_only.core import AUOnlyError,_call,_key,_validate_response,full_schema_probe,preflight,run,schema_probe,validate_manifest
from knowledge_base.pipeline_v1.au_only.__main__ import _budget

class FakeHTTP:
 def __init__(self,body):self.body=body
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def read(self):return json.dumps(self.body).encode()

def is_warmup(req): return "Respond with {} only." in req.data.decode() or "Return exactly this minimal valid JSON object" in req.data.decode()
def warmup_ok(): return FakeHTTP({"choices":[{"finish_reason":"stop","message":{"content":json.dumps({"schema_version":"plan10-au-model-output-v1","request_id":"probe","processed_target_ids":["probe"],"target_results":[{"target_id":"probe","decision":"unresolved","authority_units":[],"hard_negative_reason":None,"unresolved_reason":"other","reason_detail":"probe"}],"context_requests":[],"warnings":[]})}}],"usage":{}})
def valid_output(q): return {"schema_version":"plan10-au-model-output-v1","request_id":q["request_id"],"processed_target_ids":q["expected_target_ids"],"target_results":[{"target_id":q["expected_target_ids"][0],"decision":"hard_negative","authority_units":[],"hard_negative_reason":"other","unresolved_reason":None,"reason_detail":None}],"context_requests":[],"warnings":[]}

def request(n):
 source="abc";return {"case_id":f"{n:06d}","source_hash":hashlib.sha256(source.encode()).hexdigest(),"region_id":f"auo-{n}","arm":"AU-only","expected_target_ids":[f"at-{n}"],"source_refs":[{"role":"target","start_char":0,"end_char":1,"target_ids":[f"at-{n}"]}],"spec":{"model":"locked-qwen","enable_thinking":False,"caps":{"output_tokens":10}},"request_id":f"r-{n}","input_tokens":1,"hint_payload":{"version":"context-hint-payload-v1","hint_ids":[]}}
class AUOnlyTests(unittest.TestCase):
 def manifest(self): return {"artifact_type":"AUOnlyLockedManifest","schema_version":"au-only-manifest-v1","requests":[request(i) for i in range(10,20)]}
 def budget(self): return {"max_requests":20,"max_provider_attempts":20,"max_total_input_tokens":100,"max_total_output_tokens":20000}
 def test_cli_budget_mapping_uses_loaded_env_mapping(self):
  self.assertEqual(_budget({"AU_ONLY_MAX_REQUESTS":"11","AU_ONLY_MAX_TOTAL_INPUT_TOKENS":"101","AU_ONLY_MAX_TOTAL_OUTPUT_TOKENS":"202"}),{"max_requests":11,"max_provider_attempts":20,"max_total_input_tokens":101,"max_total_output_tokens":202})
 def test_schema_probe_supported_http400_and_invalid_enum(self):
  cfg={"url":"https://fake","token":"secret","model":"m","enable_thinking":False}
  with tempfile.TemporaryDirectory() as temp:
   good=schema_probe(cfg,temp,opener=lambda *a,**k:FakeHTTP({"choices":[{"message":{"content":'{"kind":"holding"}'}}],"usage":{"total_tokens":1}}));self.assertEqual(good["status"],"supported");self.assertNotIn("secret",json.dumps(good))
   bad=schema_probe(cfg,temp,opener=lambda *a,**k: (_ for _ in ()).throw(HTTPError("x",400,"bad",None,None)));self.assertEqual(bad["status"],"http_error")
   invalid=schema_probe(cfg,temp,opener=lambda *a,**k:FakeHTTP({"choices":[{"message":{"content":'{"kind":"other"}'}}]}));self.assertEqual(invalid["status"],"invalid_result")
 def test_full_schema_probe_prompt_cap_and_non_json_diagnostic(self):
  cfg={"url":"https://fake","token":"secret","model":"m","enable_thinking":False}
  with tempfile.TemporaryDirectory() as temp:
   seen=[]
   def opener(req,**kwargs):seen.append(json.loads(req.data));return FakeHTTP({"choices":[{"finish_reason":"length","message":{"content":"not-json"}}],"usage":{"total_tokens":1}})
   value=full_schema_probe(cfg,temp,opener=opener);self.assertEqual(value["status"],"invalid_result");self.assertEqual(value["finish_reason"],"length");self.assertEqual(value["content_preview"],"not-json");self.assertEqual(seen[0]["max_tokens"],512);self.assertIn('"request_id":"probe"',seen[0]["messages"][0]["content"])
 def test_call_uses_strict_full_schema_and_cache_identity(self):
  seen=[];q=request(10);cfg={"url":"https://fake","token":"secret","model":"locked-qwen","enable_thinking":False}
  def opener(req,**kwargs):seen.append(json.loads(req.data));return FakeHTTP({"choices":[{"finish_reason":"stop","message":{"content":json.dumps(valid_output(q))}}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}})
  _call(cfg,q,"text",opener);rf=seen[0]["response_format"];self.assertEqual(rf["type"],"json_schema");self.assertTrue(rf["json_schema"]["strict"]);self.assertFalse(rf["json_schema"]["schema"]["additionalProperties"]);self.assertIn("holding",json.dumps(rf));self.assertIn("at most one AU",seen[0]["messages"][0]["content"]);self.assertNotIn("SCHEMA=",seen[0]["messages"][0]["content"]);self.assertNotIn("plan10-au-model-output",seen[0]["messages"][0]["content"])
  self.assertNotEqual(_key(q,"a"),_key(q,"b"))
 def test_manifest_is_small_single_arm_and_hint_free(self):
  value=self.manifest();self.assertIs(validate_manifest(value),value)
  with patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):self.assertEqual(preflight(value,self.budget(),source_store="unused")["status"],"pass")
  for mutate in ("p2","hint","duplicate","too_small","same_target","empty_refs","zero_span"):
   bad=copy.deepcopy(value)
   if mutate=="p2":bad["requests"][0]["arm"]="P2a"
   elif mutate=="hint":bad["requests"][0]["hint_payload"]["hint_ids"]=["ch-x"]
   elif mutate=="duplicate":bad["requests"].append(copy.deepcopy(bad["requests"][0]))
   elif mutate=="same_target":bad["requests"][1]["expected_target_ids"]=bad["requests"][0]["expected_target_ids"];bad["requests"][1]["source_refs"][0]["target_ids"]=bad["requests"][0]["expected_target_ids"]
   elif mutate=="empty_refs":bad["requests"][0]["source_refs"]=[]
   elif mutate=="zero_span":bad["requests"][0]["source_refs"][0]["end_char"]=0
   else:bad["requests"]=bad["requests"][:9]
   with self.subTest(mutate=mutate),self.assertRaises(AUOnlyError):validate_manifest(bad)
 def test_preflight_is_offline_and_enforces_totals(self):
  bad=self.budget();bad["max_total_input_tokens"]=9;value=preflight(self.manifest(),bad,source_store="unused");self.assertEqual(value["status"],"fail");self.assertIn("total_input_cap",value["failures"])
  bad=self.budget();bad["max_provider_attempts"]=9;value=preflight(self.manifest(),bad,source_store="unused");self.assertEqual(value["status"],"fail");self.assertIn("provider_attempt_cap",value["failures"])
  unrestricted=self.budget();unrestricted["max_usd_micros"]=1;value=preflight(self.manifest(),unrestricted,source_store="unused");self.assertNotIn("usd_cap",value["failures"]);self.assertFalse(value["usd_limit_enforced"])
 def test_source_backed_preflight_rejects_bad_hash_or_offsets(self):
  value=self.manifest()
  with patch("knowledge_base.pipeline_v1.au_only.core.open_source",side_effect=ValueError("source hash mismatch")):
   result=preflight(value,self.budget(),source_store="unused");self.assertEqual(result["status"],"fail");self.assertIn("source hash mismatch",result["failures"][0])
  bad=copy.deepcopy(value);bad["requests"][0]["source_refs"][0]["end_char"]=4
  with patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   result=preflight(bad,self.budget(),source_store="unused");self.assertEqual(result["status"],"fail");self.assertIn("source reference",result["failures"][0])
 def test_length_usage_cache_key_and_resume_cache_hit(self):
  calls=[]
  def opener(req,*args,**kwargs):
   calls.append("warmup" if is_warmup(req) else "source")
   return warmup_ok() if is_warmup(req) else FakeHTTP({"choices":[{"finish_reason":"length","message":{"content":"{}"}}],"usage":{"prompt_tokens":7,"completion_tokens":8,"total_tokens":15}})
  with tempfile.TemporaryDirectory() as temp,patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   cfg={"url":"https://fake","token":"token","model":"locked-qwen","enable_thinking":False};cache_dir=Path(temp)/"cache";first=run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener)
   self.assertEqual(calls.count("warmup"),2);self.assertEqual(calls.count("source"),10);row=first["request_ledger"][0];self.assertNotEqual(row["cache_key"],"total_tokens");self.assertEqual(row["receipt"]["usage"],{"input_tokens":7,"output_tokens":8,"total_tokens":15});self.assertEqual(row["receipt"]["failure_diagnostic"]["kind"],"output_truncated")
   second=run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener,retry_provider_unavailable=True);self.assertEqual(calls.count("warmup"),4);self.assertEqual(calls.count("source"),10);self.assertEqual(second["request_ledger"][0]["cache_key"],row["cache_key"])
 def test_http200_invalid_keeps_usage_and_caches(self):
  calls=[]
  def opener(req,*args,**kwargs):
   calls.append("warmup" if is_warmup(req) else "source")
   return warmup_ok() if is_warmup(req) else FakeHTTP({"choices":[{"finish_reason":"stop","message":{"content":"{}"}}],"usage":{"prompt_tokens":7,"completion_tokens":8,"total_tokens":15}})
  with tempfile.TemporaryDirectory() as temp,patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   cfg={"url":"https://fake","token":"token","model":"locked-qwen","enable_thinking":False};cache_dir=Path(temp)/"cache";first=run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener);row=first["request_ledger"][0]
   self.assertEqual(row["receipt"]["usage"],{"input_tokens":7,"output_tokens":8,"total_tokens":15});self.assertEqual(row["receipt"]["failure_diagnostic"]["kind"],"host_validation");self.assertNotEqual(row["cache_key"],"total_tokens")
   run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener,retry_provider_unavailable=True);self.assertEqual(calls.count("source"),10);self.assertEqual(calls.count("warmup"),4)
 def test_transport_unavailable_cache_and_config_mismatch(self):
  calls=[]
  def opener(req,*args,**kwargs):
   calls.append("warmup" if is_warmup(req) else "source")
   if is_warmup(req):return warmup_ok()
   raise URLError("offline")
  with tempfile.TemporaryDirectory() as temp,patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   cfg={"url":"https://fake","token":"token","model":"locked-qwen","enable_thinking":False};cache_dir=Path(temp)/"cache";first=run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener);self.assertEqual(first["request_ledger"][0]["receipt"]["usage_state"],"unavailable");self.assertEqual(first["runtime_ledger"]["usage_unavailable"],1);self.assertEqual(calls.count("source"),1)
   run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener);self.assertEqual(calls.count("source"),1)
   bad={**cfg,"model":"different"}
   with self.assertRaises(AUOnlyError):run(self.manifest(),source_store="unused",cfg=bad,budget=self.budget(),cache_dir=Path(temp)/"other",execute=True,opener=opener)
 def test_httperror_unavailable_cache_resume(self):
  calls=[]
  def opener(req,*args,**kwargs):
   calls.append("warmup" if is_warmup(req) else "source")
   if is_warmup(req):return warmup_ok()
   raise HTTPError("https://fake",503,"down",None,None)
  with tempfile.TemporaryDirectory() as temp,patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   cfg={"url":"https://fake","token":"token","model":"locked-qwen","enable_thinking":False};cache_dir=Path(temp)/"cache";first=run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener);self.assertEqual(first["request_ledger"][0]["receipt"]["failure_diagnostic"]["kind"],"http")
   run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener);self.assertEqual(calls.count("source"),1)
 def test_warmup_gate_never_sends_source(self):
  payloads=[]
  def opener(req,*args,**kwargs):payloads.append(req.data.decode());raise HTTPError("https://fake",400,"bad",None,None)
  with tempfile.TemporaryDirectory() as temp,patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   cfg={"url":"https://fake","token":"token","model":"locked-qwen","enable_thinking":False}
   with self.assertRaises(AUOnlyError):run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=Path(temp)/"cache",execute=True,opener=opener)
  self.assertEqual(len(payloads),1);self.assertIn("Respond with {} only.",payloads[0]);self.assertNotIn("abc",payloads[0]);self.assertNotIn("at-10",payloads[0])
 def test_503_opens_circuit_and_explicit_retry_archives_only_unavailable_cache(self):
  calls=[];q=self.manifest()["requests"][0]
  def down(req,*args,**kwargs):
   calls.append("warmup" if is_warmup(req) else "source")
   if is_warmup(req):return warmup_ok()
   raise HTTPError("https://fake",503,"down",None,None)
  def recovered(req,*args,**kwargs):
   calls.append("warmup" if is_warmup(req) else "source")
   return warmup_ok() if is_warmup(req) else FakeHTTP({"choices":[{"finish_reason":"stop","message":{"content":json.dumps(valid_output(q))}}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}})
  with tempfile.TemporaryDirectory() as temp,patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   cfg={"url":"https://fake","token":"token","model":"locked-qwen","enable_thinking":False};cache_dir=Path(temp)/"cache";first=run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=down)
   self.assertEqual(calls,["warmup","warmup","source"]);self.assertTrue(first["runtime_ledger"]["circuit_open"]);self.assertEqual([x["status"] for x in first["request_ledger"][1:]],["budget_stopped"]*9)
   second=run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=recovered,retry_provider_unavailable=True)
   self.assertEqual(calls,["warmup","warmup","source","warmup","warmup","source"]);self.assertEqual(second["request_ledger"][0]["status"],"protocol_verified");self.assertTrue(list(cache_dir.glob("**/attempt_history/*.json")))
 def test_nonretryable_http_cache_is_not_replayed(self):
  calls=[]
  def opener(req,*args,**kwargs):
   calls.append("warmup" if is_warmup(req) else "source")
   if is_warmup(req):return warmup_ok()
   raise HTTPError("https://fake",400,"bad",None,None)
  with tempfile.TemporaryDirectory() as temp,patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   cfg={"url":"https://fake","token":"token","model":"locked-qwen","enable_thinking":False};cache_dir=Path(temp)/"cache";run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener)
   run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener,retry_provider_unavailable=True)
   self.assertEqual(calls.count("source"),10);self.assertFalse(list(cache_dir.glob("**/attempt_history/*.json")))
 def test_bad_au_and_attribution_quotes_are_rejected(self):
  q=request(10);au={"local_au_id":"au1","claim_text":"a","kind":"holding","other_kind":None,"evidence_spans":[{"start_char":0,"end_char":1,"quote":"WRONG"}],"attributions":[{"role":"authority","speaker":"current_court","evidence_span":{"start_char":0,"end_char":1,"quote":"a"}}],"condition_spans":[],"exception_spans":[],"limit_spans":[],"candidate_status":"complete","uncertainty_reasons":[]};response={"schema_version":"plan10-au-model-output-v1","request_id":q["request_id"],"processed_target_ids":q["expected_target_ids"],"target_results":[{"target_id":q["expected_target_ids"][0],"decision":"positive","authority_units":[au],"hard_negative_reason":None,"unresolved_reason":None,"reason_detail":None}],"context_requests":[],"warnings":[]}
  with self.assertRaises(AUOnlyError):_validate_response(q,response,"abc")
  au["evidence_spans"][0]["quote"]="a";au["attributions"][0]["evidence_span"]["quote"]="WRONG"
  with self.assertRaises(AUOnlyError):_validate_response(q,response,"abc")
 def test_corrupt_cached_unresolved_fails_before_opener(self):
  calls=[]
  def opener(req,*args,**kwargs):
   calls.append("warmup" if is_warmup(req) else "source")
   if is_warmup(req):return warmup_ok()
   raise URLError("offline")
  with tempfile.TemporaryDirectory() as temp,patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   cfg={"url":"https://fake","token":"token","model":"locked-qwen","enable_thinking":False};cache_dir=Path(temp)/"cache";run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener);path=next(p for p in cache_dir.glob("**/response.json") if json.loads(p.read_text())["status"]=="unresolved");bad=json.loads(path.read_text());bad["receipt"]={};path.write_text(json.dumps(bad));before=calls.count("source")
   with self.assertRaises(AUOnlyError):run(self.manifest(),source_store="unused",cfg=cfg,budget=self.budget(),cache_dir=cache_dir,execute=True,opener=opener)
   self.assertEqual(calls.count("source"),before)
 def test_persisted_exhausted_ledger_stops_uncached_without_opener(self):
  calls=[]
  def opener(req,*args,**kwargs):
   calls.append("warmup" if is_warmup(req) else "source")
   return warmup_ok() if is_warmup(req) else FakeHTTP({"choices":[{"finish_reason":"length","message":{"content":"{}"}}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}})
  with tempfile.TemporaryDirectory() as temp,patch("knowledge_base.pipeline_v1.au_only.core.open_source",return_value="abc"):
   cfg={"url":"https://fake","token":"token","model":"locked-qwen","enable_thinking":False};cache_dir=Path(temp)/"cache";budget=self.budget();budget["max_requests"]=10;budget["max_provider_attempts"]=10;first=run(self.manifest(),source_store="unused",cfg=cfg,budget=budget,cache_dir=cache_dir,execute=True,opener=opener);victim=next(cache_dir.glob("**/response.json"));os.remove(victim);before=calls.count("source");second=run(self.manifest(),source_store="unused",cfg=cfg,budget=budget,cache_dir=cache_dir,execute=True,opener=opener)
   self.assertEqual(calls.count("source"),before);self.assertIn("budget_stopped",[x["status"] for x in second["request_ledger"]]);self.assertEqual(second["runtime_ledger"]["requests"],first["runtime_ledger"]["requests"])
