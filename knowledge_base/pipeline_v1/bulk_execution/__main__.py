from __future__ import annotations
import argparse
from pathlib import Path
from knowledge_base.config import settings
from ..au_runtime_config import load_au_runtime_config
from .storage import write_json
from ..milestone1.core import ROOT,load,digest
from .core import build_manifest,prepare,run


def main():
    parser=argparse.ArgumentParser(description='Single-target AU bulk/corpus transport trial, server C4')
    parser.add_argument('command',choices=['prepare','preflight','run','compare'])
    parser.add_argument('--parent-manifest',default=str(ROOT/'outputs/concurrency_step1_adapter_fix_20261012/manifest.json'))
    parser.add_argument('--manifest')
    parser.add_argument('--workload-id')
    parser.add_argument('--arm',choices=['bulk','corpus'],default='bulk')
    parser.add_argument('--group-size',type=int,default=16)
    parser.add_argument('--source-store',default=str(ROOT/'outputs/source_store_v1'))
    parser.add_argument('--atom-root',default=str(ROOT/'outputs/plan04_sentence_atoms_v1'))
    parser.add_argument('--output-root',required=True)
    parser.add_argument('--url')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();root=Path(args.output_root).resolve()
    try:
        if args.execute and args.command!='run':raise ValueError('execute_only_for_run')
        if any(root.is_relative_to(Path(d).resolve()) for d in (args.source_store,args.atom_root)):
            raise ValueError('output_overlaps_source')
        if any((root/f).exists() for f in ('runtime_ledger.json','identity.json','probe_identity.json')):
            raise ValueError('historical_output_root_forbidden')
        if (root/'run.json').exists() and load(root/'run.json').get('version')!='bulk-au-execution-v1':
            raise ValueError('historical_output_root_forbidden')
        if args.command=='compare':
            reports={a:load(root/a/'run.json') for a in ('bulk','corpus')}
            if reports['bulk']['identity']['manifest_sha256']!=reports['corpus']['identity']['manifest_sha256']:
                raise ValueError('comparison_manifest_mismatch')
            summaries={a:{k:r.get(k) for k in ('status','completed_count','protocol_verified','needs_split','wall_seconds','tokens','transport_stats','resume_or_recovered_receipt','performance_eligible','usage_unavailable')} for a,r in reports.items()}
            pairs=[]
            left={r['original_request']['request_id']:r for r in reports['bulk']['request_ledger']}
            right={r['original_request']['request_id']:r for r in reports['corpus']['request_ledger']}
            for rid in sorted(set(left)|set(right)):
                l=left.get(rid);r=right.get(rid)
                # Arm request IDs differ; compare the model content without that field.
                def semantic(v):
                    if not isinstance(v,dict):return v
                    out=v.get('compact_response')
                    if isinstance(out,dict):
                        out=dict(out);out.pop('request_id',None)
                    return out
                pairs.append({'original_request_id':rid,'left_status':l and l['status'],'right_status':r and r['status'],'same_compact_content':semantic(l)==semantic(r)})
            eligible=all(r.get('performance_eligible') and r['protocol_verified']==r['expected_count'] and r['usage_unavailable']==0 for r in reports.values())
            result={'arms':summaries,'pairs':pairs,'operational_comparison_eligible':eligible,'semantic_review_required':True,'semantic_quality_claim':False,
                    'corpus_vs_bulk_wall_ratio':reports['corpus']['wall_seconds']/reports['bulk']['wall_seconds'] if eligible and reports['bulk']['wall_seconds'] else None}
            write_json(root/'comparison.json',result);print(f'BULK COMPARE READY — {root/"comparison.json"}');return 0
        path=Path(args.manifest or root/'manifest.json').resolve()
        if args.command=='prepare':
            if path==Path(args.parent_manifest).resolve() or any(path.is_relative_to(Path(d).resolve()) for d in (args.source_store,args.atom_root)):
                raise ValueError('manifest_overwrites_dependency')
            value=build_manifest(load(args.parent_manifest),workload_id=args.workload_id)
            if path.exists() and load(path)!=value:raise ValueError('locked_manifest_conflict')
            tasks=prepare(value,source_store=args.source_store,atom_root=args.atom_root,arm=args.arm)
            if not path.exists():write_json(path,value)
        else:
            value=load(path);tasks=prepare(value,source_store=args.source_store,atom_root=args.atom_root,arm=args.arm)
        if args.command in ('prepare','preflight'):
            if not 1<=args.group_size<=32:raise ValueError('invalid_group_size')
            report={'status':'pass','manifest_sha256':digest(value),'source_requests_per_arm':len(tasks),
                'target_per_prompt':1,'server_concurrency':4,'group_size':args.group_size,
                'reserved_output_tokens_per_arm':sum(t['capsule']['payload']['max_tokens'] for t in tasks),
                'estimated_input_utf8_bytes_per_arm':sum(len(t['capsule']['payload']['messages'][0]['content'].encode())+128 for t in tasks),
                'input_method':'utf8_bytes_conservative_estimate_not_provider_usage','remote_calls':0,'semantic_quality_claim':False}
            write_json(root/'preflight.json',report);print(f'BULK PREFLIGHT PASS targets={len(tasks)} — {root/"preflight.json"}');return 0
        if not args.execute or not args.url:raise ValueError('run_requires_execute_and_experimental_url')
        cfg,_,policy=load_au_runtime_config(settings(),'AU_COMPACT_')
        if not cfg.get('token'):raise ValueError('runtime_credentials_missing')
        cfg['url']=args.url
        result=run(value,cfg=cfg,source_store=args.source_store,atom_root=args.atom_root,arm=args.arm,output_root=root,execute=True,group_size=args.group_size,policy=policy)
        print(f'BULK {args.arm.upper()} {result["status"].upper()} — {root/"run.json"}');return 0 if result['status']=='complete' else 3
    except Exception as exc:
        safe=str(exc)
        if len(safe)>95 or not safe.replace('_','').isalnum():safe=type(exc).__name__
        print(f'BULK ERROR {safe}');return 2


if __name__=='__main__':raise SystemExit(main())
