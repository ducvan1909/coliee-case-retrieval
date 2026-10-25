"""Deterministic source addressing and atomic JSON persistence."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

SPAN_LIMIT = 2000
PREVIEW_LIMIT = 120
# The negative lookarounds prevent the regex engine from backtracking and
# interpreting one CRLF pair as two adjacent line breaks.
LINE_BREAK = r"(?:\r\n|\r(?!\n)|(?<!\r)\n)"
ABBREVIATIONS = {
    "art.", "c.", "ca.", "cf.", "ch.", "dr.", "e.g.", "etc.", "fc.",
    "fca.", "i.e.", "j.", "jj.", "mr.", "mrs.", "ms.", "no.", "para.",
    "paras.", "prof.", "s.", "ss.", "v.", "vol.",
}
FRAGMENT_MARKER = "<FRAGMENT_SUPPRESSED>"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_source(path: str | Path) -> tuple[str, str]:
    raw = Path(path).read_bytes()
    return raw.decode("utf-8-sig"), digest(raw)


def save(path: str | Path, value: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(5):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def prepare(kos: str | Path, sources: str | Path, destination: str | Path) -> dict:
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Manifest already exists; use a new path")
    rows = []
    for case in sorted((Path(kos) / "cases").iterdir()):
        if not case.is_dir() or not re.fullmatch(r"\d+", case.name):
            continue
        source = Path(sources) / (case.name + ".txt")
        text, sha = load_source(source)
        rows.append({"case_id": case.name, "source": str(source.resolve()),
                     "source_hash": sha, "chars": len(text)})
    if len(rows) < 25:
        raise ValueError("Need at least 25 source cases")
    ranked = sorted(rows, key=lambda row: (row["chars"], row["case_id"]))
    selected = {"calibration": [], "evaluation": []}
    for index in range(5):
        group = ranked[index * len(rows) // 5:(index + 1) * len(rows) // 5]
        group.sort(key=lambda row: digest(("kb-pilot-v1:" + row["case_id"]).encode()))
        selected["calibration"].append(group[0]["case_id"])
        selected["evaluation"].extend(row["case_id"] for row in group[1:5])
    manifest = {"version": 1,
                "selection": "length-stratified, sha256 kb-pilot-v1, no labels",
                "cohort_bias": "Historical KOS cohort was selected using query/gold information.",
                "cases": rows, "splits": selected}
    save(destination, manifest)
    return manifest


def _trimmed_ranges(text: str) -> list[tuple[int, int]]:
    ranges, start = [], 0
    for match in re.finditer(r"(?:\r?\n)[ \t]*(?:\r?\n)+", text):
        end = match.start()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            ranges.append((start, end))
        start = match.end()
    end = len(text)
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        ranges.append((start, end))
    return ranges


def _split_range(text: str, start: int, end: int, limit: int) -> list[tuple[int, int]]:
    parts, cursor = [], start
    while cursor < end:
        target = min(cursor + limit, end)
        if target < end:
            newline = max(text.rfind("\n", cursor, target), text.rfind("\r", cursor, target))
            if newline > cursor:
                target = newline
        piece_start, piece_end = cursor, target
        while piece_start < piece_end and text[piece_start].isspace():
            piece_start += 1
        while piece_end > piece_start and text[piece_end - 1].isspace():
            piece_end -= 1
        if piece_start < piece_end:
            parts.append((piece_start, piece_end))
        cursor = max(target, cursor + 1)
    return parts


def source_spans(text: str, source_hash: str, limit: int = SPAN_LIMIT) -> list[dict]:
    if limit <= 0:
        raise ValueError("Span limit must be positive")
    result = []
    for start, end in _trimmed_ranges(text):
        for part_start, part_end in _split_range(text, start, end, limit):
            span_id = f"sp-{source_hash[:12]}-{part_start:08d}-{part_end:08d}"
            result.append({"span_id": span_id, "start": part_start, "end": part_end,
                           "text": text[part_start:part_end]})
    return result


def _paragraph_ranges(text: str) -> list[tuple[int, int]]:
    """Find numbered and blank-line paragraphs without changing source bytes."""
    boundaries = {0, len(text)}
    blank = re.compile(rf"{LINE_BREAK}[ \t]*(?:{LINE_BREAK}[ \t]*)+")
    numbered = re.compile(rf"(?m)^[ \t]*\[\d+\][ \t]*(?:{LINE_BREAK})?")
    boundaries.update(match.end() for match in blank.finditer(text))
    boundaries.update(match.start() for match in numbered.finditer(text))
    points = sorted(boundaries)
    ranges = []
    for left, right in zip(points, points[1:]):
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            ranges.append((left, right))
    return ranges


def _looks_like_abbreviation(text: str, start: int, dot: int) -> bool:
    token_start = dot
    while token_start > start and not text[token_start - 1].isspace():
        token_start -= 1
    token = text[token_start:dot + 1].strip("()[]{}\"'").lower()
    if token in ABBREVIATIONS:
        return True
    return bool(re.fullmatch(r"(?:[a-z]\.){1,5}", token))


def _sentence_ranges(text: str, start: int, end: int) -> list[tuple[int, int]]:
    boundaries, cursor = [], start
    index = start
    while index < end:
        char = text[index]
        boundary = False
        if char in ".?!":
            decimal = (char == "." and index > start and index + 1 < end and
                       text[index - 1].isdigit() and text[index + 1].isdigit())
            if not decimal and not _looks_like_abbreviation(text, start, index):
                look = index + 1
                while look < end and text[look] in "\"')]} \t":
                    look += 1
                # A suppression marker often separates a completed sentence
                # from a heading or a new sentence. Peek past one or more such
                # markers for the boundary decision without altering source text.
                while text.startswith(FRAGMENT_MARKER, look):
                    look += len(FRAGMENT_MARKER)
                    while look < end and text[look] in "\"')]} \t":
                        look += 1
                boundary = look >= end or text[look] in "\r\n" or text[look].isupper() or text[look] == "["
        if boundary:
            part_end = index + 1
            while part_end < end and text[part_end] in "\"')]} ":
                part_end += 1
            left, right = cursor, part_end
            while left < right and text[left].isspace():
                left += 1
            while right > left and text[right - 1].isspace():
                right -= 1
            if left < right:
                boundaries.append((left, right))
            cursor = part_end
            index = part_end
            continue
        index += 1
    left, right = cursor, end
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    if left < right:
        boundaries.append((left, right))
    result = []
    for left, right in boundaries:
        result.extend(_split_range(text, left, right, SPAN_LIMIT))
    return result


def source_structure(text: str, source_hash: str) -> tuple[list[dict], list[dict]]:
    """Return paragraph containers and selectable paragraph/sentence units."""
    paragraphs, units = [], []
    bounded_ranges = []
    for paragraph_start, paragraph_end in _paragraph_ranges(text):
        bounded_ranges.extend(_split_range(text, paragraph_start, paragraph_end, SPAN_LIMIT))
    for start, end in bounded_ranges:
        paragraph_id = f"p-{source_hash[:12]}-{start:08d}-{end:08d}"
        sentence_ranges = _sentence_ranges(text, start, end)
        sentence_ids = []
        for sentence_start, sentence_end in sentence_ranges:
            sentence_id = f"s-{source_hash[:12]}-{sentence_start:08d}-{sentence_end:08d}"
            sentence_ids.append(sentence_id)
            units.append({"source_id": sentence_id, "unit_type": "sentence",
                          "parent_id": paragraph_id, "start": sentence_start,
                          "end": sentence_end, "text": text[sentence_start:sentence_end]})
        paragraph = {"source_id": paragraph_id, "unit_type": "paragraph",
                     "parent_id": None, "start": start, "end": end,
                     "text": text[start:end], "sentence_ids": sentence_ids}
        paragraphs.append(paragraph)
        units.append(paragraph)
    units.sort(key=lambda unit: (unit["start"], 0 if unit["unit_type"] == "paragraph" else 1,
                                 unit["end"]))
    return paragraphs, units


def source_handles(units: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Return deterministic short handles and their inverse for one source version."""
    counters = {"paragraph": 0, "sentence": 0}
    stable_to_handle: dict[str, str] = {}
    for unit in sorted(units, key=lambda value: (value["start"],
                                                  value["unit_type"] != "paragraph",
                                                  value["end"])):
        unit_type = unit["unit_type"]
        prefix = "P" if unit_type == "paragraph" else "S"
        handle = f"{prefix}{counters[unit_type]:04d}"
        counters[unit_type] += 1
        stable_to_handle[unit["source_id"]] = handle
    return stable_to_handle, {handle: stable for stable, handle in stable_to_handle.items()}


