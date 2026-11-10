"""Conservative structural observations. No legal semantics or model calls."""
from bisect import bisect_left
import hashlib
import json
import re


class M1Error(ValueError):
    pass


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Utf8Map:
    """Codepoint-boundary mapping; non-boundary byte offsets are rejected.

    ASCII positions need no stored entries. Each exception is [char, byte, width].
    BOM is retained as U+FEFF. CR and LF are distinct codepoints.
    """
    def __init__(self, raw):
        try:
            self.text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise M1Error("Source is not strict UTF-8") from exc
        self.byte_length = len(raw)
        self.exceptions = []
        self._positions = []
        self._extras = [0]
        byte = 0
        for index, char in enumerate(self.text):
            width = len(char.encode("utf-8"))
            if width != 1:
                self.exceptions.append([index, byte, width])
                self._positions.append(index)
                self._extras.append(self._extras[-1] + width - 1)
            byte += width

    def char_to_byte(self, index):
        if type(index) is not int or not 0 <= index <= len(self.text):
            raise M1Error("Character offset out of bounds")
        return index + self._extras[bisect_left(self._positions, index)]

    def byte_to_char(self, offset):
        if type(offset) is not int or not 0 <= offset <= self.byte_length:
            raise M1Error("Byte offset out of bounds")
        low, high = 0, len(self.text)
        while low <= high:
            middle = (low + high) // 2
            value = self.char_to_byte(middle)
            if value == offset:
                return middle
            if value < offset:
                low = middle + 1
            else:
                high = middle - 1
        raise M1Error("Byte offset is inside a UTF-8 codepoint")

    def record(self):
        return {"format": "non_ascii_exceptions_v1", "char_length": len(self.text),
                "byte_length": self.byte_length, "exceptions": self.exceptions}


# Marker detection and role classification are separate. Marker values never
# control structure, attribution or language state.
MARKER = re.compile(r"^[ \t\ufeff]*\[([0-9]+)\]")
CITATION_TAIL = re.compile(r"^\s*(?:FC|CF|FCA|CAF|SCC|CSC|F\.T\.R\.|F\.C\.|S\.C\.R\.|CanLII|[A-Z][A-Za-z.]*\s+[A-Z][A-Za-z.]*\.)\s*[0-9]", re.I)
KNOWN_HEADING = re.compile(r"^(?:summary|counsel|solicitors of record|judgment|order|introduction|arguments?|decision|reasons(?: for judgment)?|analysis|issues?|conclusions?|background|facts|the (?:respondent|applicants?)|applicable standard of review|standard of review|décision|jugement|analyse|contexte|les faits)\s*:?$", re.I)
ROMAN_HEADING = re.compile(r"^(?:[IVXLCDM]{1,8})[.)]\s*$")
PLACEHOLDER = re.compile(r"<?(?:FRAGMENT|REFERENCE|DATE)_SUPPRESSED>?")
QUOTE_CUE = re.compile(r"\b(?:quot(?:e[sd]?|ing|ation)|following|follows|stated|states|held|wrote|specified|noted|observed|paragraph\s+[0-9]+|stipulates|suivant|suit|déclar\w*|précis\w*)\b", re.I)
AUTHORITY_FRAME = re.compile(r"\b(?:court|justice|judge|tribunal|board|officer|juge|cour|tribunal)\b", re.I)
ATTRIBUTION_VERB = re.compile(r"\b(?:stated|states|held|wrote|specified|noted|observed|said|stipulates|déclar\w*|précis\w*)\b", re.I)
EXPLICIT_QUOTE = re.compile(r"\bquot(?:e[sd]?|ing|ation)\b", re.I)
CURRENT_CUE = re.compile(r"^(?:I (?:conclude|find|hold|dismiss|allow|will|am satisfied)|THIS COURT(?:'S)? (?:JUDGMENT|ORDERS|FINDS)|The application is (?:dismissed|allowed))\b", re.I)
FR_FRAME = re.compile(r"\(demandeur(?:s|esse)?\)|\(défendeur(?:s|esse)?\)|\ble juge\b", re.I)
TRANSLATION_TAG = re.compile(r"\[(traduction|translation)\]", re.I)


def _lines(text):
    result, pos = [], 0
    for value in text.splitlines(keepends=True):
        result.append((pos, pos + len(value), value))
        pos += len(value)
    return result


