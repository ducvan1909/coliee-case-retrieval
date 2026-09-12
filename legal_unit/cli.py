"""CLI for the isolated code-only LegalUnit pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from .sample_selection import materialize_sample
from .markers import find_markers
from .segmenter import SEGMENTER_VERSION, analyze_case, segment_case
from .validation import validate_candidates


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _load_sample_manifest(samples_dir: Path) -> dict[str, object]:
    return json.loads((samples_dir / "manifest.json").read_text(encoding="utf-8"))


def artifact_risk_metrics(rows: list[dict[str, object]]) -> dict[str, int]:
    """Count review signals; these counts do not establish semantic errors."""
    paragraph_marker = re.compile(r"(?m)^\[\d+\]\r?$")
    marker_counts = [len(paragraph_marker.findall(str(row.get("text", "")))) for row in rows]
    raw_bracket_counts = [len(re.findall(r"\[\d+\]", str(row.get("text", "")))) for row in rows]
    lengths = [len(str(row.get("text", ""))) for row in rows]
    return {
        "unit_count": len(rows),
        "units_at_least_10000_chars": sum(length >= 10_000 for length in lengths),
        "units_at_least_5_paragraph_markers": sum(count >= 5 for count in marker_counts),
        "units_at_least_10_paragraph_markers": sum(count >= 10 for count in marker_counts),
        "units_at_least_5_raw_bracket_numbers": sum(count >= 5 for count in raw_bracket_counts),
        "units_at_least_10_raw_bracket_numbers": sum(count >= 10 for count in raw_bracket_counts),
        "units_containing_editor": sum("Editor:" in str(row.get("text", "")) for row in rows),
        "units_where_editor_does_not_start_block": sum(
            "Editor:" in str(row.get("text", "")) and not str(row.get("text", "")).lstrip().startswith("Editor:")
            for row in rows
        ),
        "max_unit_chars": max(lengths, default=0),
        "max_paragraph_markers_in_unit": max(marker_counts, default=0),
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_comparison_report(before_path: Path, after_path: Path, output_path: Path) -> Path:
    before = _read_jsonl(before_path)
    after = _read_jsonl(after_path)
    def boundary_sets(rows: list[dict[str, object]]) -> dict[str, set[int]]:
        grouped: dict[str, list[int]] = {}
        for row in rows:
            span = row.get("source_span")
            if isinstance(row.get("case_id"), str) and isinstance(span, dict) and type(span.get("start_char")) is int:
                grouped.setdefault(str(row["case_id"]), []).append(int(span["start_char"]))
        return {case_id: set(offsets) - {min(offsets)} for case_id, offsets in grouped.items() if offsets}
    before_boundaries = boundary_sets(before)
    after_boundaries = boundary_sets(after)
    case_ids = sorted(set(before_boundaries) | set(after_boundaries))
    per_case = []
    for case_id in case_ids:
        old = before_boundaries.get(case_id, set())
        new = after_boundaries.get(case_id, set())
        per_case.append({
            "case_id": case_id,
            "added_offsets": sorted(new - old),
            "removed_offsets": sorted(old - new),
            "kept_offsets": sorted(old & new),
        })
    report = {
        "before": {"artifact": before_path.as_posix(), "metrics": artifact_risk_metrics(before)},
        "after": {"artifact": after_path.as_posix(), "metrics": artifact_risk_metrics(after)},
        "interpretation": "Counts are structural review signals, not semantic accuracy measurements.",
        "known_remaining_scope": "Within-paragraph legal-point and speaker changes require manual semantic review.",
        "boundary_delta": {
            "comparison_key": "case_id + source start offset; unit ordinals are ignored",
            "added_count": sum(len(row["added_offsets"]) for row in per_case),
            "removed_count": sum(len(row["removed_offsets"]) for row in per_case),
            "kept_count": sum(len(row["kept_offsets"]) for row in per_case),
            "cases": per_case,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def _review_queue(
    case_id: str,
    text: str,
    candidates: list[dict[str, object]],
    decisions: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Surface structural risk areas for source reading; this does not judge them."""
    queue: list[dict[str, object]] = []
    for candidate in candidates:
        span = candidate["source_span"]  # type: ignore[assignment]
        start, end = span["start_char"], span["end_char"]
        reasons: list[str] = []
        marker_names = [marker.name for marker in find_markers(text[start:end])]
        if marker_names:
            reasons.append("contains_suppression_marker")
        word_count = len(candidate["text"].split())
        if "quotation_balance_uncertain" in candidate["unknowns"]:
            reasons.append("quotation_balance_uncertain")
        if "wrapped_or_unstructured_line_kept_with_current_block" in candidate["unknowns"] and word_count >= 250:
            reasons.append("wrapped_or_unstructured_lines")
        if word_count >= 1000:
            reasons.append("very_long_structural_block")
        if reasons:
            queue.append(
                {
                    "case_id": case_id,
                    "legal_unit_id": candidate["id"],
                    "source_span": {"start_char": start, "end_char": end},
                    "review_reasons": reasons,
                    "marker_types": marker_names,
                    "finding_status": "pending_manual_review",
                    "review_note": "No semantic split/merge judgment has been made by code.",
                    "text_preview": candidate["text"][:500],
                }
            )
    for decision in decisions or []:
        if decision.get("decision") != "defer" or type(decision.get("offset")) is not int:
            continue
        offset = int(decision["offset"])
        queue.append({
            "case_id": case_id,
            "boundary_offset": offset,
            "review_reasons": ["deferred_boundary"],
            "finding_status": "pending_manual_review",
            "review_note": str(decision.get("reason", "Conflicting structural signals.")),
            "left_context": text[max(0, offset - 300) : offset],
            "right_context": text[offset : min(len(text), offset + 300)],
            "decision": decision,
        })
    return queue


