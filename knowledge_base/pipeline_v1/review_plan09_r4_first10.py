"""Executed gpt-6.1-sol low decisions for exactly the frozen first ten missing IDs."""
from pathlib import Path
from .au_gold.core import atomic_write, exact_span, load_json, model_review_trace, validate_model_proposal
from .au_gold.remediation import ROOT, dependencies, digest, effective_proposals, proposal_records
from .au_gold.r3_completion import validate_completion
from .au_gold.r4 import checkpoint, publish_progress, rebuild_manifest

BATCH_ID='p09-r4-099980-first10-sol-v1'
PRODUCER={'source_type':'model','producer_id':'model:gpt-6.1-sol','model':'gpt-6.1-sol','reasoning_effort':'low'}
PROVENANCE={'source_type':'model','producer_id':'model:gpt-6.1-sol','prompt_version':'r4-au-annotation-prompt-v1'}

# These decisions were made after reading each entire target and source context.
# No blanket generation or forced-positive policy is used.
DECISIONS=[
 ('positive','procedural_rule','In Commission fraud investigations, the investigator must follow fair-play rules when compelling a person suspected of fraud to testify.',"There is therefore a\r\nquid pro quo\r\nto the exercise of the investigator's absolute power to compel a person suspected of fraud to testify against his or her will: the investigator must adhere to the rules of fair play with respect to the individual.",'Court analytical voice, not investigator speech. The opening describes confidentiality; extract only the compelled-testimony/fair-play rule and retain that triggering scope.'),
 ('hard_negative','fact_only',None,None,'Court describes what prompted this investigation and what officials apparently did not consider under the Policy. This is case-record/background appraisal, not a final jurisdiction holding or adopted legal test; do not import paragraph 68 investigator interpretation.'),
 ('positive','holding','After applying the Baker factors, the Court found the Commission investigation procedure seriously flawed and inconsistent with the legitimate expectations of persons suspected of fraud.',"After weighing each of the factors listed in\r\nBaker\r\n, I find that the procedure put in place by the Commission, more specifically with respect to the investigation phase - which is crucial - does not respect the legitimate expectations of individuals suspected of fraud and is seriously flawed.",'Explicit I find is current-court holding. Scope to this Commission investigation procedure, not a blanket claim that every section-69 investigation is unlawful. Exclude following Evidence in the record heading.'),
 ('hard_negative','procedural_history_only',None,None,'Paragraph 178 introduces and quotes the Investigations Directorate memorandum responding to counsel. Its procedural-fairness defence is agency speech, not adopted court law. Court sceptical introductory comment alone is not a separately extracted holding; paragraph 179 is the separate court response owned by target 9.'),
 ('hard_negative','fact_only',None,None,'Paragraph 128 identifies the only sworn evidence and the certified record. Court narration of the evidentiary record, not a reusable legal proposition or a procedural holding.'),
 ('hard_negative','fact_only',None,None,'Paragraph 13 narrates the reference-checking officer work and Ms M\'Kounga response. These employment/reference events are facts, not court-created legal authority; adjacent investigator findings are not adopted here as legal propositions.'),
 ('positive','holding','In this case, the Court considered the applicant\'s irreparable harm as a public-interest factor in exercising its discretion over costs.',"Even if the applicant's \"victory\" seems complete today, it might as well be a \"Pyrrhic victory\", since she has already suffered irreparable harm because of the Commission. The public interest requires this to be taken into consideration.",'Current-court reasons in the costs discussion. Paragraph 190 explicitly scopes discretion to an increased costs award and lists irreparable harm/public interest; preserve this case-specific limit. Do not label the rhetoric as a general compensation rule.'),
 ('hard_negative','party_argument_only',None,None,'Paragraph 73 expressly reports the applicant request, submissions and arguments against Seck 1. Not current-court adoption. The respondent position starts paragraph 74 and is also not a court holding.'),
 ('positive','holding','The Court found a flagrant breach of procedural fairness in this applicant\'s case.',"The breach of procedural fairness is flagrant in the applicant's case.",'Paragraph 179 is the court response, distinct from paragraph 178 quoted Directorate defence. Extract the first sentence only; do not broaden to all investigations or promote respondent arguments to court voice.'),
 ('hard_negative','fact_only',None,None,'Paragraph 117 describes adverse transfer/advancement effects of the permission condition. This costs/fairness-impact factual background is not a standalone rule requiring Commission permission or a judicial declaration that such a general condition is valid.'),
]


