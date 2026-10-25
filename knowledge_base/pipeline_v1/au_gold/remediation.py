"""Plan 09 semantic quarantine and immutable model review amendments."""
from __future__ import annotations
import copy
import hashlib
import re
from pathlib import Path
from .core import AnnotationError, atomic_write, load_json, validate_schema, validate_model_proposal, exact_span
from ..source_contract import open_source

ROOT = Path(__file__).resolve().parents[1] / 'outputs/plan09_au_gold_v1'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def registry(root=ROOT):
    path = Path(root) / 'semantic_defect_registry.json'
    if not path.is_file():
        raise AnnotationError('semantic registry required', code='semantic_registry_missing')
    value = load_json(path)
    if value.get('artifact_type') != 'Plan09SemanticDefectRegistry' or not isinstance(value.get('findings'), list):
        raise AnnotationError('invalid semantic registry', code='semantic_registry_invalid')
    return value

def assert_lockable(value, root=ROOT):
    if not isinstance(value, dict) or not isinstance(value.get('findings'), list):
        raise AnnotationError('semantic registry required', code='semantic_registry_missing')
    opened = [x['finding_id'] for x in value['findings'] if x['severity'] == 'severe' and x['status'] != 'closed']
    if opened:
        raise AnnotationError('open severe findings: ' + ', '.join(opened), code='silver_semantic_quarantine')
    for finding in value['findings']:
        if finding['severity']!='severe' or finding['status']!='closed':
            continue
        amendment_id = finding.get('resolution_amendment_id')
        review_ref = finding.get('independent_review_ref')
        if not isinstance(amendment_id,str) or not amendment_id or not isinstance(review_ref,str) or not review_ref:
            raise AnnotationError('severe closure requires amendment and independent review records', code='silver_semantic_closure_unverified')
        root = Path(root)
        amendment_path = root/'model_amendments'/(amendment_id+'.json')
        review_path = Path(review_ref)
        if not review_path.is_absolute():
            review_path = Path(__file__).resolve().parents[1]/review_path
        if not amendment_path.is_file() or not review_path.is_file():
            raise AnnotationError('severe closure records are missing', code='silver_semantic_closure_unverified')
        amendment = load_json(amendment_path)
        validate_amendment(amendment,root)
        replacement = amendment['replacement_review']
        if (amendment['finding_id'],amendment['supersedes_proposal_id'],amendment['target_id']) != (finding['finding_id'],finding['proposal_id'],finding['target_id']) or replacement.get('model_outcome')=='unresolved':
            raise AnnotationError('severe closure resolution is not final', code='silver_semantic_closure_unverified')
        audit = load_json(review_path)
        accepted = [x for x in audit.get('items',[]) if isinstance(x,dict) and x.get('target_id')==finding['target_id'] and x.get('decision')=='accept']
        if (digest(review_path)!=finding.get('independent_review_sha256') or
            digest(amendment_path)!=finding.get('resolution_amendment_sha256') or
            len(accepted)!=1 or accepted[0].get('amendment_head')!=amendment_id or
            accepted[0].get('amendment_head_sha256')!=digest(amendment_path) or
            amendment_id not in {x['amendment_id'] for x in amendment_heads(root)}):
            raise AnnotationError('severe closure acceptance/head hash is unverified', code='silver_semantic_closure_unverified')

def dependencies(root, case_id):
    root = Path(root)
    build = load_json(root / 'au_annotation_build_manifest.json')
    row = next(x for x in build['cases'] if x['case_id'] == case_id)
    packet = load_json(root / row['packet_ref'])
    source = open_source(build['source_store'], case_id, packet['source_hash'])
    policy = load_json(Path(__file__).resolve().parents[1] / 'policies/au_annotation_policy.v1.json')
    return packet, source, policy

