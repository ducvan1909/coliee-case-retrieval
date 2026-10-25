"""Validate selected KOS inputs and write a complete plan-01 JSON report."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

PIPELINE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT = PIPELINE_DIR / "reports/plan01_validation.latest.json"
BANDS = ("short", "medium", "long")
KOS5_CASE_IDS = {"013009", "013948", "011904", "045155", "099980"}
CASE_ID_RE = re.compile(r"^[0-9]{6}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CORPUS_PATTERNS = {
    "train": "data/task1_train_files_2026/cases/*.txt",
    "test": "data/task1_test_files_2026/*.txt",
}
MANDATORY_HARD_CASES = {
    "struct-false-heading": "structure",
    "struct-bracket-year-vs-marker": "structure",
    "struct-long-multi-proposition": "structure",
    "struct-open-quote-list": "structure",
    "au-cross-block": "au_context",
    "au-condition-neighbor": "au_context",
    "au-party-vs-court": "attribution",
    "au-distant-court-response": "attribution",
    "au-no-citation": "au_selection",
    "au-long-case-sparse": "coverage",
    "au-schema-valid-omission": "coverage",
    "au-duplicate-fragment": "au_quality",
    "ops-source-mutation-resume": "operations",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_raw_source_manifest(
    repo_root: Path, manifest: dict[str, Any]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Verify all canonical KOS-5 raw sources before any transition PASS."""
    errors: list[str] = []
    details: list[dict[str, Any]] = []
    rows = manifest.get("cases", [])
    ids = [row.get("case_id") for row in rows if isinstance(row, dict)]
    if manifest.get("manifest_version") != "calibration-source-manifest-v1":
        errors.append("unsupported calibration manifest version")
    if manifest.get("workload") != "KOS-5":
        errors.append("calibration manifest workload must be KOS-5")
    if len(rows) != 5 or set(ids) != KOS5_CASE_IDS:
        errors.append(f"raw source cases must be exactly {sorted(KOS5_CASE_IDS)}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate case_id in calibration manifest")

    seen_paths: set[str] = set()
    seen_hashes: dict[str, str] = {}
    repo = repo_root.resolve()
    for row in rows:
        if not isinstance(row, dict):
            errors.append("calibration manifest case row must be an object")
            continue
        case_id = row.get("case_id")
        source_path = row.get("source_path")
        item: dict[str, Any] = {
            "case_id": case_id,
            "source_path": source_path,
            "status": "fail",
        }
        case_errors: list[str] = []
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
            case_errors.append("invalid_case_id")
        if not isinstance(source_path, str) or not source_path:
            case_errors.append("invalid_source_path")
            path = None
        else:
            relative = Path(source_path)
            if relative.is_absolute() or ".." in relative.parts:
                case_errors.append("unsafe_source_path")
                path = None
            else:
                path = (repo / relative).resolve()
                if repo not in path.parents:
                    case_errors.append("source_path_escapes_repo")
                    path = None
        expected_hash = row.get("sha256")
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            case_errors.append("invalid_manifest_sha256")
        if isinstance(source_path, str):
            if source_path in seen_paths:
                case_errors.append("duplicate_source_path")
            seen_paths.add(source_path)
        if isinstance(expected_hash, str) and SHA256_RE.fullmatch(expected_hash):
            previous = seen_hashes.get(expected_hash)
            if previous and previous != case_id:
                case_errors.append(f"duplicate_source_hash:{previous}")
            seen_hashes[expected_hash] = str(case_id)

        if path is None or not path.is_file():
            if path is not None:
                case_errors.append("missing_raw_source")
        else:
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                case_errors.append(f"utf8_sig_decode_failed:{exc}")
                text = None
            actual_hash = sha256(raw)
            item.update(
                {
                    "resolved_path": str(path),
                    "expected_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                    "expected_byte_length": row.get("byte_length"),
                    "actual_byte_length": len(raw),
                    "expected_char_length": row.get("char_length"),
                    "actual_char_length": len(text) if text is not None else None,
                }
            )
            if actual_hash != expected_hash:
                case_errors.append("sha256_mismatch")
            if row.get("byte_length") != len(raw):
                case_errors.append("byte_length_mismatch")
            if text is not None and row.get("char_length") != len(text):
                case_errors.append("char_length_mismatch")
        if case_errors:
            item["errors"] = case_errors
            errors.extend(f"{case_id}: {error}" for error in case_errors)
        else:
            item["status"] = "pass"
            item["errors"] = []
        details.append(item)
    return errors, details


