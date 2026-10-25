"""Checkpoint Plan 09 model-silver batch terra-702a4d30648c93f1d24a7f5c."""
from __future__ import annotations

from pathlib import Path

from knowledge_base.pipeline_v1.au_gold.build import checkpoint_model_proposal
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, atomic_write, exact_span, load_json, model_review_trace
from knowledge_base.pipeline_v1.source_contract import open_source


P = Path("knowledge_base/pipeline_v1")
ROOT = P / "outputs/plan09_au_gold_v1"
CASE_ID = "045155"
BATCH_ID = "terra-702a4d30648c93f1d24a7f5c"
PROPOSAL_ID = "terra-045155-702a4d30648c93f1d24a7f5c"


def main() -> None:
    manifest = load_json(ROOT / "au_annotation_build_manifest.json")
    row = next(item for item in manifest["cases"] if item["case_id"] == CASE_ID)
    packet = load_json(ROOT / row["packet_ref"])
    policy = load_json(P / "policies/au_annotation_policy.v1.json")
    source = open_source(manifest["source_store"], CASE_ID, packet["source_hash"])
    batches = load_json(ROOT / "terra_annotation_batches.json")
    batch = next(item for item in batches["batches"] if item["batch_id"] == BATCH_ID)
    tasks = {item["target_id"]: item for item in packet["tasks"]}
    if batch["case_id"] != CASE_ID:
        raise AnnotationError("unexpected case for batch")
    existing = load_json(ROOT / "terra_proposal_manifest.json")
    owned = set()
    for record in existing["proposals"]:
        proposal = load_json(ROOT / record["proposal_ref"])
        owned.update(review["target_id"] for review in proposal["target_reviews"])
    duplicate = sorted(owned & set(batch["target_ids"]))
    if duplicate:
        raise AnnotationError("target already has a canonical owner: " + ", ".join(duplicate))

    provenance = {"source_type": "model", "producer_id": "model:gpt-5.6-terra", "prompt_version": policy["terra_prompt_version"]}
    reviews = []
    for target_id in batch["target_ids"]:
        task = tasks[target_id]
        target = task["target_span"]
        reviewed_span = exact_span(source, CASE_ID, packet["source_hash"], target["start_char"], target["end_char"])
        review = {
            "target_id": target_id,
            "review_complete": True,
            "reviewed_span": reviewed_span,
            "authority_units": [],
            "hard_negative": {
                "reason": "editorial",
                "reviewed_span": reviewed_span,
                "provenance": provenance,
                "notes": ["Full-target/context review: editorial headnote taxonomy or cross-reference, not a legal proposition in the court's reasons."],
            },
            "notes": [],
            "model_outcome": "hard_negative",
            "unresolved_reasons": [],
        }
        review["review_trace"] = model_review_trace(task, source, packet["source_hash"], review)
        review["review_trace"]["region_id"] = batch["region_id"]
        review["review_trace"]["region_fingerprint"] = batch["region_fingerprint"]
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
        "batch_id": BATCH_ID,
        "status": "model_proposed",
        "target_reviews": reviews,
    }
    atomic_write(ROOT / "stage_045155_b14.json", proposal)
    print(checkpoint_model_proposal(proposal=proposal, output_root=ROOT, source_store=manifest["source_store"], policy=policy))


if __name__ == "__main__":
    main()
