"""Read-only empirical probe of M3 full search plan assumptions."""
import json
import sqlite3
import time
from pathlib import Path
import numpy as np
import requests

from pipeline_v2.optimization_v2.index import PersistentBM25
from pipeline_v2.full_corpus.storage import ReadonlyCache

ROOT = Path("E:/Git/coliee-case-retrieval")
RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
FP = "9105955758bda2eba37350535866f9b217e1b9650b1a3f081496a7c4a9965c49"
COLLECTION = "coliee_m3_full_ef2f4d6950a5b9fd"


def main():
    results = {}
    bm25 = PersistentBM25(RUN_DIR / "lexical.sqlite3", readonly=True)

    # 1. Check query plans in SQLite
    plan_q = bm25.db.execute(
        "EXPLAIN QUERY PLAN SELECT batch FROM schedule WHERE passage_id=?",
        ("000001:0000",),
    ).fetchall()
    results["schedule_lookup_plan"] = [list(r) for r in plan_q]

    plan_postings = bm25.db.execute(
        "EXPLAIN QUERY PLAN SELECT p.id,p.tf,d.length FROM postings p JOIN documents d ON d.kind=p.kind AND d.id=p.id WHERE p.kind=? AND p.term=? AND (? IS NULL OR d.case_id!=?)",
        ("passage", "reasonableness", "000001.txt", "000001.txt"),
    ).fetchall()
    results["postings_lookup_plan"] = [list(r) for r in plan_postings]
    print("1. Query plans:", json.dumps(results), flush=True)

    # 2. Load 1 cached vector from batch 0 (read-only) and test Qdrant FIRST
    row = bm25.db.execute(
        "SELECT passage_id FROM schedule WHERE batch=0 ORDER BY ordinal"
    ).fetchall()
    ids = [r[0] for r in row]
    docs = bm25.get_many("passage", ids)
    hashes = [d["exact_input_sha256"] for d in docs]
    cache = ReadonlyCache(RUN_DIR, FP, 2560)
    t_c0 = time.perf_counter()
    vecs = cache.get_batch(ids, hashes)
    t_c1 = time.perf_counter()
    results["readonly_cache_single_shard_ms"] = round((t_c1 - t_c0) * 1000, 3)
    print("2. Shard load ms:", results["readonly_cache_single_shard_ms"], flush=True)

    vec0 = vecs[0].tolist()
    qdrant_bench = []
    for exact in [False, True]:
        for lim in [20, 256, 1024, 4096]:
            ts = time.perf_counter()
            r = requests.post(
                f"http://127.0.0.1:6333/collections/{COLLECTION}/points/query",
                json={
                    "query": vec0,
                    "limit": lim,
                    "filter": {
                        "must": [
                            {"key": "embedding_fingerprint", "match": {"value": FP}}
                        ],
                        "must_not": [
                            {"key": "case_id", "match": {"value": "055641.txt"}}
                        ],
                    },
                    "with_payload": True,
                    "params": {"exact": exact},
                },
                timeout=120,
            )
            te = time.perf_counter()
            body = r.json()
            if "result" not in body:
                entry = {
                    "exact": exact,
                    "limit": lim,
                    "seconds": round(te - ts, 4),
                    "status_code": r.status_code,
                    "error_body": body,
                }
                qdrant_bench.append(entry)
                print(f"Qdrant ERROR exact={exact} limit={lim}: {entry}", flush=True)
                continue
            pts = body["result"]["points"]
            uc = len({p["payload"]["case_id"] for p in pts})
            hit_ids = [p["payload"]["passage_id"] for p in pts]
            placeholders = ",".join("?" for _ in hit_ids)
            batches_touched = {
                b[0]
                for b in bm25.db.execute(
                    f"SELECT DISTINCT batch FROM schedule WHERE passage_id IN ({placeholders})",
                    hit_ids,
                )
            }
            # Also check if there are tied scores in pts!
            scores_list = [p["score"] for p in pts]
            ties_count = len(scores_list) - len(set(scores_list))
            entry = {
                "exact": exact,
                "limit": lim,
                "seconds": round(te - ts, 4),
                "returned_points": len(pts),
                "unique_cases": uc,
                "distinct_shards_touched": len(batches_touched),
                "exact_score_ties_in_top_k": ties_count,
                "top5_scores": scores_list[:5],
            }
            qdrant_bench.append(entry)
            print("Qdrant bench:", entry, flush=True)
    results["qdrant_benchmark"] = qdrant_bench

    # 3. Benchmark BM25 case and passage search
    q = "standard of review reasonableness procedural fairness judicial review"
    t0 = time.perf_counter()
    res_case = bm25.search(q, "case", limit=100, exclude_case="055641.txt")
    t1 = time.perf_counter()
    print(f"BM25 case done in {t1-t0:.3f}s", flush=True)
    res_pass_4096 = bm25.search(q, "passage", limit=4096, exclude_case="055641.txt")
    t2 = time.perf_counter()
    print(f"BM25 passage done in {t2-t1:.3f}s", flush=True)

    results["bm25_benchmark"] = {
        "case_limit_100_seconds": round(t1 - t0, 4),
        "case_hits": len(res_case),
        "passage_limit_4096_seconds": round(t2 - t1, 4),
        "passage_256_unique_cases": len({r["case_id"] for r in res_pass_4096[:256]}),
        "passage_1024_unique_cases": len({r["case_id"] for r in res_pass_4096[:1024]}),
        "passage_4096_unique_cases": len({r["case_id"] for r in res_pass_4096}),
    }

    bm25.close()
    out_path = Path(__file__).parent / "probe_results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
