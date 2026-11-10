"""Revision-2 local preparation and explicit user-run Modal commands."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
MODAL_COMMANDS={"deploy","preflight","benchmark","search","search-benchmark"}


def main(argv=None):
    from .deploy_modal import _SafeArgumentParser,EnvConfigError
    parser=_SafeArgumentParser(description=__doc__)
    parser.add_argument("--env-file",default="pipeline_v2/.env")
    subs=parser.add_subparsers(dest="command",required=True)
    for name in ("build","deploy","preflight","benchmark","search","search-benchmark","verify","open"):
        p=subs.add_parser(name)
        if name not in ("build","deploy"):p.add_argument("--index-dir",required=True)
        if name in ("build","preflight","benchmark","search-benchmark"):p.add_argument("--output",required=True)
        if name in ("benchmark","search","search-benchmark"):p.add_argument("--compatibility",required=True)
        if name=="search":
            p.add_argument("--query",required=True);p.add_argument("--query-case");p.add_argument("--limit",type=int,default=10)
        if name=="search-benchmark":p.add_argument("--repeats",type=int,default=3)
        if name=="verify":p.add_argument("--full-db",action="store_true")
        if name=="open":p.add_argument("--passage-id",required=True)
    args=parser.parse_args(argv);started=time.perf_counter();session=None
    try:
        # Local commands neither read credentials nor initialize Modal auth.
        if args.command in MODAL_COMMANDS:
            from .deploy_modal import parse_env,build_environment
            env=Path(args.env_file)
            if not env.is_absolute():env=ROOT/env
            environment=build_environment(parse_env(env));os.environ.update(environment)
        from .optimization_v2.common import M3Error,artifact,write_json
        from .optimization_v2.index import build_index,FastSession
        if args.command=="deploy":
            return subprocess.run([sys.executable,"-m","modal","deploy","pipeline_v2/deployments/modal_opt_v2/qwen3_embed.py"],cwd=ROOT,env=environment,shell=False).returncode
        if args.command=="build":result=build_index(ROOT,args.output)
        elif args.command=="preflight":
            from .optimization_v2.runtime import preflight_compatibility
            result=preflight_compatibility(ROOT,args.index_dir,args.output)
        elif args.command=="benchmark":
            from .optimization_v2.benchmark import benchmark_index
            result=benchmark_index(ROOT,args.index_dir,args.output,args.compatibility)
        else:
            session=FastSession(ROOT,args.index_dir)
            if args.command=="verify":result=session.verify(args.full_db)
            elif args.command=="open":result=session.open(args.passage_id)
            elif args.command=="search":result=session.search(args.query,args.query_case,args.limit,args.compatibility)
            else:result=search_benchmark(ROOT,session,args.output,args.compatibility,args.repeats)
            result["session_initialization_seconds"]=session.initialization_seconds
        result["full_cli_seconds"]=time.perf_counter()-started
        result["cli_timing_origin"]="after_argument_parse_excludes_process_startup"
        if getattr(args,"output",None):
            output=artifact(ROOT,args.output)
            if output.is_dir():write_json(output/"cli_receipt.json",{"command":args.command,"result":result})
        print(json.dumps(result,ensure_ascii=True,sort_keys=True));return 0
    except Exception as exc:
        from .retrieval.common import M3Error
        result={"status":"error","error":str(exc) if isinstance(exc,(M3Error,EnvConfigError)) else type(exc).__name__,"full_cli_seconds":time.perf_counter()-started,"cli_timing_origin":"after_argument_parse_excludes_process_startup"}
        print(json.dumps(result),file=sys.stderr);return 2
    finally:
        if session is not None:session.close()


def search_benchmark(root,session,output,compatibility,repeats=3,embedder=None):
    """RPC once per query; report all timing boundaries without conflating them."""
    from .optimization_v2.common import M3Error,artifact,write_json
    from .optimization_v2.runtime import require_compatibility,query_embedding
    if type(repeats) is not int or not 3<=repeats<=10:raise M3Error("Search repeats must be3..10")
    require_compatibility(session,compatibility,allow_simulated=embedder is not None)
    target=artifact(root,output)
    if target.exists():raise M3Error("Search benchmark output exists")
    target.mkdir(parents=True,exist_ok=False)
    queries=[("standard of review",None),("standard of review","079659.txt"),("décision n'est pas raisonnable under s. 97(1)",None)]
    result={"status":"running","session_initialization_seconds":session.initialization_seconds,"queries":[],
            "cli_timing_origin":"after_argument_parse_excludes_process_startup",
            "limits":["local_vector_reuse_timings_exclude_RPC","first_RPC_can_include_cold_queue_and_load","full_cli_seconds_in_cli_receipt_not_local_timings"],
            "execution_mode":"simulated" if embedder is not None else "unified_v2_real_query"}
    try:
        for query,case in queries:
            session.guard();session.cheap_db_check()
            request_started=time.perf_counter()
            vector,receipt=query_embedding(session,query,embedder)
            first=session.search_vector(query,vector,case,10)
            warm_request=time.perf_counter()-request_started
            timings=[first["local_retrieval_seconds"]]
            for _ in range(repeats-1):
                row=session.search_vector(query,vector,case,10);timings.append(row["local_retrieval_seconds"])
            result["queries"].append({"query":query,"excluded_case":case,"local_vector_reuse_seconds":timings,
                                      "warm_session_request_seconds_including_RPC":warm_request,"query_embedding":receipt,
                                      "includes_cold_start_if_container_cold":True,
                                      "results":first["results"]})
        result["status"]="simulated" if embedder is not None else "PASS_components_measured_not_full_corpus_quality"
    except Exception as exc:
        result.update(status="failed_partial",error_type=type(exc).__name__);raise
    finally:write_json(target/"search_benchmark.json",result)
    return result


if __name__=="__main__":raise SystemExit(main())
