"""One query-region interface with token-budgeted text or map responses."""
from bisect import bisect_left
from dataclasses import replace
import json

from pipeline_v2.agent_harness import ToolResult
from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint, encode
from pipeline_v2.m4 import M3Tools
from pipeline_v2.query_navigation import HierarchicalM3Tools, QueryTree
from .model_view import project


class _SplittableQueryTree(QueryTree):
    """Give an over-budget leaf a subdivision without changing its sibling refs."""

    def __init__(self, tree):
        super().__init__(tree.raw, tree.source_hash, tree.structure, tree.config,
                         headings=[{'span_bytes': span} for span in tree.headings], case_id=tree.case_id)
        self.headings = list(tree.headings)
        # Ordinary refs retain the exact source and subdivision identity of the base tree.
        self.binding, self.prefix, self.root_ref = tree.binding, tree.prefix, tree.root_ref

    def _split_cut(self, start, end):
        midpoint = (start + end) // 2
        index = bisect_left(self.boundaries, midpoint)
        near = [point for point in self.boundaries[max(0, index - 1):index + 1]
                if start < point < end and abs(point - midpoint) <= (end - start) // 4]
        if near:
            return min(near, key=lambda point: (abs(point - midpoint), point))
        cut = self._floor(midpoint)
        if cut <= start:
            cut = self._ceil(start + 1)
        return cut if cut < end else None

    def region(self, ref):
        if not isinstance(ref, str) or '~' not in ref:
            return super().region(ref)
        original, *splits = ref.split('~')
        row = super().region(original)
        if not row['is_leaf']:
            raise HarnessError('Only a query leaf can be split for context')
        start, end = row['span_bytes']
        split_map = splits[-1] == ''
        path = splits[:-1] if split_map else splits
        label = row['label']
        for side in path:
            cut = self._split_cut(start, end)
            if cut is None or side not in ('0', '1'):
                raise HarnessError('Unknown query context split')
            if side == '0':
                end = cut
            else:
                start = cut
            label += '.' + str(int(side) + 1)
        if split_map and self._split_cut(start, end) is None:
            raise HarnessError('Query leaf cannot be split further')
        paragraphs = [(left, right) for left, right in self.paragraphs if left < end and start < right]
        return {'region_ref': ref, 'span_bytes': [start, end], 'byte_length': end - start,
                'label': label, 'is_leaf': not split_map, 'paragraph_count': len(paragraphs),
                'partial_paragraph_count': sum(not (start <= left and right <= end) for left, right in paragraphs)}

    def children(self, ref):
        if not isinstance(ref, str) or '~' not in ref:
            return super().children(ref)
        row = self.region(ref)
        return [] if row['is_leaf'] else [self.region(ref + side) for side in ('0', '1')]

    def parent(self, ref):
        if not isinstance(ref, str) or '~' not in ref:
            return super().parent(ref)
        self.region(ref)
        if ref.endswith('~'):
            return self.parent(ref[:-1])
        return ref.rsplit('~', 1)[0] + '~'


class MapFirstQueryTools(HierarchicalM3Tools):
    """Keep CM4's query routing separate from the shared M3 reader."""

    def __init__(self, sources, lexical, query_case, *, byte_budget, map_limit,
                 navigation_config, count_tokens, output_token_cap=512):
        leaf_bytes = min(navigation_config.leaf_bytes, byte_budget)
        config = replace(navigation_config, leaf_bytes=leaf_bytes)
        super().__init__(sources, lexical, query_case, byte_budget=byte_budget, map_limit=map_limit,
                         navigation_config=config, count_tokens=count_tokens, output_token_cap=output_token_cap)
        self.query_tree = _SplittableQueryTree(self.query_tree)
        self.whole_region_reader = M3Tools(sources, lexical, query_case, byte_budget=sources.profile['byte_cap'],
                                          map_limit=map_limit)
        self.fingerprint = fingerprint([self.fingerprint, 'cm4-unified-query-read-v29'])

    def preview_expansion(self, binding):
        """Plan an expansion through the same local reader used at execution."""
        return self.expand_source(binding)

    def page_tokens(self, page):
        # Count the exact CM4 projection, including the live instruction/template
        # overhead in navigation_counter. Canonical hashes/refs stay host-side.
        minimal = {'query_id': self.query_case, 'query_source_hash': self.query_tree.source_hash,
                   'max_output_tokens': self.output_token_cap, 'excerpts': [],
                   'current_payload_source_refs': [], 'm6': {'query_navigation': page}}
        wire, _, _ = project(minimal, {})
        count = self.navigation_counter(encode(wire))
        if type(count) is not int or count < 0:
            raise HarnessError('Invalid navigation token count')
        return count

    def registry(self, events, state, payload):
        if payload.get('_cm4_query_navigation_enabled') is False:
            return None, {}, {}
        page, _, reads = super().registry(self._navigation_events(events), state, payload)
        visible = {row['region_ref']: row for row in (page['current'], *page['children'])}
        epoch = next(iter(reads.values()))['binding']['visit_epoch']
        for ref in (page['parent_ref'], self.query_tree.root_ref):
            if ref and ref not in visible:
                visible[ref] = self.query_tree.region(ref)
        choices = {}
        for ref, row in visible.items():
            if row.get('status', {}).get('raw_offered') == 'full':
                continue
            binding = {'navigation_mode': 'raw', 'region_ref': ref, 'visit_epoch': epoch}
            choices[fingerprint(binding)] = {'binding': binding, 'description': {
                'label': row['label'], 'span_bytes': row['span_bytes'], 'byte_length': row['byte_length']}}
        return page, {}, choices

    @staticmethod
    def _navigation_events(events):
        """Feed the shared reader the canonical history used to track source coverage."""
        for event in events:
            if event['kind'] == 'request_admitted' and 'cm_query_navigation' in event:
                body = {'m6': {'query_navigation': event['cm_query_navigation']},
                        'current_payload_source_refs': event['current_payload_source_refs'],
                        'excerpts': [{key: row[key] for key in ('ref', 'case_id', 'span_bytes', 'source_hash')}
                                     for row in event['excerpts']]}
                event = {**event, 'payload': json.dumps(body)}
            yield event

    def can_read_region(self, region_ref):
        return self.query_tree.region(region_ref)['byte_length'] <= self.sources.profile['byte_cap']

    def split_option(self, raw_option):
        """Replace a leaf that cannot fit with a selectable subdivision map."""
        binding = raw_option['binding']
        row = self.query_tree.region(binding['region_ref'])
        if binding['navigation_mode'] != 'raw':
            raise HarnessError('Expected a query region selection')
        if not row['is_leaf']:
            split = {**binding, 'navigation_mode': 'map'}
            description = {**raw_option['description'], 'response': 'map'}
            return fingerprint(split), {'binding': split, 'description': description}
        if self.query_tree._split_cut(*row['span_bytes']) is None:
            return None
        split = {**binding, 'navigation_mode': 'map', 'region_ref': row['region_ref'] + '~'}
        description = {**raw_option['description'], 'response': 'map', 'split_for_context': True}
        return fingerprint(split), {'binding': split, 'description': description}

    def context_fallback_options(self, region_ref, visit_epoch):
        """Keep source-stable subdivision and ancestor routes for a stale full read."""
        row = self.query_tree.region(region_ref)
        original = {'binding': {'navigation_mode': 'raw', 'region_ref': region_ref,
                                'visit_epoch': visit_epoch},
                    'description': {key: row[key] for key in ('label', 'span_bytes', 'byte_length')}}
        choices = {}
        split = self.split_option(original)
        if split:
            choices[split[0]] = split[1]
        for ref in (self.query_tree.parent(region_ref), self.query_tree.root_ref):
            if ref is None or ref == region_ref:
                continue
            target = self.query_tree.region(ref)
            binding = {'navigation_mode': 'map' if not target['is_leaf'] else 'raw',
                       'region_ref': ref, 'visit_epoch': visit_epoch}
            option = {'binding': binding, 'description': {key: target[key]
                      for key in ('label', 'span_bytes', 'byte_length')}}
            if target['is_leaf']:
                alternate = self.split_option(option)
                if alternate:
                    choices[alternate[0]] = alternate[1]
            else:
                choices[fingerprint(binding)] = option
        return choices

    def read_leaf(self, region_ref):
        """Read an entire selected region and keep native M3 provenance."""
        region = self.query_tree.region(region_ref)
        start, end = region['span_bytes']
        self.verify_source(self.query_case, self.query_tree.source_hash)
        result = self.whole_region_reader.open_query({'hit_spans': [[start, end]], 'byte_budget': end - start})
        if len(result.excerpts) != 1 or result.excerpts[0].span_bytes != (start, end):
            raise HarnessError('Query reader did not return the complete region')
        observation = {**result.observation, 'query_navigation_ref': region_ref,
                       'cm4_query_leaf_span': [start, end]}
        return ToolResult(observation, result.excerpts, result.candidates, result.source_requests)

    def open_query(self, args):
        if set(args) != {'navigation_mode', 'region_ref', 'visit_epoch'}:
            raise HarnessError('Expected host-bound query navigation operation')
        if type(args['visit_epoch']) is not int or args['visit_epoch'] < 0:
            raise HarnessError('Invalid query navigation visit epoch')
        if args['navigation_mode'] == 'raw':
            return self.read_leaf(args['region_ref'])
        if args['navigation_mode'] == 'map' and self.query_tree.region(args['region_ref'])['is_leaf']:
            raise HarnessError('Read the query leaf directly')
        return super().open_query(args)
