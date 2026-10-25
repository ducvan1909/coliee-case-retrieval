"""Final seven R4 targets, coverage only, model-silver."""
from .au_gold.core import atomic_write,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest,effective_proposals,proposal_records
from .au_gold.r4_batch import run_batch
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
BATCH_ID='p09-r4-099980-final7-sol-v1'

def freeze_batch():
    pipeline=ROOT.parents[1];path=ROOT/'r4_batches'/(BATCH_ID+'.json')
    if path.exists():return load_json(path)
    pp=pipeline/'reports/plan09_model_silver_progress.latest.json';prior=load_json(pp)
    assert (prior['expected_target_count'],prior['reviewed_target_count'],prior['missing_target_count'])==(369,362,7)
    ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')
    build=load_json(ROOT/'au_annotation_build_manifest.json');packet=load_json(ROOT/next(r for r in build['cases'] if r['case_id']=='099980')['packet_ref'])
    saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
    for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):saved[str(p.relative_to(pipeline))]=digest(p)
    assert len(ids)==len(set(ids))==7
    batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':BATCH_ID,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'all_7_remaining_missing_target_ids_in_current_progress_order','frozen_before_raw_source_review':True,'before_progress':prior,'before_progress_sha256':digest(pp),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':PRODUCER,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,batch);return batch

DECISIONS=[
 ('positive','procedural_rule','Paragraph100 expressly attributes greater procedural protection to cited Court under former PSEA6(2)/(3). Current Court compares differently worded66/67 selection-error provisions. Not a blanket fraud oral-hearing entitlement or proof all schemes identical.'),
 ('hard_negative','editorial','Paragraph198 praises counsel and directs criticisms to institution/client. No standalone legal immunity, counsel-liability standard or client-instruction rule.'),
 ('hard_negative','procedural_history_only','Paragraph18 records other agency decision/report and order not personally affecting applicant. Not Court validation of that order or a fraud/sanction legal rule.'),
 ('hard_negative','party_argument_only','Paragraph30 applicant notice/evidence/fairness and jurisdiction arguments, including conditional If Court accepts. Not adopted current-court holding in this target; later adoption elsewhere must not be imported.'),
 ('positive','statutory_hook','Paragraph170 investigator letter states Public Service Employment Regulations19 publication discretion, balancing public disclosure interest/privacy and consultation if discretion considered. Preserve agency-correspondence speaker and conditional future disclosure. Not actual publication, Court endorsement of letter fraud finding or unrestricted personal-data disclosure.'),
 ('hard_negative','procedural_history_only','Paragraph140 factual report transmittal and Court reservation about contacting candidate mother. Not universal duty/no-duty to interview relatives or final relevance ruling.'),
 ('positive','statutory_hook','Paragraph82 separates PSDPA minister environment duty, Treasury Board sector-wide code duty, and chief-executive portion/code-consistency duty. Opening continuum rhetoric excluded. No substitute role for PSEA Commission or criminal guilt inference.'),
]

