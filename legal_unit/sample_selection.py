"""Deterministic selection and materialization of a 20-query pilot sample."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Iterable

from .markers import MARKER_NAMES, content_marker_count, find_markers, marker_counts


SAMPLE_SIZE = 20
BUCKET_COUNT = 4
SAMPLE_MANIFEST_VERSION = "legal-unit-pilot-sample-v1"
VALIDATION_MANIFEST_VERSION = "legal-unit-validation-sample-v1"
VALIDATION_SELECTION_VERSION = "legal-unit-validation-v1"


@dataclass(frozen=True)
class QueryStats:
    case_id: str
    source_path: Path
    sha256: str
    word_count: int
    char_count: int
    marker_counts: dict[str, int]
    content_marker_count: int
    paragraph_count: int
    heading_line_count: int
    list_line_count: int
    quotation_line_count: int

    def public_dict(self, sample_reason: str, length_bucket: int) -> dict[str, object]:
        value = asdict(self)
        value["source_path"] = self.source_path.as_posix()
        value["length_bucket"] = length_bucket
        value["selection_reason"] = sample_reason
        return value


def _query_ids(labels_path: Path) -> list[str]:
    value = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Train labels must be a JSON object keyed by query case ID")
    return sorted(value)


def _structure_counts(text: str) -> tuple[int, int, int, int]:
    lines = text.splitlines()
    paragraphs = sum(1 for part in text.replace("\r\n", "\n").split("\n\n") if part.strip())
    headings = sum(1 for line in lines if line.strip().endswith(":") or line.strip().rstrip(".").isdigit())
    lists = sum(1 for line in lines if line.lstrip().startswith(("- ", "• ", "* ")))
    quotations = sum(1 for line in lines if line.lstrip().startswith(("\"", "'", "“")))
    return paragraphs, headings, lists, quotations


def collect_query_stats(train_root: Path) -> list[QueryStats]:
    labels_path = train_root / "clean_task1_train_labels_2026.json"
    cases_dir = train_root / "cases"
    result: list[QueryStats] = []
    for case_id in _query_ids(labels_path):
        source_path = cases_dir / case_id
        raw = source_path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
        markers = find_markers(text)
        paragraphs, headings, lists, quotations = _structure_counts(text)
        result.append(
            QueryStats(
                case_id=case_id,
                source_path=source_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                word_count=len(text.split()),
                char_count=len(text),
                marker_counts=marker_counts(text),
                content_marker_count=content_marker_count(markers),
                paragraph_count=paragraphs,
                heading_line_count=headings,
                list_line_count=lists,
                quotation_line_count=quotations,
            )
        )
    if len(result) < SAMPLE_SIZE:
        raise ValueError(f"Need at least {SAMPLE_SIZE} labeled train queries")
    return sorted(result, key=lambda row: (row.word_count, row.case_id))


def _nearest(candidates: Iterable[QueryStats], target: float, chosen: set[str]) -> QueryStats | None:
    available = [row for row in candidates if row.case_id not in chosen]
    if not available:
        return None
    return min(
        available,
        key=lambda row: (
            abs(row.content_marker_count - target),
            -row.paragraph_count - row.heading_line_count - row.list_line_count - row.quotation_line_count,
            row.case_id,
        ),
    )


def _add(selected: list[tuple[QueryStats, str]], row: QueryStats | None, reason: str) -> None:
    if row is not None and row.case_id not in {existing.case_id for existing, _ in selected}:
        selected.append((row, reason))


def select_pilot_queries(rows: list[QueryStats]) -> list[tuple[QueryStats, int, str]]:
    """Select five varied queries per word-count quartile, deterministically."""
    if len(rows) < SAMPLE_SIZE:
        raise ValueError("Insufficient query rows")
    chosen_global: set[str] = set()
    seen_marker_types: set[str] = set()
    result: list[tuple[QueryStats, int, str]] = []
    bucket_sizes = [len(rows) // BUCKET_COUNT] * BUCKET_COUNT
    for index in range(len(rows) % BUCKET_COUNT):
        bucket_sizes[-1 - index] += 1
    offset = 0
    for bucket_index, size in enumerate(bucket_sizes, start=1):
        bucket = rows[offset : offset + size]
        offset += size
        selected: list[tuple[QueryStats, str]] = []
        local_chosen: set[str] = set(chosen_global)
        extreme = bucket[0] if bucket_index == 1 else bucket[-1] if bucket_index == BUCKET_COUNT else None
        if extreme is not None:
            _add(selected, extreme, "required global length extreme")
            local_chosen.add(extreme.case_id)

        no_marker = [row for row in bucket if row.content_marker_count == 0]
        if no_marker:
            target_words = median(row.word_count for row in bucket)
            row = min(no_marker, key=lambda item: (abs(item.word_count - target_words), item.case_id))
            _add(selected, row, "no content marker; nearest bucket median length")
            local_chosen.add(row.case_id)
        else:
            _add(selected, _nearest(bucket, 0, local_chosen), "closest available to no content marker")
            local_chosen.update(row.case_id for row, _ in selected)

        positive = sorted(row.content_marker_count for row in bucket if row.content_marker_count > 0)
        for percentile in (0.10, 0.50, 0.90):
            if len(selected) >= 5:
                break
            if positive:
                target = positive[round((len(positive) - 1) * percentile)]
                reason = f"content-marker percentile {int(percentile * 100)} (target={target})"
            else:
                target = 0
                reason = f"no positive content markers in bucket; fallback percentile {int(percentile * 100)}"
            row = _nearest(bucket, target, local_chosen)
            _add(selected, row, reason)
            local_chosen.update(item.case_id for item, _ in selected)

        if len(selected) < 5:
            available = [row for row in bucket if row.case_id not in local_chosen]
            def novelty_key(row: QueryStats) -> tuple[int, int, int, str]:
                types = {name for name, count in row.marker_counts.items() if count and name != "DATE_SUPPRESSED"}
                structure = row.paragraph_count + row.heading_line_count + row.list_line_count + row.quotation_line_count
                return (-len(types - seen_marker_types), -len(types), -structure, row.case_id)
            row = min(available, key=novelty_key)
            _add(selected, row, "supplement marker-type or structural diversity")
            local_chosen.add(row.case_id)
        while len(selected) < 5:
            remaining = [row for row in bucket if row.case_id not in local_chosen]
            if not remaining:
                raise AssertionError("Bucket cannot supply five unique queries")
            row = min(remaining, key=lambda item: (abs(item.word_count - median(x.word_count for x in bucket)), item.case_id))
            _add(selected, row, "bucket diversity fallback")
            local_chosen.add(row.case_id)
        for row, reason in selected:
            chosen_global.add(row.case_id)
            seen_marker_types.update(name for name, count in row.marker_counts.items() if count and name != "DATE_SUPPRESSED")
            result.append((row, bucket_index, reason))
    if len(result) != SAMPLE_SIZE or len({row.case_id for row, _, _ in result}) != SAMPLE_SIZE:
        raise AssertionError("Pilot selection must contain exactly 20 unique cases")
    return result


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bucketed(rows: list[QueryStats]) -> list[tuple[int, list[QueryStats]]]:
    bucket_sizes = [len(rows) // BUCKET_COUNT] * BUCKET_COUNT
    for index in range(len(rows) % BUCKET_COUNT):
        bucket_sizes[-1 - index] += 1
    result: list[tuple[int, list[QueryStats]]] = []
    offset = 0
    for bucket_index, size in enumerate(bucket_sizes, start=1):
        result.append((bucket_index, rows[offset : offset + size]))
        offset += size
    return result


def select_validation_queries(
    rows: list[QueryStats], excluded_case_ids: set[str], excluded_hashes: set[str]
) -> list[tuple[QueryStats, int, str]]:
    """Select a frozen holdout without using segmentation outcomes or label values."""
    available = [
        row for row in sorted(rows, key=lambda item: (item.word_count, item.case_id))
        if row.case_id not in excluded_case_ids and row.sha256 not in excluded_hashes
    ]
    if len(available) < SAMPLE_SIZE:
        raise ValueError("Insufficient non-excluded queries for validation")
    result: list[tuple[QueryStats, int, str]] = []
    for bucket_index, bucket in _bucketed(available):
        ordered = sorted(
            bucket,
            key=lambda row: (
                hashlib.sha256(f"{VALIDATION_SELECTION_VERSION}:{row.case_id}".encode("utf-8")).hexdigest(),
                row.case_id,
            ),
        )
        for row in ordered[: SAMPLE_SIZE // BUCKET_COUNT]:
            result.append((row, bucket_index, "fixed hash order within remaining word-count quartile"))
    if len(result) != SAMPLE_SIZE or len({row.case_id for row, _, _ in result}) != SAMPLE_SIZE:
        raise AssertionError("Validation selection must contain exactly 20 unique cases")
    return result


def _verify_frozen_manifest(train_root: Path, samples_dir: Path, manifest: dict[str, object]) -> None:
    samples = manifest.get("samples")
    if not isinstance(samples, list) or len(samples) != SAMPLE_SIZE:
        raise ValueError("Frozen sample manifest must contain exactly 20 samples")
    seen: set[str] = set()
    for entry in samples:
        if not isinstance(entry, dict) or not isinstance(entry.get("case_id"), str) or not isinstance(entry.get("sha256"), str):
            raise ValueError("Frozen sample manifest has an invalid sample entry")
        case_id = entry["case_id"]
        expected_hash = entry["sha256"]
        if case_id in seen:
            raise ValueError(f"Duplicate frozen sample: {case_id}")
        seen.add(case_id)
        source = train_root / "cases" / case_id
        copied = samples_dir / "cases" / case_id
        if not source.is_file() or _file_sha256(source) != expected_hash:
            raise ValueError(f"Frozen source hash mismatch: {case_id}")
        if not copied.is_file() or _file_sha256(copied) != expected_hash:
            raise ValueError(f"Frozen copied sample hash mismatch: {case_id}")


def materialize_sample(
    train_root: Path,
    samples_dir: Path,
    *,
    split: str = "development",
    exclude_manifest: Path | None = None,
) -> Path:
    """Copy the selected source bytes and persist their reproducible manifest."""
    if split not in {"development", "validation"}:
        raise ValueError("split must be development or validation")
    if split == "validation" and exclude_manifest is None:
        raise ValueError("validation selection requires exclude_manifest")
    if split == "development" and exclude_manifest is not None:
        raise ValueError("exclude_manifest is only valid for validation selection")
    manifest_path = samples_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded_split = manifest.get("split", "development")
        if recorded_split != split:
            raise ValueError(f"Frozen manifest split is {recorded_split}, requested {split}")
        if split == "validation":
            assert exclude_manifest is not None
            exclusion = manifest.get("exclusion")
            if not isinstance(exclusion, dict) or exclusion.get("manifest_sha256") != _file_sha256(exclude_manifest):
                raise ValueError("Frozen validation exclusion manifest has changed")
        _verify_frozen_manifest(train_root, samples_dir, manifest)
        return manifest_path

    rows = collect_query_stats(train_root)
    excluded_case_ids: set[str] = set()
    excluded_hashes: set[str] = set()
    exclusion: dict[str, object] | None = None
    if split == "validation":
        assert exclude_manifest is not None
        excluded = json.loads(exclude_manifest.read_text(encoding="utf-8"))
        excluded_samples = excluded.get("samples")
        if not isinstance(excluded_samples, list):
            raise ValueError("Exclusion manifest has no samples list")
        for entry in excluded_samples:
            if not isinstance(entry, dict) or not isinstance(entry.get("case_id"), str) or not isinstance(entry.get("sha256"), str):
                raise ValueError("Exclusion manifest has an invalid sample entry")
            excluded_case_ids.add(entry["case_id"])
            excluded_hashes.add(entry["sha256"])
        selected = select_validation_queries(rows, excluded_case_ids, excluded_hashes)
        exclusion = {
            "manifest_path": exclude_manifest.as_posix(),
            "manifest_sha256": _file_sha256(exclude_manifest),
            "excluded_case_ids": sorted(excluded_case_ids),
            "excluded_source_sha256": sorted(excluded_hashes),
        }
    else:
        selected = select_pilot_queries(rows)
    cases_dir = samples_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    for row, bucket, reason in selected:
        destination = cases_dir / row.case_id
        shutil.copyfile(row.source_path, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != row.sha256:
            raise RuntimeError(f"Copied sample hash mismatch: {row.case_id}")
        entries.append(row.public_dict(reason, bucket))
    manifest = {
        "schema_version": VALIDATION_MANIFEST_VERSION if split == "validation" else SAMPLE_MANIFEST_VERSION,
        "split": split,
        "source": {
            "train_root": train_root.as_posix(),
            "labels_path": (train_root / "clean_task1_train_labels_2026.json").as_posix(),
            "query_count": len(rows),
            "selection_uses": "train-label JSON keys only; values/gold candidates ignored",
        },
        "selection": {
            "sample_size": SAMPLE_SIZE,
            "length_buckets": BUCKET_COUNT,
            "sort_order": "word_count, case_id",
            "content_marker_types": list(MARKER_NAMES[:-1]),
            "date_marker_type": "DATE_SUPPRESSED",
            "method_version": VALIDATION_SELECTION_VERSION if split == "validation" else "legal-unit-development-v1",
        },
        "samples": entries,
    }
    if exclusion is not None:
        manifest["exclusion"] = exclusion
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path
