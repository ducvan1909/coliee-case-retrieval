"""Materialize the Plan 09 repair-only model-silver checkpoint for case 045155.

This is intentionally a one-off recovery script.  It does not modify the
canonical review that already owns at-5929ffb989b919cd1334a0d2.
"""
from __future__ import annotations

from pathlib import Path

from knowledge_base.pipeline_v1.au_gold.build import checkpoint_model_proposal
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, atomic_write, exact_span, load_json, model_review_trace
from knowledge_base.pipeline_v1.source_contract import open_source


P = Path("knowledge_base/pipeline_v1")
ROOT = P / "outputs/plan09_au_gold_v1"
CASE_ID = "045155"
ORIGINAL_BATCH_ID = "terra-310f12c28675c91e3de45fa8"
REPAIR_BATCH_ID = "terra-repair-045155-310f-two-unreviewed-v1"
PROPOSAL_ID = "terra-045155-repair-310f-two-unreviewed-v1"
TARGET_IDS = ("at-995c41ba2d4afb50450e88b0", "at-ed0ed2032799316a320a9fd9")
CANONICAL_TARGET_ID = "at-5929ffb989b919cd1334a0d2"


def main() -> None:
    manifest = load_json(ROOT / "au_annotation_build_manifest.json")
    row = next(item for item in manifest["cases"] if item["case_id"] == CASE_ID)
    packet = load_json(ROOT / row["packet_ref"])
    policy = load_json(P / "policies/au_annotation_policy.v1.json")
    source = open_source(manifest["source_store"], CASE_ID, packet["source_hash"])
    batches = load_json(ROOT / "terra_annotation_batches.json")
    proposal_manifest = load_json(ROOT / "terra_proposal_manifest.json")
    original = next(item for item in batches["batches"] if item["batch_id"] == ORIGINAL_BATCH_ID)
    tasks = {item["target_id"]: item for item in packet["tasks"]}

    if tuple(original["target_ids"][1:]) != TARGET_IDS or original["target_ids"][0] != CANONICAL_TARGET_ID:
        raise AnnotationError("unexpected Plan 09 scheduling-defect target layout")
    seen = set()
    for record in proposal_manifest["proposals"]:
        existing = load_json(ROOT / record["proposal_ref"])
        seen.update(review["target_id"] for review in existing["target_reviews"])
    if CANONICAL_TARGET_ID not in seen:
        raise AnnotationError("canonical target owner is missing")
    collision = sorted(set(TARGET_IDS) & seen)
    if collision:
        raise AnnotationError("repair target already has a canonical owner: " + ", ".join(collision))
    if any(item["batch_id"] == REPAIR_BATCH_ID for item in batches["batches"]):
        raise AnnotationError("repair batch already exists")

    repair_batch = {
        **original,
        "batch_id": REPAIR_BATCH_ID,
        "target_ids": list(TARGET_IDS),
        "task_ids": [tasks[target_id]["task_id"] for target_id in TARGET_IDS],
        "execution_status": "repair_checkpointed_model_review",
        "repair_of_batch_id": ORIGINAL_BATCH_ID,
        "repair_reason": "Excluded target already checkpointed by canonical owner terra-045155-339e09ea6418d500f461afa8.",
    }
    batches["batches"].append(repair_batch)
    batches["batches"].sort(key=lambda item: (item["case_id"], item["region_id"], item["batch_id"]))
    batches["batch_count"] = len(batches["batches"])
    batches["status"] = "repair_batch_materialized"
    atomic_write(ROOT / "terra_annotation_batches.json", batches)

    provenance = {
        "source_type": "model",
        "producer_id": "model:gpt-5.6-terra",
        "prompt_version": policy["terra_prompt_version"],
    }
    review_notes = {
        TARGET_IDS[0]: "Full-target review: court narrative reproduces an administrative memorandum; no current-court legal proposition is stated in this span.",
        TARGET_IDS[1]: "Full-target review: procedural/factual account and Case Management Team position; no current-court legal proposition is stated in this span.",
    }
    reviews = []
    for target_id in TARGET_IDS:
        task = tasks[target_id]
        span = task["target_span"]
        reviewed_span = exact_span(source, CASE_ID, packet["source_hash"], span["start_char"], span["end_char"])
        review = {
            "target_id": target_id,
            "review_complete": True,
            "reviewed_span": reviewed_span,
            "authority_units": [],
            "hard_negative": {
                "reason": "fact_only",
                "reviewed_span": reviewed_span,
                "provenance": provenance,
                "notes": [review_notes[target_id]],
            },
            "notes": [],
            "model_outcome": "hard_negative",
            "unresolved_reasons": [],
        }
        review["review_trace"] = model_review_trace(task, source, packet["source_hash"], review)
        review["review_trace"]["region_id"] = repair_batch["region_id"]
        review["review_trace"]["region_fingerprint"] = repair_batch["region_fingerprint"]
        reviews.append(review)
    proposal = {
        "artifact_type": "TerraAUProposal",
        "schema_version": "terra-au-proposal-v1",
        "proposal_id": PROPOSAL_ID,
        "packet_id": packet["packet_id"],
        "case_id": CASE_ID,
        "source_hash": packet["source_hash"],
        "producer": {"source_type": "model", "producer_id": "model:gpt-5.6-terra", "model": "gpt-5.6-terra", "reasoning_effort": "low"},
        "prompt_version": policy["terra_prompt_version"],
        "batch_id": REPAIR_BATCH_ID,
        "status": "model_proposed",
        "target_reviews": reviews,
    }
    atomic_write(ROOT / "stage_045155_b13_repair.json", proposal)
    record = checkpoint_model_proposal(proposal=proposal, output_root=ROOT, source_store=manifest["source_store"], policy=policy)
    print(record)


if __name__ == "__main__":
    main()
