"""Behavioral regressions for M2 bounded previews and display-window selection.

These tests validate display mechanics and raw provenance. They do not judge legal
meaning, quote ownership, or sentence completeness.
"""
import hashlib
import json
import re
import unittest
from pathlib import Path

from pipeline_v2.navigation.core import build_case_navigation
from pipeline_v2.source.core import parse_source


ROOT = Path(__file__).resolve().parents[2]
PROFILE = json.loads((ROOT / "pipeline_v2/configs/m2.json").read_text(encoding="utf-8"))
RAW_CASES = ROOT / "data/task1_train_files_2026/cases"
M1_SOURCES = ROOT / "pipeline_v2/artifacts/m1_20261105_v2/sources"
V2_AUDIT = ROOT / "pipeline_v2/reviews/m2_preview_revision2_validation/m2_navigation_20261106_v2_audit_checkpoint.json"


def build(case_id, raw):
    return build_case_navigation(case_id, raw, parse_source(case_id, raw), PROFILE)


class M2PreviewRevision2Tests(unittest.TestCase):
    def test_opening_is_bounded_content_window_not_first_period_sentence_guess(self):
        raw = (
            "[1]\r\nPinard, J.\r\n"
            "Mr. Faria applied to the Court for review. A second sentence follows. "
            + ("Additional context follows. " * 20) + "\r\n"
        ).encode("utf-8")
        record = build("123456.txt", raw)
        opening = next(p for p in record["previews"] if p["preview_kind"] == "opening")

        self.assertGreater(len(opening["text"]), 100)
        self.assertIn("Mr. Faria applied", opening["text"])
        self.assertLessEqual(len(opening["text"]), PROFILE["preview"]["max_chars"])
        self.assertIsNone(opening["partial_sentence"])
        self.assertEqual(opening["boundary_status"], "content_window_not_sentence_verified")
        for field in ("truncated", "start_clipped", "end_clipped"):
            self.assertIs(type(opening[field]), bool)
        self.assertEqual(opening["text"], raw[slice(*opening["span_bytes"])].decode("utf-8"))
        self.assertEqual(opening["text_sha256"], hashlib.sha256(raw[slice(*opening["span_bytes"])]).hexdigest())
        # The boundary should be whitespace/tag-safe, or explicitly say when
        # the fixed cap forced a split inside a long word/tag.
        if opening["end_clipped"]:
            _, end = opening["span_bytes"]
            source_text = raw.decode("utf-8")
            char_end = len(raw[:end].decode("utf-8"))
            if char_end < len(source_text) and opening["text"][-1].isalnum() and source_text[char_end].isalnum():
                self.assertTrue(opening["word_boundary_clipped"])
            if "<FRAGMENT_SUPPRES" in opening["text"]:
                self.assertTrue(opening["tag_boundary_clipped"])

    def test_placeholder_punctuation_line_is_skipped_to_real_content_and_raw_is_unchanged(self):
        raw = b"[1]\r\n<FRAGMENT_SUPPRESSED> )\r\nActual opening sentence. More content.\r\n"
        original = raw[:]
        record = build("123456.txt", raw)
        opening = next(p for p in record["previews"] if p["preview_kind"] == "opening")

        self.assertIn("Actual opening sentence", opening["text"])
        self.assertNotIn("<FRAGMENT_SUPPRESSED>", opening["text"])
        self.assertEqual(raw, original)
        start, end = opening["span_bytes"]
        self.assertEqual(opening["text"], raw[start:end].decode("utf-8"))
        self.assertEqual(opening["text_sha256"], hashlib.sha256(raw[start:end]).hexdigest())

    def test_second_window_covers_most_novel_nearby_anchors_without_duplicate_slot(self):
        text = (
            "[1] " + ("opening words " * 7) + "<FRAGMENT_SUPPRESSED> "
            + ("middle words " * 18) + "<REFERENCE_SUPPRESSED> <FRAGMENT_SUPPRESSED> "
            + ("later words " * 35) + "<FRAGMENT_SUPPRESSED> end.\n"
        )
        raw = text.encode("utf-8")
        record = build("123456.txt", raw)
        row = record["navigation"][0]
        previews = [p for p in record["previews"] if p["unit_id"] == row["unit_id"]]
        anchors = [a for a in record["anchors"] if a["unit_id"] == row["unit_id"]]

        self.assertEqual(len(anchors), 4)
        self.assertEqual(set(row["anchor_refs"]), {a["anchor_id"] for a in anchors})
        self.assertLessEqual(len(previews), PROFILE["preview"]["max_display_previews"])
        self.assertEqual(len({p["preview_id"] for p in previews}), len(previews))
        self.assertEqual(len({tuple(p["span_bytes"]) for p in previews}), len(previews))
        if len(previews) == 2:
            a, b = (p["span_bytes"] for p in previews)
            self.assertFalse(a[0] <= b[0] and b[1] <= a[1], "contained range wastes a display slot")
            self.assertFalse(b[0] <= a[0] and a[1] <= b[1], "contained range wastes a display slot")
        covered = {anchor for preview in previews for anchor in preview["anchor_refs"]}
        # The opening already exposes the first anchor; slot two should maximize
        # novel coverage by choosing the adjacent pair instead of a distant singleton.
        self.assertGreaterEqual(len(covered), 3)
        self.assertTrue(any(
            all(anchor_id in preview["anchor_refs"] for anchor_id in (anchors[1]["anchor_id"], anchors[2]["anchor_id"]))
            for preview in previews
        ))

    def test_equal_novel_anchor_windows_break_ties_by_source_order_deterministically(self):
        body = (
            "x" * 100 + "<FRAGMENT_SUPPRESSED>" + "x" * 420
            + "<FRAGMENT_SUPPRESSED>" + "y" * 420
            + "<FRAGMENT_SUPPRESSED>" + "z" * 300
        )
        raw = ("[1] " + body + "\n").encode("utf-8")
        first = build("123456.txt", raw)
        second = build("123456.txt", raw)
        row = first["navigation"][0]
        anchors = [a for a in first["anchors"] if a["unit_id"] == row["unit_id"]]
        previews = [p for p in first["previews"] if p["unit_id"] == row["unit_id"]]
        second_previews = [p for p in second["previews"] if p["unit_id"] == row["unit_id"]]
        chosen_anchor_window = next(p for p in previews if p["preview_kind"] == "anchor")

        self.assertEqual(len(anchors), 3)
        self.assertIn(anchors[1]["anchor_id"], chosen_anchor_window["anchor_refs"])
        self.assertNotIn(anchors[2]["anchor_id"], chosen_anchor_window["anchor_refs"])
        self.assertEqual(
            [(p["preview_kind"], p["span_bytes"], p["anchor_refs"]) for p in previews],
            [(p["preview_kind"], p["span_bytes"], p["anchor_refs"]) for p in second_previews],
        )

    def test_real_v2_tag_clip_regressions_no_longer_cut_through_protected_tags(self):
        checkpoint = json.loads(V2_AUDIT.read_text(encoding="utf-8"))
        regressions = checkpoint["raw_verified_tag_boundary_clip_cases"]
        self.assertEqual(checkpoint["raw_verified_tag_boundary_clip_count"], 9)

        for regression in regressions:
            case_id = regression["case_id"]
            with self.subTest(case_id=case_id, unit_id=regression["unit_id"]):
                raw = (RAW_CASES / case_id).read_bytes()
                m1 = json.loads((M1_SOURCES / f"{case_id[:-4]}.json").read_text(encoding="utf-8"))
                unit = next(u for u in m1["units"] if u["unit_id"] == regression["unit_id"])
                unit_start, _ = unit["span_chars"]
                unit_text = raw[slice(*unit["span_bytes"])].decode("utf-8")
                prior_cut = regression["cut_offset_in_unit_chars"]
                matches = [m for m in re.finditer(r"<[^<>\r\n]+>", unit_text)
                           if m.start() < prior_cut < m.end()]
                self.assertEqual(len(matches), 1, "checkpoint must pinpoint one real protected tag")
                target = matches[0]

                current = build_case_navigation(case_id, raw, m1, PROFILE)
                previews = [p for p in current["previews"] if p["unit_id"] == regression["unit_id"]]
                self.assertTrue(previews)
                for preview in previews:
                    start, end = preview["span_chars"]
                    relative_start, relative_end = start - unit_start, end - unit_start
                    intersects = relative_start < target.end() and target.start() < relative_end
                    if intersects:
                        self.assertLessEqual(relative_start, target.start())
                        self.assertGreaterEqual(relative_end, target.end())
                    self.assertFalse(preview["tag_boundary_clipped"])

    def test_long_source_cue_preview_reports_clipping_without_claiming_sentence_status(self):
        raw = ("[1] " + ("a" * 320) + "\n").encode("utf-8")
        m1 = parse_source("123456.txt", raw)
        unit = next(u for u in m1["units"] if u["unit_kind"] == "paragraph")
        start, end = unit["span_bytes"]
        m1["sidecars"] = [{"attribution_cue_refs": [{"span_bytes": [start + 5, start + 315]}]}]
        record = build_case_navigation("123456.txt", raw, m1, PROFILE)
        anchor = next(a for a in record["anchors"] if a["anchor_kind"] == "quote_introduction_candidate")
        linked = [p for p in record["previews"] if anchor["anchor_id"] in p["anchor_refs"]]

        self.assertTrue(linked)
        self.assertTrue(any(p["truncated"] for p in linked))
        for preview in linked:
            self.assertIsNone(preview["partial_sentence"])
            self.assertEqual(preview["boundary_status"], "content_window_not_sentence_verified")
            self.assertLessEqual(len(preview["text"]), PROFILE["preview"]["max_chars"])

    def test_long_cue_tail_window_advances_past_tag_or_word_without_splitting_it(self):
        bodies = {
            "tag": "x" * 34 + "<FRAGMENT_SUPPRESSED>" + "y" * 225,
            "word": "x" * 35 + "supercalifragilistic " + "fact " * 44,
        }
        for label, body in bodies.items():
            with self.subTest(boundary=label):
                raw = ("[1] " + body + "\n").encode("utf-8")
                m1 = parse_source("123456.txt", raw)
                unit = next(u for u in m1["units"] if u["unit_kind"] == "paragraph")
                unit_start, _ = unit["span_bytes"]
                cue_start = unit_start + len("[1] ".encode("utf-8"))
                cue_end = cue_start + len(body.encode("utf-8"))
                m1["sidecars"] = [{"attribution_cue_refs": [{"span_bytes": [cue_start, cue_end]}]}]
                record = build_case_navigation("123456.txt", raw, m1, PROFILE)
                row = record["navigation"][0]
                previews = [p for p in record["previews"] if p["unit_id"] == row["unit_id"]]
                anchor_previews = [p for p in previews if p["preview_kind"] == "anchor"]

                self.assertTrue(anchor_previews)
                self.assertLessEqual(len(previews), 2)
                for preview in previews:
                    self.assertLessEqual(len(preview["text"]), PROFILE["preview"]["max_chars"])
                    if preview["preview_kind"] == "anchor":
                        self.assertFalse(preview["tag_boundary_clipped"])
                        self.assertFalse(preview["word_boundary_clipped"])

    def test_real_source_regressions_open_beyond_judicial_initials_and_keep_exact_provenance(self):
        cases = {
            "011922": "On March 14, 2011",
            "051807": "This is an appeal",
            "080359": "Mr. Faria applied",
            "068193": "This is an application",
            "014101": "This is an application",
            "048208": "This is an application",
            "081945": "The Applicants seek",
            "015740": "This is an application",
        }
        for case_id, body_phrase in cases.items():
            with self.subTest(case_id=case_id):
                raw = (RAW_CASES / f"{case_id}.txt").read_bytes()
                record = build(f"{case_id}.txt", raw)
                row = next(r for r in record["navigation"] if r["observed_marker"] == 1)
                opening = next(p for p in record["previews"]
                               if p["unit_id"] == row["unit_id"] and p["preview_kind"] == "opening")
                self.assertIn(body_phrase, opening["text"])
                self.assertGreater(len(opening["text"]), 100)
                self.assertLessEqual(len(opening["text"]), PROFILE["preview"]["max_chars"])
                start, end = opening["span_bytes"]
                self.assertEqual(opening["text"], raw[start:end].decode("utf-8"))
                self.assertEqual(opening["text_sha256"], hashlib.sha256(raw[start:end]).hexdigest())
                self.assertIsNone(opening["partial_sentence"])
                self.assertEqual(opening["boundary_status"], "content_window_not_sentence_verified")


if __name__ == "__main__":
    unittest.main()
