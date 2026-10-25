"""Build, validate, cache, and audit Plan 05 sidecars."""

from __future__ import annotations

import html
import json
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from ..sentence_atoms import load_and_validate_sentence_atom_map, validate_sentence_atom_map
from ..sentence_atoms.segmenter import canonical_hash
from ..source_contract import open_source
from ..structural_prepass import load_and_validate_block_map
from .workers import run_sidecar_workers

EXPECTED_CASES = {"013009", "013948", "011904", "045155", "099980"}


class SidecarError(ValueError):
    def __init__(self, detail: str, *, code: str = "sidecar_contract", location: str = "<root>"):
        self.code, self.location, self.detail = code, location, detail
        super().__init__(f"[{code}] {location}: {detail}")


def _load_json(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise SidecarError(str(exc), code="malformed_artifact", location=str(path)) from exc
    if not isinstance(value, dict): raise SidecarError("JSON object required", code="malformed_artifact", location=str(path))
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = _load_json(Path(__file__).resolve().parents[1] / "contracts/sidecar.v1.json")
    try: Draft202012Validator.check_schema(schema)
    except SchemaError as exc: raise SidecarError(str(exc), code="invalid_schema") from exc
    return Draft202012Validator(schema)


def _write_json(path: Path, value: Any, immutable: bool = False) -> str:
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if immutable and path.read_bytes() != data: raise SidecarError("refusing to overwrite dependency-addressed artifact", code="immutable_conflict", location=str(path))
        if immutable: return "reused"
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp"); temporary.write_bytes(data); temporary.replace(path); return "created"


def validate_sidecar_map(value: dict[str, Any], text: str, sourceblocks: dict[str, Any], atoms: dict[str, Any], policy: dict[str, Any], sentence_policy: dict[str, Any], *, artifact_path: str | Path | None = None) -> dict[str, bool]:
    if not all(isinstance(item, dict) for item in (value, sourceblocks, atoms, policy, sentence_policy)) or not isinstance(text, str): raise SidecarError("wrong input type", code="malformed_input")
    try: _validator().validate(value)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"; raise SidecarError(exc.message, code="schema_violation", location=location) from exc
    try: validate_sentence_atom_map(atoms, text, sourceblocks, sentence_policy)
    except Exception as exc: raise SidecarError(str(exc), code="dependency_invalid") from exc
    policy_hash = canonical_hash(policy)
    failed = {run["worker_type"] for run in value["worker_runs"] if run["status"] == "failed"}
    expected = run_sidecar_workers(text, sourceblocks, atoms, policy, policy_hash, failed)
    if value != expected:
        for field in expected:
            if value.get(field) != expected[field]: raise SidecarError("value differs from deterministic producer", code="canonical_mismatch", location=field)
        raise SidecarError("artifact differs from deterministic producer", code="canonical_mismatch")
    if artifact_path is not None:
        path = Path(artifact_path)
        dependency_dir = f"{value['worker_bundle_version']}-{value['policy_sha256'][:16]}"
        if value["failed_workers"]: dependency_dir += f"-partial-{canonical_hash(value['failed_workers'])[:12]}"
        expected_suffix = (value["case_id"], value["source_hash"], value["sourceblock_cache_key"], value["sentence_atom_cache_key"], dependency_dir, "sidecar_map.json")
        if tuple(path.parts[-6:]) != expected_suffix: raise SidecarError("artifact path does not match dependencies", code="identity_mismatch", location="artifact_path")
    annotation_ids = [item["annotation_id"] for item in value["annotations"]]
    relation_ids = [item["relation_id"] for item in value["relations"]]
    if len(annotation_ids) != len(set(annotation_ids)) or len(relation_ids) != len(set(relation_ids)): raise SidecarError("duplicate canonical ID", code="duplicate_id")
    block_ids = {block["block_id"] for block in sourceblocks["blocks"]}; atom_ids = {atom["atom_id"] for atom in atoms["atoms"]}
    for index, annotation in enumerate(value["annotations"]):
        ref = annotation["span"]
        if annotation["block_id"] not in block_ids or any(atom not in atom_ids for atom in annotation["atom_refs"]): raise SidecarError("unknown block/atom ref", code="identity_mismatch", location=f"annotations.{index}")
        if not (0 <= ref["start_char"] < ref["end_char"] <= len(text)): raise SidecarError("annotation span out of bounds", code="offset_violation", location=f"annotations.{index}.span")
    forbidden_relations = {"qualifies", "responds_to", "condition_for", "same_legal_point"}
    for index, relation in enumerate(value["relations"]):
        if relation["relation_type"] in forbidden_relations: raise SidecarError("semantic relation forbidden", code="scope_violation", location=f"relations.{index}")
        for ref in relation["evidence_spans"]:
            if not (0 <= ref["start_char"] < ref["end_char"] <= len(text)): raise SidecarError("relation evidence out of bounds", code="offset_violation", location=f"relations.{index}")
        if relation["relation_type"] == "governed_by_heading" and relation["status"] != "candidate": raise SidecarError("heading governance cannot be accepted", code="scope_violation", location=f"relations.{index}.status")
    return {"schema_valid": True, "dependencies_validated": True, "canonical_ids_provenance": True, "annotation_spans_exact_in_bounds": True, "relation_evidence_exact_in_bounds": True, "no_duplicate_conflicting_ids": True, "adjacency_not_materialized": value["adjacency_policy"]["materialized"] is False, "no_semantic_relations": True, "artifact_path_matches_when_supplied": True, "worker_failure_isolation_contract": True}


def load_and_validate_sidecar_map(path: str | Path, text: str, sourceblocks: dict[str, Any], atoms: dict[str, Any], policy: dict[str, Any], sentence_policy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bool]]:
    artifact = Path(path); value = _load_json(artifact); return value, validate_sidecar_map(value, text, sourceblocks, atoms, policy, sentence_policy, artifact_path=artifact)


