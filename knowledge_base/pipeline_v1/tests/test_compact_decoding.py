"""Local checks of emitted EBNF; no inference or deployment is performed."""
import copy
import itertools
import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from knowledge_base.pipeline_v1.au_compact.decoding import build_decoding

try:
    import lark
except ImportError:
    lark = None
try:
    import xgrammar
except ImportError:
    xgrammar = None


SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts" /
                     "compact_au_model_output.v1.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
FLAGS = SCHEMA["$defs"]["au"]["properties"]["needs_context"]["items"]["enum"]
ATOMS = ["a", "b", "c", "d", "e"]
TARGETS = {"b", "d"}
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\[(?:\\.|[^\]\\])*\]|'
                   r'[A-Za-z][A-Za-z0-9-]*|\{\d+,\d+\}|::=|[|()+]')


def lark_grammar(ebnf):
    """Translate syntax only; preserve terminals, classes, and bounded lengths."""
    lines = []
    for line in ebnf.splitlines():
        parts = []
        previous_end = 0
        for match in TOKEN.finditer(line):
            if line[previous_end:match.start()].strip():
                raise AssertionError("Unrecognized EBNF syntax")
            token = match.group()
            if token == "::=":
                token = ":"
            elif token.startswith('"'):
                if json.loads(token) == "":
                    token = ""
            elif token.startswith("["):
                # Lark expands hex escapes before compiling regexes; an
                # expanded closing bracket would terminate this class.
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


def positive():
    # Dict insertion order is the hard grammar's canonical key order.
    return {"request_id": "r-1", "target_id": "t-1", "decision": "positive",
            "coverage_status": "complete", "aus": [
                {"kind": "holding", "other_kind": None, "claim": "Rule.",
                 "evidence_ref_ids": ["b"], "speaker": "current_court",
                 "attribution_role": "proposition", "needs_context": []}],
            "hard_negative_reason": None, "unresolved_reason": None}


def dumps(value, **kwargs):
    return json.dumps(value, separators=(",", ":"), **kwargs)


