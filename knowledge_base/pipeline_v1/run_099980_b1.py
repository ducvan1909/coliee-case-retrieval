"""Checkpoint the first canonical Plan 09 model-silver batch for case 099980."""
from __future__ import annotations

from pathlib import Path

from knowledge_base.pipeline_v1.au_gold.build import checkpoint_model_proposal
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, atomic_write, exact_span, load_json, model_review_trace
from knowledge_base.pipeline_v1.source_contract import open_source


P = Path("knowledge_base/pipeline_v1")
ROOT = P / "outputs/plan09_au_gold_v1"
CASE_ID = "099980"
BATCH_ID = "terra-b553fd82abea92ec418766f4"
PROPOSAL_ID = "terra-099980-b553fd82abea92ec418766f4"


def span_for(source: str, packet: dict, task: dict, quote: str) -> dict:
    target = task["target_span"]
    try:
        start = source.index(quote, target["start_char"], target["end_char"])
    except ValueError as exc:
        raise AnnotationError(f"evidence quote not found in {task['target_id']}") from exc
    return exact_span(source, CASE_ID, packet["source_hash"], start, start + len(quote))


def au(task: dict, evidence: dict, claim: str, kind: str, provenance: dict) -> dict:
    return {"au_id": "terra-" + task["target_id"], "owner_target_id": task["target_id"], "owner_block_id": task["owner_block_id"], "claim_text": claim, "kind": kind, "other_kind": "dignity_principle" if kind == "other" else None, "evidence_spans": [evidence], "attributions": [{"role": "proposition", "speaker": "current_court", "evidence_span": evidence}], "condition_spans": [], "exception_spans": [], "limit_spans": [], "cross_block_refs": [], "overlap_disposition": "none", "duplicate_of": None, "status": "model_proposed", "provenance": provenance, "notes": [], "uncertainty": "medium", "unresolved_reasons": []}


def main() -> None:
    manifest = load_json(ROOT / "au_annotation_build_manifest.json")
    row = next(item for item in manifest["cases"] if item["case_id"] == CASE_ID)
    packet = load_json(ROOT / row["packet_ref"])
    policy = load_json(P / "policies/au_annotation_policy.v1.json")
    source = open_source(manifest["source_store"], CASE_ID, packet["source_hash"])
    batch = next(item for item in load_json(ROOT / "terra_annotation_batches.json")["batches"] if item["batch_id"] == BATCH_ID)
    tasks = {item["target_id"]: item for item in packet["tasks"]}
    proposal_manifest = load_json(ROOT / "terra_proposal_manifest.json")
    owned = set()
    for record in proposal_manifest["proposals"]:
        prior = load_json(ROOT / record["proposal_ref"])
        owned.update(review["target_id"] for review in prior["target_reviews"])
    duplicate = sorted(owned & set(batch["target_ids"]))
    if duplicate:
        raise AnnotationError("target already has a canonical owner: " + ", ".join(duplicate))

    provenance = {"source_type": "model", "producer_id": "model:gpt-5.6-terra", "prompt_version": policy["terra_prompt_version"]}
    decisions = {
        "at-2454459151de331cb22ede05": ("Canadian case law has traditionally recognized the central role of work as an element of an individual's dignity:", "Canadian case law recognizes work's central role in individual dignity.", "other"),
        "at-817a9f8675423557e9f188bb": ("Fraud is the ultimate accusation that can lead to the highest form of punishment: the loss of confidence by the employer and the public in the personal integrity of the public servant.", "A fraud accusation can cause loss of employer and public confidence in a public servant's integrity.", "fact_pattern_rule"),
        "at-98b768da12594aef0985f6e0": ("the reputation of the public servants involved is likely to be irrevocably damaged by the public release of the impugned decision and the impugned investigation report", "Public release of the impugned decision and investigation report is likely to cause irreparable reputational damage to the affected public servants.", "fact_pattern_rule"),
        "at-a06b35624ad726cb3a99a493": ("the public servants affected by the impugned order have the right to be presumed innocent.", "Public servants affected by the order retain the right to be presumed innocent.", "procedural_rule"),
    }
    reviews = []
    for target_id in batch["target_ids"]:
        task = tasks[target_id]
        target = task["target_span"]
        reviewed = exact_span(source, CASE_ID, packet["source_hash"], target["start_char"], target["end_char"])
        quote, claim, kind = decisions[target_id]
        evidence = span_for(source, packet, task, quote)
        unit = au(task, evidence, claim, kind, provenance)
        review = {"target_id": target_id, "review_complete": True, "reviewed_span": reviewed, "authority_units": [unit], "hard_negative": None, "notes": [], "model_outcome": "positive", "unresolved_reasons": []}
        review["review_trace"] = model_review_trace(task, source, packet["source_hash"], review)
        review["review_trace"]["region_id"] = batch["region_id"]
        review["review_trace"]["region_fingerprint"] = batch["region_fingerprint"]
        reviews.append(review)
    proposal = {"artifact_type": "TerraAUProposal", "schema_version": "terra-au-proposal-v1", "proposal_id": PROPOSAL_ID, "packet_id": packet["packet_id"], "case_id": CASE_ID, "source_hash": packet["source_hash"], "producer": {"source_type": "model", "producer_id": "model:gpt-5.6-terra", "model": "gpt-5.6-terra", "reasoning_effort": "low"}, "prompt_version": policy["terra_prompt_version"], "batch_id": BATCH_ID, "status": "model_proposed", "target_reviews": reviews}
    atomic_write(ROOT / "stage_099980_b1.json", proposal)
    print(checkpoint_model_proposal(proposal=proposal, output_root=ROOT, source_store=manifest["source_store"], policy=policy))


if __name__ == "__main__":
    main()
