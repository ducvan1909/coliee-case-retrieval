"""Checkpoint Plan 09 model-silver batch terra-55f0fea06b472ba7d493c90b."""
from __future__ import annotations
from pathlib import Path
from knowledge_base.pipeline_v1.au_gold.build import checkpoint_model_proposal
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError,atomic_write,exact_span,load_json,model_review_trace
from knowledge_base.pipeline_v1.source_contract import open_source
P=Path("knowledge_base/pipeline_v1");ROOT=P/"outputs/plan09_au_gold_v1";CASE_ID="099980";BATCH_ID="terra-55f0fea06b472ba7d493c90b";PROPOSAL_ID="terra-099980-55f0fea06b472ba7d493c90b"
def sp(src,p,t,q):
 z=t["target_span"]
 try:a=src.index(q,z["start_char"],z["end_char"])
 except ValueError as e:raise AnnotationError("evidence quote not found for "+t["target_id"]) from e
 return exact_span(src,CASE_ID,p["source_hash"],a,a+len(q))
def unit(t,e,claim,kind,pv):return {"au_id":"terra-"+t["target_id"],"owner_target_id":t["target_id"],"owner_block_id":t["owner_block_id"],"claim_text":claim,"kind":kind,"other_kind":None,"evidence_spans":[e],"attributions":[{"role":"proposition","speaker":"current_court","evidence_span":e}],"condition_spans":[],"exception_spans":[],"limit_spans":[],"cross_block_refs":[],"overlap_disposition":"none","duplicate_of":None,"status":"model_proposed","provenance":pv,"notes":[],"uncertainty":"medium","unresolved_reasons":[]}
def main():
 m=load_json(ROOT/"au_annotation_build_manifest.json");row=next(x for x in m["cases"] if x["case_id"]==CASE_ID);p=load_json(ROOT/row["packet_ref"]);pol=load_json(P/"policies/au_annotation_policy.v1.json");src=open_source(m["source_store"],CASE_ID,p["source_hash"]);b=next(x for x in load_json(ROOT/"terra_annotation_batches.json")["batches"] if x["batch_id"]==BATCH_ID);ts={x["target_id"]:x for x in p["tasks"]};owned=set()
 for rec in load_json(ROOT/"terra_proposal_manifest.json")["proposals"]:owned.update(x["target_id"] for x in load_json(ROOT/rec["proposal_ref"])["target_reviews"])
 if set(b["target_ids"])&owned:raise AnnotationError("batch target already has canonical owner")
 pv={"source_type":"model","producer_id":"model:gpt-5.6-terra","prompt_version":pol["terra_prompt_version"]};d={"at-2fed8f291ffc071685556b2c":("section 69 is not only a jurisdiction - granting provision - if it has reason to believe that fraud may have occurred in the appointment process, the Commission may investigate the appointment process-but also a provision that grants some remedial powers to the Commission if it is satisfied that fraud has occurred.","Section 69 authorizes Commission investigation where it has reason to believe appointment-process fraud occurred and grants remedial powers when fraud is established.","statutory_hook"),"at-b8609be4d650e488852029fc":("The PSMA introduced a framework for human resources modernization in the federal public service","The PSMA introduced a federal public-service human-resources modernization framework and amended related public-service statutes.","statutory_hook"),"at-e7207dadc9bad13a738d039f":("Section 69 came into force on December 31, 2005, at the same time as the other PSEA provisions","Section 69 came into force on December 31, 2005 with the other PSEA provisions.","statutory_hook")};rs=[]
 for tid in b["target_ids"]:
  t=ts[tid];z=t["target_span"];reviewed=exact_span(src,CASE_ID,p["source_hash"],z["start_char"],z["end_char"])
  if tid=="at-6a0d5ed96a002aa4959047bd":r={"target_id":tid,"review_complete":True,"reviewed_span":reviewed,"authority_units":[],"hard_negative":{"reason":"other","reviewed_span":reviewed,"provenance":pv,"notes":["Full-target/context review: analytical transition and metaphor only; no legal proposition."]},"notes":[],"model_outcome":"hard_negative","unresolved_reasons":[]}
  else:q,c,k=d[tid];r={"target_id":tid,"review_complete":True,"reviewed_span":reviewed,"authority_units":[unit(t,sp(src,p,t,q),c,k,pv)],"hard_negative":None,"notes":[],"model_outcome":"positive","unresolved_reasons":[]}
  r["review_trace"]=model_review_trace(t,src,p["source_hash"],r);r["review_trace"]["region_id"]=b["region_id"];r["review_trace"]["region_fingerprint"]=b["region_fingerprint"];rs.append(r)
 q={"artifact_type":"TerraAUProposal","schema_version":"terra-au-proposal-v1","proposal_id":PROPOSAL_ID,"packet_id":p["packet_id"],"case_id":CASE_ID,"source_hash":p["source_hash"],"producer":{"source_type":"model","producer_id":"model:gpt-5.6-terra","model":"gpt-5.6-terra","reasoning_effort":"low"},"prompt_version":pol["terra_prompt_version"],"batch_id":BATCH_ID,"status":"model_proposed","target_reviews":rs};atomic_write(ROOT/"stage_099980_b3.json",q);print(checkpoint_model_proposal(proposal=q,output_root=ROOT,source_store=m["source_store"],policy=pol))
if __name__=="__main__":main()
