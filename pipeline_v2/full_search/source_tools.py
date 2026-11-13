"""Source-bound local M3 tools over the accepted immutable M2 snapshots."""
from bisect import bisect_left
from collections import OrderedDict
from copy import deepcopy
import base64
import json
from pathlib import Path
import re
import time
import uuid

from ..retrieval.bm25 import BM25
from ..retrieval.common import M3Error
from ..source.core import Utf8Map, canonical, digest


PROFILE = 'pipeline_v2/configs/m3_search.json'
DEFAULT_PROFILE = {
    'schema_version': 'pipeline-v2-m3-source-tools-1',
    'full_run': 'pipeline_v2/artifacts/m3_full_train_20261108_v1',
    'max_limit': 100,
    'default_case_scan_limit': 128,
    'max_case_scan_limit': 7708,
    'byte_cap': 65536,
    'case_cache_size': 4,
    'bm25': {'k1': 1.5, 'b': 0.75},
}


def implementation():
    root = Path(__file__).resolve().parents[2]
    names = ['pipeline_v2/full_search/source_tools.py', 'pipeline_v2/m3_search.py']
    return {name: digest((root / name).read_bytes()) for name in names}


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise M3Error('Invalid ' + label)
    return value


def _text(value):
    if not isinstance(value, str) or not value or not value.strip():
        raise M3Error('Search text must be nonempty')
    return value


def _union(spans):
    result = []
    for start, end in sorted(spans):
        if start == end:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def _intersection(left, right):
    return _union([[max(a, c), min(b, d)] for a, b in left for c, d in right
                   if max(a, c) < min(b, d)])


def _subtract(spans, removed):
    result = []
    for start, end in spans:
        current = start
        for a, b in _union(removed):
            if b <= current or a >= end:
                continue
            if a > current:
                result.append([current, a])
            current = max(current, b)
        if current < end:
            result.append([current, end])
    return result


def _cursor(binding, progress):
    body = {'version': 1, 'binding': binding, 'progress': progress}
    envelope = {**body, 'checksum': digest(canonical(body))}
    return base64.urlsafe_b64encode(canonical(envelope)).decode('ascii')


def _read_cursor(value, binding):
    try:
        if not isinstance(value, str) or len(value) > 8192:
            raise ValueError('cursor size')
        raw = base64.b64decode(value.encode('ascii'), altchars=b'-_', validate=True)
        data = json.loads(raw)
        if set(data) != {'version', 'binding', 'progress', 'checksum'}:
            raise ValueError('cursor schema')
        body = {key: data[key] for key in ('version', 'binding', 'progress')}
        if (type(data['version']) is not int or data['version'] != 1 or data['binding'] != binding
                or data['checksum'] != digest(canonical(body)) or raw != canonical(data)):
            raise ValueError('cursor binding')
        return data['progress']
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise M3Error('Invalid or stale source-tool cursor') from exc


