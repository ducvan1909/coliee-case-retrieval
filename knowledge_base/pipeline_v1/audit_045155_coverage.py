"""Audit canonical Plan 09 model-silver coverage for case 045155 after batch b15."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from knowledge_base.pipeline_v1.au_gold.core import atomic_write, load_json, validate_model_proposal
from knowledge_base.pipeline_v1.source_contract import open_source


P = Path("knowledge_base/pipeline_v1")
ROOT = P / "outputs/plan09_au_gold_v1"
CASE_ID = "045155"


def main() -> None:
    workload = load_json(ROOT / "au_annotation_build_manifest.json")
    row = next(item for item in workload["cases"] if item["case_id"] == CASE_ID)
    packet = load_json(ROOT / row["packet_ref"])
    policy = load_json(P / "policies/au_annotation_policy.v1.json")
    source = open_source(workload["source_store"], CASE_ID, packet["source_hash"])
    proposal_manifest = load_json(ROOT / "terra_proposal_manifest.json")
    records = [item for item in proposal_manifest["proposals"] if item["case_id"] == CASE_ID]
    proposals = [load_json(ROOT / item["proposal_ref"]) for item in records]
    validations = [validate_model_proposal(item, packet, source, policy) for item in proposals]
    reviews = [review for proposal in proposals for review in proposal["target_reviews"]]
    owners = Counter(review["target_id"] for review in reviews)
    expected = {task["target_id"] for task in packet["tasks"]}
    observed = set(owners)
    defect = load_json(P / "reports/plan09_scheduling_defect_045155_310f.json")
    value = {
        "artifact_type": "Plan09CaseModelSilverCoverageAudit",
        "audit_version": "plan09-case-coverage-v1",
        "case_id": CASE_ID,
        "source_hash": packet["source_hash"],
        "coverage_scope": "canonical checkpoint proposals referenced by terra_proposal_manifest only",
        "semantic_gold": False,
        "evaluation_boundary": "model_silver",
        "expected_target_count": len(expected),
        "canonical_reviewed_target_count": len(reviews),
        "unique_reviewed_target_count": len(observed),
        "authority_unit_count": sum(len(review["authority_units"]) for review in reviews),
        "hard_negative_count": sum(review["hard_negative"] is not None for review in reviews),
        "unresolved_target_count": sum(review["model_outcome"] == "unresolved" for review in reviews),
        "duplicate_target_ids": sorted(target_id for target_id, count in owners.items() if count > 1),
        "missing_target_ids": sorted(expected - observed),
        "extra_target_ids": sorted(observed - expected),
        "canonical_proposal_ids": [proposal["proposal_id"] for proposal in proposals],
        "all_canonical_proposals_valid": len(validations) == len(proposals),
        "scheduling_defect": {
            "audit_ref": str((P / "reports/plan09_scheduling_defect_045155_310f.json").resolve()),
            "status": defect["status"],
            "resolution": defect["resolution"],
            "canonical_owner_proposal_id": defect["canonical_owner_proposal_id"],
            "repair_targets": defect["remaining_target_ids"],
            "repair_targets_have_single_owner": all(owners[target_id] == 1 for target_id in defect["remaining_target_ids"]),
            "duplicate_target_has_single_owner": owners[defect["duplicate_target_id"]] == 1,
        },
    }
    value["coverage_status"] = "complete_no_duplicate_or_missing" if not value["duplicate_target_ids"] and not value["missing_target_ids"] and not value["extra_target_ids"] else "coverage_incomplete_or_conflicted"
    output = ROOT / "coverage_045155_post_b15.json"
    atomic_write(output, value)
    print(value)


if __name__ == "__main__":
    main()
