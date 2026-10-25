"""Only the two fourth10 moderate findings; immutable audit-bound overlays."""
import copy
from .au_gold.core import atomic_write,canonical_hash,load_json,exact_span,model_review_trace
from .au_gold.remediation import ROOT,digest,dependencies,effective_proposals
from .au_gold.r4_amendments import checkpoint
from .review_plan09_r4_first10 import PRODUCER,PROVENANCE
AUDIT='evaluation/reports/plan09_r4_fourth10_independent_semantic_audit.json'
TARGETS=['at-36d2799e80bf0e3f5421c6cf','at-3bf2d5382a3dbb34d161b87b']
FROZEN='r4_fourth10_correction_frozen.json'

def freeze():
    path=ROOT/FROZEN
    if path.exists():return load_json(path)
    pipeline=ROOT.parents[1];pp=pipeline/'reports/plan09_model_silver_progress.latest.json';progress=load_json(pp)
    assert (progress['reviewed_target_count'],progress['missing_target_count'],progress['authority_unit_count'],progress['hard_negative_count'],progress['unresolved_target_count'])==(369,0,187,185,10)
    folders=('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history')
    files=[p for folder in folders for p in (ROOT/folder).rglob('*.json')]+list(ROOT.glob('r4_*.json'))+[ROOT/n for n in ('model_proposal_manifest.json','terra_proposal_manifest.json','r3_completion.json','semantic_defect_registry.json','attribution_risk_queue.json')]+list((pipeline/'evaluation/reports').glob('plan09*'))+list((pipeline/'reports').glob('plan09_r4_*model_review.md'))
    saved={str(p.relative_to(pipeline)).replace('\\','/'):digest(p) for p in files if p.is_file()}
    reviews={p['case_id']+':'+r['target_id']:canonical_hash(r) for p in effective_proposals() for r in p['target_reviews']}
    snapshot=ROOT/'r4_fourth10_before_correction_progress.json';atomic_write(snapshot,progress);assert digest(snapshot)==digest(pp)
    value={'artifact_type':'R4Fourth10FrozenCorrection','target_ids':TARGETS,'audit_ref':AUDIT,'audit_sha256':digest(pipeline/AUDIT),'before_progress':progress,'before_progress_snapshot_ref':str(snapshot.relative_to(pipeline)).replace('\\','/'),'before_progress_sha256':digest(pp),'before_effective_review_hashes':reviews,'preserved_artifacts':saved,'model_only':True,'r5_pass':False,'plan10_allowed':False}
    atomic_write(path,value);return value

