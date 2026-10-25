"""Hash-bound model-silver R3 acceptance, separate from R4/R5 readiness."""
import copy
import hashlib
import json
import os
import shutil
from .core import AnnotationError, atomic_write, load_json
from .remediation import ROOT, amendment_heads, assert_lockable, dependencies, digest, registry, risk_review_heads, scan_attribution_risks, validate_amendment, validate_risk_review

AUDITS = [
    'evaluation/reports/plan09_r3_first10_independent_semantic_audit.json',
    'evaluation/reports/plan09_r3_first10_items_02_06_10_reaudit.json',
    'evaluation/reports/plan09_r3_positions_11_49_independent_semantic_audit.json',
    'evaluation/reports/plan09_r3_positions_11_32_final_reaudit.json',
]


def validate_completion(root=ROOT):
    root = root.resolve()
    value = load_json(root/'r3_completion.json')
    if (value['r3_status'] != 'PASS' or value['semantic_gold'] is not False or value['plan10_allowed'] is not False or
        value.get('risk_reviewed_count') != 49 or value.get('risk_pending_count') != 0 or
        value.get('open_severe_finding_count') != 0 or not value.get('all_heads_valid') or not value.get('all_amendments_valid') or
        {x['position'] for x in value.get('accepted_items',[])} != set(range(1,50))):
        raise AnnotationError('invalid R3 acceptance boundary', code='r3_completion_invalid')
    for row in value['bound_artifacts']:
        if digest(root.parents[1]/row['ref']) != row['sha256']:
            raise AnnotationError('R3 acceptance artifact changed: '+row['ref'], code='r3_completion_stale')
    assert_lockable(registry(root), root)
    return value


