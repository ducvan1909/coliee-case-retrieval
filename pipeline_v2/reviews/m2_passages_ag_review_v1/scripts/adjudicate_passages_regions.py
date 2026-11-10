"""Adjudicate all 120 locked sample regions + 6 separate regression regions for M2 passages review.

Distinguishes mechanical rule verification (`mechanical_integrity = PASS`) from
content/boundary evaluation (`boundary_content_assessment` and `semantic_status`),
with concrete per-region commentary on cut boundaries, overlap slices, and opened context.
"""
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[4]


def classify_boundary(text: str, split_order: int, split_count: int, overlap_text: str | None, next_overlap_text: str | None):
    """Produce a concrete content observation for the passage's start/end boundaries."""
    if split_count == 1:
        return {
            "cut_classification": "intact_whole_parent",
            "start_boundary_observation": "Starts at exact parent start (no split).",
            "end_boundary_observation": "Ends at exact parent end (no split).",
            "semantic_sentence_verified": "unresolved_not_required_for_whole_parent",
        }

    # Check start boundary
    if split_order == 0:
        start_obs = "First child of split parent; starts at exact parent start (including [N] marker if paragraph)."
    else:
        ov_len = len(overlap_text) if overlap_text else 0
        leading_snippet = repr(text[:60])
        start_obs = (
            f"Child {split_order + 1}/{split_count} starts after whitespace snap inside overlap window "
            f"(overlap={ov_len} chars); leading slice={leading_snippet}; sentence boundary not certified."
        )

    # Check end boundary
    if split_order == split_count - 1:
        end_obs = f"Final child ({split_order + 1}/{split_count}); ends at exact parent end."
    else:
        stripped = text.rstrip()
        trailing_snippet = repr(text[-60:])
        ends_punct = bool(re.search(r"[.!?;:]\s*$", stripped))
        end_obs = (
            f"Child {split_order + 1}/{split_count} ends at whitespace boundary near soft target/cap "
            f"({'ends after punctuation/clause mark' if ends_punct else 'cuts mid-sentence between words'}); "
            f"trailing slice={trailing_snippet}; full parent recovered on open_context."
        )

    return {
        "cut_classification": "split_parent_whitespace_cut_not_sentence_verified",
        "start_boundary_observation": start_obs,
        "end_boundary_observation": end_obs,
        "semantic_sentence_verified": "unresolved_whitespace_cut_only",
    }


def adjudicate_region(reg):
    tp = reg["target_passage"]
    oc = reg["opened_context"]

    # Mechanical checks on the extracted evidence
    mech_checks = {
        "exact_raw_text_hash_match": tp["text_sha256"] == tp["exact_input_sha256"],
        "full_tokens_le_448": tp["full_input_tokens"] == tp["reencoded_full_tokens"] <= 448,
        "postprocessor_endoftext_151643": (
            tp["trailing_special_token_id"] == 151643
            and tp["reencoded_full_tokens"] == tp["reencoded_content_tokens"] + 1
        ),
        "overlap_content_only_le_128": tp["overlap_tokens_with_previous"] <= 128,
        "whole_parent_kept_when_le_448": (reg["split_count"] == 1) if reg["parent_full_input_tokens_unsplit"] <= 448 else (reg["split_count"] > 1),
        "open_context_covers_full_parent_and_neighbors": (
            oc["opened_span_bytes"][0] <= reg["parent_span_bytes"][0]
            and reg["parent_span_bytes"][1] <= oc["opened_span_bytes"][1]
            and oc["hit_is_distinct_from_context"] is True
            and oc["diagnostic_only"] is True
            and oc["M4_delivery_recorded"] is False
        ),
    }
    mech_pass = all(mech_checks.values())

    boundary_eval = classify_boundary(
        tp["exact_raw_text"],
        tp["split_order"],
        tp["split_count"],
        tp["overlap_with_previous_exact_raw_text"],
        tp["overlap_with_next_exact_raw_text"],
    )

    comp_summary = [f"{c['kind']}={c['handle']}[{c['span_bytes'][0]}..{c['span_bytes'][1]}]" for c in oc["components"]]

    return {
        "case_id": reg["case_id"],
        "sample_group": reg["sample_group"],
        "stratum": reg["stratum"],
        "handle": reg["handle"],
        "unit_id": reg["unit_id"],
        "selection_reason": reg["selection_reason"],
        "unit_kind": reg["unit_kind"],
        "observed_marker": reg["observed_marker"],
        "paragraph_role": reg["paragraph_role"],
        "language_region": reg["language_region"],
        "preview_refs_count": len(reg["preview_refs"]),
        "preview_absence_reason": reg["preview_absence_reason"],
        "parent_span_bytes": reg["parent_span_bytes"],
        "parent_full_input_tokens_unsplit": reg["parent_full_input_tokens_unsplit"],
        "split_count": reg["split_count"],
        "target_passage_id": tp["passage_id"],
        "split_order": tp["split_order"],
        "passage_span_bytes": tp["span_bytes"],
        "full_input_tokens": tp["full_input_tokens"],
        "overlap_tokens_with_previous": tp["overlap_tokens_with_previous"],
        "boundary_method": tp["boundary_method"],
        "word_boundary_split": tp["word_boundary_split"],
        "opened_context_span_bytes": oc["opened_span_bytes"],
        "opened_components_summary": comp_summary,
        "intervening_headings_count": len(oc["intervening_headings"]),
        "mechanical_integrity": "PASS" if mech_pass else "FAIL",
        "mechanical_checks": mech_checks,
        "boundary_content_assessment": boundary_eval,
        "semantic_ownership_and_retrieval_optimality": "unresolved_by_design_in_M2",
        "commentary": (
            f"Case {reg['case_id']} {reg['handle']} ({reg['unit_kind']}, marker={reg['observed_marker']}, "
            f"role={reg['paragraph_role']}, lang={reg['language_region']}): parent has {reg['parent_full_input_tokens_unsplit']} "
            f"full tokens ({reg['parent_byte_length']} bytes) -> split_count={reg['split_count']}. "
            f"Inspected passage {tp['passage_id']} (child {tp['split_order'] + 1}/{tp['split_count']}, "
            f"bytes {tp['span_bytes'][0]}..{tp['span_bytes'][1]}, full_tokens={tp['full_input_tokens']}, "
            f"overlap_content_tokens={tp['overlap_tokens_with_previous']}). "
            f"{boundary_eval['end_boundary_observation']} "
            f"open_context expands to {', '.join(comp_summary)} ({oc['opened_byte_length']} bytes, "
            f"{len(oc['intervening_headings'])} intervening headings)."
        ),
    }


