"""One V2 runtime for both query and document, with an explicit compatibility gate."""
import math
from pathlib import Path
import time

import numpy as np

from ..passages import PinnedTokenizer
from ..retrieval.cache import Cache, run_lock
from ..retrieval.common import fingerprint
from ..retrieval.runtime import ModalEmbedder, call_embedding, render_query, validate_response
from ..source.core import canonical, digest
from .common import M3Error, artifact, file_digest, implementation, load_profile, read, write_json


class BenchmarkOOM(M3Error):pass


class OptModalEmbedder:
    def __init__(self,profile):
        import modal
        p=profile["embedding"]
        self.remote=modal.Cls.from_name(p["modal_app"],p["modal_class"])()
    def encode(self,texts,kind="document"):return self.remote.encode.remote(texts,kind)


def alias_code(code):
    return {"pipeline_v2/deployments/modal/engine.py":code["pipeline_v2/deployments/modal_opt_v2/engine.py"],
            "pipeline_v2/deployments/modal/qwen3_embed.py":code["pipeline_v2/deployments/modal_opt_v2/qwen3_embed.py"]}


def request_embedding(embedder,texts,kind,profile,tokenizer,code,ledger,label):
    if kind not in ("document","query") or not isinstance(texts,list) or not texts or len(texts)>128 or any(not isinstance(t,str) or not t for t in texts):
        raise M3Error("Invalid V2 embedding input")
    if kind=="query" and any(not t.strip() for t in texts):raise M3Error("Empty query")
    rendered=[render_query(t,profile) if kind=="query" else t for t in texts]
    ids=[tokenizer.backend.encode(t,add_special_tokens=True).ids for t in rendered]
    if any(len(row)>profile["embedding"]["max_tokens"] or not row or row[-1]!=151643 for row in ids):raise M3Error("V2 token cap/EOS mismatch before inference")
    attempt=ledger.begin(label,"v2_"+kind);started=time.perf_counter();response=None
    try:
        response=embedder.encode(texts,kind)
        if response.get("status")=="oom":
            d=response.get("descriptor",{})
            if d.get("embedding_fingerprint")!=fingerprint(profile) or d.get("engine_sha256")!=alias_code(code)["pipeline_v2/deployments/modal/engine.py"]:
                raise M3Error("Unattested OOM response")
            ledger.finish(attempt,"oom",time.perf_counter()-started,None,"CUDAOutOfMemory",receipt={k:response.get(k) for k in ("descriptor","input_tokens","padded_tokens","peak_allocated_bytes","peak_reserved_bytes","remote_elapsed_seconds","token_consumption")})
            raise BenchmarkOOM("CUDA OOM; no processed-token count assumed")
        vectors=validate_response(response,texts,kind,profile,tokenizer,alias_code(code))
        if response["descriptor"].get("gpu")!="NVIDIA L4":raise M3Error("Expected real L4 descriptor")
        for key in ("gpu_model_pool_seconds","peak_allocated_bytes","peak_reserved_bytes","device_total_bytes"):
            v=response.get(key)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:raise M3Error("Invalid V2 GPU metric: "+key)
        if not 0<response["device_total_bytes"] or not response["peak_allocated_bytes"]<=response["peak_reserved_bytes"]<=response["device_total_bytes"]:
            raise M3Error("Inconsistent V2 GPU memory metrics")
        receipt={k:response.get(k) for k in ("descriptor","input_hashes","input_tokens","padded_tokens","remote_elapsed_seconds","gpu_model_pool_seconds","peak_allocated_bytes","peak_reserved_bytes","device_total_bytes")}
        elapsed=time.perf_counter()-started;receipt["client_elapsed_seconds"]=elapsed
        ledger.finish(attempt,"success",elapsed,response["input_tokens"],receipt=receipt)
        return vectors,{**response,"client_elapsed_seconds":elapsed}
    except BenchmarkOOM:raise
    except Exception as exc:
        tokens=response.get("input_tokens") if isinstance(response,dict) else None
        if type(tokens) is not int or tokens<0:tokens=None
        ledger.finish(attempt,"error",time.perf_counter()-started,tokens,type(exc).__name__)
        if isinstance(exc,M3Error):raise
        raise M3Error("V2 embedding request failed: "+type(exc).__name__) from exc


def runtime_dir(session):return session.directory.parent/(session.directory.name+"_runtime")


def _bindings(session):
    return {"embedding_fingerprint":fingerprint(session.manifest["profile"]),
            "baseline_embedding_fingerprint":session.base["embedding_fingerprint"],
            "index_manifest_sha256":file_digest(session.directory/"manifest.json"),
            "optimization_implementation":implementation()}


def require_compatibility(session,path,allow_simulated=False):
    if path is None:raise M3Error("V2 query compatibility preflight is required")
    path=artifact(session.root,path)
    if path.is_dir():path=path/"compatibility.json"
    pointer=read(runtime_dir(session)/"compatibility_current.json")
    if pointer.get("status") not in (("PASS","simulated") if allow_simulated else ("PASS",)):
        raise M3Error("Latest V2 preflight has not passed")
    receipt=read(path);raw_hash=file_digest(path)
    if pointer.get("receipt")!=path.relative_to(session.root).as_posix() or pointer.get("receipt_sha256")!=raw_hash:
        raise M3Error("Compatibility receipt is stale or changed")
    if read(path.with_name("compatibility.sha256.json"))!={"sha256":raw_hash}:raise M3Error("Compatibility receipt integrity failure")
    expected_status=("PASS","simulated") if allow_simulated else ("PASS",)
    if receipt.get("status") not in expected_status or receipt.get("execution_mode") not in (("real","simulated") if allow_simulated else ("real",)):
        raise M3Error("Simulated compatibility cannot enable real inference")
    if any(receipt.get(k)!=v for k,v in _bindings(session).items()):raise M3Error("V2 compatibility fingerprint/index/code drift")
    atol=session.manifest["profile"]["compatibility"]["cosine_atol"]
    docs=receipt.get("document_checks",{});queries=receipt.get("query_checks",[])
    if docs.get("count")!=8 or len(queries)!=3:raise M3Error("Incomplete V2 compatibility checks")
    deviations=[docs.get("max_cosine_deviation"),docs.get("max_singleton_batch_deviation")]+[q.get("cosine_deviation") for q in queries]
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or abs(x)>atol for x in deviations):
        raise M3Error("Compatibility numerical tolerance not satisfied")
    if any(not q.get("baseline_descriptor") or not q.get("v2_descriptor") for q in queries):raise M3Error("Query runtime attestation missing")
    return receipt


