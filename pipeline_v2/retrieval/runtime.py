"""Explicit remote adapter; ordinary module imports do not call Modal."""
import time

import numpy as np

from ..passages import PinnedTokenizer
from ..source.core import digest
from .cache import validate_vectors
from .common import M3Error, fingerprint


class ModalEmbedder:
    def __init__(self,profile):
        import modal
        self.remote=modal.Cls.from_name(profile["embedding"]["modal_app"],profile["embedding"]["modal_class"])()

    def encode(self,texts,kind="document"):
        return self.remote.encode.remote(texts,kind)


def render_query(text,profile):
    return f"Instruct: {profile['embedding']['query_instruction']}\nQuery:{text}"


def validate_response(response,texts,kind,profile,tokenizer,code):
    if kind not in ("document","query"):raise M3Error("Invalid embedding input kind")
    descriptor=response.get("descriptor",{})
    e=profile["embedding"]
    if (descriptor.get("embedding_fingerprint")!=fingerprint(profile) or descriptor.get("model")!=e["model"] or
        descriptor.get("revision")!=e["revision"] or descriptor.get("dimensions")!=e["dimensions"] or
        descriptor.get("loaded_model_revision")!=e["revision"] or descriptor.get("device_dtype")!="torch.bfloat16" or
        descriptor.get("engine_sha256")!=code["pipeline_v2/deployments/modal/engine.py"] or
        descriptor.get("wrapper_sha256")!=code["pipeline_v2/deployments/modal/qwen3_embed.py"]):
        raise M3Error("Remote runtime implementation/profile mismatch")
    versions=descriptor.get("package_versions",{})
    for name in ("torch","transformers","tokenizers"):
        # Torch CUDA wheels append +cuNNN but preserve pinned release.
        if versions.get(name,"").split("+")[0]!=e[name]:raise M3Error("Remote package version mismatch: "+name)
    if versions.get("modal")!="1.5.3":raise M3Error("Remote Modal package version mismatch")
    rendered=[render_query(x,profile) if kind=="query" else x for x in texts]
    hashes=[digest(x.encode("utf-8")) for x in rendered]
    ids=[tokenizer.backend.encode(x,add_special_tokens=True).ids for x in rendered]
    if response.get("input_hashes")!=hashes or response.get("token_ids")!=ids or any(len(x)>e["max_tokens"] or x[-1]!=151643 for x in ids):
        raise M3Error("Remote/local input parity mismatch")
    if response.get("input_tokens")!=sum(map(len,ids)):raise M3Error("Remote token accounting mismatch")
    if response.get("padded_tokens")!=len(ids)*max(map(len,ids)):raise M3Error("Remote padded-token accounting mismatch")
    elapsed=response.get("remote_elapsed_seconds")
    if not isinstance(elapsed,(int,float)) or isinstance(elapsed,bool) or not np.isfinite(elapsed) or elapsed<0:raise M3Error("Invalid remote latency")
    return validate_vectors(response["vectors"],len(texts),e["dimensions"])


def call_embedding(embedder,texts,kind,profile,tokenizer,code,cache,batch_id):
    if kind not in ("document","query") or not texts or any(not isinstance(x,str) or not x for x in texts):raise M3Error("Invalid input")
    if kind=="query" and any(not x.strip() for x in texts):raise M3Error("Empty query")
    rendered=[render_query(x,profile) if kind=="query" else x for x in texts]
    if any(tokenizer.count(x)>profile["embedding"]["max_tokens"] for x in rendered):raise M3Error("Local input exceeds cap before inference")
    for attempt in range(profile["max_attempts"]):
        ident=cache.begin(batch_id,kind)
        started=time.perf_counter()
        response=None
        try:
            response=embedder.encode(texts,kind)
            vectors=validate_response(response,texts,kind,profile,tokenizer,code)
            receipt={k:response.get(k) for k in ("descriptor","input_hashes","input_tokens","padded_tokens","remote_elapsed_seconds")}
            cache.finish(ident,"success",time.perf_counter()-started,response["input_tokens"],receipt=receipt)
            return vectors,response
        except Exception as exc:
            tokens=response.get("input_tokens") if isinstance(response,dict) else None
            cache.finish(ident,"error",time.perf_counter()-started,tokens,type(exc).__name__)
            transient=isinstance(exc,(TimeoutError,ConnectionError)) or type(exc).__name__ in ("UnavailableError","FunctionTimeoutError")
            if not transient or attempt+1==profile["max_attempts"]:raise M3Error("Embedding attempt failed: "+type(exc).__name__) from exc
            time.sleep(min(2**attempt,4))
    raise M3Error("Embedding retry loop exhausted")
