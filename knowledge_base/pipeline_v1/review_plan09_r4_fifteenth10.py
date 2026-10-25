"""Fifteenth R4 batch, model-silver only."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
BATCH_ID='p09-r4-099980-fifteenth10-sol-v1'

def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    pp=pipeline/'reports/plan09_model_silver_progress.latest.json';prior=load_json(pp)
    assert (prior['expected_target_count'],prior['reviewed_target_count'],prior['missing_target_count'])==(369,352,17)
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
    build=load_json(ROOT/'au_annotation_build_manifest.json');packet=load_json(ROOT/next(r for r in build['cases'] if r['case_id']=='099980')['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==len(set(ids))==10
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(pp),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch);return batch

DECISIONS=[
 ('hard_negative','fact_only','Paragraph114 summarizes adverse effects on affected public servants. No standalone legal impact threshold, damages test or entitlement.'),
 ('hard_negative','fact_only','Paragraph166 quotes applicant affidavit about missing manager contact and potential evidentiary effects. Witness factual complaint, not an adopted universal duty to interview managers or legal proof rule.'),
 ('positive','standard_of_review','Paragraph75 says determination of section69 jurisdiction/powers review standard is a legal question with no deference to trial judge in that area. Does not select correctness versus reasonableness for underlying agency issue;183-184 reserve final ruling.'),
 ('positive','statutory_hook','Paragraph101 contrasts final/nonappealable section69 fraud route with section67 internal-revocation complaint under74. No appeal is not no judicial review:21 expressly describes judicial review route. Exclude heading and do not imply every revocation may go to Tribunal.'),
 ('positive','holding','Paragraph161 case-specific legitimate expectation that matter would end after finished sworn testimony uncontradicted in revised report. Not immunity, actual innocence, absolute ban on reopening, or universal finality once a witness testifies.'),
 ('hard_negative','procedural_history_only','Paragraph59 unsuccessful request for Personnel Psychology Centre full report and respondent Rule317 objections. Not adopted legal record-production threshold;60 separately records motion dismissal.'),
 ('hard_negative','fact_only','Paragraph162 late Cousineau email factual testimony and disputed recollections. Not court adoption of truth, late-evidence admissibility rule or proof applicant knew false references.'),
 ('hard_negative','fact_only','Paragraph130 case-specific credibility and delayed knowledge findings. Not a general fairness rule or innocence holding; Court elsewhere distinguishes procedural remedy from guilt adjudication.'),
 ('positive','statutory_hook','Paragraph2 separates section29 in-principle appointment authority and sections66-73 supervisory jurisdiction. Historical delegation is context; neither implies every appointment made personally by Commission or a final third-party sanction power.'),
 ('positive','holding','Paragraph199 separate case-specific fee exclusions and increased lump-sum costs with unpaid650 deduction. Preserve not-incurred-on-this-application and dismissed-production-motion scopes, reasonable-in-this-case qualifier and payable-forthwith; no universal12000 tariff. Costs award reiterated in formal judgment, not proof of semantic deduplication.'),
]

def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(c,d):return exact_span(source,packet['case_id'],packet['source_hash'],c,d)
    def local(q):
        c=source.index(q,a,b);return span(c,c+len(q))
    def between(q,end):
        c=source.index(q,a,b);d=source.index(end,c,b);return span(c,c+len(source[c:d].rstrip()))
    outcome,kind,reason=DECISIONS[position-1];contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position==3:contexts.append(span(source.index('[183]'),source.index('[185]')))
    if position==4:contexts.append(span(source.index('[21]'),source.index('[22]')))
    if position==8:contexts.append(span(source.index('[196]'),source.index('[197]')))
    if position==10:contexts.append(span(source.index('[190]'),source.index('[191]')))
    r={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[],'context_spans':contexts}
    def unit(w,claim,suffix='',uncertainty='low'):
        return {'au_id':'r4-au-'+task['target_id'][3:]+suffix,'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[w],'attributions':[{'role':'proposition','speaker':'current_court','evidence_span':w}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':uncertainty,'unresolved_reasons':[]}
    if outcome=='hard_negative':r['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif position==3:
        au=unit(span(a,a+len(source[a:b].rstrip())),'Determining the standard of review for Commission section69 jurisdiction/powers is a question of law on which no deference is owed to the trial judge.',uncertainty='medium')
        au['limit_spans']=[local('the jurisdiction and powers granted to the Commission under section 69 of the PSEA'),local('to the trial judge in that area')];au['cross_block_refs']=[span(source.index('[183]'),source.index('[185]'))];r['authority_units']=[au]
    elif position==4:
        au=unit(between('It must also be noted','Choice of procedures'),'Section69 fraud decisions are final and nonappealable through the statutory route described; unlike section67 internal appointment revocation complaints under74, a person suspected of fraud cannot invoke the Staffing Tribunal route and call witnesses.',uncertainty='medium')
        au['condition_spans']=[local('when an internal appointment is revoked under section 67 (error, omission or improper conduct)')];au['limit_spans']=[local('under section 69'),local('Public Service Staffing Tribunal')];au['cross_block_refs']=[span(source.index('[21]'),source.index('[22]'))];r['authority_units']=[au]
    elif position==5:
        au=unit(span(a,a+len(source[a:b].rstrip())),'In these circumstances, the applicant legitimately expected the matter to end after her sworn testimony was finished and was not directly contradicted in the revised factual report.',uncertainty='medium')
        au['condition_spans']=[local('her testimony under oath was finished'),local('it was not directly contradicted by other testimony reported in the revised factual report')];au['limit_spans']=[local('Under the circumstances')];r['authority_units']=[au]
    elif position==9:
        appointment=unit(between('In principle,','However,'),'In principle, PSEA section29 gives the Commission exclusive authority to make appointments to or from within the public service.','-appointment')
        appointment['limit_spans']=[local('In principle'),local('to or from within the public service')]
        c=source.index('There is no dispute',a,b);supervision=unit(span(c,a+len(source[a:b].rstrip())),'PSEA sections66-73 give the Commission broad supervisory jurisdiction over internal/external public-service appointments.','-supervision')
        supervision['limit_spans']=[local('pursuant to sections 66 to 73 of the PSEA'),local('over internal and external appointments within the public service')];r['authority_units']=[appointment,supervision]
    elif position==10:
        exclusions=unit(between('It goes without saying','I am also of the opinion'),'For this judicial review costs award, former-counsel fees/disbursements not incurred on this application are not claimable, and expenses of the dismissed production motion must be deducted.','-exclusions')
        exclusions['limit_spans']=[local('because they were not incurred on this application for judicial review'),local('the motion for production of documents that was dismissed by Prothonotary Tabib')]
        c=source.index('I am also of the opinion',a,b);award=unit(span(c,a+len(source[a:b].rstrip())),'The Court finds $12,000 lump-sum costs reasonable in this case and payable forthwith, deducting $650 payable to respondent only if applicant has not yet paid that amount.','-award')
        award['condition_spans']=[local('if that amount has not yet been paid by the applicant')];award['limit_spans']=[local('reasonable in this case'),local('after deducting the amount of $650 payable to the respondent')];r['authority_units']=[exclusions,award]
    r['review_trace']=model_review_trace(task,source,packet['source_hash'],r)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-fifteenth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[r]}

if __name__=='__main__':
    freeze_batch();run_batch('fifteenth10',make_proposal,PRODUCER,352,{'authority_units':7,'hard_negatives':5,'unresolved':0})
