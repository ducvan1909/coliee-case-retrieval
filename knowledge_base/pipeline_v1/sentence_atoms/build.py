"""Build, validate, cache, and audit SentenceAtom maps for KOS-5."""

from __future__ import annotations

import html
import json
import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from ..source_contract import open_source
from ..structural_prepass import load_and_validate_block_map, validate_block_map
from .segmenter import FORBIDDEN_TYPES, canonical_hash, segment_case

EXPECTED_CASES = {"013009", "013948", "011904", "045155", "099980"}


class SentenceAtomError(ValueError):
    def __init__(self, detail: str, *, code: str = "sentence_atom_contract", location: str = "<root>"):
        self.code, self.location, self.detail = code, location, detail
        super().__init__(f"[{code}] {location}: {detail}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SentenceAtomError(str(exc), code="malformed_artifact", location=str(path)) from exc
    if not isinstance(value, dict):
        raise SentenceAtomError("JSON object required", code="malformed_artifact", location=str(path))
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = _load_json(Path(__file__).resolve().parents[1] / "contracts/sentence_atom.v1.json")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SentenceAtomError(str(exc), code="invalid_schema") from exc
    return Draft202012Validator(schema)


def _write_json(path: Path, value: Any, immutable: bool = False) -> str:
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if immutable and path.read_bytes() != data:
            raise SentenceAtomError("refusing to overwrite dependency-addressed artifact", code="immutable_conflict", location=str(path))
        if immutable:
            return "reused"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return "created"


def _artifact_path_check(atom_map: dict[str, Any], artifact_path: Path) -> None:
    expected = (
        atom_map["case_id"], atom_map["source_hash"], atom_map["sourceblock_map_cache_key"],
        f"{atom_map['segmenter_version']}-{atom_map['policy_sha256'][:16]}", "sentence_atom_map.json",
    )
    actual = tuple(artifact_path.parts[-5:])
    if actual != expected:
        raise SentenceAtomError(f"expected suffix {expected!r}, got {actual!r}", code="identity_mismatch", location="artifact_path")


def validate_sentence_atom_map(
    atom_map: dict[str, Any], text: str, sourceblock_map: dict[str, Any], policy: dict[str, Any],
    *, artifact_path: str | Path | None = None,
) -> dict[str, bool]:
    if not isinstance(atom_map, dict) or not isinstance(text, str) or not isinstance(sourceblock_map, dict) or not isinstance(policy, dict):
        raise SentenceAtomError("map/text/sourceblock/policy have wrong type", code="malformed_input")
    try:
        _validator().validate(atom_map)
    except ValidationError as exc:
        location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
        raise SentenceAtomError(exc.message, code="schema_violation", location=location) from exc
    try:
        validate_block_map(sourceblock_map, text)
    except Exception as exc:
        raise SentenceAtomError(str(exc), code="parent_sourceblock_invalid") from exc
    if artifact_path is not None:
        _artifact_path_check(atom_map, Path(artifact_path))

    policy_hash = canonical_hash(policy)
    expected = segment_case(text, sourceblock_map, policy, policy_hash)
    if atom_map != expected:
        for field in expected:
            if atom_map.get(field) != expected[field]:
                raise SentenceAtomError("value differs from deterministic producer", code="canonical_mismatch", location=field)
        raise SentenceAtomError("artifact differs from deterministic producer", code="canonical_mismatch")

    block_by_id = {block["block_id"]: block for block in sourceblock_map["blocks"]}
    atoms_by_block: dict[str, list[dict[str, Any]]] = defaultdict(list)
    protected_by_id = {item["protected_span_id"]: item for item in atom_map["protected_spans"]}
    for atom in atom_map["atoms"]:
        atoms_by_block[atom["parent_block_id"]].append(atom)
    for block in sourceblock_map["blocks"]:
        atoms = atoms_by_block[block["block_id"]]
        if not atoms:
            raise SentenceAtomError("parent block has no atom", code="coverage_failure", location=block["block_id"])
        cursor = block["span"]["start_char"]
        for order, atom in enumerate(atoms):
            ref = atom["span"]
            if atom["order_in_block"] != order or ref["start_char"] != cursor:
                raise SentenceAtomError("atom order/gap/overlap", code="coverage_failure", location=atom["atom_id"])
            cursor = ref["end_char"]
            for protected_id in atom["protected_span_refs"]:
                if protected_id not in protected_by_id:
                    raise SentenceAtomError("unknown protected span reference", code="identity_mismatch", location=atom["atom_id"])
        if cursor != block["span"]["end_char"]:
            raise SentenceAtomError("atoms do not cover parent block", code="coverage_failure", location=block["block_id"])

    atom_boundaries = {atom["span"]["end_char"] for atom in atom_map["atoms"]}
    for item in atom_map["protected_spans"]:
        block = block_by_id[item["parent_block_id"]]
        ref = item["span"]
        if not (block["span"]["start_char"] <= ref["start_char"] < ref["end_char"] <= block["span"]["end_char"]):
            raise SentenceAtomError("protected span escapes parent", code="offset_violation", location=item["protected_span_id"])
        expected_forbidden = item["span_type"] in FORBIDDEN_TYPES
        if item["boundary_forbidden"] != expected_forbidden or (item["protection_mode"] == "boundary_forbidden") != expected_forbidden:
            raise SentenceAtomError("protection mode/type mismatch", code="protected_span_mismatch", location=item["protected_span_id"])
        if expected_forbidden and any(ref["start_char"] < boundary <= ref["end_char"] for boundary in atom_boundaries if boundary != block["span"]["end_char"]):
            raise SentenceAtomError("atom boundary cuts forbidden span", code="protected_boundary_cut", location=item["protected_span_id"])

    for plan in atom_map["slice_plans"]:
        block = block_by_id[plan["parent_block_id"]]
        cursor = block["span"]["start_char"]
        for order, item in enumerate(plan["slices"]):
            if item["slice_order"] != order or item["span"]["start_char"] != cursor:
                raise SentenceAtomError("slice order/gap/overlap", code="slice_contract", location=plan["plan_id"])
            cursor = item["span"]["end_char"]
        if cursor != block["span"]["end_char"]:
            raise SentenceAtomError("slices do not cover parent", code="slice_contract", location=plan["plan_id"])

    return {
        "schema_valid": True, "parent_sourceblock_valid": True, "canonical_identity_and_provenance": True,
        "atom_parent_containment": True, "atom_exact_block_round_trip": True, "zero_atom_gap_overlap": True,
        "no_forbidden_boundary_cut": True, "protected_modes_explicit": True, "slice_plan_exact_parent_coverage": True,
        "artifact_path_matches_when_supplied": True,
    }


def load_and_validate_sentence_atom_map(path: str | Path, text: str, sourceblock_map: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bool]]:
    artifact_path = Path(path)
    value = _load_json(artifact_path)
    return value, validate_sentence_atom_map(value, text, sourceblock_map, policy, artifact_path=artifact_path)


