"""Bounded model views over an immutable canonical snapshot, with no inference."""
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from functools import wraps

from jsonschema import Draft202012Validator
from pipeline_v2.agent_harness.contracts import HarnessError, encode, fingerprint
from pipeline_v2.agent_harness.evidence import excerpt, source_record

VERSION = 'cm01-offline-v2'
MODES = ('pool', 'candidates', 'needs', 'results', 'query', 'assessment')


def require(condition, message):
    if not condition:
        raise HarnessError(message)


def write_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(encode(value))
        stream.flush()
        __import__('os').fsync(stream.fileno())


def digest_file(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def single_writer(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        db = sqlite3.connect(self.directory / 'context_writer.sqlite3', timeout=0)
        try:
            try:
                db.execute('BEGIN EXCLUSIVE')
            except sqlite3.OperationalError as exc:
                raise HarnessError('Another writer owns this context session') from exc
            return method(self, *args, **kwargs)
        finally:
            db.rollback()
            db.close()
    return guarded


@dataclass(frozen=True)
class Config:
    page_size: int = 5
    page_tokens: int = 800
    input_cap: int = 8500
    soft_target: int = 7900
    output_cap: int = 512
    context_cap: int = 12288
    preview_chars: int = 120

    def __post_init__(self):
        require(all(type(v) is int and v >= 0 for v in asdict(self).values()), 'Invalid context settings')
        require(0 < self.page_size <= 5 and self.page_tokens > 0, 'Page size must be 1..5 with positive token budget')
        require(0 < self.soft_target <= self.input_cap and self.output_cap > 0, 'Invalid context budget')
        require(self.input_cap + self.output_cap <= self.context_cap, 'Context window exceeded')


class Snapshot:
    """Exact IDs and search operations; no semantic need merging or reranking."""
    def __init__(self, query_id, bindings, candidates, needs, operations=(), assessments=(), pending=()):
        self.query_id, self.bindings = query_id, deepcopy(bindings)
        self.candidates = deepcopy(list(candidates))
        require(len({r['case_id'] for r in self.candidates}) == len(self.candidates), 'Duplicate canonical candidates')
        require(query_id not in {r['case_id'] for r in self.candidates}, 'Query cannot be a candidate')
        self.needs, self.operations = deepcopy(needs), deepcopy(list(operations))
        self.assessments, self.pending = deepcopy(list(assessments)), deepcopy(list(pending))
        for row in self.candidates:
            require(all(n in self.needs for n in row.get('need_ids', [])), 'Unknown candidate need')
        ids = {r['case_id'] for r in self.candidates}
        for operation in self.operations:
            require(operation['need_id'] in self.needs, 'Unknown operation need')
            require(all(h['case_id'] in ids for h in operation['hits']), 'Operation candidate outside pool')
        self.revision = fingerprint(self.record())

    def record(self):
        return {'query_id': self.query_id, 'bindings': self.bindings, 'candidates': self.candidates,
                'needs': self.needs, 'operations': self.operations,
                'assessments': self.assessments, 'pending': self.pending}

    @classmethod
    def from_record(cls, value):
        return cls(**value)

    @classmethod
    def from_events(cls, events, source_binding):
        from pipeline_v2.agent_harness.ledger import RunState
        state = RunState(events)
        require(state.config is not None, 'Missing run configuration')
        needs, operations = {}, []
        ordered_cases = []
        for event in events:
            result = event.get('result') or event.get('initial_result') or {}
            for hit in result.get('observation', {}).get('hits', []):
                if hit['case_id'] in state.candidates and hit['case_id'] not in ordered_cases:
                    ordered_cases.append(hit['case_id'])
            for case in result.get('candidates', []):
                if case in state.candidates and case not in ordered_cases:
                    ordered_cases.append(case)
        ordered_cases.extend(case for case in state.candidates if case not in ordered_cases)
        cases = {case: {'case_id': case, 'need_ids': [], 'leads': []} for case in ordered_cases}
        actions = {e['action_id']: e['action'] for e in events if e['kind'] == 'action_started'}
        for event in events:
            if event['kind'] == 'action_started':
                need = event['action']['args'].get('_m6_need')
                if need:
                    cls._need(needs, need)
            if event['kind'] != 'action_result' or not event.get('result'):
                continue
            observation = event['result']['observation']
            need = observation.get('m6_source_need') or actions.get(event['action_id'], {}).get('args', {}).get('_m6_need')
            if not need:
                continue
            cls._need(needs, need)
            hits = observation.get('hits', [])
            if 'hits' in observation:
                operations.append({'operation_id': event['action_id'], 'need_id': need['source_need_id'],
                                   'hits': deepcopy(hits), 'status': event['status']})
            for hit in hits:
                case = hit['case_id']
                if case not in cases:
                    continue
                row = cases[case]
                if need['source_need_id'] not in row['need_ids']:
                    row['need_ids'].append(need['source_need_id'])
                if hit not in row['leads']:
                    row['leads'].append(deepcopy(hit))
                if hit.get('open_ref'):
                    row['open_ref'] = deepcopy(hit['open_ref'])
        return cls(state.config['identity']['query_id'],
                   {**source_binding, 'identity': state.config['identity'], 'source_hashes': state.source_hashes,
                    'prefix_sha256': fingerprint(events)},
                   list(cases.values()), needs, operations,
                   [state.assessments[k] for k in state.active_assessments.values()],
                   list(state.pending_assessments.values()))

    @staticmethod
    def _need(needs, need):
        key = need['source_need_id']
        require(key not in needs or needs[key] == need, 'Conflicting exact source_need_id; no silent merging')
        needs[key] = deepcopy(need)


class Session:
    """Separate experimental journal. Requests below are offline view admissions."""
    def __init__(self, directory, snapshot, counter, config=None, counter_binding='test-counter'):
        self.directory, self.snapshot = Path(directory), snapshot
        self.counter, self.config = counter, config or Config()
        self.counter_binding = counter_binding
        self.scope = fingerprint([VERSION, digest_file(__file__), counter_binding, snapshot.revision, asdict(self.config)])
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / 'context_events.sqlite3'
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, body BLOB NOT NULL)')
            db.execute("CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append only'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append only'); END")
            first = db.execute('SELECT body FROM events ORDER BY seq LIMIT 1').fetchone()
            header = {'kind': 'session_created', 'scope': self.scope, 'snapshot': snapshot.record(), 'config': asdict(self.config)}
            if first:
                require(json.loads(first[0]) == header, 'Snapshot/source/config drift; use a new context namespace')
            else:
                db.execute('INSERT INTO events(body) VALUES(?)', (encode(header),))

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def events(self):
        with self._db() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM events ORDER BY seq')]

    def _append(self, kind, **fields):
        with self._db() as db:
            db.execute('INSERT INTO events(body) VALUES(?)', (encode({'kind': kind, **fields}),))

    def state(self):
        require(self.snapshot.revision == fingerprint(self.snapshot.record()), 'Canonical snapshot mutated')
        need = self.snapshot.operations[-1]['need_id'] if self.snapshot.operations else next(iter(self.snapshot.needs), None)
        result = {'focus': {'need_id': need, 'candidate_id': None, 'stage': 'ready'},
                  'in_flight': None, 'seen_candidates': set(), 'seen_needs': set(),
                  'seen_need_context': set(), 'seen_need_list': set(), 'delivered_raw': set(),
                  'requests': {}, 'commands': set(), 'last_view': None}
        for event in self.events()[1:]:
            if event['kind'] == 'view_admitted':
                result['in_flight'] = event['request_id']
                result['requests'][event['request_id']] = {'admission': event, 'receipt': None}
                result['last_view'] = event['request_id']
            elif event['kind'] == 'view_receipt':
                row = result['requests'][event['request_id']]
                row['receipt'] = event['status']
                result['in_flight'] = None
                if event['status'] == 'success':
                    manifest, view = self.load(event['request_id'], result['requests'])
                    result['seen_candidates'].update(manifest['shown_candidate_ids'])
                    result['seen_need_context'].update(manifest['context_need_ids'])
                    result['seen_need_list'].update(manifest['listed_need_ids'])
                    result['seen_needs'].update(manifest['shown_need_ids'])
                    result['delivered_raw'].update(view['current_payload_source_refs'])
            elif event['kind'] == 'command_applied':
                result['focus'] = event['focus']
                result['commands'].add(event['request_id'])
        return result

    def load(self, request_id, requests=None):
        requests = requests or self.state()['requests']
        require(request_id in requests, 'Unknown view request')
        admission = requests[request_id]['admission']
        paths = [self.directory / admission[k] for k in ('manifest_path', 'view_path')]
        require(all(p.resolve().is_relative_to(self.directory.resolve()) for p in paths), 'Artifact path escapes session')
        require(digest_file(paths[0]) == admission['manifest_sha256'] and digest_file(paths[1]) == admission['view_sha256'], 'View/manifest artifact changed')
        manifest, view = (json.loads(p.read_bytes()) for p in paths)
        require(manifest['scope'] == self.scope and manifest['view_sha256'] == fingerprint(view), 'Manifest binding mismatch')
        require(manifest['schema_sha256'] == fingerprint(manifest['schema']), 'Schema binding mismatch')
        return manifest, view

    def _handle(self, kind, target):
        return kind[0] + fingerprint([self.scope, kind, target])[:16]

    def _sequence(self, mode, focus):
        if mode == 'needs':
            return list(self.snapshot.needs)
        if mode == 'results':
            op = next((op for op in reversed(self.snapshot.operations) if op['need_id'] == focus['need_id']), None)
            return list(dict.fromkeys(h['case_id'] for h in op['hits'])) if op else []
        if mode in ('query', 'assessment'):
            return []
        return [r['case_id'] for r in self.snapshot.candidates
                if mode == 'pool' or focus['need_id'] is None or focus['need_id'] in r.get('need_ids', [])]

    @single_writer
    def compile(self, mode='results', cursor=None, evidence=None):
        require(mode in MODES, 'Unknown view mode')
        state = self.state()
        require(state['in_flight'] is None, 'Unresolved view admission; never resend')
        require(not any(r['receipt'] == 'unknown' for r in state['requests'].values()), 'Unknown receipt requires explicit resolution outside CM1')
        focus = state['focus']
        sequence = self._sequence(mode, focus)
        # Warning only: the model/AG chooses whether to continue. Ignore handles
        # and visit epochs so renaming does not masquerade as useful progress.
        prior_views = [self.load(request, state['requests'])[1] for request in state['requests']]
        start, back_history = 0, []
        if cursor:
            targets = {}
            for request in state['requests']:
                if state['requests'][request]['receipt'] != 'success':
                    continue
                manifest, _ = self.load(request, state['requests'])
                targets.update({key: value for key, value in manifest['handles'].items() if value['kind'] == 'page'})
            require(cursor in targets, 'Unknown, stale or foreign cursor')
            target = targets[cursor]
            require(target['mode'] == mode and target['focus'] == focus, 'Cursor mode/focus changed; refresh page')
            start = target['start']
            back_history = list(target['back_history'])
        evidence = deepcopy(evidence or {'excerpts': [], 'current_payload_source_refs': []})
        rows = evidence.get('excerpts', [])
        refs = evidence.get('current_payload_source_refs', [])
        require(refs == [row['ref'] for row in rows] and len(refs) == len(set(refs)), 'Current raw refs mismatch')
        for row in rows:
            require(source_record(excerpt(row), overlay=row.get('provenance_overlay', False))['ref'] == row['ref'], 'Raw evidence canonical record mismatch')
            expected = self.snapshot.bindings.get('source_hashes', {}).get(row['case_id'])
            require(expected is not None and row['source_hash'] == expected, 'Evidence source outside bound snapshot')
            require(row['case_id'] in (self.snapshot.query_id, focus['candidate_id']), 'Raw outside current A/B focus')
        case_map = {r['case_id']: r for r in self.snapshot.candidates}
        request_id = 'view-' + fingerprint([self.scope, len(state['requests']) + 1])[:24]
        best = None
        for length in range(min(self.config.page_size, len(sequence) - start), -1, -1):
            handles, cards = {}, []
            def add(kind, target):
                key = self._handle(kind, target)
                binding = {'kind': kind, **deepcopy(target)}
                require(key not in handles or handles[key] == binding, 'Handle collision')
                handles[key] = binding
                return key
            selected = sequence[start:start + length]
            for key in selected:
                if mode == 'needs':
                    need = self.snapshot.needs[key]
                    handle = add('need', {'need_id': key})
                    cards.append({'ref': handle, 'issue': need.get('intent', '')[:160], 'annotation': need.get('source_proposition', '')[:self.config.preview_chars]})
                else:
                    canonical = case_map[key]
                    # A case can have different passage leads for different needs.
                    # Select only this need's actual operation lead for dispatch.
                    scoped = deepcopy(canonical)
                    scoped.pop('open_ref', None)
                    lead = next((h for operation in reversed(self.snapshot.operations)
                                 if operation['need_id'] == focus['need_id']
                                 for h in operation['hits'] if h['case_id'] == key and h.get('open_ref')), None)
                    if lead:
                        scoped['open_ref'] = deepcopy(lead['open_ref'])
                    handle = add('candidate', {'case_id': key, 'need_id': focus['need_id'], 'canonical': scoped})
                    op = next((op for op in reversed(self.snapshot.operations) if op['need_id'] == focus['need_id']), None) if mode == 'results' else None
                    hit = next((r for r in op['hits'] if r['case_id'] == key), {}) if op else {}
                    assessed = any(r.get('candidate_id') == key and r.get('source_need_id') == focus['need_id'] for r in self.snapshot.assessments)
                    pending = any(r.get('candidate_id') == key and r.get('source_need_id') == focus['need_id'] for r in self.snapshot.pending)
                    cards.append({'ref': handle, 'case_id': key, 'rank_this_operation': hit.get('rank'),
                                  'status_for_current_need': 'assessed' if assessed else 'pending_evidence' if pending else 'unassessed'})
                    visible_lead = hit or lead or {}
                    preview = visible_lead.get('preview', {})
                    cards[-1]['lead'] = {k: visible_lead[k] for k in ('span_bytes', 'paragraph_role', 'channel_ranks') if k in visible_lead}
                    cards[-1]['preview'] = (preview.get('text', '') if isinstance(preview, dict) else str(preview))[:self.config.preview_chars]
            # Current need is available even when browsing candidates, without all needs.
            current_need = None
            if focus['need_id']:
                current_need = {'ref': add('need', {'need_id': focus['need_id']}),
                                'issue': self.snapshot.needs[focus['need_id']].get('intent', '')[:160],
                                'model_annotation': self.snapshot.needs[focus['need_id']].get('source_proposition', '')[:self.config.preview_chars]}
            controls = {}
            if start + length < len(sequence) and length:
                controls['next'] = add('page', {'mode': mode, 'focus': focus, 'start': start + length,
                                               'back_history': [*back_history, start]})
            if back_history:
                controls['previous'] = add('page', {'mode': mode, 'focus': focus,
                                                   'start': back_history[-1], 'back_history': back_history[:-1]})
            for view_mode in MODES:
                controls[view_mode] = add('page', {'mode': view_mode, 'focus': focus, 'start': 0, 'back_history': []})
            allowed = self.allowed_actions(handles, focus)
            for card in cards:
                action = 'read_case_passages' if 'case_id' in card else 'set_context_focus'
                card['action_available'] = card['ref'] in (allowed.get(action) or [])
                if 'case_id' in card:
                    card['read_allowed'] = card['action_available']
                    card['belongs_to_current_need'] = focus['need_id'] in handles[card['ref']]['canonical'].get('need_ids', [])
            schema = self._schema(handles, focus)
            view = {'version': VERSION, 'query_id': self.snapshot.query_id, 'max_output_tokens': self.config.output_cap,
                    'mode': mode, 'focus': focus, 'current_need': current_need,
                    'progress': {'pool_total': len(self.snapshot.candidates), 'needs_total': len(self.snapshot.needs),
                                 'candidates_delivered': len(state['seen_candidates']),
                                 'needs_context_delivered': len(state['seen_need_context']),
                                 'need_list_items_delivered': len(state['seen_need_list'])},
                    'page': {'start': start, 'count': length, 'total': len(sequence), 'revision': self.snapshot.revision,
                             'cards': cards, 'controls': controls},
                    'excerpts': rows, 'current_payload_source_refs': refs,
                    'pending_source_count': evidence.get('pending_source_count', 0),
                    'source_status': 'raw_A_B_present_not_semantic_validation' if rows and {r['case_id'] for r in rows} - {self.snapshot.query_id} and any(r['case_id'] == self.snapshot.query_id for r in rows) else 'no_current_pair',
                    'context_actions': self._prompt_tools(schema), 'source_action_execution': 'CM2/CM3 integration not enabled'}
            repeated = sum(old['mode'] == mode and old['focus'] == focus
                           and old['page']['start'] == start
                           and old['current_payload_source_refs'] == refs for old in prior_views)
            view['warnings'] = ['repeated_context_without_new_snapshot_or_raw; inspect progress before continuing'] if repeated >= 2 else []
            tokens = self.counter(encode(view))
            page_tokens = self.counter(encode({'max_output_tokens': self.config.output_cap, 'page': view['page']})) - self.counter(encode({'max_output_tokens': self.config.output_cap}))
            if tokens <= self.config.input_cap and page_tokens <= self.config.page_tokens and (length or not sequence):
                best = view, handles, schema, tokens, page_tokens
                if tokens <= self.config.soft_target:
                    break
        if best is None:
            return {'status': 'unfit', 'reason': 'mandatory_raw_or_minimum_view_exceeds_budget', 'model_requests': 0,
                    'raw_unchanged': True, 'input_cap': self.config.input_cap}
        view, handles, schema, tokens, page_tokens = best
        manifest = {'version': VERSION, 'request_id': request_id, 'scope': self.scope,
                    'snapshot_sha256': self.snapshot.revision, 'bindings': self.snapshot.bindings,
                    'config': asdict(self.config), 'handles': handles, 'schema': schema, 'schema_sha256': fingerprint(schema),
                    'canonical_evidence': evidence, 'shown_candidate_ids': [r['case_id'] for r in view['page']['cards'] if 'case_id' in r],
                    'shown_need_ids': list(dict.fromkeys(v['need_id'] for v in handles.values() if v['kind'] == 'need')),
                    'context_need_ids': [focus['need_id']] if focus['need_id'] else [],
                    'listed_need_ids': [key for key in self.snapshot.needs
                                        if mode == 'needs' and any(card['ref'] == self._handle('need', {'need_id': key})
                                                                  for card in view['page']['cards'])],
                    'view_sha256': fingerprint(view), 'input_tokens': tokens, 'page_tokens': page_tokens,
                    'above_soft_target': tokens > self.config.soft_target,
                    'soft_reason': 'required_raw_retained_below_hard_cap' if tokens > self.config.soft_target else None}
        vp, mp = f'views/{request_id}.json', f'manifests/{request_id}.json'
        write_once(self.directory / vp, view)
        write_once(self.directory / mp, manifest)
        self._append('view_admitted', request_id=request_id, view_path=vp, manifest_path=mp,
                     view_sha256=digest_file(self.directory / vp), manifest_sha256=digest_file(self.directory / mp))
        return {'status': 'ready', 'request_id': request_id, 'input_tokens': tokens, 'page_tokens': page_tokens,
                'view': view, 'manifest': manifest, 'model_requests': 0}

    @staticmethod
    def allowed_actions(handles, focus):
        """Single availability rule used by schema rendering and host dispatch."""
        safe = focus['stage'] in ('ready', 'assessed', 'missing_evidence', 'error', 'no_hit')
        result = {'show_context_page': sorted(k for k, v in handles.items() if v['kind'] == 'page')}
        needs = sorted(k for k, v in handles.items() if v['kind'] == 'need'
                       and v['need_id'] != focus['need_id'] and safe)
        candidates = sorted(k for k, v in handles.items() if v['kind'] == 'candidate'
                            and focus['need_id'] is not None and v['need_id'] == focus['need_id']
                            and focus['need_id'] in v['canonical'].get('need_ids', [])
                            and (safe or v['case_id'] == focus['candidate_id']))
        if needs:
            result['set_context_focus'] = needs
        if candidates:
            result['read_case_passages'] = candidates
        if focus['candidate_id'] is not None and focus['stage'] == 'reading':
            result['record_missing_evidence'] = None
        return result

    @classmethod
    def _schema(cls, handles, focus):
        allowed = cls.allowed_actions(handles, focus)
        branches = []
        def add(name, properties):
            branches.append({'type': 'object', 'additionalProperties': False,
                'properties': {'action': {'const': name}, 'args': {'type': 'object', 'additionalProperties': False,
                'properties': properties, 'required': list(properties)}}, 'required': ['action', 'args']})
        add('show_context_page', {'page_ref': {'enum': allowed['show_context_page'], 'type': 'string'}})
        if 'set_context_focus' in allowed:
            add('set_context_focus', {'need_ref': {'enum': allowed['set_context_focus'], 'type': 'string'}})
        if 'read_case_passages' in allowed:
            add('read_case_passages', {'candidate_ref': {'enum': allowed['read_case_passages'], 'type': 'string'},
                                      'focus': {'type': 'string', 'minLength': 4, 'maxLength': 160}})
        if 'record_missing_evidence' in allowed:
            add('record_missing_evidence', {'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}})
        return {'type': 'object', 'anyOf': branches}

    @staticmethod
    def _prompt_tools(schema):
        guidance = {
            'show_context_page': ('View another page without changing the active work focus.',
                                  'Use a page control to inspect pool, candidates, needs or return to overview.',
                                  'A bounded page; inspecting cards does not read source text.'),
            'set_context_focus': ('Change to a different source need.',
                                  'Available after a useful work boundary; finish reading or record missing evidence first.',
                                  'The selected need becomes focus; no search, reading or assessment is executed.'),
            'read_case_passages': ('Choose a candidate for the current need and a reading focus.',
                                   'Choose a current-page candidate offered by this tool; other-need cards may be browse-only.',
                                   'A validated canonical read intent; CM1 does not execute source reading.'),
            'record_missing_evidence': ('Record concrete evidence missing for the candidate being read.',
                                        'Use when the current pair cannot yet be resolved; do not invent an assessment to switch focus.',
                                        'The work boundary is recorded and another focus can then be chosen.')}
        paths = {'page_ref': 'page.controls values', 'need_ref': 'page.cards ref (need-list view)',
                 'candidate_ref': 'page.cards ref where action_available=true'}
        tools = []
        for row in schema['anyOf']:
            name = row['properties']['action']['const']
            parameters = deepcopy(row['properties']['args'])
            for key, value in parameters['properties'].items():
                if 'enum' in value:
                    value.pop('enum')
                    value['choices_from'] = paths[key]
            description, when, result = guidance[name]
            tools.append({'name': name, 'description': description, 'when': when, 'result': result,
                          'parameters': parameters})
        return tools

    @single_writer
    def receipt(self, request_id, status):
        require(status in ('success', 'unknown', 'error'), 'Invalid offline receipt status')
        state = self.state()
        require(state['in_flight'] == request_id, 'Receipt is not for current pending view')
        self.load(request_id, state['requests'])
        self._append('view_receipt', request_id=request_id, status=status)

    @single_writer
    def command(self, request_id, action):
        state = self.state()
        require(state['in_flight'] is None and request_id not in state['commands'] and request_id == state['last_view'], 'Unsafe, stale or already applied command')
        require(not any(r['receipt'] == 'unknown' for r in state['requests'].values()), 'Unknown receipt blocks commands')
        require(state['requests'].get(request_id, {}).get('receipt') == 'success', 'No successful response for this view')
        manifest, view = self.load(request_id, state['requests'])
        require(view['focus'] == state['focus'], 'Admission focus is stale; refresh context')
        Draft202012Validator(manifest['schema']).validate(action)
        current_allowed = self.allowed_actions(manifest['handles'], state['focus'])
        require(action['action'] in current_allowed, 'Action unavailable for current focus')
        ref_field = {'show_context_page': 'page_ref', 'set_context_focus': 'need_ref', 'read_case_passages': 'candidate_ref'}.get(action['action'])
        if ref_field:
            require(action['args'][ref_field] in current_allowed[action['action']], 'Handle unavailable for current focus')
        focus = deepcopy(state['focus'])
        name, args = action['action'], action['args']
        intent = None
        if name == 'record_missing_evidence':
            require(args['reason'].strip(), 'Missing-evidence reason blank')
            focus['stage'] = 'missing_evidence'
            focus['missing_reason'] = args['reason']
        else:
            field = {'show_context_page': 'page_ref', 'set_context_focus': 'need_ref', 'read_case_passages': 'candidate_ref'}[name]
            target = manifest['handles'][args[field]]
            new_need = target.get('need_id', focus['need_id'])
            changing = new_need != focus['need_id'] or name == 'read_case_passages' and target['case_id'] != focus['candidate_id']
            require(not changing or focus['stage'] in ('ready', 'assessed', 'missing_evidence', 'error', 'no_hit'), 'Finish useful work or record missing evidence before switching focus')
            if name == 'set_context_focus':
                if target['need_id'] != focus['need_id']:
                    focus = {'need_id': target['need_id'], 'candidate_id': None, 'stage': 'ready'}
            elif name == 'read_case_passages':
                require(args['focus'].strip() and len(args['focus'].split()) >= 2, 'Reading focus requires two words')
                require(focus['need_id'] in target['canonical'].get('need_ids', []), 'Candidate not bound to current need')
                focus = {'need_id': target['need_id'], 'candidate_id': target['case_id'], 'stage': 'reading'}
                need = self.snapshot.needs[target['need_id']]
                intent = {'action': 'read_case_passages', 'candidate_id': target['case_id'], 'focus': args['focus'],
                          'canonical_candidate': deepcopy(target['canonical']), 'canonical_need': deepcopy(need),
                          'execution': 'not_executed_CM1'}
            else:
                intent = {'mode': target['mode'], 'cursor': args[field]}
        self._append('command_applied', request_id=request_id, action=action, focus=focus, dispatch_intent=intent)
        return {'focus': focus, 'dispatch_intent': intent, 'model_requests': 0}
