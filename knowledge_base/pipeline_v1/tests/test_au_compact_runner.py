import hashlib
import json
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from knowledge_base.pipeline_v1.au_compact.runner import CompactRunError, run
from knowledge_base.pipeline_v1.au_compact.core import COMPACT_SCHEMA, COMPACT_TRANSPORT_SCHEMA


class FakeHTTP:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.body).encode()


class CompactRunnerTests(unittest.TestCase):
    def test_transport_schema_omits_conditionals_but_host_schema_keeps_them(self):
        host = json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8"))
        transport = json.loads(COMPACT_TRANSPORT_SCHEMA.read_text(encoding="utf-8"))
        self.assertIn("allOf", host)
        self.assertIn("allOf", host["$defs"]["au"])
        self.assertNotIn("allOf", transport)
        self.assertNotIn("allOf", transport["$defs"]["au"])

    def setup_manifest(self, folder):
        source = "Rule fact"; digest = hashlib.sha256(source.encode()).hexdigest(); root = Path(folder) / "atoms"; relative = "cases/000001/atoms.json"
        atom = {"case_id": "000001", "source_hash": digest, "cache_key": "c" * 64, "segmenter_version": "s1", "policy_sha256": "p" * 64, "atoms": [{"atom_id": "sa-target", "case_id": "000001", "source_hash": digest, "span": {"start_char": 0, "end_char": 4}}, {"atom_id": "sa-context", "case_id": "000001", "source_hash": digest, "span": {"start_char": 5, "end_char": 9}}]}
        path = root / relative; path.parent.mkdir(parents=True); path.write_text(json.dumps(atom), encoding="utf-8")
        request = {"case_id": "000001", "source_hash": digest, "request_id": "r-1", "expected_target_ids": ["at-1"], "source_refs": [{"role": "target", "start_char": 0, "end_char": 4, "target_ids": ["at-1"]}, {"role": "context", "start_char": 5, "end_char": 9, "target_ids": []}], "spec": {"model": "m", "enable_thinking": False, "caps": {"output_tokens": 800}}, "atom_binding": {"atom_map_relative_path": relative, "atom_map_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "atom_map_cache_key": atom["cache_key"], "case_id": "000001", "source_hash": digest, "segmenter_version": "s1", "policy_sha256": "p" * 64}}
        return source, root, {"artifact_type": "AUCompactLockedManifest", "schema_version": "au-compact-manifest-v1", "base_manifest_sha256": "x", "requests": [request]}

    def kwargs(self, folder, atom_root):
        return {"source_store": "unused", "atom_root": atom_root, "cfg": {"url": "https://fake", "token": "secret", "model": "m", "enable_thinking": False}, "budget": {"max_requests": 2, "max_provider_attempts": 2, "max_total_input_tokens": 99999, "max_total_output_tokens": 1600}, "cache_dir": Path(folder) / "out/cache", "execute": True, "warmup_policy": {"max_attempts": 1, "max_wait_seconds": 1}}

    def compact_probe(self):
        return {"request_id": "probe", "target_id": "probe", "decision": "hard_negative", "coverage_status": "complete", "aus": [], "hard_negative_reason": "other", "unresolved_reason": None}

    def test_no_source_provider_call_before_warmup_and_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder); calls = []
            def opener(req, **_):
                calls.append(json.loads(req.data)["messages"][0]["content"])
                raise HTTPError("https://fake", 400, "bad", None, None)
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source), patch("knowledge_base.pipeline_v1.au_compact.runner.open_source", return_value=source):
                with self.assertRaises(CompactRunError): run(manifest, opener=opener, **self.kwargs(folder, atom_root))
            self.assertEqual(len(calls), 1); self.assertIn("Respond with {} only.", calls[0]); self.assertNotIn("Rule", calls[0])

    def test_compact_probe_failure_blocks_source_provider_call(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder); calls = []
            def opener(req, **_):
                text = json.loads(req.data)["messages"][0]["content"]; calls.append(text)
                return FakeHTTP({"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {}})
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source), patch("knowledge_base.pipeline_v1.au_compact.runner.open_source", return_value=source):
                with self.assertRaises(CompactRunError): run(manifest, opener=opener, **self.kwargs(folder, atom_root))
            self.assertEqual(len(calls), 2); self.assertIn("Respond with {} only.", calls[0]); self.assertIn("Return exactly this compact", calls[1]); self.assertNotIn("ATOMS:", "\n".join(calls))

    def test_multi_au_normalizes_and_persists_needs_split_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder); calls = []
            positive = {"request_id": "r-1", "target_id": "at-1", "decision": "positive", "coverage_status": "needs_split", "aus": [{"kind": "holding", "other_kind": None, "claim": "Rule one.", "evidence_ref_ids": ["sa-target"], "speaker": "current_court", "attribution_role": "proposition", "needs_context": []}, {"kind": "procedural_rule", "other_kind": None, "claim": "Rule two.", "evidence_ref_ids": ["sa-target", "sa-context"], "speaker": "current_court", "attribution_role": "proposition", "needs_context": ["condition"]}], "hard_negative_reason": None, "unresolved_reason": None}
            def opener(req, **_):
                text = json.loads(req.data)["messages"][0]["content"]; calls.append(text)
                content = "{}" if "Respond with {} only." in text else (json.dumps(self.compact_probe()) if "Return exactly this compact" in text else json.dumps(positive))
                return FakeHTTP({"choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}})
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source), patch("knowledge_base.pipeline_v1.au_compact.runner.open_source", return_value=source):
                result = run(manifest, opener=opener, **self.kwargs(folder, atom_root))
            row = result["request_ledger"][0]; self.assertEqual((result["status"], row["status"], len(row["response"]["target_results"][0]["authority_units"])), ("complete", "protocol_verified", 2)); self.assertIn("<TARGET atom_id=sa-target", calls[-1]); self.assertTrue(list((Path(folder) / "out/needs_split").glob("*.json")))

    def test_length_is_unresolved_and_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder); source_calls = []
            def opener(req, **_):
                text = json.loads(req.data)["messages"][0]["content"]
                if "Respond with {} only." in text: content, reason = "{}", "stop"
                elif "Return exactly this compact" in text: content, reason = json.dumps(self.compact_probe()), "stop"
                else: source_calls.append(1); content, reason = "{}", "length"
                return FakeHTTP({"choices": [{"finish_reason": reason, "message": {"content": content}}], "usage": {"prompt_tokens": 2, "completion_tokens": 800, "total_tokens": 802}})
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source), patch("knowledge_base.pipeline_v1.au_compact.runner.open_source", return_value=source):
                first = run(manifest, opener=opener, **self.kwargs(folder, atom_root)); second = run(manifest, opener=opener, **self.kwargs(folder, atom_root))
            self.assertEqual((first["request_ledger"][0]["status"], first["request_ledger"][0]["receipt"]["failure_diagnostic"]["kind"], len(source_calls)), ("unresolved", "output_truncated", 1)); self.assertEqual(second["request_ledger"][0]["status"], "unresolved")

    def test_json_list_is_host_unresolved_without_crashing(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder)
            def opener(req, **_):
                text = json.loads(req.data)["messages"][0]["content"]
                if "Respond with {} only." in text:
                    content = "{}"
                elif "Return exactly this compact" in text:
                    content = json.dumps(self.compact_probe())
                else:
                    content = "[]"
                return FakeHTTP({"choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source), patch("knowledge_base.pipeline_v1.au_compact.runner.open_source", return_value=source):
                result = run(manifest, opener=opener, **self.kwargs(folder, atom_root))
            row = result["request_ledger"][0]
            self.assertEqual((result["status"], row["status"]), ("incomplete", "unresolved"))
            self.assertEqual(row["receipt"]["failure_diagnostic"]["kind"], "host_validation")

    def test_tampered_map_blocks_before_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder); binding = manifest["requests"][0]["atom_binding"]; (atom_root / binding["atom_map_relative_path"]).write_text("{}", encoding="utf-8")
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source), patch("knowledge_base.pipeline_v1.au_compact.runner.open_source", return_value=source):
                with self.assertRaises(CompactRunError): run(manifest, opener=lambda *_a, **_k: self.fail("provider must not run"), **self.kwargs(folder, atom_root))

    def test_smoke_selection_dispatches_one_request_and_records_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder); second = copy.deepcopy(manifest["requests"][0]); second["request_id"] = "r-2"; second["expected_target_ids"] = ["at-2"]; second["source_refs"][0]["target_ids"] = ["at-2"]; manifest["requests"].append(second); source_calls = []
            positive = {"request_id": "r-1", "target_id": "at-1", "decision": "positive", "coverage_status": "complete", "aus": [{"kind": "holding", "other_kind": None, "claim": "Rule.", "evidence_ref_ids": ["sa-target"], "speaker": "current_court", "attribution_role": "proposition", "needs_context": []}], "hard_negative_reason": None, "unresolved_reason": None}
            def opener(req, **_):
                text = json.loads(req.data)["messages"][0]["content"]
                if "Respond with {} only." in text: content = "{}"
                elif "Return exactly this compact" in text: content = json.dumps(self.compact_probe())
                else: source_calls.append(text); content = json.dumps(positive)
                return FakeHTTP({"choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source), patch("knowledge_base.pipeline_v1.au_compact.runner.open_source", return_value=source):
                result = run(manifest, opener=opener, request_ids=["r-1"], **self.kwargs(folder, atom_root))
            self.assertEqual((len(manifest["requests"]), result["selection_request_ids"], len(result["request_ledger"]), len(source_calls)), (2, ["r-1"], 1, 1)); self.assertEqual(result["runtime_ledger"]["selection_request_ids"], ["r-1"]); self.assertIn("TARGET_ID=at-1", source_calls[0])

    def test_unknown_or_empty_selection_fails_before_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder)
            with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source), patch("knowledge_base.pipeline_v1.au_compact.runner.open_source", return_value=source):
                for selection in (["unknown"], []):
                    with self.subTest(selection=selection), self.assertRaises(CompactRunError):
                        run(manifest, opener=lambda *_a, **_k: self.fail("provider must not run"), request_ids=selection, **self.kwargs(folder, atom_root))
