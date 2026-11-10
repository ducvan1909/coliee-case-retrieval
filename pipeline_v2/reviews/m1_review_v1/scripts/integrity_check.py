"""Independent full-corpus integrity checker for M1 bundle.

Directly inspects all 7,708 cases and artifacts without calling M1's parse_source().
Verifies:
1. Universe and hash consistency with M0 inventory and raw disk files.
2. UTF-8 strictness, CRLF newline preservation, byte length.
3. Utf8Map exceptions match independent codepoint scanning.
4. Continuous partition: [0, len(raw)), no gaps, no overlaps, start < end.
5. Byte spans strictly align to UTF-8 codepoint boundaries.
6. Char spans match decoded substring length.
7. Unit IDs: format compliance, case-level and global uniqueness.
8. Section refs: exist, are headings, precede the referring unit.
9. Sidecars: valid spans, parent exists and contains sidecar span, route_unknown status.
10. Metadata: exact raw evidence matches extracted value.
11. Independent summary counts match summary.json.
12. Seal matches all artifact files.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
M0_BUNDLE = ROOT / "pipeline_v2" / "artifacts" / "m0_20261105_v2"
M1_BUNDLE = ROOT / "pipeline_v2" / "artifacts" / "m1_20261105_v1"
CORPUS_DIR = ROOT / "data" / "task1_train_files_2026" / "cases"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_check():
    start_time = time.perf_counter()
    errors = []
    warnings = []

    print("Step 1: Checking Seal and Top-Level Artifacts...")
    seal_path = M1_BUNDLE / "seal.json"
    if not seal_path.exists():
        return {"status": "FAIL", "error": "seal.json missing"}
    with open(seal_path, "r", encoding="utf-8") as f:
        seal = json.load(f)

    # Check top level files against seal
    for rel_path, meta in seal["files"].items():
        p = M1_BUNDLE / rel_path
        if not p.exists():
            errors.append(f"Sealed file missing: {rel_path}")
            continue
        raw = p.read_bytes()
        if len(raw) != meta["byte_length"] or sha256_bytes(raw) != meta["sha256"]:
            errors.append(f"Sealed file corrupted: {rel_path}")

    # Check M0 inventory
    with open(M0_BUNDLE / "inventory.json", "r", encoding="utf-8") as f:
        m0_inventory = json.load(f)
    m0_sources = {s["case_id"]: s for s in m0_inventory["sources"]}

    # Check M1 registry
    with open(M1_BUNDLE / "source_registry.json", "r", encoding="utf-8") as f:
        m1_registry = json.load(f)
    m1_sources = {s["case_id"]: s for s in m1_registry["sources"]}

    if set(m0_sources.keys()) != set(m1_sources.keys()):
        errors.append(f"Universe mismatch between M0 and M1 registry: {len(m0_sources)} vs {len(m1_sources)}")

    with open(M1_BUNDLE / "summary.json", "r", encoding="utf-8") as f:
        expected_summary = json.load(f)

    print(f"Step 2: Checking all {len(m0_sources)} sources independently...")
    global_unit_ids = set()
    total_bytes_checked = 0
    unit_counts = Counter()
    uncertainty_counts = Counter()
    sources_with_uncertainties = 0

    unit_id_regex = re.compile(r"^\d{6}:[0-9a-f]{16}:\d+-\d+:[0-9a-f]{12}$")

    for idx, (case_id, m0_row) in enumerate(m0_sources.items()):
        if (idx + 1) % 1000 == 0:
            print(f"  Processed {idx + 1}/{len(m0_sources)} cases...")

        raw_path = CORPUS_DIR / case_id
        if not raw_path.exists():
            errors.append(f"Raw source file missing on disk: {case_id}")
            continue

        raw = raw_path.read_bytes()
        raw_hash = sha256_bytes(raw)

        # Hash & length checks
        if raw_hash != m0_row["sha256"]:
            errors.append(f"Raw hash mismatch for {case_id}: expected {m0_row['sha256']}, got {raw_hash}")
        if len(raw) != m0_row["byte_length"]:
            errors.append(f"Raw length mismatch for {case_id}")

        m1_row = m1_sources.get(case_id)
        if not m1_row:
            errors.append(f"Case missing in M1 registry: {case_id}")
            continue
        if m1_row["raw_sha256"] != raw_hash:
            errors.append(f"Registry hash mismatch for {case_id}")
        if m1_row["byte_length"] != len(raw):
            errors.append(f"Registry length mismatch for {case_id}")

        # UTF-8 strict decode check
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as e:
            errors.append(f"Raw file is not strict UTF-8: {case_id} ({e})")
            continue

        # CRLF check
        if b"\r\n" not in raw and b"\n" in raw:
            warnings.append(f"Raw file lacks CRLF: {case_id}")

        total_bytes_checked += len(raw)

        # Read structure JSON
        struct_path = M1_BUNDLE / m1_row["structure_ref"]
        if not struct_path.exists():
            errors.append(f"Structure JSON missing: {m1_row['structure_ref']}")
            continue

        with open(struct_path, "r", encoding="utf-8") as f:
            rec = json.load(f)

        if rec["case_id"] != case_id or rec["raw_sha256"] != raw_hash:
            errors.append(f"Structure header mismatch for {case_id}")

        # Check char_byte_map
        cbm = rec.get("char_byte_map", {})
        cbm_exceptions = cbm.get("exceptions", [])
        # Independent scan of multi-byte characters
        byte_cursor = 0
        expected_exceptions = []
        for c_idx, ch in enumerate(text):
            ch_width = len(ch.encode("utf-8"))
            if ch_width > 1:
                expected_exceptions.append([c_idx, byte_cursor, ch_width])
            byte_cursor += ch_width
        if cbm_exceptions != expected_exceptions:
            errors.append(f"char_byte_map exceptions mismatch for {case_id}: {len(cbm_exceptions)} vs {len(expected_exceptions)}")

        # Check units partition
        units = rec.get("units", [])
        if not units:
            errors.append(f"Zero units for {case_id}")
            continue

        cursor = 0
        headings_seen = {}
        case_had_uncertainty = False

        for order, u in enumerate(units):
            uid = u["unit_id"]
            if not unit_id_regex.match(uid):
                errors.append(f"Invalid unit ID format: {uid} in {case_id}")
            if uid in global_unit_ids:
                errors.append(f"Duplicate unit ID across corpus: {uid}")
            global_unit_ids.add(uid)

            if u["order"] != order:
                errors.append(f"Unit order discrepancy in {case_id}: expected {order}, got {u['order']}")

            u_start, u_end = u["span_bytes"]
            # Partition continuity
            if u_start != cursor:
                errors.append(f"Partition gap or overlap in {case_id} at order {order}: cursor={cursor}, start={u_start}")
            if u_start >= u_end:
                errors.append(f"Empty or inverted unit span in {case_id} at order {order}: [{u_start}, {u_end})")
            if u_end > len(raw):
                errors.append(f"Unit span out of bounds in {case_id} at order {order}: {u_end} > {len(raw)}")

            # Codepoint boundary alignment
            try:
                u_slice = raw[u_start:u_end].decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                errors.append(f"Unit byte span splits UTF-8 codepoint in {case_id}: [{u_start}, {u_end})")
                u_slice = ""

            c_start, c_end = u["span_chars"]
            if len(u_slice) != (c_end - c_start):
                errors.append(f"Unit char span mismatch with decoded slice length in {case_id}: {len(u_slice)} vs {c_end - c_start}")

            # Section path refs check
            sec_refs = u.get("section_path_refs", [])
            for sref in sec_refs:
                if sref not in headings_seen:
                    errors.append(f"section_path_ref {sref} not seen or not a preceding heading in {case_id}")

            if u["unit_kind"] == "heading":
                headings_seen[uid] = u

            unit_counts[u["unit_kind"]] += 1
            for unc in u.get("uncertainties", []):
                uncertainty_counts[unc] += 1
                case_had_uncertainty = True

            cursor = u_end

        if cursor != len(raw):
            errors.append(f"Partition does not cover entire source for {case_id}: cursor={cursor}, raw_len={len(raw)}")

        # Check sidecars
        sidecars = rec.get("sidecars", [])
        unit_by_id = {u["unit_id"]: u for u in units}
        for s in sidecars:
            s_start, s_end = s["span_bytes"]
            if not (0 <= s_start < s_end <= len(raw)):
                errors.append(f"Invalid sidecar span in {case_id}: [{s_start}, {s_end})")
            m_start, m_end = s["marker_span_bytes"]
            if not (s_start <= m_start < m_end <= s_end):
                errors.append(f"Sidecar marker span out of bounds in {case_id}")

            p_id = s.get("parent_unit_id")
            if p_id is not None:
                parent = unit_by_id.get(p_id)
                if not parent:
                    errors.append(f"Sidecar parent {p_id} not found in units for {case_id}")
                else:
                    if parent["unit_kind"] != "paragraph":
                        errors.append(f"Sidecar parent is not a paragraph in {case_id}: kind={parent['unit_kind']}")
                    pu_start, pu_end = parent["span_bytes"]
                    if not (pu_start <= s_start < s_end <= pu_end):
                        errors.append(f"Sidecar span not contained in parent span for {case_id}: sidecar=[{s_start},{s_end}), parent=[{pu_start},{pu_end})")
            else:
                if not s.get("route_unknown"):
                    errors.append(f"Unparented sidecar lacks route_unknown=True in {case_id}")

            for cue in s.get("attribution_cue_refs", []):
                cb_start, cb_end = cue["span_bytes"]
                if not (0 <= cb_start < cb_end <= len(raw)):
                    errors.append(f"Attribution cue span out of bounds in {case_id}")

        unit_counts["sidecars"] += len(sidecars)

        # Check metadata
        for item in rec.get("metadata", []):
            field = item["field"]
            val = item["value"]
            refs = item.get("source_refs", [])
            if val is not None:
                if not refs:
                    errors.append(f"Metadata {field} has value {val!r} but empty source_refs in {case_id}")
                else:
                    for ref in refs:
                        rb_start, rb_end = ref["span_bytes"]
                        if not (0 <= rb_start < rb_end <= len(raw)):
                            errors.append(f"Metadata ref out of bounds in {case_id}: [{rb_start}, {rb_end})")
                        else:
                            extracted = raw[rb_start:rb_end].decode("utf-8").strip()
                            if extracted != val:
                                errors.append(f"Metadata raw slice mismatch for {field} in {case_id}: {extracted!r} != {val!r}")
            else:
                if refs:
                    errors.append(f"Metadata {field} is None but has non-empty source_refs in {case_id}")

        if case_had_uncertainty:
            sources_with_uncertainties += 1

    print("Step 3: Comparing independent totals with summary.json...")
    expected_unit_counts = expected_summary.get("unit_counts", {})
    expected_uncertainties = expected_summary.get("uncertainty_counts", {})

    diff_units = {}
    for k in set(unit_counts) | set(expected_unit_counts):
        if unit_counts[k] != expected_unit_counts.get(k, 0):
            diff_units[k] = {"actual": unit_counts[k], "expected": expected_unit_counts.get(k, 0)}

    diff_unc = {}
    for k in set(uncertainty_counts) | set(expected_uncertainties):
        if uncertainty_counts[k] != expected_uncertainties.get(k, 0):
            diff_unc[k] = {"actual": uncertainty_counts[k], "expected": expected_uncertainties.get(k, 0)}

    if diff_units:
        errors.append(f"Unit count discrepancies: {diff_units}")
    if diff_unc:
        errors.append(f"Uncertainty count discrepancies: {diff_unc}")
    if total_bytes_checked != expected_summary.get("total_bytes"):
        errors.append(f"Total bytes mismatch: actual={total_bytes_checked}, expected={expected_summary.get('total_bytes')}")

    elapsed = round(time.perf_counter() - start_time, 3)

    result = {
        "status": "PASS" if not errors else "FAIL",
        "elapsed_seconds": elapsed,
        "total_sources_checked": len(m0_sources),
        "total_bytes_checked": total_bytes_checked,
        "total_units_checked": sum(v for k, v in unit_counts.items() if k != "sidecars"),
        "total_sidecars_checked": unit_counts["sidecars"],
        "unit_counts": dict(unit_counts),
        "uncertainty_counts": dict(uncertainty_counts),
        "sources_with_uncertainties": sources_with_uncertainties,
        "errors_count": len(errors),
        "errors_sample": errors[:20],
        "warnings_count": len(warnings),
        "warnings_sample": warnings[:20],
    }

    print(f"\nCompleted in {elapsed}s. Status: {result['status']}. Errors: {len(errors)}, Warnings: {len(warnings)}")
    return result


if __name__ == "__main__":
    res = run_check()
    out_file = ROOT / "pipeline_v2" / "reviews" / "m1_review_v1" / "integrity_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    sys.exit(0 if res["status"] == "PASS" else 1)
