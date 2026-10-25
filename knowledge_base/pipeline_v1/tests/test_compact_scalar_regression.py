"""Regression checks for JSON scalar handling in compact claim strings.

Lark is an optional grammar-level check. The XGrammar check uses the isolated
0.2.1 runtime and tokenizer diagnostic artifacts when those dependencies exist.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
import unittest
from importlib.metadata import PathDistribution
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC_ROOT = PIPELINE_ROOT / "outputs" / "grammar_diagnostic_deps"
_DECODING_PATH = PIPELINE_ROOT / "au_compact" / "decoding.py"
_DECODING_SPEC = importlib.util.spec_from_file_location(
    "_compact_scalar_regression_decoding", _DECODING_PATH
)
_DECODING_MODULE = importlib.util.module_from_spec(_DECODING_SPEC)
_DECODING_SPEC.loader.exec_module(_DECODING_MODULE)
build_decoding = _DECODING_MODULE.build_decoding
TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"|\[(?:\\.|[^\]\\])*\]|'
    r'[A-Za-z][A-Za-z0-9-]*|\{\d+,\d+\}|::=|[|()]'
)


def _lark_grammar(ebnf: str) -> str:
    """Translate emitted EBNF syntax to Lark while preserving terminals."""
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
                token = "/" + token.replace("/", r"\/").replace(
                    r"\x5b", r"\["
                ).replace(r"\x5d", r"\]") + "/"
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


def _payload(raw_claim: str) -> str:
    return (
        '{"request_id":"r","target_id":"t","decision":"positive",'
        '"coverage_status":"complete","aus":[{"kind":"holding",'
        '"other_kind":null,"claim":"' + raw_claim +
        '","evidence_ref_ids":["a"],"speaker":"current_court",'
        '"attribution_role":"proposition","needs_context":[]}],'
        '"hard_negative_reason":null,"unresolved_reason":null}'
    )


class CompactScalarLarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            lark = importlib.import_module("lark")
        except ImportError:
            raise unittest.SkipTest("optional lark unavailable")
        grammar = build_decoding("r", "t", ["a"], ["a"])["ebnf"]
        cls.lark = lark
        cls.parser = lark.Lark(
            _lark_grammar(grammar), start="root", parser="earley",
            lexer="dynamic_complete",
        )

    def assert_accepted(self, raw_claim: str):
        self.parser.parse(_payload(raw_claim))

    def assert_rejected(self, raw_claim: str):
        with self.assertRaises(self.lark.exceptions.UnexpectedInput):
            self.parser.parse(_payload(raw_claim))

    def test_ascii_and_unicode_scalar_text_are_accepted(self):
        self.assert_accepted("Ordinary claim: Rule 12.")
        self.assert_accepted("Tiếng Việt — café — 😀")

    def test_json_escapes_are_accepted_but_raw_quote_backslash_and_controls_are_not(self):
        self.assert_accepted(r'escaped quote: \" and slash: \\ and controls: \n\t\b')
        self.assert_rejected('raw " quote')
        self.assert_rejected("raw \\ backslash")
        self.assert_rejected("raw\ncontrol")
        self.assert_rejected("raw\x00control")

    def test_surrogate_pair_escape_is_accepted_but_lone_surrogates_are_rejected(self):
        self.assert_accepted(r"supplementary character: \uD83D\uDE00")
        self.assert_rejected(r"lone high surrogate: \uD83D")
        self.assert_rejected(r"lone low surrogate: \uDE00")


class CompactScalarXGrammarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pinned = DIAGNOSTIC_ROOT / "pinned"
        runtime = DIAGNOSTIC_ROOT / "runtime"
        tokenizer_path = DIAGNOSTIC_ROOT / "tokenizer.json"
        if not (pinned / "xgrammar").is_dir() or not runtime.is_dir() or not tokenizer_path.is_file():
            raise unittest.SkipTest("isolated XGrammar 0.2.1 runtime or tokenizer artifact unavailable")

        # The diagnostic bundles dependencies without installing them into the
        # project environment. Put the pinned backend before its support runtime.
        sys.path[:0] = [str(pinned), str(runtime)]
        try:
            xgrammar = importlib.import_module("xgrammar")
            if not Path(xgrammar.__file__).resolve().is_relative_to(pinned.resolve()):
                raise unittest.SkipTest("XGrammar did not load from the pinned diagnostic directory")
            version = PathDistribution(
                pinned / "xgrammar-0.2.1.dist-info"
            ).version
            if version != "0.2.1":
                raise unittest.SkipTest(f"pinned XGrammar 0.2.1 required; loaded {version!r}")
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
        except ImportError as exc:
            raise unittest.SkipTest(f"optional pinned XGrammar dependencies unavailable: {exc}")

        tokenizer = transformers.PreTrainedTokenizerFast(tokenizer_file=str(tokenizer_path))
        stop_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
        tokenizer_info = xgrammar.TokenizerInfo.from_huggingface(
            tokenizer, stop_token_ids=[stop_id]
        )
        compiler = xgrammar.GrammarCompiler(tokenizer_info, max_threads=1)
        grammar = xgrammar.Grammar.from_ebnf(
            build_decoding("r", "t", ["a"], ["a"])["ebnf"]
        )
        cls.xgrammar = xgrammar
        cls.torch = torch
        cls.tokenizer = tokenizer
        cls.tokenizer_info = tokenizer_info
        cls.compiled = compiler.compile_grammar(grammar)

    def test_qwen_token_mask_allows_claim_text_and_closing_quote(self):
        matcher = self.xgrammar.GrammarMatcher(self.compiled)
        prefix = (
            '{"request_id":"r","target_id":"t","decision":"positive",'
            '"coverage_status":"complete","aus":[{"kind":"holding",'
            '"other_kind":null,"claim":"'
        )
        self.assertTrue(matcher.accept_string(prefix))

        claim = "The Court finds Tiếng Việt 😀."
        token_ids = self.tokenizer.encode(claim, add_special_tokens=False)
        self.assertTrue(token_ids, "claim should tokenize to ordinary Qwen tokens")
        for token_id in token_ids:
            mask = self.xgrammar.allocate_token_bitmask(
                1, self.tokenizer_info.vocab_size
            )
            matcher.fill_next_token_bitmask(mask)
            logits = self.torch.zeros((1, self.tokenizer_info.vocab_size))
            self.xgrammar.apply_token_bitmask_inplace(logits, mask)
            self.assertTrue(
                bool(self.torch.isfinite(logits[0, token_id])),
                f"XGrammar 0.2.1 masked ordinary claim token {token_id}",
            )
            self.assertTrue(matcher.accept_token(token_id))

        mask = self.xgrammar.allocate_token_bitmask(1, self.tokenizer_info.vocab_size)
        matcher.fill_next_token_bitmask(mask)
        logits = self.torch.zeros((1, self.tokenizer_info.vocab_size))
        self.xgrammar.apply_token_bitmask_inplace(logits, mask)
        quote_id = self.tokenizer.encode('"', add_special_tokens=False)[0]
        self.assertTrue(
            bool(self.torch.isfinite(logits[0, quote_id])),
            "the claim-closing quote must remain available after ordinary text",
        )


if __name__ == "__main__":
    unittest.main()
