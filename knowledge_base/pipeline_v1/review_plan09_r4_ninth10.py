"""Ninth R4 batch: freeze IDs before raw-source review."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE

BATCH_ID='p09-r4-099980-ninth10-sol-v1'


def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    pp=pipeline/'reports/plan09_model_silver_progress.latest.json';prior=load_json(pp)
    assert (prior['expected_target_count'],prior['reviewed_target_count'],prior['missing_target_count'])==(369,292,77)
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
    build=load_json(ROOT/'au_annotation_build_manifest.json');row=next(r for r in build['cases'] if r['case_id']=='099980');packet=load_json(ROOT/row['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==len(set(ids))==10
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(pp),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch);return batch


DECISIONS=[
 ('positive','standard_of_review','For complaints confined to Commission evidence-analysis errors and PSEA interpretations with no genuine jurisdiction issue, the Court considers the cited decisions to have satisfactorily settled the applicable review standard.','Court conditional precedent-sufficiency statement. Do not invent a named reasonableness/correctness standard absent from this target or apply the condition to the live jurisdiction dispute. Paragraphs 93/183-184 reserve a final jurisdiction/reasonableness ruling; the cited Seck appeal status remains raw context.'),
 ('hard_negative','editorial',None,'Paragraph 197 expresses indignation and criticizes institutional refusal to resolve the matter earlier. In the costs discussion this explains disapproval, but it states no freestanding legal duty to consent to judgment or automatic costs rule; formal costs disposition is elsewhere.'),
 ('positive','procedural_rule','When acting for the Commission without another party supporting the decision legality, the respondent should act like an amicus, though with more latitude, and objectively explain the decision and Commission reasoning without supplying new justification.','Court role guidance, not literal appointment as amicus or an unrestricted merits-advocacy licence. Preserve respondent-for-Commission/absence-of-other-party conditions, greater-latitude qualification and no-new-justification limit. Paragraphs 45-46 separately restrict fairness advocacy and explain actual consideration absent objection.'),
 ('hard_negative','fact_only',None,'Paragraph 64 narrates June 5 notice, DNR information and appointment-process history. Section 69 mention does not prove actual jurisdiction or adopt a legal finding that the candidate committed fraud.'),
 ('positive','holding','The Court rejected the respondent suggestion that this investigator approach caused no prejudice to the applicant as refuted by the record.','Explicit court prejudice finding, primary first sentence only. Scope is this approach/applicant/record, not a universal two-day interview/report rule or adoption of respondent no-prejudice position. Later draft-report heading is not evidence.'),
 ('hard_negative','other',None,'Reported institutional mission statement lists four values, not an independently formulated enforceable legal proposition in this target. Do not transform a published values pledge into current-court law; the separate legitimate-expectations rule is stated in paragraph 105.'),
 ('positive','procedural_rule','Before disciplinary action a deputy head must investigate and give the public servant an opportunity to be heard and defend; the PSLRA and applicable collective-agreement procedures must be followed, with disciplinary action challengeable through a grievance potentially referred to an adjudicator.','Primary middle legal statements are court voice, not opening possible-duplication argument or closing unanswered third-party Commission-power question. Preserve disciplinary context, applicable agreement and could-be-referred modality; no binding adoption of Review Team recommendation or guarantee every grievance reaches adjudication. Jurisdiction reservation remains context.'),
 ('positive','holding','For this applicant, the June 28 opportunity to make submissions on proposed corrective actions was too little, too late in light of the investigator groundwork and circumstances.','Court scoped adequacy finding, not merely notice history. Read paragraphs 173-176: final fraud analysis preceded this corrective-action phase. Not a universal rule that every later hearing can never cure a procedural defect; date, applicant and circumstances constrain this holding.'),
 ('positive','standard_of_review','The Dunsmuir framework recited in this judgment first asks whether precedent satisfactorily settles deference for the question category and, if not, proceeds to a factors analysis to identify the standard.','Explicit Supreme Court attribution and conditional two-stage framework. Record cited_court voice, not party submissions or the final standard for this applicant. No assertion that this historic framework is current law today; no invented suppressed case name beyond the visible Dunsmuir handle.'),
 ('positive','holding','Even assuming the Commission did not change its mandate, the Court found serious procedural-fairness breaches, lack of transparency and substantial injustice to this applicant that damaged investigation integrity.','Only court response is primary; preceding unchanged-mandate assertion is respondent advocacy and disputed, not court acceptance. Preserve even-if assumption and this-case limit. No holding that the mandate actually stayed unchanged or that every unchanged mandate implies unfairness; exclude the next heading.'),
]


def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(start,end):return exact_span(source,packet['case_id'],packet['source_hash'],start,end)
    def local(quote):
        c=source.index(quote,a,b);return span(c,c+len(quote))
    outcome,kind,claim,reason=DECISIONS[position-1]
    contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position in (1,7):contexts.extend([span(source.index('[92]'),source.index('[94]')),span(source.index('[183]'),source.index('[185]'))])
    if position==3:contexts.append(span(source.index('[43]'),source.index('[47]')))
    if position==8:contexts.append(span(source.index('[173]'),source.index('[177]')))
    review={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':contexts}
    if outcome=='hard_negative':review['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif outcome=='positive':
        if position in (1,3,8,9):witness=span(a,a+len(source[a:b].rstrip()))
        elif position==5:witness=span(a,source.index(' This is obvious',a,b))
        elif position==7:
            c=source.index('In fact, it must be understood',a,b);witness=span(c,source.index(' Regarding other candidates',c,b))
        elif position==10:
            c=source.index('Even if that is true',a,b);end=source.index('Notice of investigation not involving',c,b);witness=span(c,c+len(source[c:end].rstrip()))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[witness],'attributions':[{'role':'proposition','speaker':'cited_court' if position==9 else 'current_court','evidence_span':witness}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'medium' if position in (1,3,7,8) else 'low','unresolved_reasons':[]}
        if position==1:au['condition_spans']=[local('To the extent that the blame lies solely on the Commission-in effect, the investigator-for erring in its analysis of the evidence'),local('where no jurisdiction issue is truly at stake')]
        if position==3:
            au['condition_spans']=[local('when the respondent agrees to act on behalf of the Commission'),local('in the absence of another party to support the legality of the impugned decision')]
            c=source.index('even if the respondent has more latitude',a,b);end=source.index('. After all',c,b);au['exception_spans']=[span(c,end)]
            au['limit_spans']=[local('without seeking justification that was not provided by the Commission itself in the impugned decision')]
            au['cross_block_refs']=[span(source.index('[45]'),source.index('[47]'))]
        if position==5:au['limit_spans']=[local("the investigator's approach"),local('to the applicant')]
        if position==7:
            au['condition_spans']=[local('In such a case')];au['limit_spans']=[local('any applicable collective agreement'),local('could be referred to an adjudicator')]
        if position==8:
            au['condition_spans']=[local("with the investigator's ground work")];au['limit_spans']=[local('On June 28, 2010'),local('under the circumstances')]
        if position==9:au['condition_spans']=[local('where the first inquiry proves unfruitful')]
        if position==10:au['condition_spans']=[local('Even if that is true')];au['limit_spans']=[local('in this case')]
        review['authority_units']=[au]
    review['review_trace']=model_review_trace(task,source,packet['source_hash'],review)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-ninth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[review]}


if __name__=='__main__':
    freeze_batch()
    run_batch('ninth10',make_proposal,PRODUCER,292,{'authority_units':7,'hard_negatives':3,'unresolved':0})
