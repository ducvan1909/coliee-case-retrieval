from __future__ import annotations

from pathlib import Path
import unittest

from legal_unit.segmenter import segment_case
from legal_unit.validation import validate_candidates


SAMPLES = Path(__file__).parents[2] / "legal_unit" / "samples" / "cases"


class RealBoundaryRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = (
            "000002.txt", "009672.txt", "024310.txt", "024385.txt", "030009.txt",
            "030566.txt", "036344.txt", "041409.txt", "050167.txt", "055641.txt",
            "057341.txt", "065299.txt", "067375.txt",
        )
        if not SAMPLES.is_dir() or any(not (SAMPLES / case_id).is_file() for case_id in required):
            raise unittest.SkipTest("generated LegalUnit pilot samples are not available")

    def units(self, case_id: str):
        source = SAMPLES / case_id
        text = source.read_bytes().decode("utf-8", errors="strict")
        units = segment_case(case_id, text, source.as_posix())
        self.assertEqual([], validate_candidates(text, units, case_id))
        return text, units

    def assert_range_in_one_unit(self, case_id: str, start: int, end: int, expected: str) -> None:
        text, units = self.units(case_id)
        expected_end = start + len(expected)
        self.assertEqual(expected, text[start:expected_end])
        owners = [unit for unit in units if unit["source_span"]["start_char"] <= start and expected_end <= unit["source_span"]["end_char"]]
        self.assertEqual(1, len(owners), f"{case_id}:{start}-{expected_end} was split")

    def test_reported_wrapped_phrases_are_not_split(self) -> None:
        cases = [
            ("030009.txt", 395, 422, 'Election Law\r\n") respecting'),
            ("041409.txt", 421, 440, "section 25 of\r\nIRPA"),
            ("055641.txt", 246872, 246906, 'European Convention\r\n"]. Article 3'),
            ("055641.txt", 278700, 278720, 'parent\r\n": at p. 220'),
            ("055641.txt", 313234, 313253, "Simon Fraser\r\ncase."),
            ("055641.txt", 325374, 325397, 'program\r\n", my emphasis'),
            ("055641.txt", 358605, 358726, 'status changes,\r\neither because he is reclassified or because the Minister grants him landed immigrant status\r\n":\r\nIrshad'),
            ("030009.txt", 5764, 5801, "Election Law\r\nto give written reasons"),
            ("000002.txt", 23463, 23498, 'live with her.\r\n" (Emphasis added.)'),
            ("000002.txt", 32692, 32741, 'members of the KENNE family\r\n;" (Emphasis added.)'),
            ("030566.txt", 8937, 8994, 'if he were to return to his country\r\n." (Emphasis added.)'),
            ("030566.txt", 9585, 9699, 'necessarily mean there is a risk to a given individual\r\n(\r\n <FRAGMENT_SUPPRESSED>'),
            ("055641.txt", 235778, 235855, "Sagharian (Litigation guardian of) v. Ontario (Minister of Education)\r\n, 2008"),
            ("067375.txt", 1450, 1518, 'Product: ZITHROMAX azithromycin dihydrate\r\n(hereinafter "ZITHROMAX")'),
            ("067375.txt", 3089, 3151, 'Product: LIPITOR atorvastatin calcium\r\n(hereinafter "LIPITOR")'),
            ("067375.txt", 4394, 4467, 'product: REBETRON ribavirin/interferon alfa 2-b\r\n(hereinafter "REBETRON")'),
            ("067375.txt", 30616, 30671, "The Interpretation of Legislation in Canada\r\n, 3rd. Ed."),
            ("050167.txt", 54024, 54068, 'commonly used in the trade\r\n." (My emphasis)'),
            ("050167.txt", 80553, 80661, "conduct complained of those of the directing minds: see\r\n <FRAGMENT_SUPPRESSED>"),
            ("057341.txt", 11376, 11453, 'This is consistent with\r\n <FRAGMENT_SUPPRESSED>  (F.C.T.D.)."'),
        ]
        for case_id, start, end, expected in cases:
            with self.subTest(case_id=case_id, start=start):
                self.assert_range_in_one_unit(case_id, start, end, expected)

    def test_reported_multiline_headings_attach_forward(self) -> None:
        expected_starts = {
            "024385.txt": "FACTS\r\nBackground\r\n[2]",
            "041409.txt": "Analysis\r\nDid the Officer properly consider the best interests of the children?\r\n[20]",
            "065299.txt": "DISCUSSION\r\n1.\r\nStandard of Review\r\n[7]",
            "009672.txt": "The Appraisals\r\nThe plaintiffs\r\n[55]",
            "055641.txt": "VI.\r\nAre the 2012 OICs\r\nUltra Vires\r\nthe Governor in Council?\r\n[354]",
        }
        for case_id, expected in expected_starts.items():
            with self.subTest(case_id=case_id):
                _, units = self.units(case_id)
                self.assertTrue(any(unit["text"].startswith(expected) for unit in units))

    def test_v51_heading_regressions_attach_forward_by_source_offset(self) -> None:
        expected = {
            "024385.txt": [(9425, "STANDARD OF REVIEW\r\n[13]")],
            "036344.txt": [(433, "FACTS\r\n[2]"), (22095, "CONCLUSION\r\n[40]")],
            "041409.txt": [(445, "Background\r\n[2]")],
            "055641.txt": [
                (70835, "(a)\r\nThe Frailties in the Applicants' Non-expert Evidence\r\n[158]"),
                (76822, "(b)\r\nMr. Ayubi's Experience\r\n[174]"),
                (85645, "(c)\r\nMr. Garcia Rodrigues' Experience\r\n[198]"),
                (91310, "(d)\r\nSaleem Akhtar\r\n[215]"),
                (93497, "(e)\r\nVictor Pathiyage Wijenaike\r\n[221]"),
                (96831, "(f)\r\nRosa Maria Aylas Marcos de Arroyo\r\n[229]"),
                (386609, "(a)\r\nCost Containment\r\n[944]"),
                (387758, "(b)\r\nFairness to Canadians\r\n[946]"),
                (390138, "(c)\r\nProtecting Public Health and Safety\r\n[953]"),
                (394017, "(d)\r\nProtecting the Integrity of Canada's Immigration System\r\n[963]"),
                (405492, "(a)\r\nCost Containment\r\n[997]"),
                (413773, "(b)\r\nProtecting the Integrity of Canada's Immigration System\r\n[1018]"),
                (418410, "(c)\r\nOther Minimal Impairment Arguments\r\n[1028]"),
            ],
        }
        for case_id, fixtures in expected.items():
            text, units = self.units(case_id)
            by_start = {unit["source_span"]["start_char"]: unit for unit in units}
            for offset, prefix in fixtures:
                with self.subTest(case_id=case_id, offset=offset):
                    self.assertEqual(prefix, text[offset : offset + len(prefix)])
                    self.assertIn(offset, by_start)
                    self.assertTrue(by_start[offset]["text"].startswith(prefix))

    def test_reported_editor_blocks_are_separate(self) -> None:
        for case_id in ("024310.txt", "057341.txt"):
            with self.subTest(case_id=case_id):
                _, units = self.units(case_id)
                editor_units = [unit for unit in units if unit["text"].startswith("Editor:")]
                self.assertEqual(1, len(editor_units))
                self.assertNotIn("Application dismissed", editor_units[0]["text"])
                self.assertNotIn("Order accordingly", editor_units[0]["text"])

    def test_paragraph_markers_do_not_accumulate_in_large_units(self) -> None:
        for case_id in ("055641.txt", "009672.txt", "057341.txt"):
            with self.subTest(case_id=case_id):
                _, units = self.units(case_id)
                import re
                self.assertLessEqual(max(len(re.findall(r"(?m)^\[\d+\]\r?$", unit["text"])) for unit in units), 1)
