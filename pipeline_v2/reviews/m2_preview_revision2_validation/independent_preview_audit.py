"""Independent full-corpus audit of M2 preview revision 2.

This deliberately does not import the navigation builder or validator. It uses
sealed M1/M2 JSON and the raw source files to check invariants and provenance.
It measures display mechanics, not legal or semantic preview quality.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time


PLACEHOLDER = re.compile(r"[<(]?(?:FRAGMENT|REFERENCE)_SUPPRESSED[>)]?")
PROTECTED_TAG = re.compile(r"<[^<>\r\n]+>|\((?:FRAGMENT|REFERENCE|DATE)_SUPPRESSED\)")
ROW_FIELDS_EXCLUDED = {"preview_refs", "preview_absence_reason"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def char_before(raw: bytes, offset: int):
    if offset <= 0 or offset > len(raw):
        return ""
    start = offset - 1
    while start > 0 and raw[start] & 0xC0 == 0x80:
        start -= 1
    return raw[start:offset].decode("utf-8", errors="strict")


def char_after(raw: bytes, offset: int):
    if offset < 0 or offset >= len(raw):
        return ""
    first = raw[offset]
    width = 1 if first < 0x80 else 2 if first < 0xE0 else 3 if first < 0xF0 else 4
    return raw[offset:offset + width].decode("utf-8", errors="strict")


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def verify_bundle(bundle: Path):
    seal = read_json(bundle / "seal.json")
    errors = []
    expected = set(seal.get("files", {})) | {"seal.json"}
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()}
    if actual != expected:
        errors.append(f"bundle inventory mismatch: expected={len(expected)}, actual={len(actual)}")
    for name, meta in seal.get("files", {}).items():
        path = bundle / name
        if not path.is_file():
            errors.append(f"missing sealed file: {name}")
            continue
        raw = path.read_bytes()
        if sha(raw) != meta.get("sha256") or len(raw) != meta.get("byte_length"):
            errors.append(f"seal mismatch: {name}")
    registry = read_json(bundle / "source_registry.json")
    rows = {r["case_id"]: r for r in registry["sources"]}
    if len(rows) != len(registry["sources"]):
        errors.append("duplicate case in source registry")
    return rows, errors


def audit(root: Path, old_path: Path, new_path: Path):
    started = time.perf_counter()
    old, old_errors = verify_bundle(old_path)
    new, new_errors = verify_bundle(new_path)
    errors = old_errors + new_errors
    counters = Counter()
    suspicious_short_openings = []
    suspicious_boundary_cases = []
    tag_boundary_clip_cases = []
    examples = []
    requested_examples = {"011922", "051807", "080359", "068193", "014101", "048208", "081945", "015740"}
    if set(old) != set(new):
        errors.append("old/new source universes differ")
    if set(old) != set(new):
        common = sorted(set(old) & set(new))
    else:
        common = sorted(old)

    # Resolve M1 from the old bundle's pinned manifest instead of assuming a
    # fixed artifact directory layout.
    manifest = read_json(old_path / "manifest.json")
    m1_relative = manifest["m1"]["bundle"]
    m1_root = root / m1_relative
    m1_registry = read_json(m1_root / "source_registry.json")
    m1_rows = {r["case_id"]: r for r in m1_registry["sources"]}
    new_manifest = read_json(new_path / "manifest.json")
    if new_manifest.get("m1") != manifest.get("m1"):
        errors.append("new bundle M1 provenance differs from old bundle")
    usage = new_manifest.get("usage", {})
    if any(usage.get(key) != 0 for key in ("model_requests", "model_retries", "model_tokens")):
        errors.append("new bundle reports model usage during M2 build")
    if new_manifest.get("labels_accessed") is not False or new_manifest.get("test_sources_accessed") is not False:
        errors.append("new bundle reports label or test-source access")
    summary = read_json(new_path / "summary.json")
    summary_readiness = summary.get("readiness", {})
    for key in ("token_validated_chunks", "token_counts", "agent_payload_budget", "dense"):
        if summary_readiness.get(key) != "not_ready":
            errors.append(f"token/model-dependent readiness unexpectedly set: {key}")

    for case_id in common:
        counters["cases"] += 1
        old_rec = read_json(old_path / old[case_id]["navigation_ref"])
        new_rec = read_json(new_path / new[case_id]["navigation_ref"])
        m1_path = m1_root / m1_rows[case_id]["structure_ref"]
        m1_rec = read_json(m1_path)
        raw = (root / m1_rows[case_id]["path"]).read_bytes()
        if sha(raw) != old_rec.get("source_hash") or sha(raw) != new_rec.get("source_hash"):
            errors.append(f"raw source hash mismatch: {case_id}")
        if sha(raw) != m1_rows[case_id].get("raw_sha256"):
            errors.append(f"raw source differs from M1 registry: {case_id}")
        if sha(canonical(m1_rec)) != m1_rows[case_id].get("structure_sha256"):
            errors.append(f"M1 structure record differs from registry: {case_id}")
        if old_rec.get("source_hash") != new_rec.get("source_hash"):
            errors.append(f"old/new raw source changed: {case_id}")
        if old_rec.get("m1_structure_sha256") != new_rec.get("m1_structure_sha256"):
            errors.append(f"M1 structure fingerprint changed: {case_id}")
        if old_rec.get("anchors") != new_rec.get("anchors"):
            errors.append(f"anchor catalog changed: {case_id}")
        if old_rec.get("source_anchors") != new_rec.get("source_anchors"):
            errors.append(f"source anchor catalog changed: {case_id}")
        if old_rec.get("headings") != new_rec.get("headings"):
            errors.append(f"heading catalog changed: {case_id}")

        old_rows = {r["unit_id"]: r for r in old_rec["navigation"]}
        new_rows = {r["unit_id"]: r for r in new_rec["navigation"]}
        units = {u["unit_id"]: u for u in m1_rec["units"] if u["unit_kind"] in ("paragraph", "unnumbered")}
        if set(old_rows) != set(new_rows) or set(new_rows) != set(units):
            errors.append(f"navigation IDs/coverage changed or diverged from M1: {case_id}")
        preview_map = {p["preview_id"]: p for p in new_rec["previews"]}
        anchor_map = {a["anchor_id"]: a for a in new_rec["anchors"]}
        preview_ids = [p["preview_id"] for p in new_rec["previews"]]
        if len(set(preview_ids)) != len(preview_ids):
            errors.append(f"duplicate preview IDs: {case_id}")

        if case_id[:-4] in requested_examples:
            old_marker_one = next((r for r in old_rec["navigation"] if r.get("observed_marker") == 1), None)
            new_marker_one = next((r for r in new_rec["navigation"] if r.get("observed_marker") == 1), None)
            if old_marker_one and new_marker_one and old_marker_one["handle"] == new_marker_one["handle"]:
                old_previews = {p["preview_id"]: p for p in old_rec["previews"]}
                after = [preview_map[p] for p in new_marker_one["preview_refs"]]
                before = [old_previews[p] for p in old_marker_one["preview_refs"] if p in old_previews]
                examples.append({
                    "case_id": case_id,
                    "handle": new_marker_one["handle"],
                    "unit_id": new_marker_one["unit_id"],
                    "before": [{"kind": p["preview_kind"], "span_bytes": p["span_bytes"],
                                "text_prefix": p["text"][:120]} for p in before],
                    "after": [{"kind": p["preview_kind"], "span_bytes": p["span_bytes"],
                               "text_prefix": p["text"][:120]} for p in after],
                })

        for unit_id in set(old_rows) & set(new_rows):
            old_row, new_row = old_rows[unit_id], new_rows[unit_id]
            counters["navigation_units"] += 1
            if {k: v for k, v in old_row.items() if k not in ROW_FIELDS_EXCLUDED} != {
                    k: v for k, v in new_row.items() if k not in ROW_FIELDS_EXCLUDED}:
                errors.append(f"navigation fields outside preview mapping changed: {case_id}/{unit_id}")
            if new_row["span_bytes"] != units[unit_id]["span_bytes"]:
                errors.append(f"navigation source span changed: {case_id}/{unit_id}")
            refs = new_row["preview_refs"]
            if len(refs) > 2 or len(set(refs)) != len(refs):
                errors.append(f"preview ref count/uniqueness invalid: {case_id}/{unit_id}")
            if any(ref not in preview_map or preview_map[ref]["unit_id"] != unit_id for ref in refs):
                errors.append(f"dangling or cross-unit preview ref: {case_id}/{unit_id}")
            if set(new_row["anchor_refs"]) != {a["anchor_id"] for a in new_rec["anchors"] if a["unit_id"] == unit_id}:
                errors.append(f"anchor catalog not completely referenced: {case_id}/{unit_id}")
            if any(aid not in anchor_map or anchor_map[aid]["unit_id"] != unit_id for aid in new_row["anchor_refs"]):
                errors.append(f"dangling or cross-unit anchor ref: {case_id}/{unit_id}")

        previews_by_unit = {}
        unit_texts = {unit_id: raw[unit["span_bytes"][0]:unit["span_bytes"][1]].decode("utf-8", errors="strict")
                      for unit_id, unit in units.items()}
        for preview in new_rec["previews"]:
            counters["previews"] += 1
            unit = units.get(preview["unit_id"])
            if unit is None:
                errors.append(f"preview refers to unknown unit: {case_id}/{preview.get('preview_id')}")
                continue
            a, b = preview["span_bytes"]
            ua, ub = unit["span_bytes"]
            if not (ua <= a < b <= ub <= len(raw)):
                errors.append(f"preview outside exact M1/raw bounds: {case_id}/{preview['preview_id']}")
                continue
            try:
                source_slice = raw[a:b].decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                errors.append(f"preview splits UTF-8 codepoint: {case_id}/{preview['preview_id']}")
                continue
            if preview.get("text") != source_slice or preview.get("text_sha256") != sha(raw[a:b]):
                errors.append(f"preview text/hash differs from raw slice: {case_id}/{preview['preview_id']}")
            if len(source_slice) > 240:
                errors.append(f"preview exceeds 240 Unicode codepoints: {case_id}/{preview['preview_id']}")
            counters["max_preview_chars"] = max(counters["max_preview_chars"], len(source_slice))
            counters["word_boundary_clipped"] += int(preview.get("word_boundary_clipped") is True)
            counters["tag_boundary_clipped"] += int(preview.get("tag_boundary_clipped") is True)
            if preview.get("partial_sentence") is not None:
                errors.append(f"preview claims sentence completeness: {case_id}/{preview['preview_id']}")
            counters["sentence_status_unverified"] += int(preview.get("partial_sentence") is None)
            if preview.get("boundary_status") != "content_window_not_sentence_verified":
                errors.append(f"unexpected sentence boundary status: {case_id}/{preview['preview_id']}")
            for flag in ("truncated", "start_clipped", "end_clipped"):
                if type(preview.get(flag)) is not bool:
                    errors.append(f"missing/nonboolean {flag}: {case_id}/{preview['preview_id']}")
            for flag in ("word_boundary_clipped", "tag_boundary_clipped"):
                if type(preview.get(flag)) is not bool:
                    errors.append(f"missing/nonboolean {flag}: {case_id}/{preview['preview_id']}")
            expected_word_clip = (
                a > ua and char_before(raw, a).isalnum() and char_after(raw, a).isalnum()
            ) or (
                b < ub and char_before(raw, b).isalnum() and char_after(raw, b).isalnum()
            )
            unit_text = unit_texts[preview["unit_id"]]
            rel_start = len(raw[ua:a].decode("utf-8", errors="strict"))
            rel_end = len(raw[ua:b].decode("utf-8", errors="strict"))
            tag_matches = list(PROTECTED_TAG.finditer(unit_text))
            crossing_tags = [match for match in tag_matches
                             if match.start() < rel_start < match.end() or match.start() < rel_end < match.end()]
            expected_tag_clip = bool(crossing_tags)
            if preview.get("word_boundary_clipped") is not expected_word_clip:
                errors.append(f"word clipping flag differs from raw neighboring characters: {case_id}/{preview['preview_id']}")
            if preview.get("tag_boundary_clipped") is not expected_tag_clip:
                errors.append(f"tag clipping flag differs from raw tag boundary: {case_id}/{preview['preview_id']}")
            if any(aid not in anchor_map or anchor_map[aid]["unit_id"] != preview["unit_id"]
                   for aid in preview.get("anchor_refs", [])):
                errors.append(f"preview has invalid anchor refs: {case_id}/{preview['preview_id']}")
            previews_by_unit.setdefault(preview["unit_id"], []).append(preview)
            if preview["preview_kind"] == "opening":
                clean = PLACEHOLDER.sub("", source_slice)
                if not any(char.isalnum() for char in clean):
                    errors.append(f"opening preview has no alphanumeric content: {case_id}/{preview['preview_id']}")
                unit_text = raw[ua:ub].decode("utf-8", errors="strict")
                substantive = PLACEHOLDER.sub("", unit_text)
                if len(substantive) >= 120 and len(clean) < 100:
                    suspicious_short_openings.append({"case_id": case_id, "unit_id": preview["unit_id"],
                                                      "preview_id": preview["preview_id"], "preview_chars": len(clean)})
            if preview.get("word_boundary_clipped") or preview.get("tag_boundary_clipped"):
                suspicious_boundary_cases.append({"case_id": case_id, "preview_id": preview["preview_id"],
                                                  "word_boundary_clipped": preview.get("word_boundary_clipped"),
                                                  "tag_boundary_clipped": preview.get("tag_boundary_clipped"),
                                                  "ending": source_slice[-24:]})
            if expected_tag_clip:
                for match in crossing_tags:
                    boundary = "start" if match.start() < rel_start < match.end() else "end"
                    cut = rel_start if boundary == "start" else rel_end
                    delta = cut - match.start() if boundary == "start" else match.end() - cut
                    preview_chars = len(source_slice)
                    fully_visible = [anchor_map[relation["anchor_ref"]] for relation in preview.get("anchor_visibility", [])
                                     if relation.get("fully_visible") and relation.get("anchor_ref") in anchor_map]
                    if boundary == "start":
                        simple_repair = preview_chars + delta <= 240
                        shrink_end = max(0, preview_chars + delta - 240)
                        candidate_end_char = rel_end - shrink_end
                        shrink_preserves_full_anchors = all(
                            len(raw[ua:anchor["span_bytes"][1]].decode("utf-8", errors="strict")) <= candidate_end_char
                            for anchor in fully_visible
                        )
                    else:
                        simple_repair = preview_chars + delta <= 240
                        shift_start = max(0, preview_chars + delta - 240)
                        candidate_start_char = rel_start + shift_start
                        shrink_preserves_full_anchors = all(
                            len(raw[ua:anchor["span_bytes"][0]].decode("utf-8", errors="strict")) >= candidate_start_char
                            for anchor in fully_visible
                        )
                    tag_boundary_clip_cases.append({
                        "case_id": case_id, "unit_id": preview["unit_id"], "preview_id": preview["preview_id"],
                        "span_bytes": [a, b], "tag": match.group(0), "tag_length": len(match.group(0)),
                        "boundary": boundary, "cut_offset_in_unit_chars": cut,
                        "preview_chars": preview_chars, "chars_to_restore_tag": delta,
                        "simple_repair_within_240": simple_repair,
                        "same_full_anchor_coverage_possible_within_240": simple_repair or shrink_preserves_full_anchors,
                        "raw_context": unit_text[max(0, cut - 80):min(len(unit_text), cut + 80)],
                    })

        for unit_id, previews in previews_by_unit.items():
            counters["units_with_previews"] += 1
            for i, left in enumerate(previews):
                la, lb = left["span_bytes"]
                for right in previews[i + 1:]:
                    ra, rb = right["span_bytes"]
                    if (la <= ra and rb <= lb) or (ra <= la and lb <= rb):
                        counters["contained_preview_pairs"] += 1
                        errors.append(f"contained/duplicate display windows: {case_id}/{unit_id}/{left['preview_id']}/{right['preview_id']}")

        readiness = new_rec.get("readiness", {})
        if readiness.get("token_counts") != "not_ready" or readiness.get("token_validated_chunks") != "not_ready":
            errors.append(f"token-dependent readiness changed: {case_id}")
        for row in new_rec["navigation"]:
            if row.get("token_count") is not None or "read_state" in row or "Open" in row:
                errors.append(f"runtime/token field present: {case_id}/{row['unit_id']}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "old_bundle": str(old_path), "new_bundle": str(new_path),
        "counts": dict(counters), "error_count": len(errors), "errors": errors[:100],
        "contained_preview_pair_count": counters["contained_preview_pairs"],
        "errors_truncated": len(errors) > 100,
        "short_opening_diagnostics": suspicious_short_openings[:100],
        "short_opening_diagnostic_count": len(suspicious_short_openings),
        "same_handle_raw_source_examples": examples,
        "boundary_clip_flag_diagnostics": suspicious_boundary_cases[:100],
        "boundary_clip_flag_count": len(suspicious_boundary_cases),
        "raw_verified_tag_boundary_clip_cases": tag_boundary_clip_cases,
        "raw_verified_tag_boundary_clip_count": len(tag_boundary_clip_cases),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "limitations": [
            "This audit checks structure, provenance, selection bounds, and sentence-status claims only.",
            "Short-opening and word/tag-boundary clipping counts are diagnostics, not semantic error rates.",
            "It does not assess legal relevance, quote ownership, or whether an opening is a good summary."
        ]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--old", type=Path, default=Path("pipeline_v2/artifacts/m2_navigation_20261105_v1"))
    parser.add_argument("--new", type=Path, default=Path("pipeline_v2/artifacts/m2_navigation_20261106_v2"))
    parser.add_argument("--output", type=Path, default=Path("pipeline_v2/reviews/m2_preview_revision2_validation/full_corpus_audit.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    result = audit(root, (root / args.old).resolve(), (root / args.new).resolve())
    out = (root / args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "counts", "error_count", "contained_preview_pair_count",
                                                 "raw_verified_tag_boundary_clip_count", "elapsed_seconds",
                                                 "short_opening_diagnostic_count")},
                     ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
