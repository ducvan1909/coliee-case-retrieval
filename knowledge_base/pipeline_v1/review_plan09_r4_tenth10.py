"""Tenth R4 batch: freeze IDs before raw-source review."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE

BATCH_ID='p09-r4-099980-tenth10-sol-v1'


def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    pp=pipeline/'reports/plan09_model_silver_progress.latest.json';prior=load_json(pp)
    assert (prior['expected_target_count'],prior['reviewed_target_count'],prior['missing_target_count'])==(369,302,67)
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
    build=load_json(ROOT/'au_annotation_build_manifest.json');row=next(r for r in build['cases'] if r['case_id']=='099980');packet=load_json(ROOT/row['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==len(set(ids))==10
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(pp),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch);return batch


DECISIONS=[
 ('positive','statutory_hook','Subsection 18.1(3) FCA gives the Court broad remedy discretion, while discretionary costs require consideration of Rule 400(3) factors and other relevant matters.','Court states legal bases and constraints of remedy/costs discretion. Primary last two sentences, not mere opening outcome roadmap. Broad is not unfettered discretion and no specific costs amount is awarded in this paragraph.'),
 ('hard_negative','fact_only',None,'Paragraph 15 compares evidentiary strength/seriousness for this applicant with others. No standalone legal standard of proof or finding that she is innocent is announced.'),
 ('positive','statutory_hook','In the CHRA scheme described by the cited Supreme Court decision, the CHRC filters complaints for possible tribunal referral rather than determining rights.','Explicit cited-court attribution. Do not transfer that CHRC role to the PSEA Commission or infer procedural-fairness exemption. Paragraphs 109-113 distinguish schemes and preserve the nested Sopinka quote context; suppressed name stays raw.'),
 ('positive','statutory_hook','After investigation, the Commission may cancel or prevent appointment if satisfied of selection-affecting error, omission or improper conduct, political influence, or appointment-process fraud under the respective PSEA provisions.','Court statutory summary with three alternative grounds, not cumulative mandatory gates or automatic revocation. Preserve investigation/satisfaction thresholds and permissive may. Appointment power is not a decided section69 third-party sanction jurisdiction.'),
 ('positive','procedural_rule','The Commission exercise of section69 powers justifies greater procedural protection in this fraud-and-individual-impact context.','Explicit court Baker-assessment conclusion. Primary first sentence; grounds and comparison remain reviewed context. No automatic oral hearing, criminal proof standard or specification of every procedural requirement is invented.'),
 ('positive','holding',None,'Formal judgment: separately record scoped fairness/relief, costs/deduction and conditional finality. No declaration of innocent applicant or general invalidation for other public servants. Points 1-4, 5 and 6 have disjoint primary witnesses; editor credit is not authority.'),
 ('hard_negative','fact_only',None,'Paragraph 12 reports agency fraud/credibility findings and factual reference/job-title narrative. Investigator finding is not current-court guilt or credibility adjudication, nor a general fraud test.'),
 ('hard_negative','other',None,'Paragraph 52 reports a dictionary definition used by the investigator. It is a lexical source in an agency report, not a distinct adopted court legal definition in this target. Paragraph53 develops separate court analysis; do not infer that later analysis never adopts lexical concepts, or import it into this target.'),
 ('hard_negative','fact_only',None,'Paragraph153 recounts reference-checking duties, candidate examination/interview and October23 e-mail. No legal rule on references or court fraud finding is formulated.'),
 ('positive','statutory_hook','Under the sections66-68 appointment-supervision context, the Commission may revoke or not make an appointment and take appropriate corrective action for selection-affecting error, omission or improper conduct, or political influence.','Court remedial explanation scoped to sections66/67 and68 and the stated alternatives. Do not extend it into a final independent third-party power under section69; paragraph84 poses that question and93/183-184 reserve the ruling.'),
]


def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    def local(quote):
        c=source.index(quote,a,b);return span(c,c+len(quote))
    outcome,kind,claim,reason=DECISIONS[position-1]
    contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position==3:contexts.append(span(source.index('[109]'),source.index('[114]')))
    if position==5:contexts.append(span(source.index('[97]'),source.index('[98]')))
    if position==6:contexts.extend([span(source.index('[183]'),source.index('[185]')),span(source.index('[196]'),source.index('[197]'))])
    if position in (4,10):contexts.extend([span(source.index('[92]'),source.index('[94]')),span(source.index('[183]'),source.index('[185]'))])
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':contexts}
    def unit(witness,claim,kind,suffix='',speaker='current_court',uncertainty='low'):
        return {'au_id':'r4-au-'+task['target_id'][3:]+suffix,'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':speaker,'evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':uncertainty,'unresolved_reasons':[]}
    if outcome=='hard_negative':review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif position==6:
        c=source.index('1. This application',a,b);d=source.index('5. The applicant',c,b);e=source.index('6. This judgment',d,b);end=source.index('Application allowed.',e,b)
        relief=unit(span(c,c+len(source[c:d].rstrip())),'The application is allowed with costs; the Commission breached fairness and its decision and conclusions are set aside or declared invalid insofar as they affect the applicant.','holding','-relief')
        relief['limit_spans']=[local('insofar as the applicant is affected by the finding of fraud and the corrective action contained therein'),local('affecting the applicant specifically'),local('with respect to the applicant for all legal purposes')]
        costs=unit(span(d,d+len(source[d:e].rstrip())),'The applicant receives $12,000 in costs payable forthwith, with a $650 deduction payable to the respondent only if the applicant has not yet paid it.','holding','-costs')
        costs['condition_spans']=[local('if that amount has not yet been paid by the applicant')];costs['limit_spans']=[local('after deducting the amount of $650 payable to the respondent')]
        finality=unit(span(e,e+len(source[e:end].rstrip())),'The judgment becomes final and binding upon expiry of rights of appeal.','procedural_rule','-finality')
        finality['condition_spans']=[local('upon the expiry of rights of appeal')]
        review['authority_units']=[relief,costs,finality]
    elif outcome=='positive':
        if position==1:
            c=source.index('On this point',a,b);witness=span(c,a+len(source[a:b].rstrip()))
        elif position==5:witness=span(a,source.index(' The very seriousness',a,b))
        else:witness=span(a,a+len(source[a:b].rstrip()))
        au=unit(witness,claim,kind,speaker='cited_court' if position==3 else 'current_court',uncertainty='medium' if position in (1,3,4,5,10) else 'low')
        if position==1:au['limit_spans']=[local('the factors listed in subsection (3) of Rule 400 and any other issue that it deems relevant')]
        if position==3:au['limit_spans']=[local('under the provisions of the CHRA')]
        if position==4:
            au['condition_spans']=[local('following an investigation'),local('if it is satisfied'),local('an error, an omission or improper conduct that affected the selection of the person appointed or proposed for appointment'),local('the appointment or proposed appointment was not free from political influence'),local('fraud has occurred in the appointment process')]
            au['limit_spans']=[local('may cancel an appointment or prevent someone from being appointed')]
        if position==5:au['limit_spans']=[local("the Commission's exercise of the power set out in section 69 of the PSEA")]
        if position==10:
            au['condition_spans']=[local('when there was an error, an omission or improper conduct that affected the selection of the person appointed or proposed for appointment'),local('when the appointment or proposed appointment was not free from political influence')]
            au['limit_spans']=[local('that it considers appropriate to re-establish public confidence'),local('sections 66 and 67 of the PSEA'),local('section 68 of the PSEA')]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-tenth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


if __name__=='__main__':
    freeze_batch()
    run_batch('tenth10',make_proposal,PRODUCER,302,{'authority_units':8,'hard_negatives':4,'unresolved':0})
