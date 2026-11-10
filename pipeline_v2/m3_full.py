"""Full M3 local preparation; Modal runs require an explicit run command."""
from pathlib import Path
import json
import os
import sys
import time

ROOT=Path(__file__).resolve().parents[1]

def main(argv=None):
    from .deploy_modal import _SafeArgumentParser,EnvConfigError
    parser=_SafeArgumentParser(description=__doc__);parser.add_argument('--env-file',default='pipeline_v2/.env')
    subs=parser.add_subparsers(dest='command',required=True)
    p=subs.add_parser('plan');p.add_argument('--output',required=True)
    for name in ('run','status','verify','open'):
        p=subs.add_parser(name);p.add_argument('--run-dir',required=True)
        if name=='run':p.add_argument('--max-batches',type=int)
        if name=='open':p.add_argument('--passage-id',required=True)
    args=parser.parse_args(argv);started=time.perf_counter()
    try:
        if args.command=='run':
            from .deploy_modal import parse_env,build_environment
            path=Path(args.env_file)
            if not path.is_absolute():path=ROOT/path
            os.environ.update(build_environment(parse_env(path)))
        from .full_corpus.runner import plan_full,run_full,status_full,verify_full,open_full
        if args.command=='plan':result=plan_full(ROOT,args.output)
        elif args.command=='run':result=run_full(ROOT,args.run_dir,max_batches=args.max_batches)
        elif args.command=='status':result=status_full(ROOT,args.run_dir)
        elif args.command=='verify':result=verify_full(ROOT,args.run_dir)
        else:result=open_full(ROOT,args.run_dir,args.passage_id)
        result['internal_cli_seconds']=time.perf_counter()-started
        result['cli_timing_origin']='after_argument_parse_excludes_process_startup'
        print(json.dumps(result,ensure_ascii=True,sort_keys=True));return 0
    except Exception as exc:
        from .retrieval.common import M3Error
        print(json.dumps({'status':'error','error':str(exc) if isinstance(exc,(M3Error,EnvConfigError)) else type(exc).__name__,
                          'internal_cli_seconds':time.perf_counter()-started}),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
