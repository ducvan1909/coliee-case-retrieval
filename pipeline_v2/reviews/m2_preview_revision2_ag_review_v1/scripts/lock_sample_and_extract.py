"""Lock deterministic sample (seed 20261106) and extract map -> raw context views.

Follows AG_REVIEW_M2_PREVIEW_REVISION2_PROMPT.md:
- Seed: 20261106
- 20 uniform random cases + 20 risk-stratified cases (4 per stratum across 5 strata)
- Deduplicated via a single shared `selected` set BEFORE reading raw text.
- Uses M0 cohort (`pipeline_v2/artifacts/m0_20261105_v2/cohort.json`) ONLY to exclude
  discovery and holdout IDs from the manual sample; exposed regression cases are reported separately.
- Never reads labels.
- Selects up to 3 regions per case by a pre-locked metadata rule.
- Extracts Step 1 (`NavigationReader.map` + `anchors` + `source_anchors`) and
  Step 2 (`NavigationReader.open_context` + parent/neighbor raw slices + old v1 preview comparison).
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import random
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_v2.navigation import NavigationReader

SEED = 20261106
PLACEHOLDER = re.compile(r"[<(]?(?:FRAGMENT|REFERENCE)_SUPPRESSED[>)]?")

PROMPT_REGRESSION_CASES = [
    "011922.txt",
    "051807.txt",
    "080359.txt",
    "068193.txt",
    "014101.txt",
    "048208.txt",
    "081945.txt",
    "015740.txt",
]

V2_TAG_CLIP_REGRESSION_CASES = [
    "004301.txt",
    "006063.txt",
    "008545.txt",
    "013122.txt",
    "031088.txt",
    "059397.txt",
    "071931.txt",
    "093363.txt",
    "095618.txt",
]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build_metadata_index(v3_dir: Path, all_case_ids: list[str]) -> dict[str, dict]:
    """Scan M2 v3 sidecar metadata (without opening raw files) to stratify risk pools."""
    index = {}
    for cid in all_case_ids:
        rec = read_json(v3_dir / "sources" / f"{cid[:-4]}.json")
        nav = rec["navigation"]
        previews = {p["preview_id"]: p for p in rec["previews"]}
        anchors = {a["anchor_id"]: a for a in rec["anchors"]}
        source_anchors = rec["source_anchors"]

        max_unit_anchors = max((len(r["anchor_refs"]) for r in nav), default=0)
        units_ge_4_anchors = sum(1 for r in nav if len(r["anchor_refs"]) >= 4)
        units_without_preview = sum(1 for r in nav if not r["preview_refs"])
        unnumbered_units = sum(1 for r in nav if r["unit_kind"] == "unnumbered")
        french_units = sum(1 for r in nav if str(r.get("language_region", "")).startswith("fr:"))

        markers = [r["observed_marker"] for r in nav if r["observed_marker"] is not None]
        marker_counts = Counter(markers)
        repeated_marker_units = sum(c - 1 for c in marker_counts.values() if c > 1)
        non_monotonic_jumps = sum(
            1 for i in range(1, len(markers)) if markers[i] != markers[i - 1] + 1
        )

        long_cues = sum(1 for sa in source_anchors if (sa["span_bytes"][1] - sa["span_bytes"][0]) > 240)
        cross_unit_cues = sum(1 for sa in source_anchors if len(sa["unit_refs"]) > 1)
        max_cue_bytes = max(((sa["span_bytes"][1] - sa["span_bytes"][0]) for sa in source_anchors), default=0)

        short_clean_openings = 0
        partial_anchor_previews = 0
        max_cap_240_previews = 0
        for r in nav:
            u_bytes = r["span_bytes"][1] - r["span_bytes"][0]
            for pid in r["preview_refs"]:
                p = previews[pid]
                if len(p["text"]) == 240:
                    max_cap_240_previews += 1
                if any(not v["fully_visible"] for v in p.get("anchor_visibility", [])):
                    partial_anchor_previews += 1
                if p["preview_kind"] == "opening":
                    clean_len = len(PLACEHOLDER.sub("", p["text"]))
                    if u_bytes >= 220 and clean_len < 100:
                        short_clean_openings += 1

        index[cid] = {
            "case_id": cid,
            "navigation_units": len(nav),
            "max_unit_anchors": max_unit_anchors,
            "units_ge_4_anchors": units_ge_4_anchors,
            "units_without_preview": units_without_preview,
            "unnumbered_units": unnumbered_units,
            "french_units": french_units,
            "repeated_marker_units": repeated_marker_units,
            "non_monotonic_jumps": non_monotonic_jumps,
            "long_cues": long_cues,
            "cross_unit_cues": cross_unit_cues,
            "max_cue_bytes": max_cue_bytes,
            "short_clean_openings": short_clean_openings,
            "partial_anchor_previews": partial_anchor_previews,
            "max_cap_240_previews": max_cap_240_previews,
        }
    return index


def select_3_regions_for_case(rec: dict, stratum: str) -> list[dict]:
    """Deterministic pre-locked rule to select up to 3 regions (handles) per case from metadata."""
    nav = rec["navigation"]
    previews = {p["preview_id"]: p for p in rec["previews"]}
    anchors = {a["anchor_id"]: a for a in rec["anchors"]}
    chosen_handles = []
    chosen_meta = []

    def add_row(row, reason: str):
        if row and row["handle"] not in chosen_handles and len(chosen_handles) < 3:
            chosen_handles.append(row["handle"])
            chosen_meta.append({"handle": row["handle"], "unit_id": row["unit_id"], "selection_reason": reason})

    # Slot 1: First paragraph with observed_marker == 1 (or first unit with opening preview)
    r1 = next((r for r in nav if r.get("observed_marker") == 1), None)
    if r1 is None:
        r1 = next((r for r in nav if r["preview_refs"]), nav[0] if nav else None)
    add_row(r1, "slot1_opening_marker1_or_first_unit")

    # Slot 2: Risk-targeted or highest anchor/cue/absence unit
    remaining = [r for r in nav if r["handle"] not in chosen_handles]
    if remaining:
        r2 = None
        reason2 = "slot2_anchor_or_cue_focus"
        if stratum == "risk_4_units_without_preview" or any(not r["preview_refs"] for r in remaining):
            no_prev = [r for r in remaining if not r["preview_refs"]]
            if no_prev:
                r2 = no_prev[0]
                reason2 = "slot2_unit_without_preview"
        if r2 is None and stratum == "risk_3_clipped_or_short_opening_boundary":
            # Look for short clean opening or partial anchor visibility
            for r in remaining:
                for pid in r["preview_refs"]:
                    p = previews[pid]
                    if (p["preview_kind"] == "opening" and (r["span_bytes"][1] - r["span_bytes"][0]) >= 220 and len(PLACEHOLDER.sub("", p["text"])) < 100) or any(
                        not v["fully_visible"] for v in p.get("anchor_visibility", [])
                    ):
                        r2 = r
                        reason2 = "slot2_short_clean_opening_or_partial_cue_boundary"
                        break
                if r2:
                    break
        if r2 is None:
            # Score by (has_quote_cue, len(anchor_refs), len(preview_refs), -source_order)
            def score_r2(r):
                has_q = any(anchors[aid]["anchor_kind"] == "quote_introduction_candidate" for aid in r["anchor_refs"])
                has_part = any(
                    not v["fully_visible"]
                    for pid in r["preview_refs"]
                    for v in previews[pid].get("anchor_visibility", [])
                )
                return (int(has_q), int(has_part), len(r["anchor_refs"]), len(r["preview_refs"]), -r["source_order"])

            r2 = max(remaining, key=score_r2)
        add_row(r2, reason2)

    # Slot 3: Structural/neighbor focus (repeated marker, unnumbered, French, or deeper unit at ~2/3)
    remaining = [r for r in nav if r["handle"] not in chosen_handles]
    if remaining:
        marker_counts = Counter(r["observed_marker"] for r in nav if r["observed_marker"] is not None)
        rep = [r for r in remaining if r["observed_marker"] is not None and marker_counts[r["observed_marker"]] > 1]
        unnum = [r for r in remaining if r["unit_kind"] == "unnumbered"]
        fr = [r for r in remaining if str(r.get("language_region", "")).startswith("fr:")]
        if stratum == "risk_5_repeated_markers_or_unnumbered" and (rep or unnum):
            r3 = rep[0] if rep else unnum[0]
            reason3 = "slot3_repeated_marker_or_unnumbered_neighbor_chain"
        elif rep:
            r3 = rep[0]
            reason3 = "slot3_repeated_marker_neighbor_chain"
        elif fr:
            r3 = fr[0]
            reason3 = "slot3_french_region_neighbor_chain"
        elif unnum:
            r3 = unnum[0]
            reason3 = "slot3_unnumbered_unit_neighbor_chain"
        else:
            r3 = remaining[(2 * len(remaining)) // 3]
            reason3 = "slot3_deep_paragraph_neighbor_chain"
        add_row(r3, reason3)

    return chosen_meta


def main():
    started = time.perf_counter()
    out_dir = Path(__file__).resolve().parents[1]
    out_dir.mkdir(parents=True, exist_ok=True)

    m0_cohort = read_json(ROOT / "pipeline_v2/artifacts/m0_20261105_v2/cohort.json")
    v1_dir = ROOT / "pipeline_v2/artifacts/m2_navigation_20261105_v1"
    v3_dir = ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v3"
    v3_reg = read_json(v3_dir / "source_registry.json")["sources"]
    all_case_ids = sorted(r["case_id"] for r in v3_reg)

    discovery_ids = set(m0_cohort["discovery_queries"])
    holdout_ids = set(m0_cohort["holdout_queries"])
    regression_separate_ids = set(PROMPT_REGRESSION_CASES) | set(V2_TAG_CLIP_REGRESSION_CASES)
    excluded_from_sample = discovery_ids | holdout_ids | regression_separate_ids

    eligible_pool = [cid for cid in all_case_ids if cid not in excluded_from_sample]
    meta_index = build_metadata_index(v3_dir, eligible_pool)

    rng = random.Random(SEED)
    selected = set()

    # 1. 20 Uniform Random Cases
    uniform_random_20 = sorted(rng.sample(eligible_pool, 20))
    selected.update(uniform_random_20)

    # 2. 20 Risk-Stratified Cases (5 strata x 4 cases), deduplicated via shared `selected` set
    def pick_risk_stratum(candidates: list[str], k: int = 4) -> list[str]:
        avail = [c for c in candidates if c not in selected]
        # Take top deterministic pool of size min(len(avail), 20) and sample k with locked rng
        pool = avail[: max(k, min(len(avail), 20))]
        chosen = sorted(rng.sample(pool, min(k, len(pool))))
        selected.update(chosen)
        return chosen

    # Stratum 1: Many anchors in a unit (units_ge_4_anchors >= 1)
    s1_cands = sorted(
        [c for c in eligible_pool if meta_index[c]["units_ge_4_anchors"] >= 1],
        key=lambda c: (-meta_index[c]["max_unit_anchors"], -meta_index[c]["units_ge_4_anchors"], c),
    )
    risk_1 = pick_risk_stratum(s1_cands, 4)

    # Stratum 2: Long or cross-unit quote cues
    s2_cands = sorted(
        [c for c in eligible_pool if meta_index[c]["long_cues"] >= 1 or meta_index[c]["cross_unit_cues"] >= 1],
        key=lambda c: (-meta_index[c]["cross_unit_cues"], -meta_index[c]["max_cue_bytes"], c),
    )
    risk_2 = pick_risk_stratum(s2_cands, 4)

    # Stratum 3: Short clean openings (<100 clean chars in >=220 byte unit) or partial cue / tight boundary
    s3_cands = sorted(
        [c for c in eligible_pool if meta_index[c]["short_clean_openings"] >= 1 or meta_index[c]["partial_anchor_previews"] >= 1],
        key=lambda c: (-meta_index[c]["short_clean_openings"], -meta_index[c]["partial_anchor_previews"], -meta_index[c]["max_cap_240_previews"], c),
    )
    risk_3 = pick_risk_stratum(s3_cands, 4)

    # Stratum 4: Units without preview
    s4_cands = sorted(
        [c for c in eligible_pool if meta_index[c]["units_without_preview"] >= 1],
        key=lambda c: (-meta_index[c]["units_without_preview"], -meta_index[c]["max_unit_anchors"], c),
    )
    risk_4 = pick_risk_stratum(s4_cands, 4)

    # Stratum 5: Repeated markers or high unnumbered context
    s5_cands = sorted(
        [c for c in eligible_pool if meta_index[c]["repeated_marker_units"] >= 2 or meta_index[c]["unnumbered_units"] >= 10],
        key=lambda c: (-meta_index[c]["repeated_marker_units"], -meta_index[c]["unnumbered_units"], c),
    )
    risk_5 = pick_risk_stratum(s5_cands, 4)

    risk_stratified_20 = {
        "risk_1_many_anchors": risk_1,
        "risk_2_long_or_cross_unit_cues": risk_2,
        "risk_3_clipped_or_short_opening_boundary": risk_3,
        "risk_4_units_without_preview": risk_4,
        "risk_5_repeated_markers_or_unnumbered": risk_5,
    }
    risk_flat = [c for grp in risk_stratified_20.values() for c in grp]

    # Build sampling manifest BEFORE reading raw text
    case_selections = []
    for cid in uniform_random_20:
        rec = read_json(v3_dir / "sources" / f"{cid[:-4]}.json")
        case_selections.append({
            "case_id": cid,
            "sample_group": "uniform_random_20",
            "stratum": "uniform_random",
            "metadata_summary": meta_index[cid],
            "selected_regions": select_3_regions_for_case(rec, "uniform_random"),
        })
    for stratum, cids in risk_stratified_20.items():
        for cid in cids:
            rec = read_json(v3_dir / "sources" / f"{cid[:-4]}.json")
            case_selections.append({
                "case_id": cid,
                "sample_group": "risk_stratified_20",
                "stratum": stratum,
                "metadata_summary": meta_index[cid],
                "selected_regions": select_3_regions_for_case(rec, stratum),
            })

    manifest = {
        "schema_version": "m2-preview-revision2-sampling-manifest-v1",
        "seed": SEED,
        "locked_before_reading_raw": True,
        "labels_accessed": False,
        "total_corpus_cases": len(all_case_ids),
        "excluded_discovery_count": len(discovery_ids),
        "excluded_holdout_count": len(holdout_ids),
        "separate_regression_cases_count": len(regression_separate_ids),
        "eligible_pool_count": len(eligible_pool),
        "uniform_random_20": uniform_random_20,
        "risk_stratified_20": risk_stratified_20,
        "total_sampled_unique_cases": len(selected),
        "overlap_between_uniform_and_risk": len(set(uniform_random_20) & set(risk_flat)),
        "overlap_with_discovery_or_holdout": len(selected & (discovery_ids | holdout_ids)),
        "overlap_with_separate_regressions": len(selected & regression_separate_ids),
        "total_sampled_regions": sum(len(x["selected_regions"]) for x in case_selections),
        "separate_regression_groups": {
            "prompt_8_verbatim_regressions": PROMPT_REGRESSION_CASES,
            "v2_9_tag_clip_regressions": V2_TAG_CLIP_REGRESSION_CASES,
        },
        "case_selections": case_selections,
    }
    (out_dir / "sampling_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Now extract Step 1 (map/anchors/source_anchors) and Step 2 (open_context + v1 comparison) using NavigationReader
    reader = NavigationReader(ROOT, "pipeline_v2/artifacts/m2_navigation_20261106_v3")
    extracted_regions = []
    for entry in case_selections:
        cid = entry["case_id"]
        v1_rec = read_json(v1_dir / "sources" / f"{cid[:-4]}.json")
        v3_rec = read_json(v3_dir / "sources" / f"{cid[:-4]}.json")
        v1_p_by_unit = {}
        for p in v1_rec["previews"]:
            v1_p_by_unit.setdefault(p["unit_id"], []).append(p)
        handle_to_idx = {r["handle"]: idx for idx, r in enumerate(v3_rec["navigation"])}

        for reg in entry["selected_regions"]:
            handle = reg["handle"]
            idx = handle_to_idx[handle]
            # Step 1: Map view + anchor catalogs
            map_page = reader.map(cid, offset=idx, limit=1)
            map_item = map_page["items"][0]
            anchors_page = reader.anchors(cid, handle, offset=0, limit=100)
            source_anchors_page = reader.source_anchors(cid, offset=0, limit=100)

            # Step 2: Open raw parent + neighbor context
            opened = reader.open_context(cid, handle)
            raw_bytes = (ROOT / "data/task1_train_files_2026/cases" / cid).read_bytes()
            comp_texts = {}
            for comp in opened["components"]:
                ca, cb = comp["span_bytes"]
                comp_texts[comp["kind"]] = {
                    "handle": comp["handle"],
                    "unit_id": comp["unit_id"],
                    "span_bytes": [ca, cb],
                    "raw_text": raw_bytes[ca:cb].decode("utf-8"),
                }

            extracted_regions.append({
                "region_id": f"{cid[:-4]}:{handle}",
                "case_id": cid,
                "source_hash": map_page["source_hash"],
                "sample_group": entry["sample_group"],
                "stratum": entry["stratum"],
                "handle": handle,
                "unit_id": reg["unit_id"],
                "selection_reason": reg["selection_reason"],
                "step1_map_item": map_item,
                "step1_unit_anchors": anchors_page["items"],
                "step1_case_source_anchors": source_anchors_page["items"],
                "v1_old_previews": v1_p_by_unit.get(reg["unit_id"], []),
                "step2_opened_context": {
                    "span_bytes": opened["span_bytes"],
                    "neighbor_policy": opened["neighbor_policy"],
                    "intervening_headings": opened["intervening_headings"],
                    "components": comp_texts,
                },
            })

    # Extract separate regression regions (8 prompt verbatim + 9 v2 tag-clip cases)
    regression_targets = [
        ("011922.txt", "p000005", "prompt_8_verbatim_regressions", "opening_truncated_on_judge_initial"),
        ("051807.txt", "u000030", "prompt_8_verbatim_regressions", "opening_truncated_on_numbered_list_prefix"),
        ("080359.txt", "u000002", "prompt_8_verbatim_regressions", "opening_truncated_on_counsel_middle_initial"),
        ("068193.txt", "p000025", "prompt_8_verbatim_regressions", "opening_truncated_on_section_abbreviation_and_contained_duplicate"),
        ("014101.txt", "p000008", "prompt_8_verbatim_regressions", "contained_duplicate_crowded_out_third_anchor_a0003"),
        ("048208.txt", "p000015", "prompt_8_verbatim_regressions", "contained_duplicate_crowded_out_anchors_a0002_and_a0003"),
        ("081945.txt", "u000001", "prompt_8_verbatim_regressions", "placeholder_punct_prefix_line_skipped_to_alphanumeric_opening"),
        ("015740.txt", "u000001", "prompt_8_verbatim_regressions", "no_alphanumeric_text_outside_placeholders_single_full_anchor_preview"),
        ("004301.txt", "p000076", "v2_9_tag_clip_regressions", "v2_tail_candidate_clipped_mid_fragment_suppressed_tag"),
        ("006063.txt", "p000033", "v2_9_tag_clip_regressions", "v2_tail_candidate_clipped_mid_fragment_suppressed_tag"),
        ("008545.txt", "p000034", "v2_9_tag_clip_regressions", "v2_tail_candidate_clipped_mid_fragment_suppressed_tag"),
        ("013122.txt", "p000026", "v2_9_tag_clip_regressions", "v2_tail_candidate_clipped_mid_fragment_suppressed_tag"),
        ("031088.txt", "p000063", "v2_9_tag_clip_regressions", "v2_tail_candidate_clipped_mid_fragment_suppressed_tag"),
        ("059397.txt", "p000023", "v2_9_tag_clip_regressions", "v2_tail_candidate_clipped_mid_fragment_suppressed_tag"),
        ("071931.txt", "p000010", "v2_9_tag_clip_regressions", "v2_tail_candidate_clipped_mid_fragment_suppressed_tag"),
        ("093363.txt", "p000011", "v2_9_tag_clip_regressions", "v2_tail_candidate_clipped_mid_fragment_suppressed_tag"),
        ("095618.txt", "p000021", "v2_9_tag_clip_regressions", "v2_tail_candidate_clipped_mid_fragment_suppressed_tag"),
    ]
    v2_dir = ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v2"
    separate_regression_regions = []
    for cid, handle, reg_group, reason in regression_targets:
        v1_rec = read_json(v1_dir / "sources" / f"{cid[:-4]}.json")
        v2_rec = read_json(v2_dir / "sources" / f"{cid[:-4]}.json")
        v3_rec = read_json(v3_dir / "sources" / f"{cid[:-4]}.json")
        v1_p_by_unit = {}
        for p in v1_rec["previews"]:
            v1_p_by_unit.setdefault(p["unit_id"], []).append(p)
        v2_p_by_unit = {}
        for p in v2_rec["previews"]:
            v2_p_by_unit.setdefault(p["unit_id"], []).append(p)
        handle_to_idx = {r["handle"]: idx for idx, r in enumerate(v3_rec["navigation"])}
        idx = handle_to_idx[handle]
        uid = v3_rec["navigation"][idx]["unit_id"]

        map_page = reader.map(cid, offset=idx, limit=1)
        map_item = map_page["items"][0]
        anchors_page = reader.anchors(cid, handle, offset=0, limit=100)
        source_anchors_page = reader.source_anchors(cid, offset=0, limit=100)
        opened = reader.open_context(cid, handle)
        raw_bytes = (ROOT / "data/task1_train_files_2026/cases" / cid).read_bytes()
        comp_texts = {}
        for comp in opened["components"]:
            ca, cb = comp["span_bytes"]
            comp_texts[comp["kind"]] = {
                "handle": comp["handle"],
                "unit_id": comp["unit_id"],
                "span_bytes": [ca, cb],
                "raw_text": raw_bytes[ca:cb].decode("utf-8"),
            }
        separate_regression_regions.append({
            "region_id": f"{cid[:-4]}:{handle}",
            "case_id": cid,
            "source_hash": map_page["source_hash"],
            "sample_group": reg_group,
            "stratum": reg_group,
            "handle": handle,
            "unit_id": uid,
            "selection_reason": reason,
            "step1_map_item": map_item,
            "step1_unit_anchors": anchors_page["items"],
            "step1_case_source_anchors": source_anchors_page["items"],
            "v1_old_previews": v1_p_by_unit.get(uid, []),
            "v2_intermediate_previews": v2_p_by_unit.get(uid, []),
            "step2_opened_context": {
                "span_bytes": opened["span_bytes"],
                "neighbor_policy": opened["neighbor_policy"],
                "intervening_headings": opened["intervening_headings"],
                "components": comp_texts,
            },
        })

    extracted_payload = {
        "schema_version": "m2-preview-revision2-extracted-regions-v1",
        "seed": SEED,
        "total_cases": len(case_selections),
        "total_regions": len(extracted_regions),
        "separate_regression_regions_count": len(separate_regression_regions),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "regions": extracted_regions,
        "separate_regression_regions": separate_regression_regions,
    }
    (out_dir / "extracted_regions_raw.json").write_text(
        json.dumps(extracted_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": "OK",
        "total_sampled_unique_cases": manifest["total_sampled_unique_cases"],
        "total_sampled_regions": manifest["total_sampled_regions"],
        "uniform_random_20": uniform_random_20,
        "risk_stratified_20": risk_stratified_20,
        "elapsed_seconds": extracted_payload["elapsed_seconds"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
