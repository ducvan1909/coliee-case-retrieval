"""Independent acceptance tests for the generated repair wire grammar.

The grammar is parsed as EBNF and then exercised with concrete serialized
responses. These checks do not use the JSON Schema validator as a substitute
for grammar behavior, and they make no AU semantic-quality claim.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC_ROOT = PIPELINE_ROOT / "outputs" / "grammar_diagnostic_deps"
PYTHON310 = Path(r"C:\Users\ducva\AppData\Local\Programs\Python\Python310\python.exe")
CHILD_ENV = "COLIEE_REPAIR_GRAMMAR_DIAGNOSTIC_CHILD"


def _load_lark():
    try:
        import lark
    except ImportError:
        raise unittest.SkipTest("Lark absent in this interpreter; parent test routes to Python 3.10")
    # Test-only translation of the emitted EBNF dialect. The compact scalar
    # helper predates the bounded-repeat forms used by the repair compiler.
    token_re = re.compile(
        r'"(?:\\.|[^"\\])*"|\[(?:\\.|[^\]\\])*\]|'
        r'[A-Za-z][A-Za-z0-9-]*|\{\d+,\d+\}|::=|[|()?*]'
    )

    def convert(ebnf):
        lines = []
        for line in ebnf.splitlines():
            parts = []
            previous_end = 0
            for match in token_re.finditer(line):
                if line[previous_end:match.start()].strip():
                    raise AssertionError("Unrecognized EBNF syntax")
                token = match.group()
                if token == "::=":
                    token = ":"
                elif token.startswith('"'):
                    if json.loads(token) == "":
                        token = ""
                elif token.startswith("["):
                    token = token.replace(r"\x5b", r"\[").replace(r"\x5d", r"\]")
                    token = "/" + token.replace("/", r"\/") + "/"
                elif token.startswith("{"):
                    low, high = token[1:-1].split(",")
                    token = f"~{low}..{high}"
                else:
                    token = token.replace("-", "_")
                parts.append(token)
                previous_end = match.end()
            if line[previous_end:].strip():
                raise AssertionError("Unrecognized trailing EBNF syntax")
            lines.append(" ".join(parts))
        return "\n".join(lines)

    return lark, convert


def _wire(task_id, decisions):
    # Preserve the schema emitter's property order; sort_keys would describe a
    # different wire spelling because the decoder grammar is canonical.
    return {"tool_calls": [{"name": "submit_revision", "arguments": {
        "task_id": task_id,
        "decisions": decisions,
    }}]}


def _decision(proposal_id, verdict="uncertain", reason="Independent grammar fixture"):
    return {"proposal_id": proposal_id, "verdict": verdict, "reason": reason}


class RepairGrammarAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lark, converter = _load_lark()
        from knowledge_base.pipeline_v1.repair_agent.formal_probe import synthetic_task
        from knowledge_base.pipeline_v1.repair_agent.wire import decoding

        cls.synthetic_task = synthetic_task
        cls.decoding = staticmethod(decoding)
        cls.task = synthetic_task(2)
        cls.proposal_ids = [row["proposal_id"] for row in cls.task["original_proposals"]]
        cls.read_ids = ["atom-a", "atom-b"]
        cls.ebnf = decoding(cls.task, "R2", 1, cls.read_ids)["ebnf"]
        cls.parser = cls._parser(cls.ebnf, converter)
        cls.single_task = synthetic_task(1)
        cls.single_ebnf = decoding(cls.single_task, "R1", 1, ["atom-a"])["ebnf"]
        cls.single_parser = cls._parser(cls.single_ebnf, converter)
        cls.final_ebnf = decoding(cls.task, "R2", 2, cls.read_ids)["ebnf"]
        cls.final_parser = cls._parser(cls.final_ebnf, converter)

    @classmethod
    def _parser(cls, ebnf, converter):
        return cls.lark.Lark(
            converter(ebnf), start="root", parser="earley", lexer="dynamic_complete"
        )

    def accepts(self, parser, value):
        parser.parse(value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        ))

    def rejects(self, parser, value):
        with self.assertRaises(self.lark.exceptions.UnexpectedInput):
            self.accepts(parser, value)

    def _valid_two_decisions(self, first=None, second=None):
        return _wire("formal-task", [
            first or _decision(self.proposal_ids[0]),
            second or _decision(self.proposal_ids[1]),
        ])

    def test_reason_and_claim_decoded_unicode_length_and_json_scalar_rules(self):
        pid = self.proposal_ids[0]
        base_second = _decision(self.proposal_ids[1])
        for text in ("x" * 120, "😀" * 120, "é" * 120, "a" * 119 + "😀"):
            with self.subTest(reason_length=len(text), tail=repr(text[-3:])):
                row = _decision(pid, reason=text)
                self.accepts(self.parser, self._valid_two_decisions(row, base_second))
        for text in ("x" * 121, "😀" * 121, "é" * 121):
            with self.subTest(rejected_reason_length=len(text)):
                self.rejects(self.parser, self._valid_two_decisions(
                    _decision(pid, reason=text), base_second
                ))

        # JSON escapes count by the decoded scalar, while malformed JSON
        # scalar spellings remain excluded by the emitted grammar itself.
        escaped = json.dumps("😀" * 120, ensure_ascii=True)[1:-1]
        escaped_wire = self._valid_two_decisions(
            _decision(pid, reason="😀" * 120), base_second
        )
        escaped_wire = json.dumps(escaped_wire, ensure_ascii=False, separators=(",", ":"))
        escaped_wire = escaped_wire.replace("😀" * 120, escaped)
        self.accepts(self.parser, escaped_wire)
        raw_prefix = (
            '{"tool_calls":[{"name":"submit_revision","arguments":'
            '{"task_id":"formal-task","decisions":[{"proposal_id":"'
            + pid + '","verdict":"uncertain","reason":"'
        )
        raw_suffix = (
            '"},{"proposal_id":"' + self.proposal_ids[1]
            + '","verdict":"uncertain","reason":"ok"}]}}]}'
        )
        for raw in ('a"b', "a\\q", "line\nfeed", "nul\x00byte"):
            with self.subTest(raw=repr(raw)):
                self.rejects(self.parser, raw_prefix + raw + raw_suffix)

        replacement = {
            "action": "replace",
            "replacements": [{
                "au": {
                    "kind": "holding", "claim": "😀" * 300,
                    "evidence_ref_ids": ["atom-a"], "speaker": "current_court",
                    "attribution_role": "proposition",
                },
                "primary_proposition": {"atom_id": "atom-a", "quote": "Rule."},
            }],
        }
        defect = {
            "proposal_id": pid, "verdict": "defect_found", "reason": "evidence mismatch",
            "defect_type": "evidence_support", "witnesses": [
                {"atom_id": "atom-a", "quote": "Rule."}
            ], "correction": replacement,
        }
        self.accepts(self.parser, self._valid_two_decisions(defect, base_second))
        replacement["replacements"][0]["au"]["claim"] = "😀" * 301
        self.rejects(self.parser, self._valid_two_decisions(defect, base_second))

    def test_conditional_other_kind_and_optional_field_commas(self):
        pid = self.proposal_ids[0]
        other = {
            "proposal_id": pid, "verdict": "defect_found", "reason": "repair kind",
            "defect_type": "qualification", "witnesses": [
                {"atom_id": "atom-a", "quote": "Rule."}
            ], "correction": {"action": "replace", "replacements": [{
                "au": {"kind": "other", "other_kind": "administrative doctrine",
                       "claim": "Claim.", "evidence_ref_ids": ["atom-a"],
                       "speaker": "current_court", "attribution_role": "proposition"},
                "primary_proposition": {"atom_id": "atom-a", "quote": "Rule."},
            }]},
        }
        second = _decision(self.proposal_ids[1])
        self.accepts(self.parser, self._valid_two_decisions(other, second))
        for value in (None, ""):
            bad = copy.deepcopy(other)
            bad["correction"]["replacements"][0]["au"]["other_kind"] = value
            self.rejects(self.parser, self._valid_two_decisions(bad, second))
        for missing in (True, False):
            bad = copy.deepcopy(other)
            au = bad["correction"]["replacements"][0]["au"]
            if missing:
                del au["other_kind"]
            else:
                au["other_kind"] = "x" * 161
            self.rejects(self.parser, self._valid_two_decisions(bad, second))

        nonother = copy.deepcopy(other)
        au = nonother["correction"]["replacements"][0]["au"]
        au["kind"] = "holding"
        au["other_kind"] = None
        self.accepts(self.parser, self._valid_two_decisions(nonother, second))
        au["other_kind"] = "label"
        self.rejects(self.parser, self._valid_two_decisions(nonother, second))

        without_optional = self._valid_two_decisions(
            _decision(pid), second
        )
        with_optional = self._valid_two_decisions(
            {**_decision(pid), "needed_context": ["condition", "exception"]}, second
        )
        self.accepts(self.parser, without_optional)
        self.accepts(self.parser, with_optional)
        self.rejects(self.parser, self._valid_two_decisions(
            {**_decision(pid), "needed_context": ["condition", "condition"]}, second
        ))

    def test_duplicate_branch_and_single_proposal_duplicate_is_impossible(self):
        first, second = self.proposal_ids
        duplicate = {
            "proposal_id": first, "verdict": "defect_found", "reason": "duplicate",
            "defect_type": "duplicate", "witnesses": [
                {"atom_id": "atom-a", "quote": "Rule."}
            ], "correction": {"action": "reject"}, "retained_proposal_id": second,
        }
        self.accepts(self.parser, self._valid_two_decisions(
            duplicate, {"proposal_id": second, "verdict": "supported",
                        "reason": "supported", "primary_proposition":
                        {"atom_id": "atom-a", "quote": "Rule."}}
        ))
        no_retained = copy.deepcopy(duplicate)
        del no_retained["retained_proposal_id"]
        self.rejects(self.parser, self._valid_two_decisions(no_retained, _decision(second)))
        wrong_action = copy.deepcopy(duplicate)
        wrong_action["correction"] = {"action": "replace", "replacements": []}
        self.rejects(self.parser, self._valid_two_decisions(wrong_action, _decision(second)))

        sole = self.single_task["original_proposals"][0]["proposal_id"]
        impossible = {
            "proposal_id": sole, "verdict": "defect_found", "reason": "duplicate",
            "defect_type": "duplicate", "witnesses": [
                {"atom_id": "atom-a", "quote": "Rule."}
            ], "correction": {"action": "reject"}, "retained_proposal_id": sole,
        }
        self.rejects(self.single_parser, _wire("formal-task", [impossible]))
        self.accepts(self.single_parser, _wire("formal-task", [_decision(sole)]))

    def test_open_span_integer_zero_and_one_bounds_are_in_generated_grammar(self):
        def span(start, end):
            return {"tool_calls": [{"name": "open_span", "arguments": {
                "atom_id": "atom-a", "start_char": start, "end_char": end,
            }}]}

        self.accepts(self.parser, span(0, 1))
        self.accepts(self.parser, span(0, 2))
        for start, end in ((-1, 1), (0, 0), (0.5, 1), (0, 1.5), ("0", 1), (0, "1")):
            with self.subTest(start=start, end=end):
                self.rejects(self.parser, span(start, end))

    def test_dynamic_id_binding_stability_and_bounded_relation_growth(self):
        from knowledge_base.pipeline_v1.repair_agent.formal_probe import synthetic_task

        normal = self.decoding(self.task, "R2", 1, self.read_ids)["ebnf"]
        reordered = self.decoding(self.task, "R2", 1, list(reversed(self.read_ids)))["ebnf"]
        self.assertEqual(normal, reordered)
        self.assertEqual(normal, self.decoding(self.task, "R2", 1, self.read_ids)["ebnf"])
        bad_evidence = {
            "proposal_id": self.proposal_ids[0], "verdict": "supported",
            "reason": "supported", "primary_proposition": {
                "atom_id": "foreign-atom", "quote": "Rule."},
        }
        self.rejects(self.parser, self._valid_two_decisions(
            bad_evidence, _decision(self.proposal_ids[1])
        ))
        for atom_id in self.read_ids:
            with self.subTest(atom_id=atom_id):
                supported = {
                    "proposal_id": self.proposal_ids[0], "verdict": "supported",
                    "reason": "supported",
                    "primary_proposition": {"atom_id": atom_id, "quote": "Rule."},
                }
                self.accepts(self.parser, self._valid_two_decisions(
                    supported, _decision(self.proposal_ids[1])
                ))
                defect = {
                    "proposal_id": self.proposal_ids[0], "verdict": "defect_found",
                    "reason": "repair", "defect_type": "evidence_support",
                    "witnesses": [{"atom_id": atom_id, "quote": "Rule."}],
                    "correction": {"action": "replace", "replacements": [{
                        "au": {"kind": "holding", "claim": "Claim.",
                               "evidence_ref_ids": [atom_id], "speaker": "current_court",
                               "attribution_role": "proposition"},
                        "primary_proposition": {"atom_id": atom_id, "quote": "Rule."},
                    }]},
                }
                self.accepts(self.parser, self._valid_two_decisions(
                    defect, _decision(self.proposal_ids[1])
                ))

        sizes = []
        for count in (4, 8, 16, 32):
            # The finite evidence domain should still grow without expanding
            # decision relationships. Supported-set states are exponential in
            # proposal count, so production deliberately caps that count at 6.
            task = synthetic_task(2)
            ids = [f"atom-{i:04d}" for i in range(count)]
            grammar = self.decoding(task, "R2", 1, ids)["ebnf"]
            self.assertEqual(grammar, self.decoding(task, "R2", 1, list(reversed(ids)))["ebnf"])
            sizes.append(len(grammar))
        self.assertLess(sizes[-1], sizes[0] * 12,
                        f"evidence-domain growth looks combinatorial: {sizes}")
        from knowledge_base.pipeline_v1.repair_agent.grammar import DECISION_RELATION_LIMIT
        self.assertEqual(6, DECISION_RELATION_LIMIT)
        bounded = self.decoding(synthetic_task(DECISION_RELATION_LIMIT), "R1", 1, ["a"])["ebnf"]
        self.assertLess(len(bounded.encode("utf-8")), 250000)
        with self.assertRaisesRegex(ValueError, "decision_relation_limit_exceeded"):
            self.decoding(synthetic_task(DECISION_RELATION_LIMIT + 1), "R1", 1, ["a"])

    def test_final_turn_is_submit_only_and_host_only_relations_are_not_semantic_claims(self):
        names = ("open_span", "expand_context", "get_related_aus")
        for name in names:
            self.rejects(self.final_parser, {"tool_calls": [{"name": name, "arguments": {}}]})
        supported = {
            "proposal_id": self.proposal_ids[0], "verdict": "supported", "reason": "ok",
            "primary_proposition": {"atom_id": "atom-a", "quote": "Rule."},
        }
        self.accepts(self.final_parser, self._valid_two_decisions(supported, _decision(self.proposal_ids[1])))


class RepairGrammarDiagnosticSubprocessTests(unittest.TestCase):
    @unittest.skipIf(os.environ.get(CHILD_ENV) == "1", "already running in diagnostic child")
    def test_actual_grammar_checks_run_in_explicit_python310(self):
        if not PYTHON310.is_file():
            self.skipTest(f"diagnostic Python 3.10 unavailable: {PYTHON310}")
        env = os.environ.copy()
        env[CHILD_ENV] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        suites = [
            "knowledge_base.pipeline_v1.tests.test_repair_grammar_independent.RepairGrammarAcceptanceTests",
            "knowledge_base.pipeline_v1.tests.test_repair_grammar_independent.RepairGrammarXGrammarTests",
        ]
        result = subprocess.run(
            [str(PYTHON310), "-m", "unittest", *suites, "-v"],
            cwd=REPO_ROOT, env=env, text=True, capture_output=True, timeout=180,
        )
        self.assertEqual(
            0, result.returncode,
            "Python 3.10 actual-grammar suites failed.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        output = result.stderr + result.stdout
        self.assertIn("Ran 8 tests", output, output)
        self.assertNotIn("skipped", output.lower(), output)


class RepairGrammarXGrammarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the established pinned XGrammar/tokenizer diagnostic loader.
        from knowledge_base.pipeline_v1.tests.test_compact_scalar_regression import (
            CompactScalarXGrammarTests,
        )
        CompactScalarXGrammarTests.setUpClass()
        xgrammar = CompactScalarXGrammarTests.xgrammar
        torch = CompactScalarXGrammarTests.torch

        from knowledge_base.pipeline_v1.repair_agent.wire import decoding
        from knowledge_base.pipeline_v1.repair_agent.formal_probe import synthetic_task

        cls.xgrammar = xgrammar
        cls.torch = torch
        cls.task = synthetic_task(2)
        cls.proposal_ids = [row["proposal_id"] for row in cls.task["original_proposals"]]
        cls.read_ids = ["atom-a", "atom-b"]
        cls.ebnf = decoding(cls.task, "R2", 1, cls.read_ids)["ebnf"]
        cls.vocab = list(dict.fromkeys(
            [chr(code) for code in range(32, 127)] + ["é", "😀", "<eos>"]
        ))
        cls.tokenizer_info = xgrammar.TokenizerInfo(
            cls.vocab, stop_token_ids=[cls.vocab.index("<eos>")]
        )
        compiler = xgrammar.GrammarCompiler(cls.tokenizer_info, max_threads=1)
        cls.compiled = compiler.compile_grammar(xgrammar.Grammar.from_ebnf(cls.ebnf))

    def _serialize(self, value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _two(self, first=None, second=None):
        return _wire("formal-task", [
            first or _decision(self.proposal_ids[0]),
            second or _decision(self.proposal_ids[1]),
        ])

    def _accept(self, value):
        matcher = self.xgrammar.GrammarMatcher(self.compiled)
        accepted = matcher.accept_string(value if isinstance(value, str) else self._serialize(value))
        self.assertTrue(accepted, repr(value)[:300])

    def _reject(self, value):
        matcher = self.xgrammar.GrammarMatcher(self.compiled)
        accepted = matcher.accept_string(value if isinstance(value, str) else self._serialize(value))
        self.assertFalse(accepted, repr(value)[:300])

    def _mask_after(self, prefix):
        matcher = self.xgrammar.GrammarMatcher(self.compiled)
        self.assertTrue(matcher.accept_string(prefix), prefix[-100:])
        mask = self.xgrammar.allocate_token_bitmask(1, self.tokenizer_info.vocab_size)
        matcher.fill_next_token_bitmask(mask)
        logits = self.torch.zeros((1, self.tokenizer_info.vocab_size))
        self.xgrammar.apply_token_bitmask_inplace(logits, mask, backend="cpu")
        return {
            token: bool(self.torch.isfinite(logits[0, self.vocab.index(token)]))
            for token in ('a', '"')
        }

    def test_xgrammar_accept_string_enforces_decoded_lengths_and_scalar_validity(self):
        pid = self.proposal_ids[0]
        second = _decision(self.proposal_ids[1])
        for length in (119, 120):
            self._accept(self._two(_decision(pid, reason="a" * length), second))
        for length in (121,):
            self._reject(self._two(_decision(pid, reason="a" * length), second))

        for length in (299, 300):
            replacement = {
                "action": "replace", "replacements": [{
                    "au": {"kind": "holding", "claim": "a" * length,
                           "evidence_ref_ids": ["atom-a"], "speaker": "current_court",
                           "attribution_role": "proposition"},
                    "primary_proposition": {"atom_id": "atom-a", "quote": "Rule."},
                }],
            }
            defect = {
                "proposal_id": pid, "verdict": "defect_found", "reason": "fix",
                "defect_type": "qualification", "witnesses": [
                    {"atom_id": "atom-a", "quote": "Rule."}
                ], "correction": replacement,
            }
            self._accept(self._two(defect, second))
        replacement["replacements"][0]["au"]["claim"] = "a" * 301
        self._reject(self._two(defect, second))

        escaped_pair = json.dumps("😀", ensure_ascii=True)[1:-1]
        escaped_wire = self._serialize(self._two(
            _decision(pid, reason="😀" * 120), second
        )).replace("😀" * 120, escaped_pair * 120)
        self._accept(escaped_wire)
        lone_surrogate = self._serialize(self._two(
            _decision(pid, reason="x"), second
        )).replace('"reason":"x"', r'"reason":"\uD800"')
        self._reject(lone_surrogate)

    def test_xgrammar_token_masks_allow_ascii_and_quote_at_boundary(self):
        pid = self.proposal_ids[0]
        template = self._two(_decision(pid, reason="SENTINEL"), _decision(self.proposal_ids[1]))
        reason_wire = self._serialize(template)
        reason_prefix = reason_wire.split("SENTINEL", 1)[0]
        self.assertEqual({"a": True, '"': True}, self._mask_after(reason_prefix + "a" * 119))
        at_reason_cap = self._mask_after(reason_prefix + "a" * 120)
        self.assertTrue(at_reason_cap['"'])
        self.assertFalse(at_reason_cap["a"])

        replacement = {
            "action": "replace", "replacements": [{
                "au": {"kind": "holding", "claim": "SENTINEL",
                       "evidence_ref_ids": ["atom-a"], "speaker": "current_court",
                       "attribution_role": "proposition"},
                "primary_proposition": {"atom_id": "atom-a", "quote": "Rule."},
            }],
        }
        defect = {
            "proposal_id": pid, "verdict": "defect_found", "reason": "fix",
            "defect_type": "qualification", "witnesses": [
                {"atom_id": "atom-a", "quote": "Rule."}
            ], "correction": replacement,
        }
        claim_wire = self._serialize(self._two(defect, _decision(self.proposal_ids[1])))
        claim_prefix = claim_wire.split("SENTINEL", 1)[0]
        self.assertEqual({"a": True, '"': True}, self._mask_after(claim_prefix + "a" * 299))
        at_claim_cap = self._mask_after(claim_prefix + "a" * 300)
        self.assertTrue(at_claim_cap['"'])
        self.assertFalse(at_claim_cap["a"])


if __name__ == "__main__":
    unittest.main()
