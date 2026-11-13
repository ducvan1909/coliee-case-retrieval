"""Independent contract tests for local M3 source tools."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pipeline_v2.full_search.source_tools import SourceToolsSession
from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.source.core import canonical, digest


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def seal_files(bundle, names):
    files = {}
    for name in names:
        raw = (bundle / name).read_bytes()
        files[name] = {"sha256": digest(raw), "byte_length": len(raw)}
    seal = {"schema_version": "fixture-seal-1", "files": files}
    write_json(bundle / "seal.json", seal)
    return digest((bundle / "seal.json").read_bytes())


def union_intervals(spans):
    result = []
    for start, end in sorted(spans):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


class InjectedSnapshot:
    def __init__(self, manifest):
        self.manifest = manifest
        self.binding = {"manifest.json": "fixture-manifest", "seal.json": "fixture-seal"}
        self.guard_calls = 0
        self.invalidated = False

    def guard(self):
        self.guard_calls += 1
        if self.invalidated:
            raise M3Error("fixture snapshot invalidated")

    def revalidate(self):
        self.guard()
        return {"status": "fixture_revalidated"}


class SourceToolsFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case_dir = self.root / "data/task1_train_files_2026/cases"
        self.artifacts = self.root / "pipeline_v2/artifacts"
        self.case_dir.mkdir(parents=True)
        write_json(self.root / "pipeline_v2/configs/m3_search.json", {
            "schema_version": "pipeline-v2-m3-source-tools-1",
            "full_run": "pipeline_v2/artifacts/m3_full_train_20261108_v1",
            "max_limit": 100,
            "default_case_scan_limit": 128,
            "max_case_scan_limit": 7708,
            "byte_cap": 65536,
            "case_cache_size": 4,
            "bm25": {"k1": 1.5, "b": 0.75},
        })
        self.sources = {}
        self.nav_records = {}
        self.passage_records = {}
        self.m1_records = {}

    def add_case(self, case_id, raw_text, ranges, *, headings=None, passages=None,
                 m1_extra_units=None, anchors=None, source_anchors=None):
        """Make small, explicitly authored raw/navigation/passages fixtures."""
        raw = raw_text.encode("utf-8")
        (self.case_dir / case_id).write_bytes(raw)
        source_hash = digest(raw)
        self.sources[case_id] = source_hash
        headings = headings or []
        passage_rows = []
        nav_rows = []
        for index, entry in enumerate(ranges):
            handle = entry.get("handle", f"u{index:04d}")
            unit_id = entry.get("unit_id", f"{case_id[:6]}:unit:{index}")
            span = entry["span_bytes"]
            passage_rows.append({
                "passage_id": entry.get("passage_id", f"{case_id[:6]}:passage:{index}"),
                "case_id": case_id,
                "source_hash": source_hash,
                "exact_input_sha256": digest(raw[span[0]:span[1]]),
                "text_sha256": digest(raw[span[0]:span[1]]),
                "text": raw[span[0]:span[1]].decode("utf-8"),
                "span_bytes": span,
                "parent_unit_ids": [unit_id],
                "parent_handle": handle,
            })
            nav_rows.append({
                "handle": handle,
                "unit_id": unit_id,
                "unit_kind": entry.get("unit_kind", "paragraph"),
                "span_bytes": span,
                "paragraph_role": entry.get("paragraph_role", "current_case"),
                "observed_marker": entry.get("observed_marker"),
                "role_evidence_refs": entry.get("role_evidence_refs", []),
                "language_region": entry.get("language_region", "en:0"),
                "uncertainties": entry.get("uncertainties", []),
                "reading_expansion": {},
                "preview_refs": [],
                "section_refs": [],
            })
        if passages is not None:
            passage_rows = passages
        for index, row in enumerate(nav_rows):
            row["reading_expansion"] = {
                "neighbor_policy": "paragraph_order",
                "previous_ref": nav_rows[index - 1]["handle"] if index else None,
                "parent_ref": row["handle"],
                "next_ref": nav_rows[index + 1]["handle"] if index + 1 < len(nav_rows) else None,
            }
        for heading in headings:
            heading.setdefault("unit_id", f"{case_id[:6]}:heading:{len(self.nav_records)}:{len(headings)}")
            heading.setdefault("unit_kind", "heading")
            heading.setdefault("paragraph_role", None)
            heading.setdefault("observed_marker", None)
            heading.setdefault("role_evidence_refs", [])
            heading.setdefault("language_region", "unknown:0")
            heading.setdefault("uncertainties", [])
        m1_units = []
        for index, entry in enumerate(ranges):
            m1_units.append({
                "unit_id": entry.get("unit_id", f"{case_id[:6]}:unit:{index}"),
                "unit_kind": entry.get("unit_kind", "paragraph"),
                "span_bytes": entry["span_bytes"],
                "language_region": entry.get("language_region", "en:0"),
                "paragraph_role": entry.get("paragraph_role", "current_case"),
                "observed_marker": entry.get("observed_marker"),
                "role_evidence_refs": entry.get("role_evidence_refs", []),
                "uncertainties": entry.get("uncertainties", []),
                "order": index,
            })
        for heading in headings:
            m1_units.append({
                "unit_id": heading["unit_id"], "unit_kind": "heading",
                "span_bytes": heading["span_bytes"],
                "language_region": heading.get("language_region", "unknown:0"),
                "paragraph_role": None, "observed_marker": None,
                "role_evidence_refs": [], "uncertainties": [],
                "order": len(m1_units),
            })
        m1_units.extend(m1_extra_units or [])
        self.m1_records[case_id] = {
            "case_id": case_id, "raw_sha256": source_hash, "byte_length": len(raw),
            "units": sorted(m1_units, key=lambda unit: unit["span_bytes"]),
        }
        nav = {
            "case_id": case_id,
            "source_hash": source_hash,
            "m1_structure_sha256": digest(canonical(self.m1_records[case_id])),
            "navigation": nav_rows,
            "headings": headings,
            "previews": [],
            "anchors": anchors or [],
            "source_anchors": source_anchors or [],
        }
        self.nav_records[case_id] = nav
        self.passage_records[case_id] = {
            "case_id": case_id,
            "source_hash": source_hash,
            "navigation_sha256": digest(canonical(nav)),
            "passages": passage_rows,
        }

    def make_session(self):
        m1_bundle = self.artifacts / "m1_fixture_v1"
        nav_bundle = self.artifacts / "m2_navigation_fixture_v1"
        pass_bundle = self.artifacts / "m2_passages_fixture_v1"
        m1_bundle.mkdir(parents=True)
        nav_bundle.mkdir(parents=True)
        pass_bundle.mkdir(parents=True)
        m1_rows, nav_rows, passage_rows = [], [], []
        for case_id, nav in self.nav_records.items():
            name = f"sources/{case_id[:-4]}.json"
            write_json(m1_bundle / name, self.m1_records[case_id])
            write_json(nav_bundle / name, nav)
            passages = self.passage_records[case_id]
            write_json(pass_bundle / name, passages)
            nav_rows.append({"case_id": case_id, "navigation_ref": name,
                             "navigation_sha256": digest(canonical(nav))})
            m1_rows.append({"case_id": case_id, "raw_sha256": self.sources[case_id],
                            "byte_length": (self.case_dir / case_id).stat().st_size,
                            "structure_ref": name,
                            "structure_sha256": digest(canonical(self.m1_records[case_id]))})
            passage_rows.append({"case_id": case_id, "passages_ref": name,
                                 "passages_sha256": digest(canonical(passages))})
        write_json(m1_bundle / "manifest.json", {"schema_version": "fixture-m1-1"})
        write_json(m1_bundle / "source_registry.json", {"sources": m1_rows})
        m1_seal_sha = seal_files(m1_bundle, [
            "manifest.json", "source_registry.json",
            *[f"sources/{case_id[:-4]}.json" for case_id in self.m1_records],
        ])
        nav_manifest = {
            "schema_version": "fixture-nav-1",
            "m1": {"bundle": "pipeline_v2/artifacts/m1_fixture_v1",
                   "seal_sha256": m1_seal_sha,
                   "manifest_sha256": digest((m1_bundle / "manifest.json").read_bytes()),
                   "registry_sha256": digest((m1_bundle / "source_registry.json").read_bytes())},
        }
        write_json(nav_bundle / "manifest.json", nav_manifest)
        write_json(nav_bundle / "source_registry.json", {"sources": nav_rows})
        nav_seal_sha = seal_files(nav_bundle, [
            "manifest.json", "source_registry.json",
            *[f"sources/{case_id[:-4]}.json" for case_id in self.nav_records],
        ])
        nav_manifest_sha = digest((nav_bundle / "manifest.json").read_bytes())
        nav_registry_sha = digest((nav_bundle / "source_registry.json").read_bytes())
        write_json(pass_bundle / "manifest.json", {
            "navigation": {"bundle": "pipeline_v2/artifacts/m2_navigation_fixture_v1",
                           "seal_sha256": nav_seal_sha,
                           "manifest_sha256": nav_manifest_sha,
                           "registry_sha256": nav_registry_sha},
        })
        write_json(pass_bundle / "source_registry.json", {"sources": passage_rows})
        pass_seal_sha = seal_files(pass_bundle, [
            "manifest.json", "source_registry.json",
            *[f"sources/{case_id[:-4]}.json" for case_id in self.passage_records],
        ])
        manifest = {
            "source_hashes": dict(self.sources),
            "profile": {"passages_bundle": "pipeline_v2/artifacts/m2_passages_fixture_v1",
                        "accepted_m2_seal_sha256": pass_seal_sha},
        }
        self.snapshot = InjectedSnapshot(manifest)
        self.session = SourceToolsSession(self.root, self.snapshot)
        self.addCleanup(self.session.close)
        return self.session


def single_span(case_id, raw, start, end, **metadata):
    return [{"handle": metadata.pop("handle", "p000001"),
             "unit_id": metadata.pop("unit_id", f"{case_id[:6]}:p000001"),
             "span_bytes": [start, end], **metadata}]


class PhraseSearchTests(SourceToolsFixture):
    def test_unicode_casefold_expansions_map_only_whole_codepoints(self):
        cases = (("000001.txt", "ß"), ("000002.txt", "İ"), ("000003.txt", "ﬁ"))
        for case_id, text in cases:
            raw = text.encode("utf-8")
            self.add_case(case_id, text, single_span(case_id, raw, 0, len(raw)))
        session = self.make_session()
        needles = {"000001.txt": ("ss", "s"), "000002.txt": ("i\u0307", "i"),
                   "000003.txt": ("fi", "f")}
        for case_id, (whole, partial) in needles.items():
            hit = session.search_phrase(whole, case_id, "unicode_casefold_mapped")["hits"]
            self.assertEqual(len(hit), 1)
            self.assertEqual(hit[0]["span_bytes"], [0, len((self.case_dir / case_id).read_bytes())])
            self.assertEqual(hit[0]["text"].casefold(), whole.casefold())
            self.assertEqual(session.search_phrase(partial, case_id, "unicode_casefold_mapped")["hits"], [])

    def test_crlf_bom_cross_unit_overlapping_repeated_matches_round_trip(self):
        raw_text = "\ufeff[1] aaa\r\n[2] B"
        raw = raw_text.encode("utf-8")
        split = raw.index(b"\r\n")
        ranges = [
            {"handle": "p1", "unit_id": "unit-1", "span_bytes": [0, split], "observed_marker": 1},
            {"handle": "p2", "unit_id": "unit-2", "span_bytes": [split + 2, len(raw)], "observed_marker": 2,
             "paragraph_role": "quoted", "uncertainties": ["attribution_unresolved"]},
        ]
        self.add_case("000001.txt", raw_text, ranges,
                      headings=[{"unit_id": "h1", "span_bytes": [split - 1, split], "text": "1"}])
        session = self.make_session()
        hits = session.search_phrase("aa", "000001.txt", limit=10)["hits"]
        self.assertEqual([hit["text"] for hit in hits], ["aa", "aa"])
        self.assertEqual([hit["span_chars"] for hit in hits], [[5, 7], [6, 8]])
        for hit in hits:
            raw_slice = raw[hit["span_bytes"][0]:hit["span_bytes"][1]]
            self.assertEqual(raw_slice.decode("utf-8"), hit["text"])
            self.assertEqual(digest(raw_slice), hit["text_sha256"])
        cross = session.search_phrase("aaa\r\n[2]", "000001.txt")["hits"]
        self.assertEqual(cross[0]["text"], "aaa\r\n[2]")
        self.assertEqual(len(cross[0]["intersecting_handles"]), 2)

    def test_cursor_resumes_empty_scan_page_and_binds_query_and_scope(self):
        for case_id, text in (("000001.txt", "nothing here"), ("000002.txt", "target")):
            raw = text.encode()
            self.add_case(case_id, text, single_span(case_id, raw, 0, len(raw)))
        session = self.make_session()
        first = session.search_phrase("target", case_scan_limit=1)
        self.assertEqual(first["hits"], [])
        self.assertEqual(first["coverage"]["scanned_cases"], 1)
        self.assertIsNotNone(first["next_cursor"])
        second = session.search_phrase("target", case_scan_limit=1, cursor=first["next_cursor"])
        self.assertEqual([hit["case_id"] for hit in second["hits"]], ["000002.txt"])
        self.assertTrue(second["exhausted"])
        with self.assertRaises(M3Error):
            session.search_phrase("different", case_scan_limit=1, cursor=first["next_cursor"])
        with self.assertRaises(M3Error):
            session.search_phrase("target", "000002.txt", case_scan_limit=1, cursor=first["next_cursor"])
        tampered = first["next_cursor"][:-3] + "AAA"
        with self.assertRaises(M3Error):
            session.search_phrase("target", case_scan_limit=1, cursor=tampered)

    def test_cursor_is_bound_to_logical_tool_and_rejects_boolean_version(self):
        for case_id, text in (("000001.txt", "target"), ("000002.txt", "target again")):
            raw = text.encode()
            self.add_case(case_id, text, single_span(case_id, raw, 0, len(raw)))
        session = self.make_session()
        phrase = session.search_phrase("target", "000001.txt", limit=1)
        phrase_cursor = phrase["next_cursor"]
        self.assertIsNotNone(phrase_cursor)
        with self.assertRaises(M3Error):
            session.search_identity("target", "000001.txt", limit=1, cursor=phrase_cursor)
        with self.assertRaises(M3Error):
            session.search_case("000001.txt", "target", mode="literal", limit=1, cursor=phrase_cursor)

        identity = session.search_identity("target", "000001.txt", limit=1)
        with self.assertRaises(M3Error):
            session.search_phrase("target", "000001.txt", limit=1, cursor=identity["next_cursor"])

        import base64
        binding = session._binding("search_phrase", {
            "text": "target", "case_ids": ["000001.txt"], "mode": "exact_case_sensitive"})
        body = {"version": True, "binding": binding,
                "progress": {"case_index": 0, "char_start": 0}}
        envelope = {**body, "checksum": digest(canonical(body))}
        boolean_version_cursor = base64.urlsafe_b64encode(canonical(envelope)).decode("ascii")
        with self.assertRaises(M3Error):
            session.search_phrase("target", "000001.txt", cursor=boolean_version_cursor)

    def test_raw_source_drift_invalidates_session(self):
        raw = b"before"
        self.add_case("000001.txt", raw.decode(), single_span("000001.txt", raw, 0, len(raw)))
        session = self.make_session()
        (self.case_dir / "000001.txt").write_bytes(b"changed")
        with self.assertRaises(M3Error):
            session.search_phrase("before", "000001.txt")
        with self.assertRaises(M3Error):
            session.case_map("000001.txt")

    def test_identity_search_reports_observed_lead_with_raw_anchor_and_pagination(self):
        text = "Smith v. Jones mentioned in this judgment."
        raw = text.encode()
        end = len("Smith v. Jones".encode())
        anchor = {"anchor_id": "a1", "case_id": "000001.txt", "source_hash": digest(raw),
                  "unit_id": "000001:p000001", "span_bytes": [0, end],
                  "text_sha256": digest(raw[:end]), "text": text[:14], "anchor_kind": "case_name"}
        self.add_case("000001.txt", text, single_span("000001.txt", raw, 0, len(raw)),
                      anchors=[anchor], source_anchors=[])
        session = self.make_session()
        identity = session.search_identity("SMITH V. JONES", "000001.txt", limit=1)
        self.assertEqual(identity["identity_status"], "observed_not_identity_verified")
        self.assertEqual(identity["hits"][0]["text"], "Smith v. Jones")
        self.assertEqual(identity["hits"][0]["anchor_refs"], [anchor])
        page = session.case_anchors("000001.txt", handle="p000001", limit=1)
        self.assertEqual(page["items"], [anchor])
        self.assertEqual(page["source_hash"], digest(raw))

    def test_each_search_hit_open_ref_can_be_passed_directly_to_open_source(self):
        text = "Smith v. Jones held the claim."
        raw = text.encode()
        self.add_case("000001.txt", text, single_span("000001.txt", raw, 0, len(raw)))
        session = self.make_session()
        search_results = [
            session.search_case("000001.txt", "held claim", mode="lexical"),
            session.search_case("000001.txt", "Smith v. Jones", mode="literal"),
            session.search_phrase("Smith v. Jones", "000001.txt"),
            session.search_identity("SMITH V. JONES", "000001.txt"),
        ]
        for result in search_results:
            with self.subTest(tool=result["tool"]):
                hit = result["hits"][0]
                opened = session.open_source(**hit["open_ref"])
                self.assertTrue(opened["fragments"])

    def test_missing_raw_source_invalidates_session(self):
        raw = b"still here"
        self.add_case("000001.txt", raw.decode(), single_span("000001.txt", raw, 0, len(raw)))
        session = self.make_session()
        (self.case_dir / "000001.txt").unlink()
        with self.assertRaises(FileNotFoundError):
            session.search_phrase("still", "000001.txt")
        with self.assertRaises(M3Error):
            session.case_anchors("000001.txt")


class OpenSourceTests(SourceToolsFixture):
    def test_query_case_can_be_mapped_searched_and_opened(self):
        text = "The query contains a cited holding."
        raw = text.encode()
        self.add_case("095448.txt", text, single_span("095448.txt", raw, 0, len(raw), unit_id="095448:unit:0"), passages=[{
            "passage_id": "095448:p1", "case_id": "095448.txt", "source_hash": digest(raw),
            "exact_input_sha256": digest(raw), "text_sha256": digest(raw), "text": text,
            "span_bytes": [0, len(raw)], "parent_unit_ids": ["095448:unit:0"], "parent_handle": "p0001",
        }])
        session = self.make_session()
        mapped = session.case_map("095448.txt")
        self.assertEqual(mapped["case_id"], "095448.txt")
        searched = session.search_case("095448.txt", "holding")
        self.assertTrue(searched["hits"])
        opened = session.open_source("095448.txt", digest(raw), passage_ids=["095448:p1"])
        self.assertEqual(opened["fragments"][0]["text"], text)

    def test_middle_hit_paginates_with_two_pending_parent_intervals_and_metadata(self):
        raw = ("prev context.\n" + "x" * 100 + "\nnext context.").encode()
        pstart, pend = len("prev context.\n".encode()), len("prev context.\n".encode()) + 100
        prev_start, prev_end = 0, pstart - 1
        next_start, next_end = pend + 1, len(raw)
        middle_start, middle_end = pstart + 50, pstart + 55
        ranges = [
            {"handle": "prev", "unit_id": "unit-prev", "span_bytes": [prev_start, prev_end],
             "paragraph_role": "quoted", "observed_marker": 4},
            {"handle": "parent", "unit_id": "unit-parent", "span_bytes": [pstart, pend],
             "paragraph_role": "unknown", "uncertainties": ["paragraph_ownership_unresolved"],
             "role_evidence_refs": ["evidence-1"], "language_region": "unknown:0"},
            {"handle": "next", "unit_id": "unit-next", "span_bytes": [next_start, next_end],
             "unit_kind": "unnumbered", "paragraph_role": None, "uncertainties": ["structure_unknown"]},
        ]
        self.add_case("000001.txt", raw.decode(), ranges,
                      headings=[{"unit_id": "heading-1", "span_bytes": [pstart - 1, pstart], "text": "\n"}])
        session = self.make_session()
        first = session.open_source("000001.txt", digest(raw), hit_spans=[[middle_start, middle_end]], byte_budget=15)
        self.assertEqual(first["delivered_spans"][0][0], middle_start)
        self.assertGreaterEqual(len(first["pending_spans"]), 2)
        pending = first["pending_spans"]
        self.assertTrue(any(span[1] <= middle_start for span in pending))
        self.assertTrue(any(span[0] >= middle_end for span in pending))
        components = first["components"]
        parent = next(component for component in components if component.get("handle") == "parent")
        self.assertEqual(parent["paragraph_role"], "unknown")
        self.assertEqual(parent["uncertainties"], ["paragraph_ownership_unresolved"])
        previous = next(component for component in components if component.get("handle") == "prev")
        self.assertEqual(previous["paragraph_role"], "quoted")
        following = next(component for component in components if component.get("handle") == "next")
        self.assertEqual(following["unit_kind"], "unnumbered")

        cursor = first["next_cursor"]
        seen = list(first["delivered_spans"])
        last = first
        while cursor is not None:
            last = session.open_source("000001.txt", digest(raw), hit_spans=[[middle_start, middle_end]],
                                       byte_budget=15, cursor=cursor)
            seen.extend(last["delivered_spans"])
            cursor = last["next_cursor"]
        self.assertTrue(last["complete"])
        requested = last["requested_spans"]
        self.assertEqual(union_intervals(seen), requested)
        self.assertFalse(last["token_safe_agent_payload"])
        self.assertFalse(last["M4_delivery_recorded"])
        self.assertTrue(last["hit_refs"])
        for hit_delivery in last["hit_refs"]:
            self.assertIn("kind", hit_delivery)
            self.assertIn("span_bytes", hit_delivery)
            self.assertIn("delivered_spans", hit_delivery)
            self.assertIn("pending_spans", hit_delivery)

    def test_full_open_fragments_follow_raw_source_order_and_keep_m1_heading_whitespace(self):
        text = "left HEADER right"
        raw = text.encode()
        headings = [{"unit_id": "heading-1", "span_bytes": [5, 11], "text": "HEADER",
                     "language_region": "fr:0", "order": 1}]
        extra = [
            {"unit_id": "whitespace-1", "unit_kind": "whitespace", "span_bytes": [4, 5],
             "language_region": "unknown:0", "order": 1},
            {"unit_id": "whitespace-2", "unit_kind": "whitespace", "span_bytes": [11, 12],
             "language_region": "unknown:0", "order": 3},
        ]
        ranges = [
            {"handle": "left", "unit_id": "left-unit", "span_bytes": [0, 4], "language_region": "en:0"},
            {"handle": "right", "unit_id": "right-unit", "span_bytes": [12, len(raw)], "language_region": "en:0"},
        ]
        self.add_case("000001.txt", text, ranges, headings=headings, m1_extra_units=extra)
        session = self.make_session()
        result = session.open_source("000001.txt", digest(raw), hit_spans=[[5, 11]], byte_budget=65536)
        reconstructed = "".join(fragment["text"] for fragment in result["fragments"])
        self.assertEqual(reconstructed, raw[result["requested_spans"][0][0]:result["requested_spans"][0][1]].decode())
        components = result["components"]
        self.assertEqual([item["span_bytes"] for item in components], [[0, 4], [4, 5], [5, 11], [11, 12], [12, 17]])
        heading = next(item for item in components if item["unit_kind"] == "heading")
        self.assertEqual(heading["language_region"], "fr:0")
        self.assertEqual(heading["order"], 2)
        whitespace = [item for item in components if item["unit_kind"] == "whitespace"]
        self.assertEqual([item["language_region"] for item in whitespace], ["unknown:0", "unknown:0"])

    def test_open_deduplicates_intervals_preserves_hit_mapping_and_rejects_utf8_no_progress(self):
        text = "éclair and more text"
        raw = text.encode("utf-8")
        self.add_case("000001.txt", text, single_span("000001.txt", raw, 0, len(raw)))
        session = self.make_session()
        opened = session.open_source("000001.txt", digest(raw), handles=["p000001"],
                                     hit_spans=[[0, 2], [0, 2]], byte_budget=64)
        self.assertEqual(opened["requested_spans"], [[0, len(raw)]])
        self.assertEqual(len(opened["hit_refs"]), 2)
        self.assertEqual(opened["fragments"][0]["text"], text)
        with self.assertRaisesRegex(M3Error, "UTF-8 codepoint"):
            session.open_source("000001.txt", digest(raw), hit_spans=[[0, 2]], byte_budget=1)
        with self.assertRaises(M3Error):
            session.open_source("000001.txt", digest(raw), hit_spans=[[0, 2]], byte_budget=True)

    def test_open_cursor_binds_hash_and_raw_offsets_are_codepoint_boundaries(self):
        text = "A é B C D E F G"
        raw = text.encode("utf-8")
        self.add_case("000001.txt", text, single_span("000001.txt", raw, 0, len(raw)))
        session = self.make_session()
        first = session.open_source("000001.txt", digest(raw), hit_spans=[[0, 1]], byte_budget=2)
        self.assertIsNotNone(first["next_cursor"])
        with self.assertRaises(M3Error):
            session.open_source("000001.txt", digest(raw), hit_spans=[[3, 4]],
                                byte_budget=2, cursor=first["next_cursor"])
        with self.assertRaises(M3Error):
            session.open_source("000001.txt", "0" * 64, hit_spans=[[0, 1]],
                                byte_budget=2, cursor=first["next_cursor"])
        with self.assertRaises(M3Error):
            session.open_source("000001.txt", digest(raw), hit_spans=[[2, 3]], byte_budget=2)


if __name__ == "__main__":
    unittest.main()
