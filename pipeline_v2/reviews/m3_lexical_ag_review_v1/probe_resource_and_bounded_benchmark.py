"""Bounded resource, PRAGMA, CLI, unique-case parity, and stage-decomposed benchmark for M3 lexical review."""
from collections import defaultdict
import ctypes
from ctypes import wintypes
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

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
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


def get_process_memory() -> dict:
    counters = PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    handle = k32.GetCurrentProcess()
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    ok = psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(counters), ctypes.sizeof(counters)
    )
    if not ok:
        raise RuntimeError("GetProcessMemoryInfo failed")
    return {
        "working_set_bytes": int(counters.WorkingSetSize),
        "working_set_mib": round(counters.WorkingSetSize / (1024 * 1024), 3),
        "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
        "peak_working_set_mib": round(counters.PeakWorkingSetSize / (1024 * 1024), 3),
        "private_usage_bytes": int(counters.PrivateUsage),
        "private_usage_mib": round(counters.PrivateUsage / (1024 * 1024), 3),
        "page_fault_count": int(counters.PageFaultCount),
    }


def clean_env() -> dict:
    env = os.environ.copy()
    for k in list(env):
        if k.upper().startswith("MODAL_") or k.upper().startswith("QDRANT_"):
            env.pop(k)
    return env


