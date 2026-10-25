from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from knowledge_base.pipeline_v1.source_contract import (
    ImmutableSourceError,
    SourceContractError,
    SpanRef,
    build_source_store,
    load_source_manifest,
    open_source,
    open_span,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_DIR = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = PIPELINE_DIR / "manifests/calibration_manifest.v1.json"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class Plan02SourceContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.store = self.root / "store"
        manifest_value = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        for row in manifest_value["cases"]:
            source = REPO_ROOT / row["source_path"]
            destination = self.repo / row["source_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        self.manifest_path = self.repo / "calibration_manifest.v1.json"
        _write_json(self.manifest_path, manifest_value)

        selected_manifest = self.repo / manifest_value["audit_kos_manifest"]
        _write_json(selected_manifest, {"manifest_version": "selected-kos-manifest-v1"})
        self.plan01_report = self.repo / "plan01_report.json"
        _write_json(
            self.plan01_report,
            {
                "status": "pass",
                "inputs": {"selected_kos_manifest": str(selected_manifest.resolve())},
                "checks": {
                    "selected_kos_inputs": {
                        "cases": [
                            {"case_id": row["case_id"], "status": "pass"}
                            for row in manifest_value["cases"]
                        ]
                    }
                },
            },
        )

    def tearDown(self):
        self.temporary.cleanup()

    def build(self) -> dict:
        return build_source_store(
            repo_root=self.repo,
            manifest_path=self.manifest_path,
            plan01_report_path=self.plan01_report,
            store_root=self.store,
        )

    def test_manifest_loader_locks_kos5_and_raw_hashes(self):
        manifest = load_source_manifest(self.manifest_path)
        self.assertEqual(manifest.workload, "KOS-5")
        self.assertEqual({row.case_id for row in manifest.cases}, {"013009", "013948", "011904", "045155", "099980"})

    def test_build_round_trip_hash_and_full_offset_coverage(self):
        report = self.build()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["round_trip_hash_offset_rate"], 1.0)
        self.assertEqual(report["summary"]["case_count"], 5)
        for record in report["records"]:
            source = self.repo / record["metadata"]["input_source_path"]
            stored = self.store / record["text_ref"]
            self.assertEqual(stored.read_bytes(), source.read_bytes())
            text = source.read_bytes().decode("utf-8-sig")
            self.assertEqual(open_source(self.store, record["case_id"], record["source_hash"]), text)
            self.assertEqual(
                open_span(
                    self.store,
                    SpanRef(record["case_id"], record["source_hash"], 0, len(text)),
                ),
                text,
            )

    def test_exact_half_open_span_and_bounds(self):
        report = self.build()
        record = next(row for row in report["records"] if row["case_id"] == "045155")
        text = open_source(self.store, record["case_id"], record["source_hash"])
        start = next(index for index, character in enumerate(text) if ord(character) > 127)
        end = min(start + 37, len(text))
        span = SpanRef(record["case_id"], record["source_hash"], start, end)
        self.assertEqual(open_span(self.store, span), text[start:end])
        with self.assertRaises(SourceContractError):
            open_span(
                self.store,
                SpanRef(record["case_id"], record["source_hash"], 0, len(text) + 1),
            )
        with self.assertRaises(SourceContractError):
            open_span(
                self.store,
                SpanRef(record["case_id"], record["source_hash"], end, start),
            )

    def test_source_mutation_creates_new_version_and_invalidation(self):
        first = self.build()
        old = next(row for row in first["records"] if row["case_id"] == "013009")
        old_path = self.store / old["text_ref"]
        old_bytes = old_path.read_bytes()

        manifest_value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        row = next(item for item in manifest_value["cases"] if item["case_id"] == "013009")
        source = self.repo / row["source_path"]
        mutated = source.read_bytes() + b"\nMUTATION TEST\n"
        source.write_bytes(mutated)
        row["sha256"] = hashlib.sha256(mutated).hexdigest()
        row["byte_length"] = len(mutated)
        row["char_length"] = len(mutated.decode("utf-8-sig"))
        _write_json(self.manifest_path, manifest_value)

        second = self.build()
        new = next(item for item in second["records"] if item["case_id"] == "013009")
        self.assertNotEqual(new["source_version"], old["source_version"])
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertEqual((self.store / new["text_ref"]).read_bytes(), mutated)
        self.assertEqual(second["summary"]["invalidation_events"], 1)
        index = json.loads((self.store / "cases/013009/index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["versions"]), 2)

    def test_existing_version_is_reused_and_input_is_not_modified(self):
        before = {
            row.source_path: (self.repo / row.source_path).read_bytes()
            for row in load_source_manifest(self.manifest_path).cases
        }
        self.build()
        second = self.build()
        self.assertEqual(second["summary"]["source_versions_created"], 0)
        self.assertEqual(second["summary"]["source_versions_reused"], 5)
        for relative, raw in before.items():
            self.assertEqual((self.repo / relative).read_bytes(), raw)

    def test_corrupt_immutable_copy_is_never_overwritten(self):
        report = self.build()
        record = report["records"][0]
        stored = self.store / record["text_ref"]
        stored.write_bytes(b"corrupt")
        with self.assertRaises(ImmutableSourceError):
            self.build()
        self.assertEqual(stored.read_bytes(), b"corrupt")

    def test_case_source_contract_tampering_is_rejected_by_read_api(self):
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
        original = json.loads(record_path.read_text(encoding="utf-8"))
        mutations = {
            "record_type": lambda value: value.update(record_type="NotCaseSource"),
            "contract_version": lambda value: value.update(contract_version="untrusted"),
            "encoding": lambda value: value.update(encoding="utf-16"),
            "offset_unit": lambda value: value.update(offset_unit="byte"),
            "source_version": lambda value: value.update(source_version="src-0000000000000000"),
            "text_ref": lambda value: value.update(text_ref="cases/other/source.txt"),
            "missing_required": lambda value: value.pop("metadata"),
            "wrong_type": lambda value: value.update(byte_length="not-an-integer"),
            "extra_field": lambda value: value.update(untrusted=True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = json.loads(json.dumps(original))
                mutate(changed)
                record_path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(SourceContractError):
                    open_source(self.store, record["case_id"], record["source_hash"])
        record_path.write_text("not-json", encoding="utf-8")
        with self.assertRaises(SourceContractError):
            open_source(self.store, record["case_id"], record["source_hash"])

    def test_raw_hash_preflight_fails_before_store_write(self):
        manifest_value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        row = manifest_value["cases"][0]
        (self.repo / row["source_path"]).write_bytes(b"changed without manifest update")
        with self.assertRaises(SourceContractError):
            self.build()
        self.assertFalse(self.store.exists())

    def test_source_contract_schema_is_valid(self):
        schema = json.loads(
            (PIPELINE_DIR / "contracts/source_contract.v1.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        report = self.build()
        record = report["records"][0]
        case_source = {
            key: value
            for key, value in record.items()
            if key not in {"source_action", "record_action", "checks", "verified_characters"}
        }
        validator = Draft202012Validator(schema)
        validator.validate(case_source)
        validator.validate(
            SpanRef(record["case_id"], record["source_hash"], 0, record["char_length"]).to_dict()
        )


if __name__ == "__main__":
    unittest.main()