def structure_windows(paragraphs: list[dict], target_chars: int) -> list[dict]:
    if target_chars <= 0:
        raise ValueError("Window target must be positive")
    windows, cursor = [], 0
    while cursor < len(paragraphs):
        selected, used, index = [], 0, cursor
        while index < len(paragraphs) and (not selected or used + len(paragraphs[index]["text"]) <= target_chars):
            selected.append(paragraphs[index])
            used += len(paragraphs[index]["text"])
            index += 1
        unit_ids = []
        for paragraph in selected:
            unit_ids.append(paragraph["source_id"])
            unit_ids.extend(paragraph["sentence_ids"])
        windows.append({"window_id": len(windows),
                        "paragraph_ids": [paragraph["source_id"] for paragraph in selected],
                        "source_ids": unit_ids, "start": selected[0]["start"],
                        "end": selected[-1]["end"]})
        if index >= len(paragraphs):
            break
        cursor = max(cursor + 1, index - 1)
    return windows


def structure_catalogue(units: list[dict], windows: list[dict]) -> dict:
    by_id = {unit["source_id"]: unit for unit in units}
    compact_windows = []
    for window in windows:
        paragraphs = [by_id[source_id] for source_id in window["paragraph_ids"]]
        middle = paragraphs[len(paragraphs) // 2]
        compact_windows.append({"window_id": window["window_id"],
            "start": window["start"], "end": window["end"],
            "paragraph_count": len(paragraphs),
            "start_preview": paragraphs[0]["text"][:PREVIEW_LIMIT],
            "middle_preview": middle["text"][:PREVIEW_LIMIT],
            "end_preview": paragraphs[-1]["text"][-PREVIEW_LIMIT:]})
    return {"windows": compact_windows,
            "preview_is_not_read": True,
            "note": "These code-cut window previews are navigation only. Paragraph and sentence IDs and full sentence text are supplied only when a window is opened."}


def guided_catalogue(text: str, units: list[dict], windows: list[dict]) -> tuple[dict, dict]:
    """Add source-grounded navigation cues without changing selectable spans."""
    base = structure_catalogue(units, windows)
    headings = []
    for line in re.finditer(r"[^\r\n]+", text):
        raw = line.group()
        stripped = raw.strip()
        if (3 <= len(stripped) <= 160 and
            (re.fullmatch(r"(?:[IVX]{1,8}|[A-Z])\.\s+\S.*", stripped) or
             (len(stripped) <= 120 and stripped.isupper() and
              sum(char.isalpha() for char in stripped) >= 4))):
            start = line.start() + len(raw) - len(raw.lstrip())
            headings.append({"start": start, "end": start + len(stripped),
                             "text": text[start:start + len(stripped)]})
    markers = [{"start": match.start(), "end": match.end(),
                "kind": "fragment_suppressed"}
               for match in re.finditer(re.escape(FRAGMENT_MARKER), text)]
    full_windows = []
    for compact, window in zip(base["windows"], windows):
        start, end = window["start"], window["end"]
        inside_headings = [heading for heading in headings
                           if start <= heading["start"] < end]
        covering = next((heading for heading in reversed(headings)
                         if heading["start"] <= start), None)
        inside_markers = [marker for marker in markers
                          if start <= marker["start"] < end]
        shown = inside_markers[:1] + (inside_markers[-1:]
                                      if len(inside_markers) > 1 else [])
        compact.update({"covering_heading": covering,
            "headings": inside_headings[:3], "heading_count": len(inside_headings),
            "marker_count": len(inside_markers),
            "marker_previews": [{**marker,
                "preview": text[max(0, marker["start"] - 60):
                                min(len(text), marker["end"] + 60)][:PREVIEW_LIMIT]}
                for marker in shown]})
        full_windows.append({"window_id": window["window_id"],
                             "headings": inside_headings,
                             "markers": inside_markers})
    base["note"] += " Markers and headings are navigation hints, not legal evidence."
    return base, {"headings": headings, "markers": markers,
                  "windows": full_windows}


def opened_sources(source_map: dict[str, dict], opened_ids: set[str],
                   stable_to_handle: dict[str, str] | None = None) -> list[dict]:
    handle = stable_to_handle or {source_id: source_id for source_id in source_map}
    result = []
    for unit in source_map.values():
        if unit["unit_type"] != "paragraph" or unit["source_id"] not in opened_ids:
            continue
        sentences = []
        for sentence_id in unit["sentence_ids"]:
            if sentence_id not in opened_ids:
                continue
            sentence = source_map[sentence_id]
            sentences.append({"source_id": handle[sentence_id], "start": sentence["start"],
                              "end": sentence["end"], "text": sentence["text"]})
        result.append({"source_id": handle[unit["source_id"]], "unit_type": "paragraph",
                       "start": unit["start"], "end": unit["end"],
                       "text": unit["text"],
                       "sentences": sentences})
    return result


def compact_opened_sources(source_map: dict[str, dict], opened_ids: set[str],
                           stable_to_handle: dict[str, str]) -> list[dict]:
    """Transmit source text once; sentence handles address slices of the paragraph."""
    result = opened_sources(source_map, opened_ids, stable_to_handle)
    for paragraph in result:
        parent_start = paragraph["start"]
        paragraph["sentences"] = [{"source_id": sentence["source_id"],
            "start": sentence["start"], "end": sentence["end"],
            "start_offset": sentence["start"] - parent_start,
            "end_offset": sentence["end"] - parent_start}
            for sentence in paragraph["sentences"]]
    return result


def alias_item_sources(item: dict, stable_to_handle: dict[str, str]) -> dict:
    """Copy a public item using request handles without exposing stable source IDs."""
    from copy import deepcopy
    result = deepcopy(item)
    for ref in result.get("source_refs", []):
        ref["source_id"] = stable_to_handle[ref["source_id"]]
    treatment = result.get("treatment")
    if treatment:
        for key in ("authority_source_ids", "response_source_ids"):
            treatment[key] = [stable_to_handle[source_id] for source_id in treatment[key]]
    return result


def materialize_sources(source_refs: list[dict], source_map: dict[str, dict],
                        source_hash: str) -> list[dict]:
    return [{"source_id": ref["source_id"], "role": ref["role"],
             "attribution": ref["attribution"],
             "unit_type": source_map[ref["source_id"]]["unit_type"],
             "parent_id": source_map[ref["source_id"]].get("parent_id"),
             "start": source_map[ref["source_id"]]["start"],
             "end": source_map[ref["source_id"]]["end"],
             "text": source_map[ref["source_id"]]["text"], "source_hash": source_hash}
            for ref in source_refs]


def reading_windows(spans: list[dict], target_chars: int) -> list[dict]:
    if target_chars <= 0:
        raise ValueError("Window target must be positive")
    if not spans:
        return []
    windows, cursor = [], 0
    while cursor < len(spans):
        ids, used, index = [], 0, cursor
        while index < len(spans) and (not ids or used + len(spans[index]["text"]) <= target_chars):
            ids.append(spans[index]["span_id"])
            used += len(spans[index]["text"])
            index += 1
        windows.append({"window_id": len(windows), "span_ids": ids,
                        "start": spans[cursor]["start"], "end": spans[index - 1]["end"]})
        if index >= len(spans):
            break
        cursor = max(cursor + 1, index - 1)
    return windows


def catalogue(spans: list[dict], windows: list[dict]) -> dict:
    return {"windows": windows,
            "spans": [{"span_id": span["span_id"], "start": span["start"],
                       "end": span["end"], "preview": span["text"][:PREVIEW_LIMIT]}
                      for span in spans],
            "preview_is_not_read": True}


def opened_payload(span_map: dict[str, dict], opened_span_ids: set[str]) -> list[dict]:
    return [span_map[span_id] for span_id in span_map if span_id in opened_span_ids]


def interval_coverage(spans: list[dict], opened_span_ids: set[str], text_length: int) -> dict:
    intervals = sorted((span["start"], span["end"]) for span in spans
                       if span["span_id"] in opened_span_ids)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    covered = sum(end - start for start, end in merged)
    return {"opened_span_count": len(opened_span_ids), "total_span_count": len(spans),
            "covered_characters": covered, "source_characters": text_length,
            "covered_fraction": covered / text_length if text_length else 0,
            "merged_intervals": merged, "provided_not_proven_understood": True}


def source_interval_coverage(units: list[dict], source_ids: set[str],
                             text_length: int, label: str) -> dict:
    """Measure unique source characters supplied, despite overlapping addresses."""
    selected = [unit for unit in units if unit["source_id"] in source_ids]
    intervals = sorted((unit["start"], unit["end"]) for unit in selected)
    merged: list[list[int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    covered = sum(end - start for start, end in merged)
    return {"coverage_kind": label, "provided_source_count": len(source_ids),
            "total_source_count": len(units), "covered_characters": covered,
            "source_characters": text_length,
            "covered_fraction": covered / text_length if text_length else 0,
            "merged_intervals": merged, "provided_not_proven_understood": True}


def materialize(span_refs: list[dict], span_map: dict[str, dict], source_hash: str) -> list[dict]:
    return [{"span_id": ref["span_id"], "role": ref["role"],
             "start": span_map[ref["span_id"]]["start"],
             "end": span_map[ref["span_id"]]["end"],
             "text": span_map[ref["span_id"]]["text"], "source_hash": source_hash}
            for ref in span_refs]
