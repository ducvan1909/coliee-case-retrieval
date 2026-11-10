"""Independent raw-byte marker coverage scan for an M1 R2 bundle.

This deliberately does not import M1's parser or marker-coverage validator.
It verifies that each line-start numeric token in the raw files has one
separately addressable paragraph unit or an evidence-backed reporter marker.
Ownership correctness is outside this script's claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[4]
M0_DEFAULT = ROOT / "pipeline_v2" / "artifacts" / "m0_20261105_v2"
CORPUS = ROOT / "data" / "task1_train_files_2026" / "cases"
RAW_MARKER = re.compile(rb"(?m)^[ \t]*(?:\xef\xbb\xbf)?(\[[0-9]+\])")
REPORTER = re.compile(
    rb"^[ \t]*(?:FC|CF|FCA|CAF|SCC|CSC|F\.T\.R\.|F\.C\.|S\.C\.R\.|CanLII|"
    rb"[A-Z][A-Za-z.]*[ \t]+[A-Z][A-Za-z.]*\.)[ \t]*[0-9]", re.I
)


def load(path):
    return json.loads(path.read_bytes().decode("utf-8"))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fail(message):
    raise ValueError(message)


def scan(bundle: Path, m0_bundle: Path):
    m0_inventory = load(m0_bundle / "inventory.json")
    m1_registry = load(bundle / "source_registry.json")["sources"]
    manifest = load(bundle / "manifest.json")
    frozen = {row["case_id"]: row for row in m0_inventory["sources"]}
    registry = {row["case_id"]: row for row in m1_registry}
    if set(registry) != set(frozen) or manifest.get("m0", {}).get("inventory_sha256") is None:
        fail("M0/M1 source universes differ or M1 lacks M0 inventory provenance")

    counts = Counter()
    marker_totals = Counter()
    role_counts = Counter()
    errors = []
    for case_id in sorted(frozen):
        raw_path = CORPUS / case_id
        raw = raw_path.read_bytes()
        m0_row, row = frozen[case_id], registry[case_id]
        if sha(raw) != m0_row["sha256"] or len(raw) != m0_row["byte_length"]:
            errors.append(f"{case_id}: raw differs from frozen M0")
            continue
        if row.get("raw_sha256") != m0_row["sha256"] or row.get("byte_length") != m0_row["byte_length"]:
            errors.append(f"{case_id}: registry differs from frozen M0")
            continue

        record = load(bundle / row["structure_ref"])
        if record.get("raw_sha256") != m0_row["sha256"]:
            errors.append(f"{case_id}: record source hash mismatch")
            continue
        candidate_spans = {}
        for match in RAW_MARKER.finditer(raw):
            span = match.span(1)
            candidate_spans[span] = match.group(1).decode("ascii")

        represented = {}
        units = {u["unit_id"]: u for u in record["units"]}
        for unit in record["units"]:
            if unit.get("unit_kind") != "paragraph":
                continue
            marker_span = tuple(unit.get("marker_span_bytes", ()))
            if marker_span not in candidate_spans:
                errors.append(f"{case_id}: paragraph marker missing from independent raw scan: {marker_span}")
                continue
            if marker_span in represented:
                errors.append(f"{case_id}: marker mapped to multiple paragraph units: {marker_span}")
                continue
            if not (unit["span_bytes"][0] <= marker_span[0] < marker_span[1] <= unit["span_bytes"][1]):
                errors.append(f"{case_id}: marker is outside its own paragraph unit: {marker_span}")
            marker_text = raw[slice(*marker_span)].decode("ascii")
            if marker_text != candidate_spans[marker_span]:
                errors.append(f"{case_id}: marker literal mismatch: {marker_span}")
            represented[marker_span] = "paragraph"
            role = unit.get("paragraph_role")
            if role not in {"current_case", "quoted", "unknown"}:
                errors.append(f"{case_id}: invalid paragraph_role {role!r}")
            role_counts[role] += 1
            if role != "unknown" and not unit.get("role_evidence_refs"):
                errors.append(f"{case_id}: role {role!r} has no evidence refs")
            for evidence in unit.get("role_evidence_refs", []):
                a, b = evidence["span_bytes"]
                if not (0 <= a < b <= len(raw)) or not raw[a:b].decode("utf-8").strip():
                    errors.append(f"{case_id}: empty/out-of-range role evidence {a}:{b}")

        for observation in record.get("marker_observations", []):
            marker_span = tuple(observation.get("span_bytes", ()))
            if marker_span not in candidate_spans:
                errors.append(f"{case_id}: citation observation absent from raw scan: {marker_span}")
                continue
            if marker_span in represented:
                errors.append(f"{case_id}: marker duplicated as paragraph and citation: {marker_span}")
                continue
            a, b = marker_span
            line_end = raw.find(b"\n", b)
            tail = raw[b: line_end if line_end >= 0 else len(raw)]
            if not REPORTER.match(tail):
                errors.append(f"{case_id}: citation observation lacks reporter tail: {marker_span}")
            represented[marker_span] = "citation"

        if set(represented) != set(candidate_spans):
            missing = sorted(set(candidate_spans) - set(represented))[:5]
            extra = sorted(set(represented) - set(candidate_spans))[:5]
            errors.append(f"{case_id}: marker coverage mismatch missing={missing} extra={extra}")

        paragraph_markers = sorted(a for (a, _), kind in represented.items() if kind == "paragraph")
        for unit in record["units"]:
            if unit.get("unit_kind") != "paragraph":
                continue
            a, b = unit["span_bytes"]
            next_index = next((i for i, marker in enumerate(paragraph_markers) if marker >= a), len(paragraph_markers))
            if next_index + 1 < len(paragraph_markers) and paragraph_markers[next_index + 1] < b:
                errors.append(f"{case_id}: a paragraph span swallows a later line marker")

        for relation in record.get("sidecars", []):
            quoted = units.get(relation.get("quoted_unit_id"))
            attribution = units.get(relation.get("attribution_unit_id"))
            if quoted is None or quoted.get("paragraph_role") != "quoted":
                errors.append(f"{case_id}: quotation relation has no quoted unit")
            if relation.get("attribution_unit_id") is not None and attribution is None:
                errors.append(f"{case_id}: quotation relation references an unknown attribution unit")
            for evidence in relation.get("attribution_cue_refs", []):
                a, b = evidence["span_bytes"]
                if not (0 <= a < b <= len(raw)) or not raw[a:b].decode("utf-8").strip():
                    errors.append(f"{case_id}: empty/out-of-range attribution evidence {a}:{b}")

        counts["sources"] += 1
        marker_totals["line_markers"] += len(candidate_spans)
        marker_totals["paragraph_units"] += sum(kind == "paragraph" for kind in represented.values())
        marker_totals["citation_observations"] += sum(kind == "citation" for kind in represented.values())
        counts["paragraph_units"] += sum(u.get("unit_kind") == "paragraph" for u in record["units"])
        counts["quotation_relations"] += len(record.get("sidecars", []))

    return {"sources_scanned": counts["sources"], "paragraph_units": counts["paragraph_units"],
            "line_markers": marker_totals["line_markers"], "marker_units": marker_totals["paragraph_units"],
            "citation_observations": marker_totals["citation_observations"],
            "paragraph_roles": dict(role_counts), "quotation_relations": counts["quotation_relations"],
            "errors": errors[:100], "error_count": len(errors),
            "claim": "independent marker boundary/address coverage only; not ownership or semantic structure accuracy"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--m0-bundle", type=Path, default=M0_DEFAULT)
    args = parser.parse_args()
    result = scan(args.bundle, args.m0_bundle)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["error_count"] == 0 else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
