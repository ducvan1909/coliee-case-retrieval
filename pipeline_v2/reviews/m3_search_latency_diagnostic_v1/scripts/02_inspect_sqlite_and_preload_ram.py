"""Step 3 & 4 (Part 1): Inspect SQLite index structure, EXPLAIN QUERY PLAN, actual preload RAM/time, and fixture oracle parity."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import gc
import json
import math
import re
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("E:/Git/coliee-case-retrieval")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2.optimization_v2.index import PersistentBM25
from pipeline_v2.retrieval.bm25 import BM25, analyze

OUT_DIR = ROOT / "pipeline_v2/reviews/m3_search_latency_diagnostic_v1"
RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
DB_PATH = RUN_DIR / "lexical.sqlite3"


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
        "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
        "private_usage_bytes": int(counters.PrivateUsage),
        "working_set_mib": round(counters.WorkingSetSize / (1024**2), 3),
        "peak_working_set_mib": round(counters.PeakWorkingSetSize / (1024**2), 3),
        "private_usage_mib": round(counters.PrivateUsage / (1024**2), 3),
    }


def inspect_sqlite_structure() -> dict:
    uri = f"file:{DB_PATH.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")

    pragmas = {}
    for p in (
        "cache_size",
        "mmap_size",
        "temp_store",
        "page_size",
        "page_count",
        "freelist_count",
        "journal_mode",
        "locking_mode",
        "synchronous",
        "query_only",
    ):
        row = conn.execute(f"PRAGMA {p}").fetchone()
        pragmas[p] = row[0] if row else None

    schema_rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    schema = [
        {"type": r[0], "name": r[1], "tbl_name": r[2], "sql": r[3]} for r in schema_rows
    ]

    stats_rows = conn.execute("SELECT kind, n, avg, k1, b FROM stats").fetchall()
    stats_table = {
        r[0]: {"n": r[1], "avg": r[2], "k1": r[3], "b": r[4]} for r in stats_rows
    }

    term_counts = dict(
        conn.execute("SELECT kind, COUNT(*), SUM(df), MAX(df) FROM terms GROUP BY kind")
        .fetchall()
        and [
            (r[0], {"distinct_terms": r[1], "sum_df_postings": r[2], "max_df": r[3]})
            for r in conn.execute(
                "SELECT kind, COUNT(*), SUM(df), MAX(df) FROM terms GROUP BY kind"
            ).fetchall()
        ]
    )

    doc_metadata_stats = {}
    for kind in ("case", "passage"):
        r = conn.execute(
            "SELECT COUNT(*), SUM(LENGTH(metadata)), AVG(LENGTH(metadata)), MAX(LENGTH(metadata)) FROM documents WHERE kind=?",
            (kind,),
        ).fetchone()
        doc_metadata_stats[kind] = {
            "row_count": r[0],
            "total_metadata_bytes": r[1],
            "avg_metadata_bytes": round(r[2], 2),
            "max_metadata_bytes": r[3],
        }

    # Explain query plans
    eqp = {}
    eqp["A_postings_join_documents"] = [
        list(r)
        for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT p.id,p.tf,d.length FROM postings p JOIN documents d ON d.kind=p.kind AND d.id=p.id WHERE p.kind=? AND p.term=? AND (? IS NULL OR d.case_id!=?)",
            ("passage", "the", "011904.txt", "011904.txt"),
        ).fetchall()
    ]
    eqp["BC_postings_no_join"] = [
        list(r)
        for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT id, tf FROM postings WHERE kind=? AND term=?",
            ("passage", "the"),
        ).fetchall()
    ]
    eqp["terms_df_lookup"] = [
        list(r)
        for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT df FROM terms WHERE kind=? AND term=?",
            ("passage", "the"),
        ).fetchall()
    ]
    eqp["get_many_256"] = [
        list(r)
        for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT id,metadata FROM documents WHERE kind=? AND id IN (?,?,?)",
            ("passage", "000001:0", "000001:1", "000001:2"),
        ).fetchall()
    ]
    eqp["preload_documents_scan"] = [
        list(r)
        for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT id, case_id, length FROM documents WHERE kind=?",
            ("passage",),
        ).fetchall()
    ]

    conn.close()
    return {
        "sqlite_version": sqlite3.sqlite_version,
        "db_file_size_bytes": DB_PATH.stat().st_size,
        "db_file_size_gib": round(DB_PATH.stat().st_size / (1024**3), 4),
        "default_pragmas": pragmas,
        "schema": schema,
        "stats_table": stats_table,
        "term_and_posting_totals": term_counts,
        "document_metadata_stats": doc_metadata_stats,
        "explain_query_plans": eqp,
    }


def measure_preload_costs() -> dict:
    """Measure exact startup/preload latency and actual RAM delta (tracemalloc + Windows RSS/PrivateUsage)."""
    uri = f"file:{DB_PATH.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")

    # 1. Measure preloading (id -> (length, case_id)) for both 'case' and 'passage'
    gc.collect()
    tracemalloc.start()
    snap_before_all = tracemalloc.take_snapshot()
    traced_before, _ = tracemalloc.get_traced_memory()
    proc_before = get_process_memory()

    t0 = time.perf_counter()
    case_lengths = {}
    case_case_ids = {}
    for ident, cid, length in conn.execute(
        "SELECT id, case_id, length FROM documents WHERE kind='case'"
    ):
        case_lengths[ident] = int(length)
        case_case_ids[ident] = cid
    t1 = time.perf_counter()

    traced_after_case, traced_peak_case = tracemalloc.get_traced_memory()
    proc_after_case = get_process_memory()

    # Check passage id -> case_id invariant while loading passage_lengths and passage_case_ids
    t2 = time.perf_counter()
    passage_lengths = {}
    passage_case_ids = {}
    prefix_invariant_holds = True
    for ident, cid, length in conn.execute(
        "SELECT id, case_id, length FROM documents WHERE kind='passage'"
    ):
        passage_lengths[ident] = int(length)
        passage_case_ids[ident] = cid
        if ident.split(":", 1)[0] + ".txt" != cid:
            prefix_invariant_holds = False
    t3 = time.perf_counter()

    traced_after_both, traced_peak_both = tracemalloc.get_traced_memory()
    proc_after_both = get_process_memory()

    # Also measure just `passage_lengths` dict alone (when `passage_case_ids` is released vs kept)
    del passage_case_ids
    gc.collect()
    traced_lengths_only, _ = tracemalloc.get_traced_memory()
    proc_lengths_only = get_process_memory()

    tracemalloc.stop()
    conn.close()

    return {
        "case_preload": {
            "row_count": len(case_lengths),
            "elapsed_seconds": round(t1 - t0, 6),
            "tracemalloc_delta_bytes": traced_after_case - traced_before,
            "tracemalloc_delta_mib": round((traced_after_case - traced_before) / (1024**2), 3),
            "process_private_delta_mib": round(
                proc_after_case["private_usage_mib"] - proc_before["private_usage_mib"], 3
            ),
            "process_working_set_delta_mib": round(
                proc_after_case["working_set_mib"] - proc_before["working_set_mib"], 3
            ),
        },
        "passage_preload_with_explicit_case_id_dict": {
            "row_count": len(passage_lengths),
            "elapsed_seconds": round(t3 - t2, 6),
            "total_case_plus_passage_elapsed_seconds": round((t1 - t0) + (t3 - t2), 6),
            "passage_id_prefix_equals_case_id_for_all_415693_rows": prefix_invariant_holds,
            "tracemalloc_delta_bytes_over_baseline": traced_after_both - traced_before,
            "tracemalloc_delta_mib_over_baseline": round(
                (traced_after_both - traced_before) / (1024**2), 3
            ),
            "tracemalloc_peak_mib_during_load": round(
                (traced_peak_both - traced_before) / (1024**2), 3
            ),
            "process_private_delta_mib": round(
                proc_after_both["private_usage_mib"] - proc_before["private_usage_mib"], 3
            ),
            "process_working_set_delta_mib": round(
                proc_after_both["working_set_mib"] - proc_before["working_set_mib"], 3
            ),
            "process_before": proc_before,
            "process_after": proc_after_both,
        },
        "passage_preload_lengths_dict_only": {
            "tracemalloc_delta_bytes_over_baseline": traced_lengths_only - traced_before,
            "tracemalloc_delta_mib_over_baseline": round(
                (traced_lengths_only - traced_before) / (1024**2), 3
            ),
            "process_private_delta_mib": round(
                proc_lengths_only["private_usage_mib"] - proc_before["private_usage_mib"], 3
            ),
            "process_working_set_delta_mib": round(
                proc_lengths_only["working_set_mib"] - proc_before["working_set_mib"], 3
            ),
        },
    }


def search_variant_b_or_c(
    db: sqlite3.Connection,
    query: str,
    kind: str,
    limit: int,
    exclude_case: str | None,
    lengths_map: dict[str, int],
    case_ids_map: dict[str, str],
    get_many_fn,
) -> list[dict]:
    """Exact BM25 search using preloaded id->length and id->case_id maps without JOIN documents."""
    stats = db.execute("SELECT n,avg,k1,b FROM stats WHERE kind=?", (kind,)).fetchone()
    n, avg, k1, b = stats
    scores = defaultdict(float)
    for term in sorted(set(analyze(query))):
        row = db.execute(
            "SELECT df FROM terms WHERE kind=? AND term=?", (kind, term)
        ).fetchone()
        if row is None:
            continue
        idf = math.log(1 + (n - row[0] + 0.5) / (row[0] + 0.5))
        rows = db.execute(
            "SELECT id, tf FROM postings WHERE kind=? AND term=?", (kind, term)
        )
        for ident, tf in rows:
            if exclude_case is not None and case_ids_map[ident] == exclude_case:
                continue
            length = lengths_map[ident]
            scores[ident] += (
                idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (avg or 1)))
            )
    ids = sorted(scores, key=lambda ident: (-scores[ident], ident))[:limit]
    return [{**doc, "score": scores[ident]} for ident, doc in zip(ids, get_many_fn(kind, ids))]


def run_small_fixture_oracle_tests() -> dict:
    """Compare A, B, C against independent in-memory BM25 oracle on small fixtures."""
    case_docs = [
        {
            "case_id": "000001.txt",
            "source_hash": "h1",
            "text": "La décision n'est pas raisonnable sous s. 97(1) et 100% café. Judicial review.",
        },
        {
            "case_id": "000002.txt",
            "source_hash": "h2",
            "text": "Tiebreak alpha beta gamma judicial review reasonableness.",
        },
        {
            "case_id": "000003.txt",
            "source_hash": "h3",
            "text": "Tiebreak alpha delta epsilon judicial review reasonableness.",
        },
        {
            "case_id": "000004.txt",
            "source_hash": "h4",
            "text": "Procedural fairness and natural justice in citizenship appeal 2019.",
        },
    ]
    passage_docs = [
        {
            "case_id": "000001.txt",
            "passage_id": "000001:p01",
            "text": "La décision n'est pas raisonnable sous s. 97(1) et 100% café.",
        },
        {
            "case_id": "000001.txt",
            "passage_id": "000001:p02",
            "text": "Judicial review standard of review reasonableness.",
        },
        {
            "case_id": "000002.txt",
            "passage_id": "000002:p01",
            "text": "Tiebreak alpha beta gamma.",
        },
        {
            "case_id": "000003.txt",
            "passage_id": "000003:p01",
            "text": "Tiebreak alpha delta epsilon.",
        },
        {
            "case_id": "000004.txt",
            "passage_id": "000004:p01",
            "text": "Procedural fairness and natural justice in citizenship appeal 2019.",
        },
    ]

    oracle_case = BM25(case_docs, k1=1.5, b=0.75)
    oracle_passage = BM25(passage_docs, k1=1.5, b=0.75)

    test_cases = [
        ("décision n'est pas 97(1) café", None, 10),
        ("judicial review reasonableness", "000001.txt", 10),
        ("tiebreak alpha", None, 1),
        ("tiebreak alpha", "000002.txt", 1),
        ("procedural fairness 2019", None, 5),
        ("nonexistentterm999", None, 5),
    ]

    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        db_file = Path(tmp) / "fixture_lexical.sqlite3"
        created = PersistentBM25.create(
            db_file, {"case": iter(case_docs), "passage": iter(passage_docs)}, k1=1.5, b=0.75
        )
        created.close()

        bm_a = PersistentBM25(db_file, readonly=True)
        bm_b = PersistentBM25(db_file, readonly=True)
        bm_c = PersistentBM25(db_file, readonly=True)
        bm_c.db.execute("PRAGMA mmap_size=67108864")
        bm_c.db.execute("PRAGMA cache_size=-16384")
        bm_c.db.execute("PRAGMA temp_store=MEMORY")

        lengths_map = {}
        case_ids_map = {}
        for kind in ("case", "passage"):
            lengths_map[kind] = {}
            case_ids_map[kind] = {}
            for ident, cid, length in bm_b.db.execute(
                "SELECT id, case_id, length FROM documents WHERE kind=?", (kind,)
            ):
                lengths_map[kind][ident] = int(length)
                case_ids_map[kind][ident] = cid

        for kind, oracle, id_key in (
            ("case", oracle_case, "case_id"),
            ("passage", oracle_passage, "passage_id"),
        ):
            for q, excl, lim in test_cases:
                ref = oracle.search(q, limit=lim, exclude_case=excl)
                res_a = bm_a.search(q, kind, limit=lim, exclude_case=excl)
                res_b = search_variant_b_or_c(
                    bm_b.db,
                    q,
                    kind,
                    lim,
                    excl,
                    lengths_map[kind],
                    case_ids_map[kind],
                    bm_b.get_many,
                )
                res_c = search_variant_b_or_c(
                    bm_c.db,
                    q,
                    kind,
                    lim,
                    excl,
                    lengths_map[kind],
                    case_ids_map[kind],
                    bm_c.get_many,
                )

                ref_ids = [r[id_key] for r in ref]
                a_ids = [r[id_key] for r in res_a]
                b_ids = [r[id_key] for r in res_b]
                c_ids = [r[id_key] for r in res_c]

                assert ref_ids == a_ids == b_ids == c_ids
                max_diff_oracle_a = max(
                    (abs(x["score"] - y["score"]) for x, y in zip(ref, res_a)), default=0.0
                )
                max_diff_a_b = max(
                    (abs(x["score"] - y["score"]) for x, y in zip(res_a, res_b)), default=0.0
                )
                max_diff_a_c = max(
                    (abs(x["score"] - y["score"]) for x, y in zip(res_a, res_c)), default=0.0
                )
                assert max_diff_oracle_a <= 1e-12
                assert max_diff_a_b == 0.0
                assert max_diff_a_c == 0.0

                checks.append(
                    {
                        "channel": kind,
                        "query": q,
                        "exclude_case": excl,
                        "limit": lim,
                        "hits": len(ref),
                        "ids_match_oracle_A_B_C": True,
                        "max_score_diff_oracle_vs_A": max_diff_oracle_a,
                        "max_score_diff_A_vs_B": max_diff_a_b,
                        "max_score_diff_A_vs_C": max_diff_a_c,
                    }
                )

        bm_a.close()
        bm_b.close()
        bm_c.close()

    return {
        "status": "PASS",
        "numeric_tolerance_declared": {"atol": 1e-12, "rtol": 1e-12},
        "total_fixture_checks": len(checks),
        "all_passed": True,
        "checks": checks,
    }


def main() -> None:
    sqlite_info = inspect_sqlite_structure()
    preload_info = measure_preload_costs()
    fixture_oracle = run_small_fixture_oracle_tests()

    out = {
        "sqlite_structure": sqlite_info,
        "preload_measurements": preload_info,
        "small_fixture_oracle_parity": fixture_oracle,
    }
    (OUT_DIR / "sqlite_and_preload_diagnostics.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
