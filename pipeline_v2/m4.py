"""Bind the M4 harness to the accepted M3 search and source readers."""

from copy import deepcopy
import hashlib
from pathlib import Path

from .agent_harness import SourceDrift, SourceExcerpt, ToolResult
from .agent_harness.contracts import fingerprint
from .retrieval.common import M3Error


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _fields(row, names):
    return {name: row[name] for name in names if name in row}


def _lead(hit):
    lead = _fields(hit, ('case_id', 'score', 'rank', 'span_bytes', 'parent_handle',
                         'open_ref', 'source_hash', 'paragraph_role'))
    if 'passage_id' in hit and 'open_ref' not in lead:
        lead['open_ref'] = {'case_id': hit['case_id'], 'source_hash': hit['source_hash'],
                            'passage_ids': [hit['passage_id']]}
    if 'text' in hit:
        lead['preview'] = _fields(hit, ('text', 'span_bytes', 'text_sha256'))
    return lead


class M3Tools:
    """Reuse caller-owned sessions across actions and exclude the query from retrieval."""

    def __init__(self, sources, lexical, query_case, *, byte_budget, map_limit, recorded_search=None):
        for value, key in ((byte_budget, 'byte_cap'), (map_limit, 'max_limit')):
            if type(value) is not int or not 1 <= value <= sources.profile[key]:
                raise ValueError(f'M4 tool setting exceeds the M3 {key}')
        self.sources = sources
        self.lexical = lexical
        self.query_case = query_case
        self.byte_budget = byte_budget
        self.map_limit = map_limit
        if recorded_search is not None and (
            recorded_search['sparse_manifest_sha256'] != lexical.index_binding['manifest.json']
            or recorded_search['full_manifest_sha256'] != lexical.binding['manifest.json']
        ):
            raise ValueError('Recorded retrieval uses a different M3 index')
        self._recorded_search = deepcopy(recorded_search)
        self.fingerprint = fingerprint({
            'implementation': _sha(Path(__file__).read_bytes()),
            'source_snapshot': sources.snapshot_sha256,
            'source_profile': sources.profile_sha256,
            'sparse_index': lexical.index_binding['manifest.json'],
            'query_case': query_case,
            'byte_budget': byte_budget,
            'map_limit': map_limit,
            'recorded_search': None if recorded_search is None else fingerprint(recorded_search),
        })

    def actions(self):
        return {'search_corpus': self.search_corpus, 'search_case': self.search_case,
                'open_source': self.open_source, 'expand_source': self.expand_source,
                'open_query': self.open_query, 'search_phrase': self.search_phrase,
                'search_identity': self.search_identity}

    def verify_source(self, case_id, source_hash):
        self.sources.guard()
        if self.sources.sources.get(case_id) != source_hash:
            raise M3Error('Evidence source hash differs from the bound corpus')
        self.sources._raw(case_id)
        return True

    def _read_source(self, method, **args):
        try:
            return method(**args)
        except (M3Error, OSError) as exc:
            if self.sources.invalidated:
                raise SourceDrift(args.get('case_id')) from exc
            raise

    def query_start(self):
        """Return a map fallback and a whole-query excerpt for token admission."""
        query_map = self.open_query({'offset': 0})
        items = query_map.observation['items']
        first_paragraph = next((item for item in items if item['unit_kind'] == 'paragraph'), None)
        priority = next((item for item in items if item.get('anchor_refs')), first_paragraph)
        if priority is not None and self.byte_budget >= 4:
            page = self.open_query({'handles': [priority['handle']]})
            query_map = ToolResult(observation={**query_map.observation, 'priority_open': page.observation},
                                   excerpts=page.excerpts,
                                   source_requests=page.source_requests)
        raw = self.sources._raw(self.query_case)
        source_hash = self.sources.sources[self.query_case]
        full = SourceExcerpt(self.query_case, source_hash, (0, len(raw)),
                             raw.decode('utf-8'), source_hash, {'kind': 'whole_query'})
        return query_map, full

    def search_corpus(self, args):
        channel, text, limit = args['channel'], args['text'], args['limit']
        if channel in ('case_bm25', 'passage_bm25'):
            kind = {'case_bm25': 'case', 'passage_bm25': 'passage'}[channel]
            response = self.lexical.search(text, kind, limit, self.query_case, unique_cases=True)
            hits = [_lead(hit) for hit in response['hits']]
            mode = 'local'
        elif channel in ('hybrid', 'dense_passage') and self._recorded_search is not None:
            response = self._recorded_search
            recorded = response['hits'] if channel == 'hybrid' else response['channels'][channel]
            if (response['status'] != 'ok' or response['query_case'] != self.query_case
                    or response['query_sha256'] != _sha(text.encode('utf-8'))
                    or type(limit) is not int or not 1 <= limit <= len(recorded)):
                raise ValueError('Search does not match the recorded query and available hits')
            if channel == 'hybrid':
                hits = [{**_lead(hit), 'channels': {name: _lead(lead) for name, lead in hit['channels'].items()}}
                        for hit in recorded[:limit]]
            else:
                hits = [_lead(hit) for hit in recorded[:limit]]
            mode = 'recorded_replay'
        else:
            raise ValueError('Search channel is unavailable in this M4 profile')
        metadata = _fields(response, ('full_manifest_sha256', 'sparse_manifest_sha256',
                                      'implementation_sha256', 'coverage', 'query_sha256'))
        if mode == 'recorded_replay':
            metadata['recorded_request_id'] = response['request_id']
        return ToolResult(observation={**metadata, 'channel': channel, 'hits': hits, 'mode': mode},
                          candidates=tuple(hit['case_id'] for hit in hits))

    def _search_hits(self, result):
        hits = [_lead(hit) for hit in result['hits']]
        cases = tuple(dict.fromkeys(hit['case_id'] for hit in hits if hit['case_id'] != self.query_case))
        observation = _fields(result, ('tool', 'case_id', 'mode', 'next_cursor', 'coverage'))
        return ToolResult(observation={**observation, 'hits': hits}, candidates=cases)

    def search_case(self, args):
        return self._search_hits(self._read_source(self.sources.search_case, **args))

    def search_phrase(self, args):
        return self._search_hits(self._read_source(self.sources.search_phrase, **args))

    def search_identity(self, args):
        return self._search_hits(self._read_source(self.sources.search_identity, **args))

    def open_query(self, args):
        if 'offset' in args:
            if set(args) != {'offset'}:
                raise ValueError('Query map pagination accepts offset only')
            page = self._read_source(self.sources.case_map, case_id=self.query_case,
                                     offset=args['offset'], limit=self.map_limit)
            items = []
            for row in page['items']:
                item = _fields(row, ('handle', 'span_bytes', 'observed_marker', 'unit_kind',
                                     'paragraph_role', 'language_region', 'anchor_refs', 'reading_expansion'))
                item['previews'] = [_fields(p, ('preview_id', 'text', 'text_sha256', 'span_bytes', 'anchor_refs'))
                                    for p in row['previews']]
                item['sections'] = [_fields(s, ('unit_id', 'heading_scope', 'text', 'text_sha256', 'span_bytes'))
                                    for s in row['sections']]
                items.append(item)
            summary = _fields(page, ('case_id', 'source_hash', 'total', 'offset', 'next_offset'))
            return ToolResult(observation={'kind': 'query_map', **summary, 'items': items})
        if 'case_id' in args or 'source_hash' in args:
            raise ValueError('Query case and source hash are fixed by the run')
        return self.open_source({**args, 'case_id': self.query_case,
                                 'source_hash': self.sources.sources[self.query_case]})

    def expand_source(self, args):
        if 'target_handle' not in args:
            return self.open_source(args)
        if 'handles' in args or 'passage_ids' in args or 'hit_spans' in args:
            raise ValueError('An explicit expansion target requires a single handle')
        values = {key: value for key, value in args.items() if key != 'target_handle'}
        return self.open_source({**values, 'handles': [args['target_handle']]})

    def open_source(self, args):
        case_id, source_hash = args['case_id'], args['source_hash']
        byte_budget = args.get('byte_budget', self.byte_budget)
        if type(byte_budget) is not int or not 1 <= byte_budget <= self.byte_budget:
            raise ValueError('Open page exceeds the configured byte cap')
        page = self._read_source(self.sources.open_source, **{**args, 'byte_budget': byte_budget})
        excerpts = []
        for fragment in page['fragments']:
            start, end = fragment['span_bytes']
            components = [_fields(component, ('unit_id', 'span_bytes', 'handle', 'unit_kind',
                                              'observed_marker', 'marker_span_bytes',
                                              'paragraph_role', 'language_region', 'context_roles',
                                              'role_evidence_refs', 'ownership_cue_observations',
                                              'attribution_unit_id', 'section_refs', 'uncertainties',
                                              'reading_expansion'))
                          for component in page['components']
                          if component['span_bytes'][0] < end and start < component['span_bytes'][1]]
            excerpts.append(SourceExcerpt(case_id, source_hash, (start, end), fragment['text'],
                                          fragment['text_sha256'], {'components': components}))
        request = _fields(page, ('case_id', 'source_hash', 'requested_spans', 'pending_spans', 'next_cursor'))
        request['opened_spans'] = page['delivered_spans']
        request['cumulative_opened_spans'] = page['cumulative_delivered_spans']
        observation = _fields(page, ('case_id', 'source_hash', 'hit_refs', 'next_cursor', 'complete'))
        if page['next_cursor'] is not None:
            observation['continuation'] = {**args, 'cursor': page['next_cursor']}
        candidates = () if case_id == self.query_case else (case_id,)
        return ToolResult(observation=observation, excerpts=tuple(excerpts), candidates=candidates,
                          source_requests=(request,))
