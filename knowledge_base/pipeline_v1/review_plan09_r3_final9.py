"""Fixed final nine risk items, source-reviewed model-only; no missing targets."""
import copy
from .au_gold.core import atomic_write,exact_span,load_json,model_review_trace
from .au_gold.progress import build_progress
from .au_gold.remediation import ROOT,checkpoint_amendment,checkpoint_risk_review,dependencies,digest,effective_proposals,registry,risk_review_heads,scan_attribution_risks,validate_risk_review

DECISIONS=[
 ('at-ec01061e01622d86bb3107a2','Paragraph 30 is the court case-specific negative-risk holding. Keep holding/current_court and record the since condition that the applicant had not established the stated risk; paragraphs 25-31 explain why written assessment and paragraph 113(d) assessment were unnecessary.'),
 ('at-d1425cdc57fccc22bca63b22','Paragraph 5 is the court case-specific attribution of responsibility for this rejected PRRA application, not officer speech. Paragraph 4 identifies the missing risk/evidence, later confirmed by paragraphs 56-58. Preserve holding and record the explicit failure-to-file-evidence qualification, rather than generalize fault attribution.'),
 ('at-4745273a6ff2708807d277d2','Paragraph 22 places this excluded applicant within subsection 112(3) and describes paragraph 113(d) special assessment. Paragraphs 23-27 qualify written assessments under subsection 172(4) when section 97 risk is not established. Keep statutory_hook, record covered-person condition and the exact negative-risk exception, and make the qualification explicit in the claim.'),
 ('at-d92f9fa84ec2df3db74965a2','Paragraph 21 is current-court criticism of the applicant reliance on subsection 172(2), not adoption of his submission. Set case-specific holding, scope the claim to the ignored subsection 172(4), narrow the court attribution witness before when he submits, and preserve the negative-risk exception from paragraph 25.'),
 ('at-06c77e704242747ebd7f5f94','Paragraph 48 begins with the court assignment of evidentiary onus, followed by officer Notes to File quotation. Narrow claim/evidence/current-court witness to the first sentence; do not promote the officer quote to court voice. Paragraphs 47 and 49-50 identify the prior refugee-claim facts that were not submitted in PRRA.'),
 ('at-2d5dc405fcc3b68543fb36f8','Paragraph 47 is the court rejection of this applicant assertion about prior Board evidence. Paragraphs 46 and 48-50 explicitly condition that conclusion on the evidence not being submitted in PRRA. Preserve holding/current_court and add the neighboring exact non-submission qualification to avoid a blanket duty-free rule.'),
 ('at-3820d6c51502d2177b73a081','Paragraph 46 draws the court consequence of failure to discharge this applicant burden. Preserve holding and scoped claim, record the because burden-failure condition and the not-submitted-evidence limit; paragraphs 42-50 establish the actual evidentiary record.'),
 ('at-531abd531d3559d2b6f298ca','Paragraph 18 quotes section 15 of the Regulations; the following French text confirms notice within 60 days and reasons if denial. Isolate quoted legislative text, use legislature attribution rather than undifferentiated current-court voice, and record section-29-transfer, denial, and 60-day witnesses. Keep statutory_hook; this is not a court-created unconditional disclosure duty.'),
 ('at-dc762fc78fb3970f9e23f864','Paragraph 157 expressly says In my view and sets minimum disclosure for this interview. Preserve procedural_rule/current_court but scope claim to the interview and documents likely to be used, record the missing-prior-testimony condition for the factual report and its relevant-information/intended-questioning limit. Remove the following report heading. This canonical target is not among the 157 missing IDs.'),
]

