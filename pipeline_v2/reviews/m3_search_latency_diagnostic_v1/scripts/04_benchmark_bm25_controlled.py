"""Step 3, 4 & 6 (BM25 channels): Stage-instrumented breakdown and controlled A/B/C comparison with crossover repeats."""
from __future__ import annotations

from collections import defaultdict
import ctypes
from ctypes import wintypes
import gc
import json
import math
import random
import shutil
import sqlite3
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path("E:/Git/coliee-case-retrieval")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2.optimization_v2.index import PersistentBM25
from pipeline_v2.retrieval.bm25 import analyze

OUT_DIR = ROOT / "pipeline_v2/reviews/m3_search_latency_diagnostic_v1"
RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
DB_PATH = RUN_DIR / "lexical.sqlite3"
CHECKPOINT_PATH = OUT_DIR / "bm25_measurements_checkpoint.json"


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


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
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
    psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(counters), ctypes.sizeof(counters)
    )
    return {
        "working_set_bytes": int(counters.WorkingSetSize),
        "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
        "private_usage_bytes": int(counters.PrivateUsage),
        "page_fault_count": int(counters.PageFaultCount),
        "working_set_mib": round(counters.WorkingSetSize / (1024**2), 3),
        "peak_working_set_mib": round(counters.PeakWorkingSetSize / (1024**2), 3),
        "private_usage_mib": round(counters.PrivateUsage / (1024**2), 3),
    }


def get_avail_ram_gib() -> float:
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return round(stat.ullAvailPhys / (1024**3), 3)


def open_ro_connection(variant: str) -> tuple[sqlite3.Connection, dict, float]:
    """Open read-only SQLite connection for variant A, B, or C and record active PRAGMAs."""
    t0 = time.perf_counter()
    uri = f"file:{DB_PATH.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    if variant == "C":
        conn.execute("PRAGMA mmap_size = 4294967296")  # 4 GiB
        conn.execute("PRAGMA cache_size = -524288")    # 512 MiB
        conn.execute("PRAGMA temp_store = MEMORY")
    t1 = time.perf_counter()
    pragmas = {
        p: conn.execute(f"PRAGMA {p}").fetchone()[0]
        for p in ("cache_size", "mmap_size", "temp_store", "query_only")
    }
    return conn, pragmas, (t1 - t0)


def get_many_docs(conn: sqlite3.Connection, kind: str, ids: list[str]) -> list[dict]:
    found = {}
    for offset in range(0, len(ids), 256):
        block = ids[offset : offset + 256]
        if not block:
            continue
        q = (
            "SELECT id,metadata FROM documents WHERE kind=? AND id IN ("
            + ",".join("?" for _ in block)
            + ")"
        )
        found.update(
            (ident, json.loads(meta))
            for ident, meta in conn.execute(q, [kind, *block])
        )
    if set(found) != set(ids):
        raise RuntimeError("Missing lexical document metadata")
    return [found[i] for i in ids]


