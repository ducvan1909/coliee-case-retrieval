"""Eighth R4 batch: freeze IDs before opening raw source."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE

BATCH_ID='p09-r4-099980-eighth10-sol-v1'


def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    progress_path=pipeline/'reports/plan09_model_silver_progress.latest.json'
    prior=load_json(progress_path)
    assert prior['expected_target_count']==369 and prior['reviewed_target_count']==282 and prior['missing_target_count']==87
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
    build=load_json(ROOT/'au_annotation_build_manifest.json');row=next(r for r in build['cases'] if r['case_id']=='099980');packet=load_json(ROOT/row['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):
        saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==10 and len(set(ids))==10
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(progress_path),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch)
    return batch


DECISIONS=[
 ('positive','statutory_hook','A witness called by a commissioner must appear and answer the commissioner questions; refusal may result in a contempt finding and criminal prosecution.','Court explains commissioner compulsion under the Inquiries Act, not an adjudicated contempt finding or automatic conviction. Primary last sentence preserves refusal condition and can modality. Paragraphs 103/107-108 preserve the commissioner/Commission nexus and fair-play, notice, disclosure and applicable testimony protections; no power to ignore statutory/Charter safeguards.'),
 ('hard_negative','fact_only',None,'Paragraph 20 reports the other investigation, investigator fraud findings and reference-compilation facts. These are agency findings/history, not Court guilt findings or a general legal rule of entitlement to give references.'),
 ('positive','procedural_rule','Regardless of the procedure chosen, the investigative means used in this Commission fraud-investigation context must respect legitimate expectations of integrity, fairness, respect and transparency.','Primary second sentence is explicit court norm, not merely the first sentence evidence-collection description. Scope such a case refers to Commission compulsion/fraud-investigation context; not every investigation by every body or four automatic freestanding remedies. Mission-statement values in paragraph 106 are separate reported policy context.'),
 ('unresolved',None,None,'Paragraph 174 is an anaphoric confirmation of the preceding paragraph 173 draft-report rhetorical question followed by a heading. The underlying fairness proposition is in the preceding target, whereas this target supplies no distinct standalone formulation. Whether it warrants an additional AU versus a confirmation/duplicate cross-reference is uncertain. Preserve full 173-174 context; no forced new AU or editorial/no-AU negative.'),
 ('positive','statutory_hook','Document manufacture and misuse in an appointment process can lead to fraud disqualification while the process is ongoing or revocation if the candidate has already been appointed.','Court remedial explanation is conditional and uses could lead, not automatic penalty. Primary first sentence preserves two appointment-stage conditions. The next sentence says requires investigate, whereas the section 69 quotation in paragraph 48 says may investigate; do not generalize that paraphrase into an unconditional mandatory-investigation rule or silently replace the raw statutory wording.'),
 ('positive','procedural_rule','In this respondent-for-Commission context, explaining the impugned decision and objectively illuminating Commission jurisdiction and statutory powers is permissible.','Court first-sentence summary is expressly conditional on objective explanation. Paragraph 43 limits the role to public-interest clarification without new justification; paragraphs 45-46 qualify fairness advocacy and actual consideration absent objection. Not unrestricted merits advocacy, permission to defend procedural fairness, or adoption of the following suppressed-citation jurisdiction dictum.'),
 ('positive','procedural_rule','When deciding whether to investigate, the Commission Policy requires consideration of jurisdiction, statutory/delegation problems, irregularity patterns, timing, possible corrective action and alternative recourse, with extension/other-source qualifications to the six-month participant timing factor.','Primary Policy introduction and complete list, attributed to commission_policy rather than current-court holding or statute. Must consider whether does not make every item a mandatory cumulative eligibility gate. Preserve participant six-month period, fairness/merit extension and other-means intervention whether or not within six months. Exclude first sentence reported notice compliance; it does not prove actual Policy compliance.'),
 ('positive','standard_of_review','Assuming the Commission has jurisdiction to investigate and sanction third parties, the Court frames the inquiry as whether the applicant fraud finding is defensible in facts and law.','Primary final sentence is a conditional court review inquiry, not an actual jurisdiction finding, final reasonableness adjudication or universal review standard. Keep the explicit jurisdiction assumption and applicant-fraud-finding limit. Paragraphs 93/183-184 reserve a final jurisdiction/reasonableness ruling; earlier motion dismissal/history/regret is not primary or a rule compelling production.'),
 ('hard_negative','fact_only',None,'Paragraph 138 describes the actual interview/questioning format, oath/compulsion and announced two-report plan. It is case-process history rather than a distinct general legal compulsion rule or holding that every investigator must use two reports. Do not promote the reported investigator plan into statute or import later draft-comment duty.'),
 ('hard_negative','fact_only',None,'Paragraph 171 identifies the internal approval note and final report differences from the revised factual report. This is record appraisal/history, not a general administrative-finality rule or freestanding draft-comment requirement; paragraph 173 supplies that separate proposition.'),
]


def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    def local(quote):
        c=source.index(quote,a,b);return span(c,c+len(quote))
    outcome,kind,claim,reason=DECISIONS[position-1]
    contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position==1:contexts.append(span(source.index('[103]'),source.index('[109]')))
    if position==4:contexts.append(span(source.index('[173]'),source.index('[175]')))
    if position==5:contexts.append(span(source.index('[48]'),source.index('[49]')))
    if position==6:contexts.append(span(source.index('[43]'),source.index('[47]')))
    if position==8:contexts.extend([span(source.index('[92]'),source.index('[94]')),span(source.index('[183]'),source.index('[185]'))])
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':contexts}
    if outcome=='hard_negative':review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif outcome=='positive':
        if position==1:
            c=source.index('Thus, someone',a,b);witness=span(c,a+len(source[a:b].rstrip()))
        elif position==3:
            c=source.index('However, regardless',a,b);witness=span(c,a+len(source[a:b].rstrip()))
        elif position==5:witness=span(a,source.index(' This is clearly',a,b))
        elif position==6:witness=span(a,source.index(' I acknowledge',a,b))
        elif position==7:
            c=source.index('According to the Policy',a,b);witness=span(c,a+len(source[a:b].rstrip()))
        elif position==8:
            c=source.index('To the extent that',a,b);witness=span(c,a+len(source[a:b].rstrip()))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':'commission_policy' if position==7 else 'current_court','evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'medium' if position in (1,5,6,7,8) else 'low','unresolved_reasons':[]}
        if position==1:
            au['condition_spans']=[local('someone who is called as a witness'),local('if the individual refuses to appear or to respond')]
            au['limit_spans']=[local('by the commissioner')]
            au['cross_block_refs']=[span(source.index('[103]'),source.index('[104]')),span(source.index('[107]'),source.index('[109]'))]
        if position==3:au['limit_spans']=[local('in such a case')]
        if position==5:
            au['condition_spans']=[local('if the appointment process is still in progress'),local('if he or she has already been appointed')]
            au['limit_spans']=[local('could lead to')]
        if position==6:
            au['condition_spans']=[local("as long as the respondent explains the impugned decision and provides objective light on the Commission's jurisdiction and the powers vested in it under the law")]
            au['cross_block_refs']=[span(source.index('[43]'),source.index('[44]')),span(source.index('[45]'),source.index('[47]'))]
        if position==7:
            au['condition_spans']=[local('in deciding whether to conduct an investigation')]
            au['exception_spans']=[local('however, the Commission may, in the interest of fairness and the protection of merit, extend this time period'),local('whether or not it is within six months of the appointment being made or proposed')]
            au['limit_spans']=[local('by a person involved in the process within six months of the appointment being made or proposed'),local('by any other means')]
        if position==8:
            au['condition_spans']=[local('To the extent that the Commission actually has jurisdiction to investigate and sanction third parties')]
            au['limit_spans']=[local('the finding that the applicant committed fraud')]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-eighth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


if __name__=='__main__':
    freeze_batch()
    run_batch('eighth10',make_proposal,PRODUCER,282,{'authority_units':6,'hard_negatives':3,'unresolved':1})
