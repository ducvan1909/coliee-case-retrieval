"""Canonical source checks and UTF-8 windows; no semantic compression."""
from copy import deepcopy
from hashlib import sha256
from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.agent_harness.evidence import SourceDrift, excerpt, slice_record, source_record


def unread_spans(span, offered):
    """Return portions of a byte span that have yet to appear in a payload."""
    position, end = span
    gaps = []
    for left, right in sorted(offered):
        if right <= position or left >= end:
            continue
        if left > position:
            gaps.append([position, left])
        position = max(position, right)
    if position < end:
        gaps.append([position, end])
    return gaps


def lead_window_start(record, span, byte_limit):
    """Keep the lead in the first window when it can fit."""
    start, end = record['span_bytes']
    if end - start <= byte_limit:
        return start
    left, right = span
    if right - left > byte_limit:
        return left
    padding = (byte_limit - (right - left)) // 2
    offset = max(start, min(left - padding, end - byte_limit))
    raw = record['text'].encode('utf-8')
    while raw[offset - start] & 0xc0 == 0x80:
        offset -= 1
    return offset if offset + byte_limit >= right else left


class EvidenceStore:
    def __init__(self, raw_reader):
        self.raw_reader = raw_reader

    def verify(self, record):
        value = excerpt(record)
        raw = self.raw_reader(value.case_id)
        if sha256(raw).hexdigest() != value.source_hash:
            raise SourceDrift(value.case_id)
        start, end = value.span_bytes
        if raw[start:end] != value.text.encode('utf-8'):
            raise SourceDrift(value.case_id)
        canonical = source_record(value, overlay=record.get('provenance_overlay', False))
        if canonical['ref'] != record['ref']:
            raise HarnessError('Evidence canonical ref/provenance mismatch')
        return deepcopy(record)

    def window(self, record, offset=None, byte_limit=1024, requested_span=None):
        self.verify(record)
        if type(byte_limit) is not int or byte_limit < 1:
            raise HarnessError('Evidence window needs positive byte budget')
        start, end = record['span_bytes']
        if requested_span is not None:
            a, b = requested_span
            if not start <= a < b <= end:
                raise HarnessError('Requested evidence anchor outside canonical record')
            start, end = a, b
        offset = start if offset is None else offset
        if type(offset) is not int or not start <= offset < end:
            raise HarnessError('Invalid evidence continuation offset')
        raw = record['text'].encode('utf-8')
        base = record['span_bytes'][0]
        try:
            raw[:offset-base].decode('utf-8')
        except UnicodeDecodeError as exc:
            raise HarnessError('Continuation is not a UTF-8 boundary') from exc
        right = min(end, offset + byte_limit)
        while right > offset:
            try:
                raw[offset-base:right-base].decode('utf-8')
                break
            except UnicodeDecodeError:
                right -= 1
        if right == offset:
            raise HarnessError('Window cannot hold one UTF-8 codepoint')
        part = deepcopy(record) if (offset, right) == tuple(record['span_bytes']) else slice_record(record, offset, right)
        self.verify(part)
        return part, {'requested': [start, end], 'offered': [offset, right],
                      'pending': ([right, end] if right < end else None), 'canonical_ref': record['ref']}
