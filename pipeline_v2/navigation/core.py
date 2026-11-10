"""Deterministic navigation, provenance previews and reading-expansion mapping."""
from bisect import bisect_left
import re

from ..source.core import Utf8Map, canonical, digest, validate_partition


class M2Error(ValueError):
    pass


PLACEHOLDER = re.compile(r"[<(]?(?:FRAGMENT|REFERENCE)_SUPPRESSED[>)]?")
MARKER = re.compile(r"^\[[0-9]+\]")


PROTECTED_TAG = re.compile(r"<[^<>\r\n]+>|\((?:FRAGMENT|REFERENCE|DATE)_SUPPRESSED\)")


def _body_start(text, start, end):
    pos = start + (start < end and text[start] == "\ufeff")
    marker = MARKER.match(text[pos:end])
    return pos + marker.end() if marker else pos


def _content_start(text, start, end):
    """Skip redaction/punctuation-only lines for display, never edit source."""
    pos = _body_start(text,start,end)
    while pos < end:
        line_end = text.find("\n",pos,end)
        line_end = end if line_end < 0 else line_end
        value = text[pos:line_end]
        if any(ch.isalnum() for ch in PLACEHOLDER.sub("",value)):
            return pos + len(value)-len(value.lstrip())
        pos = min(end,line_end+1)
    return None


def _safe_window(text, lower, end, left, maximum, protected, focus=None):
    """Use whitespace/tag boundaries if they retain the focus and fit the cap.

    A single overlong token/tag may still be clipped; metadata reports that fact.
    No punctuation is treated as a certified sentence ending.
    """
    left = max(lower,left)
    if focus and focus[1]-focus[0] <= maximum:
        left = max(left,focus[1]-maximum)
    if left > lower:
        containing = next(((a,b) for a,b in protected if a < left < b),None)
        candidate = containing[1] if containing else left
        if containing is None and not text[left-1].isspace() and not text[left].isspace():
            whitespace = re.search(r"\s+",text[left:end])
            candidate = left+whitespace.end() if whitespace else end
        # A long-cue tail has intentionally omitted the cue start. It may
        # advance to a safe token/tag boundary while retaining some cue text.
        # Full-fit anchors must still retain their complete original span.
        long_focus = focus is not None and focus[1]-focus[0] > maximum
        if candidate < end and (focus is None or candidate <= focus[0] or (long_focus and candidate < focus[1])):
            left = candidate
    while left < end and text[left].isspace() and (focus is None or left < focus[0] or (focus[1]-focus[0] > maximum and left+1 < focus[1])):
        left += 1
    right = min(end,left+maximum)
    minimum = min(right,focus[1] if focus and focus[1]-focus[0] <= maximum else max(left+1,focus[0]+1) if focus else left+1)
    if right < end:
        containing = next(((a,b) for a,b in protected if a < right < b),None)
        if containing and containing[0] >= minimum:
            right = containing[0]
        elif containing is None and not text[right-1].isspace() and not text[right].isspace():
            whitespace = list(re.finditer(r"\s+",text[left:right]))
            candidates = [left+m.start() for m in whitespace if left+m.start() >= minimum]
            if candidates:
                right = candidates[-1]
    while right > left and text[right-1].isspace():
        right -= 1
    return (left,right) if left < right else None


def _opening(text, start, end, maximum, protected=None):
    pos = _content_start(text,start,end)
    if pos is None:
        return None
    protected = protected if protected is not None else [m.span() for m in PROTECTED_TAG.finditer(text,start,end)]
    return _safe_window(text,pos,end,pos,maximum,protected)


def _covered_length(a,b,ranges):
    spans = sorted((max(a,r[0]),min(b,r[1])) for r in ranges if a < r[1] and r[0] < b)
    total, cursor = 0,a
    for left,right in spans:
        total += max(0,right-max(cursor,left))
        cursor = max(cursor,right)
    return total


