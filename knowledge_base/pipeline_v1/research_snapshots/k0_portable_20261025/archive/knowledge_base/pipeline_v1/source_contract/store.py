"""Immutable source-store build, lookup, and exact-span operations."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .models import CaseSource, ManifestCase, SourceManifest, SpanRef

EXPECTED_CASES = {"013009", "013948", "011904", "045155", "099980"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SourceContractError(ValueError):
    """Source manifest, provenance, or span validation failed."""


class ImmutableSourceError(SourceContractError):
    """An immutable source artifact exists with unexpected bytes."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _source_contract_validator() -> Draft202012Validator:
    schema_path = Path(__file__).resolve().parents[1] / "contracts" / "source_contract.v1.json"
    try:
        schema = _load_json(schema_path)
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaError) as exc:
        raise SourceContractError(f"cannot load source contract schema: {exc}") from exc
    return Draft202012Validator(schema)


def _safe_relative_path(value: str, field: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not value or ".." in path.parts:
        raise SourceContractError(f"{field} must be a safe relative path: {value!r}")
    return path


def load_source_manifest(path: str | Path) -> SourceManifest:
    manifest_path = Path(path)
    value = _load_json(manifest_path)
    if value.get("manifest_version") != "calibration-source-manifest-v1":
        raise SourceContractError("unsupported source manifest version")
    if value.get("workload") != "KOS-5":
        raise SourceContractError("source manifest workload must be KOS-5")
    contract = value.get("source_contract", {})
    expected_contract = {
        "hash_algorithm": "sha256_raw_bytes",
        "text_decoding": "utf-8-sig",
        "offset_unit": "unicode_codepoint_after_utf8_sig_decode",
        "span_interval": "half_open",
        "source_mutability": "immutable",
    }
    if contract != expected_contract:
        raise SourceContractError("source contract does not match case-source-v1")
    rows = value.get("cases", [])
    if len(rows) != 5 or {row.get("case_id") for row in rows} != EXPECTED_CASES:
        raise SourceContractError(f"manifest cases must be exactly {sorted(EXPECTED_CASES)}")
    cases: list[ManifestCase] = []
    seen_paths: set[str] = set()
    seen_hashes: set[str] = set()
    for row in rows:
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not re.fullmatch(r"[0-9]{6}", case_id):
            raise SourceContractError(f"invalid case_id: {case_id!r}")
        source_path = str(row.get("source_path", ""))
        _safe_relative_path(source_path, "source_path")
        digest = row.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise SourceContractError(f"{case_id}: invalid SHA-256")
        if source_path in seen_paths or digest in seen_hashes:
            raise SourceContractError(f"{case_id}: duplicate source path or hash")
        seen_paths.add(source_path)
        seen_hashes.add(digest)
        cases.append(
            ManifestCase(
                case_id=case_id,
                kos_role=str(row.get("kos_role", "")),
                corpus_split=str(row.get("corpus_split", "")),
                source_path=source_path,
                sha256=digest,
                byte_length=int(row.get("byte_length", -1)),
                char_length=int(row.get("char_length", -1)),
            )
        )
    audit_path = str(value.get("audit_kos_manifest", ""))
    _safe_relative_path(audit_path, "audit_kos_manifest")
    return SourceManifest(
        manifest_version=value["manifest_version"],
        workload=value["workload"],
        source_contract=contract,
        cases=tuple(cases),
        audit_kos_manifest=audit_path,
    )


def _verify_plan01_audit(
    repo_root: Path, manifest: SourceManifest, plan01_report_path: Path
) -> dict[str, Any]:
    report = _load_json(plan01_report_path)
    if report.get("status") != "pass":
        raise SourceContractError("Plan 01 report is not PASS")
    cases = report.get("checks", {}).get("selected_kos_inputs", {}).get("cases", [])
    audit_ids = {row.get("case_id") for row in cases if row.get("status") == "pass"}
    source_ids = {row.case_id for row in manifest.cases}
    if audit_ids != source_ids:
        raise SourceContractError(
            f"Plan 01 KOS cases {sorted(audit_ids)} do not match raw-source cases {sorted(source_ids)}"
        )
    expected_manifest = (repo_root / manifest.audit_kos_manifest).resolve()
    reported_manifest = Path(report.get("inputs", {}).get("selected_kos_manifest", "")).resolve()
    if expected_manifest != reported_manifest:
        raise SourceContractError("Plan 01 report references a different selected KOS manifest")
    return {
        "status": "pass",
        "report_path": str(plan01_report_path.resolve()),
        "selected_kos_manifest": str(reported_manifest),
        "case_ids": sorted(audit_ids),
        "semantic_gold": False,
    }


def _preflight_sources(
    repo_root: Path, manifest: SourceManifest
) -> list[tuple[ManifestCase, Path, bytes, str]]:
    verified: list[tuple[ManifestCase, Path, bytes, str]] = []
    errors: list[str] = []
    for row in manifest.cases:
        relative = _safe_relative_path(row.source_path, "source_path")
        source_path = (repo_root / relative).resolve()
        if repo_root.resolve() not in source_path.parents:
            errors.append(f"{row.case_id}: source path escapes repository")
            continue
        if not source_path.is_file():
            errors.append(f"{row.case_id}: missing raw source {source_path}")
            continue
        raw = source_path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            errors.append(f"{row.case_id}: utf-8-sig decode failed: {exc}")
            continue
        actual = (_sha256(raw), len(raw), len(text))
        expected = (row.sha256, row.byte_length, row.char_length)
        if actual != expected:
            errors.append(f"{row.case_id}: hash/length mismatch expected={expected}, actual={actual}")
            continue
        verified.append((row, source_path, raw, text))
    if errors:
        raise SourceContractError("raw-source preflight failed:\n- " + "\n- ".join(errors))
    return verified


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _write_immutable(path: Path, data: bytes) -> str:
    if path.exists():
        if path.read_bytes() != data:
            raise ImmutableSourceError(f"refusing to overwrite immutable artifact: {path}")
        return "reused"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return "created"


def _load_index(path: Path, case_id: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "index_version": "case-source-index-v1",
            "case_id": case_id,
            "current_source_hash": None,
            "current_source_version": None,
            "versions": [],
        }
    value = _load_json(path)
    if value.get("case_id") != case_id:
        raise SourceContractError(f"case index mismatch: {path}")
    return value


def _record_invalidation(
    store_root: Path, case_id: str, old_hash: str, new_hash: str
) -> dict[str, Any]:
    event_digest = _sha256(f"{case_id}:{old_hash}:{new_hash}".encode("utf-8"))
    event = {
        "event_version": "source-invalidation-v1",
        "event_id": f"inv-{event_digest[:16]}",
        "case_id": case_id,
        "old_source_hash": old_hash,
        "new_source_hash": new_hash,
        "source_versions_retained": True,
        "invalidated_dependency_selectors": [
            {"case_id": case_id, "source_hash": old_hash, "scope": "dependency_closure"}
        ],
        "affected_future_artifacts": [
            "SourceBlock",
            "SentenceAtom",
            "AnalysisRegionManifest",
            "Annotation",
            "AuthorityUnit",
            "worker_cache",
        ],
    }
    path = store_root / "invalidation" / f"{event['event_id']}.json"
    encoded = (json.dumps(event, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_immutable(path, encoded)
    return event


def _case_source_path(store_root: Path, case_id: str, source_hash: str) -> Path:
    return store_root / "cases" / case_id / "versions" / source_hash / "case_source.json"


def load_case_source(store_root: str | Path, case_id: str, source_hash: str) -> CaseSource:
    if not isinstance(case_id, str) or not re.fullmatch(r"[0-9]{6}", case_id):
        raise SourceContractError(f"invalid CaseSource case_id: {case_id!r}")
    if not isinstance(source_hash, str) or not SHA256_RE.fullmatch(source_hash):
        raise SourceContractError(f"invalid CaseSource source_hash: {source_hash!r}")
    root = Path(store_root)
    path = _case_source_path(root, case_id, source_hash)
    if not path.is_file():
        raise SourceContractError(f"CaseSource not found: {case_id}/{source_hash}")
    try:
        value = _load_json(path)
        if not isinstance(value, dict):
            raise SourceContractError("CaseSource record must be a JSON object")
        _source_contract_validator().validate(value)
        record = CaseSource.from_dict(value)
    except SourceContractError:
        raise
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise SourceContractError(
            f"CaseSource contract violation at {location}: {exc.message}"
        ) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SourceContractError(f"invalid CaseSource record {path}: {exc}") from exc
    if record.case_id != case_id or record.source_hash != source_hash:
        raise SourceContractError(f"CaseSource identity mismatch: {path}")
    expected_version = f"src-{source_hash[:16]}"
    if record.source_version != expected_version:
        raise SourceContractError(
            f"CaseSource source_version mismatch: expected {expected_version}, got {record.source_version}"
        )
    expected_text_ref = (
        Path("cases") / case_id / "versions" / source_hash / "source.txt"
    ).as_posix()
    if record.text_ref != expected_text_ref:
        raise SourceContractError(
            f"CaseSource text_ref mismatch: expected {expected_text_ref}, got {record.text_ref}"
        )
    return record


def open_source(store_root: str | Path, case_id: str, source_hash: str) -> str:
    root = Path(store_root)
    record = load_case_source(root, case_id, source_hash)
    try:
        raw = record.resolve_text(root).read_bytes()
    except (OSError, ValueError) as exc:
        raise SourceContractError(
            f"cannot resolve/read CaseSource text_ref for {case_id}/{source_hash}: {exc}"
        ) from exc
    if _sha256(raw) != source_hash or len(raw) != record.byte_length:
        raise ImmutableSourceError(f"stored source failed hash/length check: {case_id}/{source_hash}")
    try:
        text = raw.decode(record.encoding)
    except UnicodeDecodeError as exc:
        raise SourceContractError(f"stored source decode failed: {case_id}/{source_hash}: {exc}") from exc
    if len(text) != record.char_length:
        raise ImmutableSourceError(f"stored source char length mismatch: {case_id}/{source_hash}")
    return text


def open_span(store_root: str | Path, span: SpanRef) -> str:
    if span.start_char < 0 or span.end_char < span.start_char:
        raise SourceContractError(f"invalid half-open span: [{span.start_char}, {span.end_char})")
    text = open_source(store_root, span.case_id, span.source_hash)
    if span.end_char > len(text):
        raise SourceContractError(
            f"span end {span.end_char} exceeds source length {len(text)}"
        )
    return text[span.start_char : span.end_char]


def build_source_store(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    plan01_report_path: str | Path,
    store_root: str | Path,
) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    store = Path(store_root).resolve()
    manifest = load_source_manifest(manifest_path)
    audit = _verify_plan01_audit(repo, manifest, Path(plan01_report_path))
    verified = _preflight_sources(repo, manifest)

    records: list[dict[str, Any]] = []
    invalidations: list[dict[str, Any]] = []
    for row, _source_path, raw, text in verified:
        version = f"src-{row.sha256[:16]}"
        version_dir = store / "cases" / row.case_id / "versions" / row.sha256
        text_path = version_dir / "source.txt"
        text_ref = text_path.relative_to(store).as_posix()
        record = CaseSource(
            case_id=row.case_id,
            source_version=version,
            source_hash=row.sha256,
            text_ref=text_ref,
            byte_length=len(raw),
            char_length=len(text),
            metadata={
                "corpus_split": row.corpus_split,
                "kos_role": row.kos_role,
                "input_source_path": row.source_path,
                "audit_only_kos": True,
            },
        )
        source_action = _write_immutable(text_path, raw)
        record_bytes = (json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        record_action = _write_immutable(version_dir / "case_source.json", record_bytes)

        index_path = store / "cases" / row.case_id / "index.json"
        index = _load_index(index_path, row.case_id)
        old_hash = index.get("current_source_hash")
        if old_hash and old_hash != row.sha256:
            invalidations.append(_record_invalidation(store, row.case_id, old_hash, row.sha256))
        if not any(item.get("source_hash") == row.sha256 for item in index["versions"]):
            index["versions"].append(
                {
                    "source_version": version,
                    "source_hash": row.sha256,
                    "case_source_ref": (version_dir / "case_source.json").relative_to(store).as_posix(),
                }
            )
        index["current_source_hash"] = row.sha256
        index["current_source_version"] = version
        _atomic_write_json(index_path, index)

        full_span = SpanRef(row.case_id, row.sha256, 0, len(text))
        opened = open_span(store, full_span)
        checks = {
            "raw_byte_round_trip": text_path.read_bytes() == raw,
            "source_hash": _sha256(text_path.read_bytes()) == row.sha256,
            "decoded_text_round_trip": opened == text,
            "full_span_offset_coverage": len(opened) == len(text),
            "zero_length_boundary_spans": (
                open_span(store, SpanRef(row.case_id, row.sha256, 0, 0)) == ""
                and open_span(store, SpanRef(row.case_id, row.sha256, len(text), len(text))) == ""
            ),
        }
        records.append(
            {
                **record.to_dict(),
                "source_action": source_action,
                "record_action": record_action,
                "checks": checks,
                "verified_characters": len(text) if all(checks.values()) else 0,
            }
        )

    all_checks = [value for record in records for value in record["checks"].values()]
    report = {
        "report_version": "plan02-source-validation-v1",
        "status": "pass" if all(all_checks) and len(records) == 5 else "fail",
        "scope": "KOS-5 raw source; KOS artifacts are audit-only and not gold",
        "inputs": {
            "repo_root": str(repo),
            "source_manifest": str(Path(manifest_path).resolve()),
            "plan01_report": str(Path(plan01_report_path).resolve()),
        },
        "source_store": str(store),
        "audit": audit,
        "summary": {
            "case_count": len(records),
            "source_versions_created": sum(record["source_action"] == "created" for record in records),
            "source_versions_reused": sum(record["source_action"] == "reused" for record in records),
            "verified_bytes": sum(record["byte_length"] for record in records),
            "verified_characters": sum(record["verified_characters"] for record in records),
            "round_trip_hash_offset_rate": 1.0 if all(all_checks) and all_checks else 0.0,
            "invalidation_events": len(invalidations),
        },
        "records": records,
        "invalidation_events": invalidations,
        "non_applicable": [
            "parser_version",
            "segmenter_version",
            "worker_version",
            "SourceBlock_schema",
            "region_policy",
            "annotation",
            "LLM",
        ],
    }
    store_manifest = {
        "build_manifest_version": "source-store-build-v1",
        "status": report["status"],
        "source_manifest_version": manifest.manifest_version,
        "workload": manifest.workload,
        "cases": [
            {
                "case_id": record["case_id"],
                "source_version": record["source_version"],
                "source_hash": record["source_hash"],
                "case_source_ref": _case_source_path(
                    store, record["case_id"], record["source_hash"]
                ).relative_to(store).as_posix(),
            }
            for record in records
        ],
        "cache_fingerprint_fields": ["case_id", "source_hash", "SpanRef"],
        "invalidation_contract": "source hash change invalidates dependency closure; old source retained",
    }
    _atomic_write_json(store / "source_store_manifest.json", store_manifest)
    return report

