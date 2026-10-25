from __future__ import annotations
import copy
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from ..concurrency_benchmark import core as bench
from ..au_compact import runner
from ..au_compact.core import deduplicate_lists
from ..au_compact.decoding import build_decoding
from ..au_compact.jobs_client import payload_digest
from .storage import write_json
from ..milestone1.core import digest,load
from ..au_only.core import warmup
from .transport import GroupTransport,GroupTransportError,group_id

VERSION='bulk-au-execution-v1'


def build_manifest(parent,*,workload_id):
    if not isinstance(workload_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',workload_id):raise ValueError('invalid_workload_id')
    return {'version':VERSION,'workload_id':workload_id,'parent':copy.deepcopy(parent),
            'parent_sha256':digest(parent),'source_count':len(parent.get('requests',[])),
            'model':bench.MODEL,'server_concurrency':4,'target_per_prompt':1,
            'semantic_quality_claim':False}


def prepare(manifest,*,source_store,atom_root,arm):
    parent=manifest.get('parent',{})
    if manifest!=build_manifest(parent,workload_id=manifest.get('workload_id')) or arm not in ('bulk','corpus'):
        raise ValueError('invalid_bulk_manifest')
    tasks=bench.prepare(parent,source_store=source_store,atom_root=atom_root)
    prepared=[]
    for task in tasks:
        q=copy.deepcopy(task['request'])
        q['request_id']='bulk-'+digest({'manifest':digest(manifest),'arm':arm,'source_id':q['request_id']})[:24]
        atoms=task['catalog']['atoms']
        constraint=build_decoding(q['request_id'],q['expected_target_ids'][0],list(atoms),
            [aid for aid,atom in atoms.items() if atom['target_intersecting']],string_mode='host_validated')
        prompt=runner.build_prompt(q,task['rendered'])
        if len(prompt.encode())+128>11488:raise ValueError('bulk_input_ceiling_exceeded')
        payload={'model':bench.MODEL,'messages':[{'role':'user','content':prompt}],
                 'temperature':0,'max_tokens':q['spec']['caps']['output_tokens'],**constraint,
                 'chat_template_kwargs':{'enable_thinking':False}}
        prepared.append({**task,'effective':q,'capsule':{'job_id':payload_digest(payload),'payload':payload}})
    return prepared


def validate_progress(value,*,gid,mode,after,expected_ids):
    if not isinstance(value,dict) or value.get('group_id')!=gid or value.get('mode')!=mode:
        raise ValueError('group_progress_identity_mismatch')
    if type(value.get('cursor')) is not int or value.get('cursor')!=after or type(value.get('next_cursor')) is not int:
        raise ValueError('group_cursor_invalid')
    rows=value.get('results')
    if not isinstance(rows,list) or value['next_cursor']!=after+len(rows) or value['next_cursor']>len(expected_ids):
        raise ValueError('group_cursor_invalid')
    counts=value.get('counts',{})
    if not isinstance(counts,dict) or type(counts.get('total')) is not int or counts.get('total')!=len(expected_ids):raise ValueError('group_count_mismatch')
    keys=('queued','running','completed','failed','interrupted')
    if any(type(counts.get(k)) is not int or counts[k]<0 for k in keys) or sum(counts[k] for k in keys)!=counts['total']:
        raise ValueError('group_count_mismatch')
    if any(not isinstance(r,dict) or not isinstance(r.get('job_id'),str) for r in rows):raise ValueError('group_receipt_invalid')
    if len({r.get('job_id') for r in rows})!=len(rows):raise ValueError('duplicate_group_result')
    for r in rows:
        if r.get('job_id') not in expected_ids or r.get('payload_sha256')!=r.get('job_id') or r.get('status') not in ('completed','failed','interrupted'):
            raise ValueError('group_receipt_invalid')
        if r['status']=='completed' and (not isinstance(r.get('response'),dict) or r.get('response_sha256')!=payload_digest(r['response'])):
            raise ValueError('group_response_digest_mismatch')
    if sum(counts[k] for k in ('completed','failed','interrupted'))<value['next_cursor']:
        raise ValueError('group_count_mismatch')
    if any(sum(r['status']==k for r in rows)>counts[k] for k in ('completed','failed','interrupted')):
        raise ValueError('group_count_mismatch')
    return rows


def normalize_receipt(job,task):
    q=task['effective'];body=job.get('response');compact=None;normalized=None
    receipt={'usage':runner._usage(body) if isinstance(body,dict) else None,
        'cache_observation':runner._cache_observation(body),'usage_state':'unavailable',
        'finish_reason':'host_unresolved','server_timing':{k:job.get(k) for k in ('created_at','started_at','finished_at','inference_seconds')},
        'job_id':job['job_id']}
    if receipt['usage'] is None and isinstance(job.get('usage'),dict):receipt['usage']=runner._usage({'usage':job['usage']})
    if receipt['usage'] is not None:receipt['usage_state']='provider'
    status='unresolved'
    if job['status']=='completed':
        try:
            choice=body['choices'][0];receipt['finish_reason']=choice.get('finish_reason')
            content=choice['message']['content'];receipt['raw_response']=content
            if receipt['finish_reason']!='stop':
                receipt['failure_diagnostic']={'kind':'output_truncated' if receipt['finish_reason']=='length' else 'incomplete_generation'}
            else:
                compact=json.loads(content);cleaned,cleanup=deduplicate_lists(compact)
                normalized=runner._normalize(cleaned,q,task['binding'],task['source'])
                receipt['exact_duplicate_cleanup']=cleanup;status='protocol_verified'
        except Exception as exc:
            receipt['failure_diagnostic']={'kind':'host_validation','error_type':type(exc).__name__}
    else:
        receipt['failure_diagnostic']={'kind':'job_'+job['status'],'outcome_unknown':job['status']=='interrupted','server_error':job.get('error')}
    return {'request':q,'original_request':task['request'],'status':status,
            'compact_response':compact,'response':normalized,'receipt':receipt}


def run(manifest,*,cfg,source_store,atom_root,arm,output_root,execute=False,group_size=16,
        transport=None,capability_fetch=None,warmup_fn=None,policy=None,clock=time.monotonic,sleep=time.sleep):
    if not execute:raise ValueError('bulk_requires_execute')
    setup_started=clock()
    if type(group_size) is not int or not 1<=group_size<=32:raise ValueError('invalid_group_size')
    parsed=urlsplit(cfg.get('url',''))
    if (parsed.scheme!='https' or parsed.path!='/v1/chat/completions' or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment or
        not re.fullmatch(r'[a-z0-9-]+--coliee-qwen35-9b-bulk-server\.(?:[a-z0-9.-]+\.modal\.direct|modal\.run)',parsed.hostname or '')):
        raise ValueError('isolated_bulk_endpoint_required')
    if cfg.get('model')!=bench.MODEL or cfg.get('enable_thinking') is not False:raise ValueError('bulk_model_changed')
    tasks=prepare(manifest,source_store=source_store,atom_root=atom_root,arm=arm)
    root=Path(output_root).resolve()
    if any(root.is_relative_to(Path(d).resolve()) for d in (source_store,atom_root)) or any((root/f).exists() for f in ('runtime_ledger.json','identity.json','probe_identity.json')):
        raise ValueError('historical_output_root_forbidden')
    if (root/'run.json').exists() and load(root/'run.json').get('version')!=VERSION:raise ValueError('historical_output_root_forbidden')
    root.mkdir(parents=True,exist_ok=True);lock=root/'bulk_execution.lock'
    try:handle=lock.open('x')
    except FileExistsError:raise ValueError('bulk_locked_manual_recovery_required') from None
    try:
        handle.close()
        identity={'version':VERSION,'manifest_sha256':digest(manifest),'arm':arm,'group_size':group_size,
                  'endpoint_sha256':hashlib.sha256(cfg['url'].encode()).hexdigest(),
                  'prompt_identity':runner.prompt_identity(),'decoder_version':runner.RESPONSE_FORMAT_VERSION}
        ip=root/'execution_identity.json'
        if ip.exists() and load(ip)!=identity:raise ValueError('bulk_resume_identity_mismatch')
        write_json(ip,identity)
        info=bench.wait_capability(cfg,capability_fetch or bench.capability,policy or {'max_attempts':50,'max_wait_seconds':1500},root)
        write_json(root/'capability.json',info)
        required={'experiment':'au-bulk-v1','app':'coliee-qwen35-9b-bulk','gateway_concurrency':4,'server_concurrency':4,
                  'model':bench.MODEL,'gpu':'L40S:1','context_length':12288,'max_total_tokens':12288,
                  'max_containers':1,'exclusive_probes':True,'backend_retry':False}
        prior_groups=bool(list((root/'groups').glob('*.json')))
        unhealthy=(info.get('ready') is not True or any(info.get(k) for k in ('poisoned','stopping','backend_outcome_unknown')))
        if any(info.get(k)!=v for k,v in required.items()) or (unhealthy and not prior_groups):
            raise ValueError('bulk_endpoint_capability_mismatch')
        features=info.get('capabilities',{})
        if not all(features.get(k) is True for k in ('bulk_submit','incremental_progress','pending_queue','corpus_runner')):
            raise ValueError('bulk_features_missing')
        warm=({'status':'skipped_for_resume','usage':None} if prior_groups else
              (warmup_fn or warmup)(cfg,policy or {'max_attempts':50,'max_wait_seconds':1500},root/'warmup'))
        if warm.get('status') not in ('success','skipped_for_resume'):raise ValueError('bulk_warmup_failed')
        transport=transport or GroupTransport(cfg)
        groups=[tasks] if arm=='corpus' else [tasks[i:i+group_size] for i in range(0,len(tasks),group_size)]
        rows={};resumed=False;stop=False;failure=None;began=clock();group_reports=[]
        for batch in groups:
            jobs=[t['capsule'] for t in batch];gid=group_id(arm,jobs)
            by_job={t['capsule']['job_id']:t for t in batch};gp=root/'groups'/(gid+'.json')
            state={'group_id':gid,'mode':arm,'cursor':0,'jobs':[j['job_id'] for j in jobs],'identity':identity,'finished':False}
            existing=gp.exists()
            if existing:
                old=load(gp)
                if old.get('identity')!=identity or old.get('jobs')!=state['jobs']:raise ValueError('bulk_group_checkpoint_mismatch')
                state=old;resumed=True
            for task in batch:
                p=root/'cache'/(task['capsule']['job_id']+'.json')
                if p.exists():
                    row=load(p)
                    if row.get('identity')!=identity or row.get('request')!=task['effective']:raise ValueError('bulk_cached_result_mismatch')
                    rows[task['capsule']['job_id']]=row;resumed=True
            if state['cursor']>sum(j['job_id'] in rows for j in jobs):raise ValueError('bulk_cursor_ahead_of_receipts')
            prior_unknown=any(r['receipt'].get('failure_diagnostic',{}).get('outcome_unknown') for r in rows.values())
            if state['finished']:
                if not all(j['job_id'] in rows for j in jobs):raise ValueError('bulk_cursor_ahead_of_receipts')
                group_reports.append(state)
                if prior_unknown:stop=True;break
                continue
            write_json(gp,state) # Durable reservation before any POST.
            try:
                if unhealthy:
                    if not existing:raise GroupTransportError('backend_unavailable_new_admission_forbidden',outcome_unknown=True)
                    ack=transport.progress(arm,gid,0);recovered=True
                else:ack,recovered=transport.admit(arm,jobs,resume=existing)
                resumed|=recovered
                if ack.get('group_id')!=gid or ack.get('mode')!=arm:raise ValueError('group_ack_identity_mismatch')
                deadline=clock()+cfg.get('job_wait_seconds',1800)
                seen_events=set()
                while True:
                    if clock()>=deadline:raise GroupTransportError('group_wait_timeout',outcome_unknown=True)
                    try:progress=transport.progress(arm,gid,state['cursor'],remaining=deadline-clock())
                    except GroupTransportError as exc:
                        if exc.http_status not in (429,502,503,504) and exc.kind!='group_transport':raise
                        sleep(min(cfg.get('job_poll_seconds',2),max(0,deadline-clock())));continue
                    completed=validate_progress(progress,gid=gid,mode=arm,after=state['cursor'],expected_ids=set(by_job))
                    for job in completed:
                        if job['job_id'] in seen_events:raise ValueError('duplicate_group_event')
                        seen_events.add(job['job_id'])
                        task=by_job[job['job_id']]
                        row=normalize_receipt(job,task);row['identity']=identity
                        old=rows.get(job['job_id'])
                        if old is not None and old!=row:raise ValueError('group_receipt_changed_after_checkpoint')
                        write_json(root/'cache'/(job['job_id']+'.json'),row);rows[job['job_id']]=row
                    # Cursor only advances AFTER all returned receipts are durable locally.
                    state['cursor']=progress['next_cursor'];state['server_counts']=progress['counts']
                    state['finished']=all(j['job_id'] in rows for j in jobs)
                    write_json(gp,state)
                    write_json(root/'checkpoint.json',{'saved_count':len(rows),'expected_count':len(tasks),'last_group':gid,'cursor':state['cursor']})
                    halt=any(r['receipt'].get('failure_diagnostic',{}).get('outcome_unknown') for r in rows.values()) or progress.get('status') in ('paused','blocked','interrupted')
                    # Drain already durable terminal receipts before stopping admission.
                    terminal_total=sum(progress['counts'][k] for k in ('completed','failed','interrupted'))
                    if halt and state['cursor']>=terminal_total:stop=True;break
                    if state['finished']:break
                    if not completed:sleep(min(cfg.get('job_poll_seconds',2),max(0,deadline-clock())))
                group_reports.append(state)
                if stop:break
            except (GroupTransportError,ValueError) as exc:
                failure={'kind':exc.kind if isinstance(exc,GroupTransportError) else type(exc).__name__,
                         'http_status':getattr(exc,'http_status',None),'outcome_unknown':getattr(exc,'outcome_unknown',True)}
                write_json(root/'transport_failure.json',failure);stop=True;break
        ordered=[rows[t['capsule']['job_id']] for t in tasks if t['capsule']['job_id'] in rows]
        usages=[r['receipt'].get('usage') for r in ordered];wall=clock()-began
        complete=len(ordered)==len(tasks)
        result={'version':VERSION,'identity':identity,'arm':arm,'status':'complete' if complete else 'incomplete',
            'expected_count':len(tasks),'completed_count':len(ordered),'request_ledger':ordered,
            'protocol_verified':sum(r['status']=='protocol_verified' for r in ordered),
            'needs_split':sum(isinstance(r.get('compact_response'),dict) and r['compact_response'].get('coverage_status')=='needs_split' for r in ordered),
            'wall_seconds':wall,'performance_eligible':complete and not resumed and not stop,
            'resume_or_recovered_receipt':resumed,'stop_dispatch':stop,'transport_failure':failure,
            'groups':group_reports,'transport_stats':copy.deepcopy(getattr(transport,'stats',{})),
            'tokens':{k:sum(u.get(k,0) for u in usages if isinstance(u,dict)) for k in ('input_tokens','output_tokens','total_tokens')},
            'usage_unavailable':sum(not isinstance(u,dict) for u in usages),
            'semantic_quality_claim':False,'target_per_prompt':1,'server_concurrency':4,
            'setup':{'warmup':warm,'outside_workload_wall':True,'seconds':began-setup_started,
                     'server_startup_warmup_usage':None,'server_startup_warmup_usage_state':'not_collected'},
            'total_client_seconds':clock()-setup_started,
            'resource_usage':{'gpu_hours':None,'vram_peak':None,'billing':None}}
        write_json(root/'run.json',result);return result
    finally:lock.unlink(missing_ok=True)
