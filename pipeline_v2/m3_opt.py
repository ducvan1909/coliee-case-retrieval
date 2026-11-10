"""Isolated M3 optimization CLI; never runs full-corpus embedding."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]


def main(argv=None):
    from .deploy_modal import parse_env,build_environment,_SafeArgumentParser
    parser=_SafeArgumentParser(description=__doc__)
    parser.add_argument("--env-file",default="pipeline_v2/.env")
    subs=parser.add_subparsers(dest="command",required=True)
    for name in ("build","deploy","search","search-benchmark","open","verify","benchmark"):
        p=subs.add_parser(name)
        if name not in ("build","deploy"):p.add_argument("--index-dir",required=True)
        if name in ("build","benchmark","search-benchmark"):p.add_argument("--output",required=True)
        if name=="search":
            p.add_argument("--query",required=True);p.add_argument("--query-case");p.add_argument("--limit",type=int,default=10)
        if name=="search-benchmark":p.add_argument("--repeats",type=int,default=3)
        if name=="verify":p.add_argument("--full-db",action="store_true")
        if name=="open":p.add_argument("--passage-id",required=True)
    args=parser.parse_args(argv)
    started=time.perf_counter()
    session=None
    try:
        env_path=Path(args.env_file)
        if not env_path.is_absolute():env_path=ROOT/env_path
        environment=build_environment(parse_env(env_path))
        # No Modal import precedes this assignment: SDK profile is read at import.
        os.environ.update(environment)
        from .optimization.common import M3Error,artifact,write_json
        from .optimization.index import build_index,FastSession
        if args.command=="deploy":
            return subprocess.run([sys.executable,"-m","modal","deploy","pipeline_v2/deployments/modal_opt/qwen3_embed.py"],cwd=ROOT,env=environment,shell=False).returncode
        if args.command=="build":result=build_index(ROOT,args.output)
        elif args.command=="benchmark":
            from .optimization.benchmark import benchmark_index
            result=benchmark_index(ROOT,args.index_dir,args.output)
        else:
            session=FastSession(ROOT,args.index_dir)
            if args.command=="search":result=session.search(args.query,args.query_case,args.limit)
            elif args.command=="open":result=session.open(args.passage_id)
            elif args.command=="verify":result=session.verify(args.full_db)
            else:result=search_benchmark(ROOT,session,args.output,args.repeats)
        result["cli_seconds"]=time.perf_counter()-started
        if getattr(args,"index_dir",None):
            index=artifact(ROOT,args.index_dir)
            runtime=index.parent/(index.name+"_runtime")
            write_json(runtime/"operations"/(str(time.time_ns())+"_"+uuid.uuid4().hex+".json"),{"command":args.command,"result":result})
        print(json.dumps(result,ensure_ascii=True,sort_keys=True))
        return 0
    except Exception as exc:
        from .retrieval.common import M3Error
        from .deploy_modal import EnvConfigError
        print(json.dumps({"status":"error","error":str(exc) if isinstance(exc,(M3Error,EnvConfigError)) else type(exc).__name__,"cli_seconds":time.perf_counter()-started}),file=sys.stderr)
        return 2
    finally:
        if session is not None:session.close()


def search_benchmark(root,session,output,repeats=3):
    """Encode each query once; reuse vectors to measure local cold/warm paths."""
    import numpy as np
    from .optimization.common import M3Error,artifact,write_json
    from .optimization.index import PersistentBM25
    from .retrieval.bm25 import BM25
    from .retrieval.cache import Cache
    from .retrieval.runtime import ModalEmbedder,call_embedding
    from .passages import PinnedTokenizer
    if type(repeats) is not int or not 2<=repeats<=10:raise M3Error("Search benchmark repeats must be2..10")
    target=artifact(root,output)
    if target.exists():raise M3Error("Search benchmark output exists")
    target.mkdir(parents=True,exist_ok=False)
    queries=[("standard of review",None),("standard of review","079659.txt"),("décision n'est pas raisonnable under s. 97(1)",None)]
    b=session.base
    cache=Cache(target,b["embedding_fingerprint"],b["profile"]["embedding"]["dimensions"])
    tok=PinnedTokenizer(root,"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
    remote=ModalEmbedder(b["profile"])
    rows=[]
    try:
        for n,(query,excluded) in enumerate(queries):
            vector,response=call_embedding(remote,[query],"query",b["profile"],tok,b["implementation"],cache,f"benchmark-query-{n}")
            timings=[]; result=None
            for _ in range(repeats):
                start=time.perf_counter();result=session.search_vector(query,vector[0],excluded,10)
                timings.append(time.perf_counter()-start)
            # Independently compare persisted lexical scores/ranks to frozen BM25.
            lexical=[]
            for kind in ("case","passage"):
                docs=session.lexical.documents(kind)
                params={k:b["profile"]["bm25"][k] for k in ("k1","b")}
                expected=BM25(docs,**params).search(query,1024,excluded)
                actual=session.lexical.search(query,kind,1024,excluded)
                key=lambda h:h.get("passage_id",h["case_id"])
                if list(map(key,expected))!=list(map(key,actual)) or not np.allclose([x["score"] for x in expected],[x["score"] for x in actual],atol=1e-10,rtol=1e-10):
                    raise M3Error("Persistent lexical index differs from baseline BM25")
                lexical.append({"kind":kind,"hits":len(actual),"status":"PASS"})
            rows.append({"query":query,"excluded_case":excluded,"local_seconds":timings,"results":result["results"],"lexical_reference":lexical,
                         "query_remote_seconds":response["remote_elapsed_seconds"]})
        result={"status":"PASS_local_search_with_real_query_vectors","queries":rows,"usage":cache.usage(),
                "baseline_original_search_cli_seconds":[67.331,66.326,66.169],"scope":"same_pilot_only_no_gold"}
        write_json(target/"search_benchmark.json",result)
        return result
    except Exception as exc:
        write_json(target/"failure.json",{"status":"partial","error_type":type(exc).__name__,"usage":cache.usage(),"completed_queries":rows})
        raise


if __name__=="__main__":raise SystemExit(main())
