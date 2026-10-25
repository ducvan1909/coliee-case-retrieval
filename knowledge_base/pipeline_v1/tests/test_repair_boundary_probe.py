"""Implementer boundary smoke: real grammar acceptance, zero inference."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from knowledge_base.pipeline_v1.repair_agent.boundary_probe import (
    boundary_case, probe_decoding, _target_nodes)
from knowledge_base.pipeline_v1.repair_agent.formal_probe import (
    VERSION, _at, _coverage, _branch_exercised, aggregate_reports,
    run_formal_probe, selection_fixtures)
from knowledge_base.pipeline_v1.repair_agent.selection import selection_schema, selection_decoding
from knowledge_base.pipeline_v1.repair_agent.core import MODEL, POLICY

INDEX = {f["case_id"]: f for f in selection_fixtures()}
VALID = [cid for cid, f in INDEX.items() if boundary_case(f) and f["expected_valid"]]
PYTHON310 = Path(r"C:\Users\ducva\AppData\Local\Programs\Python\Python310\python.exe")
ADAPTER = "knowledge_base.pipeline_v1.repair_agent.adapter.JobsAdapter"


def grammar(f):
    claim = "replacements" in f["target_path"]
    return probe_decoding(f, forced_verdict="defect_found" if claim else "uncertain",
                          forced_action="replace" if claim else None)


def text(f, value=None, *, ascii=False):
    output = copy.deepcopy(f["output"])
    if value is not None:
        _at(output, f["target_path"][:-1])[f["target_path"][-1]] = value
    schema = selection_schema(f["task"], f["arm"], f["turn"], ["a"])
    def order(value, node):
        if "oneOf" in node or "anyOf" in node:
            variants = node.get("oneOf", node.get("anyOf", []))
            node = next((v for v in variants if isinstance(value, dict) and all(
                value.get(k) == n["const"] for k, n in v.get("properties", {}).items()
                if "const" in n)), variants[0])
        if isinstance(value, dict):
            props = node.get("properties", {})
            return {k: order(value[k], props.get(k, {})) for k in props if k in value}
        if isinstance(value, list): return [order(v, node.get("items", {})) for v in value]
        return value
    return json.dumps(order(output, schema), ensure_ascii=ascii, separators=(",", ":"))


class BoundaryProbeTests(unittest.TestCase):
    def test_all_79_fixtures_prepare_with_zero_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
            report = run_formal_probe(tmp)
        adapter.assert_not_called()
        self.assertEqual(79, len(report["cases"]))
        self.assertEqual("pass", report["host_check_status"])
        self.assertEqual("pass", report["selection_check_status"])
        self.assertEqual(0, report["cost_summary"]["attempts"])
        self.assertTrue(all(r["status"] == "prepared" for r in report["cases"]))

    def test_all_seven_valid_boundaries_and_production_unchanged(self):
        self.assertEqual(7, len(VALID))
        for cid in VALID:
            f = INDEX[cid]
            before = selection_decoding(f["task"], f["arm"], f["turn"], ["a"])
            _, detail = grammar(f)
            length = len(_at(f["output"], f["target_path"]))
            self.assertEqual(length, detail["probe_restriction"]["minLength"])
            self.assertEqual(length, detail["probe_restriction"]["maxLength"])
            original = _target_nodes(selection_schema(f["task"], f["arm"], f["turn"], ["a"]), f["target_path"])
            self.assertEqual(detail["production_limits"]["maxLength"], original[0]["maxLength"])
            self.assertEqual(before, selection_decoding(f["task"], f["arm"], f["turn"], ["a"]))

    def test_invalid_limits_not_narrowed_or_const_forced(self):
        for cid, f in INDEX.items():
            if not boundary_case(f) or f["expected_valid"]: continue
            actual, detail = grammar(f)
            claim = "replacements" in f["target_path"]
            original = selection_decoding(f["task"], f["arm"], f["turn"], ["a"],
                forced_verdict="defect_found" if claim else "uncertain",
                forced_action="replace" if claim else None)
            self.assertEqual(original, actual, cid)
            self.assertIsNone(detail["probe_restriction"])
            self.assertEqual("unverified", detail["original_max_enforcement"])

    def test_length_coverage_unicode_condition_and_exact_escape_fixtures(self):
        for cid in VALID:
            f = INDEX[cid]; out = copy.deepcopy(f["output"])
            n = len(_at(out, f["target_path"]))
            _at(out, f["target_path"][:-1])[f["target_path"][-1]] = ("é" if "unicode" in cid else "y") * n
            self.assertTrue(_coverage(out, f), cid)
            self.assertTrue(_branch_exercised(out, f), cid)
            _at(out, f["target_path"][:-1])[f["target_path"][-1]] = "y" * (n - 1)
            self.assertFalse(_coverage(out, f), cid)
        f = INDEX["reason_unicode_120"]; out = copy.deepcopy(f["output"])
        _at(out, f["target_path"][:-1])["reason"] = "a" * 120
        self.assertFalse(_coverage(out, f))
        self.assertFalse(_branch_exercised(out, f))
        for cid in ("reason_unicode_escape", "claim_unicode_escape"):
            f = INDEX[cid]; out = copy.deepcopy(f["output"])
            _at(out, f["target_path"][:-1])[f["target_path"][-1]] = "é" * len(_at(out, f["target_path"]))
            self.assertFalse(_coverage(out, f))

    def test_supported_and_duplicate_do_not_cover_wrong_target(self):
        for cid in ("supported_reject", "duplicate_2_anchor", "other_kind_length_160"):
            f = INDEX[cid]; out = copy.deepcopy(f["output"])
            decisions = out["tool_calls"][0]["arguments"]["decisions"]
            original = copy.deepcopy(decisions[0])
            decisions[0] = dict(proposal_id=original["proposal_id"], verdict="uncertain", reason="x")
            decisions.append(original)  # Matching another decision is insufficient.
            self.assertFalse(_coverage(out, f), cid)
            self.assertFalse(_branch_exercised(out, f), cid)

    def test_report_observation_version_and_cost_identity(self):
        f = INDEX["reason_length_120"]; output = copy.deepcopy(f["output"])
        _at(output, f["target_path"][:-1])["reason"] = "y" * 120
        cfg = dict(model=MODEL, jobs_url="https://example.invalid/v1/jobs", token="synthetic")
        with tempfile.TemporaryDirectory() as tmp, patch(ADAPTER) as adapter:
            adapter.return_value.return_value = dict(output=output, provider_usage=dict(total_tokens=23))
            report = run_formal_probe(tmp, cfg, [f["case_id"]])
        row = report["cases"][0]
        self.assertEqual("covered", row["branch_status"])
        self.assertEqual("exercised", row["target_branch_status"])
        self.assertEqual(120, row["boundary_probe"]["observed_decoded_length"])
        self.assertEqual(dict(minLength=1, maxLength=120), row["boundary_probe"]["production_limits"])
        self.assertEqual("unverified", row["grammar_enforcement"])
        self.assertEqual(23, report["cost_summary"]["charged_or_reserved_tokens"])
        self.assertEqual(1, report["cost_summary"]["attempts"])
        self.assertEqual(64, len(row["attempt_id"]))
        self.assertEqual(VERSION, report["version"])
        old = copy.deepcopy(report); old["version"] = "repair-formal-suite-selection-v1"
        with self.assertRaisesRegex(ValueError, "incompatible_formal_report"):
            aggregate_reports([old, report])
        self.assertEqual(1200, POLICY["output_tokens"])

    def test_diagnostic_grammar_acceptance(self):
        if not PYTHON310.is_file(): self.skipTest("diagnostic Python310 unavailable")
        result = subprocess.run([str(PYTHON310), "-m", "unittest",
            __name__ + ".BoundaryLarkTests", __name__ + ".BoundaryXGrammarTests", "-v"],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=180)
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("skipped", output.lower(), output)


class BoundaryLarkTests(unittest.TestCase):
    def test_all_valid_lengths_accept_reject(self):
        from knowledge_base.pipeline_v1.tests.test_repair_grammar import parser, Lark
        if Lark is None: self.skipTest("Lark unavailable in this interpreter")
        for cid in VALID:
            f = INDEX[cid]; p = parser(grammar(f)[0]["ebnf"])
            n = len(_at(f["output"], f["target_path"]))
            for ascii in (False, True):
                p.parse(text(f, ("é😀" * 60) if "unicode" in cid else "y" * n, ascii=ascii))
            for size in (n - 1, n + 1):
                with self.subTest(cid=cid, size=size), self.assertRaises(Exception):
                    p.parse(text(f, ("é" if "unicode" in cid else "y") * size))
            if "unicode" in cid:
                with self.assertRaises(Exception): p.parse(text(f, "x" * n))
            if cid.startswith("other_kind_length_"):
                nonother = copy.deepcopy(f)
                _at(nonother["output"], f["target_path"][:-1]).update(kind="holding", other_kind=None)
                with self.assertRaises(Exception): p.parse(text(nonother))

    def test_original_production_boundaries_without_narrowing(self):
        from knowledge_base.pipeline_v1.tests.test_repair_grammar import parser, Lark
        if Lark is None: self.skipTest("Lark unavailable in this interpreter")
        for cid, f in INDEX.items():
            if not boundary_case(f): continue
            claim = "replacements" in f["target_path"]
            p = parser(selection_decoding(f["task"], f["arm"], f["turn"], ["a"],
                forced_verdict="defect_found" if claim else "uncertain",
                forced_action="replace" if claim else None)["ebnf"])
            with self.subTest(cid=cid):
                if f["expected_valid"]: p.parse(text(f, ascii=True))
                else:
                    with self.assertRaises(Exception): p.parse(text(f, ascii=True))


class BoundaryXGrammarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from knowledge_base.pipeline_v1.tests.test_compact_scalar_regression import CompactScalarXGrammarTests
        CompactScalarXGrammarTests.setUpClass()
        cls.xg = CompactScalarXGrammarTests.xgrammar
        vocab = [chr(i) for i in range(32, 127)] + ["é", "😀", "<eos>"]
        cls.info = cls.xg.TokenizerInfo(vocab, stop_token_ids=[len(vocab) - 1])
        cls.compiler = cls.xg.GrammarCompiler(cls.info, max_threads=1)

    def test_real_acceptance_and_completion_all_boundaries(self):
        for cid in VALID:
            f = INDEX[cid]; n = len(_at(f["output"], f["target_path"]))
            compiled = self.compiler.compile_grammar(self.xg.Grammar.from_ebnf(grammar(f)[0]["ebnf"]))
            cases = [("é😀" * 60 if "unicode" in cid else "y" * n, True),
                     (("é" if "unicode" in cid else "y") * (n - 1), False),
                     (("é" if "unicode" in cid else "y") * (n + 1), False)]
            if "unicode" in cid: cases.append(("x" * n, False))
            for value, expected in cases:
                for ascii in (False, True):
                    matcher = self.xg.GrammarMatcher(compiled)
                    accepted = matcher.accept_string(text(f, value, ascii=ascii))
                    if accepted: accepted = matcher.accept_token(self.info.vocab_size - 1)
                    with self.subTest(cid=cid, length=len(value), ascii=ascii):
                        self.assertEqual(expected, accepted)
            if "unicode" in cid:
                for escaped in (r"\ud83d", r"\ude00", r"\uZZZZ", r"\xE9"):
                    malformed = text(f, "é" * n).replace("é", escaped, 1)
                    matcher = self.xg.GrammarMatcher(compiled)
                    self.assertFalse(matcher.accept_string(malformed), escaped)
            if cid.startswith("other_kind_length_"):
                nonother = copy.deepcopy(f)
                _at(nonother["output"], f["target_path"][:-1]).update(kind="holding", other_kind=None)
                matcher = self.xg.GrammarMatcher(compiled)
                self.assertFalse(matcher.accept_string(text(nonother)))


if __name__ == "__main__": unittest.main()
