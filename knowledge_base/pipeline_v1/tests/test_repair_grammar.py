"""Local grammar-language tests; no transport, semantic or token-mask claims.

Run with the existing Python 3.10/Lark environment when venv lacks Lark.
Independent tester owns backend compilation/tokenizer coverage.
"""
import json
import re
import unittest

from knowledge_base.pipeline_v1.repair_agent.grammar import Compiler
from knowledge_base.pipeline_v1.repair_agent.wire import decoding
from knowledge_base.pipeline_v1.repair_agent.formal_probe import fixtures, synthetic_task, envelope

try:
    from lark import Lark
except ImportError:
    Lark = None


def parser(ebnf):
    """Translate the emitted EBNF subset to Lark, preserving terminals/classes."""
    lines = []
    token = re.compile(r'"(?:\\.|[^"\\])*"|\[(?:\\.|[^\]\\])*\]|[a-z][a-z0-9-]*|\S')
    for line in ebnf.splitlines():
        name, expression = line.split(" ::= ", 1)
        parts = []
        for value in token.findall(expression):
            if value.startswith('"'):
                # Lark has no empty terminal; empty expansion is supported.
                decoded = json.loads(value)
                regex = re.escape(decoded).replace("/", r"\/")
                parts.append("/" + regex + "/" if decoded else "")
            elif value.startswith("["):
                # Lark decodes hex escapes before regex compilation; preserve
                # escaped brackets so JSON scalar ranges remain a single class.
                value = value.replace(r"\x5b", r"\[").replace(r"\x5d", r"\]")
                parts.append("/" + value.replace("/", r"\/") + "/")
            elif value[0].isalpha(): parts.append(value.replace("-", "_"))
            else: parts.append(value)
        lines.append(name.replace("-", "_") + ": " + " ".join(parts))
    return Lark("\n".join(lines), start="root", parser="earley")


def canonical(value):
    """Contract property order plus canonical enum/evidence list order."""
    flags = ["attribution", "condition", "exception", "limit", "current_court_response", "cross_block_context"]
    if isinstance(value, list): return [canonical(v) for v in value]
    if not isinstance(value, dict): return value
    result = {}
    for key, child in value.items():
        if key in {"needs_context", "needed_context"}:
            child = sorted(child, key=lambda flag: flags.index(flag) if flag in flags else len(flags))
        elif key == "evidence_ref_ids": child = sorted(child)
        result[key] = canonical(child)
    return result


def ordered_output(output):
    # Reorder objects according to schema declaration, irrespective of fixture
    # construction order. This doesn't alter accepted host contract semantics.
    from knowledge_base.pipeline_v1.repair_agent.core import CONTRACTS, load
    def order(value, schema):
        if "oneOf" in schema:
            variants = schema["oneOf"]
            for variant in variants:
                props = variant.get("properties", {})
                if all(value.get(k) == v["const"] for k, v in props.items() if "const" in v):
                    schema = variant; break
        if isinstance(value, dict):
            props = schema.get("properties", {})
            keys = list(props) + [k for k in value if k not in props]
            return {k: order(value[k], props.get(k, {})) for k in keys if k in value}
        if isinstance(value, list): return [order(v, schema.get("items", {})) for v in value]
        return value
    return canonical(order(output, load(CONTRACTS / "repair_wire.v2.json")))


class CompilerChecks(unittest.TestCase):
    def test_unknown_constraints_fail_closed(self):
        for schema in ({"type": "string", "pattern": "x"},
                       {"type": "integer", "minimum": 2},
                       {"type": "integer"},
                       {"type": "string", "properties": {}},
                       {"oneOf": [{"type": "string"}, {"type": "string"}]},
                       {"oneOf": [{"const": "x"}], "maxLength": 1},
                       {"type": "object", "additionalProperties": False,
                        "allOf": [{"if": {}, "then": {}}]},
                       {"type": "array", "maxItems": 3, "uniqueItems": True,
                        "items": {"type": "string"}}):
            with self.subTest(schema=schema), self.assertRaises(ValueError): Compiler().compile(schema)

    def test_growth_linear_evidence_shared_string_bounds(self):
        counts = []
        for count in (1, 10, 100):
            grammar = decoding(synthetic_task(), "R1", 1, [f"a{i:03}" for i in range(count)])["ebnf"]
            counts.append(len(grammar.splitlines()))
            self.assertNotIn("json-char{", grammar)
        self.assertLess(counts[2] - counts[1], 12 * (100 - 10))
        self.assertLess(counts[2], 1800)


