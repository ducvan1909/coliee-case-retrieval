from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pipeline_v2.m0 import build_bundle as build_m0
from pipeline_v2.navigation import M2Error, NavigationReader, build_bundle as build_m2, validate_bundle as validate_m2
from pipeline_v2.source import M1Error, build_bundle as build_m1


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


class M2NavigationStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / "repo"
        config_dir = cls.root / "pipeline_v2" / "configs"
        cases = cls.root / "data" / "task1_train_files_2026" / "cases"
        config_dir.mkdir(parents=True)
        cases.mkdir(parents=True)
        for name in ("m0.json", "m1.json", "m2.json"):
            shutil.copyfile(REPO / "pipeline_v2" / "configs" / name, config_dir / name)
        m0_config = read_json(config_dir / "m0.json")
        m0_config["exposure_artifacts"] = []
        m0_config["manual_exposures"] = []
        write_json(config_dir / "m0.json", m0_config)
        cls.ids = [f"{n:06d}.txt" for n in range(1, 41)]
        cls.raw_by_id = {}
        for index, ident in enumerate(cls.ids):
            raw = (
                f"Indexed As: Café Case {index}\r\n2019 FC {index + 1}\r\nFederal Court\r\n\r\n"
                "REASONS FOR JUDGMENT\r\n\r\n[1]\r\nThe Court states the following:\r\n"
                "[9]\r\nQuoted authority 🧑‍⚖️ with <FRAGMENT_SUPPRESSED>.\r\n[2]\r\nConclusion.\r\n"
            ).encode("utf-8")
            cls.raw_by_id[ident] = raw
            (cases / ident).write_bytes(raw)
        labels = {ident: [cls.ids[(i + 1) % len(cls.ids)]] for i, ident in enumerate(cls.ids)}
        write_json(cls.root / "data" / "task1_train_files_2026" / "clean_task1_train_labels_2026.json", labels)
        artifacts = cls.root / "pipeline_v2" / "artifacts"
        artifacts.mkdir()
        cls.m0_bundle = artifacts / "m0-fixture"
        cls.m1_bundle = artifacts / "m1-fixture"
        cls.m2_bundle = artifacts / "m2-fixture"
        build_m0(cls.root, cls.m0_bundle)
        build_m1(cls.root, "pipeline_v2/artifacts/m0-fixture", cls.m1_bundle)
        build_m2(cls.root, "pipeline_v2/artifacts/m1-fixture", "pipeline_v2/artifacts/m2-fixture")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_bundle_valid_deterministic_and_write_once(self):
        self.assertTrue(validate_m2(self.root, "pipeline_v2/artifacts/m2-fixture")["valid"])
        with self.assertRaises(M2Error):
            build_m2(self.root, "pipeline_v2/artifacts/m1-fixture", "pipeline_v2/artifacts/m2-fixture")
        second = self.root / "pipeline_v2" / "artifacts" / "m2-second"
        build_m2(self.root, "pipeline_v2/artifacts/m1-fixture", "pipeline_v2/artifacts/m2-second")
        first_files = {p.relative_to(self.m2_bundle).as_posix(): p.read_bytes()
                       for p in self.m2_bundle.rglob("*") if p.is_file()}
        second_files = {p.relative_to(second).as_posix(): p.read_bytes()
                        for p in second.rglob("*") if p.is_file()}
        self.assertEqual(first_files, second_files)

    def test_reader_map_anchor_pagination_and_context_materialize_exact_source(self):
        reader = NavigationReader(self.root, "pipeline_v2/artifacts/m2-fixture")
        ident = self.ids[0]
        all_rows = []
        offset = 0
        while True:
            page = reader.map(ident, offset=offset, limit=1)
            all_rows.extend(page["items"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        paragraph = next(row for row in all_rows if row["unit_kind"] == "paragraph" and row["observed_marker"] == 9)
        anchor_rows = []
        offset = 0
        while True:
            page = reader.anchors(ident, paragraph["handle"], offset=offset, limit=1)
            anchor_rows.extend(page["items"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        self.assertEqual(paragraph["anchor_count"], len(anchor_rows))
        self.assertTrue(any(row["anchor_kind"] == "placeholder" for row in anchor_rows))
        source_cues = reader.source_anchors(ident, limit=1)
        self.assertEqual(source_cues["total"], 1)
        opened = reader.open_context(ident, paragraph["handle"])
        raw = self.raw_by_id[ident]
        start, end = opened["span_bytes"]
        self.assertEqual(opened["text"], raw[start:end].decode("utf-8"))
        self.assertEqual([component["kind"] for component in opened["components"]],
                         ["previous_context", "parent", "next_context"])
        self.assertFalse(opened["M4_delivery_recorded"])

    def test_resealed_navigation_tamper_and_source_drift_are_rejected(self):
        tampered = self.root / "pipeline_v2" / "artifacts" / "m2-tampered"
        shutil.copytree(self.m2_bundle, tampered)
        relative = "sources/000001.json"
        path = tampered / relative
        value = read_json(path)
        value["navigation"][0]["token_count"] = 17
        write_json(path, value)
        reseal(tampered, relative)
        with self.assertRaises(M2Error):
            validate_m2(self.root, "pipeline_v2/artifacts/m2-tampered")

        source_path = self.root / "data" / "task1_train_files_2026" / "cases" / self.ids[0]
        original = source_path.read_bytes()
        source_path.write_bytes(original + b"drift")
        try:
            with self.assertRaises((M1Error, M2Error)):
                NavigationReader(self.root, "pipeline_v2/artifacts/m2-fixture").map(self.ids[0])
        finally:
            source_path.write_bytes(original)

    def test_profile_drift_is_rejected_before_reading_map(self):
        profile_path = self.root / "pipeline_v2" / "configs" / "m2.json"
        profile = read_json(profile_path)
        original = profile_path.read_bytes()
        profile["preview"]["max_chars"] = 239
        write_json(profile_path, profile)
        try:
            with self.assertRaises(M2Error):
                NavigationReader(self.root, "pipeline_v2/artifacts/m2-fixture")
        finally:
            profile_path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
