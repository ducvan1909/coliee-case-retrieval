"""Local, deterministic SourceBlock parser.

The parser emits an exact partition of the decoded source.  It intentionally
does not create semantic headings, trees, sentences, regions, or LegalUnits.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


MARKER_RE = re.compile(r"^[ \t]*\[(\d{1,3})\](?=$|[ \t]|\r|\n)")
YEAR_RE = re.compile(r"\[(?:18|19|20)\d{2}\]")
LIST_RE = re.compile(r"(?m)^[ \t]*(?:\([a-zA-Z0-9ivxIVX]+\)|[-*\u2022])(?=[ \t]+)")
FOOTNOTE_RE = re.compile(r"^[ \t]*(?:Footnotes?|Notes?):?[ \t]*$", re.IGNORECASE)
EDITORIAL_RE = re.compile(r"<FRAGMENT_SUPPRESSED>|\[(?:emphasis|sic|translation)\b", re.IGNORECASE)
TABLE_RE = re.compile(r"(?:\t| {3,}\S+ {3,}|^\s*(?:Date|Court|File|Citation|Temp\. Cite):)", re.IGNORECASE)
CITATION_RE = re.compile(
    r"\b(?:\d{4}\s+(?:SCC|FC|FCA|FCT|CanLII)\s+\d+|\d+\s+(?:S\.C\.R\.|F\.T\.R\.|D\.L\.R\.)\s+\d+)"
)
ROMAN_HEADING_RE = re.compile(r"^[ \t]*[IVXLC]+\.[ \t]+\S+", re.IGNORECASE)
FORMAL_HEADING_RE = re.compile(
    r"^[ \t]*(?:INTRODUCTION|BACKGROUND|FACTS|ISSUES?|ANALYSIS|CONCLUSION|ORDER|DECISION|"
    r"LEGAL PROCEEDINGS|STANDARD OF REVIEW|REASONS(?: FOR (?:JUDGMENT|ORDER))?)[ \t]*$",
    re.IGNORECASE,
)

EVENT_CONTRACT_VERSION = "sourceblock-event-v2"
EVENT_SPECS: dict[str, dict[str, str]] = {
    "heading_candidate_review": {
        "severity": "review",
        "message_code": "heading_candidate_requires_semantic_review",
        "message": "Formal heading candidate; semantic role is not asserted.",
    },
    "bracket_year_protected": {
        "severity": "info",
        "message_code": "bracket_year_excluded_from_paragraph_marker",
        "message": "Bracketed year protected from paragraph-marker classification.",
    },
    "unclosed_quotation": {
        "severity": "review",
        "message_code": "odd_straight_quote_count_requires_review",
        "message": "Odd straight-quote count; inspect quotation continuation.",
    },
    "very_long_block": {
        "severity": "review",
        "message_code": "block_exceeds_structural_review_threshold",
        "message": "Block exceeds the configured structural review threshold.",
    },
    "unknown_block": {
        "severity": "error",
        "message_code": "block_classification_failed",
        "message": "Parser could not classify this exact source range.",
    },
}


@dataclass(frozen=True)
class Line:
    start: int
    end: int
    body_end: int
    body: str

    @property
    def blank(self) -> bool:
        return not self.body.strip()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def cache_key_payload(
    case_id: str, source_hash: str, parser_version: str, policy_sha256: str
) -> dict[str, str]:
    """Canonical cache identity payload (field names and values are contract data)."""
    return {
        "case_id": case_id,
        "source_hash": source_hash,
        "parser_version": parser_version,
        "policy_sha256": policy_sha256,
    }


def cache_key_for(case_id: str, source_hash: str, parser_version: str, policy_sha256: str) -> str:
    return _canonical_hash(cache_key_payload(case_id, source_hash, parser_version, policy_sha256))


def block_id_payload(
    *,
    case_id: str,
    source_hash: str,
    parser_version: str,
    policy_sha256: str,
    order: int,
    start_char: int,
    end_char: int,
    block_type: str,
) -> dict[str, Any]:
    """Canonical SourceBlock identity payload used by producer and validator."""
    return {
        "identity_contract": "sourceblock-id-v1",
        "case_id": case_id,
        "source_hash": source_hash,
        "parser_version": parser_version,
        "policy_sha256": policy_sha256,
        "order": order,
        "span": {"start_char": start_char, "end_char": end_char},
        "block_type": block_type,
    }


def block_id_for(**identity: Any) -> str:
    return f"sb-{_canonical_hash(block_id_payload(**identity))[:24]}"


def event_id_for(
    *,
    case_id: str,
    source_hash: str,
    parser_version: str,
    policy_sha256: str,
    block_id: str,
    block_order: int,
    event_type: str,
    severity: str,
    message_code: str,
    message: str,
    start_char: int,
    end_char: int,
) -> str:
    payload = {
        "identity_contract": EVENT_CONTRACT_VERSION,
        "case_id": case_id,
        "source_hash": source_hash,
        "parser_version": parser_version,
        "policy_sha256": policy_sha256,
        "block_id": block_id,
        "block_order": block_order,
        "event_type": event_type,
        "severity": severity,
        "message_code": message_code,
        "message": message,
        "span": {"start_char": start_char, "end_char": end_char},
    }
    return f"evt-{_canonical_hash(payload)[:20]}"


def _lines(text: str) -> list[Line]:
    result: list[Line] = []
    for match in re.finditer(r".*?(?:\r\n|\r|\n|$)", text):
        raw = match.group(0)
        if not raw:
            continue
        newline_len = 2 if raw.endswith("\r\n") else (1 if raw.endswith(("\r", "\n")) else 0)
        result.append(Line(match.start(), match.end(), match.end() - newline_len, raw[:-newline_len] if newline_len else raw))
    return result


def _marker(line: Line, policy: dict[str, Any]) -> re.Match[str] | None:
    match = MARKER_RE.match(line.body)
    if not match:
        return None
    number = int(match.group(1))
    low, high = policy["paragraph_marker"]["bracket_year_range_excluded"]
    return None if low <= number <= high else match


def _heading_candidate(body: str, policy: dict[str, Any]) -> bool:
    stripped = body.strip()
    config = policy["heading_candidate"]
    if not stripped or len(stripped) > config["max_chars"] or len(stripped.split()) > config["max_words"]:
        return False
    if config["terminal_sentence_punctuation_rejected"] and stripped.endswith((".", "?", "!", ";")):
        return False
    if FORMAL_HEADING_RE.fullmatch(stripped) or ROMAN_HEADING_RE.match(stripped):
        return True
    letters = [char for char in stripped if char.isalpha()]
    if len(letters) < 4:
        return False
    upper_ratio = sum(char.isupper() for char in letters) / len(letters)
    return upper_ratio >= config["uppercase_ratio"]


def _standalone_type(body: str, policy: dict[str, Any]) -> str | None:
    stripped = body.strip()
    if _heading_candidate(body, policy):
        return "heading_candidate"
    if FOOTNOTE_RE.fullmatch(body):
        return "footnote"
    if LIST_RE.match(body):
        return "list_item"
    if stripped.startswith(('"', "\u201c", "'")) and stripped.endswith(('"', "\u201d", "'")):
        return "quotation_block"
    if TABLE_RE.search(body):
        return "table_or_form"
    if EDITORIAL_RE.search(body):
        return "editorial"
    return None


def _span(case_id: str, source_hash: str, start: int, end: int) -> dict[str, Any]:
    return {"case_id": case_id, "source_hash": source_hash, "start_char": start, "end_char": end}


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _nested_spans(
    text: str, case_id: str, source_hash: str, start: int, end: int, parser_version: str
) -> list[dict[str, Any]]:
    fragment = text[start:end]
    found: list[tuple[int, int, str]] = []
    for match in YEAR_RE.finditer(fragment):
        found.append((start + match.start(), start + match.end(), "citation_year"))
    for match in CITATION_RE.finditer(fragment):
        found.append((start + match.start(), start + match.end(), "citation_candidate"))
    for match in LIST_RE.finditer(fragment):
        found.append((start + match.start(), start + match.end(), "list_marker"))
    for quote_re in (re.compile(r'"[^"\r\n]+"'), re.compile(r"\u201c[^\u201d\r\n]+\u201d")):
        for match in quote_re.finditer(fragment):
            found.append((start + match.start(), start + match.end(), "quotation_candidate"))
    found = sorted(set(found), key=lambda item: (item[0], item[1], item[2]))
    return [
        {
            "span_type": span_type,
            "span": _span(case_id, source_hash, nested_start, nested_end),
            "status": "observed_candidate",
            "producer_version": parser_version,
        }
        for nested_start, nested_end, span_type in found
    ]


def parser_event_for(
    case_id: str,
    source_hash: str,
    parser_version: str,
    policy_sha256: str,
    block_id: str,
    block_order: int,
    event_type: str,
    start: int,
    end: int,
) -> dict[str, Any]:
    spec = EVENT_SPECS[event_type]
    return {
        "event_contract_version": EVENT_CONTRACT_VERSION,
        "event_id": event_id_for(
            case_id=case_id,
            source_hash=source_hash,
            parser_version=parser_version,
            policy_sha256=policy_sha256,
            block_id=block_id,
            block_order=block_order,
            event_type=event_type,
            severity=spec["severity"],
            message_code=spec["message_code"],
            message=spec["message"],
            start_char=start,
            end_char=end,
        ),
        "case_id": case_id,
        "source_hash": source_hash,
        "parser_version": parser_version,
        "policy_sha256": policy_sha256,
        "block_id": block_id,
        "block_order": block_order,
        "event_type": event_type,
        "severity": spec["severity"],
        "message_code": spec["message_code"],
        "span": _span(case_id, source_hash, start, end),
        "message": spec["message"],
    }


def _draft_ranges(text: str, policy: dict[str, Any]) -> Iterable[tuple[int, int, str, tuple[int, int] | None]]:
    lines = _lines(text)
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.blank:
            start = line.start
            index += 1
            while index < len(lines) and lines[index].blank:
                index += 1
            yield start, lines[index - 1].end, "whitespace", None
            continue

        marker = _marker(line, policy)
        if marker:
            start = line.start
            marker_span = (line.start + marker.start(), line.start + marker.end())
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if _marker(candidate, policy) or (not candidate.blank and _heading_candidate(candidate.body, policy)):
                    break
                index += 1
            end = lines[index - 1].end
            yield start, end, "numbered_paragraph", marker_span
            continue

        standalone = _standalone_type(line.body, policy)
        if standalone:
            yield line.start, line.end, standalone, None
            index += 1
            continue

        start = line.start
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if candidate.blank or _marker(candidate, policy) or _standalone_type(candidate.body, policy):
                break
            index += 1
        end = lines[index - 1].end
        body = text[start:end].strip()
        block_type = "independent_line" if "\n" not in body and "\r" not in body and len(body) <= 120 else "unnumbered_paragraph"
        yield start, end, block_type, None


def parse_source(
    *,
    text: str,
    case_id: str,
    source_hash: str,
    policy: dict[str, Any],
    policy_sha256: str | None = None,
    parser_version: str | None = None,
) -> dict[str, Any]:
    """Parse one decoded immutable source into an exact ordered leaf partition."""
    policy_hash = policy_sha256 or _canonical_hash(policy)
    version = parser_version or policy["parser_version"]
    drafts = list(_draft_ranges(text, policy))

    # Separator whitespace belongs to the previous block.  Leading whitespace
    # remains explicit because there is no prior block to own it.
    merged: list[tuple[int, int, str, tuple[int, int] | None]] = []
    for draft in drafts:
        if draft[2] == "whitespace" and merged:
            previous = merged[-1]
            merged[-1] = (previous[0], draft[1], previous[2], previous[3])
        else:
            merged.append(draft)

    blocks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for order, (start, end, block_type, marker_bounds) in enumerate(merged):
        content_start, content_end = _trim_span(text, start, end)
        if marker_bounds:
            content_start = marker_bounds[1]
            while content_start < end and text[content_start].isspace():
                content_start += 1
            content_end = _trim_span(text, content_start, end)[1]
        heading = block_type == "heading_candidate"
        block = {
            "record_type": "SourceBlock",
            "block_id": block_id_for(
                case_id=case_id,
                source_hash=source_hash,
                parser_version=version,
                policy_sha256=policy_hash,
                order=order,
                start_char=start,
                end_char=end,
                block_type=block_type,
            ),
            "case_id": case_id,
            "source_hash": source_hash,
            "parser_version": version,
            "policy_sha256": policy_hash,
            "order": order,
            "block_type": block_type,
            "span": _span(case_id, source_hash, start, end),
            "content_span": _span(case_id, source_hash, content_start, content_end),
            "marker_span": _span(case_id, source_hash, *marker_bounds) if marker_bounds else None,
            "heading_candidate": heading,
            "parser_confidence": 0.75 if heading else (0.98 if block_type == "numbered_paragraph" else 0.85),
            "nested_spans": _nested_spans(text, case_id, source_hash, start, end, version),
        }
        blocks.append(block)
        if heading:
            events.append(parser_event_for(case_id, source_hash, version, policy_hash, block["block_id"], order, "heading_candidate_review", content_start, content_end))
        if block_type == "unknown":
            events.append(parser_event_for(case_id, source_hash, version, policy_hash, block["block_id"], order, "unknown_block", start, end))
        if end - start > policy["long_block_review_chars"]:
            events.append(parser_event_for(case_id, source_hash, version, policy_hash, block["block_id"], order, "very_long_block", start, end))
        fragment = text[start:end]
        for match in YEAR_RE.finditer(fragment):
            events.append(parser_event_for(case_id, source_hash, version, policy_hash, block["block_id"], order, "bracket_year_protected", start + match.start(), start + match.end()))
        if fragment.count('"') % 2:
            events.append(parser_event_for(case_id, source_hash, version, policy_hash, block["block_id"], order, "unclosed_quotation", start, end))

    return {
        "artifact_type": "SourceBlockMap",
        "schema_version": policy["schema_version"],
        "case_id": case_id,
        "source_hash": source_hash,
        "parser_version": version,
        "policy_sha256": policy_hash,
        "cache_key": cache_key_for(case_id, source_hash, version, policy_hash),
        "source_char_length": len(text),
        "blocks": blocks,
        "parser_events": sorted(events, key=lambda item: (item["span"]["start_char"], item["event_type"], item["event_id"])),
        "relations": [],
    }