def run_instrumented_bm25(
    conn: sqlite3.Connection,
    variant: str,
    query: str,
    kind: str,
    limit: int,
    exclude_case: str | None,
    preloaded_lengths: dict[str, int] | None = None,
    preloaded_case_ids: dict[str, str] | None = None,
) -> tuple[list[dict], dict]:
    """Execute BM25 search for Variant A, B, or C with fine-grained stage timing."""
    mem_before = get_process_memory()
    t_total0 = time.perf_counter()

    # Stage b: stats + terms df lookup
    t_b0 = time.perf_counter()
    stats = conn.execute(
        "SELECT n,avg,k1,b FROM stats WHERE kind=?", (kind,)
    ).fetchone()
    n, avg, k1, b = stats
    unique_terms = sorted(set(analyze(query)))
    term_idfs = []
    total_df_sum = 0
    for term in unique_terms:
        row = conn.execute(
            "SELECT df FROM terms WHERE kind=? AND term=?", (kind, term)
        ).fetchone()
        if row is None:
            continue
        df_val = int(row[0])
        total_df_sum += df_val
        idf = math.log(1 + (n - df_val + 0.5) / (df_val + 0.5))
        term_idfs.append((term, df_val, idf))
    t_b1 = time.perf_counter()
    stage_b_seconds = t_b1 - t_b0

    # Stage c (SQLite postings fetch / join) & Stage d (Python BM25 scoring accumulation)
    stage_c_seconds = 0.0
    stage_d_seconds = 0.0
    scores = defaultdict(float)
    postings_rows_fetched = 0
    postings_rows_scored = 0

    if variant == "A":
        for term, _, idf in term_idfs:
            tc0 = time.perf_counter()
            rows = conn.execute(
                "SELECT p.id,p.tf,d.length FROM postings p JOIN documents d ON d.kind=p.kind AND d.id=p.id WHERE p.kind=? AND p.term=? AND (? IS NULL OR d.case_id!=?)",
                (kind, term, exclude_case, exclude_case),
            ).fetchall()
            tc1 = time.perf_counter()
            stage_c_seconds += tc1 - tc0
            postings_rows_fetched += len(rows)

            td0 = time.perf_counter()
            for ident, tf, length in rows:
                scores[ident] += (
                    idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (avg or 1)))
                )
            td1 = time.perf_counter()
            stage_d_seconds += td1 - td0
            postings_rows_scored += len(rows)
    else:
        assert preloaded_lengths is not None and preloaded_case_ids is not None
        for term, _, idf in term_idfs:
            tc0 = time.perf_counter()
            rows = conn.execute(
                "SELECT id, tf FROM postings WHERE kind=? AND term=?", (kind, term)
            ).fetchall()
            tc1 = time.perf_counter()
            stage_c_seconds += tc1 - tc0
            postings_rows_fetched += len(rows)

            td0 = time.perf_counter()
            for ident, tf in rows:
                if exclude_case is not None and preloaded_case_ids[ident] == exclude_case:
                    continue
                length = preloaded_lengths[ident]
                scores[ident] += (
                    idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (avg or 1)))
                )
                postings_rows_scored += 1
            td1 = time.perf_counter()
            stage_d_seconds += td1 - td0

    # Stage e: Sort and select top hits
    t_e0 = time.perf_counter()
    all_sorted_ids = sorted(scores, key=lambda ident: (-scores[ident], ident))
    ids = all_sorted_ids[:limit]
    t_e1 = time.perf_counter()
    stage_e_seconds = t_e1 - t_e0

    # Stage f: Fetch and parse metadata for top `limit` hits
    t_f0 = time.perf_counter()
    docs = get_many_docs(conn, kind, ids)
    results = [{**doc, "score": scores[ident]} for ident, doc in zip(ids, docs)]
    t_f1 = time.perf_counter()
    stage_f_seconds = t_f1 - t_f0

    t_total1 = time.perf_counter()
    total_seconds = t_total1 - t_total0
    mem_after = get_process_memory()

    # Also measure how fast Stage f is if only fetching top-100 unique-case best hits (without affecting total_seconds)
    seen_c = set()
    top100_uc_ids = []
    for r in results:
        cid = r["case_id"]
        if cid not in seen_c:
            seen_c.add(cid)
            top100_uc_ids.append(r.get("passage_id", r["case_id"]))
            if len(top100_uc_ids) == 100:
                break
    t_f100_0 = time.perf_counter()
    _ = get_many_docs(conn, kind, top100_uc_ids)
    t_f100_1 = time.perf_counter()

    # Count unique cases at windows 256, 1024, 4096 and across all positive hits
    uc_256 = len({r["case_id"] for r in results[:256]})
    uc_1024 = len({r["case_id"] for r in results[:1024]})
    uc_limit = len({r["case_id"] for r in results})
    if kind == "case":
        total_pos_uc = len(scores)
    elif preloaded_case_ids is not None:
        total_pos_uc = len({preloaded_case_ids[i] for i in scores})
    else:
        total_pos_uc = len({i.split(":", 1)[0] for i in scores})

    metrics = {
        "variant": variant,
        "channel": kind,
        "limit": limit,
        "exclude_case": exclude_case,
        "unique_query_terms": len(unique_terms),
        "matched_query_terms": len(term_idfs),
        "total_df_all_cases": total_df_sum,
        "postings_rows_fetched_from_sqlite": postings_rows_fetched,
        "postings_rows_scored_after_exclusion": postings_rows_scored,
        "total_positive_hits": len(scores),
        "total_positive_unique_cases": total_pos_uc,
        "returned_hits": len(results),
        "unique_cases_at_256": uc_256,
        "unique_cases_at_1024": uc_1024,
        "unique_cases_at_limit": uc_limit,
        "stage_b_df_and_stats_seconds": round(stage_b_seconds, 6),
        "stage_c_postings_sqlite_fetch_seconds": round(stage_c_seconds, 6),
        "stage_d_python_scoring_seconds": round(stage_d_seconds, 6),
        "stage_e_sort_top_hits_seconds": round(stage_e_seconds, 6),
        "stage_f_metadata_fetch_limit_seconds": round(stage_f_seconds, 6),
        "stage_f_top100_unique_cases_metadata_seconds": round(t_f100_1 - t_f100_0, 6),
        "stage_g_total_query_seconds": round(total_seconds, 6),
        "stage_shares_percent": {
            "b_df_stats_pct": round(100.0 * stage_b_seconds / total_seconds, 2)
            if total_seconds > 0
            else 0.0,
            "c_postings_sqlite_pct": round(100.0 * stage_c_seconds / total_seconds, 2)
            if total_seconds > 0
            else 0.0,
            "d_python_scoring_pct": round(100.0 * stage_d_seconds / total_seconds, 2)
            if total_seconds > 0
            else 0.0,
            "e_sort_pct": round(100.0 * stage_e_seconds / total_seconds, 2)
            if total_seconds > 0
            else 0.0,
            "f_metadata_pct": round(100.0 * stage_f_seconds / total_seconds, 2)
            if total_seconds > 0
            else 0.0,
        },
        "page_fault_delta": mem_after["page_fault_count"] - mem_before["page_fault_count"],
        "working_set_mib_after": mem_after["working_set_mib"],
        "avail_system_ram_gib_after": get_avail_ram_gib(),
    }
    return results, metrics


