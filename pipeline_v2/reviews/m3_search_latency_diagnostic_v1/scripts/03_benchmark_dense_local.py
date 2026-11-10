"""Step 5 & 6 (Dense channel): Fair local Qdrant exact=True benchmark on 3 locked cached vectors."""
from __future__ import annotations

from collections import OrderedDict
import json
import random
import shutil
import sqlite3
import sys
import time
from pathlib import Path
import numpy as np
import requests

ROOT = Path("E:/Git/coliee-case-retrieval")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2.full_corpus.storage import ReadonlyCache
from pipeline_v2.retrieval.cache import validate_vectors

OUT_DIR = ROOT / "pipeline_v2/reviews/m3_search_latency_diagnostic_v1"
RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
FP = "9105955758bda2eba37350535866f9b217e1b9650b1a3f081496a7c4a9965c49"
COLLECTION = "coliee_m3_full_ef2f4d6950a5b9fd"
QDRANT_URL = "http://127.0.0.1:6333"
SERVER_TIMEOUT_SECONDS = 120
HTTP_CONNECT_TIMEOUT_SECONDS = 10.0
HTTP_READ_TIMEOUT_SECONDS = 130.0


def load_locked_vectors(workload: dict, conn: sqlite3.Connection) -> list[dict]:
    cache = ReadonlyCache(RUN_DIR, FP, 2560)
    loaded = []
    for vspec in workload["diagnostic_dense_vectors"]:
        bnum = vspec["schedule_batch"]
        rows = conn.execute(
            "SELECT passage_id FROM schedule WHERE batch=? ORDER BY ordinal", (bnum,)
        ).fetchall()
        batch_ids = [r[0] for r in rows]
        ph = ",".join("?" for _ in batch_ids)
        meta_map = {
            ident: json.loads(m)
            for ident, m in conn.execute(
                f"SELECT id, metadata FROM documents WHERE kind='passage' AND id IN ({ph})",
                batch_ids,
            )
        }
        batch_hashes = [meta_map[i]["exact_input_sha256"] for i in batch_ids]
        t0 = time.perf_counter()
        vecs = cache.get_batch(batch_ids, batch_hashes)
        t1 = time.perf_counter()
        vec = vecs[vspec["batch_row_index"]]
        assert batch_ids[vspec["batch_row_index"]] == vspec["passage_id"]
        loaded.append(
            {
                **vspec,
                "shard_load_seconds": round(t1 - t0, 6),
                "vector_list": vec.astype(np.float32).tolist(),
                "vector_np": vec.astype(np.float32),
            }
        )
    return loaded


