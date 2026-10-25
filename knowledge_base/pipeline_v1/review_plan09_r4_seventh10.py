"""Seventh R4 batch: freeze IDs before opening raw source."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE

BATCH_ID='p09-r4-099980-seventh10-sol-v1'


def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    progress_path=pipeline/'reports/plan09_model_silver_progress.latest.json'
    prior=load_json(progress_path)
    assert prior['expected_target_count']==369 and prior['reviewed_target_count']==272 and prior['missing_target_count']==97
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
    build=load_json(ROOT/'au_annotation_build_manifest.json')
    row=next(r for r in build['cases'] if r['case_id']=='099980')
    packet=load_json(ROOT/row['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):
        saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==10 and len(set(ids))==10
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(progress_path),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch)
    return batch


DECISIONS=[
 ('hard_negative','fact_only',None,'Paragraph 137 compares the candidate notice/representation information with the applicant exclusion. These are case-history facts; neither the communicated candidate right nor investigator choice of approach is stated as a general court procedural rule. Do not import the separate paragraph 136 fairness conclusion.'),
 ('hard_negative','party_argument_only',None,'Paragraph 177 reports former counsel fairness/remedy complaints and applicant innocence/supervision account. Eloquently is not adoption of each party proposition. Later court conclusions do not change this span speaker into current_court.'),
 ('positive','procedural_rule','The Commission Policy describes the decision whether to investigate as discretionary and determined case by case.','Explicit reported administrative-policy proposition, attributed to Commission policy, not current-court holding or statutory command. Primary excludes the following heading. Read paragraph 65 policy factors: discretion is not an unrestricted exemption from jurisdiction, fairness or other policy considerations. No final jurisdiction finding is inferred.'),
 ('hard_negative','party_argument_only',None,'Paragraph 31 frames the applicant alternative unreasonableness argument based on no personal gain and then reports investigator/evidence contrasts within that argument. No adopted current-court rule that personal gain is always a necessary fraud element.'),
 ('hard_negative','party_argument_only',None,'Paragraph 47 juxtaposes applicant jurisdiction objections and respondent defence of section 69 powers/reasonableness. The Court does not adopt either in this span; no settled jurisdiction or reasonable-decision holding.'),
 ('hard_negative','fact_only',None,'Paragraph 129 is a case-specific credibility finding and acceptance of affidavit allegations as uncontradicted by documents. No general rule of credibility or procedural fairness is formulated; not fact_pattern_rule merely because the Court accepts facts.'),
 ('unresolved',None,None,'Paragraph 86 mixes reported Seck 1 reasoning, respondent submissions, Commission no-practical-effect position and a court doubt about stakeholder consistency. It does not clearly adopt a reusable integrity/no-effect rule or finally reject statutory jurisdiction. AU eligibility/speaker boundaries of the mixed passage remain uncertain; paragraphs 93/183-184 reserve final jurisdiction/reasonableness. No AU or hard-negative label is forced.'),
 ('positive','holding','The Court held that the two judgments relied on by the respondent in paragraph 113 did not apply in this case.','Direct court distinction of the two suppressed-citation judgments. Primary is first sentence only; retain this-case limit and do not invent missing case names. The ensuing CHRC/resource/tribunal comparison explains context, not a categorical rule that all CHRC precedents are inapplicable or a universal corporate-resource legal presumption. Read paragraphs 100-113 to separate preceding nested cited-court quotations.'),
 ('positive','procedural_rule','Before assessing the reasonableness of the fraud finding in this third-party case, the Court states that one should first be satisfied the Commission has jurisdiction over third parties.','Explicit court sequencing statement, not a finding that jurisdiction exists or is absent. Primary first sentence; next sentence is analytical roadmap. Preserve before-reasonableness and third-party scope; paragraphs 93/183-184 reserve a final jurisdiction/reasonableness ruling. Do not infer a mandatory universal standard of review.'),
 ('positive','holding','Any declaration of illegality and nullity in the judgment is limited to the applicant and the fraud finding and corrective actions insofar as they affect her; no declaration is made on Commission jurisdiction or decision reasonableness.','Court expressly specifies relief scope and reservation. Primary complete paragraph 184. Preserve exclusive applicant benefit, affected-decision/report scope and no-jurisdiction/reasonableness declaration; no general invalidation for other public servants or statutory jurisdiction holding. Paragraph 185 supplies the procedural-fairness ground, not a jurisdiction decision.'),
]


def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    def local(quote):
        c=source.index(quote,a,b);return span(c,c+len(quote))
    outcome,kind,claim,reason=DECISIONS[position-1]
    contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position in (7,9):
        contexts.extend([span(source.index('[92]'),source.index('[94]')),span(source.index('[183]'),source.index('[185]'))])
    if position==3:contexts.append(span(source.index('[65]'),source.index('[66]')))
    if position==8:contexts.append(span(source.index('[100]'),source.index('[114]')))
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':contexts}
    if outcome=='hard_negative':review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif outcome=='positive':
        if position==3:
            end=source.index('case by case basis.',a,b)+len('case by case basis.');witness=span(a,end)
        elif position==8:witness=span(a,source.index(' It must also',a,b))
        elif position==9:witness=span(a,source.index(' Before assessing the parties',a,b))
        elif position==10:witness=span(a,a+len(source[a:b].rstrip()))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':'commission_policy' if position==3 else 'current_court','evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'medium' if position in (3,9) else 'low','unresolved_reasons':[]}
        if position==3:
            au['limit_spans']=[local('the decision to investigate or not to investigate'),local('on a case by case basis')]
            au['cross_block_refs']=[span(source.index('[65]'),source.index('[66]'))]
        if position==8:au['limit_spans']=[local('in this case')]
        if position==9:
            au['limit_spans']=[local('before assessing the reasonableness of the finding of "fraud"'),local('in respect of third parties')]
        if position==10:
            au['limit_spans']=[local('to the exclusive benefit of the applicant'),local('insofar as the applicant is affected by the impugned decision and the impugned investigation report')]
            au['exception_spans']=[local("There will therefore be no declaration in my judgment on the Commission's jurisdiction or the reasonableness of the impugned decision.")]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-seventh10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


if __name__=='__main__':
    freeze_batch()
    run_batch('seventh10',make_proposal,PRODUCER,272,{'authority_units':4,'hard_negatives':5,'unresolved':1})
