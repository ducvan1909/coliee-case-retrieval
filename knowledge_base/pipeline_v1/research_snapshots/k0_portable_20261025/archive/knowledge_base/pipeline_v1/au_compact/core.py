"""Fail-closed, offline bridge from compact AU proposals to the existing full output."""
from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path

from jsonschema import Draft202012Validator

from ..au_only.atom_binding import AtomBindingError, resolve as resolve_atom_binding


ROOT = Path(__file__).resolve().parents[1]
COMPACT_SCHEMA = ROOT / "contracts" / "compact_au_model_output.v1.json"
COMPACT_TRANSPORT_SCHEMA = ROOT / "contracts" / "compact_au_transport.v1.json"
FULL_SCHEMA = ROOT / "contracts" / "plan10_au_model_output.v1.json"
FULL_SCHEMA_VERSION = "plan10-au-model-output-v1"
SIDECAR_SCHEMA_VERSION = "au-compact-needs-split-v1"
_VALIDATOR = Draft202012Validator(json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8")))
_FULL_VALIDATOR = Draft202012Validator(json.loads(FULL_SCHEMA.read_text(encoding="utf-8")))


class CompactAUError(ValueError):
    pass


def deduplicate_lists(value):
    """Remove exact string duplicates only; never infer labels or evidence."""
    result = copy.deepcopy(value)
    changes = []
    if not isinstance(result, dict) or not isinstance(result.get("aus"), list):
        return result, changes
    for index, au in enumerate(result["aus"]):
        if not isinstance(au, dict):
            continue
        for field in ("needs_context", "evidence_ref_ids"):
            values = au.get(field)
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                continue
            unique = list(dict.fromkeys(values))
            if unique != values:
                changes.append({"au_index": index, "field": field, "removed_count": len(values) - len(unique)})
                au[field] = unique
    return result, changes


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _span(value, source_length):
    try:
        start, end = value["start_char"], value["end_char"]
    except (KeyError, TypeError) as exc:
        raise CompactAUError("missing atom span") from exc
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= source_length:
        raise CompactAUError("invalid atom span")
    return start, end


def _intersects(atom_span, refs):
    start, end = atom_span
    return any(start < ref["end_char"] and ref["start_char"] < end for ref in refs)


def _union(spans):
    merged = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def build_evidence_catalog(request, binding, source):
    """Expand requested refs to whole overlapping atoms; never retain source fragments."""
    if not isinstance(source, str):
        raise CompactAUError("source must be text")
    if hashlib.sha256(source.encode()).hexdigest() != request.get("source_hash"):
        raise CompactAUError("request source hash mismatch")
    try:
        atom_map = resolve_atom_binding(binding)
    except (AtomBindingError, KeyError) as exc:
        raise CompactAUError(str(exc)) from exc
    if binding.get("case_id") != request.get("case_id") or binding.get("source_hash") != request.get("source_hash"):
        raise CompactAUError("request/binding identity mismatch")
    refs = request.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise CompactAUError("request has no source refs")
    checked_refs = []
    for ref in refs:
        start, end = _span(ref, len(source))
        if ref.get("role") not in {"target", "context"}:
            raise CompactAUError("invalid source ref role")
        checked_refs.append({**ref, "start_char": start, "end_char": end})
    target_refs = [ref for ref in checked_refs if ref["role"] == "target"]
    if not target_refs:
        raise CompactAUError("request has no target source ref")
    expected = request.get("expected_target_ids", [])
    if len(expected) != 1 or any(expected[0] not in ref.get("target_ids", []) for ref in target_refs):
        raise CompactAUError("target source ref does not own locked target")
    atoms = {}
    for atom in atom_map.get("atoms", []):
        if atom.get("case_id") != request["case_id"] or atom.get("source_hash") != request["source_hash"]:
            raise CompactAUError("atom identity mismatch")
        atom_id = atom.get("atom_id")
        if not isinstance(atom_id, str) or not atom_id or atom_id in atoms:
            raise CompactAUError("invalid or duplicate atom id")
        start, end = _span(atom.get("span", {}), len(source))
        if not _intersects((start, end), checked_refs):
            continue
        atoms[atom_id] = {
            "atom_id": atom_id,
            "start_char": start,
            "end_char": end,
            "quote": source[start:end],
            "target_intersecting": _intersects((start, end), target_refs),
        }
    requested_union = _union([(ref["start_char"], ref["end_char"]) for ref in checked_refs])
    rendered_union = _union([(atom["start_char"], atom["end_char"]) for atom in atoms.values()])
    requested_chars = sum(end - start for start, end in requested_union)
    rendered_chars = sum(end - start for start, end in rendered_union)
    rendered_bytes = sum(len(source[start:end].encode("utf-8")) for start, end in rendered_union)
    return {
        "atom_map": atom_map,
        "atoms": atoms,
        "metrics": {
            "requested_char_union": requested_chars,
            "rendered_atom_char_union": rendered_chars,
            "expansion_chars": rendered_chars - requested_chars,
            "estimated_input_tokens": rendered_bytes + 512,
        },
    }


def validate_compact(value, request):
    errors = sorted(_VALIDATOR.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        raise CompactAUError("compact schema: " + errors[0].message)
    expected = request.get("expected_target_ids", [])
    if len(expected) != 1:
        raise CompactAUError("compact normalization requires one locked target")
    if value["request_id"] != request.get("request_id") or value["target_id"] != expected[0]:
        raise CompactAUError("compact request/target ownership mismatch")
    return value


def _uncertainties(needs_context):
    mapping = {
        "attribution": "ambiguous_speaker",
        "condition": "missing_condition",
        "exception": "missing_exception",
        "limit": "missing_limit",
        "current_court_response": "insufficient_court_response",
        "cross_block_context": "other",
    }
    return list(dict.fromkeys(mapping[item] for item in needs_context))


def normalize_positive(value, request, binding, source):
    """Validate and normalize a positive compact result without inventing legal spans."""
    validate_compact(value, request)
    if value["decision"] != "positive":
        raise CompactAUError("only positive compact output can be normalized to authority units")
    catalog = build_evidence_catalog(request, binding, source)["atoms"]
    normalized = []
    for ordinal, compact_au in enumerate(value["aus"]):
        try:
            evidence = [catalog[atom_id] for atom_id in compact_au["evidence_ref_ids"]]
        except KeyError as exc:
            raise CompactAUError("evidence atom is not region-allowed") from exc
        if not any(atom["target_intersecting"] for atom in evidence):
            raise CompactAUError("authority unit needs target-intersecting evidence")
        spans = [{key: atom[key] for key in ("start_char", "end_char", "quote")} for atom in evidence]
        attribution_span = spans[0]
        normalized.append({
            "local_au_id": "auc-" + _hash({"request_id": request["request_id"], "target_id": value["target_id"], "ordinal": ordinal, "compact_au": compact_au})[:24],
            "claim_text": compact_au["claim"],
            "kind": compact_au["kind"],
            "other_kind": compact_au["other_kind"],
            "evidence_spans": spans,
            "attributions": [{"role": compact_au["attribution_role"], "speaker": compact_au["speaker"], "evidence_span": attribution_span}],
            "condition_spans": [],
            "exception_spans": [],
            "limit_spans": [],
            "candidate_status": "needs_context" if compact_au["needs_context"] else "complete",
            "uncertainty_reasons": _uncertainties(compact_au["needs_context"]),
        })
    result = {
        "schema_version": FULL_SCHEMA_VERSION,
        "request_id": request["request_id"],
        "processed_target_ids": request["expected_target_ids"],
        "target_results": [{
            "target_id": value["target_id"], "decision": "positive", "authority_units": normalized,
            "hard_negative_reason": None, "unresolved_reason": None, "reason_detail": None,
        }],
        "context_requests": [], "warnings": [],
    }
    errors = sorted(_FULL_VALIDATOR.iter_errors(result), key=lambda error: list(error.absolute_path))
    if errors:
        raise CompactAUError("full normalization schema: " + errors[0].message)
    return result


def build_needs_split_sidecar(value, normalized=None):
    """Persist split-needed status without discarding already normalized positive AUs."""
    if value.get("coverage_status") != "needs_split":
        raise CompactAUError("needs-split sidecar requires coverage_status needs_split")
    result = normalized or {"authority_units": []}
    if normalized is not None:
        targets = normalized.get("target_results", [])
        if len(targets) != 1 or normalized.get("request_id") != value.get("request_id"):
            raise CompactAUError("normalized output does not match compact request")
        authority_units = targets[0].get("authority_units", [])
    else:
        authority_units = []
    return {
        "artifact_type": "AUCompactNeedsSplit",
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "request_id": value["request_id"],
        "target_id": value["target_id"],
        "decision": value["decision"],
        "coverage_status": "needs_split",
        "unresolved_reason": value["unresolved_reason"],
        "normalized_authority_units": authority_units,
    }
