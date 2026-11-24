"""CM4's disposable, suffix-fed projection of the durable append-only ledger.

Only trusted engine code sees the internal projections. Public accessors return
detached values, and a read view cannot silently cross a committed generation.
"""
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from hashlib import sha256
import json
from types import SimpleNamespace

from pipeline_v2.agent_harness.contracts import HarnessError, encode, fingerprint
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.runtime_timing import timed


def default_context():
    return {'need_id': None, 'candidate_id': None, 'stage': 'ready', 'mode': 'query',
            'offset': 0, 'back': [], 'revision': 0, 'pair_pins': {}, 'pair_targets': {}, 'pair_progress': {}}


class EventLog(list):
    """Trusted internal history with indexes; never returned by public events()."""
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime


class StateView:
    """Detached per-field reads without copying every admitted payload per getter."""
    def __init__(self, runtime):
        self._runtime, self._generation = runtime, runtime.generation

    def __getattr__(self, name):
        runtime = self._runtime
        if runtime.generation != self._generation or not runtime.valid:
            raise HarnessError('Runtime read view crossed a committed boundary')
        if name in ('apply', 'queue', 'add_result', 'invalidate'):
            raise HarnessError('Public runtime state is read-only')
        value = getattr(runtime.state, name)
        if callable(value):
            if name not in ('usage', 'snapshot', 'candidate_states'):
                raise HarnessError('Public runtime state exposes read methods only')
            def detached(*args, **kwargs):
                if runtime.generation != self._generation or not runtime.valid:
                    raise HarnessError('Runtime read view crossed a committed boundary')
                return deepcopy(value(*args, **kwargs))
            return detached
        return deepcopy(value)


