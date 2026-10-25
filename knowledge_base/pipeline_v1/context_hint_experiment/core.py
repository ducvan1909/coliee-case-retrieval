"""Build locked pairs from actual hints and source; no paid calls at import/build."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

from ..au_compact import hints
from ..au_compact.core import build_evidence_catalog
from ..au_compact.manifest import _binding_for, _binding_path, preflight
from ..au_compact.prompting import build_prompt, prompt_identity
from ..au_compact.runner import RENDER_VERSION, _render
from ..source_contract import open_source

def _read(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()

def build_pairs(readiness_path, source_store, atom_root, model='Qwen/Qwen3.5-9B'):
    ready, ready_sha = _read(readiness_path)
    plan04, plan04_sha = _read(Path(atom_root)/'sentence_atom_build_manifest.json')
    if plan04.get('status') != 'pass': raise ValueError('Plan04 build must pass')
    fingerprints = {str(Path(x['path']).resolve()): x['sha256'] for x in ready['input_file_fingerprints']}
    def locked_read(path):
        path = Path(path).resolve()
        value, sha = _read(path)
        if fingerprints.get(str(path)) != sha:
            raise ValueError('readiness dependency is missing or stale: '+str(path))
        return value, sha
    inventory = {(x['case_id'],x['source_hash']): x for x in ready['current_plan06_hint_inventory']}
    requests, pairs = [], []
    seen_targets = set()
    for chosen in ready['selected_real_hint_targets']:
        identity = (chosen['case_id'], chosen['source_hash'])
        if (identity,chosen['target_id']) in seen_targets: raise ValueError('duplicate selected target')
        seen_targets.add((identity,chosen['target_id']))
        work, work_sha = locked_read(inventory[identity]['workload_map'])
        hint_map, map_sha = locked_read(chosen['actual_hint_map'])
        source = open_source(source_store, *identity)
        if hashlib.sha256(source.encode()).hexdigest() != identity[1]: raise ValueError('source mismatch')
        if (work['case_id'], work['source_hash'], hint_map['case_id'], hint_map['source_hash']) != (*identity,*identity):
            raise ValueError('workload/hint identity mismatch')
        target = next(x for x in work['targets'] if x['target_id']==chosen['target_id'])
        if {k:chosen['target_span'][k] for k in ('case_id','source_hash','start_char','end_char')} != target['content_span']:
            raise ValueError('selected target changed')
        region = next(x for x in work['regions'] if x['region_id']==chosen['p2a_region_id'])
        if region['arm'] != 'P2a' or chosen['target_id'] not in region['target_ids']:
            raise ValueError('P2a target/region mismatch')
        refs = []
        for item in region['render_items']:
            own = item['role']=='target' and chosen['target_id'] in item['ref_ids']
            refs.append({**item['span'], 'role':'target' if own else 'context',
                         'target_ids':[chosen['target_id']] if own else []})
        base = {'case_id':identity[0], 'source_hash':identity[1], 'region_id':region['region_id'],
                'arm':'P2a', 'expected_target_ids':[chosen['target_id']], 'source_refs':refs,
                'spec':{'model':model,'enable_thinking':False,'caps':{'targets':1,'output_tokens':800,'au_candidates':3}},
                'context_hint_experiment':hints.MODE,
                'hint_payload':{'version':hints.VERSION,'case_id':identity[0],'source_hash':identity[1],'hints':[]},
                'provenance':{'readiness_sha256':ready_sha,'plan07_workload_sha256':work_sha,
                              'selection':'four real hint targets; development only; not gold'}}
        base['atom_binding'] = _binding_for(base, atom_root, plan04)
        catalog = build_evidence_catalog(base, _binding_path(base['atom_binding'],atom_root),source)
        record = next(x for x in hint_map['hints'] if x['hint_id']==chosen['hint_id'])
        if record != chosen['resolved_hint_record']: raise ValueError('selected hint changed')
        relative = Path(chosen['actual_hint_map']).resolve().relative_to(hints.HINT_ROOT.resolve()).as_posix()
        resolved = {'content':hints.resolve_hint(record,catalog),
                    'provenance':{'map_relative_path':relative,'map_sha256':map_sha,'record_sha256':hints.digest(record)}}
        pair_id = 'hp-'+hints.digest({'case':identity,'target':chosen['target_id'],'hint':resolved})[:24]
        arm_requests = []
        for arm in ('P2a','P2b'):
            req = copy.deepcopy(base); req['arm']=arm
            if arm=='P2b': req['hint_payload']['hints']=[resolved]
            req['request_id']='hreq-'+hints.digest({'pair_id':pair_id,'arm':arm})[:24]
            rendered = _render(req,catalog)
            req['input_tokens']=len(build_prompt(req,rendered).encode('utf-8'))
            requests.append(req); arm_requests.append(req)
        if arm_requests[0]['source_refs'] != arm_requests[1]['source_refs'] or arm_requests[0]['spec'] != arm_requests[1]['spec']:
            raise ValueError('pair context/config mismatch')
        atom_snapshot = [{k:a[k] for k in ('atom_id','start_char','end_char','quote','target_intersecting')}
                         for a in sorted(catalog['atoms'].values(),key=lambda a:a['start_char'])]
        prompts = [build_prompt(q,_render(q,catalog)) for q in arm_requests]
        normal = [p.replace(q['request_id'],'PAIR_REQUEST') for q,p in zip(arm_requests,prompts)]
        if normal[0] == normal[1]: raise ValueError('hint treatment not delivered')
        pairs.append({'pair_id':pair_id,'case_id':identity[0],'target_id':chosen['target_id'],
                      'hint_id':record['hint_id'],'hint_type':record['hint_type'],
                      'request_ids':{q['arm']:q['request_id'] for q in arm_requests},
                      'same_atom_snapshot_sha256':hints.digest(atom_snapshot),
                      'same_source_refs':True,'same_spec':True,'hint_transmitted':True,
                      'prompt_sha256':{q['arm']:hashlib.sha256(p.encode()).hexdigest() for q,p in zip(arm_requests,prompts)},
                      'estimated_prompt_bytes':{q['arm']:q['input_tokens'] for q in arm_requests}})
    manifest = {'artifact_type':'AUCompactLockedManifest','schema_version':'au-compact-manifest-v1',
                'base_manifest_sha256':ready_sha,'plan04_build_manifest_sha256':plan04_sha,'requests':requests}
    check = preflight(manifest,source_store,atom_root)
    if check['status'] != 'pass': raise ValueError('compact preflight failed: '+str(check['failures']))
    pairing = {'artifact_type':'ContextHintMetadataPairing','schema_version':'context-hint-pairs-v1',
               'status':'ready','semantic_gold':False,'semantic_quality_claim':False,
               'mode':hints.MODE,'manifest_sha256':hints.digest(manifest),'prompt_identity':prompt_identity(),
               'render_version':RENDER_VERSION,
               'pair_count':len(pairs),'request_count':len(requests),'pairs':pairs,
               'preflight':check,'reserved_prompt_bytes_estimate':sum(q['input_tokens'] for q in requests),
               'notes':['Other batch targets become CONTEXT for this single-target experiment.',
                        'No new source characters in P2b; cues repeat only supplied text.',
                        'Editorial target retained as negative control for an unhelpful structural hint.',
                        'Prompt bytes are conservative local estimates, not provider tokens.']}
    return {'manifest':manifest,'pairing':pairing}
