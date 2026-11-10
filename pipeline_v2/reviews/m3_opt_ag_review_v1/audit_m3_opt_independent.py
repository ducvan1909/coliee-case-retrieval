from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from pipeline_v2.optimization.batching import batches, padding_stats
from pipeline_v2.optimization.benchmark import representative as select_representative_passages
from pipeline_v2.optimization.common import (
    implementation as opt_implementation,
    read as read_json,
    validate_seal,
)
from pipeline_v2.optimization.index import FastSession, PersistentBM25, readonly_vectors, upstream_fingerprints
from pipeline_v2.passages.tokenizer import PinnedTokenizer
from pipeline_v2.retrieval.common import fingerprint as emb_fingerprint, implementation as base_implementation
from pipeline_v2.source.core import canonical, digest


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


ROOT = Path(__file__).resolve().parents[3]
REVIEW_DIR = Path(__file__).resolve().parent

WORD_RE = re.compile(r"\w+", re.UNICODE)


def independent_analyze(text: str) -> list[str]:
    return WORD_RE.findall(str(text).casefold())


class IndependentBM25Oracle:
    """Independent BM25 implementation built directly from raw texts/dicts, not sharing PersistentBM25 code."""

    def __init__(self, docs: list[dict[str, Any]], key: str, k1: float = 1.5, b: float = 0.75) -> None:
        self.key = key
        self.k1 = float(k1)
        self.b = float(b)
        self.docs = []
        self.doc_freqs: list[Counter[str]] = []
        self.doc_lens: list[int] = []
        df: Counter[str] = Counter()
        for d in docs:
            tokens = independent_analyze(d["text"])
            cnt = Counter(tokens)
            self.docs.append(d)
            self.doc_freqs.append(cnt)
            self.doc_lens.append(len(tokens))
            for term in cnt:
                df[term] += 1
        self.n_docs = len(self.docs)
        self.avgdl = (sum(self.doc_lens) / self.n_docs) if self.n_docs else 1.0
        self.idf = {
            term: math.log(1.0 + (self.n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def search(self, query: str, limit: int, exclude_case_id: str | None = None) -> list[dict[str, Any]]:
        q_terms = sorted(set(independent_analyze(query)))
        if not q_terms or not self.n_docs:
            return []
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for d, tf_map, dl in zip(self.docs, self.doc_freqs, self.doc_lens):
            if exclude_case_id and d["case_id"] == exclude_case_id:
                continue
            score = 0.0
            norm = self.k1 * (1.0 - self.b + self.b * (dl / (self.avgdl or 1.0)))
            for term in q_terms:
                tf = tf_map.get(term, 0)
                if not tf:
                    continue
                idf = self.idf.get(term, 0.0)
                score += idf * ((tf * (self.k1 + 1.0)) / (tf + norm))
            if score > 0.0:
                scored.append((score, str(d[self.key]), d))
        scored.sort(key=lambda item: (-item[0], item[1]))
        results = []
        for score, ident, d in scored[:limit]:
            row = {k: v for k, v in d.items() if k != "text"}
            row["score"] = score
            results.append(row)
        return results


def open_sqlite_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def check_1_hashes_and_baseline_snapshot() -> dict[str, Any]:
    opt_profile = read_json(ROOT / "pipeline_v2/configs/m3_opt.json")
    base_profile = read_json(ROOT / "pipeline_v2/configs/m3.json")

    opt_code_files = opt_implementation()
    opt_code_fp = digest(canonical(opt_code_files))
    base_code_files = base_implementation()
    base_code_fp = digest(canonical(base_code_files))
    opt_prof_fp = digest(canonical(opt_profile))
    base_prof_fp = digest(canonical(base_profile))
    opt_emb_fp = emb_fingerprint(opt_profile)
    base_emb_fp = emb_fingerprint(base_profile)

    # Verify baseline snapshot (147 files)
    snapshot = read_json(ROOT / "pipeline_v2/artifacts/m3_opt_baseline_snapshot_20261106_v1.json")
    baseline_dir = ROOT / Path(snapshot["baseline_run"])
    snapshot_files = snapshot["files"]
    actual_files = sorted(p for p in baseline_dir.rglob("*") if p.is_file())
    mismatches = []
    for p in actual_files:
        rel = p.relative_to(baseline_dir).as_posix()
        if rel not in snapshot_files:
            mismatches.append({"file": rel, "error": "missing_in_snapshot"})
        else:
            actual_sha = sha256_file(p)
            actual_bytes = p.stat().st_size
            if actual_sha != snapshot_files[rel]["sha256"] or actual_bytes != snapshot_files[rel]["bytes"]:
                mismatches.append({"file": rel, "error": "hash_or_size_mismatch"})
    for rel in snapshot_files:
        if not (baseline_dir / rel).exists():
            mismatches.append({"file": rel, "error": "missing_on_disk"})

    # Check index v1 (failed partial) and v2 (sealed valid)
    v1_dir = ROOT / "pipeline_v2/artifacts/m3_opt_index_20261107_v1"
    v2_dir = ROOT / "pipeline_v2/artifacts/m3_opt_index_20261107_v2"
    v2_seal = read_json(v2_dir / "seal.json")
    v2_manifest = read_json(v2_dir / "manifest.json")
    validate_seal(v2_dir, v2_seal["files"])

    # Independently reconstruct baseline vectors from the 64 committed .npz/.json shards in m3_pilot_20261106_l4_v1
    pilot_manifest = read_json(baseline_dir / "pilot_manifest.json")
    ids = pilot_manifest["passage_ids"]
    hashes = pilot_manifest["input_hashes"]
    bsize = pilot_manifest["profile"]["batch_size"]
    reconstructed_vectors = []
    reconstructed_passage_ids = []
    reconstructed_input_hashes = []
    shard_sha_ok = True
    shard_count = 0
    for i in range(0, len(ids), bsize):
        batch_ids = ids[i : i + bsize]
        batch_hashes = hashes[i : i + bsize]
        shard_key = digest(canonical([pilot_manifest["embedding_fingerprint"], batch_ids]))
        meta_path = baseline_dir / "vectors" / f"{shard_key}.json"
        npz_path = baseline_dir / "vectors" / f"{shard_key}.npz"
        meta = read_json(meta_path)
        if sha256_file(npz_path) != meta["array_sha256"]:
            shard_sha_ok = False
        with np.load(npz_path, allow_pickle=False) as z:
            arr = np.asarray(z["vectors"], dtype=np.float32)
            reconstructed_vectors.append(arr)
            reconstructed_passage_ids.extend(z["ids"].tolist())
            reconstructed_input_hashes.extend(z["input_hashes"].tolist())
        shard_count += 1

    stacked_baseline = np.vstack(reconstructed_vectors)
    index_vectors = np.load(v2_dir / "vectors.npy", allow_pickle=False, mmap_mode="r")
    max_abs_diff = float(np.max(np.abs(stacked_baseline - index_vectors)))
    exact_equal = bool(np.array_equal(stacked_baseline, index_vectors))
    norms = np.linalg.norm(index_vectors, axis=1)
    max_norm_dev = float(np.max(np.abs(norms - 1.0)))

    # Inspect lexical.sqlite3 in readonly mode
    lex_conn = open_sqlite_ro(v2_dir / "lexical.sqlite3")
    lex_passages = lex_conn.execute(
        "SELECT id, case_id, length, metadata FROM documents WHERE kind='passage' ORDER BY rowid"
    ).fetchall()
    lex_cases = lex_conn.execute(
        "SELECT id, case_id, length, metadata FROM documents WHERE kind='case' ORDER BY rowid"
    ).fetchall()
    postings_count = lex_conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
    terms_count = lex_conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
    lex_conn.close()

    lex_passage_ids = [r["id"] for r in lex_passages]
    lex_input_hashes = [json.loads(r["metadata"])["exact_input_sha256"] for r in lex_passages]

    return {
        "opt_code_fingerprint": opt_code_fp,
        "opt_code_files": opt_code_files,
        "base_code_fingerprint": base_code_fp,
        "base_code_files": base_code_files,
        "opt_profile_fingerprint": opt_prof_fp,
        "base_profile_fingerprint": base_prof_fp,
        "opt_embedding_fingerprint": opt_emb_fp,
        "base_embedding_fingerprint": base_emb_fp,
        "baseline_snapshot_file_count": len(actual_files),
        "baseline_snapshot_mismatches": mismatches,
        "index_v1_state": {
            "exists": v1_dir.exists(),
            "has_seal": (v1_dir / "seal.json").exists(),
            "has_manifest": (v1_dir / "manifest.json").exists(),
            "files": [p.name for p in v1_dir.iterdir()] if v1_dir.exists() else [],
        },
        "index_v2_seal_verified": True,
        "index_v2_files_in_seal": v2_seal["files"],
        "vectors_verification": {
            "committed_shard_count": shard_count,
            "all_shard_sha256_verified": shard_sha_ok,
            "shape": list(index_vectors.shape),
            "dtype": str(index_vectors.dtype),
            "all_finite": bool(np.isfinite(index_vectors).all()),
            "max_norm_deviation_from_1": max_norm_dev,
            "exact_array_equal_to_baseline_shards": exact_equal,
            "max_abs_diff_vs_baseline_shards": max_abs_diff,
            "passage_ids_exact_match": lex_passage_ids == reconstructed_passage_ids == v2_manifest["passage_ids"],
            "input_hashes_exact_match": lex_input_hashes == reconstructed_input_hashes,
        },
        "upstream_fingerprints_match_manifest": upstream_fingerprints(ROOT, pilot_manifest) == v2_manifest["upstream_fingerprints"],
        "lexical_sqlite_storage_inspection": {
            "file_size_bytes": (v2_dir / "lexical.sqlite3").stat().st_size,
            "case_count": len(lex_cases),
            "passage_count": len(lex_passages),
            "postings_row_count": postings_count,
            "terms_row_count": terms_count,
            "case_metadata_stores_raw_text": "text" in json.loads(lex_cases[0]["metadata"]),
            "passage_metadata_stores_raw_text": "text" in json.loads(lex_passages[0]["metadata"]),
            "total_case_metadata_bytes": sum(len(r["metadata"].encode("utf-8")) for r in lex_cases),
            "total_passage_metadata_bytes": sum(len(r["metadata"].encode("utf-8")) for r in lex_passages),
        },
    }


def check_2_bm25_oracle_and_lexical_equivalence() -> dict[str, Any]:
    v2_dir = ROOT / "pipeline_v2/artifacts/m3_opt_index_20261107_v2"
    base_run_dir = ROOT / "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1"
    pilot_manifest = read_json(base_run_dir / "pilot_manifest.json")
    raw_dir = ROOT / "data/task1_train_files_2026/cases"
    m2_passages_dir = ROOT / "pipeline_v2/artifacts/m2_passages_20261106_v1/sources"
    m2_nav_dir = ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v3/sources"

    # Reconstruct cases and passages directly from raw case files and M2 passage/navigation bundles
    raw_cases: list[dict[str, Any]] = []
    for cid, expected_sha in sorted(pilot_manifest["source_hashes"].items()):
        p = raw_dir / cid
        raw_bytes = p.read_bytes()
        assert sha256_bytes(raw_bytes) == expected_sha, f"Raw hash mismatch for {cid}"
        raw_cases.append({"case_id": cid, "text": raw_bytes.decode("utf-8"), "source_hash": expected_sha})

    selected_passage_set = set(pilot_manifest["passage_ids"])
    passage_by_id: dict[str, dict[str, Any]] = {}
    for cid in sorted(pilot_manifest["source_hashes"]):
        stem = cid[:-4] if cid.endswith(".txt") else cid
        bundle = read_json(m2_passages_dir / f"{stem}.json")
        nav_bundle = read_json(m2_nav_dir / f"{stem}.json")
        preview_counts = {r["unit_id"]: len(r["preview_refs"]) for r in nav_bundle["navigation"]}
        raw_bytes = (raw_dir / cid).read_bytes()
        for row in bundle["passages"]:
            pid = row["passage_id"]
            if pid in selected_passage_set:
                b_start, b_end = row["span_bytes"]
                text_slice = raw_bytes[b_start:b_end].decode("utf-8")
                assert sha256_bytes(text_slice.encode("utf-8")) == row["exact_input_sha256"]
                rec = dict(row)
                rec["text"] = text_slice
                rec["navigation_preview_count"] = preview_counts[row["parent_unit_ids"][0]]
                passage_by_id[pid] = rec
    raw_passages = [passage_by_id[pid] for pid in pilot_manifest["passage_ids"]]

    # Build independent oracle
    oracle_case = IndependentBM25Oracle(raw_cases, "case_id")
    oracle_passage = IndependentBM25Oracle(raw_passages, "passage_id")

    # Open PersistentBM25 readonly
    persistent = PersistentBM25(v2_dir / "lexical.sqlite3", readonly=True)

    case_ids_sorted = sorted(pilot_manifest["source_hashes"])
    test_queries = [
        {"query": "standard of review", "exclude": None},
        {"query": "standard of review", "exclude": "079659.txt"},
        {"query": "décision n'est pas raisonnable under s. 97(1)", "exclude": None},
        {"query": "judicial review procedural fairness standard of review reasonableness", "exclude": case_ids_sorted[0]},
        {"query": "patent claim construction infringement anticipation obviousness", "exclude": case_ids_sorted[1]},
        {"query": "crédibilité contrôle judiciaire décision déraisonnable", "exclude": None},
        {"query": "section 96 97(1) 2019 100% non-refoulement don't", "exclude": case_ids_sorted[2]},
        {"query": "zzznonexistenttokenxyz12345", "exclude": None},
    ]

    comparisons = []
    for item in test_queries:
        q = item["query"]
        excl = item["exclude"]
        for kind, key, oracle in [("case", "case_id", oracle_case), ("passage", "passage_id", oracle_passage)]:
            t0 = time.perf_counter()
            o_hits = oracle.search(q, 1024, exclude_case_id=excl)
            t_oracle = time.perf_counter() - t0

            t1 = time.perf_counter()
            p_hits = persistent.search(q, kind, 1024, exclude_case=excl)
            t_pers = time.perf_counter() - t1

            ids_equal = [h[key] for h in o_hits] == [h[key] for h in p_hits]
            max_score_diff = (
                max((abs(a["score"] - b["score"]) for a, b in zip(o_hits, p_hits)), default=0.0)
                if ids_equal
                else float("inf")
            )
            meta_equal = all(
                {k: v for k, v in a.items() if k != "score"} == {k: v for k, v in b.items() if k != "score"}
                for a, b in zip(o_hits, p_hits)
            )
            comparisons.append(
                {
                    "query": q,
                    "kind": kind,
                    "exclude_case_id": excl,
                    "hit_count": len(p_hits),
                    "ids_equal": ids_equal,
                    "metadata_equal": meta_equal,
                    "max_score_diff": max_score_diff,
                    "oracle_seconds": round(t_oracle, 6),
                    "persistent_sqlite_seconds": round(t_pers, 6),
                }
            )

    persistent.close()
    return {
        "reconstructed_case_count": len(raw_cases),
        "reconstructed_passage_count": len(raw_passages),
        "all_queries_ids_equal": all(c["ids_equal"] for c in comparisons),
        "all_queries_metadata_equal": all(c["metadata_equal"] for c in comparisons),
        "max_score_diff_across_all_queries": max(c["max_score_diff"] for c in comparisons),
        "comparisons": comparisons,
    }


def check_3_qdrant_and_fast_session() -> dict[str, Any]:
    v2_dir = ROOT / "pipeline_v2/artifacts/m3_opt_index_20261107_v2"
    manifest = read_json(v2_dir / "manifest.json")
    collection = manifest["baseline_manifest"]["collection"]
    qdrant_url = f"http://127.0.0.1:6333/collections/{collection}"

    qdrant_reachable = False
    qdrant_info = None
    try:
        with urllib.request.urlopen(qdrant_url, timeout=3) as resp:
            qdrant_info = json.loads(resp.read().decode("utf-8"))
            qdrant_reachable = True
    except Exception as exc:
        qdrant_info = {"error": str(exc)}

    session_verify_quick = None
    session_verify_full = None
    search_vector_timing = None
    if qdrant_reachable:
        t0 = time.perf_counter()
        session = FastSession(ROOT, v2_dir)
        t_init = time.perf_counter() - t0
        try:
            t1 = time.perf_counter()
            session_verify_quick = session.verify(full_db=False)
            session_verify_quick["elapsed_seconds"] = round(time.perf_counter() - t1, 6)

            t2 = time.perf_counter()
            session_verify_full = session.verify(full_db=True)
            session_verify_full["elapsed_seconds"] = round(time.perf_counter() - t2, 6)

            qvec = np.asarray(session.vectors[0], dtype=np.float32)
            t3 = time.perf_counter()
            res = session.search_vector(
                "standard of review",
                qvec,
                query_case=session.passages[0]["case_id"],
                limit=10,
            )
            t_search = time.perf_counter() - t3
            search_vector_timing = {
                "init_seconds": round(t_init, 6),
                "search_vector_seconds": round(t_search, 6),
                "reported_seconds": round(res["seconds"], 6),
                "top_case_ids": [r["case_id"] for r in res["results"][:5]],
            }
        finally:
            session.close()

    return {
        "qdrant_reachable": qdrant_reachable,
        "collection": collection,
        "qdrant_points_count": qdrant_info.get("result", {}).get("points_count") if qdrant_reachable else None,
        "session_verify_quick": session_verify_quick,
        "session_verify_full": session_verify_full,
        "search_vector_timing": search_vector_timing,
    }


def check_4_length_batching_and_padding() -> dict[str, Any]:
    v2_dir = ROOT / "pipeline_v2/artifacts/m3_opt_index_20261107_v2"
    manifest = read_json(v2_dir / "manifest.json")
    lex = PersistentBM25(v2_dir / "lexical.sqlite3", readonly=True)
    docs_by_id = {p["passage_id"]: p for p in lex.documents("passage")}
    lex.close()
    pilot_passages = [docs_by_id[pid] for pid in manifest["passage_ids"]]

    # Verify full_input_tokens with PinnedTokenizer on pilot passages
    tokenizer = PinnedTokenizer(ROOT, "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
    recomputed_token_counts = [tokenizer.count(p["text"]) for p in pilot_passages]
    stored_token_counts = [int(p["full_input_tokens"]) for p in pilot_passages]
    token_counts_exact_match = recomputed_token_counts == stored_token_counts

    # Unsorted baseline batch_size=16 padding
    unsorted_16 = batches(pilot_passages, 16, ordered=False)
    unsorted_16_stats = padding_stats(unsorted_16)

    # Sorted batch sizes 16, 32, 64, 128 on 1,024 pilot passages
    pilot_sorted_stats = {}
    for bs in (16, 32, 64, 128):
        bs_batches = batches(pilot_passages, bs, ordered=True)
        seen_pids = [p["passage_id"] for b in bs_batches for p in b]
        assert sorted(seen_pids) == sorted(p["passage_id"] for p in pilot_passages)
        st = padding_stats(bs_batches)
        vs_base = round(1.0 - (st["padded_tokens"] / unsorted_16_stats["padded_tokens"]), 6)
        st["padded_token_reduction_vs_unsorted_16"] = vs_base
        st["padding_fraction_of_padded_tokens"] = round(
            (st["padded_tokens"] - st["input_tokens"]) / st["padded_tokens"], 6
        )
        pilot_sorted_stats[str(bs)] = st

    # Sorted batch sizes 16, 32, 64, 128 on the 256 representative benchmark sample
    rep_256 = select_representative_passages(pilot_passages, 256)
    rep_256_unsorted_16 = padding_stats(batches(rep_256, 16, ordered=False))
    rep_256_sorted_stats = {}
    for bs in (16, 32, 64, 128):
        bs_batches = batches(rep_256, bs, ordered=True)
        st = padding_stats(bs_batches)
        st["padded_token_reduction_vs_unsorted_16"] = round(
            1.0 - (st["padded_tokens"] / rep_256_unsorted_16["padded_tokens"]), 6
        )
        st["padding_fraction_of_padded_tokens"] = round(
            (st["padded_tokens"] - st["input_tokens"]) / st["padded_tokens"], 6
        )
        rep_256_sorted_stats[str(bs)] = st

    # Also compute padding stats across ALL 415,693 passages in M2 to see real full-corpus behavior!
    m2_sources_dir = ROOT / "pipeline_v2/artifacts/m2_passages_20261106_v1/sources"
    full_corpus_passages = []
    for p in sorted(m2_sources_dir.glob("*.json")):
        data = json.loads(p.read_bytes())
        for row in data["passages"]:
            full_corpus_passages.append(
                {
                    "passage_id": row["passage_id"],
                    "full_input_tokens": int(row["full_input_tokens"]),
                }
            )
    full_unsorted_16 = padding_stats(batches(full_corpus_passages, 16, ordered=False))
    full_sorted_stats = {}
    for bs in (16, 32, 64, 128):
        bs_batches = batches(full_corpus_passages, bs, ordered=True)
        st = padding_stats(bs_batches)
        st["padded_token_reduction_vs_unsorted_16"] = round(
            1.0 - (st["padded_tokens"] / full_unsorted_16["padded_tokens"]), 6
        )
        st["padding_fraction_of_padded_tokens"] = round(
            (st["padded_tokens"] - st["input_tokens"]) / st["padded_tokens"], 6
        )
        full_sorted_stats[str(bs)] = st

    return {
        "pinned_tokenizer_matches_stored_token_counts": token_counts_exact_match,
        "pilot_1024": {
            "unsorted_batch_16": unsorted_16_stats,
            "sorted_by_batch_size": pilot_sorted_stats,
        },
        "benchmark_representative_256": {
            "unsorted_batch_16": rep_256_unsorted_16,
            "sorted_by_batch_size": rep_256_sorted_stats,
        },
        "full_corpus_415693": {
            "passage_count": len(full_corpus_passages),
            "unsorted_batch_16": full_unsorted_16,
            "sorted_by_batch_size": full_sorted_stats,
        },
    }


def check_5_and_6_gpu_benchmark_ledger() -> dict[str, Any]:
    bench_dir = ROOT / "pipeline_v2/artifacts/m3_opt_gpu_benchmark_20261107_v1"
    reported = read_json(bench_dir / "benchmark_result.json")
    plan = read_json(bench_dir / "benchmark_plan.json")

    conn = open_sqlite_ro(bench_dir / "ledger.sqlite3")
    attempts = conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()
    conn.close()

    total_attempts = len(attempts)
    status_counts = Counter(r["status"] for r in attempts)
    phase_summary: dict[str, dict[str, Any]] = {}
    unique_input_hashes: set[str] = set()
    total_non_unique_docs = 0
    total_input_tokens = 0
    total_padded_tokens = 0
    unknown_token_attempts = 0
    descriptor_checks = []

    for r in attempts:
        rec = json.loads(r["receipt"]) if r["receipt"] else {}
        bid = str(r["batch"])
        if bid == "warmup-16":
            phase = "warmup"
        elif bid.startswith("stress-"):
            phase = bid  # stress-16, stress-32, stress-64, stress-128
        elif bid.startswith("size-"):
            parts = bid.split("-")
            phase = f"bs{parts[1]}"  # bs16, bs32, bs64, bs128
        else:
            phase = "other"

        in_hashes = rec.get("input_hashes", [])
        unique_input_hashes.update(in_hashes)
        doc_cnt = len(in_hashes)
        in_tok = r["tokens"]
        pad_tok = rec.get("padded_tokens")
        if in_tok is None or pad_tok is None:
            unknown_token_attempts += 1
        else:
            total_input_tokens += int(in_tok)
            total_padded_tokens += int(pad_tok)
        total_non_unique_docs += doc_cnt

        desc = rec.get("descriptor", {})
        descriptor_checks.append(
            {
                "gpu": desc.get("gpu"),
                "device_dtype": desc.get("device_dtype"),
                "dimensions": desc.get("dimensions"),
                "model": desc.get("model"),
                "revision": desc.get("revision"),
                "loaded_model_revision": desc.get("loaded_model_revision"),
                "embedding_fingerprint": desc.get("embedding_fingerprint"),
                "engine_sha256": desc.get("engine_sha256"),
                "wrapper_sha256": desc.get("wrapper_sha256"),
                "package_versions": desc.get("package_versions"),
            }
        )

        st = phase_summary.setdefault(
            phase,
            {
                "request_count": 0,
                "doc_count": 0,
                "input_tokens": 0,
                "padded_tokens": 0,
                "client_seconds": 0.0,
                "remote_total_seconds": 0.0,
                "gpu_model_pool_seconds": 0.0,
                "peak_allocated_bytes": 0,
                "peak_reserved_bytes": 0,
                "device_total_bytes": 0,
            },
        )
        st["request_count"] += 1
        st["doc_count"] += doc_cnt
        st["input_tokens"] += int(in_tok or 0)
        st["padded_tokens"] += int(pad_tok or 0)
        st["client_seconds"] += float(rec.get("client_elapsed_seconds", r["elapsed"]) or 0.0)
        st["remote_total_seconds"] += float(rec.get("remote_elapsed_seconds") or 0.0)
        st["gpu_model_pool_seconds"] += float(rec.get("gpu_model_pool_seconds") or 0.0)
        st["peak_allocated_bytes"] = max(st["peak_allocated_bytes"], int(rec.get("peak_allocated_bytes", 0)))
        st["peak_reserved_bytes"] = max(st["peak_reserved_bytes"], int(rec.get("peak_reserved_bytes", 0)))
        st["device_total_bytes"] = max(st["device_total_bytes"], int(rec.get("device_total_bytes", 0)))

    reported_grid_by_bs = {str(row["batch_size"]): row for row in reported["grid"]}
    warm_batch_analysis = {}
    for bs in (16, 32, 64, 128):
        key = f"bs{bs}"
        st = phase_summary[key]
        stress_st = phase_summary[f"stress-{bs}"]
        rep_row = reported_grid_by_bs[str(bs)]
        client_s = st["client_seconds"]
        remote_s = st["remote_total_seconds"]
        gpu_s = st["gpu_model_pool_seconds"]
        docs = st["doc_count"]
        in_tok = st["input_tokens"]
        pad_tok = st["padded_tokens"]
        alloc = max(st["peak_allocated_bytes"], stress_st["peak_allocated_bytes"])
        resv = max(st["peak_reserved_bytes"], stress_st["peak_reserved_bytes"])
        tot_vram = st["device_total_bytes"]
        rpc_overhead_s = client_s - remote_s
        max_cos_dev = max(
            [stress_st_cos := rep_row["stress"]["max_cosine_deviation_vs_baseline"]]
            + [c["max_cosine_deviation_vs_baseline"] for c in rep_row["warm_calls"]]
        )
        warm_batch_analysis[str(bs)] = {
            "request_count": st["request_count"],
            "documents_encoded": docs,
            "input_tokens": in_tok,
            "padded_tokens": pad_tok,
            "padding_ratio": round((pad_tok - in_tok) / pad_tok, 6),
            "client_total_seconds": round(client_s, 6),
            "remote_total_seconds": round(remote_s, 6),
            "gpu_cuda_model_pool_seconds": round(gpu_s, 6),
            "rpc_network_overhead_seconds": round(rpc_overhead_s, 6),
            "rpc_overhead_per_call_seconds": round(rpc_overhead_s / st["request_count"], 6),
            "client_end_to_end_docs_per_second": round(docs / client_s, 6),
            "remote_docs_per_second": round(docs / remote_s, 6),
            "gpu_cuda_docs_per_second": round(docs / gpu_s, 6),
            "client_real_tokens_per_second": round(in_tok / client_s, 6),
            "remote_real_tokens_per_second": round(in_tok / remote_s, 6),
            "gpu_cuda_real_tokens_per_second": round(in_tok / gpu_s, 6),
            "gpu_cuda_padded_tokens_per_second": round(pad_tok / gpu_s, 6),
            "peak_memory_allocated_bytes_warm": st["peak_allocated_bytes"],
            "peak_memory_allocated_bytes_with_stress": alloc,
            "peak_memory_reserved_bytes_with_stress": resv,
            "device_total_bytes": tot_vram,
            "allocated_fraction_of_vram": round(alloc / tot_vram, 6),
            "reserved_fraction_of_vram": round(resv / tot_vram, 6),
            "allocated_headroom_fraction": round(1.0 - (alloc / tot_vram), 6),
            "reserved_headroom_fraction": round(1.0 - (resv / tot_vram), 6),
            "max_cosine_deviation_vs_baseline": max_cos_dev,
            "matches_reported_summary": {
                "end_to_end_docs_per_sec": abs((docs / client_s) - rep_row["end_to_end_documents_per_second"]) < 1e-9,
                "remote_docs_per_sec": abs((docs / remote_s) - rep_row["remote_documents_per_second"]) < 1e-9,
                "memory_headroom_fraction": abs((1.0 - alloc / tot_vram) - rep_row["memory_headroom_fraction"]) < 1e-9,
                "reserved_headroom_fraction": abs((1.0 - resv / tot_vram) - rep_row["reserved_headroom_fraction"]) < 1e-9,
            },
        }

    return {
        "plan_matched": (
            plan["profile"]["benchmark"]["batch_sizes"] == [16, 32, 64, 128]
            and len(plan["representative_ids"]) == 256
            and plan["maximum_documents_if_all_grid_sizes_complete"] == 2304
        ),
        "total_sqlite_attempts": total_attempts,
        "status_counts": dict(status_counts),
        "unknown_token_attempts": unknown_token_attempts,
        "unique_input_hashes_encoded": len(unique_input_hashes),
        "representative_ids_count": len(plan["representative_ids"]),
        "non_unique_document_encodings": total_non_unique_docs,
        "total_real_input_tokens_across_all_65_calls": total_input_tokens,
        "total_padded_tokens_across_all_65_calls": total_padded_tokens,
        "all_descriptors_uniform": len({json.dumps(d, sort_keys=True) for d in descriptor_checks}) == 1,
        "descriptor_sample": descriptor_checks[0] if descriptor_checks else None,
        "warmup_16_summary": phase_summary.get("warmup"),
        "stress_summaries": {str(bs): phase_summary.get(f"stress-{bs}") for bs in (16, 32, 64, 128)},
        "warm_batch_analysis": warm_batch_analysis,
        "reported_winner_batch_size": reported["winner_batch_size"],
        "winner_by_metric": {
            "by_client_end_to_end_docs_per_second": max(
                warm_batch_analysis.items(), key=lambda kv: kv[1]["client_end_to_end_docs_per_second"]
            )[0],
            "by_remote_docs_per_second": max(
                warm_batch_analysis.items(), key=lambda kv: kv[1]["remote_docs_per_second"]
            )[0],
            "by_gpu_cuda_docs_per_second": max(
                warm_batch_analysis.items(), key=lambda kv: kv[1]["gpu_cuda_docs_per_second"]
            )[0],
        },
    }


def check_7_search_benchmark_ledger() -> dict[str, Any]:
    sb_dir = ROOT / "pipeline_v2/artifacts/m3_opt_search_benchmark_20261107_v1"
    reported = read_json(sb_dir / "search_benchmark.json")
    conn = open_sqlite_ro(sb_dir / "ledger.sqlite3")
    attempts = conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()
    conn.close()

    rows = []
    for r in attempts:
        rec = json.loads(r["receipt"]) if r["receipt"] else {}
        desc = rec.get("descriptor", {})
        rows.append(
            {
                "id": r["id"],
                "batch": r["batch"],
                "phase": r["phase"],
                "status": r["status"],
                "tokens": r["tokens"],
                "elapsed_seconds": r["elapsed"],
                "remote_elapsed_seconds": rec.get("remote_elapsed_seconds"),
                "engine_sha256": desc.get("engine_sha256"),
                "wrapper_sha256": desc.get("wrapper_sha256"),
                "embedding_fingerprint": desc.get("embedding_fingerprint"),
            }
        )

    base_engine_sha = sha256_file(ROOT / "pipeline_v2/deployments/modal/engine.py")
    base_app_sha = sha256_file(ROOT / "pipeline_v2/deployments/modal/qwen3_embed.py")
    opt_engine_sha = sha256_file(ROOT / "pipeline_v2/deployments/modal_opt/engine.py")
    opt_app_sha = sha256_file(ROOT / "pipeline_v2/deployments/modal_opt/qwen3_embed.py")

    used_baseline_modal_app = all(
        r["engine_sha256"] == base_engine_sha and r["wrapper_sha256"] == base_app_sha for r in rows
    )

    all_local_timings = [t for q in reported["queries"] for t in q["local_seconds"]]

    # Verify RRF fusion math on all returned top-10 results across the 3 queries
    rrf_math_verified = True
    max_rrf_diff = 0.0
    for q in reported["queries"]:
        excl = q["excluded_case"]
        for row in q["results"]:
            if excl and row["case_id"] == excl:
                rrf_math_verified = False
            expected_rrf = sum(1.0 / (60.0 + ch["rank"]) for ch in row["channels"].values())
            diff = abs(expected_rrf - row["score"])
            max_rrf_diff = max(max_rrf_diff, diff)
            if diff > 1e-12:
                rrf_math_verified = False

    return {
        "sqlite_attempt_count": len(rows),
        "sqlite_attempts": rows,
        "total_query_input_tokens": sum(int(r["tokens"] or 0) for r in rows),
        "used_baseline_modal_app_instead_of_opt_app": used_baseline_modal_app,
        "base_engine_sha256": base_engine_sha,
        "opt_engine_sha256": opt_engine_sha,
        "query_count": len(reported["queries"]),
        "local_search_runs_count": len(all_local_timings),
        "local_search_min_seconds": round(min(all_local_timings), 6),
        "local_search_max_seconds": round(max(all_local_timings), 6),
        "local_search_mean_seconds": round(sum(all_local_timings) / len(all_local_timings), 6),
        "rrf_math_and_exclusion_verified": rrf_math_verified,
        "max_rrf_score_diff": max_rrf_diff,
        "baseline_original_search_cli_seconds": reported["baseline_original_search_cli_seconds"],
    }


def main() -> None:
    results = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "check_1_hashes_and_snapshot": check_1_hashes_and_baseline_snapshot(),
        "check_2_bm25_oracle_and_lexical": check_2_bm25_oracle_and_lexical_equivalence(),
        "check_3_qdrant_and_fast_session": check_3_qdrant_and_fast_session(),
        "check_4_length_batching_and_padding": check_4_length_batching_and_padding(),
        "check_5_and_6_gpu_benchmark": check_5_and_6_gpu_benchmark_ledger(),
        "check_7_search_benchmark": check_7_search_benchmark_ledger(),
    }
    out_path = REVIEW_DIR / "recomputed_metrics.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
