"""Production decision relations: native/Lark acceptance, no inference."""
import copy
import itertools
import json
from pathlib import Path
import subprocess
import unittest

from knowledge_base.pipeline_v1.repair_agent.formal_probe import (
    envelope, synthetic_task, selection_fixture)
from knowledge_base.pipeline_v1.repair_agent.grammar import Compiler, DECISION_RELATION_LIMIT
from knowledge_base.pipeline_v1.repair_agent.selection import selection_decoding, selection_schema
from knowledge_base.pipeline_v1.repair_agent.wire import decoding, wire_schema

PYTHON310 = Path(r"C:\Users\ducva\AppData\Local\Programs\Python\Python310\python.exe")


def output(task, choices, selection):
    rows = []
    for i, choice in enumerate(choices):
        verdict = choice if isinstance(choice, str) else "defect_found"
        row = copy.deepcopy(envelope(task, verdict)["tool_calls"][0]["arguments"]["decisions"][i])
        if isinstance(choice, int):
            row.update(defect_type="duplicate", correction={"action": "reject"},
                       retained_proposal_id=task["original_proposals"][choice]["proposal_id"])
        rows.append(row)
    value = envelope(task)
    value["tool_calls"][0]["arguments"]["decisions"] = rows
    if selection:
        value = selection_fixture(dict(task=task, output=value, case_id="relations",
            target_path=["tool_calls", 0, "arguments", "decisions", 0, "reason"]))["output"]
    return value


def serialize(value, schema):
    """Canonical properties only; never reorder decisions or repair values."""
    if "oneOf" in schema:
        schema = next(v for v in schema["oneOf"] if all(
            value.get(k) == n["const"] for k, n in v.get("properties", {}).items() if "const" in n))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        value = {k: json.loads(serialize(value[k], props.get(k, {})))
                 for k in list(props) + [k for k in value if k not in props] if k in value}
    elif isinstance(value, list):
        value = [json.loads(serialize(v, schema.get("items", {}))) for v in value]
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


class RelationCases:
    def test_all_three_proposal_verdict_anchor_assignments(self):
        task = synthetic_task(3)
        for selection in (False, True):
            schema = (selection_schema if selection else wire_schema)(task, "R1", 1, ["a"])
            compiled = self.compile((selection_decoding if selection else decoding)(
                task, "R1", 1, ["a"])["ebnf"])
            # Includes all supported sets, uncertain/nonduplicate defects,
            # distinct/later anchors, self edges, chains and cycles.
            for choices in itertools.product(("supported", "uncertain", "defect_found", 0, 1, 2), repeat=3):
                expected = all(not isinstance(c, int) or
                    (c != i and choices[c] == "supported") for i, c in enumerate(choices))
                with self.subTest(selection=selection, choices=choices):
                    self.assertEqual(expected, self.accepts(compiled, serialize(output(task, choices, selection), schema)))

    def test_identity_order_and_forced_branches(self):
        task = synthetic_task(2)
        for selection in (False, True):
            schema = (selection_schema if selection else wire_schema)(task, "R1", 1, ["a"])
            decode = selection_decoding if selection else decoding
            compiled = self.compile(decode(task, "R1", 1, ["a"])["ebnf"])
            value = output(task, ("uncertain", "uncertain"), selection)
            decisions = value["tool_calls"][0]["arguments"]["decisions"]
            for bad in ([decisions[0], decisions[0]], list(reversed(decisions)), decisions[:1],
                        decisions + [decisions[0]]):
                mutant = copy.deepcopy(value)
                mutant["tool_calls"][0]["arguments"]["decisions"] = bad
                self.assertFalse(self.accepts(compiled, serialize(mutant, schema)))
            for verdict, action in (("supported", None), ("uncertain", None),
                                    ("defect_found", "reject"), ("defect_found", "replace")):
                forced = self.compile(decode(task, "R1", 1, ["a"],
                    forced_verdict=verdict, forced_action=action)["ebnf"])
                value = output(task, (verdict, verdict), selection)
                if action == "replace":
                    value = envelope(task, verdict, action)
                    if selection:
                        value = selection_fixture(dict(task=task, output=value, case_id="replace",
                            target_path=["tool_calls", 0, "arguments", "decisions", 0, "reason"]))["output"]
                self.assertTrue(self.accepts(forced, serialize(value, schema)))
                if verdict == "defect_found":
                    self.assertFalse(self.accepts(forced, serialize(output(task, (1, verdict), selection), schema)))

    def test_six_proposals_later_and_multiple_supported_anchors(self):
        task = synthetic_task(6)
        schema = selection_schema(task, "R2", 2, ["a"])
        compiled = self.compile(selection_decoding(task, "R2", 2, ["a"])["ebnf"])
        for choices in ((5, "uncertain", 4, 5, "supported", "supported"),
                        ("uncertain",) * 6, ("defect_found",) * 6, ("supported",) * 6):
            self.assertTrue(self.accepts(compiled, serialize(output(task, choices, True), schema)))
        self.assertFalse(self.accepts(compiled, serialize(output(task,
            (5, "uncertain", 4, 5, "supported", "uncertain"), True), schema)))