def make_proposal(task,packet,source,position,batch):
    a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(c,d):return exact_span(source,packet['case_id'],packet['source_hash'],c,d)
    def local(q):
        c=source.index(q,a,b);return span(c,c+len(q))
    def between(q,end):
        c=source.index(q,a,b);d=source.index(end,c,b);return span(c,c+len(source[c:d].rstrip()))
    outcome,kind,reason=DECISIONS[position-1];contexts=[span(max(0,a-1200),min(len(source),b+1200))]
    r={'target_id':task['target_id'],'review_complete':True,'reviewed_span':span(a,b),'authority_units':[],'hard_negative':None,'notes':[reason],'model_outcome':outcome,'unresolved_reasons':[],'context_spans':contexts}
    def unit(w,claim,suffix='',speaker='current_court',uncertainty='low'):
        return {'au_id':'r4-au-'+task['target_id'][3:]+suffix,'owner_target_id':task['target_id'],'owner_block_id':task['owner_block_id'],'claim_text':claim,'kind':kind,'other_kind':None,'evidence_spans':[w],'attributions':[{'role':'proposition','speaker':speaker,'evidence_span':w}],'condition_spans':[],'exception_spans':[],'limit_spans':[],'cross_block_refs':[],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':uncertainty,'unresolved_reasons':[]}
    if outcome=='hard_negative':r['hard_negative']={'reason':kind,'reviewed_span':span(a,b),'provenance':PROVENANCE,'notes':[reason]}
    elif position==1:
        au=unit(between('In <FRAGMENT_SUPPRESSED>','Those provisions'),'The cited Court held that the scheme under former PSEA subsections6(2)/(3) favoured greater procedural protection.',speaker='cited_court',uncertainty='medium')
        au['limit_spans']=[local('subsections 6(2) and (3) of the former')];r['authority_units']=[au]
    elif position==5:
        au=unit(between('As previously advised,','Given that the investigation'),'The investigator letter describes Regulations19 discretion to disclose investigation personal information, considering whether disclosure public interest outweighs privacy and providing consultation/comments if publication discretion is considered.',speaker='commission_correspondence',uncertainty='medium')
        au['condition_spans']=[local('whether the public interest in disclosure outweighs privacy interests'),local('Should the PSC consider exercising its discretion with respect to disclosure of personal information')];au['limit_spans']=[local('the PSC has the discretionary authority'),local('obtained in the course of an investigation')];r['authority_units']=[au]
    elif position==7:
        minister=unit(between('In accordance with the PSDPA,','Furthermore,'),'Under PSDPA, the Minister responsible for Treasury Board Secretariat must encourage an environment conducive to wrongdoing disclosure.','-minister')
        tb=unit(between('Furthermore,','Chief executives'),'The Treasury Board must establish a code of conduct applicable to the entire public sector.','-treasury-board')
        tb['limit_spans']=[local('applicable to the entire public sector')]
        c=source.index('Chief executives',a,b);chief=unit(span(c,a+len(source[a:b].rstrip())),'Chief executives must establish codes for their responsible public-sector portions consistent with the Treasury Board code.','-chief-executives')
        chief['limit_spans']=[local('applicable to the portion of the public sector for which they are responsible'),local('These codes must be consistent with the code of conduct established by the Treasury Board')];r['authority_units']=[minister,tb,chief]
    r['review_trace']=model_review_trace(task,source,packet['source_hash'],r)
    return {'artifact_type':'ModelAUProposal','schema_version':'model-au-proposal-v1','proposal_id':f'p09-r4-099980-final7-{position:02d}-gpt61sol-v1','packet_id':packet['packet_id'],'case_id':packet['case_id'],'source_hash':packet['source_hash'],'producer':PRODUCER,'prompt_version':'r4-au-annotation-prompt-v1','batch_id':batch['batch_id'],'status':'model_proposed','target_reviews':[r]}

def complete_coverage(output_name='r4_coverage_completion.json'):
    from .au_gold.r3_completion import validate_completion
    from .au_gold.core import validate_model_proposal
    from .au_gold.remediation import dependencies
    build=load_json(ROOT/'au_annotation_build_manifest.json');expected=set()
    for row in build['cases']:
        p=load_json(ROOT/row['packet_ref']);expected.update((p['case_id'],t['target_id']) for t in p['tasks'])
    actual=[(p['case_id'],r['target_id']) for p in effective_proposals() for r in p['target_reviews']]
    assert len(actual)==len(set(actual))==len(expected)==369 and set(actual)==expected
    validate_completion();records=proposal_records();bound=[];legacy_without_sidecar=[]
    for row in records:
        q=load_json(ROOT/row['proposal_ref']);p,s,pol=dependencies(ROOT,q['case_id']);checks=validate_model_proposal(q,p,s,pol)
        refs=[row['proposal_ref']];sidecar=row.get('validation_ref',row['proposal_ref']+'.validation.json')
        if (ROOT/sidecar).exists():refs.append(sidecar)
        else:
            assert 'validation_ref' not in row
            legacy_without_sidecar.append({'proposal_ref':row['proposal_ref'],'fresh_validation':checks,'existing_sidecar_present':False,'original_unchanged':True})
        for ref in refs:bound.append({'ref':'outputs/plan09_au_gold_v1/'+ref,'sha256':digest(ROOT/ref)})
    progress=load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
    assert all(c['coverage_complete'] and not c['missing_target_ids'] for c in progress['cases'])
    assert progress['gates']=={'r3_pass':True,'r4_coverage_complete':True,'r5_final_audit_pass':False,'plan10_allowed':False}
    for ref in ('outputs/plan09_au_gold_v1/model_proposal_manifest.json','outputs/plan09_au_gold_v1/terra_proposal_manifest.json','outputs/plan09_au_gold_v1/r3_completion.json','outputs/plan09_au_gold_v1/r4_final7_validation.json','outputs/plan09_au_gold_v1/r4_batches/'+BATCH_ID+'.json','reports/plan09_model_silver_progress.latest.json'):
        bound.append({'ref':ref,'sha256':digest(ROOT.parents[1]/ref)})
    b=freeze_batch();assert all(digest(ROOT.parents[1]/ref)==sha for ref,sha in b['preserved_artifacts'].items())
    value={'artifact_type':'Plan09R4CoverageCompletion','date':'2026-10-06','valid':True,'r4_coverage_complete':True,'model_only':True,'evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False,'expected_target_count':369,'reviewed_target_count':369,'missing_target_count':0,'canonical_duplicate_target_count':0,'exact_expected_case_target_set_verified':True,'all_cases_coverage_complete':True,'cases':progress['cases'],'effective_counts':{'authority_units':progress['authority_unit_count'],'hard_negatives':progress['hard_negative_count'],'unresolved':progress['unresolved_target_count']},'r4_checkpoint_count':157,'all_proposals_valid':True,'preserved_artifact_count':len(b['preserved_artifacts']),'all_preservation_hashes_match':True,'gates':progress['gates'],'bound_artifacts':bound,'remaining_gate':'R5 independent final audit required. Coverage includes unresolved model reviews, not semantic acceptance or human gold; Plan10 locked.'}
    value.update(r4_all_sidecars_hash_bound=True,legacy_proposals_without_sidecar=legacy_without_sidecar,legacy_sidecar_absence_count=len(legacy_without_sidecar),legacy_sidecars_not_created_or_modified=True)
    if output_name!='r4_coverage_completion.json':
        value.update(coverage_revision=2,supersedes_ref='outputs/plan09_au_gold_v1/r4_coverage_completion.json',supersedes_sha256=digest(ROOT/'r4_coverage_completion.json'))
        value['bound_artifacts'].extend({'ref':str(p.relative_to(ROOT.parents[1])).replace('\\','/'),'sha256':digest(p)} for p in sorted((ROOT/'r4_model_amendments').glob('*.json')))
    atomic_write(ROOT/output_name,value)
    print('PASS R4 coverage exact369/369 missing0 duplicate0 R5=false Plan10=false',flush=True)

if __name__=='__main__':
    freeze_batch();run_batch('final7',make_proposal,PRODUCER,362,{'authority_units':5,'hard_negatives':4,'unresolved':0},target_count=7);complete_coverage()
