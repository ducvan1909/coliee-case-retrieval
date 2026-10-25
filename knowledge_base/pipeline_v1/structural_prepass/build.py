"""Build, cache, validate, and audit KOS-5 SourceBlock maps."""

from __future__ import annotations

import hashlib
import html
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from ..source_contract import SpanRef, open_source, open_span
from .parser import (
    EVENT_CONTRACT_VERSION,
    EVENT_SPECS,
    block_id_for,
    cache_key_for,
    event_id_for,
    parse_source,
)

EXPECTED_CASES = {"013009", "013948", "011904", "045155", "099980"}


class StructuralPrepassError(ValueError):
    """Controlled structural-contract failure with a stable code and location."""

    def __init__(self, detail: str, *, code: str = "structural_contract", location: str = "<root>"):
        self.code = code
        self.location = location
        self.detail = detail
        super().__init__(f"[{code}] {location}: {detail}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StructuralPrepassError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StructuralPrepassError(f"JSON object required: {path}")
    return value


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    path = Path(__file__).resolve().parents[1] / "contracts" / "sourceblock.v1.json"
    schema = _load_json(path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise StructuralPrepassError(f"invalid SourceBlock schema: {exc}") from exc
    return Draft202012Validator(schema)


def _write_json(path: Path, value: Any, *, immutable: bool = False) -> str:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if immutable and path.read_bytes() != encoded:
            raise StructuralPrepassError(f"refusing to overwrite dependency-addressed artifact: {path}")
        if immutable:
            return "reused"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return "created"


def _identity_error(detail: str, location: str) -> StructuralPrepassError:
    return StructuralPrepassError(detail, code="identity_mismatch", location=location)


def _check_span_identity(
    ref: dict[str, Any], *, case_id: str, source_hash: str, location: str
) -> None:
    if ref["case_id"] != case_id:
        raise _identity_error(f"case_id must equal map case_id {case_id}", f"{location}.case_id")
    if ref["source_hash"] != source_hash:
        raise _identity_error(
            f"source_hash must equal map source_hash {source_hash}", f"{location}.source_hash"
        )


def _check_artifact_path(block_map: dict[str, Any], artifact_path: str | Path) -> None:
    path = Path(artifact_path)
    expected_dependency_dir = (
        f"{block_map['parser_version']}-{block_map['policy_sha256'][:16]}"
    )
    expected_suffix = (
        block_map["case_id"],
        block_map["source_hash"],
        expected_dependency_dir,
        "block_map.json",
    )
    actual_suffix = tuple(part for part in path.parts[-4:])
    if actual_suffix != expected_suffix:
        raise _identity_error(
            f"artifact suffix must be {expected_suffix!r}, got {actual_suffix!r}",
            "artifact_path",
        )


def validate_block_map(
    block_map: dict[str, Any],
    text: str,
    store_root: str | Path | None = None,
    artifact_path: str | Path | None = None,
) -> dict[str, bool]:
    if not isinstance(block_map, dict):
        raise StructuralPrepassError(
            "SourceBlock map must be an object", code="malformed_artifact", location="<root>"
        )
    if not isinstance(text, str):
        raise StructuralPrepassError(
            "decoded source must be a string", code="malformed_input", location="text"
        )
    try:
        _validator().validate(block_map)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise StructuralPrepassError(
            exc.message, code="schema_violation", location=location
        ) from exc

    case_id = block_map["case_id"]
    source_hash = block_map["source_hash"]
    parser_version = block_map["parser_version"]
    policy_sha256 = block_map["policy_sha256"]
    expected_cache_key = cache_key_for(case_id, source_hash, parser_version, policy_sha256)
    if block_map["cache_key"] != expected_cache_key:
        raise _identity_error(
            f"cache_key must be canonical value {expected_cache_key}", "cache_key"
        )
    if artifact_path is not None:
        _check_artifact_path(block_map, artifact_path)

    blocks = block_map["blocks"]
    expected_start = 0
    opened: list[str] = []
    ids: set[str] = set()
    for order, block in enumerate(blocks):
        span = block["span"]
        location = f"blocks.{order}"
        if block["order"] != order:
            raise _identity_error(f"order must be canonical ordinal {order}", f"{location}.order")
        if block["block_id"] in ids:
            raise _identity_error("block_id must be unique", f"{location}.block_id")
        for field, expected in (
            ("case_id", case_id),
            ("source_hash", source_hash),
            ("parser_version", parser_version),
            ("policy_sha256", policy_sha256),
        ):
            if block[field] != expected:
                raise _identity_error(
                    f"must equal map {field} {expected}", f"{location}.{field}"
                )
        for span_field in ("span", "content_span", "marker_span"):
            ref = block[span_field]
            if ref is not None:
                _check_span_identity(
                    ref, case_id=case_id, source_hash=source_hash, location=f"{location}.{span_field}"
                )
        expected_block_id = block_id_for(
            case_id=case_id,
            source_hash=source_hash,
            parser_version=parser_version,
            policy_sha256=policy_sha256,
            order=order,
            start_char=span["start_char"],
            end_char=span["end_char"],
            block_type=block["block_type"],
        )
        if block["block_id"] != expected_block_id:
            raise _identity_error(
                f"block_id must be canonical value {expected_block_id}", f"{location}.block_id"
            )
        ids.add(block["block_id"])
        if span["start_char"] != expected_start or span["end_char"] < span["start_char"]:
            raise StructuralPrepassError(f"gap/overlap at block {order}: expected {expected_start}, got {span}")
        expected_start = span["end_char"]
        for field in ("content_span", "marker_span"):
            nested = block[field]
            if nested is not None and not (span["start_char"] <= nested["start_char"] <= nested["end_char"] <= span["end_char"]):
                raise StructuralPrepassError(f"{field} escapes block {order}")
        for nested_index, nested in enumerate(block["nested_spans"]):
            ref = nested["span"]
            nested_location = f"{location}.nested_spans.{nested_index}"
            _check_span_identity(
                ref, case_id=case_id, source_hash=source_hash, location=f"{nested_location}.span"
            )
            if nested["producer_version"] != parser_version:
                raise _identity_error(
                    f"producer_version must equal map parser_version {parser_version}",
                    f"{nested_location}.producer_version",
                )
            if not (span["start_char"] <= ref["start_char"] <= ref["end_char"] <= span["end_char"]):
                raise StructuralPrepassError(f"nested span escapes block {order}")
        if store_root is None:
            opened.append(text[span["start_char"] : span["end_char"]])
        else:
            opened.append(open_span(store_root, SpanRef(block_map["case_id"], block_map["source_hash"], span["start_char"], span["end_char"])))
    event_ids: set[str] = set()
    for event_index, event in enumerate(block_map["parser_events"]):
        location = f"parser_events.{event_index}"
        for field, expected in (
            ("case_id", case_id),
            ("source_hash", source_hash),
            ("parser_version", parser_version),
            ("policy_sha256", policy_sha256),
            ("event_contract_version", EVENT_CONTRACT_VERSION),
        ):
            if event[field] != expected:
                raise _identity_error(
                    f"must equal map {field} {expected}", f"{location}.{field}"
                )
        ref = event["span"]
        _check_span_identity(
            ref, case_id=case_id, source_hash=source_hash, location=f"{location}.span"
        )
        if not (0 <= ref["start_char"] <= ref["end_char"] <= len(text)):
            raise StructuralPrepassError(
                "event span is outside source", code="offset_violation", location=f"{location}.span"
            )
        block_order = event["block_order"]
        if not (0 <= block_order < len(blocks)):
            raise _identity_error("block_order does not identify a block", f"{location}.block_order")
        related_block = blocks[block_order]
        if event["block_id"] != related_block["block_id"]:
            raise _identity_error(
                "block_id does not match block_order", f"{location}.block_id"
            )
        related_span = related_block["span"]
        if not (
            related_span["start_char"]
            <= ref["start_char"]
            <= ref["end_char"]
            <= related_span["end_char"]
        ):
            raise StructuralPrepassError(
                "event span is outside related block",
                code="offset_violation",
                location=f"{location}.span",
            )
        spec = EVENT_SPECS[event["event_type"]]
        for field in ("severity", "message_code", "message"):
            if event[field] != spec[field]:
                raise _identity_error(
                    f"must equal canonical {event['event_type']} value {spec[field]!r}",
                    f"{location}.{field}",
                )
        expected_event_id = event_id_for(
            case_id=case_id,
            source_hash=source_hash,
            parser_version=parser_version,
            policy_sha256=policy_sha256,
            block_id=event["block_id"],
            block_order=block_order,
            event_type=event["event_type"],
            severity=event["severity"],
            message_code=event["message_code"],
            message=event["message"],
            start_char=ref["start_char"],
            end_char=ref["end_char"],
        )
        if event["event_id"] != expected_event_id or event["event_id"] in event_ids:
            raise _identity_error(
                f"event_id must be unique canonical value {expected_event_id}",
                f"{location}.event_id",
            )
        event_ids.add(event["event_id"])

    checks = {
        "schema_valid": True,
        "canonical_cache_identity": True,
        "canonical_block_identity_and_provenance": True,
        "canonical_event_identity_and_provenance": True,
        "artifact_path_matches_metadata_when_supplied": True,
        "coverage_100_percent": expected_start == len(text) == block_map["source_char_length"],
        "zero_gap_overlap": (not text and not blocks) or bool(blocks),
        "exact_ordered_round_trip": "".join(opened) == text,
        "stable_unique_ids_and_order": len(ids) == len(blocks),
        "no_materialized_relations": block_map["relations"] == [],
    }
    if not all(checks.values()):
        raise StructuralPrepassError(f"structural gate failed: {checks}")
    return checks


def load_and_validate_block_map(
    artifact_path: str | Path, text: str, store_root: str | Path | None = None
) -> tuple[dict[str, Any], dict[str, bool]]:
    """Read an artifact with controlled errors, then validate path and full identity."""
    path = Path(artifact_path)
    block_map = _load_json(path)
    checks = validate_block_map(
        block_map, text, store_root=store_root, artifact_path=path
    )
    return block_map, checks


def _verify_dependencies(store_root: Path, store_manifest_path: Path, plan02_report_path: Path) -> list[dict[str, Any]]:
    manifest = _load_json(store_manifest_path)
    report = _load_json(plan02_report_path)
    if manifest.get("status") != "pass" or manifest.get("workload") != "KOS-5":
        raise StructuralPrepassError("source-store manifest must be PASS KOS-5")
    if report.get("status") != "pass" or report.get("summary", {}).get("round_trip_hash_offset_rate") != 1.0:
        raise StructuralPrepassError("Plan 02 report must PASS at rate 1.0")
    if Path(report.get("source_store", "")).resolve() != store_root.resolve():
        raise StructuralPrepassError("Plan 02 report references a different source store")
    cases = manifest.get("cases", [])
    if len(cases) != 5 or {row.get("case_id") for row in cases} != EXPECTED_CASES:
        raise StructuralPrepassError("source-store manifest must contain exactly KOS-5")
    return cases


def _audit_html(rows: list[dict[str, Any]], store_root: Path) -> str:
    sections = ["<!doctype html><meta charset='utf-8'><title>Plan 03 SourceBlock audit</title>",
                "<style>body{font:14px system-ui;max-width:1200px;margin:2rem auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.35rem;text-align:left}code{white-space:pre-wrap}</style>",
                "<h1>Plan 03 SourceBlock audit</h1><p>Previews are noncanonical audit views. Exact text remains in the immutable source store.</p>"]
    for row in rows:
        block_map = row["block_map"]
        text = open_source(store_root, row["case_id"], row["source_hash"])
        sections.append(f"<h2>Case {html.escape(row['case_id'])}</h2><table><tr><th>#</th><th>type</th><th>span</th><th>preview</th></tr>")
        for block in block_map["blocks"]:
            span = block["span"]
            preview = text[span["start_char"]:span["end_char"]].replace("\r", "\\r").replace("\n", "\\n")[:180]
            sections.append(f"<tr><td>{block['order']}</td><td>{html.escape(block['block_type'])}</td><td>[{span['start_char']},{span['end_char']})</td><td><code>{html.escape(preview)}</code></td></tr>")
        sections.append("</table>")
    return "\n".join(sections) + "\n"


def build_source_blocks(
    *,
    store_root: str | Path,
    store_manifest_path: str | Path,
    plan02_report_path: str | Path,
    policy_path: str | Path,
    output_root: str | Path,
    audit_path: str | Path | None = None,
) -> dict[str, Any]:
    store = Path(store_root).resolve()
    output = Path(output_root).resolve()
    policy = _load_json(Path(policy_path))
    policy_hash = _canonical_hash(policy)
    parser_version = policy.get("parser_version")
    if not isinstance(parser_version, str) or not parser_version:
        raise StructuralPrepassError("policy parser_version is required")
    cases = _verify_dependencies(store, Path(store_manifest_path), Path(plan02_report_path))
    results: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []

    for row in cases:
        case_id, source_hash = row["case_id"], row["source_hash"]
        text = open_source(store, case_id, source_hash)  # hash gate before parse
        first = parse_source(text=text, case_id=case_id, source_hash=source_hash, policy=policy, policy_sha256=policy_hash)
        second = parse_source(text=text, case_id=case_id, source_hash=source_hash, policy=policy, policy_sha256=policy_hash)
        if first != second:
            raise StructuralPrepassError(f"non-deterministic parse for {case_id}")
        artifact = output / "cases" / case_id / source_hash / f"{parser_version}-{policy_hash[:16]}" / "block_map.json"
        checks = validate_block_map(first, text, store, artifact_path=artifact)
        action = _write_json(artifact, first, immutable=True)
        counts = dict(sorted(Counter(block["block_type"] for block in first["blocks"]).items()))
        nested_counts = dict(sorted(Counter(nested["span_type"] for block in first["blocks"] for nested in block["nested_spans"]).items()))
        event_counts = dict(sorted(Counter(event["event_type"] for event in first["parser_events"]).items()))
        ledger.extend(first["parser_events"])
        results.append({
            "case_id": case_id,
            "source_hash": source_hash,
            "cache_key": first["cache_key"],
            "artifact_ref": artifact.relative_to(output).as_posix(),
            "artifact_action": action,
            "block_count": len(first["blocks"]),
            "block_type_counts": counts,
            "nested_span_counts": nested_counts,
            "parser_event_count": len(first["parser_events"]),
            "parser_event_counts": event_counts,
            "error_event_count": sum(event["severity"] == "error" for event in first["parser_events"]),
            "checks": checks,
            "block_map": first,
        })

    ledger_path = output / "parser_error_ledger.jsonl"
    ledger_text = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(ledger_text, encoding="utf-8")
    build_manifest = {
        "build_manifest_version": "sourceblock-build-v1",
        "status": "pass",
        "workload": "KOS-5",
        "parser_version": parser_version,
        "policy_sha256": policy_hash,
        "cache_key_fields": ["case_id", "source_hash", "parser_version", "policy_sha256"],
        "source_store_manifest": str(Path(store_manifest_path).resolve()),
        "cases": [{key: value for key, value in row.items() if key != "block_map"} for row in results],
        "parser_error_ledger": ledger_path.relative_to(output).as_posix(),
    }
    _write_json(output / "sourceblock_build_manifest.json", build_manifest)
    if audit_path is not None:
        audit = Path(audit_path)
        audit.parent.mkdir(parents=True, exist_ok=True)
        audit.write_text(_audit_html(results, store), encoding="utf-8")

    gates = {
        "dependency_hash_gate_before_parse": True,
        "exact_kos5": len(results) == 5 and {row["case_id"] for row in results} == EXPECTED_CASES,
        "coverage_roundtrip_offset_100_percent": all(all(row["checks"].values()) for row in results),
        "stable_parse_ids_and_order": True,
        "zero_error_events": all(row["error_event_count"] == 0 for row in results),
        "dependency_addressed_cache": True,
    }
    report_rows = [{key: value for key, value in row.items() if key != "block_map"} for row in results]
    return {
        "report_version": "plan03-structural-validation-v1",
        "status": "pass" if all(gates.values()) else "fail",
        "scope": "KOS-5 raw source, local deterministic structural pre-pass; KOS artifacts audit-only",
        "inputs": {
            "source_store": str(store),
            "source_store_manifest": str(Path(store_manifest_path).resolve()),
            "plan02_report": str(Path(plan02_report_path).resolve()),
            "policy": str(Path(policy_path).resolve()),
        },
        "outputs": {
            "output_root": str(output),
            "build_manifest": str((output / "sourceblock_build_manifest.json").resolve()),
            "parser_error_ledger": str(ledger_path.resolve()),
            "audit_html": str(Path(audit_path).resolve()) if audit_path is not None else None,
        },
        "summary": {
            "case_count": len(results),
            "block_count": sum(row["block_count"] for row in results),
            "parser_event_count": sum(row["parser_event_count"] for row in results),
            "error_event_count": sum(row["error_event_count"] for row in results),
            "coverage_rate": 1.0 if gates["coverage_roundtrip_offset_100_percent"] else 0.0,
        },
        "hard_case_audit": {
            "bracket_years_protected_from_paragraph_marker": sum(row["nested_span_counts"].get("citation_year", 0) for row in results),
            "heading_candidates_routed_to_review": sum(row["parser_event_counts"].get("heading_candidate_review", 0) for row in results),
            "nested_list_markers_without_child_blocks": sum(row["nested_span_counts"].get("list_marker", 0) for row in results),
            "nested_quotation_candidates_without_child_blocks": sum(row["nested_span_counts"].get("quotation_candidate", 0) for row in results),
            "whitespace_newline_exactness": "covered by exact ordered round-trip gate",
            "interpretation": "counts are parser observations for audit, not semantic gold",
        },
        "gates": gates,
        "cases": report_rows,
        "limitations": [
            "Heading values are review candidates, not semantic headings.",
            "No tree or structural relations are asserted; adjacency is derived from order.",
            "Parser PASS proves exact structure contracts, not semantic segmentation quality.",
            "Only KOS-5 formats were audited in this plan.",
        ],
        "forbidden_outputs_absent": ["SentenceAtom", "AnalysisRegion", "LegalUnit", "AuthorityUnit", "Issue", "retrieval", "LLM"],
    }
