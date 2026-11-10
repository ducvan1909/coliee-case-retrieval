"""Independent full integrity and raw marker coverage scanner for M1 Revision 2.
Does NOT import parse_source, validate_marker_coverage, or SourceReader as oracle.
Directly reads raw bytes and artifact JSON from disk.
"""
import bisect
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(".").resolve()
M0_BUNDLE = REPO_ROOT / "pipeline_v2/artifacts/m0_20261105_v2"
M1_BUNDLE = REPO_ROOT / "pipeline_v2/artifacts/m1_20261105_v2"
CORPUS_DIR = REPO_ROOT / "data/task1_train_files_2026/cases"

MARKER_RAW_REGEX = re.compile(rb"(?m)^[ \t]*(?:\xef\xbb\xbf)?(\[[0-9]+\])")
CITATION_TAIL_REGEX = re.compile(rb"^[ \t]*(?:FC|CF|FCA|CAF|SCC|CSC|F\.T\.R\.|F\.C\.|S\.C\.R\.|CanLII|[A-Z][A-Za-z.]*[ \t]+[A-Z][A-Za-z.]*\.)[ \t]*[0-9]", re.I)


def sha256_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_utf8_exceptions(raw: bytes):
    text = raw.decode("utf-8", errors="strict")
    exceptions = []
    positions = []
    extras = [0]
    byte_offset = 0
    for idx, ch in enumerate(text):
        w = len(ch.encode("utf-8"))
        if w != 1:
            exceptions.append([idx, byte_offset, w])
            positions.append(idx)
            extras.append(extras[-1] + w - 1)
        byte_offset += w

    def char_to_byte(c_idx: int) -> int:
        return c_idx + extras[bisect.bisect_left(positions, c_idx)]

    def byte_to_char(b_off: int) -> int:
        low, high = 0, len(text)
        while low <= high:
            mid = (low + high) // 2
            val = char_to_byte(mid)
            if val == b_off:
                return mid
            if val < b_off:
                low = mid + 1
            else:
                high = mid - 1
        raise ValueError(f"Byte offset {b_off} not on char boundary")

    return text, exceptions, char_to_byte, byte_to_char


