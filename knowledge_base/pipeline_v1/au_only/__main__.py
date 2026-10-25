from __future__ import annotations
import argparse,json
from pathlib import Path
from knowledge_base.config import settings
from ..au_runtime_config import load_au_runtime_config
from .core import _atomic,preflight,run,warmup,schema_probe,full_schema_probe
def _budget(env): return load_au_runtime_config(env,"AU_ONLY_")[1]
def main():
 p=argparse.ArgumentParser();p.add_argument("command",choices=["preflight","run","warmup","schema-probe","full-schema-probe"]);p.add_argument("--manifest");p.add_argument("--source-store");p.add_argument("--output-root",default="knowledge_base/pipeline_v1/outputs/au_only_v1");p.add_argument("--execute",action="store_true");p.add_argument("--retry-provider-unavailable",action="store_true");args=p.parse_args();root=Path(args.output_root);env=settings();cfg,budget,warmup_policy=load_au_runtime_config(env,"AU_ONLY_")
 if args.command in {"warmup","schema-probe","full-schema-probe"}:
  if not args.execute:p.error(f"{args.command} requires --execute")
  if not all(cfg[k] for k in ("url","token","model")):p.error("command requires AU_URL, AU_TOKEN, and AU_MODEL (AU_ONLY_* fallback is deprecated)")
  result=warmup(cfg,warmup_policy,root) if args.command=="warmup" else (schema_probe(cfg,root) if args.command=="schema-probe" else full_schema_probe(cfg,root));print(f"AU-ONLY {args.command.upper()} {result['status'].upper()} — output: {root.resolve()}");return 0 if result["status"] in {"success","supported"} else 3
 if not args.manifest or not args.source_store:p.error("preflight/run require --manifest and --source-store")
 value=json.loads(Path(args.manifest).read_text(encoding="utf-8"))
 if args.command=="preflight":
  result=preflight(value,budget,source_store=args.source_store);_atomic(root/"preflight.json",result);print(f"AU-ONLY PREFLIGHT {result['status'].upper()} — output: {(root/'preflight.json').resolve()}");return 0 if result["status"]=="pass" else 2
 if not args.execute:p.error("run requires --execute")
 if not all(cfg[k] for k in ("url","token","model")):p.error("run requires AU_URL, AU_TOKEN, and AU_MODEL (AU_ONLY_* fallback is deprecated)")
 result=run(value,source_store=args.source_store,cfg=cfg,budget=budget,cache_dir=root/"cache",execute=True,warmup_policy=warmup_policy,retry_provider_unavailable=args.retry_provider_unavailable);_atomic(root/"run.json",result);print(f"AU-ONLY RUN {result['status'].upper()} — output: {(root/'run.json').resolve()}");return 0 if result["status"]=="complete" else 3
if __name__=="__main__":raise SystemExit(main())
