"""Fixed queue positions 31-40; source-reviewed model-only decisions."""
import copy
from .au_gold.core import atomic_write,exact_span,load_json,model_review_trace
from .au_gold.progress import build_progress
from .au_gold.remediation import ROOT,amendment_heads,checkpoint_amendment,checkpoint_risk_review,dependencies,digest,effective_proposals,registry,scan_attribution_risks,validate_risk_review

DECISIONS=[
 ('at-726483a83077ee92addf3aff','amendment','Paragraph 28 explains the written-assessment process using the Protected Persons Manual; paragraphs 25-27 provide the negative-risk limit. Replace the copied whole manual holding with a scoped procedural rule, preserve the positive-risk condition, and separate court explanation from quoted manual voice.'),
 ('at-3f8c7b00587a03395a1070fa','unresolved','This pending queue target is P09-S01. Paragraph 34 expressly reports Bayavuge submission, followed by a court-response heading. Paragraphs 32-39 establish the speaker transition, but the target alone mixes party argument with a heading fragment. Preserve unresolved rather than revive the original party-as-court holding or force party_argument_only across the heading. Append to the existing amendment head; severe quarantine remains open pending independent resolution.'),
 ('at-286fc0f30a53d4bce2eeb5c3','amendment','Paragraph 20 states the judicial-review evidence-record rule, then appends an issue question about written assessment. A question is not a statutory proposition or holding. Keep only the affirmative procedural rule, narrow evidence/current-court witness and record its only-evidence-before-decision-maker limit.'),
 ('at-329c7590de0a0f2cb690f50c','amendment','Paragraph 18 under PRRA OFFICER DECISION reports why the officer rejected the application: missing specified risk and supporting evidence. The neighboring section turns to ISSUES and ANALYSIS only afterwards. This target is procedural history of the administrative decision, not a current-court holding. Record full-target procedural_history_only hard negative; do not import later court approval as this target voice.'),
 ('at-3afd82f9ffea744294fd4624','amendment','Paragraph 41 draws the court case-specific consequence of the Board not examining inclusion. The following line is a heading introducing missing evidence. Set holding, retain the no-inclusion condition and omit the next heading from claim/evidence; paragraphs 39-43 support the distinction.'),
 ('at-7544c78cf589f672a909022b','amendment','Paragraph 42 specifies the applicant evidentiary obligation in this PRRA assessment, with the burden rule explained in paragraph 43. Treat it as procedural_rule rather than a statutory hook inferred from a section number; retain current-court attribution and the section-97-risk purpose condition.'),
 ('at-4b45893be1af385679d8c79a','amendment','Paragraph 50 is the current court applicant-specific onus finding, not officer speech. The duty to resubmit evidence is expressly conditional on wanting prior Board evidence considered in PRRA; record that If condition without broadening the claim. Paragraphs 48-51 establish the missing submission context.'),
 ('at-a323323de17b57ed9f104642','keep','Paragraph 51 expressly states the current court conclusion that the officer need not search this applicant immigration file. Paragraphs 49-50 explain the unsubmitted evidence; paragraph 52 distinguishes awareness of the Board decision from evidence of personalized section 97 risk. Claim remains case-specific and holding/current_court is supported.'),
 ('at-ba8ab2cc049d5dbf250b0516','amendment','Paragraph 49 is court reasoning that this applicant could not demand consideration of evidence not submitted in PRRA, with no proof it was otherwise in the immigration file. Preserve holding/current_court and record the submission condition and file-availability qualification explicitly.'),
 ('at-3d0be6036210c5ff292aecc6','amendment','Paragraph 31 concludes no error or court intervention on written assessment, followed by the next issue heading. Set holding, narrow claim/evidence to the disposition on this point, remove the issue question and preserve the negative-risk premise from paragraph 30 as a source-grounded condition witness.'),
]

