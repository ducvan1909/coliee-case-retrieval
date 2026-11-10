"""Independent AG full-corpus audit, array integrity verification, memory/mmap breakdown,
and recomputed parity/hybrid metrics for `m3_sparse_20261110_v1` and `m3_full_train_20261108_v1`.

Read-only on all production files and historical artifacts. Writes only to
`pipeline_v2/reviews/m3_sparse_ag_review_v1/recomputed_metrics.json`.
"""

from collections import defaultdict
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import subprocess
import sys
import time
import tracemalloc

import numpy as np

from pipeline_v2.full_corpus.common import implementation as full_impl
from pipeline_v2.full_corpus.runner import source_path
from pipeline_v2.full_corpus.storage import PAYLOAD, ReadonlyCache
from pipeline_v2.full_search.hybrid import (
    CHANNEL_BUDGET,
    DENSE_CAP,
    OUTPUT_CAP,
    RRF_K,
    SCORE_ATOL,
    TIE_ATOL,
    VERIFY_RECEIPT,
    VERIFY_RECEIPT_SHA256,
    VERIFIED_MANIFEST_SHA256,
    fuse_channels,
    implementation as hybrid_impl,
)
from pipeline_v2.full_search.lexical import FastBM25, implementation as lexical_impl
from pipeline_v2.optimization_v2.common import file_digest, read
from pipeline_v2.retrieval.bm25 import analyze
from pipeline_v2.retrieval.qdrant import point_id
from pipeline_v2.source.core import canonical, digest
from pipeline_v2.sparse_bm25.index import SparseBM25, SparseSession, implementation as sparse_impl, load_profile


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(__file__).resolve().parent
FULL_RUN = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
SPARSE_DIR = ROOT / "pipeline_v2/artifacts/m3_sparse_20261110_v1"
SPARSE_VAL_DIR = ROOT / "pipeline_v2/reviews/m3_sparse_validation_v1"
HYBRID_VAL_DIR = ROOT / "pipeline_v2/reviews/m3_hybrid_validation_v1"
WORKLOAD_PATH = ROOT / "pipeline_v2/reviews/m3_search_latency_diagnostic_v1/workload_manifest.json"


class ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def get_os_memory():
    counters = ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCountersEx), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return {
        "page_fault_count": int(counters.PageFaultCount),
        "working_set_bytes": int(counters.WorkingSetSize),
        "working_set_mib": round(counters.WorkingSetSize / (1024 * 1024), 3),
        "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
        "peak_working_set_mib": round(counters.PeakWorkingSetSize / (1024 * 1024), 3),
        "private_usage_bytes": int(counters.PrivateUsage),
        "private_usage_mib": round(counters.PrivateUsage / (1024 * 1024), 3),
    }


