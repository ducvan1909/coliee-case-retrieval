from __future__ import annotations

import unittest
from pathlib import Path
import json
import tempfile

from legal_unit.sample_selection import (
    QueryStats,
    collect_query_stats,
    materialize_sample,
    select_pilot_queries,
    select_validation_queries,
)


def _row(index: int) -> QueryStats:
    markers = {"FRAGMENT_SUPPRESSED": index % 4, "REFERENCE_SUPPRESSED": 0, "CITATION_SUPPRESSED": 0, "DATE_SUPPRESSED": 1}
    return QueryStats(f"{index:06}.txt", Path(f"{index:06}.txt"), "a" * 64, index + 10, index + 20, markers, index % 4, index, 0, 0, 0)


class SampleSelectionTests(unittest.TestCase):
    def test_gold_values_do_not_affect_development_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "cases"
            cases.mkdir()
            labels = {}
            for index in range(40):
                case_id = f"{index:06}.txt"
                (cases / case_id).write_text(f"Case {index}.\n" * (index + 1), encoding="utf-8")
                labels[case_id] = ["first-gold-value"]
            labels_path = root / "clean_task1_train_labels_2026.json"
            labels_path.write_text(json.dumps(labels), encoding="utf-8")
            first = select_pilot_queries(collect_query_stats(root))
            labels_path.write_text(
                json.dumps({case_id: ["different", "values"] for case_id in labels}),
                encoding="utf-8",
            )
            second = select_pilot_queries(collect_query_stats(root))
            self.assertEqual(
                [row.case_id for row, _, _ in first],
                [row.case_id for row, _, _ in second],
            )

    def test_returns_20_unique_queries_and_five_per_bucket(self) -> None:
        selected = select_pilot_queries([_row(index) for index in range(40)])
        self.assertEqual(20, len(selected))
        self.assertEqual(20, len({row.case_id for row, _, _ in selected}))
        self.assertEqual([5, 5, 5, 5], [sum(bucket == item for _, bucket, _ in selected) for item in range(1, 5)])
        self.assertIn("000000.txt", {row.case_id for row, _, _ in selected})
        self.assertIn("000039.txt", {row.case_id for row, _, _ in selected})

    def test_validation_selection_is_deterministic_disjoint_and_bucketed(self) -> None:
        rows = [_row(index) for index in range(80)]
        excluded_ids = {f"{index:06}.txt" for index in range(20)}
        excluded_hashes: set[str] = set()
        first = select_validation_queries(rows, excluded_ids, excluded_hashes)
        second = select_validation_queries(list(reversed(rows)), excluded_ids, excluded_hashes)
        self.assertEqual([row.case_id for row, _, _ in first], [row.case_id for row, _, _ in second])
        self.assertFalse({row.case_id for row, _, _ in first} & excluded_ids)
        self.assertEqual([5, 5, 5, 5], [sum(bucket == item for _, bucket, _ in first) for item in range(1, 5)])

    def test_materialized_validation_is_frozen_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "train"
            cases = root / "cases"
            cases.mkdir(parents=True)
            labels = {}
            for index in range(60):
                case_id = f"{index:06}.txt"
                (cases / case_id).write_text((f"Case {index}.\n" * (index + 1)), encoding="utf-8")
                labels[case_id] = ["ignored-gold-value"]
            (root / "clean_task1_train_labels_2026.json").write_text(json.dumps(labels), encoding="utf-8")
            development = Path(directory) / "development"
            validation = Path(directory) / "validation"
            development_manifest = materialize_sample(root, development)
            validation_manifest = materialize_sample(
                root, validation, split="validation", exclude_manifest=development_manifest
            )
            before = validation_manifest.read_bytes()
            self.assertEqual(
                validation_manifest,
                materialize_sample(root, validation, split="validation", exclude_manifest=development_manifest),
            )
            self.assertEqual(before, validation_manifest.read_bytes())
            dev = json.loads(development_manifest.read_text(encoding="utf-8"))
            val = json.loads(validation_manifest.read_text(encoding="utf-8"))
            self.assertFalse({item["case_id"] for item in dev["samples"]} & {item["case_id"] for item in val["samples"]})
            dev["selection"]["method_version"] = "changed"
            development_manifest.write_text(json.dumps(dev), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exclusion manifest has changed"):
                materialize_sample(root, validation, split="validation", exclude_manifest=development_manifest)