def run_single_qdrant_query(
    session: requests.Session,
    conn: sqlite3.Connection,
    v_item: dict,
    limit: int,
    with_payload: bool = True,
    with_vector: bool = False,
) -> dict:
    url = f"{QDRANT_URL}/collections/{COLLECTION}/points/query?timeout={SERVER_TIMEOUT_SECONDS}"
    body = {
        "query": v_item["vector_list"],
        "limit": limit,
        "filter": {
            "must": [{"key": "embedding_fingerprint", "match": {"value": FP}}],
            "must_not": [
                {"key": "case_id", "match": {"value": v_item["query_case_excluded"]}}
            ],
        },
        "with_payload": with_payload,
        "with_vector": with_vector,
        "params": {"exact": True},
    }
    t0 = time.perf_counter()
    try:
        resp = session.post(
            url,
            json=body,
            timeout=(HTTP_CONNECT_TIMEOUT_SECONDS, HTTP_READ_TIMEOUT_SECONDS),
        )
        t1 = time.perf_counter()
    except Exception as exc:
        t1 = time.perf_counter()
        return {
            "vector_id": v_item["vector_id"],
            "passage_id": v_item["passage_id"],
            "exclude_case": v_item["query_case_excluded"],
            "exact": True,
            "limit": limit,
            "with_payload": with_payload,
            "with_vector": with_vector,
            "server_timeout_seconds": SERVER_TIMEOUT_SECONDS,
            "http_timeout_seconds": [
                HTTP_CONNECT_TIMEOUT_SECONDS,
                HTTP_READ_TIMEOUT_SECONDS,
            ],
            "status": "exception",
            "error": repr(exc),
            "client_walltime_seconds": round(t1 - t0, 6),
        }

    try:
        payload_json = resp.json()
    except Exception:
        payload_json = {"raw_text": resp.text[:500]}

    if resp.status_code != 200 or payload_json.get("status") != "ok":
        return {
            "vector_id": v_item["vector_id"],
            "passage_id": v_item["passage_id"],
            "exclude_case": v_item["query_case_excluded"],
            "exact": True,
            "limit": limit,
            "with_payload": with_payload,
            "with_vector": with_vector,
            "server_timeout_seconds": SERVER_TIMEOUT_SECONDS,
            "http_timeout_seconds": [
                HTTP_CONNECT_TIMEOUT_SECONDS,
                HTTP_READ_TIMEOUT_SECONDS,
            ],
            "status": "http_error",
            "http_status_code": resp.status_code,
            "error_body": payload_json,
            "client_walltime_seconds": round(t1 - t0, 6),
        }

    pts = payload_json["result"]["points"]
    server_time = payload_json.get("time")

    # Verify exclusion and fingerprint on all returned points
    hit_ids = [p["payload"]["passage_id"] for p in pts]
    bad_excl = any(
        p["payload"].get("case_id") == v_item["query_case_excluded"] for p in pts
    )
    bad_fp = any(p["payload"].get("embedding_fingerprint") != FP for p in pts)
    assert not bad_excl, "Query case exclusion violated in Qdrant response"
    assert not bad_fp, "Fingerprint filter violated in Qdrant response"

    seen_cases = set()
    unique_cases_ordered = []
    top100_best_hit_ids = []
    for p in pts:
        cid = p["payload"]["case_id"]
        if cid not in seen_cases:
            seen_cases.add(cid)
            unique_cases_ordered.append(cid)
            if len(top100_best_hit_ids) < 100:
                top100_best_hit_ids.append(p["payload"]["passage_id"])

    scores = [float(p["score"]) for p in pts]
    exact_ties = len(scores) - len(set(scores))

    # Count distinct shards touched for all hits vs top-100 unique-case best hits
    all_shards = set()
    for offset in range(0, len(hit_ids), 512):
        chunk = hit_ids[offset : offset + 512]
        ph = ",".join("?" for _ in chunk)
        all_shards.update(
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT batch FROM schedule WHERE passage_id IN ({ph})", chunk
            )
        )

    ph100 = ",".join("?" for _ in top100_best_hit_ids)
    top100_shards = {
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT batch FROM schedule WHERE passage_id IN ({ph100})",
            top100_best_hit_ids,
        )
    }

    return {
        "vector_id": v_item["vector_id"],
        "passage_id": v_item["passage_id"],
        "exclude_case": v_item["query_case_excluded"],
        "exact": True,
        "limit": limit,
        "with_payload": with_payload,
        "with_vector": with_vector,
        "server_timeout_seconds": SERVER_TIMEOUT_SECONDS,
        "http_timeout_seconds": [
            HTTP_CONNECT_TIMEOUT_SECONDS,
            HTTP_READ_TIMEOUT_SECONDS,
        ],
        "status": "ok",
        "http_status_code": resp.status_code,
        "client_walltime_seconds": round(t1 - t0, 6),
        "qdrant_server_reported_seconds": round(float(server_time), 6)
        if server_time is not None
        else None,
        "http_and_deserialization_overhead_seconds": round(
            (t1 - t0) - float(server_time), 6
        )
        if server_time is not None
        else None,
        "returned_points": len(pts),
        "unique_cases": len(unique_cases_ordered),
        "all_hits_distinct_shards": len(all_shards),
        "top100_unique_cases_distinct_shards": len(top100_shards),
        "exact_score_ties_count": exact_ties,
        "top5_passage_ids": hit_ids[:5],
        "top5_scores": [round(s, 7) for s in scores[:5]],
        "top100_best_hit_ids": top100_best_hit_ids,
        "top100_best_hit_scores": [
            float(p["score"])
            for p in pts
            if p["payload"]["passage_id"] in set(top100_best_hit_ids)
        ][:100],
    }


