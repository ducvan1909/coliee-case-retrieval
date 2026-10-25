"""Append only the two requested model revisions; acceptance stays pending."""
import copy
from .au_gold.core import atomic_write,exact_span,load_json,model_review_trace
from .au_gold.progress import build_progress
from .au_gold.remediation import ROOT,amendment_heads,checkpoint_amendment,checkpoint_risk_review_revision,dependencies,digest,effective_proposals,registry,scan_attribution_risks,validate_risk_review

def main():
    pipeline=ROOT.parents[1];audit_path=pipeline/'evaluation/reports/plan09_r3_positions_11_49_independent_semantic_audit.json';audit=load_json(audit_path)
    if audit['snapshot']['queue_sha256']!=digest(ROOT/'attribution_risk_queue.json'):raise RuntimeError('audit snapshot changed')
    queue=scan_attribution_risks()
    if queue['pending_model_review_count']!=0:raise RuntimeError('queue no longer fully reviewed')
    saved={str(p):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews') for p in (ROOT/folder).rglob('*.json')}
    prior=load_json(pipeline/'reports/plan09_model_silver_progress.latest.json')
    reviewer={'source_type':'model','reviewer_id':'p09-r3-audit11-32-gpt-6.1-sol','model':'gpt-6.1-sol'};results=[]
    for position in (11,32):
        item=queue['items'][position-1];request=next(x for x in audit['mandatory_revisions'] if x['position']==position)
        if (item['case_id'],item['target_id'])!=(request['case_id'],request['target_id']):raise RuntimeError('audit identity mismatch')
        old_review_path=ROOT/item['review_ref'];old_review=load_json(old_review_path)
        old_amendment=next((x for x in amendment_heads() if x['supersedes_proposal_id']==item['proposal_id'] and x['target_id']==item['target_id']),None)
        packet,source,_=dependencies(ROOT,item['case_id'])
        task=next(x for x in packet['tasks'] if x['target_id']==item['target_id']);a,b=task['target_span']['start_char'],task['target_span']['end_char']
        def span(start,end):return exact_span(source,item['case_id'],item['source_hash'],start,end)
        original=load_json(ROOT/'model_proposals'/item['case_id']/(item['proposal_id']+'.json'))
        original_review=next(x for x in original['target_reviews'] if x['target_id']==item['target_id'])
        replacement=copy.deepcopy(old_amendment['replacement_review'] if old_amendment else original_review)
        aid=f'p09-r3-audit-11-32-{position:02d}-gpt61sol-v2'
        contexts=[span(max(0,a-850),min(len(source),b+850))]
        if position==11:
            reason='Independent audit position 11 accepts the claim, current-court attribution and exact evidence, but identifies the proposition as an analytical requirement rather than case disposition. Change only kind to procedural_rule (plus explicit model provenance and trace); preserve claim, witnesses and all qualifications.'
            au=replacement['authority_units'][0]
            accepted_fields={k:copy.deepcopy(au[k]) for k in ('claim_text','attributions','evidence_spans','condition_spans','exception_spans','limit_spans')}
            au['kind']='procedural_rule'
            fid='P09-R3-AUDIT-11'
            reg=registry()
            if any(x['finding_id']==fid for x in reg['findings']):raise RuntimeError('revision already exists')
            reg['findings'].append({'finding_id':fid,'severity':'moderate','status':'pending_reaudit','case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'proposal_id':item['proposal_id'],'proposal_sha256':item['proposal_sha256'],'error_types':['wrong_kind'],'evidence_span':span(a,b),'reason':reason,'audit_ref':audit_path.relative_to(pipeline).as_posix(),'audit_sha256':digest(audit_path)})
            atomic_write(ROOT/'semantic_defect_registry.json',reg)
            assert all(au[k]==value for k,value in accepted_fields.items())
        else:
            reason='Independent audit position 32 supports a narrow final current-court holding in the standalone heading. Use only raw [11890,11945) as proposition/attribution evidence; paragraphs 35-39 clarify that the Board never decided this applicant return risks. Exclude all paragraph-34 party submission from proposition evidence. Final positive model correction remains pending independent re-audit, not accepted or closed.'
            heading=span(11890,11945)
            if heading['quote']!="The Board never ruled on Mr. Bayavuge's risks of return":raise RuntimeError('exact heading/source changed')
            supports=[span(start,end) for start,end in ((11953,12084),(12092,12474),(12482,12755),(12763,13024),(13032,13231))]
            contexts+=supports
            au=copy.deepcopy(original_review['authority_units'][0])
            au.update(claim_text=heading['quote'],kind='holding',evidence_spans=[heading],attributions=[{'role':'proposition','speaker':'current_court','evidence_span':heading}],condition_spans=[],exception_spans=[],limit_spans=[],cross_block_refs=supports,notes=[reason],uncertainty='low',unresolved_reasons=[])
            replacement.update(authority_units=[au],hard_negative=None,model_outcome='positive',unresolved_reasons=[])
            fid='P09-S01'
        au['provenance']={'source_type':'model','producer_id':'model:gpt-6.1-sol','prompt_version':'p09-r3-audit11-32-remediation-v1'}
        replacement['notes']=replacement.get('notes',[])+[reason]
        trace=replacement['review_trace'];replacement['review_trace']=model_review_trace(task,source,item['source_hash'],replacement)
        for k in ('region_id','region_fingerprint'):replacement['review_trace'][k]=trace[k]
        amendment={'artifact_type':'AUModelAmendment','schema_version':'au-model-amendment-v1','amendment_id':aid,'finding_id':fid,'supersedes_proposal_id':item['proposal_id'],'supersedes_proposal_sha256':item['proposal_sha256'],'case_id':item['case_id'],'target_id':item['target_id'],'source_hash':item['source_hash'],'reviewer':reviewer,'reason':reason,'replacement_review':replacement,'context_spans':contexts,'status':'model_reviewed_pending_independent_audit'}
        if old_amendment:
            amendment.update(schema_version='au-model-amendment-v2',supersedes_amendment_id=old_amendment['amendment_id'],supersedes_amendment_sha256=digest(ROOT/'model_amendments'/(old_amendment['amendment_id']+'.json')))
        checkpoint_amendment(amendment)
        if position==32:
            reg=registry();finding=next(x for x in reg['findings'] if x['finding_id']=='P09-S01')
            finding.update(status='pending_reaudit',proposed_resolution_amendment_id=aid,revision_request_audit_ref=audit_path.relative_to(pipeline).as_posix(),revision_request_audit_sha256=digest(audit_path))
            # Deliberately not resolution_amendment_id/independent acceptance or closed.
            atomic_write(ROOT/'semantic_defect_registry.json',reg)
        rid=f'p09-r3-audit-11-32-{position:02d}-gpt61sol-v2'
        review=copy.deepcopy(old_review)
        review.update(review_id=rid,reviewer=reviewer,outcome='amendment',reason=reason,amendment_id=aid,context_spans=contexts,supersedes_review_id=old_review['review_id'],supersedes_review_sha256=digest(old_review_path))
        checks=checkpoint_risk_review_revision(review)
        results.append({**checks,'position':position,'target_id':item['target_id'],'review_ref':'risk_reviews/'+rid+'.json','amendment_ref':'model_amendments/'+aid+'.json','superseded_review_id':old_review['review_id'],'superseded_review_sha256':digest(old_review_path),'superseded_amendment_id':old_amendment['amendment_id'] if old_amendment else None,'audit_requested_correction':request['requested_correction'],'reason':reason})
        print(f'PASS position={position} amendment={aid} review={rid}',flush=True)
    assert all(digest(path)==sha for path,sha in saved.items()),'immutable history changed'
    queue=scan_attribution_risks()
    checks=[validate_risk_review(load_json(ROOT/x['review_ref'])) for x in queue['items']]
    assert len(checks)==49 and queue['pending_model_review_count']==0
    progress=build_progress(ROOT,prior['blocker'])
    assert progress==load_json(pipeline/'reports/plan09_model_silver_progress.latest.json') and queue==load_json(ROOT/'attribution_risk_queue.json')
    assert [(x['case_id'],x['missing_target_ids']) for x in progress['cases']]==[(x['case_id'],x['missing_target_ids']) for x in prior['cases']]
    reviews=[r for p in effective_proposals() for r in p['target_reviews']]
    counts={'authority_units':sum(len(r['authority_units']) for r in reviews),'hard_negatives':sum(r['hard_negative'] is not None for r in reviews),'unresolved':sum(r['model_outcome']=='unresolved' for r in reviews)}
    assert counts=={'authority_units':98,'hard_negatives':113,'unresolved':1}
    report={'artifact_type':'Plan09AuditPositions11And32Remediation','model':'gpt-6.1-sol','semantic_gold':False,'independent_acceptance':False,'semantic_pass':False,'plan10_allowed':False,'audit_ref':audit_path.relative_to(pipeline).as_posix(),'audit_sha256':digest(audit_path),'audit_queue_sha256':audit['snapshot']['queue_sha256'],'results':results,'all_49_head_validation':checks,'pending_count':0,'effective_counts':counts,'originals_and_history_unchanged':True,'missing_ids_unchanged':True,'p09_s01_status':'pending_reaudit'}
    atomic_write(ROOT/'remediation_audit_positions11_32_validation.json',report)
    print('PASS revisions=2 all_heads=49 pending=0 effective=98/113/1 history=unchanged missing=157 S01=pending_reaudit Plan10=false')

if __name__=='__main__':main()