def main():
    before=scan_attribution_risks();items=[x for x in before['items'] if x['status']=='pending_model_review'][:10]
    if before['pending_model_review_count']!=19 or [x['target_id'] for x in items]!=[x[0] for x in DECISIONS]:raise RuntimeError('Fixed fourth batch changed')
    saved={str(p):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews') for p in (ROOT/folder).rglob('*.json')}
    prior=load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
    prior_s01=copy.deepcopy(next(x for x in registry()['findings'] if x['finding_id']=='P09-S01'))
    reviewer={'source_type':'model','reviewer_id':'p09-r3-fourth10-gpt-6.1-sol','model':'gpt-6.1-sol'};results=[]
    for position,(item,(_,outcome,reason)) in enumerate(zip(items,DECISIONS),31):
        packet,source,_=dependencies(ROOT,item['case_id']) # open_source UTF-8; no normalization
        task=next(x for x in packet['tasks'] if x['target_id']==item['target_id'])
        a,b=task['target_span']['start_char'],task['target_span']['end_char']
        def span(start,end):return exact_span(source,item['case_id'],item['source_hash'],start,end)
        def witness(text):
            start=source.index(text,a,b);return span(start,start+len(text))
        def attribution(w,speaker='current_court',role='proposition'):return {'role':role,'speaker':speaker,'evidence_span':w}
        target=span(a,b);context=span(max(0,a-850),min(len(source),b+850));aid=None
        if outcome!='keep':
            proposal=load_json(ROOT/'model_proposals'/item['case_id']/(item['proposal_id']+'.json'))
            old_head=next((x for x in amendment_heads() if x['supersedes_proposal_id']==item['proposal_id'] and x['target_id']==item['target_id']),None)
            replacement=copy.deepcopy(old_head['replacement_review'] if old_head else next(r for r in proposal['target_reviews'] if r['target_id']==item['target_id']))
            provenance={'source_type':'model','producer_id':'model:gpt-6.1-sol','prompt_version':'p09-r3-source-review-v1'}
            if position==32:
                replacement.update(authority_units=[],hard_negative=None,model_outcome='unresolved',unresolved_reasons=[reason])
            elif position==34:
                replacement.update(authority_units=[],model_outcome='hard_negative',unresolved_reasons=[],hard_negative={'reason':'procedural_history_only','reviewed_span':target,'provenance':provenance,'notes':[reason]})
            else:
                au=next(x for x in replacement['authority_units'] if x['au_id']==item['au_id']);au['provenance']=provenance
                if position==31:
                    boundary=source.index('"The PRRA officer must follow',a,b)
                    court=span(a,boundary);manual=span(boundary,b)
                    au.update(kind='procedural_rule',claim_text='For the PRRA process described here, a positive risk assessment triggers the paragraph 113(d) assessment and written assessment; the quoted manual directs rejection where the risk assessment is negative.',evidence_spans=[court,manual],attributions=[attribution(court),attribution(manual,'administrative_manual','quoted_process')],condition_spans=[witness('it is only when the PRRA officer concludes that the risk assessment is positive')],limit_spans=[witness('Should the risk assessment be negative, the PRRA officer will make the final decision to reject the application for protection.')])
                elif position==33:
                    text='It is well established in case law that judicial review of a decision should proceed only on the basis of the evidence before the decision-maker.'
                    court=witness(text)
                    au.update(kind='procedural_rule',claim_text='Judicial review of a decision proceeds only on the evidence before the decision-maker.',evidence_spans=[court],attributions=[attribution(court)],limit_spans=[witness('only on the basis of the evidence before the decision-maker.')])
                elif position==35:
                    end=source.index('The PRRA officer had no submission or evidence before him',a,b)
                    court=span(a,end)
                    au.update(kind='holding',claim_text='Because the Board did not rule on this applicant inclusion, the PRRA officer had to assess whether he met section 97 requirements.',evidence_spans=[court],attributions=[attribution(court)],condition_spans=[witness("Because the Board did not rule on the issue of Mr. Bayavuge's inclusion")])
                elif position==36:
                    au['kind']='procedural_rule';end=source.index(', Mr. Bayavuge had to',a,b)
                    au['condition_spans']=[span(a,end)]
                elif position==37:
                    au['condition_spans']=[witness('If Mr. Bayavuge wanted the PRRA officer to consider the evidence he submitted to the Board')]
                elif position==39:
                    au['condition_spans']=[witness('because he did not submit this evidence in support of his PRRA application.')]
                    au['limit_spans']=[witness('Nothing shows that this evidence was in the file Citizenship and Immigration Canada had concerning Mr. Bayavuge.')]
                elif position==40:
                    end=source.index('2. Could the PRRA officer',a,b);court=span(a,end)
                    start=source.index('since the PRRA officer concluded',max(0,a-850),a);finish=source.index(', he was not obliged',start,a)
                    condition=span(start,finish)
                    au.update(kind='holding',claim_text='In this case, the PRRA officer did not err by omitting the subsection 172(2) written assessment, and court intervention was not warranted on that point.',evidence_spans=[court],attributions=[attribution(court)],condition_spans=[condition])
                replacement.update(model_outcome='positive',hard_negative=None,unresolved_reasons=[])
            replacement['notes']=replacement.get('notes',[])+[reason]
            trace=replacement['review_trace'];replacement['review_trace']=model_review_trace(task,source,item['source_hash'],replacement)
            for k in ('region_id','region_fingerprint'):replacement['review_trace'][k]=trace[k]
            fid='P09-S01' if position==32 else f'P09-R3-{position:02d}'
            aid=f'p09-r3-fourth10-{position:02d}-gpt61sol-v1'
            if position!=32:
                reg=registry()
                if any(x['finding_id']==fid for x in reg['findings']):raise RuntimeError('finding already exists')
                reg['findings'].append({'finding_id':fid,'severity':'moderate','status':'amended_pending_independent_audit','case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'proposal_id':item['proposal_id'],'proposal_sha256':item['proposal_sha256'],'error_types':['kind_attribution_or_field_witness'],'evidence_span':target,'reason':reason})
                atomic_write(ROOT/'semantic_defect_registry.json',reg)
            amendment={'artifact_type':'AUModelAmendment','schema_version':'au-model-amendment-v1','amendment_id':aid,'finding_id':fid,'supersedes_proposal_id':item['proposal_id'],'supersedes_proposal_sha256':item['proposal_sha256'],'case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'reviewer':reviewer,'reason':reason,'replacement_review':replacement,'context_spans':[context],'status':'model_reviewed_pending_independent_audit'}
            if old_head:
                amendment.update(schema_version='au-model-amendment-v2',supersedes_amendment_id=old_head['amendment_id'],supersedes_amendment_sha256=digest(ROOT/'model_amendments'/(old_head['amendment_id']+'.json')))
            checkpoint_amendment(amendment)
        rid=f'p09-r3-fourth10-{position:02d}-gpt61sol-v1';review={k:item[k] for k in ('proposal_id','proposal_sha256','case_id','source_hash','target_id','au_id')}
        review.update(artifact_type='Plan09AttributionRiskReview',review_id=rid,reviewer=reviewer,outcome=outcome,reason=reason,target_span=target,context_spans=[context],amendment_id=aid,semantic_gold=False)
        checks=checkpoint_risk_review(review);validate_risk_review(load_json(ROOT/'risk_reviews'/(rid+'.json')))
        results.append({**checks,'queue_position':position,'case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'proposal_sha256':item['proposal_sha256'],'target_offsets':[a,b],'review_ref':'risk_reviews/'+rid+'.json','amendment_id':aid,'outcome':outcome,'reason':reason})
        print(f'PASS position={position} outcome={outcome} target={item["target_id"]}',flush=True)
    assert all(digest(path)==sha for path,sha in saved.items()),'immutable historical bytes changed'
    assert prior_s01==next(x for x in registry()['findings'] if x['finding_id']=='P09-S01')
    queue=scan_attribution_risks();progress=build_progress(ROOT,prior['blocker'])
    assert queue==load_json(ROOT/'attribution_risk_queue.json') and queue['pending_model_review_count']==9
    assert progress==load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
    assert [(x['case_id'],x['missing_target_ids']) for x in progress['cases']]==[(x['case_id'],x['missing_target_ids']) for x in prior['cases']]
    reviews=[r for p in effective_proposals() for r in p['target_reviews']]
    counts={'authority_units':sum(len(r['authority_units']) for r in reviews),'hard_negatives':sum(r['hard_negative'] is not None for r in reviews),'unresolved':sum(r['model_outcome']=='unresolved' for r in reviews)}
    assert counts=={'authority_units':97,'hard_negatives':113,'unresolved':2}
    report={'artifact_type':'Plan09R3FourthTenValidation','model':'gpt-6.1-sol','semantic_gold':False,'semantic_pass':False,'independent_audit_complete':False,'plan10_allowed':False,'review_count':10,'pending_before':19,'pending_after':9,'total_risk_items':49,'original_proposals_unchanged':True,'previous_heads_history_unchanged':True,'missing_targets_unchanged':True,'p09_s01_registry_unchanged':True,'reviewed_target_count':progress['reviewed_target_count'],'missing_target_count':progress['missing_target_count'],'effective_counts':counts,'results':results}
    atomic_write(ROOT/'remediation_r3_fourth10_validation.json',report)
    print('PASS fourth_batch=10 queue=40_reviewed/9_pending effective=97/113/2 originals=unchanged prior_history=unchanged missing=157 S01=open')

if __name__=='__main__':main()
