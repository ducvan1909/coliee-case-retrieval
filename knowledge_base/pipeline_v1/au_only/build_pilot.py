from __future__ import annotations
import argparse,json
from pathlib import Path
from ..sentence_atoms.segmenter import canonical_hash
from .core import _atomic,validate_manifest
S={"011904":["at-056fd4ca0454c65c2b585cea","at-ade4a3797b31d7deb9bf7baf"],"013009":["at-d1a9498ecd408d28317aa793","at-f4a073144323210976dace57"],"013948":["at-3afd82f9ffea744294fd4624","at-726483a83077ee92addf3aff"],"045155":["at-923a3aae96b77d61178e6d57","at-52c4e1747233e8e73f3510f5"],"099980":["at-c346a3add188a66127ed9fb5","at-422fbd7f49cb2cff502c7399"]}
def build(root):
 maps=[(p,json.loads(p.read_text())) for p in Path(root).glob("cases/**/p2-offline-scheduler-v1.4-*/analysis_workload_map.json")];rows=[];spec={"model":"Qwen/Qwen3.5-9B","enable_thinking":False,"caps":{"targets":1,"output_tokens":1600,"au_candidates":8}}
 for case,targets in S.items():
  for target in targets:
   path,v=next((p,x) for p,x in maps if x["case_id"]==case and any(target in r["target_ids"] for r in x["regions"] if r["arm"]=="P2a"));r=next(r for r in v["regions"] if r["arm"]=="P2a" and target in r["target_ids"]);refs=[{"role":"target" if target in i.get("ref_ids",[]) else "context","start_char":i["span"]["start_char"],"end_char":i["span"]["end_char"],"target_ids":[target] if target in i.get("ref_ids",[]) else []} for i in r["render_items"]];rows.append({"case_id":case,"source_hash":v["source_hash"],"region_id":"auo-"+canonical_hash({"v14":r["region_id"],"target":target})[:24],"arm":"AU-only","expected_target_ids":[target],"source_refs":refs,"spec":spec,"request_id":"auo-"+canonical_hash({"case":case,"target":target,"spec":spec})[:24],"input_tokens":r["metrics"]["estimated_input_tokens"]+1600,"hint_payload":{"version":"context-hint-payload-v1","hint_ids":[]},"provenance":{"identity_source":"frozen Plan07 v1.4 exact Plan09 R5 namespace","frozen_map":str(path),"frozen_region_id":r["region_id"],"selection":"model_silver development only; not human gold"}})
 out={"artifact_type":"AUOnlyLockedManifest","schema_version":"au-only-manifest-v1","requests":rows};validate_manifest(out);return out
def main():
 p=argparse.ArgumentParser();p.add_argument("--root",default="knowledge_base/pipeline_v1/outputs/plan07_analysis_regions_v1");p.add_argument("--output",default="knowledge_base/pipeline_v1/manifests/au_only_pilot_r5_model_silver.v1.json");a=p.parse_args();_atomic(a.output,build(a.root));print("AU-ONLY PILOT MANIFEST PASS — output: "+str(Path(a.output).resolve()))
if __name__=="__main__":main()
