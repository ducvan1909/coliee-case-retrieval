"""M3 pilot CLI. Code does not deploy Modal or start Docker automatically."""
import argparse
import json
import time
import uuid
from pathlib import Path

from .retrieval import M3Error,plan_pilot,preflight,run_pilot,verify_pilot,search_pilot,literal_search
from .retrieval.pilot import load_run
from .retrieval.common import write_json
from .source.store import contained


def operation_receipt(args,result):
    """Immutable command outcomes coexist with mutable latest-state pointers."""
    if not hasattr(args,"run_dir"):return
    try:
        run=contained(Path(args.repo_root).resolve(),args.run_dir,"pipeline_v2/artifacts")
        if not (run/"pilot_manifest.json").is_file():return
        name=f"{time.time_ns()}_{uuid.uuid4().hex}_{args.command}.json"
        write_json(run/"operations"/name,{"command":args.command,"result":result})
    except Exception:
        # Never mask the primary outcome; CLI emits an explicit receipt flag.
        result["operation_receipt_write_failed"]=True


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("plan","preflight","run","verify","search","open","literal"):
        p=sub.add_parser(name)
        p.add_argument("--repo-root",default=".")
        if name=="plan":p.add_argument("--output",required=True)
        else:p.add_argument("--run-dir",required=True)
        if name=="run":p.add_argument("--stop-after-batches",type=int)
        if name=="verify":p.add_argument("--restore-test",action="store_true")
        if name=="search":
            p.add_argument("--query",required=True);p.add_argument("--query-case");p.add_argument("--limit",type=int,default=10)
        if name=="open":p.add_argument("--passage-id",required=True)
        if name=="literal":
            p.add_argument("--text",required=True);p.add_argument("--ignore-case",action="store_true")
    a=parser.parse_args(argv);started=time.perf_counter()
    try:
        if a.command=="plan":r=plan_pilot(a.repo_root,a.output)
        elif a.command=="preflight":r=preflight(a.repo_root,a.run_dir)
        elif a.command=="run":
            if a.stop_after_batches is not None and a.stop_after_batches<1:raise M3Error("stop-after-batches must be positive")
            r=run_pilot(a.repo_root,a.run_dir,stop_after_batches=a.stop_after_batches)
        elif a.command=="verify":r=verify_pilot(a.repo_root,a.run_dir,restore=a.restore_test)
        elif a.command=="search":r=search_pilot(a.repo_root,a.run_dir,a.query,a.query_case,a.limit)
        elif a.command=="literal":r=literal_search(a.repo_root,a.run_dir,a.text,not a.ignore_case)
        else:
            root,run,m,corpus,passages=load_run(a.repo_root,a.run_dir)
            if a.passage_id not in m["passage_ids"]:raise M3Error("Passage is outside pilot")
            r=corpus.open(a.passage_id)
        r["local_elapsed_seconds"]=time.perf_counter()-started
        operation_receipt(a,r)
        print(json.dumps(r,ensure_ascii=True,sort_keys=True));return 2 if r.get("operation_receipt_write_failed") else 0
    except Exception as exc:
        # SDK/network exception strings may contain credentials. Only explicit
        # local validation errors are safe to show verbatim.
        error=str(exc) if isinstance(exc,M3Error) else type(exc).__name__
        r={"status":"error","error":error,"local_elapsed_seconds":time.perf_counter()-started}
        operation_receipt(a,r)
        print(json.dumps(r));return 2


if __name__=="__main__":raise SystemExit(main())
