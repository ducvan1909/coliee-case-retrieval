"""Checkpoint Plan 09 model-silver batch terra-223fe84ba41cb3b34e776991."""
from __future__ import annotations
from pathlib import Path
from knowledge_base.pipeline_v1.au_gold.build import checkpoint_model_proposal
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError,atomic_write,exact_span,load_json,model_review_trace
from knowledge_base.pipeline_v1.source_contract import open_source
P=Path("knowledge_base/pipeline_v1");ROOT=P/"outputs/plan09_au_gold_v1";CASE_ID="099980";BATCH_ID="terra-223fe84ba41cb3b34e776991";PROPOSAL_ID="terra-099980-223fe84ba41cb3b34e776991"
def main():
 m=load_json(ROOT/"au_annotation_build_manifest.json");row=next(x for x in m["cases"] if x["case_id"]==CASE_ID);p=load_json(ROOT/row["packet_ref"]);pol=load_json(P/"policies/au_annotation_policy.v1.json");src=open_source(m["source_store"],CASE_ID,p["source_hash"]);b=next(x for x in load_json(ROOT/"terra_annotation_batches.json")["batches"] if x["batch_id"]==BATCH_ID);ts={x["target_id"]:x for x in p["tasks"]};owned=set()
 for rec in load_json(ROOT/"terra_proposal_manifest.json")["proposals"]:owned.update(x["target_id"] for x in load_json(ROOT/rec["proposal_ref"])["target_reviews"])
 if set(b["target_ids"])&owned:raise AnnotationError("batch target already has canonical owner")
 pv={"source_type":"model","producer_id":"model:gpt-5.6-terra","prompt_version":pol["terra_prompt_version"]};party={"at-85193f8835b0938b8891b2e3","at-d5e6f6906ee33eb694b13a74"};rs=[]
 for tid in b["target_ids"]:
  t=ts[tid];z=t["target_span"];span=exact_span(src,CASE_ID,p["source_hash"],z["start_char"],z["end_char"]);reason="party_argument_only" if tid in party else "fact_only";note="Full-target/context review: agency or litigant position only; no current-court determination." if reason=="party_argument_only" else "Full-target/context review: factual background or case record only."
  r={"target_id":tid,"review_complete":True,"reviewed_span":span,"authority_units":[],"hard_negative":{"reason":reason,"reviewed_span":span,"provenance":pv,"notes":[note]},"notes":[],"model_outcome":"hard_negative","unresolved_reasons":[]};r["review_trace"]=model_review_trace(t,src,p["source_hash"],r);r["review_trace"]["region_id"]=b["region_id"];r["review_trace"]["region_fingerprint"]=b["region_fingerprint"];rs.append(r)
 q={"artifact_type":"TerraAUProposal","schema_version":"terra-au-proposal-v1","proposal_id":PROPOSAL_ID,"packet_id":p["packet_id"],"case_id":CASE_ID,"source_hash":p["source_hash"],"producer":{"source_type":"model","producer_id":"model:gpt-5.6-terra","model":"gpt-5.6-terra","reasoning_effort":"low"},"prompt_version":pol["terra_prompt_version"],"batch_id":BATCH_ID,"status":"model_proposed","target_reviews":rs};atomic_write(ROOT/"stage_099980_b6.json",q);print(checkpoint_model_proposal(proposal=q,output_root=ROOT,source_store=m["source_store"],policy=pol))
if __name__=="__main__":main()
