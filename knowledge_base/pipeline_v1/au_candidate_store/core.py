"""Offline Plan 11 candidate store built from untrusted compact run reports.

build_store accepts report dictionaries or JSON paths and returns candidates,
target_ledger and audit. Run IDs hash canonical JSON content, not filenames.
Candidate IDs identify the original run/row/AU; exact duplicates retain that
provenance and point to the lexicographically smallest ID. No full normalized
output is trusted. Field witnesses link MODEL_ASSERTED values to selected atoms,
not precise field spans or validated entailment. Ownership is only a structural
target-overlap locator: compact output supplies no primary proposition start.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

from ..au_compact.core import COMPACT_SCHEMA
from ..au_compact.manifest import _binding_path
from ..au_only.atom_binding import resolve
from ..source_contract import open_source


VERSION = "au-candidate-store-v1"
_SCHEMA = json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8"))
_AU_VALIDATOR = Draft202012Validator(_SCHEMA["$defs"]["au"])
_ENVELOPE_SCHEMA = copy.deepcopy(_SCHEMA)
_ENVELOPE_SCHEMA["properties"]["aus"]["items"] = {}
_ENVELOPE_VALIDATOR = Draft202012Validator(_ENVELOPE_SCHEMA)
_LEADING_MARKER = re.compile(r"^\s*\[\d+\]\s*")


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _errors(validator, value):
    return sorted("/".join(map(str, e.absolute_path)) + ": " + e.message
                  for e in validator.iter_errors(value))


def _exact_span(value, source, case_id, source_hash):
    if not isinstance(value, dict):
        raise ValueError("invalid_span_shape")
    start, end = value.get("start_char"), value.get("end_char")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source):
        raise ValueError("invalid_span_offsets")
    if value.get("case_id", case_id) != case_id or value.get("source_hash", source_hash) != source_hash:
        raise ValueError("span_identity_mismatch")
    quote = source[start:end]
    if "quote" in value and value["quote"] != quote:
        raise ValueError("span_quote_mismatch")
    return {"case_id": case_id, "source_hash": source_hash,
            "start_char": start, "end_char": end, "quote": quote}


def _intersects(a, b):
    return a["start_char"] < b["end_char"] and b["start_char"] < a["end_char"]


def _catalog(request, source_store, atom_root):
    """Verify row identities, then isolate malformed atoms by ID.

    The compact catalog's allowlist rule is atom overlap with requested refs.
    Unlike batch normalization, a corrupt selected atom rejects only its AU.
    """
    case_id, digest = request["case_id"], request["source_hash"]
    source = open_source(source_store, case_id, digest)
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != digest:
        raise ValueError("source_hash_mismatch")
    binding = request["atom_binding"]
    if binding["case_id"] != case_id or binding["source_hash"] != digest:
        raise ValueError("binding_identity_mismatch")
    atom_map = resolve(_binding_path(binding, atom_root))
    if atom_map.get("cache_key") != binding["atom_map_cache_key"]:
        raise ValueError("atom_map_cache_key_mismatch")
    target_ids = request.get("expected_target_ids")
    if not isinstance(target_ids, list) or len(target_ids) != 1 or not isinstance(target_ids[0], str) or not target_ids[0]:
        raise ValueError("one_locked_target_required")
    refs = request.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise ValueError("source_refs_required")
    checked = []
    for ref in refs:
        span = _exact_span(ref, source, case_id, digest)
        if ref.get("role") not in {"target", "context"}:
            raise ValueError("invalid_source_ref_role")
        checked.append({**span, "role": ref["role"], "target_ids": ref.get("target_ids", []),
                        "block_id": ref.get("block_id", ref.get("owner_block_id"))})
    targets = [ref for ref in checked if ref["role"] == "target"]
    if not targets or any(target_ids[0] not in ref["target_ids"] for ref in targets):
        raise ValueError("target_ref_identity_mismatch")
    atoms, invalid = {}, {}
    raw_atoms = atom_map.get("atoms")
    if not isinstance(raw_atoms, list):
        raise ValueError("invalid_atom_map_shape")
    counts = Counter(atom.get("atom_id") for atom in raw_atoms
                     if isinstance(atom, dict) and isinstance(atom.get("atom_id"), str))
    for atom in raw_atoms:
        if not isinstance(atom, dict) or not isinstance(atom.get("atom_id"), str) or not atom["atom_id"]:
            continue
        aid = atom["atom_id"]
        try:
            if counts[aid] != 1:
                raise ValueError("duplicate_atom_id")
            if atom.get("case_id") != case_id or atom.get("source_hash") != digest:
                raise ValueError("atom_identity_mismatch")
            span = _exact_span(atom.get("span"), source, case_id, digest)
            if "quote" in atom and atom["quote"] != span["quote"]:
                raise ValueError("atom_quote_mismatch")
            if any(_intersects(span, ref) for ref in checked):
                atoms[aid] = {**span, "atom_id": aid, "parent_block_id": atom.get("parent_block_id"),
                              "target_intersecting": any(_intersects(span, ref) for ref in targets)}
        except ValueError as exc:
            invalid[aid] = str(exc)
    return atoms, invalid, targets


def _owner(evidence, targets, target_id):
    intersections = [(max(atom["start_char"], ref["start_char"]), atom["atom_id"], atom, ref)
                     for atom in evidence for ref in targets if _intersects(atom, ref)]
    anchor, _, atom, ref = min(intersections, key=lambda item: (item[0], item[1], item[3]["start_char"]))
    evidence_start = min(item["start_char"] for item in evidence)
    # Raw evidence start is preserved. Neither overlap nor a recognizable
    # paragraph marker licenses trimming or proves a legal proposition start.
    ambiguous = not any(target["start_char"] <= evidence_start < target["end_char"]
                        for target in targets)
    marker_outside = any(_LEADING_MARKER.match(item["quote"]) and
                         item["start_char"] < target["start_char"]
                         for item in evidence for target in targets if _intersects(item, target))
    ambiguous = ambiguous or marker_outside
    return {"status": "structural_owner_candidate", "target_id": target_id,
            "anchor_char": anchor, "evidence_start_char": evidence_start,
            "evidence_atom_id": atom["atom_id"],
            "owner_block_id": atom.get("parent_block_id") or ref.get("block_id"),
            "rule": "minimum_target_evidence_overlap_start",
            "primary_proposition_start": None, "primary_proposition_start_available": False,
            "ownership_verified": False, "ownership_review": "pending",
            "flags": ["primary_proposition_start_unavailable"] +
                     (["ambiguous_evidence_start"] if ambiguous else []) +
                     (["leading_marker_outside_target_ref"] if marker_outside else [])}


def _witnesses(au, evidence):
    spans = [{key: atom[key] for key in ("case_id", "source_hash", "start_char", "end_char", "quote")}
             for atom in evidence]
    return {field: {"value": copy.deepcopy(value), "status": "MODEL_ASSERTED",
                    "scope": "candidate", "evidence_ref_ids": [a["atom_id"] for a in evidence],
                    "evidence_spans": spans, "precise_field_span": None,
                    "entailment_validated": False, "semantic_review": "pending"}
            for field, value in au.items() if field != "evidence_ref_ids"}


def _candidate(au, ordinal, row_id, run_id, row, atoms, invalid, targets, row_errors, envelope_errors):
    request = row.get("request")
    request = request if isinstance(request, dict) else {}
    compact = row.get("compact_response", {})
    cid = "auc-" + _hash({"run_id": run_id, "row_id": row_id, "au_index": ordinal, "au": au})
    receipt = row.get("receipt") if isinstance(row.get("receipt"), dict) else {}
    result = {"candidate_id": cid, "case_id": request.get("case_id"),
              "source_hash": request.get("source_hash"), "target_id": compact.get("target_id"),
              "status": "rejected", "structural_status": "invalid", "reasons": [],
              "proposal": copy.deepcopy(au),
              **{field: copy.deepcopy(au.get(field)) if isinstance(au, dict) else None
                 for field in ("claim", "kind", "other_kind", "speaker", "attribution_role", "needs_context", "evidence_ref_ids")},
              "evidence_spans": [], "selected_evidence": [],
              "field_witnesses": {}, "ownership": None, "semantic_review": "pending",
              "accepted_semantic": False, "superseded_by": None, "related_candidate_ids": [],
              "provenance": {"run_id": run_id, "row_id": row_id, "request_id": request.get("request_id"),
                             "au_index": ordinal, "model_asserted": True,
                             "producer_config_sha256": _hash(request.get("spec", {})),
                             "prompt_identity": {k: receipt["prompt_identity"][k]
                                                 for k in ("prompt_version", "content_sha256")
                                                 if isinstance(receipt.get("prompt_identity"), dict) and
                                                 k in receipt["prompt_identity"]}}}
    errors = row_errors + envelope_errors + _errors(_AU_VALIDATOR, au)
    if errors:
        result["reasons"] = errors
        return result
    selected = []
    for aid in au["evidence_ref_ids"]:
        if aid in invalid:
            errors.append(aid + ": " + invalid[aid])
        elif aid not in atoms:
            errors.append(aid + ": evidence_id_not_region_allowed")
        else:
            selected.append(atoms[aid])
    if not any(a["target_intersecting"] for a in selected):
        errors.append("target_intersecting_evidence_required")
    if errors:
        result["reasons"] = errors
        return result
    selected.sort(key=lambda a: (a["start_char"], a["end_char"], a["atom_id"]))
    result["selected_evidence"] = copy.deepcopy(selected)
    result["evidence_spans"] = [{k: a[k] for k in ("case_id", "source_hash", "start_char", "end_char", "quote")} for a in selected]
    result["field_witnesses"] = _witnesses(au, selected)
    result["ownership"] = _owner(selected, targets, compact["target_id"])
    reasons = []
    if au["speaker"] == "unknown":
        reasons.append("unknown_speaker")
    if au["kind"] == "unresolved_kind":
        reasons.append("unresolved_kind")
    reasons.extend("needs_context:" + flag for flag in au["needs_context"])
    if compact["coverage_status"] == "needs_split":
        reasons.append("needs_split")
    if "ambiguous_evidence_start" in result["ownership"]["flags"]:
        reasons.append("ambiguous_evidence_start")
    required_witnesses = {"claim", "kind", "speaker", "attribution_role"}
    if au["kind"] == "other":
        required_witnesses.add("other_kind")
    if any(not result["field_witnesses"].get(field, {}).get("evidence_spans") for field in required_witnesses):
        reasons.append("missing_required_field_witness")
    result.update(status="unresolved" if reasons else "candidate", structural_status="valid", reasons=reasons)
    return result


def _dedup_key(record):
    au = record["proposal"]
    return _hash({"case_id": record["case_id"], "source_hash": record["source_hash"],
                  **{key: au[key] for key in ("claim", "kind", "other_kind", "speaker", "attribution_role")},
                  "needs_context": sorted(au["needs_context"]),
                  "evidence": sorted({(s["start_char"], s["end_char"], s["quote"]) for s in record["evidence_spans"]})})


def build_store(reports, source_store, atom_root, reviews=None):
    """Return deterministic candidate/audit records without writing or remote calls.

    Invalid AU schemas/IDs/spans reject that AU only. Row source/binding or
    envelope failures reject its AUs and remain visible in the target ledger.
    Negative/unresolved targets are model assertions with omission review pending.
    """
    if isinstance(reports, (dict, str, Path)):
        reports = [reports]
    unique = {}
    exact_hashes = {}
    for report in reports:
        if isinstance(report, (str, Path)):
            raw = Path(report).read_bytes()
            report = json.loads(raw.decode("utf-8-sig"))
            exact_digest = hashlib.sha256(raw).hexdigest()
        else:
            exact_digest = _hash(report)
        if not isinstance(report, dict) or report.get("artifact_type") != "AUCompactRun":
            raise ValueError("input_must_be_compact_run_report")
        if report.get("schema_version") != "au-compact-runtime-v1" or not isinstance(report.get("request_ledger"), list):
            raise ValueError("invalid_compact_run_report_shape")
        unique[_hash(report)] = report
        exact_hashes.setdefault(_hash(report), set()).add(exact_digest)
    candidates, ledger = [], []
    for digest, report in sorted(unique.items()):
        run_id = "run-" + digest
        rows = {_hash(row): row for row in report["request_ledger"]}
        for row_digest, row in sorted(rows.items()):
            row_id = "row-" + row_digest
            if not isinstance(row, dict):
                ledger.append({"run_id": run_id, "row_id": row_id, "errors": ["invalid_row_shape"],
                               "target_omission_review": "pending", "candidate_ids": []})
                continue
            request = row.get("request")
            request = request if isinstance(request, dict) else {}
            compact = row.get("compact_response")
            errors = []
            atoms, invalid, targets = {}, {}, []
            try:
                atoms, invalid, targets = _catalog(request, source_store, atom_root)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append("source_or_binding: " + str(exc))
            envelope_errors = _errors(_ENVELOPE_VALIDATOR, compact)
            if isinstance(compact, dict) and (compact.get("request_id") != request.get("request_id") or
                    request.get("expected_target_ids") != [compact.get("target_id")]):
                envelope_errors.append("compact_request_target_identity_mismatch")
            aus = compact.get("aus", []) if isinstance(compact, dict) else []
            aus = aus if isinstance(aus, list) else []
            records = [_candidate(au, i, row_id, run_id, row, atoms, invalid, targets, errors, envelope_errors)
                       for i, au in enumerate(aus)]
            candidates.extend(records)
            for record in records:
                record["provenance"]["run_sha256"] = sorted(exact_hashes[digest])
                record["provenance"]["proposal_sha256"] = _hash(record["proposal"])
            ledger.append({"run_id": run_id, "row_id": row_id, "case_id": request.get("case_id"),
                           "source_hash": request.get("source_hash"), "request_id": request.get("request_id"),
                           "target_ids": request.get("expected_target_ids", []),
                           "source_refs": copy.deepcopy(request.get("source_refs", [])),
                           "protocol_status_reported": row.get("status"),
                           "model_decision": compact.get("decision") if isinstance(compact, dict) else None,
                           "coverage_status": compact.get("coverage_status") if isinstance(compact, dict) else None,
                           "hard_negative_reason": compact.get("hard_negative_reason") if isinstance(compact, dict) else None,
                           "unresolved_reason": compact.get("unresolved_reason") if isinstance(compact, dict) else None,
                           "errors": errors + envelope_errors, "invalid_atom_ids": dict(sorted(invalid.items())),
                           "candidate_ids": [record["candidate_id"] for record in records],
                           "target_omission_review": "pending", "semantic_review": "pending",
                           "run_sha256": sorted(exact_hashes[digest]),
                           "proposal_sha256": _hash(compact),
                           "atom_binding": copy.deepcopy(request.get("atom_binding"))})
    candidates.sort(key=lambda r: r["candidate_id"])
    groups = {}
    for record in candidates:
        if record["structural_status"] == "valid":
            groups.setdefault(_dedup_key(record), []).append(record)
    for group in groups.values():
        canonical = group[0]["candidate_id"]
        for record in group[1:]:
            record["status_before_supersession"] = record["status"]
            record.update(status="superseded", superseded_by=canonical)
    valid = [record for record in candidates if record["structural_status"] == "valid"]
    for i, left in enumerate(valid):
        for right in valid[i + 1:]:
            if (left["case_id"] == right["case_id"] and left["source_hash"] == right["source_hash"] and
                    left["proposal"]["claim"] != right["proposal"]["claim"] and
                    any(_intersects(a, b) for a in left["evidence_spans"] for b in right["evidence_spans"])):
                left["related_candidate_ids"].append(right["candidate_id"])
                right["related_candidate_ids"].append(left["candidate_id"])
    counts = Counter(record["status"] for record in candidates)
    audit = {"artifact_type": "AUCandidateStoreAudit", "schema_version": VERSION,
             "run_ids": ["run-" + digest for digest in sorted(unique)], "run_count": len(unique),
             "target_ledger_count": len(ledger), "candidate_count": counts["candidate"],
             "rejected_count": counts["rejected"], "unresolved_count": counts["unresolved"],
             "superseded_count": counts["superseded"], "accepted_count": 0,
             "total_au_count": len(candidates), "structurally_valid_count": len(valid),
             "semantic_status": "pending", "semantic_gold": False, "semantic_quality_claim": False,
             "ownership_status": "structural_candidates_only", "verified_ownership_count": 0,
             "primary_proposition_start_unavailable_count": len(valid),
             "limitations": ["MODEL_ASSERTED field witnesses link selected source atoms, not precise per-field spans or validated entailment.",
                             "Compact output supplies no primary proposition start; structural anchors do not prove evidence-start ownership.",
                             "All target omission and AU semantic reviews remain pending; no candidate is accepted."]}
    store = {"artifact_type": "AUCandidateStore", "schema_version": VERSION,
            "semantic_gold": False, "semantic_quality_claim": False,
            "candidates": candidates, "target_ledger": ledger, "audit": audit}
    if reviews is not None:
        from .reviews import apply_reviews
        return apply_reviews(store, reviews, source_store=source_store, atom_root=atom_root)
    return store
