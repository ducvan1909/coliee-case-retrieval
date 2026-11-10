"""Four locally dense length strata, counterbalanced sizes, disjoint timings."""
from pathlib import Path
import random
import time

import numpy as np

from ..passages import PinnedTokenizer
from ..retrieval.cache import Cache, run_lock
from ..retrieval.common import fingerprint
from .common import M3Error, artifact, implementation, write_json
from .index import FastSession
from .runtime import BenchmarkOOM, OptModalEmbedder, request_embedding, require_compatibility


def stratified_windows(passages):
    values=sorted(passages,key=lambda p:(p["full_input_tokens"],p["passage_id"]))
    if len(values)<256 or len({p["passage_id"] for p in values})!=len(values):raise M3Error("Need at least256 unique pilot passages")
    result=[]
    for i in range(4):
        lo=i*len(values)//4;hi=(i+1)*len(values)//4
        if hi-lo<64:raise M3Error("Insufficient stratum width")
        start=lo+(hi-lo-64)//2
        docs=values[start:start+64]
        result.append({"stratum_id":f"length_quarter_{i+1}","passage_ids":[p["passage_id"] for p in docs],
                       "min_tokens":docs[0]["full_input_tokens"],"max_tokens":docs[-1]["full_input_tokens"],
                       "input_tokens":sum(p["full_input_tokens"] for p in docs),"documents":64,
                       "selection":"centered_contiguous64_within_sorted_quarter_not_all_corpus_distribution"})
    return result


def crossover_orders(sizes,repeats,seed):
    base=list(sizes);random.Random(seed).shuffle(base)
    return [base[i%len(base):]+base[:i%len(base)] for i in range(repeats)]


