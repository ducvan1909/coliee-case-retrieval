"""Deterministic checks of model labels against the current raw payload."""

from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from .contracts import HarnessError, fingerprint, integer
from .evidence import excerpt, source_record, string_list
from .schema import ASSESSMENT_SCHEMA_VERSION, ASSESSMENT_VALIDATOR_VERSION, REF_FIELDS


class AssessmentStateError(HarnessError):
    """A schema-valid assessment disagrees with its current source state."""


def assessment_validator_fingerprint():
    root = Path(__file__).parent
    implementations = {
        name: sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in ("assessment.py", "evidence.py", "contracts.py", "schema.py", "harness.py", "ledger.py")
    }
    return fingerprint([ASSESSMENT_VALIDATOR_VERSION, version("jsonschema"), implementations])


def _span(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(integer(offset) for offset in value) or value[0] >= value[1]):
        raise AssessmentStateError("invalid_provenance_span")
    return tuple(value)


def _overlaps(left, right):
    return max(left[0], right[0]) < min(left[1], right[1])


def _covers(outer, inner):
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def _record(state, ref):
    if ref not in state.current_records:
        raise AssessmentStateError("ref_not_in_current_payload")
    row = state.current_records[ref]
    source = excerpt(row)
    if (row != state.catalog.get(ref) or state.source_hashes.get(source.case_id) != source.source_hash
            or source_record(source, overlay=row.get("provenance_overlay", False))["ref"] != ref):
        raise AssessmentStateError("ref_source_or_provenance_mismatch")
    provenance = source.provenance
    for key in ("case_id", "source_hash"):
        if key in provenance and provenance[key] != row[key]:
            raise AssessmentStateError("ref_source_or_provenance_mismatch")
    if "span_bytes" in provenance and _span(provenance["span_bytes"]) != source.span_bytes:
        raise AssessmentStateError("ref_source_or_provenance_mismatch")
    components = provenance.get("components", [])
    if not isinstance(components, list):
        raise AssessmentStateError("invalid_provenance_components")
    for component in components:
        if not isinstance(component, dict) or not _overlaps(source.span_bytes, _span(component.get("span_bytes"))):
            raise AssessmentStateError("component_outside_raw_excerpt")
        for key in ("unit_id", "handle", "attribution_unit_id"):
            label = component.get(key)
            if label is not None and (not isinstance(label, str) or not label.strip()):
                raise AssessmentStateError("invalid_provenance_component_anchor")
    return row


def _component_rows(rows):
    return [(row, component) for row in rows for component in row["provenance"].get("components", [])]


def _anchor(component):
    return component.get("unit_id") or component.get("handle")


def _require_side(evidence, names, case_id):
    for name in names:
        if any(row["case_id"] != case_id for row in evidence[name]):
            raise AssessmentStateError(f"{name}_belongs_to_another_case")


def _chain_matches(chain, quoted):
    sources = [
        (_span(row["span_bytes"]), {_anchor(component) for _, component in _component_rows([row])})
        for row in chain
    ]
    matched = set()
    for _, component in quoted:
        attribution = component.get("attribution_unit_id")
        cues = component.get("role_evidence_refs", [])
        if not isinstance(cues, list):
            raise AssessmentStateError("invalid_quote_chain_provenance")
        for cue in cues:
            if not isinstance(cue, dict):
                raise AssessmentStateError("invalid_quote_chain_provenance")
            start, end = _span(cue.get("span_bytes"))
            overlaps = sorted((span, index) for index, (span, anchors) in enumerate(sources)
                              if (not attribution or attribution in anchors) and _overlaps(span, (start, end)))
            position = start
            for (left, right), _ in overlaps:
                if left > position:
                    break
                position = max(position, right)
            if position >= end:
                matched.update(index for _, index in overlaps)
    return len(matched) == len(chain)