def main():
    before=scan_attribution_risks();items=[x for x in before['items'] if x['status']=='pending_model_review']
    if len(items)!=9 or [x['target_id'] for x in items]!=[x[0] for x in DECISIONS]:raise RuntimeError('Fixed final-nine queue changed')
    saved={str(p):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews') for p in (ROOT/folder).rglob('*.json')}
    prior=load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
    previous_s01=copy.deepcopy(next(x for x in registry()['findings'] if x['finding_id']=='P09-S01'))
    missing={x['case_id']:set(x['missing_target_ids']) for x in prior['cases']}
    reviewer={'source_type':'model','reviewer_id':'p09-r3-final9-gpt-6.1-sol','model':'gpt-6.1-sol'};results=[]
    for position,(item,(_,reason)) in enumerate(zip(items,DECISIONS),41):
        if item['target_id'] in missing[item['case_id']]:raise RuntimeError('missing target outside scope')
        packet,source,_=dependencies(ROOT,item['case_id']) # open_source; locked raw UTF-8/CRLF
        task=next(x for x in packet['tasks'] if x['target_id']==item['target_id'])
        a,b=task['target_span']['start_char'],task['target_span']['end_char']
        def span(start,end):return exact_span(source,item['case_id'],item['source_hash'],start,end)
        def witness(text,start=a,end=b):
            offset=source.index(text,start,end);return span(offset,offset+len(text))
        def attribution(w,speaker='current_court'):return {'role':'proposition','speaker':speaker,'evidence_span':w}
        target=span(a,b)
        context=span(max(0,a-1000),min(len(source),b+(2000 if position in (43,44) else 1000)))
        proposal=load_json(ROOT/'model_proposals'/item['case_id']/(item['proposal_id']+'.json'))
        replacement=copy.deepcopy(next(x for x in proposal['target_reviews'] if x['target_id']==item['target_id']))
        au=next(x for x in replacement['authority_units'] if x['au_id']==item['au_id'])
        au['provenance']={'source_type':'model','producer_id':'model:gpt-6.1-sol','prompt_version':'p09-r3-source-review-v1'}
        if position==41:
            start=source.index('since the PRRA officer concluded',a,b);end=source.index(', he was not obliged',start,b)
            au['condition_spans']=[span(start,end)]
        elif position==42:
            au['condition_spans']=[witness('He was the person who failed to file any evidence in support of his PRRA application.')]
        elif position in (43,44):
            exception_start=source.index('if the Minister decides on the basis of the factors set out in section 97 of the Act',b,context['end_char'])
            exception_end=source.index('(b) the application is rejected.',exception_start,context['end_char'])+len('(b) the application is rejected.')
            exception=span(exception_start,exception_end)
            if position==43:
                au['claim_text']='The court places this Article 1F-excluded applicant within paragraph 112(3)(c) and describes paragraph 113(d) special assessment for subsection 112(3) applicants; written assessments remain subject to subsection 172(4), which dispenses with them and rejects the application when the applicant is not described in section 97.'
                start=source.index('persons described in one of the paragraphs of subsection 112(3)',a,b)
                au['condition_spans']=[span(start,start+len('persons described in one of the paragraphs of subsection 112(3)'))]
            else:
                end=source.index('when he submits',a,b);court=span(a,end)
                au.update(kind='holding',claim_text='The court found that this applicant reliance on the subsection 172(2) written assessment ignored subsection 172(4), including its exception for applicants not described in section 97.',attributions=[attribution(court)])
            au['exception_spans']=[exception]
        elif position==45:
            court=witness('It was up to Mr. Bayavuge to submit these facts in evidence to the PRRA officer.')
            au.update(claim_text='Mr. Bayavuge had to submit his refugee-claim facts in evidence to the PRRA officer.',evidence_spans=[court],attributions=[attribution(court)])
        elif position==46:
            qualification=witness('because he did not submit this evidence in support of his PRRA application.',b,context['end_char'])
            au['condition_spans']=[qualification]
            au['claim_text']='In this PRRA application, the court held the officer need not refer to facts submitted for the earlier refugee claim where the applicant had not submitted that evidence in support of PRRA.'
        elif position==47:
            au['condition_spans']=[witness('because he obviously did not discharge his burden of proof.')]
            au['limit_spans']=[witness('the evidence which was not submitted by Mr. Bayavuge in support of his PRRA application.')]
        elif position==48:
            start=source.index('"15. Where an inmate',a,b);end=source.index('if the decision is to deny the request.',start,b)+len('if the decision is to deny the request.')
            quoted=span(start,end)
            au.update(claim_text='Quoted regulation 15 requires written notice of the decision on a section 29 inmate transfer request within 60 days after submission, including reasons if the request is denied.',evidence_spans=[quoted],attributions=[attribution(quoted,'legislature')],condition_spans=[witness('Where an inmate submits a request for a transfer referred to in section 29 of the Act'),witness('if the decision is to deny the request.')],limit_spans=[witness('within 60 days after the submission of the request')])
        elif position==49:
            end=source.index('Revised factual report dated April 29, 2010',a,b);court=span(a,end)
            au.update(claim_text='For the April 27, 2010 interview, the court required minimum prior disclosure of documentary evidence likely to be used; because prior witness testimony had not been provided, the factual report was included only to the extent of relevant information on which the investigator intended to question the applicant.',evidence_spans=[court],attributions=[attribution(court)],condition_spans=[witness('documentary evidence likely to be used in the interview'),witness("since the summary or the full content of Ms. Cousineau's prior testimony had not been provided")],limit_spans=[witness('to the extent that it contained relevant information in respect of which the investigator had the intention of questioning the applicant.')])
        replacement['notes']=replacement.get('notes',[])+[reason]
        trace=replacement['review_trace'];replacement['review_trace']=model_review_trace(task,source,item['source_hash'],replacement)
        for k in ('region_id','region_fingerprint'):replacement['review_trace'][k]=trace[k]
        fid=f'P09-R3-{position:02d}';aid=f'p09-r3-final9-{position:02d}-gpt61sol-v1'
        reg=registry()
        if any(x['finding_id']==fid for x in reg['findings']):raise RuntimeError('finding already exists')
        reg['findings'].append({'finding_id':fid,'severity':'moderate','status':'amended_pending_independent_audit','case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'proposal_id':item['proposal_id'],'proposal_sha256':item['proposal_sha256'],'error_types':['claim_attribution_or_qualification_witness'],'evidence_span':target,'reason':reason})
        atomic_write(ROOT/'semantic_defect_registry.json',reg)
        amendment={'artifact_type':'AUModelAmendment','schema_version':'au-model-amendment-v1','amendment_id':aid,'finding_id':fid,'supersedes_proposal_id':item['proposal_id'],'supersedes_proposal_sha256':item['proposal_sha256'],'case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'reviewer':reviewer,'reason':reason,'replacement_review':replacement,'context_spans':[context],'status':'model_reviewed_pending_independent_audit'}
        checkpoint_amendment(amendment)
        rid=f'p09-r3-final9-{position:02d}-gpt61sol-v1';review={k:item[k] for k in ('proposal_id','proposal_sha256','case_id','source_hash','target_id','au_id')}
        review.update(artifact_type='Plan09AttributionRiskReview',review_id=rid,reviewer=reviewer,outcome='amendment',reason=reason,target_span=target,context_spans=[context],amendment_id=aid,semantic_gold=False)
        checks=checkpoint_risk_review(review);validate_risk_review(load_json(ROOT/'risk_reviews'/(rid+'.json')))
        results.append({**checks,'queue_position':position,'case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'proposal_sha256':item['proposal_sha256'],'target_offsets':[a,b],'review_ref':'risk_reviews/'+rid+'.json','amendment_id':aid,'outcome':'amendment','reason':reason})
        print(f'PASS position={position} outcome=amendment target={item["target_id"]}',flush=True)
    assert all(digest(path)==sha for path,sha in saved.items()),'immutable historical bytes changed'
    assert previous_s01==next(x for x in registry()['findings'] if x['finding_id']=='P09-S01')
    queue=scan_attribution_risks();progress=build_progress(ROOT,prior['blocker'])
    assert queue==load_json(ROOT/'attribution_risk_queue.json') and queue['pending_model_review_count']==0
    assert len(risk_review_heads())==49
    assert progress==load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
    assert [(x['case_id'],x['missing_target_ids']) for x in progress['cases']]==[(x['case_id'],x['missing_target_ids']) for x in prior['cases']]
    reviews=[r for p in effective_proposals() for r in p['target_reviews']]
    counts={'authority_units':sum(len(r['authority_units']) for r in reviews),'hard_negatives':sum(r['hard_negative'] is not None for r in reviews),'unresolved':sum(r['model_outcome']=='unresolved' for r in reviews)}
    assert counts=={'authority_units':97,'hard_negatives':113,'unresolved':2}
    report={'artifact_type':'Plan09R3FinalNineValidation','model':'gpt-6.1-sol','semantic_gold':False,'semantic_pass':False,'independent_acceptance':False,'plan10_allowed':False,'review_count':9,'pending_before':9,'pending_after':0,'total_risk_items':49,'original_proposals_unchanged':True,'previous_history_unchanged':True,'missing_ids_unchanged':True,'p09_s01_registry_unchanged':True,'reviewed_target_count':progress['reviewed_target_count'],'missing_target_count':progress['missing_target_count'],'effective_counts':counts,'results':results}
    atomic_write(ROOT/'remediation_r3_final9_validation.json',report)
    print('PASS final_batch=9 queue=49_reviewed/0_pending effective=97/113/2 coverage=212/369 history=unchanged missing=157 S01=open Plan10=false')

if __name__=='__main__':main()
