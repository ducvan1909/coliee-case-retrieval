"""Capture prior state of baseline, V1, V2, full plan, disk space, and Qdrant collections."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import requests

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2.full_corpus import common as full_common
from pipeline_v2.optimization_v2 import common as v2_common
from pipeline_v2.optimization import common as v1_common
from pipeline_v2.retrieval import common as base_common
from pipeline_v2.source.core import canonical, digest


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def snapshot_state():
    # 1. Code & profile fingerprints
    full_impl = full_common.implementation()
    v2_impl = v2_common.implementation()
    v1_impl = v1_common.implementation()
    base_impl = base_common.implementation()

    profiles = {}
    for p in ("pipeline_v2/configs/m3.json", "pipeline_v2/configs/m3_opt.json", "pipeline_v2/configs/m3_opt_v2.json", "pipeline_v2/configs/m3_full.json"):
        profiles[p] = sha256_file(ROOT / p)

    # 2. Seal checks on pilot, V1, V2, M2, and Full Plan
    pilot_dir = ROOT / "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1"
    pilot_files = sorted(p.relative_to(pilot_dir).as_posix() for p in pilot_dir.rglob("*") if p.is_file())
    pilot_manifest_sha = sha256_file(pilot_dir / "pilot_manifest.json")

    v1_index = ROOT / "pipeline_v2/artifacts/m3_opt_index_20261107_v2"
    v1_seal = json.loads((v1_index / "seal.json").read_bytes())

    v2_index = ROOT / "pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1"
    v2_seal = json.loads((v2_index / "seal.json").read_bytes())

    v2_compat = ROOT / "pipeline_v2/artifacts/m3_opt_v2_compat_20261108_v1/compatibility.json"
    v2_compat_sha = sha256_file(v2_compat)

    full_plan = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
    full_seal = json.loads((full_plan / "seal.json").read_bytes())

    # 3. Disk free space on E: (cache + WSL Docker data) and C:
    e_usage = shutil.disk_usage("E:/")
    c_usage = shutil.disk_usage("C:/")

    # 4. Qdrant server & collections
    q_info = requests.get("http://127.0.0.1:6333/", timeout=10).json()
    q_colls = requests.get("http://127.0.0.1:6333/collections", timeout=10).json()["result"]["collections"]
    coll_details = {}
    for c in q_colls:
        name = c["name"]
        cnt = requests.post(f"http://127.0.0.1:6333/collections/{name}/points/count", json={"exact": True}, timeout=10).json()["result"]["count"]
        coll_details[name] = {"exact_count": cnt}

    return {
        "fingerprints": {
            "full_implementation_sha256": digest(canonical(full_impl)),
            "v2_implementation_sha256": digest(canonical(v2_impl)),
            "v1_implementation_sha256": digest(canonical(v1_impl)),
            "base_implementation_sha256": digest(canonical(base_impl)),
            "full_implementation_files": full_impl,
            "profile_sha256": profiles,
        },
        "artifacts": {
            "pilot_file_count": len(pilot_files),
            "pilot_manifest_sha256": pilot_manifest_sha,
            "v1_index_seal": v1_seal,
            "v2_index_seal": v2_seal,
            "v2_compat_sha256": v2_compat_sha,
            "full_plan_seal": full_seal,
        },
        "disk_space": {
            "cache_drive_E": {
                "path": "E:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_full_train_20261108_v1",
                "total_bytes": e_usage.total,
                "used_bytes": e_usage.used,
                "free_bytes": e_usage.free,
                "free_gb": round(e_usage.free / (1024**3), 2),
            },
            "docker_wsl_host_drive_E": {
                "wsl_base_path": "\\\\?\\E:\\Data\\Docker\\DockerDesktopWSL\\main",
                "host_free_bytes": e_usage.free,
                "host_free_gb": round(e_usage.free / (1024**3), 2),
                "qdrant_container_mount": "/qdrant/storage (volume coliee_pipeline_v2_qdrant_storage_v1, 945G virtual avail on /dev/sdd backed by E:)",
            },
            "system_drive_C": {
                "total_bytes": c_usage.total,
                "used_bytes": c_usage.used,
                "free_bytes": c_usage.free,
                "free_gb": round(c_usage.free / (1024**3), 2),
            },
        },
        "qdrant": {
            "version": q_info.get("version"),
            "collections": coll_details,
        },
    }


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "before"
    out_file = Path(__file__).resolve().parent / f"state_{mode}.json"
    data = snapshot_state()
    out_file.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"saved": out_file.name, "full_impl": data["fingerprints"]["full_implementation_sha256"], "E_free_gb": data["disk_space"]["cache_drive_E"]["free_gb"]}))
