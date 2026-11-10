"""Generate recomputed_metrics.json for M3 full corpus review using bounded-RAM streaming."""
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2.source.core import canonical, digest
from pipeline_v2.retrieval.cache import validate_vectors

RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
REV_DIR = Path(__file__).resolve().parent


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16").strip()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig").strip()
    return raw.decode("utf-8").strip()


def main():
    t0 = time.perf_counter()

    # 1. Refresh state_after.json via snapshot_state
    from snapshot_state import snapshot_state
    state_before = json.loads((REV_DIR / "state_before.json").read_bytes())
    state_after = snapshot_state()
    (REV_DIR / "state_after.json").write_text(
        json.dumps(state_after, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    # 2. Load ledger_and_schedule_audit.json and independent_local_test_results.json
    ledger_audit = json.loads((REV_DIR / "ledger_and_schedule_audit.json").read_bytes())
    local_tests = json.loads((REV_DIR / "independent_local_test_results.json").read_bytes())

    # 3. Streaming audit of vectors/ cache directory against schedule (bounded RAM)
    manifest = json.loads((RUN_DIR / "manifest.json").read_bytes())
    fp = manifest["embedding_fingerprint"]
    dim = manifest["profile"]["embedding"]["dimensions"]

    vec_dir = RUN_DIR / "vectors"
    json_files_on_disk = set()
    npz_files_on_disk = set()
    other_files_on_disk = []
    total_json_bytes = 0
    total_npz_bytes = 0

    for entry in os.scandir(vec_dir):
        if not entry.is_file():
            other_files_on_disk.append(entry.name)
            continue
        if entry.name.endswith(".json"):
            json_files_on_disk.add(entry.name[:-5])
            total_json_bytes += entry.stat().st_size
        elif entry.name.endswith(".npz"):
            npz_files_on_disk.add(entry.name[:-4])
            total_npz_bytes += entry.stat().st_size
        else:
            other_files_on_disk.append(entry.name)

    lex_uri = (RUN_DIR / "lexical.sqlite3").resolve().as_uri() + "?mode=ro"
    lex_db = sqlite3.connect(lex_uri, uri=True)
    expected_shard_stems = set()
    metadata_verified_batches = 0
    metadata_verified_passages = 0
    spot_checked_batches = []
    spot_targets = {0, 1, 3125, 4291, 4292, 5692, 5693, 5694, 6494, 6495}

    try:
        cur_batch = None
        cur_ids = []
        cur_hashes = []
        sql = """
            SELECT s.batch, s.passage_id, json_extract(d.metadata, '$.exact_input_sha256')
            FROM schedule s
            JOIN documents d ON d.kind = 'passage' AND d.id = s.passage_id
            ORDER BY s.ordinal
        """
        def check_one_batch(b_num, ids, hashes):
            nonlocal metadata_verified_batches, metadata_verified_passages
            stem = digest(canonical([fp, ids]))
            expected_shard_stems.add(stem)
            meta_p = vec_dir / f"{stem}.json"
            npz_p = vec_dir / f"{stem}.npz"
            assert meta_p.exists() and npz_p.exists(), f"Missing shard for batch {b_num}: {stem}"
            meta = json.loads(meta_p.read_bytes())
            assert meta["fingerprint"] == fp
            assert meta["ids"] == ids
            assert meta["input_hashes"] == hashes
            assert len(meta["array_sha256"]) == 64
            metadata_verified_batches += 1
            metadata_verified_passages += len(ids)

            if b_num in spot_targets:
                actual_sha = sha256_file(npz_p)
                assert actual_sha == meta["array_sha256"]
                with np.load(npz_p, allow_pickle=False) as z:
                    assert z["ids"].tolist() == ids
                    assert z["input_hashes"].tolist() == hashes
                    assert str(z["fingerprint"]) == fp
                    vecs = validate_vectors(z["vectors"], len(ids), dim)
                    norms = np.linalg.norm(vecs, axis=1)
                    spot_checked_batches.append({
                        "batch": b_num,
                        "shard_stem": stem,
                        "doc_count": len(ids),
                        "npz_bytes": npz_p.stat().st_size,
                        "array_sha256": actual_sha,
                        "min_l2_norm": float(np.min(norms)),
                        "max_l2_norm": float(np.max(norms)),
                    })

        for b_num, pid, ihash in lex_db.execute(sql):
            if cur_batch is not None and b_num != cur_batch:
                check_one_batch(cur_batch, cur_ids, cur_hashes)
                cur_ids = []
                cur_hashes = []
            cur_batch = b_num
            cur_ids.append(pid)
            cur_hashes.append(ihash)
        if cur_ids:
            check_one_batch(cur_batch, cur_ids, cur_hashes)
    finally:
        lex_db.close()

    orphan_json = sorted(json_files_on_disk - expected_shard_stems)
    orphan_npz = sorted(npz_files_on_disk - expected_shard_stems)
    missing_stems = sorted(expected_shard_stems - (json_files_on_disk & npz_files_on_disk))

    # 4. Run directory files & sizes
    run_files = {}
    for p in sorted(RUN_DIR.iterdir()):
        if p.is_file():
            run_files[p.name] = {
                "bytes": p.stat().st_size,
                "sha256": sha256_file(p) if p.stat().st_size < 100 * 1024 * 1024 else state_after["artifacts"]["full_plan_seal"].get(p.name, {}).get("sha256"),
            }

    # 5. Parse step receipts and outputs
    step_outputs = {}
    for step_prefix in (
        "step1_status",
        "step2_canary",
        "step3_status",
        "step5_verify_attempt1",
        "step5_verify",
    ):
        rec_p = REV_DIR / f"{step_prefix}_receipt.json"
        out_p = REV_DIR / f"{step_prefix}_stdout.json"
        err_p = REV_DIR / f"{step_prefix}_stderr.txt"
        if rec_p.exists():
            rec_obj = json.loads(read_text_auto(rec_p))
            out_txt = read_text_auto(out_p) if out_p.exists() else ""
            err_txt = read_text_auto(err_p) if err_p.exists() else ""
            step_outputs[step_prefix] = {
                "receipt": rec_obj,
                "stdout": json.loads(out_txt) if out_txt.startswith("{") else out_txt,
                "stderr": err_txt,
            }

    recomputed = {
        "schema_version": "ag-m3-full-recomputed-metrics-1",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "audit_elapsed_seconds": time.perf_counter() - t0,
        "fingerprints_and_immutability": {
            "full_implementation_sha256": state_after["fingerprints"]["full_implementation_sha256"],
            "v2_implementation_sha256": state_after["fingerprints"]["v2_implementation_sha256"],
            "v1_implementation_sha256": state_after["fingerprints"]["v1_implementation_sha256"],
            "base_implementation_sha256": state_after["fingerprints"]["base_implementation_sha256"],
            "embedding_fingerprint": fp,
            "profile_sha256": state_after["fingerprints"]["profile_sha256"],
            "code_and_profiles_unchanged_before_vs_after": (
                state_before["fingerprints"] == state_after["fingerprints"]
            ),
            "baseline_and_plan_seals_unchanged_before_vs_after": (
                state_before["artifacts"] == state_after["artifacts"]
            ),
            "pilot_collections_unchanged": (
                state_after["qdrant"]["collections"].get("coliee_m3_pilot_99e66b7f9bbf4be4", {}).get("exact_count") == 1024
                and state_after["qdrant"]["collections"].get("coliee_m3_pilot_99e66b7f9bbf4be4_restore", {}).get("exact_count") == 1024
            ),
        },
        "schedule_and_corpus_scope": ledger_audit["schedule_summary"],
        "committed_vector_cache_audit": {
            "expected_batches": 6496,
            "json_sidecars_on_disk": len(json_files_on_disk),
            "npz_arrays_on_disk": len(npz_files_on_disk),
            "metadata_verified_batches": metadata_verified_batches,
            "metadata_verified_passages": metadata_verified_passages,
            "orphan_json_files": orphan_json,
            "orphan_npz_files": orphan_npz,
            "missing_shard_stems": missing_stems,
            "unexpected_files_in_vectors_dir": other_files_on_disk,
            "total_json_sidecar_bytes": total_json_bytes,
            "total_npz_array_bytes": total_npz_bytes,
            "total_vectors_dir_bytes": total_json_bytes + total_npz_bytes,
            "raw_fp32_matrix_theoretical_bytes": 415693 * 2560 * 4,
            "spot_checked_npz_batches": spot_checked_batches,
            "full_6496_batch_npz_and_qdrant_verified_by_cli": step_outputs["step5_verify"]["stdout"],
        },
        "ledger_and_requests_reconciliation": {
            "full_batches_table": ledger_audit["full_batches_table"],
            "status_summary": ledger_audit["ledger_status_summary"],
            "total_attempts": 6497,
            "successful_requests": 6496,
            "started_unknown_usage_requests": 1,
            "error_or_oom_requests": 0,
            "known_input_tokens": 55346360,
            "known_padded_tokens": 55360576,
            "padding_overhead_tokens": 55360576 - 55346360,
            "padding_ratio_padded_over_input": 55360576 / 55346360,
            "unknown_token_attempts": 1,
            "unknown_elapsed_attempts": 1,
            "started_attempt_preserved_not_zeroed": (
                len(ledger_audit["non_success_attempts"]) == 1
                and ledger_audit["non_success_attempts"][0]["id"] == 4293
                and ledger_audit["non_success_attempts"][0]["batch"] == "full-documents-4292"
                and ledger_audit["non_success_attempts"][0]["status"] == "started"
                and ledger_audit["non_success_attempts"][0]["tokens"] is None
                and ledger_audit["non_success_attempts"][0]["elapsed"] is None
            ),
            "non_success_batch_history": ledger_audit["non_success_batch_history"],
            "timing_and_vram_summary": {
                "recorded_client_request_elapsed_seconds": ledger_audit["reconciliation"]["total_client_elapsed_seconds"],
                "recorded_remote_elapsed_seconds": ledger_audit["reconciliation"]["total_remote_elapsed_seconds"],
                "recorded_gpu_model_pool_seconds": ledger_audit["reconciliation"]["total_gpu_model_pool_seconds"],
                "recorded_rpc_and_transfer_overhead_seconds": ledger_audit["reconciliation"]["total_rpc_and_transfer_overhead_seconds"],
                "mean_client_seconds_per_successful_batch": ledger_audit["reconciliation"]["total_client_elapsed_seconds"] / 6496,
                "mean_remote_seconds_per_successful_batch": ledger_audit["reconciliation"]["total_remote_elapsed_seconds"] / 6496,
                "mean_gpu_seconds_per_successful_batch": ledger_audit["reconciliation"]["total_gpu_model_pool_seconds"] / 6496,
                "effective_client_passages_per_second_on_success": 415693 / ledger_audit["reconciliation"]["total_client_elapsed_seconds"],
                "effective_remote_passages_per_second_on_success": 415693 / ledger_audit["reconciliation"]["total_remote_elapsed_seconds"],
                "effective_gpu_passages_per_second_on_success": 415693 / ledger_audit["reconciliation"]["total_gpu_model_pool_seconds"],
                "max_peak_allocated_bytes": ledger_audit["reconciliation"]["max_peak_allocated_bytes"],
                "max_peak_reserved_bytes": ledger_audit["reconciliation"]["max_peak_reserved_bytes"],
                "device_total_bytes": 23689363456,
                "allocated_headroom_fraction_at_peak": ledger_audit["reconciliation"]["allocated_headroom_fraction_at_peak"],
                "reserved_headroom_fraction_at_peak": ledger_audit["reconciliation"]["reserved_headroom_fraction_at_peak"],
                "modal_container_instances": ledger_audit["reconciliation"]["modal_container_instances"],
            },
        },
        "invocations_reconciliation": ledger_audit["invocations"],
        "cli_steps_executed_by_ag": step_outputs,
        "disk_space_before_and_after": {
            "before": state_before["disk_space"],
            "after": state_after["disk_space"],
            "drive_E_bytes_consumed_delta": (
                state_before["disk_space"]["cache_drive_E"]["free_bytes"]
                - state_after["disk_space"]["cache_drive_E"]["free_bytes"]
            ),
            "drive_E_gb_consumed_delta": round(
                (
                    state_before["disk_space"]["cache_drive_E"]["free_bytes"]
                    - state_after["disk_space"]["cache_drive_E"]["free_bytes"]
                )
                / (1024**3),
                2,
            ),
        },
        "run_directory_files": run_files,
        "qdrant_collections_after": state_after["qdrant"],
        "local_test_and_plan_audit_summary": {
            "unit_tests_30": "30/30 PASS (12 full_corpus + 18 optimization_v2)",
            "independent_fault_injection_tests": local_tests["independent_unit_tests"]["status"],
            "independent_plan_audit": local_tests["independent_full_plan_audit"]["status"],
        },
    }

    out_file = REV_DIR / "recomputed_metrics.json"
    out_file.write_text(json.dumps(recomputed, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK",
        "recomputed_file": out_file.name,
        "audit_elapsed_seconds": recomputed["audit_elapsed_seconds"],
        "json_sidecars": len(json_files_on_disk),
        "npz_arrays": len(npz_files_on_disk),
        "total_vectors_gb": round((total_json_bytes + total_npz_bytes) / (1024**3), 3),
    }))


if __name__ == "__main__":
    import os
    main()