def _render_case_debug(case_id: str, text: str, candidates: list[dict[str, object]], decisions: list[dict[str, object]]) -> str:
    by_offset = {int(decision["offset"]): decision for decision in decisions if type(decision.get("offset")) is int}
    blocks = [f"# Boundary debug: {case_id}\n\n"]
    for candidate in candidates:
        span = candidate["source_span"]
        start, end = int(span["start_char"]), int(span["end_char"])
        decision = by_offset.get(start)
        if decision is None:
            label = "document_start"
        else:
            label = f"{decision['decision']}: {decision['reason']}"
        blocks.append(f"<!-- {candidate['id']} {start}:{end} | {label} -->\n")
        blocks.append(text[start:end] + "\n\n")
    deferred = [decision for decision in decisions if decision.get("decision") == "defer"]
    if deferred:
        blocks.append("## Deferred line gaps\n\n")
        for decision in deferred:
            blocks.append(f"- offset {decision['offset']}: {decision['reason']}\n")
    return "".join(blocks)


def segment_samples(samples_dir: Path, outputs_dir: Path) -> Path:
    manifest = _load_sample_manifest(samples_dir)
    rows: list[dict[str, object]] = []
    review_queue: list[dict[str, object]] = []
    case_reports: list[dict[str, object]] = []
    all_decisions: list[dict[str, object]] = []
    review_blocks: list[str] = ["# LegalUnit boundary review\n", "This is structural validation and source-review material only. It is not a semantic LegalUnit evaluation.\n"]
    for sample in manifest["samples"]:  # type: ignore[index]
        case_id = sample["case_id"]  # type: ignore[index]
        source = samples_dir / "cases" / str(case_id)
        raw = source.read_bytes()
        text = raw.decode("utf-8", errors="strict")
        candidates, decisions = analyze_case(str(case_id), text, source.as_posix())
        issues = validate_candidates(text, candidates, str(case_id))
        if issues:
            raise ValueError(f"Validation failed for {case_id}: {issues}")
        rows.extend(candidates)
        review_queue.extend(_review_queue(str(case_id), text, candidates, decisions))
        all_decisions.extend(decisions)
        case_reports.append({"case_id": case_id, "sha256": hashlib.sha256(raw).hexdigest(), "unit_count": len(candidates), "validation": "passed", "semantic_review": "pending"})
        review_blocks.append(f"## {case_id}\n")
        for candidate in candidates:
            span = candidate["source_span"]  # type: ignore[assignment]
            review_blocks.append(f"<!-- {candidate['id']} {span['start_char']}:{span['end_char']} | {', '.join(candidate['boundary_basis'])} -->\n")
            review_blocks.append(candidate["text"] + "\n\n")
        debug_path = outputs_dir / "debug" / f"{case_id}.md"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(_render_case_debug(str(case_id), text, candidates, decisions), encoding="utf-8")
    artifact_path = outputs_dir / "legal_unit_candidates.jsonl"
    _write_jsonl(artifact_path, rows)
    _write_jsonl(outputs_dir / "review_queue.jsonl", review_queue)
    _write_jsonl(outputs_dir / "boundary_decisions.jsonl", all_decisions)
    report = {"segmenter_version": SEGMENTER_VERSION, "case_count": len(case_reports), "unit_count": len(rows), "structural_validation": "passed", "semantic_review": "not performed; review queue generated", "review_queue_count": len(review_queue), "risk_metrics": artifact_risk_metrics(rows), "cases": case_reports}
    (outputs_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (outputs_dir / "boundary_review.md").write_text("".join(review_blocks), encoding="utf-8")
    sample_manifest_path = samples_dir / "manifest.json"
    segmenter_path = Path(__file__).with_name("segmenter.py")
    runner_path = Path(__file__)
    code_fingerprint = hashlib.sha256(segmenter_path.read_bytes() + b"\0" + runner_path.read_bytes()).hexdigest()
    run_manifest = {
        "segmenter_version": SEGMENTER_VERSION,
        "segmenter_sha256": hashlib.sha256(segmenter_path.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(runner_path.read_bytes()).hexdigest(),
        "code_fingerprint": code_fingerprint,
        "sample_manifest": sample_manifest_path.as_posix(),
        "sample_manifest_sha256": hashlib.sha256(sample_manifest_path.read_bytes()).hexdigest(),
        "configuration": {
            "decision_values": ["split", "keep", "defer"],
            "semantic_segmentation": False,
            "hard_length_boundary": False,
        },
        "sources": [
            {"case_id": item["case_id"], "sha256": item["sha256"]}
            for item in case_reports
        ],
    }
    (outputs_dir / "run_manifest.json").write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact_path


def validate_artifact(samples_dir: Path, artifact_path: Path) -> list[str]:
    manifest = _load_sample_manifest(samples_dir)
    expected_case_ids = {str(sample["case_id"]) for sample in manifest["samples"]}  # type: ignore[index]
    grouped: dict[str, list[dict[str, object]]] = {}
    for line in artifact_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        grouped.setdefault(row["case_id"], []).append(row)
    issues: list[str] = []
    for missing in sorted(expected_case_ids - set(grouped)):
        issues.append(f"missing sample case in artifact: {missing}")
    for unexpected in sorted(set(grouped) - expected_case_ids):
        issues.append(f"unexpected case in artifact: {unexpected}")
    for case_id, candidates in grouped.items():
        if case_id not in expected_case_ids:
            continue
        text = (samples_dir / "cases" / case_id).read_bytes().decode("utf-8", errors="strict")
        case_issues = validate_candidates(text, candidates, case_id)
        issues.extend(f"{case_id}: {issue}" for issue in case_issues)
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Code-only provisional LegalUnit pilot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    select = subparsers.add_parser("select")
    select.add_argument("--train-root", type=Path, required=True)
    select.add_argument("--samples-dir", type=Path, required=True)
    select.add_argument("--split", choices=("development", "validation"), default="development")
    select.add_argument("--exclude-manifest", type=Path)
    segment = subparsers.add_parser("segment")
    segment.add_argument("--samples-dir", type=Path, required=True)
    segment.add_argument("--outputs-dir", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--samples-dir", type=Path, required=True)
    validate.add_argument("--artifact", type=Path, required=True)
    compare = subparsers.add_parser("compare", help="Compare structural review metrics for two artifacts")
    compare.add_argument("--before", type=Path, required=True)
    compare.add_argument("--after", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "select":
        print(materialize_sample(args.train_root, args.samples_dir, split=args.split, exclude_manifest=args.exclude_manifest))
    elif args.command == "segment":
        print(segment_samples(args.samples_dir, args.outputs_dir))
    elif args.command == "compare":
        print(write_comparison_report(args.before, args.after, args.output))
    else:
        issues = validate_artifact(args.samples_dir, args.artifact)
        if issues:
            raise SystemExit("\n".join(issues))
        print("schema/structural validation passed; semantic correctness not evaluated")


if __name__ == "__main__":
    main()
