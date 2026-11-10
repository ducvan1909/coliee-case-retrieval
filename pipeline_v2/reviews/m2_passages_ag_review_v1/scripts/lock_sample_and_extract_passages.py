"""Lock 40-case sample (seed 20261106: 20 uniform random + 20 risk-stratified) and extract raw passage evidence.

Strictly excludes M0 discovery_queries (10) and holdout_queries (10) from manual review,
and separates previously exposed regression cases into a distinct regression cohort.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tokenizers import Tokenizer
from pipeline_v2.passages import PassageReader

SEED = 20261106


def read_json(path: Path):
    return json.loads(path.read_bytes())


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def collect_case_metadata(bundle_dir: Path, nav_dir: Path, m1_dir: Path, registry):
    """Collect structural/token metadata from sealed JSON manifests BEFORE reading raw text."""
    meta_by_case = {}
    for row in registry:
        case_id = row["case_id"]
        pas_rec = read_json(bundle_dir / row["passages_ref"])
        nav_rec = read_json(nav_dir / "sources" / f"{case_id[:-4]}.json")
        m1_rec = read_json(m1_dir / "sources" / f"{case_id[:-4]}.json")

        nav_units = nav_rec["navigation"]
        passages = pas_rec["passages"]
        parents = pas_rec["parents"]

        split_parents = [p for p in parents if len(p["passage_refs"]) > 1]
        max_split_count = max((len(p["passage_refs"]) for p in parents), default=1)
        max_tokens = max((p["full_input_tokens"] for p in passages), default=0)
        count_448 = sum(1 for p in passages if p["full_input_tokens"] == 448)
        intact_gt_320 = sum(1 for p in passages if p["split_count"] == 1 and p["full_input_tokens"] > 320)
        wb_splits = sum(1 for p in passages if p["word_boundary_split"])
        min_positive_overlap = min(
            (p["overlap_tokens_with_previous"] for p in passages if p["split_order"] > 0),
            default=0,
        )
        max_token_to_byte_ratio = max(
            (p["full_input_tokens"] / max(1, p["span_bytes"][1] - p["span_bytes"][0]) for p in passages if p["split_count"] > 1),
            default=0.0,
        )

        utf8_exceptions = len(m1_rec["char_byte_map"]["exceptions"])
        french_passages = sum(1 for p in passages if str(p["language_region"]).startswith("fr:"))
        quoted_passages = sum(1 for p in passages if p["paragraph_role"] == "quoted")
        unknown_passages = sum(1 for p in passages if p["paragraph_role"] == "unknown")
        unnumbered_passages = sum(1 for p in passages if p["unit_kind"] == "unnumbered")
        unnumbered_split_parents = sum(
            1 for p, u in zip(parents, nav_units) if u["unit_kind"] == "unnumbered" and len(p["passage_refs"]) > 1
        )
        no_preview_units = sum(1 for u in nav_units if not u["preview_refs"])

        markers = [u["observed_marker"] for u in nav_units if u["observed_marker"] is not None]
        marker_counts = Counter(markers)
        repeated_markers = sum(c - 1 for c in marker_counts.values() if c > 1)
        non_monotonic_jumps = sum(
            1 for a, b in zip(markers, markers[1:]) if b != a + 1
        )

        meta_by_case[case_id] = {
            "case_id": case_id,
            "parent_count": len(parents),
            "passage_count": len(passages),
            "split_parents_count": len(split_parents),
            "max_split_count": max_split_count,
            "max_full_input_tokens": max_tokens,
            "passages_at_448_count": count_448,
            "intact_gt_320_le_448_count": intact_gt_320,
            "word_boundary_splits": wb_splits,
            "min_positive_overlap": min_positive_overlap,
            "max_token_to_byte_ratio": round(max_token_to_byte_ratio, 6),
            "utf8_exceptions_count": utf8_exceptions,
            "french_passages_count": french_passages,
            "quoted_passages_count": quoted_passages,
            "unknown_passages_count": unknown_passages,
            "unnumbered_passages_count": unnumbered_passages,
            "unnumbered_split_parents_count": unnumbered_split_parents,
            "no_preview_units_count": no_preview_units,
            "repeated_markers_count": repeated_markers,
            "non_monotonic_jumps_count": non_monotonic_jumps,
        }
    return meta_by_case


def select_regions_for_case(pas_rec, nav_rec):
    """Select up to 3 regions (parent units + target passage) per case deterministically."""
    nav_by_handle = {u["handle"]: u for u in nav_rec["navigation"]}
    passages_by_id = {p["passage_id"]: p for p in pas_rec["passages"]}
    parents = pas_rec["parents"]
    chosen_handles = []
    selected = []

    def add_choice(parent, reason, target_pid=None):
        h = parent["handle"]
        if h in chosen_handles or len(selected) >= 3:
            return False
        refs = parent["passage_refs"]
        if target_pid is None:
            # Prefer middle child if split_count >= 3, else second child if split_count == 2, else first child
            target_pid = refs[len(refs) // 2] if len(refs) > 1 else refs[0]
        chosen_handles.append(h)
        selected.append({
            "handle": h,
            "unit_id": parent["unit_id"],
            "target_passage_id": target_pid,
            "split_count": len(refs),
            "selection_reason": reason,
        })
        return True

    # Slot 1: Split parent (prefer one with passage at 448 cap, else largest split_count),
    # or intact parent with 320 < tokens <= 448, or largest token parent.
    parents_with_448 = [
        (p, ref)
        for p in parents
        for ref in p["passage_refs"]
        if passages_by_id[ref]["full_input_tokens"] == 448
    ]
    if parents_with_448:
        p448, ref448 = parents_with_448[0]
        add_choice(p448, "slot1_split_parent_hitting_448_cap", ref448)
    else:
        split_parents = sorted(
            [p for p in parents if len(p["passage_refs"]) > 1],
            key=lambda p: (-len(p["passage_refs"]), p["handle"]),
        )
        if split_parents:
            add_choice(split_parents[0], "slot1_longest_split_parent_middle_child")
        else:
            intact_over_320 = sorted(
                [p for p in parents if passages_by_id[p["passage_refs"][0]]["full_input_tokens"] > 320],
                key=lambda p: (-passages_by_id[p["passage_refs"][0]]["full_input_tokens"], p["handle"]),
            )
            if intact_over_320:
                add_choice(intact_over_320[0], "slot1_intact_parent_gt_320_le_448")
            else:
                largest_intact = sorted(
                    parents,
                    key=lambda p: (-passages_by_id[p["passage_refs"][0]]["full_input_tokens"], p["handle"]),
                )
                if largest_intact:
                    add_choice(largest_intact[0], "slot1_largest_token_parent")

    # Slot 2: Risk feature unit (no-preview unit > quoted role > repeated/jumping marker > French/Unicode > second split/intact >320)
    no_preview_parents = [p for p in parents if not nav_by_handle[p["handle"]]["preview_refs"] and p["handle"] not in chosen_handles]
    quoted_parents = [p for p in parents if nav_by_handle[p["handle"]]["paragraph_role"] == "quoted" and p["handle"] not in chosen_handles]
    french_parents = [p for p in parents if str(nav_by_handle[p["handle"]]["language_region"]).startswith("fr:") and p["handle"] not in chosen_handles]
    intact_320_parents = [
        p for p in parents
        if len(p["passage_refs"]) == 1 and passages_by_id[p["passage_refs"][0]]["full_input_tokens"] > 320 and p["handle"] not in chosen_handles
    ]

    # Identify jumping/repeated marker parents
    marker_seen = set()
    prev_m = None
    jump_or_repeat_parents = []
    for p in parents:
        u = nav_by_handle[p["handle"]]
        m = u["observed_marker"]
        if m is not None:
            if m in marker_seen or (prev_m is not None and m != prev_m + 1):
                if p["handle"] not in chosen_handles:
                    jump_or_repeat_parents.append(p)
            marker_seen.add(m)
            prev_m = m

    if no_preview_parents:
        add_choice(no_preview_parents[0], "slot2_unit_without_preview_still_indexed")
    elif quoted_parents:
        add_choice(quoted_parents[0], "slot2_quoted_role_parent")
    elif jump_or_repeat_parents:
        add_choice(jump_or_repeat_parents[0], "slot2_jumping_or_repeated_marker_parent")
    elif french_parents:
        add_choice(french_parents[0], "slot2_french_language_region_parent")
    elif intact_320_parents:
        add_choice(intact_320_parents[0], "slot2_intact_parent_gt_320_le_448")
    else:
        remaining_by_tok = sorted(
            [p for p in parents if p["handle"] not in chosen_handles],
            key=lambda p: (-max(passages_by_id[r]["full_input_tokens"] for r in p["passage_refs"]), p["handle"]),
        )
        if remaining_by_tok:
            add_choice(remaining_by_tok[0], "slot2_secondary_high_token_parent")

    # Slot 3: Unnumbered unit (prefer split unnumbered) or source boundary / neighbor chain parent
    unnumbered_parents = sorted(
        [p for p in parents if nav_by_handle[p["handle"]]["unit_kind"] == "unnumbered" and p["handle"] not in chosen_handles],
        key=lambda p: (-len(p["passage_refs"]), p["handle"]),
    )
    if unnumbered_parents:
        add_choice(unnumbered_parents[0], "slot3_unnumbered_unit_neighbor_expansion")
    else:
        remaining = [p for p in parents if p["handle"] not in chosen_handles]
        if remaining:
            add_choice(remaining[-1], "slot3_end_boundary_neighbor_expansion")

    return selected


def extract_region_evidence(case_id, sel, pas_rec, nav_rec, raw: bytes, reader: PassageReader, backend: Tokenizer):
    nav_by_handle = {u["handle"]: u for u in nav_rec["navigation"]}
    passages_by_id = {p["passage_id"]: p for p in pas_rec["passages"]}
    parents_by_handle = {p["handle"]: p for p in pas_rec["parents"]}

    handle = sel["handle"]
    parent = parents_by_handle[handle]
    unit = nav_by_handle[handle]
    refs = parent["passage_refs"]
    target_pid = sel["target_passage_id"]
    hit = passages_by_id[target_pid]
    idx = hit["split_order"]

    ua, ub = parent["span_bytes"]
    parent_raw = raw[ua:ub]
    parent_text = parent_raw.decode("utf-8")
    parent_full_tokens = len(backend.encode(parent_text, add_special_tokens=True).ids)

    ha, hb = hit["span_bytes"]
    hit_raw = raw[ha:hb]
    hit_text = hit_raw.decode("utf-8")
    hit_enc_full = backend.encode(hit_text, add_special_tokens=True)
    hit_enc_content = backend.encode(hit_text, add_special_tokens=False)

    prev_sibling = passages_by_id[hit["previous_sibling_ref"]] if hit["previous_sibling_ref"] else None
    next_sibling = passages_by_id[hit["next_sibling_ref"]] if hit["next_sibling_ref"] else None

    overlap_with_prev_bytes = None
    overlap_with_prev_text = None
    if prev_sibling and ha < prev_sibling["span_bytes"][1]:
        overlap_with_prev_bytes = [ha, prev_sibling["span_bytes"][1]]
        overlap_with_prev_text = raw[ha:prev_sibling["span_bytes"][1]].decode("utf-8")

    overlap_with_next_bytes = None
    overlap_with_next_text = None
    if next_sibling and next_sibling["span_bytes"][0] < hb:
        overlap_with_next_bytes = [next_sibling["span_bytes"][0], hb]
        overlap_with_next_text = raw[next_sibling["span_bytes"][0]:hb].decode("utf-8")

    opened = reader.open_context(case_id, target_pid)
    oa, ob = opened["span_bytes"]
    opened_raw = raw[oa:ob]
    assert opened["text"] == opened_raw.decode("utf-8")
    assert opened["hit_text"] == hit_text == hit["text"]

    return {
        "case_id": case_id,
        "source_hash": pas_rec["source_hash"],
        "handle": handle,
        "unit_id": unit["unit_id"],
        "selection_reason": sel["selection_reason"],
        "unit_kind": unit["unit_kind"],
        "observed_marker": unit["observed_marker"],
        "paragraph_role": unit["paragraph_role"],
        "language_region": unit["language_region"],
        "uncertainties": unit["uncertainties"],
        "preview_refs": unit["preview_refs"],
        "preview_absence_reason": unit["preview_absence_reason"],
        "parent_span_bytes": [ua, ub],
        "parent_byte_length": ub - ua,
        "parent_sha256": sha256_hex(parent_raw),
        "parent_full_input_tokens_unsplit": parent_full_tokens,
        "parent_text_excerpt": parent_text if len(parent_text) <= 1200 else (parent_text[:600] + "\n...[TRUNCATED_IN_EVIDENCE_VIEW_ONLY]...\n" + parent_text[-600:]),
        "split_count": len(refs),
        "passage_refs": refs,
        "target_passage": {
            "passage_id": target_pid,
            "split_order": idx,
            "split_count": hit["split_count"],
            "span_bytes": [ha, hb],
            "span_chars": hit["span_chars"],
            "text_sha256": hit["text_sha256"],
            "exact_input_sha256": hit["exact_input_sha256"],
            "full_input_tokens": hit["full_input_tokens"],
            "reencoded_full_tokens": len(hit_enc_full.ids),
            "reencoded_content_tokens": len(hit_enc_content.ids),
            "trailing_special_token_id": hit_enc_full.ids[-1],
            "overlap_tokens_with_previous": hit["overlap_tokens_with_previous"],
            "boundary_method": hit["boundary_method"],
            "word_boundary_split": hit["word_boundary_split"],
            "previous_sibling_ref": hit["previous_sibling_ref"],
            "next_sibling_ref": hit["next_sibling_ref"],
            "exact_raw_text": hit_text,
            "overlap_with_previous_span_bytes": overlap_with_prev_bytes,
            "overlap_with_previous_exact_raw_text": overlap_with_prev_text,
            "overlap_with_next_span_bytes": overlap_with_next_bytes,
            "overlap_with_next_exact_raw_text": overlap_with_next_text,
        },
        "opened_context": {
            "requested_handle": opened["requested_handle"],
            "hit_passage_id": opened["hit_passage_id"],
            "hit_span_bytes": opened["hit_span_bytes"],
            "opened_span_bytes": [oa, ob],
            "opened_byte_length": ob - oa,
            "opened_raw_sha256": sha256_hex(opened_raw),
            "neighbor_policy": opened["neighbor_policy"],
            "reading_expansion": hit["reading_expansion"],
            "components": opened["components"],
            "intervening_headings": opened["intervening_headings"],
            "hit_is_distinct_from_context": opened["hit_is_distinct_from_context"],
            "diagnostic_only": opened["diagnostic_only"],
            "M4_delivery_recorded": opened["M4_delivery_recorded"],
            "opened_text_head_300": opened["text"][:300],
            "opened_text_tail_300": opened["text"][-300:],
        },
    }


def main():
    t0 = time.perf_counter()
    bundle_dir = ROOT / "pipeline_v2/artifacts/m2_passages_20261106_v1"
    nav_dir = ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v3"
    m1_dir = ROOT / "pipeline_v2/artifacts/m1_20261105_v2"
    m0_dir = ROOT / "pipeline_v2/artifacts/m0_20261105_v2"
    raw_dir = ROOT / "data/task1_train_files_2026/cases"

    cohort = read_json(m0_dir / "cohort.json")
    discovery_set = set(cohort["discovery_queries"])
    holdout_set = set(cohort["holdout_queries"])
    assert len(discovery_set) == 10 and len(holdout_set) == 10

    separate_regression_groups = {
        "m2_passages_middle_child_regression": ["041666.txt"],
        "m1_m2_structural_exposed_fixtures": ["050936.txt", "061295.txt", "062436.txt", "067620.txt"],
        "m2_preview_prompt_8_regressions": [
            "011922.txt", "051807.txt", "080359.txt", "068193.txt",
            "014101.txt", "048208.txt", "081945.txt", "015740.txt",
        ],
        "m2_preview_v2_9_tag_clip_regressions": [
            "004301.txt", "006063.txt", "008545.txt", "013122.txt", "031088.txt",
            "059397.txt", "071931.txt", "093363.txt", "095618.txt",
        ],
    }
    separate_regressions = set()
    for grp in separate_regression_groups.values():
        separate_regressions.update(grp)
    # Remove any accidental overlap with discovery/holdout from separate_regressions if any
    separate_regressions -= (discovery_set | holdout_set)

    registry = read_json(bundle_dir / "source_registry.json")["sources"]
    all_cases = sorted(r["case_id"] for r in registry)
    eligible_cases = sorted(c for c in all_cases if c not in discovery_set and c not in holdout_set and c not in separate_regressions)

    meta_by_case = collect_case_metadata(bundle_dir, nav_dir, m1_dir, registry)

    rng = random.Random(SEED)
    uniform_random_20 = sorted(rng.sample(eligible_cases, 20))
    selected_set = set(uniform_random_20)

    def pick_top(key_fn, n=4):
        ranked = sorted((c for c in eligible_cases if c not in selected_set), key=key_fn)
        chosen = ranked[:n]
        selected_set.update(chosen)
        return sorted(chosen)

    risk_1 = pick_top(
        lambda c: (
            -meta_by_case[c]["passages_at_448_count"],
            -meta_by_case[c]["max_split_count"],
            -meta_by_case[c]["split_parents_count"],
            c,
        )
    )
    risk_2 = pick_top(
        lambda c: (
            -(meta_by_case[c]["french_passages_count"] > 0 and meta_by_case[c]["split_parents_count"] > 0),
            -meta_by_case[c]["utf8_exceptions_count"],
            -meta_by_case[c]["french_passages_count"],
            c,
        )
    )
    risk_3 = pick_top(
        lambda c: (
            -meta_by_case[c]["word_boundary_splits"],
            -(meta_by_case[c]["split_parents_count"] > 0),
            meta_by_case[c]["min_positive_overlap"] if meta_by_case[c]["min_positive_overlap"] > 0 else 999,
            -meta_by_case[c]["max_token_to_byte_ratio"],
            c,
        )
    )
    risk_4 = pick_top(
        lambda c: (
            -(meta_by_case[c]["quoted_passages_count"] > 0 and meta_by_case[c]["split_parents_count"] > 0),
            -meta_by_case[c]["repeated_markers_count"],
            -meta_by_case[c]["non_monotonic_jumps_count"],
            -meta_by_case[c]["quoted_passages_count"],
            c,
        )
    )
    risk_5 = pick_top(
        lambda c: (
            -(meta_by_case[c]["no_preview_units_count"] > 0 and meta_by_case[c]["unnumbered_split_parents_count"] > 0),
            -meta_by_case[c]["no_preview_units_count"],
            -meta_by_case[c]["unnumbered_split_parents_count"],
            -meta_by_case[c]["unnumbered_passages_count"],
            c,
        )
    )

    risk_stratified_20 = {
        "risk_1_long_split_parents_and_448_cap": risk_1,
        "risk_2_unicode_multibyte_and_french": risk_2,
        "risk_3_tight_whitespace_or_fallback_boundary": risk_3,
        "risk_4_jumping_or_repeated_markers_and_quoted": risk_4,
        "risk_5_unknown_unnumbered_and_no_preview": risk_5,
    }
    risk_all = [c for grp in risk_stratified_20.values() for c in grp]
    assert len(uniform_random_20) == 20
    assert len(risk_all) == 20
    assert len(set(uniform_random_20) & set(risk_all)) == 0
    assert len(selected_set) == 40
    assert len(selected_set & (discovery_set | holdout_set)) == 0
    assert len(selected_set & separate_regressions) == 0

    case_selections = []
    for c in uniform_random_20:
        pas_rec = read_json(bundle_dir / "sources" / f"{c[:-4]}.json")
        nav_rec = read_json(nav_dir / "sources" / f"{c[:-4]}.json")
        regs = select_regions_for_case(pas_rec, nav_rec)
        case_selections.append({
            "case_id": c,
            "sample_group": "uniform_random_20",
            "stratum": "uniform_random",
            "metadata_summary": meta_by_case[c],
            "selected_regions": regs,
        })
    for stratum, cases in risk_stratified_20.items():
        for c in cases:
            pas_rec = read_json(bundle_dir / "sources" / f"{c[:-4]}.json")
            nav_rec = read_json(nav_dir / "sources" / f"{c[:-4]}.json")
            regs = select_regions_for_case(pas_rec, nav_rec)
            case_selections.append({
                "case_id": c,
                "sample_group": "risk_stratified_20",
                "stratum": stratum,
                "metadata_summary": meta_by_case[c],
                "selected_regions": regs,
            })

    sampling_manifest = {
        "schema_version": "m2-passages-ag-review-sampling-manifest-v1",
        "seed": SEED,
        "locked_before_reading_raw": True,
        "labels_accessed": False,
        "test_sources_accessed": False,
        "total_corpus_cases": len(all_cases),
        "excluded_discovery_count": len(discovery_set),
        "excluded_holdout_count": len(holdout_set),
        "separate_regression_cases_count": len(separate_regressions),
        "eligible_pool_count": len(eligible_cases),
        "uniform_random_20": uniform_random_20,
        "risk_stratified_20": risk_stratified_20,
        "total_sampled_unique_cases": len(selected_set),
        "overlap_between_uniform_and_risk": 0,
        "overlap_with_discovery_or_holdout": 0,
        "overlap_with_separate_regressions": 0,
        "total_sampled_regions": sum(len(x["selected_regions"]) for x in case_selections),
        "separate_regression_groups": separate_regression_groups,
        "case_selections": case_selections,
    }

    out_dir = ROOT / "pipeline_v2/reviews/m2_passages_ag_review_v1"
    (out_dir / "sampling_manifest.json").write_text(
        json.dumps(sampling_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Now extract raw evidence and open_context for all 120 sampled regions + 10 key separate regression regions
    lock = read_json(ROOT / "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
    backend = Tokenizer.from_file(str(ROOT / lock["assets_dir"] / "tokenizer.json"))
    backend.no_truncation()
    backend.no_padding()
    reader = PassageReader(ROOT, "pipeline_v2/artifacts/m2_passages_20261106_v1")

    sampled_evidence = []
    for entry in case_selections:
        c = entry["case_id"]
        raw = (raw_dir / c).read_bytes()
        pas_rec = read_json(bundle_dir / "sources" / f"{c[:-4]}.json")
        nav_rec = read_json(nav_dir / "sources" / f"{c[:-4]}.json")
        for sel in entry["selected_regions"]:
            ev = extract_region_evidence(c, sel, pas_rec, nav_rec, raw, reader, backend)
            ev["sample_group"] = entry["sample_group"]
            ev["stratum"] = entry["stratum"]
            sampled_evidence.append(ev)

    # Also extract separate regression regions (including 041666/p000417, 041666/p000153, 061295, 067620, 062436, 050936)
    regression_targets = [
        ("041666.txt", "p000417", "041666:6aa38298330c0005b7207373", "regression_041666_largest_split_parent_middle_child"),
        ("041666.txt", "p000153", "041666:3f296642490ce0314e005143", "regression_041666_interior_middle_child_skipping_unnumbered"),
        ("061295.txt", None, None, "regression_061295_quotation_fixture"),
        ("067620.txt", None, None, "regression_067620_bilingual_repeated_marker_fixture"),
        ("062436.txt", None, None, "regression_062436_heading_context_fixture"),
        ("050936.txt", None, None, "regression_050936_quoted_marker_one_fixture"),
    ]
    regression_evidence = []
    for c, h_opt, pid_opt, reason in regression_targets:
        raw = (raw_dir / c).read_bytes()
        pas_rec = read_json(bundle_dir / "sources" / f"{c[:-4]}.json")
        nav_rec = read_json(nav_dir / "sources" / f"{c[:-4]}.json")
        if h_opt is not None:
            parent = next(p for p in pas_rec["parents"] if p["handle"] == h_opt)
            sel = {
                "handle": h_opt,
                "unit_id": parent["unit_id"],
                "target_passage_id": pid_opt or parent["passage_refs"][len(parent["passage_refs"]) // 2],
                "split_count": len(parent["passage_refs"]),
                "selection_reason": reason,
            }
        else:
            regs = select_regions_for_case(pas_rec, nav_rec)
            sel = regs[0]
            sel["selection_reason"] = reason
        ev = extract_region_evidence(c, sel, pas_rec, nav_rec, raw, reader, backend)
        ev["sample_group"] = "separate_regression"
        ev["stratum"] = "separate_regression"
        regression_evidence.append(ev)

    extracted_payload = {
        "schema_version": "m2-passages-ag-review-extracted-regions-v1",
        "seed": SEED,
        "sampled_regions_count": len(sampled_evidence),
        "separate_regression_regions_count": len(regression_evidence),
        "sampled_regions": sampled_evidence,
        "separate_regression_regions": regression_evidence,
        "elapsed_seconds": round(time.perf_counter() - t0, 6),
    }
    (out_dir / "extracted_regions_raw.json").write_text(
        json.dumps(extracted_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": "PASS",
        "sampled_cases": len(selected_set),
        "sampled_regions": len(sampled_evidence),
        "regression_regions": len(regression_evidence),
        "elapsed_seconds": extracted_payload["elapsed_seconds"],
    }))


if __name__ == "__main__":
    main()
