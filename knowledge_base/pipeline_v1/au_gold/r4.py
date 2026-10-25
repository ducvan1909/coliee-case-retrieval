"""Single-target append-only R4 checkpoints; separate from immutable Terra/R3."""
from pathlib import Path
import re
from .core import AnnotationError, atomic_write, canonical_hash, load_json, validate_model_proposal
from .remediation import ROOT, dependencies, digest, proposal_records

MANIFEST='model_proposal_manifest.json'


def checkpoint(proposal, batch, root=ROOT, *, refresh_progress=True):
    root=Path(root)
    batch_id=batch.get('batch_id','')
    if not re.fullmatch(r'p09-r4-[a-zA-Z0-9_-]+',batch_id) or canonical_hash(load_json(root/'r4_batches'/(batch_id+'.json')))!=canonical_hash(batch):
        raise AnnotationError('frozen R4 batch dependency changed',code='checkpoint_batch_mismatch')
    packet,source,policy=dependencies(root,proposal['case_id'])
    checks=validate_model_proposal(proposal,packet,source,policy)
    target=proposal['target_reviews'][0]['target_id']
    if proposal['artifact_type']!='ModelAUProposal' or proposal['batch_id']!=batch['batch_id'] or proposal['case_id']!=batch['case_id'] or proposal['source_hash']!=batch['source_hash'] or target not in batch['target_ids']:
        raise AnnotationError('R4 target must belong to frozen missing-target batch',code='checkpoint_batch_mismatch')
    relative=Path('r4_model_proposals')/proposal['case_id']/(proposal['proposal_id']+'.json')
    destination=root/relative
    records=proposal_records(root)
    owners=[]
    for row in records:
        existing=load_json(root/row['proposal_ref'])
        if existing['case_id']==proposal['case_id'] and any(r['target_id']==target for r in existing['target_reviews']):
            owners.append(row)
    if owners:
        if len(owners)!=1 or owners[0]['proposal_ref']!=relative.as_posix() or canonical_hash(load_json(destination))!=canonical_hash(proposal):
            raise AnnotationError('target already belongs to another checkpoint',code='checkpoint_duplicate_target')
        sidecar=destination.with_suffix('.validation.json')
        if not sidecar.exists():atomic_write(sidecar,checks)
        elif load_json(sidecar)!=checks:raise AnnotationError('validation sidecar changed',code='model_proposal_tampered')
        if refresh_progress:publish_progress(root)
        return {**checks,'proposal_ref':relative.as_posix(),'resumed':True}
    # Crash between durable proposal and manifest is recovered from exact validated
    # bytes. Never replace an existing proposal with a new label or model identity.
    resumed=destination.exists()
    if resumed:
        if canonical_hash(load_json(destination))!=canonical_hash(proposal):
            raise AnnotationError('immutable R4 proposal collision',code='checkpoint_duplicate_proposal')
    else:
        atomic_write(destination,proposal)
    sidecar=destination.with_suffix('.validation.json')
    if not sidecar.exists():atomic_write(sidecar,checks)
    elif load_json(sidecar)!=checks:raise AnnotationError('validation sidecar changed',code='model_proposal_tampered')
    manifest=load_json(root/MANIFEST) if (root/MANIFEST).exists() else {'artifact_type':'ModelAUProposalManifest','manifest_version':'model-au-proposal-manifest-v1','evaluation_against':'model_silver','semantic_gold':False,'independent_acceptance':False,'plan10_allowed':False,'proposals':[]}
    review=proposal['target_reviews'][0]
    row={'proposal_id':proposal['proposal_id'],'case_id':proposal['case_id'],'batch_id':proposal['batch_id'],'proposal_ref':relative.as_posix(),'proposal_sha256':digest(destination),'validation_ref':sidecar.relative_to(root).as_posix(),'reviewed_target_count':1,'authority_unit_count':len(review['authority_units']),'hard_negative_count':int(review['hard_negative'] is not None),'unresolved_target_count':int(review['model_outcome']=='unresolved'),'producer':proposal['producer']}
    manifest['proposals'].append(row)
    manifest['proposal_count']=len(manifest['proposals'])
    for key in ('reviewed_target_count','authority_unit_count','hard_negative_count','unresolved_target_count'):
        manifest[key]=sum(r[key] for r in manifest['proposals'])
    atomic_write(root/MANIFEST,manifest)
    if refresh_progress:publish_progress(root)
    return {**checks,'proposal_ref':relative.as_posix(),'resumed':resumed}


def publish_progress(root=ROOT):
    from .progress import build_progress
    progress=build_progress(root,'R3 accepted; R4 model-silver append in progress; remaining coverage and R5 independent final audit required. Plan10 locked.')
    if not progress['missing_target_count']:progress['blocker']='R3 accepted; R4 model-silver coverage complete. R5 independent final audit required; semantic acceptance pending. Plan10 locked.'
    atomic_write(Path(root).parents[1]/'reports/plan09_model_silver_progress.latest.json',progress)
    return progress


def rebuild_manifest(root=ROOT):
    """Recompute derived counts from hash-bound checkpoints; never repair labels."""
    root=Path(root)
    value=load_json(root/MANIFEST)
    before=canonical_hash(value)
    seen=set()
    for row in value['proposals']:
        path=root/row['proposal_ref']
        if digest(path)!=row['proposal_sha256']:
            raise AnnotationError('immutable proposal hash changed',code='model_proposal_tampered')
        proposal=load_json(path)
        packet,source,policy=dependencies(root,proposal['case_id'])
        checks=validate_model_proposal(proposal,packet,source,policy)
        if load_json(root/row['validation_ref'])!=checks:
            raise AnnotationError('validation sidecar changed',code='model_proposal_tampered')
        review=proposal['target_reviews'][0]
        key=(proposal['case_id'],review['target_id'])
        if key in seen:raise AnnotationError('duplicate R4 target ownership',code='checkpoint_duplicate_target')
        seen.add(key)
        row.update(reviewed_target_count=1,authority_unit_count=len(review['authority_units']),hard_negative_count=int(review['hard_negative'] is not None),unresolved_target_count=int(review['model_outcome']=='unresolved'),producer=proposal['producer'])
    value['proposal_count']=len(value['proposals'])
    for key in ('reviewed_target_count','authority_unit_count','hard_negative_count','unresolved_target_count'):
        value[key]=sum(row[key] for row in value['proposals'])
    changed=canonical_hash(value)!=before
    if changed:atomic_write(root/MANIFEST,value)
    return {'valid':True,'proposal_count':value['proposal_count'],'manifest_rebuild_changed':changed}
