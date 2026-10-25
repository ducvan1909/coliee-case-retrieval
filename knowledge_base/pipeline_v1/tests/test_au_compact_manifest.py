import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_compact.manifest import build_manifest, preflight


class CompactManifestTests(unittest.TestCase):
    def base(self, source_hash):
        return {"artifact_type": "AUOnlyLockedManifest", "schema_version": "au-only-manifest-v1", "requests": [{"case_id": "000001", "source_hash": source_hash, "request_id": "r-1", "expected_target_ids": ["at-1"], "input_tokens": 11, "source_refs": [{"role": "target", "start_char": 0, "end_char": 4, "target_ids": ["at-1"]}], "spec": {"caps": {"output_tokens": 1600}}}]}

    def plan04(self, root, source_hash):
        relative = "cases/000001/atoms.json"; atom = {"case_id": "000001", "source_hash": source_hash, "cache_key": "c" * 64, "segmenter_version": "s1", "policy_sha256": "p" * 64, "atoms": [{"atom_id": "sa-1", "case_id": "000001", "source_hash": source_hash, "span": {"start_char": 0, "end_char": 4}}]}
        path = Path(root) / relative; path.parent.mkdir(parents=True); path.write_text(json.dumps(atom), encoding="utf-8")
        (Path(root) / "sentence_atom_build_manifest.json").write_text(json.dumps({"status": "pass", "cases": [{"case_id": "000001", "source_hash": source_hash, "cache_key": atom["cache_key"], "artifact_ref": relative}]}), encoding="utf-8")
        return path

    def test_build_preserves_base_and_pins_exact_relative_map(self):
        source = "Rule"; digest = hashlib.sha256(source.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); base = root / "base.json"; base.write_text(json.dumps(self.base(digest)), encoding="utf-8"); before = base.read_bytes(); atom_path = self.plan04(root / "plan04", digest)
            manifest = build_manifest(base, root / "plan04"); base_unchanged = base.read_bytes() == before; atom_sha = hashlib.sha256(atom_path.read_bytes()).hexdigest()
            request = manifest["requests"][0]
            self.assertTrue(base_unchanged); self.assertEqual(request["spec"]["caps"]["output_tokens"], 800); self.assertEqual(request["atom_binding"]["atom_map_relative_path"], "cases/000001/atoms.json"); self.assertEqual(request["atom_binding"]["atom_map_sha256"], atom_sha)

    def test_preflight_reports_catalog_and_rejects_tampered_map(self):
        source = "Rule"; digest = hashlib.sha256(source.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); base = root / "base.json"; base.write_text(json.dumps(self.base(digest)), encoding="utf-8"); atom_path = self.plan04(root / "plan04", digest); manifest = build_manifest(base, root / "plan04")
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source):
                report = preflight(manifest, "unused", root / "plan04")
            self.assertEqual((report["status"], report["reserved_input_tokens"], report["reserved_output_tokens"], report["requests"][0]["target_atom_count"]), ("pass", 516, 800, 1)); self.assertEqual(report["requests"][0]["expansion_chars"], 0)
            atom_path.write_text("{}", encoding="utf-8")
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source):
                tampered = preflight(manifest, "unused", root / "plan04")
            self.assertEqual(tampered["status"], "fail")
    def test_preflight_fails_when_no_atom_intersects_target(self):
        source = "Rule more"; digest = hashlib.sha256(source.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); base = root / "base.json"; base.write_text(json.dumps(self.base(digest)), encoding="utf-8"); atom_path = self.plan04(root / "plan04", digest)
            atom = json.loads(atom_path.read_text()); atom["atoms"][0]["span"] = {"start_char": 5, "end_char": 9}; atom_path.write_text(json.dumps(atom), encoding="utf-8")
            plan = root / "plan04" / "sentence_atom_build_manifest.json"; plan_value = json.loads(plan.read_text()); plan_value["cases"][0]["cache_key"] = atom["cache_key"]; plan.write_text(json.dumps(plan_value), encoding="utf-8")
            manifest = build_manifest(base, root / "plan04")
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source):
                report = preflight(manifest, "unused", root / "plan04")
            self.assertEqual(report["status"], "fail"); self.assertIn("no target-intersecting atom", report["failures"][0]["error"])

    def test_real_ten_request_compact_pilot_has_target_atoms_after_expansion(self):
        pipeline = Path(__file__).resolve().parents[1]
        manifest_path = pipeline / "manifests/au_compact_pilot_r5_model_silver.v1.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report = preflight(manifest, pipeline / "outputs/source_store_v1", pipeline / "outputs/plan04_sentence_atoms_v1")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(len(report["requests"]), 10)
        self.assertTrue(all(row["target_atom_count"] > 0 for row in report["requests"]))
