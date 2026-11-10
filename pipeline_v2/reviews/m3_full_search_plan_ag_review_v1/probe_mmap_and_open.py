"""Quick read-only test of SQLite mmap_size/cache_size and open_context timing."""
import json
import time
from pathlib import Path
from pipeline_v2.optimization_v2.index import PersistentBM25
from pipeline_v2.passages import PassageReader
from pipeline_v2.navigation import NavigationReader

ROOT = Path("E:/Git/coliee-case-retrieval")
RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"


def main():
    bm25 = PersistentBM25(RUN_DIR / "lexical.sqlite3", readonly=True)
    # Check default pragmas
    default_cache = bm25.db.execute("PRAGMA cache_size").fetchone()[0]
    default_mmap = bm25.db.execute("PRAGMA mmap_size").fetchone()[0]

    # Set read-only connection pragmas (does NOT modify the file)
    bm25.db.execute("PRAGMA mmap_size=4294967296")
    bm25.db.execute("PRAGMA cache_size=-524288")  # 512 MiB
    bm25.db.execute("PRAGMA temp_store=MEMORY")

    q = "standard of review reasonableness procedural fairness judicial review"
    t0 = time.perf_counter()
    res1 = bm25.search(q, "passage", limit=4096, exclude_case="055641.txt")
    t1 = time.perf_counter()
    res2 = bm25.search(q, "passage", limit=4096, exclude_case="055641.txt")
    t2 = time.perf_counter()

    # Check open_context timing on small case and 055641.txt (1140 passages)
    pr = PassageReader(ROOT, "pipeline_v2/artifacts/m2_passages_20261106_v1")
    nr = NavigationReader(ROOT, "pipeline_v2/artifacts/m2_navigation_20261106_v3")

    small_row = bm25.db.execute(
        "SELECT id, case_id FROM documents WHERE kind='passage' AND case_id='031881.txt' LIMIT 1"
    ).fetchone()
    t_p0 = time.perf_counter()
    opened_small = pr.open_context(small_row[1], small_row[0])
    t_p1 = time.perf_counter()

    large_row = bm25.db.execute(
        "SELECT id, metadata FROM documents WHERE kind='passage' AND case_id='055641.txt' LIMIT 1"
    ).fetchone()
    large_meta = json.loads(large_row[1])
    t_p2 = time.perf_counter()
    opened_large = pr.open_context("055641.txt", large_row[0])
    t_p3 = time.perf_counter()

    t_n0 = time.perf_counter()
    opened_nav = nr.open_context("055641.txt", large_meta["parent_handle"])
    t_n1 = time.perf_counter()

    # Also check max parent byte span and max open_context byte span across all 7708 cases in m2_navigation!
    max_parent_bytes = 0
    max_parent_case = None
    parents_over_64k = 0
    windows_over_64k = 0
    max_window_bytes = 0
    max_window_info = None
    t_scan0 = time.perf_counter()
    nav_dir = ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v3/sources"
    for p in sorted(nav_dir.glob("*.json")):
        rec = json.loads(p.read_bytes())
        rows_by_h = {r["handle"]: r for r in rec["navigation"]}
        for r in rec["navigation"]:
            plen = r["span_bytes"][1] - r["span_bytes"][0]
            if plen > 65536:
                parents_over_64k += 1
            if plen > max_parent_bytes:
                max_parent_bytes = plen
                max_parent_case = (rec["case_id"], r["handle"], plen)
            exp = r["reading_expansion"]
            spans = [
                rows_by_h[exp[k]]["span_bytes"]
                for k in ("previous_ref", "parent_ref", "next_ref")
                if exp[k] is not None
            ]
            wlen = max(s[1] for s in spans) - min(s[0] for s in spans)
            if wlen > 65536:
                windows_over_64k += 1
            if wlen > max_window_bytes:
                max_window_bytes = wlen
                max_window_info = (rec["case_id"], r["handle"], wlen)
    t_scan1 = time.perf_counter()

    out = {
        "sqlite_default_cache_size": default_cache,
        "sqlite_default_mmap_size": default_mmap,
        "bm25_mmap_run1_seconds": round(t1 - t0, 4),
        "bm25_mmap_run2_seconds": round(t2 - t1, 4),
        "open_context_latency": {
            "PassageReader_small_case_031881_2_passages_seconds": round(t_p1 - t_p0, 4),
            "PassageReader_large_case_055641_1140_passages_seconds": round(t_p3 - t_p2, 4),
            "NavigationReader_large_case_055641_seconds": round(t_n1 - t_n0, 4),
            "large_case_first_parent_handle": large_meta["parent_handle"],
        },
        "m2_corpus_context_size_distribution": {
            "scan_seconds": round(t_scan1 - t_scan0, 4),
            "parents_over_64KiB": parents_over_64k,
            "max_parent_bytes": max_parent_case,
            "context_windows_over_64KiB": windows_over_64k,
            "max_context_window_bytes": max_window_info,
        },
    }
    bm25.close()
    (Path(__file__).parent / "probe_mmap_and_open_results.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