def measure_real_shard_verification(
    conn: sqlite3.Connection, v_item: dict, top100_ids: list[str]
) -> dict:
    """Empirically measure ReadonlyCache verification of top-100 unique-case leads (not extrapolated)."""
    cache = ReadonlyCache(RUN_DIR, FP, 2560)
    qvec = v_item["vector_np"]

    t0 = time.perf_counter()
    ph = ",".join("?" for _ in top100_ids)
    batch_rows = conn.execute(
        f"SELECT passage_id, batch FROM schedule WHERE passage_id IN ({ph})",
        top100_ids,
    ).fetchall()
    pid_to_batch = {r[0]: int(r[1]) for r in batch_rows}
    needed_batches = sorted(set(pid_to_batch.values()))

    shard_cache = {}
    for bnum in needed_batches:
        s_rows = conn.execute(
            "SELECT passage_id FROM schedule WHERE batch=? ORDER BY ordinal", (bnum,)
        ).fetchall()
        b_ids = [r[0] for r in s_rows]
        ph_b = ",".join("?" for _ in b_ids)
        m_map = {
            ident: json.loads(m)
            for ident, m in conn.execute(
                f"SELECT id, metadata FROM documents WHERE kind='passage' AND id IN ({ph_b})",
                b_ids,
            )
        }
        b_hashes = [m_map[i]["exact_input_sha256"] for i in b_ids]
        vecs = cache.get_batch(b_ids, b_hashes)
        shard_cache[bnum] = {pid: vecs[idx] for idx, pid in enumerate(b_ids)}

    max_score_diff = 0.0
    for pid in top100_ids:
        v = shard_cache[pid_to_batch[pid]][pid]
        cos = float(np.dot(v, qvec))
        assert np.isfinite(cos)
    t1 = time.perf_counter()

    # Second pass using already-populated in-memory LRU shard_cache
    t2 = time.perf_counter()
    for pid in top100_ids:
        v = shard_cache[pid_to_batch[pid]][pid]
        cos = float(np.dot(v, qvec))
        assert np.isfinite(cos)
    t3 = time.perf_counter()

    return {
        "vector_id": v_item["vector_id"],
        "verified_leads_count": len(top100_ids),
        "distinct_shards_loaded": len(needed_batches),
        "first_pass_disk_and_sha256_seconds": round(t1 - t0, 6),
        "warm_lru_cache_pass_seconds": round(t3 - t2, 6),
    }


