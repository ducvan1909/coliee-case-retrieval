"""Marker inventory shared by sample selection and structural validation."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


MARKER_NAMES = (
    "FRAGMENT_SUPPRESSED",
    "REFERENCE_SUPPRESSED",
    "CITATION_SUPPRESSED",
    "DATE_SUPPRESSED",
)
_MARKER_RE = re.compile("|".join(MARKER_NAMES))


@dataclass(frozen=True)
class MarkerOccurrence:
    name: str
    start_char: int
    end_char: int

    @property
    def is_content_marker(self) -> bool:
        return self.name != "DATE_SUPPRESSED"


def find_markers(text: str) -> list[MarkerOccurrence]:
    """Find known suppression tokens even when wrapped in malformed brackets."""
    return [
        MarkerOccurrence(match.group(0), match.start(), match.end())
        for match in _MARKER_RE.finditer(text)
    ]


def marker_counts(text: str) -> dict[str, int]:
    counts = Counter(marker.name for marker in find_markers(text))
    return {name: counts[name] for name in MARKER_NAMES}


def content_marker_count(markers: Iterable[MarkerOccurrence]) -> int:
    return sum(marker.is_content_marker for marker in markers)
