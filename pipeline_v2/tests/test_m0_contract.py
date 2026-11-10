from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pipeline_v2.m0 import M0Error, build_bundle, validate_bundle


REPO = Path(__file__).resolve().parents[2]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def make_fixture(root: Path, exposure_artifacts=None, manual_exposures=None):
    (root / "pipeline_v2" / "configs").mkdir(parents=True)
    (root / "data" / "task1_train_files_2026" / "cases").mkdir(parents=True)
    config = read_json(REPO / "pipeline_v2" / "configs" / "m0.json")
    config["exposure_artifacts"] = exposure_artifacts or []
    config["manual_exposures"] = manual_exposures or []
    write_json(root / "pipeline_v2" / "configs" / "m0.json", config)

    ids = [f"{n:06d}.txt" for n in range(1, 41)]
    cases = root / "data" / "task1_train_files_2026" / "cases"
    for index, ident in enumerate(ids):
        (cases / ident).write_bytes(f"Synthetic UTF-8 fixture source {index}\r\nSecond paragraph.\r\n".encode("utf-8"))
    labels = {ident: [ids[(i + 1) % len(ids)]] for i, ident in enumerate(ids)}
    write_json(root / "data" / "task1_train_files_2026" / "clean_task1_train_labels_2026.json", labels)
    return cases, ids


