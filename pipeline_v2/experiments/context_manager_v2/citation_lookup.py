"""Exact matches to a citation owned by the decision in a sealed corpus."""
from collections import defaultdict
from hashlib import sha256
import re

from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint


_CITATION = re.compile(
    r'(?<![\w.])(?:\d{4}\s+(?:FCA|CAF|FC|CF|SCC|CSC)\s+\d+'
    r'|\d+\s+(?:N\.?[ \t]*R\.?|F\.?[ \t]*T\.?[ \t]*R\.?)\s*\d+)(?!\w|\.\d)',
    re.IGNORECASE,
)
_A_CITATION = re.compile(
    r'^\s*(?:<FRAGMENT_SUPPRESSED>\s*;?\s*)?(?P<identifier>' + _CITATION.pattern + r')'
    r'\s*(?:\((?:F\.?C\.?A\.?|F\.?C\.?|T\.?D\.?)\))?'
    r'(?:\s*,?\s+at\s+(?:para\.?|paragraph|p\.?|pp\.?)\s*\d+(?:[–-]\d+)?)?\s*[.;]?\s*$',
    re.IGNORECASE,
)
_HEADER_FIELD = re.compile(r'^(?P<label>Citation|Date|Docket|Court File(?: No\.)?)\s*:\s*(?P<value>\S.*?)\s*$', re.I)
_COURT_LINE = re.compile(r'^(?:Federal Court(?: of Appeal)?|Cour fédérale|Cour d[’\x27]appel fédérale|Supreme Court of Canada)$', re.I)
_MASKED_LINE = re.compile(r'^(?:\s*<FRAGMENT_SUPPRESSED>\s*)+$')


def _key(value):
    return re.sub(r'[.\s]+', '', value).upper()


def _citation_record(case, digest, raw, start, end):
    text = raw[start:end].decode('utf-8')
    record = {'case_id': case, 'source_hash': digest, 'span_bytes': [start, end],
              'text': text, 'text_sha256': sha256(raw[start:end]).hexdigest()}
    return {**record, 'ref': fingerprint(record)}


def self_citation(raw):
    """Only a labelled citation in the leading, structured decision header qualifies.

    Stop at the first prose, section, or other non-header line. A citation in an
    appendix, headnote or cited-authority list cannot enter this index.
    """
    position = 0
    fields = {}
    for line in raw[:4096].splitlines(keepends=True):
        text = line.decode('utf-8', errors='replace').strip()
        if not text and fields:
            break
        if text and not _COURT_LINE.fullmatch(text) and not _MASKED_LINE.fullmatch(text):
            match = _HEADER_FIELD.fullmatch(text)
            if not match:
                break
            label = match['label'].lower()
            label = 'docket' if label.startswith('court file') else label
            if label in fields:
                return None
            fields[label] = (match['value'], position, position + len(line.rstrip(b'\r\n')))
        position += len(line)
    if not {'citation', 'date', 'docket'} <= fields.keys():
        return None
    value, start, end = fields['citation']
    if not _CITATION.fullmatch(value) or '\ufffd' in raw[start:end].decode('utf-8', errors='replace'):
        return None
    return _key(value), start, end


def literal_citations(text):
    return [(len(text[:m.start()].encode('utf-8')), len(text[:m.end()].encode('utf-8')))
            for m in _CITATION.finditer(text)]


def explicit_citation_key(text):
    match = _A_CITATION.fullmatch(text)
    return _key(match['identifier']) if match else None


def approved_citation(need, raw_reader):
    """Require one exact scoped citation support from the approved A need."""
    if not need.get('source_bound'):
        return None
    supports = [row for row in need.get('a_supports', ()) if row.get('role') == 'citation']
    if len(supports) != 1:
        return None
    citation, = supports
    key = explicit_citation_key(citation['text'])
    if key is None:
        return None
    anchor = need['a_anchor']
    if {_key(m.group()) for m in _CITATION.finditer(anchor['text'])} - {key}:
        return None
    case = citation['case_id']
    source = need['a_sources'][0]
    if case != source['case_id'] or citation['source_hash'] != source['source_hash']:
        raise HarnessError('Citation support belongs to another query source')
    left, right = citation['span_bytes']
    raw = raw_reader(case)
    digest = sha256(raw).hexdigest()
    if digest != source['source_hash'] or raw[left:right] != citation['text'].encode('utf-8'):
        raise HarnessError('Citation support differs from canonical A bytes')
    return key, _citation_record(case, digest, raw, left, right)


class CitationLookup:
    def __init__(self, sources, raw_reader):
        self.sources = dict(sources)
        self.raw_reader = raw_reader
        self.index = None

    def _load(self):
        index = defaultdict(list)
        for case, expected_digest in sorted(self.sources.items()):
            raw = self.raw_reader(case)
            if sha256(raw).hexdigest() != expected_digest:
                raise HarnessError(f'Sealed case changed while building citation index: {case}')
            match = self_citation(raw)
            if match:
                key, left, right = match
                index[key].append(_citation_record(case, expected_digest, raw, left, right))
        self.index = dict(index)

    def match(self, need):
        if need.get('group_kind') == 'model_confirmed':
            return None
        target = approved_citation(need, self.raw_reader)
        if target is None:
            return None
        if self.index is None:
            self._load()
        key, a = target
        matches = self.index.get(key, ())
        if len(matches) != 1 or matches[0]['case_id'] == a['case_id']:
            return None
        result = {'citation': key, 'a': a, 'b': dict(matches[0])}
        self.verify(result)
        return result

    def verify(self, match):
        for side in ('a', 'b'):
            row = match[side]
            case = row['case_id']
            raw = self.raw_reader(case)
            digest = sha256(raw).hexdigest()
            if digest != self.sources.get(case) or row != _citation_record(case, digest, raw, *row['span_bytes']):
                raise HarnessError(f'Citation evidence changed: {case}')
            if side == 'b':
                if self_citation(raw) != (match['citation'], *row['span_bytes']):
                    raise HarnessError('Citation is outside the candidate decision header')
            else:
                identifier = _A_CITATION.fullmatch(row['text'])
                if identifier is None or _key(identifier['identifier']) != match['citation']:
                    raise HarnessError('Query citation no longer matches its approved ref')
