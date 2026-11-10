import hashlib
import json
import unittest
from pathlib import Path

from pipeline_v2.navigation import NavigationReader
from pipeline_v2.navigation.core import M2Error, build_case_navigation
from pipeline_v2.source.core import parse_source


ROOT = Path(__file__).resolve().parents[2]
PROFILE = json.loads((ROOT / "pipeline_v2/configs/m2.json").read_text(encoding="utf-8"))


def build(case_id, raw):
    return build_case_navigation(case_id, raw, parse_source(case_id, raw), PROFILE)


class NavigationCoreTests(unittest.TestCase):
    def test_handles_cover_paragraph_and_unnumbered_units_without_using_marker_as_identity(self):
        raw = (
            "Unnumbered opening remains navigable.\n"
            "[35] First paragraph.\n"
            "[1] Repeated/backward marker paragraph.\n"
            "[35] Another repeated marker.\n"
        ).encode("utf-8")
        m1 = parse_source("123456.txt", raw)
        record = build_case_navigation("123456.txt", raw, m1, PROFILE)
        content = [u for u in m1["units"] if u["unit_kind"] in ("paragraph", "unnumbered")]
        rows = record["navigation"]
        self.assertEqual({r["unit_id"] for r in rows}, {u["unit_id"] for u in content})
        self.assertEqual(len(rows), len(content))
        self.assertEqual(len({r["handle"] for r in rows}), len(rows))
        repeated = [r for r in rows if r["observed_marker"] == 35]
        self.assertEqual(len(repeated), 2)
        self.assertNotEqual(repeated[0]["handle"], repeated[1]["handle"])
        self.assertTrue(any(r["unit_kind"] == "unnumbered" for r in rows))
        self.assertTrue(all(r["paragraph_role"] in ("unknown", "quoted", "current_case")
                            for r in rows if r["unit_kind"] == "paragraph"))

    def test_paragraph_neighbors_follow_source_order_and_skip_heading_whitespace_and_unnumbered(self):
        raw = (
            "Analysis\n\n[35] Alpha.\n\nAnalysis\n\n[1] Beta.\n[35] Gamma.\n"
        ).encode("utf-8")
        m1 = parse_source("123456.txt", raw)
        record = build_case_navigation("123456.txt", raw, m1, PROFILE)
        rows = record["navigation"]
        by_marker = {}
        for row in rows:
            if row["unit_kind"] == "paragraph":
                by_marker.setdefault(row["observed_marker"], []).append(row)
        paragraphs = sorted((r for r in rows if r["unit_kind"] == "paragraph"),
                            key=lambda r: r["source_order"])
        self.assertGreaterEqual(len(paragraphs), 2)
        for index, row in enumerate(paragraphs):
            expected_prev = paragraphs[index-1]["handle"] if index else None
            expected_next = paragraphs[index+1]["handle"] if index+1 < len(paragraphs) else None
            self.assertEqual(row["previous_paragraph_ref"], expected_prev)
            self.assertEqual(row["next_paragraph_ref"], expected_next)
        # A structural heading remains represented separately, not folded into a fake paragraph.
        self.assertTrue(record["headings"])
        self.assertTrue(any(u["unit_kind"] == "heading" for u in m1["units"]))

    def test_unnumbered_expansion_uses_real_content_unit_handles(self):
        raw = b"Loose opening text.\n[2] After.\n"
        m1 = parse_source("123456.txt", raw)
        record = build_case_navigation("123456.txt", raw, m1, PROFILE)
        rows = record["navigation"]
        loose = next(r for r in rows if r["unit_kind"] == "unnumbered")
        handles = {r["handle"] for r in rows}
        self.assertIn(loose["reading_expansion"]["parent_ref"], handles)
        self.assertEqual(loose["reading_expansion"]["neighbor_policy"], "content_unit_order")
        self.assertIn(loose["reading_expansion"]["next_ref"], handles)
        self.assertIsNone(loose["reading_expansion"]["previous_ref"])
        self.assertIsNone(loose["observed_marker"])

    def test_previews_are_exact_utf8_raw_spans_with_bom_crlf_accents_and_emoji(self):
        raw = "\ufeff[24] Café 😀 begins.\r\nSecond sentence <FRAGMENT_SUPPRESSED>.\r\n".encode("utf-8")
        record = build("123456.txt", raw)
        self.assertTrue(record["previews"])
        for preview in record["previews"]:
            start, end = preview["span_bytes"]
            self.assertEqual(preview["text"], raw[start:end].decode("utf-8"))
            self.assertEqual(preview["text_sha256"], hashlib.sha256(raw[start:end]).hexdigest())
            self.assertLessEqual(len(preview["text"]), 240)
            self.assertEqual(raw[start:end].decode("utf-8"), preview["text"])

    def test_opening_preview_does_not_call_marker_removal_a_partial_sentence(self):
        raw = b"[24] A complete opening sentence. The next sentence continues.\n"
        record = build("123456.txt", raw)
        opening = next(p for p in record["previews"] if p["preview_kind"] == "opening")
        self.assertIsNone(opening["partial_sentence"])
        self.assertEqual(opening["boundary_status"], "content_window_not_sentence_verified")
        self.assertTrue(opening["text"].startswith("A complete opening sentence."))

    def test_anchor_window_uses_second_display_slot_when_union_with_opening_exceeds_cap(self):
        raw = ("[1] " + ("x" * 220) + " <FRAGMENT_SUPPRESSED> " + ("y" * 100) + ".\n").encode()
        record = build("123456.txt", raw)
        row = record["navigation"][0]
        previews = [p for p in record["previews"] if p["unit_id"] == row["unit_id"]]
        self.assertEqual(len(previews), 2)
        placeholder = next(a for a in record["anchors"] if a["anchor_kind"] == "placeholder")
        visible = [p for p in previews if placeholder["anchor_id"] in p["anchor_refs"]]
        self.assertTrue(visible, "anchor should have an independently addressable display window")
        for preview in visible:
            relation = next(v for v in preview["anchor_visibility"] if v["anchor_ref"] == placeholder["anchor_id"])
            self.assertTrue(relation["fully_visible"])

    def test_long_quote_cue_partial_preview_keeps_causal_anchor_link_and_visibility(self):
        raw = ("[1] " + ("a" * 300) + "\n").encode()
        m1 = parse_source("123456.txt", raw)
        unit = next(u for u in m1["units"] if u["unit_kind"] == "paragraph")
        start, end = unit["span_bytes"]
        m1["sidecars"] = [{"attribution_cue_refs": [{"span_bytes": [start + 5, start + 295]}]}]
        record = build_case_navigation("123456.txt", raw, m1, PROFILE)
        anchor = next(a for a in record["anchors"] if a["anchor_kind"] == "quote_introduction_candidate")
        row = record["navigation"][0]
        self.assertIn(anchor["anchor_id"], row["anchor_refs"])
        linked = [p for p in record["previews"] if anchor["anchor_id"] in p["anchor_refs"]]
        self.assertTrue(linked)
        self.assertTrue(any(not v["fully_visible"] for p in linked for v in p["anchor_visibility"]
                            if v["anchor_ref"] == anchor["anchor_id"]))

    def test_preview_skips_placeholder_only_leading_line_without_mutating_raw_or_map(self):
        raw = b"[24]\n<FRAGMENT_SUPPRESSED>\nActual opening sentence.\n"
        m1 = parse_source("123456.txt", raw)
        record = build_case_navigation("123456.txt", raw, m1, PROFILE)
        self.assertEqual(raw, b"[24]\n<FRAGMENT_SUPPRESSED>\nActual opening sentence.\n")
        row = record["navigation"][0]
        opening = next((p for p in record["previews"] if p["preview_kind"] == "opening"
                        and p["unit_id"] == row["unit_id"]), None)
        if opening:
            self.assertIn("Actual opening sentence", opening["text"])
            self.assertNotIn("<FRAGMENT_SUPPRESSED>", opening["text"])
        self.assertTrue(any(a["anchor_kind"] == "placeholder" for a in record["anchors"]))
        self.assertTrue(any(u["unit_kind"] == "paragraph" for u in m1["units"]))

    def test_all_anchors_survive_display_preview_cap_and_are_referenced(self):
        body = " ".join(f"<FRAGMENT_SUPPRESSED>{i}" for i in range(7))
        raw = ("[8] Beginning. " + body + " Ending.\n").encode("utf-8")
        record = build("123456.txt", raw)
        row = record["navigation"][0]
        anchors = [a for a in record["anchors"] if a["unit_id"] == row["unit_id"]]
        previews = [p for p in record["previews"] if p["unit_id"] == row["unit_id"]]
        self.assertEqual(len(anchors), 7)
        self.assertEqual(set(row["anchor_refs"]), {a["anchor_id"] for a in anchors})
        self.assertLessEqual(len(previews), PROFILE["preview"]["max_display_previews"])
        # Every suppressed-text anchor remains independently addressable even when not displayed.
        self.assertEqual(len({a["anchor_id"] for a in anchors}), len(anchors))

    def test_token_dependent_readiness_stays_not_ready_and_runtime_state_is_not_static(self):
        raw = b"[1] Unknown ownership remains available.\n"
        record = build("123456.txt", raw)
        self.assertEqual(record["readiness"]["token_counts"], "not_ready")
        self.assertEqual(record["readiness"]["token_validated_chunks"], "not_ready")
        for row in record["navigation"]:
            self.assertIsNone(row["token_count"])
            self.assertNotIn("read_state", row)
            self.assertNotIn("Open", row)
        for preview in record["previews"]:
            self.assertIsNone(preview["token_count"])

    def test_rejects_source_hash_or_case_identity_mismatch(self):
        raw = b"[1] Text.\n"
        m1 = parse_source("123456.txt", raw)
        with self.assertRaises(M2Error):
            build_case_navigation("123456.txt", raw + b"drift", m1, PROFILE)
        with self.assertRaises(M2Error):
            build_case_navigation("654321.txt", raw, m1, PROFILE)

    def test_reader_pagination_keeps_all_rows_and_anchors_accessible(self):
        raw = ("Loose opening text.\n[2] " + " ".join(f"<FRAGMENT_SUPPRESSED>{i}" for i in range(7))
               + "\n[3] Ending.\n").encode()
        m1 = parse_source("123456.txt", raw)
        record = build_case_navigation("123456.txt", raw, m1, PROFILE)
        reader = object.__new__(NavigationReader)
        reader.profile = PROFILE
        reader._case = lambda case_id: (raw, record)
        all_items = []
        offset = 0
        while True:
            page = reader.map("123456.txt", offset=offset, limit=1)
            all_items.extend(page["items"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        self.assertEqual([r["unit_id"] for r in all_items], [r["unit_id"] for r in record["navigation"]])
        target = next(item for item in all_items if item["unit_kind"] == "paragraph")
        self.assertEqual(target["anchor_count"], 7)
        anchor_items = []
        offset = 0
        while True:
            page = reader.anchors("123456.txt", target["handle"], offset=offset, limit=2)
            anchor_items.extend(page["items"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        self.assertEqual(len(anchor_items), target["anchor_count"])
        self.assertEqual(len({item["anchor_id"] for item in anchor_items}), target["anchor_count"])
        with self.assertRaises(M2Error):
            reader.map("123456.txt", offset=0, limit=0)

    def test_open_context_returns_parent_and_source_order_paragraph_neighbors_exactly(self):
        raw = ("[10] Previous sentence.\n\nAnalysis\n\n[4] Hit parent.\n\n[10] Next sentence.\n").encode()
        m1 = parse_source("123456.txt", raw)
        record = build_case_navigation("123456.txt", raw, m1, PROFILE)
        reader = object.__new__(NavigationReader)
        reader.profile = PROFILE
        reader._case = lambda case_id: (raw, record)
        target = next(r for r in record["navigation"] if r["observed_marker"] == 4)
        result = reader.open_context("123456.txt", target["handle"])
        self.assertEqual([c["kind"] for c in result["components"]],
                         ["previous_context", "parent", "next_context"])
        self.assertEqual([c["handle"] for c in result["components"]],
                         [target["previous_paragraph_ref"], target["handle"], target["next_paragraph_ref"]])
        start, end = result["span_bytes"]
        self.assertEqual(result["text"], raw[start:end].decode("utf-8"))
        self.assertIn("Analysis", result["text"])
        self.assertTrue(result["diagnostic_only"])
        self.assertFalse(result["M4_delivery_recorded"])


if __name__ == "__main__":
    unittest.main()
