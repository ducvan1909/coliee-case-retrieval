"""V2 profiles, streaming integrity checks and frozen implementation map."""
import json
from pathlib import Path
import hashlib

from ..retrieval.common import M3Error, write_json
from ..source.core import canonical, digest
from ..source.store import contained

PROFILE="pipeline_v2/configs/m3_opt_v2.json"
BASELINE="pipeline_v2/artifacts/m3_pilot_20261106_l4_v1"
REQUIRED_FILES={"lexical.sqlite3","vectors.npy","manifest.json"}


def read(path):
    return json.loads(Path(path).read_bytes())


def file_digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def artifact(root,path):
    value=contained(Path(root).resolve(),path,"pipeline_v2/artifacts")
    if value==(Path(root).resolve()/"pipeline_v2/artifacts"):raise M3Error("Choose an artifact child directory")
    return value


def implementation():
    root=Path(__file__).resolve().parents[2]
    paths=[root/"pipeline_v2/m3_opt_v2.py"]
    for directory in ("optimization_v2","deployments/modal_opt_v2"):
        paths.extend(sorted((root/"pipeline_v2"/directory).glob("*.py")))
    paths.extend(root/name for name in ("pipeline_v2/optimization/index.py","pipeline_v2/optimization/common.py"))
    return {p.relative_to(root).as_posix():file_digest(p) for p in paths if p.exists()}


def load_profile(root):
    p=read(Path(root)/PROFILE)
    if p.get("schema_version")!="pipeline-v2-m3-opt-2" or p.get("baseline_run")!=BASELINE:
        raise M3Error("Unsupported revision-2 pilot profile")
    base=read(Path(root)/"pipeline_v2/configs/m3.json")["embedding"]
    allowed={"modal_app","max_batch_size","scaledown_window_seconds"}
    if any(p["embedding"].get(k)!=v for k,v in base.items() if k not in allowed):
        raise M3Error("Revision-2 embedding semantics differ from accepted model")
    if p["embedding"].get("gpu")!="L4" or p["embedding"].get("max_batch_size")!=128:
        raise M3Error("Unsupported GPU or stress batch cap")
    b=p["benchmark"]
    if (b["batch_sizes"]!=[16,32,64] or b["strata"]!=4 or b["documents_per_stratum"]!=64
        or type(b["repeats"]) is not int or not 3<=b["repeats"]<=5
        or b["stress_batch_sizes"]!=[16,32,64,128]):raise M3Error("Unsupported bounded benchmark grid")
    if not 0<p["compatibility"]["cosine_atol"]<=.001:raise M3Error("Unsupported compatibility tolerance")
    if p["compatibility"].get("document_fixtures")!=8 or len(p["compatibility"].get("query_fixtures",[]))!=3:
        raise M3Error("Compatibility fixture coverage must be8documents and3queries")
    return p


def seal(directory,names):
    return {name:{"sha256":file_digest(directory/name),"byte_length":(directory/name).stat().st_size} for name in names}


def validate_seal(directory,files):
    if set(files)!=REQUIRED_FILES:raise M3Error("Index seal must include exact immutable snapshot files")
    for name,expected in files.items():
        path=directory/name
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):raise M3Error("Unsafe index file")
        if expected!={"sha256":file_digest(path),"byte_length":path.stat().st_size}:raise M3Error("Index content drift: "+name)