def main():
    t0 = time.perf_counter()
    rev_dir = ROOT / "pipeline_v2/reviews/m2_passages_ag_review_v1"
    extracted = json.loads((rev_dir / "extracted_regions_raw.json").read_bytes())

    sampled_adj = [adjudicate_region(r) for r in extracted["sampled_regions"]]
    regression_adj = [adjudicate_region(r) for r in extracted["separate_regression_regions"]]

    summary = {
        "sampled_regions_total": len(sampled_adj),
        "sampled_mechanical_integrity_pass": sum(1 for x in sampled_adj if x["mechanical_integrity"] == "PASS"),
        "sampled_mechanical_integrity_fail": sum(1 for x in sampled_adj if x["mechanical_integrity"] != "PASS"),
        "sampled_split_parent_regions": sum(1 for x in sampled_adj if x["split_count"] > 1),
        "sampled_intact_parent_regions": sum(1 for x in sampled_adj if x["split_count"] == 1),
        "sampled_intact_gt_320_le_448_regions": sum(
            1 for x in sampled_adj if x["split_count"] == 1 and x["full_input_tokens"] > 320
        ),
        "sampled_passages_at_448_cap": sum(1 for x in sampled_adj if x["full_input_tokens"] == 448),
        "sampled_no_preview_units_still_indexed": sum(1 for x in sampled_adj if x["preview_refs_count"] == 0),
        "sampled_quoted_role_regions": sum(1 for x in sampled_adj if x["paragraph_role"] == "quoted"),
        "sampled_unnumbered_regions": sum(1 for x in sampled_adj if x["unit_kind"] == "unnumbered"),
        "sampled_french_regions": sum(1 for x in sampled_adj if str(x["language_region"]).startswith("fr:")),
        "separate_regression_regions_total": len(regression_adj),
        "separate_regression_mechanical_integrity_pass": sum(
            1 for x in regression_adj if x["mechanical_integrity"] == "PASS"
        ),
        "semantic_ownership_and_retrieval_optimality_status": "all_marked_unresolved_by_design_in_M2",
    }

    payload = {
        "schema_version": "m2-passages-ag-review-reviewed-regions-v1",
        "summary": summary,
        "sampled_regions_adjudication": sampled_adj,
        "separate_regression_regions_adjudication": regression_adj,
        "elapsed_seconds": round(time.perf_counter() - t0, 6),
    }
    (rev_dir / "reviewed_regions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "PASS", "summary": summary, "elapsed_seconds": payload["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
