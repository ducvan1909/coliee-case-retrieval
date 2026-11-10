"""Metamorphic tests for M1 Revision 2:
Verify that changing marker numbers (relabeling, skipping, backwards, repeated [1])
preserves identical paragraph unit boundaries, unit kinds, roles, and language regions,
without altering structural partitioning (aside from unit IDs, hashes, and observed marker values).
Also tests quotation boundary non-leakage (cue on one paragraph must not leak quoted role infinitely).
"""
import copy
import json
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

# Note: We import parse_source only to test its invariant under input transformations
from pipeline_v2.source.core import parse_source, M1Error
CORPUS_DIR = REPO_ROOT / "data/task1_train_files_2026/cases"

FIXTURES = [
    "061295.txt",
    "067620.txt",
    "062436.txt",
    "000758.txt",
    "050936.txt",
    "000432.txt",
    "014069.txt",
    "046028.txt",
]


def test_metamorphic_transformations():
    results = {}
    all_pass = True

    for case_id in FIXTURES:
        raw_path = CORPUS_DIR / case_id
        raw_original = raw_path.read_bytes()
        text_original = raw_original.decode("utf-8")

        # Parse original
        rec_orig = parse_source(case_id, raw_original)
        orig_paragraphs = [u for u in rec_orig["units"] if u["unit_kind"] == "paragraph"]
        orig_kinds = [u["unit_kind"] for u in rec_orig["units"]]
        orig_roles = [u["paragraph_role"] for u in orig_paragraphs]
        orig_languages = [u["language_region"] for u in orig_paragraphs]
        orig_char_spans = [u["span_chars"] for u in rec_orig["units"]]

        case_results = {}

        # Transformation 1: Forward jumps (pad numbers with +500)
        # Keep same marker width to preserve exact byte/char offsets
        # If original marker was [1], width=3: "[1]". Replace with "[9]" or if 2 digits "[12]" -> "[99]".
        # Or test with variable width and check relative structure.
        # But even better: test both:
        # A) Same width renumbering: [01], [02], etc. or reverse digits
        # B) Arbitrary jumps / backward renumbering: test that boundary partition, kinds, and roles match 1-to-1 in sequence!

        # Let's do Transformation A: Reverse sequence of numbers (e.g. 50, 49, 48...)
        # Find all line start markers in text:
        marker_pattern = re.compile(r"(?m)^([ \t\ufeff]*)\[([0-9]+)\]")

        def replace_numbers_reverse(match):
            prefix = match.group(1)
            # Just keep prefix and bracket, substitute descending number
            # We will use a stateful generator
            return f"{prefix}[{next(gen_rev)}]"

        # Collect count of markers
        matches = list(marker_pattern.finditer(text_original))
        total_m = len(matches)

        # Transformation 1: Descending numbers [9000], [8999], ...
        gen_rev = (str(9000 - i) for i in range(total_m))
        text_descending = marker_pattern.sub(replace_numbers_reverse, text_original)
        raw_descending = text_descending.encode("utf-8")
        rec_descending = parse_source(case_id, raw_descending)

        desc_paragraphs = [u for u in rec_descending["units"] if u["unit_kind"] == "paragraph"]
        desc_kinds = [u["unit_kind"] for u in rec_descending["units"]]
        desc_roles = [u["paragraph_role"] for u in desc_paragraphs]
        desc_languages = [u["language_region"] for u in desc_paragraphs]

        t1_ok = (len(orig_paragraphs) == len(desc_paragraphs) and
                 orig_kinds == desc_kinds and
                 orig_roles == desc_roles and
                 orig_languages == desc_languages)
        case_results["descending_numbers"] = {
            "pass": t1_ok,
            "orig_paragraphs": len(orig_paragraphs),
            "new_paragraphs": len(desc_paragraphs),
            "roles_match": orig_roles == desc_roles,
            "kinds_match": orig_kinds == desc_kinds,
            "languages_match": orig_languages == desc_languages
        }
        if not t1_ok:
            all_pass = False

        # Transformation 2: Repeated [1] for ALL paragraphs!
        # In v1, encountering [1] caused false reset or language change.
        # In R2, repeated [1] must NOT alter roles, kinds, or language regions!
        gen_ones = ("1" for _ in range(total_m))
        text_ones = marker_pattern.sub(lambda m: f"{m.group(1)}[1]", text_original)
        raw_ones = text_ones.encode("utf-8")
        rec_ones = parse_source(case_id, raw_ones)

        ones_paragraphs = [u for u in rec_ones["units"] if u["unit_kind"] == "paragraph"]
        ones_kinds = [u["unit_kind"] for u in rec_ones["units"]]
        ones_roles = [u["paragraph_role"] for u in ones_paragraphs]
        ones_languages = [u["language_region"] for u in ones_paragraphs]

        t2_ok = (len(orig_paragraphs) == len(ones_paragraphs) and
                 orig_kinds == ones_kinds and
                 orig_roles == ones_roles and
                 orig_languages == ones_languages)
        case_results["all_ones"] = {
            "pass": t2_ok,
            "orig_paragraphs": len(orig_paragraphs),
            "new_paragraphs": len(ones_paragraphs),
            "roles_match": orig_roles == ones_roles,
            "kinds_match": orig_kinds == ones_kinds,
            "languages_match": orig_languages == ones_languages
        }
        if not t2_ok:
            all_pass = False

        # Transformation 3: Gaps and jumps ([10], [50], [1000], [2000]...)
        gen_gaps = (str((i + 1) * 100) for i in range(total_m))
        text_gaps = marker_pattern.sub(lambda m: f"{m.group(1)}[{next(gen_gaps)}]", text_original)
        raw_gaps = text_gaps.encode("utf-8")
        rec_gaps = parse_source(case_id, raw_gaps)

        gaps_paragraphs = [u for u in rec_gaps["units"] if u["unit_kind"] == "paragraph"]
        gaps_kinds = [u["unit_kind"] for u in rec_gaps["units"]]
        gaps_roles = [u["paragraph_role"] for u in gaps_paragraphs]
        gaps_languages = [u["language_region"] for u in gaps_paragraphs]

        t3_ok = (len(orig_paragraphs) == len(gaps_paragraphs) and
                 orig_kinds == gaps_kinds and
                 orig_roles == gaps_roles and
                 orig_languages == gaps_languages)
        case_results["large_gaps"] = {
            "pass": t3_ok,
            "orig_paragraphs": len(orig_paragraphs),
            "new_paragraphs": len(gaps_paragraphs),
            "roles_match": orig_roles == gaps_roles,
            "kinds_match": orig_kinds == gaps_kinds,
            "languages_match": orig_languages == gaps_languages
        }
        if not t3_ok:
            all_pass = False

        results[case_id] = case_results

    # Additional Test: Non-leakage of quoted role beyond single unit
    synthetic_case = "000001.txt"
    synthetic_raw = (
        b"[1] The court stated the following:\n"
        b"[2] This is a quoted paragraph.\n"
        b"[3] This is a subsequent paragraph that should NOT be quoted.\n"
        b"[4] Another subsequent paragraph that should NOT be quoted.\n"
    )
    rec_synth = parse_source(synthetic_case, synthetic_raw)
    synth_p = [u for u in rec_synth["units"] if u["unit_kind"] == "paragraph"]
    synth_roles = [(u["observed_marker"], u["paragraph_role"]) for u in synth_p]

    non_leak_ok = (
        synth_roles[0] == (1, "unknown") and
        synth_roles[1] == (2, "quoted") and
        synth_roles[2] == (3, "unknown") and
        synth_roles[3] == (4, "unknown")
    )
    results["synthetic_quote_non_leakage"] = {
        "pass": non_leak_ok,
        "roles": synth_roles,
        "sidecars": len(rec_synth["sidecars"])
    }
    if not non_leak_ok:
        all_pass = False

    out_file = REPO_ROOT / "pipeline_v2/reviews/m1_review_v2/metamorphic_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({"all_pass": all_pass, "cases": results}, indent=2), encoding="utf-8")
    print(f"Metamorphic tests complete. All pass: {all_pass}. Saved to {out_file}")
    return all_pass


if __name__ == "__main__":
    if not test_metamorphic_transformations():
        sys.exit(1)