def _preview_ranges(text,start,end,maximum,radius,max_display,anchors):
    protected = [m.span() for m in PROTECTED_TAG.finditer(text,start,end)]
    content_start = _content_start(text,start,end)
    opening = _opening(text,start,end,maximum,protected)
    selected = [[*opening,"opening"]] if opening else []
    candidates = set()
    for a,b,ident in anchors:
        lower = content_start if content_start is not None and b > content_start else _body_start(text,start,end)
        focus = (max(a,lower),b)
        if focus[0] >= focus[1]:
            continue
        window = _safe_window(text,lower,end,max(lower,a-radius),maximum,protected,focus)
        if window:
            candidates.add(window)
        if b-a > maximum:
            # A long cue may already overlap the opening. Offer its tail as a
            # separate candidate so the second slot can reveal new cue evidence.
            tail_start = max(lower,b-maximum)
            tail = _safe_window(text,lower,end,tail_start,maximum,protected,(a,b))
            if tail:
                candidates.add(tail)
    # Merge/containment is bidirectional. An opening window may expand only
    # within substantive content, never back into skipped marker/redaction lines.
    if selected:
        changed = True
        while changed:
            changed = False
            for a,b in sorted(candidates):
                left,right,_ = selected[0]
                if a < right and left < b and min(a,left) >= content_start and max(b,right)-min(a,left) <= maximum:
                    merged = [min(a,left),max(b,right),"opening"]
                    if merged != selected[0]:
                        selected[0] = merged
                        changed = True
    eligible = [(a,b,ident) for a,b,ident in anchors if content_start is None or b > content_start]
    while len(selected) < max_display:
        choices = []
        for a,b in sorted(candidates):
            if any((left <= a and b <= right) or (a <= left and right <= b) for left,right,_ in selected):
                continue
            added_full, added_chars, added_partial = 0,0,0
            for ca,cb,_ in eligible:
                before = _covered_length(ca,cb,selected)
                after = _covered_length(ca,cb,selected+[[a,b,"anchor"]])
                if after > before:
                    added_chars += after-before
                    added_partial += 1
                    added_full += before < cb-ca and after == cb-ca
            if not selected:
                # Redaction-only units may display their anchors as signals.
                score = (added_full,added_chars,added_partial,b-a,-a)
            else:
                score = (added_full,added_chars,added_partial,0,-a)
            if added_chars:
                choices.append((score,a,b))
        if not choices:
            break
        _,a,b = max(choices)
        selected.append([a,b,"anchor"])
    return sorted(selected),content_start,protected


