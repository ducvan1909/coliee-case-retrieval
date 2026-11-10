"""Independent raw/M1-to-M2 navigation bundle audit; does not import M2 code."""
import argparse
import hashlib
import json
import re
from pathlib import Path


PLACEHOLDER = re.compile(r"[<(]?(?:FRAGMENT|REFERENCE)_SUPPRESSED[>)]?")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def audit(repo, m1_bundle, m2_bundle):
    repo = Path(repo).resolve()
    m1_bundle = (repo / m1_bundle).resolve()
    m2_bundle = (repo / m2_bundle).resolve()
    m1_registry = load(m1_bundle / "source_registry.json")
    m2_registry = load(m2_bundle / "source_registry.json")
    m2_manifest = load(m2_bundle / "manifest.json")
    require(m2_manifest.get("labels_accessed") is False, "M2 manifest claims label access")
    require(m2_manifest.get("test_sources_accessed") is False, "M2 manifest claims test-source access")
    m1_rows = {row["case_id"]: row for row in m1_registry["sources"]}
    m2_rows = {row["case_id"]: row for row in m2_registry["sources"]}
    require(set(m1_rows) == set(m2_rows), "M1/M2 case universes differ")

    checked = {"cases": 0, "content_units": 0, "paragraphs": 0, "unknown_paragraphs": 0,
               "unnumbered_units": 0, "headings": 0, "previews": 0, "anchors": 0,
               "source_quote_cues": 0, "placeholder_occurrences": 0, "neighbor_links": 0}
    errors = []
    for case_id in sorted(m1_rows):
        m1_ref = m1_rows[case_id]["structure_ref"]
        m1 = load(m1_bundle / m1_ref)
        m2_ref = m2_rows[case_id]["navigation_ref"]
        m2 = load(m2_bundle / m2_ref)
        raw_path = repo / m1_rows[case_id]["path"]
        raw = raw_path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
        source_hash = sha(raw)
        require(source_hash == m1_rows[case_id]["raw_sha256"], f"{case_id}: raw hash differs from M1 registry")
        require(source_hash == m2.get("source_hash"), f"{case_id}: M2 source hash differs")
        require(source_hash == m2_rows[case_id]["source_hash"], f"{case_id}: M2 registry source hash differs")
        units = m1["units"]
        content = [u for u in units if u["unit_kind"] in ("paragraph", "unnumbered")]
        paragraphs = [u for u in content if u["unit_kind"] == "paragraph"]
        headings = [u for u in units if u["unit_kind"] == "heading"]
        nav = m2["navigation"]
        require([r["unit_id"] for r in nav] == [u["unit_id"] for u in content],
                f"{case_id}: map coverage/order differs from M1 content units")
        require(len({r["handle"] for r in nav}) == len(nav), f"{case_id}: duplicate handles")
        row_by_unit = {r["unit_id"]: r for r in nav}
        row_by_handle = {r["handle"]: r for r in nav}
        heading_by_id = {u["unit_id"]: u for u in headings}
        m2_headings = {u["unit_id"]: u for u in m2["headings"]}
        require(set(m2_headings) == set(heading_by_id), f"{case_id}: headings lost or invented")
        for ident, heading in heading_by_id.items():
            rendered = m2_headings[ident]
            a, b = heading["span_bytes"]
            require(rendered["span_bytes"] == [a, b], f"{case_id}: heading offsets differ")
            require(rendered["text"] == raw[a:b].decode("utf-8"), f"{case_id}: heading text is not exact")
            require(rendered["text_sha256"] == sha(raw[a:b]), f"{case_id}: heading provenance differs")
        for index, unit in enumerate(content):
            row = row_by_unit[unit["unit_id"]]
            require(row["span_bytes"] == unit["span_bytes"], f"{case_id}: {row['handle']} span differs")
            require(row["source_order"] == unit["order"], f"{case_id}: {row['handle']} source order differs")
            require(row["unit_kind"] == unit["unit_kind"], f"{case_id}: {row['handle']} kind differs")
            require(row["observed_marker"] == unit.get("observed_marker"), f"{case_id}: marker differs")
            require(row["token_count"] is None, f"{case_id}: token count fabricated")
            require("read_state" not in row and "Open" not in row, f"{case_id}: runtime state/boilerplate frozen in map")
            require(all(ref in heading_by_id for ref in row["section_refs"]), f"{case_id}: unknown heading ref")
            if unit["unit_kind"] == "paragraph":
                checked["paragraphs"] += 1
                checked["unknown_paragraphs"] += row["paragraph_role"] == "unknown"
                pindex = next(i for i, p in enumerate(paragraphs) if p["unit_id"] == unit["unit_id"])
                expected_prev = row_by_unit[paragraphs[pindex-1]["unit_id"]]["handle"] if pindex else None
                expected_next = row_by_unit[paragraphs[pindex+1]["unit_id"]]["handle"] if pindex + 1 < len(paragraphs) else None
                require(row["previous_paragraph_ref"] == expected_prev, f"{case_id}: prior paragraph is not source-nearest")
                require(row["next_paragraph_ref"] == expected_next, f"{case_id}: next paragraph is not source-nearest")
                checked["neighbor_links"] += (expected_prev is not None) + (expected_next is not None)
            else:
                checked["unnumbered_units"] += 1
                prev = row_by_unit[content[index-1]["unit_id"]]["handle"] if index else None
                nxt = row_by_unit[content[index+1]["unit_id"]]["handle"] if index + 1 < len(content) else None
                require(row["reading_expansion"]["previous_ref"] == prev,
                        f"{case_id}: unnumbered previous ref is not an actual content unit")
                require(row["reading_expansion"]["next_ref"] == nxt,
                        f"{case_id}: unnumbered next ref is not an actual content unit")
            checked["content_units"] += 1

        previews = {p["preview_id"]: p for p in m2["previews"]}
        anchors = {a["anchor_id"]: a for a in m2["anchors"]}
        for preview in previews.values():
            a, b = preview["span_bytes"]
            exact = raw[a:b].decode("utf-8")
            require(preview["text"] == exact, f"{case_id}: preview is not exact source slice")
            require(len(exact) <= 240, f"{case_id}: preview exceeds 240 Unicode codepoints")
            require(preview["text_sha256"] == sha(raw[a:b]), f"{case_id}: preview hash differs")
            require(preview["token_count"] is None, f"{case_id}: preview token count fabricated")
            require(set(preview["anchor_refs"]) == {v["anchor_ref"] for v in preview["anchor_visibility"]},
                    f"{case_id}: anchor visibility links incomplete")
            for visibility in preview["anchor_visibility"]:
                anchor = anchors[visibility["anchor_ref"]]
                aa, ab = anchor["span_bytes"]
                intersects = a < ab and aa < b
                fully = a <= aa and ab <= b
                require(intersects and visibility["fully_visible"] == fully,
                        f"{case_id}: preview anchor visibility is inaccurate")
            checked["previews"] += 1
        for row in nav:
            a, b = row["span_bytes"]
            expected_anchors = {x["anchor_id"] for x in anchors.values() if x["unit_id"] == row["unit_id"]}
            require(set(row["anchor_refs"]) == expected_anchors, f"{case_id}: row anchor refs incomplete")
            require(set(row["preview_refs"]).issubset(previews), f"{case_id}: missing preview ref")
            require(len(row["preview_refs"]) <= 2, f"{case_id}: display preview cap exceeded")
            for anchor_id in expected_anchors:
                anchor = anchors[anchor_id]
                aa, ab = anchor["span_bytes"]
                require(a <= aa < ab <= b, f"{case_id}: anchor escapes its M1 content unit")
                require(anchor["text_sha256"] == sha(raw[aa:ab]), f"{case_id}: anchor hash differs")
                if anchor["anchor_kind"] == "placeholder":
                    require(PLACEHOLDER.fullmatch(raw[aa:ab].decode("utf-8")) is not None,
                            f"{case_id}: placeholder anchor does not identify a literal placeholder")
                checked["anchors"] += 1
            checked["placeholder_occurrences"] += sum(x["anchor_kind"] == "placeholder" for x in anchors.values()
                                                        if x["unit_id"] == row["unit_id"])

        expected_cues = sorted({tuple(ref["span_bytes"]) for relation in m1.get("sidecars", [])
                                for ref in relation.get("attribution_cue_refs", [])})
        actual_cues = {tuple(item["span_bytes"]): item for item in m2["source_anchors"]}
        require(set(actual_cues) == set(expected_cues), f"{case_id}: source-level M1 quote cues lost/invented")
        for a, b in expected_cues:
            cue = actual_cues[(a, b)]
            require(cue["text_sha256"] == sha(raw[a:b]), f"{case_id}: source quote cue hash differs")
            require(cue["unit_refs"] == [u["unit_id"] for u in units if u["span_bytes"][0] < b and a < u["span_bytes"][1]],
                    f"{case_id}: source quote cue unit refs differ")
            expected_fragments = {
                u["unit_id"]: [max(a, u["span_bytes"][0]), min(b, u["span_bytes"][1])]
                for u in content if u["span_bytes"][0] < b and a < u["span_bytes"][1]
            }
            cue_fragments = [x for x in anchors.values() if x.get("source_anchor_ref") == cue["source_anchor_id"]]
            actual_fragments = {x["unit_id"]: x["span_bytes"] for x in cue_fragments}
            require(actual_fragments == expected_fragments,
                    f"{case_id}: quote cue local fragments differ from original span intersections")
            require(all(x.get("original_cue_span_bytes") == [a, b] for x in cue_fragments),
                    f"{case_id}: cue fragment lost the original full-cue span")
            checked["source_quote_cues"] += 1
        for unit in content:
            a, b = unit["span_chars"]
            expected_placeholders = []
            for match in PLACEHOLDER.finditer(text, a, b):
                expected_placeholders.append((len(text[:match.start()].encode("utf-8")),
                                              len(text[:match.end()].encode("utf-8"))))
            actual_placeholders = [tuple(anchor["span_bytes"]) for anchor in anchors.values()
                                   if anchor["unit_id"] == unit["unit_id"] and anchor["anchor_kind"] == "placeholder"]
            require(set(actual_placeholders) >= set(expected_placeholders), f"{case_id}: placeholder occurrence lacks an anchor")
        require(m2["readiness"]["token_counts"] == "not_ready", f"{case_id}: token counts incorrectly ready")
        require(m2["readiness"]["token_validated_chunks"] == "not_ready", f"{case_id}: chunks incorrectly token-ready")
        checked["headings"] += len(headings)
        checked["cases"] += 1
    return checked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--m1-bundle", default="pipeline_v2/artifacts/m1_20261105_v2")
    parser.add_argument("--m2-bundle", required=True)
    args = parser.parse_args()
    result = audit(args.repo_root, args.m1_bundle, args.m2_bundle)
    print(json.dumps({"valid": True, "independent_checks": result}, sort_keys=True))


if __name__ == "__main__":
    main()
