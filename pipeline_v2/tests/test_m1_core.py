from __future__ import annotations

import hashlib
from pathlib import Path
import re
import unittest

from pipeline_v2.source.core import M1Error, Utf8Map, parse_source, validate_partition


class Utf8MapTests(unittest.TestCase):
    def test_round_trip_boundaries_with_bom_accents_emoji_and_crlf(self):
        text = "\ufeffA café 🧑‍⚖️\r\nFin."
        raw = text.encode("utf-8")
        mapping = Utf8Map(raw)
        self.assertEqual(mapping.text, text)
        self.assertEqual(mapping.byte_length, len(raw))
        for char_offset in range(len(text) + 1):
            expected = len(text[:char_offset].encode("utf-8"))
            self.assertEqual(mapping.char_to_byte(char_offset), expected)
            self.assertEqual(mapping.byte_to_char(expected), char_offset)

        boundaries = {len(text[:i].encode("utf-8")) for i in range(len(text) + 1)}
        interior = [i for i in range(len(raw) + 1) if i not in boundaries]
        self.assertTrue(interior)
        for byte_offset in interior:
            with self.subTest(byte_offset=byte_offset):
                with self.assertRaises(M1Error):
                    mapping.byte_to_char(byte_offset)

    def test_rejects_invalid_utf8_and_out_of_bounds_offsets(self):
        with self.assertRaises(M1Error):
            Utf8Map(b"valid\xff")
        mapping = Utf8Map("é".encode())
        for fn, value in ((mapping.char_to_byte, -1), (mapping.char_to_byte, 2),
                          (mapping.byte_to_char, -1), (mapping.byte_to_char, 3)):
            with self.subTest(value=value):
                with self.assertRaises(M1Error):
                    fn(value)


