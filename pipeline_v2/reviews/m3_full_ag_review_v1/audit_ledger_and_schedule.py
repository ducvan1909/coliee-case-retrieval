"""Streaming readonly audit of ledger.sqlite3, lexical.sqlite3 schedule, and invocation receipts."""
import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = ROOT / "pipeline_v2/artifacts/m3_full_train_20261108_v1"
REV_DIR = Path(__file__).resolve().parent


def ts_iso(epoch_sec):
    if epoch_sec is None:
        return None
    return datetime.datetime.fromtimestamp(epoch_sec, tz=datetime.timezone.utc).isoformat()


def ns_iso(ns_str):
    ns = int(ns_str)
    return datetime.datetime.fromtimestamp(ns / 1e9, tz=datetime.timezone.utc).isoformat()


def main():
    lex_uri = (RUN_DIR / "lexical.sqlite3").resolve().as_uri() + "?mode=ro"
    led_uri = (RUN_DIR / "ledger.sqlite3").resolve().as_uri() + "?mode=ro"

    lex_db = sqlite3.connect(lex_uri, uri=True)
    led_db = sqlite3.connect(led_uri, uri=True)

    try:
        # 1. Schedule streaming summary by batch
        sched_sql = """
            SELECT s.batch,
                   COUNT(*) AS doc_count,
                   MIN(s.ordinal) AS min_ord,
                   MAX(s.ordinal) AS max_ord,
                   SUM(CAST(json_extract(d.metadata, '$.full_input_tokens') AS INTEGER)) AS sum_tokens,
                   MAX(CAST(json_extract(d.metadata, '$.full_input_tokens') AS INTEGER)) AS max_tokens,
                   MIN(CAST(json_extract(d.metadata, '$.full_input_tokens') AS INTEGER)) AS min_tokens
            FROM schedule s
            JOIN documents d ON d.kind = 'passage' AND d.id = s.passage_id
            GROUP BY s.batch
            ORDER BY s.batch
        """
        expected_batches = {}
        total_passages = 0
        total_sched_input_tokens = 0
        total_sched_padded_tokens = 0
        for b, cnt, min_o, max_o, sum_t, max_t, min_t in lex_db.execute(sched_sql):
            padded = max_t * cnt
            expected_batches[b] = {
                "doc_count": cnt,
                "min_ord": min_o,
                "max_ord": max_o,
                "input_tokens": sum_t,
                "padded_tokens": padded,
                "min_tokens": min_t,
                "max_tokens": max_t,
            }
            total_passages += cnt
            total_sched_input_tokens += sum_t
            total_sched_padded_tokens += padded

        # 2. Check full_batches table in ledger.sqlite3
        fb_row = led_db.execute(
            "SELECT COUNT(*), MIN(batch), MAX(batch), SUM(committed = 1), SUM(committed != 1) FROM full_batches"
        ).fetchone()
        fb_distinct = led_db.execute("SELECT COUNT(DISTINCT batch) FROM full_batches WHERE committed = 1").fetchone()[0]

        # 3. Stream attempts table in ledger.sqlite3
        status_summary = {}
        for st, cnt, reqs, k_tok, unk_tok, elap, unk_elap in led_db.execute(
            """
            SELECT status,
                   COUNT(*),
                   COALESCE(SUM(requests), 0),
                   COALESCE(SUM(tokens), 0),
                   SUM(tokens IS NULL),
                   COALESCE(SUM(elapsed), 0.0),
                   SUM(elapsed IS NULL)
            FROM attempts
            GROUP BY status
            """
        ):
            status_summary[st] = {
                "attempts": cnt,
                "requests": reqs,
                "known_tokens": k_tok,
                "unknown_token_attempts": unk_tok or 0,
                "recorded_elapsed_seconds": elap,
                "unknown_elapsed_attempts": unk_elap or 0,
            }

        non_success_attempts = []
        success_by_batch = {}
        duplicate_success_batches = []
        token_mismatches = []
        padded_mismatches = []
        hash_count_mismatches = []
        descriptor_anomalies = []

        total_rec_input_tokens = 0
        total_rec_padded_tokens = 0
        total_client_elapsed = 0.0
        total_remote_elapsed = 0.0
        total_gpu_pool_elapsed = 0.0
        max_peak_allocated = 0
        max_peak_reserved = 0
        device_total_bytes_set = set()
        instance_ids = {}
        gaps = []

        prev_attempt = None
        for row in led_db.execute(
            "SELECT id, batch, phase, started, elapsed, status, requests, tokens, error, receipt FROM attempts ORDER BY id"
        ):
            aid, label, phase, started, elapsed, status, reqs, tokens, error, rec_str = row
            if prev_attempt is not None:
                prev_end = prev_attempt["started"] + (prev_attempt["elapsed"] or 0.0)
                gap = started - prev_end
                if gap > 30.0 or prev_attempt["status"] != "success":
                    gaps.append({
                        "prev_id": prev_attempt["id"],
                        "prev_batch": prev_attempt["batch"],
                        "prev_status": prev_attempt["status"],
                        "prev_started_utc": ts_iso(prev_attempt["started"]),
                        "prev_elapsed": prev_attempt["elapsed"],
                        "next_id": aid,
                        "next_batch": label,
                        "next_started_utc": ts_iso(started),
                        "gap_seconds": gap,
                    })
            prev_attempt = {"id": aid, "batch": label, "started": started, "elapsed": elapsed, "status": status}

            if status != "success":
                non_success_attempts.append({
                    "id": aid,
                    "batch": label,
                    "phase": phase,
                    "started": started,
                    "started_utc": ts_iso(started),
                    "elapsed": elapsed,
                    "status": status,
                    "requests": reqs,
                    "tokens": tokens,
                    "error": error,
                    "receipt": json.loads(rec_str) if rec_str else None,
                })
                continue

            assert label.startswith("full-documents-"), f"Unexpected batch label: {label}"
            b_num = int(label.split("-")[-1])
            if b_num in success_by_batch:
                duplicate_success_batches.append((b_num, success_by_batch[b_num], aid))
            success_by_batch[b_num] = aid

            rec = json.loads(rec_str)
            exp = expected_batches[b_num]
            if tokens != exp["input_tokens"] or rec.get("input_tokens") != exp["input_tokens"]:
                token_mismatches.append((b_num, aid, tokens, rec.get("input_tokens"), exp["input_tokens"]))
            if rec.get("padded_tokens") != exp["padded_tokens"]:
                padded_mismatches.append((b_num, aid, rec.get("padded_tokens"), exp["padded_tokens"]))
            if len(rec.get("input_hashes", [])) != exp["doc_count"]:
                hash_count_mismatches.append((b_num, aid, len(rec.get("input_hashes", [])), exp["doc_count"]))

            desc = rec.get("descriptor", {})
            if (
                desc.get("gpu") != "NVIDIA L4"
                or desc.get("model") != "Qwen/Qwen3-Embedding-4B"
                or desc.get("loaded_model_revision") != "5cf2132abc99cad020ac570b19d031efec650f2b"
                or desc.get("embedding_fingerprint") != "9105955758bda2eba37350535866f9b217e1b9650b1a3f081496a7c4a9965c49"
                or desc.get("engine_sha256") != "c2c580bf1f32a9437aaae4dfdf1d7d3f08674ed1f26a3c24ee55a34bbfc14501"
                or desc.get("wrapper_sha256") != "4a08b2e0d8c14cfd6671bb04045c4cbd4be2d4a184fc01c1f0a73edec6acc101"
            ):
                # Check wrapper_sha256 exact string
                if desc.get("wrapper_sha256") != "4a08b2e0d8c14cfd6671bb04045c4cbd4be2d4a184fc01c1f0a73edec3acc101":
                    descriptor_anomalies.append((b_num, aid, desc))

            inst = desc.get("instance_id", "unknown")
            if inst not in instance_ids:
                instance_ids[inst] = {
                    "count": 0,
                    "first_attempt_id": aid,
                    "first_batch": b_num,
                    "last_attempt_id": aid,
                    "last_batch": b_num,
                    "model_load_seconds": desc.get("model_load_seconds"),
                }
            instance_ids[inst]["count"] += 1
            instance_ids[inst]["last_attempt_id"] = aid
            instance_ids[inst]["last_batch"] = b_num

            total_rec_input_tokens += rec["input_tokens"]
            total_rec_padded_tokens += rec["padded_tokens"]
            total_client_elapsed += rec["client_elapsed_seconds"]
            total_remote_elapsed += rec["remote_elapsed_seconds"]
            total_gpu_pool_elapsed += rec["gpu_model_pool_seconds"]
            max_peak_allocated = max(max_peak_allocated, rec["peak_allocated_bytes"])
            max_peak_reserved = max(max_peak_reserved, rec["peak_reserved_bytes"])
            device_total_bytes_set.add(rec["device_total_bytes"])

        # Check details of the batch that had a non-success attempt
        non_success_batch_history = []
        for ns in non_success_attempts:
            b_label = ns["batch"]
            rows = led_db.execute(
                "SELECT id, batch, phase, started, elapsed, status, requests, tokens, error FROM attempts WHERE batch = ? ORDER BY id",
                (b_label,),
            ).fetchall()
            non_success_batch_history.append({
                "batch": b_label,
                "attempts_for_this_batch": [
                    {
                        "id": r[0],
                        "batch": r[1],
                        "phase": r[2],
                        "started_utc": ts_iso(r[3]),
                        "elapsed": r[4],
                        "status": r[5],
                        "requests": r[6],
                        "tokens": r[7],
                        "error": r[8],
                    }
                    for r in rows
                ],
            })

        # 4. Invocations timeline
        invocations = []
        for p in sorted((RUN_DIR / "invocations").glob("*.json")):
            data = json.loads(p.read_bytes())
            invocations.append({
                "file": p.name,
                "finished_utc": ns_iso(p.stem),
                "data": data,
            })

        out = {
            "schedule_summary": {
                "total_batches": len(expected_batches),
                "total_passages": total_passages,
                "last_batch_size": expected_batches[6495]["doc_count"],
                "total_input_tokens": total_sched_input_tokens,
                "total_padded_tokens": total_sched_padded_tokens,
                "padding_ratio": total_sched_padded_tokens / total_sched_input_tokens,
            },
            "full_batches_table": {
                "row_count": fb_row[0],
                "min_batch": fb_row[1],
                "max_batch": fb_row[2],
                "committed_eq_1": fb_row[3],
                "committed_ne_1": fb_row[4] or 0,
                "distinct_committed_batches": fb_distinct,
            },
            "ledger_status_summary": status_summary,
            "non_success_attempts": non_success_attempts,
            "non_success_batch_history": non_success_batch_history,
            "reconciliation": {
                "unique_successful_batches": len(success_by_batch),
                "all_6496_batches_succeeded_exactly_once": (
                    len(success_by_batch) == 6496
                    and set(success_by_batch.keys()) == set(range(6496))
                    and len(duplicate_success_batches) == 0
                ),
                "duplicate_success_batches": duplicate_success_batches,
                "token_mismatches": token_mismatches,
                "padded_mismatches": padded_mismatches,
                "hash_count_mismatches": hash_count_mismatches,
                "descriptor_anomalies": descriptor_anomalies,
                "receipt_sum_input_tokens": total_rec_input_tokens,
                "receipt_sum_padded_tokens": total_rec_padded_tokens,
                "receipt_padding_ratio": total_rec_padded_tokens / total_rec_input_tokens,
                "total_client_elapsed_seconds": total_client_elapsed,
                "total_remote_elapsed_seconds": total_remote_elapsed,
                "total_gpu_model_pool_seconds": total_gpu_pool_elapsed,
                "total_rpc_and_transfer_overhead_seconds": total_client_elapsed - total_remote_elapsed,
                "max_peak_allocated_bytes": max_peak_allocated,
                "max_peak_reserved_bytes": max_peak_reserved,
                "device_total_bytes": sorted(device_total_bytes_set),
                "allocated_headroom_fraction_at_peak": (
                    1.0 - (max_peak_allocated / min(device_total_bytes_set)) if device_total_bytes_set else None
                ),
                "reserved_headroom_fraction_at_peak": (
                    1.0 - (max_peak_reserved / min(device_total_bytes_set)) if device_total_bytes_set else None
                ),
                "modal_container_instances": instance_ids,
                "timeline_gaps_and_ boundaries": gaps,
            },
            "invocations": invocations,
        }

        out_path = REV_DIR / "ledger_and_schedule_audit.json"
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "OK",
            "unique_successful_batches": len(success_by_batch),
            "non_success_count": len(non_success_attempts),
            "receipt_sum_input_tokens": total_rec_input_tokens,
            "receipt_sum_padded_tokens": total_rec_padded_tokens,
        }))
    finally:
        lex_db.close()
        led_db.close()


if __name__ == "__main__":
    main()
