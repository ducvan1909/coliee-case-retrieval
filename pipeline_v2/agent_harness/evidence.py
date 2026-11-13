"""Source provenance, token-safe delivery, and assessment validation."""

from dataclasses import fields

from .contracts import HarnessError, SourceExcerpt, ToolResult, encode, fingerprint, source_hash


class SourceDrift(HarnessError):
    def __init__(self, case_id):
        super().__init__("source_drift")
        self.case_id = case_id


def string_list(value, label, *, nonempty=False):
    if (not isinstance(value, (list, tuple)) or (nonempty and not value)
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise HarnessError(f"Invalid {label}")
    return list(value)


def excerpt(record):
    return SourceExcerpt(**{field.name: record[field.name] for field in fields(SourceExcerpt)})


def _structural_provenance(value):
    components = value.provenance.get("components")
    if not isinstance(components, list) or not components:
        return None
    return [{key: component.get(key) for key in (
        "unit_id", "handle", "span_bytes", "marker_span_bytes", "observed_marker", "unit_kind",
        "paragraph_role", "attribution_unit_id", "role_evidence_refs", "ownership_cue_observations",
    )} for component in components if isinstance(component, dict)]


def source_record(value, *, overlay=False):
    record = value.to_record()
    if overlay:
        record["provenance_overlay"] = True
        record["ref"] = fingerprint([value.ref, _structural_provenance(value)])
    return record


def slice_record(record, start, end):
    return source_record(excerpt(record).slice(start, end), overlay=record.get("provenance_overlay", False))


def _uncovered(excerpt_value, known):
    start, end = excerpt_value.span_bytes
    pieces = []
    for record in sorted(known, key=lambda row: row["span_bytes"]):
        other_start, other_end = record["span_bytes"]
        if max(excerpt_value.span_bytes[0], other_start) >= min(end, other_end):
            continue
        # The source hash identifies a single raw stream. Reject conflicting
        # bytes even when the supplied fragment itself has a valid digest.
        a, b = max(excerpt_value.span_bytes[0], other_start), min(end, other_end)
        left = excerpt_value.text.encode("utf-8")
        right = record["text"].encode("utf-8")
        base = excerpt_value.span_bytes[0]
        if left[a - base:b - base] != right[a - other_start:b - other_start]:
            raise SourceDrift(excerpt_value.case_id)
        if start >= end or other_end <= start:
            continue
        if start < other_start:
            pieces.append(excerpt_value.slice(start, other_start).to_record())
        start = max(start, other_end)
    if start < end:
        pieces.append(excerpt_value.slice(start, end).to_record())
    return pieces


def normalize_result(value, state, *, search=False, preserve_provenance=False):
    if not isinstance(value, ToolResult) or not isinstance(value.observation, dict):
        raise HarnessError("Tool must return a ToolResult with a JSON observation")
    candidates = string_list(value.candidates, "candidate IDs")
    if not isinstance(value.source_requests, (tuple, list)) or any(
        not isinstance(row, dict) for row in value.source_requests
    ):
        raise HarnessError("Invalid source request records")
    if not isinstance(value.excerpts, (tuple, list)) or any(
        not isinstance(row, SourceExcerpt) for row in value.excerpts
    ):
        raise HarnessError("Invalid source excerpts")
    if search and value.excerpts:
        raise HarnessError("Search previews cannot supply evidence excerpts")
    case_hashes = dict(state.source_hashes)
    new_hashes = {}
    observations = [row.to_record() for row in value.excerpts]
    observations.extend(row for row in value.source_requests if "source_hash" in row)
    for row in observations:
        case_id, digest = row.get("case_id"), row["source_hash"]
        if not isinstance(case_id, str) or not case_id.strip() or not source_hash(digest):
            raise HarnessError("Invalid source request identity")
        if case_hashes.get(case_id, digest) != digest:
            raise SourceDrift(case_id)
        case_hashes[case_id] = new_hashes[case_id] = digest
    accepted = []
    for row in value.excerpts:
        known = [old for old in [*state.catalog.values(), *accepted] if old["case_id"] == row.case_id]
        uncovered = _uncovered(row, known)
        structure = _structural_provenance(row) if preserve_provenance else None
        if structure:
            # A reread of bytes already delivered as the whole query may be
            # the first place where the source reader can attach structure.
            structured = [old for old in known if _structural_provenance(excerpt(old))]
            structured_uncovered = _uncovered(row, structured)
            if structured_uncovered != uncovered:
                old_refs = {old["ref"] for old in known}
                for item in structured_uncovered:
                    value_with_structure = excerpt(item)
                    accepted.append(source_record(value_with_structure, overlay=value_with_structure.ref in old_refs))
                continue
        accepted.extend(uncovered)
    result = {
        "observation": value.observation, "candidates": candidates,
        "source_requests": value.source_requests, "source_hashes": new_hashes, "excerpts": accepted,
    }
    encode(result)
    return result


REF_FIELDS = ("a_context_refs", "b_passage_refs", "identity_support_refs",
              "speaker_evidence_refs", "quote_chain_refs")
RELATIONS = {"supported", "plausible", "similarity_only", "contradicted", "unknown"}
LOCATIONS = {"pinpoint", "bounded", "unresolved"}
REQUIRED = {"source_need_id", "candidate_id", "a_context_refs", "b_passage_refs",
            "case_relation", "passage_location", "reason"}
OPTIONAL = {*REF_FIELDS[2:], "speaker_status", "container_id", "quoted_marker",
            "counterevidence", "missing_evidence"}


def validate_assessments(args, state, action_id):
    if set(args) != {"assessments"} or not isinstance(args["assessments"], list) or not args["assessments"]:
        raise HarnessError("Expected a nonempty assessments list")
    query_id = state.config["identity"]["query_id"]
    current = set(state.current)
    accepted, revised_needs, pairs = [], {}, set()
    for raw in args["assessments"]:
        if not isinstance(raw, dict) or not REQUIRED <= raw.keys() <= REQUIRED | OPTIONAL:
            raise HarnessError("Invalid assessment fields")
        need, candidate, reason = raw["source_need_id"], raw["candidate_id"], raw["reason"]
        if any(not isinstance(value, str) or not value.strip() for value in (need, candidate, reason)):
            raise HarnessError("Invalid assessment need, candidate or reason")
        pair = need, candidate
        if candidate == query_id or candidate not in state.candidates or pair in pairs:
            raise HarnessError("Unknown or duplicate assessment candidate")
        if (not isinstance(raw["case_relation"], str) or raw["case_relation"] not in RELATIONS
                or not isinstance(raw["passage_location"], str) or raw["passage_location"] not in LOCATIONS):
            raise HarnessError("Invalid case relation or passage location")
        row = {**raw, "query_id": query_id}
        for i, name in enumerate(REF_FIELDS):
            refs = string_list(raw.get(name, []), name, nonempty=i < 2)
            if not set(refs) <= current:
                raise HarnessError("Assessment references must be present as raw text in the current payload")
            if i < 2 and any(state.catalog[ref]["case_id"] != (query_id, candidate)[i] for ref in refs):
                raise HarnessError("Assessment A/B references belong to another case")
            row[name] = sorted(refs)
        for name in ("speaker_status", "container_id", "quoted_marker"):
            if name in raw and raw[name] is not None and not isinstance(raw[name], str):
                raise HarnessError(f"Invalid assessment {name}")
        for name in ("counterevidence", "missing_evidence"):
            if name in raw and not isinstance(raw[name], str):
                string_list(raw[name], name)
        refs = row["a_context_refs"]
        if revised_needs.setdefault(need, refs) != refs:
            raise HarnessError("Conflicting A context for one source need")
        pairs.add(pair)
        row["assessment_id"] = fingerprint([action_id, need, candidate])
        old_id = state.active_assessments.get(pair)
        row["version"] = 1 + sum(
            (old["source_need_id"], old["candidate_id"]) == pair for old in state.assessments.values()
        )
        row["supersedes"] = old_id
        accepted.append(row)
    invalidated = []
    for (need, candidate), assessment_id in state.active_assessments.items():
        if (need, candidate) in pairs or (need in revised_needs and revised_needs[need] != state.needs[need]):
            invalidated.append(assessment_id)
    return accepted, invalidated


def assessment_refs(row):
    return {ref for field in (*REF_FIELDS, "container_refs") for ref in row.get(field, ())}
