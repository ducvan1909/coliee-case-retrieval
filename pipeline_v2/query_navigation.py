"""Opt-in structural query navigation: immutable UTF-8 regions, never semantic summaries."""

from bisect import bisect_left
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import ceil
from pathlib import Path

from .agent_harness import SourceExcerpt, ToolResult
from .agent_harness.contracts import HarnessError, encode, fingerprint
from .m4 import M3Tools

VERSION = 'm6-query-navigation-v1'


@dataclass(frozen=True)
class QueryNavigationConfig:
    mode: str = 'hierarchical'
    max_children: int = 6
    leaf_bytes: int = 1024
    map_max_tokens: int = 2400
    snippet_chars: int = 96

    def __post_init__(self):
        if self.mode != 'hierarchical':
            raise HarnessError('Unknown query navigation mode')
        for key, minimum, maximum in (('max_children', 2, 16), ('leaf_bytes', 4, 65536),
                                     ('map_max_tokens', 1, 100000), ('snippet_chars', 1, 1024)):
            value = getattr(self, key)
            if type(value) is not int or not minimum <= value <= maximum:
                raise HarnessError('Invalid query navigation setting: ' + key)


def _union(spans):
    result = []
    for start, end in sorted(spans):
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


class QueryTree:
    """Lazy deterministic interval tree. A ref resolves without a previous visit."""
    def __init__(self, raw, source_hash, navigation, config, *, headings=(), case_id=None):
        self.raw = bytes(raw)
        self.raw.decode('utf-8')
        if not self.raw or sha256(self.raw).hexdigest() != source_hash:
            raise HarnessError('Query tree raw bytes/source hash mismatch')
        if not isinstance(config, QueryNavigationConfig):
            raise HarnessError('Explicit QueryNavigationConfig required')
        self.source_hash, self.config, self.case_id = source_hash, config, case_id
        self.structure = tuple(navigation)
        heading_rows = tuple(headings)
        self.binding = fingerprint([VERSION, case_id, source_hash, asdict(config), self.structure, heading_rows])
        self.prefix = 'qn-' + self.binding + ':'
        self.root_ref = self.prefix + 'r'
        bounds = {0, len(self.raw)}
        self.headings = []
        self.paragraphs = []
        for row in (*self.structure, *heading_rows):
            start, end = row['span_bytes']
            if not 0 <= start < end <= len(self.raw) or not self._boundary(start) or not self._boundary(end):
                raise HarnessError('Query tree structure has invalid UTF-8 span')
            bounds.update((start, end))
            if row.get('unit_kind') == 'paragraph':
                self.paragraphs.append((start, end))
            if row in heading_rows or row.get('unit_kind') == 'heading':
                literal = self.raw[start:end]
                if ('text' in row and row['text'] != literal.decode('utf-8')
                        or 'text_sha256' in row and row['text_sha256'] != sha256(literal).hexdigest()):
                    raise HarnessError('Query heading text/hash differs from raw source')
                self.headings.append((start, end))
        self.boundaries = sorted(bounds)

    def _boundary(self, offset):
        return offset in (0, len(self.raw)) or self.raw[offset] & 0xc0 != 0x80

    def _floor(self, offset):
        while offset > 0 and not self._boundary(offset):
            offset -= 1
        return offset

    def _ceil(self, offset):
        while offset < len(self.raw) and not self._boundary(offset):
            offset += 1
        return offset

    def _children(self, start, end):
        size = end - start
        if size <= self.config.leaf_bytes:
            return []
        count = min(self.config.max_children, ceil(size / self.config.leaf_bytes))
        cuts = [start]
        width = size / count
        for index in range(1, count):
            target = start + int(index * width)
            where = bisect_left(self.boundaries, target)
            near = [self.boundaries[position] for position in (where - 1, where)
                    if 0 <= position < len(self.boundaries)]
            near = [point for point in near if cuts[-1] < point < end and abs(point - target) <= width / 2]
            cut = min(near, key=lambda point: (abs(point - target), point)) if near else self._floor(target)
            if cut <= cuts[-1]:
                cut = self._ceil(cuts[-1] + 1)
            if cuts[-1] < cut < end:
                cuts.append(cut)
        if len(cuts) == 1:
            cut = self._ceil(start + 1)
            if cut >= end:
                raise HarnessError('Query region cannot be split at UTF-8 boundary')
            cuts.append(cut)
        return list(zip(cuts, [*cuts[1:], end]))

    def region(self, ref):
        if not isinstance(ref, str) or not ref.startswith(self.prefix):
            raise HarnessError('Unknown source/config-bound query region')
        suffix = ref[len(self.prefix):]
        parts = suffix.split('.')
        if not parts or parts[0] != 'r' or any(not value.isdigit() or str(int(value)) != value for value in parts[1:]):
            raise HarnessError('Invalid query region path')
        start, end = 0, len(self.raw)
        for part in parts[1:]:
            children = self._children(start, end)
            index = int(part)
            if index >= len(children):
                raise HarnessError('Unknown query region child')
            start, end = children[index]
        paragraphs = [(left, right) for left, right in self.paragraphs if left < end and start < right]
        return {'region_ref': ref, 'span_bytes': [start, end], 'byte_length': end - start,
                'paragraph_count': len(paragraphs),
                'partial_paragraph_count': sum(not (start <= left and right <= end) for left, right in paragraphs),
                'label': 'Whole query' if len(parts) == 1 else 'Region ' + '.'.join(str(int(p) + 1) for p in parts[1:]),
                'is_leaf': end - start <= self.config.leaf_bytes}

    def children(self, ref):
        start, end = self.region(ref)['span_bytes']
        return [self.region(ref + '.' + str(index)) for index, _ in enumerate(self._children(start, end))]

    def parent(self, ref):
        self.region(ref)
        return None if ref == self.root_ref else ref.rsplit('.', 1)[0]

    def _literal(self, start, end, position, chars):
        if chars <= 0 or start >= end:
            return None
        text = self.raw[start:end].decode('utf-8')
        count = min(chars, len(text))
        offset = 0 if position == 'begin' else len(text) - count if position == 'end' else (len(text) - count) // 2
        left = start + len(text[:offset].encode('utf-8'))
        literal = text[offset:offset + count]
        right = left + len(literal.encode('utf-8'))
        return {'position': position, 'span_bytes': [left, right], 'text': literal,
                'text_sha256': sha256(self.raw[left:right]).hexdigest()}

    def describe(self, ref, chars):
        row = self.region(ref)
        start, end = row['span_bytes']
        if chars:
            row['snippets'] = [self._literal(start, end, position, chars) for position in ('begin', 'middle', 'end')]
            heading = next(((left, right) for left, right in self.headings if start <= left < right <= end), None)
            if heading is not None:
                row['heading'] = self._literal(*heading, 'begin', chars)
        return row

    def page(self, ref, chars, snippets_per_region=3, include_headings=True):
        children = self.children(ref)
        def describe(region_ref, content=True):
            row = self.describe(region_ref, chars if content else 0)
            if snippets_per_region == 1 and row.get('snippets'):
                row['snippets'] = [row['snippets'][1]]  # One exact midpoint view per offered child.
            if not include_headings:
                row.pop('heading', None)
            return row
        current = describe(ref, not children)
        return {'kind': 'query_hierarchy_map', 'tree_binding': self.binding, 'source_hash': self.source_hash,
                'source_bytes': len(self.raw), 'current': current, 'root_ref': self.root_ref,
                'parent_ref': self.parent(ref),
                'children': [describe(row['region_ref']) for row in children],
                'coverage': 'structural_intervals_only', 'snippet_chars': chars,
                'snippets_per_region': snippets_per_region, 'headings_included': include_headings}


