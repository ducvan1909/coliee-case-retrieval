"""Build sampling manifest and extract raw inspection context for M1 Revision 2 review.
Adheres strictly to sampling rules:
- Seed 20261105
- M0 cohort discovery and holdout query IDs excluded (no label access)
- 8 regression cases kept in separate exposed group
- 12 uniform random cases sampled from remaining pool
- Up to 12 risk cases from:
  * Group A: quotation relations / sidecars
  * Group B: translation boundaries (cues/tags)
  * Group C: headings (known uppercase / roman)
  * Group D: voice cue observations (I find / THIS COURT where role is unknown)
- Up to 3 regions per case with wide raw context (>= 300-600 chars before/after).
"""
import hashlib
import json
import random
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
M0_BUNDLE = REPO_ROOT / "pipeline_v2/artifacts/m0_20261105_v2"
M1_BUNDLE = REPO_ROOT / "pipeline_v2/artifacts/m1_20261105_v2"
CORPUS_DIR = REPO_ROOT / "data/task1_train_files_2026/cases"

SEED = 20261105

REGRESSION_CASES = [
    "000758.txt",
    "050936.txt",
    "000432.txt",
    "014069.txt",
    "046028.txt",
    "061295.txt",
    "067620.txt",
    "062436.txt",
]


def sha256_digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def generate_sampling():
    print("[1] Loading M0 inventory and cohort...")
    m0_inv = json.loads((M0_BUNDLE / "inventory.json").read_bytes().decode("utf-8"))
    all_case_ids = [s["case_id"] for s in m0_inv["sources"]]

    cohort = json.loads((M0_BUNDLE / "cohort.json").read_bytes().decode("utf-8"))
    discovery_queries = cohort.get("discovery_queries", [])
    holdout_queries = cohort.get("holdout_queries", [])

    exclusions = set(discovery_queries) | set(holdout_queries) | set(REGRESSION_CASES)
    eligible_cases = sorted([cid for cid in all_case_ids if cid not in exclusions])

    print(f"Total sources: {len(all_case_ids)}")
    print(f"Exclusions: {len(exclusions)} ({len(discovery_queries)} discovery + {len(holdout_queries)} holdout + {len(REGRESSION_CASES)} regression)")
    print(f"Eligible pool: {len(eligible_cases)}")

    rng = random.Random(SEED)
    random_12 = sorted(rng.sample(eligible_cases, 12))
    print(f"Random 12 cases: {random_12}")

    # Risk candidates selection:
    # Scan eligible cases to categorize candidates without modifying or tuning
    # A: sidecars > 0
    # B: translation cues / french regions > 0
    # C: uppercase headings > 0
    # D: voice cues > 0
    risk_pool_a = []  # quotation relations
    risk_pool_b = []  # translation cues
    risk_pool_c = []  # headings
    risk_pool_d = []  # voice cues

    for cid in eligible_cases:
        if cid in random_12:
            continue
        p = M1_BUNDLE / f"sources/{cid[:-4]}.json"
        rec = json.loads(p.read_bytes().decode("utf-8"))

        # Check A: sidecars
        if len(rec.get("sidecars", [])) > 0:
            risk_pool_a.append((len(rec["sidecars"]), cid))

        # Check B: language regions with fr
        fr_regs = [lr for lr in rec.get("language_regions", []) if lr["region_id"].startswith("fr")]
        if fr_regs:
            risk_pool_b.append((len(fr_regs), cid))

        # Check C: headings
        headings = [u for u in rec["units"] if u["unit_kind"] == "heading"]
        if headings:
            risk_pool_c.append((len(headings), cid))

        # Check D: voice cue observations
        voice_units = [u for u in rec["units"] if u.get("ownership_cue_observations")]
        if voice_units:
            risk_pool_d.append((len(voice_units), cid))

    # Deterministic selection for risk: sort by count descending then case_id, pick top 3
    risk_pool_a.sort(key=lambda x: (-x[0], x[1]))
    risk_pool_b.sort(key=lambda x: (-x[0], x[1]))
    risk_pool_c.sort(key=lambda x: (-x[0], x[1]))
    risk_pool_d.sort(key=lambda x: (-x[0], x[1]))

    selected_a = [cid for _, cid in risk_pool_a[:3]]
    selected_b = [cid for _, cid in risk_pool_b[:3]]
    selected_c = [cid for _, cid in risk_pool_c[:3]]
    selected_d = [cid for _, cid in risk_pool_d[:3]]

    risk_cases = {
        "group_a_quotation_relations": selected_a,
        "group_b_translation_boundaries": selected_b,
        "group_c_headings": selected_c,
        "group_d_voice_cues": selected_d
    }

    all_risk_cases = selected_a + selected_b + selected_c + selected_d

    manifest = {
        "schema_version": "pipeline-v2-review-sampling-manifest-1",
        "seed": SEED,
        "universe_size": len(all_case_ids),
        "exclusions": {
            "m0_discovery_queries": discovery_queries,
            "m0_holdout_queries": holdout_queries,
            "regression_exposed_cases": REGRESSION_CASES
        },
        "eligible_pool_size": len(eligible_cases),
        "samples": {
            "regression_exposed": REGRESSION_CASES,
            "uniform_random_12": random_12,
            "structural_risk_12": risk_cases
        },
        "all_selected_cases_count": len(REGRESSION_CASES) + len(random_12) + len(all_risk_cases)
    }

    manifest_path = REPO_ROOT / "pipeline_v2/reviews/m1_review_v2/sampling_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Sampling manifest locked and saved to {manifest_path}")

    # Now extract the exact regions with context
    all_sample_cases = []
    for cid in REGRESSION_CASES:
        all_sample_cases.append((cid, "regression_exposed", None))
    for cid in random_12:
        all_sample_cases.append((cid, "uniform_random", None))
    for grp, cids in risk_cases.items():
        for cid in cids:
            all_sample_cases.append((cid, "structural_risk", grp))

    extracted_regions = []

    for cid, sample_type, sub_group in all_sample_cases:
        raw = (CORPUS_DIR / cid).read_bytes()
        text = raw.decode("utf-8")
        rec = json.loads((M1_BUNDLE / f"sources/{cid[:-4]}.json").read_bytes().decode("utf-8"))
        units = rec["units"]
        p_units = [u for u in units if u["unit_kind"] == "paragraph"]
        h_units = [u for u in units if u["unit_kind"] == "heading"]

        regions_for_case = []

        if sample_type == "regression_exposed":
            if cid == "000758.txt":
                # Region 1: [35] to [37] skip
                p35 = next(u for u in p_units if u["observed_marker"] == 35)
                p37 = next(u for u in p_units if u["observed_marker"] == 37)
                regions_for_case.append({
                    "region_name": "numbering_skip_35_to_37",
                    "focus_unit_ids": [p35["unit_id"], p37["unit_id"]],
                    "target_span_bytes": [p35["span_bytes"][0], p37["span_bytes"][1]]
                })
                # Region 2: Summary heading and [38]
                p38 = next(u for u in p_units if u["observed_marker"] == 38)
                regions_for_case.append({
                    "region_name": "heading_summary_and_p38",
                    "focus_unit_ids": [p38["unit_id"]],
                    "target_span_bytes": [p37["span_bytes"][1], p38["span_bytes"][1]]
                })
                # Region 3: Last paragraph [75]
                p75 = next(u for u in p_units if u["observed_marker"] == 75)
                regions_for_case.append({
                    "region_name": "final_paragraph_75",
                    "focus_unit_ids": [p75["unit_id"]],
                    "target_span_bytes": p75["span_bytes"]
                })
            elif cid == "050936.txt":
                # Region 1: intro and quoted [1]
                q1 = next(u for u in p_units if u["observed_marker"] == 1)
                p30 = next(u for u in p_units if u["observed_marker"] == 30)
                regions_for_case.append({
                    "region_name": "quoted_marker_1_after_p30",
                    "focus_unit_ids": [p30["unit_id"], q1["unit_id"]],
                    "target_span_bytes": [p30["span_bytes"][0], q1["span_bytes"][1]]
                })
                # Region 2: following English paragraph [31]
                p31 = next(u for u in p_units if u["observed_marker"] == 31)
                regions_for_case.append({
                    "region_name": "following_english_p31",
                    "focus_unit_ids": [p31["unit_id"]],
                    "target_span_bytes": p31["span_bytes"]
                })
            elif cid == "000432.txt":
                # Region 1: translation transition to French [2] (after separator byte 28180)
                french_p = [u for u in p_units if u["span_bytes"][0] > 28180]
                p2 = next(u for u in french_p if u["observed_marker"] == 2)
                regions_for_case.append({
                    "region_name": "french_start_at_marker_2",
                    "focus_unit_ids": [p2["unit_id"]],
                    "target_span_bytes": p2["span_bytes"]
                })
                # Region 2: mid French paragraph
                regions_for_case.append({
                    "region_name": "french_body_mid",
                    "focus_unit_ids": [french_p[len(french_p)//2]["unit_id"]],
                    "target_span_bytes": french_p[len(french_p)//2]["span_bytes"]
                })
            elif cid == "014069.txt":
                fr_p = [u for u in p_units if u["language_region"].startswith("fr")]
                regions_for_case.append({
                    "region_name": "french_transition_boundary",
                    "focus_unit_ids": [fr_p[0]["unit_id"]] if fr_p else [units[-1]["unit_id"]],
                    "target_span_bytes": fr_p[0]["span_bytes"] if fr_p else units[-1]["span_bytes"]
                })
            elif cid == "046028.txt":
                p6 = next(u for u in p_units if u["observed_marker"] == 6)
                p8 = next(u for u in p_units if u["observed_marker"] == 8)
                regions_for_case.append({
                    "region_name": "skip_marker_6_to_8",
                    "focus_unit_ids": [p6["unit_id"], p8["unit_id"]],
                    "target_span_bytes": [p6["span_bytes"][0], p8["span_bytes"][1]]
                })
            elif cid == "061295.txt":
                # sidecars
                sidecars = rec.get("sidecars", [])
                sc0 = sidecars[0]
                regions_for_case.append({
                    "region_name": "quotation_sidecar_link",
                    "focus_unit_ids": [sc0["quoted_unit_id"], sc0.get("attribution_unit_id")],
                    "target_span_bytes": sc0["span_bytes"]
                })
            elif cid == "067620.txt":
                ones = [u for u in p_units if u["observed_marker"] == 1]
                regions_for_case.append({
                    "region_name": "bilingual_repeated_marker_1",
                    "focus_unit_ids": [u["unit_id"] for u in ones[:2]],
                    "target_span_bytes": [ones[0]["span_bytes"][0], ones[min(1, len(ones)-1)]["span_bytes"][1]]
                })
            elif cid == "062436.txt":
                h_resp = next((u for u in h_units if "the respondent" in text[u["span_chars"][0]:u["span_chars"][1]].lower()), None)
                regions_for_case.append({
                    "region_name": "heading_the_respondent",
                    "focus_unit_ids": [h_resp["unit_id"]] if h_resp else [units[0]["unit_id"]],
                    "target_span_bytes": h_resp["span_bytes"] if h_resp else units[0]["span_bytes"]
                })

        elif sample_type == "uniform_random":
            # 3 standard regions: start/header, mid, end
            if p_units:
                regions_for_case.append({
                    "region_name": "header_to_first_paragraph",
                    "focus_unit_ids": [p_units[0]["unit_id"]],
                    "target_span_bytes": [0, p_units[0]["span_bytes"][1]]
                })
                mid_p = p_units[len(p_units) // 2]
                regions_for_case.append({
                    "region_name": "mid_paragraph_boundary",
                    "focus_unit_ids": [mid_p["unit_id"]],
                    "target_span_bytes": mid_p["span_bytes"]
                })
                last_p = p_units[-1]
                regions_for_case.append({
                    "region_name": "final_paragraph_boundary",
                    "focus_unit_ids": [last_p["unit_id"]],
                    "target_span_bytes": last_p["span_bytes"]
                })
            else:
                regions_for_case.append({
                    "region_name": "unnumbered_case_body",
                    "focus_unit_ids": [units[0]["unit_id"]],
                    "target_span_bytes": units[0]["span_bytes"]
                })

        elif sample_type == "structural_risk":
            if sub_group == "group_a_quotation_relations":
                # Focus on quotation sidecars
                for sc in rec.get("sidecars", [])[:2]:
                    regions_for_case.append({
                        "region_name": f"quote_relation_marker_{sc.get('observed_marker')}",
                        "focus_unit_ids": [sc["quoted_unit_id"], sc.get("attribution_unit_id")],
                        "target_span_bytes": sc["span_bytes"]
                    })
            elif sub_group == "group_b_translation_boundaries":
                # Focus on translation boundary
                fr_regs = [lr for lr in rec.get("language_regions", []) if lr["region_id"].startswith("fr")]
                if fr_regs:
                    b_byte = fr_regs[0]["start_byte"]
                    matching_unit = next((u for u in units if u["span_bytes"][0] <= b_byte < u["span_bytes"][1]), units[0])
                    regions_for_case.append({
                        "region_name": "translation_boundary_region",
                        "focus_unit_ids": [matching_unit["unit_id"]],
                        "target_span_bytes": matching_unit["span_bytes"]
                    })
            elif sub_group == "group_c_headings":
                for h in h_units[:2]:
                    regions_for_case.append({
                        "region_name": f"heading_{h.get('heading_scope')}",
                        "focus_unit_ids": [h["unit_id"]],
                        "target_span_bytes": h["span_bytes"]
                    })
            elif sub_group == "group_d_voice_cues":
                voice_p = [u for u in p_units if u.get("ownership_cue_observations")]
                for vp in voice_p[:2]:
                    regions_for_case.append({
                        "region_name": f"voice_cue_para_{vp.get('observed_marker')}",
                        "focus_unit_ids": [vp["unit_id"]],
                        "target_span_bytes": vp["span_bytes"]
                    })

        # Ensure max 3 regions per case
        regions_for_case = regions_for_case[:3]

        for reg_info in regions_for_case:
            t_start, t_end = reg_info["target_span_bytes"]
            ctx_start = max(0, t_start - 400)
            ctx_end = min(len(raw), t_end + 400)

            extracted_regions.append({
                "case_id": cid,
                "sample_type": sample_type,
                "risk_group": sub_group,
                "region_name": reg_info["region_name"],
                "focus_unit_ids": reg_info["focus_unit_ids"],
                "target_span_bytes": [t_start, t_end],
                "context_span_bytes": [ctx_start, ctx_end],
                "raw_context_text": text[ctx_start:ctx_end]
            })

    out_regions_path = REPO_ROOT / "pipeline_v2/reviews/m1_review_v2/extracted_regions_raw.json"
    out_regions_path.write_text(json.dumps(extracted_regions, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Extracted {len(extracted_regions)} regions across {len(all_sample_cases)} cases. Saved to {out_regions_path}")


if __name__ == "__main__":
    generate_sampling()
