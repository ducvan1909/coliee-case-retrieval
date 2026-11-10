"""Bounded real measurements, not full-corpus inference."""
from pathlib import Path
import time

import numpy as np

from ..passages import PinnedTokenizer
from ..retrieval.cache import Cache, run_lock
from ..source.core import canonical,digest
from .common import M3Error, artifact, implementation, load_profile, write_json
from .batching import batches,padding_stats
from .index import FastSession
from .runtime import OptModalEmbedder,request_embedding,BenchmarkOOM


def representative(passages,size=256):
    values=sorted(passages,key=lambda p:(p["full_input_tokens"],p["passage_id"]))
    if type(size) is not int or size<2 or len(values)<size:
        raise M3Error("Not enough representative pilot documents")
    return [values[round(i*(len(values)-1)/(size-1))] for i in range(size)]


def benchmark_index(root,index_dir,output,embedder=None):
    root=Path(root).resolve()
    target=artifact(root,output)
    if target.exists():
        raise M3Error("Benchmark output exists; choose a new directory")
    profile=load_profile(root)
    session=FastSession(root,index_dir)
    target.mkdir(parents=True,exist_ok=False)
    chosen=representative(session.passages,profile["benchmark"]["representative_size"])
    selected_ids=[p["passage_id"] for p in chosen]
    plan={"profile":profile,"optimization_implementation":implementation(),"index_manifest_sha256":digest((session.directory/"manifest.json").read_bytes()),
          "representative_ids":selected_ids,"purpose":"bounded_batch_throughput_and_numeric_parity_not_full_embedding",
          "maximum_documents_if_all_grid_sizes_complete":16+sum(profile["benchmark"]["batch_sizes"])+len(chosen)*profile["benchmark"]["repeats"]*len(profile["benchmark"]["batch_sizes"])}
    write_json(target/"benchmark_plan.json",plan)
    tok=PinnedTokenizer(root,"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
    ledger=Cache(target,digest(canonical(profile["embedding"])),profile["embedding"]["dimensions"])
    remote=embedder or OptModalEmbedder(profile)
    result={"status":"running","execution_mode":"simulated" if embedder is not None else "real_modal",
            "grid":[],"baseline_vector_fingerprint":session.base["embedding_fingerprint"],"selected_documents":len(chosen),"full_corpus_executed":False}
    started=time.perf_counter()
    def request(group,label):
        vectors,response=request_embedding(remote,[p["text"] for p in group],profile,tok,plan["optimization_implementation"],ledger,label)
        reference=np.asarray([session.vectors[session.byid[p["passage_id"]]] for p in group])
        deviations=1-np.einsum("ij,ij->i",reference,vectors)
        deviation=float(np.max(deviations))
        if deviation>profile["benchmark"]["parity_cosine_atol"]:
            raise M3Error("Optimized batch vectors differ from accepted baseline beyond tolerance")
        return {"documents":len(group),"input_tokens":response["input_tokens"],"padded_tokens":response["padded_tokens"],
                "remote_total_seconds":response["remote_elapsed_seconds"],"client_seconds":response["client_elapsed_seconds"],
                "gpu_model_pool_seconds":response["gpu_model_pool_seconds"],"peak_allocated_bytes":response["peak_allocated_bytes"],
                "peak_reserved_bytes":response["peak_reserved_bytes"],"device_total_bytes":response["device_total_bytes"],
                "max_cosine_deviation_vs_baseline":deviation}
    try:
        with run_lock(target):
            result["warmup"]=request(chosen[:16],"warmup-16")
            longest=max(chosen,key=lambda p:p["full_input_tokens"])
            for size in profile["benchmark"]["batch_sizes"]:
                row={"batch_size":size,"status":"running","warm_calls":[]}
                result["grid"].append(row)
                try:
                    row["stress"]={**request([longest]*size,f"stress-{size}"),"purpose":"repeated_longest_pilot_text_memory_stress_not_unique_corpus_vectors"}
                    for repeat in range(profile["benchmark"]["repeats"]):
                        for i,group in enumerate(batches(chosen,size)):
                            row["warm_calls"].append(request(group,f"size-{size}-repeat-{repeat}-batch-{i}"))
                    row["documents"]=sum(x["documents"] for x in row["warm_calls"])
                    row["client_seconds"]=sum(x["client_seconds"] for x in row["warm_calls"])
                    row["remote_total_seconds"]=sum(x["remote_total_seconds"] for x in row["warm_calls"])
                    row["end_to_end_documents_per_second"]=row["documents"]/row["client_seconds"]
                    row["remote_documents_per_second"]=row["documents"]/row["remote_total_seconds"]
                    row["memory_headroom_fraction"]=1-max(x["peak_allocated_bytes"] for x in [row["stress"]]+row["warm_calls"])/row["stress"]["device_total_bytes"]
                    row["reserved_headroom_fraction"]=1-max(x["peak_reserved_bytes"] for x in [row["stress"]]+row["warm_calls"])/row["stress"]["device_total_bytes"]
                    row["status"]="PASS"
                except BenchmarkOOM:
                    row["status"]="OOM"
                    result["larger_sizes_not_run_due_to_oom"]=True
                    break
                finally:
                    write_json(target/"benchmark_progress.json",{**result,"usage":ledger.usage()},replace=True)
            eligible=[row for row in result["grid"] if row["status"]=="PASS" and row["memory_headroom_fraction"]>=.1]
            result["winner_batch_size"]=max(eligible,key=lambda x:x["end_to_end_documents_per_second"])["batch_size"] if eligible else None
            result["status"]="simulated" if embedder is not None else "completed_with_limits"
    except Exception as exc:
        result["status"]="failed_partial"
        result["error_type"]=type(exc).__name__
        raise
    finally:
        result["usage"]=ledger.usage()
        result["total_seconds"]=time.perf_counter()-started
        write_json(target/"benchmark_result.json",result,replace=True)
        session.close()
    return result
