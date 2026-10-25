"""Legal-aware local sentence segmentation over validated SourceBlocks."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any


ABBREVIATION_RE = re.compile(
    r"(?i)(?<!\w)(?:v|J|No|Nos|s|ss|para|paras|F\.C|F\.C\.A|S\.C\.R|D\.L\.R|"
    r"Mr|Mrs|Ms|Dr|Q\.C|Ltd|Inc|Co|R)\."
)
INITIAL_RE = re.compile(r"(?<!\w)[A-Z]\.(?=\s*[A-Z])")
REPORTER_RE = re.compile(
    r"\b(?:\d{4}\s+(?:SCC|FC|FCA|FCT|CanLII)\s+\d+|\d+\s+(?:F\.C\.|F\.T\.R\.|S\.C\.R\.|D\.L\.R\.)\s+\d+)"
)
CASE_NAME_RE = re.compile(
    r"\b[A-Z][A-Za-z'’-]*(?:\s+[A-Z][A-Za-z'’-]*){0,3}\s+v\.\s+"
    r"[A-Z][A-Za-z'’-]*(?:\s+[A-Z][A-Za-z'’-]*){0,3}"
)
DECIMAL_RE = re.compile(r"\b\d+\.\d+\b")
SECTION_RE = re.compile(r"(?i)\b(?:s|ss|para|paras)\.\s*\d+(?:\([A-Za-z0-9]+\))*")
LIST_RE = re.compile(r"(?m)^[ \t]*(?:\([a-zA-Z0-9ivxIVX]+\)|[-*\u2022])(?=[ \t]+)")
NEWLINE_RE = re.compile(r"\r\n|\r|\n")
TERMINAL_RE = re.compile(r"[.!?]+")

FORBIDDEN_TYPES = {
    "abbreviation", "initial", "reporter_citation", "case_name", "decimal_reference",
    "section_reference", "citation_year", "paragraph_marker", "list_marker",
}
EVENT_SPECS = {
    "unbalanced_quotation": ("review", "unbalanced_quote_requires_review", "Quotation delimiter is unbalanced; span is context-only."),
    "oversized_atom": ("review", "atom_exceeds_slice_cap", "A SentenceAtom exceeds the configured slice cap and is not split internally."),
    "slice_exceeds_cap": ("review", "slice_exceeds_cap_due_to_atomicity", "Derived slice exceeds cap because SentenceAtom boundaries are preserved."),
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def span(case_id: str, source_hash: str, start: int, end: int) -> dict[str, Any]:
    return {"case_id": case_id, "source_hash": source_hash, "start_char": start, "end_char": end}


def cache_key_for(case_id: str, source_hash: str, sourceblock_cache: str, segmenter: str, policy_hash: str) -> str:
    return canonical_hash({"case_id": case_id, "source_hash": source_hash, "sourceblock_map_cache_key": sourceblock_cache, "segmenter_version": segmenter, "policy_sha256": policy_hash})


def _protected_id(payload: dict[str, Any]) -> str:
    return f"ps-{canonical_hash(payload)[:24]}"


def _atom_id(payload: dict[str, Any]) -> str:
    return f"sa-{canonical_hash(payload)[:24]}"


def _pairs(fragment: str, left: str, right: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    balanced: list[tuple[int, int]] = []
    unbalanced: list[tuple[int, int]] = []
    if left == right:
        positions = [match.start() for match in re.finditer(re.escape(left), fragment)]
        for index in range(0, len(positions) - 1, 2):
            balanced.append((positions[index], positions[index + 1] + len(right)))
        if len(positions) % 2:
            unbalanced.append((positions[-1], len(fragment)))
    else:
        stack: list[int] = []
        for index, char in enumerate(fragment):
            if char == left:
                stack.append(index)
            elif char == right and stack:
                balanced.append((stack.pop(), index + 1))
        unbalanced.extend((start, len(fragment)) for start in stack)
    return balanced, unbalanced


def _protected_spans(text: str, block: dict[str, Any], case_id: str, source_hash: str, segmenter: str, policy_hash: str) -> list[dict[str, Any]]:
    block_span = block["span"]
    base, end = block_span["start_char"], block_span["end_char"]
    fragment = text[base:end]
    found: set[tuple[str, int, int, bool, str]] = set()

    def add(kind: str, start: int, stop: int, forbidden: bool, reason: str) -> None:
        if start < stop:
            found.add((kind, start, stop, forbidden, reason))

    inherited = {
        "citation_year": ("citation_year", True, "inherited_sourceblock_citation_year"),
        "citation_candidate": ("reporter_citation", True, "inherited_sourceblock_citation"),
        "list_marker": ("list_marker", True, "inherited_sourceblock_list_marker"),
        "quotation_candidate": ("balanced_quotation", False, "inherited_sourceblock_quotation_context"),
    }
    if block["marker_span"] is not None:
        marker = block["marker_span"]
        add("paragraph_marker", marker["start_char"], marker["end_char"], True, "inherited_sourceblock_marker_span")
    for nested in block["nested_spans"]:
        kind, forbidden, reason = inherited[nested["span_type"]]
        ref = nested["span"]
        add(kind, ref["start_char"], ref["end_char"], forbidden, reason)

    patterns = [
        (ABBREVIATION_RE, "abbreviation", True, "legal_abbreviation"),
        (INITIAL_RE, "initial", True, "party_or_judge_initial"),
        (REPORTER_RE, "reporter_citation", True, "reporter_or_neutral_citation"),
        (CASE_NAME_RE, "case_name", True, "case_name_with_v"),
        (DECIMAL_RE, "decimal_reference", True, "decimal_reference"),
        (SECTION_RE, "section_reference", True, "section_or_paragraph_reference"),
        (LIST_RE, "list_marker", True, "line_start_list_marker"),
        (NEWLINE_RE, "newline_layout", False, "source_layout_context"),
    ]
    for regex, kind, forbidden, reason in patterns:
        for match in regex.finditer(fragment):
            add(kind, base + match.start(), base + match.end(), forbidden, reason)
    for left, right in (('"', '"'), ('\u201c', '\u201d')):
        balanced, unbalanced = _pairs(fragment, left, right)
        for start, stop in balanced:
            add("balanced_quotation", base + start, base + stop, False, "quotation_context_not_boundary_lock")
        for start, stop in unbalanced:
            add("unbalanced_quotation", base + start, base + stop, False, "unbalanced_quotation_context")

    records = []
    for kind, start, stop, forbidden, reason in sorted(found, key=lambda item: (item[1], item[2], item[0], item[4])):
        mode = "boundary_forbidden" if forbidden else "context_only"
        payload = {"identity_contract": "protected-span-v1", "case_id": case_id, "source_hash": source_hash, "parent_block_id": block["block_id"], "parent_block_order": block["order"], "span_type": kind, "protection_mode": mode, "boundary_forbidden": forbidden, "span": {"start_char": start, "end_char": stop}, "producer_version": segmenter, "policy_sha256": policy_hash, "reason_code": reason}
        records.append({"record_type": "ProtectedSpan", "protected_span_id": _protected_id(payload), **{key: value for key, value in payload.items() if key != "identity_contract"}, "span": span(case_id, source_hash, start, stop)})
    return records


def _boundaries(text: str, start: int, end: int, protected: list[dict[str, Any]]) -> list[int]:
    fragment = text[start:end]
    forbidden = [(item["span"]["start_char"], item["span"]["end_char"]) for item in protected if item["boundary_forbidden"]]
    boundaries: list[int] = []
    for match in TERMINAL_RE.finditer(fragment):
        punctuation_end = start + match.end()
        if any(left < punctuation_end <= right for left, right in forbidden):
            continue
        cursor = punctuation_end
        while cursor < end and text[cursor] in '"\'\u201d\u2019)]':
            cursor += 1
        if cursor < end and not text[cursor].isspace():
            continue
        while cursor < end and text[cursor].isspace():
            cursor += 1
        if cursor > start:
            boundaries.append(cursor)
    if not boundaries or boundaries[-1] != end:
        boundaries.append(end)
    return sorted(set(position for position in boundaries if start < position <= end))


def _event(case_id: str, source_hash: str, block_id: str, event_type: str, start: int, end: int) -> dict[str, Any]:
    severity, code, message = EVENT_SPECS[event_type]
    payload = {"event_type": event_type, "severity": severity, "case_id": case_id, "source_hash": source_hash, "parent_block_id": block_id, "span": {"start_char": start, "end_char": end}, "message_code": code, "message": message}
    return {"event_id": f"se-{canonical_hash(payload)[:20]}", **payload, "span": span(case_id, source_hash, start, end)}


def segment_case(text: str, sourceblock_map: dict[str, Any], policy: dict[str, Any], policy_hash: str | None = None) -> dict[str, Any]:
    case_id, source_hash = sourceblock_map["case_id"], sourceblock_map["source_hash"]
    segmenter = policy["segmenter_version"]
    policy_sha = policy_hash or canonical_hash(policy)
    atoms: list[dict[str, Any]] = []
    protected_all: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    atoms_by_block: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for block in sourceblock_map["blocks"]:
        protected = _protected_spans(text, block, case_id, source_hash, segmenter, policy_sha)
        protected_all.extend(protected)
        start, end = block["span"]["start_char"], block["span"]["end_char"]
        atom_start = start
        for order, atom_end in enumerate(_boundaries(text, start, end, protected)):
            refs = [item["protected_span_id"] for item in protected if item["span"]["start_char"] < atom_end and item["span"]["end_char"] > atom_start]
            payload = {"identity_contract": "sentence-atom-id-v1", "case_id": case_id, "source_hash": source_hash, "parent_block_id": block["block_id"], "parent_block_order": block["order"], "order_in_block": order, "global_order": len(atoms), "span": {"start_char": atom_start, "end_char": atom_end}, "segmenter_version": segmenter, "policy_sha256": policy_sha}
            atom = {"record_type": "SentenceAtom", "atom_id": _atom_id(payload), **{key: value for key, value in payload.items() if key != "identity_contract"}, "span": span(case_id, source_hash, atom_start, atom_end), "protected_span_refs": sorted(refs)}
            atoms.append(atom)
            atoms_by_block[block["block_id"]].append(atom)
            atom_start = atom_end
        for protected_span in protected:
            if protected_span["span_type"] == "unbalanced_quotation":
                ref = protected_span["span"]
                events.append(_event(case_id, source_hash, block["block_id"], "unbalanced_quotation", ref["start_char"], ref["end_char"]))

    slice_config = policy["slice_policy"]
    cap = slice_config["max_chars"]
    plans: list[dict[str, Any]] = []
    for block in sourceblock_map["blocks"]:
        start, end = block["span"]["start_char"], block["span"]["end_char"]
        if end - start <= cap:
            continue
        block_atoms = atoms_by_block[block["block_id"]]
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for atom in block_atoms:
            atom_len = atom["span"]["end_char"] - atom["span"]["start_char"]
            if atom_len > cap:
                events.append(_event(case_id, source_hash, block["block_id"], "oversized_atom", atom["span"]["start_char"], atom["span"]["end_char"]))
            if current and atom["span"]["end_char"] - current[0]["span"]["start_char"] > cap:
                groups.append(current)
                current = []
            current.append(atom)
        if current:
            groups.append(current)
        slices = []
        for slice_order, group in enumerate(groups):
            slice_start, slice_end = group[0]["span"]["start_char"], group[-1]["span"]["end_char"]
            payload = {"parent_block_id": block["block_id"], "slice_order": slice_order, "span": {"start_char": slice_start, "end_char": slice_end}, "first_atom_id": group[0]["atom_id"], "last_atom_id": group[-1]["atom_id"], "slice_policy_version": slice_config["policy_version"], "max_chars": cap}
            slices.append({"slice_id": f"sl-{canonical_hash(payload)[:24]}", "slice_order": slice_order, "parent_block_id": block["block_id"], "span": span(case_id, source_hash, slice_start, slice_end), "first_atom_id": group[0]["atom_id"], "last_atom_id": group[-1]["atom_id"]})
            if slice_end - slice_start > cap:
                events.append(_event(case_id, source_hash, block["block_id"], "slice_exceeds_cap", slice_start, slice_end))
        plan_payload = {"parent_block_id": block["block_id"], "parent_block_order": block["order"], "parent_span": {"start_char": start, "end_char": end}, "slice_policy_version": slice_config["policy_version"], "max_chars": cap, "slices": [item["slice_id"] for item in slices]}
        plans.append({"record_type": "DerivedSlicePlan", "plan_id": f"sp-{canonical_hash(plan_payload)[:24]}", "parent_block_id": block["block_id"], "parent_block_order": block["order"], "parent_span": span(case_id, source_hash, start, end), "slice_policy_version": slice_config["policy_version"], "max_chars": cap, "model_specific": False, "slices": slices})

    return {
        "artifact_type": "SentenceAtomMap", "schema_version": policy["schema_version"],
        "case_id": case_id, "source_hash": source_hash,
        "sourceblock_map_cache_key": sourceblock_map["cache_key"],
        "sourceblock_parser_version": sourceblock_map["parser_version"],
        "sourceblock_policy_sha256": sourceblock_map["policy_sha256"],
        "segmenter_version": segmenter, "policy_sha256": policy_sha,
        "cache_key": cache_key_for(case_id, source_hash, sourceblock_map["cache_key"], segmenter, policy_sha),
        "source_char_length": len(text),
        "parent_block_refs": [
            {
                "record_type": "SentenceAtomParentBlockRef",
                "block_id": block["block_id"], "block_order": block["order"],
                "span": block["span"], "content_span": block["content_span"],
                "marker_span": block["marker_span"], "parser_version": block["parser_version"],
                "policy_sha256": block["policy_sha256"],
            }
            for block in sourceblock_map["blocks"]
        ],
        "atoms": atoms, "protected_spans": protected_all,
        "slice_plans": plans, "segmenter_events": sorted(events, key=lambda item: (item["span"]["start_char"], item["event_type"], item["event_id"])),
    }
