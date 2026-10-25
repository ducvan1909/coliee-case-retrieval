"""Apply only the three first-ten audit corrections, retaining all histories."""
import copy
from .au_gold.core import atomic_write,exact_span,load_json,model_review_trace
from .au_gold.progress import build_progress
from .au_gold.remediation import ROOT,checkpoint_amendment,checkpoint_risk_review_revision,dependencies,digest,effective_proposals,registry,risk_review_heads,scan_attribution_risks,validate_risk_review

def main():
    pipeline=ROOT.parents[1]
    audit_path=pipeline/'evaluation/reports/plan09_r3_first10_independent_semantic_audit.json'
    audit=load_json(audit_path)
    before=scan_attribution_risks()
    if before['pending_model_review_count']!=19:raise RuntimeError('queue scope changed')
    saved={str(p):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews') for p in (ROOT/folder).rglob('*.json')}
    old_progress=load_json(pipeline/'reports/plan09_model_silver_progress.latest.json')
    packet,source,_=dependencies(ROOT,'011904')
    reviewer={'source_type':'model','reviewer_id':'p09-r3-first10-audit-remediation-gpt-6.1-sol','model':'gpt-6.1-sol'}
    results=[]
    for position in (2,6,10):
        finding=next(x for x in audit['items'] if x['position']==position)
        old_path=ROOT/'risk_reviews'/f'p09-r3-first10-{position:02d}-gpt61sol-v1.json'
        old=load_json(old_path)
        if digest(old_path)!=finding['audited_record_sha256'] or old['target_id']!=finding['target_id']:
            raise RuntimeError('audit record identity/hash mismatch')
        task=next(x for x in packet['tasks'] if x['target_id']==old['target_id'])
        a,b=task['target_span']['start_char'],task['target_span']['end_char']
        def span(start,end):return exact_span(source,old['case_id'],old['source_hash'],start,end)
        def witness(text):
            start=source.index(text,a,b);return span(start,start+len(text))
        target=span(a,b)
        contexts=[span(x['start_char'],x['end_char']) for x in old['context_spans']]
        aid=None;codepoint_evidence=None
        if position==6:
            start=source.index('Colegio de ',a,b)+len('Colegio de ')
            raw_word=source[start:start+6]
            old_word=old['target_span']['quote'].split('Colegio de ',1)[1][:6]
            codepoint_evidence={'raw_codepoints':[ord(c) for c in raw_word],'audited_record_codepoints':[ord(c) for c in old_word],'raw_contains_U00E9': '\u00e9' in raw_word,'raw_contains_UFFFD':'\ufffd' in raw_word,'old_target_matches_raw':old['target_span']==target,'old_context_matches_raw':old['context_spans']==contexts,'finding_reproduced':False}
            if raw_word!='M\u00e9xico' or target!=old['target_span'] or contexts!=old['context_spans']:
                raise RuntimeError('source/record differs from independently checked codepoint state')
            reason='Audit item 06 exact spans rebuilt exclusively from open_source. At the audited source and record hashes, both contain U+00E9, not U+FFFD; original quotes/hash already match raw source and pass validator. The claimed quote_mismatch is not reproduced. Preserve the raw codepoints without normalization; retain supported keep decision and request independent reconciliation.'
        else:
            original=load_json(ROOT/'model_proposals'/old['case_id']/(old['proposal_id']+'.json'))
            replacement=copy.deepcopy(next(r for r in original['target_reviews'] if r['target_id']==old['target_id']))
            au=replacement['authority_units'][0]
            au['provenance']={'source_type':'model','producer_id':'model:gpt-6.1-sol','prompt_version':'p09-r3-audit-remediation-v1'}
            if position==2:
                reason='Audit item 02: preserve developed-democratic-state scope and danger as an exceptional circumstance excusing exhaustion. Court voice is explicit; amend claim and record exact condition/exception/limit witnesses instead of leaving the overbroad keep decision.'
                au['claim_text']='For claimants from developed democratic states, the high state-protection burden does not require placing themselves in danger to exhaust protection avenues; requiring such danger would constitute an exceptional circumstance.'
                au['condition_spans']=[witness('claimants from developed democratic states')]
                start=source.index('Indeed, in my opinion,',a,b)
                au['exception_spans']=[span(start,b)]
                au['limit_spans']=[witness('this burden does not require that they put themselves in danger in order to exhaust all possible avenues of protection.')]
            else:
                reason='Audit item 10: a case-specific court finding need not be a generic reusable rule to qualify as a holding. Paragraph 27 supports the narrow finding that the Board faced abundant evidence indicating the principal applicant protective measures were ineffective; paragraphs 28 and 34 link contradictory evidence to reviewable error. Restore positive holding/current_court, not a general finding that all Mexican protection is ineffective.'
                narrow=witness('However, the Board was faced with an abundance of evidence which indicated that these measures were not effective.')
                au.update(kind='holding',claim_text='In this review of the principal applicant claim, the court found that the Board faced abundant evidence indicating that the protective measures were ineffective.',evidence_spans=[narrow],attributions=[{'role':'proposition','speaker':'current_court','evidence_span':narrow}])
                support='In light of the foregoing, I am of the view that the Board erred by failing to consider the abovementioned documents in its analysis of state protection.'
                start=source.index(support);contexts.append(span(start,start+len(support)))
            replacement.update(model_outcome='positive',hard_negative=None,unresolved_reasons=[])
            replacement['notes']=replacement.get('notes',[])+[reason]
            trace=replacement['review_trace']
            replacement['review_trace']=model_review_trace(task,source,old['source_hash'],replacement)
            for k in ('region_id','region_fingerprint'):replacement['review_trace'][k]=trace[k]
            fid=f'P09-R3-AUDIT-{position:02d}'
            reg=registry()
            if any(x['finding_id']==fid for x in reg['findings']):raise RuntimeError('audit correction already exists')
            reg['findings'].append({'finding_id':fid,'severity':'moderate','status':'amended_pending_independent_audit','case_id':old['case_id'],'target_id':old['target_id'],'source_hash':old['source_hash'],'proposal_id':old['proposal_id'],'proposal_sha256':old['proposal_sha256'],'error_types':['lost_qualification' if position==2 else 'unsupported_abstention'],'evidence_span':target,'reason':reason,'audit_ref':audit_path.relative_to(pipeline).as_posix(),'audit_sha256':digest(audit_path),'audited_record_sha256':finding['audited_record_sha256']})
            atomic_write(ROOT/'semantic_defect_registry.json',reg)
            aid=f'p09-r3-first10-audit-{position:02d}-gpt61sol-v2'
            amendment={'artifact_type':'AUModelAmendment','schema_version':'au-model-amendment-v1','amendment_id':aid,'finding_id':fid,'supersedes_proposal_id':old['proposal_id'],'supersedes_proposal_sha256':old['proposal_sha256'],'case_id':old['case_id'],'target_id':old['target_id'],'source_hash':old['source_hash'],'reviewer':reviewer,'reason':reason,'replacement_review':replacement,'context_spans':contexts,'status':'model_reviewed_pending_independent_audit'}
            if position==10:
                amendment.update(schema_version='au-model-amendment-v2',supersedes_amendment_id=old['amendment_id'],supersedes_amendment_sha256=digest(ROOT/'model_amendments'/(old['amendment_id']+'.json')))
            checkpoint_amendment(amendment)
        revision=copy.deepcopy(old)
        rid=f'p09-r3-first10-audit-{position:02d}-gpt61sol-v2'
        revision.update(review_id=rid,reviewer=reviewer,outcome='keep' if position==6 else 'amendment',reason=reason,target_span=target,context_spans=contexts,amendment_id=aid,supersedes_review_id=old['review_id'],supersedes_review_sha256=digest(old_path))
        checkpoint_risk_review_revision(revision)
        checks=validate_risk_review(load_json(ROOT/'risk_reviews'/(rid+'.json')))
        results.append({**checks,'audit_position':position,'target_id':old['target_id'],'audit_ref':audit_path.relative_to(pipeline).as_posix(),'audit_sha256':digest(audit_path),'audited_record_sha256':finding['audited_record_sha256'],'superseded_review_ref':old_path.relative_to(ROOT).as_posix(),'review_ref':'risk_reviews/'+rid+'.json','amendment_id':aid,'reason':reason,'codepoint_evidence':codepoint_evidence,'independent_acceptance':False})
        print(f'PASS corrected_review={position:02d} new_head={rid}',flush=True)
    assert all(digest(path)==sha for path,sha in saved.items()),'immutable historical bytes changed'
    queue=scan_attribution_risks()
    assert [(x['proposal_id'],x['target_id'],x['au_id']) for x in queue['items'] if x['status']=='pending_model_review']==[(x['proposal_id'],x['target_id'],x['au_id']) for x in before['items'] if x['status']=='pending_model_review']
    first10=[]
    for item in queue['items'][:10]:
        head=load_json(ROOT/item['review_ref']);first10.append(validate_risk_review(head))
    progress=build_progress(ROOT,old_progress['blocker'])
    assert progress==load_json(pipeline/'reports/plan09_model_silver_progress.latest.json')
    assert queue==load_json(ROOT/'attribution_risk_queue.json')
    assert [(x['case_id'],x['missing_target_ids']) for x in progress['cases']]==[(x['case_id'],x['missing_target_ids']) for x in old_progress['cases']]
    reviews=[r for p in effective_proposals() for r in p['target_reviews']]
    counts={'authority_units':sum(len(r['authority_units']) for r in reviews),'hard_negatives':sum(r['hard_negative'] is not None for r in reviews),'unresolved':sum(r['model_outcome']=='unresolved' for r in reviews)}
    assert counts=={'authority_units':98,'hard_negatives':112,'unresolved':2}
    report={'artifact_type':'Plan09FirstTenAuditRemediation','semantic_gold':False,'semantic_pass':False,'independent_acceptance':False,'plan10_allowed':False,'audit_ref':audit_path.relative_to(pipeline).as_posix(),'audit_sha256':digest(audit_path),'results':results,'first10_effective_validation':first10,'pending_count':queue['pending_model_review_count'],'reviewed_risk_count':len(risk_review_heads()),'effective_counts':counts,'history_preserved':True,'missing_ids_unchanged':True,'p09_s01_closed':False}
    atomic_write(ROOT/'remediation_first10_audit_validation.json',report)
    print('PASS first10=10/10 queue=30_reviewed/19_pending effective=98/112/2 history=unchanged S01=open item06_audit_mismatch=not_reproduced')

if __name__=='__main__':main()
