"""Checkpoint the final Plan 09 model-silver batch for case 045155."""
from __future__ import annotations

from pathlib import Path

from knowledge_base.pipeline_v1.au_gold.build import checkpoint_model_proposal
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, atomic_write, exact_span, load_json, model_review_trace
from knowledge_base.pipeline_v1.source_contract import open_source


P = Path("knowledge_base/pipeline_v1")
ROOT = P / "outputs/plan09_au_gold_v1"
CASE_ID = "045155"
BATCH_ID = "terra-9cd2459b921aa85c81cc7f3a"
PROPOSAL_ID = "terra-045155-9cd2459b921aa85c81cc7f3a"


def source_span(source: str, packet: dict, task: dict, needle: str) -> dict:
    target = task["target_span"]
    try:
        start = source.index(needle, target["start_char"], target["end_char"])
    except ValueError as exc:
        raise AnnotationError(f"evidence needle not found for {task['target_id']}") from exc
    end = start + len(needle)
    return exact_span(source, CASE_ID, packet["source_hash"], start, end)


def authority_unit(target_id: str, task: dict, span: dict, claim_text: str, kind: str, provenance: dict) -> dict:
    return {
        "au_id": f"terra-{target_id}",
        "owner_target_id": target_id,
        "owner_block_id": task["owner_block_id"],
        "claim_text": claim_text,
        "kind": kind,
        "other_kind": None,
        "evidence_spans": [span],
        "attributions": [{"role": "proposition", "speaker": "current_court", "evidence_span": span}],
        "condition_spans": [],
        "exception_spans": [],
        "limit_spans": [],
        "cross_block_refs": [],
        "overlap_disposition": "none",
        "duplicate_of": None,
        "status": "model_proposed",
        "provenance": provenance,
        "notes": [],
        "uncertainty": "low",
        "unresolved_reasons": [],
    }


def main() -> None:
    manifest = load_json(ROOT / "au_annotation_build_manifest.json")
    row = next(item for item in manifest["cases"] if item["case_id"] == CASE_ID)
    packet = load_json(ROOT / row["packet_ref"])
    policy = load_json(P / "policies/au_annotation_policy.v1.json")
    source = open_source(manifest["source_store"], CASE_ID, packet["source_hash"])
    batches = load_json(ROOT / "terra_annotation_batches.json")
    batch = next(item for item in batches["batches"] if item["batch_id"] == BATCH_ID)
    tasks = {item["target_id"]: item for item in packet["tasks"]}
    owned = set()
    proposal_manifest = load_json(ROOT / "terra_proposal_manifest.json")
    for record in proposal_manifest["proposals"]:
        prior = load_json(ROOT / record["proposal_ref"])
        owned.update(review["target_id"] for review in prior["target_reviews"])
    duplicate = sorted(owned & set(batch["target_ids"]))
    if duplicate:
        raise AnnotationError("target already has a canonical owner: " + ", ".join(duplicate))

    provenance = {"source_type": "model", "producer_id": "model:gpt-5.6-terra", "prompt_version": policy["terra_prompt_version"]}
    plans = {
        "at-7069994e3f8066109177f30d": (
            "In my view, the Correctional Service cannot avoid its obligations to inmates by means of an agreement with third parties.",
            "The Correctional Service cannot avoid its obligations to inmates through agreements with third parties.",
            "holding",
        ),
        "at-923a3aae96b77d61178e6d57": (
            "it does not specify which of the three grounds referred to under subsection 27(3) is relied upon. As a result, there has been a failure to provide the applicant with the information which was relied upon in coming to the decision.",
            "Failure to identify the relied-on subsection 27(3) ground meant the applicant was not given information relied on for the decision.",
            "holding",
        ),
        "at-c02c285269ade716ae8780ec": (
            None,
            None,
            None,
        ),
        "at-cb76ab9c2002369af7957e6e": (
            "Section 27 contemplates that one who is in receipt of a written decision is entitled to be given the material which was relied upon in coming to that decision.",
            "Section 27 entitles a recipient of a written decision to the material relied on in reaching it.",
            "statutory_hook",
        ),
    }
    reviews = []
    for target_id in batch["target_ids"]:
        task = tasks[target_id]
        target = task["target_span"]
        reviewed_span = exact_span(source, CASE_ID, packet["source_hash"], target["start_char"], target["end_char"])
        needle, claim_text, kind = plans[target_id]
        if needle is None:
            review = {"target_id": target_id, "review_complete": True, "reviewed_span": reviewed_span, "authority_units": [], "hard_negative": {"reason": "party_argument_only", "reviewed_span": reviewed_span, "provenance": provenance, "notes": ["Full-target/context review: respondent argument and factual account only; no current-court proposition occurs in this span."]}, "notes": [], "model_outcome": "hard_negative", "unresolved_reasons": []}
        else:
            evidence = source_span(source, packet, task, needle)
            unit = authority_unit(target_id, task, evidence, claim_text, kind, provenance)
            review = {"target_id": target_id, "review_complete": True, "reviewed_span": reviewed_span, "authority_units": [unit], "hard_negative": None, "notes": [], "model_outcome": "positive", "unresolved_reasons": []}
        review["review_trace"] = model_review_trace(task, source, packet["source_hash"], review)
        review["review_trace"]["region_id"] = batch["region_id"]
        review["review_trace"]["region_fingerprint"] = batch["region_fingerprint"]
        reviews.append(review)
    proposal = {"artifact_type": "TerraAUProposal", "schema_version": "terra-au-proposal-v1", "proposal_id": PROPOSAL_ID, "packet_id": packet["packet_id"], "case_id": CASE_ID, "source_hash": packet["source_hash"], "producer": {"source_type": "model", "producer_id": "model:gpt-5.6-terra", "model": "gpt-5.6-terra", "reasoning_effort": "low"}, "prompt_version": policy["terra_prompt_version"], "batch_id": BATCH_ID, "status": "model_proposed", "target_reviews": reviews}
    atomic_write(ROOT / "stage_045155_b15.json", proposal)
    print(checkpoint_model_proposal(proposal=proposal, output_root=ROOT, source_store=manifest["source_store"], policy=policy))


if __name__ == "__main__":
    main()