def main() -> None:
    workload = json.loads((OUT_DIR / "workload_manifest.json").read_bytes())
    uri = f"file:{(RUN_DIR / 'lexical.sqlite3').resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")

    vectors = load_locked_vectors(workload, conn)
    session = requests.Session()

    # Check Qdrant server info and collection info before running
    srv_resp = session.get(f"{QDRANT_URL}/", timeout=10).json()
    col_resp = session.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=10).json()
    cnt_resp = session.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/count",
        json={"exact": True},
        timeout=30,
    ).json()

    runs = []
    # 1. First-observed pass (in fixed order V01, V02, V03; limits 256, 4096)
    for v_item in vectors:
        for lim in (256, 4096):
            rec = run_single_qdrant_query(session, conn, v_item, lim)
            rec["pass_kind"] = "first_observed"
            rec["repeat_index"] = 0
            rec["run_sequence_number"] = len(runs) + 1
            runs.append(rec)
            print(
                f"[Dense first_observed] {v_item['vector_id']} limit={lim}: "
                f"status={rec['status']} client={rec['client_walltime_seconds']}s "
                f"server={rec.get('qdrant_server_reported_seconds')}s",
                flush=True,
            )

    # 2. Three warm repeats with deterministic crossover order of (vector, limit) pairs
    rng = random.Random(20261109)
    base_pairs = [(v_idx, lim) for v_idx in range(len(vectors)) for lim in (256, 4096)]
    crossover_schedules = []
    for rep in range(1, 4):
        pairs = list(base_pairs)
        rng.shuffle(pairs)
        crossover_schedules.append(
            [{"vector_id": vectors[vi]["vector_id"], "limit": lim} for vi, lim in pairs]
        )
        for vi, lim in pairs:
            v_item = vectors[vi]
            rec = run_single_qdrant_query(session, conn, v_item, lim)
            rec["pass_kind"] = "warm_repeat"
            rec["repeat_index"] = rep
            rec["run_sequence_number"] = len(runs) + 1
            runs.append(rec)
            print(
                f"[Dense warm_repeat {rep}] {v_item['vector_id']} limit={lim}: "
                f"status={rec['status']} client={rec['client_walltime_seconds']}s "
                f"server={rec.get('qdrant_server_reported_seconds')}s",
                flush=True,
            )

    # 3. Also measure real shard verification for top-100 unique-case leads on each vector
    shard_verifications = []
    for v_item in vectors:
        matching_runs = [
            r
            for r in runs
            if r["vector_id"] == v_item["vector_id"]
            and r["limit"] == 256
            and r["status"] == "ok"
        ]
        if matching_runs:
            top100_ids = matching_runs[0]["top100_best_hit_ids"]
            sv = measure_real_shard_verification(conn, v_item, top100_ids)
            shard_verifications.append(sv)

    # Remove bulky top100_best_hit_ids/scores from individual run logs after verification check
    # Check deterministic ID stability across repeats for each (vector_id, limit)
    stability_checks = []
    for v_item in vectors:
        for lim in (256, 4096):
            sub = [
                r
                for r in runs
                if r["vector_id"] == v_item["vector_id"]
                and r["limit"] == lim
                and r["status"] == "ok"
            ]
            id_lists = [r["top100_best_hit_ids"] for r in sub]
            all_identical = all(x == id_lists[0] for x in id_lists[1:]) if id_lists else False
            stability_checks.append(
                {
                    "vector_id": v_item["vector_id"],
                    "limit": lim,
                    "successful_runs": len(sub),
                    "top100_unique_case_lead_ids_identical_across_all_runs": all_identical,
                }
            )
            for r in sub:
                r.pop("top100_best_hit_ids", None)
                r.pop("top100_best_hit_scores", None)

    # Compute summary stats (first_observed vs warm median/min/max)
    summary_by_vector_and_limit = []
    for v_item in vectors:
        for lim in (256, 4096):
            first = next(
                r
                for r in runs
                if r["vector_id"] == v_item["vector_id"]
                and r["limit"] == lim
                and r["pass_kind"] == "first_observed"
            )
            warm = [
                r
                for r in runs
                if r["vector_id"] == v_item["vector_id"]
                and r["limit"] == lim
                and r["pass_kind"] == "warm_repeat"
                and r["status"] == "ok"
            ]
            w_times = sorted(r["client_walltime_seconds"] for r in warm)
            s_times = sorted(r["qdrant_server_reported_seconds"] for r in warm)
            summary_by_vector_and_limit.append(
                {
                    "vector_id": v_item["vector_id"],
                    "passage_id": v_item["passage_id"],
                    "exclude_case": v_item["query_case_excluded"],
                    "limit": lim,
                    "first_observed_status": first["status"],
                    "first_observed_client_seconds": first["client_walltime_seconds"],
                    "first_observed_server_seconds": first.get(
                        "qdrant_server_reported_seconds"
                    ),
                    "warm_repeats_count": len(w_times),
                    "warm_client_median_seconds": w_times[len(w_times) // 2]
                    if w_times
                    else None,
                    "warm_client_min_seconds": min(w_times) if w_times else None,
                    "warm_client_max_seconds": max(w_times) if w_times else None,
                    "warm_server_median_seconds": s_times[len(s_times) // 2]
                    if s_times
                    else None,
                    "warm_server_min_seconds": min(s_times) if s_times else None,
                    "warm_server_max_seconds": max(s_times) if s_times else None,
                    "returned_points": first.get("returned_points"),
                    "unique_cases": first.get("unique_cases"),
                    "all_hits_distinct_shards": first.get("all_hits_distinct_shards"),
                    "top100_unique_cases_distinct_shards": first.get(
                        "top100_unique_cases_distinct_shards"
                    ),
                    "exact_score_ties_count": first.get("exact_score_ties_count"),
                }
            )

    conn.close()
    session.close()

    output = {
        "schema_version": "m3-dense-local-diagnostic-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "qdrant_server": {
            "title": srv_resp.get("title"),
            "version": srv_resp.get("version"),
            "collection": COLLECTION,
            "exact_point_count": cnt_resp.get("result", {}).get("count"),
            "collection_vector_config": col_resp.get("result", {})
            .get("config", {})
            .get("params", {})
            .get("vectors"),
        },
        "timeout_configuration": {
            "qdrant_url_query_param_timeout_seconds": SERVER_TIMEOUT_SECONDS,
            "requests_http_connect_timeout_seconds": HTTP_CONNECT_TIMEOUT_SECONDS,
            "requests_http_read_timeout_seconds": HTTP_READ_TIMEOUT_SECONDS,
            "distinction": "URL ?timeout=120 controls Qdrant's internal Rust search operation timeout (default 60s if omitted); requests timeout=(10, 130) controls Python client socket connect/read timeout.",
        },
        "crossover_schedules": crossover_schedules,
        "summary_by_vector_and_limit": summary_by_vector_and_limit,
        "stability_checks": stability_checks,
        "real_shard_verification_measurements": shard_verifications,
        "all_runs": runs,
    }
    (OUT_DIR / "dense_measurements.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("DENSE BENCHMARK COMPLETE")


if __name__ == "__main__":
    main()
