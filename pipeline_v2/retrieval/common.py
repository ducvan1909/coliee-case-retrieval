"""M3 deterministic profiles and atomic local records."""
import json
import os
from pathlib import Path
import tempfile
import math

from ..source.core import canonical, digest
from ..source.store import contained, read_json


class M3Error(ValueError):
    pass


def write_json(path, value, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value)
    if not replace:
        with path.open("xb") as stream:
            stream.write(raw)
        return
    fd, name = tempfile.mkstemp(prefix=".m3-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_profile(root):
    path = contained(Path(root).resolve(), "pipeline_v2/configs/m3.json", "pipeline_v2/configs")
    profile = read_json(path)
    if (profile.get("schema_version") != "pipeline-v2-m3-profile-1" or
        profile.get("mode") != "pilot_only" or profile.get("pilot_size") != 1024 or
        profile.get("passages_bundle") != "pipeline_v2/artifacts/m2_passages_20261106_v1" or
        profile.get("accepted_m2_seal_sha256") != "0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6" or
        profile["embedding"]["model"] != "Qwen/Qwen3-Embedding-4B" or
        profile["embedding"]["revision"] != "5cf2132abc99cad020ac570b19d031efec650f2b" or
        profile["embedding"]["dimensions"] != 2560 or profile["embedding"]["max_tokens"] != 448):
        raise M3Error("Unsupported frozen M3 pilot profile")
    expected={"weights_dtype":"bfloat16","output_dtype":"float32","pooling":"last_nonpadding_token","normalization":"l2","document_template":"{body}","add_special_tokens":True,"truncation":False}
    if any(profile["embedding"].get(k)!=v for k,v in expected.items()):raise M3Error("Unsupported M3 encoding policy")
    if type(profile["batch_size"]) is not int or not 1<=profile["batch_size"]<=16:raise M3Error("Pilot batch size must be1..16")
    if type(profile["max_attempts"]) is not int or not 1<=profile["max_attempts"]<=3:raise M3Error("Pilot retries must be bounded1..3")
    k1,b=profile["bm25"]["k1"],profile["bm25"]["b"]
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (k1,b)) or k1<=0 or not 0<=b<=1:raise M3Error("Invalid BM25 parameters")
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not 0<x<=.01 for x in profile["numerics"].values()):raise M3Error("Invalid numeric verification tolerance")
    if profile["numerics"]["norm_atol"]!=.002:raise M3Error("Norm tolerance must match vector validation contract")
    return profile


def implementation():
    root = Path(__file__).resolve().parents[2]
    names = ["pipeline_v2/m3.py"] + [p.relative_to(root).as_posix() for p in sorted((root/"pipeline_v2/retrieval").glob("*.py"))]
    names += [p.relative_to(root).as_posix() for p in sorted((root/"pipeline_v2/deployments/modal").glob("*.py"))]
    return {name: digest((root/name).read_bytes()) for name in names if (root/name).exists()}


def fingerprint(profile):
    return digest(canonical(profile["embedding"]))