def make_proposal(task, packet, source, position, batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    outcome,kind,claim,quote,reason=DECISIONS[position-1]
    context_start=max(0,a-900)
    context_end=min(len(source),b+900)
    if position==7:context_start=source.rfind('[190]',0,a)
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[],'context_spans':[span(context_start,context_end)]}
    if outcome=='hard_negative':
        review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    else:
        start=source.index(quote,a,b)
        witness=span(start,start+len(quote))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':'current_court','evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'low','unresolved_reasons':[]}
        if position==1:
            condition="the exercise of the investigator's absolute power to compel a person suspected of fraud to testify against his or her will"
            c=source.index(condition,a,b);au['condition_spans']=[span(c,c+len(condition))]
        if position==3:
            limitation='more specifically with respect to the investigation phase - which is crucial -'
            c=source.index(limitation,a,b);au['limit_spans']=[span(c,c+len(limitation))]
        if position==7:
            support_start=context_start+len('[190]')
            support_end=source.index('[191]',support_start)
            au['cross_block_refs']=[span(support_start,support_end)]
            limitation='in this case, the irreparable harm already suffered by the applicant'
            c=source.index(limitation,support_start,support_end);au['limit_spans']=[span(c,c+len(limitation))]
        if position==9:
            limitation="in the applicant's case"
            c=source.index(limitation,a,b);au['limit_spans']=[span(c,c+len(limitation))]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-first10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


def main():
    pipeline=ROOT.parents[1]
    batch_path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    packet,source,policy=dependencies(ROOT,'099980')
    progress_path=pipeline/'reports/plan09_model_silver_progress.latest.json'
    if batch_path.exists():
        batch=load_json(batch_path)
    else:
        prior=load_json(progress_path)
        assert prior['reviewed_target_count']==212 and prior['missing_target_count']==157
        ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
        saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews') for p in (ROOT/folder).rglob('*.json')}
        for name in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json'):
            saved[str((ROOT/name).relative_to(pipeline))]=digest(ROOT/name)
        batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','before_progress':prior,'before_progress_sha256':digest(progress_path),'preserved_artifacts':saved,'producer':PRODUCER,'semantic_gold':False,'independent_acceptance':False,'plan10_allowed':False}
        atomic_write(batch_path,batch)
    assert len(batch['target_ids'])==10 and batch['source_hash']==packet['source_hash']
    tasks={t['target_id']:t for t in packet['tasks']}
    results=[]
    for position,tid in enumerate(batch['target_ids'],1):
        path=ROOT/'r4_model_proposals/099980'/f'p09-r4-099980-first10-{position:02d}-gpt61sol-v1.json'
        # A valid durable checkpoint is revalidated/reconciled, never relabelled.
        proposal=load_json(path) if path.exists() else make_proposal(tasks[tid],packet,source,position,batch)
        assert proposal['target_reviews'][0]['target_id']==tid
        result=checkpoint(proposal,batch)
        review=proposal['target_reviews'][0]
        results.append({**result,'position':position,'target_id':tid,'target_span':review['reviewed_span'],'context_spans':review['context_spans'],'outcome':review['model_outcome'],'authority_units':review['authority_units'],'hard_negative':review['hard_negative'],'reason':review['notes']})
        print(f'PASS R4 position={position} outcome={review["model_outcome"]} resumed={result["resumed"]}',flush=True)
    assert all(digest(pipeline/ref)==sha for ref,sha in batch['preserved_artifacts'].items())
    validate_completion()
    effective=effective_proposals()
    reviews=[r for p in effective for r in p['target_reviews']]
    assert len(reviews)==222
    for row in proposal_records():
        proposal=load_json(ROOT/row['proposal_ref'])
        p,t,pol=dependencies(ROOT,proposal['case_id']);validate_model_proposal(proposal,p,t,pol)
    rebuild_manifest()
    progress=publish_progress()
    assert progress['expected_target_count']==369 and progress['missing_target_count']==147
    before_missing=set(next(c['missing_target_ids'] for c in batch['before_progress']['cases'] if c['case_id']=='099980'))
    after_missing=set(next(c['missing_target_ids'] for c in progress['cases'] if c['case_id']=='099980'))
    assert before_missing-after_missing==set(batch['target_ids']) and not after_missing-before_missing
    assert progress['gates']=={'r3_pass':True,'r4_coverage_complete':False,'r5_final_audit_pass':False,'plan10_allowed':False}
    report={'artifact_type':'Plan09R4First10ModelReviewValidation','batch_ref':batch_path.relative_to(ROOT).as_posix(),'producer':PRODUCER,'semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False,'results':results,'batch_counts':{'authority_units':4,'hard_negatives':6,'unresolved':0},'effective_counts':{'authority_units':progress['authority_unit_count'],'hard_negatives':progress['hard_negative_count'],'unresolved':progress['unresolved_target_count']},'reviewed_target_count':222,'expected_target_count':369,'missing_before':157,'missing_after':147,'existing_212_targets_unchanged':True,'r3_bound_artifacts_unchanged':True,'all_proposals_valid':True,'effective_overlay_valid':True}
    atomic_write(ROOT/'r4_first10_validation.json',report)
    print('PASS R4 targets=10 AU=4 negative=6 unresolved=0 coverage=222/369 missing=147 R3=unchanged Plan10=false')


if __name__=='__main__':main()
