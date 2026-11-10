"""Deterministic sampling manifest generator for M1 independent review.

Seed: 20261105
Exclusions:
- M0 cohort discovery queries (10)
- M0 cohort holdout queries (10)
- Exposed diagnostic fixtures (3): 061295.txt, 067620.txt, 062436.txt

Sample groups:
1. 12 cases uniformly random from eligible pool.
2. Up to 12 risk-based cases across 4 structural risk categories (3 per group):
   a. High quote-marker candidate count.
   b. Numbering reset or suspected bilingual.
   c. High unnumbered bytes fraction.
   d. Heading candidates or possible quotation at outer sequence.
Deduplicated against random sample and preceding risk groups.
"""

import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[4]
M0_BUNDLE = ROOT / "pipeline_v2" / "artifacts" / "m0_20261105_v2"
M1_BUNDLE = ROOT / "pipeline_v2" / "artifacts" / "m1_20261105_v1"
OUTPUT_PATH = ROOT / "pipeline_v2" / "reviews" / "m1_review_v1" / "sampling_manifest.json"

SEED = 20261105
EXPOSED_FIXTURES = ["061295.txt", "067620.txt", "062436.txt"]


def generate_manifest():
    with open(M0_BUNDLE / "inventory.json", "r", encoding="utf-8") as f:
        inventory = json.load(f)
    with open(M0_BUNDLE / "cohort.json", "r", encoding="utf-8") as f:
        cohort = json.load(f)

    discovery_queries = set(cohort.get("discovery_queries", []))
    holdout_queries = set(cohort.get("holdout_queries", []))
    excluded = discovery_queries | holdout_queries | set(EXPOSED_FIXTURES)

    all_cases = [s["case_id"] for s in inventory["sources"]]
    eligible = sorted(c for c in all_cases if c not in excluded)

    print(f"Total sources: {len(all_cases)}")
    print(f"Excluded: {len(excluded)} (Discovery: {len(discovery_queries)}, Holdout: {len(holdout_queries)}, Fixtures: {len(EXPOSED_FIXTURES)})")
    print(f"Eligible pool: {len(eligible)}")

    # 1. 12 uniform random cases
    rng_random = random.Random(SEED)
    random_sample = sorted(rng_random.sample(eligible, 12))

    # Read M1 structural summary / source records for risk statistics
    # To avoid loading all 7708 files if slow, we can scan registry and sources
    print("Gathering case metrics for risk sampling...")
    risk_stats = {}
    sources_dir = M1_BUNDLE / "sources"
    for case_id in eligible:
        stem = case_id[:-4]
        source_json = sources_dir / f"{stem}.json"
        with open(source_json, "r", encoding="utf-8") as f:
            rec = json.load(f)

        sidecars_count = len(rec.get("sidecars", []))
        total_bytes = rec["byte_length"]
        unnumbered_bytes = sum(
            u["span_bytes"][1] - u["span_bytes"][0]
            for u in rec["units"]
            if u["unit_kind"] == "unnumbered"
        )
        unnumbered_ratio = unnumbered_bytes / total_bytes if total_bytes > 0 else 0.0

        all_uncertainties = set()
        for u in rec["units"]:
            all_uncertainties.update(u.get("uncertainties", []))

        heading_candidate_count = sum(
            1 for u in rec["units"] if "heading_candidate" in u.get("uncertainties", [])
        )
        has_outer_quote_risk = "possible_quotation_at_outer_sequence" in all_uncertainties
        has_reset_risk = bool(
            {"translation_boundary_observed", "numbering_reset_language_unknown"}.intersection(all_uncertainties)
        )

        risk_stats[case_id] = {
            "case_id": case_id,
            "sidecars_count": sidecars_count,
            "unnumbered_ratio": unnumbered_ratio,
            "unnumbered_bytes": unnumbered_bytes,
            "total_bytes": total_bytes,
            "has_reset_risk": has_reset_risk,
            "heading_candidate_count": heading_candidate_count,
            "has_outer_quote_risk": has_outer_quote_risk,
            "all_uncertainties": sorted(all_uncertainties),
        }

    already_selected = set(random_sample)
    risk_sample = []

    # Risk Group A: Top quote-marker candidates (sidecars_count >= 10, sorted desc, sampled)
    group_a_pool = sorted(
        [c for c in eligible if c not in already_selected and risk_stats[c]["sidecars_count"] >= 10],
        key=lambda c: (-risk_stats[c]["sidecars_count"], c)
    )
    rng_a = random.Random(SEED + 1)
    # Pick 3 from the top 30
    group_a_candidates = group_a_pool[:30]
    group_a_picked = sorted(rng_a.sample(group_a_candidates, min(3, len(group_a_candidates))))
    for c in group_a_picked:
        already_selected.add(c)
        risk_sample.append({
            "case_id": c,
            "group": "risk_a_high_quote_markers",
            "metric": f"sidecars={risk_stats[c]['sidecars_count']}",
            "rationale": "High quote-marker count; test if outer paragraphs are swallowed as nested sidecars."
        })

    # Risk Group B: Numbering reset or suspected bilingual
    group_b_pool = sorted(
        [c for c in eligible if c not in already_selected and risk_stats[c]["has_reset_risk"]],
        key=lambda c: c
    )
    rng_b = random.Random(SEED + 2)
    group_b_picked = sorted(rng_b.sample(group_b_pool, min(3, len(group_b_pool))))
    for c in group_b_picked:
        already_selected.add(c)
        flags = [u for u in risk_stats[c]["all_uncertainties"] if "reset" in u or "translation" in u]
        risk_sample.append({
            "case_id": c,
            "group": "risk_b_reset_or_bilingual",
            "metric": f"uncertainties={','.join(flags)}",
            "rationale": "Numbering reset or bilingual transition; test if [1] reset separates EN/FR or misattributes language."
        })

    # Risk Group C: High unnumbered bytes fraction
    # Threshold: unnumbered_ratio > 0.15 (15%)
    group_c_pool = sorted(
        [c for c in eligible if c not in already_selected and risk_stats[c]["unnumbered_ratio"] > 0.15],
        key=lambda c: (-risk_stats[c]["unnumbered_ratio"], c)
    )
    rng_c = random.Random(SEED + 3)
    group_c_candidates = group_c_pool[:30]
    group_c_picked = sorted(rng_c.sample(group_c_candidates, min(3, len(group_c_candidates))))
    for c in group_c_picked:
        already_selected.add(c)
        risk_sample.append({
            "case_id": c,
            "group": "risk_c_high_unnumbered_ratio",
            "metric": f"unnumbered_ratio={risk_stats[c]['unnumbered_ratio']:.2%}",
            "rationale": "High unnumbered bytes fraction; test whether unnumbered regions are valid headers/unstructured text or lost paragraphs."
        })

    # Risk Group D: Heading candidates or possible quotation at outer sequence
    group_d_pool = sorted(
        [
            c for c in eligible
            if c not in already_selected and (
                risk_stats[c]["heading_candidate_count"] >= 3 or risk_stats[c]["has_outer_quote_risk"]
            )
        ],
        key=lambda c: (-risk_stats[c]["heading_candidate_count"], c)
    )
    rng_d = random.Random(SEED + 4)
    group_d_candidates = group_d_pool[:30]
    group_d_picked = sorted(rng_d.sample(group_d_candidates, min(3, len(group_d_candidates))))
    for c in group_d_picked:
        already_selected.add(c)
        risk_sample.append({
            "case_id": c,
            "group": "risk_d_heading_or_outer_quote",
            "metric": f"heading_candidates={risk_stats[c]['heading_candidate_count']}, outer_quote_risk={risk_stats[c]['has_outer_quote_risk']}",
            "rationale": "Heading candidates or outer quote collision; test whether headings are true headings vs party names, and whether outer quotes collide."
        })

    manifest = {
        "schema_version": "pipeline-v2-m1-review-sampling-1",
        "seed": SEED,
        "eligibility": {
            "total_sources": len(all_cases),
            "excluded_discovery_queries_count": len(discovery_queries),
            "excluded_holdout_queries_count": len(holdout_queries),
            "excluded_exposed_fixtures_count": len(EXPOSED_FIXTURES),
            "excluded_case_ids": sorted(list(excluded)),
            "eligible_count": len(eligible)
        },
        "random_sample": [
            {
                "case_id": c,
                "selection_method": "uniform_random",
                "seed": SEED,
                "metrics": {
                    "sidecars": risk_stats[c]["sidecars_count"],
                    "unnumbered_ratio": round(risk_stats[c]["unnumbered_ratio"], 4),
                    "total_bytes": risk_stats[c]["total_bytes"]
                }
            }
            for c in random_sample
        ],
        "risk_sample": risk_sample,
        "total_reviewed_cases": len(random_sample) + len(risk_sample)
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"Saved sampling manifest to {OUTPUT_PATH}")
    print(f"Total cases selected: {len(random_sample)} random + {len(risk_sample)} risk = {manifest['total_reviewed_cases']}")


if __name__ == "__main__":
    generate_manifest()
