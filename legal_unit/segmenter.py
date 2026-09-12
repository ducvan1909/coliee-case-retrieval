"""Contextual structural boundaries for provisional LegalUnit candidates."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


SEGMENTER_VERSION = "structural-boundaries-v5.1"
_PARAGRAPH_NUMBER_RE = re.compile(r"^\[\d+\]$")
_SECTION_LABEL_RE = re.compile(r"^\((?P<label>[A-Za-z])\)$")
_HEADING_NUMBER_RE = re.compile(r"^(?:[IVXLC]+|\d+(?:\.\d+)*)\.$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^(?P<marker>[-*•])\s+\S")
_ENUMERATED_RE = re.compile(
    r"^(?P<marker>\((?:[A-Za-z]|\d+|[IVXLC]+)\)|(?:[A-Za-z]|\d+|[IVXLC]+)[.)])\s+\S",
    re.IGNORECASE,
)
_EDITOR_RE = re.compile(r"^Editor\s*:", re.IGNORECASE)
_FOOTNOTE_RE = re.compile(r"^Footnotes?$", re.IGNORECASE)
_END_DOCUMENT_RE = re.compile(r"^\[End of document\]$", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
_TERMINAL_RE = re.compile(r"[.!?][\"'”’)]*$")
_LEADING_CONTINUATION_RE = re.compile(r"^(?:[,.;:!?\]\)}\"”’]|\([a-z])")


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    content_end: int
    text: str

    @property
    def stripped(self) -> str:
        return self.text.strip()


@dataclass(frozen=True)
class LineSignal:
    line: int
    start_char: int
    end_char: int
    kind: str
    indent: int
    ends_sentence: bool
    begins_continuation: bool
    heading_shape: str | None
    list_family: str | None
    parenthesis_balance_after: int
    straight_quote_open_after: bool | None
    curly_quote_balance_after: int


@dataclass(frozen=True)
class BoundaryDecision:
    case_id: str
    offset: int
    left_line: int
    right_line: int
    left_signal: dict[str, object]
    right_signal: dict[str, object]
    block: dict[str, object] | None
    proposals: list[str]
    decision: str
    reason: str

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


def _lines(text: str) -> list[_Line]:
    result: list[_Line] = []
    position = 0
    for value in text.splitlines(keepends=True):
        end = position + len(value)
        result.append(_Line(position, end, position + len(value.rstrip("\r\n")), value))
        position = end
    if position < len(text):
        result.append(_Line(position, len(text), len(text), text[position:]))
    return result


def _list_family(marker: str) -> str:
    core = marker.strip("().")
    if marker in {"-", "*", "•"}:
        return "bullet"
    if core.isdigit():
        return "numeric"
    if len(core) == 1 and core.upper() in set("IVXLC"):
        return "roman_or_alpha"
    return "alpha"


def _local_kind(line: _Line) -> tuple[str, str | None]:
    stripped = line.stripped
    if not stripped:
        return "blank", None
    if _PARAGRAPH_NUMBER_RE.fullmatch(stripped):
        return "paragraph_number", None
    if _EDITOR_RE.match(stripped):
        return "editor", None
    if _FOOTNOTE_RE.fullmatch(stripped):
        return "footnote_heading", None
    if _END_DOCUMENT_RE.fullmatch(stripped):
        return "end_document", None
    if _HEADING_NUMBER_RE.fullmatch(stripped):
        return "heading_number", None
    section_label = _SECTION_LABEL_RE.fullmatch(stripped)
    if section_label:
        return "section_label", "alpha"
    bullet = _BULLET_RE.match(stripped)
    if bullet:
        return "list_candidate", _list_family(bullet.group("marker"))
    enumerated = _ENUMERATED_RE.match(stripped)
    if enumerated:
        return "list_candidate", _list_family(enumerated.group("marker"))
    if stripped.startswith(">"):
        return "blockquote", None
    return "text", None


def _heading_shape(stripped: str) -> str | None:
    if _HEADING_NUMBER_RE.fullmatch(stripped):
        return "number"
    words = _WORD_RE.findall(stripped)
    if not words or len(stripped) > 160 or len(words) > 18 or ":" in stripped or stripped.endswith((".", ",", ";")):
        return None
    if len(words) > 1 and all(word.upper() == word for word in words):
        return "uppercase"
    title_ratio = sum(word[:1].isupper() for word in words) / len(words)
    if stripped[:1].isupper() and title_ratio >= 0.5:
        return "title"
    if stripped.endswith("?"):
        return "question"
    return None


def detect_line_signals(text: str) -> tuple[list[_Line], list[LineSignal]]:
    """Detect local signals without deciding any LegalUnit boundary."""
    lines = _lines(text)
    signals: list[LineSignal] = []
    parentheses = 0
    straight_quote_open: bool | None = False
    curly_quotes = 0
    for index, line in enumerate(lines):
        stripped = line.stripped
        kind, family = _local_kind(line)
        if kind == "paragraph_number":
            parentheses = 0
            straight_quote_open = False
            curly_quotes = 0
        parentheses += stripped.count("(") - stripped.count(")")
        double_count = stripped.count('"')
        if straight_quote_open is not None:
            if double_count % 2:
                straight_quote_open = not straight_quote_open
            if double_count and stripped.count('""'):
                straight_quote_open = None
        curly_quotes += stripped.count("“") - stripped.count("”")
        indent = len(line.text) - len(line.text.lstrip(" \t"))
        punctuation_only = bool(stripped) and not any(character.isalnum() for character in stripped)
        signals.append(
            LineSignal(
                line=index,
                start_char=line.start,
                end_char=line.content_end,
                kind=kind,
                indent=indent,
                ends_sentence=bool(_TERMINAL_RE.search(stripped)) and not punctuation_only,
                begins_continuation=bool(_LEADING_CONTINUATION_RE.match(stripped)) or bool(stripped[:1].islower()),
                heading_shape=_heading_shape(stripped),
                list_family=family,
                parenthesis_balance_after=parentheses,
                straight_quote_open_after=straight_quote_open,
                curly_quote_balance_after=curly_quotes,
            )
        )
    return lines, signals


def _previous_nonblank(signals: list[LineSignal], index: int) -> int | None:
    for candidate in range(index - 1, -1, -1):
        if signals[candidate].kind != "blank":
            return candidate
    return None


def _next_nonblank(signals: list[LineSignal], index: int) -> int | None:
    for candidate in range(index + 1, len(signals)):
        if signals[candidate].kind != "blank":
            return candidate
    return None


def _confirmed_lists(lines: list[_Line], signals: list[LineSignal]) -> set[int]:
    confirmed: set[int] = set()
    for index, signal in enumerate(signals):
        if signal.kind != "list_candidate":
            continue
        if signal.list_family == "bullet":
            confirmed.add(index)
            continue
        previous = _previous_nonblank(signals, index)
        if previous is not None and lines[previous].stripped.endswith(":"):
            confirmed.add(index)
        for direction in (-1, 1):
            checked = 0
            cursor = index + direction
            while 0 <= cursor < len(signals) and checked < 6:
                other = signals[cursor]
                if other.kind != "blank":
                    checked += 1
                    if other.kind in {"paragraph_number", "editor", "footnote_heading", "end_document"}:
                        break
                    if other.kind == "list_candidate" and other.list_family == signal.list_family:
                        confirmed.update((index, cursor))
                        break
                cursor += direction
    return confirmed


def _can_start_heading(lines: list[_Line], signals: list[LineSignal], index: int) -> bool:
    signal = signals[index]
    if signal.heading_shape is None or signal.begins_continuation or signal.kind == "list_candidate":
        return False
    following = _next_nonblank(signals, index)
    if following is not None and signals[following].begins_continuation:
        return False
    if signal.heading_shape == "number":
        return True
    if index == 0 or signals[index - 1].kind == "blank":
        return True
    previous = _previous_nonblank(signals, index)
    if previous is None:
        return True
    return _ends_sentence_before(lines, signals, index)


def _ends_sentence_before(lines: list[_Line], signals: list[LineSignal], index: int) -> bool:
    """Recognize a terminal split over wrapped text and a punctuation-only line.

    This deliberately examines only the immediately adjacent textual tail.  A
    short lower-case connector followed by a wrapped full stop (for example a
    case-name ``v`` line) is treated as continuation rather than a terminator.
    """
    previous = index - 1
    if previous < 0 or signals[previous].kind == "blank":
        return False
    if signals[previous].ends_sentence:
        return True
    punctuation = lines[previous].stripped
    if not punctuation or any(character.isalnum() for character in punctuation):
        return False
    if not _TERMINAL_RE.search(punctuation):
        return False
    content_index = previous - 1
    if content_index < 0 or signals[content_index].kind in {
        "blank",
        "paragraph_number",
        "editor",
        "footnote_heading",
        "end_document",
    }:
        return False
    content = lines[content_index].stripped
    words = _WORD_RE.findall(content)
    if len(words) == 1 and content[:1].islower() and len(words[0]) <= 3:
        return False
    return bool(words)


def _section_heading_candidates(
    lines: list[_Line], signals: list[LineSignal]
) -> list[tuple[int, int, int, str, int]]:
    """Find provisional ``(a) -> heading -> [n]`` blocks.

    The candidates are not accepted here.  A later pass requires an ordered
    run of same-indent alphabetic labels, so an isolated parenthesized label
    cannot become a heading boundary by itself.
    """
    candidates: list[tuple[int, int, int, str, int]] = []
    for marker, signal in enumerate(signals):
        if signal.kind != "paragraph_number":
            continue
        cursor = marker - 1
        examined = 0
        while cursor >= 0 and examined < 8:
            current = signals[cursor]
            if current.kind in {"blank", "paragraph_number", "editor", "footnote_heading", "end_document"}:
                break
            examined += 1
            if current.kind == "section_label":
                title_lines = range(cursor + 1, marker)
                if cursor + 1 < marker and all(signals[item].heading_shape is not None for item in title_lines):
                    match = _SECTION_LABEL_RE.fullmatch(lines[cursor].stripped)
                    if match:
                        candidates.append(
                            (cursor, marker - 1, marker, match.group("label").lower(), current.indent)
                        )
                break
            cursor -= 1
    return candidates


def _confirmed_section_heading_blocks(
    lines: list[_Line], signals: list[LineSignal]
) -> list[tuple[int, int, int]]:
    candidates = _section_heading_candidates(lines, signals)
    confirmed: set[int] = set()
    run: list[int] = []

    def finish_run() -> None:
        if len(run) >= 3:
            confirmed.update(run)

    for candidate_index, candidate in enumerate(candidates):
        if not run:
            run.append(candidate_index)
            continue
        previous = candidates[run[-1]]
        sequential = ord(candidate[3]) == ord(previous[3]) + 1
        same_level = candidate[4] == previous[4]
        if sequential and same_level:
            run.append(candidate_index)
        else:
            finish_run()
            run = [candidate_index]
    finish_run()
    return [candidates[index][:3] for index in sorted(confirmed)]


def _heading_blocks(lines: list[_Line], signals: list[LineSignal]) -> list[tuple[int, int, int]]:
    """Return (heading start, heading end, following paragraph-marker line)."""
    blocks: list[tuple[int, int, int]] = []
    for marker, signal in enumerate(signals):
        if signal.kind != "paragraph_number":
            continue
        contiguous: list[int] = []
        cursor = marker - 1
        while cursor >= 0 and len(contiguous) < 8:
            if signals[cursor].kind == "blank":
                break
            if signals[cursor].kind in {"paragraph_number", "editor", "footnote_heading", "end_document"}:
                break
            contiguous.append(cursor)
            cursor -= 1
        contiguous.reverse()
        anchors = [index for index in contiguous if _can_start_heading(lines, signals, index)]
        if not anchors:
            continue
        start = anchors[0]
        # A heading block may contain continuation lines with weak typography,
        # but it cannot include a completed prose sentence before its anchor.
        if all(signals[index].heading_shape is not None or index > start for index in range(start, marker)):
            blocks.append((start, marker - 1, marker))
    labelled_blocks = _confirmed_section_heading_blocks(lines, signals)
    by_marker = {marker: (start, end, marker) for start, end, marker in blocks}
    # A confirmed label is the start of the heading block, so it takes
    # precedence over a title-only anchor for the same following paragraph.
    by_marker.update({marker: (start, end, marker) for start, end, marker in labelled_blocks})
    return [by_marker[marker] for marker in sorted(by_marker)]


def _decision_signal(signal: LineSignal) -> dict[str, object]:
    value = asdict(signal)
    value.pop("line")
    return value


def decide_boundaries(case_id: str, text: str) -> tuple[list[_Line], list[LineSignal], list[BoundaryDecision]]:
    """Propose and centrally decide every physical line gap."""
    lines, signals = detect_line_signals(text)
    lists = _confirmed_lists(lines, signals)
    heading_blocks = _heading_blocks(lines, signals)
    heading_by_line = {line: (start, end, marker) for start, end, marker in heading_blocks for line in range(start, marker + 1)}
    heading_starts = {start for start, _, _ in heading_blocks}
    decisions: list[BoundaryDecision] = []
    for right in range(1, len(lines)):
        left = right - 1
        proposals: list[str] = []
        block_value: dict[str, object] | None = None
        if signals[left].kind == "blank" or signals[right].kind == "blank":
            proposals.append("blank_line")
        if signals[right].kind == "paragraph_number":
            proposals.append("standalone_paragraph_marker")
        if signals[right].kind in {"editor", "footnote_heading", "end_document"}:
            proposals.append(f"metadata:{signals[right].kind}")
        if right in lists:
            proposals.append(f"confirmed_list:{signals[right].list_family}")
        if signals[right].kind == "blockquote" and signals[left].kind != "blockquote":
            proposals.append("blockquote_start")
        if signals[left].kind == "blockquote" and signals[right].kind != "blockquote":
            proposals.append("blockquote_end")
        if right in heading_starts:
            proposals.append("confirmed_heading_block")
        if right in heading_by_line:
            start, end, marker = heading_by_line[right]
            block_value = {"type": "heading", "start_line": start, "end_line": end, "paragraph_marker_line": marker}

        continuation = signals[right].begins_continuation or (
            signals[left].kind not in {"blank", "paragraph_number"} and not signals[left].ends_sentence
        )
        ambiguous_heading = (
            signals[right].heading_shape is not None
            and right not in heading_by_line
            and _next_nonblank(signals, right) is not None
            and signals[_next_nonblank(signals, right)].kind == "paragraph_number"  # type: ignore[index]
        )

        if signals[right].kind == "blank":
            decision, reason = "keep", "blank whitespace is excluded from spans"
        elif signals[left].kind == "blank":
            decision, reason = "split", "content resumes after blank line"
        elif signals[right].kind == "paragraph_number":
            if right in heading_by_line:
                decision, reason = "keep", "paragraph marker follows a confirmed heading block"
            else:
                decision, reason = "split", "standalone paragraph marker is authoritative"
        elif right in heading_starts:
            decision, reason = "split", "start of confirmed multi-line heading block"
        elif right in heading_by_line:
            decision, reason = "keep", "inside confirmed heading block"
        elif signals[right].kind in {"editor", "footnote_heading", "end_document"}:
            decision, reason = "split", "metadata boundary"
        elif right in lists:
            decision, reason = "split", "confirmed list item"
        elif "blockquote_start" in proposals or "blockquote_end" in proposals:
            decision, reason = "split", "blockquote structural boundary"
        elif ambiguous_heading or (signals[right].heading_shape is not None and continuation):
            decision, reason = "defer", "heading-like signal conflicts with grammatical continuation"
        else:
            decision, reason = "keep", "no confirmed structural boundary"
        decisions.append(
            BoundaryDecision(
                case_id=case_id,
                offset=lines[right].start,
                left_line=left,
                right_line=right,
                left_signal=_decision_signal(signals[left]),
                right_signal=_decision_signal(signals[right]),
                block=block_value,
                proposals=proposals,
                decision=decision,
                reason=reason,
            )
        )
    return lines, signals, decisions


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _build_spans(
    text: str, lines: list[_Line], signals: list[LineSignal], decisions: list[BoundaryDecision]
) -> list[tuple[int, int, list[str], list[str]]]:
    by_right_line = {decision.right_line: decision for decision in decisions}
    spans: list[tuple[int, int, list[str], list[str]]] = []
    start: int | None = None
    end: int | None = None
    basis: list[str] = []
    review: list[str] = []

    def flush() -> None:
        nonlocal start, end, basis, review
        if start is not None and end is not None:
            trimmed_start, trimmed_end = _trim_span(text, start, end)
            if trimmed_start < trimmed_end:
                spans.append((trimmed_start, trimmed_end, sorted(set(basis)), sorted(set(review))))
        start = end = None
        basis, review = [], []

    for index, (line, signal) in enumerate(zip(lines, signals)):
        if signal.kind == "blank":
            flush()
            continue
        boundary = by_right_line.get(index)
        if start is not None and boundary is not None and boundary.decision == "split":
            flush()
        if start is None:
            start = line.start
            if boundary is None:
                basis.append("document_start")
            else:
                basis.extend(boundary.proposals or [boundary.reason])
        end = line.end
        if boundary is not None and boundary.decision == "defer":
            review.append(f"deferred_boundary:{boundary.offset}")
        if signal.straight_quote_open_after is None or signal.curly_quote_balance_after < 0:
            review.append("quotation_state_uncertain")
    flush()
    return spans


def analyze_case(case_id: str, text: str, source_ref: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return provisional candidates plus auditable decisions for all line gaps."""
    lines, signals, decisions = decide_boundaries(case_id, text)
    candidates: list[dict[str, object]] = []
    for ordinal, (start, end, basis, review) in enumerate(_build_spans(text, lines, signals, decisions), start=1):
        candidates.append(
            {
                "id": f"{case_id}:lu:{ordinal}",
                "case_id": case_id,
                "text": text[start:end],
                "source_span": {"source_ref": source_ref, "start_char": start, "end_char": end},
                "order": ordinal - 1,
                "functions": ["unknown"],
                "attributed_to": {"kind": "unknown", "party_role": None},
                "reporting_voice": None,
                "language": "unknown",
                "confidence": 0.0,
                "unknowns": ["semantic function, speaker, language, and boundary adequacy require later review"] + review,
                "status": "code_provisional",
                "boundary_basis": basis,
                "segmenter_version": SEGMENTER_VERSION,
            }
        )
    return candidates, [decision.public_dict() for decision in decisions]


def segment_case(case_id: str, text: str, source_ref: str) -> list[dict[str, object]]:
    """Preserve the existing public API for provisional LegalUnit generation."""
    candidates, _ = analyze_case(case_id, text, source_ref)
    return candidates


def structural_spans(text: str) -> list[tuple[int, int, list[str], list[str]]]:
    """Compatibility API returning spans without case-specific decision output."""
    lines, signals, decisions = decide_boundaries("unknown", text)
    return _build_spans(text, lines, signals, decisions)


def _kind(value: _Line) -> str:
    """Compatibility helper for local line syntax."""
    return _local_kind(value)[0]