@unittest.skipIf(Lark is None, "Lark absent; run existing Python310 for grammar acceptance")
class GrammarAcceptance(unittest.TestCase):
    def accepts(self, grammar_parser, value, expected):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        try: grammar_parser.parse(text); accepted = True
        except Exception: accepted = False
        self.assertEqual(expected, accepted, text[:180])

    def test_all_formal_fixtures_and_explicit_host_guards(self):
        host_only = {"unique_witnesses", "offset_outside_end", "offset_reversed",
                     "offset_wrong_quote", "supported_wrong_quote"}
        parsers = {}
        for fixture in fixtures():
            key = (len(fixture["task"]["original_proposals"]), fixture["arm"], fixture["turn"])
            if key not in parsers:
                parsers[key] = parser(decoding(fixture["task"], fixture["arm"], fixture["turn"], ["a"])["ebnf"])
            with self.subTest(case=fixture["case_id"]):
                self.accepts(parsers[key], ordered_output(fixture["output"]),
                             fixture["expected_valid"] or fixture["case_id"] in host_only)

    def test_decoded_unicode_length_and_valid_json_scalars(self):
        p = parser(Compiler().compile({"type": "string", "minLength": 1, "maxLength": 2}))
        for value in ('""', '"abc"', '"\\ud800"', '"\\udc00"', '"\\x20"', '"\n"', '"\\ud800X\\udc00"'):
            self.accepts(p, value, False)
        for value in ('"\\ud83d\\ude00"', '"\\ud83d\\ude00x"', '"😀x"', '"\\u0061\\n"', '"é"', '"\\\\"', '"\\\""'):
            self.accepts(p, value, True)
        self.accepts(p, '"\\ud83d\\ude00xy"', False)

    def test_optional_before_required_all_comma_states(self):
        p = parser(Compiler().compile({"type": "object", "additionalProperties": False,
            "required": ["b"], "properties": {"a": {"const": 1}, "b": {"const": 2}, "c": {"const": 3}}}))
        for value in ({"b": 2}, {"a": 1, "b": 2}, {"b": 2, "c": 3}, {"a": 1, "b": 2, "c": 3}):
            self.accepts(p, value, True)
        for value in ('{,"b":2}', '{"b":2,}', '{"a":1"b":2}', '{"a":1}', '{}'):
            self.accepts(p, value, False)

    def test_unique_suffix_states_all_subsets_and_bounds(self):
        import itertools
        p = parser(Compiler().compile({"type": "array", "minItems": 1, "maxItems": 3,
                                      "uniqueItems": True, "items": {"enum": ["a", "b", "c", "d"]}}))
        for count in range(1, 4):
            for values in itertools.combinations(["a", "b", "c", "d"], count): self.accepts(p, list(values), True)
        for values in ([], ["a", "a"], ["b", "a"], ["a", "b", "c", "d"], ["foreign"]): self.accepts(p, values, False)

    def test_forced_probe_branches_and_call_lock(self):
        t = synthetic_task()
        for verdict, action in (("supported", None), ("uncertain", None), ("defect_found", "reject"), ("defect_found", "replace")):
            p = parser(decoding(t, "R1", 1, ["a"], forced_verdict=verdict, forced_action=action)["ebnf"])
            for candidate in ("supported", "uncertain", "defect_found"):
                self.accepts(p, ordered_output(envelope(t, candidate, action or "reject")), candidate == verdict)
        for arm, turn in (("R1", 1), ("R2", 2)):
            p = parser(decoding(t, arm, turn, ["a"])["ebnf"])
            self.accepts(p, {"tool_calls": [{"name": "get_repair_task", "arguments": {}}]}, False)


if __name__ == "__main__": unittest.main()
