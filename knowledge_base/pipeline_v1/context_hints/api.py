"""Read/query API for validated ContextHint maps."""

from __future__ import annotations
from typing import Any


class ContextHintQueryError(ValueError):
    def __init__(self, detail: str, *, code: str, location: str):
        self.code, self.location, self.detail = code, location, detail
        super().__init__(f"[{code}] {location}: {detail}")


class ContextHintAPI:
    def __init__(self, text: str, hint_map: dict[str, Any]):
        self.text, self.hint_map = text, hint_map

    def _query_span(self, case_id, source_hash, start, end):
        if case_id is not None and case_id != self.hint_map["case_id"]: raise ContextHintQueryError("case mismatch", code="identity_mismatch", location="case_id")
        if source_hash is not None and source_hash != self.hint_map["source_hash"]: raise ContextHintQueryError("source hash mismatch", code="identity_mismatch", location="source_hash")
        if (start is None) != (end is None): raise ContextHintQueryError("start/end required together", code="malformed_query", location="span")
        if start is None: return None
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool): raise ContextHintQueryError("integer offsets required", code="malformed_query", location="span")
        if start < 0 or end < start or end > len(self.text): raise ContextHintQueryError("out-of-bounds span", code="offset_violation", location="span")
        return start, end

    def query_hints(self, *, case_id=None, source_hash=None, start_char=None, end_char=None, target_block_id=None, hint_type=None, direction=None, status=None):
        query = self._query_span(case_id, source_hash, start_char, end_char)
        if query is not None and query[0] == query[1]: return []
        result = []
        for item in self.hint_map["hints"]:
            if target_block_id is not None and item["target_block_id"] != target_block_id: continue
            if hint_type is not None and item["hint_type"] != hint_type: continue
            if direction is not None and item["direction"] != direction: continue
            if status is not None and item["status"] != status: continue
            if query is not None:
                a, b = query; ref = item["target_span"]
                if not (ref["start_char"] < b and ref["end_char"] > a): continue
            result.append(item)
        return result

    def estimate_additions(self, **filters):
        hints = self.query_hints(**filters); refs = {(r["start_char"], r["end_char"]) for h in hints for r in h["related_spans"]}
        proposed = sum(r["end_char"] - r["start_char"] for h in hints for r in h["related_spans"])
        merged = []
        for a, b in sorted(refs):
            if not merged or a > merged[-1][1]: merged.append([a, b])
            else: merged[-1][1] = max(merged[-1][1], b)
        unique = sum(b - a for a, b in merged)
        return {"hint_count": len(hints), "unique_related_span_count": len(refs), "unique_related_chars": unique, "proposed_related_chars": proposed, "repeated_proposed_chars": proposed - unique}