def preload_tables_with_interned_case_id(conn: sqlite3.Connection) -> tuple[dict, dict, dict]:
    """Preload id->length and id->interned(case_id) for both case and passage, measuring exact time & OS/heap RAM."""
    gc.collect()
    proc_before = get_process_memory()
    tracemalloc.start()
    traced_0, _ = tracemalloc.get_traced_memory()

    t0 = time.perf_counter()
    lengths = {"case": {}, "passage": {}}
    case_ids = {"case": {}, "passage": {}}
    for kind in ("case", "passage"):
        l_map = lengths[kind]
        c_map = case_ids[kind]
        for ident, cid, length in conn.execute(
            "SELECT id, case_id, length FROM documents WHERE kind=?", (kind,)
        ):
            l_map[ident] = int(length)
            c_map[ident] = sys.intern(cid)
    t1 = time.perf_counter()
    traced_1, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    proc_after = get_process_memory()

    stats = {
        "preload_elapsed_seconds": round(t1 - t0, 6),
        "case_rows": len(lengths["case"]),
        "passage_rows": len(lengths["passage"]),
        "tracemalloc_heap_delta_bytes": traced_1 - traced_0,
        "tracemalloc_heap_delta_mib": round((traced_1 - traced_0) / (1024**2), 3),
        "tracemalloc_peak_delta_mib": round((traced_peak - traced_0) / (1024**2), 3),
        "working_set_before_mib": proc_before["working_set_mib"],
        "working_set_after_mib": proc_after["working_set_mib"],
        "private_usage_before_mib": proc_before["private_usage_mib"],
        "private_usage_after_mib": proc_after["private_usage_mib"],
    }
    return lengths, case_ids, stats


