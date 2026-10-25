"""Eleventh R4 batch, model-silver only."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
BATCH_ID='p09-r4-099980-eleventh10-sol-v1'

def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    pp=pipeline/'reports/plan09_model_silver_progress.latest.json';prior=load_json(pp)
    assert (prior['expected_target_count'],prior['reviewed_target_count'],prior['missing_target_count'])==(369,312,57)
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
    build=load_json(ROOT/'au_annotation_build_manifest.json');packet=load_json(ROOT/next(r for r in build['cases'] if r['case_id']=='099980')['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==len(set(ids))==10
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(pp),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch);return batch

DECISIONS=[
 ('hard_negative','fact_only',None,'Paragraph32 gives hypothetical no-practical-effect and appointment-outcome explanation in the applicant argument context. No adopted legal rule that fraud always requires an actual appointment effect; exclude next heading.'),
 ('positive','holding','For this dispute the Court chose not to give a final jurisdiction or reasonableness ruling in the interests of justice.','Express case-specific reservation decision, not a jurisdiction/standard outcome or general bar on deciding those issues. Primary explicit I-have-decided clause; paragraph184 confirms no declaration. Strong doubts earlier are not a settled lack-of-jurisdiction holding.'),
 ('hard_negative','editorial',None,'Rousseau philosophical quotation is rhetorical framing, not a statutory or court fraud-elements test. Do not promote all distinctions between cheat/fraud/calumny/fiction into law.'),
 ('hard_negative','fact_only',None,'DNR/employer participation and submissions history; no universal interested-employer participation right or legal entitlement to reports.'),
 ('positive','statutory_hook','PSEA-governed internal and external federal public-service appointments are based on merit and non-partisanship.','Court statutory-framework statement. Primary first substantive sentence only; judge/translation metadata and next general honesty expectation are excluded. Not a statutory private-sector recruitment rule or automatic fraud finding from a false reference.'),
 ('hard_negative','fact_only',None,'Written reference quality/authorship and corroborating e-mails are evidentiary facts, not Court guilt or a reusable fraud test.'),
 ('hard_negative','party_argument_only',None,'Paragraph168 quotes respondent memorandum about factual-report comments and corrective-action submissions. Skilfully insists does not adopt a legal finding that these opportunities satisfied fairness; paragraph169 identifies the omitted final-analysis issue.'),
 ('unresolved',None,None,'Court notes possible double-standard impression and asks whether reasonable apprehension of bias exists at least in appearance. No settled bias finding or complete threshold test is formulated. Eligibility/kind of a standalone AU from this tentative observation is uncertain; paragraph186 also speaks of apprehensions one may have. No forced bias holding or fact-only negative.'),
 ('hard_negative','procedural_history_only',None,'Paragraph175 describes corrective-action phase and Commission inflexibility after its fraud finding. Not Court confirmation of guilt or legal rule that subsequent submissions can never matter.'),
 ('positive','statutory_hook','In the PSDPA framework described here, the Public Sector Integrity Commissioner investigates/decides disclosure and reprisal matters, while the Tribunal hears reprisal complaints resulting from protected disclosure.','Primary final role-allocation sentence, not legislative history or public-confidence rhetoric. No transfer of these PSDPA roles to PSEA Commission, or proof applicant has an available complaint in this case; preserve protected-disclosure scope.'),
]

def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(c,d):return exact_span(source,packet['case_id'],packet['source_hash'],c,d)
    def local(q):
        c=source.index(q,a,b);return span(c,c+len(q))
    outcome,kind,claim,reason=DECISIONS[position-1];contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position==2:contexts.extend([span(source.index('[92]'),source.index('[94]')),span(source.index('[183]'),source.index('[185]'))])
    if position==8:contexts.append(span(source.index('[186]'),source.index('[187]')))
    r={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[reason] if outcome=='unresolved' else [],'context_spans':contexts}
    if outcome=='hard_negative':r['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif outcome=='positive':
        if position==2:
            c=source.index('I have decided',a,b);w=span(c,a+len(source[a:b].rstrip()))
        elif position==5:
            c=source.index('Internal and external appointments',a,b);end=source.index('the staffing system.',c,b)+len('the staffing system.');w=span(c,end)
        elif position==10:
            c=source.index('The Public Sector Integrity Commissioner',a,b);w=span(c,a+len(source[a:b].rstrip()))
        au={'au_id':'r4-au-'+task['target_id'][3:],'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[w],'attributions':[{'role':'proposition','speaker':'current_court','evidence_span':w}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'medium' if position==2 else 'low','unresolved_reasons':[]}
        if position==2:
            au['limit_spans']=[local("on the Commission's jurisdiction and the reasonableness of the impugned decision"),local('on these issues')];au['cross_block_refs']=[span(source.index('[184]'),source.index('[185]'))]
        if position==5:au['limit_spans']=[local('within the federal public service')]
        if position==10:au['limit_spans']=[local('as a result of a protected disclosure')]
        r['authority_units']=[au]
    r['review_trace']=model_review_trace(task,source,packet['source_hash'],r)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-eleventh10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[r]}

if __name__=='__main__':
    freeze_batch();run_batch('eleventh10',make_proposal,PRODUCER,312,{'authority_units':3,'hard_negatives':6,'unresolved':1})
