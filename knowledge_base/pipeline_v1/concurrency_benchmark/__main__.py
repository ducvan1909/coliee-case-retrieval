from __future__ import annotations
import argparse
from pathlib import Path
from knowledge_base.config import settings
from ..au_runtime_config import load_au_runtime_config
from ..milestone1.core import ROOT, load, digest
from ..au_compact.manifest import write_json
from ..au_compact.prompting import build_prompt
from .core import build_manifest, prepare, run, compare


def main():
    parser=argparse.ArgumentParser(description="Step1 isolated single-GPU concurrency benchmark")
    parser.add_argument("command",choices=["prepare","preflight","run","compare"])
    parser.add_argument("--parent-manifest",default=str(ROOT/"manifests/au_compact_kos5_full_m1.v1.json"))
    parser.add_argument("--manifest")
    parser.add_argument("--benchmark-id")
    parser.add_argument("--count",type=int,default=30)
    parser.add_argument("--source-store",default=str(ROOT/"outputs/source_store_v1"))
    parser.add_argument("--atom-root",default=str(ROOT/"outputs/plan04_sentence_atoms_v1"))
    parser.add_argument("--output-root",required=True)
    parser.add_argument("--url",help="New experimental endpoint /v1/chat/completions; token from knowledge_base/.env")
    parser.add_argument("--concurrency",type=int,choices=[1,2,4],default=1)
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args();root=Path(args.output_root).resolve()
    try:
        if args.execute and args.command!="run":parser.error("Only run accepts execute")
        if (root/"runtime_ledger.json").exists() or (root/"milestone1_run.lock").exists():
            raise ValueError("baseline_output_root_forbidden")
        if (root/"run.json").exists() and load(root/"run.json").get("version")!="au-concurrency-v1":
            raise ValueError("historical_output_root_forbidden")
        for dep in (args.source_store,args.atom_root):
            if root.is_relative_to(Path(dep).resolve()):raise ValueError("output_overlaps_source")
        if args.command=="compare":
            result=compare(root);print(f"CONCURRENCY COMPARE READY — {root/'comparison.json'}");return 0
        path=Path(args.manifest or root/"manifest.json")
        if args.command=="prepare":
            if path.resolve()==Path(args.parent_manifest).resolve() or any(path.resolve().is_relative_to(Path(dep).resolve()) for dep in (args.source_store,args.atom_root)):
                raise ValueError("manifest_overwrites_source_dependency")
            if not args.benchmark_id:parser.error("prepare requires --benchmark-id")
            value=build_manifest(load(args.parent_manifest),source_store=args.source_store,
                atom_root=args.atom_root,count=args.count,benchmark_id=args.benchmark_id)
            if path.exists() and load(path)!=value:raise ValueError("locked_manifest_conflict_use_new_path")
            if not path.exists():write_json(path,value)
        else:value=load(path)
        if args.command in ("prepare","preflight"):
            tasks=prepare(value,source_store=args.source_store,atom_root=args.atom_root)
            input_bytes=sum(len(build_prompt(t["request"],t["rendered"]).encode())+130 for t in tasks)
            report={"status":"pass","manifest_sha256":digest(value),"request_count_per_arm":len(tasks),
                "max_source_requests_all_arms":3*len(tasks),"reserved_output_tokens_all_arms":3*800*len(tasks),
                "estimated_input_all_arms":3*input_bytes,"input_method":"full_prompt_utf8_bytes_plus_128_framing_and_2_id_chars_not_provider_tokens",
                "remote_calls":0,"semantic_quality_claim":False}
            write_json(root/"preflight.json",report)
            print(f"CONCURRENCY PREFLIGHT PASS targets={len(tasks)} — {root/'preflight.json'}");return 0
        if not args.execute or not args.url:parser.error("run requires --execute --url EXPERIMENT_ENDPOINT")
        cfg,_,policy=load_au_runtime_config(settings(),"AU_COMPACT_")
        if not cfg.get("token"):raise ValueError("runtime_credentials_missing")
        cfg["url"]=args.url
        result=run(value,source_store=args.source_store,atom_root=args.atom_root,cfg=cfg,
            concurrency=args.concurrency,output_root=root,execute=True,warmup_policy=policy)
        print(f"CONCURRENCY C{args.concurrency} {result['status'].upper()} — {root/'run.json'}")
        return 0 if result["status"]=="complete" else 3
    except Exception as exc:
        # Never print provider responses, request text or credentials.
        allowed=str(exc)
        if not allowed.replace("_","").isalnum() or len(allowed)>95:allowed=type(exc).__name__
        print(f"CONCURRENCY ERROR {allowed}");return 2


if __name__=="__main__":raise SystemExit(main())
