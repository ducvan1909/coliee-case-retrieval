"""Step 1 & 2: Inspect environment, audit prior evidence, and lock the 8-query + 3-vector diagnostic workload."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("E:/Git/coliee-case-retrieval")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2.retrieval.bm25 import analyze

OUT_DIR = ROOT / "pipeline_v2/reviews/m3_search_latency_diagnostic_v1"
RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
PRIOR_REVIEW_DIR = ROOT / "pipeline_v2/reviews/m3_full_search_plan_ag_review_v1"
SPLIT_REGISTRY_PATH = ROOT / "knowledge_base/pipeline_v1/manifests/split_registry.v1.json"
M0_COHORT_PATH = ROOT / "pipeline_v2/artifacts/m0_20261105_v2/cohort.json"
M0_EXPOSURE_PATH = ROOT / "pipeline_v2/artifacts/m0_20261105_v2/exposure_ledger.json"
CASES_DIR = ROOT / "data/task1_train_files_2026/cases"


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


def get_system_memory() -> dict:
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return {
        "memory_load_percent": stat.dwMemoryLoad,
        "total_phys_bytes": stat.ullTotalPhys,
        "avail_phys_bytes": stat.ullAvailPhys,
        "total_phys_gib": round(stat.ullTotalPhys / (1024**3), 3),
        "avail_phys_gib": round(stat.ullAvailPhys / (1024**3), 3),
    }


def get_disk_usage(path: Path) -> dict:
    u = shutil.disk_usage(path)
    return {
        "drive": path.drive,
        "total_bytes": u.total,
        "used_bytes": u.used,
        "free_bytes": u.free,
        "free_gib": round(u.free / (1024**3), 3),
    }


def get_concurrent_processes() -> list[dict]:
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 12 ProcessName, Id, @{Name='WS_MB';Expression={[math]::Round($_.WorkingSet64/1MB,1)}}, @{Name='CPU_s';Expression={[math]::Round($_.CPU,1)}} | ConvertTo-Json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            return data if isinstance(data, list) else [data]
    except Exception as exc:
        return [{"error": str(exc)}]
    return []


def audit_prior_review() -> dict:
    expected_files = [
        "REPORT.md",
        "decision_matrix.md",
        "findings.json",
        "probe_plan_assumptions.py",
        "probe_results.json",
        "probe_deep_dive.py",
        "probe_deep_dive_results.json",
        "probe_mmap_and_open.py",
        "probe_mmap_and_open_results.json",
        "test_plan_counterexamples.py",
        "counterexample_results.json",
    ]
    inventory = {}
    for name in expected_files:
        p = PRIOR_REVIEW_DIR / name
        inventory[name] = {
            "exists": p.exists(),
            "size_bytes": p.stat().st_size if p.exists() else None,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None,
        }

    findings_doc = json.loads((PRIOR_REVIEW_DIR / "findings.json").read_bytes())
    evidence_claimed = findings_doc.get("evidence_files", [])

    return {
        "prior_review_dir": str(PRIOR_REVIEW_DIR),
        "file_inventory": inventory,
        "probe_deep_dive_results_json_exists": inventory["probe_deep_dive_results.json"]["exists"],
        "claimed_in_findings_json": evidence_claimed,
        "root_cause_of_missing_probe_deep_dive_results": (
            "probe_deep_dive.py printed steps 1 and 2 to stdout, then called "
            "nr.open_context('055641.txt', 'p000001') at line 178 before writing "
            "probe_deep_dive_results.json at line 189. In 055641.txt, handle 'p000001' "
            "does not exist (first numbered handle is 'p000351', as later recorded in "
            "probe_mmap_and_open_results.json), causing an unhandled exception before file write."
        ),
        "evidence_classification": {
            "verified_persisted_measurements": [
                "probe_results.json: SQLite EXPLAIN QUERY PLAN for schedule and postings JOIN documents",
                "probe_results.json: ReadonlyCache single shard load = 10.875 ms",
                "probe_results.json: Qdrant batch=0 vec0 exact=False (20, 256, 1024, 4096) and exact=True (timeout HTTP 500 at 60.167s on limit=20; 10.2438s at 256; 3.7133s at 1024; 3.4117s at 4096)",
                "probe_results.json: Single-query BM25 case=4.5872s (limit 100) and passage=121.5137s (limit 4096) on 6-term English query",
                "probe_mmap_and_open_results.json: default SQLite cache_size=-2000, mmap_size=0; with mmap=4GiB & cache=512MiB (still with JOIN documents) run1=86.571s, run2=63.6325s",
                "probe_mmap_and_open_results.json: PassageReader open_context 0.2349s (small) and 2.4576s (055641.txt), NavigationReader 0.7341s, M2 5 parents and 13 windows > 64KiB",
                "counterexample_results.json: 11/11 deterministic unit counterexamples (CE01..CE11)",
            ],
            "unpersisted_or_missing_artifact_claims": [
                "probe_deep_dive_results.json does not exist on disk; numbers cited from it in REPORT.md/findings.json (104.22s vs 52.18s no-join, 2.42s/2.65s batch 5000 Qdrant, 2860 vs 97 shards) lacked a persisted JSON artifact.",
            ],
            "extrapolations_and_unmeasured_estimates": [
                "'~31.1s' shard verification I/O was a linear multiplication (2,860 shards * 10.875 ms/shard), not a timed end-to-end run.",
                "'~25 MB' RAM for preloading (passage_id -> length) was an analytical estimate, not a measured heap/RSS delta.",
                "5x adaptive BM25/Qdrant latency ('5-8 minutes' / '~13s') was an analytical multiplication of 1-pass latency by 5 expansion steps.",
            ],
        },
    }


def build_locked_workload() -> dict:
    split_reg = json.loads(SPLIT_REGISTRY_PATH.read_bytes())
    cohort = json.loads(M0_COHORT_PATH.read_bytes())
    exposure = json.loads(M0_EXPOSURE_PATH.read_bytes())

    # Collect all holdout IDs from split_registry.v1.json (20 train + 20 test) and cohort.json (10 holdout_queries)
    split_train_holdout = set()
    split_train_dev = []
    for band in ("short", "medium", "long"):
        for cid in split_reg["pilot"]["train"][band]["holdout"]:
            split_train_holdout.add(f"{cid}.txt")
        for cid in split_reg["pilot"]["train"][band]["development"]:
            split_train_dev.append(f"{cid}.txt")
    split_calibration = [f"{cid}.txt" for cid in split_reg["calibration"]]
    cohort_holdout = set(cohort["holdout_queries"])
    cohort_discovery = set(cohort["discovery_queries"])
    cohort_eligible_fresh = set(cohort["eligible_query_ids"])

    all_reserved_holdout = sorted(split_train_holdout | cohort_holdout)

    # Candidate pool for diagnostic queries:
    # Use the 15 train cases explicitly designated as development (10) + calibration (5) in split_registry.v1.json,
    # minus any case that ever appeared in any holdout or fresh cohort list.
    candidate_pool = sorted(
        set(split_train_dev + split_calibration)
        - split_train_holdout
        - cohort_holdout
        - cohort_discovery
        - cohort_eligible_fresh
    )

    # Fixed seed deterministic selection of 8 cases
    SEED = 20261109
    rng = random.Random(SEED)
    selected_cases = rng.sample(candidate_pool, 8)

    # Deterministic target word window sizes assigned by index 0..7 (before looking at text/latency)
    # to span short, medium, and passage-scale lexical queries:
    target_word_counts = [4, 6, 8, 12, 16, 24, 36, 56]

    uri = f"file:{(RUN_DIR / 'lexical.sqlite3').resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")

    queries = []
    word_span_re = re.compile(r"\S+")

    for idx, (cid, target_words) in enumerate(zip(selected_cases, target_word_counts)):
        raw_path = CASES_DIR / cid
        raw_bytes = raw_path.read_bytes()
        source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        raw_text = raw_bytes.decode("utf-8")

        # Deterministic anchor position: start at 1/3 of character length, advance to next newline,
        # then take the next `target_words` whitespace-delimited tokens.
        anchor_char = len(raw_text) // 3
        nl_pos = raw_text.find("\n", anchor_char)
        search_start = (nl_pos + 1) if nl_pos != -1 and nl_pos + 1 < len(raw_text) else anchor_char

        matches = []
        for m in word_span_re.finditer(raw_text, search_start):
            matches.append(m)
            if len(matches) == target_words:
                break
        if len(matches) < target_words:
            matches = list(word_span_re.finditer(raw_text))[:target_words]

        char_start = matches[0].start()
        char_end = matches[-1].end()
        query_text = raw_text[char_start:char_end]
        byte_start = len(raw_text[:char_start].encode("utf-8"))
        byte_end = len(raw_text[:char_end].encode("utf-8"))
        assert raw_bytes[byte_start:byte_end].decode("utf-8") == query_text
        span_sha256 = hashlib.sha256(raw_bytes[byte_start:byte_end]).hexdigest()

        tokens = analyze(query_text)
        unique_terms = sorted(set(tokens))

        # Query df and posting counts in both case and passage channels
        channel_stats = {}
        for kind in ("case", "passage"):
            term_Breakdown = []
            total_df = 0
            total_postings_eligible = 0
            for t in unique_terms:
                row = conn.execute(
                    "SELECT df FROM terms WHERE kind=? AND term=?", (kind, t)
                ).fetchone()
                df_val = int(row[0]) if row else 0
                total_df += df_val
                term_Breakdown.append({"term": t, "df": df_val})
            # Also count excluded self-case postings for these terms
            if unique_terms:
                ph = ",".join("?" for _ in unique_terms)
                if kind == "case":
                    self_postings = conn.execute(
                        f"SELECT COUNT(*) FROM postings WHERE kind='case' AND id=? AND term IN ({ph})",
                        [cid, *unique_terms],
                    ).fetchone()[0]
                else:
                    prefix = cid[:-4] + ":"
                    self_postings = conn.execute(
                        f"SELECT COUNT(*) FROM postings WHERE kind='passage' AND id >= ? AND id < ? AND term IN ({ph})",
                        [prefix, cid[:-4] + ";", *unique_terms],
                    ).fetchone()[0]
            else:
                self_postings = 0
            total_postings_eligible = total_df - int(self_postings)
            channel_stats[kind] = {
                "total_postings_all_cases": total_df,
                "excluded_query_case_postings": int(self_postings),
                "eligible_postings_after_exclusion": total_postings_eligible,
                "max_term_df": max((x["df"] for x in term_Breakdown), default=0),
                "min_term_df": min((x["df"] for x in term_Breakdown), default=0),
                "terms_df": term_Breakdown,
            }

        queries.append(
            {
                "query_id": f"Q{idx+1:02d}",
                "ordinal": idx,
                "query_case": cid,
                "target_whitespace_words": target_words,
                "char_span": [char_start, char_end],
                "span_bytes": [byte_start, byte_end],
                "source_hash": source_sha256,
                "span_sha256": span_sha256,
                "text": query_text,
                "lexical_token_count": len(tokens),
                "unique_term_count": len(unique_terms),
                "unique_terms": unique_terms,
                "channel_postings": channel_stats,
            }
        )

    # Also lock the 3 cached diagnostic vectors deterministically by schedule batch quantiles
    # Total batches = 6496 (0..6495). Pick deterministic quantile batches: 1000, 3248, 5500, ordinal_in_batch = 0
    diagnostic_vectors = []
    for v_idx, batch_num in enumerate((1000, 3248, 5500)):
        rows = conn.execute(
            "SELECT ordinal, passage_id FROM schedule WHERE batch=? ORDER BY ordinal",
            (batch_num,),
        ).fetchall()
        chosen_ordinal, chosen_pid = rows[0]
        meta_row = conn.execute(
            "SELECT case_id, length, metadata FROM documents WHERE kind='passage' AND id=?",
            (chosen_pid,),
        ).fetchone()
        meta = json.loads(meta_row[2])
        diagnostic_vectors.append(
            {
                "vector_id": f"V{v_idx+1:02d}",
                "schedule_batch": batch_num,
                "batch_row_index": 0,
                "schedule_ordinal": int(chosen_ordinal),
                "passage_id": chosen_pid,
                "query_case_excluded": meta_row[0],
                "lexical_length": int(meta_row[1]),
                "full_input_tokens": int(meta["full_input_tokens"]),
                "exact_input_sha256": meta["exact_input_sha256"],
                "source_hash": meta["source_hash"],
                "span_bytes": meta["span_bytes"],
                "note": "Deterministic cached passage vector from M3 full run schedule; diagnostic vector only, not a real query-template embedding.",
            }
        )

    conn.close()

    return {
        "schema_version": "m3-search-latency-workload-manifest-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "blindness_and_exposure_status": "diagnostic_exposed_non_holdout_only_not_blind_evaluation",
        "selection_rule": {
            "seed": SEED,
            "rng": "Python random.Random(20261109).sample(candidate_pool, 8)",
            "candidate_pool_source": "knowledge_base/pipeline_v1/manifests/split_registry.v1.json train development (10) + calibration (5) cases",
            "candidate_pool_size": len(candidate_pool),
            "candidate_pool_ids": candidate_pool,
            "excluded_reserved_holdout_count": len(all_reserved_holdout),
            "excluded_reserved_holdout_ids": all_reserved_holdout,
            "overlap_with_split_registry_holdout": 0,
            "overlap_with_m0_cohort_holdout": 0,
            "overlap_with_m0_cohort_discovery": 0,
            "overlap_with_m0_fresh_eligible_queries": 0,
            "span_extraction_rule": "Start at first newline after floor(len(raw_text)/3) characters; take the next W_i whitespace-delimited tokens for W = [4, 6, 8, 12, 16, 24, 36, 56] assigned by index 0..7.",
            "used_gold_or_labels": False,
            "used_latency_or_retrieval_scores": False,
        },
        "queries": queries,
        "diagnostic_dense_vectors": diagnostic_vectors,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "scripts").mkdir(parents=True, exist_ok=True)

    prior_audit = audit_prior_review()
    (OUT_DIR / "prior_evidence_audit.json").write_text(
        json.dumps(prior_audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    workload = build_locked_workload()
    (OUT_DIR / "workload_manifest.json").write_text(
        json.dumps(workload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    env_info = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(),
        "python_version": sys.version,
        "sqlite_version": sqlite3.sqlite_version,
        "cpu_count_logical": os.cpu_count(),
        "system_memory": get_system_memory(),
        "disk_e": get_disk_usage(ROOT),
        "disk_c": get_disk_usage(Path("C:/")),
        "lexical_sqlite3_size_bytes": (RUN_DIR / "lexical.sqlite3").stat().st_size,
        "concurrent_top_processes": get_concurrent_processes(),
    }
    (OUT_DIR / "environment_snapshot.json").write_text(
        json.dumps(env_info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    summary = {
        "probe_deep_dive_results_exists": prior_audit["probe_deep_dive_results_json_exists"],
        "queries_locked": [
            {
                "id": q["query_id"],
                "case": q["query_case"],
                "tokens": q["lexical_token_count"],
                "unique_terms": q["unique_term_count"],
                "case_postings": q["channel_postings"]["case"]["total_postings_all_cases"],
                "passage_postings": q["channel_postings"]["passage"]["total_postings_all_cases"],
                "text_preview": q["text"][:80],
            }
            for q in workload["queries"]
        ],
        "vectors_locked": [
            {
                "id": v["vector_id"],
                "batch": v["schedule_batch"],
                "passage_id": v["passage_id"],
                "case_id": v["query_case_excluded"],
                "tokens": v["full_input_tokens"],
            }
            for v in workload["diagnostic_dense_vectors"]
        ],
        "env": {
            "sqlite_version": env_info["sqlite_version"],
            "avail_ram_gib": env_info["system_memory"]["avail_phys_gib"],
            "free_disk_e_gib": env_info["disk_e"]["free_gib"],
        },
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
