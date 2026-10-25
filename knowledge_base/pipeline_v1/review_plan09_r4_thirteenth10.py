"""Thirteenth R4 batch, model-silver only."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
BATCH_ID='p09-r4-099980-thirteenth10-sol-v1'

def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    pp=pipeline/'reports/plan09_model_silver_progress.latest.json';prior=load_json(pp)
    assert (prior['expected_target_count'],prior['reviewed_target_count'],prior['missing_target_count'])==(369,332,37)
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:10]
    build=load_json(ROOT/'au_annotation_build_manifest.json');packet=load_json(ROOT/next(r for r in build['cases'] if r['case_id']=='099980')['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==len(set(ids))==10
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(pp),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch);return batch

DECISIONS=[
 ('positive','holding','Paragraph136 links the late change in investigation treatment to breach of fairness/legitimate hopes warranting Court intervention. Not a legal holding that applicant had no right to notice; that wording describes unequal treatment. Exclude citation tail and next heading.'),
 ('hard_negative','procedural_history_only','Paragraph159 reproduces revised investigation purpose and allegations. Notice/report allegations and unchanged wording are not Court fraud finding or a legal jurisdiction test.'),
 ('positive','fact_pattern_rule','Paragraph53 develops Court fraud analysis after dictionary comparison: advantage/deception, intent, good-faith error and advantage-supported inference. Primary Court analysis only, not dictionary quotation. Advantage supports inference, not conclusive presumption or proof applicant guilty.'),
 ('positive','fact_pattern_rule','Paragraph58 describes Personnel Psychology Centre Commission decision, not a binding current-court guilt ruling. Separate false-reference/bad-faith proposition from quoted section69 appointment-process link. Suppressed gaps remain; do not invent missing reasoning or acquit applicant.'),
 ('hard_negative','procedural_history_only','Paragraph134 investigation notice and suspected document authorship are allegations against candidate, not established fraud or Court adoption of criminal reasonable-grounds test.'),
 ('positive','procedural_rule','Paragraph42 explicitly quotes Justice Stratas. Separate broad remedial discretion/remittal possibility from impartial open-minded redetermination and possible effect of overly aggressive merits submissions. May disable is not automatic disqualification; remittal not mandatory.'),
 ('hard_negative','procedural_history_only','Paragraph17 recounts impugned agency corrective order and transmittal requirements. Not Court endorsement of lawful third-party sanction powers or general permission-before-appointment rule. Exclude next heading.'),
 ('hard_negative','fact_only','Paragraph132 accepts case-specific hearsay/reliability and nondisclosure facts. No general inadmissibility rule for hearsay, mandatory corroboration test or innocence finding; paragraph157 separately formulates fairness disclosure requirement.'),
 ('positive','procedural_rule','Paragraph55 separately distinguishes error/fraud and states civil balance-of-probabilities rather than criminal proof. Historical candidate-only agency practice is excluded from primary witnesses; it is not a jurisdictional limit on all third-party investigations.'),
 ('positive','procedural_rule','Paragraph194 Court expresses view that accused public servants should know suspicions and defend themselves before Commission final verdict. Preserve tentative It-seems-to-me wording and Commission/fraud scope; not a mandatory particular hearing form or applicant innocence holding.'),
]

def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(c,d):return exact_span(source,packet['case_id'],packet['source_hash'],c,d)
    def local(q):
        c=source.index(q,a,b);return span(c,c+len(q))
    def between(q,end):
        c=source.index(q,a,b);d=source.index(end,c,b);return span(c,c+len(source[c:d].rstrip()))
    outcome,kind,reason=DECISIONS[position-1];contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    if position==4:contexts.append(span(source.index('[51]'),source.index('[62]')))
    if position==8:contexts.append(span(source.index('[157]'),source.index('[158]')))
    if position==9:contexts.append(span(source.index('[110]'),source.index('[111]')))
    if position==10:contexts.append(span(source.index('[196]'),source.index('[197]')))
    r={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[],'context_spans':contexts}
    def unit(w,claim,suffix='',speaker='current_court',kind_override=None,uncertainty='low'):
        return {'au_id':'r4-au-'+task['target_id'][3:]+suffix,'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind_override or kind,'other_kind':None,'evidence_spans':[w],'attributions':[{'role':'proposition','speaker':speaker,'evidence_span':w}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':uncertainty,'unresolved_reasons':[]}
    if outcome=='hard_negative':r['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif position==1:
        au=unit(between('As will be seen below,',' ('),'In this investigation, the investigator changed the rules at the end to the detriment of fairness and the applicant\'s legitimate hopes, warranting Court intervention.',uncertainty='medium')
        au['limit_spans']=[local('at the very end of the investigation process'),local("to the detriment of her duty to act fairly and the applicant's legitimate hopes")];r['authority_units']=[au]
    elif position==3:
        c=source.index('First, fraud',a,b);au=unit(span(c,a+len(source[a:b].rstrip())),'The Court explains fraud as deception to gain an advantage with intent to deceive, distinguishes good-faith error, and treats evidence of gained advantage as supporting an inference of fraudulent intent.',uncertainty='medium')
        au['condition_spans']=[local('If it was in good faith'),local('the evidence that the author does gain some advantage from the deceit')];au['limit_spans']=[local('supports the inference')];r['authority_units']=[au]
    elif position==4:
        badfaith=unit(between('However, in','The Act does not contain'),'In the Personnel Psychology Centre decision described here, the Commission held that false references from a third party alone do not establish candidate fraud without evidence of bad faith.','-badfaith','cited_commission_decision',uncertainty='medium')
        badfaith['condition_spans']=[local('in the absence of evidence of bad faith')];badfaith['limit_spans']=[local('the candidate committed fraud')]
        nexus=unit(between('According to section 69,','. . .'),'The quoted Commission summary states that a section69 fraud determination requires linking the misconduct to an appointment process.','-nexus','cited_commission_decision',kind_override='statutory_hook',uncertainty='medium')
        nexus['condition_spans']=[local('it must be possible to link the misconduct to an appointment process')]
        for au in (badfaith,nexus):au['attributions'].append({'role':'proposition','speaker':'cited_commission_decision','evidence_span':local('(Public Service Commission - Investigation Report Summary - 2007 - Unfounded - Personnel Psychology Centre, see http://www.psc -cfp.gc.ca)')})
        r['authority_units']=[badfaith,nexus]
    elif position==6:
        remedies=unit(between('When a court allows','If that happens,'),'A court allowing judicial review has broad discretion in remedy selection/design; remittal to the tribunal for redetermination is one available, common remedy.','-remedies','cited_court')
        remedies['condition_spans']=[local('When a court allows an application for judicial review')];remedies['limit_spans']=[local('One remedy, quite common')]
        c=source.index('If that happens,',a,b);impartial=unit(span(c,a+len(source[a:b].rstrip())),'If the matter is remitted, the tribunal must redetermine and appear to redetermine impartially with an open mind; overly intense/aggressive merits submissions may impair that ability and public confidence.','-impartial','cited_court')
        impartial['condition_spans']=[local('If that happens'),local('Submissions by the tribunal in a judicial review proceeding that descend too far, too intensely, or too aggressively into the merits')];impartial['limit_spans']=[local('may disable the tribunal')]
        for au in (remedies,impartial):au['attributions'].append({'role':'proposition','speaker':'cited_court','evidence_span':local('Justice Stratas reiterated the following at paragraph 16')})
        r['authority_units']=[remedies,impartial]
    elif position==9:
        distinction=unit(between('An "error"','Moreover,'),'Error must not be confused with fraud, or vice versa.','-distinction')
        proof=unit(between('Moreover,','The jurisprudence'),'The applicable fraud burden is the civil balance of probabilities, not the criminal burden.','-proof')
        proof['cross_block_refs']=[span(source.index('[110]'),source.index('[111]'))];r['authority_units']=[distinction,proof]
    elif position==10:
        c=source.index('It seems to me',a,b);au=unit(span(c,a+len(source[a:b].rstrip())),'The Court expresses the view that public servants accused of fraud have the right to know suspicions against them and defend themselves before the Commission\'s final verdict.',uncertainty='medium')
        au['limit_spans']=[local('It seems to me'),local('public servants accused of fraud'),local('before the final verdict from the Commission')];au['cross_block_refs']=[span(source.index('[196]'),source.index('[197]'))];r['authority_units']=[au]
    r['review_trace']=model_review_trace(task,source,packet['source_hash'],r)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-thirteenth10-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[r]}

if __name__=='__main__':
    freeze_batch();run_batch('thirteenth10',make_proposal,PRODUCER,332,{'authority_units':9,'hard_negatives':4,'unresolved':0})
