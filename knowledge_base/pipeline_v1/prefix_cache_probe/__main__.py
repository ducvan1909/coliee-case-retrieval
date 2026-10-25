import argparse
from pathlib import Path
from knowledge_base.config import settings
from ..au_runtime_config import load_au_runtime_config
from ..au_compact.manifest import write_json
from ..milestone1.core import ROOT, load, digest
from ..au_compact.prompting import build_prompt
from .core import build_manifest, prepare, run


def main():
    p=argparse.ArgumentParser(description="Step2 prefix-cache observability, fixed prompt/AU contract")
    p.add_argument('command',choices=['prepare','preflight','run'])
    p.add_argument('--parent-manifest',default=str(ROOT/'outputs/concurrency_step1_adapter_fix_20261012/manifest.json'))
    p.add_argument('--manifest');p.add_argument('--probe-id')
    p.add_argument('--output-root',required=True)
    p.add_argument('--source-store',default=str(ROOT/'outputs/source_store_v1'))
    p.add_argument('--atom-root',default=str(ROOT/'outputs/plan04_sentence_atoms_v1'))
    p.add_argument('--url');p.add_argument('--execute',action='store_true')
    a=p.parse_args();root=Path(a.output_root).resolve();path=Path(a.manifest or root/'manifest.json')
    try:
        if any(root.is_relative_to(Path(d).resolve()) for d in (a.source_store,a.atom_root)):
            raise ValueError('output_overlaps_source')
        if any((root/f).exists() for f in ('runtime_ledger.json','identity.json','milestone1_run.lock')):
            raise ValueError('historical_output_root_forbidden')
        if (root/'run.json').exists() and load(root/'run.json').get('version')!='prefix-cache-observation-v1':
            raise ValueError('historical_output_root_forbidden')
        if a.command=='prepare':
            if not a.probe_id or a.execute:p.error('prepare requires --probe-id and no --execute')
            if path.resolve()==Path(a.parent_manifest).resolve() or any(path.resolve().is_relative_to(Path(d).resolve()) for d in (a.source_store,a.atom_root)):
                raise ValueError('manifest_overwrites_source')
            value=build_manifest(load(a.parent_manifest),probe_id=a.probe_id)
            tasks=prepare(value,source_store=a.source_store,atom_root=a.atom_root)
            if path.exists() and load(path)!=value:raise ValueError('locked_manifest_conflict')
            if not path.exists():write_json(path,value)
        else:
            value=load(path);tasks=prepare(value,source_store=a.source_store,atom_root=a.atom_root)
        if a.command in ('prepare','preflight'):
            if a.execute:p.error('Only run accepts --execute')
            report={'status':'pass','manifest_sha256':digest(value),'source_request_count':len(tasks),
                'output_reserve':800*len(tasks),'input_reserve':sum(len(build_prompt(t['effective'],t['rendered']).encode())+128 for t in tasks),
                'input_method':'utf8_bytes_plus_framing_not_provider_tokens','remote_calls':0,'cold_cache_claim':False}
            write_json(root/'preflight.json',report)
            print(f"PREFIX-CACHE PREFLIGHT PASS requests={len(tasks)} — {root/'preflight.json'}");return 0
        if not a.execute or not a.url:p.error('run requires --execute --url')
        cfg,_,policy=load_au_runtime_config(settings(),'AU_COMPACT_')
        if not cfg.get('token'):raise ValueError('runtime_credentials_missing')
        cfg['url']=a.url
        result=run(value,cfg=cfg,source_store=a.source_store,atom_root=a.atom_root,
                   output_root=root,execute=True,policy=policy)
        print(f"PREFIX-CACHE {result['status'].upper()} reports={result['provider_report_count']}/{len(tasks)} hit={result['cache_hit_observed']} — {root/'run.json'}")
        return 0 if result['status']=='complete' and result['fresh_measurement_eligible'] else 3
    except Exception as exc:
        # Do not echo remote errors, credentials, prompt or model output.
        print(f'PREFIX-CACHE ERROR {type(exc).__name__}')
        if isinstance(exc,ValueError) and str(exc) in {'runtime_cache_report_not_enabled_or_unavailable','prefix_probe_endpoint_mismatch','prefix_probe_warmup_failed'}:
            print(str(exc))
        return 2


if __name__=='__main__':raise SystemExit(main())