def benchmark_index(root,index_dir,output,compatibility,embedder=None):
    root=Path(root).resolve();target=artifact(root,output)
    if target.exists():raise M3Error("Benchmark output exists")
    session=FastSession(root,index_dir);profile=session.manifest["profile"]
    try:require_compatibility(session,compatibility,allow_simulated=embedder is not None)
    except Exception:
        session.close();raise
    metadata=list(session.lexical.iter_documents("passage"));strata=stratified_windows(metadata)
    selected=[ident for s in strata for ident in s["passage_ids"]];docs={p["passage_id"]:p for p in session.full_passages(selected)}
    longest=max(metadata,key=lambda p:(p["full_input_tokens"],p["passage_id"]))
    longest=session.full_passages([longest["passage_id"]])[0]
    b=profile["benchmark"];orders=crossover_orders(b["batch_sizes"],b["repeats"],b["seed"])
    target.mkdir(parents=True,exist_ok=False);code=implementation()
    plan={"profile":profile,"optimization_implementation":code,"strata":strata,"orders":orders,
          "index_dir":session.directory.relative_to(root).as_posix(),"selected_unique_documents":len(selected),
          "warm_encodings_planned":len(selected)*b["repeats"]*len(b["batch_sizes"]),
          "warmup_and_stress_encodings_planned":16+sum(b["stress_batch_sizes"]),
          "candidate128":"memory_stress_only_not_throughput_candidate","full_corpus_executed":False}
    write_json(target/"benchmark_plan.json",plan)
    tok=PinnedTokenizer(root,"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
    ledger=Cache(target,fingerprint(profile),session.vectors.shape[1]);remote=embedder or OptModalEmbedder(profile)
    result={"status":"running","execution_mode":"simulated" if embedder is not None else "real_modal",
            "grid":[{"batch_size":size,"status":"pending","warm_calls":[]} for size in b["batch_sizes"]],"stress":[],"orders":orders}
    rows={r["batch_size"]:r for r in result["grid"]};started=time.perf_counter()
    def request(group,label):
        vectors,response=request_embedding(remote,[p["text"] for p in group],"document",profile,tok,code,ledger,label)
        refs=np.asarray([session.vectors[session.byid[p["passage_id"]]] for p in group])
        deviation=float(np.max(np.abs(1-np.einsum("ij,ij->i",refs,vectors))))
        if deviation>b["parity_cosine_atol"]:raise M3Error("New batch vector space parity failed")
        return {"documents":len(group),"passage_ids":[p["passage_id"] for p in group],"max_cosine_deviation":deviation,
                **{k:response[k] for k in ("input_tokens","padded_tokens","client_elapsed_seconds","remote_elapsed_seconds","gpu_model_pool_seconds","peak_allocated_bytes","peak_reserved_bytes","device_total_bytes")}}
    try:
        with run_lock(target):
            result["warmup"]=request([docs[i] for i in selected[:16]],"warmup-16")
            largest_safe=0
            for size in b["stress_batch_sizes"]:
                try:
                    metric=request([longest]*size,f"stress-{size}")
                    result["stress"].append({"batch_size":size,"status":"PASS",**metric});largest_safe=size
                except BenchmarkOOM:
                    result["stress"].append({"batch_size":size,"status":"OOM"});break
            # Stress128 OOM does not erase viable smaller candidates.
            for repeat,order in enumerate(orders):
                for size in order:
                    row=rows[size]
                    if size>largest_safe or row["status"]=="OOM":row["status"]="OOM";continue
                    try:
                        for stratum in strata:
                            groupdocs=[docs[i] for i in stratum["passage_ids"]]
                            for offset in range(0,len(groupdocs),size):
                                metric=request(groupdocs[offset:offset+size],f"repeat-{repeat}-size-{size}-{stratum['stratum_id']}-batch-{offset//size}")
                                row["warm_calls"].append({"repeat":repeat,"stratum_id":stratum["stratum_id"],**metric})
                        row["status"]="running"
                    except BenchmarkOOM:row["status"]="OOM"
                    finally:write_json(target/"benchmark_progress.json",{**result,"usage":ledger.usage()},replace=True)
            for size,row in rows.items():
                calls=row["warm_calls"]
                if row["status"]=="OOM":continue
                if sum(c["documents"] for c in calls)!=len(selected)*b["repeats"]:raise M3Error("Incomplete fair benchmark candidate")
                row.update(status="PASS",documents=sum(c["documents"] for c in calls),
                           input_tokens=sum(c["input_tokens"] for c in calls),padded_tokens=sum(c["padded_tokens"] for c in calls),
                           client_seconds=sum(c["client_elapsed_seconds"] for c in calls),
                           remote_total_seconds=sum(c["remote_elapsed_seconds"] for c in calls),gpu_model_pool_seconds=sum(c["gpu_model_pool_seconds"] for c in calls))
                row["warm_client_documents_per_second"]=row["documents"]/row["client_seconds"]
                stress=next(s for s in result["stress"] if s["batch_size"]==size and s["status"]=="PASS")
                allcalls=[stress,*calls]
                row["allocated_headroom_fraction"]=1-max(c["peak_allocated_bytes"] for c in allcalls)/stress["device_total_bytes"]
                row["reserved_headroom_fraction"]=1-max(c["peak_reserved_bytes"] for c in allcalls)/stress["device_total_bytes"]
                row["per_stratum"]=[{"stratum_id":s["stratum_id"],"min_tokens":s["min_tokens"],"max_tokens":s["max_tokens"],
                    "documents":sum(c["documents"] for c in calls if c["stratum_id"]==s["stratum_id"]),
                    "input_tokens":sum(c["input_tokens"] for c in calls if c["stratum_id"]==s["stratum_id"]),
                    "padded_tokens":sum(c["padded_tokens"] for c in calls if c["stratum_id"]==s["stratum_id"])} for s in strata]
            eligible=[r for r in rows.values() if r["status"]=="PASS" and r["allocated_headroom_fraction"]>=.1]
            result["winner_batch_size"]=max(eligible,key=lambda r:r["warm_client_documents_per_second"])["batch_size"] if eligible else None
            result["status"]="simulated" if embedder is not None else "completed_with_limits"
            result["limits"]=["four_dense_pilot_windows_not_full_corpus_throughput","winner_only_among_tested_candidates","128_memory_stress_not_speed_candidate"]
    except Exception as exc:
        result.update(status="failed_partial",error_type=type(exc).__name__);raise
    finally:
        result.update(usage=ledger.usage(),total_seconds=time.perf_counter()-started,full_corpus_executed=False)
        write_json(target/"benchmark_result.json",result,replace=True)
        ledger.db.close();session.close()
    return result