def parse_source(case_id, raw, profile=None):
    if not re.fullmatch(r"[0-9]{6}\.txt", case_id):
        raise M1Error("Expected six-digit .txt case ID")
    profile = profile or {"parser_version": "independent-markers-2"}
    source_hash, profile_hash = digest(raw), digest(canonical(profile))
    mapping = Utf8Map(raw)
    text = mapping.text
    lines = _lines(text)
    marker_events, observations = [], []
    for index, (start, end, line) in enumerate(lines):
        match = MARKER.match(line)
        if not match:
            continue
        a, b = start + line.index("["), start + match.end()
        literal = match.group(1)
        # A year-looking standalone marker is still a paragraph candidate. Only
        # an adjacent legal reporter/court pattern supplies citation evidence.
        citation = len(literal) == 4 and bool(CITATION_TAIL.match(line[match.end():]))
        if citation:
            observations.append({"span_chars": [a,b], "span_bytes": [mapping.char_to_byte(a),mapping.char_to_byte(b)],
                                 "number": int(literal), "marker_text": text[a:b],
                                 "classification": "citation_marker_with_reporter_evidence",
                                 "evidence_refs": [{"span_bytes": [mapping.char_to_byte(a),mapping.char_to_byte(end)]}]})
            continue
        marker_events.append({"start": start, "line_index": index, "kind": "paragraph",
                              "marker": int(literal), "marker_text": text[a:b], "marker_chars": [a,b]})
    first_marker = marker_events[0]["start"] if marker_events else len(text)
    notice = re.search(r"French language version follows English language version", text[:first_marker], re.I)
    language = "en:0" if notice else "unknown:0"
    language_ref = [] if notice is None else [{"span_bytes": [mapping.char_to_byte(notice.start()),mapping.char_to_byte(notice.end())]}]
    language_regions = [{"region_id": language, "start_byte": 0, "evidence_refs": language_ref,
                         "confidence_status": "observed_cue_not_language_model" if notice else "unknown"}]
    region_no = 0
    used_translation_cues = set()
    for position, event in enumerate(marker_events):
        previous = marker_events[position-1]["start"] if position else 0
        following = marker_events[position+1]["start"] if position+1 < len(marker_events) else len(text)
        start, marker_end = event["start"], event["marker_chars"][1]
        prior_start = max(previous, start-1600)
        prior = text[prior_start:start]
        body = text[marker_end:following]
        # Translation boundaries require actual tags/frame, never a marker value.
        tag_before = list(TRANSLATION_TAG.finditer(prior))
        tag_after = TRANSLATION_TAG.search(body[:400])
        separated = bool(re.search(r"\.{5,}", prior))
        french_frame = FR_FRAME.search(prior[-700:] + body[:200])
        boundary = None
        if tag_before and len(prior) - tag_before[-1].end() <= 500:
            tag = tag_before[-1]
            boundary = ("fr" if tag.group(1).lower() == "traduction" else "en", prior_start+tag.start(), prior_start+tag.end())
        elif tag_after and (separated or french_frame):
            boundary = ("fr" if tag_after.group(1).lower() == "traduction" else "en", marker_end+tag_after.start(), marker_end+tag_after.end())
        elif separated and french_frame:
            frame_start = max(prior_start, start-700)
            boundary = ("fr", frame_start, marker_end+min(len(body),200))
        if boundary and tuple(boundary) in used_translation_cues:
            boundary = None
        if boundary:
            used_translation_cues.add(tuple(boundary))
            region_no += 1
            language = f"{boundary[0]}:{region_no}"
            language_ref = [{"span_bytes": [mapping.char_to_byte(boundary[1]),mapping.char_to_byte(boundary[2])]}]
            language_regions.append({"region_id": language, "start_byte": mapping.char_to_byte(start),
                                     "evidence_refs": language_ref, "confidence_status": "observed_translation_boundary"})
        clean_prior = PLACEHOLDER.sub("", prior).rstrip()
        cue_matches = list(QUOTE_CUE.finditer(prior[-1200:]))
        strong_attribution = bool(EXPLICIT_QUOTE.search(prior[-1200:]) or (AUTHORITY_FRAME.search(prior[-1200:]) and ATTRIBUTION_VERB.search(prior[-1200:])))
        intro = clean_prior.endswith(":") and bool(cue_matches) and strong_attribution
        role, role_refs, attribution_span = "unknown", [], None
        uncertainty = ["paragraph_ownership_unresolved"]
        if intro and position:
            role = "quoted"
            context_offset = max(0,len(prior)-1200)
            local = prior[context_offset:]
            explicit = EXPLICIT_QUOTE.search(local)
            if explicit:
                cue_offset = context_offset + explicit.start()
            else:
                cue_offset = context_offset + min(AUTHORITY_FRAME.search(local).start(),ATTRIBUTION_VERB.search(local).start())
            colon_end = prior.rfind(":") + 1
            attribution_span = [prior_start+cue_offset,prior_start+colon_end]
            role_refs = [{"span_bytes": [mapping.char_to_byte(v) for v in attribution_span], "kind": "local_quote_introduction"}]
            uncertainty = ["quote_extent_beyond_this_unit_unresolved"]
        # Court voice is observable even inside quoted judgments. It cannot
        # establish ownership by itself; retain it as a weak observation only.
        voice_refs = []
        body_leading = len(body) - len(body.lstrip())
        cue = CURRENT_CUE.match(body.lstrip())
        if cue:
            a,b = marker_end+body_leading+cue.start(), marker_end+body_leading+cue.end()
            voice_refs = [{"span_bytes": [mapping.char_to_byte(a),mapping.char_to_byte(b)],
                           "kind": "court_voice_ownership_not_established"}]
        event.update({"language": language, "language_evidence_refs": language_ref,
                      "role": role, "role_refs": role_refs, "voice_refs": voice_refs, "attribution_span": attribution_span,
                      "uncertainties": uncertainty + (["translation_boundary_observed"] if boundary else [])})
    # Headings before the first marker are header observations and never become
    # section refs of body units. Broad title-case guessing has been removed.
    events = list(marker_events)
    for start, end, line in lines:
        if MARKER.match(line):
            continue
        clean = PLACEHOLDER.sub("", line).strip()
        if clean and (KNOWN_HEADING.fullmatch(clean) or ROMAN_HEADING.fullmatch(clean)):
            events.append({"start": start, "end": end, "kind": "heading", "marker": None,
                           "scope": "header" if start < first_marker else "body",
                           "uncertainties": ["heading_literal_observation"]})
    events.sort(key=lambda event: event["start"])
    segments, cursor = [], 0
    for i, event in enumerate(events):
        if event["start"] > cursor:
            segments.append((cursor,event["start"],"unnumbered",None))
        end = event.get("end", events[i+1]["start"] if i+1 < len(events) else len(text))
        segments.append((event["start"],end,event["kind"],event))
        cursor = end
    if cursor < len(text):
        segments.append((cursor,len(text),"unnumbered",None))
    units, heading_refs, paragraphs_by_start = [], [], {}
    for start,end,kind,event in segments:
        value = text[start:end]
        leading, trailing = len(value)-len(value.lstrip()), len(value.rstrip())
        ranges = [(start,start+leading,"whitespace"),(start+leading,start+trailing,kind),(start+trailing,end,"whitespace")] if trailing > leading else [(start,end,"whitespace")]
        for a,b,unit_kind in ranges:
            if a >= b:
                continue
            span = [mapping.char_to_byte(a),mapping.char_to_byte(b)]
            ident = f"{case_id[:-4]}:{source_hash[:16]}:{span[0]}-{span[1]}:{profile_hash[:12]}"
            unit = {"unit_id": ident, "source_hash": source_hash, "span_bytes": span, "span_chars": [a,b],
                    "order": len(units), "unit_kind": unit_kind,
                    "observed_marker": event["marker"] if event and unit_kind == "paragraph" else None,
                    "language_region": event.get("language","unknown:0") if event else "unknown:0",
                    "section_path_refs": list(heading_refs) if a >= first_marker else [],
                    "uncertainties": list(event["uncertainties"]) if event and unit_kind != "whitespace" else (["structure_unknown"] if unit_kind == "unnumbered" else [])}
            if unit_kind == "paragraph":
                unit.update({"marker_span_bytes": [mapping.char_to_byte(v) for v in event["marker_chars"]],
                             "marker_text": event["marker_text"], "paragraph_role": event["role"],
                             "role_evidence_refs": event["role_refs"], "ownership_cue_observations": event["voice_refs"], "language_evidence_refs": event["language_evidence_refs"],
                             "attribution_unit_id": None})
                paragraphs_by_start[event["start"]] = unit
            elif unit_kind == "heading":
                unit["heading_scope"] = event["scope"]
                unit["section_path_refs"] = []
                if event["scope"] == "body":
                    heading_refs = [ident]
            units.append(unit)
    relations = []
    for event in marker_events:
        unit = paragraphs_by_start[event["start"]]
        if event["role"] == "quoted":
            ca,cb = event["attribution_span"]
            attribution = next((u for u in units if u["span_chars"][0] <= ca and cb <= u["span_chars"][1]),None)
            unit["attribution_unit_id"] = attribution["unit_id"] if attribution else None
            relations.append({"kind": "quotation_relation", "quoted_unit_id": unit["unit_id"],
                              "attribution_unit_id": unit["attribution_unit_id"],
                              "attribution_cue_refs": unit["role_evidence_refs"],
                              "span_bytes": unit["span_bytes"], "span_chars": unit["span_chars"],
                              "observed_marker": unit["observed_marker"], "route_unknown": True,
                              "confidence_status": "local_cue_observed_extent_unresolved"})
    record = {"schema_version": "pipeline-v2-source-structure-2", "case_id": case_id,
              "raw_sha256": source_hash, "byte_length": len(raw), "char_length": len(text),
              "profile_hash": profile_hash, "char_byte_map": mapping.record(), "units": units,
              "sidecars": relations, "marker_observations": observations, "language_regions": language_regions,
              "metadata": extract_metadata(text[:first_marker],mapping)}
    validate_partition(record,raw,mapping)
    validate_marker_coverage(record,raw)
    return record


