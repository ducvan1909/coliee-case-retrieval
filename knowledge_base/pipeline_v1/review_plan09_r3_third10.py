"""Source-grounded model-only R3 review of fixed queue positions 21-30."""
import copy
from .au_gold.core import atomic_write, exact_span, load_json, model_review_trace
from .au_gold.progress import build_progress
from .au_gold.remediation import ROOT, checkpoint_amendment, checkpoint_risk_review, dependencies, digest, effective_proposals, registry, scan_attribution_risks, validate_risk_review

DECISIONS=[
 ('at-9647c642f34e461afed2bcd3','amendment','Paragraph 16 under PRRA OFFICER DECISION narrates the officer scope then quotes paragraph 112(3)(c). The quoted statutory proposition is eligible, but the entire officer report and statute should not be assigned undifferentiated current_court voice. Isolate the statutory quote and its exclusion condition; preserve statutory_hook.'),
 ('at-4f47ee824d830713909b5207','keep','Paragraph 57 is the current court case-specific conclusion that this officer properly considered the application. Paragraphs 54-56 explain missing evidence and paragraph 58 dismisses review. The officer is the object of the holding, not its speaker.'),
 ('at-18bd69bd7657d6f7040f6e4a','amendment','Paragraph 37 interprets what the Board actually decided for this family, contrasting sections 96 and 97. Paragraphs 35-38 establish the current court response to the applicant contention. This is a case-specific holding about the prior decision, not merely a statutory hook. Preserve claim and current-court attribution; record the family-recognition context.'),
 ('at-19cb3b2ba4ac3c000e7e80ea','keep','Paragraph 39 is the current court reading of this Board decision, following its rebuttal in paragraphs 36-38. Exclusion explains why the Board did not reach inclusion. Claim already retains that context and holding/current_court is supported; no party speech is promoted.'),
 ('at-1bdec346bae3fbd73ee645b0','amendment','Paragraph 40 introduces an officer quotation as a concession, then states the court section 97 distinction. Do not merge quoted officer opinion with court legal interpretation in a single proposition/witness. Narrow claim, evidence and court attribution to the latter distinction; record the not-persecution limit. Paragraph 41 applies it.'),
 ('at-55d68209bf19c9c985db1b0f','amendment','Paragraph 38 begins Therefore and rejects this applicant assertion about what the Board concluded. It is a case-specific holding, not a statutory_hook simply because section 97 is mentioned. Preserve the scoped claim and record the Board non-inclusion consideration as its qualification.'),
 ('at-eae6586b56aa73cb4d5ca550','amendment','Paragraph 2 states the section 97 scope for a PRRA applicant excluded under section 1F. Paragraph 3 explains the risk evidence required. Keep statutory_hook/current_court but add exact exclusion-condition and no-Convention-refugee-definition limit witnesses; do not generalize to every PRRA applicant.'),
 ('at-12a803f163fabfad29b3f956','amendment','Paragraph 53 draws this court conclusion from the absence of Board inclusion and personalized-risk findings. Paragraphs 50-52 explain the record; paragraphs 54-56 apply the resulting assessment. Set case-specific holding rather than citation-driven statutory_hook, and record its explicit because condition.'),
 ('at-363f52092d33564069b394ee','amendment','Paragraph 56 is the court conclusion on this protection application. Officer refers to the assessed decision-maker. Preserve holding and claim, and add the express no-evidence/no-submission/no-risk-details condition so rejection is not detached from its factual prerequisite.'),
 ('at-4adb5e627730e8e054bee5a7','keep','Paragraph 55 says the officer need not speculate about this applicant present risk. Paragraph 54 establishes the lack of evidence and even identified risk; paragraphs 56-58 explain rejection and dismissal. The claim remains applicant-specific and is court reasoning, not officer speech.'),
]

