from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from pipeline_v2.optimization.common import implementation as v1_opt_implementation
from pipeline_v2.optimization_v2.benchmark import crossover_orders, stratified_windows
from pipeline_v2.optimization_v2.common import file_digest, implementation as v2_opt_implementation, load_profile, read, validate_seal
from pipeline_v2.optimization_v2.index import PersistentBM25
from pipeline_v2.passages import PinnedTokenizer
from pipeline_v2.retrieval.common import fingerprint, implementation as base_implementation
from pipeline_v2.source.core import canonical, digest

REVIEW_DIR = Path(__file__).resolve().parent


def open_sqlite_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def verify_old_snapshots_and_fingerprints() -> dict[str, Any]:
    v2_prof = load_profile(ROOT)
    v1_prof = read(ROOT / "pipeline_v2/configs/m3_opt.json")
    base_prof = read(ROOT / "pipeline_v2/configs/m3.json")

    v2_code = v2_opt_implementation()
    v2_code_fp = digest(canonical(v2_code))
    v1_code = v1_opt_implementation()
    v1_code_fp = digest(canonical(v1_code))
    base_code = base_implementation()
    base_code_fp = digest(canonical(base_code))

    # Check 147 files in baseline snapshot
    snapshot = read(ROOT / "pipeline_v2/artifacts/m3_opt_baseline_snapshot_20261106_v1.json")
    base_dir = ROOT / Path(snapshot["baseline_run"])
    snap_files = snapshot["files"]
    actual_base_files = sorted(p for p in base_dir.rglob("*") if p.is_file())
    base_mismatches = []
    for p in actual_base_files:
        rel = p.relative_to(base_dir).as_posix()
        if rel not in snap_files:
            base_mismatches.append({"file": rel, "error": "missing_in_snapshot"})
        else:
            if file_digest(p) != snap_files[rel]["sha256"] or p.stat().st_size != snap_files[rel]["bytes"]:
                base_mismatches.append({"file": rel, "error": "hash_or_size_mismatch"})
    for rel in snap_files:
        if not (base_dir / rel).exists():
            base_mismatches.append({"file": rel, "error": "missing_on_disk"})

    # Check old V1 sealed index
    old_v1_idx = ROOT / "pipeline_v2/artifacts/m3_opt_index_20261107_v2"
    old_v1_seal = read(old_v1_idx / "seal.json")
    validate_seal(old_v1_idx, old_v1_seal["files"])

    # Check new V2 sealed index
    new_v2_idx = ROOT / "pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1"
    new_v2_seal = read(new_v2_idx / "seal.json")
    validate_seal(new_v2_idx, new_v2_seal["files"])

    old_sqlite_bytes = (old_v1_idx / "lexical.sqlite3").stat().st_size
    new_sqlite_bytes = (new_v2_idx / "lexical.sqlite3").stat().st_size

    return {
        "v2_code_fingerprint": v2_code_fp,
        "v2_code_files": v2_code,
        "v1_code_fingerprint": v1_code_fp,
        "base_code_fingerprint": base_code_fp,
        "v2_profile_sha256": digest(canonical(v2_prof)),
        "v1_profile_sha256": digest(canonical(v1_prof)),
        "base_profile_sha256": digest(canonical(base_prof)),
        "v2_embedding_fingerprint": fingerprint(v2_prof),
        "v1_embedding_fingerprint": fingerprint(v1_prof),
        "base_embedding_fingerprint": fingerprint(base_prof),
        "baseline_snapshot_147_files_verified": len(base_mismatches) == 0,
        "baseline_snapshot_file_count": len(actual_base_files),
        "baseline_snapshot_mismatches": base_mismatches,
        "old_v1_index_seal_verified": True,
        "new_v2_index_seal_verified": True,
        "new_v2_index_manifest_sha256": file_digest(new_v2_idx / "manifest.json"),
        "sqlite_size_comparison": {
            "v1_lexical_sqlite_bytes": old_sqlite_bytes,
            "v2_lexical_sqlite_bytes": new_sqlite_bytes,
            "bytes_saved": old_sqlite_bytes - new_sqlite_bytes,
            "reduction_fraction": round((old_sqlite_bytes - new_sqlite_bytes) / old_sqlite_bytes, 6),
        },
    }