def _audit_html(rows: list[dict[str, Any]], store: Path) -> str:
    parts = ["<!doctype html><meta charset='utf-8'><title>Plan 04 SentenceAtom audit</title>", "<style>body{font:14px system-ui;max-width:1200px;margin:auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:4px}code{white-space:pre-wrap}</style>", "<h1>Plan 04 SentenceAtom audit</h1><p>Previews are noncanonical. Raw immutable source remains authoritative.</p>"]
    for row in rows:
        text = open_source(store, row["case_id"], row["source_hash"])
        value = row["atom_map"]
        parts.append(f"<h2>{html.escape(row['case_id'])}</h2><table><tr><th>atom</th><th>block</th><th>span</th><th>protected</th><th>preview</th></tr>")
        for atom in value["atoms"]:
            ref = atom["span"]
            preview = text[ref["start_char"]:ref["end_char"]].replace("\r", "\\r").replace("\n", "\\n")[:180]
            parts.append(f"<tr><td>{atom['global_order']}</td><td>{atom['parent_block_order']}</td><td>[{ref['start_char']},{ref['end_char']})</td><td>{len(atom['protected_span_refs'])}</td><td><code>{html.escape(preview)}</code></td></tr>")
        parts.append("</table>")
    return "\n".join(parts) + "\n"


