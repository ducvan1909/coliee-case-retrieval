"""Independent full-corpus audit and preview/context quality diagnostic scanner for M2 navigation.

Does NOT use pipeline_v2.navigation builder/validator functions as oracle.
Reads M0, M1, M2 bundles and raw corpus bytes directly.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import time

PLACEHOLDER_RE = re.compile(r"[<(]?(?:FRAGMENT|REFERENCE)_SUPPRESSED[>)]?")
MARKER_RE = re.compile(r"^\[[0-9]+\]")
ABBREV_ENDING_RE = re.compile(
    r"(?:^|[\s(\[])(?:"
    r"Mr|Ms|Mrs|Dr|Prof|Hon|Just|J|JJ|C\.J|A\.C\.J|Prothonotary|"
    r"No|Nos|v|vs|c|s|ss|para|paras|par|art|al|ch|pt|div|sched|reg|regs|"
    r"Inc|Ltd|Corp|Co|St|Ste|Ave|Rd|Blvd|Dept|Min|Gov|Assn|Fed|"
    r"Can|Imm|Ref|Cit|Crim|Admin|Lab|Tax|Pat|Env|"
    r"R\.S\.C|S\.C|S\.O\.R|C\.R\.C|F\.C|F\.C\.A|F\.C\.J|F\.C\.T\.D|S\.C\.C|S\.C\.R|D\.L\.R|N\.R|A\.C\.W\.S|W\.C\.B|I\.A\.C|"
    r"e\.g|i\.e|etc|cf|et\s+al|viz|approx|"
    r"[A-Z]|[0-9]+"
    r")\.$"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_seal(bundle_dir: Path, expected_schema: str) -> dict:
    seal_path = bundle_dir / "seal.json"
    seal = load_json(seal_path)
    if seal.get("schema_version") != expected_schema:
        raise AssertionError(f"Unexpected seal schema in {bundle_dir}: {seal.get('schema_version')}")
    files = seal.get("files", {})
    actual_files = {
        p.relative_to(bundle_dir).as_posix()
        for p in bundle_dir.rglob("*")
        if p.is_file()
    }
    if actual_files != set(files.keys()) | {"seal.json"}:
        missing = (set(files.keys()) | {"seal.json"}) - actual_files
        extra = actual_files - (set(files.keys()) | {"seal.json"})
        raise AssertionError(f"Bundle file set mismatch in {bundle_dir}: missing={missing}, extra={extra}")
    for rel_path, meta in files.items():
        raw = (bundle_dir / rel_path).read_bytes()
        if len(raw) != meta["byte_length"] or sha256_bytes(raw) != meta["sha256"]:
            raise AssertionError(f"Seal mismatch for {bundle_dir / rel_path}")
    return seal


def build_utf8_char_to_byte(raw: bytes) -> tuple[str, list[int]]:
    text = raw.decode("utf-8", errors="strict")
    n = len(text)
    if len(raw) == n:
        return text, list(range(n + 1))
    char_to_byte = [0] * (n + 1)
    b_pos = 0
    for idx, ch in enumerate(text):
        code = ord(ch)
        if code < 0x80:
            b_pos += 1
        elif code < 0x800:
            b_pos += 2
        elif code < 0x10000:
            b_pos += 3
        else:
            b_pos += 4
        char_to_byte[idx + 1] = b_pos
    return text, char_to_byte


def simulate_opening_start(text: str, start: int, end: int) -> tuple[int | None, int, bool]:
    """Return (opening_start_char, skipped_lines_count, first_unskipped_is_placeholder_punct_only)."""
    pos = start
    if pos < end and text[pos] == "\ufeff":
        pos += 1
    marker = MARKER_RE.match(text[pos:end])
    if marker:
        pos += marker.end()
    skipped_lines = 0
    while pos < end:
        line_end = text.find("\n", pos, end)
        line_end = end if line_end < 0 else line_end
        value = text[pos:line_end]
        stripped_no_ph = PLACEHOLDER_RE.sub("", value).strip()
        if value.strip() and stripped_no_ph:
            pos += len(value) - len(value.lstrip())
            has_alnum = any(ch.isalnum() for ch in stripped_no_ph)
            has_ph = bool(PLACEHOLDER_RE.search(value))
            return (pos if pos < end else None), skipped_lines, (has_ph and not has_alnum)
        skipped_lines += 1
        pos = min(end, line_end + 1)
    return None, skipped_lines, False


def main():
    started = time.perf_counter()
    repo_root = Path(".").resolve()
    m0_dir = repo_root / "pipeline_v2/artifacts/m0_20261105_v2"
    m1_dir = repo_root / "pipeline_v2/artifacts/m1_20261105_v2"
    m2_dir = repo_root / "pipeline_v2/artifacts/m2_navigation_20261105_v1"
    profile_path = repo_root / "pipeline_v2/configs/m2.json"

    # 1. Verify seals, manifests, code fingerprints, and universe consistency
    m0_seal = verify_seal(m0_dir, "pipeline-v2-m0-seal-1")
    m1_seal = verify_seal(m1_dir, "pipeline-v2-m1-seal-2")
    m2_seal = verify_seal(m2_dir, "pipeline-v2-m2-navigation-seal-1")

    m0_inventory = load_json(m0_dir / "inventory.json")
    m0_candidates = load_json(m0_dir / "candidate_manifest.json")
    m1_manifest = load_json(m1_dir / "manifest.json")
    m1_registry = load_json(m1_dir / "source_registry.json")
    m2_manifest = load_json(m2_dir / "manifest.json")
    m2_registry = load_json(m2_dir / "source_registry.json")
    m2_summary = load_json(m2_dir / "summary.json")
    profile = load_json(profile_path)
    profile_sha = sha256_bytes(profile_path.read_bytes())
    expected_profile_hash = sha256_bytes(canonical_bytes(profile))

    assert m2_manifest["profile_sha256"] == profile_sha, "M2 profile_sha256 mismatch"
    assert m2_manifest["profile"] == profile, "M2 embedded profile mismatch"
    assert m2_manifest["labels_accessed"] is False, "labels_accessed must be False"
    assert m2_manifest["test_sources_accessed"] is False, "test_sources_accessed must be False"
    assert m2_manifest["raw_corpus_copied"] is False, "raw_corpus_copied must be False"
    assert m2_manifest["m1"] == {
        "bundle": "pipeline_v2/artifacts/m1_20261105_v2",
        "seal_sha256": sha256_bytes((m1_dir / "seal.json").read_bytes()),
        "manifest_sha256": sha256_bytes((m1_dir / "manifest.json").read_bytes()),
        "registry_sha256": sha256_bytes((m1_dir / "source_registry.json").read_bytes()),
    }, "M2->M1 provenance mismatch"

    expected_impl_files = [
        "pipeline_v2/m2.py",
        "pipeline_v2/navigation/__init__.py",
        "pipeline_v2/navigation/core.py",
        "pipeline_v2/navigation/store.py",
    ]
    for rel in expected_impl_files:
        actual_sha = sha256_bytes((repo_root / rel).read_bytes())
        assert m2_manifest["implementation"].get(rel) == actual_sha, f"Code fingerprint drift on {rel}"

    m0_cases = {r["case_id"]: r for r in m0_inventory["sources"]}
    assert set(m0_candidates["candidate_ids"]) == set(m0_cases), "M0 candidate_ids vs inventory mismatch"
    m1_cases = {r["case_id"]: r for r in m1_registry["sources"]}
    m2_cases = {r["case_id"]: r for r in m2_registry["sources"]}
    assert set(m0_cases) == set(m1_cases) == set(m2_cases), "Universe mismatch across M0/M1/M2"
    assert len(m2_cases) == 7708, f"Expected 7708 cases, got {len(m2_cases)}"

    counts = Counter()
    quality_stats = Counter()
    anomalies = defaultdict(list)
    case_metadata_for_sampling = {}

    for case_id in sorted(m2_cases):
        m0_row = m0_cases[case_id]
        m1_row = m1_cases[case_id]
        m2_row = m2_cases[case_id]

        raw_path = repo_root / m1_row["path"]
        raw = raw_path.read_bytes()
        raw_sha = sha256_bytes(raw)
        assert raw_sha == m0_row["sha256"] == m1_row["raw_sha256"] == m2_row["source_hash"], f"Hash mismatch for {case_id}"

        m1_record = load_json(m1_dir / m1_row["structure_ref"])
        m2_record_path = m2_dir / m2_row["navigation_ref"]
        m2_record_bytes = m2_record_path.read_bytes()
        m2_record = json.loads(m2_record_bytes.decode("utf-8"))

        assert m2_row["navigation_sha256"] == sha256_bytes(m2_record_bytes), f"Registry sha mismatch for {case_id}"
        assert m2_record["case_id"] == case_id
        assert m2_record["source_hash"] == raw_sha
        assert m2_record["profile_hash"] == expected_profile_hash
        assert m2_record["m1_structure_sha256"] == sha256_bytes(canonical_bytes(m1_record))
        assert m2_record["readiness"] == {
            "navigation": "ready",
            "token_counts": "not_ready",
            "token_validated_chunks": "not_ready",
        }

        text, char_to_byte = build_utf8_char_to_byte(raw)
        units = m1_record["units"]
        content_units = [u for u in units if u["unit_kind"] in ("paragraph", "unnumbered")]
        para_units = [u for u in content_units if u["unit_kind"] == "paragraph"]
        heading_units = [u for u in units if u["unit_kind"] == "heading"]

        nav_rows = m2_record["navigation"]
        assert len(nav_rows) == len(content_units) == m2_row["navigation_units"], f"Unit count mismatch in {case_id}"
        assert [r["unit_id"] for r in nav_rows] == [u["unit_id"] for u in content_units], f"Unit order mismatch in {case_id}"

        # Check handles format and uniqueness
        expected_handles = [
            f"{'p' if u['unit_kind'] == 'paragraph' else 'u'}{idx + 1:06d}"
            for idx, u in enumerate(content_units)
        ]
        assert [r["handle"] for r in nav_rows] == expected_handles, f"Handle sequence mismatch in {case_id}"

        row_by_unit = {r["unit_id"]: r for r in nav_rows}
        row_by_handle = {r["handle"]: r for r in nav_rows}

        # Check headings preservation & literal provenance
        m2_headings = m2_record["headings"]
        assert len(m2_headings) == len(heading_units), f"Heading count mismatch in {case_id}"
        heading_by_id = {}
        for h_m1, h_m2 in zip(heading_units, m2_headings):
            assert h_m1["unit_id"] == h_m2["unit_id"]
            a, b = h_m1["span_bytes"]
            assert h_m2["span_bytes"] == [a, b]
            assert h_m2["heading_scope"] == h_m1["heading_scope"]
            assert h_m2["uncertainties"] == h_m1["uncertainties"]
            assert h_m2["text"] == raw[a:b].decode("utf-8")
            assert h_m2["text_sha256"] == sha256_bytes(raw[a:b])
            heading_by_id[h_m2["unit_id"]] = h_m2

        # Check source_anchors against M1 sidecars
        expected_cue_spans = sorted({
            tuple(ref["span_bytes"])
            for rel in m1_record.get("sidecars", [])
            for ref in rel.get("attribution_cue_refs", [])
        })
        source_anchors = m2_record["source_anchors"]
        assert len(source_anchors) == len(expected_cue_spans), f"Source anchor count mismatch in {case_id}"
        source_anchor_by_id = {}
        heading_only_cues_in_case = 0
        cross_unit_cues_in_case = 0
        long_cues_in_case = 0
        for idx, (a, b) in enumerate(expected_cue_spans):
            sa = source_anchors[idx]
            assert sa["source_anchor_id"] == f"q{idx + 1:06d}"
            assert sa["case_id"] == case_id
            assert sa["source_hash"] == raw_sha
            assert sa["anchor_kind"] == "quote_introduction_candidate"
            assert sa["span_bytes"] == [a, b]
            assert sa["text_sha256"] == sha256_bytes(raw[a:b])
            ca_idx = bisect_left(char_to_byte, a)
            cb_idx = bisect_left(char_to_byte, b)
            assert char_to_byte[ca_idx] == a and char_to_byte[cb_idx] == b
            expected_u_refs = [u["unit_id"] for u in units if u["span_bytes"][0] < b and a < u["span_bytes"][1]]
            assert sa["unit_refs"] == expected_u_refs
            source_anchor_by_id[sa["source_anchor_id"]] = sa

            content_u_refs = [u["unit_id"] for u in content_units if u["span_bytes"][0] < b and a < u["span_bytes"][1]]
            if not content_u_refs:
                heading_only_cues_in_case += 1
                quality_stats["source_cues_heading_or_whitespace_only"] += 1
                anomalies["heading_or_whitespace_only_cues"].append({
                    "case_id": case_id,
                    "source_anchor_id": sa["source_anchor_id"],
                    "span_bytes": [a, b],
                    "unit_refs": expected_u_refs,
                    "text": raw[a:b].decode("utf-8"),
                })
            if len(content_u_refs) > 1 or len(expected_u_refs) > 1:
                cross_unit_cues_in_case += 1
                quality_stats["source_cues_multi_unit"] += 1
                if len(content_u_refs) > 1:
                    quality_stats["source_cues_multi_content_unit"] += 1
                    anomalies["multi_content_unit_cues"].append({
                        "case_id": case_id,
                        "source_anchor_id": sa["source_anchor_id"],
                        "span_bytes": [a, b],
                        "content_unit_refs": content_u_refs,
                    })
            cue_char_len = cb_idx - ca_idx
            if cue_char_len > 120:
                long_cues_in_case += 1
                quality_stats["source_cues_over_120_chars"] += 1
            if cue_char_len > 240:
                quality_stats["source_cues_over_240_chars"] += 1

        # Previews and unit anchors lookup
        previews_by_id = {p["preview_id"]: p for p in m2_record["previews"]}
        anchors_by_id = {a["anchor_id"]: a for a in m2_record["anchors"]}
        assert len(previews_by_id) == len(m2_record["previews"])
        assert len(anchors_by_id) == len(m2_record["anchors"])

        para_index_by_unit = {u["unit_id"]: idx for idx, u in enumerate(para_units)}
        case_short_abbrev_previews = 0
        case_over_display_limit_units = 0
        case_repeated_markers = 0
        seen_markers = set()
        marker_jumps = 0
        prev_marker_val = None

        for idx, (unit, row) in enumerate(zip(content_units, nav_rows)):
            u_id = unit["unit_id"]
            handle = row["handle"]
            u_bs, u_be = unit["span_bytes"]
            u_cs, u_ce = unit["span_chars"]
            assert row["case_id"] == case_id
            assert row["source_hash"] == raw_sha
            assert row["source_order"] == unit["order"]
            assert row["span_bytes"] == [u_bs, u_be]
            assert row["unit_kind"] == unit["unit_kind"]
            assert row["observed_marker"] == unit.get("observed_marker")
            assert row["section_refs"] == unit["section_path_refs"]
            assert all(h_ref in heading_by_id for h_ref in row["section_refs"])
            assert row["paragraph_role"] == unit.get("paragraph_role")
            assert row["uncertainties"] == unit["uncertainties"]
            assert row["role_evidence_refs"] == unit.get("role_evidence_refs", [])
            assert row["language_region"] == unit["language_region"]
            assert row["token_count"] is None
            assert "read_state" not in row and "Open" not in row
            assert row["parent_container_refs"] == [{"unit_id": u_id, "span_bytes": [u_bs, u_be]}]

            if str(unit["language_region"]).startswith("fr:"):
                quality_stats["french_content_units_preserved"] += 1

            # Check marker jumps/repeats
            m_val = row["observed_marker"]
            if m_val is not None:
                if m_val in seen_markers:
                    case_repeated_markers += 1
                    quality_stats["repeated_marker_units"] += 1
                seen_markers.add(m_val)
                if prev_marker_val is not None and m_val != prev_marker_val + 1:
                    marker_jumps += 1
                    quality_stats["non_sequential_marker_transitions"] += 1
                prev_marker_val = m_val

            # Check neighbor links
            exp_prev_content = nav_rows[idx - 1]["handle"] if idx > 0 else None
            exp_next_content = nav_rows[idx + 1]["handle"] if idx + 1 < len(nav_rows) else None
            assert row["previous_content_ref"] == exp_prev_content
            assert row["next_content_ref"] == exp_next_content

            if unit["unit_kind"] == "paragraph":
                p_idx = para_index_by_unit[u_id]
                exp_prev_para = row_by_unit[para_units[p_idx - 1]["unit_id"]]["handle"] if p_idx > 0 else None
                exp_next_para = row_by_unit[para_units[p_idx + 1]["unit_id"]]["handle"] if p_idx + 1 < len(para_units) else None
                assert row["previous_paragraph_ref"] == exp_prev_para
                assert row["next_paragraph_ref"] == exp_next_para
                assert row["reading_expansion"] == {
                    "parent_ref": handle,
                    "previous_ref": exp_prev_para,
                    "next_ref": exp_next_para,
                    "neighbor_policy": "paragraph_order",
                    "previous_absence_reason": None if exp_prev_para else "source_boundary",
                    "next_absence_reason": None if exp_next_para else "source_boundary",
                }
                counts["paragraph_neighbor_links"] += (exp_prev_para is not None) + (exp_next_para is not None)
            else:
                # unnumbered unit
                prior_paras = [p for p in para_units if p["order"] < unit["order"]]
                next_paras = [p for p in para_units if p["order"] > unit["order"]]
                exp_prev_para = row_by_unit[prior_paras[-1]["unit_id"]]["handle"] if prior_paras else None
                exp_next_para = row_by_unit[next_paras[0]["unit_id"]]["handle"] if next_paras else None
                assert row["previous_paragraph_ref"] == exp_prev_para
                assert row["next_paragraph_ref"] == exp_next_para
                assert row["reading_expansion"] == {
                    "parent_ref": handle,
                    "previous_ref": exp_prev_content,
                    "next_ref": exp_next_content,
                    "neighbor_policy": "content_unit_order",
                    "previous_absence_reason": None if exp_prev_content else "source_boundary",
                    "next_absence_reason": None if exp_next_content else "source_boundary",
                }
                counts["unnumbered_neighbor_links"] += (exp_prev_content is not None) + (exp_next_content is not None)

            # Check unit anchors
            expected_unit_anchors = []
            for m in PLACEHOLDER_RE.finditer(text, u_cs, u_ce):
                expected_unit_anchors.append((
                    char_to_byte[m.start()],
                    char_to_byte[m.end()],
                    "placeholder",
                    "literal_fragment_or_reference_placeholder_v1",
                    None,
                    None,
                ))
            for sa in source_anchors:
                sa_a, sa_b = sa["span_bytes"]
                if u_bs < sa_b and sa_a < u_be:
                    expected_unit_anchors.append((
                        max(u_bs, sa_a),
                        min(u_be, sa_b),
                        "quote_introduction_candidate",
                        "M1_local_quote_cue_reference",
                        sa["source_anchor_id"],
                        [sa_a, sa_b],
                    ))
            expected_unit_anchors = sorted(set(
                (a, b, kind, method, sref, tuple(orig) if orig else None)
                for a, b, kind, method, sref, orig in expected_unit_anchors
            ))
            assert len(row["anchor_refs"]) == len(expected_unit_anchors), f"Anchor count mismatch in {case_id} {handle}"
            unit_anchor_objs = []
            for a_idx, (aa, ab, akind, amethod, asref, aorig) in enumerate(expected_unit_anchors):
                a_id = row["anchor_refs"][a_idx]
                assert a_id == f"{handle}:a{a_idx + 1:04d}"
                a_obj = anchors_by_id[a_id]
                assert a_obj["unit_id"] == u_id
                assert a_obj["case_id"] == case_id
                assert a_obj["source_hash"] == raw_sha
                assert a_obj["anchor_kind"] == akind
                assert a_obj["span_bytes"] == [aa, ab]
                assert a_obj["text_sha256"] == sha256_bytes(raw[aa:ab])
                assert a_obj["selection_method"] == amethod
                assert a_obj["source_anchor_ref"] == asref
                assert a_obj["original_cue_span_bytes"] == (list(aorig) if aorig else None)
                unit_anchor_objs.append(a_obj)

            # Check previews for this unit
            assert len(row["preview_refs"]) <= 2
            if not row["preview_refs"]:
                assert row["preview_absence_reason"] == "no_meaningful_opening_or_anchor"
                anomalies["units_without_preview"].append({
                    "case_id": case_id,
                    "handle": handle,
                    "unit_id": u_id,
                    "unit_kind": row["unit_kind"],
                    "observed_marker": row["observed_marker"],
                    "span_bytes": [u_bs, u_be],
                    "raw_text": raw[u_bs:u_be].decode("utf-8"),
                })
            else:
                assert row["preview_absence_reason"] is None

            unit_previews = [previews_by_id[p_id] for p_id in row["preview_refs"]]
            visible_anchor_ids = set()
            fully_visible_anchor_ids = set()

            sim_open_start, skipped_lines, ph_punct_only = simulate_opening_start(text, u_cs, u_ce)
            if skipped_lines > 0:
                quality_stats["units_with_skipped_leading_lines"] += 1
            if ph_punct_only:
                quality_stats["units_with_placeholder_punct_only_first_line"] += 1
                anomalies["placeholder_punct_only_opening_lines"].append({
                    "case_id": case_id,
                    "handle": handle,
                    "unit_id": u_id,
                    "span_bytes": [u_bs, u_be],
                    "preview_texts": [p["text"] for p in unit_previews],
                    "raw_text_head": text[u_cs:min(u_ce, u_cs + 300)],
                })

            for p_idx, p_obj in enumerate(unit_previews):
                assert p_obj["preview_id"] == f"{handle}:v{p_idx + 1:02d}"
                assert p_obj["case_id"] == case_id
                assert p_obj["source_hash"] == raw_sha
                assert p_obj["unit_id"] == u_id
                assert p_obj["preview_profile_hash"] == expected_profile_hash
                assert p_obj["token_count"] is None
                p_bs, p_be = p_obj["span_bytes"]
                p_cs, p_ce = p_obj["span_chars"]
                assert u_bs <= p_bs < p_be <= u_be
                assert char_to_byte[p_cs] == p_bs and char_to_byte[p_ce] == p_be
                exact_slice = raw[p_bs:p_be].decode("utf-8")
                assert p_obj["text"] == exact_slice
                assert p_obj["text_sha256"] == sha256_bytes(raw[p_bs:p_be])
                assert 1 <= len(exact_slice) <= 240

                # Verify anchor_refs and anchor_visibility
                exp_vis = []
                for a_obj in unit_anchor_objs:
                    aa, ab = a_obj["span_bytes"]
                    if p_bs < ab and aa < p_be:
                        visible_anchor_ids.add(a_obj["anchor_id"])
                        full = (p_bs <= aa and ab <= p_be)
                        if full:
                            fully_visible_anchor_ids.add(a_obj["anchor_id"])
                        orig = a_obj["original_cue_span_bytes"]
                        src_full = None if orig is None else (p_bs <= orig[0] and orig[1] <= p_be)
                        exp_vis.append({
                            "anchor_ref": a_obj["anchor_id"],
                            "fully_visible": full,
                            "source_cue_fully_visible": src_full,
                            "visibility": "full" if full else "partial",
                        })
                        if not full:
                            quality_stats["partial_anchor_visibilities"] += 1
                        if src_full is False:
                            quality_stats["partial_source_cue_visibilities"] += 1
                assert p_obj["anchor_refs"] == [v["anchor_ref"] for v in exp_vis]
                assert p_obj["anchor_visibility"] == exp_vis

                # Preview quality checks
                quality_stats[f"preview_kind_{p_obj['preview_kind']}"] += 1
                if p_obj["partial_sentence"]:
                    quality_stats[f"partial_sentence_{p_obj['preview_kind']}"] += 1

                if p_obj["preview_kind"] == "opening":
                    rem_after_preview = text[p_ce:u_ce].strip()
                    if rem_after_preview:
                        if len(exact_slice) <= 30:
                            quality_stats["opening_preview_le_30_chars_with_more_text"] += 1
                            if len(anomalies["very_short_opening_previews_sample"]) < 200:
                                anomalies["very_short_opening_previews_sample"].append({
                                    "case_id": case_id,
                                    "handle": handle,
                                    "unit_id": u_id,
                                    "span_bytes": [p_bs, p_be],
                                    "preview_text": exact_slice,
                                    "partial_sentence": p_obj["partial_sentence"],
                                    "unit_continuation": text[p_ce:min(u_ce, p_ce + 160)],
                                })
                        if ABBREV_ENDING_RE.search(exact_slice):
                            quality_stats["opening_preview_clipped_at_abbreviation"] += 1
                            case_short_abbrev_previews += 1
                            if not p_obj["partial_sentence"]:
                                quality_stats["opening_preview_clipped_at_abbrev_marked_complete"] += 1
                            if len(anomalies["abbreviation_clipped_opening_previews_sample"]) < 200:
                                anomalies["abbreviation_clipped_opening_previews_sample"].append({
                                    "case_id": case_id,
                                    "handle": handle,
                                    "unit_id": u_id,
                                    "span_bytes": [p_bs, p_be],
                                    "preview_text": exact_slice,
                                    "partial_sentence": p_obj["partial_sentence"],
                                    "unit_continuation": text[p_ce:min(u_ce, p_ce + 160)],
                                })

            # Check overlapping opening + anchor preview slot waste
            if len(unit_previews) == 2:
                p0, p1 = unit_previews[0], unit_previews[1]
                c0s, c0e = p0["span_chars"]
                c1s, c1e = p1["span_chars"]
                if c0s < c1e and c1s < c0e:
                    quality_stats["units_with_two_overlapping_previews"] += 1
                    kinds = {p0["preview_kind"], p1["preview_kind"]}
                    if kinds == {"opening", "anchor"}:
                        quality_stats["units_with_overlapping_opening_and_anchor_preview"] += 1
                        open_p = p0 if p0["preview_kind"] == "opening" else p1
                        anch_p = p1 if p0["preview_kind"] == "opening" else p0
                        union_from_opening = max(open_p["span_chars"][1], anch_p["span_chars"][1]) - open_p["span_chars"][0]
                        if anch_p["span_chars"][0] < open_p["span_chars"][0] and union_from_opening <= 240:
                            quality_stats["units_where_anchor_failed_merge_due_to_marker_prefix"] += 1
                            if len(unit_anchor_objs) > len(visible_anchor_ids):
                                quality_stats["units_where_marker_prefix_unmerged_anchor_crowded_out_later_anchor"] += 1
                                if len(anomalies["marker_prefix_crowded_out_later_anchor_sample"]) < 100:
                                    anomalies["marker_prefix_crowded_out_later_anchor_sample"].append({
                                        "case_id": case_id,
                                        "handle": handle,
                                        "unit_id": u_id,
                                        "total_anchors": len(unit_anchor_objs),
                                        "visible_anchors": len(visible_anchor_ids),
                                        "opening_preview_span_chars": open_p["span_chars"],
                                        "anchor_preview_span_chars": anch_p["span_chars"],
                                        "opening_text": open_p["text"],
                                        "anchor_text": anch_p["text"],
                                    })

            unshown_count = len(unit_anchor_objs) - len(visible_anchor_ids)
            if unshown_count > 0:
                quality_stats["units_with_unshown_anchors_in_previews"] += 1
                quality_stats["total_anchors_unshown_in_previews"] += unshown_count
                case_over_display_limit_units += 1

        count_case_summary(counts, m2_record)
        case_metadata_for_sampling[case_id] = {
            "case_id": case_id,
            "byte_length": len(raw),
            "navigation_units": len(nav_rows),
            "paragraphs": len(para_units),
            "unnumbered": len(content_units) - len(para_units),
            "headings": len(m2_headings),
            "anchors": len(m2_record["anchors"]),
            "source_quote_cues": len(source_anchors),
            "over_display_limit_units": case_over_display_limit_units,
            "long_or_cross_or_heading_cues": long_cues_in_case + cross_unit_cues_in_case + heading_only_cues_in_case,
            "short_or_abbrev_previews": case_short_abbrev_previews,
            "repeated_markers": case_repeated_markers,
            "marker_jumps": marker_jumps,
        }

    # Verify summary counts match exactly
    expected_summary_keys = {
        "sources": counts["sources"],
        "navigation_units": counts["navigation_units"],
        "previews": counts["previews"],
        "anchors": counts["anchors"],
        "source_quote_cues": counts["source_quote_cues"],
        "headings": counts["headings"],
        "units_without_preview": counts["units_without_preview"],
        "unknown_paragraphs": counts["unknown_paragraphs"],
        "kind_paragraph": counts["kind_paragraph"],
        "kind_unnumbered": counts["kind_unnumbered"],
        "anchor_placeholder": counts["anchor_placeholder"],
        "anchor_quote_introduction_candidate": counts["anchor_quote_introduction_candidate"],
    }
    assert m2_summary["counts"] == expected_summary_keys, f"Summary counts mismatch: {m2_summary['counts']} vs {expected_summary_keys}"
    assert m2_summary["readiness"] == {
        "navigation": "ready",
        "preview_provenance": "ready",
        "parent_context_mapping": "ready",
        "token_validated_chunks": "not_ready",
        "token_counts": "not_ready",
        "agent_payload_budget": "not_ready",
        "dense": "not_ready",
    }
    assert m2_summary["chunk_manifest_generated"] is False
    assert m2_summary["M3_or_later_executed"] is False

    elapsed = round(time.perf_counter() - started, 3)
    output_dir = repo_root / "pipeline_v2/reviews/m2_navigation_ag_review_v1"
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_result = {
        "schema_version": "pipeline-v2-m2-ag-independent-audit-1",
        "valid": True,
        "elapsed_seconds": elapsed,
        "verified_counts": dict(counts),
        "quality_diagnostics": dict(quality_stats),
        "anomalies_summary": {k: len(v) for k, v in anomalies.items()},
        "anomalies": dict(anomalies),
    }
    (output_dir / "machine_audit_results.json").write_text(
        json.dumps(audit_result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "case_metadata_index.json").write_text(
        json.dumps(case_metadata_for_sampling, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "valid": True,
        "elapsed_seconds": elapsed,
        "verified_counts": dict(counts),
        "quality_diagnostics": dict(quality_stats),
        "anomalies_summary": {k: len(v) for k, v in anomalies.items()},
    }, indent=2, sort_keys=True))


def count_case_summary(counts: Counter, record: dict):
    counts["sources"] += 1
    counts["navigation_units"] += len(record["navigation"])
    counts["previews"] += len(record["previews"])
    counts["anchors"] += len(record["anchors"])
    counts["source_quote_cues"] += len(record["source_anchors"])
    counts["headings"] += len(record["headings"])
    counts["units_without_preview"] += sum(not r["preview_refs"] for r in record["navigation"])
    counts["unknown_paragraphs"] += sum(r["paragraph_role"] == "unknown" for r in record["navigation"])
    counts.update("kind_" + r["unit_kind"] for r in record["navigation"])
    counts.update("anchor_" + a["anchor_kind"] for a in record["anchors"])


if __name__ == "__main__":
    main()