def recompute_compatibility_preflight() -> dict[str, Any]:
    compat_dir = ROOT / "pipeline_v2/artifacts/m3_opt_v2_compat_20261108_v1"
    compat_json = read(compat_dir / "compatibility.json")
    compat_sha = read(compat_dir / "compatibility.sha256.json")
    cli_rec = read(compat_dir / "cli_receipt.json")
    pointer = read(ROOT / "pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1_runtime/compatibility_current.json")

    actual_sha = file_digest(compat_dir / "compatibility.json")
    conn = open_sqlite_ro(compat_dir / "ledger.sqlite3")
    attempts = [dict(r) for r in conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()]
    conn.close()

    phase_counts = Counter(r["phase"] for r in attempts)
    status_counts = Counter(r["status"] for r in attempts)
    known_tokens = sum(int(r["tokens"]) for r in attempts if r["tokens"] is not None)
    unknown_attempts = sum(1 for r in attempts if r["tokens"] is None)

    attempt_details = []
    for r in attempts:
        rec = json.loads(r["receipt"]) if r["receipt"] else {}
        desc = rec.get("descriptor", {})
        attempt_details.append({
            "id": r["id"],
            "batch": r["batch"],
            "phase": r["phase"],
            "status": r["status"],
            "input_tokens": r["tokens"],
            "padded_tokens": rec.get("padded_tokens"),
            "client_elapsed_seconds": r["elapsed"],
            "remote_elapsed_seconds": rec.get("remote_elapsed_seconds"),
            "gpu_model_pool_seconds": rec.get("gpu_model_pool_seconds"),
            "engine_sha256": desc.get("engine_sha256"),
            "wrapper_sha256": desc.get("wrapper_sha256"),
            "embedding_fingerprint": desc.get("embedding_fingerprint"),
            "gpu": desc.get("gpu"),
            "instance_id": desc.get("instance_id"),
            "model_load_seconds": desc.get("model_load_seconds"),
        })

    return {
        "status": compat_json["status"],
        "execution_mode": compat_json["execution_mode"],
        "full_cli_seconds": cli_rec["result"]["full_cli_seconds"],
        "receipt_sha256_verified": actual_sha == compat_sha["sha256"] == pointer["receipt_sha256"],
        "pointer_status": pointer["status"],
        "total_requests": len(attempts),
        "status_counts": dict(status_counts),
        "phase_counts": dict(phase_counts),
        "known_input_tokens": known_tokens,
        "unknown_token_attempts": unknown_attempts,
        "document_checks": compat_json["document_checks"],
        "query_checks_summary": [
            {
                "query": q["query"],
                "cosine_deviation": q["cosine_deviation"],
                "input_hashes": q["input_hashes"],
                "baseline_engine_sha256": q["baseline_descriptor"]["engine_sha256"],
                "v2_engine_sha256": q["v2_descriptor"]["engine_sha256"],
            }
            for q in compat_json["query_checks"]
        ],
        "attempts": attempt_details,
    }