class DecodingGenerationTests(unittest.TestCase):
    def test_exact_payload_and_deterministic_sanitization(self):
        actual = build_decoding("r-1", "t-1", reversed(ATOMS + ["b"]), ["d", "b", "b"])
        self.assertEqual(set(actual), {"ebnf"})
        self.assertEqual(actual, build_decoding("r-1", "t-1", ATOMS, TARGETS))
        self.assertTrue(actual["ebnf"].startswith("root ::="))
        self.assertNotIn("response_format", actual)

    def test_bad_input_fails_closed(self):
        for field in range(4):
            invalid = [None, "", "x" * 129, 1, "\ud800"] if field < 2 else [None, [], "b", [None], [""], ["x" * 129], ["\ud800"]]
            for value in invalid:
                args = ["r", "t", ATOMS, TARGETS]
                args[field] = value
                with self.subTest(field=field, value=repr(value)), self.assertRaises(ValueError):
                    build_decoding(*args)
        with self.assertRaises(ValueError):
            build_decoding("r", "t", ATOMS, ["missing"])
        build_decoding("r" * 128, "t" * 128, ["a" * 128], ["a" * 128])

    def test_linear_states_and_defined_references(self):
        for size in (1, 10, 100, 1000):
            ids = [f"a-{index:04}" for index in range(size)]
            grammar = build_decoding("r", "t", ids, [ids[-1]])["ebnf"]
            definitions = {line.split(" ::= ")[0] for line in grammar.splitlines()}
            self.assertLessEqual(sum(name.startswith("ev-") for name in definitions), (size + 1) * 4 * 2)
            self.assertLess(len(grammar), 1800 * size + 8000)
            for line in grammar.splitlines():
                rhs = line.split(" ::= ")[1]
                self.assertTrue(rhs.strip())
                refs = [token for token in TOKEN.findall(rhs) if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", token)]
                self.assertTrue(set(refs) <= definitions)
            self.assertEqual(len(definitions), len(grammar.splitlines()))

    @unittest.skipUnless(xgrammar, "xgrammar unavailable: actual backend compilation unverified")
    def test_xgrammar_compile(self):
        grammar = xgrammar.Grammar.from_ebnf(build_decoding("r", "t", ATOMS, TARGETS)["ebnf"])
        tokenizer_info = xgrammar.TokenizerInfo(
            [chr(code) for code in range(32, 127)] + ["<eos>"],
            stop_token_ids=[95],
        )
        xgrammar.GrammarCompiler(tokenizer_info, max_threads=1).compile_grammar(grammar)


@unittest.skipUnless(lark, "optional lark unavailable: run with system Python for acceptance tests")
class DecodingAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = lark.Lark(lark_grammar(build_decoding("r-1", "t-1", ATOMS, TARGETS)["ebnf"]),
                               start="root", parser="earley", lexer="dynamic_complete")

    def accepts(self, value, expected=True, raw=None, schema_valid=None):
        if schema_valid is None:
            schema_valid = expected
        self.assertEqual(VALIDATOR.is_valid(value), schema_valid)
        try:
            self.parser.parse(dumps(value) if raw is None else raw)
            accepted = True
        except lark.exceptions.UnexpectedInput:
            accepted = False
        self.assertEqual(accepted, expected, repr(raw if raw is not None else value))

    def test_all_branches_and_three_aus(self):
        value = positive()
        self.accepts(value)
        value["aus"] = [copy.deepcopy(value["aus"][0]) for _ in range(3)]
        value["aus"][1].update(kind="other", other_kind="A category", evidence_ref_ids=["a", "b", "e"], needs_context=FLAGS)
        value["aus"][2].update(evidence_ref_ids=["c", "d"], needs_context=["condition", "limit"])
        value["coverage_status"] = "needs_split"
        self.accepts(value)
        for decision, reason_key in [("hard_negative", "hard_negative_reason"), ("unresolved", "unresolved_reason")]:
            for reason in SCHEMA["properties"][reason_key]["enum"]:
                if reason is None:
                    continue
                for coverage in (["complete"] if decision == "hard_negative" else ["complete", "needs_split"]):
                    value = positive()
                    value.update(decision=decision, coverage_status=coverage, aus=[])
                    value[reason_key] = reason
                    self.accepts(value)

    def test_all_au_enums(self):
        for field in ("kind", "speaker", "attribution_role"):
            for item in SCHEMA["$defs"]["au"]["properties"][field]["enum"]:
                value = positive()
                value["aus"][0][field] = item
                if item == "other" and field == "kind":
                    value["aus"][0]["other_kind"] = "Other label"
                self.accepts(value)
            value["aus"][0][field] = "INVALID"
            self.accepts(value, False)

    def test_every_canonical_context_subset(self):
        for count in range(7):
            for subset in itertools.combinations(FLAGS, count):
                value = positive()
                value["aus"][0]["needs_context"] = list(subset)
                self.accepts(value)
        for flags, valid_schema in [(["condition", "condition"], False), (["limit", "condition"], True), (["unknown"], False)]:
            value["aus"][0]["needs_context"] = flags
            self.accepts(value, False, schema_valid=valid_schema)

    def test_every_small_catalog_evidence_sequence(self):
        for count in (1, 2, 3):
            for ids in itertools.product(ATOMS, repeat=count):
                value = positive()
                value["aus"][0]["evidence_ref_ids"] = list(ids)
                valid_schema = len(set(ids)) == len(ids)
                canonical = valid_schema and list(ids) == sorted(ids) and bool(set(ids) & TARGETS)
                self.accepts(value, canonical, schema_valid=valid_schema)
        for ids, valid_schema in [([], False), (["missing"], True), (["a", "b", "c", "d"], False)]:
            value["aus"][0]["evidence_ref_ids"] = ids
            self.accepts(value, False, schema_valid=valid_schema)

    def test_branch_and_au_constraints(self):
        mutations = [
            {"aus": []}, {"aus": positive()["aus"] * 4},
            {"hard_negative_reason": "other"}, {"unresolved_reason": "other"},
            {"decision": "hard_negative"}, {"decision": "unresolved"},
            {"decision": "hard_negative", "aus": [], "hard_negative_reason": "other", "coverage_status": "needs_split"},
            {"decision": "unresolved", "aus": [], "unresolved_reason": "other", "hard_negative_reason": "other"},
            {"coverage_status": "unknown"},
        ]
        for mutation in mutations:
            value = positive()
            value.update(mutation)
            self.accepts(value, False)
        for mutation in [{"kind": "other"}, {"kind": "other", "other_kind": ""},
                         {"other_kind": "label"}, {"kind": "other", "other_kind": "x" * 161},
                         {"claim": ""}, {"claim": "x" * 301}]:
            value = positive()
            value["aus"][0].update(mutation)
            self.accepts(value, False)

    def test_escaped_json_and_decoded_unicode_length(self):
        for text in ['Quote " slash \\ newline\n tab\t control\x00', "Tiếng Việt 😀",
                     "x" * 300, "😀" * 300, "\n" * 300]:
            value = positive()
            value["aus"][0]["claim"] = text
            self.accepts(value)
            self.accepts(value, raw=dumps(value, ensure_ascii=False))
        value = positive()
        value["aus"][0].update(kind="other", other_kind="😀" * 160)
        self.accepts(value)
        for text in ["😀" * 301, "\n" * 301]:
            value = positive()
            value["aus"][0]["claim"] = text
            self.accepts(value, False)
        value = positive()
        value["aus"][0]["claim"] = "a" * 300
        # Each escaped codepoint must count as one, not six serialized bytes.
        raw = dumps(value).replace('"' + "a" * 300 + '"', '"' + r"\u0061" * 300 + '"')
        self.accepts(value, raw=raw)
        raw = raw.replace(r"\u0061" * 300, r"\u0061" * 301)
        self.accepts(json.loads(raw), False, raw=raw)

    def test_locked_identity_injection_and_format(self):
        for field in ("request_id", "target_id"):
            value = positive()
            value[field] = "wrong"
            self.accepts(value, False, schema_valid=True)
        value = positive()
        raw = dumps(value)
        for invalid in [" " + raw, raw + "\n", raw.replace(",", ", ", 1), raw.replace(":", ": ", 1),
                        dumps(dict(reversed(list(value.items())))), raw.replace("Rule.", r"\q"),
                        raw.replace("Rule.", "raw\ncontrol"), raw.replace("Rule.", r"\ud800")]:
            self.accepts(value, False, raw=invalid, schema_valid=True)
        value["aus"][0]["extra"] = True
        self.accepts(value, False)
        for identity in ['r"\\\n ::= root', "yêu cầu😀"]:
            grammar = build_decoding(identity, identity, [identity], [identity])["ebnf"]
            parser = lark.Lark(lark_grammar(grammar), start="root", parser="earley")
            value = positive()
            value.update(request_id=identity, target_id=identity)
            value["aus"][0]["evidence_ref_ids"] = [identity]
            VALIDATOR.validate(value)
            parser.parse(dumps(value))


if __name__ == "__main__":
    unittest.main()