def main():
    root = ROOT
    pipeline = root.parents[1]
    event_path = root/'registry_history/p09-r3-final-acceptance-v1.json'
    before_path = root/'registry_history/p09-r3-before-final-acceptance-v1.json'
    if event_path.exists() or before_path.exists() or (root/'r3_completion.json').exists():
        raise AnnotationError('R3 closure already checkpointed; do not replay', code='history_invalid')
    audit_values = [load_json(pipeline/ref) for ref in AUDITS]
    first, first_reaudit, rest, final = audit_values
    assert final['decision']=='accept_both_revisions' and first_reaudit['decision']=='accept_all_three_revisions'
    assert all(v['model_only'] and v['semantic_gold'] is False for v in audit_values)
    queue = scan_attribution_risks()
    assert queue==load_json(root/'attribution_risk_queue.json') and len(queue['items'])==49 and queue['pending_model_review_count']==0
    assert digest(root/'attribution_risk_queue.json')==final['snapshot']['queue_sha256']
    assert digest(root/'semantic_defect_registry.json')==final['snapshot']['registry_sha256']
    raw_items = scan_attribution_risks(include_reviews=False)['items']
    heads = risk_review_heads()
    checks = [validate_risk_review(v, items=raw_items) for v in heads]
    amendments = amendment_heads()
    for path in (root/'model_amendments').glob('*.json'):
        validate_amendment(load_json(path))
    by_review = {v['review_id']:v for v in heads}
    by_amendment = {v['amendment_id']:v for v in amendments}
    accepted = {}
    for value, ref in ((first_reaudit,AUDITS[1]), (final,AUDITS[3])):
        for item in value['items']:
            assert item['decision']=='accept'
            head = by_review[item['review_head']]
            assert digest(root/'risk_reviews'/(head['review_id']+'.json'))==item['review_head_sha256']
            assert head['target_id']==item['target_id']==queue['items'][item['position']-1]['target_id']
            if item.get('amendment_head'):
                amendment = by_amendment[item['amendment_head']]
                assert amendment['target_id']==head['target_id']
                assert digest(root/'model_amendments'/(amendment['amendment_id']+'.json'))==item['amendment_head_sha256']
            _, _, _ = dependencies(root, head['case_id'])
            assert head['source_hash']==item.get('source_sha256',value.get('raw_source',{}).get('source_sha256'))
            accepted[item['position']] = {'position':item['position'],'target_id':item['target_id'],'independent_review_ref':ref,'independent_review_sha256':digest(pipeline/ref)}
    for item in first['items']:
        position = item['position']
        if position in accepted:
            continue
        assert item['audit_disposition']=='agree'
        head = load_json(root/queue['items'][position-1]['review_ref'])
        assert head['target_id']==item['target_id']
        assert digest(root/queue['items'][position-1]['review_ref'])==item['audited_record_sha256']
        accepted[position]={'position':position,'target_id':item['target_id'],'independent_review_ref':AUDITS[0],'independent_review_sha256':digest(pipeline/AUDITS[0])}
    # The positions 11–49 audit binds its complete pre-correction queue. Recreate
    # that exact native-newline byte snapshot and replace only accepted 11/32 heads.
    previous_queue = copy.deepcopy(queue)
    for position in (11,32):
        item = previous_queue['items'][position-1]
        head = load_json(root/item['review_ref'])
        ref = 'risk_reviews/'+head['supersedes_review_id']+'.json'
        item.update(review_ref=ref,outcome=load_json(root/ref)['outcome'])
    serialized=(json.dumps(previous_queue,ensure_ascii=False,indent=2)+'\n').replace('\n',os.linesep)
    assert hashlib.sha256(serialized.encode()).hexdigest()==rest['snapshot']['queue_sha256']
    for position,target,decision,*_ in rest['per_item']:
        if position in accepted:
            continue
        assert decision=='agree' and target==queue['items'][position-1]['target_id']
        accepted[position]={'position':position,'target_id':target,'independent_review_ref':AUDITS[2],'independent_review_sha256':digest(pipeline/AUDITS[2])}
    assert set(accepted)==set(range(1,50))
    saved = {str(p):digest(p) for folder in ('model_proposals','model_amendments','risk_reviews') for p in (root/folder).rglob('*.json')}
    before = registry()
    after = copy.deepcopy(before)
    changed=[]
    for position,fid in ((11,'P09-R3-AUDIT-11'),(32,'P09-S01')):
        finding=next(f for f in after['findings'] if f['finding_id']==fid)
        item=next(i for i in final['items'] if i['position']==position)
        assert finding['status']=='pending_reaudit' and finding['target_id']==item['target_id']
        finding.update(status='closed',resolution_amendment_id=item['amendment_head'],resolution_amendment_sha256=item['amendment_head_sha256'],independent_review_ref=AUDITS[3],independent_review_sha256=digest(pipeline/AUDITS[3]),closure_event_ref=event_path.relative_to(root).as_posix(),acceptance_boundary='model_only_model_silver')
        changed.append(fid)
    assert_lockable(after)
    assert not any(f['severity']=='severe' and f['status']!='closed' for f in after['findings'])
    # Preserve pre-update registry byte-for-byte, with original encoding/newlines.
    from pathlib import Path
    before_path.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/'semantic_defect_registry.json', before_path)
    event={'artifact_type':'Plan09ImmutableRegistryClosureEvent','event_id':'p09-r3-final-acceptance-v1','before_registry_ref':before_path.relative_to(root).as_posix(),'before_registry_sha256':digest(before_path),'after_registry':after,'changed_findings':changed,'independent_review_ref':AUDITS[3],'independent_review_sha256':digest(pipeline/AUDITS[3]),'semantic_gold':False,'plan10_allowed':False}
    atomic_write(event_path,event)
    atomic_write(root/'semantic_defect_registry.json',after)
    assert all(digest(Path(p))==sha for p,sha in saved.items())
    paths=[root/'semantic_defect_registry.json',root/'attribution_risk_queue.json',before_path,event_path]+[pipeline/ref for ref in AUDITS]+[Path(p) for p in saved]
    completion={'artifact_type':'Plan09R3Completion','r3_status':'PASS','model_only':True,'semantic_gold':False,'evaluation_against':'model_silver','risk_reviewed_count':49,'risk_pending_count':0,'open_severe_finding_count':0,'all_heads_valid':True,'all_amendments_valid':True,'accepted_items':[accepted[p] for p in sorted(accepted)],'head_validation':checks,'bound_artifacts':[{'ref':p.relative_to(pipeline).as_posix(),'sha256':digest(p)} for p in paths],'closed_findings':changed,'originals_and_history_unchanged':True,'plan10_allowed':False,'remaining_gates':{'R4':'incomplete_157_missing_targets','R5':'pending_final_audit'},'missing_target_count':157}
    atomic_write(root/'r3_completion.json',completion)
    validate_completion()
    from .progress import build_progress
    old=load_json(pipeline/'reports/plan09_model_silver_progress.latest.json')
    progress=build_progress(root,'R3 accepted; R4 incomplete (157 missing targets); R5 final audit pending. Model-silver only; Plan10 locked.')
    assert [(c['case_id'],c['missing_target_ids']) for c in progress['cases']]==[(c['case_id'],c['missing_target_ids']) for c in old['cases']]
    atomic_write(pipeline/'reports/plan09_model_silver_progress.latest.json',progress)
    print('PASS R3=49/49 severe_open=0 closed=S01,AUDIT11 missing=157 Plan10=false')


if __name__=='__main__':
    main()
