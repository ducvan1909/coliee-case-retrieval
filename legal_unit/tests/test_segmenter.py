from __future__ import annotations

import unittest

from legal_unit.segmenter import analyze_case, segment_case
from legal_unit.validation import validate_candidates


class SegmenterTests(unittest.TestCase):
    def test_preserves_unicode_marker_and_windows_offsets(self) -> None:
        text = "I.\r\nRésumé <FRAGMENT_SUPPRESSED> tiếp tục\r\n[1]\r\nNội dung.\r\n\r\n- First\r\n  wrapped line\r\n"
        units = segment_case("case.txt", text, "fixture")
        self.assertEqual([], validate_candidates(text, units, "case.txt"))
        self.assertNotIn("text", units[0]["source_span"])
        self.assertEqual(text[units[0]["source_span"]["start_char"] : units[0]["source_span"]["end_char"]], units[0]["text"])
        self.assertTrue(any("FRAGMENT_SUPPRESSED" in unit["text"] for unit in units))

    def test_long_unbroken_paragraph_remains_one_structural_candidate(self) -> None:
        text = "A sentence.\nThis wrapped line must remain with the same paragraph. " + "word " * 3000
        units = segment_case("long.txt", text, "fixture")
        self.assertEqual(1, len(units))
        self.assertEqual([], validate_candidates(text, units, "long.txt"))

    def test_quote_line_stays_in_paragraph_but_each_bullet_starts_a_block(self) -> None:
        text = "Court analysis.\n\"Quoted authority.\"\n- First item\n  continued\n- Second item"
        units = segment_case("structure.txt", text, "fixture")
        self.assertEqual(3, len(units))
        self.assertIn('Court analysis.\n"Quoted authority."', units[0]["text"])
        self.assertEqual([], validate_candidates(text, units, "structure.txt"))

    def test_paragraph_marker_is_a_boundary_and_heading_stays_with_paragraph(self) -> None:
        text = "Prior paragraph.\r\nBackground\r\n[2]\r\nFacts here.\r\n[3]\r\nMore facts."
        units = segment_case("paragraphs.txt", text, "fixture")
        self.assertEqual(["Prior paragraph.", "Background\r\n[2]\r\nFacts here.", "[3]\r\nMore facts."], [unit["text"] for unit in units])
        self.assertEqual([], validate_candidates(text, units, "paragraphs.txt"))

    def test_citation_year_is_not_a_paragraph_marker(self) -> None:
        text = "Authority:\r\n[1987] 1 S.C.R. 313, [1987] S.C.J. No. 10.\r\n[9]\r\nCourt analysis."
        units = segment_case("citation.txt", text, "fixture")
        self.assertEqual(2, len(units))
        self.assertIn("[1987] 1 S.C.R.", units[0]["text"])

    def test_acronym_and_wrapped_legal_name_stay_inside_sentence(self) -> None:
        text = 'Relief is requested under section 25 of\r\nIRPA\r\n. The "\r\nElection Law\r\n") respecting candidates.\r\n[2]\r\nNext paragraph.'
        units = segment_case("acronym.txt", text, "fixture")
        self.assertEqual(2, len(units))
        self.assertIn("section 25 of\r\nIRPA", units[0]["text"])
        self.assertIn('Election Law\r\n") respecting', units[0]["text"])

    def test_case_word_is_not_treated_as_an_alpha_list_marker(self) -> None:
        text = "The result in\r\nSimon Fraser\r\ncase. Both complaints were dismissed.\r\n[2]\r\nNext."
        units = segment_case("case-name.txt", text, "fixture")
        self.assertIn("Simon Fraser\r\ncase.", units[0]["text"])

    def test_enumerated_items_need_list_context_and_keep_wrapped_lines(self) -> None:
        text = "The requirements are:\r\n(a) First item\r\ncontinued text\r\n(b) Second item\r\ncontinued again"
        units = segment_case("list.txt", text, "fixture")
        self.assertEqual(3, len(units))
        self.assertEqual("(a) First item\r\ncontinued text", units[1]["text"])

    def test_metadata_footnote_and_end_document_start_separate_blocks(self) -> None:
        text = "[6]\r\nApplication dismissed.\r\nEditor: Jane Doe\r\nFootnotes\r\n1 Source note.\r\n[End of document]"
        units = segment_case("metadata.txt", text, "fixture")
        self.assertEqual(4, len(units))
        self.assertEqual("Editor: Jane Doe", units[1]["text"])
        self.assertTrue(units[2]["text"].startswith("Footnotes"))
        self.assertEqual("[End of document]", units[3]["text"])

    def test_blockquote_lines_form_one_block(self) -> None:
        text = "Analysis.\n> first quoted line\n> second quoted line\nCourt resumes."
        units = segment_case("blockquote.txt", text, "fixture")
        self.assertEqual(["Analysis.", "> first quoted line\n> second quoted line", "Court resumes."], [unit["text"] for unit in units])

    def test_analysis_api_records_every_line_gap_and_defers_conflict(self) -> None:
        text = "4. Is the rule in the\r\nElection Law\r\nto give written reasons?\r\n[14]\r\nThe provisions follow."
        units, decisions = analyze_case("decision.txt", text, "fixture")
        self.assertEqual(len(text.splitlines()) - 1, len(decisions))
        deferred = [item for item in decisions if item["decision"] == "defer"]
        self.assertTrue(deferred)
        self.assertIn("Election Law\r\nto give written reasons?", units[0]["text"])
        self.assertTrue(units[1]["text"].startswith("[14]"))

    def test_confirmed_multiline_heading_moves_as_one_block(self) -> None:
        text = "Prior conclusion.\r\nVI.\r\nAre the Measures\r\nUltra Vires\r\nthe Council?\r\n[20]\r\nAnalysis begins."
        units, decisions = analyze_case("heading.txt", text, "fixture")
        self.assertEqual(2, len(units))
        self.assertEqual("Prior conclusion.", units[0]["text"])
        self.assertTrue(units[1]["text"].startswith("VI.\r\nAre the Measures"))
        self.assertIn("[20]\r\nAnalysis begins.", units[1]["text"])
        self.assertTrue(any(item["decision"] == "split" and "heading" in item["reason"] for item in decisions))

    def test_generic_suffixes_remain_with_preceding_grammar(self) -> None:
        text = (
            "The source is\r\nA Treatise on Remedies\r\n, 4th Ed.\r\n"
            'Product: MEDICINE compound\r\n(hereinafter "MEDICINE")\r\n'
            'The quoted sentence\r\n." (Emphasis added.)\r\n[8]\r\nNext paragraph.'
        )
        units = segment_case("suffixes.txt", text, "fixture")
        self.assertEqual(2, len(units))
        self.assertIn("A Treatise on Remedies\r\n, 4th Ed.", units[0]["text"])
        self.assertIn('Product: MEDICINE compound\r\n(hereinafter "MEDICINE")', units[0]["text"])
        self.assertTrue(units[1]["text"].startswith("[8]"))

    def test_wrapped_terminal_punctuation_can_confirm_a_heading(self) -> None:
        for punctuation in ("?", ".", ")."):
            with self.subTest(punctuation=punctuation):
                text = f"A completed question under the Act\r\n{punctuation}\r\nSTANDARD OF REVIEW\r\n[2]\r\nAnalysis."
                units = segment_case("terminal.txt", text, "fixture")
                self.assertTrue(units[1]["text"].startswith("STANDARD OF REVIEW\r\n[2]"))

    def test_wrapped_case_connector_and_period_remain_a_continuation(self) -> None:
        text = "The court followed Smith\r\nv\r\n.\r\nCanada\r\n, 2000 SCC 1.\r\n[2]\r\nAnalysis."
        units = segment_case("citation-wrap.txt", text, "fixture")
        self.assertEqual(2, len(units))
        self.assertIn("Smith\r\nv\r\n.\r\nCanada\r\n, 2000 SCC 1.", units[0]["text"])

    def test_ordered_section_labels_move_with_heading_and_paragraph(self) -> None:
        text = (
            "Prior conclusion.\r\n(a)\r\nFirst Objective\r\n[2]\r\nFirst analysis.\r\n"
            "(b)\r\nSecond Objective\r\n[3]\r\nSecond analysis.\r\n"
            "(c)\r\nThird Objective\r\n[4]\r\nThird analysis."
        )
        units = segment_case("labelled-headings.txt", text, "fixture")
        starts = [unit["text"] for unit in units]
        self.assertTrue(any(value.startswith("(a)\r\nFirst Objective\r\n[2]") for value in starts))
        self.assertTrue(any(value.startswith("(b)\r\nSecond Objective\r\n[3]") for value in starts))
        self.assertTrue(any(value.startswith("(c)\r\nThird Objective\r\n[4]") for value in starts))

    def test_isolated_section_label_does_not_confirm_a_heading(self) -> None:
        text = "The choices include (a) in a sentence.\r\n(a)\r\nPossible Label\r\n[2]\r\nAnalysis."
        units, decisions = analyze_case("isolated-label.txt", text, "fixture")
        self.assertFalse(any(unit["text"].startswith("(a)\r\nPossible Label") for unit in units))
        label_offset = text.index("(a)\r\nPossible Label")
        decision = next(item for item in decisions if item["offset"] == label_offset)
        self.assertNotEqual("split", decision["decision"])