class SourceToolsSession:
    """Reuse a validated search snapshot; never tokenize or rebuild a case."""

    def __init__(self, root, snapshot=None):
        self.root = Path(root).resolve()
        self.owns_snapshot = snapshot is None
        self.execution_mode = 'validated_local_snapshot' if snapshot is None else 'injected_snapshot'
        self.snapshot = snapshot
        self.invalidated = False
        self.cache = OrderedDict()
        try:
            profile_raw = (self.root / PROFILE).read_bytes()
            self.profile = json.loads(profile_raw)
            if self.profile != DEFAULT_PROFILE:
                raise M3Error('Unsupported source-tools profile')
            self.profile_sha256 = digest(profile_raw)
            self.code = implementation()
            if snapshot is None:
                from ..sparse_bm25.index import SparseSession
                self.snapshot = SparseSession(self.root)
            self.snapshot.guard()
            self.manifest = self.snapshot.manifest
            self.sources = dict(self.manifest['source_hashes'])
            self.case_ids = sorted(self.sources)
            self.passages_bundle = self._bundle(self.manifest['profile']['passages_bundle'])
            self.passages_seal_sha256 = self.manifest['profile']['accepted_m2_seal_sha256']
            self.passages_seal = self._seal(self.passages_bundle, self.passages_seal_sha256)
            self.passages_manifest = self._artifact(self.passages_bundle, self.passages_seal, 'manifest.json')
            navigation = self.passages_manifest['navigation']
            self.navigation_bundle = self._bundle(navigation['bundle'])
            self.navigation_seal_sha256 = navigation['seal_sha256']
            self.navigation_seal = self._seal(self.navigation_bundle, self.navigation_seal_sha256)
            self.navigation_manifest = self._artifact(self.navigation_bundle, self.navigation_seal, 'manifest.json')
            for name, field in (('manifest.json', 'manifest_sha256'),
                                ('source_registry.json', 'registry_sha256')):
                self._artifact(self.navigation_bundle, self.navigation_seal, name)
                if digest((self.navigation_bundle / name).read_bytes()) != navigation[field]:
                    raise M3Error('Navigation binding differs from accepted M2')
            passage_registry = self._artifact(self.passages_bundle, self.passages_seal, 'source_registry.json')
            navigation_registry = self._artifact(self.navigation_bundle, self.navigation_seal, 'source_registry.json')
            self.passage_rows = {r['case_id']: r for r in passage_registry['sources']}
            self.navigation_rows = {r['case_id']: r for r in navigation_registry['sources']}
            if (set(self.passage_rows) != set(self.sources)
                    or set(self.navigation_rows) != set(self.sources)
                    or len(self.passage_rows) != len(passage_registry['sources'])
                    or len(self.navigation_rows) != len(navigation_registry['sources'])):
                raise M3Error('Source-tools source universe differs')
            m1 = self.navigation_manifest['m1']
            self.m1_bundle = self._bundle(m1['bundle'])
            self.m1_seal_sha256 = m1['seal_sha256']
            self.m1_seal = self._seal(self.m1_bundle, self.m1_seal_sha256)
            for name, field in (('manifest.json', 'manifest_sha256'),
                                ('source_registry.json', 'registry_sha256')):
                self._artifact(self.m1_bundle, self.m1_seal, name)
                if digest((self.m1_bundle / name).read_bytes()) != m1[field]:
                    raise M3Error('M1 binding differs from accepted navigation')
            registry = self._artifact(self.m1_bundle, self.m1_seal, 'source_registry.json')
            self.m1_rows = {r['case_id']: r for r in registry['sources']}
            if set(self.m1_rows) != set(self.sources) or len(self.m1_rows) != len(registry['sources']):
                raise M3Error('M1 source universe differs')
            self.artifact_bindings = {}
            for bundle, seal in ((self.passages_bundle, self.passages_seal),
                                 (self.navigation_bundle, self.navigation_seal),
                                 (self.m1_bundle, self.m1_seal)):
                for name in ('manifest.json', 'source_registry.json'):
                    self.artifact_bindings[bundle / name] = seal['files'][name]['sha256']
            self.snapshot_sha256 = digest(canonical({
                'full_binding': self.snapshot.binding,
                'sources': self.sources,
                'passages_seal': self.passages_seal_sha256,
                'navigation_seal': self.navigation_seal_sha256,
                'm1_seal': self.m1_seal_sha256,
                'profile': self.profile_sha256,
                'implementation': self.code,
            }))
            self.guard()
        except BaseException:
            self.close()
            raise

    def _bundle(self, value):
        path = (self.root / value).resolve()
        if not path.is_relative_to((self.root / 'pipeline_v2/artifacts').resolve()):
            raise M3Error('Source bundle escapes artifacts')
        return path

    def _seal(self, bundle, expected):
        path = bundle / 'seal.json'
        if path.is_symlink() or digest(path.read_bytes()) != expected:
            raise M3Error('Source bundle seal drift')
        seal = json.loads(path.read_bytes())
        if not isinstance(seal.get('files'), dict):
            raise M3Error('Invalid source bundle seal')
        return seal

    def _artifact(self, bundle, seal, name):
        if name not in seal['files'] or Path(name).is_absolute() or '..' in Path(name).parts:
            raise M3Error('Unknown source artifact')
        path = bundle / name
        if path.is_symlink() or not path.resolve().is_relative_to(bundle):
            raise M3Error('Source artifact escapes bundle')
        raw = path.read_bytes()
        if seal['files'][name] != {'sha256': digest(raw), 'byte_length': len(raw)}:
            raise M3Error('Source artifact seal integrity failure')
        key = (str(bundle), name, digest(raw))
        if key not in self.cache:
            self.cache[key] = json.loads(raw)
            while len(self.cache) > self.profile['case_cache_size'] * 3:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]

    def guard(self):
        try:
            if self.invalidated:
                raise M3Error('Source-tools snapshot invalidated')
            self.snapshot.guard()
            if (digest((self.root / PROFILE).read_bytes()) != self.profile_sha256
                    or implementation() != self.code
                    or (self.passages_bundle / 'seal.json').is_symlink()
                    or (self.navigation_bundle / 'seal.json').is_symlink()
                    or (self.m1_bundle / 'seal.json').is_symlink()
                    or digest((self.passages_bundle / 'seal.json').read_bytes()) != self.passages_seal_sha256
                    or digest((self.navigation_bundle / 'seal.json').read_bytes()) != self.navigation_seal_sha256
                    or digest((self.m1_bundle / 'seal.json').read_bytes()) != self.m1_seal_sha256
                    or any(path.is_symlink() or digest(path.read_bytes()) != expected
                           for path, expected in self.artifact_bindings.items())):
                raise M3Error('Source-tools dependency drift')
        except BaseException:
            self.invalidated = True
            raise

    def _case_id(self, case_id):
        if not isinstance(case_id, str) or re.fullmatch(r'[0-9]{6}\.txt', case_id) is None or case_id not in self.sources:
            raise M3Error('Case is outside the source-tools universe')
        return case_id

    def _raw(self, case_id):
        self._case_id(case_id)
        try:
            path = self.root / 'data/task1_train_files_2026/cases' / case_id
            if path.is_symlink() or not path.resolve().is_relative_to(self.root / 'data/task1_train_files_2026/cases'):
                raise M3Error('Raw source escapes corpus')
            raw = path.read_bytes()
            if digest(raw) != self.sources[case_id]:
                raise M3Error('Raw source hash drift')
        except BaseException:
            self.invalidated = True
            raise
        return raw

    def _case(self, case_id, raw=None):
        raw = self._raw(case_id) if raw is None else raw
        name = f'sources/{case_id[:-4]}.json'
        try:
            nav = self._artifact(self.navigation_bundle, self.navigation_seal, name)
            passages = self._artifact(self.passages_bundle, self.passages_seal, name)
            navigation_sha = self.navigation_seal['files'][name]['sha256']
            passages_sha = self.passages_seal['files'][name]['sha256']
            if (nav['case_id'] != case_id or passages['case_id'] != case_id
                    or nav['source_hash'] != self.sources[case_id]
                    or passages['source_hash'] != self.sources[case_id]
                    or self.navigation_rows[case_id]['navigation_ref'] != name
                    or self.passage_rows[case_id]['passages_ref'] != name
                    or self.navigation_rows[case_id]['navigation_sha256'] != navigation_sha
                    or self.passage_rows[case_id]['passages_sha256'] != passages_sha
                    or passages['navigation_sha256'] != navigation_sha):
                raise M3Error('Sealed case provenance differs')
        except BaseException:
            self.invalidated = True
            raise
        return raw, nav, passages

    def _m1_case(self, case_id, raw, nav):
        name = f'sources/{case_id[:-4]}.json'
        try:
            record = self._artifact(self.m1_bundle, self.m1_seal, name)
            row = self.m1_rows[case_id]
            structure_sha = self.m1_seal['files'][name]['sha256']
            if (record['case_id'] != case_id or record['raw_sha256'] != self.sources[case_id]
                    or record['byte_length'] != len(raw) or row['raw_sha256'] != self.sources[case_id]
                    or row['byte_length'] != len(raw) or row['structure_ref'] != name
                    or row['structure_sha256'] != structure_sha
                    or nav['m1_structure_sha256'] != structure_sha):
                raise M3Error('M1 per-case provenance differs')
            return record
        except BaseException:
            self.invalidated = True
            raise

    def _begin(self):
        self.guard()
        return time.perf_counter()

    def _result(self, tool, started, **values):
        self.guard()
        result = deepcopy({'status': 'ok', 'tool': tool, 'request_id': uuid.uuid4().hex,
                           'execution_mode': self.execution_mode, 'model_requests': 0,
                           'snapshot_sha256': self.snapshot_sha256,
                           'profile_sha256': self.profile_sha256,
                           'implementation_sha256': digest(canonical(self.code)), **values})
        result['elapsed_seconds'] = time.perf_counter() - started
        return result

    def _binding(self, operation, inputs):
        return digest(canonical({'operation': operation, 'inputs': inputs,
                                 'snapshot': self.snapshot_sha256}))

    def _page(self, values, offset, limit):
        _integer(offset, 0, len(values), 'offset')
        _integer(limit, 1, self.profile['max_limit'], 'limit')
        items = values[offset:offset + limit]
        next_offset = offset + len(items)
        return {'items': items, 'offset': offset, 'limit': limit, 'total': len(values),
                'next_offset': next_offset if next_offset < len(values) else None}

    def case_map(self, case_id, offset=0, limit=20):
        started = self._begin()
        _, record, _ = self._case(case_id)
        previews = {p['preview_id']: p for p in record['previews']}
        headings = {h['unit_id']: h for h in record['headings']}
        page = self._page(record['navigation'], offset, limit)
        page['items'] = [{**row,
                          'previews': [previews[p] for p in row['preview_refs']],
                          'sections': [headings[h] for h in row['section_refs']]}
                         for row in page['items']]
        return self._result('case_map', started, case_id=case_id,
                            source_hash=record['source_hash'], **page)

    def case_anchors(self, case_id, handle=None, offset=0, limit=20, source=False):
        started = self._begin()
        _, record, _ = self._case(case_id)
        if type(source) is not bool or (source and handle is not None):
            raise M3Error('Invalid anchor scope')
        values = record['source_anchors'] if source else record['anchors']
        if handle is not None:
            row = next((r for r in record['navigation'] if r['handle'] == handle), None)
            if row is None:
                raise M3Error('Unknown navigation handle')
            values = [a for a in values if a['unit_id'] == row['unit_id']]
        return self._result('case_anchors', started, case_id=case_id, handle=handle,
                            source_hash=record['source_hash'], source_anchors=source,
                            **self._page(values, offset, limit))

    def _hit(self, case_id, raw, mapping, start, end, nav):
        a, b = mapping.char_to_byte(start), mapping.char_to_byte(end)
        text = raw[a:b].decode('utf-8')
        handles = [r['handle'] for r in nav['navigation']
                   if r['span_bytes'][0] < b and a < r['span_bytes'][1]]
        return {'case_id': case_id, 'source_hash': self.sources[case_id],
                'span_bytes': [a, b], 'span_chars': [start, end],
                'text': text, 'text_sha256': digest(raw[a:b]),
                'intersecting_handles': handles,
                'open_ref': {'case_id': case_id, 'source_hash': self.sources[case_id],
                             'hit_spans': [[a, b]]}}

    def search_phrase(self, text, case_id=None, matching_mode='exact_case_sensitive',
                      limit=20, cursor=None, case_scan_limit=None):
        return self._search_phrase('search_phrase', text, case_id, matching_mode,
                                   limit, cursor, case_scan_limit)

    def _search_phrase(self, operation, text, case_id, matching_mode,
                       limit, cursor, case_scan_limit):
        started = self._begin()
        _text(text)
        _integer(limit, 1, self.profile['max_limit'], 'limit')
        scan_limit = self.profile['default_case_scan_limit'] if case_scan_limit is None else case_scan_limit
        _integer(scan_limit, 1, self.profile['max_case_scan_limit'], 'case scan limit')
        if matching_mode not in ('exact_case_sensitive', 'unicode_casefold_mapped'):
            raise M3Error('Unsupported phrase matching mode')
        ids = self.case_ids if case_id is None else [self._case_id(case_id)]
        binding = self._binding(operation, {'text': text, 'case_ids': ids, 'mode': matching_mode})
        progress = {'case_index': 0, 'char_start': 0} if cursor is None else _read_cursor(cursor, binding)
        if not isinstance(progress, dict) or set(progress) != {'case_index', 'char_start'}:
            raise M3Error('Invalid phrase cursor progress')
        case_index = _integer(progress['case_index'], 0, len(ids) - 1, 'cursor case index')
        char_start = _integer(progress['char_start'], 0, 2 ** 31 - 1, 'cursor character offset')
        hits, scanned = [], 0
        while case_index < len(ids) and scanned < scan_limit and len(hits) < limit:
            ident = ids[case_index]
            raw = self._raw(ident)
            nav = None
            mapping = Utf8Map(raw)
            if char_start > len(mapping.text):
                raise M3Error('Phrase cursor exceeds source')
            haystack, needle = mapping.text, text
            boundaries = None
            if matching_mode == 'unicode_casefold_mapped':
                folded, boundaries = [], [0]
                for char in haystack:
                    folded.append(char.casefold())
                    boundaries.append(boundaries[-1] + len(folded[-1]))
                haystack, needle = ''.join(folded), text.casefold()
            position = char_start if boundaries is None else boundaries[char_start]
            scanned += 1
            while len(hits) < limit:
                found = haystack.find(needle, position)
                if found < 0:
                    break
                end = found + len(needle)
                position = found + 1
                if boundaries is None:
                    a, b = found, end
                else:
                    a, b = bisect_left(boundaries, found), bisect_left(boundaries, end)
                    if boundaries[a] != found or boundaries[b] != end:
                        continue
                if nav is None:
                    _, nav, _ = self._case(ident, raw)
                hit = self._hit(ident, raw, mapping, a, b, nav)
                compared = hit['text'] if boundaries is None else hit['text'].casefold()
                if compared != needle:
                    raise M3Error('Phrase raw-byte round trip failed')
                hits.append(hit)
                char_start = a + 1
            if len(hits) == limit:
                break
            case_index += 1
            char_start = 0
        exhausted = case_index == len(ids)
        next_cursor = None if exhausted else _cursor(binding, {'case_index': case_index, 'char_start': char_start})
        return self._result(operation, started, hits=hits, matching_mode=matching_mode,
                            next_cursor=next_cursor, exhausted=exhausted,
                            coverage={'scanned_cases': scanned, 'case_scan_limit': scan_limit,
                                      'total_cases': len(ids), 'next_case_index': case_index,
                                      'remaining_cases': len(ids) - case_index,
                                      'next_char_start': char_start,
                                      'all_sources_scanned': exhausted},
                            match_policy='overlapping_whole_codepoint_matches_source_order_v1')

    def search_case(self, case_id, text, mode='lexical', limit=20, cursor=None):
        if mode == 'literal':
            result = self._search_phrase('search_case', text, case_id, 'exact_case_sensitive',
                                         limit, cursor, None)
            result.update(tool='search_case', mode=mode)
            return result
        started = self._begin()
        _text(text)
        _integer(limit, 1, self.profile['max_limit'], 'limit')
        if mode != 'lexical' or cursor is not None:
            raise M3Error('Unsupported search_case mode or cursor')
        raw, nav, record = self._case(case_id)
        documents = record['passages']
        engine = BM25(documents, **self.profile['bm25'])
        hits = engine.search(text, limit=limit)
        for hit in hits:
            a, b = hit['span_bytes']
            if digest(raw[a:b]) != hit['exact_input_sha256']:
                raise M3Error('Case passage differs from raw source')
            hit['open_ref'] = {'case_id': case_id, 'source_hash': self.sources[case_id],
                               'passage_ids': [hit['passage_id']]}
        return self._result('search_case', started, case_id=case_id, source_hash=nav['source_hash'],
                            mode=mode, hits=hits, scoring_policy='case_local_bm25_v1',
                            coverage={'case_passages': len(documents), 'returned_hits': len(hits)},
                            next_cursor=None)

    def search_identity(self, text, case_id=None, limit=20, cursor=None, case_scan_limit=None):
        started = time.perf_counter()
        _text(text)
        result = self._search_phrase('search_identity', text, case_id, 'unicode_casefold_mapped',
                                     limit, cursor, case_scan_limit)
        for hit in result['hits']:
            _, record, _ = self._case(hit['case_id'])
            a, b = hit['span_bytes']
            hit['anchor_refs'] = [anchor for anchor in record['anchors'] + record['source_anchors']
                                  if anchor['span_bytes'][0] < b and a < anchor['span_bytes'][1]]
            hit['identity_status'] = 'observed_not_identity_verified'
            hit['method_version'] = 'literal_unicode_casefold_observation_v1'
        result.update(tool='search_identity', identity_status='observed_not_identity_verified',
                      method_version='literal_unicode_casefold_observation_v1')
        self.guard()
        result['elapsed_seconds'] = time.perf_counter() - started
        return deepcopy(result)

    def _span(self, value, mapping):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise M3Error('Expected a raw byte interval')
        start = _integer(value[0], 0, mapping.byte_length, 'span start')
        end = _integer(value[1], start + 1, mapping.byte_length, 'span end')
        self._boundary(mapping, start)
        self._boundary(mapping, end)
        return [start, end]

    def _boundary(self, mapping, offset):
        try:
            return mapping.byte_to_char(offset)
        except ValueError as exc:
            raise M3Error('Byte offset must be a UTF-8 codepoint boundary') from exc

    def _open_plan(self, nav, record, mapping, handles, passage_ids, hit_spans):
        rows = {row['handle']: row for row in nav['navigation']}
        by_unit = {row['unit_id']: row for row in nav['navigation']}
        passages = {p['passage_id']: p for p in record['passages']}
        parents, hits = {}, []
        for handle in handles:
            if handle not in rows:
                raise M3Error('Unknown navigation handle')
            parents[handle] = rows[handle]
            hits.append({'kind': 'handle', 'ref': handle, 'span_bytes': self._span(rows[handle]['span_bytes'], mapping)})
        for ident in passage_ids:
            if ident not in passages:
                raise M3Error('Passage is outside requested case')
            passage = passages[ident]
            hits.append({'kind': 'passage', 'ref': ident, 'span_bytes': self._span(passage['span_bytes'], mapping)})
            for unit_id in passage['parent_unit_ids']:
                if unit_id not in by_unit:
                    raise M3Error('Passage parent is absent from navigation')
                row = by_unit[unit_id]
                parents[row['handle']] = row
        for span in hit_spans:
            span = self._span(span, mapping)
            hits.append({'kind': 'raw_span', 'ref': None, 'span_bytes': span})
            for row in nav['navigation']:
                a, b = row['span_bytes']
                if a < span[1] and span[0] < b:
                    parents[row['handle']] = row
        hits.sort(key=lambda hit: (hit['span_bytes'], hit['kind'], hit['ref'] or ''))
        roles = {}
        requested = [hit['span_bytes'] for hit in hits]
        for row in parents.values():
            expansion = row['reading_expansion']
            window = []
            for role, key in (('previous_context', 'previous_ref'), ('parent', 'parent_ref'),
                              ('next_context', 'next_ref')):
                handle = expansion[key]
                if handle is not None:
                    if handle not in rows:
                        raise M3Error('Context reference is absent from navigation')
                    chosen = rows[handle]
                    roles.setdefault(handle, set()).add(role)
                    window.append(self._span(chosen['span_bytes'], mapping))
            requested.append([min(s[0] for s in window), max(s[1] for s in window)])
        # A hit wholly in a heading/gap has no invented paragraph parent.
        for hit in hits:
            span = hit['span_bytes']
            if not any(row['span_bytes'][0] < span[1] and span[0] < row['span_bytes'][1]
                       for row in parents.values()):
                before = [r for r in nav['navigation'] if r['span_bytes'][1] <= span[0]]
                after = [r for r in nav['navigation'] if r['span_bytes'][0] >= span[1]]
                neighbors = ([before[-1]] if before else []) + ([after[0]] if after else [])
                for row in neighbors:
                    roles.setdefault(row['handle'], set()).add('adjacent_context')
                spans = [span] + [self._span(r['span_bytes'], mapping) for r in neighbors]
                requested.append([min(s[0] for s in spans), max(s[1] for s in spans)])
        requested = _union(requested)
        queue = []

        def append(span):
            queue.extend(_subtract(_intersection([span], requested), queue))

        for hit in hits:
            append(hit['span_bytes'])
        for row in sorted(parents.values(), key=lambda r: r['span_bytes']):
            a, b = row['span_bytes']
            relevant = [h['span_bytes'] for h in hits if a < h['span_bytes'][1] and h['span_bytes'][0] < b]
            pivot = min(relevant[0][1], b) if relevant else a
            append([pivot, b])
            append([a, pivot])
        for span in requested:
            append(span)
        return requested, queue, hits, roles

    def open_source(self, case_id, source_hash, handles=None, passage_ids=None,
                    hit_spans=None, byte_budget=65536, cursor=None):
        started = self._begin()
        self._case_id(case_id)
        if source_hash != self.sources[case_id]:
            raise M3Error('Requested source hash differs from snapshot')
        _integer(byte_budget, 1, self.profile['byte_cap'], 'byte budget')
        inputs = {'handles': [] if handles is None else handles,
                  'passage_ids': [] if passage_ids is None else passage_ids,
                  'hit_spans': [] if hit_spans is None else hit_spans}
        for key, values in inputs.items():
            if not isinstance(values, list) or len(values) > self.profile['max_limit']:
                raise M3Error('Invalid open_source references')
            if key != 'hit_spans' and any(not isinstance(value, str) for value in values):
                raise M3Error('Invalid open_source reference ID')
        if not any(inputs.values()):
            raise M3Error('At least one source reference is required')
        raw, nav, record = self._case(case_id)
        m1_record = self._m1_case(case_id, raw, nav)
        mapping = Utf8Map(raw)
        inputs['handles'] = sorted(set(inputs['handles']))
        inputs['passage_ids'] = sorted(set(inputs['passage_ids']))
        inputs['hit_spans'] = sorted({tuple(self._span(s, mapping)) for s in inputs['hit_spans']})
        requested, queue, hits, roles = self._open_plan(nav, record, mapping, **inputs)
        binding = self._binding('open_source', {'case_id': case_id, 'source_hash': source_hash,
                                                'references': inputs, 'queue': queue})
        total = sum(b - a for a, b in queue)
        progress = 0 if cursor is None else _read_cursor(cursor, binding)
        _integer(progress, 0, total - 1, 'open cursor progress')
        cumulative, remaining = [], []
        consumed = progress
        for a, b in queue:
            length = min(consumed, b - a)
            if length:
                cumulative.append([a, a + length])
            if a + length < b:
                self._boundary(mapping, a + length)
                remaining.append([a + length, b])
            consumed -= length
        delivered, available = [], byte_budget
        for a, b in remaining:
            end = min(b, a + available)
            while end > a and end < len(raw) and raw[end] & 0xC0 == 0x80:
                end -= 1
            if end == a:
                if not delivered:
                    raise M3Error('Byte budget cannot fit the next UTF-8 codepoint; increase byte_budget')
                break
            delivered.append([a, end])
            available -= end - a
            if end < b or available == 0:
                break
        progress += sum(b - a for a, b in delivered)
        delivered = _union(delivered)
        cumulative = _union(cumulative + delivered)
        pending = _subtract(requested, cumulative)
        for hit in hits:
            hit['delivered_spans'] = _intersection([hit['span_bytes']], delivered)
            hit['cumulative_delivered_spans'] = _intersection([hit['span_bytes']], cumulative)
            hit['pending_spans'] = _intersection([hit['span_bytes']], pending)
        components, covered = [], []
        navigation = {row['unit_id']: row for row in nav['navigation']}
        for unit in m1_record['units']:
            row = {**unit, **navigation.get(unit['unit_id'], {})}
            span = self._span(row['span_bytes'], mapping)
            if not _intersection([span], requested):
                continue
            covered.append(span)
            component = dict(row)
            component.setdefault('unit_kind', 'heading')
            component.setdefault('paragraph_role', None)
            component.setdefault('observed_marker', None)
            component.setdefault('role_evidence_refs', [])
            component.setdefault('language_region', None)
            component.setdefault('uncertainties', [])
            component['context_roles'] = sorted(roles.get(row.get('handle'), {'intervening_context'}))
            component['delivered_spans'] = _intersection([span], delivered)
            component['pending_spans'] = _intersection([span], pending)
            components.append(component)
        for a, b in _subtract(requested, covered):
            components.append({'unit_kind': 'whitespace' if not raw[a:b].decode('utf-8').strip() else 'intervening_raw',
                               'span_bytes': [a, b], 'paragraph_role': None, 'observed_marker': None,
                               'role_evidence_refs': [], 'language_region': None, 'uncertainties': [],
                               'context_roles': ['intervening_context'],
                               'delivered_spans': _intersection([[a, b]], delivered),
                               'pending_spans': _intersection([[a, b]], pending)})
        components.sort(key=lambda c: c['span_bytes'])
        fragments = [{'span_bytes': [a, b], 'text': raw[a:b].decode('utf-8'),
                      'text_sha256': digest(raw[a:b])} for a, b in delivered]
        return self._result('open_source', started, case_id=case_id, source_hash=source_hash,
                            hit_refs=hits, requested_spans=requested,
                            delivered_spans=delivered, cumulative_delivered_spans=cumulative,
                            pending_spans=pending, fragments=fragments, components=components,
                            delivered_bytes=sum(b - a for a, b in delivered), byte_budget=byte_budget,
                            complete=not pending, token_safe_agent_payload=False,
                            M4_delivery_recorded=False,
                            cursor_semantics='transport_resume_not_model_exposure_ledger',
                            next_cursor=None if not pending else _cursor(binding, progress))

    def revalidate(self):
        started = self._begin()
        self.snapshot.revalidate()
        self.cache.clear()
        return self._result('revalidate', started, revalidated=True)

    def close(self):
        if self.snapshot is not None and self.owns_snapshot:
            self.snapshot.close()
