"""Dumps detailed contextual inspections for the 24 sampled cases."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EXTRACTED_PATH = ROOT / "pipeline_v2" / "reviews" / "m1_review_v1" / "extracted_regions_raw.json"
M1_BUNDLE = ROOT / "pipeline_v2" / "artifacts" / "m1_20261105_v1"
CORPUS_DIR = ROOT / "data" / "task1_train_files_2026" / "cases"


def inspect_case_details(case_id):
    raw = (CORPUS_DIR / case_id).read_bytes()
    with open(M1_BUNDLE / "sources" / f"{case_id[:-4]}.json", "r", encoding="utf-8") as f:
        rec = json.load(f)

    with open(EXTRACTED_PATH, "r", encoding="utf-8") as f:
        extracted = json.load(f)

    regions = extracted.get(case_id, [])
    output = []
    output.append(f"================================================================================")
    output.append(f"CASE: {case_id} (Total bytes: {len(raw)}, Units: {len(rec['units'])}, Sidecars: {len(rec['sidecars'])})")
    
    # Metadata summary
    output.append("METADATA:")
    for m in rec.get("metadata", []):
        output.append(f"  {m['field']}: {m['value']} (status: {m['confidence_status']}, refs: {m['source_refs']})")

    # Units distribution
    kinds = {}
    for u in rec["units"]:
        kinds[u["unit_kind"]] = kinds.get(u["unit_kind"], 0) + 1
    output.append(f"UNITS: {kinds}")

    # Uncertainties in case
    uncs = {}
    for u in rec["units"]:
        for un in u.get("uncertainties", []):
            uncs[un] = uncs.get(un, 0) + 1
    output.append(f"UNCERTAINTIES: {uncs}")

    for idx, r in enumerate(regions):
        output.append(f"\n--- REGION {idx+1}: {r['region_id']} ---")
        output.append(f"Target: {r['target_type']}, ID: {r.get('target_id')}, Span: {r['focus_span_bytes']}")
        output.append(f"Rationale: {r['rationale']}")
        output.append(f"\n[BEFORE CONTEXT]:\n{r['before_context']}")
        output.append(f"\n[FOCUS TEXT]:\n{r['focus_text']}")
        output.append(f"\n[AFTER CONTEXT]:\n{r['after_context']}")

    return "\n".join(output)


def dump_all():
    with open(EXTRACTED_PATH, "r", encoding="utf-8") as f:
        extracted = json.load(f)

    out_file = ROOT / "pipeline_v2" / "reviews" / "m1_review_v1" / "inspected_regions_text.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        for cid in extracted:
            text = inspect_case_details(cid)
            f.write(text + "\n\n")

    print(f"Dumped inspection details for {len(extracted)} cases to {out_file}")


if __name__ == "__main__":
    dump_all()