def _speaker_evidence(speaker, evidence, query_id, candidate):
    role = speaker["role"]
    quote_required = role == "quoted_source" or speaker.get("type") == "adopted_reasoning"
    speaker_refs, container_refs, chain_refs = ("speaker_evidence_refs", "container_refs", "quote_chain_refs")
    expected_case = query_id if speaker.get("side") == "A" else candidate
    _require_side(evidence, (speaker_refs, container_refs, chain_refs), expected_case)
    missing = []
    if role != "unknown" and not evidence[speaker_refs]:
        missing.append(speaker_refs)
    if quote_required:
        missing.extend(name for name in (container_refs, chain_refs) if not evidence[name])
    speaker_components = _component_rows(evidence[speaker_refs])
    for row in evidence[speaker_refs]:
        choices = [component for _, component in _component_rows([row])
                   if component.get("unit_kind") == "paragraph"
                   or component.get("paragraph_role") in ("current_case", "quoted", "unknown")]
        if role == "quoted_source":
            choices = [component for component in choices if component.get("paragraph_role") == "quoted"]
        elif role in ("court", "party"):
            # Structural metadata need not classify the court's voice or a
            # party's submission. It must not explicitly place the claim in a quote.
            choices = [component for component in choices if component.get("paragraph_role") != "quoted"]
        if not choices:
            raise AssessmentStateError("speaker_ref_lacks_matching_provenance")
    container_components = []
    speaker_anchors = {_anchor(component) for _, component in speaker_components
                       if component.get("paragraph_role") == "quoted"}
    speaker_anchors.discard(None)
    for row in evidence[container_refs]:
        choices = [(record, component) for record, component in _component_rows([row]) if _anchor(component)]
        if quote_required:
            choices = [(record, component) for record, component in choices
                       if component.get("paragraph_role") == "quoted"]
        if role == "quoted_source" and evidence[speaker_refs]:
            choices = [(record, component) for record, component in choices if _anchor(component) in speaker_anchors]
        if not choices:
            raise AssessmentStateError("container_ref_lacks_matching_provenance")
        container_components.extend(choices)
    quoted = [(record, component) for record, component in container_components or speaker_components
              if component.get("paragraph_role") == "quoted"]
    chain = evidence[chain_refs]
    if any(not _component_rows([row]) for row in chain):
        raise AssessmentStateError("quote_chain_ref_lacks_matching_provenance")
    waiting_for_anchor = quote_required and not quoted and any(
        name in missing for name in (speaker_refs, container_refs)
    )
    if chain and not waiting_for_anchor and not _chain_matches(chain, quoted):
        raise AssessmentStateError("quote_chain_ref_lacks_a_delivered_attribution_cue")
    markers = [
        {"container_id": _anchor(component), "marker": component["observed_marker"]}
        for row, component in container_components
        if component.get("paragraph_role") == "quoted" and integer(component.get("observed_marker"))
        and component.get("marker_span_bytes") is not None
        and _covers(_span(row["span_bytes"]), _span(component["marker_span_bytes"]))
    ]
    return missing, {
        "container_ids": sorted({_anchor(component) for _, component in container_components}),
        "quoted_markers": list({(row["container_id"], row["marker"]): row for row in markers}.values()),
    }


def validate_assessment_state(args, state, action_id):
    """Check the schema-valid batch and return accepted, pending and superseded rows."""
    query_id = state.config["identity"]["query_id"]
    accepted, pending, revised, pairs = [], [], {}, set()
    for raw in args["assessments"]:
        need, candidate = raw["source_need_id"], raw["candidate_id"]
        pair = need, candidate
        if not all(raw[name].strip() for name in ("source_need_id", "candidate_id", "reason")):
            raise AssessmentStateError("blank_assessment_text")
        if candidate == query_id or candidate not in state.candidates or pair in pairs:
            raise AssessmentStateError("unknown_or_duplicate_candidate")
        pairs.add(pair)
        refs = {}
        try:
            for name in REF_FIELDS:
                refs[name] = sorted(string_list(raw.get(name, []), name))
            for name in ("counterevidence", "missing_evidence"):
                if name in raw:
                    string_list([raw[name]] if isinstance(raw[name], str) else raw[name], name)
        except HarnessError as exc:
            raise AssessmentStateError("blank_or_duplicate_evidence_refs_or_notes") from exc
        evidence = {name: [_record(state, ref) for ref in values] for name, values in refs.items()}
        _require_side(evidence, ("a_context_refs",), query_id)
        _require_side(evidence, ("b_passage_refs",), candidate)
        if any(row["case_id"] not in (query_id, candidate) for row in evidence["identity_support_refs"]):
            raise AssessmentStateError("identity_support_refs_belong_to_another_case")
        context_refs = refs["a_context_refs"]
        if context_refs and revised.setdefault(need, context_refs) != context_refs:
            raise AssessmentStateError("conflicting_a_context_for_one_need")
        speaker = raw.get("speaker", {"role": "unknown"})
        missing, structure = _speaker_evidence(speaker, evidence, query_id, candidate)
        missing.extend(name for name in REF_FIELDS[:2] if not evidence[name])
        if raw.get("missing_evidence"):
            missing.append("reported_missing_evidence")
        row = {
            **raw, **refs, "query_id": query_id, "speaker": speaker, **structure,
            "assessment_schema_version": ASSESSMENT_SCHEMA_VERSION,
            "raw_evidence": evidence,
        }
        if missing:
            pending.append({
                **row, "status": "pending_evidence", "case_relation": "unknown",
                "passage_location": raw["passage_location"] if refs["b_passage_refs"] else "unresolved",
                "missing_evidence": missing, "reported_missing_evidence": raw.get("missing_evidence"),
            })
            continue
        accepted.append({
            **row, "status": "accepted",
            "attribution_status": "unknown" if speaker["role"] == "unknown" else "model_inferred",
            "assessment_id": fingerprint([action_id, need, candidate]),
            "version": 1 + sum((old["source_need_id"], old["candidate_id"]) == pair
                               for old in state.assessments.values()),
            "supersedes": state.active_assessments.get(pair),
        })
    accepted_pairs = {(row["source_need_id"], row["candidate_id"]) for row in accepted}
    invalidated = [
        assessment_id for (need, candidate), assessment_id in state.active_assessments.items()
        if (need, candidate) in accepted_pairs or (need in revised and revised[need] != state.needs[need])
    ]
    return accepted, pending, invalidated
