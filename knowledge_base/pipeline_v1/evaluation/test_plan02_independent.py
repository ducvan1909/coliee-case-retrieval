from __future__ import annotations

import json
import hashlib
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from knowledge_base.pipeline_v1.source_contract import (
    ImmutableSourceError,
    SourceContractError,
    SpanRef,
    build_source_store,
    open_source,
    open_span,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_DIR = Path(__file__).resolve().parents[1]
MANIFEST = PIPELINE_DIR / "manifests/calibration_manifest.v1.json"
PLAN01_REPORT = PIPELINE_DIR / "evaluation/runtime/plan01_gate_retest2.json"


class Plan02IndependentEvaluation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Path(self.temporary.name) / "source-store"

    def tearDown(self):
        self.temporary.cleanup()

    def build(self) -> dict:
        return build_source_store(
            repo_root=REPO_ROOT,
            manifest_path=MANIFEST,
            plan01_report_path=PLAN01_REPORT,
            store_root=self.store,
        )

    def test_black_box_kos5_round_trip_and_sampled_codepoint_spans(self):
        report = self.build()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["case_count"], 5)
        self.assertEqual(report["summary"]["round_trip_hash_offset_rate"], 1.0)

        rng = random.Random(20261003)
        for record in report["records"]:
            raw = (REPO_ROOT / record["metadata"]["input_source_path"]).read_bytes()
            expected = raw.decode("utf-8-sig")
            actual = open_source(self.store, record["case_id"], record["source_hash"])
            self.assertEqual(actual, expected)
            boundaries = {0, 1, len(expected) - 1, len(expected)}
            boundaries.update(rng.randrange(0, len(expected) + 1) for _ in range(40))
            ordered = sorted(boundaries)
            for start, end in zip(ordered, ordered[1:]):
                span = SpanRef(record["case_id"], record["source_hash"], start, end)
                self.assertEqual(open_span(self.store, span), expected[start:end])

    def test_negative_span_identity_and_bounds_are_rejected(self):
        report = self.build()
        record = report["records"][0]
        invalid = [
            SpanRef(record["case_id"], record["source_hash"], -1, 0),
            SpanRef(record["case_id"], record["source_hash"], 2, 1),
            SpanRef(
                record["case_id"],
                record["source_hash"],
                0,
                record["char_length"] + 1,
            ),
            SpanRef(record["case_id"], "0" * 64, 0, 1),
            SpanRef("999999", record["source_hash"], 0, 1),
        ]
        for span in invalid:
            with self.subTest(span=span), self.assertRaises(SourceContractError):
                open_span(self.store, span)

    def test_corrupt_source_bytes_are_detected_without_overwrite(self):
        report = self.build()
        record = report["records"][0]
        source_path = self.store / record["text_ref"]
        source_path.write_bytes(b"fault-injected-corruption")
        with self.assertRaises(ImmutableSourceError):
            open_source(self.store, record["case_id"], record["source_hash"])
        with self.assertRaises(ImmutableSourceError):
            self.build()
        self.assertEqual(source_path.read_bytes(), b"fault-injected-corruption")

    def test_case_source_contract_tamper_is_rejected_by_read_api(self):
        report = self.build()
        record = report["records"][0]
        record_path = (
            self.store
            / "cases"
            / record["case_id"]
            / "versions"
            / record["source_hash"]
            / "case_source.json"
        )
        value = json.loads(record_path.read_text(encoding="utf-8"))
        value["record_type"] = "NotCaseSource"
        value["contract_version"] = "untrusted-contract"
        value["source_version"] = "src-0000000000000000"
        record_path.write_text(json.dumps(value), encoding="utf-8")

        with self.assertRaises(SourceContractError):
            open_source(self.store, record["case_id"], record["source_hash"])

    def test_each_case_source_contract_fault_is_rejected_independently(self):
        report = self.build()
        record = report["records"][0]
        record_path = (
            self.store
            / "cases"
            / record["case_id"]
            / "versions"
            / record["source_hash"]
            / "case_source.json"
        )
        original_text = record_path.read_text(encoding="utf-8")
        original = json.loads(original_text)
        mutations = {
            "record_type": lambda value: value.update(record_type="NotCaseSource"),
            "contract_version": lambda value: value.update(contract_version="case-source-v2"),
            "source_version": lambda value: value.update(source_version="src-0000000000000000"),
            "case_id": lambda value: value.update(case_id="999999"),
            "source_hash": lambda value: value.update(source_hash="0" * 64),
            "text_ref": lambda value: value.update(text_ref="cases/other/source.txt"),
            "encoding": lambda value: value.update(encoding="utf-16"),
            "offset_unit": lambda value: value.update(offset_unit="byte"),
            "missing_metadata": lambda value: value.pop("metadata"),
            "missing_byte_length": lambda value: value.pop("byte_length"),
            "wrong_byte_length_type": lambda value: value.update(byte_length="1"),
            "wrong_char_length_type": lambda value: value.update(char_length=[]),
            "wrong_metadata_type": lambda value: value.update(metadata="untrusted"),
            "missing_metadata_field": lambda value: value["metadata"].pop("kos_role"),
            "extra_field": lambda value: value.update(untrusted=True),
        }
        try:
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    changed = json.loads(original_text)
                    mutate(changed)
                    record_path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaises(SourceContractError):
                        open_source(self.store, record["case_id"], record["source_hash"])

            for name, malformed in {
                "invalid_json": "{not-json",
                "json_array": "[]",
                "json_null": "null",
            }.items():
                with self.subTest(name=name):
                    record_path.write_text(malformed, encoding="utf-8")
                    with self.assertRaises(SourceContractError):
                        open_source(self.store, record["case_id"], record["source_hash"])
        finally:
            record_path.write_text(original_text, encoding="utf-8")

    def test_source_byte_faults_and_span_boundaries_are_rejected(self):
        report = self.build()
        record = report["records"][0]
        source_path = self.store / record["text_ref"]
        original = source_path.read_bytes()
        for name, corrupted in {
            "same_length": bytes([original[0] ^ 1]) + original[1:],
            "truncated": original[:-1],
            "extended": original + b"x",
        }.items():
            with self.subTest(name=name):
                source_path.write_bytes(corrupted)
                with self.assertRaises(ImmutableSourceError):
                    open_source(self.store, record["case_id"], record["source_hash"])
        source_path.write_bytes(original)
        text = open_source(self.store, record["case_id"], record["source_hash"])
        valid = [(0, 0), (0, 1), (len(text), len(text))]
        for start, end in valid:
            self.assertEqual(
                open_span(
                    self.store,
                    SpanRef(record["case_id"], record["source_hash"], start, end),
                ),
                text[start:end],
            )
        invalid = [(-1, 0), (1, 0), (0, len(text) + 1)]
        for start, end in invalid:
            with self.subTest(start=start, end=end), self.assertRaises(SourceContractError):
                open_span(
                    self.store,
                    SpanRef(record["case_id"], record["source_hash"], start, end),
                )

    def test_source_change_invalidates_once_and_preserves_both_cache_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            store = root / "store"
            manifest_value = json.loads(MANIFEST.read_text(encoding="utf-8"))
            for row in manifest_value["cases"]:
                source = REPO_ROOT / row["source_path"]
                destination = repo / row["source_path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            manifest_path = repo / "calibration_manifest.json"
            manifest_path.write_text(json.dumps(manifest_value), encoding="utf-8")
            selected = repo / manifest_value["audit_kos_manifest"]
            selected.parent.mkdir(parents=True, exist_ok=True)
            selected.write_text("{}", encoding="utf-8")
            plan01 = repo / "plan01.json"
            plan01.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "inputs": {"selected_kos_manifest": str(selected.resolve())},
                        "checks": {
                            "selected_kos_inputs": {
                                "cases": [
                                    {"case_id": row["case_id"], "status": "pass"}
                                    for row in manifest_value["cases"]
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            first = build_source_store(
                repo_root=repo,
                manifest_path=manifest_path,
                plan01_report_path=plan01,
                store_root=store,
            )
            old = first["records"][0]
            row = next(item for item in manifest_value["cases"] if item["case_id"] == old["case_id"])
            source_path = repo / row["source_path"]
            changed = source_path.read_bytes() + b"\nINDEPENDENT INVALIDATION TEST\n"
            source_path.write_bytes(changed)
            row["sha256"] = hashlib.sha256(changed).hexdigest()
            row["byte_length"] = len(changed)
            row["char_length"] = len(changed.decode("utf-8-sig"))
            manifest_path.write_text(json.dumps(manifest_value), encoding="utf-8")

            second = build_source_store(
                repo_root=repo,
                manifest_path=manifest_path,
                plan01_report_path=plan01,
                store_root=store,
            )
            self.assertEqual(second["summary"]["invalidation_events"], 1)
            new = next(item for item in second["records"] if item["case_id"] == old["case_id"])
            self.assertNotEqual(old["source_hash"], new["source_hash"])
            self.assertNotEqual(old["source_version"], new["source_version"])
            self.assertEqual(
                open_source(store, old["case_id"], old["source_hash"]),
                (REPO_ROOT / row["source_path"]).read_bytes().decode("utf-8-sig"),
            )
            self.assertEqual(open_source(store, new["case_id"], new["source_hash"]), changed.decode("utf-8-sig"))

            third = build_source_store(
                repo_root=repo,
                manifest_path=manifest_path,
                plan01_report_path=plan01,
                store_root=store,
            )
            self.assertEqual(third["summary"]["invalidation_events"], 0)
            events = list((store / "invalidation").glob("*.json"))
            self.assertEqual(len(events), 1)
            index = json.loads((store / "cases" / old["case_id"] / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["current_source_hash"], new["source_hash"])
            self.assertEqual({item["source_hash"] for item in index["versions"]}, {old["source_hash"], new["source_hash"]})


if __name__ == "__main__":
    unittest.main()