def build_case_navigation(case_id, raw, m1_record, profile):
    if not re.fullmatch(r"[0-9]{6}\.txt", case_id):
        raise M2Error("Expected six-digit .txt case ID")
    if m1_record["case_id"] != case_id or digest(raw) != m1_record["raw_sha256"]:
        raise M2Error("M1 source identity/hash mismatch")
    mapping = Utf8Map(raw)
    validate_partition(m1_record, raw, mapping)
    text = mapping.text
    source_hash = digest(raw)
    profile_hash = digest(canonical(profile))
    maximum = profile["preview"]["max_chars"]
    radius = profile["preview"]["anchor_radius_chars"]
    max_display = profile["preview"]["max_display_previews"]
    if type(maximum) is not int or maximum < 1 or type(radius) is not int or radius < 0 or type(max_display) is not int or max_display < 1:
        raise M2Error("Invalid preview limits")
    units = m1_record["units"]
    content = [u for u in units if u["unit_kind"] in ("paragraph", "unnumbered")]
    paragraphs = [u for u in content if u["unit_kind"] == "paragraph"]
    handles = {u["unit_id"]: f"{'p' if u['unit_kind'] == 'paragraph' else 'u'}{i+1:06d}" for i,u in enumerate(content)}
    paragraph_orders = [u["order"] for u in paragraphs]
    all_anchors, previews, rows = [], [], []
    quote_cues = []
    for relation in m1_record.get("sidecars", []):
        for ref in relation.get("attribution_cue_refs", []):
            quote_cues.append(tuple(ref["span_bytes"]))
    quote_cues = sorted(set(quote_cues))
    source_anchors = [{"source_anchor_id":f"q{i+1:06d}","case_id":case_id,"source_hash":source_hash,
                       "anchor_kind":"quote_introduction_candidate","span_bytes":[a,b],"text_sha256":digest(raw[a:b]),
                       "selection_method":"M1_local_quote_cue_reference",
                       "unit_refs":[u["unit_id"] for u in units if u["span_bytes"][0]<b and a<u["span_bytes"][1]]}
                      for i,(a,b) in enumerate(quote_cues)]
    for i, unit in enumerate(content):
        ident, handle = unit["unit_id"], handles[unit["unit_id"]]
        start,end = unit["span_chars"]
        byte_start,byte_end = unit["span_bytes"]
        candidates = []
        for match in PLACEHOLDER.finditer(text, start, end):
            candidates.append((mapping.char_to_byte(match.start()),mapping.char_to_byte(match.end()),"placeholder","literal_fragment_or_reference_placeholder_v1",None,None))
        for source_anchor in source_anchors:
            a,b = source_anchor["span_bytes"]
            if byte_start < b and a < byte_end:
                candidates.append((max(byte_start,a),min(byte_end,b),"quote_introduction_candidate","M1_local_quote_cue_reference",source_anchor["source_anchor_id"],(a,b)))
        unit_anchors = []
        for a,b,kind,method,source_ref,original_span in sorted(set(candidates)):
            anchor_id = f"{handle}:a{len(unit_anchors)+1:04d}"
            anchor = {"anchor_id": anchor_id,"case_id": case_id,"source_hash": source_hash,"unit_id": ident,
                      "anchor_kind": kind,"span_bytes": [a,b],"text_sha256": digest(raw[a:b]),"selection_method": method,
                      "source_anchor_ref":source_ref,"original_cue_span_bytes":list(original_span) if original_span else None}
            unit_anchors.append(anchor)
            all_anchors.append(anchor)
        anchor_chars = [(mapping.byte_to_char(x["span_bytes"][0]),mapping.byte_to_char(x["span_bytes"][1]),x["anchor_id"]) for x in unit_anchors]
        ranges,content_start,protected = _preview_ranges(text,start,end,maximum,radius,max_display,anchor_chars)
        content_end = start+len(text[start:end].rstrip())
        preview_ids = []
        for a,b,kind in sorted(ranges):
            if a >= b:
                continue
            bs,be = mapping.char_to_byte(a),mapping.char_to_byte(b)
            preview_id = f"{handle}:v{len(preview_ids)+1:02d}"
            preview_ids.append(preview_id)
            previews.append({"preview_id": preview_id,"case_id": case_id,"source_hash": source_hash,"unit_id": ident,
                             "preview_kind": kind,"span_bytes": [bs,be],"span_chars": [a,b],"text": text[a:b],
                             "text_sha256": digest(raw[bs:be]),"selection_method": "bounded_content_window_novel_anchor_coverage_v3",
                             "preview_profile_hash": profile_hash,
                             "partial_sentence": None,
                             "truncated": a > (content_start if content_start is not None else _body_start(text,start,end)) or b < content_end,
                             "start_clipped": a > (content_start if content_start is not None else _body_start(text,start,end)),
                             "end_clipped": b < content_end,
                             "word_boundary_clipped": (a > start and text[a-1].isalnum() and text[a].isalnum()) or (b < end and text[b-1].isalnum() and text[b].isalnum()),
                             "tag_boundary_clipped": any(x < a < y or x < b < y for x,y in protected),
                             "boundary_status": "content_window_not_sentence_verified",
                             "anchor_refs": [x["anchor_id"] for x in unit_anchors if bs < x["span_bytes"][1] and x["span_bytes"][0] < be],
                             "anchor_visibility": [{"anchor_ref":x["anchor_id"],"fully_visible":bs <= x["span_bytes"][0] and x["span_bytes"][1] <= be,
                                                    "source_cue_fully_visible":None if x["original_cue_span_bytes"] is None else bs <= x["original_cue_span_bytes"][0] and x["original_cue_span_bytes"][1] <= be,
                                                    "visibility":"full" if bs <= x["span_bytes"][0] and x["span_bytes"][1] <= be else "partial"} for x in unit_anchors if bs < x["span_bytes"][1] and x["span_bytes"][0] < be],
                             "token_count": None})
        pi = bisect_left(paragraph_orders,unit["order"])
        previous = paragraphs[pi-1] if pi else None
        next_i = pi+1 if unit["unit_kind"] == "paragraph" else pi
        following = paragraphs[next_i] if next_i < len(paragraphs) else None
        prev_content = handles[content[i-1]["unit_id"]] if i else None
        next_content = handles[content[i+1]["unit_id"]] if i+1 < len(content) else None
        prev_para = handles[previous["unit_id"]] if previous else None
        next_para = handles[following["unit_id"]] if following else None
        is_para = unit["unit_kind"] == "paragraph"
        row = {"handle": handle,"case_id": case_id,"source_hash": source_hash,"unit_id": ident,
               "source_order": unit["order"],"span_bytes": unit["span_bytes"],"unit_kind": unit["unit_kind"],
               "observed_marker": unit.get("observed_marker"),"section_refs": unit["section_path_refs"],
               "paragraph_role": unit.get("paragraph_role"),"uncertainties": unit["uncertainties"],
               "role_evidence_refs": unit.get("role_evidence_refs",[]),"language_region": unit["language_region"],
               "previous_paragraph_ref": prev_para,"next_paragraph_ref": next_para,
               "previous_content_ref": prev_content,"next_content_ref": next_content,
               "preview_refs": preview_ids,"anchor_refs": [x["anchor_id"] for x in unit_anchors],
               "preview_absence_reason": None if preview_ids else "no_meaningful_opening_or_anchor",
               "parent_container_refs": [{"unit_id": ident,"span_bytes": unit["span_bytes"]}],
               "reading_expansion": {"parent_ref": handle,"previous_ref": prev_para if is_para else prev_content,
                                     "next_ref": next_para if is_para else next_content,
                                     "neighbor_policy": "paragraph_order" if is_para else "content_unit_order",
                                     "previous_absence_reason": None if (prev_para if is_para else prev_content) else "source_boundary",
                                     "next_absence_reason": None if (next_para if is_para else next_content) else "source_boundary"},
               "token_count": None}
        rows.append(row)
    record = {"schema_version": "pipeline-v2-m2-navigation-case-1","case_id": case_id,"source_hash": source_hash,
              "profile_hash": profile_hash,"m1_structure_sha256": digest(canonical(m1_record)),
              "navigation": rows,"previews": previews,"anchors": all_anchors,"source_anchors":source_anchors,
              "headings": [{**{k:u[k] for k in ("unit_id","span_bytes","heading_scope","uncertainties")},
                            "text":raw[slice(*u["span_bytes"])].decode("utf-8"),"text_sha256":digest(raw[slice(*u["span_bytes"])])} for u in units if u["unit_kind"] == "heading"],
              "readiness": {"navigation": "ready","token_counts": "not_ready","token_validated_chunks": "not_ready"}}
    validate_case(record,raw,m1_record,profile,mapping)
    return record


