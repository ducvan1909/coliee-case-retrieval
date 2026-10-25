"""Independent source/artifact guards and metamorphic fixtures for offline region priority.

The artifact guards deliberately validate the inputs independently of the new
scorer. Scorer-facing tests will use the public API in region_priority_offline
once that implementation is available; expected ranks must not be copied from
that scorer.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "knowledge_base" / "pipeline_v1"
SOURCE_ROOT = PIPELINE / "outputs" / "source_store_v1"
BLOCK_ROOT = PIPELINE / "outputs" / "plan03_source_blocks_v1"
ATOM_ROOT = PIPELINE / "outputs" / "plan04_sentence_atoms_v1"
KOS_MANIFEST = PIPELINE / "manifests" / "selected_kos_manifest.v1.json"
KOS_ROOT = Path(r"G:\Legal-AI\kos_sample")
CASE_IDS = ("013009", "013948", "011904", "045155", "099980")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _source_path(case_id: str, source_hash: str) -> Path:
    return SOURCE_ROOT / "cases" / case_id / "versions" / source_hash / "source.txt"


def _artifact_for(manifest_path: Path, case_id: str) -> Path:
    manifest = _json(manifest_path)
    record = next(item for item in manifest["cases"] if item["case_id"] == case_id)
    return manifest_path.parent / record["artifact_ref"]


def _sourceblock_map(case_id: str):
    return _json(_artifact_for(BLOCK_ROOT / "sourceblock_build_manifest.json", case_id))


def _source_text(case_id: str, source_hash: str | None = None) -> str:
    if source_hash is None:
        source_hash = _json(SOURCE_ROOT / "cases" / case_id / "index.json")["current_source_hash"]
    return _source_path(case_id, source_hash).read_bytes().decode("utf-8")


def _block_text(case_id: str, order: int) -> str:
    block_map = _sourceblock_map(case_id)
    block = next(item for item in block_map["blocks"] if item["order"] == order)
    source = _source_text(case_id, block_map["source_hash"])
    span = block["span"]
    return source[span["start_char"]:span["end_char"]]


def _assert_exact_partition(test: unittest.TestCase, source: str, spans, label: str):
    ordered = sorted(spans, key=lambda span: (span["start_char"], span["end_char"]))
    cursor = 0
    pieces = []
    for span in ordered:
        start, end = span["start_char"], span["end_char"]
        test.assertEqual(start, cursor, f"{label}: gap/overlap at char {cursor}")
        test.assertGreaterEqual(end, start, f"{label}: reversed span")
        pieces.append(source[start:end])
        cursor = end
    test.assertEqual(cursor, len(source), f"{label}: uncovered suffix from {cursor}")
    test.assertEqual("".join(pieces), source, f"{label}: source round trip differs")


class OfflineRegionPriorityInputEvidenceTests(unittest.TestCase):
    """Early factual coverage gates on the exact declared KOS-5 input artifacts."""

    def test_selected_kos_manifest_is_exact_five_and_matches_local_tree(self):
        manifest = _json(KOS_MANIFEST)
        cases = manifest["cases"]
        self.assertEqual(tuple(item["case_id"] for item in cases), CASE_IDS)
        self.assertEqual(manifest["role"], "contract_calibration_only")
        for case in cases:
            base = KOS_ROOT / "cases" / case["case_id"]
            entries = []
            for path in sorted(base.rglob("*"), key=lambda item: item.relative_to(base).as_posix()):
                if path.is_file() and path.suffix.lower() == ".md":
                    raw = path.read_bytes()
                    entries.append({
                        "path": path.relative_to(base).as_posix(),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "byte_length": len(raw),
                    })
            self.assertEqual(len(entries), case["file_count"], case["case_id"])
            self.assertEqual(sum(item["byte_length"] for item in entries), case["total_bytes"])
            canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8")
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), case["tree_sha256"],
                             case["case_id"])

    def test_plan03_and_plan04_cover_full_source_with_matching_provenance(self):
        block_manifest = _json(BLOCK_ROOT / "sourceblock_build_manifest.json")
        atom_manifest = _json(ATOM_ROOT / "sentence_atom_build_manifest.json")
        self.assertEqual(block_manifest["workload"], "KOS-5")
        self.assertEqual(atom_manifest["workload"], "KOS-5")
        for case_id in CASE_IDS:
            with self.subTest(case_id=case_id):
                block_map = _json(_artifact_for(BLOCK_ROOT / "sourceblock_build_manifest.json", case_id))
                atom_map = _json(_artifact_for(ATOM_ROOT / "sentence_atom_build_manifest.json", case_id))
                source_hash = block_map["source_hash"]
                self.assertEqual(atom_map["source_hash"], source_hash)
                source_bytes = _source_path(case_id, source_hash).read_bytes()
                self.assertEqual(hashlib.sha256(source_bytes).hexdigest(), source_hash)
                source = source_bytes.decode("utf-8")
                self.assertEqual(len(source), block_map["source_char_length"])
                self.assertEqual(len(source), atom_map["source_char_length"])
                self.assertTrue(all(block["span"]["source_hash"] == source_hash
                                    for block in block_map["blocks"]))
                self.assertTrue(all(atom["span"]["source_hash"] == source_hash
                                    for atom in atom_map["atoms"]))
                _assert_exact_partition(self, source,
                                        [block["span"] for block in block_map["blocks"]],
                                        f"{case_id} Plan03 blocks")
                _assert_exact_partition(self, source,
                                        [atom["span"] for atom in atom_map["atoms"]],
                                        f"{case_id} Plan04 atoms")


class OfflineRegionPriorityInventoryAndSchedulingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from knowledge_base.pipeline_v1.region_priority_offline import build_inventory
        cls.inventory = build_inventory()

    def test_inventory_contains_every_validated_sourceblock_not_first30_only(self):
        from knowledge_base.pipeline_v1.region_priority_offline.scheduler import ARMS, schedule

        self.assertEqual({c["case_id"] for c in self.inventory["cases"]}, set(CASE_IDS))
        self.assertEqual(len(self.inventory["cases"]), 5)
        by_case = {c["case_id"]: c for c in self.inventory["cases"]}
        for case_id in CASE_IDS:
            rows = sorted((r for r in self.inventory["regions"] if r["case_id"] == case_id),
                          key=lambda r: r["order"])
            block_map = _sourceblock_map(case_id)
            self.assertEqual(len(rows), len(block_map["blocks"]))
            self.assertEqual(len(rows), by_case[case_id]["block_count"])
            self.assertEqual([r["order"] for r in rows], list(range(len(rows))))
            self.assertEqual(rows[-1]["target"]["end_char"], len(self.inventory["sources"][case_id]))
            self.assertEqual(by_case[case_id]["coverage_fraction"], 1.0)
        # Each arm must retain every block, including late source regions.
        for arm in ARMS:
            result = schedule(self.inventory, arm)
            self.assertEqual(len(result["reads"]), len(self.inventory["regions"]))
            self.assertEqual(len({r["region_id"] for r in result["reads"]}), len(result["reads"]))

    def test_kos_metadata_cannot_change_schedule_order_or_labels(self):
        from knowledge_base.pipeline_v1.region_priority_offline.scheduler import ARMS, schedule

        tagged = deepcopy(self.inventory)
        for row in tagged["regions"]:
            row["kos_kind"] = "must_not_be_a_label"
            row["issue_ids"] = ["synthetic-issue"]
            row["para_idxs"] = ["999"]
            row["claim_text"] = "synthetic reference claim"
        for arm in ARMS:
            plain_order = [x["region_id"] for x in schedule(self.inventory, arm)["reads"]]
            tagged_order = [x["region_id"] for x in schedule(tagged, arm)["reads"]]
            self.assertEqual(plain_order, tagged_order)

    def test_scoped_paragraph_references_are_hints_and_unresolved_context_stays_explicit(self):
        rows = [r for r in self.inventory["regions"] if r["case_id"] == "045155"]
        paragraph_20 = next(r for r in rows if r["order"] == 70)
        refs = [x for x in paragraph_20["context_obligations"]
                if x.get("paragraph_number") == "5"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["dependency_status"], "hint")
        self.assertEqual(refs[0]["resolution"], "same_case_raw_marker_hint")
        paragraph_5 = next(r for r in rows if r["order"] == 46)
        self.assertTrue(any(paragraph_5["region_id"] in c.get("block_ids", [])
                            and c.get("dependency_status") == "hint"
                            for c in paragraph_20["packet"]["context"]))
        # The reference is a navigational hint. It is not automatically a
        # sufficient semantic dependency certificate.
        self.assertTrue(all(c["role"] == "CONTEXT" for c in paragraph_20["packet"]["context"]))

        qualified = [r for r in self.inventory["regions"]
                     if r["features"]["counts"].get("qualification", 0)]
        self.assertTrue(qualified)
        self.assertTrue(any(x.get("status") == "unknown" and
                            x.get("reason") == "bounded_neighbors_do_not_prove_condition_quote_or_voice_completion"
                            for r in qualified for x in r["context_obligations"]))

    def test_inventory_parent_source_policy_and_artifact_binding_reject_tampering(self):
        from knowledge_base.pipeline_v1.region_priority_offline import build_inventory

        block_manifest = PIPELINE / "outputs" / "plan03_source_blocks_v1" / "sourceblock_build_manifest.json"
        atom_manifest = PIPELINE / "outputs" / "plan04_sentence_atoms_v1" / "sentence_atom_build_manifest.json"
        with tempfile.TemporaryDirectory(prefix="region-priority-test-") as temp:
            temp_path = Path(temp)
            policy = _json(PIPELINE / "policies" / "sourceblock_policy.v1.json")
            policy["independent_test_tamper"] = True
            policy_path = temp_path / "block_policy.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "policy hash differs"):
                build_inventory(block_policy=policy_path)

            atom_copy = _json(atom_manifest)
            atom_copy["cases"][0]["source_hash"] = "0" * 64
            atom_path = temp_path / "atom_manifest.json"
            atom_path.write_text(json.dumps(atom_copy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source binding mismatch"):
                build_inventory(atom_manifest=atom_path)

            block_copy = _json(block_manifest)
            block_copy["cases"][0]["cache_key"] = "0" * 64
            block_path = temp_path / "block_manifest.json"
            for record in block_copy["cases"]:
                source_artifact = block_manifest.parent / record["artifact_ref"]
                copied_artifact = temp_path / record["artifact_ref"]
                copied_artifact.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_artifact, copied_artifact)
            block_path.write_text(json.dumps(block_copy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest cache binding mismatch"):
                build_inventory(block_manifest=block_path)

            map_root = temp_path / "tampered_maps"
            map_copy_manifest = _json(block_manifest)
            first_ref = map_copy_manifest["cases"][0]["artifact_ref"]
            for record in map_copy_manifest["cases"]:
                source_artifact = block_manifest.parent / record["artifact_ref"]
                copied_artifact = map_root / record["artifact_ref"]
                copied_artifact.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_artifact, copied_artifact)
            copied_map = map_root / first_ref
            damaged = _json(copied_map)
            damaged["source_hash"] = "0" * 64
            copied_map.write_text(json.dumps(damaged), encoding="utf-8")
            map_manifest_path = map_root / "sourceblock_build_manifest.json"
            map_manifest_path.write_text(json.dumps(map_copy_manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_inventory(block_manifest=map_manifest_path)

    def test_packet_cost_charges_shared_scaffold_and_repeated_context_per_target(self):
        from knowledge_base.pipeline_v1.region_priority_offline.scheduler import schedule

        rows = self.inventory["regions"]
        with_context = next(r for r in rows if r["packet"]["context"])
        # The rendered packet includes the shared scaffold and raw context. Each
        # request pays its own serialized bytes even when the context is shared.
        packet = json.loads(with_context["serialized_payload"])
        self.assertEqual(packet, with_context["packet"])
        self.assertTrue(packet["scaffold"])
        self.assertEqual(with_context["serialized_utf8_bytes"],
                         len(with_context["serialized_payload"].encode("utf-8")))
        repeated = dict(with_context)
        repeated["region_id"] = with_context["region_id"] + "-repeat-fixture"
        repeated["target"] = dict(with_context["target"],
                                  start_char=with_context["target"]["start_char"] + 1,
                                  end_char=with_context["target"]["end_char"] + 1)
        rows_fixture = [with_context, repeated]
        inventory_fixture = {"regions": rows_fixture}
        result = schedule(inventory_fixture, "source_order", bytes_per_token=4)
        expected = sum(math.ceil(r["serialized_utf8_bytes"] / 4) for r in rows_fixture)
        self.assertEqual(result["estimated_tokens"], expected)
        self.assertEqual(len(result["reads"]), 2)
        self.assertEqual(sum(len(r["packet"]["context"]) for r in rows_fixture),
                         2 * len(with_context["packet"]["context"]))

    def test_budget_residual_is_explicit_and_not_a_semantic_negative(self):
        from knowledge_base.pipeline_v1.region_priority_offline.scheduler import schedule

        rows = self.inventory["regions"]
        selected = rows[:3]
        one_cost = math.ceil(selected[0]["serialized_utf8_bytes"] / 4)
        result = schedule({"regions": selected}, "source_order", budget=one_cost, bytes_per_token=4)
        self.assertEqual(len(result["reads"]), 1)
        self.assertEqual(len(result["unknown_residual"]), 2)
        self.assertTrue(all(x["status"] == "not_assessed" for x in result["unknown_residual"]))
        self.assertFalse(result["semantic_stopping"])


class OfflineRegionPriorityExposureTests(unittest.TestCase):
    def test_partial_target_and_context_are_separate_and_unknown_alignment_excluded(self):
        from knowledge_base.pipeline_v1.region_priority_offline.core import _exposure

        unit = {"case_id": "013009", "alignment": {"status": "exact", "spans": [
            {"start_char": 10, "end_char": 20, "quote": "0123456789"}]}}
        def region(rid, target, context):
            return {"case_id": "013009", "target": target,
                    "packet": {"context": context}}
        regions = {
            "first": region("first", {"start_char": 10, "end_char": 15},
                             [{"start_char": 15, "end_char": 18}]),
            "second": region("second", {"start_char": 15, "end_char": 20}, []),
        }
        one_read = {"reads": [{"region_id": "first", "read_order": 0}]}
        partial = _exposure(unit, one_read, regions)
        self.assertTrue(partial["eligible_denominator"])
        self.assertEqual(partial["first_target"]["target_intersection_chars"], 5)
        self.assertIsNone(partial["first_full_target"])
        self.assertEqual(partial["covered_target_chars"], 5)
        self.assertEqual(partial["covered_context_chars"], 3)
        self.assertEqual(partial["status"], "not_assessed")
        complete = _exposure(unit, {"reads": one_read["reads"] + [{"region_id": "second", "read_order": 1}]}, regions)
        self.assertEqual(complete["covered_target_chars"], 10)
        self.assertTrue(complete["target_fullspan"])
        self.assertFalse(complete["context_fullspan"])

        for status in ("ambiguous", "no_match", "empty_evidence"):
            unknown = {"case_id": "013009", "alignment": {"status": status, "spans": []}}
            excluded = _exposure(unknown, one_read, regions)
            self.assertFalse(excluded["eligible_denominator"])
            self.assertEqual(excluded["status"], "excluded_alignment")
            self.assertEqual(excluded["evidence_chars"], 0)
            self.assertNotIn("para_idxs", excluded)

    def test_context_merge_removes_target_overlap_and_exposes_context_cap_residual(self):
        from knowledge_base.pipeline_v1.region_priority_offline.core import _merge_context

        source = "abcdefghijklmnopqrstuvwxyz" * 12
        target = {"start_char": 10, "end_char": 20}
        raw_contexts = [
            {"start_char": 2, "end_char": 15, "reason": "adjacent_atom", "atom_id": "a"},
            {"start_char": 7, "end_char": 13, "reason": "reference", "block_id": "b"},
        ]
        merged, unknown = _merge_context(source, raw_contexts, target)
        self.assertFalse(unknown)
        self.assertEqual([(x["start_char"], x["end_char"]) for x in merged], [(2, 10)])
        self.assertEqual(merged[0]["text"], source[2:10])
        self.assertEqual(set(merged[0]["reasons"]), {"adjacent_atom", "reference"})
        self.assertEqual(set(merged[0]["atom_ids"]), {"a"})
        self.assertEqual(set(merged[0]["block_ids"]), {"b"})

        many = [{"start_char": i * 3, "end_char": i * 3 + 1,
                 "reason": f"raw-{i}", "atom_id": f"atom-{i}"} for i in range(13)]
        included, residual = _merge_context(source, many, {"start_char": 100, "end_char": 101})
        self.assertEqual(len(included), 12)
        self.assertEqual(len(residual), 1)
        self.assertEqual(residual[0]["status"], "not_assessed")
        self.assertEqual(residual[0]["reason"], "context_cap")
        recovered = sorted((x["start_char"], x["end_char"]) for x in included + residual)
        self.assertEqual(recovered, sorted((x["start_char"], x["end_char"]) for x in many))


class OfflineRegionPriorityCliReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The CLI report is generated fresh in an isolated temporary directory
        # so the tests never depend on a prior manual run or stale output.
        cls._output_tmp = tempfile.TemporaryDirectory(prefix="region-priority-cli-")
        cls.output_root = Path(cls._output_tmp.name) / "run"
        completed = subprocess.run(
            [sys.executable, "-m", "knowledge_base.pipeline_v1.region_priority_offline",
             "run", "--output-root", str(cls.output_root)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        if completed.returncode != 0:
            cls._output_tmp.cleanup()
            raise RuntimeError(
                "fresh offline CLI run failed\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        cls.report = _json(cls.output_root / "report.json")

    @classmethod
    def tearDownClass(cls):
        cls._output_tmp.cleanup()

    def test_real_cli_report_separates_protocol_from_semantic_quality_and_excludes_queries(self):
        report = self.report
        implementation = PIPELINE / "region_priority_offline"
        fingerprints = {Path(item["path"]).name: item["sha256"]
                        for item in report["implementation_fingerprints"]}
        for source in implementation.glob("*.py"):
            with self.subTest(source=source.name):
                self.assertEqual(fingerprints.get(source.name),
                                 hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(report["protocol_status"], "pass")
        self.assertEqual(report["semantic_quality"], "not_assessed")
        self.assertEqual(report["qualified_evidence_quality"], "not_assessed")
        self.assertTrue(all(report["protocol_checks"].values()))
        summary = report["summary"]
        self.assertEqual(summary["case_count"], 5)
        self.assertEqual(summary["kos_file_count"], 61)
        self.assertEqual(summary["kos_parse_error_count"], 0)
        self.assertEqual(summary["alignment_counts"], {"exact": 9, "whitespace_normalized": 9})
        # The two query cases carry zero KOS AU references; they are NA, not
        # zero-error or 100%-recall cases. This report must preserve them as such.
        roles = {x["case_id"]: x["kos_role"] for x in report["kos_inventory"]}
        self.assertEqual({c for c, role in roles.items() if role == "query"}, {"013009", "013948"})
        au_cases = {x["case_id"] for x in report["au_audit"]}
        self.assertFalse({"013009", "013948"} & au_cases)
        self.assertEqual(summary["aligned_denominator"], 18)
        self.assertEqual(summary["excluded_alignment_count"], 0)
        self.assertEqual(report["cost"]["network_requests"], 0)
        self.assertEqual(report["cost"]["inference_requests"], 0)
        self.assertIn("estimated only", report["cost"]["billing"])
        self.assertIn("not full real extraction prompt", report["cost"]["billing"])

    def test_first_target_packets_keep_tail_context_and_mark_distant_dependency_gap(self):
        by_id = {x["kos_id"]: x for x in self.report["au_audit"]}
        relevant = {
            "au-045155-classification-reasons-s27": {
                "tail": "authorized by the Commissioner or his delegate",
                "location": "TARGET",
                "missing_remote": "reasonable grounds",
            },
            "au-045155-policy-reasons-exhaust": {
                "tail": "However, there will be circumstances in which the internal remedies are not adequate",
                "location": "TARGET",
            },
            "au-045155-exhaust-grievance-general": {
                "tail": "There are exceptions to this general rule",
                "location": "CONTEXT",
            },
            "au-099980-right-to-make-submissions": {
                "tail": "appointment of a person is at issue (section 72)",
                "location": "TARGET",
            },
        }
        for kos_id, facts in relevant.items():
            row = by_id[kos_id]
            self.assertIn(row["alignment"]["status"], ("exact", "whitespace_normalized"))
            first = row["arms"]["source_order"]["first_target"]
            self.assertIsNotNone(first)
            packet = next(p for p in row["arms"]["source_order"]["raw_context_packets"]
                          if p["region_id"] == first["region_id"])
            target_text = packet["target"]["text"]
            context_text = "\n".join(c["text"] for c in packet["context"])
            opened = target_text + "\n" + context_text
            self.assertIn(facts["tail"], opened, kos_id)
            if facts["location"] == "TARGET":
                self.assertIn(facts["tail"], target_text, kos_id)
                aligned_chars = sum(span["end_char"] - span["start_char"]
                                    for span in row["alignment"]["spans"])
                self.assertEqual(first["target_intersection_chars"], aligned_chars, kos_id)
            else:
                self.assertNotIn(facts["tail"], target_text, kos_id)
                self.assertIn(facts["tail"], context_text, kos_id)
            if "missing_remote" in facts:
                # This is a concrete residual context gap at first TARGET
                # evidence; passing this assertion records the gap, not adequacy.
                self.assertNotIn(facts["missing_remote"], opened, kos_id)


class OfflineRegionPriorityMetamorphicFixtures(unittest.TestCase):
    """Metamorphic checks use relations, not scorer-produced expected ranks."""

    @classmethod
    def setUpClass(cls):
        from knowledge_base.pipeline_v1.region_priority_offline import build_inventory
        cls.inventory = build_inventory()

    def test_name_rename_preserves_rule_feature_counts_on_fixture_and_real_case_copy(self):
        from knowledge_base.pipeline_v1.region_priority_offline import extract_features

        before, after = self.name_rename_fixture()
        first, second = extract_features(before), extract_features(after)
        self.assertEqual(first["counts"], second["counts"])
        self.assertEqual(first["lane_scores"], second["lane_scores"])

        # Real-source copy: only PERSON/ORG surface forms change; court/counsel
        # roles, statute references, punctuation and the surrounding source stay.
        source = _source_text("013009")
        self.assertIn("Krassina Kostadinov", source)
        self.assertIn("Waldman & Associates", source)
        renamed = source.replace("Krassina Kostadinov", "Alicia Nguyen").replace(
            "Waldman & Associates", "Northstar Legal")
        self.assertNotEqual(source, renamed)
        original_features = extract_features(source)
        renamed_features = extract_features(renamed)
        self.assertEqual(original_features["counts"], renamed_features["counts"])
        self.assertEqual(original_features["lane_scores"], renamed_features["lane_scores"])
        self.assertEqual(original_features["open_quote"], renamed_features["open_quote"])

        # Equal-length edits keep source offsets fixed so each region is mapped
        # by its original ordinal/span. Count changed ordinal ranks per arm.
        exact_source = self.inventory["sources"]["013009"]
        replacements = {
            "Krassina Kostadinov": "Marianne Montgomery",
            "Waldman & Associates": "Northam & Consulting",
        }
        renamed_source = exact_source
        for old, new in replacements.items():
            self.assertEqual(len(old), len(new), (old, new))
            self.assertIn(old, renamed_source)
            renamed_source = renamed_source.replace(old, new)
        from knowledge_base.pipeline_v1.region_priority_offline import schedule
        original_rank_measures = {}
        transformed = deepcopy(self.inventory)
        for row in transformed["regions"]:
            if row["case_id"] == "013009":
                span = row["target"]
                text = renamed_source[span["start_char"]:span["end_char"]]
                row["features"] = extract_features(text)
        for arm in ("round_robin", "source_order", "old_cue"):
            original = [x["region_id"] for x in schedule(self.inventory, arm)["reads"]]
            renamed_order = [x["region_id"] for x in schedule(transformed, arm)["reads"]]
            old_rank = {rid: i for i, rid in enumerate(original)}
            new_rank = {rid: i for i, rid in enumerate(renamed_order)}
            changed = sum(old_rank[rid] != new_rank[rid] for rid in old_rank)
            original_rank_measures[arm] = {"rank_changed_region_count": changed,
                                           "compared_region_count": len(old_rank)}
            self.assertEqual(changed, 0, original_rank_measures[arm])
        self.assertTrue(original_rank_measures)

    def test_negation_exception_variants_remain_distinct_source_spans(self):
        from knowledge_base.pipeline_v1.region_priority_offline import extract_features, schedule

        first, second = self.negation_exception_fixture()
        self.assertNotEqual(first, second)
        f1, f2 = extract_features(first), extract_features(second)
        self.assertTrue(f1["counts"]["negation"])
        self.assertTrue(f2["counts"]["negation"])
        # Similar content with different scope remains two independently
        # addressable source spans; no semantic text dedup is permissible.
        self.assertIn("not liable", first)
        self.assertIn("no exception", second)
        rows = []
        for i, (text, features) in enumerate(((first, f1), (second, f2))):
            rows.append({"region_id": f"fixture-{i}", "case_id": "013009",
                         "source_hash": "fixture-source", "target": {"start_char": i * 100,
                         "end_char": i * 100 + len(text)}, "position_stratum": i,
                         "features": features, "serialized_utf8_bytes": len(text.encode("utf-8"))})
        result = schedule({"regions": rows}, "round_robin")
        self.assertEqual({x["region_id"] for x in result["reads"]}, {"fixture-0", "fixture-1"})

    def test_overlapping_preview_metadata_cannot_change_full_source_schedule(self):
        from knowledge_base.pipeline_v1.region_priority_offline import schedule

        base = {"regions": self.inventory["regions"][:12]}
        with_duplicate_views = deepcopy(base)
        row = with_duplicate_views["regions"][0]
        text = self.inventory["sources"][row["case_id"]][row["target"]["start_char"]:row["target"]["end_char"]]
        preview = text[:min(180, len(text))]
        row["preview_views"] = [{"span": (0, len(preview)), "text": preview},
                                {"span": (0, len(preview)), "text": preview}]
        for arm in ("round_robin", "source_order", "old_cue"):
            original = [x["region_id"] for x in schedule(base, arm)["reads"]]
            duplicated = [x["region_id"] for x in schedule(with_duplicate_views, arm)["reads"]]
            self.assertEqual(original, duplicated)

    def test_truncated_kos_tails_are_diagnostic_only_and_full_source_retains_context(self):
        kos = KOS_ROOT / "cases"
        examples = {
            "045155": (
                "authority_units/au-045155-classification-reasons-s27.md",
                "subject only to the terms",
            ),
            "045155_policy": (
                "authority_units/au-045155-policy-reasons-exhaust.md", "ad",
            ),
            "045155_general": (
                "authority_units/au-045155-exhaust-grievance-general.md", "propositi",
            ),
            "099980": (
                "authority_units/au-099980-right-to-make-submissions.md", "appointmen",
            ),
        }
        for key, (relative, tail) in examples.items():
            case_id = "099980" if key == "099980" else "045155"
            snippet = (kos / case_id / relative).read_text(encoding="utf-8")
            self.assertIn(tail, snippet, key)

        # SourceBlock order comes from the Plan 03 manifest and exact spans,
        # independent of KOS para_idxs and without claiming semantic adequacy.
        s27 = _block_text("045155", 71)
        self.assertIn("subject only to the terms of subsection 27(3)", s27)
        self.assertIn("authorized by the Commissioner or his delegate", s27)
        self.assertIn("Section 27 has been set out earlier in paragraph 5", _block_text("045155", 70))
        section_27 = _block_text("045155", 46)
        self.assertIn('"(3) Except in relation to decisions on disciplinary offences', section_27)
        self.assertIn("reasonable grounds", section_27)

        policy = _block_text("045155", 56)
        self.assertIn("However, there will be circumstances in which the internal remedies are not adequate", policy)
        general = _block_text("045155", 53)
        exception = _block_text("045155", 54)
        self.assertIn("adequate alternate remedy", general)
        self.assertIn("There are exceptions to this general rule", exception)

        submissions = _block_text("099980", 104)
        self.assertIn("appointment of a person is at issue (section 72)", submissions)

    @staticmethod
    def overlapping_preview_fixture():
        # Inserting a second preview over an already represented source interval
        # must not alter full-source feature counts or scheduler labels/claims.
        return {
            "source": "The Court held that Smith owed $2,000 under section 12.\n",
            "previews": [(0, 59)],
            "overlap_to_insert": (0, 59),
        }

    @staticmethod
    def name_rename_fixture():
        # Two different people preserve court roles, doctrine terms, citation
        # punctuation and all token counts apart from the replacement names.
        return (
            "Judge Alice Morgan held that Alice Morgan violated section 12; "
            "the Court affirmed under statute 5.\n",
            "Judge Bruno Rivera held that Bruno Rivera violated section 12; "
            "the Court affirmed under statute 5.\n",
        )

    @staticmethod
    def negation_exception_fixture():
        return (
            "The defendant is liable under section 12. The defendant is not liable "
            "under section 12 unless an exception applies.\n",
            "The defendant is liable under section 12. The defendant is liable "
            "under section 12 unless no exception applies.\n",
        )

    @staticmethod
    def mixed_evidence_coverage_fixture():
        return {
            "evidence": [(0, 8)],
            "target": [(10, 18)],
            "context": [(20, 30)],
            "ambiguous": [(32, 40)],
            "no_match": [],
        }


if __name__ == "__main__":
    unittest.main()
