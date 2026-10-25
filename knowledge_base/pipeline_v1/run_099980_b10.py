from __future__ import annotations
from pathlib import Path
from knowledge_base.pipeline_v1.au_gold.build import checkpoint_model_proposal
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError,atomic_write,exact_span,load_json,model_review_trace
from knowledge_base.pipeline_v1.source_contract import open_source
P=Path('knowledge_base/pipeline_v1');R=P/'outputs/plan09_au_gold_v1';C='099980';B='terra-7e6e7a726f1797f54fe7efff';I='terra-099980-7e6e7a726f1797f54fe7efff'
def main():
 m=load_json(R/'au_annotation_build_manifest.json');row=next(x for x in m['cases'] if x['case_id']==C);p=load_json(R/row['packet_ref']);pol=load_json(P/'policies/au_annotation_policy.v1.json');s=open_source(m['source_store'],C,p['source_hash']);b=next(x for x in load_json(R/'terra_annotation_batches.json')['batches'] if x['batch_id']==B);ts={x['target_id']:x for x in p['tasks']};o=set()
 for x in load_json(R/'terra_proposal_manifest.json')['proposals']:o.update(y['target_id'] for y in load_json(R/x['proposal_ref'])['target_reviews'])
 if set(b['target_ids'])&o:raise AnnotationError('batch target already owned')
 pv={'source_type':'model','producer_id':'model:gpt-5.6-terra','prompt_version':pol['terra_prompt_version']};d={'at-465640dd47beffba5e476e90':('common law narrows the scope of the representations that an administrative tribunal may make on judicial review.','Common law narrows the representations an administrative tribunal may make on judicial review.','procedural_rule'),'at-e08f77cba900ac4df7b76544':('it is not up to a tribunal whose decision is under review, whether it is an appeal or a judicial review, to vindicate itself, as well as the merit of its decision.','A tribunal under review must not vindicate itself or the merits of its decision in appeal or judicial-review submissions.','procedural_rule')};rs=[]
 for tid in b['target_ids']:
  t=ts[tid];z=t['target_span'];w=exact_span(s,C,p['source_hash'],z['start_char'],z['end_char'])
  if tid in d:
   q,c,k=d[tid];a=s.index(q,z['start_char'],z['end_char']);e=exact_span(s,C,p['source_hash'],a,a+len(q));u={'au_id':'terra-'+tid,'owner_target_id':tid,'owner_block_id':t['owner_block_id'],'claim_text':c,'kind':k,'other_kind':None,'evidence_spans':[e],'attributions':[{'role':'proposition','speaker':'current_court','evidence_span':e}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':pv,'notes':[],'uncertainty':'medium','unresolved_reasons':[]};r={'target_id':tid,'review_complete':True,'reviewed_span':w,'authority_units':[u],'hard_negative':None,'notes':[],'model_outcome':'positive','unresolved_reasons':[]}
  else:r={'target_id':tid,'review_complete':True,'reviewed_span':w,'authority_units':[],'hard_negative':{'reason':'other','reviewed_span':w,'provenance':pv,'notes':['Full-target/context review: rhetorical question or litigation-position context only.']},'notes':[],'model_outcome':'hard_negative','unresolved_reasons':[]}
  r['review_trace']=model_review_trace(t,s,p['source_hash'],r);r['review_trace']['region_id']=b['region_id'];r['review_trace']['region_fingerprint']=b['region_fingerprint'];rs.append(r)
 q={'artifact_type':'TerraAUProposal','schema_version':'terra-au-proposal-v1','proposal_id':I,'packet_id':p['packet_id'],'case_id':C,'source_hash':p['source_hash'],'producer':{'source_type':'model','producer_id':'model:gpt-5.6-terra','model':'gpt-5.6-terra','reasoning_effort':'low'},'prompt_version':pol['terra_prompt_version'],'batch_id':B,'status':'model_proposed','target_reviews':rs};atomic_write(R/'stage_099980_b10.json',q);print(checkpoint_model_proposal(proposal=q,output_root=R,source_store=m['source_store'],policy=pol))
if __name__=='__main__':main()