def preflight_compatibility(root,index_dir,output,embedder=None,baseline_embedder=None):
    from .index import FastSession
    root=Path(root).resolve();target=artifact(root,output)
    if target.exists():raise M3Error("Preflight output exists; choose a new directory")
    session=FastSession(root,index_dir);p=session.manifest["profile"]
    target.mkdir(parents=True,exist_ok=False);runtime=runtime_dir(session)
    simulated=embedder is not None or baseline_embedder is not None
    result={"status":"in_progress","execution_mode":"simulated" if simulated else "real",**_bindings(session)}
    ledger=Cache(target,result["embedding_fingerprint"],session.vectors.shape[1]);runtime.mkdir(parents=True,exist_ok=True)
    pointer_path=runtime/"compatibility_current.json"
    try:
        with run_lock(runtime):
            # Invalidate old success before network/auth/model initialization.
            write_json(pointer_path,{"status":"in_progress","attempt_output":target.relative_to(root).as_posix()},replace=True)
            write_json(target/"compatibility.json",result)
            try:
                session.guard();session.cheap_db_check()
                tok=PinnedTokenizer(root,"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
                new=embedder or OptModalEmbedder(p);old=baseline_embedder or ModalEmbedder(session.base["profile"])
                ordered=sorted(session.ids,key=lambda ident:(session.passage_metadata([ident])[0]["full_input_tokens"],ident))
                ids=[ordered[round(i*(len(ordered)-1)/7)] for i in range(8)]
                docs=session.full_passages(ids)
                vectors,response=request_embedding(new,[d["text"] for d in docs],"document",p,tok,result["optimization_implementation"],ledger,"compatibility-documents-8")
                reference=np.asarray([session.vectors[session.byid[i]] for i in ids])
                deviation=float(np.max(np.abs(1-np.einsum("ij,ij->i",vectors,reference))))
                single=[]
                for i in (0,7):
                    v,_=request_embedding(new,[docs[i]["text"]],"document",p,tok,result["optimization_implementation"],ledger,f"compatibility-doc-single-{i}")
                    single.append(float(abs(1-v[0]@vectors[i])))
                result["document_checks"]={"count":8,"passage_ids":ids,"max_cosine_deviation":deviation,"max_singleton_batch_deviation":max(single),"descriptor":response["descriptor"]}
                result["query_checks"]=[]
                for i,query in enumerate(p["compatibility"]["query_fixtures"]):
                    before,baseline_response=call_embedding(old,[query],"query",session.base["profile"],tok,session.base["implementation"],ledger,f"compatibility-baseline-query-{i}")
                    after,new_response=request_embedding(new,[query],"query",p,tok,result["optimization_implementation"],ledger,f"compatibility-v2-query-{i}")
                    if baseline_response["token_ids"]!=new_response["token_ids"] or baseline_response["input_hashes"]!=new_response["input_hashes"]:
                        raise M3Error("Baseline and V2 query rendered inputs differ")
                    result["query_checks"].append({"query":query,"cosine_deviation":float(abs(1-before[0]@after[0])),
                        "baseline_descriptor":baseline_response["descriptor"],"v2_descriptor":new_response["descriptor"],
                        "input_hashes":new_response["input_hashes"]})
                atol=p["compatibility"]["cosine_atol"]
                if max([deviation,*single,*[q["cosine_deviation"] for q in result["query_checks"]]])>atol:raise M3Error("Baseline/V2 vector space compatibility failed")
                result["status"]="simulated" if simulated else "PASS"
            except Exception as exc:
                result.update(status="failed",error_type=type(exc).__name__)
                raise
            finally:
                result["usage"]=ledger.usage()
                write_json(target/"compatibility.json",result,replace=True)
                raw_hash=file_digest(target/"compatibility.json")
                if result["status"] in ("PASS","simulated"):
                    write_json(target/"compatibility.sha256.json",{"sha256":raw_hash})
                write_json(pointer_path,{"status":result["status"],"receipt":(target/"compatibility.json").relative_to(root).as_posix(),"receipt_sha256":raw_hash},replace=True)
                ledger.db.close();session.close()
    except Exception:
        ledger.db.close();session.close()
        raise
    return result


def query_embedding(session,query,embedder=None):
    p=session.manifest["profile"];code=implementation();ledger=Cache(runtime_dir(session),fingerprint(p),session.vectors.shape[1])
    try:
        tok=PinnedTokenizer(session.root,"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
        vector,response=request_embedding(embedder or OptModalEmbedder(p),[query],"query",p,tok,code,ledger,"unified-search-query")
        return vector[0],{"runtime":"unified_v2","client_rpc_seconds":response["client_elapsed_seconds"],
                          "remote_total_seconds":response["remote_elapsed_seconds"],"input_tokens":response["input_tokens"],
                          "embedding_fingerprint":fingerprint(p),"descriptor":response["descriptor"]}
    finally:ledger.db.close()
