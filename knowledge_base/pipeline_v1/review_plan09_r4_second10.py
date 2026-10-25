"""Second frozen R4 batch: exactly ten missing 099980 targets, no independent audit."""
from .au_gold.core import atomic_write, exact_span, load_json, model_review_trace, validate_model_proposal
from .au_gold.remediation import ROOT, dependencies, digest, effective_proposals, proposal_records
from .au_gold.r3_completion import validate_completion
from .au_gold.r4 import checkpoint, publish_progress, rebuild_manifest
from .review_plan09_r4_first10 import PRODUCER, PROVENANCE

BATCH_ID='p09-r4-099980-second10-sol-v1'
DECISIONS=[
 ('unresolved',None,None,None,'Paragraph 92 blends the applicant interpretation with the court tentative I am inclined to agree. Paragraph 93 explicitly declines a definitive opinion on jurisdiction/reasonableness. AU eligibility of a non-final jurisdiction observation is uncertain; neither a final jurisdiction holding nor a purely party-only negative is faithful. Abstain with no AU label.'),
 ('hard_negative','party_argument_only',None,None,'Paragraph 189 reports respondent concessions, proposed costs and unpaid motion costs. The minimum/one-cent-more language remains respondent advocacy; paragraph 190 supplies a distinct court costs decision, not adoption of respondent position.'),
 ('hard_negative','fact_only',None,None,'Paragraph 16 narrates applicant maternity leave/supervisor role and then reports the investigator fraud finding and presumed knowledge. Do not convert that investigator presumption or asserted duty to correct references into current-court law.'),
 ('hard_negative','fact_only',None,None,'Paragraph 160 assesses testimony and the factual investigation purpose. The court observation that fraud was not directly referenced is factual assessment, not a standalone legal holding. Paragraph 161 legitimate-expectation proposition has a different owner and is not imported.'),
 ('hard_negative','party_argument_only',None,None,'Paragraph 74 states respondent reliance on Seck 1 and claimed plenary jurisdiction. Broad sanction powers are respondent submissions, not adopted current-court authority; exclude the following heading.'),
 ('hard_negative','editorial',None,None,'Paragraph 196 explicitly disclaims determining innocence, then repeats case-specific criticism and Rule-of-Law rhetoric. No separate legal test or operative remedy is stated here. Do not invent an innocence holding or general concealment prohibition from rhetoric.'),
 ('hard_negative','party_argument_only',None,None,'Paragraph 95 records respondent admission of serious consequences but argues opportunity to comment was sufficient and procedure fair. Paragraph 96 begins court analysis; paragraph 95 is not court adoption or a court finding that applicant is to blame.'),
 ('positive','fact_pattern_rule','In assessing alleged fraud in this Commission context, intent behind the actions is essential; the material act alone is insufficient.',"The determination of the intent behind the actions taken is therefore an essential element of the analysis of the evidence. We cannot look only at the material fact alone.",'First two sentences are current-court analytical conclusions. The subsequent Commission section-66 quotation is an analogy, not a separate current-court witness. Keep preceding paragraph-53 fraud/deception context rather than generalize beyond this fraud analysis.'),
 ('positive','procedural_rule','Assuming Commission jurisdiction over third parties, assessing this decision reasonableness calls for examining whether the Commission considered its own relevant false-reference jurisprudence.',"In that context, for the purposes of assessing the reasonableness of the impugned decision, it becomes highly relevant to verify whether the Commission actually applied and considered its own jurisprudence governing fraud involving \"false references\" provided by third parties as part of an appointment process.",'Current-court analytical guidance, not a final reasonableness disposition. Retain the explicit jurisdiction assumption in paragraph 61 and the court reservation of any definitive jurisdiction/reasonableness opinion in paragraph 93. Do not state a universal binding-precedent duty or a final jurisdiction ruling.'),
 ('hard_negative','procedural_history_only',None,None,'Paragraph 90 recounts the Commission three corrective actions in this applicant case. Not court endorsement of general permission/revocation or RCMP-referral authority; the contested jurisdiction analysis follows.'),
]

RESERVATION='However, there is no need to express a definitive opinion on the issue of jurisdiction or reasonableness today or to base the judgment of the Court allowing the application for judicial review on such a contentious aspect that might soon be argued before the Federal Court of Appeal as part of the appeal in Seck 1.'


