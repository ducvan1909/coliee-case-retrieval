"""Frozen fictional controls, full wire demonstrations and CPU replay bundles."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from ..k0_authoring import core as old
from ..au_context_paired.build import binding, verify_bindings
from ..au_context_paired.__main__ import study_config
from ..au_compact.runner import _atomic

BASELINE = Path(__file__).resolve().parents[1]/'outputs/k0_diagnostic_v3_20261023'
PARENT = Path(__file__).resolve().parents[1]/'outputs/k0_ready_20261023'
REASONS = ('no_independent_legal_point', 'unadopted_argument_only',
           'citation_without_substance', 'insufficient_context', 'uncertain')
NEGATIVE = REASONS[:3]
VERSION = 'kos-authoring-controls-v1'


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def code_hash():
    return old.fingerprint({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(__file__).parent.glob('*.py'))})


def grammar(eids, sids, final_wire=False):
    result = old._grammar(eids, sids, [])
    if final_wire:
        root = r'root ::= "{" "\"aus\":" aus "," "\"assessed_scope_ids\":" scopes "," "\"empty_reason\":" empty-reason "," "\"next_action\":" action "}"'
        result = '\n'.join(root if line.startswith('root ::=') else line for line in result.splitlines())+'\n'
        result += 'empty-reason ::= '+ ' | '.join(json.dumps(json.dumps(v)) for v in (None, *REASONS))+'\n'
    return result


def demonstrations(final_wire=False, balanced=False):
    positive = {'aus': [{'claim': 'A licensing board must provide written reasons for cancelling a license.',
        'kind': 'procedural_rule', 'evidence_ids': ['demo-e'], 'limits': 'Except where the license holder consents.'}],
        'assessed_scope_ids': ['demo-r'], 'next_action': {'tool': 'finish_case', 'reason': 'work_scope_complete'}}
    negative = {'aus': [], 'assessed_scope_ids': ['demo-r'],
        'next_action': {'tool': 'finish_case', 'reason': 'work_scope_complete'}}
    uncertain = {'aus': [], 'assessed_scope_ids': [],
        'next_action': {'tool': 'finish_case', 'reason': 'needs_context'}}
    if final_wire:
        for v, reason in ((positive,None),(negative,'no_independent_legal_point'),(uncertain,'insufficient_context')):
            v['empty_reason'] = reason
            # Show exactly the grammar's field order, not only the set of keys.
            action=v.pop('next_action');v['next_action']=action
    examples = [('Fictional example only, scope demo-r/evidence demo-e: A licensing board must provide written reasons for cancelling a license unless the license holder consents.',positive)]
    if balanced:
        examples += [('Fictional example only, scope demo-r/evidence demo-e: The hearing began at noon and ended at two.',negative),
                     ('Fictional example only, scope demo-r/evidence demo-e: The preceding test governs. Its content is not supplied.',uncertain)]
    return ('STRUCTURE EXAMPLES ONLY. These are not SOURCE and demo IDs may not be cited in the real response.\n'+
            '\n'.join(text+'\nJSON: '+encode(out) for text,out in examples)+'\nEND EXAMPLES.\n')


def final_instructions():
    return (old.INSTRUCTIONS+'\nThe response also requires empty_reason before next_action. '
        'For nonempty aus use null. For assessed empty source use no_independent_legal_point, '
        'unadopted_argument_only, or citation_without_substance. For missing information use insufficient_context '
        'or uncertain, assessed_scope_ids empty, and finish_case needs_context. '
        'No quota: pure facts/citation lists/party-only assertions need not supply an AU. '
        'A court rule rejecting a party argument or a reported rule with proper attribution may still be an AU. '
        'For independent legal points provide separate AUs, preserve the actor, negation and exceptions. '
        'If all source is supplied and assessment is complete, finish_case work_scope_complete. '
        'Do not ask for absent synthetic source; use needs_context if required information is absent.\n')


def control_specs():
    # All source/answers here are fictional protocol fixtures, never KOS labels.
    return [
        ('positive_notice','positive',1,'Under a fictional rule, an applicant must receive notice and an opportunity to respond before an adverse decision, except in an emergency.',['applicant','notice','respond','emergency']),
        ('positive_refund','positive',1,'Under a fictional rule, the board must refund a deposit within seven days unless the applicant obtained it by fraud.',['board','refund','seven','fraud']),
        ('positive_multi','positive',2,'Under a fictional rule, an inspector must keep an inspection record. Under a separate rule, a registry must protect the confidentiality of personal data.',['inspector','record','registry','confidential']),
        ('negative_facts','negative',0,'The clerk received a blue folder on Tuesday. The hearing started at nine. The parties then left the building.',[]),
        ('negative_party','negative',0,'The applicant argued that every late claim must be granted. The court expressly declined to adopt that submission and stated no legal test or independent rationale in the supplied passage.',[]),
        ('negative_citation','negative',0,'Authorities cited: <CITATION_SUPPRESSED>; <REFERENCE_SUPPRESSED>.',[]),
        ('uncertain_test','uncertain',0,'The test stated in the preceding passage governs this issue. That preceding passage is not supplied.',[]),
        ('uncertain_voice','uncertain',0,'It was submitted that the missing rule entitled the claimant to relief. The judicial response and content of that rule appear elsewhere and are not supplied.',[]),
        ('uncertain_exception','uncertain',0,'The exception described above determines this result. Neither that exception nor the rule to which it applies is supplied.',[]),
    ]


def positive_only(cfg):
    frozen=old.load(BASELINE/'input/manifest.json')
    job=copy.deepcopy(frozen['jobs'][0]['job'])
    payload=job['payload']
    if payload['model']!=cfg['model']:raise ValueError('model mismatch')
    original=payload['messages'][0]['content']
    payload['messages'][0]['content']=demonstrations()+original
    job['payload_sha256']=old.fingerprint(payload)
    job['input_reservation']=old.input_reservation(payload)
    return [{'name':'positive_only','payload':payload,'validation_job':job,
        'expected':{'group':'positive','AU_count':1,'concepts':['applicant','notice','respond','emergency']}}]


def balanced_jobs(cfg):
    rows=[]
    for index,(name,group,count,source,concepts) in enumerate(control_specs(),1):
        sid,eid=f'r{index+20}',f'e{index+20}'
        sha=hashlib.sha256(source.encode()).hexdigest()
        job={'case_id':'fictional-'+name,'source_hash':sha,'active_scope_ids':[sid],
            'allowed_scope_ids':[sid],'draft_ids':[], 'catalog':{'evidence':{eid:{'case_id':'fictional-'+name,
            'source_hash':sha,'start_char':0,'end_char':len(source),'quote':source}}}}
        payload={'model':cfg['model'],'messages':[{'role':'user','content':final_instructions()+
            demonstrations(True,True)+'\nACTUAL FICTIONAL SOURCE:\n'+encode({'scope_id':sid,'parts':[{'id':eid,'text':source}]})}],
            'temperature':0,'max_tokens':800,'chat_template_kwargs':{'enable_thinking':False},'ebnf':grammar([eid],[sid],True)}
        job.update(payload=payload,payload_sha256=old.fingerprint(payload),input_reservation=old.input_reservation(payload))
        rows.append({'name':name,'payload':payload,'validation_job':job,
            'expected':{'group':group,'AU_count':count,'concepts':concepts}})
    return rows


def validate(value,job,final_wire=False):
    data=copy.deepcopy(value)
    if final_wire:
        if not isinstance(data,dict) or 'empty_reason' not in data:raise ValueError('missing empty reason')
        reason=data.pop('empty_reason')
        if reason is not None and reason not in REASONS:raise ValueError('invalid empty reason')
    else:reason=None
    normalized=old.validate_response(data,job)
    if normalized['au_errors']:raise ValueError('AU validation failed')
    if final_wire:
        if data['aus'] and reason is not None:raise ValueError('positive with empty reason')
        if not data['aus']:
            action=data['next_action']
            if reason in NEGATIVE and not data['assessed_scope_ids']:raise ValueError('negative without assessed scopes')
            if reason in REASONS[3:] and data['assessed_scope_ids']:raise ValueError('uncertain certified assessed')
            if reason is None and (data['assessed_scope_ids'] or action['tool']=='finish_case'):
                raise ValueError('empty assessment without reason')
            if reason in REASONS[3:] and action['tool']=='finish_case' and action['reason']!='needs_context':
                raise ValueError('uncertain completed')
    return {**normalized,'empty_reason':reason}


def cpu_bundle(jobs,final_wire=False):
    rows=[]
    for row in jobs:
        j=row['validation_job'];sid=j['active_scope_ids'][0];eid=next(iter(j['catalog']['evidence']))
        witness={'aus':[{'claim':'A fictional legal rule.','kind':None,'evidence_ids':[eid],'limits':None}],
            'assessed_scope_ids':[sid],'next_action':{'tool':'finish_case','reason':'work_scope_complete'}}
        variants=[witness]
        more=copy.deepcopy(witness);more['aus'].append({**more['aus'][0],'claim':'An independent point.'});variants.append(more)
        if final_wire:
            for x in variants:x['empty_reason']=None;action=x.pop('next_action');x['next_action']=action
            variants += [{'aus':[],'assessed_scope_ids':[sid],'empty_reason':NEGATIVE[0],
                'next_action':{'tool':'finish_case','reason':'work_scope_complete'}},
                {'aus':[],'assessed_scope_ids':[],'empty_reason':'insufficient_context',
                 'next_action':{'tool':'finish_case','reason':'needs_context'}}]
        bad=copy.deepcopy(variants[0]);bad['aus'][0]['evidence_ids']=['not-in-catalog']
        rows.append({'name':row['name'],'grammar':j['payload']['ebnf'],
            'positive_examples':[encode(v) for v in variants],'negative_examples':[encode(bad)]})
    return {'jobs':rows}


def prepare(root):
    root=Path(root).resolve();old.guard_output(root,[BASELINE,PARENT,Path(old.__file__).parent,Path(__file__).parent])
    if root.exists():raise ValueError('fresh root required')
    cfg,_,_=study_config(argparse.Namespace())
    old.preflight(PARENT/'input/workload.json',cfg=cfg)
    jobs=positive_only(cfg);future=balanced_jobs(cfg)
    bindings=[binding(p) for base in [PARENT,BASELINE] for p in sorted(base.rglob('*')) if p.is_file()]
    manifest={'version':VERSION,'code_sha256':code_hash(),'K0_code_sha256':old.code_hash(),
        'parent_bindings':bindings,'jobs':jobs,'balanced_jobs':future,'max_POST_attempts':12,'max_total_tokens':30000,
        'semantic_quality':'not_assessed'}
    manifest['sha256']=old.fingerprint(manifest)
    _atomic(root/'input/manifest.json',manifest)
    _atomic(root/'input/cpu_positive.json',cpu_bundle(jobs))
    _atomic(root/'input/cpu_balanced.json',cpu_bundle(future,True))
    return manifest


def preflight(root):
    root=Path(root);m=old.load(root/'input/manifest.json')
    if m['sha256']!=old.fingerprint({k:v for k,v in m.items() if k!='sha256'}):raise ValueError('manifest digest')
    if m['code_sha256']!=code_hash() or m['K0_code_sha256']!=old.code_hash():raise ValueError('code binding')
    verify_bindings(m['parent_bindings'])
    cfg,_,_=study_config(argparse.Namespace());old.preflight(PARENT/'input/workload.json',cfg=cfg)
    if m['jobs']!=positive_only(cfg) or m['balanced_jobs']!=balanced_jobs(cfg):raise ValueError('payload binding')
    total=0
    for row in m['jobs']+m['balanced_jobs']:
        n=old.input_reservation(row['payload'])
        if n>6000 or row['payload']['max_tokens']!=800:raise ValueError('per-request cap')
        total+=n+800
    if total>30000:raise ValueError('aggregate reserve')
    return {'status':'pass','model_requests_planned':10,'reserved_input_and_output_tokens':total,'inference':0}