def lineage_heads(values, directory, id_key, parent_key, parent_hash_key, identity_keys):
    """Resolve explicit hash-bound linear histories; reject forks/cycles/duplicate roots."""
    directory = Path(directory)
    by_id = {x[id_key]:x for x in values}
    if len(by_id)!=len(values):
        raise AnnotationError('duplicate history ID',code='history_invalid')
    children={}
    for value in values:
        parent=value.get(parent_key)
        if (parent_key in value)!=(parent_hash_key in value):
            raise AnnotationError('history parent and hash required together',code='history_invalid')
        if parent is None:continue
        if not isinstance(parent,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',parent) or parent not in by_id or parent==value[id_key] or not (directory/(parent+'.json')).is_file():
            raise AnnotationError('history parent missing',code='history_invalid')
        previous=by_id[parent]
        if any(previous[k]!=value[k] for k in identity_keys) or digest(directory/(parent+'.json'))!=value[parent_hash_key]:
            raise AnnotationError('history parent identity/hash changed',code='history_invalid')
        if parent in children:
            raise AnnotationError('history fork forbidden',code='history_invalid')
        children[parent]=value[id_key]
    heads=[x for x in values if x[id_key] not in children]
    visited=set();owners=set()
    for head in heads:
        owner=tuple(head[k] for k in identity_keys)
        if owner in owners:raise AnnotationError('multiple history heads for identity',code='history_invalid')
        owners.add(owner);node=head
        while True:
            if node[id_key] in visited:raise AnnotationError('history cycle or shared ancestor',code='history_invalid')
            visited.add(node[id_key]);parent=node.get(parent_key)
            if parent is None:break
            node=by_id[parent]
    if len(visited)!=len(values):raise AnnotationError('history cycle',code='history_invalid')
    return heads

def amendment_heads(root=ROOT):
    directory=Path(root)/'model_amendments'
    values=[load_json(p) for p in sorted(directory.glob('*.json'))]
    return lineage_heads(values,directory,'amendment_id','supersedes_amendment_id','supersedes_amendment_sha256',('supersedes_proposal_id','target_id','case_id','source_hash'))

def risk_review_heads(root=ROOT):
    directory=Path(root)/'risk_reviews'
    values=[load_json(p) for p in sorted(directory.glob('*.json'))]
    return lineage_heads(values,directory,'review_id','supersedes_review_id','supersedes_review_sha256',('proposal_id','target_id','au_id','case_id','source_hash'))

def validate_amendment(value, root=ROOT):
    root = Path(root)
    validate_schema(value, 'au_model_amendment.v1.json')
    has_parent='supersedes_amendment_id' in value
    if has_parent != ('supersedes_amendment_sha256' in value) or has_parent != (value['schema_version']=='au-model-amendment-v2'):
        raise AnnotationError('v2 amendment requires explicit predecessor/hash',code='history_invalid')
    if has_parent:
        predecessor_path=root/'model_amendments'/(value['supersedes_amendment_id']+'.json')
        predecessor=load_json(predecessor_path)
        if digest(predecessor_path)!=value['supersedes_amendment_sha256'] or any(predecessor[k]!=value[k] for k in ('supersedes_proposal_id','supersedes_proposal_sha256','target_id','case_id','source_hash')):
            raise AnnotationError('amendment predecessor changed',code='history_invalid')
    records = load_json(root / 'terra_proposal_manifest.json')['proposals']
    matches = [x for x in records if x['proposal_id'] == value['supersedes_proposal_id']]
    if len(matches) != 1:
        raise AnnotationError('superseded proposal must be canonical', code='amendment_owner_invalid')
    path = root / matches[0]['proposal_ref']
    original = load_json(path)
    if digest(path) != value['supersedes_proposal_sha256']:
        raise AnnotationError('original proposal changed', code='amendment_original_changed')
    if (original['case_id'], original['source_hash']) != (value['case_id'], value['source_hash']):
        raise AnnotationError('source dependency mismatch', code='amendment_source_mismatch')
    target = value['target_id']
    if sum(x['target_id'] == target for x in original['target_reviews']) != 1 or value['replacement_review']['target_id'] != target:
        raise AnnotationError('replacement target mismatch', code='amendment_target_mismatch')
    packet, source, policy = dependencies(root, value['case_id'])
    # Reuse structural span/ownership checks; reviewer identity stays explicit on
    # the amendment. The adapter producer is not an execution/provenance claim.
    adapter = copy.deepcopy(original)
    adapter['target_reviews'] = [copy.deepcopy(value['replacement_review'])]
    submitted_review = value['replacement_review']
    for item in submitted_review.get('authority_units',[]) + ([submitted_review['hard_negative']] if submitted_review.get('hard_negative') is not None else []):
        provenance = item.get('provenance',{})
        if provenance.get('source_type')!='model' or provenance.get('producer_id') != 'model:'+value['reviewer']['model']:
            raise AnnotationError('submitted amendment provenance must match model reviewer',code='amendment_provenance_invalid')
    for review in adapter['target_reviews']:
        provenance = {'source_type':'model','producer_id':'model:gpt-5.6-terra','prompt_version':policy['terra_prompt_version']}
        if review['hard_negative'] is not None:
            review['hard_negative']['provenance'] = provenance
        for au in review['authority_units']:
            au['provenance'] = provenance
        from .core import model_review_trace
        task = next(x for x in packet['tasks'] if x['target_id'] == target)
        trace = model_review_trace(task, source, value['source_hash'], review)
        trace['region_id'] = review['review_trace']['region_id']
        trace['region_fingerprint'] = review['review_trace']['region_fingerprint']
        # Verify submitted checksum first, then adapter checksum after provenance.
        submitted = value['replacement_review']
        expected = model_review_trace(task, source, value['source_hash'], submitted)
        if any(submitted['review_trace'].get(k) != expected[k] for k in ('task_id','target_id','source_hash','target_span_checksum','decision_checksum')):
            raise AnnotationError('amendment decision checksum mismatch', code='amendment_trace_invalid')
        review['review_trace'] = trace
    checks = validate_model_proposal(adapter, packet, source, policy)
    for span in value['context_spans']:
        from .core import verify_span
        verify_span(span, source, value['case_id'], value['source_hash'])
    finding = next((x for x in registry(root)['findings'] if x['finding_id'] == value['finding_id']), None)
    if finding is None or (finding['proposal_id'], finding['target_id'], finding['source_hash']) != (value['supersedes_proposal_id'], target, value['source_hash']):
        raise AnnotationError('finding dependency mismatch', code='amendment_finding_mismatch')
    return {**checks, 'amendment_id':value['amendment_id'], 'reviewer':value['reviewer'], 'semantic_gold':False}

def checkpoint_amendment(value, root=ROOT):
    root = Path(root)
    checks = validate_amendment(value, root)
    path = root / 'model_amendments' / (value['amendment_id'] + '.json')
    if path.exists():
        raise AnnotationError('immutable amendment already exists', code='amendment_duplicate')
    previous = [x for x in amendment_heads(root) if (x['supersedes_proposal_id'],x['target_id'])==(value['supersedes_proposal_id'],value['target_id'])]
    if previous and value.get('supersedes_amendment_id')!=previous[0]['amendment_id']:
        raise AnnotationError('must supersede current amendment head',code='amendment_duplicate')
    if not previous and value.get('supersedes_amendment_id'):
        raise AnnotationError('unexpected amendment predecessor',code='history_invalid')
    atomic_write(path, value)
    return checks

def proposal_records(root=ROOT):
    root=Path(root)
    records=load_json(root/'terra_proposal_manifest.json')['proposals']
    path=root/'model_proposal_manifest.json'
    if path.exists():
        additional=load_json(path)['proposals']
        for row in additional:
            if digest(root/row['proposal_ref'])!=row['proposal_sha256']:
                raise AnnotationError('R4 proposal hash changed',code='model_proposal_tampered')
        records=records+additional
    return records

def effective_proposals(root=ROOT):
    root = Path(root)
    values = [load_json(root / x['proposal_ref']) for x in proposal_records(root)]
    for value in values:
        if value.get('artifact_type')=='ModelAUProposal':
            packet,source,policy=dependencies(root,value['case_id'])
            validate_model_proposal(value,packet,source,policy)
    by_id = {x['proposal_id']:x for x in values}
    for path in sorted((root/'model_amendments').glob('*.json')):
        validate_amendment(load_json(path),root)
    for value in amendment_heads(root):
        proposal = by_id[value['supersedes_proposal_id']]
        proposal['target_reviews'] = [copy.deepcopy(value['replacement_review']) if x['target_id'] == value['target_id'] else x for x in proposal['target_reviews']]
    from .r4_amendments import apply
    return apply(values,root)

CUE = re.compile(r'\b(submits?|argues?|contends?|according to|testimony|investigator|officer|board|counsel|court of appeal|first instance)\b', re.I)

def scan_attribution_risks(root=ROOT, *, include_reviews=True):
    root = Path(root)
    records = load_json(root / 'terra_proposal_manifest.json')['proposals']
    items = []
    for record in sorted(records, key=lambda x:x['proposal_id']):
        proposal = load_json(root / record['proposal_ref'])
        packet, source, policy = dependencies(root, proposal['case_id'])
        validate_model_proposal(proposal, packet, source, policy)
        for review in proposal['target_reviews']:
            for au in review['authority_units']:
                cues = []
                for span in au['evidence_spans']:
                    for match in CUE.finditer(source[span['start_char']:span['end_char']]):
                        a = span['start_char'] + match.start()
                        cues.append(exact_span(source, proposal['case_id'], proposal['source_hash'], a, a+len(match.group())))
                if cues:
                    reasons = ['reporting_or_speaker_cue']
                    if au['kind'] == 'holding' and any(x['speaker'] == 'current_court' for x in au['attributions']):
                        reasons.append('holding_current_court_reporting_risk')
                    items.append({'proposal_id':proposal['proposal_id'], 'proposal_sha256':digest(root/record['proposal_ref']), 'case_id':proposal['case_id'], 'source_hash':proposal['source_hash'], 'target_id':review['target_id'], 'au_id':au['au_id'], 'reason_codes':reasons, 'cue_spans':cues, 'status':'pending_model_review'})
    if include_reviews:
        seen = set()
        for value in risk_review_heads(root):
            path=root/'risk_reviews'/(value['review_id']+'.json')
            validate_risk_review(value, root, items=items)
            key = (value['proposal_id'], value['target_id'], value['au_id'])
            if key in seen:
                raise AnnotationError('duplicate risk review', code='risk_review_duplicate')
            seen.add(key)
            item = next(x for x in items if (x['proposal_id'],x['target_id'],x['au_id']) == key)
            item.update(status='model_reviewed_pending_independent_audit', outcome=value['outcome'], review_ref=path.relative_to(root).as_posix())
    return {'artifact_type':'Plan09AttributionRiskQueue','scanner_version':'reporting-cues-v1','semantic_gold':False,'labels_changed':False,'item_count':len(items),'pending_model_review_count':sum(x['status']=='pending_model_review' for x in items),'items':items,'limitations':['Cue matching routes risk only; claim faithfulness, distant speaker and omissions require source review.']}

def validate_risk_review(value, root=ROOT, *, items=None):
    from .core import verify_span
    root = Path(root)
    required = {'artifact_type','review_id','proposal_id','proposal_sha256','case_id','source_hash','target_id','au_id','reviewer','outcome','reason','target_span','context_spans','amendment_id','semantic_gold'}
    optional={'supersedes_review_id','supersedes_review_sha256'}
    if not required.issubset(value) or set(value)-required-optional or value['artifact_type'] != 'Plan09AttributionRiskReview' or value['semantic_gold'] is not False:
        raise AnnotationError('invalid risk review contract', code='risk_review_invalid')
    if ('supersedes_review_id' in value)!=('supersedes_review_sha256' in value):
        raise AnnotationError('review predecessor/hash required together',code='history_invalid')
    if 'supersedes_review_id' in value:
        parent=value['supersedes_review_id']
        if not isinstance(parent,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',parent):raise AnnotationError('invalid predecessor ID',code='history_invalid')
        path=root/'risk_reviews'/(parent+'.json');previous=load_json(path)
        if digest(path)!=value['supersedes_review_sha256'] or any(previous[k]!=value[k] for k in ('proposal_id','proposal_sha256','case_id','source_hash','target_id','au_id')):
            raise AnnotationError('review predecessor identity/hash changed',code='history_invalid')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',value['review_id']) or value['outcome'] not in {'keep','amendment','unresolved'} or not isinstance(value['reason'],str) or not value['reason'].strip():
        raise AnnotationError('invalid risk review decision', code='risk_review_invalid')
    reviewer = value['reviewer']
    if set(reviewer) != {'source_type','reviewer_id','model'} or reviewer['source_type'] != 'model' or not reviewer['model'] or not reviewer['reviewer_id']:
        raise AnnotationError('model provenance required', code='risk_review_invalid')
    items = items if items is not None else scan_attribution_risks(root,include_reviews=False)['items']
    matches = [x for x in items if all(x[k] == value[k] for k in ('proposal_id','proposal_sha256','case_id','source_hash','target_id','au_id'))]
    if len(matches) != 1:
        raise AnnotationError('risk review source/proposal dependency changed', code='risk_review_dependency')
    packet,source,_ = dependencies(root,value['case_id'])
    task = next(x for x in packet['tasks'] if x['target_id']==value['target_id'])
    span = value['target_span']
    if any(span.get(k)!=task['target_span'][k] for k in ('start_char','end_char','case_id','source_hash')):
        raise AnnotationError('risk review target mismatch', code='risk_review_dependency')
    if not value['context_spans'] or not any(x['start_char'] <= span['start_char'] and x['end_char'] >= span['end_char'] and (x['start_char'] < span['start_char'] or x['end_char'] > span['end_char']) for x in value['context_spans']):
        raise AnnotationError('neighbor context required', code='risk_review_context')
    for witness in [span]+value['context_spans']:
        verify_span(witness,source,value['case_id'],value['source_hash'])
    if value['outcome']=='keep':
        if value['amendment_id'] is not None:
            raise AnnotationError('keep cannot amend', code='risk_review_invalid')
    else:
        aid = value['amendment_id']
        if not isinstance(aid,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',aid):
            raise AnnotationError('changed decision requires amendment', code='risk_review_invalid')
        amendment = load_json(root/'model_amendments'/(aid+'.json'))
        validate_amendment(amendment,root)
        if any(amendment[a]!=value[b] for a,b in (('supersedes_proposal_id','proposal_id'),('supersedes_proposal_sha256','proposal_sha256'),('target_id','target_id'),('source_hash','source_hash'),('reviewer','reviewer'))):
            raise AnnotationError('risk amendment dependency mismatch', code='risk_review_dependency')
        if (amendment['replacement_review']['model_outcome']=='unresolved') != (value['outcome']=='unresolved'):
            raise AnnotationError('risk amendment outcome mismatch', code='risk_review_invalid')
    return {'review_id':value['review_id'],'valid':True,'semantic_gold':False}

def checkpoint_risk_review(value, root=ROOT):
    root = Path(root)
    checks = validate_risk_review(value,root)
    queue = scan_attribution_risks(root)
    pending = [x for x in queue['items'] if x['status']=='pending_model_review']
    if not pending or any(value[k]!=pending[0][k] for k in ('proposal_id','target_id','au_id')):
        raise AnnotationError('checkpoint must follow pending queue order', code='risk_review_order')
    path = root/'risk_reviews'/(value['review_id']+'.json')
    if path.exists():
        raise AnnotationError('immutable review already exists',code='risk_review_duplicate')
    atomic_write(path,value)
    # Immutable record is authoritative; derived snapshots can be rebuilt after interruption.
    atomic_write(root/'attribution_risk_queue.json',scan_attribution_risks(root))
    from .progress import build_progress
    progress_path = root.parents[1]/'reports/plan09_model_silver_progress.latest.json'
    if root == ROOT:
        blocker = load_json(progress_path).get('blocker') if progress_path.exists() else None
        atomic_write(progress_path,build_progress(root,blocker))
    return checks

def checkpoint_risk_review_revision(value, root=ROOT):
    """Correct a reviewed item without consuming pending queue entries."""
    root=Path(root)
    checks=validate_risk_review(value,root)
    heads=risk_review_heads(root)
    previous=[x for x in heads if (x['proposal_id'],x['target_id'],x['au_id'])==(value['proposal_id'],value['target_id'],value['au_id'])]
    if len(previous)!=1 or value.get('supersedes_review_id')!=previous[0]['review_id']:
        raise AnnotationError('revision must supersede current review head',code='history_invalid')
    path=root/'risk_reviews'/(value['review_id']+'.json')
    if path.exists():raise AnnotationError('immutable revision already exists',code='risk_review_duplicate')
    # Preflight all other active records before the irreversible append.
    items=scan_attribution_risks(root,include_reviews=False)['items']
    for old in heads:
        if old['review_id']!=previous[0]['review_id']:validate_risk_review(old,root,items=items)
    atomic_write(path,value)
    atomic_write(root/'attribution_risk_queue.json',scan_attribution_risks(root))
    if root==ROOT:
        from .progress import build_progress
        progress_path=root.parents[1]/'reports/plan09_model_silver_progress.latest.json'
        blocker=load_json(progress_path).get('blocker')
        atomic_write(progress_path,build_progress(root,blocker))
    return checks
