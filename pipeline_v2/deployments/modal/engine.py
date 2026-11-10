"""Uploaded verbatim and imported on Modal; no local torch dependency."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time
import uuid


def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Engine:
    def __init__(self,profile_path="/root/pipeline_v2/configs/m3.json",lock_path="/root/pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json"):
        load_started=time.perf_counter()
        import torch
        from transformers import AutoModel, AutoTokenizer
        from huggingface_hub import hf_hub_download
        self.torch=torch
        self.profile=json.loads(Path(profile_path).read_bytes())["embedding"]
        lock=json.loads(Path(lock_path).read_bytes())
        p=self.profile
        for name,expected in lock["files"].items():
            path=hf_hub_download(p["model"],name,revision=p["revision"],cache_dir="/model-cache")
            raw=Path(path).read_bytes()
            if expected!={"sha256":sha(raw),"byte_length":len(raw)}:raise ValueError("Remote tokenizer asset mismatch")
        self.tokenizer=AutoTokenizer.from_pretrained(p["model"],revision=p["revision"],cache_dir="/model-cache",trust_remote_code=False,padding_side="left",use_fast=True)
        self.model=AutoModel.from_pretrained(p["model"],revision=p["revision"],cache_dir="/model-cache",trust_remote_code=False,torch_dtype=torch.bfloat16,attn_implementation="sdpa").to("cuda").eval()
        if self.model.config.hidden_size!=p["dimensions"]:raise ValueError("Model output dimension mismatch")
        if getattr(self.model.config,"_commit_hash",None)!=p["revision"]:raise ValueError("Loaded model revision differs from pinned snapshot")
        self.descriptor={"embedding_fingerprint":sha(canonical(p)),"model":p["model"],"revision":p["revision"],
                         "engine_sha256":sha(Path(__file__).read_bytes()),
                         "wrapper_sha256":sha(Path("/root/qwen3_embed.py").read_bytes()),
                         "package_versions":{name:importlib.metadata.version(name) for name in ("torch","transformers","tokenizers","modal","numpy","huggingface_hub","safetensors")},
                         "gpu":torch.cuda.get_device_name(),"dimensions":p["dimensions"],"device_dtype":str(next(self.model.parameters()).dtype)}
        self.descriptor["loaded_model_revision"]=self.model.config._commit_hash
        self.descriptor["instance_id"]=str(uuid.uuid4())
        self.descriptor["model_load_seconds"]=time.perf_counter()-load_started

    def encode(self,texts,kind="document"):
        if kind not in ("document","query") or not isinstance(texts,list) or not texts or any(not isinstance(x,str) or not x for x in texts):raise ValueError("Invalid embedding input")
        if kind=="query" and any(not x.strip() for x in texts):raise ValueError("Empty query")
        if len(texts)>16:raise ValueError("Pilot server maximum batch is16")
        t=time.perf_counter(); torch=self.torch
        rendered=[f"Instruct: {self.profile['query_instruction']}\nQuery:{x}" if kind=="query" else x for x in texts]
        ids=[self.tokenizer.encode(x,add_special_tokens=True,truncation=False) for x in rendered]
        if any(len(x)>self.profile["max_tokens"] or x[-1]!=151643 for x in ids):raise ValueError("Token cap or official EOS mismatch; no truncation")
        batch=self.tokenizer(rendered,padding=True,truncation=False,add_special_tokens=True,return_tensors="pt").to("cuda")
        if [batch["input_ids"][i][batch["attention_mask"][i].bool()].tolist() for i in range(len(texts))]!=ids:raise ValueError("Padding changed input IDs")
        with torch.inference_mode():
            output=self.model(**batch,use_cache=False).last_hidden_state
            last_positions=(batch["attention_mask"]*torch.arange(output.shape[1],device=output.device)).max(dim=1).values
            pooled=output[torch.arange(len(texts),device=output.device),last_positions].float()
            vectors=torch.nn.functional.normalize(pooled,p=2,dim=1).cpu().numpy()
        return {"descriptor":self.descriptor,"input_hashes":[sha(x.encode("utf-8")) for x in rendered],
                "token_ids":ids,"vectors":vectors.tolist(),"input_tokens":sum(map(len,ids)),
                "padded_tokens":int(batch["attention_mask"].numel()),"remote_elapsed_seconds":time.perf_counter()-t}
