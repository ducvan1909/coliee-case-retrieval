"""Checkpoint Plan 09 model-silver batch terra-8b90f7099372a6aa40274893."""
from __future__ import annotations
from pathlib import Path
from knowledge_base.pipeline_v1.au_gold.build import checkpoint_model_proposal
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError,atomic_write,exact_span,load_json,model_review_trace
from knowledge_base.pipeline_v1.source_contract import open_source
P=Path("knowledge_base/pipeline_v1");ROOT=P/"outputs/plan09_au_gold_v1";CASE_ID="099980";BATCH_ID="terra-8b90f7099372a6aa40274893";PROPOSAL_ID="terra-099980-8b90f7099372a6aa40274893"
def main():
 m=load_json(ROOT/"au_annotation_build_manifest.json");row=next(x for x in m["cases"] if x["case_id"]==CASE_ID);p=load_json(ROOT/row["packet_ref"]);pol=load_json(P/"policies/au_annotation_policy.v1.json");src=open_source(m["source_store"],CASE_ID,p["source_hash"]);b=next(x for x in load_json(ROOT/"terra_annotation_batches.json")["batches"] if x["batch_id"]==BATCH_ID);tasks={x["target_id"]:x for x in p["tasks"]};owned=set()
 for record in load_json(ROOT/"terra_proposal_manifest.json")["proposals"]: owned.update(x["target_id"] for x in load_json(ROOT/record["proposal_ref"])["target_reviews"])
 if set(b["target_ids"])&owned: raise AnnotationError("batch target already has canonical owner")
 reasons={"at-1431715ac2540416705d77b7":"procedural_history_only","at-3de705dad5e1c4cc11c402ec":"procedural_history_only","at-7e160cf318226a5dada732d7":"procedural_history_only","at-c5a067b53177f3d4911776f7":"party_argument_only"};pv={"source_type":"model","producer_id":"model:gpt-5.6-terra","prompt_version":pol["terra_prompt_version"]};reviews=[]
 for tid in b["target_ids"]:
  t=tasks[tid];z=t["target_span"];span=exact_span(src,CASE_ID,p["source_hash"],z["start_char"],z["end_char"]);note="Full-target/context review: procedural case history only." if reasons[tid]=="procedural_history_only" else "Full-target/context review: competing party positions only; no current-court proposition."
  r={"target_id":tid,"review_complete":True,"reviewed_span":span,"authority_units":[],"hard_negative":{"reason":reasons[tid],"reviewed_span":span,"provenance":pv,"notes":[note]},"notes":[],"model_outcome":"hard_negative","unresolved_reasons":[]};r["review_trace"]=model_review_trace(t,src,p["source_hash"],r);r["review_trace"]["region_id"]=b["region_id"];r["review_trace"]["region_fingerprint"]=b["region_fingerprint"];reviews.append(r)
 q={"artifact_type":"TerraAUProposal","schema_version":"terra-au-proposal-v1","proposal_id":PROPOSAL_ID,"packet_id":p["packet_id"],"case_id":CASE_ID,"source_hash":p["source_hash"],"producer":{"source_type":"model","producer_id":"model:gpt-5.6-terra","model":"gpt-5.6-terra","reasoning_effort":"low"},"prompt_version":pol["terra_prompt_version"],"batch_id":BATCH_ID,"status":"model_proposed","target_reviews":reviews};atomic_write(ROOT/"stage_099980_b2.json",q);print(checkpoint_model_proposal(proposal=q,output_root=ROOT,source_store=m["source_store"],policy=pol))
if __name__=="__main__":main()
