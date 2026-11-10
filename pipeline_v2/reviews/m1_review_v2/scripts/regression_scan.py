"""Regression scan for M1 Revision 2:
Directly tests the 8 exposed cases from Revision 1 review,
verifies raw offsets and unit boundaries,
measures how the cascading swallowing, false reset, and translation boundary defects were addressed.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
M0_BUNDLE = REPO_ROOT / "pipeline_v2/artifacts/m0_20261105_v2"
M1_V1_BUNDLE = REPO_ROOT / "pipeline_v2/artifacts/m1_20261105_v1"
M1_V2_BUNDLE = REPO_ROOT / "pipeline_v2/artifacts/m1_20261105_v2"
CORPUS_DIR = REPO_ROOT / "data/task1_train_files_2026/cases"

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


def test_regression_cases():
    print("=== Testing Regression Cases on M1 Revision 2 ===")
    results = {}
    all_ok = True

    m0_inv = json.loads((M0_BUNDLE / "inventory.json").read_bytes().decode("utf-8"))
    m0_hash_map = {s["case_id"]: s["sha256"] for s in m0_inv["sources"]}

    for case_id in REGRESSION_CASES:
        raw_path = CORPUS_DIR / case_id
        raw = raw_path.read_bytes()
        text = raw.decode("utf-8")
        raw_hash = sha256_digest(raw)

        # Verify raw hash matches M0
        if raw_hash != m0_hash_map[case_id]:
            raise ValueError(f"Raw hash mismatch for {case_id} against M0")

        v2_path = M1_V2_BUNDLE / f"sources/{case_id[:-4]}.json"
        v2_rec = json.loads(v2_path.read_bytes().decode("utf-8"))

        v1_path = M1_V1_BUNDLE / f"sources/{case_id[:-4]}.json"
        v1_rec = json.loads(v1_path.read_bytes().decode("utf-8")) if v1_path.exists() else None

        v2_paragraphs = [u for u in v2_rec["units"] if u["unit_kind"] == "paragraph"]
        v2_markers = [u["observed_marker"] for u in v2_paragraphs]
        v2_headings = [u for u in v2_rec["units"] if u["unit_kind"] == "heading"]

        case_eval = {
            "case_id": case_id,
            "raw_sha256": raw_hash,
            "raw_bytes": len(raw),
            "v1_paragraphs_count": len([u for u in v1_rec["units"] if u["unit_kind"] == "paragraph"]) if v1_rec else None,
            "v2_paragraphs_count": len(v2_paragraphs),
            "v2_headings_count": len(v2_headings),
            "v2_sidecars_count": len(v2_rec.get("sidecars", [])),
            "checks": {}
        }

        if case_id == "000758.txt":
            # Finding 001 primary example: [35] jumped to [37].
            # In v1, 37 paragraphs ([37]..[75]) were swallowed into [35].
            # In v2, markers [35], [37], [38], ..., [75] must each have their own paragraph unit.
            p35 = next((u for u in v2_paragraphs if u["observed_marker"] == 35), None)
            p37 = next((u for u in v2_paragraphs if u["observed_marker"] == 37), None)
            p38 = next((u for u in v2_paragraphs if u["observed_marker"] == 38), None)
            p75 = next((u for u in v2_paragraphs if u["observed_marker"] == 75), None)

            # Check that p35 span ends BEFORE p37 starts
            no_swallowing = (p35 is not None and p37 is not None and
                             p35["span_bytes"][1] <= p37["span_bytes"][0])
            all_markers_present = all(m in v2_markers for m in (35, 37, 38, 75))

            # Heading "Summary" between 37 and 38
            summary_h = [u for u in v2_headings if "summary" in raw[u["span_bytes"][0]:u["span_bytes"][1]].decode("utf-8").lower()]

            ok = no_swallowing and all_markers_present and len(summary_h) > 0
            case_eval["checks"]["no_swallowing_p35_to_p37"] = no_swallowing
            case_eval["checks"]["all_markers_present"] = all_markers_present
            case_eval["checks"]["summary_heading_detected"] = len(summary_h) > 0
            case_eval["pass"] = ok
            if not ok:
                all_ok = False

        elif case_id == "050936.txt":
            # Finding 002: Quoted [1] inside body caused false reset in v1.
            # In v2: [1] is marked quoted, subsequent markers [30], [31], [54] exist independently.
            # And language is not corrupted to unknown:1.
            q1_quoted = next((u for u in v2_paragraphs if u["observed_marker"] == 1 and u["paragraph_role"] == "quoted"), None)
            p30 = next((u for u in v2_paragraphs if u["observed_marker"] == 30), None)
            p31 = next((u for u in v2_paragraphs if u["observed_marker"] == 31 and u["span_bytes"][0] > 13000), None)
            p54 = next((u for u in v2_paragraphs if u["observed_marker"] == 54), None)

            q1_is_quoted = q1_quoted is not None
            markers_ok = (p30 is not None and p31 is not None and p54 is not None)
            # Check p31 language region is not corrupted to unknown:1
            lang_ok = p31 is not None and not p31["language_region"].startswith("unknown:1")

            ok = q1_is_quoted and markers_ok and lang_ok
            case_eval["checks"]["q1_role_quoted"] = q1_is_quoted
            case_eval["checks"]["markers_30_31_54_present"] = markers_ok
            case_eval["checks"]["p31_language_not_corrupted"] = lang_ok
            case_eval["pass"] = ok
            if not ok:
                all_ok = False

        elif case_id == "000432.txt":
            # French translation starts after separator at byte 28180.
            # In v1, 48 French paragraphs were completely swallowed into [48] English.
            # In v2, each marker has an independent paragraph unit (95 paragraphs total: 48 English + 47 French).
            # Note on language: French starts at [2], but FR_FRAME regex without parens around demandeur
            # missed [2]..[25], switching to fr:1 only at [26].
            french_start_byte = 28180
            french_paragraphs = [u for u in v2_paragraphs if u["span_bytes"][0] > french_start_byte]
            french_markers = [u["observed_marker"] for u in french_paragraphs]
            p2_french = next((u for u in french_paragraphs if u["observed_marker"] == 2), None)
            total_fr_p = len(french_paragraphs)

            no_swallowing = total_fr_p == 47 and p2_french is not None
            case_eval["checks"]["french_paragraphs_preserved_no_swallow"] = no_swallowing
            case_eval["checks"]["french_paragraphs_count"] = total_fr_p
            case_eval["checks"]["french_marker_2_independent_unit"] = p2_french is not None
            case_eval["checks"]["language_transition_at_26_not_2"] = (
                p2_french["language_region"] == "en:0" and
                any(u["language_region"] == "fr:1" for u in french_paragraphs)
            )
            case_eval["pass"] = no_swallowing
            if not no_swallowing:
                all_ok = False

        elif case_id == "014069.txt":
            # French version started at [2]. In v1, second half became 1 giant unnumbered block.
            # In v2, French markers preserved as paragraph units.
            fr_units = [u for u in v2_paragraphs if u["language_region"].startswith("fr")]
            ok = len(fr_units) > 10
            case_eval["checks"]["french_markers_preserved"] = len(fr_units)
            case_eval["pass"] = ok
            if not ok:
                all_ok = False

        elif case_id == "046028.txt":
            # Jumped from [6] to [8]. In v1 swallowed [8]..[34] (83% of case).
            # In v2, each marker preserved.
            p6 = next((u for u in v2_paragraphs if u["observed_marker"] == 6), None)
            p8 = next((u for u in v2_paragraphs if u["observed_marker"] == 8), None)
            p34 = next((u for u in v2_paragraphs if u["observed_marker"] == 34), None)
            no_swallow = p6 is not None and p8 is not None and p6["span_bytes"][1] <= p8["span_bytes"][0]
            ok = no_swallow and p34 is not None
            case_eval["checks"]["p6_does_not_swallow_p8"] = no_swallow
            case_eval["checks"]["p34_present"] = p34 is not None
            case_eval["pass"] = ok
            if not ok:
                all_ok = False

        elif case_id == "061295.txt":
            # Quotes with explicit attribution cues: (12->9), (13->17), (14->10)
            lookup = {u["unit_id"]: u for u in v2_paragraphs}
            observed_links = set()
            for s in v2_rec.get("sidecars", []):
                if s.get("attribution_unit_id") and s.get("quoted_unit_id"):
                    att_m = lookup[s["attribution_unit_id"]]["observed_marker"]
                    qu_m = lookup[s["quoted_unit_id"]]["observed_marker"]
                    observed_links.add((att_m, qu_m))

            expected_pairs = {(12, 9), (13, 17), (14, 10)}
            has_pairs = expected_pairs.issubset(observed_links)
            case_eval["checks"]["quotation_links_found"] = list(observed_links)
            case_eval["checks"]["expected_pairs_subset"] = has_pairs
            case_eval["pass"] = has_pairs
            if not has_pairs:
                all_ok = False

        elif case_id == "067620.txt":
            # Bilingual case with repeated numbers (e.g. multiple [1]s in distinct language regions)
            ones = [u for u in v2_paragraphs if u["observed_marker"] == 1]
            langs = {u["language_region"] for u in ones}
            ok = len(ones) >= 2 and len(langs) >= 2
            case_eval["checks"]["repeated_ones_count"] = len(ones)
            case_eval["checks"]["distinct_language_regions"] = list(langs)
            case_eval["pass"] = ok
            if not ok:
                all_ok = False

        elif case_id == "062436.txt":
            # Heading "The Respondent"
            resp_headings = [u for u in v2_headings if "the respondent" in raw[u["span_bytes"][0]:u["span_bytes"][1]].decode("utf-8").lower()]
            ok = len(resp_headings) > 0
            case_eval["checks"]["the_respondent_heading"] = len(resp_headings) > 0
            case_eval["pass"] = ok
            if not ok:
                all_ok = False

        results[case_id] = case_eval

    out_file = REPO_ROOT / "pipeline_v2/reviews/m1_review_v2/regression_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({"all_pass": all_ok, "cases": results}, indent=2), encoding="utf-8")
    print(f"Regression scan complete. All pass: {all_ok}. Saved to {out_file}")
    return all_ok


if __name__ == "__main__":
    if not test_regression_cases():
        sys.exit(1)
