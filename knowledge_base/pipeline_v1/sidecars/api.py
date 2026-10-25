"""Read/query API for validated sidecar artifacts."""

from __future__ import annotations

from typing import Any

from ..sentence_atoms.segmenter import canonical_hash, span


class SidecarQueryError(ValueError):
    """Controlled API query-contract error."""

    def __init__(self, detail: str, *, code: str, location: str):
        self.code, self.location, self.detail = code, location, detail
        super().__init__(f"[{code}] {location}: {detail}")


class SidecarAPI:
    def __init__(self, text: str, sourceblocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any]):
        self.text, self.sourceblocks, self.atoms, self.sidecars = text, sourceblocks, atoms, sidecars
        self._annotations = {item["annotation_id"]: item for item in sidecars["annotations"]}
        self._blocks = {item["block_id"]: item for item in sourceblocks["blocks"]}

    def _span_query(self, *, case_id: str | None, source_hash: str | None, start_char: int | None, end_char: int | None) -> tuple[int, int] | None:
        if case_id is not None and case_id != self.sidecars["case_id"]:
            raise SidecarQueryError("case_id does not match loaded sidecar", code="identity_mismatch", location="case_id")
        if source_hash is not None and source_hash != self.sidecars["source_hash"]:
            raise SidecarQueryError("source_hash does not match loaded sidecar", code="identity_mismatch", location="source_hash")
        if (start_char is None) != (end_char is None):
            raise SidecarQueryError("start_char and end_char must be supplied together", code="malformed_query", location="span")
        if start_char is None:
            return None
        if not isinstance(start_char, int) or isinstance(start_char, bool) or not isinstance(end_char, int) or isinstance(end_char, bool):
            raise SidecarQueryError("span offsets must be integers", code="malformed_query", location="span")
        if start_char < 0 or end_char < start_char or end_char > len(self.text):
            raise SidecarQueryError(f"span must satisfy 0 <= start <= end <= {len(self.text)}", code="offset_violation", location="span")
        return start_char, end_char

    @staticmethod
    def _overlaps(ref: dict[str, Any], query: tuple[int, int]) -> bool:
        start, end = query
        return start < end and ref["start_char"] < end and ref["end_char"] > start

    def query_annotations(self, *, case_id: str | None = None, source_hash: str | None = None, start_char: int | None = None, end_char: int | None = None, block_id: str | None = None, atom_id: str | None = None, worker_type: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        query = self._span_query(case_id=case_id, source_hash=source_hash, start_char=start_char, end_char=end_char)
        if query is not None and query[0] == query[1]:
            return []
        result = []
        for item in self.sidecars["annotations"]:
            ref = item["span"]
            if block_id is not None and item["block_id"] != block_id: continue
            if atom_id is not None and atom_id not in item["atom_refs"]: continue
            if worker_type is not None and item["worker_type"] != worker_type: continue
            if status is not None and item["status"] != status: continue
            if query is not None and not self._overlaps(ref, query): continue
            result.append(item)
        return result

    def open_annotation(self, annotation_id: str) -> dict[str, Any]:
        item = self._annotations[annotation_id]
        ref = item["span"]
        return {"annotation": item, "exact_source": self.text[ref["start_char"]:ref["end_char"]]}

    def query_relations(self, *, case_id: str | None = None, source_hash: str | None = None, start_char: int | None = None, end_char: int | None = None, block_id: str | None = None, relation_type: str | None = None, direction: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        query = self._span_query(case_id=case_id, source_hash=source_hash, start_char=start_char, end_char=end_char)
        if query is not None and query[0] == query[1]:
            return []
        output = []
        for item in self.sidecars["relations"]:
            actual_direction = "outgoing" if block_id is None or item["source_ref"] == block_id else ("incoming" if item["target_ref"] == block_id else None)
            if block_id is not None and actual_direction is None: continue
            if relation_type is not None and item["relation_type"] != relation_type: continue
            if direction is not None and actual_direction != direction: continue
            if status is not None and item["status"] != status: continue
            if query is not None and not any(self._overlaps(ref, query) for ref in item["evidence_spans"]): continue
            view = dict(item); view["direction"] = actual_direction or item["direction"]
            output.append(view)
        if relation_type in (None, "adjacency"):
            blocks = self.sourceblocks["blocks"]
            for index in range(len(blocks) - 1):
                pairs = ((blocks[index], blocks[index + 1], "next"), (blocks[index + 1], blocks[index], "previous"))
                for source, target, subtype in pairs:
                    actual_direction = "outgoing" if block_id is None or source["block_id"] == block_id else ("incoming" if target["block_id"] == block_id else None)
                    if block_id is not None and actual_direction is None: continue
                    if direction is not None and actual_direction != direction: continue
                    if status not in (None, "derived"): continue
                    payload = {"case_id": self.sidecars["case_id"], "source_hash": self.sidecars["source_hash"], "relation_type": "adjacency", "relation_subtype": subtype, "source_ref": source["block_id"], "target_ref": target["block_id"], "status": "derived"}
                    derived = {"record_type": "DerivedStructuralRelation", "relation_id": f"dr-{canonical_hash(payload)[:24]}", **payload, "direction": actual_direction or "outgoing", "evidence_spans": [source["span"], target["span"]], "evidence_refs": [source["block_id"], target["block_id"]], "reconstructable": True}
                    if query is not None and not any(self._overlaps(ref, query) for ref in derived["evidence_spans"]): continue
                    output.append(derived)
        return output

    def open_relation_evidence(self, relation: dict[str, Any]) -> list[str]:
        return [self.text[ref["start_char"]:ref["end_char"]] for ref in relation["evidence_spans"]]
