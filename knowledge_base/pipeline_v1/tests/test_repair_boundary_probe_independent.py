"""Independent regression checks for the FORMAL boundary probe.

These tests exercise grammar behavior, decoded-string coverage, protocol status,
and aggregation compatibility. They make no backend or AU-semantic claim.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.repair_agent import formal_probe
from knowledge_base.pipeline_v1.repair_agent.formal_probe import (
    _coverage,
    aggregate_reports,
    envelope,
    fixtures,
    remote_cases,
    run_formal_probe,
    selection_fixture,
    synthetic_task,
    validate_output,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON310 = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python310/python.exe"
CHILD_ENV = "COLIEE_FORMAL_BOUNDARY_PROBE_PY310_CHILD"
CFG = {"model": "synthetic", "jobs_url": "https://example.invalid/v1/jobs", "token": "synthetic"}
ADAPTER = "knowledge_base.pipeline_v1.repair_agent.adapter.JobsAdapter"

# Frozen at tester intake. The FORMAL probe is test-only; these production
# contracts must retain their original bytes through this correction.
CONTRACT_SHA256 = {
    "repair_wire.v2.json": "5096719941696325727c1fe51d9c2fe8fb75076f035df6cf10e34b939badc75b",
    "repair_selection_wire.v1.json": "29885b5687cbddb6061175a4b5cecbc5b6a6a11c7724dc5acde9125124621b67",
    "repair_tools.v2.json": "8991788d6a7aec73ffb5d621c67f0cda0f1c70dd1871708d7407527c0e9b981e",
}


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def _set_at(value, path, replacement):
    parent = _at(value, path[:-1])
    parent[path[-1]] = replacement


def _fixture(case_id):
    return copy.deepcopy(next(row for row in fixtures() if row["case_id"] == case_id))


def _mock_response_for(fixture, output):
    """Map a full-v2 synthetic response through the real selection adapter."""
    mapped = selection_fixture({
        "output": output,
        "task": fixture["task"],
        "target_path": fixture["target_path"],
        "case_id": fixture["case_id"],
        "arm": fixture["arm"],
        "turn": fixture["turn"],
        "branch": fixture["branch"],
        "expected_valid": fixture["expected_valid"],
    })["output"]
    return {"output": mapped, "provider_usage": None}


class BoundaryProbeRegressionTests(unittest.TestCase):
    def test_probe_fixtures_and_invalid_over_max_keep_ordinary_contract_limits(self):
        by_id = {row["case_id"]: row for row in fixtures()}
        self.assertEqual(120, len(_at(by_id["reason_length_120"]["output"], by_id["reason_length_120"]["target_path"])))
        self.assertEqual(121, len(_at(by_id["reason_length_121"]["output"], by_id["reason_length_121"]["target_path"])))
        self.assertEqual(300, len(_at(by_id["claim_length_300"]["output"], by_id["claim_length_300"]["target_path"])))
        self.assertEqual(301, len(_at(by_id["claim_length_301"]["output"], by_id["claim_length_301"]["target_path"])))

        for case_id, maximum, field in (
            ("reason_length_121", 120, "reason"),
            ("claim_length_301", 300, "claim"),
        ):
            fixture = by_id[case_id]
            # The invalid +1 challenge is still rejected by the normal
            # production bound, rather than by a probe-specific impossible value.
            out = fixture["output"]
            self.assertGreater(len(_at(out, fixture["target_path"])), maximum)
            valid_fixture = _fixture("reason_length_120" if field == "reason" else "claim_length_300")
            valid_check = validate_output(valid_fixture["output"], valid_fixture["task"], valid_fixture["arm"], valid_fixture["turn"])
            self.assertTrue(valid_check["valid"], valid_check)
            check = validate_output(out, fixture["task"], fixture["arm"], fixture["turn"])
            self.assertFalse(check["valid"], (case_id, check))
            self.assertTrue(any(error["validator"] == "maxLength" and error["path"][-1] == field
                                for error in check["schema_errors"]), check["schema_errors"])

    def test_coverage_uses_decoded_scalar_length_not_exact_fixture_text(self):
        for case_id, value, equivalent in (
            ("reason_length_120", "y" * 120, True),
            ("claim_length_300", "z" * 300, True),
            ("reason_length_120", "y" * 119, False),
            ("claim_length_300", "z" * 299, False),
        ):
            fixture = _fixture(case_id)
            output = copy.deepcopy(fixture["output"])
            _set_at(output, fixture["target_path"], value)
            self.assertEqual(equivalent, _coverage(output, fixture), case_id)

    def test_unicode_boundary_requires_120_decoded_scalars_and_non_ascii(self):
        fixture = _fixture("reason_unicode_120")
        for text, covered in (("é" * 120, True), ("😀" * 120, True), ("A" * 120, False), ("é" * 119, False)):
            output = copy.deepcopy(fixture["output"])
            _set_at(output, fixture["target_path"], text)
            self.assertEqual(covered, _coverage(output, fixture), (len(text), text[:2]))

    def test_wrong_branch_and_short_protocol_valid_output_do_not_cover_target(self):
        short_case = _fixture("reason_length_120")
        short_output = envelope(short_case["task"], "uncertain", "reject")
        _set_at(short_output, short_case["target_path"], "short but within host bounds")
        check = validate_output(short_output, short_case["task"], short_case["arm"], short_case["turn"])
        self.assertTrue(check["valid"], check)
        self.assertFalse(_coverage(short_output, short_case))

        wrong_branch = copy.deepcopy(short_case["output"])
        wrong_branch["tool_calls"][0]["arguments"]["decisions"][0]["verdict"] = "supported"
        self.assertFalse(_coverage(wrong_branch, short_case))

    def test_mocked_short_valid_result_is_protocol_valid_but_target_uncovered(self):
        fixture = _fixture("reason_length_120")
        output = envelope(fixture["task"], "uncertain", "reject")
        _set_at(output, fixture["target_path"], "valid but shorter")
        with tempfile.TemporaryDirectory() as temp, patch(ADAPTER) as adapter:
            adapter.return_value.return_value = _mock_response_for(fixture, output)
            report = run_formal_probe(Path(temp), CFG, [fixture["case_id"]])
        row = report["cases"][0]
        self.assertEqual("protocol_valid", row["status"])
        self.assertEqual("uncovered", row["branch_status"])
        self.assertEqual("uncovered", row["target_branch_status"])
        self.assertEqual("unverified", row["backend_compilation"])
        self.assertEqual("unverified", row["grammar_enforcement"])
        self.assertEqual("not_evaluated", report["semantic_quality"])
        self.assertEqual(1, report["cost_summary"]["attempts"])

    def test_coverage_does_not_credit_a_different_probe_branch(self):
        fixture = _fixture("reason_length_120")
        output = copy.deepcopy(fixture["output"])
        output["tool_calls"][0]["arguments"]["decisions"][0]["verdict"] = "supported"
        self.assertFalse(_coverage(output, fixture))

    def test_mixed_formal_suite_versions_are_rejected_by_aggregator(self):
        with tempfile.TemporaryDirectory() as temp, patch(ADAPTER) as adapter:
            fixture = _fixture("uncertain_reject")
            adapter.return_value.return_value = _mock_response_for(fixture, fixture["output"])
            report = run_formal_probe(Path(temp), CFG, [fixture["case_id"]])
        mixed = copy.deepcopy(report)
        mixed["version"] = "repair-formal-suite-selection-v0"
        with self.assertRaisesRegex(ValueError, "incompatible_formal_report"):
            aggregate_reports([report, mixed])

    def test_original_production_contract_bytes_match_pre_correction_snapshot(self):
        contract_root = REPO_ROOT / "knowledge_base" / "pipeline_v1" / "contracts"
        for name, expected in CONTRACT_SHA256.items():
            with self.subTest(contract=name):
                actual = hashlib.sha256((contract_root / name).read_bytes()).hexdigest()
                self.assertEqual(expected, actual)


try:
    import lark as _lark
except ImportError:
    _lark = None


def _lark_converter():
    """Translate only the repair compiler's emitted EBNF subset for Lark."""
    token_re = re.compile(r'"(?:\\.|[^"\\])*"|\[(?:\\.|[^\]\\])*\]|[A-Za-z][A-Za-z0-9-]*|\{\d+,\d+\}|::=|[|()?*]')

    def convert(grammar):
        lines = []
        for line in grammar.splitlines():
            parts, position = [], 0
            for match in token_re.finditer(line):
                if line[position:match.start()].strip():
                    raise AssertionError("unrecognized emitted grammar syntax")
                token = match.group()
                if token == "::=": token = ":"
                elif token.startswith('"'):
                    if json.loads(token) == "": token = ""
                elif token.startswith("["):
                    token = token.replace(r"\x5b", r"\[").replace(r"\x5d", r"\]")
                    token = "/" + token.replace("/", r"\/") + "/"
                elif token.startswith("{"):
                    low, high = token[1:-1].split(",")
                    token = f"~{low}..{high}"
                else:
                    token = token.replace("-", "_")
                parts.append(token)
                position = match.end()
            if line[position:].strip():
                raise AssertionError("unrecognized trailing emitted grammar syntax")
            lines.append(" ".join(parts))
        return "\n".join(lines)

    return convert