def compare_results(res_ref: list[dict], res_other: list[dict], id_key: str) -> dict:
    ids_ref = [r[id_key] for r in res_ref]
    ids_oth = [r[id_key] for r in res_other]
    ids_equal = ids_ref == ids_oth
    max_abs_score_diff = (
        max((abs(a["score"] - b["score"]) for a, b in zip(res_ref, res_other)), default=0.0)
        if ids_equal
        else float("inf")
    )
    meta_equal = (
        all(
            {k: v for k, v in a.items() if k != "score"}
            == {k: v for k, v in b.items() if k != "score"}
            for a, b in zip(res_ref, res_other)
        )
        if ids_equal
        else False
    )
    return {
        "count_ref": len(res_ref),
        "count_other": len(res_other),
        "ids_exact_match": ids_equal,
        "max_abs_score_diff": max_abs_score_diff,
        "within_declared_atol_1e_12": max_abs_score_diff <= 1e-12,
        "metadata_exact_match": meta_equal,
    }


def save_checkpoint(state: dict) -> None:
    CHECKPOINT_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    workload = json.loads((OUT_DIR / "workload_manifest.json").read_bytes())
    queries = workload["queries"]

    # Measure pure OS memory delta of preload WITHOUT tracemalloc first
    conn_tmp, _, _ = open_ro_connection("B")
    gc.collect()
    mem_pre_no_tm = get_process_memory()
    t_pre0 = time.perf_counter()
    tmp_l = {"case": {}, "passage": {}}
    tmp_c = {"case": {}, "passage": {}}
    for kind in ("case", "passage"):
        lm = tmp_l[kind]
        cm = tmp_c[kind]
        for ident, cid, length in conn_tmp.execute(
            "SELECT id, case_id, length FROM documents WHERE kind=?", (kind,)
        ):
            lm[ident] = int(length)
            cm[ident] = sys.intern(cid)
    t_pre1 = time.perf_counter()
    mem_post_no_tm = get_process_memory()
    del tmp_l, tmp_c
    gc.collect()
    conn_tmp.close()

    # Open the 3 persistent read-only diagnostic connections for A, B, C
    conn_a, pragmas_a, open_sec_a = open_ro_connection("A")
    conn_b, pragmas_b, open_sec_b = open_ro_connection("B")
    conn_c, pragmas_c, open_sec_c = open_ro_connection("C")

    # Preload once for B/C using conn_c (and record exact preload stats)
    lengths_map, case_ids_map, preload_stats_tm = preload_tables_with_interned_case_id(conn_b)
    preload_stats_tm["pure_os_memory_without_tracemalloc"] = {
        "preload_elapsed_seconds": round(t_pre1 - t_pre0, 6),
        "working_set_before_mib": mem_pre_no_tm["working_set_mib"],
        "working_set_after_mib": mem_post_no_tm["working_set_mib"],
        "working_set_delta_mib": round(
            mem_post_no_tm["working_set_mib"] - mem_pre_no_tm["working_set_mib"], 3
        ),
        "private_usage_before_mib": mem_pre_no_tm["private_usage_mib"],
        "private_usage_after_mib": mem_post_no_tm["private_usage_mib"],
        "private_usage_delta_mib": round(
            mem_post_no_tm["private_usage_mib"] - mem_pre_no_tm["private_usage_mib"], 3
        ),
    }

    state = {
        "schema_version": "m3-bm25-controlled-diagnostic-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "variants_declared": {
            "A": {
                "description": "Current PersistentBM25.search implementation (postings JOIN documents per term, no preload, default SQLite PRAGMAs).",
                "open_connection_seconds": round(open_sec_a, 6),
                "preload_seconds": 0.0,
                "pragmas": pragmas_a,
            },
            "B": {
                "description": "Preload (id -> length) and (id -> interned case_id) in memory; query postings without JOIN documents; default SQLite PRAGMAs.",
                "open_connection_seconds": round(open_sec_b, 6),
                "preload_seconds": preload_stats_tm["preload_elapsed_seconds"],
                "pragmas": pragmas_b,
            },
            "C": {
                "description": "Variant B + explicit read-only SQLite PRAGMAs (mmap_size=4GiB, cache_size=512MiB, temp_store=MEMORY).",
                "open_connection_seconds": round(open_sec_c, 6),
                "preload_seconds": preload_stats_tm["preload_elapsed_seconds"],
                "pragmas": pragmas_c,
            },
        },
        "startup_and_preload_measurements": preload_stats_tm,
        "uninstrumented_vs_instrumented_check": {},
        "correctness_comparisons": [],
        "case_channel_runs": [],
        "passage_channel_runs": [],
        "crossover_schedules": {"case": [], "passage": []},
    }
    save_checkpoint(state)

    # Check unperturbed PersistentBM25.search vs instrumented Variant A on Q01 (case and passage)
    raw_bm25 = PersistentBM25(DB_PATH, readonly=True)
    q01 = queries[0]
    for kind, id_key, lim in (("case", "case_id", 4096), ("passage", "passage_id", 4096)):
        t_u0 = time.perf_counter()
        res_unpert = raw_bm25.search(
            q01["text"], kind, limit=lim, exclude_case=q01["query_case"]
        )
        t_u1 = time.perf_counter()
        res_instr, m_instr = run_instrumented_bm25(
            conn_a, "A", q01["text"], kind, lim, q01["query_case"]
        )
        cmp_u = compare_results(res_unpert, res_instr, id_key)
        assert cmp_u["ids_exact_match"] and cmp_u["max_abs_score_diff"] == 0.0
        state["uninstrumented_vs_instrumented_check"][kind] = {
            "query_id": q01["query_id"],
            "unperturbed_PersistentBM25_search_seconds": round(t_u1 - t_u0, 6),
            "instrumented_variant_A_total_seconds": m_instr["stage_g_total_query_seconds"],
            "exact_parity": cmp_u,
        }
        print(
            f"[Parity & Instrumentation Check] {kind} Q01: unperturbed={t_u1-t_u0:.4f}s "
            f"instrumented={m_instr['stage_g_total_query_seconds']:.4f}s match=True",
            flush=True,
        )
    raw_bm25.close()
    save_checkpoint(state)

    conns = {"A": conn_a, "B": conn_b, "C": conn_c}

    # =========================================================================
    # PART 1: CASE CHANNEL (All 8 queries, limit=4096; first_observed + 3 warm crossover repeats)
    # =========================================================================
    rng_case = random.Random(20261109)
    for pass_idx in range(4):
        pass_kind = "first_observed" if pass_idx == 0 else "warm_repeat"
        for q in queries:
            variants_order = ["A", "B", "C"]
            if pass_idx > 0:
                rng_case.shuffle(variants_order)
            state["crossover_schedules"]["case"].append(
                {"pass_index": pass_idx, "query_id": q["query_id"], "order": variants_order}
            )
            results_this_q = {}
            for v in variants_order:
                res, metrics = run_instrumented_bm25(
                    conns[v],
                    v,
                    q["text"],
                    "case",
                    4096,
                    q["query_case"],
                    lengths_map["case"] if v in ("B", "C") else None,
                    case_ids_map["case"] if v in ("B", "C") else None,
                )
                metrics["query_id"] = q["query_id"]
                metrics["pass_kind"] = pass_kind
                metrics["repeat_index"] = pass_idx
                metrics["run_sequence_number"] = len(state["case_channel_runs"]) + 1
                state["case_channel_runs"].append(metrics)
                if pass_idx == 0:
                    results_this_q[v] = res
            if pass_idx == 0:
                cmp_ab = compare_results(results_this_q["A"], results_this_q["B"], "case_id")
                cmp_ac = compare_results(results_this_q["A"], results_this_q["C"], "case_id")
                assert cmp_ab["ids_exact_match"] and cmp_ac["ids_exact_match"]
                state["correctness_comparisons"].append(
                    {
                        "channel": "case",
                        "query_id": q["query_id"],
                        "query_case": q["query_case"],
                        "limit": 4096,
                        "A_vs_B": cmp_ab,
                        "A_vs_C": cmp_ac,
                    }
                )
        save_checkpoint(state)
        print(f"[Case BM25] Completed pass {pass_idx} ({pass_kind})", flush=True)

    # =========================================================================
    # PART 2: PASSAGE CHANNEL (All 8 queries, limit=4096; first_observed + 3 warm crossover repeats)
    # =========================================================================
    rng_pass = random.Random(20261110)
    # Run query-by-query so each query completes first_observed + 3 warm crossover repeats
    # across A, B, C (ensuring complete A/B/C warm crossover data for every query in ascending order)
    for q in queries:
        for pass_idx in range(4):
            pass_kind = "first_observed" if pass_idx == 0 else "warm_repeat"
            variants_order = ["A", "B", "C"]
            if pass_idx > 0:
                rng_pass.shuffle(variants_order)
            state["crossover_schedules"]["passage"].append(
                {"pass_index": pass_idx, "query_id": q["query_id"], "order": variants_order}
            )
            results_this_q = {}
            for v in variants_order:
                res, metrics = run_instrumented_bm25(
                    conns[v],
                    v,
                    q["text"],
                    "passage",
                    4096,
                    q["query_case"],
                    lengths_map["passage"] if v in ("B", "C") else None,
                    case_ids_map["passage"] if v in ("B", "C") else None,
                )
                metrics["query_id"] = q["query_id"]
                metrics["pass_kind"] = pass_kind
                metrics["repeat_index"] = pass_idx
                metrics["run_sequence_number"] = len(state["passage_channel_runs"]) + 1
                state["passage_channel_runs"].append(metrics)
                if pass_idx == 0:
                    results_this_q[v] = res
                print(
                    f"[Passage BM25] {q['query_id']} pass={pass_idx} ({pass_kind}) var={v}: "
                    f"total={metrics['stage_g_total_query_seconds']:.3f}s "
                    f"(c_sqlite={metrics['stage_c_postings_sqlite_fetch_seconds']:.3f}s, "
                    f"d_score={metrics['stage_d_python_scoring_seconds']:.3f}s, "
                    f"e_sort={metrics['stage_e_sort_top_hits_seconds']:.3f}s, "
                    f"f_meta={metrics['stage_f_metadata_fetch_limit_seconds']:.3f}s)",
                    flush=True,
                )
                save_checkpoint(state)
            if pass_idx == 0:
                cmp_ab = compare_results(
                    results_this_q["A"], results_this_q["B"], "passage_id"
                )
                cmp_ac = compare_results(
                    results_this_q["A"], results_this_q["C"], "passage_id"
                )
                assert cmp_ab["ids_exact_match"] and cmp_ac["ids_exact_match"]
                state["correctness_comparisons"].append(
                    {
                        "channel": "passage",
                        "query_id": q["query_id"],
                        "query_case": q["query_case"],
                        "limit": 4096,
                        "A_vs_B": cmp_ab,
                        "A_vs_C": cmp_ac,
                    }
                )
                save_checkpoint(state)

    conn_a.close()
    conn_b.close()
    conn_c.close()
    (OUT_DIR / "bm25_measurements.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("BM25 CONTROLLED BENCHMARK COMPLETE", flush=True)


if __name__ == "__main__":
    main()
