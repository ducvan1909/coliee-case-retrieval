"""Independent full-corpus audit and before/after comparison for M2 Preview Revision 2 (v3).

Audits:
- pipeline_v2/artifacts/m0_20261105_v2
- pipeline_v2/artifacts/m1_20261105_v2
- pipeline_v2/artifacts/m2_navigation_20261105_v1 (old baseline)
- pipeline_v2/artifacts/m2_navigation_20261106_v2 (intermediate checkpoint)
- pipeline_v2/artifacts/m2_navigation_20261106_v3 (target acceptance bundle)

Does not use the M2 builder as sole oracle; computes raw hashes, UTF-8 char/byte spans,
content-start, clipping flags, containment/overlap metrics, novel anchor coverage,
and verbatim regression comparisons directly from raw files and M1/M2 artifacts.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time


PLACEHOLDER = re.compile(r"[<(]?(?:FRAGMENT|REFERENCE)_SUPPRESSED[>)]?")
MARKER = re.compile(r"^\[[0-9]+\]")
PROTECTED_TAG = re.compile(r"<[^<>\r\n]+>|\((?:FRAGMENT|REFERENCE|DATE)_SUPPRESSED\)")
ROW_INVARIANT_EXCLUDED = {"preview_refs", "preview_absence_reason"}

REGRESSION_TARGETS = [
    ("011922.txt", "p000005"),
    ("051807.txt", "u000030"),
    ("080359.txt", "u000002"),
    ("068193.txt", "p000025"),
    ("014101.txt", "p000008"),
    ("048208.txt", "p000015"),
    ("081945.txt", "u000001"),
    ("015740.txt", "u000001"),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def independent_body_start(text: str, start: int, end: int) -> int:
    pos = start + (1 if (start < end and text[start] == "\ufeff") else 0)
    m = MARKER.match(text[pos:end])
    return pos + m.end() if m else pos


def independent_content_start(text: str, start: int, end: int):
    pos = independent_body_start(text, start, end)
    while pos < end:
        nl = text.find("\n", pos, end)
        line_end = end if nl < 0 else nl
        line = text[pos:line_end]
        if any(ch.isalnum() for ch in PLACEHOLDER.sub("", line)):
            return pos + len(line) - len(line.lstrip())
        pos = min(end, line_end + 1)
    return None


def covered_length(a: int, b: int, ranges: list[tuple[int, int]]) -> int:
    spans = sorted((max(a, r0), min(b, r1)) for r0, r1 in ranges if a < r1 and r0 < b)
    total, cursor = 0, a
    for left, right in spans:
        total += max(0, right - max(cursor, left))
        cursor = max(cursor, right)
    return total


def verify_bundle_seal(bundle_dir: Path) -> dict:
    seal_path = bundle_dir / "seal.json"
    seal_raw = seal_path.read_bytes()
    seal = json.loads(seal_raw.decode("utf-8"))
    files_map = seal.get("files", {})
    actual_files = {p.relative_to(bundle_dir).as_posix() for p in bundle_dir.rglob("*") if p.is_file()}
    expected_files = set(files_map.keys()) | {"seal.json"}
    missing = sorted(expected_files - actual_files)
    extra = sorted(actual_files - expected_files)
    mismatches = []
    for rel_path, meta in files_map.items():
        fpath = bundle_dir / rel_path
        if not fpath.is_file():
            continue
        raw = fpath.read_bytes()
        if sha256_bytes(raw) != meta.get("sha256") or len(raw) != meta.get("byte_length"):
            mismatches.append(rel_path)
    return {
        "bundle": bundle_dir.as_posix(),
        "seal_sha256": sha256_bytes(seal_raw),
        "sealed_file_entries_count": len(files_map),
        "total_bundle_files_on_disk": len(actual_files),
        "missing_files": missing,
        "extra_files": extra,
        "hash_or_size_mismatches": mismatches,
        "valid": not missing and not extra and not mismatches,
    }


def analyze_preview_cuts_and_overlaps(rec: dict, unit_map: dict, raw: bytes, full_text: str) -> dict:
    """Compute per-case preview metrics for a given M2 case record."""
    previews_by_unit = {}
    for p in rec["previews"]:
        previews_by_unit.setdefault(p["unit_id"], []).append(p)
    anchors_by_unit = {}
    for a in rec["anchors"]:
        anchors_by_unit.setdefault(a["unit_id"], []).append(a)

    stats = Counter()
    examples = {
        "short_le_30": [],
        "short_le_15": [],
        "short_clean_lt_100": [],
        "contained_pairs": [],
        "mergeable_overlap_pairs": [],
        "complementary_overlap_pairs": [],
        "placeholder_punct_openings": [],
        "word_clips": [],
        "tag_clips": [],
        "crowded_out_anchors": [],
    }

    for row in rec["navigation"]:
        uid = row["unit_id"]
        u = unit_map[uid]
        ua, ub = u["span_bytes"]
        ucs, uce = u["span_chars"]
        utext = full_text[ucs:uce]
        body_start = independent_body_start(full_text, ucs, uce)
        content_start = independent_content_start(full_text, ucs, uce)
        content_end = ucs + len(utext.rstrip())
        protected = [m.span() for m in PROTECTED_TAG.finditer(full_text, ucs, uce)]

        upreviews = sorted(previews_by_unit.get(uid, []), key=lambda x: x["span_bytes"])
        uanchors = anchors_by_unit.get(uid, [])
        stats["units"] += 1
        if not upreviews:
            stats["units_without_preview"] += 1
            if content_start is None:
                stats["units_without_preview_no_alnum"] += 1
            else:
                stats["units_without_preview_with_alnum"] += 1

        for p in upreviews:
            stats["previews"] += 1
            stats[f"kind_{p['preview_kind']}"] += 1
            pa, pb = p["span_bytes"]
            ptext = raw[pa:pb].decode("utf-8", errors="strict")
            # Derive char offsets
            pcs = ucs + len(raw[ua:pa].decode("utf-8", errors="strict"))
            pce = pcs + len(ptext)

            # Word clip check
            word_clip = (
                (pcs > ucs and full_text[pcs - 1].isalnum() and full_text[pcs].isalnum())
                or (pce < uce and full_text[pce - 1].isalnum() and full_text[pce].isalnum())
            )
            tag_clip = any(x < pcs < y or x < pce < y for x, y in protected)
            if word_clip:
                stats["word_clipped_raw"] += 1
                if len(examples["word_clips"]) < 25:
                    examples["word_clips"].append({
                        "case_id": rec["case_id"], "handle": row["handle"], "preview_id": p["preview_id"],
                        "span_bytes": [pa, pb], "text": ptext
                    })
            if tag_clip:
                stats["tag_clipped_raw"] += 1
                examples["tag_clips"].append({
                    "case_id": rec["case_id"], "handle": row["handle"], "preview_id": p["preview_id"],
                    "span_bytes": [pa, pb], "text": ptext
                })

            if p["preview_kind"] == "opening":
                # Check if first line of opening has only placeholder + punct
                first_nl = ptext.find("\n")
                first_line = ptext if first_nl < 0 else ptext[:first_nl]
                if not any(ch.isalnum() for ch in PLACEHOLDER.sub("", first_line)):
                    stats["opening_starts_on_placeholder_punct_line"] += 1
                    if len(examples["placeholder_punct_openings"]) < 25:
                        examples["placeholder_punct_openings"].append({
                            "case_id": rec["case_id"], "handle": row["handle"], "preview_id": p["preview_id"],
                            "span_bytes": [pa, pb], "first_line": first_line, "text": ptext
                        })
                rem_chars = content_end - pce
                if len(ptext) <= 30 and rem_chars > 20:
                    stats["short_opening_le_30_with_more_text"] += 1
                    if len(examples["short_le_30"]) < 25:
                        examples["short_le_30"].append({
                            "case_id": rec["case_id"], "handle": row["handle"], "preview_id": p["preview_id"],
                            "span_bytes": [pa, pb], "text": ptext, "remaining_chars": rem_chars
                        })
                if len(ptext) <= 15 and rem_chars > 20:
                    stats["short_opening_le_15_with_more_text"] += 1
                    if len(examples["short_le_15"]) < 25:
                        examples["short_le_15"].append({
                            "case_id": rec["case_id"], "handle": row["handle"], "preview_id": p["preview_id"],
                            "span_bytes": [pa, pb], "text": ptext, "remaining_chars": rem_chars
                        })
                if ptext.endswith(".") and pce < content_end:
                    stats["opening_ends_with_period_before_unit_end"] += 1
                clean_p = PLACEHOLDER.sub("", ptext)
                clean_u = PLACEHOLDER.sub("", utext)
                if len(clean_u) >= 120 and len(clean_p) < 100:
                    stats["short_opening_clean_lt_100_unit_ge_120"] += 1
                    examples["short_clean_lt_100"].append({
                        "case_id": rec["case_id"], "handle": row["handle"], "unit_id": uid,
                        "preview_id": p["preview_id"], "span_bytes": [pa, pb],
                        "raw_char_len": len(ptext), "clean_char_len": len(clean_p),
                        "unit_clean_char_len": len(clean_u), "text": ptext, "unit_text": utext
                    })

        # Pairwise overlap & containment on unit previews
        if len(upreviews) == 2:
            stats["units_with_2_previews"] += 1
            p1, p2 = upreviews[0], upreviews[1]
            a1, b1 = p1["span_bytes"]
            a2, b2 = p2["span_bytes"]
            c1s = ucs + len(raw[ua:a1].decode("utf-8", errors="strict"))
            c1e = c1s + len(p1["text"])
            c2s = ucs + len(raw[ua:a2].decode("utf-8", errors="strict"))
            c2e = c2s + len(p2["text"])
            if (a1 <= a2 and b2 <= b1) or (a2 <= a1 and b1 <= b2):
                stats["contained_preview_pairs"] += 1
                if len(examples["contained_pairs"]) < 25:
                    examples["contained_pairs"].append({
                        "case_id": rec["case_id"], "handle": row["handle"],
                        "p1_span": [a1, b1], "p2_span": [a2, b2]
                    })
            elif max(a1, a2) < min(b1, b2):
                stats["overlapping_preview_pairs"] += 1
                union_len = max(c1e, c2e) - min(c1s, c2s)
                if content_start is not None and min(c1s, c2s) < content_start:
                    stats["overlap_reaching_before_content_start"] += 1
                if content_start is not None and min(c1s, c2s) >= content_start and union_len <= 240:
                    stats["mergeable_within_240_overlap_pairs"] += 1
                    if len(examples["mergeable_overlap_pairs"]) < 25:
                        examples["mergeable_overlap_pairs"].append({
                            "case_id": rec["case_id"], "handle": row["handle"],
                            "p1_span": [a1, b1], "p2_span": [a2, b2], "union_chars": union_len
                        })
                else:
                    stats["complementary_overlap_pairs_gt_240"] += 1
                    if len(examples["complementary_overlap_pairs"]) < 25:
                        examples["complementary_overlap_pairs"].append({
                            "case_id": rec["case_id"], "handle": row["handle"],
                            "p1_span": [a1, b1], "p2_span": [a2, b2], "union_chars": union_len
                        })

        # Anchor coverage in unit
        if uanchors:
            stats["units_with_anchors"] += 1
            stats["total_unit_anchors"] += len(uanchors)
            covered_ids = {aid for p in upreviews for aid in p["anchor_refs"]}
            fully_covered_ids = {
                v["anchor_ref"] for p in upreviews for v in p.get("anchor_visibility", []) if v.get("fully_visible")
            }
            stats["displayed_unit_anchors_any"] += len(covered_ids)
            stats["displayed_unit_anchors_full"] += len(fully_covered_ids)
            if len(uanchors) >= 2:
                stats["units_with_ge_2_anchors"] += 1
                if len(covered_ids) >= 2:
                    stats["units_with_ge_2_anchors_covering_ge_2"] += 1
                if len(upreviews) == 2 and len(covered_ids) == 1:
                    # Check if the 2 previews had overlapping spans that crowded out another eligible anchor
                    p1, p2 = upreviews[0], upreviews[1]
                    if max(p1["span_bytes"][0], p2["span_bytes"][0]) < min(p1["span_bytes"][1], p2["span_bytes"][1]):
                        stats["units_overlapping_2_previews_covering_only_1_of_multiple_anchors"] += 1
                        if len(examples["crowded_out_anchors"]) < 25:
                            examples["crowded_out_anchors"].append({
                                "case_id": rec["case_id"], "handle": row["handle"],
                                "anchor_count": len(uanchors), "covered_anchors": sorted(covered_ids)
                            })

    return {"stats": stats, "examples": examples}


def main():
    started = time.perf_counter()
    root = Path(__file__).resolve().parents[4]
    out_dir = Path(__file__).resolve().parents[1]
    out_dir.mkdir(parents=True, exist_ok=True)

    m0_dir = root / "pipeline_v2/artifacts/m0_20261105_v2"
    m1_dir = root / "pipeline_v2/artifacts/m1_20261105_v2"
    v1_dir = root / "pipeline_v2/artifacts/m2_navigation_20261105_v1"
    v2_dir = root / "pipeline_v2/artifacts/m2_navigation_20261106_v2"
    v3_dir = root / "pipeline_v2/artifacts/m2_navigation_20261106_v3"
    raw_cases_dir = root / "data/task1_train_files_2026/cases"

    seals = {
        "m0_20261105_v2": verify_bundle_seal(m0_dir),
        "m1_20261105_v2": verify_bundle_seal(m1_dir),
        "m2_navigation_20261105_v1": verify_bundle_seal(v1_dir),
        "m2_navigation_20261106_v2": verify_bundle_seal(v2_dir),
        "m2_navigation_20261106_v3": verify_bundle_seal(v3_dir),
    }

    # Check manifest and profile provenance on v3
    v3_manifest = read_json(v3_dir / "manifest.json")
    v1_manifest = read_json(v1_dir / "manifest.json")
    profile_path = root / "pipeline_v2/configs/m2.json"
    profile_raw = profile_path.read_bytes()
    profile = json.loads(profile_raw.decode("utf-8"))
    impl_files = ["pipeline_v2/m2.py"] + [f"pipeline_v2/navigation/{x}" for x in ("__init__.py", "core.py", "store.py")]
    actual_impl = {name: sha256_bytes((root / name).read_bytes()) for name in impl_files}
    expected_m1_prov = {
        "bundle": "pipeline_v2/artifacts/m1_20261105_v2",
        "seal_sha256": sha256_bytes((m1_dir / "seal.json").read_bytes()),
        "manifest_sha256": sha256_bytes((m1_dir / "manifest.json").read_bytes()),
        "registry_sha256": sha256_bytes((m1_dir / "source_registry.json").read_bytes()),
    }

    m0_reg = {r["case_id"]: r for r in read_json(m0_dir / "inventory.json")["sources"]}
    m1_reg = {r["case_id"]: r for r in read_json(m1_dir / "source_registry.json")["sources"]}
    v1_reg = {r["case_id"]: r for r in read_json(v1_dir / "source_registry.json")["sources"]}
    v2_reg = {r["case_id"]: r for r in read_json(v2_dir / "source_registry.json")["sources"]}
    v3_reg = {r["case_id"]: r for r in read_json(v3_dir / "source_registry.json")["sources"]}

    raw_files = sorted(p.name for p in raw_cases_dir.glob("*.txt"))

    errors = []
    if not all(s["valid"] for s in seals.values()):
        errors.append("One or more bundle seals failed verification")
    if v3_manifest.get("m1") != expected_m1_prov:
        errors.append("v3 M1 provenance mismatch")
    if v3_manifest.get("profile_sha256") != sha256_bytes(profile_raw) or v3_manifest.get("profile") != profile:
        errors.append("v3 profile hash/content mismatch")
    if v3_manifest.get("implementation") != actual_impl:
        errors.append("v3 implementation hashes mismatch")
    if set(raw_files) != set(m0_reg) or set(raw_files) != set(m1_reg) or set(raw_files) != set(v1_reg) or set(raw_files) != set(v3_reg):
        errors.append("Universe of 7,708 cases differs across raw, M0, M1, v1, v3")

    v1_stats = Counter()
    v2_stats = Counter()
    v3_stats = Counter()
    v1_examples = {}
    v3_examples = {}
    invariance_counters = Counter()
    v3_contract_counters = Counter()

    # Track placeholder-only line transitions from v1 to v3
    placeholder_line_transitions = Counter()
    placeholder_line_transition_examples = []
    units_without_preview_v3_list = []
    v2_tag_clip_cases_comparison = []
    regression_comparisons = []
    regression_lookup = {cid: handle for cid, handle in REGRESSION_TARGETS}

    # Load v2 checkpoint tag clip cases to verify all 9 in v1, v2, v3
    v2_audit_path = root / "pipeline_v2/reviews/m2_preview_revision2_validation/m2_navigation_20261106_v2_audit_checkpoint.json"
    v2_checkpoint_data = read_json(v2_audit_path)
    v2_9_cases = {(c["case_id"], c["unit_id"]): c for c in v2_checkpoint_data["raw_verified_tag_boundary_clip_cases"]}

    for case_id in raw_files:
        raw = (raw_cases_dir / case_id).read_bytes()
        raw_sha = sha256_bytes(raw)
        full_text = raw.decode("utf-8", errors="strict")

        m1_rec = read_json(m1_dir / m1_reg[case_id]["structure_ref"])
        v1_rec = read_json(v1_dir / v1_reg[case_id]["navigation_ref"])
        v2_rec = read_json(v2_dir / v2_reg[case_id]["navigation_ref"])
        v3_rec = read_json(v3_dir / v3_reg[case_id]["navigation_ref"])

        if not (raw_sha == m0_reg[case_id]["sha256"] == m1_reg[case_id]["raw_sha256"] == v1_rec["source_hash"] == v3_rec["source_hash"]):
            errors.append(f"Raw SHA256 mismatch on {case_id}")
        if sha256_bytes(canonical_bytes(m1_rec)) != v3_rec["m1_structure_sha256"]:
            errors.append(f"M1 structure sha256 mismatch on {case_id}")

        # Check catalog invariance between v1 and v3
        if v1_rec["anchors"] != v3_rec["anchors"]:
            errors.append(f"Anchors catalog changed between v1 and v3 in {case_id}")
        else:
            invariance_counters["cases_anchors_identical"] += 1
            invariance_counters["unit_anchors_verified"] += len(v3_rec["anchors"])

        if v1_rec["source_anchors"] != v3_rec["source_anchors"]:
            errors.append(f"Source anchors catalog changed between v1 and v3 in {case_id}")
        else:
            invariance_counters["cases_source_anchors_identical"] += 1
            invariance_counters["source_anchors_verified"] += len(v3_rec["source_anchors"])

        if v1_rec["headings"] != v3_rec["headings"]:
            errors.append(f"Headings changed between v1 and v3 in {case_id}")
        else:
            invariance_counters["cases_headings_identical"] += 1
            invariance_counters["headings_verified"] += len(v3_rec["headings"])

        unit_map = {u["unit_id"]: u for u in m1_rec["units"] if u["unit_kind"] in ("paragraph", "unnumbered")}
        v1_rows = {r["unit_id"]: r for r in v1_rec["navigation"]}
        v3_rows = {r["unit_id"]: r for r in v3_rec["navigation"]}
        if set(v1_rows) != set(v3_rows) or set(v3_rows) != set(unit_map):
            errors.append(f"Unit coverage mismatch in {case_id}")

        v1_p_by_unit = {}
        for p in v1_rec["previews"]:
            v1_p_by_unit.setdefault(p["unit_id"], []).append(p)
        v2_p_by_unit = {}
        for p in v2_rec["previews"]:
            v2_p_by_unit.setdefault(p["unit_id"], []).append(p)
        v3_p_by_unit = {}
        for p in v3_rec["previews"]:
            v3_p_by_unit.setdefault(p["unit_id"], []).append(p)
        v3_a_by_id = {a["anchor_id"]: a for a in v3_rec["anchors"]}
        v3_sa_by_id = {sa["source_anchor_id"]: sa for sa in v3_rec["source_anchors"]}

        for uid, v3_row in v3_rows.items():
            v1_row = v1_rows[uid]
            if {k: v for k, v in v1_row.items() if k not in ROW_INVARIANT_EXCLUDED} != {
                k: v for k, v in v3_row.items() if k not in ROW_INVARIANT_EXCLUDED
            }:
                errors.append(f"Non-preview navigation field changed in {case_id}/{uid}")
            else:
                invariance_counters["navigation_units_non_preview_identical"] += 1

            u = unit_map[uid]
            ucs, uce = u["span_chars"]
            utext = full_text[ucs:uce]
            body_start = independent_body_start(full_text, ucs, uce)
            content_start = independent_content_start(full_text, ucs, uce)
            content_end = ucs + len(utext.rstrip())
            protected = [m.span() for m in PROTECTED_TAG.finditer(full_text, ucs, uce)]

            if not v3_row["preview_refs"]:
                units_without_preview_v3_list.append({
                    "case_id": case_id,
                    "handle": v3_row["handle"],
                    "unit_id": uid,
                    "unit_kind": v3_row["unit_kind"],
                    "observed_marker": v3_row["observed_marker"],
                    "span_bytes": v3_row["span_bytes"],
                    "anchor_count": len(v3_row["anchor_refs"]),
                    "had_preview_in_v1": bool(v1_row["preview_refs"]),
                    "content_start_is_none": content_start is None,
                    "raw_text": utext,
                })

            # Check if v1 opening started on placeholder+punct-only line
            v1_openings = [p for p in v1_p_by_unit.get(uid, []) if p["preview_kind"] == "opening"]
            if v1_openings:
                v1_op = v1_openings[0]
                first_nl = v1_op["text"].find("\n")
                first_line = v1_op["text"] if first_nl < 0 else v1_op["text"][:first_nl]
                if not any(ch.isalnum() for ch in PLACEHOLDER.sub("", first_line)):
                    v3_openings = [p for p in v3_p_by_unit.get(uid, []) if p["preview_kind"] == "opening"]
                    if v3_openings:
                        placeholder_line_transitions["advanced_to_alphanumeric_opening"] += 1
                        if len(placeholder_line_transition_examples) < 15:
                            placeholder_line_transition_examples.append({
                                "transition": "advanced_to_alphanumeric_opening",
                                "case_id": case_id, "handle": v3_row["handle"], "unit_id": uid,
                                "v1_opening_span_bytes": v1_op["span_bytes"], "v1_opening_text": v1_op["text"],
                                "v3_opening_span_bytes": v3_openings[0]["span_bytes"], "v3_opening_text": v3_openings[0]["text"],
                            })
                    else:
                        placeholder_line_transitions["no_alphanumeric_in_unit_now_no_preview"] += 1
                        if len(placeholder_line_transition_examples) < 30:
                            placeholder_line_transition_examples.append({
                                "transition": "no_alphanumeric_in_unit_now_no_preview",
                                "case_id": case_id, "handle": v3_row["handle"], "unit_id": uid,
                                "v1_opening_span_bytes": v1_op["span_bytes"], "v1_opening_text": v1_op["text"],
                                "v3_preview_refs": v3_row["preview_refs"],
                                "v3_anchor_refs": v3_row["anchor_refs"],
                            })

            # Validate every v3 preview on this unit
            upreviews = v3_p_by_unit.get(uid, [])
            baseline = content_start if content_start is not None else body_start
            for p in upreviews:
                v3_contract_counters["previews_checked"] += 1
                pa, pb = p["span_bytes"]
                pcs, pce = p["span_chars"]
                if not (u["span_bytes"][0] <= pa < pb <= u["span_bytes"][1]):
                    errors.append(f"Preview byte span out of unit bounds: {case_id}/{p['preview_id']}")
                raw_slice = raw[pa:pb].decode("utf-8", errors="strict")
                if p["text"] != raw_slice or p["text_sha256"] != sha256_bytes(raw[pa:pb]):
                    errors.append(f"Preview text/sha256 mismatch: {case_id}/{p['preview_id']}")
                if pcs != ucs + len(raw[u["span_bytes"][0]:pa].decode("utf-8", errors="strict")) or pce != pcs + len(raw_slice):
                    errors.append(f"Preview span_chars mismatch: {case_id}/{p['preview_id']}")
                if len(raw_slice) > 240:
                    errors.append(f"Preview > 240 codepoints: {case_id}/{p['preview_id']}")
                if p["partial_sentence"] is not None or p["boundary_status"] != "content_window_not_sentence_verified":
                    errors.append(f"Preview sentence status invalid: {case_id}/{p['preview_id']}")
                exp_start_clip = pcs > baseline
                exp_end_clip = pce < content_end
                exp_trunc = exp_start_clip or exp_end_clip
                if p["start_clipped"] != exp_start_clip or p["end_clipped"] != exp_end_clip or p["truncated"] != exp_trunc:
                    errors.append(f"Preview clipping flags mismatch: {case_id}/{p['preview_id']}")
                if p["preview_kind"] == "opening" and pcs != baseline:
                    errors.append(f"Opening preview does not start at content_start: {case_id}/{p['preview_id']}")
                exp_word_clip = (
                    (pcs > ucs and full_text[pcs - 1].isalnum() and full_text[pcs].isalnum())
                    or (pce < uce and full_text[pce - 1].isalnum() and full_text[pce].isalnum())
                )
                exp_tag_clip = any(x < pcs < y or x < pce < y for x, y in protected)
                if p["word_boundary_clipped"] != exp_word_clip or p["tag_boundary_clipped"] != exp_tag_clip:
                    errors.append(f"Preview word/tag boundary flag mismatch: {case_id}/{p['preview_id']}")

                # Verify anchor visibility
                expected_overlapping_anchors = [
                    a for a in v3_rec["anchors"]
                    if a["unit_id"] == uid and pa < a["span_bytes"][1] and a["span_bytes"][0] < pb
                ]
                if p["anchor_refs"] != [a["anchor_id"] for a in expected_overlapping_anchors]:
                    errors.append(f"Preview anchor_refs mismatch: {case_id}/{p['preview_id']}")
                for vis, a in zip(p["anchor_visibility"], expected_overlapping_anchors):
                    full_vis = pa <= a["span_bytes"][0] and a["span_bytes"][1] <= pb
                    orig = a["original_cue_span_bytes"]
                    orig_vis = None if orig is None else (pa <= orig[0] and orig[1] <= pb)
                    if (
                        vis["anchor_ref"] != a["anchor_id"]
                        or vis["fully_visible"] != full_vis
                        or vis["source_cue_fully_visible"] != orig_vis
                        or vis["visibility"] != ("full" if full_vis else "partial")
                    ):
                        errors.append(f"Preview anchor_visibility mismatch: {case_id}/{p['preview_id']}")

            # Check if this unit is one of the 9 v2 tag clip cases
            if (case_id, uid) in v2_9_cases:
                cinfo = v2_9_cases[(case_id, uid)]
                v2_tag_clip_cases_comparison.append({
                    "case_id": case_id,
                    "handle": v3_row["handle"],
                    "unit_id": uid,
                    "v2_clipped_preview": next(p for p in v2_p_by_unit[uid] if p["preview_id"] == cinfo["preview_id"]),
                    "v3_previews": v3_p_by_unit[uid],
                    "unit_anchors": [v3_a_by_id[aid] for aid in v3_row["anchor_refs"]],
                })

            # Check if this unit is one of the 8 verbatim regression targets
            if regression_lookup.get(case_id) == v3_row["handle"]:
                v1_ps = v1_p_by_unit.get(uid, [])
                v3_ps = v3_p_by_unit.get(uid, [])
                v1_cov = {aid for p in v1_ps for aid in p["anchor_refs"]}
                v3_cov = {aid for p in v3_ps for aid in p["anchor_refs"]}
                regression_comparisons.append({
                    "case_id": case_id,
                    "handle": v3_row["handle"],
                    "unit_id": uid,
                    "source_hash": raw_sha,
                    "unit_span_bytes": u["span_bytes"],
                    "unit_span_chars": u["span_chars"],
                    "unit_raw_text": utext,
                    "v1_previews": v1_ps,
                    "v3_previews": v3_ps,
                    "unit_anchor_refs": v3_row["anchor_refs"],
                    "unit_anchors": [
                        {**v3_a_by_id[aid], "raw_text": raw[slice(*v3_a_by_id[aid]["span_bytes"])].decode("utf-8")}
                        for aid in v3_row["anchor_refs"]
                    ],
                    "v1_displayed_anchor_refs": sorted(v1_cov),
                    "v3_displayed_anchor_refs": sorted(v3_cov),
                    "anchors_added_to_display_in_v3": sorted(v3_cov - v1_cov),
                    "anchors_removed_from_display_in_v3": sorted(v1_cov - v3_cov),
                    "all_unit_anchors_accessible_in_catalog": set(v3_row["anchor_refs"]) == {
                        a["anchor_id"] for a in v3_rec["anchors"] if a["unit_id"] == uid
                    },
                    "case_source_anchors_count": len(v3_rec["source_anchors"]),
                })

        # Accumulate before/after stats
        r1 = analyze_preview_cuts_and_overlaps(v1_rec, unit_map, raw, full_text)
        r2 = analyze_preview_cuts_and_overlaps(v2_rec, unit_map, raw, full_text)
        r3 = analyze_preview_cuts_and_overlaps(v3_rec, unit_map, raw, full_text)
        v1_stats.update(r1["stats"])
        v2_stats.update(r2["stats"])
        v3_stats.update(r3["stats"])
        for k, vals in r1["examples"].items():
            v1_examples.setdefault(k, [])
            if len(v1_examples[k]) < 25:
                v1_examples[k].extend(vals[: 25 - len(v1_examples[k])])
        for k, vals in r3["examples"].items():
            v3_examples.setdefault(k, [])
            if len(v3_examples[k]) < 25:
                v3_examples[k].extend(vals[: 25 - len(v3_examples[k])])

    result = {
        "schema_version": "m2-preview-revision2-independent-audit-v1",
        "status": "PASS" if not errors else "FAIL",
        "error_count": len(errors),
        "errors": errors[:100],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "seals_and_inventory": seals,
        "v3_manifest_verification": {
            "m1_provenance_matches": v3_manifest.get("m1") == expected_m1_prov,
            "profile_sha256": v3_manifest.get("profile_sha256"),
            "implementation_hashes": actual_impl,
            "v1_profile_sha256": v1_manifest.get("profile_sha256"),
            "v1_implementation_hashes": v1_manifest.get("implementation"),
            "usage": v3_manifest.get("usage"),
            "labels_accessed": v3_manifest.get("labels_accessed"),
            "test_sources_accessed": v3_manifest.get("test_sources_accessed"),
        },
        "cross_version_invariance": dict(invariance_counters),
        "v3_contract_verification": dict(v3_contract_counters),
        "before_after_metrics": {
            "metric_definitions": {
                "short_opening_le_30_with_more_text": "Opening preview with len(text) <= 30 codepoints and content_end - preview_end > 20 codepoints.",
                "short_opening_le_15_with_more_text": "Opening preview with len(text) <= 15 codepoints and content_end - preview_end > 20 codepoints.",
                "opening_ends_with_period_before_unit_end": "Opening preview ending with '.' where preview_end < content_end. In v1 this resulted from stopping at the first '.!?' and setting partial_sentence=False; in v3 windows run up to 240 chars with partial_sentence=None.",
                "short_opening_clean_lt_100_unit_ge_120": "Opening preview where PLACEHOLDER-stripped preview has < 100 chars while PLACEHOLDER-stripped unit has >= 120 chars (heuristic diagnostic).",
                "contained_preview_pairs": "Pairs of previews on the same unit where one byte span is a subset of the other.",
                "mergeable_within_240_overlap_pairs": "Overlapping preview pairs on the same unit both starting >= content_start whose union is <= 240 codepoints.",
                "complementary_overlap_pairs_gt_240": "Overlapping preview pairs on the same unit whose union exceeds 240 codepoints and where the second slot adds novel anchor coverage.",
                "opening_starts_on_placeholder_punct_line": "Opening preview whose first line has 0 alphanumeric characters after stripping PLACEHOLDER tags.",
                "word_clipped_raw": "Previews where start or end cuts between two adjacent alphanumeric characters in raw source.",
                "tag_clipped_raw": "Previews where start or end falls strictly inside a PROTECTED_TAG span in raw source.",
            },
            "v1_baseline_counts": dict(v1_stats),
            "v2_checkpoint_counts": dict(v2_stats),
            "v3_final_counts": dict(v3_stats),
            "placeholder_only_line_transitions_v1_to_v3": dict(placeholder_line_transitions),
        },
        "v3_short_clean_lt_100_all_cases": v3_examples.get("short_clean_lt_100", []),
        "v3_units_without_preview_summary": {
            "total_count": len(units_without_preview_v3_list),
            "had_preview_in_v1_count": sum(1 for x in units_without_preview_v3_list if x["had_preview_in_v1"]),
            "had_no_preview_in_v1_count": sum(1 for x in units_without_preview_v3_list if not x["had_preview_in_v1"]),
            "all_have_content_start_none": all(x["content_start_is_none"] for x in units_without_preview_v3_list),
            "sample_records": units_without_preview_v3_list[:30],
        },
        "placeholder_line_transition_examples": placeholder_line_transition_examples,
        "verbatim_8_regressions": sorted(regression_comparisons, key=lambda x: x["case_id"]),
        "v2_9_tag_clip_regressions_in_v3": sorted(v2_tag_clip_cases_comparison, key=lambda x: x["case_id"]),
        "v1_diagnostic_examples": v1_examples,
        "v3_diagnostic_examples": v3_examples,
    }

    out_file = out_dir / "machine_audit_results.json"
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "error_count": result["error_count"],
        "elapsed_seconds": result["elapsed_seconds"],
        "v1_counts": result["before_after_metrics"]["v1_baseline_counts"],
        "v2_counts": result["before_after_metrics"]["v2_checkpoint_counts"],
        "v3_counts": result["before_after_metrics"]["v3_final_counts"],
        "placeholder_transitions": result["before_after_metrics"]["placeholder_only_line_transitions_v1_to_v3"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
