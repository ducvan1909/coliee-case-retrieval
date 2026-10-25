"""Fourteenth R4 batch, model-silver only."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
BATCH_ID='p09-r4-099980-fourteenth10-sol-v1'

def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    pp=pipeline/'reports/plan09_model_silver_progress.latest.json';prior=load_json(pp)
    assert (prior['expected_target_count'],prior['reviewed_target_count'],prior['missing_target_count'])==(369,342,27)
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
    build=load_json(ROOT/'au_annotation_build_manifest.json');packet=load_json(ROOT/next(r for r in build['cases'] if r['case_id']=='099980')['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==len(set(ids))==10
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(pp),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch);return batch

DECISIONS=[
 ('hard_negative','fact_only','Paragraph56 agency investigation illustration and credibility/plagiarism findings; paragraph57 separately mentions judicial confirmation. Not current-court applicant guilt or standalone legal fraud test.'),
 ('positive','procedural_rule','Paragraph110 distinguishes Commission post-investigation satisfaction threshold from reasonable grounds, then expressly attributes civil balance-of-probabilities rule to cited Court. Separate witnesses/speakers; no criminal burden or automatic guilt.'),
 ('hard_negative','fact_only','Paragraph9 identifies other persons allegations outside this application and investigation origins. Not adjudication of those allegations or legal immunity for applicant.'),
 ('positive','procedural_rule','Rule303(3) permissive substitution on AG motion and Court satisfaction AG unable/unwilling after naming under(2). Not automatic substitution or unqualified right to name tribunal; no such motion here is contextual only.'),
 ('positive','procedural_rule','Paragraph108 separate notice/document access and conditional witness-protection statutory hook. Preserve if-applicable and tentative section13 observation. No unconditional right to refuse answers or exclusion of all interview evidence; exclude next heading.'),
 ('positive','holding','Paragraph93 Court reserves definitive jurisdiction/reasonableness opinion and declines that basis today. Paragraphs183-184 confirm no declaration. Not final lack-of-jurisdiction finding from paragraph92; fairness seems determinative is roadmap, not independent innocence adjudication. Reiterates same reservation later in reasons.'),
 ('positive','statutory_hook','Paragraph103 subsection70(2) informal/expeditious procedure and Inquiries Act PartII commissioner powers. Informality does not displace fairness; nearby105-108 preserve legitimate expectations and protections.'),
 ('positive','holding','Paragraph169 Court identifies final report approval without applicant opportunity to comment on final analysis/conclusions as determinative in this fraud case;173-174 confirm missing draft-comment opportunity. Not universal duty to disclose every draft or current-court guilt adoption.'),
 ('positive','statutory_hook','Paragraph98 section72 statutory right to submissions when appointment/proposed appointment of person is at issue. Primary last sentence, not broad right in every investigation or proof section69 third-party sanction jurisdiction.'),
 ('hard_negative','procedural_history_only','Paragraph158 comments request/deadline and perceived phase transition. No adopted general lawful deadline or finding that revised-factual-report comments cured final-analysis nondisclosure.'),
]

def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(c,d):return exact_span(source,packet['case_id'],packet['source_hash'],c,d)
    def local(q):
        c=source.index(q,a,b);return span(c,c+len(q))
    def between(q,end):
        c=source.index(q,a,b);d=source.index(end,c,b);return span(c,c+len(source[c:d].rstrip()))
    outcome,kind,reason=DECISIONS[position-1];contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position==6:contexts.append(span(source.index('[183]'),source.index('[185]')))
    if position==8:contexts.append(span(source.index('[171]'),source.index('[175]')))
    r={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[],'context_spans':contexts}
    def unit(w,claim,suffix='',speaker='current_court',kind_override=None,uncertainty='low'):
        return {'au_id':'r4-au-'+task['target_id'][3:]+suffix,'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind_override or kind,'other_kind':None,'evidence_spans':[w],'attributions':[{'role':'proposition','speaker':speaker,'evidence_span':w}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':uncertainty,'unresolved_reasons':[]}
    if outcome=='hard_negative':r['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif position==2:
        threshold=unit(between('When it makes an order','Thus, the Court'),'For a section69 order following investigation, the Commission must be satisfied of fraud rather than merely having reasonable grounds to believe it.','-threshold')
        threshold['condition_spans']=[local('When it makes an order following an investigation')];threshold['limit_spans']=[local('pursuant to section 69 of the PSEA')]
        c=source.index('Thus, the Court',a,b);proof=unit(span(c,a+len(source[a:b].rstrip())),'The cited Court held that the civil balance-of-probabilities standard applies when the Commission investigator determines whether a candidate committed fraud.','-proof','cited_court')
        proof['limit_spans']=[local("when the Commission's investigator is asked to determine whether fraud has been committed by a candidate")];r['authority_units']=[threshold,proof]
    elif position==4:
        au=unit(between('Nonetheless,','In this case,'),'Under Rule303(3), on AG motion and Court satisfaction that the AG named under(2) is unable or unwilling to act, the Court may substitute another person/body, including the tribunal, as respondent.')
        au['condition_spans']=[local('on a motion by the Attorney General of Canada'),local('where it is satisfied that the Attorney General is unable or unwilling to act as a respondent after having been named under subsection (2)')];au['limit_spans']=[local('the Court may')];r['authority_units']=[au]
    elif position==5:
        notice=unit(between('No matter who the witness is,','A witness must be able'),'A person summoned to an interview must be made aware of suspicions against them and have access to documents relevant to the investigation.','-notice')
        notice['condition_spans']=[local('a person summoned to an interview')];notice['limit_spans']=[local('documents relevant to the investigation')]
        protection=unit(between('A witness must be able','On this point,'),'A witness must be able, if applicable, to invoke Canada Evidence Act section5 protection; the Court observes this no longer seems really necessary because of Charter section13.','-protection',kind_override='statutory_hook',uncertainty='medium')
        protection['condition_spans']=[local('if applicable')];protection['limit_spans']=[local('even though it no longer seems really necessary because of section 13')];r['authority_units']=[notice,protection]
    elif position==6:
        au=unit(between('However,','In fact,'),'For this judicial review, the Court declines to express a definitive opinion on jurisdiction/reasonableness or base its allowance of the application on that contentious issue.',uncertainty='medium')
        au['limit_spans']=[local('today'),local('as part of the appeal in Seck 1')];au['cross_block_refs']=[span(source.index('[183]'),source.index('[185]'))];r['authority_units']=[au]
    elif position==7:
        au=unit(span(a,a+len(source[a:b].rstrip())),'Under PSEA subsection70(2), Commission investigations are informal/expeditious while the Commission retains all PartII Inquiries Act commissioner powers.',uncertainty='medium')
        au['limit_spans']=[local('as informally and expeditiously as possible'),local('under Part II of the')];r['authority_units']=[au]
    elif position==8:
        au=unit(span(a,a+len(source[a:b].rstrip())),'In this alleged-fraud case, the Court treats final Commission report approval without applicant opportunity to comment on final conclusions and analysis as a determinative procedural omission.',uncertainty='medium')
        au['limit_spans']=[local('with respect to the alleged fraud in this case')];au['cross_block_refs']=[span(source.index('[173]'),source.index('[175]'))];r['authority_units']=[au]
    elif position==9:
        c=source.index('Furthermore,',a,b);au=unit(span(c,a+len(source[a:b].rstrip())),'PSEA section72 legislatively recognizes the right to make submissions when a person\'s appointment or proposed appointment is at issue.')
        au['condition_spans']=[local('when the appointment or proposed appointment of a person is at issue')];au['limit_spans']=[local('section 72')];r['authority_units']=[au]
    r['review_trace']=model_review_trace(task,source,packet['source_hash'],r)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-fourteenth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[r]}

if __name__=='__main__':
    freeze_batch();run_batch('fourteenth10',make_proposal,PRODUCER,342,{'authority_units':9,'hard_negatives':3,'unresolved':0})
