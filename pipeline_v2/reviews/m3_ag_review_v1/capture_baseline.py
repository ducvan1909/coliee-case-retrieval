"""Capture baseline state of m3_pilot_20261106_l4_v1 and Qdrant before AG pilot execution."""
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1"
OUT_PATH = Path(__file__).resolve().parent / "baseline_state.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    preflight = json.loads((RUN_DIR / "preflight.json").read_bytes())
    manifest_raw = (RUN_DIR / "pilot_manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    seal = json.loads((RUN_DIR / "manifest.sha256.json").read_bytes())

    db = sqlite3.connect(RUN_DIR / "ledger.sqlite3")
    rows = db.execute(
        "SELECT id, batch, phase, started, elapsed, status, requests, tokens, error FROM attempts ORDER BY id"
    ).fetchall()
    db.close()

    vectors_dir = RUN_DIR / "vectors"
    vector_files = sorted(p.name for p in vectors_dir.glob("*")) if vectors_dir.exists() else []
    op_files = sorted(p.name for p in (RUN_DIR / "operations").glob("*.json"))

    with urllib.request.urlopen("http://127.0.0.1:6333/collections", timeout=10) as resp:
        collections = json.loads(resp.read().decode("utf-8"))
    with urllib.request.urlopen(
        f"http://127.0.0.1:6333/collections/{manifest['collection']}", timeout=10
    ) as resp:
        collection_info = json.loads(resp.read().decode("utf-8"))

    baseline = {
        "run_dir": "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1",
        "manifest_sha256": sha256_bytes(manifest_raw),
        "manifest_seal": seal,
        "embedding_fingerprint": manifest["embedding_fingerprint"],
        "collection": manifest["collection"],
        "preflight_status": preflight["status"],
        "preflight_gpu": preflight["descriptor"]["gpu"],
        "preflight_max_batch_cosine_deviation": preflight["max_batch_cosine_deviation"],
        "ledger_attempts_count": len(rows),
        "ledger_known_input_tokens": sum(r[7] or 0 for r in rows),
        "ledger_unknown_token_attempts": sum(r[7] is None for r in rows),
        "ledger_attempts": [
            {
                "id": r[0],
                "batch": r[1],
                "phase": r[2],
                "started": r[3],
                "elapsed_seconds": r[4],
                "status": r[5],
                "requests": r[6],
                "input_tokens": r[7],
                "error": r[8],
            }
            for r in rows
        ],
        "cached_vector_files": vector_files,
        "operation_receipt_files": op_files,
        "run_result_exists": (RUN_DIR / "run_result.json").exists(),
        "progress_exists": (RUN_DIR / "progress.json").exists(),
        "verification_exists": (RUN_DIR / "verification.json").exists(),
        "qdrant_collections": collections["result"]["collections"],
        "qdrant_pilot_collection_points_count": collection_info["result"]["points_count"],
        "qdrant_pilot_collection_status": collection_info["result"]["status"],
    }
    OUT_PATH.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(baseline, sort_keys=True))


if __name__ == "__main__":
    main()