def validate_marker_coverage(record, raw):
    """Independent raw-byte scan: every numeric line marker has its own unit or
    explicit citation observation. No parser events or numbering state reused.
    This proves boundary preservation, not correctness of ownership labels.
    """
    candidates = {}
    for match in re.finditer(rb"(?m)^[ \t]*(?:\xef\xbb\xbf)?(\[[0-9]+\])",raw):
        a,b = match.span(1)
        candidates[(a,b)] = match.group(1).decode("ascii")
    represented = {}
    for unit in record["units"]:
        if unit["unit_kind"] != "paragraph":
            continue
        marker = tuple(unit["marker_span_bytes"])
        if marker in represented or marker not in candidates:
            raise M1Error("Duplicate or unexpected paragraph marker")
        if not unit["span_bytes"][0] <= marker[0] < marker[1] <= unit["span_bytes"][1]:
            raise M1Error("Marker outside its paragraph")
        if unit["paragraph_role"] not in ("current_case","quoted","unknown"):
            raise M1Error("Unknown paragraph ownership role")
        represented[marker] = "paragraph"
    for observation in record["marker_observations"]:
        marker = tuple(observation["span_bytes"])
        if marker in represented or marker not in candidates:
            raise M1Error("Duplicate or unexpected citation marker")
        a,b = marker
        newline = raw.find(b"\n",b)
        line_tail = raw[b:newline if newline >= 0 else len(raw)]
        # Separate bytes regex checks reporter adjacency, not parser predicate.
        if not re.match(rb"[ \t]*(?:FC|CF|FCA|CAF|SCC|CSC|F\.T\.R\.|F\.C\.|S\.C\.R\.|CanLII|[A-Z][A-Za-z.]*[ \t]+[A-Z][A-Za-z.]*\.)[ \t]*[0-9]",line_tail,re.I):
            raise M1Error("Citation marker lacks adjacent reporter evidence")
        represented[marker] = "citation"
    if set(represented) != set(candidates):
        raise M1Error("Numeric line marker missing independent addressable boundary")
    paragraph_spans = [u["span_bytes"] for u in record["units"] if u["unit_kind"] == "paragraph"]
    starts = sorted(marker[0] for marker,kind in represented.items() if kind == "paragraph")
    for a,b in paragraph_spans:
        index = bisect_left(starts,a)
        if index+1 < len(starts) and starts[index+1] < b:
            raise M1Error("Paragraph swallowed another numeric marker")
    return True


