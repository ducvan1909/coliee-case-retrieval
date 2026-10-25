"""Freeze and run one ten-target R4 batch without changing earlier cohorts."""
from .core import atomic_write,load_json,validate_model_proposal
from .remediation import ROOT,dependencies,digest,effective_proposals,proposal_records
from .r4 import checkpoint,rebuild_manifest,publish_progress
from .r3_completion import validate_completion


def run_batch(name,make_proposal,producer,before_reviewed,batch_counts,*,target_count=10):
    assert target_count in (7,10)
    pipeline=ROOT.parents[1];bid=f'p09-r4-099980-{name}-sol-v1'
    path=ROOT/'r4_batches'/(bid+'.json')
    packet,source,policy=dependencies(ROOT,'099980')
    if path.exists():batch=load_json(path)
    else:
        progress_path=pipeline/'reports/plan09_model_silver_progress.latest.json'
        prior=load_json(progress_path)
        assert prior['expected_target_count']==369 and prior['reviewed_target_count']==before_reviewed
        ids=next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980')[:target_count]
        assert len(ids)==target_count
        saved={str(p.relative_to(pipeline)):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews','r4_model_proposals','r4_batches','registry_history') for p in (ROOT/folder).rglob('*.json')}
        for p in list(ROOT.glob('r4_*validation.json'))+list(ROOT.glob('r4_*verification.json'))+[ROOT/n for n in ('r3_completion.json','attribution_risk_queue.json','semantic_defect_registry.json','terra_proposal_manifest.json')]+list((pipeline/'reports').glob('plan09_r4_*model_review.md')):
            saved[str(p.relative_to(pipeline))]=digest(p)
        batch={'artifact_type':'Plan09R4FrozenMissingBatch','batch_id':bid,'case_id':'099980','source_hash':packet['source_hash'],'target_ids':ids,'selection':'first_10_missing_target_ids_in_current_progress_order','before_progress':prior,'before_progress_sha256':digest(progress_path),'before_model_manifest':load_json(ROOT/'model_proposal_manifest.json'),'before_model_manifest_sha256':digest(ROOT/'model_proposal_manifest.json'),'preserved_artifacts':saved,'producer':producer,'semantic_gold':False,'independent_acceptance':False,'plan10_allowed':False}
        atomic_write(path,batch)
    assert len(batch['target_ids'])==target_count and batch['source_hash']==packet['source_hash']
    if target_count==7:assert before_reviewed==362 and len(next(c['missing_target_ids'] for c in batch['before_progress']['cases'] if c['case_id']=='099980'))==7
    tasks={t['target_id']:t for t in packet['tasks']};results=[]
    for position,tid in enumerate(batch['target_ids'],1):
        destination=ROOT/'r4_model_proposals/099980'/f'p09-r4-099980-{name}-{position:02d}-gpt61sol-v1.json'
        proposal=load_json(destination) if destination.exists() else make_proposal(tasks[tid],packet,source,position,batch)
        assert proposal['target_reviews'][0]['target_id']==tid
        checks=checkpoint(proposal,batch);review=proposal['target_reviews'][0]
        results.append({**checks,'position':position,'target_id':tid,'target_span':review['reviewed_span'],'context_spans':review['context_spans'],'outcome':review['model_outcome'],'authority_units':review['authority_units'],'hard_negative':review['hard_negative'],'unresolved_reasons':review['unresolved_reasons'],'reason':review['notes']})
        print(f'PASS R4 {name} position={position} outcome={review["model_outcome"]} resumed={checks["resumed"]}',flush=True)
    assert all(digest(pipeline/ref)==sha for ref,sha in batch['preserved_artifacts'].items())
    validate_completion();rebuild_manifest()
    manifest=load_json(ROOT/'model_proposal_manifest.json')
    assert manifest['proposals'][:len(batch['before_model_manifest']['proposals'])]==batch['before_model_manifest']['proposals']
    for row in proposal_records():
        proposal=load_json(ROOT/row['proposal_ref']);p,t,pol=dependencies(ROOT,proposal['case_id']);validate_model_proposal(proposal,p,t,pol)
    reviews=[r for p in effective_proposals() for r in p['target_reviews']]
    progress=publish_progress();prior=batch['before_progress']
    assert len(reviews)==before_reviewed+target_count and progress['missing_target_count']==369-before_reviewed-target_count
    before_missing=set(next(c['missing_target_ids'] for c in prior['cases'] if c['case_id']=='099980'))
    after_missing=set(next(c['missing_target_ids'] for c in progress['cases'] if c['case_id']=='099980'))
    assert before_missing-after_missing==set(batch['target_ids']) and not after_missing-before_missing
    observed={'authority_units':sum(len(r['authority_units']) for r in results),'hard_negatives':sum(r['hard_negative'] is not None for r in results),'unresolved':sum(r['outcome']=='unresolved' for r in results)}
    assert observed==batch_counts
    totals={'authority_units':progress['authority_unit_count'],'hard_negatives':progress['hard_negative_count'],'unresolved':progress['unresolved_target_count']}
    assert totals=={'authority_units':prior['authority_unit_count']+batch_counts['authority_units'],'hard_negatives':prior['hard_negative_count']+batch_counts['hard_negatives'],'unresolved':prior['unresolved_target_count']+batch_counts['unresolved']}
    assert progress['gates']=={'r3_pass':True,'r4_coverage_complete':before_reviewed+target_count==369,'r5_final_audit_pass':False,'plan10_allowed':False}
    report={'artifact_type':'Plan09R4TenTargetModelReviewValidation' if target_count==10 else 'Plan09R4FinalSevenModelReviewValidation','batch_ref':path.relative_to(ROOT).as_posix(),'producer':producer,'semantic_gold':False,'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False,'results':results,'batch_counts':batch_counts,'effective_counts':totals,'reviewed_before':before_reviewed,'reviewed_after':before_reviewed+target_count,'expected_target_count':369,'missing_before':369-before_reviewed,'missing_after':369-before_reviewed-target_count,'existing_targets_unchanged':True,'prior_batches_unchanged':True,'r3_bound_artifacts_unchanged':True,'preserved_artifact_count':len(batch['preserved_artifacts']),'all_proposals_valid':True,'effective_overlay_valid':True}
    atomic_write(ROOT/f'r4_{name}_validation.json',report)
    print(f'PASS R4 {name} targets={target_count} batch={batch_counts} coverage={before_reviewed+target_count}/369 missing={369-before_reviewed-target_count} R3=unchanged Plan10=false')