def run_memory_probe_subprocess(with_tracemalloc: bool):
    code = f"""
import json, time, tracemalloc
from pathlib import Path
import numpy as np
from pipeline_v2.sparse_bm25.index import SparseBM25
from pipeline_v2.reviews.m3_sparse_ag_review_v1.audit_and_recompute_sparse import get_os_memory, ROOT, FULL_RUN, SPARSE_DIR, WORKLOAD_PATH

workload = json.loads(WORKLOAD_PATH.read_bytes())["queries"]
if {with_tracemalloc}:
    tracemalloc.start()

def snap(phase, extra=None):
    row = {{"phase": phase, **get_os_memory()}}
    if {with_tracemalloc}:
        cur, peak = tracemalloc.get_traced_memory()
        row["tracemalloc_current_bytes"] = int(cur)
        row["tracemalloc_current_mib"] = round(cur / (1024 * 1024), 3)
        row["tracemalloc_peak_bytes"] = int(peak)
        row["tracemalloc_peak_mib"] = round(peak / (1024 * 1024), 3)
    if extra:
        row.update(extra)
    return row

rows = [snap("01_before_open")]
t0 = time.perf_counter()
reader = SparseBM25(FULL_RUN / "lexical.sqlite3", SPARSE_DIR, validate_database=False)
open_sec = time.perf_counter() - t0

mapped_bytes = 0
for kind, ch in reader.channels.items():
    for k in ("indices", "values", "offsets", "cases"):
        mapped_bytes += int(ch[k].nbytes)

rows.append(snap("02_after_sparse_bm25_init", {{
    "open_seconds": round(open_sec, 4),
    "mapped_array_payload_bytes": mapped_bytes,
    "mapped_array_payload_mib": round(mapped_bytes / (1024 * 1024), 3),
}}))

q1 = workload[0]
q8 = workload[-1]
r_c = reader.search_detailed(q1["text"], "case", limit=100, exclude_case=q1["query_case"], unique_cases=True)
rows.append(snap("03_after_q01_case_unique100", {{"timings": r_c["timings"]}}))

r_p100 = reader.search_detailed(q1["text"], "passage", limit=100, exclude_case=q1["query_case"], unique_cases=True)
rows.append(snap("04_after_q01_passage_unique100", {{"timings": r_p100["timings"]}}))

r_p4096 = reader.search_detailed(q8["text"], "passage", limit=4096, exclude_case=q8["query_case"], unique_cases=False)
rows.append(snap("05_after_q08_passage_raw4096", {{"timings": r_p4096["timings"]}}))

r_p8_100 = reader.search_detailed(q8["text"], "passage", limit=100, exclude_case=q8["query_case"], unique_cases=True)
rows.append(snap("06_after_q08_passage_unique100", {{"timings": r_p8_100["timings"]}}))

reader.close()
rows.append(snap("07_after_close"))
print(json.dumps(rows))
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout.strip())


def audit_fingerprints_and_seals():
    s_code = sparse_impl()
    s_agg = digest(canonical(s_code))
    f_code = full_impl()
    f_agg = digest(canonical(f_code))
    l_code = lexical_impl()
    l_agg = digest(canonical(l_code))
    h_code = hybrid_impl()
    h_agg = digest(canonical(h_code))

    # Check prior_state.json in m3_sparse_validation_v1
    prior = read(SPARSE_VAL_DIR / "prior_state.json")
    prior_mismatches = []
    prior_checked = 0
    for group_name, group in prior.items():
        for rel_path, exp_sha in group.items():
            actual_sha = file_digest(ROOT / rel_path)
            prior_checked += 1
            if actual_sha != exp_sha:
                prior_mismatches.append({"file": rel_path, "expected": exp_sha, "actual": actual_sha})

    # Check m3_sparse_20261110_v1 seal
    sparse_seal = read(SPARSE_DIR / "seal.json")
    sparse_manifest = read(SPARSE_DIR / "manifest.json")
    sparse_files_verification = {}
    total_sealed_bytes = 0
    for name, entry in sorted(sparse_seal.items()):
        p = SPARSE_DIR / name
        actual_bytes = p.stat().st_size
        actual_sha = file_digest(p)
        total_sealed_bytes += actual_bytes
        sparse_files_verification[name] = {
            "bytes": actual_bytes,
            "sha256": actual_sha,
            "matches_seal": (actual_bytes == entry["bytes"] and actual_sha == entry["sha256"]),
        }

    # Check unsealed files in SPARSE_DIR
    all_dir_files = sorted(p.name for p in SPARSE_DIR.iterdir())
    unsealed_files = {
        name: {"bytes": (SPARSE_DIR / name).stat().st_size, "sha256": file_digest(SPARSE_DIR / name)}
        for name in all_dir_files if name not in sparse_seal
    }

    # Check full run manifest & seal & ledger historical preservation
    full_manifest_sha = file_digest(FULL_RUN / "manifest.json")
    full_seal_sha = file_digest(FULL_RUN / "seal.json")
    full_seal = read(FULL_RUN / "seal.json")
    lexical_db_entry = full_seal["lexical.sqlite3"]
    verify_receipt_sha = file_digest(ROOT / VERIFY_RECEIPT)

    # Check ingestion ledger in m3_full_train_20261108_v1/ledger.sqlite3
    ledger_db = sqlite3.connect((FULL_RUN / "ledger.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        attempt_summary = [
            {
                "status": row[0],
                "count": row[1],
                "requests_sum": row[2],
                "known_tokens": row[3],
                "null_token_rows": row[4],
                "sum_elapsed_seconds": round(row[5] or 0.0, 3),
            }
            for row in ledger_db.execute(
                "SELECT status, COUNT(*), SUM(requests), SUM(tokens), "
                "SUM(CASE WHEN tokens IS NULL THEN 1 ELSE 0 END), "
                "SUM(elapsed) FROM attempts GROUP BY status ORDER BY status"
            )
        ]
        non_ok_attempts = [
            {
                "id": row[0],
                "batch": row[1],
                "phase": row[2],
                "status": row[3],
                "requests": row[4],
                "tokens": row[5],
                "elapsed": row[6],
                "error": row[7],
            }
            for row in ledger_db.execute(
                "SELECT id, batch, phase, status, requests, tokens, elapsed, error "
                "FROM attempts WHERE status != 'success' OR tokens IS NULL ORDER BY id"
            )
        ]
    finally:
        ledger_db.close()

    return {
        "sparse_implementation_aggregate_sha256": s_agg,
        "full_implementation_aggregate_sha256": f_agg,
        "lexical_implementation_aggregate_sha256": l_agg,
        "hybrid_implementation_aggregate_sha256": h_agg,
        "sparse_code_files": {
            k: s_code[k] for k in ("pipeline_v2/m3_sparse.py", "pipeline_v2/sparse_bm25/__init__.py", "pipeline_v2/sparse_bm25/index.py")
        },
        "sparse_profile_sha256": file_digest(ROOT / "pipeline_v2/configs/m3_sparse.json"),
        "sparse_profile": load_profile(ROOT),
        "prior_state_files_checked": prior_checked,
        "prior_state_mismatches": prior_mismatches,
        "full_run_bindings": {
            "manifest_sha256": full_manifest_sha,
            "matches_verified_manifest_constant": full_manifest_sha == VERIFIED_MANIFEST_SHA256,
            "seal_sha256": full_seal_sha,
            "lexical_sqlite3_seal_sha256": lexical_db_entry["sha256"],
            "lexical_sqlite3_seal_bytes": lexical_db_entry["bytes"],
            "sparse_manifest_database_sha256_matches": sparse_manifest["database_sha256"] == lexical_db_entry["sha256"],
            "verify_receipt_sha256": verify_receipt_sha,
            "matches_verify_receipt_constant": verify_receipt_sha == VERIFY_RECEIPT_SHA256,
        },
        "historical_ingestion_ledger_preserved": {
            "attempt_summary": attempt_summary,
            "non_ok_or_unknown_token_attempts": non_ok_attempts,
        },
        "sparse_artifact_seal_verification": {
            "total_sealed_files": len(sparse_files_verification),
            "total_sealed_bytes": total_sealed_bytes,
            "total_sealed_mib": round(total_sealed_bytes / (1024 * 1024), 3),
            "all_sealed_files_match": all(v["matches_seal"] for v in sparse_files_verification.values()),
            "sealed_files": sparse_files_verification,
            "unsealed_auxiliary_files": unsealed_files,
            "build_elapsed_seconds_in_manifest": sparse_manifest["elapsed_seconds"],
            "build_wall_seconds_in_receipt": read(SPARSE_VAL_DIR / "build_command_receipt.json")["wall_seconds"],
        },
    }


def audit_array_integrity_and_formula_spotcheck():
    t0 = time.perf_counter()
    reader = SparseBM25(FULL_RUN / "lexical.sqlite3", SPARSE_DIR, validate_database=False)
    init_seconds = time.perf_counter() - t0
    db = reader.db
    channel_audits = {}
    try:
        for kind in ("case", "passage"):
            ch = reader.channels[kind]
            stats_row = db.execute("SELECT n, avg, k1, b FROM stats WHERE kind=?", (kind,)).fetchone()
            n, avg, k1, b = stats_row
            term_count_sql = db.execute("SELECT COUNT(*), SUM(df) FROM terms WHERE kind=?", (kind,)).fetchone()
            doc_rows = list(db.execute("SELECT id, case_id, length FROM documents WHERE kind=? ORDER BY id", (kind,)))
            lengths = np.asarray([r[2] for r in doc_rows], dtype=np.float64)
            norm = k1 * (1.0 - b + b * lengths / (avg or 1.0))

            indices = ch["indices"]
            values = ch["values"]
            offsets = ch["offsets"]
            cases = ch["cases"]
            diffs = np.diff(offsets)

            # Spot-check 25 terms evenly spaced across the vocabulary + top-5 highest-df terms
            num_terms = len(ch["terms"])
            sample_term_ids = sorted(set(
                list(np.linspace(0, num_terms - 1, num=min(25, num_terms), dtype=int))
                + [int(x) for x in np.argsort(diffs)[-5:]]
            ))
            max_formula_abs_diff = 0.0
            postings_spotchecked = 0
            for tid in sample_term_ids:
                term_str = ch["terms"][tid]
                start, end = int(offsets[tid]), int(offsets[tid + 1])
                df = end - start
                idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
                sql_postings = list(db.execute(
                    "SELECT id, tf FROM postings WHERE kind=? AND term=?", (kind, term_str)
                ))
                assert len(sql_postings) == df, f"df mismatch on {kind}:{term_str}"
                sql_postings.sort(key=lambda r: ch["ordinals"][r[0]])
                expected_ords = np.asarray([ch["ordinals"][r[0]] for r in sql_postings], dtype=np.uint32)
                expected_tfs = np.asarray([r[1] for r in sql_postings], dtype=np.float64)
                expected_vals = idf * expected_tfs * (k1 + 1.0) / (expected_tfs + norm[expected_ords])
                actual_ords = np.asarray(indices[start:end])
                actual_vals = np.asarray(values[start:end])
                assert np.array_equal(actual_ords, expected_ords), f"ordinal mismatch on {kind}:{term_str}"
                diff = float(np.max(np.abs(actual_vals - expected_vals))) if df else 0.0
                if diff > max_formula_abs_diff:
                    max_formula_abs_diff = diff
                postings_spotchecked += df

            channel_audits[kind] = {
                "n": n,
                "avg": avg,
                "k1": k1,
                "b": b,
                "terms": num_terms,
                "sql_terms_count": term_count_sql[0],
                "postings": int(offsets[-1]),
                "sql_postings_sum_df": int(term_count_sql[1]),
                "dtypes": {
                    "indices": str(indices.dtype),
                    "values": str(values.dtype),
                    "offsets": str(offsets.dtype),
                    "cases": str(cases.dtype),
                },
                "shapes": {
                    "indices": list(indices.shape),
                    "values": list(values.shape),
                    "offsets": list(offsets.shape),
                    "cases": list(cases.shape),
                },
                "mmap_readonly": {
                    "indices": isinstance(indices, np.memmap) and not indices.flags.writeable,
                    "values": isinstance(values, np.memmap) and not values.flags.writeable,
                    "offsets": isinstance(offsets, np.memmap) and not offsets.flags.writeable,
                    "cases": isinstance(cases, np.memmap) and not cases.flags.writeable,
                },
                "array_payload_bytes": {
                    "indices": int(indices.nbytes),
                    "values": int(values.nbytes),
                    "offsets": int(offsets.nbytes),
                    "cases": int(cases.nbytes),
                    "total_mib": round((indices.nbytes + values.nbytes + offsets.nbytes + cases.nbytes) / (1024 * 1024), 3),
                },
                "df_min": int(diffs.min()),
                "df_median": float( np.median(diffs) ),
                "df_max": int(diffs.max()),
                "values_min": float(values.min()),
                "values_max": float(values.max()),
                "spotcheck_terms_count": len(sample_term_ids),
                "spotcheck_postings_count": postings_spotchecked,
                "spotcheck_max_abs_formula_diff": max_formula_abs_diff,
            }
        return {
            "sparse_bm25_init_seconds_without_db_hash": round(init_seconds, 4),
            "channels": channel_audits,
        }
    finally:
        reader.close()


def run_locked_8query_stage_benchmark():
    workload = read(WORKLOAD_PATH)["queries"]
    reader = SparseBM25(FULL_RUN / "lexical.sqlite3", SPARSE_DIR, validate_database=False)
    prior_lexical_bench = read(ROOT / "pipeline_v2/reviews/m3_lexical_ag_review_v1/bounded_benchmark_results.json")
    prior_by_key = {
        (r["query_id"], r["kind"]): r for r in prior_lexical_bench["part_c_stage_decomposed_8_query_benchmark"]["rows"]
    }
    main_bench = read(SPARSE_VAL_DIR / "actual_benchmark.json")
    main_by_key = {(r["query_id"], r["kind"]): r for r in main_bench["rows"]}
    rows = []
    try:
        for q in workload:
            qid = q["query_id"]
            text = q["text"]
            qcase = q["query_case"]
            for kind in ("case", "passage"):
                id_key = "passage_id" if kind == "passage" else "case_id"
                # 1. Sparse raw 4096
                s_raw = reader.search_detailed(text, kind, limit=4096, exclude_case=qcase, unique_cases=False)
                # 2. Sparse unique 100 (run 3 times to record first + 2 repeats, keeping all runs)
                s_uniq_runs = [
                    reader.search_detailed(text, kind, limit=100, exclude_case=qcase, unique_cases=True)
                    for _ in range(3)
                ]
                s_uniq = s_uniq_runs[0]
                for r_rep in s_uniq_runs[1:]:
                    assert [h[id_key] for h in r_rep["hits"]] == [h[id_key] for h in s_uniq["hits"]]
                    assert [h["score"] for h in r_rep["hits"]] == [h["score"] for h in s_uniq["hits"]]

                prior_row = prior_by_key[(qid, kind)]
                main_row = main_by_key[(qid, kind)]
                assert s_uniq["terms_matched"] == prior_row["terms_matched"]
                assert s_uniq["postings_rows"] == prior_row["postings_rows"]
                assert s_uniq["matched_documents"] == prior_row["matched_documents"]

                sql_uniq = prior_row["warm_vectorized_unique_cases_100"]
                sql_uniq_total = sql_uniq["total_seconds"]
                sql_scoring_top = (
                    sql_uniq["postings_fetch_seconds"]
                    + sql_uniq["mapping_and_scoring_seconds"]
                    + sql_uniq["top_selection_seconds"]
                )

                rows.append({
                    "query_id": qid,
                    "kind": kind,
                    "terms_matched": s_uniq["terms_matched"],
                    "postings_rows": s_uniq["postings_rows"],
                    "matched_documents": s_uniq["matched_documents"],
                    "top1_id": s_uniq["hits"][0][id_key],
                    "top1_score": s_uniq["hits"][0]["score"],
                    "matches_prior_fastbm25_and_oracle": True,
                    "main_benchmark_max_abs_score_diff": main_row["max_abs_score_diff"],
                    "sparse_raw_4096_timings": s_raw["timings"],
                    "sparse_unique_100_first_timings": s_uniq["timings"],
                    "sparse_unique_100_repeat_totals_seconds": [
                        round(r["timings"]["total_seconds"], 6) for r in s_uniq_runs[1:]
                    ],
                    "sqlite_fastbm25_warm_unique_100_reference_seconds": round(sql_uniq_total, 6),
                    "speedup_unique_100_vs_sqlite_fastbm25_warm": round(
                        sql_uniq_total / max(s_uniq["timings"]["total_seconds"], 1e-9), 2
                    ),
                    "speedup_scoring_plus_top_vs_sqlite_fastbm25_warm": round(
                        sql_scoring_top
                        / max(
                            s_uniq["timings"]["array_scoring_seconds"] + s_uniq["timings"]["top_selection_seconds"],
                            1e-9,
                        ),
                        2,
                    ),
                    "speedup_unique_100_vs_main_scalar_oracle": round(
                        main_row["scalar_oracle_seconds"] / max(main_row["unique_100_seconds"], 1e-9), 2
                    ),
                })

        summary = {}
        for kind in ("case", "passage"):
            krows = [r for r in rows if r["kind"] == kind]
            summary[kind] = {
                "sparse_unique_100_array_scoring_median_ms": round(
                    1000.0 * statistics.median(r["sparse_unique_100_first_timings"]["array_scoring_seconds"] for r in krows), 3
                ),
                "sparse_unique_100_top_selection_median_ms": round(
                    1000.0 * statistics.median(r["sparse_unique_100_first_timings"]["top_selection_seconds"] for r in krows), 3
                ),
                "sparse_unique_100_metadata_median_ms": round(
                    1000.0 * statistics.median(r["sparse_unique_100_first_timings"]["metadata_seconds"] for r in krows), 3
                ),
                "sparse_unique_100_total_no_guard_median_ms": round(
                    1000.0 * statistics.median(r["sparse_unique_100_first_timings"]["total_seconds"] for r in krows), 3
                ),
                "sparse_raw_4096_array_scoring_median_ms": round(
                    1000.0 * statistics.median(r["sparse_raw_4096_timings"]["array_scoring_seconds"] for r in krows), 3
                ),
                "sparse_raw_4096_top_selection_median_ms": round(
                    1000.0 * statistics.median(r["sparse_raw_4096_timings"]["top_selection_seconds"] for r in krows), 3
                ),
                "sparse_raw_4096_metadata_median_ms": round(
                    1000.0 * statistics.median(r["sparse_raw_4096_timings"]["metadata_seconds"] for r in krows), 3
                ),
                "sparse_raw_4096_total_no_guard_median_ms": round(
                    1000.0 * statistics.median(r["sparse_raw_4096_timings"]["total_seconds"] for r in krows), 3
                ),
                "sqlite_fastbm25_unique_100_warm_median_ms": round(
                    1000.0 * statistics.median(r["sqlite_fastbm25_warm_unique_100_reference_seconds"] for r in krows), 3
                ),
                "median_speedup_unique_100_vs_sqlite_fastbm25_warm": round(
                    statistics.median(r["speedup_unique_100_vs_sqlite_fastbm25_warm"] for r in krows), 2
                ),
                "median_speedup_scoring_plus_top_vs_sqlite_fastbm25_warm": round(
                    statistics.median(r["speedup_scoring_plus_top_vs_sqlite_fastbm25_warm"] for r in krows), 2
                ),
            }

        main_recomputed = {}
        for kind in ("case", "passage"):
            mrows = [r for r in main_bench["rows"] if r["kind"] == kind]
            main_recomputed[kind] = {
                "raw_4096_median_seconds": statistics.median(r["raw_4096_seconds"] for r in mrows),
                "scalar_oracle_median_seconds": statistics.median(r["scalar_oracle_seconds"] for r in mrows),
                "unique_100_median_seconds": statistics.median(r["unique_100_seconds"] for r in mrows),
                "repeated_unique_100_median_seconds": statistics.median(
                    v for r in mrows for v in r["unique_100_repeats_seconds"]
                ),
                "max_abs_score_diff": max(r["max_abs_score_diff"] for r in mrows),
            }

        return {
            "main_actual_benchmark_recomputed": main_recomputed,
            "ag_stage_separated_benchmark_summary": summary,
            "ag_stage_separated_rows": rows,
        }
    finally:
        reader.close()


def audit_hybrid_benchmarks_and_recompute():
    workload = read(WORKLOAD_PATH)
    fixtures = {f["vector_id"]: f for f in workload["diagnostic_dense_vectors"]}

    def load_jsonl(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    sqlite_qdrant = load_jsonl(HYBRID_VAL_DIR / "qdrant_cached_benchmark.jsonl")
    sqlite_offline = load_jsonl(HYBRID_VAL_DIR / "offline_cached_benchmark.jsonl")
    sparse_qdrant = load_jsonl(SPARSE_VAL_DIR / "qdrant_cached_benchmark.jsonl")
    offline_ref = read(HYBRID_VAL_DIR / "dense_reference.json")

    by_vec_sqlite = {r["vector_id"]: r for r in sqlite_qdrant if r.get("event") == "query_complete"}
    by_vec_offline = {r["vector_id"]: r for r in sqlite_offline if r.get("event") == "query_complete"}
    by_vec_sparse = {r["vector_id"]: r for r in sparse_qdrant if r.get("event") == "query_complete"}

    manifest = read(FULL_RUN / "manifest.json")
    fingerprint = manifest["embedding_fingerprint"]
    dimensions = manifest["profile"]["embedding"]["dimensions"]

    reader = SparseBM25(FULL_RUN / "lexical.sqlite3", SPARSE_DIR, validate_database=False)
    cache = ReadonlyCache(FULL_RUN, fingerprint, dimensions)
    from pipeline_v2.full_search.hybrid import _ScheduleVectors
    sched_vectors = _ScheduleVectors(reader, cache)

    vector_audits = []
    try:
        for vid in ("V01", "V02", "V03"):
            fix = fixtures[vid]
            qcase = fix["query_case_excluded"]
            pid = fix["passage_id"]
            raw_bytes = source_path(ROOT, qcase).read_bytes()
            span_bytes = raw_bytes[slice(*fix["span_bytes"])]
            query_text = span_bytes.decode("utf-8")

            sp_resp = by_vec_sparse[vid]["response"]
            sq_resp = by_vec_sqlite[vid]["response"]
            of_resp = by_vec_offline[vid]["response"]

            # 1. Independently run SparseBM25 on query_text for case and passage
            ind_case = reader.search_detailed(query_text, "case", limit=CHANNEL_BUDGET, exclude_case=qcase, unique_cases=True)
            ind_pass = reader.search_detailed(query_text, "passage", limit=CHANNEL_BUDGET, exclude_case=qcase, unique_cases=True)

            assert [h["case_id"] for h in ind_case["hits"]] == [h["case_id"] for h in sp_resp["channels"]["case_bm25"]]
            assert [h["passage_id"] for h in ind_pass["hits"]] == [h["passage_id"] for h in sp_resp["channels"]["passage_bm25"]]

            # 2. Verify parity across Sparse Qdrant, SQLite Qdrant, and SQLite Offline Replay
            exact_hits_sqlite_vs_sparse = (sp_resp["hits"] == sq_resp["hits"])
            exact_hits_offline_vs_sparse = (
                [h["case_id"] for h in sp_resp["hits"]] == [h["case_id"] for h in of_resp["hits"]]
            )
            exact_channels_sqlite_vs_sparse = all(
                sp_resp["channels"][ch] == sq_resp["channels"][ch]
                for ch in ("case_bm25", "passage_bm25", "dense_passage")
            )

            # 3. Independently recompute RRF fusion from channel rankings
            recomputed_fused = fuse_channels(sp_resp["channels"], limit=OUTPUT_CAP)
            rrf_matches = (recomputed_fused == sp_resp["hits"])

            # 4. Independently verify cosine scores of dense_passage leads against ReadonlyCache shards
            dense_leads = sp_resp["channels"]["dense_passage"]
            check_ids = [pid] + [h["passage_id"] for h in dense_leads]
            vecs = sched_vectors.select(check_ids)
            qvec = np.asarray(vecs[pid], dtype=np.float64)
            qvec /= np.linalg.norm(qvec)
            max_cos_diff_cache = 0.0
            for h in dense_leads:
                cvec = np.asarray(vecs[h["passage_id"]], dtype=np.float64)
                cos_val = float(qvec @ cvec / np.linalg.norm(cvec))
                diff = abs(cos_val - h["score"])
                if diff > max_cos_diff_cache:
                    max_cos_diff_cache = diff
                assert diff <= SCORE_ATOL, f"Dense cosine drift on {vid}:{h['passage_id']}"

            # Also compare dense_passage leads against offline_ref
            ref_by_pid = {r["passage_id"]: r["score"] for r in offline_ref["results"][vid]}
            max_cos_diff_offline_ref = max(
                abs(h["score"] - ref_by_pid[h["passage_id"]]) for h in dense_leads
            )

            # 5. Check query_case exclusion & 100 unique case budget
            for ch_name, ch_hits in sp_resp["channels"].items():
                cases_in_ch = [h["case_id"] for h in ch_hits]
                assert qcase not in cases_in_ch, f"Excluded query case {qcase} present in {ch_name}"
                assert len(cases_in_ch) == len(set(cases_in_ch)) <= CHANNEL_BUDGET

            # 6. Compute BM25 and Hybrid speedups
            sq_bm25 = sq_resp["timings"]["case_bm25_seconds"] + sq_resp["timings"]["passage_bm25_seconds"]
            sp_bm25 = sp_resp["timings"]["case_bm25_seconds"] + sp_resp["timings"]["passage_bm25_seconds"]

            vector_audits.append({
                "vector_id": vid,
                "query_case": qcase,
                "passage_id": pid,
                "query_char_length": len(query_text),
                "query_unique_terms": len(set(analyze(query_text))),
                "exact_hits_sqlite_vs_sparse": exact_hits_sqlite_vs_sparse,
                "exact_channels_sqlite_vs_sparse": exact_channels_sqlite_vs_sparse,
                "exact_top20_case_ids_vs_offline_ref": exact_hits_offline_vs_sparse,
                "independent_rrf_recomputation_matches": rrf_matches,
                "max_dense_cosine_diff_vs_sealed_cache": max_cos_diff_cache,
                "max_dense_cosine_diff_vs_offline_ref": max_cos_diff_offline_ref,
                "coverage": sp_resp["coverage"],
                "top5_fused_cases": [
                    {"rank": i + 1, "case_id": h["case_id"], "score": round(h["score"], 8), "channels": sorted(h["channels"].keys())}
                    for i, h in enumerate(sp_resp["hits"][:5])
                ],
                "timings_comparison": {
                    "sqlite_case_bm25_s": round(sq_resp["timings"]["case_bm25_seconds"], 4),
                    "sparse_case_bm25_s": round(sp_resp["timings"]["case_bm25_seconds"], 4),
                    "sqlite_passage_bm25_s": round(sq_resp["timings"]["passage_bm25_seconds"], 4),
                    "sparse_passage_bm25_s": round(sp_resp["timings"]["passage_bm25_seconds"], 4),
                    "sqlite_total_bm25_s": round(sq_bm25, 4),
                    "sparse_total_bm25_s": round(sp_bm25, 4),
                    "bm25_speedup_factor": round(sq_bm25 / sp_bm25, 1),
                    "passage_bm25_speedup_factor": round(
                        sq_resp["timings"]["passage_bm25_seconds"] / sp_resp["timings"]["passage_bm25_seconds"], 1
                    ),
                    "sqlite_dense_query_s": round(sq_resp["timings"]["dense_query_seconds"], 4),
                    "sparse_dense_query_s": round(sp_resp["timings"]["dense_query_seconds"], 4),
                    "sqlite_dense_validation_s": round(sq_resp["timings"]["dense_validation_seconds"], 4),
                    "sparse_dense_validation_s": round(sp_resp["timings"]["dense_validation_seconds"], 4),
                    "sqlite_hybrid_total_s": round(sq_resp["timings"]["total_seconds"], 4),
                    "sparse_hybrid_total_s": round(sp_resp["timings"]["total_seconds"], 4),
                    "hybrid_total_speedup_factor": round(
                        sq_resp["timings"]["total_seconds"] / sp_resp["timings"]["total_seconds"], 2
                    ),
                },
            })

        return {
            "sqlite_hybrid_session_open_seconds": next(
                r["seconds"] for r in sqlite_qdrant if r.get("event") == "session_opened"
            ),
            "sparse_hybrid_session_open_seconds": next(
                r["seconds"] for r in sparse_qdrant if r.get("event") == "session_opened"
            ),
            "queries": vector_audits,
        }
    finally:
        reader.close()


def measure_guard_overhead():
    # Measure single SparseSession.guard() file-hashing cost
    fake_session = object.__new__(SparseSession)
    fake_session.root = ROOT
    fake_session.profile = load_profile(ROOT)
    fake_session.directory = FULL_RUN
    fake_session.index_dir = SPARSE_DIR
    fake_session.code = sparse_impl()
    fake_session.invalidated = False
    fake_session.reader = None
    fake_session.manifest = read(FULL_RUN / "manifest.json")
    fake_session.binding = {
        name: file_digest(FULL_RUN / name) for name in ("manifest.json", "seal.json")
    }
    fake_session.index_binding = {
        name: file_digest(SPARSE_DIR / name) for name in ("manifest.json", "seal.json")
    }
    timings = []
    for _ in range(10):
        t0 = time.perf_counter()
        fake_session.guard()
        timings.append(time.perf_counter() - t0)
    return {
        "files_hashed_in_sparse_implementation": len(fake_session.code),
        "single_guard_median_ms": round(1000.0 * statistics.median(timings), 3),
        "double_guard_per_lexical_search_median_ms": round(2000.0 * statistics.median(timings), 3),
        "seven_guards_per_hybrid_search_median_ms": round(7000.0 * statistics.median(timings), 3),
    }


def main():
    started = time.perf_counter()
    print("[1/5] Auditing fingerprints, seals, and ingestion ledger...", flush=True)
    fp_audit = audit_fingerprints_and_seals()

    print("[2/5] Auditing full-corpus sparse arrays and spot-checking float64 BM25 contributions...", flush=True)
    array_audit = audit_array_integrity_and_formula_spotcheck()

    print("[3/5] Running isolated subprocess memory probes (tracemalloc + OS WorkingSet/PrivateUsage)...", flush=True)
    mem_tracemalloc = run_memory_probe_subprocess(with_tracemalloc=True)
    mem_os_clean = run_memory_probe_subprocess(with_tracemalloc=False)

    print("[4/5] Running locked 8-query stage-separated parity & latency benchmark...", flush=True)
    lexical_bench = run_locked_8query_stage_benchmark()

    print("[5/5] Auditing 3-query hybrid benchmark and recomputing RRF + dense cosine checks...", flush=True)
    hybrid_audit = audit_hybrid_benchmarks_and_recompute()
    guard_stats = measure_guard_overhead()

    output = {
        "schema_version": "ag-m3-sparse-recomputed-metrics-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_audit_elapsed_seconds": round(time.perf_counter() - started, 3),
        "fingerprints_and_seals": fp_audit,
        "array_integrity_and_spotcheck": array_audit,
        "memory_breakdown": {
            "subprocess_with_tracemalloc": mem_tracemalloc,
            "subprocess_without_tracemalloc_os_clean": mem_os_clean,
            "main_hybrid_memory_artifact": read(SPARSE_VAL_DIR / "hybrid_memory.json"),
        },
        "guard_overhead_analysis": guard_stats,
        "locked_8query_lexical_parity_and_stage_timings": lexical_bench,
        "hybrid_3query_audit_and_recomputation": hybrid_audit,
    }
    out_path = OUT_DIR / "recomputed_metrics.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Audit complete in {output['total_audit_elapsed_seconds']}s -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
