"""Sample inspection and region extractor for locked 24 cases.

Applies the locked region selection rules (max 3 regions per case):
- Random normal cases: (1) Header-to-para1 boundary, (2) Median paragraph boundary, (3) Document tail / conclusion.
- High quote marker cases: (1) First quote marker boundary, (2) Transition back to outer sequence or next paragraph, (3) Header-to-para1 boundary.
- Reset / bilingual cases: (1) Pre-reset text & boundary, (2) Reset [1] marker and following text, (3) Language cue / separator context.
- High unnumbered ratio cases: (1) Boundary into unnumbered region, (2) Internal content of unnumbered block, (3) Boundary exiting unnumbered region.
- Heading / outer quote cases: (1) Heading candidate context, (2) Outer quote collision candidate, (3) Known heading or typical boundary.

Extracts ample raw context (minimum 300-600 characters around boundary).
"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
M1_BUNDLE = ROOT / "pipeline_v2" / "artifacts" / "m1_20261105_v1"
CORPUS_DIR = ROOT / "data" / "task1_train_files_2026" / "cases"
SAMPLING_PATH = ROOT / "pipeline_v2" / "reviews" / "m1_review_v1" / "sampling_manifest.json"
OUTPUT_REGIONS_PATH = ROOT / "pipeline_v2" / "reviews" / "m1_review_v1" / "extracted_regions_raw.json"


def get_context(raw: bytes, start_byte: int, end_byte: int, context_bytes: int = 400):
    ctx_start = max(0, start_byte - context_bytes)
    ctx_end = min(len(raw), end_byte + context_bytes)

    # Align to UTF-8
    while ctx_start > 0:
        try:
            raw[ctx_start:start_byte].decode("utf-8")
            break
        except UnicodeDecodeError:
            ctx_start -= 1

    while ctx_end < len(raw):
        try:
            raw[end_byte:ctx_end].decode("utf-8")
            break
        except UnicodeDecodeError:
            ctx_end += 1

    before_text = raw[ctx_start:start_byte].decode("utf-8", errors="replace")
    focus_text = raw[start_byte:end_byte].decode("utf-8", errors="replace")
    after_text = raw[end_byte:ctx_end].decode("utf-8", errors="replace")

    return {
        "context_span_bytes": [ctx_start, ctx_end],
        "focus_span_bytes": [start_byte, end_byte],
        "before_context": before_text,
        "focus_text": focus_text,
        "after_context": after_text,
    }


def select_regions_for_case(case_info, rec, raw):
    case_id = case_info["case_id"]
    group = case_info.get("group", "random_uniform")
    units = rec["units"]
    sidecars = rec.get("sidecars", [])
    paragraphs = [u for u in units if u["unit_kind"] == "paragraph"]
    headings = [u for u in units if u["unit_kind"] == "heading"]
    unnumbered = [u for u in units if u["unit_kind"] == "unnumbered"]

    regions = []

    if group == "risk_a_high_quote_markers":
        # Region 1: First sidecar
        if sidecars:
            s0 = sidecars[0]
            ctx = get_context(raw, s0["span_bytes"][0], min(s0["span_bytes"][1], s0["span_bytes"][0] + 150))
            regions.append({
                "region_id": f"{case_id[:-4]}_R1_first_quote_sidecar",
                "target_type": "sidecar",
                "target_id": s0.get("observed_marker"),
                "span_bytes": s0["span_bytes"],
                "parent_unit_id": s0.get("parent_unit_id"),
                "rationale": "Verify whether first quote sidecar is genuinely inside quotation or misclassified outer paragraph.",
                **ctx
            })

        # Region 2: Last sidecar or sidecar cluster
        if len(sidecars) > 1:
            s_last = sidecars[-1]
            ctx = get_context(raw, s_last["span_bytes"][0], min(s_last["span_bytes"][1], s_last["span_bytes"][0] + 150))
            regions.append({
                "region_id": f"{case_id[:-4]}_R2_last_quote_sidecar",
                "target_type": "sidecar",
                "target_id": s_last.get("observed_marker"),
                "span_bytes": s_last["span_bytes"],
                "parent_unit_id": s_last.get("parent_unit_id"),
                "rationale": "Verify whether subsequent numbered paragraphs were swallowed as sidecars.",
                **ctx
            })

        # Region 3: Initial paragraph or heading boundary
        if paragraphs:
            p0 = paragraphs[0]
            ctx = get_context(raw, p0["span_bytes"][0], min(p0["span_bytes"][1], p0["span_bytes"][0] + 150))
            regions.append({
                "region_id": f"{case_id[:-4]}_R3_initial_paragraph_boundary",
                "target_type": "paragraph_boundary",
                "target_id": p0["unit_id"],
                "span_bytes": p0["span_bytes"],
                "rationale": "Verify transition from header/title into initial paragraph.",
                **ctx
            })

    elif group == "risk_b_reset_or_bilingual":
        # Region 1: Reset paragraph [1]
        reset_paras = [p for p in paragraphs if "translation_boundary_observed" in p.get("uncertainties", [])
                       or "numbering_reset_language_unknown" in p.get("uncertainties", [])
                       or (p["observed_marker"] == 1 and p["order"] > 0 and any(p2["observed_marker"] == 1 for p2 in paragraphs[:paragraphs.index(p)]))]
        if reset_paras:
            rp = reset_paras[0]
            ctx = get_context(raw, rp["span_bytes"][0], min(rp["span_bytes"][1], rp["span_bytes"][0] + 200))
            regions.append({
                "region_id": f"{case_id[:-4]}_R1_reset_marker_boundary",
                "target_type": "reset_paragraph",
                "target_id": rp["unit_id"],
                "span_bytes": rp["span_bytes"],
                "language_region": rp.get("language_region"),
                "uncertainties": rp.get("uncertainties", []),
                "rationale": "Examine raw context around numbering reset [1] to determine if truly French or false reset.",
                **ctx
            })

        # Region 2: Initial paragraph [1] for comparison
        if paragraphs:
            p0 = paragraphs[0]
            ctx = get_context(raw, p0["span_bytes"][0], min(p0["span_bytes"][1], p0["span_bytes"][0] + 200))
            regions.append({
                "region_id": f"{case_id[:-4]}_R2_first_para_boundary",
                "target_type": "first_paragraph",
                "target_id": p0["unit_id"],
                "span_bytes": p0["span_bytes"],
                "language_region": p0.get("language_region"),
                "rationale": "Examine first paragraph language and structure to contrast with reset.",
                **ctx
            })

        # Region 3: Intermediate boundary or heading between [1]s
        if len(reset_paras) > 0 and paragraphs:
            # pick unit just before reset paragraph
            rp = reset_paras[0]
            rp_idx = units.index(rp)
            prev_u = units[max(0, rp_idx - 1)]
            ctx = get_context(raw, prev_u["span_bytes"][0], prev_u["span_bytes"][1])
            regions.append({
                "region_id": f"{case_id[:-4]}_R3_pre_reset_separator",
                "target_type": "pre_reset_unit",
                "target_id": prev_u["unit_id"],
                "span_bytes": prev_u["span_bytes"],
                "unit_kind": prev_u["unit_kind"],
                "rationale": "Check separator or cue preceding reset (e.g. [translation], stars, dots).",
                **ctx
            })

    elif group == "risk_c_high_unnumbered_ratio":
        # Region 1: Largest unnumbered unit
        if unnumbered:
            largest_un = max(unnumbered, key=lambda u: u["span_bytes"][1] - u["span_bytes"][0])
            ctx = get_context(raw, largest_un["span_bytes"][0], min(largest_un["span_bytes"][1], largest_un["span_bytes"][0] + 300))
            regions.append({
                "region_id": f"{case_id[:-4]}_R1_largest_unnumbered_block",
                "target_type": "unnumbered_block",
                "target_id": largest_un["unit_id"],
                "span_bytes": largest_un["span_bytes"],
                "rationale": "Check why this large unnumbered block was not parsed into paragraphs or headings.",
                **ctx
            })

        # Region 2: Transition into first paragraph
        if paragraphs:
            p0 = paragraphs[0]
            ctx = get_context(raw, p0["span_bytes"][0], min(p0["span_bytes"][1], p0["span_bytes"][0] + 200))
            regions.append({
                "region_id": f"{case_id[:-4]}_R2_unnumbered_to_para_transition",
                "target_type": "transition",
                "target_id": p0["unit_id"],
                "span_bytes": p0["span_bytes"],
                "rationale": "Check boundary between header unnumbered region and first paragraph.",
                **ctx
            })

        # Region 3: Any other unnumbered or heading unit
        if len(unnumbered) > 1:
            other_un = sorted(unnumbered, key=lambda u: u["span_bytes"][1] - u["span_bytes"][0], reverse=True)[1]
            ctx = get_context(raw, other_un["span_bytes"][0], min(other_un["span_bytes"][1], other_un["span_bytes"][0] + 200))
            regions.append({
                "region_id": f"{case_id[:-4]}_R3_secondary_unnumbered_block",
                "target_type": "unnumbered_block",
                "target_id": other_un["unit_id"],
                "span_bytes": other_un["span_bytes"],
                "rationale": "Check secondary unnumbered region for missing structure.",
                **ctx
            })

    elif group == "risk_d_heading_or_outer_quote":
        # Region 1: First heading candidate
        h_cands = [u for u in units if "heading_candidate" in u.get("uncertainties", [])]
        if h_cands:
            hc = h_cands[0]
            ctx = get_context(raw, hc["span_bytes"][0], hc["span_bytes"][1])
            regions.append({
                "region_id": f"{case_id[:-4]}_R1_heading_candidate",
                "target_type": "heading_candidate",
                "target_id": hc["unit_id"],
                "span_bytes": hc["span_bytes"],
                "rationale": "Verify whether candidate is a genuine legal heading or party/counsel/sentence fragment.",
                **ctx
            })

        # Region 2: Outer quote collision candidate
        oq_paras = [u for u in paragraphs if "possible_quotation_at_outer_sequence" in u.get("uncertainties", [])]
        if oq_paras:
            oq = oq_paras[0]
            ctx = get_context(raw, oq["span_bytes"][0], min(oq["span_bytes"][1], oq["span_bytes"][0] + 250))
            regions.append({
                "region_id": f"{case_id[:-4]}_R2_outer_quote_collision",
                "target_type": "paragraph",
                "target_id": oq["unit_id"],
                "span_bytes": oq["span_bytes"],
                "rationale": "Examine outer sequence paragraph with possible quotation cue to verify outer vs quote.",
                **ctx
            })
        elif len(h_cands) > 1:
            hc2 = h_cands[1]
            ctx = get_context(raw, hc2["span_bytes"][0], hc2["span_bytes"][1])
            regions.append({
                "region_id": f"{case_id[:-4]}_R2_heading_candidate_2",
                "target_type": "heading_candidate",
                "target_id": hc2["unit_id"],
                "span_bytes": hc2["span_bytes"],
                "rationale": "Verify second candidate heading.",
                **ctx
            })

        # Region 3: Known heading or typical boundary
        known_h = [u for u in headings if "heading_candidate" not in u.get("uncertainties", [])]
        if known_h:
            kh = known_h[0]
            ctx = get_context(raw, kh["span_bytes"][0], kh["span_bytes"][1])
            regions.append({
                "region_id": f"{case_id[:-4]}_R3_known_heading",
                "target_type": "known_heading",
                "target_id": kh["unit_id"],
                "span_bytes": kh["span_bytes"],
                "rationale": "Compare candidate with known heading.",
                **ctx
            })
        elif paragraphs:
            p0 = paragraphs[0]
            ctx = get_context(raw, p0["span_bytes"][0], min(p0["span_bytes"][1], p0["span_bytes"][0] + 200))
            regions.append({
                "region_id": f"{case_id[:-4]}_R3_para_boundary",
                "target_type": "paragraph",
                "target_id": p0["unit_id"],
                "span_bytes": p0["span_bytes"],
                "rationale": "Examine initial paragraph boundary.",
                **ctx
            })

    else:
        # Random uniform case:
        # Region 1: Header to Para 1
        if paragraphs:
            p0 = paragraphs[0]
            ctx = get_context(raw, p0["span_bytes"][0], min(p0["span_bytes"][1], p0["span_bytes"][0] + 200))
            regions.append({
                "region_id": f"{case_id[:-4]}_R1_header_to_para1",
                "target_type": "initial_paragraph",
                "target_id": p0["unit_id"],
                "span_bytes": p0["span_bytes"],
                "rationale": "Check boundary from metadata/header to first paragraph.",
                **ctx
            })

        # Region 2: Median paragraph
        if len(paragraphs) > 2:
            pmid = paragraphs[len(paragraphs) // 2]
            ctx = get_context(raw, pmid["span_bytes"][0], min(pmid["span_bytes"][1], pmid["span_bytes"][0] + 200))
            regions.append({
                "region_id": f"{case_id[:-4]}_R2_mid_paragraph",
                "target_type": "mid_paragraph",
                "target_id": pmid["unit_id"],
                "span_bytes": pmid["span_bytes"],
                "rationale": "Check middle paragraph boundary and text integrity.",
                **ctx
            })

        # Region 3: Final paragraph
        if len(paragraphs) > 1:
            plast = paragraphs[-1]
            ctx = get_context(raw, plast["span_bytes"][0], min(plast["span_bytes"][1], plast["span_bytes"][0] + 200))
            regions.append({
                "region_id": f"{case_id[:-4]}_R3_final_paragraph",
                "target_type": "final_paragraph",
                "target_id": plast["unit_id"],
                "span_bytes": plast["span_bytes"],
                "rationale": "Check conclusion/final paragraph boundary.",
                **ctx
            })

    return regions[:3]


def main():
    with open(SAMPLING_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    all_cases = manifest["random_sample"] + manifest["risk_sample"]
    extracted = {}

    for c in all_cases:
        cid = c["case_id"]
        raw_path = CORPUS_DIR / cid
        raw = raw_path.read_bytes()
        struct_path = M1_BUNDLE / "sources" / f"{cid[:-4]}.json"
        with open(struct_path, "r", encoding="utf-8") as sf:
            rec = json.load(sf)
        regs = select_regions_for_case(c, rec, raw)
        extracted[cid] = regs

    total_regions = sum(len(r) for r in extracted.values())
    print(f"Extracted {total_regions} regions across {len(extracted)} cases.")
    with open(OUTPUT_REGIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(extracted, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
