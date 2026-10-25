"""Independent offline contract tests for the isolated AU length probe."""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator
from knowledge_base.pipeline_v1.au_claim import core as au_claim_core
from knowledge_base.pipeline_v1.au_length_probe import build_cases, build_grammar, build_schema, prepare
from knowledge_base.pipeline_v1.au_length_probe.core import (
    CAPS, IDS, KINDS, ORIGINAL_VARIANTS, VARIANTS, host_valid, offline, runtime,
)


def case_map():
    return {case["name"]: case for case in build_cases()}


class GrammarContractTests(unittest.TestCase):
    def test_host_variant_is_byte_for_byte_current_au_claim_grammar(self):
        for ids in (("s1", "c1"), ("s12", "c8", "s7")):
            with self.subTest(ids=ids):
                self.assertEqual(build_grammar(ids, "host_validated"), au_claim_core._grammar(ids))

    def test_variants_keep_wire_shape_enum_and_caps_explicit(self):
        host = build_grammar(variant="host_validated")
        bounded = build_grammar(variant="bounded")
        experimental = build_grammar(variant="max_chars")
        self.assertEqual(ORIGINAL_VARIANTS, ("host_validated", "bounded", "max_chars"))
        self.assertEqual(VARIANTS, (*ORIGINAL_VARIANTS, "json_schema"))
        for grammar in (host, bounded, experimental):
            for key in ("aus", "context_request", "claim", "kind", "evidence_ids", "limits", "question"):
                self.assertIn(json.dumps(json.dumps(key) + ":"), grammar)
            for kind in (*KINDS, None):
                encoded = json.dumps(json.dumps(kind, ensure_ascii=True), ensure_ascii=True)
                self.assertIn(encoded, grammar)
        for field, cap in CAPS.items():
            self.assertIn(f"{field}-text ::=", bounded)
            self.assertIn("json-char{1," + str(cap) + "}", bounded)
            self.assertIn(f"{field}-text[max_chars={cap + 2}]", experimental)
        self.assertIn("json-char*", host)
        self.assertNotIn("max_chars(", host)
        self.assertNotIn("max_chars(", bounded)
        self.assertNotIn("response_format", host + bounded + experimental)

    def test_json_schema_has_exact_wire_shape_enums_and_text_bounds(self):
        schema = build_schema()
        Draft202012Validator.check_schema(schema)
        self.assertEqual(schema["type"], "object")
        self.assertEqual(set(schema["properties"]), {"aus", "context_request"})
        self.assertEqual(set(schema["required"]), {"aus", "context_request"})
        self.assertFalse(schema["additionalProperties"])

        aus = schema["properties"]["aus"]
        self.assertEqual((aus["type"], aus["minItems"], aus["maxItems"]), ("array", 0, 3))
        au = aus["items"]
        self.assertEqual(au["type"], "object")
        self.assertEqual(set(au["required"]), {"claim", "kind", "evidence_ids", "limits"})
        self.assertFalse(au["additionalProperties"])
        props = au["properties"]
        for field, cap in (("claim", 500), ("limits", 250)):
            text_schema = props[field] if field == "claim" else props[field]["anyOf"][0]
            self.assertEqual((text_schema["type"], text_schema["minLength"], text_schema["maxLength"]),
                             ("string", 1, cap))
        self.assertEqual(props["kind"]["enum"], [*KINDS, None])
        evidence = props["evidence_ids"]
        self.assertEqual((evidence["type"], evidence["minItems"]), ("array", 1))
        self.assertEqual(evidence["items"], {"type": "string", "enum": list(IDS)})

        context = schema["properties"]["context_request"]["anyOf"]
        self.assertEqual(context[1], {"type": "null"})
        question = context[0]
        self.assertEqual(question["type"], "object")
        self.assertEqual(set(question["required"]), {"question"})
        self.assertFalse(question["additionalProperties"])
        self.assertEqual(question["properties"]["question"],
                         {"type": "string", "minLength": 1, "maxLength": 200})

    def test_builder_rejects_invalid_catalogs_without_rewriting_ids(self):
        for ids, variant in (((), "host_validated"), (("s0",), "bounded"),
                             (("x1",), "max_chars"), (("s1",) * 33, "host_validated"),
                             (("s1",), "unknown")):
            with self.subTest(ids=ids, variant=variant), self.assertRaises(ValueError):
                build_grammar(ids, variant)


