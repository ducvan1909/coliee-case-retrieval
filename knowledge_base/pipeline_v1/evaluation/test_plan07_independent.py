from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from knowledge_base.pipeline_v1.analysis_regions import AnalysisRegionError, load_and_validate_region_build, render_region


P = Path(__file__).resolve().parents[1]


class Plan07IndependentEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((P / "reports/plan07_analysis_region_validation.latest.json").read_text(encoding="utf-8"))
        cls.root = Path(cls.report["outputs"]["output_root"])
        cls.maps = [(row, json.loads((cls.root / row["artifact_ref"]).read_text(encoding="utf-8"))) for row in cls.report["cases"]]

    def fixture(self):
        temp = tempfile.TemporaryDirectory(); root = Path(temp.name)
        manifest = json.loads(Path(self.report["outputs"]["build_manifest"]).read_text(encoding="utf-8"))
        for row in manifest["cases"]:
            dst = root / row["artifact_ref"]; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(self.root / row["artifact_ref"], dst)
        mp = root / "analysis_region_build_manifest.json"; mp.write_text(json.dumps(manifest), encoding="utf-8")
        kwargs = {"manifest_path": mp, "source_store": self.report["inputs"]["source_store"], "plan03_report": self.report["inputs"]["plan03_report"],
                  "plan04_report": self.report["inputs"]["plan04_report"], "plan05_report": self.report["inputs"]["plan05_report"],
                  "plan06_report": self.report["inputs"]["plan06_report"], "sourceblock_policy": P / "policies/sourceblock_policy.v1.json",
                  "sentence_policy": P / "policies/sentence_atom_policy.v1.json", "sidecar_policy": P / "policies/sidecar_policy.v1.json",
                  "context_hint_policy": P / "policies/context_hint_policy.v1.json", "region_policy": self.report["inputs"]["policy"]}
        return temp, root, manifest, kwargs

    def test_recompute_coverage_slices_batches_regions_and_hint_dispositions(self):
        values = [v for _, v in self.maps]
        self.assertEqual(sum(len(v["block_roles"]) for v in values), 431)
        eligible = [r for v in values for r in v["block_roles"] if r["eligible"]]
        excluded = [r for v in values for r in v["block_roles"] if not r["eligible"]]
        self.assertEqual((len(eligible), len(excluded)), (369, 62))
        self.assertEqual(Counter(r["role"] for r in excluded), Counter({"audit_only_editorial": 22, "structural_context_candidate_only": 39, "structural_only_not_content": 1}))
        self.assertEqual(sum(r["content_span"]["start_char"] == r["content_span"]["end_char"] for r in excluded), 1)
        self.assertEqual(sum(len(v["targets"]) for v in values), 369)
        self.assertEqual(sum(len(v["slices"]) for v in values), 10)
        self.assertEqual(sum(sum(len(b["work_items"]) for b in v["batches"]) for v in values), 374)
        self.assertEqual(sum(len(v["batches"]) for v in values), 96)
        self.assertEqual(sum(len(v["regions"]) for v in values), 192)
        dispositions = [x for v in values for x in v["hint_dispositions"]]
        self.assertEqual(len(dispositions), 28)
        self.assertEqual(Counter(x["target_eligibility"] for x in dispositions), Counter({"eligible_primary_target": 16, "target_ineligible_structural_only": 12}))
        self.assertEqual(Counter(x["disposition"] for x in dispositions), Counter(self.report["summary"]["hint_disposition_counts"]))

    def test_slice_partitions_and_each_parent_target_exactly_once(self):
        for _, value in self.maps:
            targets = {x["parent_block_id"]: x for x in value["targets"]}
            eligible = {x["block_id"]: x for x in value["block_roles"] if x["eligible"]}
            self.assertEqual(set(targets), set(eligible))
            for bid, target in targets.items():
                slices = sorted((s for s in value["slices"] if s["parent_block_id"] == bid), key=lambda x: x["slice_order"])
                if target["mode"] == "sliced":
                    self.assertGreater(len(slices), 1)
                    self.assertEqual(slices[0]["span"]["start_char"], eligible[bid]["content_span"]["start_char"])
                    self.assertEqual(slices[-1]["span"]["end_char"], eligible[bid]["content_span"]["end_char"])
                    self.assertTrue(all(a["span"]["end_char"] == b["span"]["start_char"] for a, b in zip(slices, slices[1:])))
                else:
                    self.assertEqual(slices, [])

    def test_each_analysis_target_occurs_in_one_region_per_arm(self):
        for _, value in self.maps:
            expected = {target["target_id"] for target in value["targets"]}
            for arm in ("P2a", "P2b"):
                actual = [target_id for region in value["regions"] if region["arm"] == arm for target_id in region["target_ids"]]
                self.assertEqual(set(actual), expected)
                self.assertEqual(len(actual), len(set(actual)))

    def test_recompute_arm_metrics_and_p2b_has_no_new_source_context(self):
        s = self.report["summary"]
        for arm in ("P2a", "P2b"):
            regions = [r for _, v in self.maps for r in v["regions"] if r["arm"] == arm]
            self.assertEqual(len(regions), 96)
            refs = [(r["case_id"], x["span"]["start_char"], x["span"]["end_char"]) for r in regions for x in r["render_items"]]
            proposed = sum(b - a for _, a, b in refs); merged = []
            for cid, a, b in sorted(set(refs)):
                if not merged or cid != merged[-1][0] or a > merged[-1][2]: merged.append([cid, a, b])
                else: merged[-1][2] = max(merged[-1][2], b)
            unique = sum(b - a for _, a, b in merged)
            self.assertEqual((unique, proposed, proposed - unique), (s["arm_metrics"][arm]["unique_source_chars"], s["arm_metrics"][arm]["proposed_source_chars"], s["arm_metrics"][arm]["repeated_source_chars"]))
        comparison = s["p2_context_comparison"]
        self.assertEqual(comparison["new_p2b_context_spans"], 0)
        self.assertEqual(comparison["displaced_p2a_context_spans"], 0)
        for _, value in self.maps:
            a = {r["batch_id"]: r for r in value["regions"] if r["arm"] == "P2a"}; b = {r["batch_id"]: r for r in value["regions"] if r["arm"] == "P2b"}
            for bid in a:
                self.assertEqual(a[bid]["render_items"], b[bid]["render_items"])
                self.assertEqual(a[bid]["render_order"], b[bid]["render_order"])

    def test_renderer_uses_exact_immutable_source_refs_and_no_canonical_text(self):
        store = Path(self.report["inputs"]["source_store"])
        for row, value in self.maps:
            text = (store / "cases" / row["case_id"] / "versions" / row["source_hash"] / "source.txt").read_bytes().decode("utf-8")
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), row["source_hash"])
            self.assertNotIn("source_text", value)
            for region in value["regions"]:
                rendered = render_region(text, region)
                self.assertIn("<TARGET", rendered)
                for item in region["render_items"]:
                    ref = item["span"]; self.assertIn(text[ref["start_char"]:ref["end_char"]], rendered)

    def test_reader_rejects_metric_hint_ref_and_cache_mutations(self):
        temp, root, manifest, kwargs = self.fixture()
        try:
            _, checks = load_and_validate_region_build(**kwargs)
            self.assertEqual(checks["summary"]["primary_target_count"], 369)
            mutations = [("summary", "primary_target_count"), ("summary", "slice_count"), ("summary", "batch_count"), ("summary", "hint_disposition_count")]
            for scope, field in mutations:
                bad = copy.deepcopy(manifest); bad[scope][field] += 1; kwargs["manifest_path"].write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(field=field), self.assertRaises(AnalysisRegionError): load_and_validate_region_build(**kwargs)
            for ref in ("../escape.json", "missing/analysis_workload_map.json"):
                bad = copy.deepcopy(manifest); bad["cases"][0]["artifact_ref"] = ref; kwargs["manifest_path"].write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(ref=ref), self.assertRaises(AnalysisRegionError): load_and_validate_region_build(**kwargs)
            kwargs["manifest_path"].write_text(json.dumps(manifest), encoding="utf-8")
            artifact = root / manifest["cases"][1]["artifact_ref"]; value = json.loads(artifact.read_text(encoding="utf-8")); value["hint_dispositions"].pop(); artifact.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AnalysisRegionError): load_and_validate_region_build(**kwargs)
        finally:
            temp.cleanup()

    def test_historical_artifacts_are_preserved_but_not_selected_current(self):
        all_paths = list(self.root.glob("cases/**/analysis_workload_map.json"))
        refs = {(self.root / row["artifact_ref"]).resolve() for row in self.report["cases"]}
        current_policy = self.report["cases"][0]["artifact_ref"].split("/")[-2]
        selected = {p.resolve() for p in all_paths if p.parent.name == current_policy}
        self.assertEqual(len(refs), 5)
        self.assertGreaterEqual(len(all_paths), len(refs))
        self.assertEqual(selected, refs)
        self.assertTrue(all(p.exists() for p in set(map(Path.resolve, all_paths)) - refs))


if __name__ == "__main__":
    unittest.main()