@unittest.skipIf(_lark is None, "Lark absent; parent test routes this grammar suite to existing Python 3.10")
class BoundaryProbeActualGrammarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from knowledge_base.pipeline_v1.repair_agent.grammar import Compiler
        cls.convert = _lark_converter()
        # This is a test-only scalar-length boundary grammar. It deliberately
        # has no const enum containing the fixture's complete string value.
        cls.exact_120 = _lark.Lark(
            cls.convert(Compiler().compile({"type": "string", "minLength": 120, "maxLength": 120})),
            start="root", parser="earley", lexer="dynamic_complete",
        )
        cls.production_120 = _lark.Lark(
            cls.convert(Compiler().compile({"type": "string", "minLength": 1, "maxLength": 120})),
            start="root", parser="earley", lexer="dynamic_complete",
        )
        cls.production_300 = _lark.Lark(
            cls.convert(Compiler().compile({"type": "string", "minLength": 1, "maxLength": 300})),
            start="root", parser="earley", lexer="dynamic_complete",
        )

    def _accepts(self, parser, encoded_string):
        try:
            parser.parse(encoded_string)
            return True
        except _lark.exceptions.LarkError:
            return False

    def test_test_only_exact_length_is_decoded_scalar_count_not_const_value(self):
        for text in ("é" * 120, "😀" * 120, "A" * 120):
            encoded = json.dumps(text, ensure_ascii=True, separators=(",", ":"))
            with self.subTest(prefix=repr(text[:2])):
                self.assertTrue(self._accepts(self.exact_120, encoded))
        self.assertFalse(self._accepts(self.exact_120, json.dumps("é" * 119)))
        self.assertFalse(self._accepts(self.exact_120, json.dumps("é" * 121)))
        # JSON escape sequences are counted after decoding: one surrogate pair
        # encodes one scalar, so 119 ASCII scalars plus that pair totals 120.
        escaped = '"' + ("a" * 119) + r"\ud83d\ude00" + '"'
        self.assertTrue(self._accepts(self.exact_120, escaped))

    def test_invalid_max_plus_one_fixtures_remain_rejected_by_ordinary_limits(self):
        for parser, value in ((self.production_120, "x" * 121), (self.production_300, "x" * 301)):
            self.assertFalse(self._accepts(parser, json.dumps(value, ensure_ascii=True)))
        self.assertTrue(self._accepts(self.production_120, json.dumps("x" * 120)))
        self.assertTrue(self._accepts(self.production_300, json.dumps("x" * 300)))


class BoundaryProbePython310DiagnosticTests(unittest.TestCase):
    @unittest.skipIf(os.environ.get(CHILD_ENV) == "1", "already running in the Python 3.10 child")
    def test_actual_grammar_runs_under_existing_python310_when_available(self):
        if not PYTHON310.is_file():
            self.skipTest(f"existing Python 3.10 not found: {PYTHON310}")
        env = os.environ.copy()
        env[CHILD_ENV] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [str(PYTHON310), "-m", "unittest",
             "knowledge_base.pipeline_v1.tests.test_repair_boundary_probe_independent.BoundaryProbeActualGrammarTests", "-v"],
            cwd=REPO_ROOT, env=env, text=True, capture_output=True, timeout=180,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("Ran 2 tests", output, output)
        self.assertNotIn("skipped", output.lower(), output)


if __name__ == "__main__":
    unittest.main()