class FixtureAndHostBoundaryTests(unittest.TestCase):
    def test_each_decoded_character_cap_has_minus_exact_plus_fixtures(self):
        cases = case_map()
        for field, cap in CAPS.items():
            for encoding in ("ascii", "bmp", "nonbmp", "escaped_unicode", "quote",
                             "backslash", "control_escape"):
                for size in (cap - 1, cap, cap + 1):
                    name = f"{field}_{encoding}_{size}"
                    with self.subTest(name=name):
                        case = cases[name]
                        decoded = json.loads(case["text"])
                        value = (decoded["context_request"]["question"] if field == "question"
                                 else decoded["aus"][0][field])
                        self.assertEqual(len(value), size)
                        self.assertEqual(case["expected"]["bounded"], size <= cap)
                        self.assertEqual(case["expected"]["host_validated"], True)
                        self.assertEqual(case["host_valid"], size <= cap)

    def test_escaped_and_nonbmp_wire_lengths_are_not_decoded_lengths(self):
        cases = case_map()
        for field, cap in CAPS.items():
            plain = cases[f"{field}_nonbmp_{cap}"]["text"]
            escaped = cases[f"{field}_escaped_unicode_{cap}"]["text"]
            self.assertEqual(len(json.loads(plain)["aus"][0][field] if field != "question"
                                         else json.loads(plain)["context_request"][field]), cap)
            decoded_escaped = json.loads(escaped)
            text = (decoded_escaped["context_request"][field] if field == "question"
                    else decoded_escaped["aus"][0][field])
            self.assertEqual(len(text), cap)
            self.assertGreater(len(escaped), len(plain))
            escaped_string_token = json.dumps("😀" * cap, ensure_ascii=True)
            self.assertEqual(len(escaped_string_token), 12 * cap + 2)
            self.assertGreater(len(escaped_string_token), cap + 2)
            # max_chars is intentionally not assigned a decoded-character PASS oracle.
            self.assertNotIn("max_chars", cases[f"{field}_escaped_unicode_{cap}"]["expected"])

    def test_quote_backslash_combining_controls_and_lone_surrogates(self):
        cases = case_map()
        for field, cap in CAPS.items():
            for label in ("quote", "backslash", "combining", "control_escape"):
                with self.subTest(field=field, label=label):
                    case = cases[f"{field}_{label}_{cap}"]
                    self.assertTrue(case["host_valid"])
                    value = json.loads(case["text"])
                    decoded = (value["context_request"]["question"] if field == "question"
                               else value["aus"][0][field])
                    self.assertEqual(len(decoded), cap)
            for label in ("lone_high", "lone_low"):
                case = cases[f"{field}_{label}"]
                self.assertFalse(case["host_valid"])
                self.assertFalse(case["expected"]["bounded"])
                self.assertFalse(case["expected"]["host_validated"])

    def test_au_a14_length_regression_is_two_distinct_host_failures(self):
        au = {"claim": "c" * 153, "kind": None, "evidence_ids": ["s1"], "limits": "l" * 476}
        self.assertFalse(host_valid({"aus": [au], "context_request": None}))
        au["limits"] = "l" * 250
        self.assertTrue(host_valid({"aus": [au], "context_request": None}))
        au["claim"] = "c" * 476
        self.assertTrue(host_valid({"aus": [au], "context_request": None}))
        self.assertFalse(host_valid({"aus": [], "context_request": {"question": "q" * 258}}))
        self.assertTrue(host_valid({"aus": [], "context_request": {"question": "q" * 200}}))

    def test_host_rejects_empty_whitespace_bad_enum_and_more_than_three_aus(self):
        cases = case_map()
        for name in ("claim_empty", "claim_whitespace_host_invalid", "limits_empty",
                     "question_empty", "bad_kind", "bad_ref", "null_claim", "extra_key", "au_cap_4"):
            with self.subTest(name=name):
                self.assertFalse(cases[name]["host_valid"])


