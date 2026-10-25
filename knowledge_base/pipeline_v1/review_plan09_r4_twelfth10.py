"""Twelfth R4 batch, model-silver only."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
BATCH_ID='p09-r4-099980-twelfth10-sol-v1'

def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    pp=pipeline/'reports/plan09_model_silver_progress.latest.json';prior=load_json(pp)
    assert (prior['expected_target_count'],prior['reviewed_target_count'],prior['missing_target_count'])==(369,322,47)
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
    build=load_json(ROOT/'au_annotation_build_manifest.json');packet=load_json(ROOT/next(r for r in build['cases'] if r['case_id']=='099980')['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==len(set(ids))==10
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(pp),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch);return batch

DECISIONS=[
 ('hard_negative','fact_only','Paragraph192 describes reputational harm and distress in the costs discussion. No independent legal test, damages entitlement, or finding that Web dissemination occurred.'),
 ('positive','holding','Court considers all respondent arguments because applicant counsel did not object, while reserving possible remedy/costs consequences. Case-specific discretion, not a universal waiver of fairness or tribunal standing limits.'),
 ('positive','procedural_rule','Separate cited Sopinka-majority propositions on investigator delegation and CHRC filtering/fairness. CHRA statutory context only; current Court distinguishes PSEA section69. No imported exemption from fairness or criminal-style merits hearing.'),
 ('hard_negative','fact_only','Investigation interview chronology, representation and oath facts. Applicant exclusion is factual in this target; no standalone oath entitlement or jurisdiction holding. Exclude next heading.'),
 ('positive','statutory_hook','Separate PSDPA section9 disciplinary consequences and FAA section12 deputy-head powers. Conditional wrongdoing, appropriate discipline, permissive employer action; no automatic dismissal or Commission third-party sanction jurisdiction.'),
 ('positive','holding','Court reiterates that public-confidence aims cannot justify the unfair means used by the investigator in this case. Narrow case-specific fairness conclusion, not a categorical illegality finding for all private-email interception or a finding applicant innocent.'),
 ('positive','procedural_rule','Rule303(2) naming of Attorney General when no person can be named under subsection1. Extract intact rule notwithstanding earlier suppressed procedural list. No conclusion that Commission can never be substituted: paragraph24 preserves subsection3.'),
 ('hard_negative','party_argument_only','Respondent advocacy from another case is recounted and criticized; quoted too-late/guilt and reasonable corrective measures are not adopted court propositions.'),
 ('hard_negative','fact_only','Other appointment-process reference facts and agency fraud finding. Not applicant guilt adjudication or an adopted legal fraud definition.'),
 ('positive','procedural_rule','Court compares greater legitimate expectations of persons suspected of fraud under PSEA section69 with discrimination investigations. Not a general ban on CHRA analogies or automatic entitlement to any specified hearing procedure.'),
]

def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(c,d):return exact_span(source,packet['case_id'],packet['source_hash'],c,d)
    def local(q):
        c=source.index(q,a,b);return span(c,c+len(q))
    def between(q,end):
        c=source.index(q,a,b);d=source.index(end,c,b);return span(c,c+len(source[c:d].rstrip()))
    outcome,kind,reason=DECISIONS[position-1];contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position==3:contexts.append(span(source.index('[109]'),source.index('[114]')))
    if position==6:contexts.append(span(source.index('[190]'),source.index('[197]')))
    r={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[],'context_spans':contexts}
    def unit(w,claim,suffix='',speaker='current_court',uncertainty='low'):
        return {'au_id':'r4-au-'+task['target_id'][3:]+suffix,'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[w],'attributions':[{'role':'proposition','speaker':speaker,'evidence_span':w}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':uncertainty,'unresolved_reasons':[]}
    if outcome=='hard_negative':r['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif position==2:
        au=unit(span(a,a+len(source[a:b].rstrip())),'Given no objection by applicant counsel at the hearing, the Court chose to consider all respondent arguments, reserving possible consequences in its discretion over remedies and costs.')
        au['condition_spans']=[local("counsel for the applicant did not object at the hearing before the Court to counsel for the respondent's argument on the issues of natural justice")];au['limit_spans']=[local('with, nevertheless, the possible consequences from the point of view of the exercise of discretion that is conferred upon me in matters of remedies and costs')];r['authority_units']=[au]
    elif position==3:
        delegation=unit(between('The investigator, in conducting the investigation','Section 36(3)'), 'In the cited CHRA context, the investigator acts as an extension of the Commission preparing its report, not an independent evidentiary witness; administrative tribunals may delegate some work.','-delegation','cited_court','medium')
        c=source.index('The other course of action',a,b)
        filtering=unit(span(c,a+len(source[a:b].rstrip())),'For the CHRC filtering function described in the cited decision, the Commission assesses whether evidence reasonably supports proceeding to a tribunal rather than weighing merits as at a judicial hearing; no preliminary formal hearing or formal natural-justice rules were intended, but procedural fairness remains required.','-filtering','cited_court','medium')
        filtering['condition_spans']=[local('whether there is a reasonable basis in the evidence for proceeding to the next stage')];filtering['limit_spans']=[local("in view of the nature of the Commission's function and giving effect to the statutory provisions referred to")]
        for au in (delegation,filtering):
            au['attributions'].append({'role':'proposition','speaker':'cited_court','evidence_span':between('Justice Sopinka','The investigator, in conducting')})
            au['cross_block_refs']=[span(source.index('[111]'),a),span(source.index('[113]'),source.index('[114]'))]
        r['authority_units']=[delegation,filtering]
    elif position==5:
        psdpa=unit(between('However, pursuant to section 9','That leads me'),'Under PSDPA section9, independently of punishment authorized by law, a public servant who commits wrongdoing is subject to appropriate disciplinary action, including termination.','-psdpa')
        psdpa['condition_spans']=[local('if he or she commits a wrongdoing')];psdpa['limit_spans']=[local('appropriate disciplinary action'),local('independently of any punishment authorized by law')]
        c=source.index('That leads me',a,b);faa=unit(span(c,a+len(source[a:b].rstrip())),'FAA section12 confers on deputy heads general power to discipline and terminate public servants working under their authority.','-faa')
        faa['limit_spans']=[local('public servants who work under their authority')];r['authority_units']=[psdpa,faa]
    elif position==6:
        au=unit(between('I repeat,','A blind institutional machine'),'In this case, ensuring public confidence in institutions cannot justify the unfair means used by the investigator.',uncertainty='medium')
        au['limit_spans']=[local('in a context where we are talking about ensuring public confidence in our institutions'),local('that were used by the investigator in this case')];au['cross_block_refs']=[span(source.index('[196]'),source.index('[197]'))];r['authority_units']=[au]
    elif position==7:
        w=between('In such a case,','This is set out');au=unit(w,'When no person can be named as respondent under Rule303(1), the applicant shall name the Attorney General of Canada under Rule303(2).')
        au['condition_spans']=[local('where there are no persons that can be named under subsection (1)')];au['limit_spans']=[local('subsection (2) of Rule 303')];au['cross_block_refs']=[span(source.index('[24]'),source.index('[25]'))];r['authority_units']=[au]
    elif position==10:
        c=source.index('Furthermore,',a,b);au=unit(span(c,a+len(source[a:b].rstrip())),'A person suspected of fraud in a PSEA section69 investigation has much greater legitimate expectations than in a discrimination case.',uncertainty='medium')
        au['limit_spans']=[local('a person who is suspected of fraud in an investigation conducted under the authority of section 69 of the PSEA'),local('than in a discrimination case')];r['authority_units']=[au]
    r['review_trace']=model_review_trace(task,source,packet['source_hash'],r)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-twelfth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[r]}

if __name__=='__main__':
    freeze_batch();run_batch('twelfth10',make_proposal,PRODUCER,322,{'authority_units':8,'hard_negatives':4,'unresolved':0})
