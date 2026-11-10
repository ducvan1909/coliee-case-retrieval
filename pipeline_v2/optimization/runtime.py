"""Optimization-only authenticated backend and complete request accounting."""
import time
import math

from ..retrieval.runtime import validate_response
from ..retrieval.common import fingerprint
from .common import M3Error


class BenchmarkOOM(M3Error):
    pass


class OptModalEmbedder:
    def __init__(self,profile):
        import modal
        p=profile["embedding"]
        self.remote=modal.Cls.from_name(p["modal_app"],p["modal_class"])()

    def encode(self,texts,kind="document"):
        return self.remote.encode.remote(texts,kind)


def _aliased_code(code):
    return {"pipeline_v2/deployments/modal/engine.py":code["pipeline_v2/deployments/modal_opt/engine.py"],
            "pipeline_v2/deployments/modal/qwen3_embed.py":code["pipeline_v2/deployments/modal_opt/qwen3_embed.py"]}


def request_embedding(embedder,texts,profile,tokenizer,code,ledger,batch_id):
    if not isinstance(texts,list) or not texts or len(texts)>128 or any(not isinstance(t,str) or not t for t in texts):
        raise M3Error("Invalid optimization document batch")
    ids=[tokenizer.backend.encode(t,add_special_tokens=True).ids for t in texts]
    if any(len(row)>profile["embedding"]["max_tokens"] for row in ids):
        raise M3Error("Optimization input exceeds token cap")
    attempt=ledger.begin(batch_id,"optimization_document")
    start=time.perf_counter()
    response=None
    try:
        response=embedder.encode(texts,"document")
        if response.get("status")=="oom":
            d=response.get("descriptor",{})
            if d.get("embedding_fingerprint")!=fingerprint(profile) or d.get("engine_sha256")!=_aliased_code(code)["pipeline_v2/deployments/modal/engine.py"]:
                raise M3Error("OOM response runtime identity mismatch")
            safe={k:response.get(k) for k in ("descriptor","input_tokens","padded_tokens","remote_elapsed_seconds","peak_allocated_bytes","peak_reserved_bytes","token_consumption")}
            ledger.finish(attempt,"oom",time.perf_counter()-start,None,"CUDAOutOfMemory",receipt=safe)
            raise BenchmarkOOM("CUDA OOM; stop larger benchmark sizes")
        vectors=validate_response(response,texts,"document",profile,tokenizer,_aliased_code(code))
        for key in ("gpu_model_pool_seconds","peak_allocated_bytes","peak_reserved_bytes","device_total_bytes"):
            v=response.get(key)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:
                raise M3Error("Invalid GPU metric: "+key)
        if response["peak_allocated_bytes"]>response["peak_reserved_bytes"] or response["peak_reserved_bytes"]>response["device_total_bytes"]:
            raise M3Error("Inconsistent GPU memory metrics")
        safe={k:response.get(k) for k in ("descriptor","input_hashes","input_tokens","padded_tokens","remote_elapsed_seconds","gpu_model_pool_seconds","peak_allocated_bytes","peak_reserved_bytes","device_total_bytes")}
        elapsed=time.perf_counter()-start
        safe["client_elapsed_seconds"]=elapsed
        ledger.finish(attempt,"success",elapsed,response["input_tokens"],receipt=safe)
        return vectors,{**response,"client_elapsed_seconds":elapsed}
    except BenchmarkOOM:
        raise
    except Exception as exc:
        tokens=response.get("input_tokens") if isinstance(response,dict) else None
        if type(tokens) is not int or tokens < 0: tokens=None
        ledger.finish(attempt,"error",time.perf_counter()-start,tokens,type(exc).__name__)
        if isinstance(exc,M3Error): raise
        raise M3Error("Optimization request failed: "+type(exc).__name__) from exc
