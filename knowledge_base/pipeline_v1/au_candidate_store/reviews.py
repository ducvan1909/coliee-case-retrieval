"""Offline review integration. Exact witnesses are verified, entailment is not.

Path run bindings use SHA256 of exact file bytes; dictionary runs use canonical
JSON SHA256. AU proposal hashes cover the original AU; omission hashes cover the
whole compact response. Conflicting sidecars never use timestamp/latest wins.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

from .core import _catalog, _errors, _hash

REVIEW_SCHEMA = Path(__file__).resolve().parents[1] / "contracts" / "au_candidate_review.v1.json"
CHECKS = ("authority_qualification", "target_contribution", "claim_support",
          "attribution", "qualification", "duplicate")


def canonical_sha256(value):
    """SHA256 of UTF-8 JSON, sorted keys, compact separators, no NaN."""
    return _hash(value)


def run_sha256(report):
    """Exact bytes for a path, canonical JSON for a dictionary."""
    return hashlib.sha256(Path(report).read_bytes()).hexdigest() if isinstance(report, (str, Path)) else _hash(report)


def _quote(witness, atoms, targets, primary=False):
    atom = atoms.get(witness["atom_id"])
    if atom is None:
        raise ValueError("witness_atom_not_allowed")
    quote = witness["quote"]
    position = atom["quote"].find(quote)
    if position < 0 or atom["quote"].find(quote, position + 1) >= 0:
        raise ValueError("witness_quote_missing_or_nonunique")
    start = atom["start_char"] + position
    end = start + len(quote)
    if primary and not any(t["start_char"] <= start < end <= t["end_char"] for t in targets):
        raise ValueError("primary_quote_outside_raw_target")
    return {"atom_id": atom["atom_id"], "case_id": atom["case_id"],
            "source_hash": atom["source_hash"], "start_char": start, "end_char": end, "quote": quote}


def _load(reviews):
    if isinstance(reviews, (dict, str, Path)):
        reviews = [reviews]
    documents = {}
    for value in reviews:
        if isinstance(value, (str, Path)):
            def strict_object(pairs):
                obj = {}
                for key, item in pairs:
                    if key in obj:
                        raise ValueError("duplicate_review_json_key:" + key)
                    obj[key] = item
                return obj
            value = json.loads(Path(value).read_text(encoding="utf-8-sig"), object_pairs_hook=strict_object)
        documents[_hash(value)] = copy.deepcopy(value)
    return documents


def build_review_template(reports, source_store, atom_root):
    """Return a strict pending sidecar plus source quote choices, no decisions.

    Primary is deliberately null, fields empty, and all checks unknown. Quotes
    are whole verified atoms with raw target bounds, never inferred ownership.
    """
    from .core import build_store
    store = build_store(reports, source_store, atom_root)
    entries, choices = [], []
    for candidate in store["candidates"]:
        p = candidate["provenance"]
        for digest in p["run_sha256"]:
            entries.append({"review_type": "au", "run_sha256": digest, "request_id": p["request_id"],
                "au_index": p["au_index"], "proposal_sha256": p["proposal_sha256"], "reason": "Pending agent review",
                "primary_proposition": None, "field_witnesses": {},
                "material_conditions": {"status": "unknown", "witnesses": []},
                "checks": {check: "unknown" for check in CHECKS}})
        choices.append({"candidate_id": candidate["candidate_id"], "request_id": p["request_id"],
            "au_index": p["au_index"], "proposal": candidate["proposal"],
            "selected_atoms": candidate["selected_evidence"]})
    for ledger in store["target_ledger"]:
        if "run_sha256" not in ledger:
            continue
        for digest in ledger["run_sha256"]:
            entries.append({"review_type": "target_omission", "run_sha256": digest,
                "request_id": ledger["request_id"], "proposal_sha256": ledger["proposal_sha256"],
                "reason": "Pending target omission review", "checks": {"omission": "unknown"}, "witnesses": []})
        choices.append({"request_id": ledger["request_id"], "source_refs": ledger["source_refs"],
            "target_ids": ledger["target_ids"], "run_sha256": ledger["run_sha256"]})
    review = {"artifact_type": "AUCandidateReview", "schema_version": "au-candidate-review-v1",
        "reviewer": {"reviewer_id": "pending", "reviewer_type": "agent", "producer": "pending",
            "version": "pending", "provenance": {"method": "pending source-based agent review",
                "input_artifacts": store["audit"]["run_ids"] or ["pending"]}}, "reviews": entries}
    return {"review": review, "quote_choices": {"artifact_type": "AUCandidateReviewQuoteChoices",
        "semantic_gold": False, "semantic_quality_claim": False, "rows": choices}}


def apply_reviews(store, reviews, *, source_store, atom_root):
    """Return a copy with strict agent review decisions, retaining all inputs.

    Reapplication unions sidecars with prior inputs: a later pass cannot erase
    a fail/unknown/stale review. Source and atom stores are reverified locally.
    Invalid files fail closed; malformed entries isolate by request/AU binding.
    """
    result = copy.deepcopy(store)
    documents = _load(result.get("review_inputs", []))
    documents.update(_load(reviews))
    result["review_inputs"] = [value for _, value in sorted(documents.items())]
    schema = json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    entry_validator = Draft202012Validator({"$defs": schema["$defs"], **schema["$defs"]["review"]})
    entries, audit_inputs = [], []
    for digest, document in sorted(documents.items()):
        errors = _errors(validator, document)
        audit_inputs.append({"review_sha256": digest, "errors": errors})
        # Envelope must be strict; entry errors are isolated to their binding.
        envelope = copy.deepcopy(document)
        if isinstance(envelope, dict):
            envelope["reviews"] = []
        envelope_errors = _errors(validator, envelope)
        if envelope_errors:
            raise ValueError("invalid_review_envelope: " + "; ".join(envelope_errors))
        for entry in document["reviews"]:
            entries.append((digest, document["reviewer"], entry, _errors(entry_validator, entry)))

    matched_entries = set()
    known_run_hashes = {digest for ledger in result["target_ledger"] for digest in ledger.get("run_sha256", [])}
    def relevant(record, kind):
        # Ignore unrelated rows, but retain stale hashes for this exact row/AU.
        matches = []
        for digest, reviewer, entry, errors in entries:
            if not isinstance(entry, dict):
                raise ValueError("unbound_invalid_review")
            if not isinstance(entry.get("request_id"), str) or entry.get("review_type") not in {"au", "target_omission"}:
                raise ValueError("unbound_invalid_review")
            if entry["request_id"] != record.get("request_id") or entry["review_type"] != kind:
                continue
            # Same request IDs legitimately recur across runs. A known other
            # run is unrelated; an unknown hash targeting this locator is stale.
            if entry.get("run_sha256") in known_run_hashes and entry["run_sha256"] not in record["run_sha256"]:
                continue
            if kind == "au" and entry.get("au_index") != record["au_index"]:
                if type(entry.get("au_index")) is not int:
                    raise ValueError("unbound_invalid_au_review")
                continue
            errors = list(errors)
            matched_entries.add((digest, _hash(entry)))
            if entry.get("run_sha256") not in record["run_sha256"]:
                errors.append("stale_run_sha256")
            if entry.get("proposal_sha256") != record["proposal_sha256"]:
                errors.append("stale_proposal_sha256")
            locator_count = sum(record["run_id"] == l["run_id"] and record["request_id"] == l.get("request_id")
                                for l in result["target_ledger"])
            if locator_count != 1:
                errors.append("ambiguous_request_binding")
            matches.append((digest, reviewer, entry, errors))
        return matches

    catalogs = {}
    for ledger in result["target_ledger"]:
        key = (ledger["run_id"], ledger["row_id"])
        try:
            atoms, _, targets = _catalog({"case_id": ledger["case_id"], "source_hash": ledger["source_hash"],
                "atom_binding": ledger["atom_binding"], "expected_target_ids": ledger["target_ids"],
                "source_refs": ledger["source_refs"]}, source_store, atom_root)
            catalogs[key] = (atoms, targets, [])
        except (ValueError, OSError, KeyError, TypeError) as exc:
            catalogs[key] = ({}, [], ["review_source_or_binding: " + str(exc)])
        matches = relevant(ledger, "target_omission") if "run_sha256" in ledger else []
        if not matches:
            continue
        atoms, targets, source_errors = catalogs[key]
        reasons, spans, fails = [], [], []
        signatures = set()
        for _, _, entry, errors in matches:
            reasons.extend(errors + source_errors)
            if errors:
                continue
            signatures.add(_hash({k: v for k, v in entry.items() if k != "reason"}))
            check = entry.get("checks", {}).get("omission")
            if check == "fail":
                fails.append("omission: " + entry["reason"])
            elif check != "pass":
                reasons.append("omission_check_missing_or_unknown")
            if not entry.get("witnesses"):
                reasons.append("omission_witness_required")
            for witness in entry.get("witnesses", []):
                try:
                    spans.append(_quote(witness, atoms, targets, primary=True))
                except ValueError as exc:
                    reasons.append(str(exc))
        if len(signatures) > 1:
            reasons.append("conflicting_reviews")
        if ledger.get("errors") or ledger.get("coverage_status") == "needs_split" or ledger.get("model_decision") == "unresolved":
            reasons.append("target_requires_resolution")
        ledger.update(target_omission_review="unresolved" if "conflicting_reviews" in reasons else "rejected" if fails else "unresolved" if reasons else "accepted_agent_reviewed",
                      omission_review_reasons=sorted(set(fails + reasons)), omission_witnesses=spans,
                      review_provenance=[{"review_sha256": d, "reviewer": r} for d, r, _, _ in matches],
                      semantic_gold=False, evidence_grade="agent_reviewed")

    for candidate in result["candidates"]:
        provenance = candidate["provenance"]
        matches = relevant(provenance, "au")
        if not matches:
            continue
        base_keys = ("status", "reasons", "ownership", "field_witnesses", "semantic_review", "accepted_semantic")
        base = candidate.setdefault("review_base", {k: copy.deepcopy(candidate[k]) for k in base_keys})
        candidate.update(copy.deepcopy(base))
        atoms, targets, source_errors = catalogs[(provenance["run_id"], provenance["row_id"])]
        selected = {aid: atoms[aid] for aid in candidate.get("evidence_ref_ids", []) if aid in atoms}
        reasons, fails, signatures, verified = [], [], set(), []
        for _, _, entry, errors in matches:
            reasons.extend(errors + source_errors)
            if errors:
                continue
            signatures.add(_hash({k: v for k, v in entry.items() if k != "reason"}))
            for check in CHECKS:
                verdict = entry.get("checks", {}).get(check)
                if verdict == "fail":
                    fails.append(check + ": " + entry["reason"])
                elif verdict != "pass":
                    reasons.append("check_missing_or_unknown:" + check)
            primary = None
            try:
                if entry.get("primary_proposition") is None:
                    raise ValueError("primary_proposition_required")
                primary = _quote(entry["primary_proposition"], selected, targets, primary=True)
            except ValueError as exc:
                reasons.append(str(exc))
            fields = {}
            required = {"claim", "kind", "speaker", "attribution_role"}
            if candidate["kind"] == "other":
                required.add("other_kind")
            supplied = entry.get("field_witnesses", {})
            for field in sorted(required | set(supplied)):
                if not supplied.get(field):
                    reasons.append("field_witness_required:" + field)
                    continue
                try:
                    fields[field] = [_quote(w, selected, targets) for w in supplied[field]]
                except ValueError as exc:
                    reasons.append(field + ": " + str(exc))
            conditions = entry.get("material_conditions")
            if not conditions or conditions["status"] == "unknown":
                reasons.append("material_conditions_missing_or_unknown")
            elif conditions["status"] == "present":
                if not conditions["witnesses"]:
                    reasons.append("material_condition_witness_required")
                try:
                    fields["material_conditions"] = [_quote(w, selected, targets) for w in conditions["witnesses"]]
                except ValueError as exc:
                    reasons.append("material_conditions: " + str(exc))
            verified.append((primary, fields, entry))
        if len(signatures) > 1:
            reasons.append("conflicting_reviews")
        # Review can resolve structural evidence padding ambiguity, never the
        # original producer's explicit need for context/splitting or bad labels.
        reasons.extend(r for r in base["reasons"] if r != "ambiguous_evidence_start")
        if candidate["structural_status"] != "valid":
            reasons.append("structural_invalid")
        rejected = candidate["structural_status"] != "valid" or (bool(fails) and "conflicting_reviews" not in reasons)
        status = "rejected" if rejected else "unresolved" if reasons else "accepted_agent_reviewed"
        candidate.update(status=status, accepted_semantic=status == "accepted_agent_reviewed",
                         semantic_review=status, semantic_gold=False, evidence_grade="agent_reviewed",
                         reasons=sorted(set(fails + reasons)),
                         review_provenance=[{"review_sha256": d, "reviewer": r} for d, r, _, _ in matches])
        if status == "accepted_agent_reviewed":
            primary, fields, entry = verified[0]
            candidate["ownership"].update(status="reviewed_owner", ownership_verified=True,
                ownership_review="agent_reviewed", primary_proposition_start=primary["start_char"],
                primary_proposition_start_available=True, primary_proposition_span=primary,
                evidence_atom_id=primary["atom_id"], anchor_char=primary["start_char"],
                rule="reviewer_primary_exact_quote_within_raw_target", flags=[])
            candidate["field_witnesses"] = {field: {"value": copy.deepcopy(candidate["proposal"].get(field)),
                "status": "AGENT_REVIEWED", "evidence_spans": spans, "source_verified": True,
                "entailment_validated": False, "semantic_review": "agent_reviewed"} for field, spans in fields.items()}
        if candidate.get("superseded_by"):
            candidate["status_before_supersession"] = candidate["status"]
            candidate.update(status="superseded", accepted_semantic=False)

    counts = Counter(c["status"] for c in result["candidates"])
    audit = result["audit"]
    for status in ("candidate", "rejected", "unresolved", "superseded"):
        audit[status + "_count"] = counts[status]
    au_reviewed = sum(bool(c.get("review_provenance")) for c in result["candidates"])
    omission_reviewed = sum(bool(l.get("review_provenance")) for l in result["target_ledger"])
    coverage_complete = au_reviewed == len(result["candidates"]) and omission_reviewed == len(result["target_ledger"])
    implementation_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                             for name in ("core.py", "reviews.py")}
    audit.update(accepted_count=counts["accepted_agent_reviewed"], review_inputs=audit_inputs,
        review_implementation_sha256=implementation_hashes,
        unmatched_reviews=[{"review_sha256": d, "entry_sha256": _hash(e), "reason": "unmatched_review_binding"}
                           for d, _, e, _ in entries if (d, _hash(e)) not in matched_entries],
        reviewed_au_count=au_reviewed, pending_au_review_count=len(result["candidates"]) - au_reviewed,
        reviewed_target_omission_count=omission_reviewed,
        pending_target_omission_review_count=len(result["target_ledger"]) - omission_reviewed,
        review_coverage_complete=coverage_complete,
        review_cache_key=_hash({"version": "au-candidate-review-v1", "schema": schema,
            "implementation_sha256": implementation_hashes,
            "runs": [l.get("run_sha256") for l in result["target_ledger"]], "reviews": sorted(documents)}),
        semantic_status="agent_reviewed_complete" if coverage_complete else "agent_reviewed_partial",
        ownership_status="reviewed_and_structural_candidates",
        verified_ownership_count=sum(bool(c.get("ownership", {}).get("ownership_verified")) for c in result["candidates"] if c.get("ownership")),
        primary_proposition_start_unavailable_count=sum(not c.get("ownership", {}).get("primary_proposition_start_available", False) for c in result["candidates"] if c.get("ownership")),
        limitations=["Host verifies exact source membership and ownership, not semantic truth.",
                     "Agent reviewed decisions are not human gold or a semantic quality claim.",
                     "Unreviewed AU and target omissions remain pending."])
    return result