def inventory_case(case_dir: Path) -> tuple[list[dict[str, Any]], str]:
    """Return the deterministic file inventory and its canonical tree digest."""
    paths = sorted(
        (path for path in case_dir.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(case_dir).as_posix(),
    )
    files: list[dict[str, Any]] = []
    for path in paths:
        raw = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(case_dir).as_posix(),
                "sha256": sha256(raw),
                "byte_length": len(raw),
            }
        )
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return files, sha256(canonical)


def validate_kos_manifest(
    kos_root: Path, manifest: dict[str, Any]
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    details: list[dict[str, Any]] = []
    rows = manifest.get("cases", [])
    expected_ids = {"013009", "013948", "011904", "045155", "099980"}
    ids = [row.get("case_id") for row in rows]
    if len(rows) != 5 or set(ids) != expected_ids:
        errors.append(f"selected KOS cases must be exactly {sorted(expected_ids)}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate case_id in selected KOS manifest")

    allowed_suffixes = set(manifest.get("input_contract", {}).get("allowed_suffixes", []))
    seen_file_hashes: dict[str, str] = {}
    for row in rows:
        case_id = str(row.get("case_id", "<missing>"))
        case_path = str(row.get("case_path", ""))
        case_dir = kos_root / case_path
        item: dict[str, Any] = {
            "case_id": case_id,
            "kos_role": row.get("kos_role"),
            "case_path": case_path,
            "status": "fail",
        }
        if not case_dir.is_dir():
            errors.append(f"{case_id}: missing KOS case directory {case_dir}")
            item["errors"] = ["missing_case_directory"]
            details.append(item)
            continue

        files, tree_digest = inventory_case(case_dir)
        item.update(
            {
                "file_count": len(files),
                "total_bytes": sum(file["byte_length"] for file in files),
                "tree_sha256": tree_digest,
                "files": files,
            }
        )
        case_errors: list[str] = []
        if not files:
            case_errors.append("empty_case_directory")
        if not any(file["path"] == "CASE.md" for file in files):
            case_errors.append("missing_CASE.md")
        else:
            case_text = (case_dir / "CASE.md").read_text(encoding="utf-8-sig")
            expected_role = row.get("kos_role")
            if f"role: {expected_role}" not in case_text:
                case_errors.append(f"kos_role_mismatch:expected={expected_role!r}")
        invalid_suffixes = [
            file["path"] for file in files if Path(file["path"]).suffix not in allowed_suffixes
        ]
        if invalid_suffixes:
            case_errors.append(f"disallowed_suffixes:{invalid_suffixes}")
        for field, actual in (
            ("file_count", len(files)),
            ("total_bytes", item["total_bytes"]),
            ("tree_sha256", tree_digest),
        ):
            if row.get(field) != actual:
                case_errors.append(
                    f"{field}_mismatch:manifest={row.get(field)!r},actual={actual!r}"
                )
        for file in files:
            owner = f"{case_id}/{file['path']}"
            previous = seen_file_hashes.get(file["sha256"])
            if previous and previous != owner:
                case_errors.append(f"duplicate_file_content:{previous}")
            seen_file_hashes[file["sha256"]] = owner
        if case_errors:
            errors.extend(f"{case_id}: {error}" for error in case_errors)
            item["errors"] = case_errors
        else:
            item["status"] = "pass"
            item["errors"] = []
        details.append(item)
    return errors, details


def _role_sets(registry: dict[str, Any]) -> dict[str, set[str]]:
    roles = {
        "calibration": set(registry.get("calibration", [])),
        "development": set(),
        "holdout": set(),
    }
    for corpus_split in ("train", "test"):
        for band in BANDS:
            cell = registry["pilot"][corpus_split][band]
            roles["development"].update(cell["development"])
            roles["holdout"].update(cell["holdout"])
    return roles


def _pilot_digest(pilot: Any) -> str:
    canonical = json.dumps(pilot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(canonical)


def reproduce_pilot(repo_root: Path) -> tuple[dict[str, Any], dict[str, int]]:
    """Reproduce the locked no-label length-band/hash split from corpus metadata."""
    result: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for corpus_split, pattern in CORPUS_PATTERNS.items():
        paths = list(repo_root.glob(pattern))
        if not paths:
            raise ValueError(f"no corpus files found for {corpus_split}: {pattern}")
        malformed = [path.name for path in paths if not re.fullmatch(r"[0-9]{6}\.txt", path.name)]
        if malformed:
            raise ValueError(f"malformed corpus case filenames for {corpus_split}: {malformed[:5]}")
        paths.sort(key=lambda path: (path.stat().st_size, path.stem))
        counts[corpus_split] = len(paths)
        selected: list[tuple[str, str]] = []
        for band_index, band in enumerate(BANDS):
            members = paths[
                band_index * len(paths) // 3 : (band_index + 1) * len(paths) // 3
            ]
            ranked = sorted(
                members,
                key=lambda path: sha256(
                    f"lynx-round2:{corpus_split}:{band}:{path.stem}".encode("utf-8")
                ),
            )[:10]
            selected.extend((band, path.stem) for path in ranked)
        split_result = {
            band: {"development": [], "holdout": []} for band in BANDS
        }
        for global_index, (band, case_id) in enumerate(selected):
            role = "development" if global_index % 3 == 0 else "holdout"
            split_result[band][role].append(case_id)
        result[corpus_split] = split_result
    return result, counts


def validate_split_registry(
    registry: dict[str, Any], repo_root: Path = DEFAULT_REPO_ROOT
) -> tuple[list[str], dict[str, Any]]:
    """Validate shape, provenance digest, corpus existence, hashes, and reproducibility."""
    errors: list[str] = []
    expected_policy = {
        "labels_used": False,
        "inputs": CORPUS_PATTERNS,
        "ordering": "ascending (byte_length, case_id)",
        "band_partition": "band i is rows[i*n//3:(i+1)*n//3], i=0..2",
        "rank_key": "sha256('lynx-round2:{corpus_split}:{band}:{case_id}')",
        "selected_per_band": 10,
        "assignment": "concatenate short, medium, long; development iff global_selected_index % 3 == 0",
    }
    if registry.get("registry_version") != "p2-split-registry-v1":
        errors.append("unsupported split registry version")
    policy = registry.get("pilot_policy")
    if not isinstance(policy, dict):
        errors.append("pilot_policy must be an object")
        policy = {}
    for key, expected in expected_policy.items():
        if policy.get(key) != expected:
            errors.append(f"pilot policy mismatch for {key}")
    expected_digest = policy.get("assignment_sha256")
    if not isinstance(expected_digest, str) or not SHA256_RE.fullmatch(expected_digest):
        errors.append("pilot policy lacks valid assignment_sha256 provenance")

    try:
        roles = _role_sets(registry)
    except (KeyError, TypeError, AttributeError) as exc:
        errors.append(f"malformed pilot registry: {exc}")
        roles = {"calibration": set(), "development": set(), "holdout": set()}

    all_ids: list[str] = []
    calibration = registry.get("calibration", [])
    if not isinstance(calibration, list):
        errors.append("calibration must be a list")
    else:
        all_ids.extend(calibration)
        if set(calibration) != KOS5_CASE_IDS or len(calibration) != 5:
            errors.append(f"calibration cases must be exactly {sorted(KOS5_CASE_IDS)}")
    pilot = registry.get("pilot")
    if not isinstance(pilot, dict):
        errors.append("pilot must be an object")
    else:
        for corpus_split in ("train", "test"):
            split_value = pilot.get(corpus_split)
            if not isinstance(split_value, dict):
                errors.append(f"pilot.{corpus_split} must be an object")
                continue
            for band in BANDS:
                cell = split_value.get(band)
                if not isinstance(cell, dict):
                    errors.append(f"pilot.{corpus_split}.{band} must be an object")
                    continue
                for role in ("development", "holdout"):
                    values = cell.get(role)
                    if not isinstance(values, list):
                        errors.append(f"pilot.{corpus_split}.{band}.{role} must be a list")
                        continue
                    all_ids.extend(values)
                    if len(values) != len(set(values)):
                        errors.append(f"duplicate case ID inside pilot.{corpus_split}.{band}.{role}")
    malformed_ids = sorted({str(case_id) for case_id in all_ids if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id)})
    if malformed_ids:
        errors.append(f"malformed case IDs: {malformed_ids}")

    expected_counts = {"calibration": 5, "development": 20, "holdout": 40}
    for role, expected in expected_counts.items():
        if len(roles[role]) != expected:
            errors.append(f"{role} must contain {expected} unique cases, got {len(roles[role])}")
    overlaps: dict[str, list[str]] = {}
    for left, right in (
        ("calibration", "development"),
        ("calibration", "holdout"),
        ("development", "holdout"),
    ):
        overlap = sorted(roles[left] & roles[right], key=lambda value: str(value))
        overlaps[f"{left}__{right}"] = overlap
        if overlap:
            errors.append(f"leakage: {left}/{right} overlap: {overlap}")

    actual_digest = _pilot_digest(pilot) if isinstance(pilot, dict) else None
    if expected_digest != actual_digest:
        errors.append(
            f"pilot assignment provenance mismatch: expected={expected_digest!r}, actual={actual_digest!r}"
        )

    reproduced: dict[str, Any] | None = None
    corpus_counts: dict[str, int] = {}
    try:
        reproduced, corpus_counts = reproduce_pilot(repo_root)
        if pilot != reproduced:
            errors.append("pilot assignment does not reproduce from the locked corpus policy")
    except (OSError, ValueError) as exc:
        errors.append(f"pilot reproduction failed: {exc}")

    locked_hashes: dict[str, dict[str, str]] = {}
    seen_hashes: dict[str, tuple[str, str]] = {}
    for role, case_ids in roles.items():
        for case_id in sorted(case_ids, key=lambda value: str(value)):
            if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
                continue
            candidates = [
                repo_root / f"data/task1_train_files_2026/cases/{case_id}.txt",
                repo_root / f"data/task1_test_files_2026/{case_id}.txt",
            ]
            existing = [path for path in candidates if path.is_file()]
            if len(existing) != 1:
                errors.append(f"{role}/{case_id}: expected exactly one corpus source, got {len(existing)}")
                continue
            digest = sha256(existing[0].read_bytes())
            locked_hashes[case_id] = {"role": role, "sha256": digest}
            previous = seen_hashes.get(digest)
            if previous and previous[0] != case_id:
                errors.append(
                    f"duplicate source hash across locked sets: {previous[1]}/{previous[0]} and {role}/{case_id}"
                )
            seen_hashes[digest] = (case_id, role)
    details = {
        "status": "pass" if not errors else "fail",
        "counts": {role: len(case_ids) for role, case_ids in roles.items()},
        "overlaps": overlaps,
        "assignment_sha256": actual_digest,
        "expected_assignment_sha256": expected_digest,
        "reproduced_from_policy": reproduced == pilot if reproduced is not None else False,
        "corpus_file_counts": corpus_counts,
        "locked_source_hashes": locked_hashes,
        "labels_read": False,
    }
    return errors, details


def validate_annotation_schema(
    schema: dict[str, Any], fixture: dict[str, Any] | None = None
) -> list[str]:
    errors: list[str] = []
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        errors.append(f"invalid Draft 2020-12 schema: {exc.message}")
        return errors
    if fixture is None:
        fixture_path = PIPELINE_DIR / "examples/minimal_annotation.v1.json"
        try:
            fixture = load_json(fixture_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot load annotation fixture: {exc}")
            fixture = None
    if fixture is not None:
        try:
            Draft202012Validator(schema).validate(fixture)
        except ValidationError as exc:
            errors.append(f"annotation fixture violates schema: {exc.message}")
    required_top = {"source_blocks", "authority_units", "context_obligations"}
    if not required_top <= set(schema.get("required", [])):
        errors.append("annotation schema lacks required top-level collections")
    defs = schema.get("$defs", {})
    for name in ("spanRef", "sourceBlock", "attribution", "authorityUnit", "contextObligation"):
        if name not in defs:
            errors.append(f"annotation schema lacks $defs.{name}")
    au_required = set(defs.get("authorityUnit", {}).get("required", []))
    expected_au = {
        "proposition_span",
        "evidence_spans",
        "attributions",
        "condition_spans",
        "context_obligation_ids",
    }
    if not expected_au <= au_required:
        errors.append(
            f"AuthorityUnit cannot represent required fields: {sorted(expected_au - au_required)}"
        )
    obligation_required = set(defs.get("contextObligation", {}).get("required", []))
    if not {"target_id", "obligation_type", "requested_context", "status"} <= obligation_required:
        errors.append("ContextObligation lacks target/context/status contract")
    return errors


def validate_hard_cases(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = catalog.get("situations", [])
    if catalog.get("catalog_version") != "p2-hard-cases-v1":
        errors.append("unsupported hard-case catalog version")
    if catalog.get("status") != "annotation_queue_not_gold":
        errors.append("hard-case catalog status must be annotation_queue_not_gold")
    rules = catalog.get("rules")
    if not isinstance(rules, list) or not all(isinstance(rule, str) and rule.strip() for rule in rules):
        errors.append("hard-case catalog rules must be non-empty strings")
    else:
        normalized_rules = " ".join(rules).lower()
        if "not accepted labels" not in normalized_rules or "cannot establish semantic truth" not in normalized_rules:
            errors.append("hard-case catalog must preserve explicit non-gold rules")
    if not isinstance(rows, list):
        return errors + ["hard-case situations must be a list"]
    ids = [row.get("situation_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate situation_id in hard-case catalog")
    missing = sorted(set(MANDATORY_HARD_CASES) - set(ids))
    if missing:
        errors.append(f"missing mandatory hard-case situations: {missing}")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"hard-case row {index} must be an object")
            continue
        situation_id = row.get("situation_id")
        if not isinstance(situation_id, str) or not situation_id:
            errors.append(f"hard-case row {index} has invalid situation_id")
            continue
        expected_class = MANDATORY_HARD_CASES.get(situation_id)
        if expected_class and row.get("class") != expected_class:
            errors.append(
                f"{situation_id}: class must be {expected_class!r}, got {row.get('class')!r}"
            )
        for field in ("description", "basis"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"{situation_id}: {field} must be a non-empty string")
        candidate_cases = row.get("candidate_cases")
        if not isinstance(candidate_cases, list):
            errors.append(f"{situation_id}: candidate_cases must be a list")
        else:
            if len(candidate_cases) != len(set(candidate_cases)):
                errors.append(f"{situation_id}: duplicate candidate case")
            invalid_candidates = sorted(
                {
                    str(case_id)
                    for case_id in candidate_cases
                    if not isinstance(case_id, str)
                    or not CASE_ID_RE.fullmatch(case_id)
                    or case_id not in KOS5_CASE_IDS
                }
            )
            if invalid_candidates:
                errors.append(
                    f"{situation_id}: candidate cases must belong to KOS-5: {invalid_candidates}"
                )
        required_labels = row.get("required_labels")
        if (
            not isinstance(required_labels, list)
            or not required_labels
            or not all(isinstance(label, str) and label.strip() for label in required_labels)
        ):
            errors.append(f"{situation_id}: required_labels must be a non-empty string list")
    return errors


def build_report(
    kos_root: Path, repo_root: Path = DEFAULT_REPO_ROOT
) -> dict[str, Any]:
    manifest_path = PIPELINE_DIR / "manifests/selected_kos_manifest.v1.json"
    calibration_path = PIPELINE_DIR / "manifests/calibration_manifest.v1.json"
    split_path = PIPELINE_DIR / "manifests/split_registry.v1.json"
    schema_path = PIPELINE_DIR / "contracts/annotation_schema.v1.json"
    fixture_path = PIPELINE_DIR / "examples/minimal_annotation.v1.json"
    hard_cases_path = PIPELINE_DIR / "hard_cases.v1.json"
    manifest = load_json(manifest_path)
    calibration = load_json(calibration_path)
    registry = load_json(split_path)
    schema = load_json(schema_path)
    fixture = load_json(fixture_path)
    hard_cases = load_json(hard_cases_path)

    raw_errors, raw_details = validate_raw_source_manifest(repo_root, calibration)
    kos_errors, case_details = validate_kos_manifest(kos_root, manifest)
    split_errors, split_details = validate_split_registry(registry, repo_root)
    schema_errors = validate_annotation_schema(schema, fixture)
    hard_case_errors = validate_hard_cases(hard_cases)
    errors = raw_errors + kos_errors + split_errors + schema_errors + hard_case_errors
    return {
        "report_version": "plan01-validation-report-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not errors else "fail",
        "inputs": {
            "repo_root": str(repo_root.resolve()),
            "kos_root": str(kos_root.resolve()),
            "calibration_manifest": str(calibration_path.resolve()),
            "selected_kos_manifest": str(manifest_path.resolve()),
            "split_registry": str(split_path.resolve()),
            "annotation_schema": str(schema_path.resolve()),
            "annotation_fixture": str(fixture_path.resolve()),
            "hard_case_catalog": str(hard_cases_path.resolve()),
        },
        "summary": {
            "raw_source_cases": len(raw_details),
            "raw_source_bytes": sum(
                case.get("actual_byte_length", 0) for case in raw_details
            ),
            "selected_cases": len(case_details),
            "selected_files": sum(case.get("file_count", 0) for case in case_details),
            "selected_bytes": sum(case.get("total_bytes", 0) for case in case_details),
            "error_count": len(errors),
        },
        "checks": {
            "raw_source_hashes": {
                "status": "pass" if not raw_errors else "fail",
                "cases": raw_details,
                "errors": raw_errors,
            },
            "selected_kos_inputs": {
                "status": "pass" if not kos_errors else "fail",
                "cases": case_details,
            },
            "split_registry": split_details,
            "annotation_schema": {
                "status": "pass" if not schema_errors else "fail",
                "draft": "2020-12",
                "metaschema_valid": not any(
                    error.startswith("invalid Draft 2020-12 schema")
                    for error in schema_errors
                ),
                "fixture_valid": not any(
                    error.startswith("annotation fixture violates schema")
                    or error.startswith("cannot load annotation fixture")
                    for error in schema_errors
                ),
                "errors": schema_errors,
            },
            "hard_case_catalog": {
                "status": "pass" if not hard_case_errors else "fail",
                "situation_count": len(hard_cases.get("situations", [])),
                "errors": hard_case_errors,
            },
        },
        "errors": errors,
        "scope_note": (
            "PASS validates canonical KOS-5 raw-source hashes, split provenance, "
            "the selected KOS audit inventory, and contracts; "
            "existing gold_noticed/gold_for_queries and materialized KOS labels are not evaluation gold; "
            "PASS does not establish semantic correctness, parser quality, or retrieval quality."
        ),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the five selected KOS case directories and write a JSON report."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help=f"Repository root containing raw sources (default: {DEFAULT_REPO_ROOT})",
    )
    parser.add_argument(
        "--kos-root",
        type=Path,
        required=True,
        help="KOS root containing cases/<case_id>, for example G:/Legal-AI/kos_sample",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Output JSON report (default: {DEFAULT_REPORT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.kos_root, args.repo_root)
    write_report(args.report, report)
    print(f"PLAN01 {report['status'].upper()} - report: {args.report.resolve()}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

