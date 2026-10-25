"""Create a resumable, evidence-based Plan 09 model-silver progress snapshot."""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from .core import AnnotationError, atomic_write, load_json


def build_progress(output_root: Path, blocker: str | None = None):
    root = Path(output_root)
    build = load_json(root / "au_annotation_build_manifest.json")
    from .remediation import proposal_records
    proposals = {'proposals':proposal_records(root)}
    expected = {}
    for case in build["cases"]:
        packet = load_json(root / case["packet_ref"])
        expected[case["case_id"]] = {task["target_id"] for task in packet["tasks"]}

    owners = defaultdict(list)
    counts = defaultdict(lambda: {"proposal_count": 0, "reviewed_target_count": 0,
                                  "authority_unit_count": 0, "hard_negative_count": 0,
                                  "unresolved_target_count": 0})
    from .remediation import effective_proposals, registry
    effective = {x['proposal_id']:x for x in effective_proposals(root)} if (root/'semantic_defect_registry.json').exists() else {}
    for record in proposals["proposals"]:
        value = effective.get(record['proposal_id']) or load_json(root / record["proposal_ref"])
        case_id = record["case_id"]
        counts[case_id]["proposal_count"] += 1
        for review in value["target_reviews"]:
            owners[(case_id, review["target_id"])].append(record["proposal_id"])
            counts[case_id]["reviewed_target_count"] += 1
            counts[case_id]["authority_unit_count"] += len(review.get("authority_units", []))
            counts[case_id]["hard_negative_count"] += review.get("hard_negative") is not None
            counts[case_id]["unresolved_target_count"] += review.get("model_outcome") == "unresolved"

    duplicate = [{"case_id": case_id, "target_id": target_id, "proposal_ids": ids}
                 for (case_id, target_id), ids in sorted(owners.items()) if len(ids) > 1]
    if duplicate:
        raise AnnotationError("canonical proposals contain duplicate target ownership",
                              code="progress_duplicate_target")

    cases = []
    for case_id in sorted(expected):
        reviewed = {target_id for cid, target_id in owners if cid == case_id}
        missing = sorted(expected[case_id] - reviewed)
        row = {"case_id": case_id, "expected_target_count": len(expected[case_id]),
               **counts[case_id], "missing_target_count": len(missing),
               "missing_target_ids": missing,
               "coverage_complete": not missing}
        cases.append(row)
    reviewed_total = sum(row["reviewed_target_count"] for row in cases)
    expected_total = sum(row["expected_target_count"] for row in cases)
    result = {"artifact_type": "Plan09ModelSilverProgress",
            "progress_version": "plan09-model-silver-progress-v1",
            "status": "complete" if reviewed_total == expected_total else "partial_resumable",
            "semantic_gold": False, "evaluation_against": "model_silver",
            "blocker": blocker, "expected_target_count": expected_total,
            "reviewed_target_count": reviewed_total,
            "missing_target_count": expected_total - reviewed_total,
            "authority_unit_count": sum(row["authority_unit_count"] for row in cases),
            "hard_negative_count": sum(row["hard_negative_count"] for row in cases),
            "unresolved_target_count": sum(row["unresolved_target_count"] for row in cases),
            "canonical_duplicate_target_count": 0, "cases": cases}
    if (root/'semantic_defect_registry.json').exists():
        findings = registry(root)['findings']
        result['semantic_remediation'] = {'quarantined_target_count':len({(x['case_id'],x['target_id']) for x in findings if x['status']!='closed'}), 'open_severe_finding_count':sum(x['severity']=='severe' and x['status']!='closed' for x in findings), 'amendment_count':len(list((root/'model_amendments').glob('*.json'))), 'semantic_pass':False, 'plan10_allowed':False}
        from .remediation import scan_attribution_risks
        queue = scan_attribution_risks(root)
        result['semantic_remediation'].update(risk_item_count=queue['item_count'], risk_reviewed_count=queue['item_count']-queue['pending_model_review_count'], risk_pending_count=queue['pending_model_review_count'])
        if (root/'r3_completion.json').exists():
            from .r3_completion import validate_completion
            completion = validate_completion(root)
            result['semantic_remediation'].update(r3_status=completion['r3_status'], r3_independent_model_acceptance=True)
            result['gates'] = {'r3_pass':True, 'r4_coverage_complete':not result['missing_target_count'], 'r5_final_audit_pass':False, 'plan10_allowed':False}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blocker")
    args = parser.parse_args()
    value = build_progress(args.output_root, args.blocker)
    atomic_write(args.output, value)
    print(f"written={args.output} reviewed={value['reviewed_target_count']} "
          f"missing={value['missing_target_count']} status={value['status']}")


if __name__ == "__main__":
    main()
