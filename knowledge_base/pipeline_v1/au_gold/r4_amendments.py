"""Immutable audit-bound R4 overlays, separate from Terra/R3."""
import copy,re
from pathlib import Path
from .core import AnnotationError,atomic_write,canonical_hash,load_json,validate_model_proposal
from .remediation import ROOT,digest,dependencies

def validate(a,root=ROOT):
    root=Path(root);pipeline=root.parents[1]
    required={'artifact_type','amendment_id','supersedes_proposal_ref','supersedes_proposal_sha256','case_id','target_id','source_hash','producer','audit_ref','audit_sha256','replacement_review','semantic_gold','independent_acceptance','r5_pass','plan10_allowed'}
    def need(ok):
        if not ok:raise AnnotationError('R4 amendment dependency/contract mismatch',code='r4_amendment_invalid')
    need(set(a)==required and a['artifact_type']=='R4ModelReviewAmendment' and re.fullmatch(r'[a-zA-Z0-9_-]+',a['amendment_id']))
    need(all(a[k] is False for k in ('semantic_gold','independent_acceptance','r5_pass','plan10_allowed')))
    path=(root/a['supersedes_proposal_ref']).resolve();need(path.is_relative_to((root/'r4_model_proposals').resolve()));need(digest(path)==a['supersedes_proposal_sha256'])
    rows=[r for r in load_json(root/'model_proposal_manifest.json')['proposals'] if r['proposal_ref']==a['supersedes_proposal_ref']];need(len(rows)==1 and rows[0]['proposal_sha256']==a['supersedes_proposal_sha256'])
    q=load_json(path);need((q['case_id'],q['source_hash'],q['target_reviews'][0]['target_id'])==(a['case_id'],a['source_hash'],a['target_id']))
    ap=(pipeline/a['audit_ref']).resolve();need(ap.is_relative_to((pipeline/'evaluation/reports').resolve()));need(digest(ap)==a['audit_sha256'])
    audit=load_json(ap);items=[i for i in audit['items'] if i['target_id']==a['target_id'] and i['decision']=='disagree' and i['severity']=='moderate'];need(len(items)==1 and audit['scope']['batch_id']==q['batch_id'])
    r=a['replacement_review'];i=items[0];need(r['target_id']==a['target_id'] and r['model_outcome']==i['proposed_outcome'])
    if r['model_outcome']=='positive':need(len(r['authority_units'])==1 and r['authority_units'][0]['kind']==i['proposed_kind'] and r['authority_units'][0]['attributions'][0]['speaker']==i['proposed_attribution'])
    if r['model_outcome']=='hard_negative':need(r['hard_negative']['reason']==i['proposed_reason'])
    q=copy.deepcopy(q);q['producer']=a['producer'];q['target_reviews']=[r];p,s,pol=dependencies(root,a['case_id']);checks=validate_model_proposal(q,p,s,pol)
    return {**checks,'amendment_id':a['amendment_id'],'audit_sha256':a['audit_sha256'],'supersedes_proposal_sha256':a['supersedes_proposal_sha256'],'independent_acceptance':False,'r5_pass':False,'plan10_allowed':False}

def apply(values,root=ROOT):
    root=Path(root);by_id={p['proposal_id']:p for p in values};seen=set()
    for path in sorted((root/'r4_model_amendments').glob('*.json')):
        if path.name.endswith('.validation.json'):continue
        a=load_json(path);checks=validate(a,root)
        if load_json(path.with_suffix('.validation.json'))!=checks:raise AnnotationError('R4 overlay sidecar mismatch',code='r4_amendment_invalid')
        key=(a['case_id'],a['target_id'])
        if key in seen:raise AnnotationError('R4 overlay fork forbidden',code='r4_amendment_invalid')
        seen.add(key);q=load_json(root/a['supersedes_proposal_ref']);by_id[q['proposal_id']]['target_reviews']=[copy.deepcopy(a['replacement_review'])]
    return values

def checkpoint(a,root=ROOT):
    root=Path(root);checks=validate(a,root);path=root/'r4_model_amendments'/(a['amendment_id']+'.json')
    for other in path.parent.glob('*.json'):
        if other.name.endswith('.validation.json') or other==path:continue
        old=load_json(other)
        if (old['case_id'],old['target_id'])==(a['case_id'],a['target_id']):raise AnnotationError('R4 overlay fork forbidden',code='r4_amendment_invalid')
    if path.exists():
        if canonical_hash(load_json(path))!=canonical_hash(a):raise AnnotationError('immutable overlay collision',code='r4_amendment_invalid')
    else:atomic_write(path,a)
    sidecar=path.with_suffix('.validation.json')
    if sidecar.exists():
        if load_json(sidecar)!=checks:raise AnnotationError('R4 overlay sidecar mismatch',code='r4_amendment_invalid')
    else:atomic_write(sidecar,checks)
    return checks

def effective_count_delta(root=ROOT):
    delta={'authority_units':0,'hard_negatives':0,'unresolved':0}
    for path in (Path(root)/'r4_model_amendments').glob('*.json'):
        if path.name.endswith('.validation.json'):continue
        a=load_json(path);validate(a,root);old=load_json(Path(root)/a['supersedes_proposal_ref'])['target_reviews'][0];new=a['replacement_review']
        delta['authority_units']+=len(new['authority_units'])-len(old['authority_units']);delta['hard_negatives']+=int(new['hard_negative'] is not None)-int(old['hard_negative'] is not None);delta['unresolved']+=int(new['model_outcome']=='unresolved')-int(old['model_outcome']=='unresolved')
    return delta
