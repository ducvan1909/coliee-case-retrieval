"""Independent post-run verification of the real 1,024-passage L4 pilot execution."""
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import urllib.request
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2.retrieval.corpus import Corpus

RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1"
REVIEW_DIR = Path(__file__).resolve().parent
NAMESPACE = uuid.UUID("a8979bd6-50a2-41f3-87d2-e2744801d753")
EXPECTED_FP = "d945329fa49e2f4b4f83d530df03fb4897babd5345562cbeaebd3b21499649bf"
EXPECTED_M2_SEAL = "0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def qdrant_request(method: str, path: str, body=None):
    url = f"http://127.0.0.1:6333{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("status") != "ok":
        raise RuntimeError(f"Qdrant non-ok status on {path}: {payload}")
    return payload["result"]


def scroll_all(collection: str):
    points = []
    offset = None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": True}
        if offset is not None:
            body["offset"] = offset
        res = qdrant_request("POST", f"/collections/{collection}/points/scroll", body)
        points.extend(res["points"])
        offset = res.get("next_page_offset")
        if offset is None:
            return points


def main():
    manifest = json.loads((RUN_DIR / "pilot_manifest.json").read_bytes())
    profile = manifest["profile"]
    passage_ids = manifest["passage_ids"]
    input_hashes = manifest["input_hashes"]
    collection = manifest["collection"]
    restore_collection = collection + "_restore"

    # 1. Verify all 64 vector cache shards directly from disk
    batch_size = profile["batch_size"]
    shards_checked = 0
    all_vectors = []
    norm_deviations = []
    for start in range(0, len(passage_ids), batch_size):
        b_ids = passage_ids[start : start + batch_size]
        b_hashes = input_hashes[start : start + batch_size]
        shard_key = sha256_bytes(canonical_bytes([EXPECTED_FP, b_ids]))
        meta_path = RUN_DIR / "vectors" / f"{shard_key}.json"
        npz_path = RUN_DIR / "vectors" / f"{shard_key}.npz"
        assert meta_path.is_file() and npz_path.is_file(), f"Missing shard at {start}"
        meta = json.loads(meta_path.read_bytes())
        npz_raw = npz_path.read_bytes()
        assert meta == {
            "fingerprint": EXPECTED_FP,
            "ids": b_ids,
            "input_hashes": b_hashes,
            "array_sha256": sha256_bytes(npz_raw),
        }, f"Shard metadata mismatch at {start}"
        with np.load(npz_path, allow_pickle=False) as z:
            assert z["ids"].tolist() == b_ids
            assert z["input_hashes"].tolist() == b_hashes
            assert str(z["fingerprint"]) == EXPECTED_FP
            vecs = np.asarray(z["vectors"], dtype=np.float32)
            assert vecs.shape == (len(b_ids), 2560)
            assert np.isfinite(vecs).all()
            norms = np.linalg.norm(vecs, axis=1)
            devs = np.abs(norms - 1.0)
            assert float(devs.max()) <= 0.002
            norm_deviations.extend(devs.tolist())
            all_vectors.append(vecs)
        shards_checked += 1

    vectors_matrix = np.concatenate(all_vectors, axis=0)
    assert vectors_matrix.shape == (1024, 2560)

    # 2. Verify ledger.sqlite3 accounting, stop/resume proof, and cold/warm latency
    db = sqlite3.connect(RUN_DIR / "ledger.sqlite3")
    rows = db.execute(
        "SELECT id, batch, phase, started, elapsed, status, requests, tokens, error, receipt FROM attempts ORDER BY id"
    ).fetchall()
    db.close()

    attempts = []
    for r in rows:
        attempts.append({
            "id": r[0],
            "batch": r[1],
            "phase": r[2],
            "started": r[3],
            "elapsed_seconds": r[4],
            "status": r[5],
            "requests": r[6],
            "input_tokens": r[7],
            "error": r[8],
            "receipt": json.loads(r[9]) if r[9] else None,
        })

    doc_batches = [a for a in attempts if a["batch"].startswith("documents-")]
    assert len(doc_batches) == 64, f"Expected 64 document batch requests, got {len(doc_batches)}"
    assert [a["batch"] for a in doc_batches] == [f"documents-{i}" for i in range(64)]
    assert all(a["status"] == "success" and a["error"] is None for a in attempts)

    preflight_attempts = [a for a in attempts if a["batch"].startswith("preflight-")]
    search_attempts = [a for a in attempts if a["batch"] == "search-query"]
    assert len(preflight_attempts) == 6
    assert len(search_attempts) == 3

    preflight_input_tokens = sum(a["input_tokens"] for a in preflight_attempts)
    preflight_padded_tokens = sum(a["receipt"]["padded_tokens"] for a in preflight_attempts)
    doc_input_tokens = sum(a["input_tokens"] for a in doc_batches)
    doc_padded_tokens = sum(a["receipt"]["padded_tokens"] for a in doc_batches)
    search_input_tokens = sum(a["input_tokens"] for a in search_attempts)
    search_padded_tokens = sum(a["receipt"]["padded_tokens"] for a in search_attempts)

    assert preflight_input_tokens == 988
    assert doc_input_tokens == 132843

    # Cold start vs warm batch latency
    batch0 = doc_batches[0]
    warm_doc_batches = doc_batches[1:]
    warm_remote_secs = [a["receipt"]["remote_elapsed_seconds"] for a in warm_doc_batches]
    warm_client_secs = [a["elapsed_seconds"] for a in warm_doc_batches]
    total_doc_remote_secs = sum(a["receipt"]["remote_elapsed_seconds"] for a in doc_batches)

    # 3. Verify Qdrant primary and restored collections directly after container restart
    corpus = Corpus(ROOT, profile["passages_bundle"], EXPECTED_M2_SEAL)
    passages = corpus.selected(passage_ids)

    primary_points = scroll_all(collection)
    restore_points = scroll_all(restore_collection)
    assert len(primary_points) == 1024
    assert len(restore_points) == 1024

    prim_by_id = {p["id"]: p for p in primary_points}
    rest_by_id = {p["id"]: p for p in restore_points}
    assert set(prim_by_id) == set(rest_by_id)

    max_prim_cache_diff = 0.0
    max_rest_prim_diff = 0.0
    for idx, p in enumerate(passages):
        pid = str(uuid.uuid5(NAMESPACE, f"{EXPECTED_FP}:{p['passage_id']}"))
        assert pid in prim_by_id and pid in rest_by_id
        p_row = prim_by_id[pid]
        r_row = rest_by_id[pid]
        expected_payload = {
            k: p[k]
            for k in (
                "case_id", "passage_id", "source_hash", "exact_input_sha256",
                "span_bytes", "parent_handle", "policy_hash", "tokenizer_fingerprint",
            )
        }
        expected_payload["embedding_fingerprint"] = EXPECTED_FP
        assert p_row["payload"] == expected_payload
        assert r_row["payload"] == expected_payload
        pv = np.asarray(p_row["vector"], dtype=np.float32)
        rv = np.asarray(r_row["vector"], dtype=np.float32)
        cv = vectors_matrix[idx]
        max_prim_cache_diff = max(max_prim_cache_diff, float(np.max(np.abs(pv - cv))))
        max_rest_prim_diff = max(max_rest_prim_diff, float(np.max(np.abs(rv - pv))))

    assert max_prim_cache_diff <= 1e-5
    assert max_rest_prim_diff <= 1e-6

    # 4. Independent exact NumPy reference vs Qdrant dense search across 10 diverse pilot passages
    probe_indices = [0, 17, 128, 256, 384, 512, 640, 768, 896, 1023]
    dense_probes = []
    max_dense_score_diff = 0.0
    for idx in probe_indices:
        q_pas = passages[idx]
        q_vec = vectors_matrix[idx]
        excl = q_pas["case_id"]
        scores = vectors_matrix @ q_vec
        valid = [j for j, pas in enumerate(passages) if pas["case_id"] != excl]
        expected_top = sorted(valid, key=lambda j: (-float(scores[j]), passages[j]["passage_id"]))[:10]
        res = qdrant_request(
            "POST",
            f"/collections/{collection}/points/query",
            {
                "query": q_vec.tolist(),
                "limit": 10,
                "filter": {
                    "must": [{"key": "embedding_fingerprint", "match": {"value": EXPECTED_FP}}],
                    "must_not": [{"key": "case_id", "match": {"value": excl}}],
                },
                "with_payload": True,
                "params": {"exact": True},
            },
        )["points"]
        assert len(res) == 10
        by_pid = {pas["passage_id"]: j for j, pas in enumerate(passages)}
        for hit in res:
            h_pid = hit["payload"]["passage_id"]
            assert hit["payload"]["case_id"] != excl
            exact_score = float(scores[by_pid[h_pid]])
            diff = abs(exact_score - float(hit["score"]))
            max_dense_score_diff = max(max_dense_score_diff, diff)
            assert diff <= profile["numerics"]["search_score_atol"]
        dense_probes.append({
            "probe_index": idx,
            "query_passage_id": q_pas["passage_id"],
            "excluded_case_id": excl,
            "top1_passage_id": res[0]["payload"]["passage_id"],
            "top1_score": float(res[0]["score"]),
            "exact_top1_score": float(scores[expected_top[0]]),
        })

    # 5. Inspect immutable operation receipts for stop/resume, search, verify, literal, open
    op_files = sorted((RUN_DIR / "operations").glob("*.json"))
    ops_summary = []
    search_receipts = []
    for op_path in op_files:
        op_data = json.loads(op_path.read_bytes())
        cmd = op_data["command"]
        res = op_data["result"]
        ops_summary.append({
            "file": op_path.name,
            "command": cmd,
            "status": res.get("status") or res.get("execution_mode") or res.get("scope"),
            "local_elapsed_seconds": res.get("local_elapsed_seconds"),
        })
        if cmd == "search":
            search_receipts.append((op_path.name, res))

    assert len(search_receipts) == 3
    # Verify search 1 vs search 2 (--query-case 079659.txt exclusion) and RRF math
    s1_name, s1 = search_receipts[0]
    s2_name, s2 = search_receipts[1]
    s3_name, s3 = search_receipts[2]
    assert s1["query_case_excluded"] is None
    assert s2["query_case_excluded"] == "079659.txt"
    assert any(h["case_id"] == "079659.txt" for h in s1["channels"]["case_bm25"])
    for ch_name, ch_hits in s2["channels"].items():
        assert all(h["case_id"] != "079659.txt" for h in ch_hits), f"Excluded case leaked in {ch_name}"
    assert all(r["case_id"] != "079659.txt" for r in s2["results"])

    # Verify RRF score calculation and open context on top hits from search receipts
    opened_search_hits = []
    for label, s_res in (("q1_standard_of_review", s1), ("q2_exclude_079659", s2), ("q3_bilingual_negation_citation", s3)):
        for r in s_res["results"]:
            expected_rrf = sum(1.0 / (60 + ch_info["rank"]) for ch_info in r["channels"].values())
            assert abs(r["score"] - expected_rrf) < 1e-12
        # Open top dense hit and top passage_bm25 hit
        for ch in ("dense_passage", "passage_bm25"):
            top_hit = s_res["channels"][ch][0]
            pid = top_hit["passage_id"]
            ctx = corpus.open(pid)
            assert ctx["hit_passage_id"] == pid
            assert ctx["case_id"] == top_hit["case_id"]
            assert ctx["diagnostic_only"] is True
            assert ctx["M4_delivery_recorded"] is False
            opened_search_hits.append({
                "search_label": label,
                "channel": ch,
                "passage_id": pid,
                "case_id": ctx["case_id"],
                "requested_handle": ctx["requested_handle"],
                "hit_span_bytes": ctx["hit_span_bytes"],
                "context_envelope_span_bytes": ctx["span_bytes"],
                "component_kinds": [c["kind"] for c in ctx["components"]],
            })

    summary = {
        "status": "PASS",
        "run_dir": "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1",
        "embedding_fingerprint": EXPECTED_FP,
        "m2_seal_sha256": EXPECTED_M2_SEAL,
        "shards_verified": shards_checked,
        "passages_verified": len(passages),
        "vector_dimensions": 2560,
        "l2_norm_deviation": {
            "max": float(max(norm_deviations)),
            "mean": float(statistics.mean(norm_deviations)),
        },
        "qdrant_verification": {
            "primary_collection": collection,
            "restored_collection": restore_collection,
            "primary_points": len(primary_points),
            "restored_points": len(restore_points),
            "max_primary_vs_cache_abs_diff": max_prim_cache_diff,
            "max_restored_vs_primary_abs_diff": max_rest_prim_diff,
            "max_dense_query_vs_numpy_score_diff": max_dense_score_diff,
            "dense_probes": dense_probes,
        },
        "usage_accounting": {
            "baseline_preflight_requests": 6,
            "baseline_preflight_input_tokens": preflight_input_tokens,
            "baseline_preflight_padded_tokens": preflight_padded_tokens,
            "pilot_document_batch_requests": 64,
            "pilot_document_input_tokens": doc_input_tokens,
            "pilot_document_padded_tokens": doc_padded_tokens,
            "pilot_document_padding_overhead_tokens": doc_padded_tokens - doc_input_tokens,
            "search_query_requests": 3,
            "search_query_input_tokens": search_input_tokens,
            "search_query_padded_tokens": search_padded_tokens,
            "ag_incremental_requests": 67,
            "ag_incremental_input_tokens": doc_input_tokens + search_input_tokens,
            "ag_incremental_padded_tokens": doc_padded_tokens + search_padded_tokens,
            "total_requests_including_preflight": len(attempts),
            "total_known_input_tokens_including_preflight": preflight_input_tokens + doc_input_tokens + search_input_tokens,
            "total_padded_tokens_including_preflight": preflight_padded_tokens + doc_padded_tokens + search_padded_tokens,
            "failed_attempts": 0,
            "retries": 0,
            "unknown_token_attempts": 0,
            "batch_0_reembedded_on_resume": False,
        },
        "latency_and_throughput": {
            "preflight_cold_model_load_seconds": preflight_attempts[0]["receipt"]["descriptor"]["model_load_seconds"],
            "preflight_batch_client_elapsed_seconds": preflight_attempts[0]["elapsed_seconds"],
            "preflight_batch_remote_elapsed_seconds": preflight_attempts[0]["receipt"]["remote_elapsed_seconds"],
            "pilot_batch0_cold_model_load_seconds": batch0["receipt"]["descriptor"]["model_load_seconds"],
            "pilot_batch0_client_elapsed_seconds": batch0["elapsed_seconds"],
            "pilot_batch0_remote_elapsed_seconds": batch0["receipt"]["remote_elapsed_seconds"],
            "warm_batches_count": len(warm_doc_batches),
            "warm_batch_remote_elapsed_seconds": {
                "min": float(min(warm_remote_secs)),
                "median": float(statistics.median(warm_remote_secs)),
                "mean": float(statistics.mean(warm_remote_secs)),
                "max": float(max(warm_remote_secs)),
                "sum": float(sum(warm_remote_secs)),
            },
            "warm_batch_client_elapsed_seconds": {
                "min": float(min(warm_client_secs)),
                "median": float(statistics.median(warm_client_secs)),
                "mean": float(statistics.mean(warm_client_secs)),
                "max": float(max(warm_client_secs)),
                "sum": float(sum(warm_client_secs)),
            },
            "total_document_remote_gpu_seconds": float(total_doc_remote_secs),
            "effective_remote_gpu_tokens_per_second_input": float(doc_input_tokens / total_doc_remote_secs),
            "effective_remote_gpu_tokens_per_second_padded": float(doc_padded_tokens / total_doc_remote_secs),
            "effective_remote_gpu_passages_per_second": float(1024 / total_doc_remote_secs),
            "search_query_remote_elapsed_seconds": [a["receipt"]["remote_elapsed_seconds"] for a in search_attempts],
            "search_query_client_elapsed_seconds": [a["elapsed_seconds"] for a in search_attempts],
        },
        "opened_search_hits": opened_search_hits,
        "operation_receipts": ops_summary,
    }

    out_path = REVIEW_DIR / "pilot_execution_audit.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "total_requests": summary["usage_accounting"]["total_requests_including_preflight"], "total_input_tokens": summary["usage_accounting"]["total_known_input_tokens_including_preflight"]}, sort_keys=True))


if __name__ == "__main__":
    main()