def main():
    before=scan_attribution_risks()
    items=[x for x in before['items'] if x['status']=='pending_model_review'][:10]
    if before['pending_model_review_count']!=29 or [x['target_id'] for x in items]!=[x[0] for x in DECISIONS]:
        raise RuntimeError('Fixed third-ten queue changed; do not substitute or replay targets')
    originals={str(p):digest(p) for p in (ROOT/'model_proposals').rglob('*.json')}
    old_reviews={str(p):digest(p) for p in (ROOT/'risk_reviews').glob('*.json')}
    prior=load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
    reviewer={'source_type':'model','reviewer_id':'p09-r3-third10-gpt-6.1-sol','model':'gpt-6.1-sol'}
    results=[]
    for position,(item,(_,outcome,reason)) in enumerate(zip(items,DECISIONS),21):
        packet,source,_=dependencies(ROOT,item['case_id']) # open_source; locked hash and raw CRLF
        task=next(x for x in packet['tasks'] if x['target_id']==item['target_id'])
        a,b=task['target_span']['start_char'],task['target_span']['end_char']
        def span(start,end):return exact_span(source,item['case_id'],item['source_hash'],start,end)
        def witness(text):
            start=source.index(text,a,b);return span(start,start+len(text))
        def attribution(w,speaker='current_court'):return {'role':'proposition','speaker':speaker,'evidence_span':w}
        target=span(a,b);context=span(max(0,a-850),min(len(source),b+850));aid=None
        if outcome!='keep':
            proposal=load_json(ROOT/'model_proposals'/item['case_id']/(item['proposal_id']+'.json'))
            replacement=copy.deepcopy(next(r for r in proposal['target_reviews'] if r['target_id']==item['target_id']))
            au=next(x for x in replacement['authority_units'] if x['au_id']==item['au_id'])
            au['provenance']={'source_type':'model','producer_id':'model:gpt-6.1-sol','prompt_version':'p09-r3-source-review-v1'}
            if position==21:
                quote=span(source.index('"(3)',a,b),b)
                au['claim_text']='Quoted paragraph 112(3)(c) provides that refugee protection may not result from an application for protection if the person made a refugee-protection claim rejected on the basis of section F of Article 1 of the Refugee Convention.'
                au.update(evidence_spans=[quote],attributions=[attribution(quote,'legislature')],condition_spans=[witness('made a claim to refugee protection that was rejected on the basis of section F of Article 1 of the Refugee Convention.')])
            elif position==23:
                au['kind']='holding'
                end=source.index(', the Board',a,b)
                au['condition_spans']=[span(a,end)]
            elif position==25:
                start=source.index('the fact is that according to section 97',a,b)
                end=source.index('persecution.',start,b)+len('persecution.')
                court=span(start,end)
                au.update(claim_text='The section 97 assessment concerns danger of torture, risk to life, or risk of cruel and unusual treatment or punishment, not risk of persecution.',evidence_spans=[court],attributions=[attribution(court)],limit_spans=[witness('and not if there is a risk of persecution.')])
            elif position==26:
                au['kind']='holding'
                au['limit_spans']=[witness("especially since the Board never considered the issue of Mr. Bayavuge's inclusion.")]
            elif position==27:
                start=source.index('made by a person',a,b)
                end=source.index(' is not assessed',start,b)
                au['condition_spans']=[span(start,end)]
                au['limit_spans']=[witness('is not assessed on the basis of the definition of "Convention refugee"')]
            elif position==28:
                au['kind']='holding'
                start=source.index('because no examination',a,b)
                end=source.index(', the PRRA officer had to',start,b)
                au['condition_spans']=[span(start,end)]
            elif position==29:
                au['condition_spans']=[witness('With no evidence submitted to him, no submissions made and no details adduced about the possible risk')]
            replacement['notes']=replacement.get('notes',[])+[reason]
            old_trace=replacement['review_trace']
            replacement['review_trace']=model_review_trace(task,source,item['source_hash'],replacement)
            for k in ('region_id','region_fingerprint'):replacement['review_trace'][k]=old_trace[k]
            fid=f'P09-R3-{position:02d}';aid=f'p09-r3-third10-{position:02d}-gpt61sol-v1'
            reg=registry()
            if any(x['finding_id']==fid for x in reg['findings']):raise RuntimeError('finding already exists')
            reg['findings'].append({'finding_id':fid,'severity':'moderate','status':'amended_pending_independent_audit','case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'proposal_id':item['proposal_id'],'proposal_sha256':item['proposal_sha256'],'error_types':['kind_attribution_or_field_witness'],'evidence_span':target,'reason':reason})
            atomic_write(ROOT/'semantic_defect_registry.json',reg)
            amendment={'artifact_type':'AUModelAmendment','schema_version':'au-model-amendment-v1','amendment_id':aid,'finding_id':fid,'supersedes_proposal_id':item['proposal_id'],'supersedes_proposal_sha256':item['proposal_sha256'],'case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'reviewer':reviewer,'reason':reason,'replacement_review':replacement,'context_spans':[context],'status':'model_reviewed_pending_independent_audit'}
            checkpoint_amendment(amendment)
        rid=f'p09-r3-third10-{position:02d}-gpt61sol-v1'
        review={k:item[k] for k in ('proposal_id','proposal_sha256','case_id','source_hash','target_id','au_id')}
        review.update(artifact_type='Plan09AttributionRiskReview',review_id=rid,reviewer=reviewer,outcome=outcome,reason=reason,target_span=target,context_spans=[context],amendment_id=aid,semantic_gold=False)
        checks=checkpoint_risk_review(review)
        validate_risk_review(load_json(ROOT/'risk_reviews'/(rid+'.json')))
        results.append({**checks,'queue_position':position,'case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'proposal_sha256':item['proposal_sha256'],'target_offsets':[a,b],'review_ref':'risk_reviews/'+rid+'.json','amendment_id':aid,'outcome':outcome,'reason':reason})
        print(f'PASS position={position} outcome={outcome} target={item["target_id"]}',flush=True)
    assert originals=={str(p):digest(p) for p in (ROOT/'model_proposals').rglob('*.json')},'original proposals changed'
    assert all(digest(p)==sha for p,sha in old_reviews.items()),'previous reviews changed'
    after=scan_attribution_risks();progress=build_progress(ROOT,prior['blocker'])
    assert after==load_json(ROOT/'attribution_risk_queue.json') and after['pending_model_review_count']==19
    assert progress==load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
    assert [(x['case_id'],x['missing_target_ids']) for x in progress['cases']]==[(x['case_id'],x['missing_target_ids']) for x in prior['cases']]
    reviews=[r for p in effective_proposals() for r in p['target_reviews']]
    counts={'authority_units':sum(len(r['authority_units']) for r in reviews),'hard_negatives':sum(r['hard_negative'] is not None for r in reviews),'unresolved':sum(r['model_outcome']=='unresolved' for r in reviews)}
    assert counts=={'authority_units':97,'hard_negatives':112,'unresolved':3}
    report={'artifact_type':'Plan09R3ThirdTenValidation','model':'gpt-6.1-sol','semantic_gold':False,'semantic_pass':False,'independent_audit_complete':False,'plan10_allowed':False,'review_count':10,'pending_before':29,'pending_after':19,'total_risk_items':49,'original_proposals_unchanged':True,'previous_reviews_unchanged':True,'missing_targets_unchanged':True,'reviewed_target_count':progress['reviewed_target_count'],'missing_target_count':progress['missing_target_count'],'effective_counts':counts,'results':results}
    atomic_write(ROOT/'remediation_r3_third10_validation.json',report)
    print('PASS third_batch=10 queue=30_reviewed/19_pending effective=97/112/3 coverage=212/369 originals=unchanged missing=157',flush=True)

if __name__=='__main__':main()