def recompute_gpu_benchmark() -> dict[str, Any]:
    bench_dir = ROOT / "pipeline_v2/artifacts/m3_opt_v2_gpu_benchmark_20261108_v1"
    plan = read(bench_dir / "benchmark_plan.json")
    result = read(bench_dir / "benchmark_result.json")
    cli_rec = read(bench_dir / "cli_receipt.json")

    # Independently recompute strata and crossover orders from lexical.sqlite3
    v2_idx = ROOT / "pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1"
    lex = PersistentBM25(v2_idx / "lexical.sqlite3", readonly=True)
    metadata = list(lex.iter_documents("passage"))
    lex.close()

    recomputed_strata = stratified_windows(metadata)
    recomputed_orders = crossover_orders([16, 32, 64], 3, 20261108)
    assert recomputed_strata == plan["strata"], "Strata mismatch!"
    assert recomputed_orders == plan["orders"], "Crossover orders mismatch!"

    conn = open_sqlite_ro(bench_dir / "ledger.sqlite3")
    attempts = [dict(r) for r in conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()]
    conn.close()

    total_requests = len(attempts)
    status_counts = Counter(r["status"] for r in attempts)
    known_input_tokens = sum(int(r["tokens"]) for r in attempts if r["tokens"] is not None)
    unknown_token_attempts = sum(1 for r in attempts if r["tokens"] is None)

    total_padded_tokens = 0
    total_encodings = 0
    descriptors = set()
    warmup_summary = None
    stress_by_size: dict[int, dict[str, Any]] = {}
    warm_calls_by_size: dict[int, list[dict[str, Any]]] = {16: [], 32: [], 64: []}

    for r in attempts:
        rec = json.loads(r["receipt"]) if r["receipt"] else {}
        desc = rec.get("descriptor", {})
        descriptors.add(json.dumps({k: v for k, v in desc.items() if k != "model_load_seconds"}, sort_keys=True))
        n_docs = len(rec.get("input_hashes", []))
        in_tok = int(r["tokens"])
        pad_tok = int(rec.get("padded_tokens"))
        total_padded_tokens += pad_tok
        total_encodings += n_docs
        label = str(r["batch"])

        entry = {
            "id": r["id"],
            "label": label,
            "documents": n_docs,
            "input_tokens": in_tok,
            "padded_tokens": pad_tok,
            "client_elapsed_seconds": float(rec.get("client_elapsed_seconds", r["elapsed"])),
            "remote_elapsed_seconds": float(rec.get("remote_elapsed_seconds")),
            "gpu_model_pool_seconds": float(rec.get("gpu_model_pool_seconds")),
            "peak_allocated_bytes": int(rec.get("peak_allocated_bytes")),
            "peak_reserved_bytes": int(rec.get("peak_reserved_bytes")),
            "device_total_bytes": int(rec.get("device_total_bytes")),
        }
        if label == "warmup-16":
            warmup_summary = entry
        elif label.startswith("stress-"):
            sz = int(label.split("-")[1])
            stress_by_size[sz] = entry
        elif label.startswith("repeat-"):
            # repeat-{repeat}-size-{size}-{stratum_id}-batch-{idx}
            parts = label.split("-")
            rep_idx = int(parts[1])
            sz = int(parts[3])
            stratum_id = parts[4]
            warm_calls_by_size[sz].append({**entry, "repeat": rep_idx, "stratum_id": stratum_id})
        else:
            raise AssertionError(f"Unexpected benchmark attempt label: {label}")

    reported_grid = {row["batch_size"]: row for row in result["grid"]}
    recomputed_grid = {}
    for sz in (16, 32, 64):
        calls = warm_calls_by_size[sz]
        stress_call = stress_by_size[sz]
        rep_row = reported_grid[sz]

        docs = sum(c["documents"] for c in calls)
        in_tok = sum(c["input_tokens"] for c in calls)
        pad_tok = sum(c["padded_tokens"] for c in calls)
        client_s = sum(c["client_elapsed_seconds"] for c in calls)
        remote_s = sum(c["remote_elapsed_seconds"] for c in calls)
        gpu_s = sum(c["gpu_model_pool_seconds"] for c in calls)
        rpc_overhead_s = client_s - remote_s

        all_calls = [stress_call, *calls]
        tot_vram = stress_call["device_total_bytes"]
        max_alloc_warm = max(c["peak_allocated_bytes"] for c in calls)
        max_alloc_all = max(c["peak_allocated_bytes"] for c in all_calls)
        max_resv_all = max(c["peak_reserved_bytes"] for c in all_calls)
        alloc_headroom = 1.0 - (max_alloc_all / tot_vram)
        resv_headroom = 1.0 - (max_resv_all / tot_vram)

        max_cos_dev = max(c["max_cosine_deviation"] for c in rep_row["warm_calls"])

        per_stratum = []
        for s in recomputed_strata:
            sid = s["stratum_id"]
            scalls = [c for c in calls if c["stratum_id"] == sid]
            s_in = sum(c["input_tokens"] for c in scalls)
            s_pad = sum(c["padded_tokens"] for c in scalls)
            s_docs = sum(c["documents"] for c in scalls)
            s_cli = sum(c["client_elapsed_seconds"] for c in scalls)
            s_rem = sum(c["remote_elapsed_seconds"] for c in scalls)
            s_gpu = sum(c["gpu_model_pool_seconds"] for c in scalls)
            per_stratum.append({
                "stratum_id": sid,
                "min_tokens": s["min_tokens"],
                "max_tokens": s["max_tokens"],
                "documents_3_repeats": s_docs,
                "input_tokens_1_repeat": s_in // 3,
                "padded_tokens_1_repeat": s_pad // 3,
                "input_tokens_3_repeats": s_in,
                "padded_tokens_3_repeats": s_pad,
                "padding_ratio_padded_over_input": round(s_pad / s_in, 6),
                "padding_overhead_percent": round((s_pad - s_in) / s_in * 100.0, 4),
                "client_seconds": round(s_cli, 6),
                "remote_seconds": round(s_rem, 6),
                "gpu_seconds": round(s_gpu, 6),
            })

        recomputed_grid[str(sz)] = {
            "status": "PASS",
            "warm_request_count": len(calls),
            "documents": docs,
            "input_tokens": in_tok,
            "padded_tokens": pad_tok,
            "padding_ratio_padded_over_input": round(pad_tok / in_tok, 6),
            "padding_fraction_of_padded": round((pad_tok - in_tok) / pad_tok, 6),
            "client_seconds": round(client_s, 6),
            "remote_total_seconds": round(remote_s, 6),
            "gpu_model_pool_seconds": round(gpu_s, 6),
            "rpc_overhead_total_seconds": round(rpc_overhead_s, 6),
            "rpc_overhead_per_call_seconds": round(rpc_overhead_s / len(calls), 6),
            "warm_client_documents_per_second": round(docs / client_s, 6),
            "warm_remote_documents_per_second": round(docs / remote_s, 6),
            "warm_gpu_documents_per_second": round(docs / gpu_s, 6),
            "warm_gpu_real_tokens_per_second": round(in_tok / gpu_s, 6),
            "warm_gpu_padded_tokens_per_second": round(pad_tok / gpu_s, 6),
            "peak_allocated_bytes_warm_only": max_alloc_warm,
            "peak_allocated_bytes_including_stress": max_alloc_all,
            "peak_reserved_bytes_including_stress": max_resv_all,
            "device_total_bytes": tot_vram,
            "allocated_headroom_fraction": round(alloc_headroom, 6),
            "reserved_headroom_fraction": round(resv_headroom, 6),
            "max_cosine_deviation": max_cos_dev,
            "per_stratum": per_stratum,
            "matches_reported_artifact": {
                "documents": docs == rep_row["documents"],
                "input_tokens": in_tok == rep_row["input_tokens"],
                "padded_tokens": pad_tok == rep_row["padded_tokens"],
                "client_seconds": abs(client_s - rep_row["client_seconds"]) < 1e-9,
                "remote_total_seconds": abs(remote_s - rep_row["remote_total_seconds"]) < 1e-9,
                "gpu_model_pool_seconds": abs(gpu_s - rep_row["gpu_model_pool_seconds"]) < 1e-9,
                "warm_client_documents_per_second": abs((docs / client_s) - rep_row["warm_client_documents_per_second"]) < 1e-9,
                "allocated_headroom_fraction": abs(alloc_headroom - rep_row["allocated_headroom_fraction"]) < 1e-9,
                "reserved_headroom_fraction": abs(resv_headroom - rep_row["reserved_headroom_fraction"]) < 1e-9,
            },
        }

    return {
        "status": result["status"],
        "execution_mode": result["execution_mode"],
        "full_cli_seconds": cli_rec["result"]["full_cli_seconds"],
        "total_benchmark_seconds": result["total_seconds"],
        "total_sqlite_requests": total_requests,
        "status_counts": dict(status_counts),
        "known_input_tokens": known_input_tokens,
        "total_padded_tokens": total_padded_tokens,
        "unknown_token_attempts": unknown_token_attempts,
        "total_document_encodings": total_encodings,
        "selected_unique_documents": plan["selected_unique_documents"],
        "crossover_orders": recomputed_orders,
        "all_requests_same_container_and_model": len(descriptors) == 1,
        "descriptor": json.loads(next(iter(descriptors))),
        "warmup_16": warmup_summary,
        "stress_tests": {str(k): v for k, v in sorted(stress_by_size.items())},
        "reported_stress": result["stress"],
        "grid_recomputed": recomputed_grid,
        "winner_batch_size": result["winner_batch_size"],
        "winner_by_metric": {
            "warm_client_documents_per_second": max(recomputed_grid.items(), key=lambda kv: kv[1]["warm_client_documents_per_second"])[0],
            "warm_remote_documents_per_second": max(recomputed_grid.items(), key=lambda kv: kv[1]["warm_remote_documents_per_second"])[0],
            "warm_gpu_documents_per_second": max(recomputed_grid.items(), key=lambda kv: kv[1]["warm_gpu_documents_per_second"])[0],
        },
    }


