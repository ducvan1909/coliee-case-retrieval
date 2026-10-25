"""Fixed source-reviewed second R3 batch; model-only, sequential checkpoints."""
import copy
from .au_gold.core import atomic_write, exact_span, load_json, model_review_trace
from .au_gold.progress import build_progress
from .au_gold.remediation import ROOT, checkpoint_amendment, checkpoint_risk_review, dependencies, digest, effective_proposals, registry, scan_attribution_risks, validate_risk_review

# Explicit decisions made after raw target + neighboring context review.
DECISIONS = [
 ('at-a5b5b0fdf3bab9574aa4429e','keep','Paragraph 26 is the current court assessment: However contrasts state efforts with the required effectiveness of protection. Paragraphs 25 and 27 establish this as reasoning in the state-protection review, not Board speech. The claim is faithful and the applied holding can be retained.'),
 ('at-08bf65c4ca25403730d5353c','amendment','Paragraph 4 first expressly finds failure to consider a letter, then quotes the officer. Claim is supported, but the whole-target attribution witness crosses the speaker boundary. Narrow proposition evidence and current-court witness to the first sentence; paragraphs 3 and 5 confirm the court finding.'),
 ('at-fad288640dd0c7aa6b551320','keep','Paragraph 6 expressly calls the officer finding unreasonable and simply wrong. Paragraph 5 supplies the brother letter and paragraph 7 changes topic. Officer/counsel mentions do not make the extracted court criticism their speech.'),
 ('at-5522df4fca96eee9c7176c4c','amendment','Paragraph 17 finds this officer treatment of this applicant charges erroneous and sufficient for this judicial review. Preserve holding/current_court, but scope the claim to this case instead of a general rule that any treatment error necessarily allows review.'),
 ('at-6fd1350b5e4ed36850040c15','amendment','Paragraph 3 explicitly begins In this case and announces this application will be allowed. Preserve holding/current_court, but make the H&C application-specific scope explicit rather than generalize the disposition.'),
 ('at-79ddc136c68ac1dccc949df4','amendment','Paragraph 12 appellate quotation speaks of withdrawn or dismissed charges, not pending charges. Following court text adopts that law and extends its reasoning to H&C. Correct the claim scope and record the no-criminality-alone limit and separate adopted/quoted attribution witnesses. Paragraph 14 confirms pending charges may be considered subject to procedural fairness.'),
 ('at-81ed7da8dd8cb3dab2bdd33e','amendment','Paragraph 15 applies the cited decision to this applicant and officer, including the qualifier does not appear to have attempted. It is a case-specific finding supporting paragraph 17, not a generalized fact-pattern rule. Preserve that qualifier and set holding with a court-comparison witness after the initial officer factual report.'),
 ('at-d1a9498ecd408d28317aa793','amendment','Paragraph 16 rejects the respondent submission and explicitly makes the current court inference In my view. The following appellate quotation is supporting authority. Scope claim and evidence to this decision and narrow the attribution witness so the nested quotation is not indiscriminately labelled current-court speech.'),
 ('at-f4a073144323210976dace57','amendment','Paragraph 14 rejects a blanket ban on considering pending charges and adopts procedural-fairness boundaries illustrated by a quoted decision. Retain procedural_rule, explicitly preserve permitted consideration and record a limit plus separate current-court adoption and cited-court underlying-facts/opportunity-to-respond witnesses.'),
 ('at-085b9017aac39b55a1c66d99','amendment','Paragraph 14 is the court interpretation of section 163, not party speech. Preserve statutory_hook and the supported claim, but record the late-application condition and explicit absence of a PRRA decision-time restriction; paragraphs 11-15 explain the timeline.'),
]