class ParseSourceTests(unittest.TestCase):
    def test_partition_is_full_contiguous_raw_coverage_and_round_trips(self):
        raw = (
            "Indexed As: Café v. R.\r\n2019 FC 42\r\nFederal Court\r\n\r\n"
            "JUDGMENT\r\n\r\n[1]\r\nIntro follows:\r\n[9]\r\n"
            "Quoted naïve 🧑‍⚖️ text.\r\n[2]\r\nThe Court decides.\r\n"
        ).encode("utf-8")
        record = parse_source("123456.txt", raw)
        self.assertEqual(record["raw_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertTrue(validate_partition(record, raw))
        cursor = 0
        for unit in record["units"]:
            start, end = unit["span_bytes"]
            self.assertEqual(start, cursor)
            self.assertLess(start, end)
            self.assertEqual(raw[start:end].decode("utf-8"), record_text_slice(record, raw, unit))
            cursor = end
        self.assertEqual(cursor, len(raw))

    def test_marker_lines_remain_independent_and_quote_link_is_explicit(self):
        raw = (
            "Title\n\n[1]\nThe Court quotes the following:\n[9]\n"
            "Quoted authority\n[2012] FC 9\n[2]\nDisposition.\n"
        ).encode("utf-8")
        record = parse_source("123456.txt", raw)
        paragraphs = [unit for unit in record["units"] if unit["unit_kind"] == "paragraph"]
        self.assertEqual([unit["observed_marker"] for unit in paragraphs], [1, 9, 2])
        self.assertEqual([unit["paragraph_role"] for unit in paragraphs], ["unknown", "quoted", "unknown"])
        self.assertTrue(all(unit["marker_span_bytes"] for unit in paragraphs))
        self.assertTrue(all(isinstance(unit["role_evidence_refs"], list) for unit in paragraphs))
        self.assertTrue(paragraphs[1]["role_evidence_refs"])
        relations = record["sidecars"]
        self.assertEqual(len(relations), 1)
        by_id = {unit["unit_id"]: unit for unit in paragraphs}
        relation = relations[0]
        self.assertEqual(by_id[relation["quoted_unit_id"]]["observed_marker"], 9)
        self.assertEqual(by_id[relation["attribution_unit_id"]]["observed_marker"], 1)
        self.assertNotEqual(relation["quoted_unit_id"], relation["attribution_unit_id"])
        years = [ob for ob in record["marker_observations"]
                 if ob["classification"] == "citation_marker_with_reporter_evidence"]
        self.assertEqual([ob["number"] for ob in years], [2012])

    def test_metadata_values_have_exact_raw_evidence_and_absent_fields_stay_unknown(self):
        raw = (
            "Indexed As: Café v. R.\r\n2019 FC 42\r\nFederal Court\r\n"
            "January 5, 2019\r\n\r\n[1]\r\nBody.\r\n"
        ).encode("utf-8")
        record = parse_source("123456.txt", raw)
        metadata = {item["field"]: item for item in record["metadata"]}
        self.assertEqual(metadata["case_name"]["value"], "Café v. R.")
        self.assertEqual(metadata["neutral_citation"]["value"], "2019 FC 42")
        for name in ("case_name", "neutral_citation", "court", "date"):
            field = metadata[name]
            if field["value"] is None:
                self.assertEqual(field["confidence_status"], "unknown")
                self.assertEqual(field["source_refs"], [])
            else:
                ref = field["source_refs"][0]["span_bytes"]
                self.assertEqual(raw[ref[0]:ref[1]].decode("utf-8"), field["value"])
        self.assertNotIn("speaker", metadata)
        self.assertNotIn("holding", metadata)

    def test_repeated_one_without_cue_does_not_reset_region_or_swallow_markers(self):
        raw = "[1]\nEnglish text.\n[2]\nMore English.\n[1]\nAmbiguous reset.\n".encode()
        record = parse_source("123456.txt", raw)
        paragraphs = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
        self.assertEqual([u["observed_marker"] for u in paragraphs], [1, 2, 1])
        self.assertEqual(paragraphs[-1]["paragraph_role"], "unknown")
        self.assertEqual(paragraphs[-1]["language_region"], "unknown:0")
        self.assertEqual(record["sidecars"], [])

    def test_multiple_header_citations_are_preserved_as_observations_not_identity(self):
        raw = ("Indexed As: Case A v. B\n2019 FC 42\n2020 FC 17\n\n[1]\nBody.\n").encode()
        record = parse_source("123456.txt", raw)
        citations = [field for field in record["metadata"] if field["field"] == "neutral_citation"]
        self.assertEqual([field["value"] for field in citations], ["2019 FC 42", "2020 FC 17"])
        self.assertTrue(all(field["confidence_status"] == "observed_not_identity_verified" for field in citations))
        for field in citations:
            start, end = field["source_refs"][0]["span_bytes"]
            self.assertEqual(raw[start:end].decode("utf-8"), field["value"])

    def test_rejects_invalid_case_id(self):
        with self.assertRaises(M1Error):
            parse_source("../123456.txt", b"text")

    def test_line_start_marker_coverage_is_independent_of_number_order(self):
        raw = ("[35]\nBody A.\n[37]Body B.\n[1]\nQuoted or translated.\n"
               "[37]\nRepeated number.\n[2]\nReturns to text.\n[2012] FC 9\n").encode()
        record = parse_source("123456.txt", raw)
        units = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
        observed = {tuple(u["marker_span_bytes"]) for u in units}
        observations = {tuple(item["span_bytes"]) for item in record["marker_observations"]}
        expected = set()
        text = raw.decode("utf-8")
        for match in re.finditer(r"(?m)^[ \t\ufeff]*\[\d+\]", text):
            expected.add((len(text[:match.start()].encode("utf-8")), len(text[:match.end()].encode("utf-8"))))
        self.assertEqual(observed | observations, expected)
        self.assertEqual(len(units), 5)
        self.assertEqual([u["observed_marker"] for u in units], [35, 37, 1, 37, 2])

    def test_marker_with_leading_zero_and_no_space_after_bracket_is_preserved(self):
        raw = "[0007]Text without whitespace.\n[10000]\nStandalone year-like marker.\n".encode()
        record = parse_source("123456.txt", raw)
        paragraphs = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
        self.assertEqual([u["marker_text"] for u in paragraphs], ["[0007]", "[10000]"])
        self.assertEqual([u["observed_marker"] for u in paragraphs], [7, 10000])
        self.assertEqual([u["paragraph_role"] for u in paragraphs], ["unknown", "unknown"])

    def test_translation_cue_assigns_fr_even_when_first_marker_is_two(self):
        raw = ("French language version follows English language version\n"
               "[1]\nEnglish reasons.\n........................\n"
               "[Traduction]\nLe juge Annis (demandeur)\n[2]\nLe juge explique le résultat.\n").encode("utf-8")
        record = parse_source("123456.txt", raw)
        french = next(u for u in record["units"]
                      if u["unit_kind"] == "paragraph" and u["observed_marker"] == 2)
        self.assertTrue(french["language_region"].startswith("fr:"))
        self.assertTrue(french["language_evidence_refs"])
        a, b = french["language_evidence_refs"][0]["span_bytes"]
        self.assertIn("Traduction", raw[a:b].decode("utf-8"))

    def test_relabeling_paragraph_numbers_cannot_change_structural_ownership(self):
        one = ("[35]\nThe Court states the following:\n[9]\nQuoted part.\n"
               "[38]\nNext current paragraph.\n").encode()
        two = ("[4]\nThe Court states the following:\n[27]\nQuoted part.\n"
               "[2]\nNext current paragraph.\n").encode()
        first = parse_source("123456.txt", one)
        second = parse_source("123456.txt", two)
        roles_one = [u["paragraph_role"] for u in first["units"] if u["unit_kind"] == "paragraph"]
        roles_two = [u["paragraph_role"] for u in second["units"] if u["unit_kind"] == "paragraph"]
        self.assertEqual(roles_one, ["unknown", "quoted", "unknown"])
        self.assertEqual(roles_two, roles_one)

    def test_first_person_judicial_voice_alone_does_not_close_quote_scope(self):
        raw = ("[1]\nThe Court quotes the following:\n[9]\nThe judge stated that no hearing was required.\n"
               "[10]\nI find that the Board's decision was reasonable.\n[11]\nThe application is dismissed.\n").encode()
        record = parse_source("123456.txt", raw)
        paragraphs = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
        by_number = {u["observed_marker"]: u for u in paragraphs}
        self.assertEqual(by_number[9]["paragraph_role"], "quoted")
        self.assertEqual(by_number[10]["paragraph_role"], "unknown")
        self.assertEqual(by_number[11]["paragraph_role"], "unknown")
        self.assertFalse(any(r["quoted_unit_id"] == by_number[10]["unit_id"] for r in record["sidecars"]))

    def test_generic_following_colon_is_not_quote_attribution_evidence(self):
        raw = ("[1]\nMy reasons are the following:\n[2]\nA numbered part of the reasons.\n"
               "[3]\nAnother part.\n").encode()
        record = parse_source("123456.txt", raw)
        paragraphs = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
        self.assertEqual([u["observed_marker"] for u in paragraphs], [1, 2, 3])
        self.assertTrue(all(u["paragraph_role"] == "unknown" for u in paragraphs))
        self.assertEqual(record["sidecars"], [])

    def test_exposed_number_gap_and_quoted_one_do_not_swallow_following_markers(self):
        cases = {
            "000758.txt": {35, 37, 38, 75},
            "050936.txt": {30, 1, 31, 54},
            "046028.txt": {6, 8, 34},
        }
        corpus = Path(__file__).resolve().parents[2] / "data" / "task1_train_files_2026" / "cases"
        for case_id, required in cases.items():
            with self.subTest(case_id=case_id):
                raw = (corpus / case_id).read_bytes()
                record = parse_source(case_id, raw)
                paragraphs = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
                by_marker = {}
                for unit in paragraphs:
                    by_marker.setdefault(unit["observed_marker"], []).append(unit)
                self.assertTrue(required.issubset(by_marker))
                self.assertGreaterEqual(len(paragraphs), len(required))
                self.assertTrue(all(u["paragraph_role"] in {"current_case", "quoted", "unknown"}
                                    for u in paragraphs))

    def test_french_body_starting_at_two_is_preserved_and_language_is_evidence_based(self):
        corpus = Path(__file__).resolve().parents[2] / "data" / "task1_train_files_2026" / "cases"
        for case_id in ("000432.txt", "014069.txt"):
            with self.subTest(case_id=case_id):
                record = parse_source(case_id, (corpus / case_id).read_bytes())
                paragraphs = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
                self.assertTrue(any(u["observed_marker"] == 2 and u["paragraph_role"] == "unknown"
                                    for u in paragraphs))
                self.assertTrue(all(u["paragraph_role"] in {"current_case", "quoted", "unknown"}
                                    for u in paragraphs))

    def test_exposed_050936_quote_one_and_following_english_markers_are_distinct(self):
        corpus = Path(__file__).resolve().parents[2] / "data" / "task1_train_files_2026" / "cases" / "050936.txt"
        record = parse_source("050936.txt", corpus.read_bytes())
        paragraphs = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
        quoted_ones = [u for u in paragraphs if u["observed_marker"] == 1 and u["paragraph_role"] == "quoted"]
        self.assertTrue(quoted_ones)
        self.assertIn(31, {u["observed_marker"] for u in paragraphs})
        self.assertIn(54, {u["observed_marker"] for u in paragraphs})
        self.assertTrue(any(r["quoted_unit_id"] == quoted_ones[0]["unit_id"]
                            for r in record["sidecars"]))

    def test_uppercase_headings_are_recognized_without_promoting_court_header(self):
        raw = ("Federal Court\nTrial Division\n\n[1]\nText.\n\nORDER\n\n[2]\nDone.\n"
               "\nINTRODUCTION\n\n[3]\nStart.\n\nARGUMENTS\n\n[4]\nArgue.\n"
               "\nDECISION\n\n[5]\nResult.\n").encode()
        record = parse_source("123456.txt", raw)
        headings = [raw[slice(*u["span_bytes"])].decode().strip()
                    for u in record["units"] if u["unit_kind"] == "heading"]
        self.assertEqual(headings, ["ORDER", "INTRODUCTION", "ARGUMENTS", "DECISION"])
        paragraphs = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
        self.assertTrue(all("Federal Court" not in str(u["section_path_refs"]) for u in paragraphs))

    def test_exposed_061295_quotes_are_separate_with_raw_evidence_links(self):
        path = Path(__file__).resolve().parents[2] / "data" / "task1_train_files_2026" / "cases" / "061295.txt"
        raw = path.read_bytes()
        record = parse_source("061295.txt", raw)
        units = {unit["unit_id"]: unit for unit in record["units"]}
        relation_pairs = {
            (units[relation["attribution_unit_id"]]["observed_marker"],
             units[relation["quoted_unit_id"]]["observed_marker"])
            for relation in record["sidecars"]
        }
        self.assertTrue({(12, 9), (13, 17), (14, 10)}.issubset(relation_pairs))
        quote9_relation = next(relation for relation in record["sidecars"]
                               if units[relation["quoted_unit_id"]]["observed_marker"] == 9 and
                               units[relation["attribution_unit_id"]]["observed_marker"] == 12)
        self.assertEqual(units[quote9_relation["quoted_unit_id"]]["paragraph_role"], "quoted")
        self.assertTrue(quote9_relation["attribution_cue_refs"])
        cue_ref = quote9_relation["attribution_cue_refs"][0]["span_bytes"]
        cue = raw[cue_ref[0]:cue_ref[1]].decode("utf-8")
        self.assertTrue(cue.strip())
        self.assertIn("at paragraph 9", cue)

    def test_exposed_067620_repeated_number_is_separate_bilingual_region(self):
        path = Path(__file__).resolve().parents[2] / "data" / "task1_train_files_2026" / "cases" / "067620.txt"
        record = parse_source("067620.txt", path.read_bytes())
        first_markers = [unit for unit in record["units"]
                         if unit["unit_kind"] == "paragraph" and unit["observed_marker"] == 1]
        self.assertGreaterEqual(len(first_markers), 2)
        self.assertGreaterEqual(len({unit["language_region"] for unit in first_markers}), 2)
        french = [unit for unit in first_markers if unit["language_region"].startswith("fr:")]
        self.assertTrue(french)
        self.assertTrue(french[0]["language_evidence_refs"])

    def test_exposed_062436_heading_is_observed_structure_without_semantic_speaker(self):
        path = Path(__file__).resolve().parents[2] / "data" / "task1_train_files_2026" / "cases" / "062436.txt"
        raw = path.read_bytes()
        record = parse_source("062436.txt", raw)
        respondents = [unit for unit in record["units"] if unit["unit_kind"] == "heading" and
                       raw[slice(*unit["span_bytes"])].decode("utf-8").strip() == "The Respondent"]
        self.assertTrue(respondents)
        self.assertTrue(any(respondents[0]["unit_id"] in unit["section_path_refs"]
                            for unit in record["units"] if unit["order"] > respondents[0]["order"]))
        self.assertTrue(all("speaker" not in unit and "holding" not in unit for unit in record["units"]))


def record_text_slice(record, raw, unit):
    start, end = unit["span_bytes"]
    return raw[start:end].decode("utf-8")


if __name__ == "__main__":
    unittest.main()