def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    outcome,kind,claim,quote,reason=DECISIONS[position-1]
    contexts=[span(max(0,a-1000),min(len(source),b+1000))]
    if position==8:
        c=source.rfind('[53]',0,a)
        contexts=[span(c,min(len(source),b+1000))]
    if position==9:
        c=source.index(RESERVATION)
        contexts.append(span(source.rfind('[92]',0,c),source.index('[94]',c)))
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':contexts}
    if outcome=='hard_negative':
        review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif outcome=='positive':
        start=source.index(quote,a,b);witness=span(start,start+len(quote))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':'current_court','evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'medium' if position==9 else 'low','unresolved_reasons':[]}
        if position==8:
            c=source.rfind('[53]',0,a)+len('[53]')
            end=source.rfind('[54]',0,a)
            au['cross_block_refs']=[span(c,end)]
            exception='If it was in good faith, we are talking about an "error" instead.'
            start=source.index(exception,c,end)
            au['exception_spans']=[span(start,start+len(exception))]
        if position==9:
            au['claim_text']='Assuming Commission jurisdiction over third parties, it is highly relevant in assessing this decision reasonableness to examine whether the Commission considered its own relevant false-reference jurisprudence.'
            assumption='always on the assumption that the Commission had jurisdiction'
            c=source.index(assumption,a,b);au['condition_spans']=[span(c,c+len(assumption))]
            c=source.index(RESERVATION);au['limit_spans']=[span(c,c+len(RESERVATION))]
            au['cross_block_refs']=[span(c,c+len(RESERVATION))]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-second10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


def main():
    pipeline=ROOT.parents[1]
    batch_path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    packet,source,policy=dependencies(ROOT,'099980')
    progress_path=pipeline/'reports/plan09_model_silver_progress.latest.json'
    if batch_path.exists():batch=load_json(batch_path)
    else:
        prior=load_json(progress_path)
        assert prior['reviewed_target_count']==222 and prior['missing_target_count']==147
        ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
        saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
        for name in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json','r4_first10_validation.json','r4_first10_resume_verification.json'):
            saved[str((ROOT/name).relative_to(pipeline))]=digest(ROOT/name)
        batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','before_progress':prior,'before_progress_sha256':digest(progress_path),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'semantic_gold':False,'independent_acceptance':False,'plan10_allowed':False}
        atomic_write(batch_path,batch)
    assert len(batch['target_ids'])==10 and batch['source_hash']==packet['source_hash']
    tasks={t['target_id']:t for t in packet['tasks']};results=[]
    for position,tid in enumerate(batch['target_ids'],1):
        path=ROOT/'r4_model_proposals/099980'/f'p09-r4-099980-second10-{position:02d}-gpt61sol-v1.json'
        proposal=load_json(path) if path.exists() else make_proposal(tasks[tid],packet,source,position,batch)
        assert proposal['target_reviews'][0]['target_id']==tid
        result=checkpoint(proposal,batch);review=proposal['target_reviews'][0]
        results.append({**result,'position':position,'target_id':tid,'target_span':review['reviewed_span'],'context_spans':review['context_spans'],'outcome':review['model_outcome'],'authority_units':review['authority_units'],'hard_negative':review['hard_negative'],'unresolved_reasons':review['unresolved_reasons'],'reason':review['notes']})
        print(f'PASS R4 second10 position={position} outcome={review["model_outcome"]} resumed={result["resumed"]}',flush=True)
    assert all(digest(pipeline/ref)==sha for ref,sha in batch['preserved_artifacts'].items())
    validate_completion();rebuild_manifest()
    manifest=load_json(ROOT/'model_proposal_manifest.json')
    assert manifest['proposals'][:len(batch['before_model_manifest']['proposals'])]==batch['before_model_manifest']['proposals']
    for row in proposal_records():
        proposal=load_json(ROOT/row['proposal_ref']);p,t,pol=dependencies(ROOT,proposal['case_id']);validate_model_proposal(proposal,p,t,pol)
    reviews=[r for p in effective_proposals() for r in p['target_reviews']]
    progress=publish_progress()
    assert len(reviews)==232 and progress['expected_target_count']==369 and progress['missing_target_count']==137
    before_missing=set(next(c['missing_target_ids'] for c in batch['before_progress']['cases'] if c['case_id']=='099980'))
    after_missing=set(next(c['missing_target_ids'] for c in progress['cases'] if c['case_id']=='099980'))
    assert before_missing-after_missing==set(batch['target_ids']) and not after_missing-before_missing
    assert (sum(len(r['authority_units']) for r in reviews),sum(r['hard_negative'] is not None for r in reviews),sum(r['model_outcome']=='unresolved' for r in reviews))==(104,126,2)
    assert progress['gates']=={'r3_pass':True,'r4_coverage_complete':False,'r5_final_audit_pass':False,'plan10_allowed':False}
    report={'artifact_type':'Plan09R4Second10ModelReviewValidation','batch_ref':batch_path.relative_to(ROOT).as_posix(),'producer':PRODUCER,'semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False,'results':results,'batch_counts':{'authority_units':2,'hard_negatives':7,'unresolved':1},'effective_counts':{'authority_units':104,'hard_negatives':126,'unresolved':2},'reviewed_target_count':232,'expected_target_count':369,'missing_before':147,'missing_after':137,'existing_222_targets_unchanged':True,'first10_batch_unchanged':True,'r3_bound_artifacts_unchanged':True,'all_proposals_valid':True,'effective_overlay_valid':True}
    atomic_write(ROOT/'r4_second10_validation.json',report)
    print('PASS R4 second10 targets=10 AU=2 negative=7 unresolved=1 coverage=232/369 missing=137 R3=unchanged Plan10=false')


if __name__=='__main__':main()
