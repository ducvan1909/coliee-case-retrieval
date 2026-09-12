"""Structural validation only; passing it does not establish semantic correctness."""

from __future__ import annotations

from .markers import find_markers


def validate_structure(text: str, candidates: list[dict[str, object]], case_id: str | None = None, source_ref: str | None = None) -> list[str]:
    issues: list[str] = []
    expected_case_id = case_id or (candidates[0].get("case_id") if candidates and isinstance(candidates[0], dict) else None)
    previous_end = 0
    seen_ids: set[str] = set()
    spans: list[tuple[int, int]] = []
    for expected_order, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            issues.append(f"unit at order {expected_order} must be an object")
            continue
        identifier = str(candidate.get("id"))
        if not isinstance(candidate.get("id"), str) or not candidate["id"].strip():
            issues.append(f"invalid id at order {expected_order}")
        if identifier in seen_ids:
            issues.append(f"duplicate id: {identifier}")
        seen_ids.add(identifier)
        if not isinstance(candidate.get("case_id"), str) or not candidate["case_id"].strip() or candidate.get("case_id") != expected_case_id:
            issues.append(f"wrong case_id for {identifier}")
        if type(candidate.get("order")) is not int or candidate.get("order") != expected_order:
            issues.append(f"wrong order for {identifier}")
        source_span = candidate.get("source_span")
        if not isinstance(source_span, dict):
            issues.append(f"missing source_span for {identifier}")
            continue
        start, end = source_span.get("start_char"), source_span.get("end_char")
        if not isinstance(source_span.get("source_ref"), str) or not source_span["source_ref"].strip():
            issues.append(f"invalid source_ref for {identifier}")
        elif source_ref is not None and source_span["source_ref"] != source_ref:
            issues.append(f"wrong source_ref for {identifier}")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            issues.append(f"invalid span for {identifier}")
            continue
        if start < previous_end:
            issues.append(f"overlapping span for {identifier}")
        previous_end = end
        slice_text = text[start:end]
        if candidate.get("text") != slice_text:
            issues.append(f"source text mismatch for {identifier}")
        if "text" in source_span:
            issues.append(f"redundant source_span.text for {identifier}")
        spans.append((start, end))
    owners = [False] * len(text)
    for start, end in spans:
        for index in range(start, end):
            if owners[index]:
                issues.append(f"duplicate coverage at char {index}")
                break
            owners[index] = True
    uncovered = next((index for index, char in enumerate(text) if not char.isspace() and not owners[index]), None)
    if uncovered is not None:
        issues.append(f"uncovered non-whitespace char at {uncovered}")
    for marker in find_markers(text):
        if sum(start <= marker.start_char and marker.end_char <= end for start, end in spans) != 1:
            issues.append(f"marker split or uncovered: {marker.name} at {marker.start_char}")
    return issues


def validate_candidates(text: str, candidates: list[dict[str, object]], case_id: str | None = None) -> list[str]:
    """Validate provisional code output, without allowing semantic labels."""
    issues = validate_structure(text, candidates, case_id)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        identifier = candidate.get("id")
        if candidate.get("functions") != ["unknown"] or type(candidate.get("confidence")) not in (int, float) or candidate.get("confidence") != 0.0:
            issues.append(f"unexpected semantic output for {identifier}")
        if candidate.get("attributed_to") != {"kind": "unknown", "party_role": None}:
            issues.append(f"invalid provisional attributed_to for {identifier}")
        if "reporting_voice" not in candidate or candidate["reporting_voice"] is not None:
            issues.append(f"invalid provisional reporting_voice for {identifier}")
        if candidate.get("status") != "code_provisional":
            issues.append(f"wrong status for {identifier}")
    return issues