def runtime_operation(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        runtime = getattr(self, '_runtime', None)
        if runtime is None:
            return method(self, *args, **kwargs)
        with runtime.operation():
            return method(self, *args, **kwargs)
    return call


class RuntimeSnapshot:
    def __init__(self, ledger):
        self.ledger = ledger
        self.valid = False
        self.generation = 0
        self.depth = 0
        self.frozen_config = None
        self.stats = {'full_reads': 0, 'tail_reads': 0, 'rows_decoded': 0, 'events_applied': 0, 'rebuilds': 0}
        self._reset()

    def _reset(self):
        self.events = EventLog(self)
        self.state = RunState()
        self.context = default_context()
        self.last_seq = 0
        self.hasher = sha256(b'[')
        self.actions = {}
        self.outcomes = []
        self.last_search = None
        self.requests = {}
        self.receipts = {}
        self.queries = {}
        self.delivered = {}
        self.needs = {}
        self.result_needs = {}
        self.successful_search_actions = []
        self.has_search_results = False
        self.operations = []
        self.case_order = []
        self.case_records = {}
        self.opened_leads = []
        self.opened_lead_keys = set()
        self.repair_scopes = set()
        self.latest_boundary = {}
        self.observations = []
        self.priority_observations = []
        self.completed = []
        self.used = {}
        self.exhausted_reads = {}
        self.reviewed = set()
        self.review_count = 0
        self._snapshot = None
        self.navigation_pages = {}
        self.navigation_evidence = {}
        self.navigation_delivered = {}
        self.navigation_maps = {}
        self.navigation_received = {}
        self.navigation_searches = {}

    def invalidate(self):
        self.valid = False

    @contextmanager
    def operation(self):
        outer = self.depth == 0
        self.depth += 1
        try:
            if outer:
                self.sync(force=True)
            yield self
        except BaseException:
            # A durable callback invalidates on reducer failure. Other failures
            # may only concern uncommitted working context, so retain the cursor.
            raise
        finally:
            self.depth -= 1

    def _file_identity(self):
        path = self.ledger.path / 'events.sqlite3'
        if not path.exists():
            return None
        stat = path.stat()
        return stat.st_dev, stat.st_ino

    @timed('runtime_sync')
    def sync(self, db=None, *, force=False):
        if self.depth and self.valid and db is None and not force:
            return self
        identity = self._file_identity()
        head = self.ledger.latest_seq(db)
        if not self.valid or identity != getattr(self, '_identity', None) or head < self.last_seq:
            self._reset()
            self.stats['full_reads'] += 1
            self.stats['rebuilds'] += 1
            rows = self.ledger.read(db)
            self._identity = identity
            self.valid = True
        else:
            if head == self.last_seq:
                return self
            self.stats['tail_reads'] += 1
            rows = self.ledger.read_after(self.last_seq, db, through_seq=head)
        try:
            self.stats['rows_decoded'] += len(rows)
            for event in rows:
                self._apply(event, already_applied=False)
        except BaseException:
            self.invalidate()
            raise
        return self

    @timed('runtime_apply')
    def _apply(self, event, *, already_applied):
        if event['seq'] <= self.last_seq:
            raise HarnessError('Runtime events must advance strictly')
        if event['kind'] == 'run_created':
            if self.events:
                raise HarnessError('Runtime ledger contains more than one run header')
            if self.frozen_config is not None and event['config'] != self.frozen_config:
                raise HarnessError('Runtime run identity/configuration changed during rebuild')
            self.frozen_config = deepcopy(event['config'])
        if not already_applied:
            # RunState keeps aliases to event fields. Its private event is
            # distinct from the canonical history retained for hashing/audit.
            self.state.apply(deepcopy(event))
        owned = deepcopy(event)
        self._index(owned)
        if owned.get('cm_context'):
            self.context = deepcopy(owned['cm_context'])
        for key in ('cm_auto_query_view', 'cm_auto_candidate_view'):
            if owned.get(key):
                self.context.update(deepcopy(owned[key]))
        if self.events:
            self.hasher.update(b',')
        self.hasher.update(encode(owned))
        self.events.append(owned)
        self.last_seq = owned['seq']
        self.generation += 1
        self.stats['events_applied'] += 1
        self._snapshot = None

    def committed(self, event, state):
        try:
            if not self.valid:
                raise HarnessError('Committed event reached an invalid runtime')
            if state is not self.state:
                raise HarnessError('Write did not use the current runtime state')
            self._apply(event, already_applied=True)
            self._identity = self._file_identity()
        except BaseException:
            self.invalidate()
            raise

    @property
    def prefix_sha256(self):
        closed = self.hasher.copy()
        closed.update(b']')
        return closed.hexdigest()

    def _need(self, need):
        key = need['source_need_id']
        if key in self.needs and self.needs[key] != need:
            raise HarnessError('Conflicting exact source_need_id; no silent merging')
        self.needs[key] = need

    def _index(self, event):
        kind = event['kind']
        if event.get('cm_tool_repair', {}).get('scope'):
            self.repair_scopes.add(event['cm_tool_repair']['scope'])
        if kind in ('request_result', 'action_result'):
            self.latest_boundary = event
        if kind == 'run_created':
            self.observations.append(event['initial_result']['observation'])
        elif kind == 'request_admitted':
            self.requests[event['request_id']] = event
            if 'cm_query_navigation' in event:
                page = event['cm_query_navigation']
                nav_rows = event['excerpts']
                nav_current = event['current_payload_source_refs']
            else:
                body = event.get('payload', '{}')
                body = json.loads(body) if isinstance(body, str) else body
                page = body.get('m6', {}).get('query_navigation')
                nav_rows = body.get('excerpts', [])
                nav_current = body.get('current_payload_source_refs', [])
            self.navigation_pages[event['request_id']] = page
            self.navigation_evidence[event['request_id']] = [
                (row.get('case_id'), row.get('source_hash'), row['span_bytes']) for row in nav_rows
                if row.get('ref') in nav_current and row.get('source_hash')]
        elif kind == 'request_result':
            self.receipts[event['request_id']] = event
            if event.get('received_response'):
                admission = self.requests[event['request_id']]
                for case, digest, span in self.navigation_evidence.get(event['request_id'], []):
                    self.navigation_delivered.setdefault((case, digest), []).append(span)
                page = self.navigation_pages.get(event['request_id'])
                if page:
                    nav = self.navigation_received.setdefault(page.get('tree_binding'), {'seen': set(), 'previews': set()})
                    nav['seen'].add(page['current']['region_ref'])
                    nav['previews'].update(row['region_ref'] for row in (page['current'], *page['children']))
                for row in admission['excerpts']:
                    if row['ref'] in admission['current_payload_source_refs']:
                        self.delivered.setdefault((row['case_id'], row['source_hash']), []).append(row['span_bytes'])
                query = self.queries.get(admission.get('cm_search_query_id'))
                if query is not None:
                    query['survey_exposed'] = list(dict.fromkeys([*query['survey_exposed'],
                        *(case for case in admission.get('cm_survey_candidates', []) if case in query['candidate_ids'])]))
                    query['raw_exposed'] = list(dict.fromkeys([*query['raw_exposed'],
                        *(row['case_id'] for row in admission['excerpts']
                          if row['ref'] in admission['current_payload_source_refs']
                          and row['case_id'] in query['candidate_ids'] and row['text'].strip())]))
        elif kind == 'action_started':
            self.actions[event['action_id']] = event
            action = event['action']
            if need := action['args'].get('_m6_need'):
                self._need(need)
            if action['action'] == 'assess_links':
                for row in action['args']['assessments']:
                    if row['reason'].startswith('Targeted review: '):
                        self.reviewed.add(row['candidate_id'])
                        self.review_count += 1
        elif kind == 'action_result':
            self.outcomes.append(event)
            started = self.actions.get(event['action_id'], {})
            action = started.get('action', {'action': None, 'args': {}})
            if event['status'] in ('success', 'pending_evidence'):
                self.completed.append(action)
                self.used.setdefault(action['action'], set()).add(fingerprint(action['args']))
            observation = (event.get('result') or {}).get('observation', {})
            if event.get('result') and event['status'] in ('success', 'pending_evidence'):
                if observation.get('kind') == 'query_hierarchy_map':
                    binding = observation.get('tree_binding')
                    nav = self.navigation_maps.setdefault(binding, {'current': None, 'opened': set()})
                    nav['current'] = observation['current']['region_ref']
                    nav['opened'].add(nav['current'])
                if started.get('executes_tool') and action['action'] == 'search_corpus':
                    need = action['args'].get('_m6_need', {})
                    for row in need.get('a_sources', []):
                        self.navigation_searches.setdefault((row['case_id'], row['source_hash']), []).append(row['span_bytes'])
            if need := observation.get('m6_source_need'):
                self.result_needs[need['source_need_id']] = need
                if 'hits' in observation:
                    self.has_search_results = True
                if event['status'] == 'success' and action['action'] == 'search_corpus':
                    self.successful_search_actions.append(action)
            if event.get('result'):
                self.observations.append(observation)
            if (event['status'] == 'success' and action['action'] in ('search_corpus', 'search_identity')
                    and (started['executes_tool'] or event.get('reason') == 'reused_exact_hybrid_search')
                    and 'hits' in observation):
                self.last_search = event
            if event['status'] == 'success' and action['action'] == 'search_corpus' and 'hits' in observation:
                need = action['args'].get('_m6_need', {})
                if need:
                    key = event['action_id']
                    self.queries[key] = {'query_id': key, 'need_id': need['source_need_id'],
                        'issue': action['args']['text'], 'candidate_ids': list(dict.fromkeys(h['case_id'] for h in observation['hits'])),
                        'action_id': key, 'source_need': need, 'retrieval_request_id': observation.get('request_id'),
                        'query_sha256': observation.get('query_sha256'), 'search_reuse': observation.get('search_reuse'),
                        'hits': observation['hits'], 'survey_exposed': [], 'raw_exposed': [],
                        'passage_review': bool(observation.get('cm4_passage_review'))}
            if event['status'] == 'success' and action['action'] == 'open_source' and 'm6_candidate' in action['args']:
                args, result = action['args'], event.get('result') or {}
                candidate = args['m6_candidate']
                if result.get('excerpts'):
                    self.exhausted_reads.pop(candidate['case_id'], None)
                else:
                    self.exhausted_reads[candidate['case_id']] = candidate.get('open_ref')
                lead = args.get('cm4_retrieved_lead')
                if not lead and observation.get('route') == 'open_observed_lead':
                    lead = candidate.get('open_ref')
                if not lead and observation.get('route') == 'within_case_then_open':
                    lead = next((h['open_ref'] for h in observation.get('local_search', {}).get('hits', []) if h.get('open_ref')), None)
                if lead:
                    need_id = args.get('cm4_need_id') or event.get('cm_context', {}).get('need_id')
                    self.opened_leads.append((need_id, candidate['case_id'], lead, event))
                    self.opened_lead_keys.add(fingerprint([need_id, candidate['case_id'], lead]))
        result = event.get('result') or event.get('initial_result') or {}
        observation = result.get('observation', {})
        if isinstance(observation.get('priority_open'), dict):
            self.priority_observations.append(observation['priority_open'])
        for case in [*(h['case_id'] for h in observation.get('hits', [])), *result.get('candidates', [])]:
            if case not in self.case_order:
                self.case_order.append(case)
        if kind != 'action_result' or not event.get('result'):
            return
        need = observation.get('m6_source_need') or self.actions.get(event['action_id'], {}).get('action', {}).get('args', {}).get('_m6_need')
        if not need:
            return
        self._need(need)
        if 'hits' in observation:
            self.operations.append({'operation_id': event['action_id'], 'need_id': need['source_need_id'],
                                    'hits': observation['hits'], 'status': event['status']})
        for hit in observation.get('hits', []):
            row = self.case_records.setdefault(hit['case_id'], {'case_id': hit['case_id'], 'need_ids': [], 'leads': []})
            if need['source_need_id'] not in row['need_ids']:
                row['need_ids'].append(need['source_need_id'])
            if hit not in row['leads']:
                row['leads'].append(hit)
            if hit.get('open_ref'):
                row['open_ref'] = hit['open_ref']

    def snapshot(self):
        """Trusted history-derived Snapshot fields without replay or full-prefix hashing."""
        if self._snapshot is None:
            state = self.state
            ordered = [case for case in self.case_order if case in state.candidates]
            ordered.extend(case for case in state.candidates if case not in ordered)
            self._snapshot = SimpleNamespace(
                needs=self.needs, operations=self.operations,
                candidates=[self.case_records.get(case, {'case_id': case, 'need_ids': [], 'leads': []}) for case in ordered],
                bindings={'identity': state.config['identity'], 'source_hashes': state.source_hashes,
                          'prefix_sha256': self.prefix_sha256})
        return self._snapshot

    def navigation_state(self, case, digest, tree_binding):
        """Exact historical navigation facts; offered rows remain render-specific."""
        if any(binding != tree_binding for binding in self.navigation_maps):
            raise HarnessError('Query map result uses a different tree')
        mapped = self.navigation_maps.get(tree_binding, {})
        received = self.navigation_received.get(tree_binding, {})
        return {'current': mapped.get('current'), 'opened': mapped.get('opened', set()),
                'seen': received.get('seen', set()), 'previews': received.get('previews', set()),
                'searched': self.navigation_searches.get((case, digest), []),
                'delivered': self.navigation_delivered.get((case, digest), []), 'epoch': self.state.actions}