class HierarchicalM3Tools(M3Tools):
    """Opt-in query map adapter; corpus/source operations continue using accepted M3."""
    def __init__(self, sources, lexical, query_case, *, byte_budget, map_limit,
                 navigation_config, count_tokens, output_token_cap=512):
        super().__init__(sources, lexical, query_case, byte_budget=byte_budget, map_limit=map_limit)
        if not callable(count_tokens):
            raise HarnessError('Query navigation requires the actual payload token counter')
        self.navigation_config = navigation_config
        self.navigation_counter = count_tokens
        self.output_token_cap = output_token_cap
        raw = sources._raw(query_case)
        _, structure, _ = sources._case(query_case)
        self.query_tree = QueryTree(raw, sources.sources[query_case],
                                    structure['navigation'], navigation_config,
                                    headings=structure.get('headings', []), case_id=query_case)
        self.fingerprint = fingerprint([self.fingerprint, self.query_tree.binding,
                                        sha256(Path(__file__).read_bytes()).hexdigest(), output_token_cap])

    def page_tokens(self, page):
        # The caller's live counter includes its fixed instructions/chat template.
        minimal = {'query_id': self.query_case, 'query_source_hash': self.query_tree.source_hash,
                   'max_output_tokens': self.output_token_cap, 'excerpts': [], 'current_payload_source_refs': [],
                   'm6': {'query_navigation': page}}
        count = self.navigation_counter(encode(minimal))
        if type(count) is not int or count < 0:
            raise HarnessError('Invalid navigation token count')
        return count

    def map_page(self, ref, *, status=None, totals=None, compact=False):
        # Exact span/hash metadata has a nonzero cost even for a one-character
        # string. Reduce multiplicity before reducing literal content to zero.
        defaults = {'map_opened': False, 'map_seen': False, 'preview_seen': False,
                    'raw_read': 'unread', 'search_used': False, 'raw_offered': 'none'}
        variants = ((1, False),) if compact else ((3, True), (1, True), (1, False))
        for snippets, headings in variants:
            chars = min(24, self.navigation_config.snippet_chars) if compact else self.navigation_config.snippet_chars
            while True:
                page = self.query_tree.page(ref, chars, snippets, headings)
                if status is not None:
                    page['status_defaults'] = defaults
                    page['preview_currently_offered'] = True
                    for row in (page['current'], *page['children']):
                        row['status'] = {key: value for key, value in status(row).items() if defaults.get(key) != value}
                    page['totals'] = totals
                if self.page_tokens(page) <= self.navigation_config.map_max_tokens:
                    return page
                if chars == 1:
                    break
                chars = max(1, chars // 2)
        raise HarnessError('Query map with nonempty literal previews cannot fit its explicit token cap')

    def query_start(self):
        page = self.map_page(self.query_tree.root_ref)
        raw = self.query_tree.raw
        whole = SourceExcerpt(self.query_case, self.query_tree.source_hash, (0, len(raw)),
                              raw.decode('utf-8'), self.query_tree.source_hash, {'kind': 'whole_query'})
        return ToolResult(page), whole

    def shrink_map_page(self, page):
        """Reduce literal detail under full payload pressure without hiding routes."""
        chars, snippets, headings = page['snippet_chars'], page['snippets_per_region'], page['headings_included']
        if snippets == 3:
            snippets = 1
        elif headings:
            headings = False
        elif chars > 1:
            chars = max(1, chars // 2)
        else:
            return None
        reduced = self.query_tree.page(page['current']['region_ref'], chars, snippets, headings)
        for key in ('status_defaults', 'preview_currently_offered', 'totals'):
            if key in page:
                reduced[key] = deepcopy(page[key])
        for row, original in zip((reduced['current'], *reduced['children']),
                                 (page['current'], *page['children']), strict=True):
            if 'status' in original:
                row['status'] = deepcopy(original['status'])
        return reduced

    def open_query(self, args):
        if not {'navigation_mode', 'region_ref', 'visit_epoch'} == set(args):
            raise HarnessError('Expected host-bound query navigation operation')
        if type(args['visit_epoch']) is not int or args['visit_epoch'] < 0:
            raise HarnessError('Invalid query navigation visit epoch')
        self.verify_source(self.query_case, self.query_tree.source_hash)
        region = self.query_tree.region(args['region_ref'])
        if args['navigation_mode'] == 'map':
            return ToolResult(self.map_page(region['region_ref']))
        if args['navigation_mode'] != 'raw':
            raise HarnessError('Unknown query navigation operation')
        result = super().open_query({'hit_spans': [region['span_bytes']]})
        return ToolResult({**result.observation, 'query_navigation_ref': region['region_ref']},
                          result.excerpts, result.candidates, result.source_requests)

    def registry(self, events, state, payload):
        """Rebuild bounded current navigation from durable effects and actual receipts."""
        current = self.query_tree.root_ref
        opened, seen, previews, searched = set(), set(), set(), []
        delivered = []
        admissions, actions = {}, {}
        epoch = 0
        for event in events:
            kind = event['kind']
            if kind == 'request_admitted':
                admissions[event['request_id']] = json.loads(event['payload'])
            elif kind == 'request_result' and event.get('received_response'):
                body = admissions.get(event['request_id'], {})
                page = body.get('m6', {}).get('query_navigation')
                if page and page.get('tree_binding') == self.query_tree.binding:
                    seen.add(page['current']['region_ref'])
                    previews.update(row['region_ref'] for row in (page['current'], *page['children']))
                delivered.extend(row['span_bytes'] for row in body.get('excerpts', [])
                                 if row['ref'] in body.get('current_payload_source_refs', [])
                                 and row['case_id'] == self.query_case and row['source_hash'] == self.query_tree.source_hash)
            elif kind == 'action_started':
                actions[event['action_id']] = event
                epoch += 1
            elif kind == 'action_result' and event.get('result') and event.get('status') in ('success', 'pending_evidence'):
                observation = event['result']['observation']
                if observation.get('kind') == 'query_hierarchy_map':
                    if observation.get('tree_binding') != self.query_tree.binding:
                        raise HarnessError('Query map result uses a different tree')
                    current = self.query_tree.region(observation['current']['region_ref'])['region_ref']
                    opened.add(current)
                action = actions.get(event['action_id'], {})
                if action.get('executes_tool') and action['action']['action'] == 'search_corpus':
                    need = action['action']['args'].get('_m6_need', {})
                    searched.extend(row['span_bytes'] for row in need.get('a_sources', [])
                                    if row['case_id'] == self.query_case and row['source_hash'] == self.query_tree.source_hash)
        intervals = _union(delivered)
        offered = _union(row['span_bytes'] for row in payload.get('excerpts', [])
                         if row['ref'] in payload.get('current_payload_source_refs', [])
                         and row['case_id'] == self.query_case and row['source_hash'] == self.query_tree.source_hash)
        def status(row):
            start, end = row['span_bytes']
            covered = sum(max(0, min(end, right) - max(start, left)) for left, right in intervals)
            offered_bytes = sum(max(0, min(end, right) - max(start, left)) for left, right in offered)
            ref = row['region_ref']
            return {'map_opened': ref in opened, 'map_seen': ref in seen, 'preview_seen': ref in previews,
                    'raw_read': 'full' if covered == end - start else 'partial' if covered else 'unread',
                    'search_used': any(max(start, left) < min(end, right) for left, right in searched),
                    'raw_offered': 'full' if offered_bytes == end - start else 'partial' if offered_bytes else 'none'}
        totals = {'maps_opened': len(opened), 'maps_seen': len(seen), 'previews_seen': len(previews),
                  'raw_read_bytes': sum(right - left for left, right in intervals),
                  'search_source_spans': len(searched)}
        page = self.map_page(current, status=status, totals=totals, compact=bool(offered))
        map_refs = [current, *[row['region_ref'] for row in page['children'] if not row['is_leaf']]]
        parent = page['parent_ref']
        map_refs.extend(ref for ref in (parent, self.query_tree.root_ref) if ref is not None)
        maps, reads = {}, {}
        for mode, refs, target in (('map', map_refs, maps),
                                   ('raw', [current, *[row['region_ref'] for row in page['children']]], reads)):
            for ref in dict.fromkeys(refs):
                binding = {'navigation_mode': mode, 'region_ref': ref, 'visit_epoch': epoch}
                # The binding already names the opaque region. Do not repeat its
                # long digest in the same choice's structural description.
                description = {'label': self.query_tree.region(ref)['label']}
                target[fingerprint(binding)] = {'binding': binding, 'description': description}
        return page, maps, reads