def extract_metadata(header, mapping):
    fields = []
    specs = [
        ("neutral_citation", re.compile(r"\b(?:19|20)\d{2}\s+(?:FC|CF|FCA|CAF|SCC|CSC)\s+\d+\b")),
        ("court", re.compile(r"(?m)^[ \t]*(?:Federal Court(?: of Appeal)?|Supreme Court of Canada|Cour fédérale|Cour d'appel fédérale)[ \t]*\r?$", re.I)),
        ("case_name", re.compile(r"(?m)^[ \t]*Indexed As:\s*([^\r\n]+)")),
        ("date", re.compile(r"(?m)^[ \t]*(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+(?:19|20)\d{2}\.?[ \t]*\r?$", re.I)),
    ]
    for field, pattern in specs:
        found = False
        for match in pattern.finditer(header):
            a,b = match.span(1) if field == "case_name" else match.span()
            while a < b and header[a].isspace():
                a += 1
            while b > a and header[b-1].isspace():
                b -= 1
            fields.append({"field": field, "value": header[a:b].strip(),
                           "source_refs": [{"span_bytes": [mapping.char_to_byte(a),mapping.char_to_byte(b)]}],
                           "extraction_method": "header_literal_regex_v1", "confidence_status": "observed_not_identity_verified"})
            found = True
        if not found:
            fields.append({"field": field, "value": None, "source_refs": [], "extraction_method": "header_literal_regex_v1", "confidence_status": "unknown"})
    return fields


def validate_partition(record, raw, mapping=None):
    mapping = mapping or Utf8Map(raw)
    cursor = 0
    for order, unit in enumerate(record["units"]):
        a,b = unit["span_bytes"]
        if a != cursor or not a < b <= len(raw) or unit["order"] != order:
            raise M1Error("Structural partition gap, overlap or invalid order")
        if [mapping.byte_to_char(a),mapping.byte_to_char(b)] != unit["span_chars"]:
            raise M1Error("Char/byte spans disagree")
        cursor = b
    if cursor != len(raw):
        raise M1Error("Structural partition does not cover complete source")
    return True