class M0ContractTests(unittest.TestCase):
    def build_fixture(self, temp, *, exposures=None, manual=None, name="bundle"):
        root = Path(temp) / "repo"
        cases, ids = make_fixture(root, exposures, manual)
        output = root / "pipeline_v2" / "artifacts" / name
        build_bundle(root, output)
        return root, cases, ids, output

    def test_build_is_deterministic_train_only_and_has_no_gold_edges(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _, ids, first = self.build_fixture(temp, name="one")
            first_bytes = {p.name: p.read_bytes() for p in first.iterdir()}
            second = root / "pipeline_v2" / "artifacts" / "two"
            build_bundle(root, second)
            self.assertEqual(first_bytes, {p.name: p.read_bytes() for p in second.iterdir()})

            cohort = read_json(first / "cohort.json")
            self.assertEqual(len(cohort["discovery_queries"]), 10)
            self.assertEqual(len(cohort["holdout_queries"]), 10)
            self.assertEqual(set(cohort["discovery_queries"]).intersection(cohort["holdout_queries"]), set())
            self.assertTrue(set(cohort["discovery_queries"] + cohort["holdout_queries"]).issubset(cohort["eligible_query_ids"]))
            self.assertEqual(cohort["eligible_query_ids"], sorted(cohort["eligible_query_ids"]))

            candidate = read_json(first / "candidate_manifest.json")
            self.assertEqual(candidate["candidate_ids"], ids)
            self.assertTrue(candidate["contains_gold_edges"] is False)
            evaluator = read_json(first / "evaluator_metadata.json")
            self.assertEqual(evaluator["query_ids"], ids)
            self.assertEqual(evaluator["counts"]["queries"], len(ids))
            self.assertNotIn("edges", candidate)
            self.assertNotIn("gold", cohort)
            self.assertNotIn("gold_edges", evaluator)
            self.assertEqual(validate_bundle(root, first)["valid"], True)

            readiness = read_json(first / "readiness.json")
            self.assertEqual(readiness["m0"], "prepared_with_pending_model_profiles")
            self.assertEqual(readiness["dense"], "not_ready")
            self.assertEqual(readiness["runtime"], "not_ready")
            self.assertFalse(readiness["m1_or_later_executed"])

    def test_exposure_and_reserved_query_ids_are_excluded_with_reasons(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            history_dir = root / "knowledge_base" / "pipeline_v1"
            history_dir.mkdir(parents=True)
            study = {"discovery_queries": ["000001.txt"], "verification_queries": ["000002.txt"],
                     "sampling_protocol": {"excluded_queries": ["000003.txt"]}}
            registry = {"calibration": ["000005.txt"], "pilot": {"train": {
                "short": {"development": ["000006.txt"], "holdout": ["000007.txt"]},
                "medium": {"development": [], "holdout": []},
                "long": {"development": [], "holdout": []},
            }}}
            au = {"cases": {"000008": {"role": "candidate"}}, "query_gold_pairs": []}
            write_json(history_dir / "study.json", study)
            write_json(history_dir / "registry.json", registry)
            write_json(history_dir / "au.json", au)
            spec = [
                {"path": "knowledge_base/pipeline_v1/study.json", "adapter": "rule_study"},
                {"path": "knowledge_base/pipeline_v1/registry.json", "adapter": "split_registry"},
                {"path": "knowledge_base/pipeline_v1/au.json", "adapter": "au_reference"},
            ]
            root, _, _, bundle = self.build_fixture(temp, exposures=spec, manual=["000004.txt"])
            cohort = read_json(bundle / "cohort.json")
            excluded = {entry["case_id"]: set(entry["reasons"]) for entry in cohort["excluded_queries"]}
            for ident in ("000001.txt", "000002.txt", "000003.txt", "000004.txt", "000005.txt", "000006.txt", "000007.txt", "000008.txt"):
                self.assertIn(ident, excluded)
            self.assertNotIn("000001.txt", cohort["eligible_query_ids"])
            self.assertNotIn("000004.txt", cohort["discovery_queries"] + cohort["holdout_queries"])
            ledger = read_json(bundle / "exposure_ledger.json")
            by_id = {item["case_id"]: {reason["kind"] for reason in item["reasons"]} for item in ledger["entries"]}
            self.assertIn("query_gold_exposed", by_id["000001.txt"])
            self.assertIn("reserved_holdout", by_id["000007.txt"])
            self.assertIn("candidate_read_not_query_gold", by_id["000008.txt"])
            self.assertNotIn("query_gold_exposed", by_id["000008.txt"])
            self.assertTrue(ledger["coverage"]["history_complete"] is False)
            self.assertEqual(ledger["coverage"]["freshness_claim"], "fresh-by-ledger")

    def test_source_drift_invalidates_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root, cases, ids, bundle = self.build_fixture(temp)
            (cases / ids[0]).write_bytes(b"changed source\n")
            with self.assertRaises(M0Error):
                validate_bundle(root, bundle)

    def test_seal_tamper_and_resealed_semantic_tamper_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _, _, bundle = self.build_fixture(temp)
            cohort_path = bundle / "cohort.json"
            cohort_path.write_text(cohort_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaises(M0Error):
                validate_bundle(root, bundle)

        with tempfile.TemporaryDirectory() as temp:
            root, _, _, bundle = self.build_fixture(temp)
            cohort_path = bundle / "cohort.json"
            cohort = read_json(cohort_path)
            cohort["discovery_queries"][0] = "999999.txt"
            write_json(cohort_path, cohort)
            seal_path = bundle / "seal.json"
            seal = read_json(seal_path)
            raw = cohort_path.read_bytes()
            seal["files"]["cohort.json"] = {"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
            write_json(seal_path, seal)
            with self.assertRaises(M0Error):
                validate_bundle(root, bundle)

    def test_build_is_write_once_and_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _, _, bundle = self.build_fixture(temp)
            before = {p.name: p.read_bytes() for p in bundle.iterdir()}
            with self.assertRaises(M0Error):
                build_bundle(root, bundle)
            self.assertEqual(before, {p.name: p.read_bytes() for p in bundle.iterdir()})

    def test_real_au_reference_gold_ids_are_separately_marked_as_serialized_gold(self):
        path = REPO / "knowledge_base" / "pipeline_v1" / "au_reference_gold_exposed_v1" / "manifest.json"
        data = read_json(path)
        pair_query_ids = {row["query_id"] for row in data["query_gold_pairs"]}
        source_query_ids = {ident for ident, record in data["cases"].items() if record["role"] in ("query", "both")}
        self.assertEqual(len(pair_query_ids), 401)
        self.assertEqual(len(source_query_ids), 102)
        self.assertEqual(len(pair_query_ids - source_query_ids), 299)

        # Full historical bundle integration runs after M0's configured adapters have completed.
        bundle_roots = list((REPO / "pipeline_v2" / "artifacts").glob("m0_*"))
        if not bundle_roots:
            self.skipTest("real M0 bundle not built yet")
        ledger = read_json(sorted(bundle_roots)[-1] / "exposure_ledger.json")
        by_id = {item["case_id"]: item["reasons"] for item in ledger["entries"]}
        for ident in pair_query_ids:
            self.assertTrue(any(reason["kind"] == "serialized_gold_reference" for reason in by_id.get(ident + ".txt", [])), ident)


if __name__ == "__main__":
    unittest.main()
