"""Lock sampling_manifest.json using only metadata and extract review regions for M2 navigation review.

Follows AG_REVIEW_M2_NAVIGATION_PROMPT.md Section B strictly:
- Seed 20261105
- Excludes 10 discovery + 10 holdout queries from M0 cohort.json (never opens labels)
- Reports 8 exposed regression cases separately (excluded from random/risk pools so no overlap)
- 20 uniform random cases + 20 risk-stratified cases (4 per group across 5 metadata-defined risk groups)
- Deduplicates across all groups via a shared selected-set
- Extracts up to 3 pre-locked regions per case:
  (1) opening_region
  (2) anchor_or_partial_cue_region
  (3) parent_neighbor_window_region
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import re
import sys
import time

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline_v2.navigation import NavigationReader

SEED = 20261105
REGRESSION_EXPOSED = [
    "061295.txt",
    "067620.txt",
    "062436.txt",
    "000758.txt",
    "050936.txt",
    "000432.txt",
    "014069.txt",
    "046028.txt",
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build_case_metadata_from_m2(m2_dir: Path) -> dict[str, dict]:
    registry = load_json(m2_dir / "source_registry.json")
    meta = {}
    for row in registry["sources"]:
        cid = row["case_id"]
        rec = load_json(m2_dir / row["navigation_ref"])
        nav = rec["navigation"]
        previews = {p["preview_id"]: p for p in rec["previews"]}
        anchors = {a["anchor_id"]: a for a in rec["anchors"]}
        source_anchors = rec["source_anchors"]
        headings = rec["headings"]

        over_display_units = 0
        unshown_anchors_total = 0
        short_opening_units = 0
        units_without_preview = 0
        quoted_units = 0
        unnumbered_units = 0
        repeated_markers = 0
        marker_jumps = 0
        seen_markers = set()
        prev_marker = None
        max_byte = 0

        for r in nav:
            bs, be = r["span_bytes"]
            if be > max_byte:
                max_byte = be
            if r["unit_kind"] == "unnumbered":
                unnumbered_units += 1
            if r["paragraph_role"] == "quoted":
                quoted_units += 1
            m = r["observed_marker"]
            if m is not None:
                if m in seen_markers:
                    repeated_markers += 1
                seen_markers.add(m)
                if prev_marker is not None and m != prev_marker + 1:
                    marker_jumps += 1
                prev_marker = m
            if not r["preview_refs"]:
                units_without_preview += 1
            vis_anchors = set()
            for pid in r["preview_refs"]:
                p = previews[pid]
                vis_anchors.update(p["anchor_refs"])
                if p["preview_kind"] == "opening":
                    plen = p["span_chars"][1] - p["span_chars"][0]
                    if plen <= 25 and p["span_bytes"][1] < be - 2:
                        short_opening_units += 1
            if len(r["anchor_refs"]) > len(vis_anchors):
                over_display_units += 1
                unshown_anchors_total += len(r["anchor_refs"]) - len(vis_anchors)

        nav_unit_ids = {r["unit_id"] for r in nav}
        heading_only_cues = 0
        cross_unit_cues = 0
        long_cues = 0
        max_cue_bytes = 0
        for sa in source_anchors:
            sa_len = sa["span_bytes"][1] - sa["span_bytes"][0]
            if sa_len > max_cue_bytes:
                max_cue_bytes = sa_len
            if sa_len >= 120:
                long_cues += 1
            content_refs = [u for u in sa["unit_refs"] if u in nav_unit_ids]
            if not content_refs:
                heading_only_cues += 1
            if len(sa["unit_refs"]) > 1:
                cross_unit_cues += 1

        meta[cid] = {
            "case_id": cid,
            "approx_byte_length": max_byte,
            "navigation_units": len(nav),
            "unnumbered_units": unnumbered_units,
            "quoted_units": quoted_units,
            "headings": len(headings),
            "anchors": len(anchors),
            "source_quote_cues": len(source_anchors),
            "over_display_units": over_display_units,
            "unshown_anchors_total": unshown_anchors_total,
            "short_opening_units": short_opening_units,
            "units_without_preview": units_without_preview,
            "repeated_markers": repeated_markers,
            "marker_jumps": marker_jumps,
            "heading_only_cues": heading_only_cues,
            "cross_unit_cues": cross_unit_cues,
            "long_cues": long_cues,
            "max_cue_bytes": max_cue_bytes,
        }
    return meta


def select_samples(meta: dict[str, dict], m0_cohort: dict) -> dict:
    discovery = list(m0_cohort["discovery_queries"])
    holdout = list(m0_cohort["holdout_queries"])
    excluded = set(discovery) | set(holdout) | set(REGRESSION_EXPOSED)

    eligible_ids = sorted(cid for cid in meta if cid not in excluded)
    rng = random.Random(SEED)

    selected_set = set()
    uniform_random_20 = rng.sample(eligible_ids, 20)
    selected_set.update(uniform_random_20)

    def pick_from_pool(candidates: list[str], count: int) -> tuple[list[str], int]:
        available = [c for c in candidates if c not in selected_set]
        chosen = available[:count]
        selected_set.update(chosen)
        return chosen, len(available)

    # Risk Group 1: Many anchors exceeding display limit
    pool_g1 = sorted(
        [
            cid for cid in eligible_ids
            if meta[cid]["over_display_units"] >= 3 and meta[cid]["unshown_anchors_total"] >= 10
        ],
        key=lambda c: (-meta[c]["unshown_anchors_total"], -meta[c]["over_display_units"], c),
    )
    g1_cases, g1_avail = pick_from_pool(pool_g1, 4)

    # Risk Group 2: Long cue (>=120 bytes), cross-unit cue, or heading-only cue
    pool_g2 = sorted(
        [
            cid for cid in eligible_ids
            if (meta[cid]["heading_only_cues"] > 0 or meta[cid]["cross_unit_cues"] > 0 or meta[cid]["long_cues"] > 0)
        ],
        key=lambda c: (
            -meta[c]["heading_only_cues"],
            -meta[c]["cross_unit_cues"],
            -meta[c]["max_cue_bytes"],
            c,
        ),
    )
    g2_cases, g2_avail = pick_from_pool(pool_g2, 4)

    # Risk Group 3: Very short opening previews (<=25 chars clipped early) or placeholder-only / no-preview units
    pool_g3 = sorted(
        [
            cid for cid in eligible_ids
            if (meta[cid]["units_without_preview"] > 0 or meta[cid]["short_opening_units"] >= 2)
        ],
        key=lambda c: (
            -meta[c]["units_without_preview"],
            -meta[c]["short_opening_units"],
            c,
        ),
    )
    g3_cases, g3_avail = pick_from_pool(pool_g3, 4)

    # Risk Group 4: Context with repeated markers, quotations, and unnumbered units
    pool_g4 = sorted(
        [
            cid for cid in eligible_ids
            if meta[cid]["repeated_markers"] >= 2 and meta[cid]["quoted_units"] >= 1 and meta[cid]["unnumbered_units"] >= 1
        ],
        key=lambda c: (
            -meta[c]["repeated_markers"],
            -meta[c]["quoted_units"],
            -meta[c]["unnumbered_units"],
            c,
        ),
    )
    g4_cases, g4_avail = pick_from_pool(pool_g4, 4)

    # Risk Group 5: Very long sources with many headings
    pool_g5 = sorted(
        [
            cid for cid in eligible_ids
            if meta[cid]["approx_byte_length"] >= 80000 and meta[cid]["headings"] >= 20 and meta[cid]["navigation_units"] >= 120
        ],
        key=lambda c: (
            -meta[c]["headings"],
            -meta[c]["approx_byte_length"],
            c,
        ),
    )
    g5_cases, g5_avail = pick_from_pool(pool_g5, 4)

    risk_groups = {
        "risk_1_anchors_exceeding_display_limit": {
            "criterion": "over_display_units >= 3 and unshown_anchors_total >= 10, sorted by (-unshown_anchors_total, -over_display_units, case_id)",
            "eligible_matching_count": g1_avail,
            "requested_slots": 4,
            "selected_cases": g1_cases,
        },
        "risk_2_long_cross_unit_or_heading_cues": {
            "criterion": "heading_only_cues > 0 or cross_unit_cues > 0 or long_cues (>=120 bytes) > 0, sorted by (-heading_only_cues, -cross_unit_cues, -max_cue_bytes, case_id)",
            "eligible_matching_count": g2_avail,
            "requested_slots": 4,
            "selected_cases": g2_cases,
        },
        "risk_3_very_short_abbrev_or_placeholder_previews": {
            "criterion": "units_without_preview > 0 or short_opening_units (<=25 chars clipped before unit end) >= 2, sorted by (-units_without_preview, -short_opening_units, case_id)",
            "eligible_matching_count": g3_avail,
            "requested_slots": 4,
            "selected_cases": g3_cases,
        },
        "risk_4_repeated_markers_quotations_unnumbered_context": {
            "criterion": "repeated_markers >= 2 and quoted_units >= 1 and unnumbered_units >= 1, sorted by (-repeated_markers, -quoted_units, -unnumbered_units, case_id)",
            "eligible_matching_count": g4_avail,
            "requested_slots": 4,
            "selected_cases": g4_cases,
        },
        "risk_5_very_long_or_heading_dense_sources": {
            "criterion": "approx_byte_length >= 80000 and headings >= 20 and navigation_units >= 120, sorted by (-headings, -approx_byte_length, case_id)",
            "eligible_matching_count": g5_avail,
            "requested_slots": 4,
            "selected_cases": g5_cases,
        },
    }

    risk_flat = [c for g in risk_groups.values() for c in g["selected_cases"]]
    assert len(set(uniform_random_20) & set(risk_flat)) == 0, "Overlap between uniform random and risk samples"
    assert len(set(risk_flat)) == len(risk_flat) == 20, "Duplicate or missing risk cases"

    return {
        "schema_version": "pipeline-v2-m2-review-sampling-manifest-1",
        "seed": SEED,
        "rng_method": "Python random.Random(20261105).sample on sorted eligible case IDs for uniform_random_20; deterministic metadata-threshold ranking with shared selected_set deduplication for risk_stratified_20",
        "selection_locked_before_raw_inspection": True,
        "labels_or_gold_accessed": False,
        "universe_size": len(meta),
        "exclusions": {
            "m0_discovery_queries": discovery,
            "m0_holdout_queries": holdout,
            "regression_exposed_reported_separately": REGRESSION_EXPOSED,
        },
        "eligible_pool_size": len(eligible_ids),
        "slot_accounting": {
            "uniform_random_slots_requested": 20,
            "uniform_random_unique_selected": len(uniform_random_20),
            "risk_stratified_slots_requested": 20,
            "risk_stratified_unique_selected": len(risk_flat),
            "combined_new_sample_slots": 40,
            "combined_new_sample_unique_cases": len(selected_set),
            "regression_exposed_separate_cases": len(REGRESSION_EXPOSED),
            "total_unique_cases_reviewed": len(selected_set) + len(REGRESSION_EXPOSED),
            "shortfall_slots": 0,
        },
        "region_selection_policy": {
            "max_regions_per_case": 3,
            "region_1_opening": "First unit with preview_absence_reason or opening preview <= 40 chars clipped before unit end; otherwise first paragraph unit in source order.",
            "region_2_anchor_or_partial_cue": "First distinct unit with quote_introduction_candidate anchor, partial anchor visibility, or unshown anchors (> display limit); otherwise first distinct unit with any anchor (or heading-only source anchor if present); fallback to middle unit.",
            "region_3_parent_neighbor_window": "First distinct unit with repeated/jumped marker neighbor, quoted role, intervening heading in expansion envelope, or unnumbered kind; fallback to 2/3 position unit.",
        },
        "samples": {
            "uniform_random_20": uniform_random_20,
            "risk_stratified_20": risk_groups,
            "regression_exposed_8": REGRESSION_EXPOSED,
        },
    }


def choose_three_regions(m2_record: dict, reader: NavigationReader, raw: bytes) -> list[dict]:
    case_id = m2_record["case_id"]
    nav = m2_record["navigation"]
    previews = {p["preview_id"]: p for p in m2_record["previews"]}
    anchors = {a["anchor_id"]: a for a in m2_record["anchors"]}
    headings = {h["unit_id"]: h for h in m2_record["headings"]}
    source_anchors = m2_record["source_anchors"]

    chosen_handles = []

    # 1. Opening region
    r1 = None
    for r in nav:
        if not r["preview_refs"]:
            r1 = r
            break
        for pid in r["preview_refs"]:
            p = previews[pid]
            if p["preview_kind"] == "opening":
                plen = p["span_chars"][1] - p["span_chars"][0]
                if plen <= 40 and p["span_bytes"][1] < r["span_bytes"][1] - 2:
                    r1 = r
                    break
        if r1:
            break
    if r1 is None:
        r1 = next((r for r in nav if r["unit_kind"] == "paragraph"), nav[0])
    chosen_handles.append((r1["handle"], "opening"))

    # 2. Anchor or partial cue region
    r2 = None
    # Priority A: quote_introduction_candidate or partial visibility or unshown anchors
    for r in nav:
        if r["handle"] in {h for h, _ in chosen_handles}:
            continue
        u_anchors = [anchors[aid] for aid in r["anchor_refs"]]
        u_previews = [previews[pid] for pid in r["preview_refs"]]
        vis_ids = {aid for p in u_previews for aid in p["anchor_refs"]}
        has_quote_cue = any(a["anchor_kind"] == "quote_introduction_candidate" for a in u_anchors)
        has_partial = any(
            not v["fully_visible"] or v["source_cue_fully_visible"] is False
            for p in u_previews
            for v in p["anchor_visibility"]
        )
        has_unshown = len(u_anchors) > len(vis_ids)
        if has_quote_cue or has_partial or has_unshown:
            r2 = r
            break
    # Priority B: any anchor
    if r2 is None:
        for r in nav:
            if r["handle"] not in {h for h, _ in chosen_handles} and r["anchor_refs"]:
                r2 = r
                break
    # Priority C: middle unit
    if r2 is None and len(nav) > 1:
        mid_idx = len(nav) // 2
        if nav[mid_idx]["handle"] in {h for h, _ in chosen_handles}:
            mid_idx = min(len(nav) - 1, mid_idx + 1)
        if nav[mid_idx]["handle"] not in {h for h, _ in chosen_handles}:
            r2 = nav[mid_idx]
    if r2 is not None:
        chosen_handles.append((r2["handle"], "anchor_or_partial_cue"))

    # 3. Parent-neighbor window region
    r3 = None
    seen_m = set()
    prev_m = None
    for idx, r in enumerate(nav):
        m = r["observed_marker"]
        is_rep_or_jump = False
        if m is not None:
            if m in seen_m or (prev_m is not None and m != prev_m + 1):
                is_rep_or_jump = True
            seen_m.add(m)
            prev_m = m
        if r["handle"] in {h for h, _ in chosen_handles}:
            continue
        if is_rep_or_jump or r["paragraph_role"] == "quoted" or r["unit_kind"] == "unnumbered":
            r3 = r
            break
    if r3 is None and len(nav) > 2:
        idx3 = min(len(nav) - 1, max(1, (2 * len(nav)) // 3))
        for cand_idx in [idx3, idx3 - 1, idx3 + 1, len(nav) - 1]:
            if 0 <= cand_idx < len(nav) and nav[cand_idx]["handle"] not in {h for h, _ in chosen_handles}:
                r3 = nav[cand_idx]
                break
    if r3 is not None:
        chosen_handles.append((r3["handle"], "parent_neighbor_window"))

    row_by_handle = {r["handle"]: r for r in nav}
    extracted = []
    for reg_idx, (handle, reg_type) in enumerate(chosen_handles):
        r = row_by_handle[handle]
        u_previews = [previews[pid] for pid in r["preview_refs"]]
        u_anchors = [anchors[aid] for aid in r["anchor_refs"]]
        u_sections = [headings[hid] for hid in r["section_refs"]]
        opened = reader.open_context(case_id, handle)
        u_bs, u_be = r["span_bytes"]
        unit_raw_text = raw[u_bs:u_be].decode("utf-8")

        # Also check if there is any heading-only source anchor in this case
        heading_only_source_anchors = [
            {
                **sa,
                "raw_text": raw[sa["span_bytes"][0]:sa["span_bytes"][1]].decode("utf-8"),
            }
            for sa in source_anchors
            if not any(u in {x["unit_id"] for x in nav} for u in sa["unit_refs"])
        ]
        linked_source_anchors = [
            {
                **sa,
                "raw_text": raw[sa["span_bytes"][0]:sa["span_bytes"][1]].decode("utf-8"),
            }
            for sa in source_anchors
            if r["unit_id"] in sa["unit_refs"]
        ]

        extracted.append({
            "case_id": case_id,
            "source_hash": m2_record["source_hash"],
            "region_index": reg_idx,
            "region_type": reg_type,
            "handle": handle,
            "unit_id": r["unit_id"],
            "unit_kind": r["unit_kind"],
            "source_order": r["source_order"],
            "observed_marker": r["observed_marker"],
            "paragraph_role": r["paragraph_role"],
            "language_region": r["language_region"],
            "uncertainties": r["uncertainties"],
            "unit_span_bytes": r["span_bytes"],
            "map_view": {
                "sections": [{"unit_id": s["unit_id"], "text": s["text"], "span_bytes": s["span_bytes"]} for s in u_sections],
                "preview_absence_reason": r["preview_absence_reason"],
                "previews": [
                    {
                        "preview_id": p["preview_id"],
                        "preview_kind": p["preview_kind"],
                        "span_bytes": p["span_bytes"],
                        "span_chars": p["span_chars"],
                        "char_length": p["span_chars"][1] - p["span_chars"][0],
                        "partial_sentence": p["partial_sentence"],
                        "text": p["text"],
                        "anchor_refs": p["anchor_refs"],
                        "anchor_visibility": p["anchor_visibility"],
                    }
                    for p in u_previews
                ],
                "anchor_count": len(u_anchors),
                "visible_anchor_count": len({aid for p in u_previews for aid in p["anchor_refs"]}),
            },
            "unit_anchors": u_anchors,
            "linked_source_anchors": linked_source_anchors,
            "case_heading_only_source_anchors": heading_only_source_anchors if reg_type == "anchor_or_partial_cue" else [],
            "reading_expansion": r["reading_expansion"],
            "open_context_view": {
                "components": opened["components"],
                "envelope_span_bytes": opened["span_bytes"],
                "intervening_headings": opened["intervening_headings"],
                "neighbor_policy": opened["neighbor_policy"],
                "diagnostic_only": opened["diagnostic_only"],
                "M4_delivery_recorded": opened["M4_delivery_recorded"],
                "envelope_raw_text": opened["text"],
            },
            "unit_full_raw_text": unit_raw_text,
        })
    return extracted


def main():
    started = time.perf_counter()
    m0_cohort = load_json(REPO / "pipeline_v2/artifacts/m0_20261105_v2/cohort.json")
    m2_dir = REPO / "pipeline_v2/artifacts/m2_navigation_20261105_v1"
    out_dir = REPO / "pipeline_v2/reviews/m2_navigation_ag_review_v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = build_case_metadata_from_m2(m2_dir)
    manifest = select_samples(meta, m0_cohort)

    manifest_path = out_dir / "sampling_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    reader = NavigationReader(REPO, "pipeline_v2/artifacts/m2_navigation_20261105_v1")
    all_extracted = []

    sample_schedule = []
    for cid in manifest["samples"]["uniform_random_20"]:
        sample_schedule.append((cid, "uniform_random_20", None))
    for g_name, g_info in manifest["samples"]["risk_stratified_20"].items():
        for cid in g_info["selected_cases"]:
            sample_schedule.append((cid, "risk_stratified_20", g_name))
    for cid in manifest["samples"]["regression_exposed_8"]:
        sample_schedule.append((cid, "regression_exposed_8", "regression_exposed"))

    for cid, sample_group, risk_subgroup in sample_schedule:
        raw, m2_record = reader._case(cid)
        regions = choose_three_regions(m2_record, reader, raw)
        for reg in regions:
            reg["sample_group"] = sample_group
            reg["risk_subgroup"] = risk_subgroup
            all_extracted.append(reg)

    extracted_path = out_dir / "extracted_regions_raw.json"
    extracted_path.write_text(
        json.dumps(all_extracted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    elapsed = round(time.perf_counter() - started, 3)
    print(json.dumps({
        "sampling_manifest_locked": True,
        "elapsed_seconds": elapsed,
        "slot_accounting": manifest["slot_accounting"],
        "total_extracted_regions": len(all_extracted),
        "regions_by_sample_group": {
            "uniform_random_20": sum(1 for r in all_extracted if r["sample_group"] == "uniform_random_20"),
            "risk_stratified_20": sum(1 for r in all_extracted if r["sample_group"] == "risk_stratified_20"),
            "regression_exposed_8": sum(1 for r in all_extracted if r["sample_group"] == "regression_exposed_8"),
        },
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