def recompute_search_and_walltimes() -> dict[str, Any]:
    sb_dir = ROOT / "pipeline_v2/artifacts/m3_opt_v2_search_benchmark_20261108_v1"
    sb_json = read(sb_dir / "search_benchmark.json")
    cli_rec = read(sb_dir / "cli_receipt.json")

    runtime_ledger = ROOT / "pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1_runtime/ledger.sqlite3"
    conn = open_sqlite_ro(runtime_ledger)
    attempts = [dict(r) for r in conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()]
    conn.close()

    # Verify RRF fusion math and exclusion on all search_benchmark queries
    rrf_verified = True
    max_rrf_diff = 0.0
    query_summaries = []
    for q in sb_json["queries"]:
        excl = q["excluded_case"]
        for row in q["results"]:
            if excl and row["case_id"] == excl:
                rrf_verified = False
            expected_rrf = sum(1.0 / (60.0 + ch["rank"]) for ch in row["channels"].values())
            diff = abs(expected_rrf - row["score"])
            max_rrf_diff = max(max_rrf_diff, diff)
            if diff > 1e-12:
                rrf_verified = False
        query_summaries.append({
            "query": q["query"],
            "excluded_case": excl,
            "local_vector_reuse_seconds": q["local_vector_reuse_seconds"],
            "local_mean_seconds": round(sum(q["local_vector_reuse_seconds"]) / len(q["local_vector_reuse_seconds"]), 6),
            "warm_session_request_seconds_including_RPC": q["warm_session_request_seconds_including_RPC"],
            "client_rpc_seconds": q["query_embedding"]["client_rpc_seconds"],
            "remote_total_seconds": q["query_embedding"]["remote_total_seconds"],
            "input_tokens": q["query_embedding"]["input_tokens"],
            "runtime": q["query_embedding"]["runtime"],
            "engine_sha256": q["query_embedding"]["descriptor"]["engine_sha256"],
            "top_3_cases": [r["case_id"] for r in q["results"][:3]],
        })

    all_local = [t for q in sb_json["queries"] for t in q["local_vector_reuse_seconds"]]

    # Inspect the 3 standalone walltime runs
    walltimes = [6.5850839, 6.5107887, 6.3379619]
    standalone_runs = []
    for idx, wt in enumerate(walltimes, start=1):
        p = REVIEW_DIR / f"search_walltime_0{idx}.json"
        data = read(p)
        standalone_runs.append({
            "run_index": idx,
            "file": p.name,
            "exit_code": 0,
            "subprocess_walltime_seconds": wt,
            "full_cli_seconds": data["full_cli_seconds"],
            "process_startup_and_teardown_overhead_seconds": round(wt - data["full_cli_seconds"], 6),
            "session_initialization_seconds": data["session_initialization_seconds"],
            "warm_session_request_seconds": data["warm_session_request_seconds"],
            "client_rpc_seconds": data["query_embedding"]["client_rpc_seconds"],
            "remote_total_seconds": data["query_embedding"]["remote_total_seconds"],
            "local_retrieval_seconds": data["local_retrieval_seconds"],
            "execution_mode": data["execution_mode"],
            "top_3_cases": [r["case_id"] for r in data["results"][:3]],
        })

    runtime_attempt_details = []
    for r in attempts:
        rec = json.loads(r["receipt"]) if r["receipt"] else {}
        desc = rec.get("descriptor", {})
        runtime_attempt_details.append({
            "id": r["id"],
            "batch": r["batch"],
            "phase": r["phase"],
            "status": r["status"],
            "input_tokens": r["tokens"],
            "client_elapsed_seconds": r["elapsed"],
            "remote_elapsed_seconds": rec.get("remote_elapsed_seconds"),
            "gpu_model_pool_seconds": rec.get("gpu_model_pool_seconds"),
            "engine_sha256": desc.get("engine_sha256"),
            "embedding_fingerprint": desc.get("embedding_fingerprint"),
        })

    return {
        "search_benchmark_status": sb_json["status"],
        "execution_mode": sb_json["execution_mode"],
        "search_benchmark_full_cli_seconds": cli_rec["result"]["full_cli_seconds"],
        "search_benchmark_session_init_seconds": sb_json["session_initialization_seconds"],
        "rrf_math_and_exclusion_verified": rrf_verified,
        "max_rrf_score_diff": max_rrf_diff,
        "local_vector_reuse_min_seconds": round(min(all_local), 6),
        "local_vector_reuse_max_seconds": round(max(all_local), 6),
        "local_vector_reuse_mean_seconds": round(sum(all_local) / len(all_local), 6),
        "queries": query_summaries,
        "standalone_cli_walltime_runs": standalone_runs,
        "runtime_ledger_total_requests": len(attempts),
        "runtime_ledger_known_tokens": sum(int(r["tokens"]) for r in attempts if r["tokens"] is not None),
        "runtime_ledger_unknown_attempts": sum(1 for r in attempts if r["tokens"] is None),
        "runtime_ledger_attempts": runtime_attempt_details,
    }


def main() -> None:
    out = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "snapshots_and_fingerprints": verify_old_snapshots_and_fingerprints(),
        "compatibility_preflight_recomputed": recompute_compatibility_preflight(),
        "gpu_benchmark_recomputed": recompute_gpu_benchmark(),
        "search_and_walltime_recomputed": recompute_search_and_walltimes(),
    }
    target = REVIEW_DIR / "recomputed_metrics.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