def _audit_html(rows: list[dict[str, Any]], store: Path) -> str:
    parts = ["<!doctype html><meta charset='utf-8'><title>Plan 05 sidecar audit</title>", "<style>body{font:14px system-ui;max-width:1200px;margin:auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:4px}code{white-space:pre-wrap}</style>", "<h1>Plan 05 sidecar audit</h1><p>Previews are runtime exact-source views, not materialized artifact text.</p>"]
    for row in rows:
        text = open_source(store, row["case_id"], row["source_hash"]); value = row["map"]
        parts.append(f"<h2>{html.escape(row['case_id'])}</h2><table><tr><th>worker</th><th>type</th><th>status</th><th>span</th><th>preview</th></tr>")
        for item in value["annotations"]:
            ref = item["span"]; preview = text[ref["start_char"]:ref["end_char"]].replace("\r", "\\r").replace("\n", "\\n")[:160]
            parts.append(f"<tr><td>{item['worker_type']}</td><td>{item['annotation_type']}</td><td>{item['status']}</td><td>[{ref['start_char']},{ref['end_char']})</td><td><code>{html.escape(preview)}</code></td></tr>")
        parts.append("</table>")
    return "\n".join(parts) + "\n"


def build_sidecars(*, source_store: str | Path, plan03_report: str | Path, plan04_report: str | Path, plan04_independent_report: str | Path, sourceblock_policy: str | Path, sentence_policy: str | Path, policy_path: str | Path, output_root: str | Path, audit_path: str | Path | None = None, fault_workers: set[str] | None = None) -> dict[str, Any]:
    started = time.perf_counter(); store, output = Path(source_store).resolve(), Path(output_root).resolve()
    report03, report04, policy, sentence_pol, sourceblock_pol = _load_json(Path(plan03_report)), _load_json(Path(plan04_report)), _load_json(Path(policy_path)), _load_json(Path(sentence_policy)), _load_json(Path(sourceblock_policy))
    independent = Path(plan04_independent_report).read_text(encoding="utf-8")
    if report03.get("status") != "pass" or report04.get("status") != "pass" or "**PASS" not in independent: raise SidecarError("Plan 03/04 dependencies and Plan 04 independent verdict must PASS", code="dependency_gate")
    if {row["case_id"] for row in report04["cases"]} != EXPECTED_CASES: raise SidecarError("Plan 04 is not exact KOS-5", code="dependency_gate")
    policy_hash = canonical_hash(policy); rows = []
    report03_cases = {row["case_id"]: row for row in report03["cases"]}
    for atom_row in report04["cases"]:
        case_id, source_hash = atom_row["case_id"], atom_row["source_hash"]; text = open_source(store, case_id, source_hash)
        block_row = report03_cases[case_id]; block_path = Path(report03["outputs"]["output_root"]) / block_row["artifact_ref"]
        blocks, _ = load_and_validate_block_map(block_path, text, store)
        if canonical_hash(sourceblock_pol) != blocks["policy_sha256"]: raise SidecarError("SourceBlock policy file does not match parent artifact", code="dependency_gate", location=case_id)
        atom_path = Path(report04["outputs"]["output_root"]) / atom_row["artifact_ref"]
        atoms, _ = load_and_validate_sentence_atom_map(atom_path, text, blocks, sentence_pol)
        value = run_sidecar_workers(text, blocks, atoms, policy, policy_hash, fault_workers)
        dependency_dir = f"{policy['worker_bundle_version']}-{policy_hash[:16]}"
        if value["failed_workers"]: dependency_dir += f"-partial-{canonical_hash(value['failed_workers'])[:12]}"
        artifact = output / "cases" / case_id / source_hash / blocks["cache_key"] / atoms["cache_key"] / dependency_dir / "sidecar_map.json"
        checks = validate_sidecar_map(value, text, blocks, atoms, policy, sentence_pol, artifact_path=artifact)
        action = _write_json(artifact, value, immutable=True)
        rows.append({"case_id": case_id, "source_hash": source_hash, "artifact_ref": artifact.relative_to(output).as_posix(), "artifact_action": action, "annotation_count": len(value["annotations"]), "annotation_worker_counts": dict(sorted(Counter(item["worker_type"] for item in value["annotations"]).items())), "annotation_type_counts": dict(sorted(Counter(item["annotation_type"] for item in value["annotations"]).items())), "annotation_status_counts": dict(sorted(Counter(item["status"] for item in value["annotations"]).items())), "annotation_review_count": sum(item["status"] == "review" for item in value["annotations"]), "relation_count": len(value["relations"]), "relation_type_counts": dict(sorted(Counter(item["relation_type"] for item in value["relations"]).items())), "relation_status_counts": dict(sorted(Counter(item["status"] for item in value["relations"]).items())), "worker_event_count": len(value["worker_events"]), "review_event_count": sum(item["severity"] == "review" for item in value["worker_events"]), "error_event_count": sum(item["severity"] == "error" for item in value["worker_events"]), "worker_runs": value["worker_runs"], "checks": checks, "map": value})
    ledger = [event for row in rows for event in row["map"]["worker_events"]]; ledger_path = output / "worker_event_ledger.jsonl"; ledger_path.parent.mkdir(parents=True, exist_ok=True); ledger_path.write_text("".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in ledger), encoding="utf-8")
    manifest = {"build_manifest_version": "sidecar-build-v1", "status": "partial" if any(row["error_event_count"] for row in rows) else "pass", "workload": "KOS-5", "worker_bundle_version": policy["worker_bundle_version"], "policy_sha256": policy_hash, "cache_key_fields": ["case_id", "source_hash", "sourceblock_cache_key", "sentence_atom_cache_key", "worker_bundle_version", "policy_sha256"], "cases": [{key: value for key, value in row.items() if key != "map"} for row in rows]}; _write_json(output / "sidecar_build_manifest.json", manifest)
    if audit_path: audit = Path(audit_path); audit.parent.mkdir(parents=True, exist_ok=True); audit.write_text(_audit_html(rows, store), encoding="utf-8")
    elapsed = max(time.perf_counter() - started, 1e-9); report_rows = [{key: value for key, value in row.items() if key != "map"} for row in rows]
    gates = {"plan04_independent_pass": True, "exact_kos5": True, "dependencies_hash_path_validated_before_workers": True, "annotation_relation_exact_spans": all(all(row["checks"].values()) for row in rows), "canonical_ids_provenance": True, "no_duplicate_conflicting_ids": True, "no_semantic_graph_relations": True, "worker_failure_isolated": True, "zero_worker_errors": all(row["error_event_count"] == 0 for row in rows), "dependency_addressed_cache": True}
    aggregate_workers, aggregate_annotation_status, aggregate_relation_types, aggregate_relation_status = Counter(), Counter(), Counter(), Counter()
    for row in rows:
        aggregate_workers.update(row["annotation_worker_counts"]); aggregate_annotation_status.update(row["annotation_status_counts"]); aggregate_relation_types.update(row["relation_type_counts"]); aggregate_relation_status.update(row["relation_status_counts"])
    return {"report_version": "plan05-sidecar-validation-v1", "status": "pass" if all(gates.values()) else "fail", "scope": "KOS-5 local deterministic sidecars; no model/LLM; KOS artifacts audit-only", "inputs": {"source_store": str(store), "plan03_report": str(Path(plan03_report).resolve()), "plan04_report": str(Path(plan04_report).resolve()), "plan04_independent_report": str(Path(plan04_independent_report).resolve()), "policy": str(Path(policy_path).resolve())}, "outputs": {"output_root": str(output), "build_manifest": str((output / "sidecar_build_manifest.json").resolve()), "worker_event_ledger": str(ledger_path.resolve()), "audit_html": str(Path(audit_path).resolve()) if audit_path else None}, "summary": {"case_count": len(rows), "annotation_count": sum(row["annotation_count"] for row in rows), "annotation_worker_counts": dict(sorted(aggregate_workers.items())), "annotation_status_counts": dict(sorted(aggregate_annotation_status.items())), "annotation_review_count": sum(row["annotation_review_count"] for row in rows), "relation_count": sum(row["relation_count"] for row in rows), "relation_type_counts": dict(sorted(aggregate_relation_types.items())), "relation_status_counts": dict(sorted(aggregate_relation_status.items())), "worker_event_count": sum(row["worker_event_count"] for row in rows), "review_event_count": sum(row["review_event_count"] for row in rows), "error_event_count": sum(row["error_event_count"] for row in rows), "elapsed_seconds": elapsed, "characters_per_second": sum(len(open_source(store, row["case_id"], row["source_hash"])) for row in rows) / elapsed}, "gates": gates, "cases": report_rows, "metrics_not_reported": ["precision", "recall", "F1"], "metrics_reason": "No adjudicated Plan 05 annotation/relation gold exists; counts and error audit only.", "limitations": ["Annotations are observed/candidate/review sidecars, not legal conclusions.", "Speaker cues do not assign speaker or attribution.", "Citation/reference candidates do not identify authority, treatment, noticed case, or relevance.", "Heading governance remains candidate-only and no mandatory tree is created.", "Adjacency is reconstructed from SourceBlock order and is not materialized.", "No NER/model, ContextHint, AnalysisRegion, LegalUnit, AU, Issue, NN, retrieval, or LLM is implemented."]}
