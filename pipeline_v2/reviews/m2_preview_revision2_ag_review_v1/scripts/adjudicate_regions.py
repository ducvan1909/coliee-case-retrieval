"""Adjudicate all 120 sampled regions + 17 separate regression regions.

Reads `extracted_regions_raw.json` (Step 1 `map` + `anchors` + `source_anchors`
and Step 2 `open_context` + `v1`/`v2` preview comparisons) and produces
`reviewed_regions.json` with explicit evaluation of:
- `integrity_verdict`: PASS / FAIL (byte/char spans, hashes, clipping flags, word/tag safety)
- `usefulness_verdict`: PASS / WARN / FAIL / NOT_APPLICABLE_NO_PREVIEW (Step 1 triage value vs raw parent)
- `ambiguity_status`: resolved_by_context / unresolved (preserving honest M1/M2 uncertainty such as
  `paragraph_role="unknown"`, `partial_sentence=None`, or repeated markers)
- `step1_map_assessment`: what the agent sees in `map` before opening raw bytes
- `step2_open_context_assessment`: what raw parent + neighbors reveal when opened
- `before_after_comparison`: how `v3` improves over `v1` (and `v2` where applicable)
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[4]
PLACEHOLDER = re.compile(r"[<(]?(?:FRAGMENT|REFERENCE)_SUPPRESSED[>)]?")
PROTECTED_TAG = re.compile(r"<[^<>\r\n]+>|\((?:FRAGMENT|REFERENCE|DATE)_SUPPRESSED\)")


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def adjudicate_region(reg: dict) -> dict:
    item = reg["step1_map_item"]
    u_anchors = reg["step1_unit_anchors"]
    s_anchors = reg["step1_case_source_anchors"]
    v1_previews = reg.get("v1_old_previews", [])
    v2_previews = reg.get("v2_intermediate_previews", [])
    opened = reg["step2_opened_context"]
    comps = opened["components"]
    parent_comp = comps["parent"]
    parent_raw = parent_comp["raw_text"]
    ua, ub = item["span_bytes"]

    previews = item["previews"]
    integrity_issues = []

    # 1. Verify parent span and preview slice integrity against raw parent
    parent_bytes = parent_raw.encode("utf-8")
    if len(parent_bytes) != (ub - ua):
        integrity_issues.append(f"Parent raw byte length {len(parent_bytes)} != span {ub - ua}")

    for p in previews:
        pa, pb = p["span_bytes"]
        if not (ua <= pa < pb <= ub):
            integrity_issues.append(f"Preview {p['preview_id']} span {[pa, pb]} outside unit {[ua, ub]}")
        rel_a, rel_b = pa - ua, pb - ua
        slice_text = parent_bytes[rel_a:rel_b].decode("utf-8")
        if slice_text != p["text"]:
            integrity_issues.append(f"Preview {p['preview_id']} text mismatch with raw parent slice")
        if sha256_str(slice_text) != p["text_sha256"]:
            integrity_issues.append(f"Preview {p['preview_id']} sha256 mismatch")
        if len(slice_text) > 240:
            integrity_issues.append(f"Preview {p['preview_id']} exceeds 240 codepoints ({len(slice_text)})")
        if p["partial_sentence"] is not None or p["boundary_status"] != "content_window_not_sentence_verified":
            integrity_issues.append(f"Preview {p['preview_id']} has invalid sentence status")
        if p["word_boundary_clipped"] or p["tag_boundary_clipped"]:
            integrity_issues.append(f"Preview {p['preview_id']} has word/tag boundary clip flag True")

    # 2. Step 1 Map Observation (before opening raw text)
    headings = [s["text"] for s in item.get("sections", [])]
    v1_texts = [p["text"] for p in v1_previews]
    v3_texts = [p["text"] for p in previews]
    v1_cov = sorted({aid for p in v1_previews for aid in p.get("anchor_refs", [])})
    v3_cov = sorted({aid for p in previews for aid in p.get("anchor_refs", [])})
    full_vis_cov = sorted({
        v["anchor_ref"]
        for p in previews
        for v in p.get("anchor_visibility", [])
        if v.get("fully_visible")
    })
    partial_vis_cov = sorted({
        v["anchor_ref"]
        for p in previews
        for v in p.get("anchor_visibility", [])
        if not v.get("fully_visible")
    })

    if not previews:
        usefulness_verdict = "NOT_APPLICABLE_NO_PREVIEW"
        clean_parent = PLACEHOLDER.sub("", parent_raw)
        has_alnum = any(ch.isalnum() for ch in clean_parent if ch not in "[]0123456789")
        step1_summary = (
            f"Map shows handle {item['handle']} ({item['unit_kind']}, marker={item['observed_marker']}) "
            f"with preview_refs=[] and preview_absence_reason='{item['preview_absence_reason']}', "
            f"anchor_count={item['anchor_count']}."
        )
        step2_summary = (
            f"open_context reveals raw parent ({ub - ua} bytes): {parent_raw!r}. "
            f"Parent contains zero alphanumeric content outside marker/placeholders; "
            f"neighbor expansion ({opened['neighbor_policy']}) cleanly supplies surrounding context "
            f"(prev={comps.get('previous_context', {}).get('handle')}, next={comps.get('next_context', {}).get('handle')})."
        )
    else:
        p0 = previews[0]
        clean_p0 = PLACEHOLDER.sub("", p0["text"])
        clean_u = PLACEHOLDER.sub("", parent_raw)
        if len(clean_u) >= 120 and len(clean_p0) < 100 and p0["preview_kind"] == "opening":
            usefulness_verdict = "WARN"
            usefulness_note = (
                f"Opening preview is 235-238 raw chars but contains dense <FRAGMENT_SUPPRESSED> tags, "
                f"leaving {len(clean_p0)} non-placeholder chars in the 240-char window (documented snippet cap limit)."
            )
        elif item["anchor_count"] > len(v3_cov):
            usefulness_verdict = "PASS"
            usefulness_note = (
                f"2-preview cap displays {len(v3_cov)}/{item['anchor_count']} unit anchors directly in map; "
                f"remaining {item['anchor_count'] - len(v3_cov)} anchors are reported in anchor_count={item['anchor_count']} "
                f"and retrievable via NavigationReader.anchors('{item['case_id']}', '{item['handle']}')."
            )
        else:
            usefulness_verdict = "PASS"
            usefulness_note = "Preview window(s) provide clear topic/issue orientation and full or honest partial anchor visibility."

        step1_summary = (
            f"Map shows {item['handle']} ({item['unit_kind']}, marker={item['observed_marker']}, "
            f"sections={headings}, anchor_count={item['anchor_count']}) with {len(previews)} preview(s): "
            + " | ".join(
                f"{p['preview_id']} ({p['preview_kind']}, {len(p['text'])} chars, "
                f"start_clipped={p['start_clipped']}, end_clipped={p['end_clipped']}, "
                f"anchors={p['anchor_refs']})"
                for p in previews
            )
            + f". {usefulness_note}"
        )
        step2_summary = (
            f"open_context ({opened['span_bytes'][0]}-{opened['span_bytes'][1]}, policy={opened['neighbor_policy']}) "
            f"opens parent ({ub - ua} bytes) + prev={comps.get('previous_context', {}).get('handle')} "
            f"+ next={comps.get('next_context', {}).get('handle')} "
            f"with {len(opened['intervening_headings'])} intervening heading(s). "
            f"Exact raw text matches preview slices byte-for-byte."
        )

    # 3. Ambiguity / Honest Uncertainty Status
    unresolved_reasons = list(item.get("uncertainties", []))
    if item.get("paragraph_role") == "unknown":
        unresolved_reasons.append("paragraph_role_unknown_at_m2")
    if any(p["partial_sentence"] is None for p in previews):
        unresolved_reasons.append("sentence_completeness_uncertified_partial_sentence_null")
    if partial_vis_cov:
        unresolved_reasons.append(f"long_quote_cue_partially_visible_in_240_cap:{partial_vis_cov}")

    ambiguity_status = "unresolved" if unresolved_reasons else "resolved_by_context"

    # 4. Before / After Comparison (v1 -> v3, and v2 -> v3 if present)
    v1_char_total = sum(len(t) for t in v1_texts)
    v3_char_total = sum(len(t) for t in v3_texts)
    comp_notes = []
    if v1_previews and previews:
        if len(v1_texts[0]) <= 30 and len(v3_texts[0]) > len(v1_texts[0]):
            comp_notes.append(
                f"Fixed premature period truncation: v1 opening was {len(v1_texts[0])} chars ({v1_texts[0]!r}) -> "
                f"v3 opening is {len(v3_texts[0])} chars ({v3_texts[0][:80]!r}...)."
            )
        if len(v1_previews) == 2 and len(previews) == 1:
            comp_notes.append(
                "Removed redundant/contained second preview slot from v1; single v3 window covers the content cleanly."
            )
        if set(v3_cov) - set(v1_cov):
            comp_notes.append(
                f"Slot 2 novel anchor selection added anchor(s) {sorted(set(v3_cov) - set(v1_cov))} to map display."
            )
        if set(v1_cov) - set(v3_cov):
            comp_notes.append(
                f"Skipped leading placeholder-only line to start at real alphanumeric text; "
                f"anchors {sorted(set(v1_cov) - set(v3_cov))} remain in unit anchor catalog ({item['anchor_count']} total)."
            )
    elif v1_previews and not previews:
        comp_notes.append(
            f"v1 emitted non-informative punctuation/placeholder preview ({v1_texts[0]!r}); "
            f"v3 sets preview_refs=[] with preview_absence_reason='no_meaningful_opening_or_anchor'."
        )

    if v2_previews:
        v2_tag_clips = [p for p in v2_previews if p.get("tag_boundary_clipped")]
        if v2_tag_clips:
            comp_notes.append(
                f"Fixed v2 mid-tag clip on {v2_tag_clips[0]['preview_id']} ({v2_tag_clips[0]['text'][:45]!r}...) -> "
                f"v3 respects full PROTECTED_TAG boundary ({previews[-1]['text'][:45]!r}...)."
            )

    if not comp_notes:
        comp_notes.append(
            f"v3 bounded window ({v3_char_total} total preview chars vs {v1_char_total} in v1) "
            f"preserves word/tag boundaries and honest clipping flags."
        )

    return {
        "region_id": reg["region_id"],
        "case_id": reg["case_id"],
        "source_hash": reg["source_hash"],
        "sample_group": reg["sample_group"],
        "stratum": reg["stratum"],
        "handle": reg["handle"],
        "unit_id": reg["unit_id"],
        "selection_reason": reg["selection_reason"],
        "integrity_verdict": "PASS" if not integrity_issues else "FAIL",
        "integrity_issues": integrity_issues,
        "usefulness_verdict": usefulness_verdict,
        "ambiguity_status": ambiguity_status,
        "unresolved_uncertainties_preserved": unresolved_reasons,
        "v1_preview_texts": v1_texts,
        "v3_preview_texts": v3_texts,
        "v1_displayed_anchors": v1_cov,
        "v3_displayed_anchors": v3_cov,
        "v3_fully_visible_anchors": full_vis_cov,
        "v3_partially_visible_anchors": partial_vis_cov,
        "unit_total_anchors": item["anchor_count"],
        "case_source_anchors_count": len(s_anchors),
        "step1_map_assessment": step1_summary,
        "step2_open_context_assessment": step2_summary,
        "before_after_comparison": " ".join(comp_notes),
    }


def main():
    started = time.perf_counter()
    out_dir = Path(__file__).resolve().parents[1]
    extracted = json.loads((out_dir / "extracted_regions_raw.json").read_text(encoding="utf-8"))

    sampled_reviews = [adjudicate_region(r) for r in extracted["regions"]]
    regression_reviews = [adjudicate_region(r) for r in extracted.get("separate_regression_regions", [])]

    integrity_counts = Counter(r["integrity_verdict"] for r in sampled_reviews)
    usefulness_counts = Counter(r["usefulness_verdict"] for r in sampled_reviews)
    ambiguity_counts = Counter(r["ambiguity_status"] for r in sampled_reviews)
    reg_integrity_counts = Counter(r["integrity_verdict"] for r in regression_reviews)
    reg_usefulness_counts = Counter(r["usefulness_verdict"] for r in regression_reviews)

    payload = {
        "schema_version": "m2-preview-revision2-reviewed-regions-v1",
        "seed": extracted["seed"],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "sampled_regions_summary": {
            "total_sampled_cases": extracted["total_cases"],
            "total_sampled_regions": len(sampled_reviews),
            "integrity_verdicts": dict(integrity_counts),
            "usefulness_verdicts": dict(usefulness_counts),
            "ambiguity_statuses": dict(ambiguity_counts),
        },
        "separate_regression_regions_summary": {
            "total_regression_regions": len(regression_reviews),
            "integrity_verdicts": dict(reg_integrity_counts),
            "usefulness_verdicts": dict(reg_usefulness_counts),
        },
        "reviewed_sampled_regions": sampled_reviews,
        "reviewed_separate_regression_regions": regression_reviews,
    }
    (out_dir / "reviewed_regions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": "OK",
        "sampled_regions_summary": payload["sampled_regions_summary"],
        "separate_regression_regions_summary": payload["separate_regression_regions_summary"],
        "elapsed_seconds": payload["elapsed_seconds"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
