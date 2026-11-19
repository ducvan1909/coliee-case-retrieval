"""Conservative CM4/M6 pilot selection based on observable case identity."""

from hashlib import sha256
from pathlib import Path
import re


_CITATION = re.compile(
    r"\b(?P<year>\d{4})\s+(?P<court>FCA|FC|CAF|CF|SCC|CSC)\s+(?P<number>\d+)\b"
    r"|\[(?P<report_year>\d{4})\]\s*F\.?\s*C\.?\s*J\.?\s*(?:No\.?|n[°º])\s*(?P<report_number>\d+)\b"
    r"|\b(?P<volume>\d+)\s+F\.?\s*T\.?\s*R\.?\s+(?P<page>\d+)\b",
    re.IGNORECASE,
)
_BODY = re.compile(r"(?m)^[ \t]*\[(?!(?:19|20)\d{2}\])\d+\]")
_HEADER_END = re.compile(r"(?im)^[ \t]*(?:cases? cited|jurisprudence citée|authorities|counsel|summary|headnote)\s*:")
_COURTS = {"CAF": "FCA", "CF": "FC", "CSC": "SCC"}


def _identifiers(text):
    keys = set()
    for match in _CITATION.finditer(text):
        if match["year"]:
            court = match["court"].upper()
            keys.add(("neutral", match["year"], _COURTS.get(court, court), match["number"]))
        elif match["report_year"]:
            keys.add(("fcj", match["report_year"], match["report_number"]))
        else:
            keys.add(("ftr", match["volume"], match["page"]))
    return keys


def _header_identifiers(records):
    keys = set()
    for row in records:
        if row["span_bytes"][0] == 0 and (body := _BODY.search(row["text"])):
            header = row["text"][:body.start()]
            end = _HEADER_END.search(header)
            keys.update(_identifiers(header[:end.start()] if end else header))
    return keys


def witnessed_identity(row):
    """Accept a citation in A matched to an identifier observed in B's header.

    A shared citation in the bodies of A and B cannot pass. Parallel identifiers
    qualify when both are observable in the same candidate header, without
    guessing aliases from reporter numbers.
    """
    raw = row.get("raw_evidence", {})
    query = row.get("query_id")
    candidate = row.get("candidate_id")
    identity = raw.get("identity_support_refs", [])
    a_rows = [r for r in [*raw.get("a_context_refs", []), *identity] if r["case_id"] == query]
    b_rows = [r for r in [*raw.get("b_passage_refs", []), *identity] if r["case_id"] == candidate]
    if row.get("speaker", {}).get("role") == "quoted_source":
        return False
    b_ids = _header_identifiers(b_rows)
    a_header = _header_identifiers(a_rows)
    for record in a_rows:
        start = record["span_bytes"][0]
        text = record["text"]
        body = _BODY.search(text) if start == 0 else None
        # For a prefix excerpt, require a witnessed boundary before treating any
        # identifier as body evidence. A citation in the query header is self-ID.
        if start == 0 and body is None:
            continue
        for match in _CITATION.finditer(text, body.start() if body else 0):
            left = start + len(text[:match.start()].encode("utf-8"))
            right = left + len(match.group().encode("utf-8"))
            if any(c.get("paragraph_role") == "quoted" and c["span_bytes"][0] < right
                   and left < c["span_bytes"][1] for c in record.get("provenance", {}).get("components", [])):
                continue
            if (_identifiers(match.group()) & b_ids) - a_header:
                return True
    return False


def aggregate_assessments(accepted, pending, *, require_identity_witness=True):
    positive = [row for row in accepted if row["case_relation"] == "supported"]
    if positive:
        witnesses = [row["assessment_id"] for row in positive
                     if not require_identity_witness or witnessed_identity(row)]
        return "supported", min(witnesses, default=None)
    relations = {row["case_relation"] for row in accepted}
    if pending or "supported" in relations or "unknown" in relations or len(relations) != 1:
        return "unknown", None
    return next(iter(relations)), None


def select_supported_cases(snapshot):
    """Select candidates with a supported assessment eligible under the run policy."""
    rows = sorted((case, row["selection_assessment_id"])
                  for case, row in snapshot["candidate_states"].items()
                  if row["case_relation"] == "supported" and row.get("selection_assessment_id"))
    return {"prediction": [case for case, _ in rows], "assessment_ids": [ref for _, ref in rows]}


def selector_fingerprint():
    return sha256(Path(__file__).read_bytes()).hexdigest()
