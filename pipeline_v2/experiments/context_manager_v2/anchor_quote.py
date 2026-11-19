"""Locate an anchor in the query evidence admitted for one model reply."""

from difflib import SequenceMatcher
import re

ANCHOR_QUOTE_SCHEMA = {'type': 'string', 'minLength': 12, 'maxLength': 240}
_SUGGESTION_LIMIT = 3
_WORD = re.compile(r"\w+(?:['’]\w+)*")
_SENTENCE = re.compile(r'[^.!?\r\n]+(?:[.!?]+|(?=[\r\n]|$))')
_QUOTED = tuple(re.compile(
    rf'(?<!\w)({start})(?=\S)[^\r\n]{{1,240}}?(?<=\S)({end})(?!\w)')
    for start, end in (('"', '"'), ("'", "'"), ('“', '”'), ('‘', '’')))


def _normalized_text(text):
    """Collapse whitespace and map normalized boundaries to original characters."""
    fragments, boundaries = [], [0]
    for match in re.finditer(r'\s+|\S+', text):
        value = match.group()
        if value.isspace():
            fragments.append(' ')
            boundaries.append(match.end())
        else:
            fragments.append(value)
            boundaries.extend(range(match.start() + 1, match.end() + 1))
    return ''.join(fragments), boundaries


def _quote_wrappers(text):
    """Equate paired delimiters while preserving apostrophes within words."""
    chars = list(text)
    for pattern in _QUOTED:
        for pair in pattern.finditer(text):
            chars[pair.start(1)] = chars[pair.start(2)] = '"'
    return ''.join(chars)


def _visible_paragraphs(body):
    current = set(body['current_payload_source_refs'])
    query_records = {row['ref']: row for row in body['excerpts']
                     if row['ref'] in current and row['case_id'] == body['query_id']
                     and row['source_hash'] == body['query_source_hash']}
    raw = {key: row['text'].encode('utf-8') for key, row in query_records.items()}
    for handle, paragraph in body['m6']['a_paragraphs'].items():
        ref = paragraph['source_ref']
        if ref not in raw:
            continue
        left, right = paragraph['span_bytes']
        origin, end = query_records[ref]['span_bytes']
        if origin <= left < right <= end:
            yield handle, ref, left, raw[ref][left - origin:right - origin].decode('utf-8')


def _raw_anchor(paragraph, start, end):
    handle, ref, left, raw = paragraph
    text = raw[start:end]
    byte_start = left + len(raw[:start].encode('utf-8'))
    return handle, {'source_ref': ref, 'span_bytes': [byte_start, byte_start + len(text.encode('utf-8'))],
                    'text': text}


def _matches(paragraphs, sought, *, normalize=None):
    if normalize:
        sought = normalize(sought)[0].strip()
    matches = {}
    for paragraph in paragraphs:
        raw = paragraph[3]
        text, boundaries = normalize(raw) if normalize else (raw, range(len(raw) + 1))
        offset = text.find(sought)
        while offset >= 0:
            anchor = _raw_anchor(paragraph, boundaries[offset], boundaries[offset + len(sought)])
            span = tuple(anchor[1]['span_bytes'])
            matches.setdefault(span, anchor)
            if len(matches) == _SUGGESTION_LIMIT:
                return list(matches.values())
            offset = text.find(sought, offset + 1)
    return list(matches.values())


def _typographic_text(text):
    return _normalized_text(_quote_wrappers(text))


def _nearby_anchors(paragraphs, quote):
    terms = tuple(word.group().casefold() for word in _WORD.finditer(quote))
    if len(terms) < 3:
        return []
    term_set = set(terms)
    scored = {}
    for paragraph in paragraphs:
        raw = paragraph[3]
        for sentence in _SENTENCE.finditer(raw):
            words = list(_WORD.finditer(sentence.group()))
            tokens = tuple(word.group().casefold() for word in words)
            if len(term_set.intersection(tokens)) < 2:
                continue
            whole = len(sentence.group().strip()) <= ANCHOR_QUOTE_SCHEMA['maxLength']
            # Long sentences get quote-sized windows beginning at matching words.
            windows = [(0, len(words))] if whole else [
                (index, min(len(words), index + len(terms) + 1))
                for index, token in enumerate(tokens) if token in term_set]
            best = None
            for start, end in windows:
                candidate = tokens[start:end]
                if len(term_set.intersection(candidate)) < 2:
                    continue
                score = SequenceMatcher(None, terms, candidate, autojunk=False).ratio()
                if score < 0.55 or (best and score <= best[0]):
                    continue
                if whole:
                    left = sentence.start() + len(sentence.group()) - len(sentence.group().lstrip())
                    right = sentence.start() + len(sentence.group().rstrip())
                else:
                    left = sentence.start() + words[start].start()
                    right = sentence.start() + words[end - 1].end()
                if ANCHOR_QUOTE_SCHEMA['minLength'] <= right - left <= ANCHOR_QUOTE_SCHEMA['maxLength']:
                    best = (score, _raw_anchor(paragraph, left, right))
            if best:
                span = tuple(best[1][1]['span_bytes'])
                if span not in scored or scored[span][0] < best[0]:
                    scored[span] = best
    ordered = sorted(scored.values(), key=lambda row: (-row[0], row[1][1]['span_bytes']))
    return [anchor for _, anchor in ordered[:_SUGGESTION_LIMIT]]


def find_anchor(body, quote):
    """Return a verified unique match or exact-source choices requiring confirmation."""
    quote = quote.strip()
    if len(' '.join(quote.split())) < ANCHOR_QUOTE_SCHEMA['minLength']:
        return None, []
    paragraphs = list(_visible_paragraphs(body))
    for normalizer in (None, _normalized_text, _typographic_text):
        matches = _matches(paragraphs, quote, normalize=normalizer)
        if matches:
            return (matches[0], []) if len(matches) == 1 else (None, matches)
    return None, _nearby_anchors(paragraphs, quote)
