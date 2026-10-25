import hashlib,json,tempfile,unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from knowledge_base.pipeline_v1.au_only.atom_binding import AtomBindingError,resolve
P=Path(__file__).resolve().parents[1]
class CompactFoundation(unittest.TestCase):
 def schema(self):
  value=json.loads((P/'contracts/compact_au_model_output.v1.json').read_text());Draft202012Validator.check_schema(value);return Draft202012Validator(value)
 def au(self,**overrides):
  value={"kind":"holding","other_kind":None,"claim":"A proposition.","evidence_ref_ids":["sa-1"],"speaker":"current_court","attribution_role":"proposition","needs_context":[]};return {**value,**overrides}
 def test_schema_decision_cardinality_and_coverage(self):
  v=self.schema();positive={"request_id":"r","target_id":"t","decision":"positive","coverage_status":"complete","aus":[self.au()],"hard_negative_reason":None,"unresolved_reason":None};self.assertFalse(list(v.iter_errors(positive)))
  split={**positive,"coverage_status":"needs_split","aus":[self.au(),self.au(claim="B."),self.au(claim="C.")]};self.assertFalse(list(v.iter_errors(split)))
  hard={"request_id":"r","target_id":"t","decision":"hard_negative","coverage_status":"complete","aus":[],"hard_negative_reason":"fact_only","unresolved_reason":None};self.assertFalse(list(v.iter_errors(hard)))
  unresolved={"request_id":"r","target_id":"t","decision":"unresolved","coverage_status":"needs_split","aus":[],"hard_negative_reason":None,"unresolved_reason":"needs_split"};self.assertFalse(list(v.iter_errors(unresolved)))
  for bad in ({**positive,"aus":[]},{**hard,"coverage_status":"needs_split"},{**hard,"aus":[self.au()]},{**hard,"hard_negative_reason":None},{**unresolved,"unresolved_reason":None},{**unresolved,"hard_negative_reason":"other"},{**unresolved,"aus":[self.au()]},{**positive,"aus":[self.au(),self.au(claim="B."),self.au(claim="C."),self.au(claim="D.")]}):
   self.assertTrue(list(v.iter_errors(bad)))
 def test_schema_needs_context_is_closed_obligation_array(self):
  v=self.schema();base={"request_id":"r","target_id":"t","decision":"positive","coverage_status":"complete","aus":[self.au(needs_context=["attribution","limit"])],"hard_negative_reason":None,"unresolved_reason":None};self.assertFalse(list(v.iter_errors(base)))
  for bad_needs in (True,["unknown"],["limit","limit"]):self.assertTrue(list(v.iter_errors({**base,"aus":[self.au(needs_context=bad_needs)]})))
 def test_schema_other_kind_is_not_invented(self):
  v=self.schema();base={"request_id":"r","target_id":"t","decision":"positive","coverage_status":"complete","aus":[self.au()],"hard_negative_reason":None,"unresolved_reason":None};self.assertTrue(list(v.iter_errors({**base,"aus":[self.au(other_kind="label")]})))
  self.assertTrue(list(v.iter_errors({**base,"aus":[self.au(kind="other",other_kind=None)]})))
  self.assertFalse(list(v.iter_errors({**base,"aus":[self.au(kind="other",other_kind="custom")] })))
 def test_explicit_atom_binding_rejects_tamper_and_mismatch(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'map.json';value={"case_id":"000001","source_hash":"a"*64,"segmenter_version":"v","policy_sha256":"b"*64};p.write_text(json.dumps(value));b={"atom_map_path":str(p),"atom_map_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),**value};self.assertEqual(resolve(b),value);b["atom_map_sha256"]="0"*64
   with self.assertRaises(AtomBindingError):resolve(b)