def main():
    before=scan_attribution_risks()
    items=[x for x in before['items'] if x['status']=='pending_model_review'][:10]
    if [x['target_id'] for x in items]!=[x[0] for x in DECISIONS] or before['pending_model_review_count']!=39:
        raise RuntimeError('Fixed second-ten queue changed; do not replay or substitute targets')
    originals={str(p):digest(p) for p in (ROOT/'model_proposals').rglob('*.json')}
    old_reviews={str(p):digest(p) for p in (ROOT/'risk_reviews').glob('*.json')}
    previous_progress=load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
    reviewer={'source_type':'model','reviewer_id':'p09-r3-second10-gpt-6.1-sol','model':'gpt-6.1-sol'}
    results=[]
    for position,(item,(_,outcome,reason)) in enumerate(zip(items,DECISIONS),11):
        packet,source,_=dependencies(ROOT,item['case_id'])
        task=next(x for x in packet['tasks'] if x['target_id']==item['target_id'])
        a,b=task['target_span']['start_char'],task['target_span']['end_char']
        target=exact_span(source,item['case_id'],item['source_hash'],a,b)
        context=exact_span(source,item['case_id'],item['source_hash'],max(0,a-850),min(len(source),b+850))
        def witness(text):
            start=source.index(text,a,b)
            return exact_span(source,item['case_id'],item['source_hash'],start,start+len(text))
        def attribution(span,speaker='current_court',role='proposition'):
            return {'role':role,'speaker':speaker,'evidence_span':span}
        aid=None
        if outcome!='keep':
            proposal=load_json(ROOT/'model_proposals'/item['case_id']/(item['proposal_id']+'.json'))
            replacement=copy.deepcopy(next(r for r in proposal['target_reviews'] if r['target_id']==item['target_id']))
            au=next(x for x in replacement['authority_units'] if x['au_id']==item['au_id'])
            au['provenance']={'source_type':'model','producer_id':'model:gpt-6.1-sol','prompt_version':'p09-r3-source-review-v1'}
            if position==12:
                span=witness("I find that the officer failed to consider one of two letters submitted by the applicant's brother.")
                au.update(evidence_spans=[span],attributions=[attribution(span)])
            elif position==14:
                au['claim_text']='In this case, the court found the officer treatment of the applicant pending criminal charges erroneous; that error alone was sufficient to allow this application for judicial review.'
            elif position==15:
                au['claim_text']='In this H&C judicial review, the court allowed the application because the officer failed to consider evidence and considered irrelevant facts.'
            elif position==16:
                au['claim_text']='Evidence surrounding withdrawn or dismissed charges may be considered at an immigration hearing, but such charges alone cannot evidence criminality; the court adopts this reasoning for H&C decisions.'
                quoted=witness("The jurisprudence of this Court indicates that evidence surrounding withdrawn or dismissed charges can be taken into consideration at an immigration hearing. However, such charges cannot be used, in and of themselves, as evidence of an individual's criminality")
                tail=source.index(' is an accurate statement of the law.',a,b)
                adopted=exact_span(source,item['case_id'],item['source_hash'],source.rfind('<FRAGMENT_SUPPRESSED>',a,tail),b)
                au['attributions']=[attribution(adopted),attribution(quoted,'cited_court','quoted_proposition')]
                au['limit_spans']=[witness("such charges cannot be used, in and of themselves, as evidence of an individual's criminality")]
            elif position==17:
                start=source.index('parallels the applicant',a,b)
                court=exact_span(source,item['case_id'],item['source_hash'],start,b)
                au.update(kind='holding',claim_text='In applying the cited decision to this applicant, the court found the officer did not appear to have attempted to ascertain the underlying facts, made no attempt to determine conviction or acquittal, and discounted supporting letters because of the charges.',attributions=[attribution(court)])
            elif position==18:
                start=source.index('In my view,',a,b);end=source.index('As stated at para.',start,b)
                court=exact_span(source,item['case_id'],item['source_hash'],start,end)
                au.update(claim_text='In this decision, the court inferred from the officer reference to the charges that they were at least a factor considered, rejecting the respondent contrary submission.',evidence_spans=[court],attributions=[attribution(court)])
            elif position==19:
                adopted=witness('The decision in <FRAGMENT_SUPPRESSED> does not stand for the proposition that officers may not consider criminal charges; rather, it defines the boundaries of a procedurally fair consideration of charges.')
                quoted=witness('the Officer made no attempt to ascertain the underlying facts and circumstances of the charges, and denied the applicants an opportunity to respond.')
                au['claim_text']='H&C officers may consider pending criminal charges, but consideration must remain procedurally fair; the adopted decision condemns reliance on outstanding charges without ascertaining underlying facts and circumstances or allowing a response.'
                au['attributions']=[attribution(adopted),attribution(quoted,'cited_court','quoted_proposition')]
                au['limit_spans']=[adopted]
            elif position==20:
                au['condition_spans']=[witness('because Mr. Bayavuge submitted his application after the expiry of the time limit of 15 days following the receipt of a notice to submit his application')]
                au['limit_spans']=[witness('This provision does not mention any restriction as to how much time a PRRA officer may take to render a decision.')]
            replacement['notes']=replacement.get('notes',[])+[reason]
            old_trace=replacement['review_trace']
            replacement['review_trace']=model_review_trace(task,source,item['source_hash'],replacement)
            for k in ('region_id','region_fingerprint'):replacement['review_trace'][k]=old_trace[k]
            fid=f'P09-R3-{position:02d}';aid=f'p09-r3-second10-{position:02d}-gpt61sol-v1'
            reg=registry()
            if any(x['finding_id']==fid for x in reg['findings']):raise RuntimeError('finding already exists')
            reg['findings'].append({'finding_id':fid,'severity':'moderate','status':'amended_pending_independent_audit','case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'proposal_id':item['proposal_id'],'proposal_sha256':item['proposal_sha256'],'error_types':['claim_scope_or_field_witness'],'evidence_span':target,'reason':reason})
            atomic_write(ROOT/'semantic_defect_registry.json',reg)
            amendment={'artifact_type':'AUModelAmendment','schema_version':'au-model-amendment-v1','amendment_id':aid,'finding_id':fid,'supersedes_proposal_id':item['proposal_id'],'supersedes_proposal_sha256':item['proposal_sha256'],'case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'reviewer':reviewer,'reason':reason,'replacement_review':replacement,'context_spans':[context],'status':'model_reviewed_pending_independent_audit'}
            checkpoint_amendment(amendment)
        review={k:item[k] for k in ('proposal_id','proposal_sha256','case_id','source_hash','target_id','au_id')}
        rid=f'p09-r3-second10-{position:02d}-gpt61sol-v1'
        review.update(artifact_type='Plan09AttributionRiskReview',review_id=rid,reviewer=reviewer,outcome=outcome,reason=reason,target_span=target,context_spans=[context],amendment_id=aid,semantic_gold=False)
        checks=checkpoint_risk_review(review)
        validate_risk_review(load_json(ROOT/'risk_reviews'/(rid+'.json')))
        results.append({**checks,'queue_position':position,'case_id':item['case_id'],'target_id':item['target_id'],'proposal_sha256':item['proposal_sha256'],'source_hash':item['source_hash'],'target_offsets':[a,b],'review_ref':'risk_reviews/'+rid+'.json','amendment_id':aid,'outcome':outcome,'reason':reason})
        print(f'PASS position={position} outcome={outcome} target={item["target_id"]}',flush=True)
    assert originals=={str(p):digest(p) for p in (ROOT/'model_proposals').rglob('*.json')},'original proposal bytes changed'
    assert all(digest(p)==sha for p,sha in old_reviews.items()),'previous reviews changed'
    after=scan_attribution_risks();progress=build_progress(ROOT,previous_progress['blocker'])
    assert progress==load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
    assert after==load_json(ROOT/'attribution_risk_queue.json')
    assert after['pending_model_review_count']==29
    assert progress['cases'][-1]['missing_target_ids']==previous_progress['cases'][-1]['missing_target_ids']
    effective=effective_proposals()
    counts={'authority_units':sum(len(r['authority_units']) for p in effective for r in p['target_reviews']),'hard_negatives':sum(r['hard_negative'] is not None for p in effective for r in p['target_reviews']),'unresolved':sum(r['model_outcome']=='unresolved' for p in effective for r in p['target_reviews'])}
    assert counts=={'authority_units':97,'hard_negatives':112,'unresolved':3}
    report={'artifact_type':'Plan09R3SecondTenValidation','model':'gpt-6.1-sol','semantic_gold':False,'semantic_pass':False,'independent_audit_complete':False,'plan10_allowed':False,'review_count':10,'pending_before':39,'pending_after':29,'total_risk_items':49,'original_proposals_unchanged':True,'previous_reviews_unchanged':True,'missing_targets_unchanged':True,'reviewed_target_count':progress['reviewed_target_count'],'missing_target_count':progress['missing_target_count'],'effective_counts':counts,'results':results}
    atomic_write(ROOT/'remediation_r3_second10_validation.json',report)
    print('PASS second_batch=10 queue=20_reviewed/29_pending originals=unchanged effective=97/112/3 missing=157',flush=True)

if __name__=='__main__':main()