class RelationLarkTests(RelationCases, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from knowledge_base.pipeline_v1.tests.test_repair_grammar import parser, Lark
        if Lark is None:
            raise unittest.SkipTest("Lark unavailable")
        cls.compile = staticmethod(parser)

    def accepts(self, compiled, text):
        from lark.exceptions import UnexpectedInput
        try:
            compiled.parse(text)
            return True
        except UnexpectedInput:
            return False


class RelationNativeTests(RelationCases, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from knowledge_base.pipeline_v1.tests.test_compact_scalar_regression import CompactScalarXGrammarTests
        CompactScalarXGrammarTests.setUpClass()
        cls.xgrammar = CompactScalarXGrammarTests.xgrammar
        vocab = [chr(i) for i in range(32, 127)] + ["<eos>"]
        cls.compiler = cls.xgrammar.GrammarCompiler(
            cls.xgrammar.TokenizerInfo(vocab, stop_token_ids=[95]), max_threads=1)

    def compile(self, grammar):
        return self.compiler.compile_grammar(self.xgrammar.Grammar.from_ebnf(grammar))

    def accepts(self, compiled, text):
        matcher = self.xgrammar.GrammarMatcher(compiled)
        return matcher.accept_string(text) and matcher.is_completed()


class RelationBoundTests(unittest.TestCase):
    def test_incompatible_force_action_fails_explicitly(self):
        from knowledge_base.pipeline_v1.repair_agent.wire import force_branches
        task = synthetic_task(2)
        for build in (wire_schema, selection_schema):
            for verdict, action in itertools.product(("supported", "uncertain"), ("reject", "replace")):
                schema = build(task, "R1", 1, ["a"])
                before = copy.deepcopy(schema)
                with self.assertRaisesRegex(ValueError, "^invalid_probe_action_for_verdict$"):
                    force_branches(schema, forced_verdict=verdict, forced_action=action)
                self.assertEqual(before, schema)

    def test_limit_and_schema_preserved(self):
        self.assertEqual(6, DECISION_RELATION_LIMIT)
        for count in range(1, 7):
            task = synthetic_task(count)
            schema = selection_schema(task, "R1", 1, ["a"])
            before = copy.deepcopy(schema)
            grammar = Compiler().compile(schema)
            self.assertEqual(before, schema)
            self.assertLess(len(grammar), 250000)
            print(f"relations count={count} bytes={len(grammar)} rules={len(grammar.splitlines())}")
        for decode in (decoding, selection_decoding):
            with self.assertRaisesRegex(ValueError, "^decision_relation_limit_exceeded$"):
                decode(synthetic_task(7), "R1", 1, ["a"])

    def test_actual_diagnostic_backends(self):
        if not PYTHON310.is_file():
            self.skipTest("diagnostic Python310 unavailable")
        result = subprocess.run([str(PYTHON310), "-m", "unittest",
            __name__ + ".RelationLarkTests", __name__ + ".RelationNativeTests", "-v"],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=180)
        message = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, message)
        self.assertNotIn("skipped", message.lower(), message)


if __name__ == "__main__":
    unittest.main()