def run_part_a_subprocesses() -> dict:
    """Run two isolated subprocesses to measure FastBM25 Python heap (tracemalloc) and OS RSS cleanly."""
    db_path = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1/lexical.sqlite3"
    manifest = json.loads(
        (ROOT / "pipeline_v2/reviews/m3_search_latency_diagnostic_v1/workload_manifest.json").read_bytes()
    )
    q01 = manifest["queries"][0]

    # Pass 1: tracemalloc Python heap measurement
    code_tracemalloc = f"""
import json, tracemalloc
from pathlib import Path
from pipeline_v2.full_search.lexical import FastBM25

db_path = Path({repr(str(db_path))})
tracemalloc.start()
before_cur, before_peak = tracemalloc.get_traced_memory()
reader = FastBM25(db_path, cache_mib=128, mmap_mib=512, fetch_size=4096)
after_preload_cur, after_preload_peak = tracemalloc.get_traced_memory()
res_case = reader.search_detailed({repr(q01['text'])}, 'case', limit=4096, exclude_case={repr(q01['query_case'])})
after_case_cur, after_case_peak = tracemalloc.get_traced_memory()
res_pass = reader.search_detailed({repr(q01['text'])}, 'passage', limit=4096, exclude_case={repr(q01['query_case'])})
after_pass_cur, after_pass_peak = tracemalloc.get_traced_memory()
reader.close()
tracemalloc.stop()

out = {{
    'preload_seconds': reader.preload_seconds,
    'pragmas': reader.pragmas,
    'heap_before_bytes': before_cur,
    'heap_after_preload_current_bytes': after_preload_cur,
    'heap_after_preload_delta_bytes': after_preload_cur - before_cur,
    'heap_after_preload_delta_mib': round((after_preload_cur - before_cur) / (1024 * 1024), 3),
    'heap_after_preload_peak_bytes': after_preload_peak,
    'heap_after_preload_peak_mib': round(after_preload_peak / (1024 * 1024), 3),
    'heap_after_q01_passage_peak_bytes': after_pass_peak,
    'heap_after_q01_passage_peak_mib': round(after_pass_peak / (1024 * 1024), 3),
    'channel_array_bytes': {{
        kind: {{
            'cases_int32_bytes': int(ch['cases'].nbytes),
            'norm_float64_bytes': int(ch['norm'].nbytes),
            'n': int(ch['n']),
            'unique_cases': len(ch['case_codes']),
        }}
        for kind, ch in reader.channels.items()
    }}
}}
print(json.dumps(out))
"""
    p1 = subprocess.run(
        [sys.executable, "-c", code_tracemalloc],
        cwd=str(ROOT),
        env=clean_env(),
        capture_output=True,
        text=True,
         check=True,
    )
    tracemalloc_res = json.loads(p1.stdout.strip())

    # Pass 2: OS WorkingSet / PrivateUsage without tracemalloc overhead
    code_os_mem = f"""
import json
from pathlib import Path
from pipeline_v2.full_search.lexical import FastBM25
from pipeline_v2.reviews.m3_lexical_ag_review_v1.probe_resource_and_bounded_benchmark import get_process_memory

db_path = Path({repr(str(db_path))})
mem_before = get_process_memory()
reader = FastBM25(db_path, cache_mib=128, mmap_mib=512, fetch_size=4096)
mem_after_preload = get_process_memory()
page_size = reader.db.execute('PRAGMA page_size').fetchone()[0]
page_count = reader.db.execute('PRAGMA page_count').fetchone()[0]
freelist_count = reader.db.execute('PRAGMA freelist_count').fetchone()[0]

res_case = reader.search_detailed({repr(q01['text'])}, 'case', limit=4096, exclude_case={repr(q01['query_case'])})
mem_after_case_q01 = get_process_memory()

res_pass_4096 = reader.search_detailed({repr(q01['text'])}, 'passage', limit=4096, exclude_case={repr(q01['query_case'])}, unique_cases=False)
mem_after_passage_q01_4096 = get_process_memory()

res_pass_u100 = reader.search_detailed({repr(q01['text'])}, 'passage', limit=100, exclude_case={repr(q01['query_case'])}, unique_cases=True)
mem_after_passage_q01_u100 = get_process_memory()
reader.close()

out = {{
    'preload_seconds_no_tracemalloc': reader.preload_seconds,
    'pragmas_verified': {{
        **reader.pragmas,
        'page_size': page_size,
        'page_count': page_count,
        'freelist_count': freelist_count,
        'sqlite_file_bytes': db_path.stat().st_size,
    }},
    'os_memory_stages': {{
        'before_open': mem_before,
        'after_preload': mem_after_preload,
        'after_q01_case_4096': mem_after_case_q01,
        'after_q01_passage_4096': mem_after_passage_q01_4096,
        'after_q01_passage_unique100': mem_after_passage_q01_u100,
    }},
    'preload_os_deltas': {{
        'working_set_delta_mib': round(mem_after_preload['working_set_mib'] - mem_before['working_set_mib'], 3),
        'private_usage_delta_mib': round(mem_after_preload['private_usage_mib'] - mem_before['private_usage_mib'], 3),
    }}
}}
print(json.dumps(out))
"""
    p2 = subprocess.run(
        [sys.executable, "-c", code_os_mem],
        cwd=str(ROOT),
        env=clean_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    os_mem_res = json.loads(p2.stdout.strip())
    return {"tracemalloc_pass": tracemalloc_res, "os_memory_pass": os_mem_res}


def run_part_b_cli_checks() -> dict:
    """Run standalone CLI revalidate and search commands with MODAL_* and QDRANT_* env vars removed."""
    env = clean_env()
    t0 = time.perf_counter()
    p_rev = subprocess.run(
        [sys.executable, "-m", "pipeline_v2.m3_lexical", "revalidate"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    rev_wall = time.perf_counter() - t0
    rev_json = json.loads(p_rev.stdout.strip())

    t1 = time.perf_counter()
    p_search = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline_v2.m3_lexical",
            "search",
            "--channel",
            "passage",
            "--query",
            "standard of review",
            "--query-case",
            "000002.txt",
            "--limit",
            "100",
            "--unique-cases",
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    search_wall = time.perf_counter() - t1
    search_json = json.loads(p_search.stdout.strip())
    hits = search_json.get("hits", [])
    unique_case_ids = {h["case_id"] for h in hits}
    assert len(hits) == 100 and len(unique_case_ids) == 100 and "000002.txt" not in unique_case_ids

    return {
        "cli_revalidate": {
            "returncode": p_rev.returncode,
            "subprocess_wall_seconds": rev_wall,
            "internal_cli_seconds": rev_json["internal_cli_seconds"],
            "status": rev_json["status"],
            "model_requests": rev_json["model_requests"],
        },
        "cli_search_unique_cases_100": {
            "returncode": p_search.returncode,
            "subprocess_wall_seconds": search_wall,
            "internal_cli_seconds": search_json["internal_cli_seconds"],
            "session_initialization_seconds": search_json["session_initialization_seconds"],
            "preload_seconds": search_json["preload_seconds"],
            "search_timings": search_json["timings"],
            "hits_count": len(hits),
            "unique_cases_count": len(unique_case_ids),
            "query_case_excluded": search_json["query_case_excluded"],
            "top_3_hits": [
                {"passage_id": h["passage_id"], "case_id": h["case_id"], "score": h["score"]}
                for h in hits[:3]
            ],
        },
    }


def scalar_decomposed(db: sqlite3.Connection, maps: dict, query: str, kind: str, exclude: str | None, limit: int = 4096) -> dict:
    """Stage-instrumented scalar BM25 comparator returning both top-4096 raw hits and top-100 unique cases."""
    t_start = time.perf_counter()
    scores = defaultdict(float)
    n, avg, k1, b = db.execute("SELECT n,avg,k1,b FROM stats WHERE kind=?", (kind,)).fetchone()
    fetch_seconds = 0.0
    score_seconds = 0.0
    rows_seen = 0
    terms_seen = 0
    lookup = maps[kind]

    for term in sorted(set(re.findall(r"\w+", query.casefold(), re.UNICODE))):
        row = db.execute("SELECT df FROM terms WHERE kind=? AND term=?", (kind, term)).fetchone()
        if row is None:
            continue
        terms_seen += 1
        idf = math.log(1.0 + (n - row[0] + 0.5) / (row[0] + 0.5))
        t0 = time.perf_counter()
        cursor = db.execute("SELECT id,tf FROM postings WHERE kind=? AND term=?", (kind, term))
        fetch_seconds += time.perf_counter() - t0
        while True:
            t0 = time.perf_counter()
            rows = cursor.fetchmany(4096)
            fetch_seconds += time.perf_counter() - t0
            if not rows:
                break
            t0 = time.perf_counter()
            rows_seen += len(rows)
            for ident, tf in rows:
                case, length = lookup[ident]
                if case == exclude:
                    continue
                scores[ident] += idf * tf * (k1 + 1.0) / (tf + k1 * (1.0 - b + b * length / (avg or 1.0)))
            score_seconds += time.perf_counter() - t0

    t0 = time.perf_counter()
    all_sorted = sorted(scores.items(), key=lambda p: (-p[1], p[0]))
    top_raw = all_sorted[:limit]
    sort_seconds = time.perf_counter() - t0
    total_seconds = time.perf_counter() - t_start

    # Also compute oracle unique_cases top 100 across the entire positive-score universe (outside timer)
    uniq_100 = []
    seen_cases = set()
    for ident, sc in all_sorted:
        cid = lookup[ident][0]
        if cid not in seen_cases:
            seen_cases.add(cid)
            uniq_100.append((ident, cid, sc))
            if len(uniq_100) == 100:
                break

    return {
        "top_raw": top_raw,
        "uniq_100": uniq_100,
        "matched_documents": len(all_sorted),
        "terms_matched": terms_seen,
        "postings_rows": rows_seen,
        "timings": {
            "total_seconds": total_seconds,
            "postings_fetch_seconds": fetch_seconds,
            "python_scoring_seconds": score_seconds,
            "sort_seconds": sort_seconds,
        },
    }


def run_part_c_stage_benchmark() -> dict:
    from pipeline_v2.full_search.lexical import LexicalSession

    manifest = json.loads(
        (ROOT / "pipeline_v2/reviews/m3_search_latency_diagnostic_v1/workload_manifest.json").read_bytes()
    )
    t_open = time.perf_counter()
    session = LexicalSession(ROOT)
    open_wall = time.perf_counter() - t_open

    # Measure single guard() call latency and revalidate() latency
    t_g = time.perf_counter()
    for _ in range(10):
        session.guard()
    single_guard_seconds = (time.perf_counter() - t_g) / 10.0

    t_rev = time.perf_counter()
    rev_res = session.revalidate()
    revalidate_seconds = time.perf_counter() - t_rev

    # Build compact interned maps for scalar comparator using the same SQLite connection
    t_map = time.perf_counter()
    maps = {
        kind: {
            ident: (sys.intern(case), length)
            for ident, case, length in session.reader.db.execute(
                "SELECT id,case_id,length FROM documents WHERE kind=?", (kind,)
            )
        }
        for kind in ("case", "passage")
    }
    scalar_map_seconds = time.perf_counter() - t_map

    rows = []
    try:
        for kind in ("case", "passage"):
            for q in manifest["queries"]:
                qid = q["query_id"]
                qtext = q["text"]
                qcase = q["query_case"]
                ordinal = q["ordinal"]

                def run_vec_4096():
                    t0 = time.perf_counter()
                    resp = session.search(qtext, kind, limit=4096, exclude_case=qcase, unique_cases=False)
                    outer = time.perf_counter() - t0
                    return resp, outer

                def run_scal_4096():
                    return scalar_decomposed(session.reader.db, maps, qtext, kind, qcase, limit=4096)

                # Counterbalanced 3-step sequence so the first call warms postings for the query,
                # and steps 2 & 3 compare scalar vs vectorized on matched warm postings cache.
                if ordinal % 2 == 0:
                    first_method = "vectorized"
                    vec_first_resp, vec_first_outer = run_vec_4096()
                    scal_warm = run_scal_4096()
                    vec_warm_resp, vec_warm_outer = run_vec_4096()
                    first_seconds = vec_first_outer
                else:
                    first_method = "scalar"
                    scal_first = run_scal_4096()
                    vec_warm_resp, vec_warm_outer = run_vec_4096()
                    scal_warm = run_scal_4096()
                    first_seconds = scal_first["timings"]["total_seconds"]

                # Step 4: Run unique_cases=True, limit=100 on warm cache
                t_u = time.perf_counter()
                vec_u100_resp = session.search(qtext, kind, limit=100, exclude_case=qcase, unique_cases=True)
                vec_u100_outer = time.perf_counter() - t_u

                # Parity check 1: limit=4096 raw hits
                id_key = "passage_id" if kind == "passage" else "case_id"
                vec_raw_pairs = [(h[id_key], h["score"]) for h in vec_warm_resp["hits"]]
                scal_raw_pairs = scal_warm["top_raw"]
                assert [i for i, _ in vec_raw_pairs] == [i for i, _ in scal_raw_pairs], (qid, kind, "raw_4096_id_mismatch")
                max_diff_4096 = max((abs(a[1] - b[1]) for a, b in zip(vec_raw_pairs, scal_raw_pairs)), default=0.0)
                assert max_diff_4096 <= 1e-12

                # Parity check 2: unique_cases=True, limit=100
                vec_u100_triples = [(h[id_key], h["case_id"], h["score"]) for h in vec_u100_resp["hits"]]
                scal_u100_triples = scal_warm["uniq_100"]
                assert [(i, c) for i, c, _ in vec_u100_triples] == [(i, c) for i, c, _ in scal_u100_triples], (
                    qid,
                    kind,
                    "unique_100_id_mismatch",
                )
                max_diff_u100 = max((abs(a[2] - b[2]) for a, b in zip(vec_u100_triples, scal_u100_triples)), default=0.0)
                assert max_diff_u100 <= 1e-12
                assert len({c for _, c, _ in vec_u100_triples}) == len(vec_u100_triples)
                assert qcase not in {c for _, c, _ in vec_u100_triples}

                vec_t = vec_warm_resp["timings"]
                scal_t = scal_warm["timings"]
                u100_t = vec_u100_resp["timings"]

                row = {
                    "query_id": qid,
                    "kind": kind,
                    "ordinal": ordinal,
                    "first_method_in_pair": first_method,
                    "first_call_seconds": first_seconds,
                    "matched_documents": vec_warm_resp["matched_documents"],
                    "terms_matched": vec_warm_resp["terms_matched"],
                    "postings_rows": vec_warm_resp["postings_rows"],
                    "parity": {
                        "raw_4096_ids_exact": True,
                        "raw_4096_max_abs_score_diff": max_diff_4096,
                        "unique_100_ids_and_cases_exact": True,
                        "unique_100_max_abs_score_diff": max_diff_u100,
                        "unique_100_hits_returned": len(vec_u100_triples),
                    },
                    "warm_vectorized_4096": {
                        "session_outer_seconds": vec_warm_outer,
                        "guard_overhead_seconds": max(0.0, vec_warm_outer - vec_t["total_seconds"]),
                        **vec_t,
                        "scoring_plus_top_seconds": vec_t["mapping_and_scoring_seconds"] + vec_t["top_selection_seconds"],
                        "scoring_only_seconds_without_guard_and_metadata": (
                            vec_t["postings_fetch_seconds"]
                            + vec_t["mapping_and_scoring_seconds"]
                            + vec_t["top_selection_seconds"]
                        ),
                    },
                    "warm_scalar_4096": {
                        **scal_t,
                        "scoring_plus_sort_seconds": scal_t["python_scoring_seconds"] + scal_t["sort_seconds"],
                    },
                    "warm_vectorized_unique_cases_100": {
                        "session_outer_seconds": vec_u100_outer,
                        "guard_overhead_seconds": max(0.0, vec_u100_outer - u100_t["total_seconds"]),
                        **u100_t,
                    },
                    "warm_stage_ratios": {
                        "numpy_score_plus_top_vs_python_score_plus_sort_speedup": round(
                            (scal_t["python_scoring_seconds"] + scal_t["sort_seconds"])
                            / max(1e-9, vec_t["mapping_and_scoring_seconds"] + vec_t["top_selection_seconds"]),
                            3,
                        ),
                        "numpy_mapping_and_scoring_vs_python_scoring_speedup": round(
                            scal_t["python_scoring_seconds"] / max(1e-9, vec_t["mapping_and_scoring_seconds"]),
                            3,
                        ),
                        "top_partition_vs_python_sort_speedup": round(
                            scal_t["sort_seconds"] / max(1e-9, vec_t["top_selection_seconds"]),
                            3,
                        ),
                        "metadata_4096_vs_unique100_ratio": round(
                            vec_t["metadata_seconds"] / max(1e-9, u100_t["metadata_seconds"]),
                            3,
                        ),
                    },
                }
                rows.append(row)
                (HERE / "bounded_benchmark_progress.json").write_text(
                    json.dumps({"completed_rows": len(rows), "rows": rows}, indent=2),
                    encoding="utf-8",
                )
                print(
                    json.dumps(
                        {
                            "query_id": qid,
                            "kind": kind,
                            "vec_4096_warm_s": round(vec_warm_outer, 4),
                            "scal_4096_warm_s": round(scal_t["total_seconds"], 4),
                            "vec_u100_warm_s": round(vec_u100_outer, 4),
                            "vec_score_s": round(vec_t["mapping_and_scoring_seconds"], 4),
                            "scal_score_s": round(scal_t["python_scoring_seconds"], 4),
                            "meta_4096_s": round(vec_t["metadata_seconds"], 4),
                            "meta_u100_s": round(u100_t["metadata_seconds"], 4),
                        }
                    ),
                    flush=True,
                )
    finally:
        session.close()

    summary = {}
    for kind in ("case", "passage"):
        krows = [r for r in rows if r["kind"] == kind]
        summary[kind] = {
            "warm_vectorized_4096_outer_median_s": statistics.median(
                r["warm_vectorized_4096"]["session_outer_seconds"] for r in krows
            ),
            "warm_vectorized_4096_scoring_only_no_meta_no_guard_median_s": statistics.median(
                r["warm_vectorized_4096"]["scoring_only_seconds_without_guard_and_metadata"] for r in krows
            ),
            "warm_scalar_4096_total_median_s": statistics.median(
                r["warm_scalar_4096"]["total_seconds"] for r in krows
            ),
            "warm_vectorized_unique100_outer_median_s": statistics.median(
                r["warm_vectorized_unique_cases_100"]["session_outer_seconds"] for r in krows
            ),
            "warm_postings_fetch_vec_median_s": statistics.median(
                r["warm_vectorized_4096"]["postings_fetch_seconds"] for r in krows
            ),
            "warm_postings_fetch_scal_median_s": statistics.median(
                r["warm_scalar_4096"]["postings_fetch_seconds"] for r in krows
            ),
            "warm_numpy_mapping_and_scoring_median_s": statistics.median(
                r["warm_vectorized_4096"]["mapping_and_scoring_seconds"] for r in krows
            ),
            "warm_python_scoring_median_s": statistics.median(
                r["warm_scalar_4096"]["python_scoring_seconds"] for r in krows
            ),
            "warm_numpy_top_selection_4096_median_s": statistics.median(
                r["warm_vectorized_4096"]["top_selection_seconds"] for r in krows
            ),
            "warm_numpy_top_selection_unique100_median_s": statistics.median(
                r["warm_vectorized_unique_cases_100"]["top_selection_seconds"] for r in krows
            ),
            "warm_python_sort_4096_median_s": statistics.median(
                r["warm_scalar_4096"]["sort_seconds"] for r in krows
            ),
            "warm_metadata_4096_median_s": statistics.median(
                r["warm_vectorized_4096"]["metadata_seconds"] for r in krows
            ),
            "warm_metadata_unique100_median_s": statistics.median(
                r["warm_vectorized_unique_cases_100"]["metadata_seconds"] for r in krows
            ),
            "warm_guard_overhead_median_s": statistics.median(
                r["warm_vectorized_4096"]["guard_overhead_seconds"] for r in krows
            ),
            "median_numpy_score_plus_top_speedup_vs_python": statistics.median(
                r["warm_stage_ratios"]["numpy_score_plus_top_vs_python_score_plus_sort_speedup"] for r in krows
            ),
        }

    return {
        "session_open_seconds": open_wall,
        "session_initialization_seconds": session.initialization_seconds,
        "reader_preload_seconds": session.reader.preload_seconds,
        "single_guard_seconds": single_guard_seconds,
        "explicit_revalidate_seconds": revalidate_seconds,
        "explicit_revalidate_response": rev_res,
        "scalar_map_preload_seconds": scalar_map_seconds,
        "summary_by_channel": summary,
        "rows": rows,
    }


def main():
    started = time.perf_counter()
    print("=== Running Part A: Memory & PRAGMA Subprocess Audit ===", flush=True)
    part_a = run_part_a_subprocesses()
    print("=== Running Part B: Standalone No-Env CLI Checks ===", flush=True)
    part_b = run_part_b_cli_checks()
    print("=== Running Part C: Locked 8-Query Stage-Decomposed Benchmark ===", flush=True)
    part_c = run_part_c_stage_benchmark()

    out = {
        "schema_version": "ag-m3-lexical-bounded-benchmark-results-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "manifest_path": "pipeline_v2/reviews/m3_lexical_ag_review_v1/bounded_benchmark_manifest.json",
        "total_elapsed_seconds": time.perf_counter() - started,
        "part_a_memory_and_pragma_audit": part_a,
        "part_b_standalone_cli_verification": part_b,
        "part_c_stage_decomposed_8_query_benchmark": part_c,
    }
    out_path = HERE / "bounded_benchmark_results.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"=== ALL DONE in {out['total_elapsed_seconds']:.2f}s -> {out_path} ===", flush=True)


if __name__ == "__main__":
    main()
