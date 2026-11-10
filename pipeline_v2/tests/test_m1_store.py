from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pipeline_v2.m0 import build_bundle as build_m0
from pipeline_v2.source import M1Error, SourceReader, build_bundle, parse_source, validate_bundle


REPO = Path(__file__).resolve().parents[2]


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def reseal(bundle: Path, relative: str):
    seal_path = bundle / "seal.json"
    seal = read_json(seal_path)
    raw = (bundle / relative).read_bytes()
    seal["files"][relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
    write_json(seal_path, seal)


class M1StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        config_dir = self.root / "pipeline_v2" / "configs"
        cases = self.root / "data" / "task1_train_files_2026" / "cases"
        config_dir.mkdir(parents=True)
        cases.mkdir(parents=True)
        shutil.copyfile(REPO / "pipeline_v2" / "configs" / "m0.json", config_dir / "m0.json")
        shutil.copyfile(REPO / "pipeline_v2" / "configs" / "m1.json", config_dir / "m1.json")
        m0_config = read_json(config_dir / "m0.json")
        m0_config["exposure_artifacts"] = []
        m0_config["manual_exposures"] = []
        write_json(config_dir / "m0.json", m0_config)
        self.ids = [f"{n:06d}.txt" for n in range(1, 41)]
        self.raw_by_id = {}
        for index, ident in enumerate(self.ids):
            raw = (
                f"Indexed As: Café Case {index}\r\n2019 FC {index + 1}\r\nFederal Court\r\n\r\n"
                "REASONS FOR JUDGMENT\r\n\r\n[1]\r\nThe Court states the following:\r\n"
                "[9]\r\nQuoted authority 🧑‍⚖️.\r\n[2]\r\nConclusion.\r\n"
            ).encode("utf-8")
            self.raw_by_id[ident] = raw
            (cases / ident).write_bytes(raw)
        labels = {ident: [self.ids[(i + 1) % len(self.ids)]] for i, ident in enumerate(self.ids)}
        write_json(self.root / "data" / "task1_train_files_2026" / "clean_task1_train_labels_2026.json", labels)
        artifacts = self.root / "pipeline_v2" / "artifacts"
        artifacts.mkdir()
        self.m0_bundle = artifacts / "m0-fixture"
        self.m1_bundle = artifacts / "m1-fixture"
        build_m0(self.root, self.m0_bundle)
        build_bundle(self.root, "pipeline_v2/artifacts/m0-fixture", self.m1_bundle)

    def tearDown(self):
        self.temp.cleanup()

    def test_build_is_deterministic_valid_and_write_once(self):
        self.assertTrue(validate_bundle(self.root, self.m1_bundle)["valid"])
        with self.assertRaises(M1Error):
            build_bundle(self.root, "pipeline_v2/artifacts/m0-fixture", self.m1_bundle)
        second = self.root / "pipeline_v2" / "artifacts" / "m1-second"
        build_bundle(self.root, "pipeline_v2/artifacts/m0-fixture", second)
        first_files = {p.relative_to(self.m1_bundle).as_posix(): p.read_bytes() for p in self.m1_bundle.rglob("*") if p.is_file()}
        second_files = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
        self.assertEqual(first_files, second_files)

    def test_reader_returns_exact_raw_evidence_and_neighbors(self):
        reader = SourceReader(self.root, self.m1_bundle)
        parsed = parse_source(self.ids[0], self.raw_by_id[self.ids[0]], read_json(REPO / "pipeline_v2" / "configs" / "m1.json"))
        paragraph = next(unit for unit in parsed["units"] if unit["unit_kind"] == "paragraph" and unit["observed_marker"] == 1)
        opened = reader.open_unit(self.ids[0], paragraph["unit_id"], before=1, after=2)
        self.assertEqual(opened["raw_sha256"], hashlib.sha256(self.raw_by_id[self.ids[0]]).hexdigest())
        start, end = opened["span_bytes"]
        self.assertEqual(opened["text"].encode("utf-8"), self.raw_by_id[self.ids[0]][start:end])
        self.assertEqual(opened["requested_unit_id"], paragraph["unit_id"])
        self.assertIn(paragraph["unit_id"], opened["unit_ids"])
        exact = reader.open_range(self.ids[0], start, end)
        self.assertEqual(exact["text"], opened["text"])
        self.assertEqual(exact["span_chars"][1] - exact["span_chars"][0], len(exact["text"]))

    def test_reader_rejects_invalid_utf8_boundaries_unknown_units_and_drift(self):
        reader = SourceReader(self.root, self.m1_bundle)
        raw = self.raw_by_id[self.ids[0]]
        emoji_byte = raw.index("🧑".encode("utf-8")) + 1
        with self.assertRaises(M1Error):
            reader.open_range(self.ids[0], emoji_byte, emoji_byte + 1)
        with self.assertRaises(M1Error):
            reader.open_unit(self.ids[0], "not-a-unit")
        with self.assertRaises(M1Error):
            reader.open_unit(self.ids[0], "not-a-unit", before=-1)

        source = self.root / "data" / "task1_train_files_2026" / "cases" / self.ids[0]
        source.write_bytes(raw + b" changed")
        with self.assertRaisesRegex(M1Error, "Source drift"):
            SourceReader(self.root, self.m1_bundle).open_unit(self.ids[0], "not-a-unit")

    def test_reader_rejects_resealed_record_row_and_profile_tampering(self):
        source_id = self.ids[0]
        record_path = self.m1_bundle / "sources" / f"{source_id[:-4]}.json"
        record = read_json(record_path)
        record["units"][0]["span_bytes"][1] += 1
        write_json(record_path, record)
        reseal(self.m1_bundle, f"sources/{source_id[:-4]}.json")
        with self.assertRaises(M1Error):
            SourceReader(self.root, self.m1_bundle).open_unit(source_id, record["units"][0]["unit_id"])

        # Restore a pristine bundle, then alter its registry row and consistently reseal.
        shutil.rmtree(self.m1_bundle)
        build_bundle(self.root, "pipeline_v2/artifacts/m0-fixture", self.m1_bundle)
        registry_path = self.m1_bundle / "source_registry.json"
        registry = read_json(registry_path)
        registry["sources"][0]["raw_sha256"] = "0" * 64
        write_json(registry_path, registry)
        reseal(self.m1_bundle, "source_registry.json")
        with self.assertRaises(M1Error):
            SourceReader(self.root, self.m1_bundle).open_unit(source_id, "irrelevant")

        shutil.rmtree(self.m1_bundle)
        build_bundle(self.root, "pipeline_v2/artifacts/m0-fixture", self.m1_bundle)
        manifest_path = self.m1_bundle / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["profile"]["semantic_speaker_or_holding"] = True
        write_json(manifest_path, manifest)
        reseal(self.m1_bundle, "manifest.json")
        with self.assertRaises(M1Error):
            SourceReader(self.root, self.m1_bundle)


if __name__ == "__main__":
    unittest.main()
