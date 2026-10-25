"""Integration contracts for constrained compact AU decoding and host validation."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_compact import core
from knowledge_base.pipeline_v1.au_compact.runner import CompactRunError, _key, run
from knowledge_base.pipeline_v1.au_compact import constraint_suite_probe as suite_module
from urllib.error import HTTPError


class FakeHTTP:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


class CompactDecodingIntegrationTests(unittest.TestCase):
    cfg = {"url": "https://fake", "token": "test-token", "model": "test-model", "enable_thinking": False}

    @staticmethod
    def compact(decision="positive", **overrides):
        value = {
            "request_id": "r-1",
            "target_id": "at-1",
            "decision": decision,
            "coverage_status": "complete",
            "aus": [{
                "kind": "holding", "other_kind": None, "claim": "Rule applies.",
                "evidence_ref_ids": ["sa-target"], "speaker": "current_court",
                "attribution_role": "proposition", "needs_context": [],
            }] if decision == "positive" else [],
            "hard_negative_reason": "other" if decision == "hard_negative" else None,
            "unresolved_reason": "other" if decision == "unresolved" else None,
        }
        value.update(overrides)
        return value

    def setup_manifest(self, folder):
        source = "Rule fact"
        digest = hashlib.sha256(source.encode()).hexdigest()
        atom_root = Path(folder) / "atoms"
        relative = "cases/000001/atoms.json"
        atom_map = {
            "case_id": "000001", "source_hash": digest, "cache_key": "c" * 64,
            "segmenter_version": "s1", "policy_sha256": "p" * 64,
            "atoms": [
                {"atom_id": "sa-target", "case_id": "000001", "source_hash": digest,
                 "span": {"start_char": 0, "end_char": 4}},
                {"atom_id": "sa-context", "case_id": "000001", "source_hash": digest,
                 "span": {"start_char": 5, "end_char": 9}},
            ],
        }
        path = atom_root / relative
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(atom_map), encoding="utf-8")
        request = {
            "case_id": "000001", "source_hash": digest, "request_id": "r-1",
            "expected_target_ids": ["at-1"],
            "source_refs": [
                {"role": "target", "start_char": 0, "end_char": 4, "target_ids": ["at-1"]},
                {"role": "context", "start_char": 5, "end_char": 9, "target_ids": []},
            ],
            "spec": {"model": "test-model", "enable_thinking": False, "caps": {"output_tokens": 800}},
            "atom_binding": {
                "atom_map_relative_path": relative,
                "atom_map_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "atom_map_cache_key": atom_map["cache_key"], "case_id": "000001",
                "source_hash": digest, "segmenter_version": "s1", "policy_sha256": "p" * 64,
            },
        }
        return source, atom_root, {"artifact_type": "AUCompactLockedManifest", "schema_version": "au-compact-manifest-v1", "base_manifest_sha256": "x", "requests": [request]}

    def run_kwargs(self, folder, atom_root, cfg=None):
        return {
            "source_store": "unused", "atom_root": atom_root, "cfg": cfg or self.cfg,
            "budget": {"max_requests": 2, "max_provider_attempts": 2, "max_total_input_tokens": 99999, "max_total_output_tokens": 1600},
            "cache_dir": Path(folder) / "out/cache", "execute": True,
            "warmup_policy": {"max_attempts": 1, "max_wait_seconds": 1},
        }

    @staticmethod
    def response(content, finish_reason="stop"):
        return FakeHTTP({"choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
                         "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}})

    def runner_opener(self, source_value, seen, *, probe_content=None, finish_reason="stop"):
        def opener(req, **_kwargs):
            payload = json.loads(req.data)
            seen.append(payload)
            turn = (len(seen) - 1) % 3
            if turn == 0:
                return self.response("{}")
            if turn == 1:
                return self.response(probe_content if probe_content is not None else json.dumps(self.compact("hard_negative", request_id="probe", target_id="probe")))
            return self.response(source_value if isinstance(source_value, str) else json.dumps(source_value), finish_reason)
        return opener

    def invoke(self, folder, source, atom_root, manifest, opener, cfg=None):
        with patch("knowledge_base.pipeline_v1.au_compact.manifest.open_source", return_value=source), \
             patch("knowledge_base.pipeline_v1.au_compact.runner.open_source", return_value=source):
            return run(manifest, opener=opener, **self.run_kwargs(folder, atom_root, cfg))

    def test_request_uses_per_request_grammar_and_binds_response_to_locked_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder)
            seen = []
            canonical = self.compact()
            canonical["aus"][0]["evidence_ref_ids"] = ["sa-context", "sa-target"]
            result = self.invoke(folder, source, atom_root, manifest,
                                 self.runner_opener(canonical, seen))

        self.assertEqual(result["request_ledger"][0]["status"], "protocol_verified")
        self.assertEqual(result["request_ledger"][0]["compact_response"]["request_id"], "r-1")
        self.assertEqual(result["request_ledger"][0]["compact_response"]["target_id"], "at-1")
        source_payload = seen[-1]
        self.assertIn("ebnf", source_payload)
        self.assertIsInstance(source_payload["ebnf"], str)
        self.assertTrue(source_payload["ebnf"].strip())
        self.assertNotIn("response_format", source_payload)
        self.assertIn("REQUEST_ID=r-1", source_payload["messages"][0]["content"])
        self.assertIn("TARGET_ID=at-1", source_payload["messages"][0]["content"])
        for payload in seen:
            self.assertNotIn("response_format", payload)

    def test_cache_key_binds_runtime_identity_and_legacy_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder)
            request = manifest["requests"][0]
            base = _key(request, "manifest-hash")
            endpoint_key = _key(request, "manifest-hash", {**self.cfg, "url": "https://other"})
            model_key = _key(request, "manifest-hash", {**self.cfg, "model": "other-model"})
            self.assertTrue(all(isinstance(value, str) for value in (base, endpoint_key, model_key)))
            self.assertEqual(len({base, endpoint_key, model_key}), 3)

            seen = []
            positive = self.compact()
            first = self.invoke(folder, source, atom_root, manifest,
                                self.runner_opener(positive, seen))
            self.assertEqual(first["request_ledger"][0]["status"], "protocol_verified")
            ledger_path = Path(folder) / "out" / "runtime_ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            current_identity = ledger["selection_identity"]
            ledger["selection_identity"] = "legacy-without-decoder-endpoint"
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            before_retry = len(seen)
            with self.assertRaisesRegex(CompactRunError, "identity mismatch"):
                self.invoke(folder, source, atom_root, manifest,
                            self.runner_opener(positive, seen))
            self.assertNotEqual(current_identity, ledger["selection_identity"])
            self.assertEqual(len(seen) - before_retry, 2)  # warmup and probe; no source dispatch

    def test_probe_failure_blocks_source_dispatch_and_schema_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder)
            seen = []
            opener = self.runner_opener("should never be sent", seen, probe_content="{}")
            with self.assertRaises(CompactRunError):
                self.invoke(folder, source, atom_root, manifest, opener)
        self.assertEqual(len(seen), 2)  # source-free warmup and decoding capability probe only
        self.assertTrue(all("ebnf" in payload for payload in seen[1:]))
        self.assertTrue(all("response_format" not in payload for payload in seen))
        self.assertIn("probe", seen[1]["ebnf"])
        self.assertIn("sa-target", seen[1]["ebnf"])

    def test_probe_http_rejection_gates_source_and_does_not_retry_with_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder)
            seen = []

            def opener(req, **_kwargs):
                seen.append(json.loads(req.data))
                prompt = seen[-1]["messages"][0]["content"]
                if "Respond with {} only." in prompt:
                    return self.response("{}")
                raise HTTPError("https://fake", 400, "grammar rejected", None, None)

            with self.assertRaises(CompactRunError):
                self.invoke(folder, source, atom_root, manifest, opener)
        self.assertEqual(len(seen), 2)
        self.assertNotIn("response_format", json.dumps(seen))

    def test_only_exact_stop_and_complete_json_can_be_normalized(self):
        invalid_cases = [
            (json.dumps(self.compact()), "length"),
            (" \n\t ", "stop"),
            ('{"request_id":"r-1","target_id":"at-1"', "stop"),
        ]
        for raw, finish_reason in invalid_cases:
            with self.subTest(raw=raw, finish_reason=finish_reason), tempfile.TemporaryDirectory() as folder:
                source, atom_root, manifest = self.setup_manifest(folder)
                seen = []
                result = self.invoke(folder, source, atom_root, manifest,
                                     self.runner_opener(raw, seen, finish_reason=finish_reason))
                row = result["request_ledger"][0]
                self.assertEqual(row["status"], "unresolved")
                self.assertEqual(row["response"]["target_results"][0]["decision"], "unresolved")
                self.assertEqual(row["response"]["target_results"][0]["authority_units"], [])
                diagnostic = row["receipt"].get("failure_diagnostic", {})
                self.assertTrue(diagnostic)
                self.assertEqual(row["receipt"].get("raw_response"), raw)
                self.assertIsNone(row.get("compact_response"))

    def test_request_and_target_mismatches_are_rejected_by_host(self):
        for field, wrong in (("request_id", "other-request"), ("target_id", "other-target")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                source, atom_root, manifest = self.setup_manifest(folder)
                invalid = self.compact(**{field: wrong})
                result = self.invoke(folder, source, atom_root, manifest,
                                     self.runner_opener(invalid, []))
                self.assertEqual(result["request_ledger"][0]["status"], "unresolved")
                self.assertEqual(result["request_ledger"][0]["receipt"]["failure_diagnostic"]["kind"], "host_validation")

    def test_host_still_rejects_invalid_kind_decision_and_evidence_ids(self):
        cases = []
        bad_kind = self.compact()
        bad_kind["aus"][0]["kind"] = "not_a_kind"
        cases.append(("kind", bad_kind))
        bad_decision = self.compact("hard_negative")
        bad_decision["aus"] = [self.compact()["aus"][0]]
        cases.append(("decision", bad_decision))
        bad_evidence = self.compact()
        bad_evidence["aus"][0]["evidence_ref_ids"] = ["not-in-catalog"]
        cases.append(("evidence", bad_evidence))
        for name, value in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                source, atom_root, manifest = self.setup_manifest(folder)
                result = self.invoke(folder, source, atom_root, manifest,
                                     self.runner_opener(value, []))
                row = result["request_ledger"][0]
                self.assertEqual(row["status"], "unresolved")
                self.assertEqual(row["receipt"]["failure_diagnostic"]["kind"], "host_validation")

    def test_deduplicate_lists_only_string_values_in_the_two_declared_fields(self):
        self.assertTrue(hasattr(core, "deduplicate_lists"), "core must expose the cleanup contract")
        original = {
            "aus": [
                {"needs_context": ["condition", "condition"],
                 "evidence_ref_ids": ["sa-target", "sa-target"],
                 "kind": "holding"},
                {"needs_context": ["condition", 7, 7, None, None],
                 "evidence_ref_ids": ["sa-context", "sa-context", 7]},
            ],
            "unrelated_list": ["same", "same"],
            "decision": "positive",
        }
        cleaned, changes = core.deduplicate_lists(original)
        self.assertEqual(original["aus"][0]["needs_context"], ["condition", "condition"])
        self.assertIsNot(cleaned, original)
        self.assertEqual(cleaned["aus"][0]["needs_context"], ["condition"])
        self.assertEqual(cleaned["aus"][0]["evidence_ref_ids"], ["sa-target"])
        self.assertEqual(cleaned["aus"][0]["kind"], "holding")
        self.assertEqual(cleaned["unrelated_list"], ["same", "same"])
        self.assertEqual(cleaned["aus"][1]["needs_context"], ["condition", 7, 7, None, None])
        self.assertEqual(cleaned["aus"][1]["evidence_ref_ids"], ["sa-context", "sa-context", 7])
        self.assertTrue(changes)
        self.assertIsInstance(changes, list)

    def test_deduplication_is_recorded_as_cleanup_and_raw_response_is_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            source, atom_root, manifest = self.setup_manifest(folder)
            compact = self.compact()
            compact["aus"][0]["needs_context"] = ["condition", "condition"]
            raw = json.dumps(compact, separators=(",", ":"))
            result = self.invoke(folder, source, atom_root, manifest,
                                 self.runner_opener(raw, []))
            row = result["request_ledger"][0]
        self.assertEqual(row["compact_response"]["aus"][0]["needs_context"], ["condition", "condition"])
        self.assertEqual(row["receipt"].get("raw_response"), raw)
        self.assertTrue(row["receipt"].get("exact_duplicate_cleanup"))
        self.assertEqual(row["status"], "protocol_verified")

    def test_constraint_suite_ebnf_builds_schema_only_control_from_its_own_ids(self):
        requested = {
            "request_id": "custom-request",
            "target_id": "custom-target",
            "decision": "positive",
            "coverage_status": "complete",
            "aus": [{
                "kind": "holding", "other_kind": None, "claim": "Custom catalog control.",
                "evidence_ref_ids": ["zz-custom", "aa-custom"], "speaker": "current_court",
                "attribution_role": "proposition", "needs_context": [],
            }],
            "hard_negative_reason": None,
            "unresolved_reason": None,
        }
        original = json.loads(json.dumps(requested))
        case = {
            "case_id": "custom-schema-only-control", "mode": "valid", "scope": "schema_only",
            "keyword": "enum", "path": ["aus", 0, "evidence_ref_ids"],
            "requested_value": json.loads(json.dumps(requested)), "expected_transport_valid": True,
            "expected_full_valid": True, "expected_host_valid": False,
        }
        seen = []

        def opener(req, **_kwargs):
            payload = json.loads(req.data)
            seen.append(payload)
            return self.response(json.dumps(
                {**requested, "aus": [{**requested["aus"][0], "evidence_ref_ids": ["aa-custom", "zz-custom"]}]},
                separators=(",", ":"),
            ))

        with tempfile.TemporaryDirectory() as folder, \
             patch.object(suite_module, "build_cases", return_value=[case]), \
             patch.object(suite_module, "_coverage", return_value={
                 "uncovered_constraints": [], "full_schema_sha256": "full",
                 "transport_schema_sha256": "transport",
             }):
            report = suite_module.constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, decoder="ebnf")

        self.assertEqual(requested, original)
        self.assertEqual(case["requested_value"]["aus"][0]["evidence_ref_ids"], ["aa-custom", "zz-custom"])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["identity"]["decoder"], "ebnf")
        self.assertEqual(len(seen), 1)
        self.assertIn("ebnf", seen[0])
        self.assertNotIn("response_format", seen[0])
        self.assertIn("custom-request", seen[0]["ebnf"])
        self.assertIn("custom-target", seen[0]["ebnf"])
        self.assertIn("aa-custom", seen[0]["ebnf"])
        self.assertIn("zz-custom", seen[0]["ebnf"])
        self.assertGreater(report["budget"]["estimated_payload_tokens"], report["budget"]["estimated_input_tokens"])

    def test_constraint_suite_ebnf_rejects_noncanonical_format_but_accepts_compact_json(self):
        canonical = {
            "request_id": "format-request", "target_id": "format-target", "decision": "positive",
            "coverage_status": "complete", "aus": [{
                "kind": "holding", "other_kind": None, "claim": "A compact control.",
                "evidence_ref_ids": ["sa-target"], "speaker": "current_court",
                "attribution_role": "proposition", "needs_context": [],
            }],
            "hard_negative_reason": None, "unresolved_reason": None,
        }
        variants = [("compact", canonical, "pass", None)]
        pretty = json.dumps(canonical, indent=2)
        variants.append(("pretty", canonical, "grammar_format_violation", "formatting whitespace outside JSON strings"))

        reversed_root = dict(reversed(list(canonical.items())))
        variants.append(("root-order", reversed_root, "grammar_format_violation", "root key order"))

        reversed_au = json.loads(json.dumps(canonical))
        reversed_au["aus"][0] = dict(reversed(list(reversed_au["aus"][0].items())))
        variants.append(("au-order", reversed_au, "grammar_format_violation", "AU key order"))

        unsorted_evidence = json.loads(json.dumps(canonical))
        unsorted_evidence["aus"][0]["evidence_ref_ids"] = ["sa-target-2", "sa-target"]
        variants.append(("evidence-order", unsorted_evidence, "grammar_format_violation", "evidence is not an ordered unique subset"))

        context_order = json.loads(json.dumps(canonical))
        context_order["aus"][0]["needs_context"] = ["exception", "condition"]
        variants.append(("context-order", context_order, "grammar_format_violation", "needs_context is not an ordered unique subset"))

        duplicate_evidence = json.loads(json.dumps(canonical))
        duplicate_evidence["aus"][0]["evidence_ref_ids"] = ["sa-target", "sa-target"]
        variants.append(("duplicate-evidence", duplicate_evidence, "transport_schema_violation", "evidence is not an ordered unique subset"))

        duplicate_context = json.loads(json.dumps(canonical))
        duplicate_context["aus"][0]["needs_context"] = ["condition", "condition"]
        variants.append(("duplicate-context", duplicate_context, "transport_schema_violation", "needs_context is not an ordered unique subset"))

        for case_name, response, expected_status, expected_error in variants:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as folder:
                case = {
                    "case_id": "format-control", "mode": "valid", "scope": "schema_only",
                    "keyword": "format", "path": [], "requested_value": json.loads(json.dumps(canonical)),
                    "expected_transport_valid": True, "expected_full_valid": True, "expected_host_valid": False,
                }
                if case_name == "pretty":
                    raw = pretty
                else:
                    raw = json.dumps(response, separators=(",", ":"))

                def opener(req, **_kwargs):
                    return self.response(raw)

                with patch.object(suite_module, "build_cases", return_value=[case]), \
                     patch.object(suite_module, "_coverage", return_value={
                         "uncovered_constraints": [], "full_schema_sha256": "full",
                         "transport_schema_sha256": "transport",
                     }):
                    report = suite_module.constraint_suite_probe(self.cfg, folder, execute=True, opener=opener, decoder="ebnf")
                result = report["results"][0]
                self.assertEqual(result["status"], expected_status)
                if expected_error:
                    self.assertTrue(any(expected_error in error for error in result["grammar_format_errors"]))

    def test_constraint_suite_cli_passes_ebnf_decoder(self):
        from knowledge_base.pipeline_v1.au_compact import __main__ as cli

        with tempfile.TemporaryDirectory() as folder, \
             patch.object(sys, "argv", ["au_compact", "constraint-suite-probe", "--decoder", "ebnf", "--output-root", folder]), \
             patch.object(cli, "settings", return_value={}), \
             patch.object(cli, "load_au_runtime_config", return_value=(self.cfg, None, None)), \
             patch.object(cli, "constraint_suite_probe", return_value={"status": "planned"}) as probe:
            self.assertEqual(cli.main(), 0)
        self.assertEqual(probe.call_args.kwargs["decoder"], "ebnf")


if __name__ == "__main__":
    unittest.main()