class OfflineLifecycleTests(unittest.TestCase):
    def test_prepare_is_zero_inference_and_writes_bounded_synthetic_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "prepared"
            report = prepare(output)
            persisted = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report, persisted)
            self.assertEqual(report["status"], "PREPARED")
            self.assertEqual(report["inference_requests"], 0)
            self.assertFalse(report["inference_speed_claim"])
            self.assertEqual(report["matches"], "NOT_RUN")
            self.assertEqual(set(report["grammars"]), set(ORIGINAL_VARIANTS))
            self.assertEqual(len(report["cases"]), 113)
            self.assertLessEqual((output / "report.json").stat().st_size, 2_000_000)

    def test_offline_backend_missing_is_unavailable_never_pass(self):
        real_import = __import__

        def without_optional_backend(name, *args, **kwargs):
            if name == "xgrammar":
                raise ModuleNotFoundError("xgrammar intentionally unavailable in this test")
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, mock.patch("builtins.__import__", side_effect=without_optional_backend):
            report = offline("unused-tokenizer-path", Path(tmp) / "offline")
            self.assertEqual(report["status"], "UNAVAILABLE")
            self.assertIsNone(report.get("recommended"))
            self.assertEqual(report["inference_requests"], 0)
            self.assertFalse(report["inference_speed_claim"])
            self.assertNotEqual(report["status"], "PASS")

    def test_output_roots_are_never_overwritten_and_budget_failure_is_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing"
            existing.mkdir()
            sentinel = existing / "sentinel"
            sentinel.write_text("preserve", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                prepare(existing)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
            with self.assertRaises(ValueError):
                prepare(Path(tmp) / "small-budget", report_max_bytes=1)

    def test_json_schema_path_uses_bounded_labels_and_surfaces_scalar_gap(self):
        captured = {}
        validator = Draft202012Validator(build_schema())

        class Tokenizer:
            eos_token_id = 248044
            def __len__(self): return 260_000
            def encode(self, *args, **kwargs): return []

        class TokenizerInfo:
            vocab_size = 260_000

        class Mask:
            def numel(self): return 8_125
            def element_size(self): return 4

        class Compiler:
            def __init__(self, info, max_threads):
                captured["threads"] = max_threads
            def compile_json_schema(self, source):
                captured["schema_text"] = source
                captured["schema_calls"] = captured.get("schema_calls", 0) + 1
                return validator
            def compile_grammar(self, grammar):
                raise AssertionError("json_schema variant must use compile_json_schema")

        class Matcher:
            def __init__(self, compiled): self.compiled, self.complete = compiled, False
            def accept_string(self, raw):
                try: value = json.loads(raw)
                except json.JSONDecodeError:
                    self.complete = False
                    return False
                self.complete = self.compiled.is_valid(value)
                return self.complete
            def is_completed(self): return self.complete

        xgrammar = types.ModuleType("xgrammar")
        xgrammar.TokenizerInfo = types.SimpleNamespace(
            from_huggingface=lambda *args, **kwargs: TokenizerInfo())
        xgrammar.GrammarCompiler = Compiler
        xgrammar.GrammarMatcher = Matcher
        xgrammar.allocate_token_bitmask = lambda *args, **kwargs: Mask()
        transformers = types.ModuleType("transformers")
        transformers.AutoTokenizer = types.SimpleNamespace(
            from_pretrained=lambda *args, **kwargs: Tokenizer())
        torch = types.ModuleType("torch")
        cases = [dict(case, replay=False) for case in build_cases()]

        with tempfile.TemporaryDirectory() as tmp:
            tokenizer_path = Path(tmp) / "tokenizer"
            tokenizer_path.mkdir()
            (tokenizer_path / "tokenizer.json").write_text("{}", encoding="utf-8")
            (tokenizer_path / "config.json").write_text(
                json.dumps({"vocab_size": 260_000}), encoding="utf-8")
            with mock.patch.dict(sys.modules, {"xgrammar": xgrammar, "transformers": transformers, "torch": torch}), \
                    mock.patch("knowledge_base.pipeline_v1.au_length_probe.core.build_cases", return_value=cases):
                report = offline(tokenizer_path, Path(tmp) / "schema-run", variants=("json_schema",))

        self.assertEqual(captured["schema_calls"], 1)
        self.assertEqual(captured["threads"], 1)
        self.assertEqual(json.loads(captured["schema_text"]), build_schema())
        self.assertEqual(len(report["variants"]["json_schema"]["cases"]), 113)
        rows = {row["name"]: row for row in report["variants"]["json_schema"]["cases"]}
        oracle = {case["name"]: case["expected"]["bounded"] for case in cases}
        self.assertEqual({name: row["expected"] for name, row in rows.items()}, oracle)
        # The standard JSON Schema bounds have no rule excluding lone UTF-16
        # surrogates. This mocked validator is only a semantic diagnostic: the
        # native XGrammar compiler and tokenizer replay remain untested here.
        mismatches = sorted(name for name, row in rows.items() if not row["correct"])
        self.assertEqual(mismatches, [
            "claim_lone_high", "claim_lone_low", "limits_lone_high", "limits_lone_low",
            "question_lone_high", "question_lone_low",
        ])
        self.assertEqual(report["variants"]["json_schema"]["status"], "FAIL")
        self.assertEqual(report["status"], "FAIL")
        self.assertIsNone(report["recommended"])


class RuntimeInspectorTests(unittest.TestCase):
    def setUp(self):
        self.config = {"url": "https://probe.example/v1/chat/completions", "token": "secret-sentinel"}
        self.settings_patch = mock.patch("knowledge_base.config.settings", return_value={})
        self.runtime_config_patch = mock.patch(
            "knowledge_base.pipeline_v1.au_runtime_config.load_au_runtime_config",
            return_value=(self.config, None, None),
        )
        self.settings_patch.start()
        self.runtime_config_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.addCleanup(self.runtime_config_patch.stop)

    def test_success_is_one_fixed_authenticated_get_and_report_is_whitelisted(self):
        response_value = {
            "versions": {"xgrammar": "0.2.1", "sglang": "0.5.19+cu130",
                         "python": "3.12.1", "api_key": "must-not-persist"},
            "scheduler": {"xgrammar_stop_token_ids": [248044, 248046], "credential": "must-not-persist"},
            "arbitrary": "must-not-persist",
        }

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit):
                self.limit = limit
                return json.dumps(response_value).encode("utf-8")

        opener = mock.Mock()
        opener.open.return_value = Response()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("urllib.request.build_opener", return_value=opener) as build_opener:
            report = runtime(Path(tmp) / "runtime")
            request = opener.open.call_args.args[0]
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.full_url, "https://probe.example/v1/diagnostics/json/info")
            self.assertEqual(request.get_header("Authorization"), "Bearer secret-sentinel")
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)
            self.assertEqual(report["status"], "OBSERVED")
            self.assertEqual(report["http_requests"], 1)
            self.assertEqual(report["runtime_versions"], {
                "xgrammar": "0.2.1", "sglang": "0.5.19+cu130", "python": "3.12.1"})
            self.assertEqual(report["eos_info"]["scheduler"], {"xgrammar_stop_token_ids": [248044, 248046]})
            self.assertEqual(set(report["eos_info"]), {"root", "scheduler", "backend", "text_config"})
            self.assertEqual(build_opener.call_count, 1)
            from urllib.request import HTTPRedirectHandler
            self.assertTrue(any(isinstance(handler, HTTPRedirectHandler)
                                for handler in build_opener.call_args.args))
            serialized = json.dumps(report)
            for secret in ("secret-sentinel", "probe.example", "must-not-persist", "arbitrary"):
                self.assertNotIn(secret, serialized)

    def test_redirect_response_is_not_followed_and_no_retry_occurs(self):
        from urllib.error import HTTPError

        opener = mock.Mock()
        opener.open.side_effect = HTTPError(
            "https://probe.example/v1/diagnostics/json/info", 302, "redirect secret-sentinel",
            {"Location": "https://other.example/leak?token=secret-sentinel"}, None)
        with tempfile.TemporaryDirectory() as tmp, mock.patch("urllib.request.build_opener", return_value=opener):
            report = runtime(Path(tmp) / "redirect")
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(report["http_requests"], 1)
            self.assertEqual(report["status"], "UNAVAILABLE")
            self.assertEqual(report["http_status"], 302)
            serialized = json.dumps(report)
            self.assertNotIn("secret-sentinel", serialized)
            self.assertNotIn("other.example", serialized)
            self.assertNotIn("redirect", serialized)

    def test_invalid_url_and_transport_error_do_not_retry_or_leak_messages(self):
        with mock.patch(
                "knowledge_base.pipeline_v1.au_runtime_config.load_au_runtime_config",
                return_value=({"url": "http://probe.example/v1/chat/completions", "token": "secret-sentinel"}, None, None)), \
                tempfile.TemporaryDirectory() as tmp, \
                mock.patch("urllib.request.build_opener") as build_opener:
            report = runtime(Path(tmp) / "invalid-url")
            build_opener.assert_not_called()
            self.assertEqual(report["http_requests"], 0)
            self.assertNotIn("secret-sentinel", json.dumps(report))

        opener = mock.Mock()
        opener.open.side_effect = OSError("failure included secret-sentinel and https://probe.example")
        with tempfile.TemporaryDirectory() as tmp, mock.patch("urllib.request.build_opener", return_value=opener):
            report = runtime(Path(tmp) / "transport")
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(report["http_requests"], 1)
            serialized = json.dumps(report)
            self.assertNotIn("secret-sentinel", serialized)
            self.assertNotIn("probe.example", serialized)
            self.assertNotIn("failure included", serialized)


if __name__ == "__main__":
    unittest.main()