def make(position):
    p,s,_=dependencies(ROOT,'099980');tid=TARGETS[position-1];task=next(t for t in p['tasks'] if t['target_id']==tid)
    ref=f'r4_model_proposals/099980/p09-r4-099980-fourth10-{7 if position==1 else 10:02d}-gpt61sol-v1.json';q=load_json(ROOT/ref);r=copy.deepcopy(q['target_reviews'][0]);a,b=task['target_span']['start_char'],task['target_span']['end_char']
    def span(c,d):return exact_span(s,p['case_id'],p['source_hash'],c,d)
    def local(v):
        c=s.index(v,a,b);return span(c,c+len(v))
    r.update(authority_units=[],hard_negative=None,unresolved_reasons=[])
    if position==1:
        reason='Correct moderate audit finding: explicit current-court characterization in paragraph35 survives later reservation. Narrow jurisdictional/vital legal question merits correct interpretation, not final jurisdiction outcome or settled agency-review standard.'
        c=s.index('With respect, in my view,',a,b);phrase='interpretation of the PSEA.';d=s.index(phrase,c,b)+len(phrase);w=span(c,d)
        r.update(model_outcome='positive',notes=[reason]);r['context_spans'].append(span(s.index('[183]'),s.index('[185]')))
        r['authority_units']=[{'au_id':'r4-corrected-au-'+tid[3:],'owner_target_id':tid,'owner_block_id':task['owner_block_id'],'claim_text':'The Court characterizes the section69 power issue concerning other candidates and third parties where alleged fraud had no practical appointment effect as a jurisdictional question, if not a legal question vital to the public-service appointment system, meriting correct statutory interpretation.','kind':'standard_of_review','other_kind':None,'evidence_spans':[w],'attributions':[{'role':'proposition','speaker':'current_court','evidence_span':w}],'condition_spans':[],'exception_spans':[],'limit_spans':[local('other candidates and third parties'),local('where fraud may have occurred but had no practical effect'),local('a question of jurisdiction, if not a question of law')],'cross_block_refs':[span(s.index('[93]'),s.index('[94]')),span(s.index('[183]'),s.index('[185]'))],'overlap_disposition':'none','duplicate_of':None,'status':'model_proposed','provenance':PROVENANCE,'notes':[reason],'uncertainty':'medium','unresolved_reasons':[]}]
    else:
        reason='Correct moderate audit finding: paragraph62 is explicitly applicant advocacy, no adoption within target. Paragraph63 postpones merits review. Do not infer personal gain as a universal fraud element.'
        r.update(model_outcome='hard_negative',notes=[reason]);r['hard_negative']={'reason':'party_argument_only','reviewed_span':r['reviewed_span'],'provenance':PROVENANCE,'notes':[reason]}
    r['review_trace']=model_review_trace(task,s,p['source_hash'],r)
    return {'artifact_type':'R4ModelReviewAmendment','amendment_id':f'r4-fourth10-moderate-correction-{position:02d}-gpt61sol-v1','supersedes_proposal_ref':ref,'supersedes_proposal_sha256':digest(ROOT/ref),'case_id':p['case_id'],'target_id':tid,'source_hash':p['source_hash'],'producer':PRODUCER,'audit_ref':AUDIT,'audit_sha256':digest(ROOT.parents[1]/AUDIT),'replacement_review':r,'semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}

def main():
    frozen=freeze()
    for n in (1,2):print('PASS correction',n,checkpoint(make(n)),flush=True)
    from .au_gold.r4 import rebuild_manifest,publish_progress
    from .au_gold.r3_completion import validate_completion
    from .review_plan09_r4_final7 import complete_coverage
    rebuild=rebuild_manifest();assert not rebuild['manifest_rebuild_changed'];progress=publish_progress();validate_completion()
    assert (progress['reviewed_target_count'],progress['missing_target_count'],progress['authority_unit_count'],progress['hard_negative_count'],progress['unresolved_target_count'])==(369,0,188,186,8)
    assert all(digest(ROOT.parents[1]/ref)==sha for ref,sha in frozen['preserved_artifacts'].items())
    after={p['case_id']+':'+r['target_id']:canonical_hash(r) for p in effective_proposals() for r in p['target_reviews']}
    changed=[key for key in after if after[key]!=frozen['before_effective_review_hashes'][key]];assert set(changed)=={'099980:'+t for t in TARGETS}
    complete_coverage('r4_coverage_completion.after_fourth10_corrections.json')
    report={'artifact_type':'R4Fourth10CorrectionValidation','valid':True,'target_ids':TARGETS,'effective_changed_target_ids':changed,'all_other_367_reviews_unchanged':True,'preserved_artifact_count':len(frozen['preserved_artifacts']),'all_preservation_hashes_match':True,'raw_manifest_unchanged':True,'audit_ref':AUDIT,'audit_sha256':frozen['audit_sha256'],'effective_counts_before':{'authority_units':187,'hard_negatives':185,'unresolved':10},'effective_counts_after':{'authority_units':188,'hard_negatives':186,'unresolved':8},'reviewed_target_count':369,'missing_target_count':0,'gates':progress['gates'],'semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False,'reaudit_required':True}
    atomic_write(ROOT/'r4_fourth10_correction_validation.json',report);print('PASS exactly2 overlays,369/369,U10->8 R5=false Plan10=false')

if __name__=='__main__':main()