def validate_case(record, raw, m1_record, profile, mapping=None):
    """Raw provenance/reference gates, independent of preview selection logic."""
    mapping = mapping or Utf8Map(raw)
    source_hash = digest(raw)
    actual = {u["unit_id"]:u for u in m1_record["units"] if u["unit_kind"] in ("paragraph","unnumbered")}
    rows = record["navigation"]
    if len(rows) != len(actual) or {r["unit_id"] for r in rows} != set(actual) or len({r["handle"] for r in rows}) != len(rows):
        raise M2Error("Navigation does not cover content units uniquely")
    row_by_id = {r["unit_id"]:r for r in rows}
    source_cues = {a["source_anchor_id"]:a for a in record["source_anchors"]}
    expected_cues = {tuple(ref["span_bytes"]) for relation in m1_record.get("sidecars",[]) for ref in relation.get("attribution_cue_refs",[])}
    if len(source_cues) != len(record["source_anchors"]) or {tuple(a["span_bytes"]) for a in source_cues.values()} != expected_cues:
        raise M2Error("M1 quote cues missing or duplicated in source anchors")
    for cue in source_cues.values():
        a,b = cue["span_bytes"]
        if not 0 <= a < b <= len(raw) or cue["text_sha256"] != digest(raw[a:b]):
            raise M2Error("Source quote cue raw evidence mismatch")
        mapping.byte_to_char(a)
        mapping.byte_to_char(b)
        if cue["unit_refs"] != [u["unit_id"] for u in m1_record["units"] if u["span_bytes"][0] < b and a < u["span_bytes"][1]]:
            raise M2Error("Source quote cue units mismatch")
    previews = {p["preview_id"]:p for p in record["previews"]}
    anchors = {a["anchor_id"]:a for a in record["anchors"]}
    if len(previews) != len(record["previews"]) or len(anchors) != len(record["anchors"]):
        raise M2Error("Duplicate preview/anchor ID")
    for collection in (record["previews"],record["anchors"]):
        for item in collection:
            a,b = item["span_bytes"]
            unit = actual.get(item["unit_id"])
            if unit is None or not unit["span_bytes"][0] <= a < b <= unit["span_bytes"][1]:
                raise M2Error("Preview/anchor outside source unit")
            if item["text_sha256"] != digest(raw[a:b]) or item["source_hash"] != source_hash:
                raise M2Error("Preview/anchor source provenance mismatch")
            if item["case_id"] != record["case_id"]:
                raise M2Error("Preview/anchor case identity mismatch")
            mapping.byte_to_char(a)
            mapping.byte_to_char(b)
            if "text" in item and (item["text"] != raw[a:b].decode("utf-8") or len(item["text"]) > profile["preview"]["max_chars"]):
                raise M2Error("Preview is not exact bounded raw text")
            if "text" in item:
                cs,ce = unit["span_chars"]
                a_char,b_char = mapping.byte_to_char(a),mapping.byte_to_char(b)
                baseline = _content_start(mapping.text,cs,ce)
                baseline = baseline if baseline is not None else _body_start(mapping.text,cs,ce)
                content_end = cs+len(mapping.text[cs:ce].rstrip())
                if (item["partial_sentence"] is not None or item["boundary_status"] != "content_window_not_sentence_verified" or
                        type(item["truncated"]) is not bool or type(item["start_clipped"]) is not bool or type(item["end_clipped"]) is not bool or
                        item["start_clipped"] != (a_char > baseline) or item["end_clipped"] != (b_char < content_end) or
                        item["truncated"] != (item["start_clipped"] or item["end_clipped"])):
                    raise M2Error("Preview clipping/sentence metadata is not truthful")
                if item["preview_kind"] == "opening" and a_char != baseline:
                    raise M2Error("Opening preview does not begin at meaningful content")
            source_ref = item.get("source_anchor_ref")
            if source_ref is not None:
                if source_ref not in source_cues or item["original_cue_span_bytes"] != source_cues[source_ref]["span_bytes"]:
                    raise M2Error("Anchor fragment source cue mismatch")
                ca,cb = source_cues[source_ref]["span_bytes"]
                if [a,b] != [max(ca,unit["span_bytes"][0]),min(cb,unit["span_bytes"][1])]:
                    raise M2Error("Anchor fragment does not cover cue/unit intersection")
    for cue in source_cues.values():
        a,b = cue["span_bytes"]
        expected_units = {u["unit_id"] for u in actual.values() if u["span_bytes"][0] < b and a < u["span_bytes"][1]}
        if {x["unit_id"] for x in anchors.values() if x.get("source_anchor_ref") == cue["source_anchor_id"]} != expected_units:
            raise M2Error("Source cue missing bounded navigation fragments")
    ordered = sorted(actual.values(),key=lambda u:u["order"])
    expected_neighbors = {u["unit_id"]:{"previous_content_ref":ordered[i-1] if i else None,
                                         "next_content_ref":ordered[i+1] if i+1<len(ordered) else None} for i,u in enumerate(ordered)}
    previous = None
    for unit in ordered:
        expected_neighbors[unit["unit_id"]]["previous_paragraph_ref"] = previous
        if unit["unit_kind"] == "paragraph":
            previous = unit
    following = None
    for unit in reversed(ordered):
        expected_neighbors[unit["unit_id"]]["next_paragraph_ref"] = following
        if unit["unit_kind"] == "paragraph":
            following = unit
    for row in rows:
        unit = actual[row["unit_id"]]
        if row["span_bytes"] != unit["span_bytes"] or row["source_order"] != unit["order"]:
            raise M2Error("Navigation source span/order mismatch")
        for key,neighbor in expected_neighbors[unit["unit_id"]].items():
            if row[key] != (row_by_id[neighbor["unit_id"]]["handle"] if neighbor else None):
                raise M2Error("Navigation neighbor mapping differs from source order")
        if len(row["preview_refs"]) > profile["preview"]["max_display_previews"]:
            raise M2Error("Too many displayed previews")
        if any(p not in previews or previews[p]["unit_id"] != row["unit_id"] for p in row["preview_refs"]):
            raise M2Error("Invalid preview reference")
        if any(a not in anchors or anchors[a]["unit_id"] != row["unit_id"] for a in row["anchor_refs"]):
            raise M2Error("Invalid anchor reference")
        visible = [previews[p]["span_bytes"] for p in row["preview_refs"]]
        for i,(a,b) in enumerate(visible):
            for c,d in visible[i+1:]:
                if (a <= c and d <= b) or (c <= a and b <= d):
                    raise M2Error("Contained preview wastes a display slot")
        if row["token_count"] is not None or "read_state" in row or "Open" in row:
            raise M2Error("Unselected token profile or runtime state in immutable map")
    return True