def build_sentence_atoms(*, source_store: str | Path, plan03_report: str | Path, plan03_independent_report: str | Path, policy_path: str | Path, output_root: str | Path, audit_path: str | Path | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    store, output = Path(source_store).resolve(), Path(output_root).resolve()
    report03, policy = _load_json(Path(plan03_report)), _load_json(Path(policy_path))
    try:
        independent_text = Path(plan03_independent_report).read_text(encoding="utf-8")
    except OSError as exc:
        raise SentenceAtomError(str(exc), code="dependency_missing") from exc
    if report03.get("status") != "pass" or "**PASS" not in independent_text or "fixed_verified" not in independent_text.lower():
        raise SentenceAtomError("Plan 03 implementation and independent gate must PASS", code="dependency_gate")
    if Path(report03["inputs"]["source_store"]).resolve() != store:
        raise SentenceAtomError("Plan 03 source store mismatch", code="dependency_gate")
    if len(report03.get("cases", [])) != 5 or {row["case_id"] for row in report03["cases"]} != EXPECTED_CASES:
        raise SentenceAtomError("Plan 03 report is not exact KOS-5", code="dependency_gate")

    policy_hash = canonical_hash(policy)
    results: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    for row in report03["cases"]:
        case_id, source_hash = row["case_id"], row["source_hash"]
        text = open_source(store, case_id, source_hash)
        sourceblock_path = Path(report03["outputs"]["output_root"]) / row["artifact_ref"]
        sourceblock_map, _ = load_and_validate_block_map(sourceblock_path, text, store)
        if sourceblock_map["parser_version"] != "sourceblock-rules-v1.3":
            raise SentenceAtomError("Plan 04 requires validated SourceBlock v1.3", code="dependency_gate", location=case_id)
        first = segment_case(text, sourceblock_map, policy, policy_hash)
        if first != segment_case(text, sourceblock_map, policy, policy_hash):
            raise SentenceAtomError("non-deterministic segmentation", code="determinism", location=case_id)
        artifact = output / "cases" / case_id / source_hash / sourceblock_map["cache_key"] / f"{policy['segmenter_version']}-{policy_hash[:16]}" / "sentence_atom_map.json"
        checks = validate_sentence_atom_map(first, text, sourceblock_map, policy, artifact_path=artifact)
        action = _write_json(artifact, first, immutable=True)
        protected_counts = dict(sorted(Counter(item["span_type"] for item in first["protected_spans"]).items()))
        mode_counts = dict(sorted(Counter(item["protection_mode"] for item in first["protected_spans"]).items()))
        event_counts = dict(sorted(Counter(item["event_type"] for item in first["segmenter_events"]).items()))
        ledger.extend(first["segmenter_events"])
        results.append({"case_id": case_id, "source_hash": source_hash, "sourceblock_cache_key": sourceblock_map["cache_key"], "cache_key": first["cache_key"], "artifact_ref": artifact.relative_to(output).as_posix(), "artifact_action": action, "source_characters": len(text), "sourceblock_count": len(sourceblock_map["blocks"]), "atom_count": len(first["atoms"]), "protected_span_count": len(first["protected_spans"]), "protected_span_type_counts": protected_counts, "protection_mode_counts": mode_counts, "slice_plan_count": len(first["slice_plans"]), "slice_count": sum(len(plan["slices"]) for plan in first["slice_plans"]), "review_event_count": sum(event["severity"] == "review" for event in first["segmenter_events"]), "error_event_count": sum(event["severity"] == "error" for event in first["segmenter_events"]), "event_type_counts": event_counts, "checks": checks, "atom_map": first})

    ledger_path = output / "segmenter_event_ledger.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in ledger), encoding="utf-8")
    manifest = {"build_manifest_version": "sentence-atom-build-v1", "status": "pass", "workload": "KOS-5", "segmenter_version": policy["segmenter_version"], "policy_sha256": policy_hash, "cache_key_fields": ["case_id", "source_hash", "sourceblock_map_cache_key", "segmenter_version", "policy_sha256"], "cases": [{key: value for key, value in row.items() if key != "atom_map"} for row in results]}
    _write_json(output / "sentence_atom_build_manifest.json", manifest)
    if audit_path:
        audit = Path(audit_path); audit.parent.mkdir(parents=True, exist_ok=True); audit.write_text(_audit_html(results, store), encoding="utf-8")
    elapsed = max(time.perf_counter() - started, 1e-9)
    gates = {"plan03_independent_pass": True, "exact_kos5": True, "source_parent_hash_checked_before_segment": True, "sourceblock_marker_content_identity_inherited": True, "atom_coverage_round_trip_100_percent": all(all(row["checks"].values()) for row in results), "zero_forbidden_boundary_cuts": True, "deterministic_ids_order": True, "zero_segmenter_errors": all(row["error_event_count"] == 0 for row in results), "dependency_addressed_cache": True}
    rows = [{key: value for key, value in row.items() if key != "atom_map"} for row in results]
    aggregate_types = Counter()
    aggregate_events = Counter()
    for row in results:
        aggregate_types.update(row["protected_span_type_counts"])
        aggregate_events.update(row["event_type_counts"])
    return {"report_version": "plan04-sentence-atom-validation-v1", "status": "pass" if all(gates.values()) else "fail", "scope": "KOS-5 raw source through validated SourceBlock v1.3; local deterministic; KOS artifacts audit-only", "inputs": {"source_store": str(store), "plan03_report": str(Path(plan03_report).resolve()), "plan03_independent_report": str(Path(plan03_independent_report).resolve()), "policy": str(Path(policy_path).resolve())}, "outputs": {"output_root": str(output), "build_manifest": str((output / "sentence_atom_build_manifest.json").resolve()), "event_ledger": str(ledger_path.resolve()), "audit_html": str(Path(audit_path).resolve()) if audit_path else None}, "summary": {"case_count": len(results), "source_characters": sum(row["source_characters"] for row in results), "atom_count": sum(row["atom_count"] for row in results), "protected_span_count": sum(row["protected_span_count"] for row in results), "slice_plan_count": sum(row["slice_plan_count"] for row in results), "slice_count": sum(row["slice_count"] for row in results), "review_event_count": sum(row["review_event_count"] for row in results), "error_event_count": sum(row["error_event_count"] for row in results), "elapsed_seconds": elapsed, "characters_per_second": sum(row["source_characters"] for row in results) / elapsed}, "hard_case_audit": {"protected_span_type_counts": dict(sorted(aggregate_types.items())), "event_type_counts": dict(sorted(aggregate_events.items())), "abbreviation_and_initial_rules_exercised": aggregate_types["abbreviation"] + aggregate_types["initial"], "citation_and_case_name_rules_exercised": aggregate_types["citation_year"] + aggregate_types["reporter_citation"] + aggregate_types["case_name"], "marker_and_list_rules_exercised": aggregate_types["paragraph_marker"] + aggregate_types["list_marker"], "quotation_context_observations": aggregate_types["balanced_quotation"] + aggregate_types["unbalanced_quotation"], "interpretation": "observed rule matches and review events, not sentence gold"}, "gates": gates, "cases": rows, "limitations": ["SentenceAtom is an address, not a legal or semantic unit.", "Protected-span rules are deterministic candidates and are not corpus-wide gold.", "Balanced quotation and newline layout are context-only; they do not forbid internal sentence boundaries.", "Derived slices are workload plans only and do not create SourceBlock, LegalUnit, candidate, or materialized text.", "Only KOS-5 formats were audited; semantic segmentation quality beyond hard cases is unproven."]}
