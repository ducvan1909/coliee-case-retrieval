"""Reproduction script for M1 independent review findings."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
M1_BUNDLE = ROOT / "pipeline_v2" / "artifacts" / "m1_20261105_v1"
CORPUS_DIR = ROOT / "data" / "task1_train_files_2026" / "cases"


def repro_001():
    print("=== REPRO M1-FINDING-001: Cascading Swallowing of Outer Paragraphs ===")
    case_id = "000758.txt"
    with open(M1_BUNDLE / "sources" / "000758.json", "r", encoding="utf-8") as f:
        rec = json.load(f)
    raw = (CORPUS_DIR / case_id).read_bytes()
    text = raw.decode("utf-8")

    # Show paragraph 35
    p35 = next(u for u in rec["units"] if u.get("observed_marker") == 35)
    print(f"Parent Unit ID: {p35['unit_id']}")
    print(f"Paragraph 35 Span: {p35['span_bytes']} (Length: {p35['span_bytes'][1] - p35['span_bytes'][0]} bytes)")
    print(f"Uncertainties: {p35.get('uncertainties')}")

    # Show sidecars swallowed under 35
    sidecars = [s for s in rec["sidecars"] if s.get("parent_unit_id") == p35["unit_id"]]
    markers = [s["observed_marker"] for s in sidecars]
    print(f"Total sidecars swallowed under Para 35: {len(sidecars)}")
    print(f"Swallowed markers: {markers}")

    # Context in raw text showing [35], skip of 36, and [37]
    idx35 = text.find("[35]")
    idx37 = text.find("[37]")
    print("\n--- Raw text around [35] to [37] ---")
    print(text[idx37 - 200:idx37 + 250])


def repro_002():
    print("=== REPRO M1-FINDING-002: False Numbering Reset Triggered by Quoted [1] Marker ===")
    case_id = "050936.txt"
    with open(M1_BUNDLE / "sources" / "050936.json", "r", encoding="utf-8") as f:
        rec = json.load(f)
    raw = (CORPUS_DIR / case_id).read_bytes()
    text = raw.decode("utf-8")

    # Locate false reset unit
    reset_u = next(u for u in rec["units"] if "numbering_reset_language_unknown" in u.get("uncertainties", []))
    print(f"False Reset Unit ID: {reset_u['unit_id']}")
    print(f"Span: {reset_u['span_bytes']}, Language: {reset_u['language_region']}")
    print(f"Uncertainties: {reset_u['uncertainties']}")

    # Raw text showing quote introduction and quoted [1]
    s_start, s_end = reset_u["span_bytes"]
    print("\n--- Raw text before and at quoted [1] ---")
    print(text[s_start - 350:s_start + 300])

    # Sidecars under this unit
    swallowed = [s["observed_marker"] for s in rec["sidecars"] if s.get("parent_unit_id") == reset_u["unit_id"]]
    print(f"\nOuter English paragraphs swallowed under quoted [1]: {swallowed}")


def repro_003():
    print("=== REPRO M1-FINDING-003: False Positive Headings from Header & Headnotes ===")
    case_ids = ["019591.txt", "077071.txt", "042691.txt"]
    for cid in case_ids:
        with open(M1_BUNDLE / "sources" / f"{cid[:-4]}.json", "r", encoding="utf-8") as f:
            rec = json.load(f)
        raw = (CORPUS_DIR / cid).read_bytes()
        print(f"\n--- Case {cid} ---")
        headings = [u for u in rec["units"] if u["unit_kind"] == "heading"]
        for h in headings[:5]:
            htxt = raw[slice(*h["span_bytes"])].decode("utf-8").strip()
            print(f"  Heading unit {h['unit_id'][:25]}...: {htxt!r} | flags: {h.get('uncertainties')}")


def repro_004():
    print("=== REPRO M1-FINDING-004: False Negative Headings (ALL CAPS Headings Missed) ===")
    case_id = "000758.txt"
    raw = (CORPUS_DIR / case_id).read_bytes()
    text = raw.decode("utf-8")
    with open(M1_BUNDLE / "sources" / "000758.json", "r", encoding="utf-8") as f:
        rec = json.load(f)

    # Search for "Summary" in text
    idx = text.find("\r\nSummary\r\n")
    print(f"Raw occurrence of 'Summary' at char offset {idx}")
    print("Text around it:\n", text[idx - 50:idx + 100])

    # Check if any unit in 000758 is a heading with Summary
    summary_heading = [u for u in rec["units"] if u["unit_kind"] == "heading" and "Summary" in raw[slice(*u["span_bytes"])].decode("utf-8")]
    print(f"Was 'Summary' parsed as a heading? {'YES' if summary_heading else 'NO (MISSED)'}")


def repro_005():
    print("=== REPRO M1-FINDING-005: Tautological Bundle Validation ===")
    from pipeline_v2.source.core import parse_source
    from pipeline_v2.source.store import read_json

    # Show that parse_source recreates the exact flawed structure
    cid = "000758.txt"
    raw = (CORPUS_DIR / cid).read_bytes()
    stored = read_json(M1_BUNDLE / "sources" / "000758.json")
    fresh = parse_source(cid, raw, read_json(M1_BUNDLE / "manifest.json")["profile"])

    print(f"stored == fresh for 000758.txt: {stored == fresh}")
    print("Notice: Stored record contains 37 swallowed paragraphs under Para 35, yet stored == fresh evaluates to TRUE.")
    print("Conclusion: Validator tests algorithm reproducibility, NOT structural correctness.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--finding", choices=["M1-FINDING-001", "M1-FINDING-002", "M1-FINDING-003", "M1-FINDING-004", "M1-FINDING-005", "ALL"], default="ALL")
    args = parser.parse_args()

    repros = {
        "M1-FINDING-001": repro_001,
        "M1-FINDING-002": repro_002,
        "M1-FINDING-003": repro_003,
        "M1-FINDING-004": repro_004,
        "M1-FINDING-005": repro_005,
    }

    if args.finding == "ALL":
        for fn in repros.values():
            fn()
            print()
    else:
        repros[args.finding]()


if __name__ == "__main__":
    main()
