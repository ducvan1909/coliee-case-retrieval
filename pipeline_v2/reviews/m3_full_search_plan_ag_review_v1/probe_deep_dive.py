"""Deep-dive read-only empirical probe for M3 full search plan review."""
import json
import math
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
import numpy as np
import requests

from pipeline_v2.optimization_v2.index import PersistentBM25, analyze
from pipeline_v2.full_corpus.storage import ReadonlyCache
from pipeline_v2.passages import PassageReader
from pipeline_v2.navigation import NavigationReader

ROOT = Path("E:/Git/coliee-case-retrieval")
RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
FP = "9105955758bda2eba37350535866f9b217e1b9650b1a3f081496a7c4a9965c49"
COLLECTION = "coliee_m3_full_ef2f4d6950a5b9fd"


def main():
    out = {}
    bm25 = PersistentBM25(RUN_DIR / "lexical.sqlite3", readonly=True)
    q = "standard of review reasonableness procedural fairness judicial review"

    # 1. Measure warm PersistentBM25.search (with JOIN documents)
    t0 = time.perf_counter()
    res_join = bm25.search(q, "passage", limit=4096, exclude_case="055641.txt")
    t1 = time.perf_counter()
    out["bm25_warm_join_seconds"] = round(t1 - t0, 4)

    # Measure loading (id -> length) once and querying postings without JOIN documents
    t_load0 = time.perf_counter()
    lengths = dict(
        bm25.db.execute("SELECT id, length FROM documents WHERE kind='passage'").fetchall()
    )
    t_load1 = time.perf_counter()
    out["preload_passage_lengths_seconds"] = round(t_load1 - t_load0, 4)
    out["preload_passage_lengths_count"] = len(lengths)

    t_nojoin0 = time.perf_counter()
    n, avg, k1, b = bm25.db.execute(
        "SELECT n,avg,k1,b FROM stats WHERE kind='passage'"
    ).fetchone()
    scores = defaultdict(float)
    excl_prefix = "055641:"
    for term in sorted(set(analyze(q))):
        row = bm25.db.execute(
            "SELECT df FROM terms WHERE kind='passage' AND term=?", (term,)
        ).fetchone()
        if row is None:
            continue
        idf = math.log(1 + (n - row[0] + 0.5) / (row[0] + 0.5))
        for ident, tf in bm25.db.execute(
            "SELECT id, tf FROM postings WHERE kind='passage' AND term=?", (term,)
        ):
            if ident.startswith(excl_prefix):
                continue
            length = lengths[ident]
            scores[ident] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (avg or 1)))
    ids_nojoin = sorted(scores, key=lambda ident: (-scores[ident], ident))[:4096]
    t_nojoin1 = time.perf_counter()
    out["bm25_nojoin_seconds"] = round(t_nojoin1 - t_nojoin0, 4)
    out["bm25_join_vs_nojoin_exact_match"] = [r["passage_id"] for r in res_join] == ids_nojoin
    out["bm25_total_positive_passages"] = len(scores)
    out["bm25_total_positive_unique_cases"] = len({i.split(":", 1)[0] for i in scores})
    print("1. BM25 comparison:", json.dumps(out, indent=2), flush=True)

    # 2. Test Qdrant on a realistic 300-token passage vector (batch 5000, ordinal 0)
    row = bm25.db.execute(
        "SELECT passage_id FROM schedule WHERE batch=5000 ORDER BY ordinal"
    ).fetchall()
    ids_5000 = [r[0] for r in row]
    docs_5000 = bm25.get_many("passage", ids_5000)
    hashes_5000 = [d["exact_input_sha256"] for d in docs_5000]
    cache = ReadonlyCache(RUN_DIR, FP, 2560)
    vecs_5000 = cache.get_batch(ids_5000, hashes_5000)
    qvec = vecs_5000[0].tolist()
    qcase = docs_5000[0]["case_id"]

    realistic_qdrant = []
    exact_sets = {}
    for exact in [True, False]:
        for lim in [256, 1024, 4096]:
            ts = time.perf_counter()
            r = requests.post(
                f"http://127.0.0.1:6333/collections/{COLLECTION}/points/query?timeout=120",
                json={
                    "query": qvec,
                    "limit": lim,
                    "filter": {
                        "must": [{"key": "embedding_fingerprint", "match": {"value": FP}}],
                        "must_not": [{"key": "case_id", "match": {"value": qcase}}],
                    },
                    "with_payload": True,
                    "params": {"exact": exact},
                },
                timeout=120,
            )
            te = time.perf_counter()
            pts = r.json()["result"]["points"]
            hit_ids = [p["payload"]["passage_id"] for p in pts]
            uc_list = []
            seen_c = set()
            for p in pts:
                cid = p["payload"]["case_id"]
                if cid not in seen_c:
                    seen_c.add(cid)
                    uc_list.append(cid)
            placeholders = ",".join("?" for _ in hit_ids)
            batches_touched = {
                b[0]
                for b in bm25.db.execute(
                    f"SELECT DISTINCT batch FROM schedule WHERE passage_id IN ({placeholders})",
                    hit_ids,
                )
            }
            # Also how many shards touched if we only verify top-1 best hit for the top 100 unique cases?
            top100_best_ids = []
            seen_c2 = set()
            for p in pts:
                cid = p["payload"]["case_id"]
                if cid not in seen_c2:
                    seen_c2.add(cid)
                    top100_best_ids.append(p["payload"]["passage_id"])
                    if len(top100_best_ids) == 100:
                        break
            ph100 = ",".join("?" for _ in top100_best_ids)
            batches_100 = {
                b[0]
                for b in bm25.db.execute(
                    f"SELECT DISTINCT batch FROM schedule WHERE passage_id IN ({ph100})",
                    top100_best_ids,
                )
            }
            exact_sets[(exact, lim)] = (hit_ids, uc_list)
            realistic_qdrant.append(
                {
                    "exact": exact,
                    "limit": lim,
                    "seconds": round(te - ts, 4),
                    "returned_points": len(pts),
                    "unique_cases": len(uc_list),
                    "all_hits_shards_touched": len(batches_touched),
                    "top100_case_best_hits_shards_touched": len(batches_100),
                }
            )
    # Compare approx vs exact recall on top-100 unique cases
    exact_top100_cases = set(exact_sets[(True, 256)][1][:100])
    approx_top100_cases = set(exact_sets[(False, 256)][1][:100])
    out["realistic_qdrant_batch5000"] = realistic_qdrant
    out["approx_vs_exact_top100_case_overlap_at_256"] = len(
        exact_top100_cases & approx_top100_cases
    )
    print("2. Realistic Qdrant:", json.dumps(realistic_qdrant, indent=2), flush=True)

    # 3. Measure PassageReader.open_context vs NavigationReader.open_context vs direct artifact read
    pr = PassageReader(ROOT, "pipeline_v2/artifacts/m2_passages_20261106_v1")
    nr = NavigationReader(ROOT, "pipeline_v2/artifacts/m2_navigation_20261106_v3")

    # Small case vs longest case (055641.txt, 1140 passages)
    small_pid = docs_5000[0]["passage_id"]
    small_cid = docs_5000[0]["case_id"]
    t_p0 = time.perf_counter()
    pr.open_context(small_cid, small_pid)
    t_p1 = time.perf_counter()

    large_row = bm25.db.execute(
        "SELECT id FROM documents WHERE kind='passage' AND case_id='055641.txt' LIMIT 1"
    ).fetchone()
    large_pid = large_row[0]
    t_p2 = time.perf_counter()
    pr.open_context("055641.txt", large_pid)
    t_p3 = time.perf_counter()

    t_n0 = time.perf_counter()
    nr.open_context("055641.txt", "p000001")
    t_n1 = time.perf_counter()

    out["open_context_latency"] = {
        "PassageReader_open_small_case_seconds": round(t_p1 - t_p0, 4),
        "PassageReader_open_055641_1140_passages_seconds": round(t_p3 - t_p2, 4),
        "NavigationReader_open_055641_seconds": round(t_n1 - t_n0, 4),
    }
    print("3. Open context latency:", json.dumps(out["open_context_latency"], indent=2), flush=True)

    bm25.close()
    (Path(__file__).parent / "probe_deep_dive_results.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print("DEEP DIVE DONE", flush=True)


if __name__ == "__main__":
    main()