def run_full_scan():
    start_time = time.perf_counter()
    errors = []
    warnings = []

    print("[1] Checking M0 bundle and frozen inventory...")
    m0_seal_data = json.loads((M0_BUNDLE / "seal.json").read_bytes().decode("utf-8"))
    m0_inv_bytes = (M0_BUNDLE / "inventory.json").read_bytes()
    m0_cand_bytes = (M0_BUNDLE / "candidate_manifest.json").read_bytes()

    if m0_seal_data["files"]["inventory.json"]["sha256"] != sha256_digest(m0_inv_bytes):
        errors.append("M0 inventory.json seal mismatch")
    if m0_seal_data["files"]["candidate_manifest.json"]["sha256"] != sha256_digest(m0_cand_bytes):
        errors.append("M0 candidate_manifest.json seal mismatch")

    m0_inv = json.loads(m0_inv_bytes.decode("utf-8"))
    m0_cand = json.loads(m0_cand_bytes.decode("utf-8"))
    m0_sources = m0_inv["sources"]
    m0_ids = [s["case_id"] for s in m0_sources]

    if m0_cand["candidate_ids"] != m0_ids:
        errors.append("M0 candidate_ids != inventory IDs")
    if len(m0_ids) != 7708:
        errors.append(f"Expected 7708 sources, got {len(m0_ids)}")

    print(f"M0 verified: {len(m0_ids)} sources.")

    print("[2] Checking M1 bundle seal, manifest, and source registry...")
    m1_seal_data = json.loads((M1_BUNDLE / "seal.json").read_bytes().decode("utf-8"))
    m1_files = m1_seal_data["files"]

    # Verify actual disk files match seal exactly
    disk_files = {p.relative_to(M1_BUNDLE).as_posix() for p in M1_BUNDLE.rglob("*") if p.is_file()}
    expected_disk_files = set(m1_files.keys()) | {"seal.json"}
    if disk_files != expected_disk_files:
        extra = disk_files - expected_disk_files
        missing = expected_disk_files - disk_files
        errors.append(f"M1 disk files mismatch: extra={len(extra)}, missing={len(missing)}")

    # Check manifest
    m1_manifest_bytes = (M1_BUNDLE / "manifest.json").read_bytes()
    if m1_files["manifest.json"]["sha256"] != sha256_digest(m1_manifest_bytes):
        errors.append("M1 manifest.json seal sha256 mismatch")
    m1_manifest = json.loads(m1_manifest_bytes.decode("utf-8"))

    if m1_manifest["schema_version"] != "pipeline-v2-m1-manifest-2":
        errors.append(f"Unexpected manifest schema: {m1_manifest['schema_version']}")

    # Check source registry
    m1_reg_bytes = (M1_BUNDLE / "source_registry.json").read_bytes()
    if m1_files["source_registry.json"]["sha256"] != sha256_digest(m1_reg_bytes):
        errors.append("M1 source_registry.json seal sha256 mismatch")
    m1_reg = json.loads(m1_reg_bytes.decode("utf-8"))
    reg_sources = m1_reg["sources"]
    reg_cases = {s["case_id"]: s for s in reg_sources}

    if set(reg_cases.keys()) != set(m0_ids):
        errors.append("Source registry IDs differ from M0 inventory")

    print("[3] Scanning all 7,708 cases against raw bytes, UTF-8 mapping, partition, markers, and sidecars...")

    unit_counts = Counter()
    role_counts = Counter()
    uncertainty_counts = Counter()
    total_sidecars = 0
    total_raw_bytes = 0
    total_markers_raw = 0
    total_paragraph_markers = 0
    total_citation_markers = 0
    all_unit_ids = set()

    for idx, s in enumerate(m0_sources):
        case_id = s["case_id"]
        raw_path = REPO_ROOT / s["path"]
        raw = raw_path.read_bytes()
        raw_len = len(raw)
        total_raw_bytes += raw_len
        raw_sha = sha256_digest(raw)

        if raw_sha != s["sha256"]:
            errors.append(f"Raw source drift for {case_id}: sha mismatch with M0")
        if raw_len != s["byte_length"]:
            errors.append(f"Raw source drift for {case_id}: len mismatch with M0")

        # Load M1 source JSON
        struct_rel = f"sources/{case_id[:-4]}.json"
        struct_path = M1_BUNDLE / struct_rel
        struct_raw = struct_path.read_bytes()

        if m1_files[struct_rel]["sha256"] != sha256_digest(struct_raw):
            errors.append(f"Seal sha mismatch for {struct_rel}")

        record = json.loads(struct_raw.decode("utf-8"))

        if record["case_id"] != case_id:
            errors.append(f"Record case_id mismatch: {record['case_id']} != {case_id}")
        if record["raw_sha256"] != raw_sha:
            errors.append(f"Record raw_sha256 mismatch for {case_id}")
        if record["byte_length"] != raw_len:
            errors.append(f"Record byte_length mismatch for {case_id}")

        # UTF-8 map verification
        try:
            text, exceptions, char_to_byte, byte_to_char = compute_utf8_exceptions(raw)
        except Exception as exc:
            errors.append(f"UTF-8 decode failed for {case_id}: {exc}")
            continue

        cbm = record["char_byte_map"]
        if cbm["char_length"] != len(text) or cbm["byte_length"] != raw_len or cbm["exceptions"] != exceptions:
            errors.append(f"Utf8Map mismatch for {case_id}")

        # Partition verification (contiguous, no gap, no overlap, byte_to_char match)
        units = record["units"]
        cursor = 0
        heading_ids = []
        unit_id_map = {}

        for order, u in enumerate(units):
            u_id = u["unit_id"]
            if u_id in all_unit_ids:
                errors.append(f"Duplicate unit_id across corpus: {u_id}")
            all_unit_ids.add(u_id)
            unit_id_map[u_id] = u

            a, b = u["span_bytes"]
            if a != cursor or not (0 <= a < b <= raw_len) or u["order"] != order:
                errors.append(f"Partition error in {case_id} at order {order}: span [{a},{b}] cursor {cursor}")
            cursor = b

            ca, cb = u["span_chars"]
            if [byte_to_char(a), byte_to_char(b)] != [ca, cb]:
                errors.append(f"Char/byte disagreement in {case_id} unit {u_id}")

            unit_kind = u["unit_kind"]
            unit_counts[unit_kind] += 1
            for unc in u.get("uncertainties", []):
                uncertainty_counts[unc] += 1

            if unit_kind == "heading":
                if u.get("heading_scope") == "body":
                    heading_ids = [u_id]
                # Heading unit must not have section_path_refs pointing to self
                if u.get("section_path_refs") != []:
                    errors.append(f"Heading unit {u_id} has non-empty section_path_refs")
            elif unit_kind == "paragraph":
                role = u["paragraph_role"]
                role_counts[role] += 1
                if role not in ("current_case", "quoted", "unknown"):
                    errors.append(f"Invalid paragraph role {role} in {case_id}")

                # Marker checks
                m_span = u["marker_span_bytes"]
                if not (a <= m_span[0] < m_span[1] <= b):
                    errors.append(f"Marker span outside unit in {case_id} unit {u_id}")

                # Check section_path_refs
                sec_refs = u.get("section_path_refs", [])
                for sref in sec_refs:
                    if sref not in unit_id_map:
                        errors.append(f"section_path_ref {sref} not seen prior to {u_id}")

        if cursor != raw_len:
            errors.append(f"Partition does not cover entire source for {case_id}: {cursor} != {raw_len}")

        # Sidecars verification
        sidecars = record.get("sidecars", [])
        total_sidecars += len(sidecars)
        for sc in sidecars:
            qu_id = sc["quoted_unit_id"]
            if qu_id not in unit_id_map:
                errors.append(f"Sidecar quoted_unit_id {qu_id} not in units of {case_id}")
            att_id = sc.get("attribution_unit_id")
            if att_id is not None:
                if att_id not in unit_id_map:
                    errors.append(f"Sidecar attribution_unit_id {att_id} not in units of {case_id}")
                else:
                    att_unit = unit_id_map[att_id]
                    # Check attribution cue refs are within attribution unit
                    for ref in sc.get("attribution_cue_refs", []):
                        ra, rb = ref["span_bytes"]
                        if not (att_unit["span_bytes"][0] <= ra < rb <= att_unit["span_bytes"][1]):
                            errors.append(f"Attribution cue [{ra},{rb}] outside attribution unit {att_id}")

        # Metadata verification: exact slices match raw
        for meta in record.get("metadata", []):
            if meta["value"] is not None:
                ref = meta["source_refs"][0]["span_bytes"]
                extracted = raw[ref[0]:ref[1]].decode("utf-8", errors="replace").strip()
                if extracted != meta["value"]:
                    errors.append(f"Metadata slice mismatch in {case_id}: '{extracted}' != '{meta['value']}'")

        # Independent Raw Marker Scan
        # Find all raw marker candidates
        raw_marker_candidates = {}
        for m in MARKER_RAW_REGEX.finditer(raw):
            ma, mb = m.span(1)
            raw_marker_candidates[(ma, mb)] = m.group(1).decode("ascii")

        total_markers_raw += len(raw_marker_candidates)

        represented_markers = {}
        # Paragraph markers
        for u in units:
            if u["unit_kind"] == "paragraph":
                m_tuple = tuple(u["marker_span_bytes"])
                if m_tuple in represented_markers:
                    errors.append(f"Duplicate paragraph marker representation {m_tuple} in {case_id}")
                if m_tuple not in raw_marker_candidates:
                    errors.append(f"Paragraph marker {m_tuple} not in raw candidates for {case_id}")
                represented_markers[m_tuple] = "paragraph"
                total_paragraph_markers += 1

        # Citation markers
        for obs in record.get("marker_observations", []):
            m_tuple = tuple(obs["span_bytes"])
            if m_tuple in represented_markers:
                errors.append(f"Duplicate citation marker representation {m_tuple} in {case_id}")
            if m_tuple not in raw_marker_candidates:
                errors.append(f"Citation marker {m_tuple} not in raw candidates for {case_id}")
            # Verify reporter evidence
            ma, mb = m_tuple
            nl = raw.find(b"\n", mb)
            tail = raw[mb:nl if nl >= 0 else len(raw)]
            if not CITATION_TAIL_REGEX.match(tail):
                errors.append(f"Citation marker {m_tuple} lacks adjacent reporter evidence in {case_id}")
            represented_markers[m_tuple] = "citation"
            total_citation_markers += 1

        # Check all candidates are represented
        if set(represented_markers.keys()) != set(raw_marker_candidates.keys()):
            missing = set(raw_marker_candidates.keys()) - set(represented_markers.keys())
            errors.append(f"Raw markers missing from representation in {case_id}: {missing}")

        # Check NO paragraph unit swallows another line marker!
        paragraph_spans = [u["span_bytes"] for u in units if u["unit_kind"] == "paragraph"]
        p_starts = sorted(m[0] for m, k in represented_markers.items() if k == "paragraph")
        for pa, pb in paragraph_spans:
            idx_b = bisect.bisect_left(p_starts, pa)
            if idx_b + 1 < len(p_starts) and p_starts[idx_b + 1] < pb:
                errors.append(f"Paragraph [{pa},{pb}] in {case_id} swallowed subsequent paragraph marker at {p_starts[idx_b+1]}")

        if (idx + 1) % 1000 == 0 or idx + 1 == len(m0_sources):
            print(f"  Scanned {idx + 1}/7708 cases...")

    print("[4] Comparing summary counts...")
    m1_summary = json.loads((M1_BUNDLE / "summary.json").read_bytes().decode("utf-8"))

    expected_unit_counts = dict(unit_counts)
    expected_unit_counts["role_current_case"] = role_counts["current_case"]
    expected_unit_counts["role_quoted"] = role_counts["quoted"]
    expected_unit_counts["role_unknown"] = role_counts["unknown"]
    expected_unit_counts["sidecars"] = total_sidecars

    if m1_summary["source_count"] != len(m0_sources):
        errors.append(f"Summary source_count {m1_summary['source_count']} != {len(m0_sources)}")
    if m1_summary["total_bytes"] != total_raw_bytes:
        errors.append(f"Summary total_bytes {m1_summary['total_bytes']} != {total_raw_bytes}")
    if m1_summary["unit_counts"] != expected_unit_counts:
        errors.append(f"Summary unit_counts mismatch: {m1_summary['unit_counts']} != {expected_unit_counts}")
    if m1_summary["uncertainty_counts"] != dict(uncertainty_counts):
        errors.append(f"Summary uncertainty_counts mismatch")

    elapsed = round(time.perf_counter() - start_time, 3)
    print(f"Full scan completed in {elapsed}s.")
    print(f"Total raw markers: {total_markers_raw} ({total_paragraph_markers} paragraph + {total_citation_markers} citation)")
    print(f"Total units: {sum(unit_counts.values())} (paragraph={unit_counts['paragraph']}, heading={unit_counts['heading']}, unnumbered={unit_counts['unnumbered']}, whitespace={unit_counts['whitespace']})")
    print(f"Total sidecars: {total_sidecars}")
    print(f"Role counts: current_case={role_counts['current_case']}, quoted={role_counts['quoted']}, unknown={role_counts['unknown']}")
    print(f"Errors count: {len(errors)}, Warnings count: {len(warnings)}")

    result = {
        "elapsed_seconds": elapsed,
        "source_count": len(m0_sources),
        "total_bytes": total_raw_bytes,
        "raw_markers_total": total_markers_raw,
        "paragraph_markers": total_paragraph_markers,
        "citation_markers": total_citation_markers,
        "unit_counts": expected_unit_counts,
        "uncertainty_counts": dict(uncertainty_counts),
        "errors": errors[:50],  # first 50 if any
        "error_count": len(errors),
        "warnings": warnings,
        "status": "PASS" if not errors else "FAIL"
    }

    out_path = REPO_ROOT / "pipeline_v2/reviews/m1_review_v2/integrity_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved integrity results to {out_path}")
    return result


if __name__ == "__main__":
    res = run_full_scan()
    if res["error_count"] > 0:
        sys.exit(1)
