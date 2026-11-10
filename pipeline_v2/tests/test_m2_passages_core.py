import json
from pathlib import Path
import unittest

from pipeline_v2.passages import PinnedTokenizer, PassageError, split_text, build_case_passages
from pipeline_v2.navigation.core import build_case_navigation
from pipeline_v2.source.core import parse_source

ROOT = Path(__file__).resolve().parents[2]
PROFILE = json.loads((ROOT/"pipeline_v2/configs/m2_passages.json").read_text())


class PassageCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = PinnedTokenizer(ROOT,PROFILE["tokenizer_lock"])

    def check_slices(self,text,profile=PROFILE):
        parts = split_text(text,self.tok,profile)
        self.assertEqual(parts[0]["start"],0)
        self.assertEqual(parts[-1]["end"],len(text))
        covered = 0
        for p in parts:
            self.assertLessEqual(p["start"],covered)
            self.assertGreater(p["end"],covered)
            self.assertEqual(p["token_count"],self.tok.count(text[p["start"]:p["end"]]))
            self.assertLessEqual(p["token_count"],profile["max_input_tokens"])
            self.assertLessEqual(p["overlap_tokens"],profile["overlap_tokens"])
            covered=p["end"]
        return parts

    def test_fitting_parent_above_target_stays_intact(self):
        text="word "*400
        self.assertTrue(320<self.tok.count(text)<=448)
        self.assertEqual(len(self.check_slices(text)),1)

    def test_long_unicode_whitespace_special_tokens_roundtrip(self):
        for text in ["  word\r\n"*1000, "\u00e9\u6cd5\U0001f9d1\u200d\u2696\ufe0f "*400,
                     "A"*9000,"\r\n\t "*3000, "<|endoftext|> literal <|im_start|> "*500]:
            with self.subTest(prefix=repr(text[:20])):
                self.check_slices(text)

    def test_invalid_profile_and_impossible_codepoint_rejected(self):
        with self.assertRaises(PassageError):
            split_text("abc",self.tok,{**PROFILE,"overlap_tokens":320})
        with self.assertRaises(PassageError):
            split_text("\U0001f9d1"*100,self.tok,{**PROFILE,"target_tokens":1,"overlap_tokens":0,"max_input_tokens":1})

    def test_special_token_overhead_is_measured(self):
        self.assertEqual(self.tok.count("hello"),self.tok.count_content("hello")+1)
        self.assertEqual(self.tok.backend.encode("hello",add_special_tokens=True).ids[-1],151643)

    def test_all_parents_repeated_markers_unknown_quoted_and_french_kept(self):
        raw=("[12] " + "word "*900 + "\r\n[2] The Court states the following:\r\n"
             "[12] Quoted \u00e9l\u00e9ment.\r\n[1] \u00c9nonc\u00e9 fran\u00e7ais.\r\n").encode()
        nav_profile=json.loads((ROOT/"pipeline_v2/configs/m2.json").read_text())
        nav=build_case_navigation("123456.txt",raw,parse_source("123456.txt",raw),nav_profile)
        result=build_case_passages("123456.txt",raw,nav,PROFILE,self.tok)
        self.assertEqual(len(result["parents"]),len(nav["navigation"]))
        self.assertGreater(len(result["passages"]),len(result["parents"]))
        for p in result["passages"]:
            self.assertEqual(raw[slice(*p["span_bytes"])].decode(),p["text"])
            parent=next(n for n in nav["navigation"] if n["handle"]==p["parent_handle"])
            self.assertEqual(p["reading_expansion"],parent["reading_expansion"])
            self.assertEqual(p["paragraph_role"],parent["paragraph_role"])
        self.assertEqual(result,build_case_passages("123456.txt",raw,nav,PROFILE,self.tok))


if __name__=="__main__":
    unittest.main()
