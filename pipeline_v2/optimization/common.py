import json
from pathlib import Path

from ..retrieval.common import M3Error, write_json
from ..source.core import canonical, digest
from ..source.store import contained

PROFILE = "pipeline_v2/configs/m3_opt.json"


def read(path):
    return json.loads(Path(path).read_bytes())


def load_profile(root):
    p = read(Path(root)/PROFILE)
    if p.get("schema_version") != "pipeline-v2-m3-opt-1" or p["embedding"]["gpu"] != "L4":
        raise M3Error("Unsupported optimization profile")
    if (p["benchmark"]["batch_sizes"] != [16,32,64,128] or
        type(p["benchmark"]["repeats"]) is not int or not 2 <= p["benchmark"]["repeats"] <= 3 or
        p["benchmark"].get("representative_size") != 256):
        raise M3Error("Unsupported bounded benchmark grid")
    if p.get("baseline_run") != "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1":
        raise M3Error("Unexpected accepted baseline")
    base=read(Path(root)/"pipeline_v2/configs/m3.json")["embedding"]
    changed={"modal_app","scaledown_window_seconds","max_batch_size"}
    if any(p["embedding"].get(k)!=v for k,v in base.items() if k not in changed):
        raise M3Error("Optimization model encoding differs from baseline")
    if p["embedding"].get("max_batch_size") != 128:
        raise M3Error("Unexpected benchmark batch cap")
    return p


def implementation():
    root = Path(__file__).resolve().parents[2]
    paths = [root/"pipeline_v2/m3_opt.py"]
    for directory in ("optimization", "deployments/modal_opt"):
        paths += sorted((root/"pipeline_v2"/directory).glob("*.py"))
    return {p.relative_to(root).as_posix():digest(p.read_bytes()) for p in paths if p.exists()}


def artifact(root, path):
    return contained(Path(root).resolve(), path, "pipeline_v2/artifacts")


def seal(directory, names):
    return {n:{"sha256":digest((directory/n).read_bytes()), "byte_length":(directory/n).stat().st_size} for n in names}


def validate_seal(directory, files):
    if set(files)!={"lexical.sqlite3","vectors.npy","manifest.json"}:
        raise M3Error("Optimization seal must cover the exact immutable index files")
    for name, expected in files.items():
        p = directory/name
        if p.is_symlink() or not p.resolve().is_relative_to(directory.resolve()):
            raise M3Error("Unsafe optimization artifact")
        raw = p.read_bytes()
        if expected != {"sha256":digest(raw),"byte_length":len(raw)}:
            raise M3Error("Optimization artifact integrity failure: "+name)
