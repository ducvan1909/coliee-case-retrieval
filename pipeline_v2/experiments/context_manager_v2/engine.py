"""Integrated offline M6 controller on durable M4 events and source validators."""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from jsonschema import Draft202012Validator
from pipeline_v2.agent_harness import Budget, ToolResult, SourceExcerpt
from pipeline_v2.agent_harness.contracts import HarnessError, encode, fingerprint
from pipeline_v2.agent_harness.evidence import SourceDrift, normalize_result, slice_record, source_record
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.agent_harness.harness import AgentHarness
from pipeline_v2.agent_harness.schema import parse_model_response
from pipeline_v2.runtime_timing import measure, timed
from pipeline_v2.experiments.uncapped_probe import policy
from pipeline_v2.experiments.context_manager_v1.core import Snapshot, require, write_once
from .anchor_quote import ANCHOR_QUOTE_SCHEMA, find_anchor
from .assessment_options import attribution_options, speaker_refs
from .evidence import EvidenceStore, lead_window_start, unread_spans
from .read_options import focused_action, focused_read_key, next_unread_expansion, retrieved_action
from .query_options import CONTROLLER_OUTPUT_TOKEN_CAP, MapFirstQueryTools
from .model_view import project, restore_action
from .read_options import execute_candidate_header, execute_retrieved_passage, opened_lead_keys, retrieved_passages
from .tool_repair import bind_repair, repair_feedback, visible_repair
from . import source_gate, query_review, passage_review

VERSION = 'cm4-query-review-v31'
ASSESSMENT_TOOLS = ('assess_case_link', 'review_conflicting_link')
SPEAKER_SIDE_REFS = ('speaker_evidence_refs', 'quote_chain_refs', 'container_refs')
EVIDENCE_CHOICES = (('identity_support_choice', 'identity_support_refs'), ('counterevidence_choice', 'counterevidence'))
CONTEXT_ACTIONS = {'show_context_page', 'set_context_focus', 'record_missing_evidence', 'reload_pair_evidence', 'resume_pair_evidence', 'continue_raw_evidence'}
CONTEXT_ACTIONS |= {'stage_query_anchor', 'defer_query_anchor', 'resume_query_anchor'}
CONTEXT_ACTIONS |= {'assess_source_need', 'assess_source_needs', 'defer_source_need', 'show_source_need_page', 'close_query_anchor', 'choose_source_span', 'revise_source_need', 'read_source_context'}
CONTEXT_ACTIONS |= {'defer_approved_source_need', 'resume_approved_source_need'}
CONTEXT_ACTIONS.add('group_source_needs')
CONTEXT_ACTIONS.add('defer_case_pair')
CONTEXT_ACTIONS |= {'report_review_blocker', 'prioritize_query_results', 'conclude_search_query', 'revisit_source_need', 'read_query_span'}
CONTEXT_ACTIONS |= passage_review.ACTIONS
GATE_MUTATIONS = {'assess_source_need', 'assess_source_needs', 'defer_source_need', 'defer_approved_source_need',
                  'resume_approved_source_need', 'revisit_source_need', 'show_source_need_page', 'choose_source_span', 'revise_source_need'}
GATE_MUTATIONS.add('group_source_needs')
BLOCKER_RECOVERY = {
    'missing_identity': ('open_candidate_header', 'read_more_context', 'record_missing_evidence', 'defer_case_pair'),
    'no_readable_text': ('reload_pair_evidence', 'continue_raw_evidence', 'read_more_context',
                         'read_query_passages', 'record_missing_evidence', 'defer_case_pair'),
    'tool_rejected': ('read_more_context', 'continue_raw_evidence', 'defer_case_pair'),
    'cannot_find_next_step': (),
    'other': (),
}
ANCHOR_VIEW_KEYS = ('need_id', 'candidate_id', 'stage', 'mode', 'offset', 'back', 'query_leaf_region', 'query_map_region')


def code_binding():
    from pipeline_v2.experiments.uncapped_probe.runner import code_binding as base_binding
    directory = Path(__file__).parent
    files = [directory / name for name in ('engine.py', 'evidence.py', 'tool_repair.py', 'assessment_options.py',
                                           'read_options.py', 'query_options.py', 'model_view.py', 'anchor_quote.py',
                                           'source_gate.py', 'query_review.py', 'passage_review.py')]
    files += [directory.parent / 'context_manager_v1' / 'core.py']
    root = directory.parents[2]
    result = base_binding(root)
    result.update({str(p.relative_to(root)).replace('\\', '/'): sha256(p.read_bytes()).hexdigest() for p in files})
    return result


class NoInferenceTransport:
    def __init__(self, count):
        self.count_tokens = count
    def send_structured(self, *args):
        raise AssertionError('CM2/CM3 must never invoke model transport')


class IntegratedHarness(policy.AdaptiveHarness):
    def __init__(self, *args, engine, **kwargs):
        self.engine = engine
        super().__init__(*args, **kwargs)

    def _final(self, reason, detail, prediction=None, assessment_ids=()):
        final = super()._final(reason, detail, prediction, assessment_ids)
        deferred = self.engine.context().get('deferred_pairs', {})
        if deferred:
            final['deferred_pair_count'] = len(deferred)
            if reason == 'complete':
                final['review_status'] = 'partial_with_deferred_pairs'
        if self.engine.gate_enabled:
            rows = query_review.queries(self.engine.events(), self.engine.context())
            unresolved = [key for key, row in rows.items() if not row['conclusion']
                          or row['conclusion']['unresolved_candidate_ids']
                          or row['conclusion']['remaining_source_need'].strip()]
            final['unresolved_search_query_count'] = len(unresolved)
            final['unresolved_search_query_ids'] = unresolved
            if reason == 'complete' and unresolved:
                final['review_status'] = 'partial_with_unresolved_queries'
        if reason == 'complete' and final.get('review_status', '').startswith('partial_'):
            # Preserve the validated selection, rather than invoking the base
            # harness's fallback path for a non-complete stop reason.
            final['stop_reason'] = 'partial'
        return final

    def _validate_stop(self, state, args):
        final = super()._validate_stop(state, args)
        if final['stop_reason'] not in ('complete', 'partial') or final['prediction'] is None:
            return final
        matches = self.engine.context().get('host_citation_matches', {})
        if not matches:
            return final
        for match in matches.values():
            self.engine.citation_lookup.verify(match)
        selected = {match['b']['case_id'] for match in matches.values()}
        final['prediction'] = sorted(set(final['prediction']) | selected)
        final['prediction_host_citation_matches'] = sorted(matches)
        return final

    def _reuse_hybrid_search(self, state, action, actions, outcomes):
        """Locate a committed paid result with the same effective retrieval input."""
        backend = self.hybrid_search
        snapshot = getattr(backend, 'expected_snapshot', None)
        journal = getattr(backend, 'journal', None)
        if not snapshot or journal is None or getattr(backend, 'execution_mode', None) != 'real_query':
            return None
        if state.config.get('m6', {}).get('hybrid_binding') != backend.fingerprint:
            return None
        args = action['args']
        effective = {key: value for key, value in args.items() if key != '_m6_need'}
        query_hash = sha256(args['text'].encode('utf-8')).hexdigest()
        for previous in reversed(outcomes):
            started = actions[previous['action_id']]
            original = started['action']
            if previous['status'] != 'success' or not started['executes_tool'] or original['action'] != 'search_corpus':
                continue
            prior_need = original['args'].get('_m6_need', {})
            prior_effective = {key: value for key, value in original['args'].items() if key != '_m6_need'}
            if prior_effective != effective or prior_need.get('source_need_id') == args['_m6_need']['source_need_id']:
                continue
            result = previous.get('result') or {}
            observation = result.get('observation', {})
            hits = observation.get('hits')
            if (not isinstance(hits, list) or observation.get('m6_source_need') != prior_need
                    or observation.get('query_case') != self.identity.query_id
                    or observation.get('query_sha256') != query_hash
                    or observation.get('execution_mode') != backend.execution_mode
                    or any(observation.get(key) != value for key, value in snapshot.items())):
                continue
            source_action_id = started['action_id']
            operation = fingerprint([source_action_id, args['text'], self.identity.query_id, args['limit']])
            attempt = {'action_id': source_action_id, 'operation': operation, 'query_sha256': query_hash,
                       'query_case': self.identity.query_id, 'limit': args['limit']}
            receipts = [row for row in journal.events() if all(row.get(key) == value for key, value in attempt.items())]
            admitted = [row for row in receipts if row['kind'] == 'search_admitted']
            returned = [row for row in receipts if row['kind'] == 'search_returned']
            source_request_id = observation.get('request_id')
            if (len(admitted) != 1 or len(returned) != 1 or not source_request_id
                    or returned[0].get('status') != 'success' or returned[0].get('m3_request_id') != source_request_id):
                continue
            provenance = {'source_action_id': source_action_id, 'source_operation': operation,
                          'source_m3_request_id': source_request_id}
            return ToolResult({'hits': deepcopy(hits), 'm6_source_need': deepcopy(args['_m6_need']),
                               'query_case': self.identity.query_id, 'query_sha256': query_hash,
                               'search_reuse': provenance}, candidates=result['candidates'])
        return None

    def _apply_action(self, db, state):
        receipt = state.pending_action
        action = receipt['action']
        args = action['args']
        if (self.engine.dual_search is not None and action['action'] == 'search_corpus'
                and args.get('channel') == 'hybrid'):
            self.engine._verify_search_permit(action, self.engine.context())
            original = self.tools['search_corpus']
            parent_id = fingerprint([receipt['request_id'], 'action'])
            def execute_branch(branch):
                previous = self._executing_action_id
                branch_id = fingerprint([parent_id, 'cm4-hybrid-branch', branch['args']['text']])
                self._executing_action_id = branch_id
                try:
                    result = original(branch['args'])
                    return ToolResult({**result.observation, 'cm4_branch_action_id': branch_id},
                                      result.excerpts, result.candidates, result.source_requests)
                finally:
                    self._executing_action_id = previous
            def execute_search(bound):
                lookup = getattr(self.engine, 'citation_lookup', None)
                if lookup is not None:
                    with measure('citation_lookup'):
                        match = lookup.match(bound['_m6_need'])
                    if match is not None:
                        return ToolResult({'hits': [], 'cm4_passage_review': True, 'host_citation_match': match,
                                           'm6_source_need': bound['_m6_need'], 'query_case': self.identity.query_id})
                return self.engine.dual_search(
                    {'action': 'search_corpus', 'args': bound}, execute_branch, self.engine.store.raw_reader)

            self.tools['search_corpus'] = execute_search
            try:
                return super()._apply_action(db, state)
            finally:
                self.tools['search_corpus'] = original
        if self.engine.gate_enabled and action['action'] == 'open_source':
            query = query_review.active(self.engine.events(), self.engine.context())
            require(query is None or query['phase'] == 'reviewing', 'Survey all results before reading candidates')
        if self.engine.gate_enabled and action['action'] in ('search_corpus', 'search_identity'):
            self.engine._verify_search_permit(action, self.engine.context())
        if action['action'] == 'expand_source' and hasattr(self.m3, 'preview_expansion'):
            original = self.tools['expand_source']

            def expand_unread(binding):
                result = next_unread_expansion(self.m3.expand_source, state, binding, {})
                require(result is not None, 'Expansion no longer adds source bytes')
                self.engine._observed_excerpts = list(result.excerpts)
                return result

            self.tools['expand_source'] = expand_unread
            try:
                return super()._apply_action(db, state)
            finally:
                self.tools['expand_source'] = original
        if action['action'] == 'open_source' and 'cm4_retrieved_lead' in args:
            original = self.tools['open_source']

            def open_retrieved(bound):
                result = execute_retrieved_passage(self, state, bound)
                self.engine._observed_excerpts = list(result.excerpts)
                return result

            self.tools['open_source'] = open_retrieved
            try:
                return super()._apply_action(db, state)
            finally:
                self.tools['open_source'] = original
        if action['action'] == 'open_source' and 'cm4_candidate_header' in args:
            original = self.tools['open_source']
            target = args['cm4_candidate_header']
            context = self.engine.context()
            require((target['need_id'], target['case_id']) == (context['need_id'], context['candidate_id'])
                    and source_gate.authorized(context, target['need_id']), 'Candidate header is outside the active pair')
            self.tools['open_source'] = lambda bound: execute_candidate_header(self, state, bound['cm4_candidate_header'])
            try:
                return super()._apply_action(db, state)
            finally:
                self.tools['open_source'] = original
        if action['action'] != 'search_corpus' or args.get('channel') != 'hybrid' or '_m6_need' not in args:
            return super()._apply_action(db, state)
        digest = fingerprint(action)
        if digest in state.tool_actions:
            return super()._apply_action(db, state)

        events = self.events()
        actions = {row['action_id']: row for row in events if row['kind'] == 'action_started'}
        outcomes = [row for row in events if row['kind'] == 'action_result']
        duplicated = any(actions[row['action_id']]['action_fingerprint'] == digest
                         and (row.get('result') or {}).get('observation', {}).get('search_reuse')
                         for row in outcomes)
        started = perf_counter()
        reused = None if duplicated else self._reuse_hybrid_search(state, action, actions, outcomes)
        if not duplicated and reused is None:
            return super()._apply_action(db, state)
        action_id = fingerprint([receipt['request_id'], 'action'])
        self._write(db, state, 'action_started', action_id=action_id, request_id=receipt['request_id'],
                    action=action, action_fingerprint=digest, executes_tool=False)
        if duplicated:
            outcome = normalize_result(ToolResult({'action': 'search_corpus', 'status': 'duplicate'}), state)
            self._action_result(db, state, 'duplicate', result=outcome, reason='duplicate_action', started=started)
        else:
            outcome = normalize_result(reused, state, search=True)
            self._action_result(db, state, 'success', result=outcome, reason='reused_exact_hybrid_search', started=started)

    @timed('registry_and_map')
    def _registry(self, state, payload):
        context = self.engine.context()
        registry_payload = {**payload, '_cm4_query_navigation_enabled': context['mode'] == 'query'}
        full = policy.OriginalAdaptiveHarness._registry(self, state, registry_payload)
        if self.engine.gate_enabled:
            full['review_candidates'] = {}
        context = self.engine.context()
        events = self.events()
        snapshot = Snapshot.from_events(events, {})
        opened_leads = opened_lead_keys(events)
        need_id, candidate_id = context['need_id'], context['candidate_id']
        mode = context['mode']
        expansion_cases = (candidate_id,) if isinstance(self.m3, MapFirstQueryTools) else (self.identity.query_id, candidate_id)
        preview = getattr(self.m3, 'preview_expansion', None)
        full['expansions'] = {
            key: option for key, option in full['expansions'].items()
            if option.get('description', {}).get('case_id') in expansion_cases
            and (preview is None or next_unread_expansion(
                preview, state, option['binding'], self.engine._expansion_previews) is not None)
        }
        lead_cursor = self.engine._progress(context).get('lead_source_continuation')
        lead_can_continue = any(option['binding'] == lead_cursor for option in full['expansions'].values())
        candidates = full['candidates']
        leading_hits = {}
        for operation in reversed(snapshot.operations):
            if operation['need_id'] == need_id:
                for hit in operation['hits']:
                    if hit.get('open_ref'):
                        leading_hits.setdefault(hit['case_id'], hit)
        if mode == 'results':
            op = next((op for op in reversed(snapshot.operations) if op['need_id'] == need_id), None)
            order = list(dict.fromkeys(h['case_id'] for h in op['hits'])) if op else []
        elif mode == 'pool':
            order = [row['case_id'] for row in snapshot.candidates]
        elif mode == 'needs':
            order = []
        else:
            order = [candidate_id] if candidate_id else []
        by_case = {row['case_id']: (key, row) for key, row in candidates.items()}
        page = order[context['offset']:context['offset'] + self.engine.render_page_size]
        deferred = context.get('deferred_pairs', {})
        reviewed = {case for case in order if (need_id, case) in state.active_assessments
                    and (need_id, case) not in state.pending_assessments} if mode == 'results' else set()
        reviewed.update(case for case in order if fingerprint([need_id, case]) in deferred)
        prioritize_unfinished = (mode == 'results' and bool(page) and len(reviewed) < len(order)
                                 and all(case in reviewed for case in page))
        selected = {}
        displayed = list(dict.fromkeys([*page, candidate_id])) if mode == 'assessment' else page
        for case in displayed:
            if case not in by_case:
                continue
            key, row = by_case[case]
            row = deepcopy(row)
            row['needs'] = [n for n in row['needs'] if n['source_need_id'] == need_id]
            row.pop('open_ref', None)
            row.pop('already_opened', None)
            lead = leading_hits.get(case)
            if lead:
                row['open_ref'] = deepcopy(lead['open_ref'])
                if fingerprint([need_id, case, row['open_ref']]) in opened_leads:
                    row['already_opened'] = True
            # A previous need's no-hit reader cannot block a different need or focus.
            if row.get('read_status') == 'no_new_raw_use_context_or_another_candidate':
                row.pop('read_status')
            # Pool cards from another need are browse-only.
            if not row['needs']:
                row['read_status'] = 'other_need_select_need_first'
            elif fingerprint([need_id, case]) in deferred:
                row['read_status'] = 'deferred_missing_evidence'
            elif not self.engine.gate_enabled and context['stage'] == 'reading' and candidate_id != case:
                row['read_status'] = 'finish_pair_or_record_missing_first'
            elif prioritize_unfinished:
                row['read_status'] = 'assessed_use_unfinished_results'
            selected[key] = row
        if candidate_id and self.engine._has_pending_pair_source(state, context, payload['cm_coverage'], lead_can_continue):
            for row in selected.values():
                if row['case_id'] == candidate_id and not row.get('read_status'):
                    row['read_status'] = 'queued_raw_available_use_continue_or_expand'
        full['candidates'] = selected
        full['retrieved_passages'] = retrieved_passages(opened_leads, selected, leading_hits, need_id)
        if mode != 'query':
            full.pop('query_navigation', None)
            full['query_maps'], full['query_targets'] = {}, {}
        elif 'query_navigation' in full:
            current_map = full['query_navigation']['current']['region_ref']
            full['query_maps'] = {key: value for key, value in full['query_maps'].items()
                                  if value['binding']['region_ref'] != current_map}
            if isinstance(self.m3, MapFirstQueryTools):
                targets = {}
                options = sorted(full['query_targets'].items(),
                                 key=lambda item: item[1]['binding']['region_ref'] != self.m3.query_tree.root_ref)
                for key, option in options:
                    region = option['binding']['region_ref']
                    next_context = {**context, 'mode': 'query_leaf', 'offset': 0, 'back': [],
                                    'query_leaf_region': region, 'revision': context['revision'] + 1}
                    projection = (self.engine._query_leaf_payload(state, next_context)
                                  if self.m3.can_read_region(region) else None)
                    fits = projection is not None and projection[4] <= self.budget.max_payload_tokens
                    if region == self.m3.query_tree.root_ref:
                        full['whole_query_fit'] = {'input_tokens': projection[4] if projection else None,
                                                   'fits': fits, 'max_payload_tokens': self.budget.max_payload_tokens}
                    if fits:
                        targets[key] = {**option, 'description': {**option['description'], 'response': 'full_text'}}
                        if region == current_map == self.m3.query_tree.root_ref:
                            break
                    else:
                        split = self.m3.split_option(option)
                        if split:
                            map_ref, map_option = split
                            if map_option['binding']['region_ref'] != current_map:
                                targets[map_ref] = map_option
                if self.engine.gate_enabled:
                    left, right = full['query_navigation']['current']['span_bytes']
                    remaining = source_gate.unscreened_spans(
                        context, self.identity.query_source_hash, self.query_paragraphs)
                    spans = {ref: tuple(option['description']['span_bytes']) for ref, option in targets.items()}
                    if any(left <= start < end <= right and (start, end) != (left, right)
                           and any(start < gap_end and gap_start < end for gap_start, gap_end in remaining)
                           for start, end in spans.values()):
                        # Returning to a larger map would reoffer this unfinished branch.
                        targets = {ref: option for ref, option in targets.items()
                                   if not (spans[ref][0] <= left and right <= spans[ref][1])}
                full['query_targets'] = targets
                full['query_maps'] = {}
                whole_choice = next((row for row in targets.values()
                                     if row['binding']['region_ref'] == self.m3.query_tree.root_ref), None)
                if not targets or (len(targets) == 1 and whole_choice and whole_choice['description'].get('response') == 'full_text'):
                    full.pop('query_navigation')
        # Full historical reload catalog stays outside the prompt. Pair reload is explicit.
        full['reloads'] = {}
        citation_pages = full['citation_search_pages'].items()
        full['citation_search_pages'] = dict(sorted(citation_pages, key=lambda item:
            item[1]['binding'].get('_m6_need', {}).get('source_need_id') != need_id)[:1])
        full['review_candidates'] = {k: v for k, v in full['review_candidates'].items() if k == candidate_id}
        native_ranks = {hit['case_id']: hit.get('rank') for operation in snapshot.operations
                        if operation['need_id'] == need_id for hit in operation['hits']}
        ordered_cards = [{'candidate_ref': by_case[case][0], 'case_id': case,
                          'original_rank': native_ranks.get(case), 'read_allowed': False}
                         for case in page if case in by_case and by_case[case][0] in selected]
        for card in ordered_cards:
            lead = leading_hits.get(card['case_id'])
            if lead:
                preview = self.engine._survey_preview(lead)
                if preview:
                    card['literal_preview'] = preview
        full['cm_page'] = {'total': len(order), 'offset': context['offset'], 'count': len(ordered_cards),
                           'candidates': ordered_cards}
        full['cm_context'] = {key: context[key] for key in ('need_id', 'candidate_id', 'stage', 'mode')}
        # Literal previews and canonical hashes remain intact; remove repeated need copies.
        table = {}
        for row in selected.values():
            refs = []
            for need in row['needs']:
                key = 'n' + fingerprint(need)[:16]
                require(key not in table or table[key] == need, 'Need hash collision')
                table[key] = need
                refs.append(key)
            row['needs'] = refs
        if table:
            full['source_needs'] = table
        return full

    def _write(self, db, state, kind, **fields):
        if kind == 'request_result':
            fields.update(getattr(self.engine, '_reply_metadata', {}))
            self.engine._reply_metadata = {}
            if fields.get('telemetry_error') and fields.get('cm_tool_repair'):
                fields['cm_tool_repair']['retry_allowed'] = False
            if fields.get('telemetry_error'):
                fields.pop('cm_batch_length_recovery', None)
        if kind == 'action_result' and 'cm_context' not in fields:
            context = self.engine.context()
            action = state.active_action['action'] if state.active_action else {}
            self.engine._transition_result(context, action, fields)
            context['revision'] = context.get('revision', 0) + 1
            fields['cm_context'] = context
        return super()._write(db, state, kind, **fields)


class Engine:
    """No provider calls. Scripted replies exercise actual dispatch and validators."""
    def __init__(self, directory, *, identity, tools, count_tokens, raw_reader,
                 config=None, initial_observation=None, query_excerpt=None,
                 hybrid_search=None, counter_binding=None, page_size=5, execution_mode='offline', run_binding=None,
                 gate_enabled=False, selector=None, selector_fingerprint=None, loop_guard_mode=None,
                 dual_search=None, embedding_profile=None):
        from pipeline_v2.m6 import AdaptiveConfig
        require(execution_mode in ('offline', 'live'), 'Invalid execution mode')
        self.execution_mode = execution_mode
        self.gate_enabled = gate_enabled
        self.dual_search = dual_search
        self.embedding_profile = deepcopy(embedding_profile)
        self.loop_guard_mode = loop_guard_mode or ('warn' if gate_enabled else 'stop')
        require(self.loop_guard_mode in ('warn', 'stop'), 'Invalid loop guard mode')
        require(type(gate_enabled) is bool, 'Source gate flag must be boolean')
        self._reply_metadata = {}
        self._expansion_previews = {}
        self._survey_previews = {}
        self.directory = Path(directory)
        self.page_size = page_size
        self.render_page_size = page_size
        require(type(page_size) is int and 1 <= page_size <= 5, 'page_size must be 1..5')
        self.store = EvidenceStore(raw_reader)
        self.counter_binding = counter_binding
        self.harness = IntegratedHarness(directory, engine=self, identity=identity,
            budget=Budget(2**60, 2**60, 2**60, 8500, CONTROLLER_OUTPUT_TOKEN_CAP, None, 0), m3_tools=tools,
            transport=NoInferenceTransport(count_tokens), config=config or AdaptiveConfig(),
            initial_observation=initial_observation, query_excerpt=query_excerpt, hybrid_search=hybrid_search,
            selector=selector, selector_fingerprint=selector_fingerprint)
        if gate_enabled:
            self.harness.config['m6'].pop('validated_support', None)
            self.harness.config['m6'].update(model_attribution=True, model_support=True)
        self.harness.config['cm23'] = {'version': VERSION, 'code': code_binding(),
                                     'counter_binding': counter_binding, 'page_size': page_size,
                                     'passage_review': dual_search is not None,
                                     'source_gate': source_gate.VERSION if gate_enabled else None,
                                     'provider_execution': 'forbidden_offline' if execution_mode == 'offline' else 'live_user_or_AG',
                                     'run_binding': run_binding}
        self._observed_excerpts = []
        for name, tool in list(self.harness.tools.items()):
            def observe(args, tool=tool):
                result = tool(args)
                self._observed_excerpts = list(result.excerpts)
                return result
            self.harness.tools[name] = observe
        with self.harness.ledger.writer() as db:
            state = RunState(self.harness.ledger.read(db))
            self.harness._start(db, state)

    def events(self):
        return self.harness.events()

    def state(self):
        return RunState(self.events())

    def context(self):
        context = {'need_id': None, 'candidate_id': None, 'stage': 'ready', 'mode': 'query',
                   'offset': 0, 'back': [], 'revision': 0, 'pair_pins': {}, 'pair_targets': {}, 'pair_progress': {}}
        for event in self.events():
            if event.get('cm_context'):
                context = deepcopy(event['cm_context'])
            if event.get('cm_auto_query_view'):
                context.update(deepcopy(event['cm_auto_query_view']))
        self._sync_missing(context)
        return context

    @staticmethod
    def _progress(context, pair=None):
        pair = pair or fingerprint([context['need_id'], context['candidate_id']])
        return context['pair_progress'].setdefault(pair, {'window_offsets': {}, 'next_offsets': {},
            'active_roots': {}, 'completed_roots': []})

    @staticmethod
    def _blocker_scope(context):
        if context['mode'] in ('assessment', 'results', 'pool', 'needs', 'parked'):
            return fingerprint([context['need_id'], context['candidate_id']])
        return fingerprint([context.get('query_leaf_region') if context['mode'] == 'query_leaf'
                            else context.get('query_map_region')])

    @classmethod
    def _sync_missing(cls, context):
        # The active reason belongs to this exact need/candidate, never the last pair.
        context.pop('missing_reason', None)
        reason = cls._progress(context).get('missing_reason')
        if context['stage'] == 'missing_evidence' and reason:
            context['missing_reason'] = reason

    @classmethod
    def _commit_coverage(cls, context, coverage):
        progress = cls._progress(context)
        for row in coverage:
            ref = row['canonical_ref']
            seen = progress.setdefault('offered_spans', {}).setdefault(ref, [])
            if row['offered'] not in seen:
                seen.append(row['offered'])
            lead = progress.get('lead_windows', {}).get(ref)
            if lead is not None:
                if row['offered'] not in lead['offered']:
                    lead['offered'].append(row['offered'])
                if row['pending'] is None:
                    progress['completed_roots'] = list(dict.fromkeys([*progress['completed_roots'], ref]))
                continue
            progress['next_offsets'][ref] = max(progress['next_offsets'].get(ref, row['offered'][0]), row['offered'][1])
            if row['pending'] is None:
                progress['completed_roots'] = list(dict.fromkeys([*progress['completed_roots'], ref]))

    def _transition_result(self, context, action, fields, *, reopen_stage=None):
        """Establish results/no-hit from a successful search or exact reuse."""
        status = fields.get('status')
        name, args = action.get('action'), action.get('args', {})
        if self.gate_enabled and name == 'search_corpus' and status in ('success', 'duplicate'):
            need = args.get('_m6_need', {})
            gate_ref = need.get('source_gate_ref')
            if gate_ref:
                decision = context['source_gate'][gate_ref]
                decision.update(status='searched', need_id=need['source_need_id'])
                context.setdefault('source_gate_searches', {})[need['source_need_id']] = deepcopy(decision)
        confirmed_draft = (context.get('active_anchor_draft')
                           if name == 'search_corpus' and status in ('success', 'duplicate') else None)
        if confirmed_draft:
            context['anchor_drafts'].pop(confirmed_draft)
            context.pop('active_anchor_draft')
        if status == 'duplicate':
            need = args.get('_m6_need', {}).get('source_need_id')
            if name in ('search_corpus', 'search_identity') and need and (need == context['need_id'] or confirmed_draft):
                snapshot = Snapshot.from_events(self.events(), {})
                operation = next((row for row in reversed(snapshot.operations) if row['need_id'] == need), None)
                if operation and confirmed_draft:
                    context.update(need_id=need, candidate_id=None, mode='results', offset=0, back=[],
                                   stage='results_ready' if operation['hits'] else 'no_hit')
                elif operation and operation['hits']:
                    context.update(mode='results', offset=0, back=[])
            return
        if name == 'assess_links' and status == 'pending_evidence':
            context['stage'] = 'missing_evidence'
            pending = [row for row in (fields.get('pending_assessments') or [])
                       if row.get('candidate_id') == context['candidate_id']]
            reported = []
            for row in pending:
                notes = row.get('reported_missing_evidence')
                if isinstance(notes, str):
                    notes = [notes]
                reported.extend(note for note in (notes or []) if isinstance(note, str))
            codes = [reason for row in pending for reason in (row.get('missing_evidence') or []) if isinstance(reason, str)]
            progress = self._progress(context)
            if progress.get('lead_windows'):
                progress['lead_reviewed'] = True
            progress['reported_missing_evidence'] = [reason[:240] for reason in reported[:3]]
            progress['validation_missing_codes'] = codes[:5]
            reasons = reported or codes
            if reasons:
                progress['missing_reason'] = '; '.join(reasons)[:240]
            self._sync_missing(context)
            return
        if status != 'success':
            if status in ('error', 'unknown'):
                context['stage'] = 'error'
            return
        observation = (fields.get('result') or {}).get('observation', {})
        if name == 'search_corpus' and (match := observation.get('host_citation_match')):
            require(getattr(self, 'citation_lookup', None) is not None, 'Host citation selection is disabled')
            query_id, case = fields['action_id'], match['b']['case_id']
            need_id = args['_m6_need']['source_need_id']
            context.setdefault('host_citation_matches', {})[query_id] = deepcopy(match)
            context.setdefault('candidate_conclusions', {})[query_id] = {case: {
                'decision': 'select', 'disposition': 'confirmed_identity', 'status': 'final',
                'selection_origin': 'host_exact_citation', 'action_id': query_id, 'query_id': query_id,
                'need_id': need_id, 'a_refs': [match['a']['ref']], 'identity_refs': [match['b']['ref']],
                'reason': 'The approved A citation matches the self-identified decision B.'}}
            context.setdefault('query_conclusions', {})[query_id] = {
                'outcome': 'resolved', 'reason': 'Exact self-citation matched a unique corpus decision.',
                'remaining_source_need': '', 'unresolved_reason': '', 'candidate_ids': [case],
                'unresolved_candidate_ids': [], 'not_read_candidate_ids': []}
            context.pop('passage_session', None)
            context.update(need_id=need_id, candidate_id=None, stage='ready', mode='query', offset=0, back=[])
            return
        if name == 'open_query' and observation.get('kind') == 'query_hierarchy_map':
            context.update(mode='query', offset=0, back=[], query_map_region=observation['current']['region_ref'])
        if name == 'open_query' and observation.get('cm4_query_leaf_span') is not None:
            context.update(mode='query_leaf', offset=0, back=[], query_leaf_region=observation['query_navigation_ref'])
        if name in ('search_corpus', 'search_identity') and args.get('_m6_need') and 'hits' in observation:
            context.update(need_id=args['_m6_need']['source_need_id'], candidate_id=None,
                           mode='results', offset=0, back=[],
                           stage='results_ready' if observation['hits'] else 'no_hit')
            self._progress(context).pop('missing_reason', None)
        if name == 'open_source' and args.get('m6_candidate'):
            context.update(candidate_id=args['m6_candidate']['case_id'],
                           mode='results' if reopen_stage else 'assessment', offset=0, back=[],
                           stage=reopen_stage or 'reading')
            if reopen_stage is None:
                self._progress(context).pop('missing_reason', None)
        if name == 'assess_links':
            context['stage'] = 'missing_evidence' if fields.get('pending_assessments') else 'assessed'
            if context['stage'] == 'assessed':
                progress = self._progress(context)
                if progress.get('lead_windows'):
                    progress['lead_reviewed'] = True
                for key in ('missing_reason', 'reported_missing_evidence', 'validation_missing_codes'):
                    progress.pop(key, None)
        self._sync_missing(context)

    @timed('feedback_from_history')
    def _feedback(self, context):
        """Bounded projection of durable outcomes, not an unbounded chat history."""
        events = self.events()
        actions = {row['action_id']: row for row in events if row['kind'] == 'action_started'}
        outcomes = [row for row in events if row['kind'] == 'action_result']
        last = outcomes[-1] if outcomes else None
        last_search = next((row for row in reversed(outcomes)
            if row.get('status') == 'success' and row['action_id'] in actions
            and actions[row['action_id']]['action']['action'] in ('search_corpus', 'search_identity')
            and (actions[row['action_id']]['executes_tool'] or row.get('reason') == 'reused_exact_hybrid_search')
            and 'hits' in (row.get('result') or {}).get('observation', {})), None)
        summary = None
        if last_search:
            started = actions[last_search['action_id']]
            observation = last_search['result']['observation']
            hits = observation['hits']
            summary = {'action_id': last_search['action_id'], 'status': 'success',
                'source_need_id': started['action']['args']['_m6_need']['source_need_id'],
                'hit_count': len(hits),
                'first_results_native_order': [{'case_id': row['case_id'], 'original_rank': row.get('rank', index + 1)}
                    for index, row in enumerate(hits[:5])], 'results_omitted': max(0, len(hits) - 5)}
            if observation.get('search_reuse'):
                summary['source_action_id'] = observation['search_reuse']['source_action_id']
            if match := observation.get('host_citation_match'):
                summary['host_selection'] = {'case_id': match['b']['case_id'],
                                             'citation': match['a']['text'], 'decision': 'select'}
        outcome = {'status': 'not_yet_executed'}
        if last:
            started = actions[last['action_id']]
            action = started['action']
            search = action['action'] in ('search_corpus', 'search_identity')
            observation = (last.get('result') or {}).get('observation', {})
            outcome = {'action_id': last['action_id'], 'action': action['action'],
                'status': last['status'], 'reason': (last.get('reason') or '')[:240],
                'search_executed': bool(started.get('executes_tool')) if search else None,
                'hit_count': len(observation['hits']) if search and last['status'] == 'success' and 'hits' in observation else None}
            if action['action'] == 'assess_source_need' and last['status'] == 'success':
                submitted = action['args']['assessment']
                committed = context.get('source_gate', {}).get(submitted['source_need_ref'], submitted)
                outcome['source_gate'] = {key: committed[key] for key in (
                    'paragraph_handle', 'proposed_decision', 'decision', 'status', 'validation_message')}
            if search and last['status'] == 'duplicate':
                outcome['message'] = 'Duplicate search was not executed. Existing results are retained; this is not a no-hit search.'
                prior = next((q for q in query_review.queries(events, context).values()
                              if q['need_id'] == action['args'].get('_m6_need', {}).get('source_need_id')
                              and q['issue'] == action['args'].get('text') and q['conclusion']), None)
                if prior:
                    outcome['concluded_query_id'] = prior['query_id']
                    outcome['previous_conclusion'] = {key: prior['conclusion'][key]
                        for key in ('outcome', 'reason', 'unresolved_reason', 'remaining_source_need')}
                    outcome['message'] = ('This exact query and anchor were already concluded. '
                        'The prior conclusion is retained without new retrieval or survey. '
                        'Revisit the source need and change the query if more evidence is needed.')
            elif last['status'] == 'duplicate' and (read_key := focused_read_key(action)) is not None:
                need_id, case_id, focus = read_key
                outcome['duplicate_focus'] = {'need_id': need_id, 'case_id': case_id, 'focus': focus}
                outcome['message'] = 'This candidate focus was already tried for this need. It was not searched again.'
            elif search and (match := observation.get('host_citation_match')):
                outcome.update(search_executed=False, matched_case_id=match['b']['case_id'],
                               message='The host resolved this need by exact self-citation. No retrieval ran.')
            elif search and observation.get('search_reuse'):
                outcome['source_action_id'] = observation['search_reuse']['source_action_id']
                outcome['message'] = 'Reused exact hybrid results for this need. No retrieval or embedding ran again.'
            elif last.get('reason') == 'reopened_without_new_raw':
                outcome['message'] = 'The reader found no new candidate text for this pair. Its accepted assessment is still active.'
        if last:
            receipt = next((row for row in reversed(events) if row['kind'] == 'request_result'
                            and row['request_id'] == started['request_id']), {})
            raw = receipt.get('raw_model_reply')
            try:
                chosen = parse_model_response(raw) if isinstance(raw, str) else raw
            except Exception:
                chosen = None
            outcome['canonical_action'] = action['action']
            outcome['model_tool'] = chosen.get('action') if isinstance(chosen, dict) else None
        feedback = {'last_action': outcome, 'last_successful_search': summary,
                    'next_options': []}
        if repair := visible_repair(events):
            feedback['tool_repair'] = repair
        if context.get('missing_reason'):
            feedback['missing_reason'] = context['missing_reason'][:240]
        if context['stage'] == 'missing_evidence':
            progress = self._progress(context)
            feedback['reported_missing_evidence'] = progress.get('reported_missing_evidence', [])[:3]
            feedback['validation_missing_codes'] = progress.get('validation_missing_codes', [])[:5]
            feedback['guidance'] = ('Evidence is missing. Continue or expand the query excerpt or candidate excerpt '
                                    'if an offered read addresses the gap. You can also browse other candidates or '
                                    'needs, switch focus, search a new need, or finish. Assess only from current '
                                    'excerpts. Repeating a read adds no evidence.')
        if context['stage'] == 'results_ready':
            feedback['guidance'] = 'Search returned candidates. Read any eligible candidate, browse results, or record concrete missing evidence before starting another search need.'
        elif context['stage'] == 'reading':
            feedback['guidance'] = 'Finish this pair with assessment or record missing evidence before switching need or candidate.'
        return feedback

    def _has_pending_pair_source(self, state, context, coverage, lead_can_continue):
        pair = fingerprint([context['need_id'], context['candidate_id']])
        progress = self._progress(context, pair)
        if lead_can_continue:
            return True
        full_in_view = {row['canonical_ref'] for row in coverage if row['pending'] is None}
        return any(ref not in progress['completed_roots'] for ref in context['pair_pins'].get(pair, [])
                   if ref in state.catalog and state.catalog[ref]['case_id'] == context['candidate_id']
                   and ref not in full_in_view)

    def _prioritize_initial_hit(self, context, action, fields, known, fresh_refs):
        """Track the target bytes and any reader cursor needed to fetch them."""
        args = action['args']
        candidate = args.get('m6_candidate')
        case = context['candidate_id']
        pair = fingerprint([context['need_id'], case])
        progress = self._progress(context, pair)
        native_continuation = (action['action'] == 'expand_source'
                               and args == progress.get('lead_source_continuation'))
        if not (action['action'] == 'open_source' and candidate) and not native_continuation:
            return
        roots = [ref for ref in fresh_refs if known[ref]['case_id'] == case]
        # Any committed raw from this side means this is not its initial offer.
        if not roots or (not native_continuation and not args.get('cm4_retrieved_lead')
                         and any(ref in progress['next_offsets'] for ref, row in known.items() if row['case_id'] == case)):
            return
        observation = (fields.get('result') or {}).get('observation', {})
        opened = args if native_continuation else candidate.get('open_ref') or {}
        expected_hash = opened.get('source_hash') or observation.get('source_hash')
        if opened.get('case_id', case) != case:
            return
        roots = [ref for ref in roots if expected_hash is None or known[ref]['source_hash'] == expected_hash]
        requested_ids = set(opened.get('passage_ids', []))
        hits = observation.get('hit_refs', [])
        matched = [hit for hit in hits if hit.get('ref') in requested_ids]
        # hit_refs belong to this actual reader result; unlike requested_spans,
        # they identify the trigger rather than its whole neighbor envelope.
        selected_hits = matched if requested_ids else hits
        if observation.get('continuation') and any(hit.get('pending_spans') for hit in selected_hits):
            progress['lead_source_continuation'] = observation['continuation']
            progress['lead_reviewed'] = False
        else:
            progress.pop('lead_source_continuation', None)
        spans = [span for hit in selected_hits for span in (hit.get('delivered_spans') or [hit.get('span_bytes')])
                 if isinstance(span, (list, tuple)) and len(span) == 2]
        if not spans:
            spans = [lead['span_bytes'] for lead in (candidate or {}).get('leads', [])
                     if lead.get('source_need_id') == context['need_id'] and lead.get('span_bytes')]
        if not roots or not spans:
            return
        def overlap(ref):
            start, end = known[ref]['span_bytes']
            return sum(max(0, min(end, right) - max(start, left)) for left, right in spans)
        best = max(roots, key=overlap)
        if overlap(best):
            progress['active_roots'][case] = best
            pins = context['pair_pins'][pair]
            first = next(i for i, ref in enumerate(pins) if known[ref]['case_id'] == case)
            pins.remove(best)
            pins.insert(first, best)
            windows = progress.setdefault('lead_windows', {})
            for ref in roots:
                start, end = known[ref]['span_bytes']
                portions = [(max(start, left), min(end, right)) for left, right in spans
                            if max(start, left) < min(end, right)]
                if portions and ref not in windows and ref not in progress['next_offsets']:
                    windows[ref] = {'span': [min(left for left, _ in portions), max(right for _, right in portions)],
                                    'offered': []}
                    progress['lead_reviewed'] = False

    @staticmethod
    def _lead_review_status(context, coverage, lead_can_continue):
        """Include the prospective payload in the coverage check for the first assessment."""
        pair = fingerprint([context['need_id'], context['candidate_id']])
        progress = context['pair_progress'].get(pair, {})
        if lead_can_continue:
            return True, None
        if progress.get('lead_reviewed'):
            return False, None
        windows = progress.get('lead_windows', {})
        current = {row['canonical_ref']: row['offered'] for row in coverage}
        first = None
        visible = False
        for ref in context['pair_pins'].get(pair, []):
            if ref in windows:
                lead = windows[ref]
                offered = [*lead['offered'], *([current[ref]] if ref in current else [])]
                if unread_spans(lead['span'], offered):
                    return True, None
                start, end = lead['span']
                first = first or (ref, start, end)
                if ref in current:
                    visible |= max(start, current[ref][0]) < min(end, current[ref][1])
        return (True, first) if first and not visible else (False, None)

    @timed('assemble_source_rows')
    def _rows(self, state, context, byte_limit):
        pair = fingerprint([context['need_id'], context['candidate_id']])
        pins = list(context['pair_pins'].get(pair, []))
        progress = self._progress(context, pair)
        needs = [e['result']['observation'].get('m6_source_need') for e in self.events()
                 if e['kind'] == 'action_result' and e.get('result')]
        need = next((n for n in reversed(needs) if n and n['source_need_id'] == context['need_id']), None)
        if not pins:
            if need:
                pins.extend(ref for ref in need['a_refs'] if ref in state.catalog)
            if context['candidate_id']:
                pins.extend(ref for ref in state.pending if state.catalog[ref]['case_id'] == context['candidate_id'])
                if not any(state.catalog[ref]['case_id'] == context['candidate_id'] for ref in pins):
                    pins.extend(ref for ref in reversed(state.catalog) if state.catalog[ref]['case_id'] == context['candidate_id'])
            elif context['mode'] == 'query':
                pins.extend(ref for ref in state.pending if state.catalog[ref]['case_id'] == self.harness.identity.query_id)
        rows, coverage = [], []
        seen_cases = set()
        pins = list(dict.fromkeys(pins))
        pins.sort(key=lambda ref: progress['active_roots'].get(state.catalog[ref]['case_id']) != ref)
        for ref in pins:
            if ref not in state.catalog:
                raise HarnessError('Pinned evidence missing from catalog')
            record = state.catalog[ref]
            if record['case_id'] in seen_cases:
                continue
            if record['case_id'] not in (self.harness.identity.query_id, context['candidate_id']):
                raise HarnessError('Pinned evidence belongs to another pair')
            offset = progress['window_offsets'].get(ref)
            anchor = need.get('a_paragraph') if need and record['case_id'] == self.harness.identity.query_id else None
            requested = anchor['span_bytes'] if anchor and anchor['source_ref'] == ref else None
            if record['case_id'] != self.harness.identity.query_id:
                requested = progress.get('reopened_spans', {}).get(ref)
            limit = byte_limit
            query_anchor = need.get('a_anchor') if anchor and requested else None
            if query_anchor and query_anchor['source_ref'] == ref:
                start, end = query_anchor['span_bytes']
                if offset is None or offset == start:
                    limit = max(limit, end - start)
                    if offset is None:
                        offset = max(requested[0], lead_window_start(record, [start, end], limit))
            lead = progress.get('lead_windows', {}).get(ref) if requested is None else None
            if lead is not None:
                if offset is None:
                    offset = lead_window_start(record, lead['span'], limit)
                else:
                    gap = next((right for left, right in unread_spans(record['span_bytes'], lead['offered'])
                                if left <= offset < right), None)
                    if gap is not None:
                        limit = min(limit, gap - offset)
            part, spans = self.store.window(record, offset=offset, byte_limit=limit, requested_span=requested)
            if lead is not None:
                offered = [*lead['offered'], spans['offered']]
                pending = unread_spans(lead['span'], offered) or unread_spans(spans['requested'], offered)
                spans['pending'] = pending[0] if pending else None
            if part['text'].strip():
                rows.append(part)
                seen_cases.add(record['case_id'])
            coverage.append(spans)
            # At most one A and one B window per current working view.
            if context['candidate_id'] and len({r['case_id'] for r in rows}) == 2:
                break
        if context['mode'] == 'assessment' and (header := progress.get('candidate_header')):
            rows.extend(self._header_rows(state, context['candidate_id'], header, rows))
        return rows, coverage

    def _header_rows(self, state, case_id, header, rows):
        visible = [row['span_bytes'] for row in rows if row['case_id'] == case_id]
        gaps = unread_spans(header['span_bytes'], visible)
        if not gaps:
            return []
        records = [row for row in state.catalog.values() if row['case_id'] == case_id
                   and row['source_hash'] == header['source_hash']
                   and row['span_bytes'][0] < header['span_bytes'][1]]
        parts = []
        for start, end in gaps:
            while start < end:
                record = max((row for row in records if row['span_bytes'][0] <= start < row['span_bytes'][1]),
                             key=lambda row: row['span_bytes'][1], default=None)
                require(record is not None, 'Candidate header is missing from verified source catalog')
                right = min(end, record['span_bytes'][1])
                part, _ = self.store.window(record, offset=start, byte_limit=right - start)
                parts.append(part)
                start = right
        return parts

    @staticmethod
    def _branch(name, properties):
        return {'type': 'object', 'additionalProperties': False, 'required': ['action', 'args'],
                'properties': {'action': {'const': name}, 'args': {'type': 'object', 'additionalProperties': False,
                'properties': properties, 'required': list(properties)}}}

    @staticmethod
    def _speaker_supported_refs(payload, refs, quoted):
        allowed = set(refs)
        return speaker_refs([row for row in payload['excerpts'] if row['ref'] in allowed],
                            'quoted_source' if quoted else 'court')

    @staticmethod
    def _bind_assessment_sides(payload, tools, branches, pairs, *, model_attribution=False):
        """Give each decoder branch the same pair and speaker side as M4."""
        if not pairs:
            return branches
        rows_by_case = {}
        current = set(payload['current_payload_source_refs'])
        for row in payload['excerpts']:
            if row['ref'] in current:
                rows_by_case.setdefault(row['case_id'], []).append(row)
        refs_by_case = {case: [row['ref'] for row in rows] for case, rows in rows_by_case.items()}
        query_id = payload['query_id']
        a_refs = refs_by_case[query_id]
        b_refs = {pair['candidate_id']: refs_by_case[pair['candidate_id']] for pair in pairs.values()}
        payload['m6']['assessment_ref_sides'] = {'A': a_refs, 'B_by_candidate': b_refs}

        offered_pairs = {ref for branch in branches
                         if branch['properties']['action']['const'] in ASSESSMENT_TOOLS
                         for ref in branch['properties']['args']['properties']['pair_ref']['enum']}
        options_by_pair = {}
        if not model_attribution:
            a_options = list(attribution_options(rows_by_case[query_id], 'A'))
            b_options = {case: list(attribution_options(rows_by_case[case], 'B')) for case in b_refs}
            options_by_pair = {key: [*b_options[pair['candidate_id']], *a_options] for key, pair in pairs.items()
                               if key in offered_pairs}
        if options_by_pair:
            payload['m6']['assessment_attribution_options'] = options_by_pair

        for tool in tools:
            if tool['name'] not in ASSESSMENT_TOOLS:
                continue
            properties = tool['parameters']['properties']
            for new, old in EVIDENCE_CHOICES:
                properties.pop(old)
                properties[new] = {'type': 'string', 'enum': ['A', 'B', 'A+B'],
                                   'description': 'Choose excerpts from the query case, candidate case, or both cases. Omit when unsupported.'}
            if model_attribution:
                for name in SPEAKER_SIDE_REFS:
                    properties[name]['items']['choices_from'] = 'm6.assessment_ref_sides for the selected pair and speaker side'
                tool['when'] += (' If you identify a speaker, choose its role, type and side from the current excerpts. '
                                 'Speaker and quotation references are optional and must come from that side.')
                continue
            for name in SPEAKER_SIDE_REFS:
                properties[name]['items']['choices_from'] = 'm6.assessment_attribution_options for the selected pair'
            properties['speaker']['choices_from'] = 'm6.assessment_attribution_options for the selected pair'
            tool['when'] += (
                ' Use one attribution option for the chosen pair. Set speaker.side to "query case" for a query excerpt. '
                'For a quote chain, use that option\'s container and all of its chain refs. '
                'A pending_only option records missing evidence. Read more or omit speaker if attribution is unresolved.'
            )

        if model_attribution:
            return Engine._model_speaker_branches(branches, pairs, a_refs, b_refs)

        specialized = []
        for branch in branches:
            if branch['properties']['action']['const'] not in ASSESSMENT_TOOLS:
                specialized.append(branch)
                continue
            params = branch['properties']['args']
            for pair_ref in params['properties']['pair_ref']['enum']:
                for option in options_by_pair[pair_ref]:
                    variant = deepcopy(branch)
                    args = variant['properties']['args']
                    fields = args['properties']
                    fields['pair_ref']['enum'] = [pair_ref]
                    known_speaker = option['role'] != 'unknown'
                    complete_quote = bool(option.get('quote_chain_refs'))
                    for field, refs in (('speaker_evidence_refs', option['speaker_refs']),
                                        ('container_refs', option['container_refs']),
                                        ('quote_chain_refs', option.get('quote_chain_refs', []))):
                        if not refs:
                            fields.pop(field)
                            continue
                        fields[field]['items']['enum'] = refs
                        if len(refs) == 1:
                            fields[field]['maxItems'] = 1
                        if complete_quote and field != 'speaker_evidence_refs':
                            fields[field]['minItems'] = len(refs)
                            fields[field]['maxItems'] = len(refs)
                            args['required'].append(field)
                        elif known_speaker and field == 'speaker_evidence_refs':
                            fields[field]['minItems'] = 1
                            args['required'].append(field)
                    for new, old in EVIDENCE_CHOICES:
                        fields.pop(old)
                        fields[new] = {'type': 'string', 'enum': ['A', 'B', 'A+B']}
                    speaker = next(item for item in fields['speaker']['anyOf']
                                   if item['properties']['role']['const'] == option['role'])
                    if known_speaker:
                        speaker['properties']['type']['enum'] = [option['type']]
                        speaker['properties']['side']['enum'] = [option['side']]
                        if option['side'] == 'A':
                            speaker['required'].append('side')
                        args['required'].append('speaker')
                    fields['speaker']['anyOf'] = [speaker]
                    specialized.append(variant)
        return specialized

    @staticmethod
    def _model_speaker_branches(branches, pairs, query_refs, candidate_refs):
        specialized = []
        for branch in branches:
            if branch['properties']['action']['const'] not in ASSESSMENT_TOOLS:
                specialized.append(branch)
                continue
            params = branch['properties']['args']
            for pair_ref in params['properties']['pair_ref']['enum']:
                candidate = pairs[pair_ref]['candidate_id']
                for side, refs in ((None, []), ('A', query_refs), ('B', candidate_refs[candidate])):
                    variant = deepcopy(branch)
                    args = variant['properties']['args']
                    fields = args['properties']
                    fields['pair_ref']['enum'] = [pair_ref]
                    for new, old in EVIDENCE_CHOICES:
                        fields.pop(old)
                        fields[new] = {'type': 'string', 'enum': ['A', 'B', 'A+B']}
                    speakers = fields['speaker']['anyOf']
                    if side is None:
                        fields['speaker']['anyOf'] = [speakers[0]]
                        for field in SPEAKER_SIDE_REFS:
                            fields.pop(field)
                    else:
                        fields['speaker']['anyOf'] = speakers[1:]
                        args['required'].append('speaker')
                        for speaker in speakers[1:]:
                            speaker['properties']['side']['enum'] = [side]
                            speaker['required'].append('side')
                        for field in SPEAKER_SIDE_REFS:
                            fields[field]['items']['enum'] = refs
                    specialized.append(variant)
        return specialized

    @staticmethod
    def _has_new_assessment_raw(state, pair, current):
        need_id, case_id = pair['source_need_id'], pair['candidate_id']
        if (need_id, case_id) not in state.active_assessments:
            return True

        previous = {}
        for assessment in state.assessments.values():
            if (assessment['source_need_id'], assessment['candidate_id']) != (need_id, case_id):
                continue
            for ref_field in ('a_context_refs', 'b_passage_refs'):
                for record in assessment['raw_evidence'][ref_field]:
                    key = record['case_id'], record['source_hash']
                    previous.setdefault(key, []).append(record['span_bytes'])

        for ref in pair['a_context_refs'] + pair['b_passage_refs']:
            record = current[ref]
            position, end = record['span_bytes']
            key = record['case_id'], record['source_hash']
            for left, right in sorted(previous.get(key, [])):
                if left > position or position >= end:
                    break
                position = max(position, right)
            if position < end:
                return True
        return False

    @staticmethod
    def _new_deferred_refs(state, deferred):
        choices = {}
        for ref, record in state.catalog.items():
            if record['case_id'] != deferred['candidate_id'] or not record['text'].strip():
                continue
            for start, end in unread_spans(record['span_bytes'], deferred['known_spans']):
                if slice_record(record, start, end)['text'].strip():
                    choices[ref] = [start, end]
                    break
        return choices

    @timed('catalog_and_schema')
    def _catalog(self, payload, state, context, coverage):
        lead_cursor = self._progress(context).get('lead_source_continuation')
        lead_can_continue = any(option['binding'] == lead_cursor for option in payload['m6']['expansions'].values())
        lead_waiting, revisit_lead = self._lead_review_status(context, coverage, lead_can_continue)
        if lead_waiting:
            payload['m6']['expansions'] = {
                ref: option for ref, option in payload['m6']['expansions'].items()
                if option['binding'] == lead_cursor}
        tools, schema, citations, pairs = policy.catalog(payload)
        finish_tool = next(tool for tool in tools if tool['name'] == 'finish_case_review')
        if self.gate_enabled:
            finish_tool['description'] = 'End evidence collection. The prediction uses the cases you assessed as supported.'
        finish_branch = next(branch for branch in schema['anyOf']
                             if branch['properties']['action']['const'] == 'finish_case_review')
        for params in (finish_tool['parameters'], finish_branch['properties']['args']):
            reasons = params['properties']['reason']['enum']
            params['properties']['reason']['enum'] = [reason for reason in reasons if reason != 'no_progress']
        finish_tool['when'] = ('Use complete_policy after all retrieved pairs are reviewed. '
                               'Use failure only for a concrete error blocking the review.')
        search_available = any(tool['name'] == 'search_cases_by_issue' for tool in tools)
        for tool in tools:
            name = tool['name']
            if name == 'search_cases_by_issue':
                tool['description'] = 'Find candidate cases for one proposition in a current query excerpt.'
                tool['when'] = ('Copy a distinctive phrase inside one visible query paragraph as anchor_quote. '
                                'Use the same phrase to ground issue and source_proposition.')
                tool['examples'][0] = ('Copy the relevant words from the query excerpt. Choose a longer quote '
                                       'if those words occur more than once.')
                branch = next(row for row in schema['anyOf']
                              if row['properties']['action']['const'] == name)
                for params in (tool['parameters'], branch['properties']['args']):
                    params['properties'].pop('a_paragraph_ref')
                    params['properties']['anchor_quote'] = dict(ANCHOR_QUOTE_SCHEMA)
                    params['required'] = [key for key in params['required'] if key != 'a_paragraph_ref'] + ['anchor_quote']
            elif name == 'read_query_passages' and isinstance(self.harness.m3, MapFirstQueryTools):
                tool['description'] = 'Read a selected region of the query case.'
                tool['when'] = 'Choose a query_ref from query_targets. Use this tool to select a smaller region or return to a larger region.'
                tool['result'] = 'A complete query excerpt if it fits, otherwise a map of smaller regions.'
            elif name == 'reload_evidence':
                tool['description'] = 'Bring earlier query and candidate excerpts back into the next payload.'
                tool['examples'][0] = 'Choose one evidence_ref for the query and candidate pair.'
            elif name == 'assess_case_link':
                tool['description'] = 'Assess whether the query case cites or relies on the candidate case.'
                tool['when'] = 'Use current query and candidate excerpts. Similarity alone does not establish reliance.'
                tool['examples'][1] = 'A shared quotation from a third case is insufficient to infer reliance.'
        citations = {}
        payload['m6']['citation_search_pages'] = {}
        # Completion describes reviewed retrieval results.
        events = self.events()
        snapshot = Snapshot.from_events(events, {})
        feedback = payload['last_action_feedback']
        drafts = context.get('anchor_drafts', {})
        active_draft_id = context.get('active_anchor_draft')
        active_draft = drafts.get(active_draft_id)
        need = snapshot.needs.get(context['need_id'], {})
        query_anchor = need.get('a_anchor')
        revisit_query_anchor = None
        if query_anchor:
            left, right = query_anchor['span_bytes']
            current_anchor = next((row for row in payload['excerpts']
                if row['case_id'] == payload['query_id'] and row['source_hash'] == payload['query_source_hash']
                and row['span_bytes'][0] <= left < right <= row['span_bytes'][1]), None)
            if current_anchor:
                payload['query_anchor'] = {'source_ref': current_anchor['ref'], 'span_bytes': [left, right],
                                           'paragraph_ref': need['a_paragraph']['paragraph_handle']}
            elif context['mode'] == 'assessment' or pairs:
                revisit_query_anchor = query_anchor
        deferred = context.get('deferred_pairs', {})
        deferred_keys = {(row['need_id'], row['candidate_id']) for row in deferred.values()}
        pending_pairs = [pair for pair in state.pending_assessments if pair not in deferred_keys]
        unreviewed_pairs = []
        if payload['m6'].get('search_completed') or drafts:
            retrieved_pairs = dict.fromkeys((operation['need_id'], hit['case_id'])
                for operation in snapshot.operations if operation['status'] == 'success'
                for hit in operation['hits'] if hit['case_id'] in state.candidates)
            pending_pair_keys = state.pending_assessments.keys()
            accepted_pairs = (retrieved_pairs.keys() & state.active_assessments.keys()) - pending_pair_keys
            unreviewed_pairs = [pair for pair in retrieved_pairs
                                if pair not in accepted_pairs and pair not in pending_pair_keys
                                and pair not in deferred_keys]
            legacy_cases = state.candidates.keys() - {case for _, case in retrieved_pairs}
            reviewed_cases = {case for _, case in state.active_assessments} | {case for _, case in pending_pairs}
            unread = list(dict.fromkeys([*(case for _, case in unreviewed_pairs),
                *(case for case in state.candidates if case in legacy_cases
                  and case not in reviewed_cases)]))
            pending_count = len(pending_pairs)
            complete_allowed = not unread and not pending_count and not drafts
            unfinished = set(unread) | {case for _, case in [*pending_pairs, *deferred_keys]}
            payload['last_action_feedback']['review_progress'] = {
                'retrieved_candidates': len(state.candidates),
                'accepted_candidates': len({case for _, case in state.active_assessments} - unfinished),
                'retrieval_only_candidates': len(unread), 'retrieval_only_examples': unread[:3],
                'retrieved_pairs': len(retrieved_pairs), 'accepted_pairs': len(accepted_pairs),
                'unreviewed_pairs': len(unreviewed_pairs),
                'remaining_pair_examples': [{'need_id': need, 'case_id': case}
                    for need, case in [*pending_pairs, *unreviewed_pairs][:3]],
                'pending_pairs': pending_count, 'complete_policy_allowed': complete_allowed,
            }
            if deferred:
                feedback['review_progress']['deferred_pairs'] = len(deferred)
            if drafts:
                feedback['review_progress']['unresolved_anchor_drafts'] = len(drafts)
            if not complete_allowed:
                for params in (finish_tool['parameters'], finish_branch['properties']['args']):
                    reasons = params['properties']['reason']
                    reasons['enum'] = [reason for reason in reasons['enum'] if reason != 'complete_policy']
                finish_tool['when'] = ('Review remains open. Use results or needs to reach unreviewed pairs, '
                                       'or continue pending evidence. Use failure only for a concrete error blocking the review.')
        current = {row['ref']: row for row in payload['excerpts']}
        gated = {ref for ref, pair in pairs.items() if
                 not all(any(current[raw]['text'].strip() for raw in pair[side])
                         for side in ('a_context_refs', 'b_passage_refs'))
                 or not self._has_new_assessment_raw(state, pair, current)}
        if lead_waiting or revisit_query_anchor:
            tools = [tool for tool in tools if tool['name'] not in ASSESSMENT_TOOLS]
            schema['anyOf'] = [branch for branch in schema['anyOf']
                               if branch['properties']['action']['const'] not in ASSESSMENT_TOOLS]
        elif gated:
            eligible = [ref for ref in pairs if ref not in gated]
            if eligible:
                prompt = next(tool for tool in tools if tool['name'] == 'assess_case_link')
                prompt['parameters']['properties']['pair_ref'] = {'type': 'string', 'enum': eligible}
                branch = next(row for row in schema['anyOf'] if row['properties']['action']['const'] == 'assess_case_link')
                branch['properties']['args']['properties']['pair_ref']['enum'] = eligible
            else:
                tools = [tool for tool in tools if tool['name'] != 'assess_case_link']
                schema['anyOf'] = [branch for branch in schema['anyOf']
                                   if branch['properties']['action']['const'] != 'assess_case_link']
        blocked = {'find_citation_matches', 'continue_citation_search'}
        if context['stage'] in ('reading', 'results_ready') or active_draft:
            blocked.add('search_cases_by_issue')
        if blocked:
            tools = [tool for tool in tools if tool['name'] not in blocked]
            schema = {**schema, 'anyOf': [branch for branch in schema['anyOf']
                      if branch['properties']['action']['const'] not in blocked]}
        handles = {}
        def handle(kind, target):
            key = kind[0] + fingerprint([self.harness.identity.run_id, context['revision'], kind, target])[:16]
            require(key not in handles or handles[key] == {'kind': kind, **target}, 'Context handle collision')
            handles[key] = {'kind': kind, **deepcopy(target)}
            return key
        controls = {}
        page = payload['m6']['cm_page']
        pair_key = fingerprint([context['need_id'], context['candidate_id']])
        parked = [pair for pair, target in context['pair_targets'].items()
                  if pair != pair_key and pair in context['pair_pins'] and target['need_id'] and target['candidate_id']]
        safe = self.gate_enabled or context['stage'] in ('ready', 'assessed', 'missing_evidence', 'error', 'no_hit')
        if context['mode'] == 'needs':
            need_ids = list(snapshot.needs)[context['offset']:context['offset'] + self.render_page_size]
            page.update(total=len(snapshot.needs), count=len(need_ids))
            page['needs'] = [{'ref': handle('need', {'need_id': key}),
                              'issue': snapshot.needs[key].get('intent', '')[:160]} for key in need_ids]
        if context['mode'] == 'parked':
            selected_pairs = parked[context['offset']:context['offset'] + self.render_page_size] if safe else []
            page.update(total=len(parked) if safe else 0, count=len(selected_pairs), candidates=[])
        else:
            selected_pairs = []
        if context['mode'] == 'anchor_drafts':
            total = len(drafts) if safe and not active_draft else 0
            page.update(total=total, count=min(self.render_page_size, max(0, total - context['offset'])),
                        candidates=[])
        if context['offset'] + page['count'] < page['total'] and page['count']:
            controls['next'] = handle('page', {'mode': context['mode'], 'offset': context['offset'] + page['count'],
                                             'back': [*context['back'], context['offset']]})
        if context['back']:
            controls['previous'] = handle('page', {'mode': context['mode'], 'offset': context['back'][-1], 'back': context['back'][:-1]})
        result_operation = next((row for row in reversed(snapshot.operations) if row['need_id'] == context['need_id']), None)
        tree = getattr(self.harness.m3, 'query_tree', None)
        full_query_shown = (active_draft and tree and context['mode'] == 'query_leaf'
                            and context.get('query_leaf_region') == tree.root_ref)
        reachable = {'query': not full_query_shown, 'results': bool(result_operation and result_operation['hits']),
                     'pool': bool(state.candidates), 'needs': any(key != context['need_id'] for key in snapshot.needs),
                     'parked': safe and bool(parked), 'assessment': bool(context['candidate_id']),
                     'anchor_drafts': safe and not active_draft and len(drafts) > self.render_page_size}
        active_query = query_review.active(self.events(), context) if self.gate_enabled else None
        for mode, available in reachable.items():
            target_offset = (query_review.first_unseen_offset(active_query) or 0) if mode == 'results' and active_query else 0
            if available and (mode != context['mode'] or context['offset'] != target_offset):
                controls[mode] = handle('page', {'mode': mode, 'offset': target_offset, 'back': []})
        if active_query:
            backlog = query_review.pending_read_next(active_query)
            if active_query['phase'] == 'reviewing' and backlog:
                target_offset = active_query['candidate_ids'].index(backlog[0])
                if context['mode'] != 'results' or context['offset'] != target_offset:
                    controls['read_next'] = handle('page', {'mode': 'results', 'offset': target_offset, 'back': []})
            current_cases = [card['case_id'] for card in page.get('candidates', [])] if context['mode'] == 'results' else []
            unseen = query_review.first_unseen_offset(active_query, current_cases)
            if unseen is not None:
                target = {'mode': 'results', 'offset': unseen, 'back': [*context['back'], context['offset']] if context['mode'] == 'results' else []}
                controls['next_unseen'] = handle('page', target)
            # Results is a resume route, not a duplicate previous/next control.
            for preferred in ('previous', 'next', 'next_unseen'):
                if preferred in controls and 'results' in controls:
                    a, b = handles[controls[preferred]], handles[controls['results']]
                    if (a['mode'], a['offset']) == (b['mode'], b['offset']):
                        del controls['results']
            if 'next' in controls and 'next_unseen' in controls:
                a, b = handles[controls['next']], handles[controls['next_unseen']]
                if (a['mode'], a['offset']) == (b['mode'], b['offset']):
                    del controls['next']
        page['controls'] = controls
        branches = list(schema['anyOf'])
        def add(name, fields, description):
            branches.append(self._branch(name, fields))
            tools.append({'name': name, 'description': description, 'parameters': {'type': 'object', 'properties': fields, 'required': list(fields)}})
        if drafts and not self.gate_enabled:
            anchor_view = {'status': 'parked', 'unresolved_total': len(drafts), 'candidates': [], 'parked': []}
            if active_draft:
                resolved, suggested = find_anchor(payload, active_draft['args']['anchor_quote'])
                choices = [resolved] if resolved else suggested[:3]
                source_rows = {row['ref']: row for row in payload['excerpts']}
                paragraph_counts = {}
                for paragraph_key, anchor in choices:
                    ref = handle('anchor', {'draft_id': active_draft_id, 'paragraph_key': paragraph_key, 'anchor': anchor})
                    paragraph_ref = payload['m6']['a_paragraphs'][paragraph_key]['paragraph_handle']
                    paragraph_counts[paragraph_ref] = paragraph_counts.get(paragraph_ref, 0) + 1
                    candidate = {
                        'anchor_ref': ref, 'text': anchor['text'], 'span_bytes': anchor['span_bytes'],
                        'paragraph_ref': paragraph_ref,
                    }
                    left, right = anchor['span_bytes']
                    components = source_rows[anchor['source_ref']].get('provenance', {}).get('components', [])
                    marker = next((row['observed_marker'] for row in components if row.get('observed_marker') is not None
                                   and row['span_bytes'][0] <= left < right <= row['span_bytes'][1]), None)
                    if marker is not None:
                        candidate['paragraph_marker'] = marker
                    anchor_view['candidates'].append(candidate)
                for candidate, (_, anchor) in zip(anchor_view['candidates'], choices):
                    if paragraph_counts[candidate['paragraph_ref']] > 1:
                        row = source_rows[anchor['source_ref']]
                        raw = row['text'].encode('utf-8')
                        base = row['span_bytes'][0]
                        left, right = (point - base for point in anchor['span_bytes'])
                        candidate['prefix'] = raw[max(0, left - 24):left].decode('utf-8', errors='ignore')
                        candidate['suffix'] = raw[right:right + 24].decode('utf-8', errors='ignore')
                anchor_view.update(issue=active_draft['args']['issue'],
                                   source_proposition=active_draft['args']['source_proposition'],
                                   anchor_quote=active_draft['args']['anchor_quote'],
                                   status='awaiting_choice' if choices else 'needs_query_text')
                if choices and search_available:
                    add('choose_query_anchor', {'anchor_ref': {'type': 'string', 'enum': [
                        row['anchor_ref'] for row in anchor_view['candidates']]}},
                        'Confirm a visible query excerpt and run the saved search.')
                elif choices:
                    anchor_view['status'] = 'search_unavailable'
                add('defer_query_anchor', {}, 'Park this unresolved search and continue other review work.')
            elif safe:
                offset = context['offset'] if context['mode'] == 'anchor_drafts' else 0
                for draft_id, draft in list(drafts.items())[offset:offset + self.render_page_size]:
                    ref = handle('draft', {'draft_id': draft_id})
                    anchor_view['parked'].append({'draft_ref': ref, 'issue': draft['args']['issue']})
                if anchor_view['parked']:
                    add('resume_query_anchor', {'draft_ref': {'type': 'string', 'enum': [
                        row['draft_ref'] for row in anchor_view['parked']]}}, 'Return to a parked search and choose its query excerpt.')
            feedback['anchor_resolution'] = anchor_view
        direct_reads = payload['m6'].get('retrieved_passages', {})
        if direct_reads:
            add('open_retrieved_passage', {'lead_ref': {'type': 'string', 'enum': list(direct_reads)}},
                'Read the candidate excerpt indicated by a retrieval lead. No focus phrase is required.')
        candidate = context['candidate_id']
        if (self.gate_enabled and context['mode'] == 'assessment' and candidate in state.source_hashes
                and source_gate.authorized(context, context['need_id'])):
            header = self._progress(context, pair_key).get('candidate_header')
            if header:
                feedback['candidate_header'] = {'case_id': candidate, 'span_bytes': header['span_bytes']}
            else:
                add('open_candidate_header', {},
                    'Read the beginning of the current candidate case alongside the retrieved passage. '
                    'Use it to check the case identity before assigning supported when the identity is unclear.')
        for tool in tools:
            if tool['name'] == 'read_case_passages':
                tool['description'] = 'Search inside this candidate case for a new legal focus and open a matching candidate excerpt.'
                tool['when'] = 'Use a legal phrase of at least two words. Use open_retrieved_passage for an existing retrieval lead.'
        if controls:
            add('show_context_page', {'page_ref': {'type': 'string', 'enum': list(dict.fromkeys(controls.values()))}}, 'View another page without changing the source need or candidate.')
        need_refs = [key for key, value in handles.items() if value['kind'] == 'need' and value['need_id'] != context['need_id']]
        next_need = next((need for need, _ in [*pending_pairs, *unreviewed_pairs]
                          if need != context['need_id'] and need in snapshot.needs), None)
        if safe and next_need is not None and 'review_progress' in feedback:
            ref = handle('need', {'need_id': next_need})
            if ref not in need_refs:
                need_refs.append(ref)
            feedback['review_progress']['next_need_ref'] = ref
        if safe and need_refs:
            add('set_context_focus', {'need_ref': {'type': 'string', 'enum': need_refs}}, 'Switch need after a useful work boundary, without discarding previous evidence.')
        if (context['candidate_id'] and context['stage'] == 'reading') or (context['need_id'] and context['stage'] == 'results_ready'):
            add('record_missing_evidence', {'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}}, 'Record concrete missing evidence before switching away from this pair.')
        focused_pair = context['need_id'], context['candidate_id']
        if all(focused_pair) and context['stage'] == 'missing_evidence' and pair_key not in deferred and (
                focused_pair not in state.active_assessments or focused_pair in state.pending_assessments):
            add('defer_case_pair', {'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}},
                'Record what evidence remains missing for this need and candidate, then return to results. '
                'The pair remains unresolved. Continue reviewing the other candidates or query paragraphs.')
        pins = context['pair_pins'].get(pair_key, [])
        first_roots = {}
        for ref in pins:
            first_roots.setdefault(state.catalog[ref]['case_id'], ref)
        if context['need_id'] and context['candidate_id'] and pair_key in context['pair_targets'] and any(
                row['offered'][0] > row['requested'][0]
                or first_roots.get(state.catalog[row['canonical_ref']]['case_id']) != row['canonical_ref']
                for row in coverage if row['canonical_ref'] in pins):
            reload_ref = handle('pair', {'pair': pair_key})
            add('reload_pair_evidence', {'evidence_ref': {'type': 'string', 'enum': [reload_ref]}}, 'Reload earlier source text for this pair.')
        if selected_pairs:
            resume_refs = [handle('resume', {'pair': pair, **context['pair_targets'][pair]})
                           for pair in selected_pairs if pair in parked
                           and (pair not in deferred or self._new_deferred_refs(state, deferred[pair]))]
            page['parked_pairs'] = [{'ref': key, 'need_id': handles[key]['need_id'], 'candidate_id': handles[key]['candidate_id']} for key in resume_refs]
            page['deferred_pairs'] = [{key: deferred[pair][key] for key in ('need_id', 'candidate_id', 'reason')}
                                      for pair in selected_pairs if pair in deferred]
            if resume_refs:
                add('resume_pair_evidence', {'evidence_ref': {'type': 'string', 'enum': resume_refs}},
                    'Return to a parked need/candidate and reload exact source refs without a new search or source-read call.')
        progress = self._progress(context, pair_key)
        continuations = {}
        for row in coverage:
            if row['pending']:
                ref = row['canonical_ref']
                start, end = row['pending']
                offset = start if ref in progress.get('lead_windows', {}) else max(start, progress['next_offsets'].get(ref, start))
                if offset < end:
                    key = handle('continuation', {'ref': ref, 'offset': offset, 'pair': pair_key})
                    continuations[key] = [offset, end]
        offered_roots = {row['canonical_ref'] for row in coverage}
        other_roots = [ref for ref in context['pair_pins'].get(pair_key, [])
                       if ref not in offered_roots and ref not in progress['completed_roots']
                       and progress['next_offsets'].get(ref, 0) < state.catalog[ref]['span_bytes'][1]]
        if lead_waiting:
            other_roots.sort(key=lambda ref: not (ref in progress.get('lead_windows', {})
                and unread_spans(progress['lead_windows'][ref]['span'], progress['lead_windows'][ref]['offered'])))
        next_roots = []
        sides = set()
        for ref in other_roots:
            side = state.catalog[ref]['case_id']
            if side not in sides:
                next_roots.append(ref)
                sides.add(side)
        for ref in next_roots:
            record = state.catalog[ref]
            requested = progress.get('reopened_spans', {}).get(ref)
            lead = progress.get('lead_windows', {}).get(ref) if requested is None else None
            if lead:
                pending = unread_spans(lead['span'], lead['offered']) or unread_spans(record['span_bytes'], lead['offered'])
                if not pending:
                    continue
                offset, end = pending[0]
            else:
                start, end = requested or record['span_bytes']
                offset = max(start, progress['next_offsets'].get(ref, start))
                if offset >= end:
                    continue
            key = handle('continuation', {'ref': ref, 'offset': offset, 'pair': pair_key})
            continuations[key] = [offset, end]
        payload['cm_unoffered_raw'] = [{'ref': ref, 'case_id': state.catalog[ref]['case_id'],
                                       'span_bytes': list(state.catalog[ref]['span_bytes'])} for ref in next_roots]
        payload['cm_unoffered_raw_count'] = len(other_roots)
        payload['pending_source_count'] += len(other_roots)
        if revisit_lead:
            ref, offset, end = revisit_lead
            key = handle('continuation', {'ref': ref, 'offset': offset, 'pair': pair_key})
            continuations[key] = [offset, end]
            payload['lead_review_option'] = {'context_ref': key, 'span_bytes': [offset, end]}
        if revisit_query_anchor:
            ref = revisit_query_anchor['source_ref']
            offset, end = revisit_query_anchor['span_bytes']
            key = handle('continuation', {'ref': ref, 'offset': offset, 'pair': pair_key})
            continuations[key] = [offset, end]
            payload['query_anchor_option'] = {'context_ref': key, 'span_bytes': [offset, end]}
        if continuations:
            add('continue_raw_evidence', {'context_ref': {'type': 'string', 'enum': list(continuations)}},
                'Read an offered UTF-8 source window for the next excerpt.')
        payload['m6'].update(citation_refs=citations, pair_refs=pairs, policy_version=policy.VERSION)
        branches = self._bind_assessment_sides(
            payload, tools, branches, pairs, model_attribution=self.gate_enabled)
        read_branch = next((row for row in branches if row['properties']['action']['const'] == 'read_case_passages'), None)
        readable_refs = read_branch['properties']['args']['properties']['candidate_ref']['enum'] if read_branch else []
        candidate_rows = payload['m6']['candidates']
        visible_cases = {row['case_id'] for row in candidate_rows.values()}
        recent_focuses = {}
        for event in reversed(events):
            if event['kind'] != 'action_started' or not event.get('executes_tool'):
                continue
            key = focused_read_key(event['action'])
            if key is None or key[0] != context['need_id'] or key[1] not in visible_cases:
                continue
            _, case, focus = key
            focuses = recent_focuses.setdefault(case, [])
            if len(focuses) < 3 and focus not in focuses:
                focuses.append(focus)
        if recent_focuses:
            feedback['recent_candidate_focuses'] = recent_focuses
        last_action = feedback.get('last_action', {})
        duplicate = last_action.get('duplicate_focus')
        if duplicate and duplicate['need_id'] == context['need_id']:
            case = duplicate['case_id']
            unfinished = set(unreviewed_pairs) | set(pending_pairs)
            other_readable = any(candidate_rows[ref]['case_id'] != case
                and (context['need_id'], candidate_rows[ref]['case_id']) in unfinished for ref in readable_refs)
            back_to_other_results = 'results' in controls and any(
                need == context['need_id'] and other_case != case for need, other_case in unfinished)
            has_alternative = bool(direct_reads or continuations or other_readable or back_to_other_results
                                   or (safe and next_need is not None)
                                   or any(tool['name'] in ('read_more_context', 'assess_case_link') for tool in tools))
            if has_alternative:
                keep = [ref for ref in readable_refs if candidate_rows[ref]['case_id'] != case]
                if keep != readable_refs:
                    feedback['focus_retry_paused_case_id'] = case
                    for ref in readable_refs:
                        if ref not in keep:
                            candidate_rows[ref]['read_status'] = 'duplicate_focus_use_other_offered_options'
                    if keep:
                        readable_refs[:] = keep
                        tool = next(tool for tool in tools if tool['name'] == 'read_case_passages')
                        tool['parameters']['properties']['candidate_ref'] = {'type': 'string', 'enum': keep}
                    else:
                        branches = [row for row in branches if row is not read_branch]
                        tools = [tool for tool in tools if tool['name'] != 'read_case_passages']
                    readable_refs = keep
        readable = set(readable_refs)
        lead_by_candidate = {row['description']['candidate_ref']: ref for ref, row in direct_reads.items()}
        for card in payload['m6']['cm_page']['candidates']:
            candidate_ref = card['candidate_ref']
            card['read_allowed'] = candidate_ref in readable or candidate_ref in lead_by_candidate
            if candidate_ref in lead_by_candidate:
                card['retrieved_lead_ref'] = lead_by_candidate[candidate_ref]
        unread_readable = any(card['read_allowed'] and (context['need_id'], card['case_id']) not in state.active_assessments
                              and (context['need_id'], card['case_id']) not in state.pending_assessments
                              for card in page['candidates'])
        recover_search = (context['mode'] == 'results' and unread_readable and last_action.get('status') == 'duplicate'
                          and last_action.get('action') in ('search_corpus', 'search_identity'))
        if recover_search:
            tools = [tool for tool in tools if tool['name'] != 'search_cases_by_issue']
            branches = [branch for branch in branches if branch['properties']['action']['const'] != 'search_cases_by_issue']
        schema = {'type': 'object', 'anyOf': branches}
        payload['available_tools'] = tools
        feedback['next_options'] = [tool['name'] for tool in tools]
        focused_pair = context['need_id'], context['candidate_id']
        assessment_id = state.active_assessments.get(focused_pair)
        focus_gated = any((pairs[ref]['source_need_id'], pairs[ref]['candidate_id']) == focused_pair for ref in gated)
        if assessment_id and (context['stage'] == 'assessed' or focus_gated):
            accepted = state.assessments[assessment_id]
            feedback['active_assessment'] = {name: accepted[name] for name in
                                             ('assessment_id', 'candidate_id', 'case_relation', 'passage_location')}
        if context['stage'] == 'assessed' and assessment_id:
            feedback['guidance'] = ('This pair already has an accepted assessment. To make progress, read new relevant raw '
                                    'evidence, open results to inspect another candidate, open needs to switch focus, '
                                    'or finish when evidence collection is complete. Reassessment requires new raw for this pair.')
            if feedback['last_action'].get('reason') == 'reopened_without_new_raw':
                feedback['guidance'] = ('The reread produced no new candidate text. Choose an unread candidate in '
                                        'these results, or open needs to switch focus.')
            feedback['navigation_options'] = [{'tool': 'show_context_page', 'args': {'page_ref': controls[mode]}, 'view': mode}
                                              for mode in ('results', 'needs') if mode in controls]
        elif context['stage'] == 'reading' and focus_gated:
            feedback['guidance'] = ('This pair already has an accepted assessment on these bytes. Read new relevant raw '
                                    'evidence, record a concrete evidence gap, or finish. The current raw does not support '
                                    'another ordinary assessment of this pair.')
        if context['stage'] == 'missing_evidence':
            pending = state.pending_assessments.get(focused_pair, {})
            if 'speaker_evidence_refs' in (pending.get('missing_evidence') or []):
                speaker = pending['speaker']
                role = speaker['role']
                side = 'A' if speaker.get('side') == 'A' else 'B'
                sides = payload['m6'].get('assessment_ref_sides', {})
                refs = sides.get('A', []) if side == 'A' else sides.get('B_by_candidate', {}).get(focused_pair[1], [])
                support = []
                if any((pair['source_need_id'], pair['candidate_id']) == focused_pair and ref not in gated
                       for ref, pair in pairs.items()):
                    support = self._speaker_supported_refs(payload, refs, quoted=role == 'quoted_source')
                feedback['speaker_evidence_repair'] = {'role': role, 'side': side, 'eligible_current_refs': support[:3]}
                guidance = ('For this pending speaker attribution, use a listed current ref in speaker_evidence_refs only if '
                            'its raw text supports the claimed role. ' if support else '')
                feedback['guidance'] = (guidance + 'If attribution cannot be grounded, read more evidence or omit speaker / use '
                                        'role unknown and record any unresolved gap. ' + feedback['guidance'])
            evidence_options = []
            for branch in branches:
                name = branch['properties']['action']['const']
                if name not in ('continue_raw_evidence', 'read_more_context', 'read_query_passages'):
                    continue
                params = branch['properties']['args']['properties']
                for arg, spec in params.items():
                    for ref in spec.get('enum', [])[:5]:
                        if name == 'continue_raw_evidence':
                            case = state.catalog[handles[ref]['ref']]['case_id']
                        elif name == 'read_more_context':
                            case = payload['m6']['expansions'][ref].get('description', {}).get('case_id')
                        else:
                            case = self.harness.identity.query_id
                        evidence_options.append({'tool': name, 'args': {arg: ref}, 'case_id': case,
                                                 'side': 'A' if case == self.harness.identity.query_id else 'B' if case == context['candidate_id'] else 'unspecified'})
            feedback['evidence_options'] = evidence_options
            feedback['unoffered_raw_count'] = payload['cm_unoffered_raw_count']
            feedback['pending_source_count'] = payload['pending_source_count']
            feedback['navigation_options'] = [{'tool': 'show_context_page', 'args': {'page_ref': controls[mode]}, 'view': mode}
                for mode in ('query', 'results', 'pool', 'needs', 'parked') if mode in controls]
        if recover_search and not self.gate_enabled:
            feedback['guidance'] = 'The repeated query was skipped. Choose an unread candidate in these existing results or change need.'
        if lead_waiting:
            feedback['guidance'] = ('Use lead_review_option to bring the selected candidate lead back for assessment.'
                                    if revisit_lead else 'The selected candidate lead has unread text. Continue the '
                                    'candidate excerpt before assessing this pair, or record the evidence gap.')
        if revisit_query_anchor:
            feedback['guidance'] = 'Use query_anchor_option to restore the query quotation before assessment.'
        if feedback.get('focus_retry_paused_case_id'):
            feedback['guidance'] = 'The repeated candidate focus was skipped. Choose another offered read or return to unfinished results.'
        if context['mode'] == 'results' and 'next' in controls and page['candidates'] and all(
                candidate_rows[card['candidate_ref']].get('read_status') in
                ('assessed_use_unfinished_results', 'deferred_missing_evidence')
                for card in page['candidates']):
            feedback['guidance'] = 'This page has no remaining candidate reads for this need. Open the next results page.'
            feedback['navigation_options'] = [{'tool': 'show_context_page',
                                               'args': {'page_ref': controls['next']}, 'view': 'next'}]
        if not self.gate_enabled:
            self._draft_close_catalog(payload, context, schema, handles)
        if self.gate_enabled:
            schema = self._gate_catalog(payload, state, context, schema, handles)
            schema = self._query_review_catalog(payload, state, context, schema, handles)
            schema = self._current_tool_catalog(payload, schema)
        payload['m6']['schema_fingerprint'] = fingerprint(schema if self.gate_enabled else policy.catalog(payload)[1])
        return schema, handles

    @staticmethod
    def _current_tool_catalog(payload, schema):
        """Keep CM4's public catalog and all recovery hints on the current API."""
        allowed = {
            'expand_query_map', 'read_query_passages', 'read_query_span',
            'assess_source_need', 'assess_source_needs', 'group_source_needs', 'search_cases_by_issue', 'defer_source_need',
            'choose_source_span', 'read_source_context', 'revise_source_need',
            'defer_approved_source_need', 'resume_approved_source_need', 'revisit_source_need',
            'show_context_page', 'show_source_need_page', 'set_context_focus', 'prioritize_query_results',
            'open_retrieved_passage', 'read_case_passages', 'open_candidate_header',
            'read_more_context', 'continue_raw_evidence', 'reload_pair_evidence', 'resume_pair_evidence',
            'assess_case_link', 'review_conflicting_link', 'record_missing_evidence',
            'defer_case_pair', 'report_review_blocker', 'conclude_search_query', 'finish_case_review',
        }
        payload['available_tools'] = [tool for tool in payload['available_tools'] if tool['name'] in allowed]
        branches = [branch for branch in schema['anyOf']
                    if branch['properties']['action']['const'] in allowed]
        offered = {tool['name'] for tool in payload['available_tools']}
        for tool in payload['available_tools']:
            if tool['name'] == 'record_missing_evidence':
                tool['description'] = 'Record the evidence gap for this pair. You may compare other candidates within the active query.'
        feedback = payload['last_action_feedback']
        blocker = feedback.get('review_blocker')
        if blocker:
            blocker['suggested_tools'] = [name for name in blocker.get('suggested_tools', []) if name in offered]
        feedback['next_options'] = [tool['name'] for tool in payload['available_tools']]
        for key in ('navigation_options', 'evidence_options'):
            if key in feedback:
                feedback[key] = [option for option in feedback[key] if option.get('tool') in offered]
        for key in ('anchor_resolution', 'closable_anchor_drafts', 'anchor_replacements'):
            feedback.pop(key, None)
            payload['m6'].pop(key, None)
        return {'type': 'object', 'anyOf': branches}

    def _query_review_catalog(self, payload, state, context, schema, handles):
        """Lock retrieval to one immutable result set and require complete survey."""
        query = query_review.active(self.events(), context)
        if query is None:
            return schema
        payload['m6']['query_review'] = query_review.progress(query, state)
        feedback = payload['last_action_feedback']
        gate_progress = feedback.pop('query_gate_progress', {})
        feedback['query_gate_paused'] = {'reason': 'Conclude the active search query before more source screening.',
            'approved_waiting_search': gate_progress.get('unsearched_count', 0),
            'screening_paused': True}
        payload['m6'].pop('source_gate_segments', None)
        payload['m6'].pop('source_gate_proposition_refs', None)
        payload['m6'].pop('source_gate_permits', None)
        payload['m6'].pop('deferred_source_searches', None)
        payload['m6'].pop('unresolved_source_needs', None)
        payload['m6'].pop('unresolved_source_need_page', None)
        page = payload['m6']['cm_page']
        page['survey_position'] = query_review.page_status(query, page.get('candidates', []), context['offset'])
        for card in page.get('candidates', []):
            card['survey_received_before'] = card['case_id'] in query['survey_exposed']
        pending_ref = page.get('controls', {}).get('read_next')
        if pending_ref:
            feedback.setdefault('navigation_options', []).insert(0, {
                'tool': 'show_context_page', 'args': {'page_ref': pending_ref}, 'view': 'read_next'})
            feedback['guidance'] = 'Return to the highest-ranked unread read_next candidate. Read it or change its priority with a reason before concluding.'
        unseen_ref = page.get('controls', {}).get('next_unseen')
        if unseen_ref:
            feedback['navigation_options'] = [{'tool': 'show_context_page', 'args': {'page_ref': unseen_ref}, 'view': 'next_unseen'}]

        payload['m6']['query_review']['priorities'] = {
            case: row for case, row in query['priorities'].items()
            if case in [card['case_id'] for card in payload['m6']['cm_page'].get('candidates', [])]}
        blocked = {'search_cases_by_issue', 'find_citation_matches', 'continue_citation_search',
                   'choose_query_anchor', 'set_context_focus', 'resume_query_anchor', 'finish_case_review'} | GATE_MUTATIONS
        if query['phase'] == 'surveying':
            for card in page.get('candidates', []):
                card['read_allowed'] = False
            blocked |= {'open_retrieved_passage', 'read_case_passages', 'open_candidate_header',
                        'assess_case_link', 'review_conflicting_link', 'resume_pair_evidence',
                        'reload_pair_evidence', 'read_more_context', 'continue_raw_evidence'}
            payload['last_action_feedback']['guidance'] = (
                'Survey every results page before reading candidate raw. Cards are leads, not assessments. '
                'Choose priorities; then use another page. Conclude this query before starting another search.')
        for name in ('resume_pair_evidence', 'reload_pair_evidence'):
            for branch in schema['anyOf']:
                if branch['properties']['action']['const'] == name:
                    props = branch['properties']['args']['properties']
                    refs = props['evidence_ref'].get('enum', [])
                    valid = [ref for ref in refs if handles.get(ref, {}).get('need_id', query['need_id']) == query['need_id']]
                    if not valid:
                        blocked.add(name)
                    else:
                        props['evidence_ref']['enum'] = valid
        tools = [tool for tool in payload['available_tools'] if tool['name'] not in blocked]
        branches = [branch for branch in schema['anyOf']
                    if branch['properties']['action']['const'] not in blocked]
        def add(name, props, description):
            branches.append(self._branch(name, props))
            tools.append({'name': name, 'description': description,
                          'parameters': {'type': 'object', 'additionalProperties': False,
                                         'properties': props, 'required': list(props)}})
        choices = {}
        for card in payload['m6']['cm_page'].get('candidates', []):
            case = card['case_id']
            if case in query['candidate_ids']:
                ref = 'survey-' + fingerprint([query['query_id'], case])[:16]
                handles[ref] = {'kind': 'query_candidate', 'case_id': case}
                choices[ref] = case
        if choices:
            payload['m6']['query_result_choices'] = choices
            eligibility = {}
            for priority in ('read_next', 'maybe', 'low_priority'):
                changed = [ref for ref, case in choices.items()
                           if query['priorities'].get(case, {}).get('priority') != priority]
                if changed:
                    eligibility[priority] = changed
                    add('prioritize_query_results', {
                        'candidate_refs': {'type': 'array', 'items': {'type': 'string', 'enum': changed},
                                           'minItems': 1, 'maxItems': 5},
                        'priority': {'type': 'string', 'enum': [priority]},
                        'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}},
                        'Set or change reading priorities for shown results. Unchanged assignments are not offered; '
                        'use the next unseen page instead of repeating a classification.')
            priority_tools = [tool for tool in tools if tool['name'] == 'prioritize_query_results']
            if priority_tools:
                descriptor = deepcopy(priority_tools[0])
                descriptor['parameters']['properties']['priority']['enum'] = list(eligibility)
                descriptor['parameters']['properties']['candidate_refs']['items']['enum'] = list(dict.fromkeys(
                    ref for refs in eligibility.values() for ref in refs))
                descriptor['description'] = ('Set or change reading priority. Select candidate_refs from '
                    'm6.priority_choices_by_value for the chosen priority. Unchanged assignments are unavailable.')
                tools = [tool for tool in tools if tool['name'] != 'prioritize_query_results']
                tools.append(descriptor)
                payload['m6']['priority_choices_by_value'] = eligibility
        if query['phase'] == 'reviewing' and not query_review.pending_read_next(query):
            outcomes = ['partially_resolved']
            if not query_review.unresolved_candidates(query, state):
                outcomes.insert(0, 'resolved')
            if (not query['candidate_ids'] or query['raw_exposed']) and not any(state.assessments.get(state.active_assessments.get((query['need_id'], case)), {}).get('case_relation') == 'supported'
                       and (query['need_id'], case) not in state.pending_assessments for case in query['candidate_ids']):
                outcomes.append('no_supported_source_found')
            add('conclude_search_query', {
                'outcome': {'type': 'string', 'enum': outcomes},
                'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240},
                'unresolved_reason': {'type': 'string', 'maxLength': 240},
                'remaining_source_need': {'type': 'string', 'maxLength': 240}},
                'Conclude this search explicitly. State why unread or unresolved results will not be read further; '
                'the host keeps their IDs and raw/assessment counters. Partial conclusions permit a new search, '
                'but do not mark unread cases as unsupported or assert corpus completeness.')
        # Keep navigation inside the current query, while query raw remains accessible.
        payload['available_tools'] = tools
        payload['last_action_feedback']['next_options'] = [tool['name'] for tool in tools]
        return {'type': 'object', 'anyOf': branches}

    def _gate_catalog(self, payload, state, context, schema, handles):
        """Publish assessment first, then permit-bound search on a later admission."""
        tools = payload['available_tools']
        branches = schema['anyOf']
        review_allowed = (context['mode'] in ('results', 'assessment', 'pool', 'parked')
                          and source_gate.authorized(context, context['need_id']))
        remove = {'search_cases_by_issue', 'find_citation_matches', 'continue_citation_search',
                  'choose_query_anchor', 'resume_query_anchor'}
        if not review_allowed:
            remove.update({'read_case_passages', 'open_retrieved_passage', 'assess_case_link',
                           'review_conflicting_link', 'resume_pair_evidence', 'reload_pair_evidence',
                           'set_context_focus', 'defer_case_pair', 'open_candidate_header'})
            payload['m6']['candidates'] = {}
            payload['m6']['retrieved_passages'] = {}
            payload['m6']['cm_page']['candidates'] = []
            # Source expansions in query-reading mode must belong to A.
            keep_expansions = {ref: option for ref, option in payload['m6']['expansions'].items()
                               if option.get('description', {}).get('case_id') == self.harness.identity.query_id}
            payload['m6']['expansions'] = keep_expansions
            if not keep_expansions:
                remove.add('read_more_context')
            else:
                for branch in branches:
                    if branch['properties']['action']['const'] == 'read_more_context':
                        branch['properties']['args']['properties']['context_ref']['enum'] = list(keep_expansions)
            # Continuations may only show A until the current review need is authorized.
            allowed_continuations = [ref for ref, target in handles.items()
                                     if target['kind'] == 'continuation'
                                     and state.catalog[target['ref']]['case_id'] == self.harness.identity.query_id]
            if not allowed_continuations:
                remove.add('continue_raw_evidence')
            else:
                for branch in branches:
                    if branch['properties']['action']['const'] == 'continue_raw_evidence':
                        branch['properties']['args']['properties']['context_ref']['enum'] = allowed_continuations
        tools = [tool for tool in tools if tool['name'] not in remove]
        branches = [branch for branch in branches if branch['properties']['action']['const'] not in remove]

        def add(name, properties, description):
            branches.append(self._branch(name, properties))
            tools.append({'name': name, 'description': description,
                          'parameters': {'type': 'object', 'additionalProperties': False,
                                         'properties': properties, 'required': list(properties)}})

        adjacent_spans = {} if context.get('_checking_query_span') else source_gate.span_options(state, payload)
        if self.dual_search is not None and not context.get('_checking_query_span'):
            # Small source-bound routes to received text with unfinished work.
            settled = source_gate._settled_spans(context)
            received = source_gate.delivered_query_rows(state, self.harness.identity.query_id, self.harness.identity.query_source_hash)
            pending = []
            received_spans = sorted((r['span_bytes'] for r in received))
            merged = []
            for left, right in received_spans:
                if merged and left <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], right)
                else:
                    merged.append([left, right])
            raw = self.store.raw_reader(self.harness.identity.query_id) if merged else b''
            if merged and sha256(raw).hexdigest() != self.harness.identity.query_source_hash:
                raise SourceDrift(self.harness.identity.query_id)
            for paragraph in self.harness.query_paragraphs:
                for received_left, received_right in merged:
                    left=max(paragraph['span_bytes'][0],received_left)
                    right=min(paragraph['span_bytes'][1],received_right)
                    if left >= right:
                        continue
                    for span in unread_spans([left,right], settled.get((self.harness.identity.query_source_hash,paragraph['handle']),[])):
                        end=min(span[1],span[0]+4096)
                        while end > span[0] and end < len(raw) and raw[end] & 0xc0 == 0x80:
                            end-=1
                        if not raw[span[0]:end].strip():
                            continue
                        target={'source_hash':self.harness.identity.query_source_hash,
                                'span_bytes':[span[0],end],'paragraph_handle':paragraph['handle']}
                        if target not in pending:
                            pending.append(target)
                if len(pending) >= 3:
                    break
            if focus := context.get('source_return_focus'):
                pending.insert(0,focus)
            for target in pending[:3]:
                ref='query-pending-'+fingerprint(target)[:16]
                adjacent_spans.setdefault(ref,target)
        fitted_spans = {}
        for ref, target in adjacent_spans.items():
            record = self._combined_query_record(state, target)
            projected = {**context, 'mode': 'query_span', 'query_span_record': record,
                         'offset': 0, 'back': [], '_checking_query_span': True}
            if self._query_leaf_payload(state, projected)[4] <= self.harness.budget.max_payload_tokens:
                fitted_spans[ref] = target
        adjacent_spans = fitted_spans
        if adjacent_spans:
            for ref, target in adjacent_spans.items():
                handles[ref] = {'kind': 'query_span', **target}
            payload['m6']['query_span_options'] = {ref: {'span_bytes': row['span_bytes'],
                'paragraph_handle': row['paragraph_handle']} for ref, row in adjacent_spans.items()}
            add('read_query_span', {'span_ref': {'type': 'string', 'enum': list(adjacent_spans)}},
                'Reload an issued contiguous query region spanning previously received windows. '
                'Use it when one proposition crosses a page boundary; it need not contain the full paragraph.')
        paragraphs = source_gate.screening_choices(payload, context)
        surveying = getattr(self, 'survey_first', False)
        if surveying:
            ready = source_gate.survey_ready(context, self.harness.query_paragraphs)
            payload['m6']['source_survey'] = {'phase': 'retrieval' if ready else 'survey',
                'queued_needs': sum(row['status'] == 'approved' for row in context.get('source_gate', {}).values())}
            queued = {key: row for key, row in context.get('source_gate', {}).items() if row['status'] == 'approved'}
            if ready and len(queued) > 1:
                visible_queue = dict(list(queued.items())[:self.render_page_size])
                payload['m6']['source_survey']['group_choices'] = {
                    key: {'text': row['proposition']['text'], 'supports': row.get('a_supports', [])}
                    for key, row in visible_queue.items()}
                add('group_source_needs', {
                    'source_need_refs': {'type': 'array', 'minItems': 2, 'maxItems': 3,
                                         'items': {'type': 'string', 'enum': list(visible_queue)}},
                    'reason': {'type': 'string', 'minLength': 8, 'maxLength': 240}},
                    'Confirm these spans cite the same decision using their source details. Keep separate quotations with different authorities separate. The first need supplies the main search span.')
        permits = source_gate.visible_permits(payload, context)
        if surveying and not ready:
            permits = {}
        can_search = (bool(permits) and context['stage'] not in ('reading', 'results_ready')
                      and query_review.active(self.events(), context) is None)
        if paragraphs and context['stage'] != 'reading' and not can_search:
            segments = source_gate.segments(payload, context, bound=self.dual_search is not None)
            payload['m6']['source_gate_segments'] = segments
            bound = self.dual_search is not None
            if bound:
                tree=getattr(self.harness.m3,'query_tree',None)
                raw = self.store.raw_reader(self.harness.identity.query_id)
                headings = set(map(tuple, getattr(tree, 'headings', []))) | set(source_gate.heading_spans(raw))
                payload['m6']['known_heading_spans'] = [list(span) for span in sorted(headings)
                    if any(p['span_bytes'][0] < span[1] and span[0] < p['span_bytes'][1]
                           for p in payload['m6']['a_paragraphs'].values())]
                payload['m6']['settled_source_spans'] = [span for (digest,_),spans in source_gate._settled_spans(context).items()
                                                        if digest==self.harness.identity.query_source_hash for span in spans]
            payload['m6']['source_gate_proposition_refs'] = [ref for ref, row in segments.items() if row.get('proposition_selectable', True)]
            description = ('Choose exactly one offered source ref or literal quote for search_needed or no_search_needed. '
                           'remaining_visible refs settle only their listed remaining ranges with no_search_needed. '
                           'Use need_more_context to read more. Typed supports do not settle their text.')
            if bound:
                repair = visible_repair(self.events()) or {}
                quote_recovery = repair.get('code') == 'source_span_required' or any(
                    row['status'] == 'unresolved' and row.get('requested_args', {}).get('proposition_quote')
                    and row['paragraph_handle'] in {p['paragraph_handle'] for p in payload['m6']['a_paragraphs'].values()}
                    for row in context.get('source_gate', {}).values())
                first_tool = len(tools)
                for fields, required in source_gate.bound_assessment_variants(paragraphs, segments):
                    if quote_recovery and 'proposition_quote' in fields:
                        continue
                    add('assess_source_need', fields, description)
                    branches[-1]['properties']['args']['required'] = required
                    tools[-1]['parameters']['required'] = required
                # Keep decoder branches explicit while displaying one compact
                # catalog entry to the model.
                entries = tools[first_tool:]
                if entries:
                    properties = {}
                    for entry in entries:
                        for key,spec in entry['parameters']['properties'].items():
                            if key not in properties:
                                properties[key] = deepcopy(spec)
                            elif 'enum' in spec:
                                properties[key]['enum'] = list(dict.fromkeys(properties[key].get('enum', []) + spec['enum']))
                    tools[first_tool:] = [{**entries[0], 'parameters': {'type':'object','properties':properties,
                        'required':[key for key in properties if key not in ('proposition_ref','proposition_quote','signal_ref',
                                                                          'sufficient_for_search','missing_context','a_supports')],
                        'additionalProperties':False}}]
            else:
                add('assess_source_need', source_gate.assessment_properties(paragraphs, segments),
                    'Decide whether the visible query span needs a source. Select proposition_ref for search_needed.')
                optional = {'proposition_ref', 'signal_ref', 'sufficient_for_search', 'missing_context', 'proposition_quote', 'a_supports'}
                branch = branches[-1]
                params = branch['properties']['args']
                params['required'] = [key for key in params['required'] if key not in optional]
                prompt = tools[-1]['parameters']
                prompt['required'] = [key for key in prompt['required'] if key not in optional]
                prompt['properties'] = {
                    key: ({'type': 'string', 'choices_from': ('m6.source_gate_proposition_refs'
                          if key == 'proposition_ref' else 'm6.source_gate_segments keys')}
                          if key in ('proposition_ref', 'signal_ref') else spec)
                    for key, spec in prompt['properties'].items()}
        if surveying and paragraphs and context['stage'] != 'reading' and not can_search and self.dual_search is not None:
            variants = source_gate.bound_assessment_variants(paragraphs, segments)
            if quote_recovery:
                variants = [(fields, required) for fields, required in variants if 'proposition_quote' not in fields]
            item_schemas = [{'type': 'object', 'properties': fields, 'required': required,
                             'additionalProperties': False} for fields, required in variants]
            add('assess_source_needs', {'items': {'type': 'array', 'minItems': 1,
                                                'maxItems': context.get('batch_item_limit', 3),
                                                'items': {'anyOf': item_schemas}}},
                'Screen one to three distinct visible source spans. Search decisions are queued until A survey completes.')
        if can_search:
            properties = {
                'source_need_ref': {'type': 'string', 'enum': list(permits)},
                'issue': {'type': 'string', 'minLength': 4, 'maxLength': 160},
                'source_proposition': {'type': 'string', 'minLength': 4, 'maxLength': 240}}
            if self.dual_search is not None:
                properties = {'source_need_ref': properties['source_need_ref']}
            add('search_cases_by_issue', properties,
                'Run retrieval from the locked source permit. Revise the permit if the selected text needs to change.'
                if self.dual_search is not None else
                'Find source cases for one approved query proposition. Select its source_need_ref; '
                'the host fixes the anchor. Search terms must address that approved proposition.')
            add('defer_approved_source_need', {
                'source_need_ref': {'type': 'string', 'enum': list(permits)},
                'reason_code': {'type': 'string', 'enum': ['duplicate_source_question', 'search_terms_unclear']},
                'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}},
                'Record why this approved search should wait. The ledger keeps it as an unexecuted search.')
            if self.dual_search is not None:
                add('revise_source_need',{'source_need_ref':{'type':'string','enum':list(permits)}},
                    'Revise an unconsumed source permit before searching. This withdraws approval and returns to source-span selection; it does not run retrieval.')
        if self.dual_search is not None and not can_search:
            choices={}
            for key,draft in reversed(list(context.get('source_gate',{}).items())):
                if draft['status']!='unresolved':
                    continue
                for candidate in draft.get('resolution_choices',[]):
                    record=next((row for row in payload['excerpts'] if row['ref']==candidate['source_ref']),None)
                    if record is None:
                        continue
                    ref='source-choice-'+fingerprint([key,candidate])[:16]
                    handles[ref]={'kind':'source_choice','draft_ref':key,'candidate':candidate}
                    choices[ref]={'span_bytes':candidate['span_bytes'],'text':candidate['text']}
                    if len(choices) == 3:
                        break
                if len(choices) == 3:
                    break
            if choices:
                payload['m6']['source_span_choices']=choices
                add('choose_source_span',{'choice_ref':{'type':'string','enum':list(choices)}},
                    'Confirm an exact canonical source suggestion for the saved decision; an approximate quote alone never authorizes retrieval.')
            raw=self.store.raw_reader(self.harness.identity.query_id)
            context_options={}
            for key,draft in list(context.get('source_gate',{}).items())[-3:]:
                if draft['status'] not in ('unresolved','revision_requested'):
                    continue
                left,right=draft['visible_span_bytes']
                start=max(0,left-700)
                end=min(len(raw),max(right+700,start+2000),start+4096)
                while start>0 and raw[start] & 0xc0 == 0x80:
                    start-=1
                while end<len(raw) and raw[end] & 0xc0 == 0x80:
                    end-=1
                target={'source_hash':self.harness.identity.query_source_hash,'span_bytes':[start,end],
                        'paragraph_handle':draft['paragraph_handle'],'draft_ref':key}
                ref='source-context-'+fingerprint(target)[:16]
                handles[ref]={'kind':'source_context',**target}
                context_options[ref]={'span_bytes':[start,end],'source_need_ref':key}
            if context_options:
                payload['m6']['source_context_options']=context_options
                add('read_source_context',{'context_ref':{'type':'string','enum':list(context_options)}},
                    'Read bounded literal A context around a pending source span. The saved decision and typed supports remain a draft; reading does not settle additional text.')
        if query_review.active(self.events(), context) is None and self.dual_search is None:
            searched = source_gate.visible_permits(payload, context, status='searched')
            if searched:
                add('revisit_source_need', {
                    'source_need_ref': {'type': 'string', 'enum': list(searched)},
                    'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}},
                    'Reopen a searched proposition after concluding its query, to formulate a different search.')
        deferred = source_gate.visible_permits(payload, context, status='search_deferred')
        if not can_search and deferred and context['stage'] not in ('reading', 'results_ready'):
            add('resume_approved_source_need', {
                'source_need_ref': {'type': 'string', 'enum': list(deferred)},
                'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}},
                'Reopen a deferred search when you can address the recorded reason for postponing it.')
            payload['m6']['deferred_source_searches'] = {key: {
                'paragraph_ref': item['paragraph_ref'], 'reason': item['decision']['search_defer_reason']}
                for key, item in deferred.items()}
        payload['m6']['source_gate_permits'] = {key: {
            'paragraph_ref': row['paragraph_ref'], 'anchor_quote': row['decision']['proposition']['text'],
            'signal': row['decision']['signal']['text'] if row['decision'].get('signal') else None,
            'attribution': row['decision']['attribution'],
            **({'supports': [{k: support[k] for k in ('role', 'span_bytes', 'text')}
                             for support in row['decision'].get('a_supports', [])]}
               if self.dual_search is not None else {})}
            for key, row in permits.items()}
        status = source_gate.progress(context, self.harness.query_paragraphs)
        payload['last_action_feedback']['query_gate_progress'] = status
        unresolved = {key: row for key, row in context.get('source_gate', {}).items() if row['status'] == 'unresolved'}
        deferrable = {key: row for key, row in unresolved.items() if row['context_complete']}
        if unresolved and len(deferrable) < len(unresolved) and source_gate.query_fully_read(
                state, self.harness.query_paragraphs, self.harness.identity.query_id, self.harness.identity.query_source_hash):
            deferrable = unresolved
        if deferrable and not can_search and query_review.active(self.events(), context) is None:
            all_keys = list(context.get('source_gate', {}))
            eligible = list(deferrable)
            cursor = context.get('source_need_page_start')
            ranks = {key: index for index, key in enumerate(all_keys)}
            start = next((index for index, key in enumerate(eligible)
                          if ranks[key] >= ranks.get(cursor, 0)), len(eligible))
            if start == len(eligible):
                start = max(0, len(eligible) - self.render_page_size)
            page_keys = eligible[start:start + self.render_page_size]
            controls = {}
            for name, index in (('previous', max(0, start - self.render_page_size)),
                                ('next', start + len(page_keys))):
                if (name == 'previous' and start == 0) or index >= len(eligible):
                    continue
                target = {'kind': 'source_need_page', 'start_ref': eligible[index]}
                ref = 'gate-page-' + fingerprint([self.harness.identity.run_id, context['revision'], target])[:16]
                handles[ref] = target
                controls[name] = ref
            add('defer_source_need', {
                'source_need_ref': {'type': 'string', 'enum': page_keys},
                'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}},
                'Record why a listed source question remains unresolved after reading its context. '
                'Other unresolved questions remain available on the next/previous source-need page.')
            if controls:
                add('show_source_need_page', {'page_ref': {'type': 'string', 'enum': list(controls.values())}},
                    'View another bounded page of unresolved source questions without changing the current '
                    'query region, candidate, evidence, or reading focus.')
            payload['m6']['unresolved_source_needs'] = {
                key: {'paragraph_handle': deferrable[key]['paragraph_handle'], 'reason': deferrable[key]['reason'],
                      'validation_message': deferrable[key].get('validation_message')} for key in page_keys}
            payload['m6']['unresolved_source_need_page'] = {
                'total': len(eligible), 'offset': start, 'count': len(page_keys),
                'first_index': start + 1, 'last_index': start + len(page_keys), 'controls': controls}
        review = payload['last_action_feedback'].get('review_progress', {})
        complete = (status['complete'] and not context.get('anchor_drafts')
                    and query_review.active(self.events(), context) is None)
        if review:
            review['complete_policy_allowed'] = complete
        if complete and not any(tool['name'] == 'finish_case_review' for tool in tools):
            add('finish_case_review', {'reason': {'type': 'string', 'enum': ['complete_policy']}},
                'Complete screened case review; unresolved query conclusions remain explicit in the report.')
        for tool in tools:
            if tool['name'] == 'finish_case_review':
                tool['parameters']['properties']['reason']['enum'] = ['complete_policy']
                tool['when'] = 'Use when the review is complete. The prediction uses the active supported assessments.'
        for branch in branches:
            if branch['properties']['action']['const'] == 'finish_case_review':
                branch['properties']['args']['properties']['reason']['enum'] = ['complete_policy']
        if not complete:
            tools = [tool for tool in tools if tool['name'] != 'finish_case_review']
            branches = [branch for branch in branches
                        if branch['properties']['action']['const'] != 'finish_case_review']
        if can_search:
            allowed = {'search_cases_by_issue', 'defer_approved_source_need', 'revise_source_need', 'group_source_needs'}
            tools = [tool for tool in tools if tool['name'] in allowed]
            branches = [branch for branch in branches if branch['properties']['action']['const'] in allowed]
            payload['last_action_feedback']['guidance'] = (
                'An approved source question is ready. Search it or record why you are postponing it before screening another paragraph.')
        elif not review_allowed and not permits:
            payload['last_action_feedback']['guidance'] = (
                'Read query text and assess_source_need before retrieval. A topic alone is insufficient. '
                'Inspect other query regions until query_gate_progress is complete.')
            if context['mode'] == 'query_leaf' and not paragraphs and not status['complete']:
                payload['last_action_feedback']['guidance'] = (
                    'No paragraph in this view needs screening. Use show_context_page to return to the '
                    'query map and read another region.')
            elif context['mode'] == 'query' and not paragraphs and not status['complete']:
                remaining = source_gate.unscreened_spans(
                    context, self.harness.identity.query_source_hash, self.harness.query_paragraphs)
                targets = [(option['description']['span_bytes'], ref)
                           for ref, option in payload['m6']['query_targets'].items()
                           if 'span_bytes' in option['description']]
                next_ref = next((ref for (left, right), ref in sorted(targets)
                                 if any(left < end and start < right for start, end in remaining)), None)
                if next_ref:
                    payload['last_action_feedback']['guidance'] = 'Open the next query region with unscreened paragraphs.'
                    payload['last_action_feedback']['navigation_options'] = [
                        {'tool': 'read_query_passages', 'args': {'query_ref': next_ref}}]
        if not complete and not can_search:
            reports = context.get('review_blockers', {}).get(self._blocker_scope(context), {})
            kinds = [kind for kind in BLOCKER_RECOVERY if kind not in reports]
            if kinds:
                add('report_review_blocker', {
                    'kind': {'type': 'string', 'enum': kinds},
                    'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240},
                }, 'Report a specific obstacle in the current review. This action keeps the review open.')
            self._blocker_feedback(payload, tools, reports)
        payload['available_tools'] = tools
        payload['last_action_feedback']['next_options'] = [tool['name'] for tool in tools]
        return {'type': 'object', 'anyOf': branches}

    @staticmethod
    def _blocker_feedback(payload, tools, reports):
        feedback = payload['last_action_feedback']
        last = feedback['last_action']
        if last.get('action') != 'report_review_blocker' or not reports:
            return
        # Context is serialized in the ledger with sorted keys. Bind the report to
        # the preceding action ID instead of relying on dictionary order.
        report = next((row for row in reports.values() if row['action_id'] == last['action_id']), None)
        if report is None:
            return
        offered = {tool['name'] for tool in tools}
        controls = payload['m6']['cm_page'].get('controls', {})
        routes = [option for option in feedback.get('navigation_options', []) if option['tool'] in offered]
        if 'show_context_page' in offered:
            for mode in ('results', 'next', 'query', 'needs'):
                if mode in controls:
                    option = {'tool': 'show_context_page', 'args': {'page_ref': controls[mode]}, 'view': mode}
                    if option not in routes:
                        routes.append(option)
        suggested = [name for name in BLOCKER_RECOVERY[report['kind']] if name in offered]
        suggested.extend(dict.fromkeys(option['tool'] for option in routes if option['tool'] not in suggested))
        feedback['review_blocker'] = {key: report[key] for key in ('kind', 'reason')}
        feedback['review_blocker']['suggested_tools'] = suggested
        if 'observed_repair' in report:
            feedback['review_blocker']['observed_repair'] = report['observed_repair']
        if routes:
            feedback['navigation_options'] = routes
        if suggested:
            feedback['guidance'] = 'The obstacle was recorded. Choose an available recovery or navigation action.'

    def _survey_preview(self, hit):
        """Bounded literal lead content, verified locally; not raw assessment evidence."""
        options = [hit, *hit.get('channels', {}).values()]
        lead = next((row for row in options if isinstance(row.get('preview'), dict)
                     and row['preview'].get('span_bytes') and row.get('source_hash')), None)
        supplied = lead.get('preview') if lead else None
        lead = lead or next((row for row in options if row.get('span_bytes') and row.get('source_hash')), None)
        if lead is None:
            return None
        left, right = (supplied or lead)['span_bytes']
        key = (hit['case_id'], lead['source_hash'], left, right)
        if key in self._survey_previews:
            return deepcopy(self._survey_previews[key])
        raw = self.store.raw_reader(hit['case_id'])
        if sha256(raw).hexdigest() != lead['source_hash']:
            raise SourceDrift(hit['case_id'])
        require(0 <= left < right <= len(raw), 'Retrieval preview span outside source')
        text = raw[left:right].decode('utf-8')
        if supplied:
            require(supplied.get('text') == text and supplied.get('text_sha256') == sha256(text.encode('utf-8')).hexdigest(),
                    'Retrieval preview differs from its source binding')
        excerpt = text[:320]
        end = left + len(excerpt.encode('utf-8'))
        preview = {'text': excerpt, 'span_bytes': [left, end], 'source_hash': lead['source_hash'],
                   'text_sha256': sha256(excerpt.encode('utf-8')).hexdigest(),
                   'truncated': end < right, 'lead_only': True}
        self._survey_previews[key] = preview
        return deepcopy(preview)

    def _verify_gate_mutation(self, name, context):
        if self.gate_enabled and name in GATE_MUTATIONS:
            require(query_review.active(self.events(), context) is None,
                    'Conclude the active search query before changing source screening decisions')

    def _verify_search_permit(self, action, context):
        if getattr(self, 'survey_first', False):
            require(source_gate.survey_ready(context, self.harness.query_paragraphs), 'Finish surveying A before retrieval')
        require(action['action'] == 'search_corpus', 'Source gate disallows ungated identity retrieval')
        require(query_review.active(self.events(), context) is None, 'Conclude the active search query before another retrieval')
        need = action['args'].get('_m6_need', {})
        decision = context.get('source_gate', {}).get(need.get('source_gate_ref'))
        require(decision is not None and (decision['status'] == 'approved'
                or (decision['status'] == 'searched' and decision.get('need_id') == need.get('source_need_id'))),
                'Retrieval has no active source gate permit')
        require(decision['source_hash'] == self.harness.identity.query_source_hash, 'Source gate hash mismatch')
        anchor = need.get('a_anchor', {})
        require(anchor.get('span_bytes') == decision['proposition']['span_bytes']
                and anchor.get('text') == decision['proposition']['text'], 'Retrieval anchor differs from its approved proposition')
        if self.dual_search is not None:
            require(need.get('source_bound') is True,'Source-bound retrieval mode is required')
            require(need.get('a_supports')==decision.get('a_supports',[]),'Retrieval supports differ from the approved source')
            expected = source_gate.query_text(decision)
            require(action['args']['text']==expected and need.get('source_query_text')==expected
                    and need.get('source_query_sha256')==sha256(expected.encode('utf-8')).hexdigest(),
                    'Retrieval query text differs from the locked canonical source')
            require(self._embedding_query_budget(expected)['accepted'],
                    'Approved source query exceeds the pinned embedding token/EOS cap')
        self.harness.m3.verify_source(self.harness.identity.query_id, decision['source_hash'])

    def _embedding_query_budget(self, text):
        return source_gate.embedding_query_budget(text, self.embedding_profile)

    def _draft_close_catalog(self, payload, context, schema, handles):
        drafts = context.get('anchor_drafts', {})
        if not drafts:
            return
        refs = {}
        for draft_id, draft in drafts.items():
            ref = 'draft-' + fingerprint(draft_id)[:16]
            handles[ref] = {'kind': 'draft_close', 'draft_id': draft_id}
            refs[ref] = {'issue': draft['args']['issue'], 'anchor_quote': draft['args']['anchor_quote']}
        properties = {'draft_ref': {'type': 'string', 'enum': list(refs)},
                      'resolution': {'type': 'string', 'enum': ['discarded', 'superseded']},
                      'replacement_ref': {'type': 'string', 'maxLength': 160},
                      'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}}
        schema['anyOf'].append(self._branch('close_query_anchor', properties))
        payload['available_tools'].append({'name': 'close_query_anchor',
            'description': 'Close an unusable draft explicitly. superseded requires a listed replacement_ref; discarded uses an empty replacement_ref.',
            'parameters': {'type': 'object', 'properties': properties, 'required': list(properties)}})
        payload['m6']['closable_anchor_drafts'] = refs
        snapshot = Snapshot.from_events(self.events(), {})
        payload['m6']['anchor_replacements'] = [*snapshot.needs, *context.get('source_gate', {}), *refs]

    def _payload_base(self, state, rows, coverage, feedback):
        return {'query_id': self.harness.identity.query_id, 'query_source_hash': self.harness.identity.query_source_hash,
                'max_output_tokens': CONTROLLER_OUTPUT_TOKEN_CAP, 'query_delivery': 'continuation', 'excerpts': rows,
                'current_payload_source_refs': [r['ref'] for r in rows],
                'pending_source_count': sum(bool(c['pending']) for c in coverage),
                'observation_omitted': True, 'observation_scope': 'full_observation_omitted_bounded_feedback_included',
                'last_action_feedback': feedback, 'candidate_count': len(state.candidates),
                'active_assessment_count': len(state.active_assessments), 'cm_coverage': coverage}

    def _pack_payload(self, payload, schema):
        with measure('project_wire_payload'):
            wire, wire_schema, aliases = project(payload, schema)
        with measure('serialize_wire_payload'):
            body = encode(wire)
        return wire, self.harness._count(body), wire_schema, aliases

    def _combined_query_record(self, state, target):
        span = target['span_bytes']
        records = source_gate.delivered_query_rows(state, self.harness.identity.query_id, target['source_hash'])
        require(not unread_spans(span, [row['span_bytes'] for row in records]), 'Combined query span includes unreceived bytes')
        for row in records:
            if row['span_bytes'][0] < span[1] and span[0] < row['span_bytes'][1]:
                self.store.verify(row)
        raw = self.store.raw_reader(self.harness.identity.query_id)
        if sha256(raw).hexdigest() != target['source_hash']:
            raise SourceDrift(self.harness.identity.query_id)
        components = {fingerprint(component): component for row in records
                      for component in row.get('provenance', {}).get('components', [])
                      if component['span_bytes'][0] < span[1] and span[0] < component['span_bytes'][1]}
        text = raw[span[0]:span[1]].decode('utf-8')
        return source_record(SourceExcerpt(self.harness.identity.query_id, target['source_hash'], tuple(span),
            text, sha256(text.encode('utf-8')).hexdigest(), provenance={'components': list(components.values())}))

    @timed('leaf_payload_projection')
    def _query_leaf_payload(self, state, context, progress_warning=None):
        """Offer and publish a region using the same full-source, map-free projection."""
        with measure('open_query_leaf'):
            record = (deepcopy(context['query_span_record']) if context['mode'] == 'query_span'
                      else source_record(self.harness.m3.read_leaf(context['query_leaf_region']).excerpts[0]))
        self.store.verify(record)
        span = record['span_bytes']
        rows = [record]
        coverage = [{'requested': span, 'offered': span, 'pending': None, 'canonical_ref': record['ref']}]
        feedback = self._feedback(context)
        repair = feedback.get('tool_repair')
        if repair:
            feedback['tool_repair'] = repair
            feedback['guidance'] = 'Correct the rejected tool input using the current query excerpt.'
        payload = self._payload_base(state, rows, coverage, feedback)
        backend = self.harness.hybrid_search
        searched = any((row.get('result') or {}).get('observation', {}).get('m6_source_need') and
                       'hits' in row['result']['observation'] for row in self.events() if row['kind'] == 'action_result')
        dispatch = {**asdict(self.harness.adaptive_config), 'a_paragraphs': self.harness._visible_paragraphs(payload),
                    'hybrid_budget_remaining': backend.remaining() if backend is not None else None,
                    'search_completed': searched, 'candidates': {}, 'expansions': {}, 'reloads': {},
                    'review_candidates': {}, 'review_count': 0, 'query_targets': {}, 'citation_search_pages': {},
                    'cm_context': {key: context[key] for key in ('need_id', 'candidate_id', 'stage', 'mode')},
                    'cm_page': {'total': 0, 'offset': 0, 'count': 0, 'candidates': []}}
        payload['m6'] = dispatch
        # Navigation at this reading step does not project evidence from other pairs.
        projected_context = {**context, 'pair_pins': {}, 'pair_targets': {}, 'pair_progress': {}}
        schema, handles = self._catalog(payload, state, projected_context, coverage)
        if progress_warning is not None:
            feedback['progress_warning'] = deepcopy(progress_warning)
        packed, tokens, wire_schema, aliases = self._pack_payload(payload, schema)
        if tokens > self.harness.budget.max_payload_tokens and progress_warning is not None:
            feedback.pop('progress_warning')
            packed, tokens, wire_schema, aliases = self._pack_payload(payload, schema)
        if tokens > self.harness.budget.max_payload_tokens and (
                feedback.get('anchor_resolution') or (repair and repair['tool'] == 'search_cases_by_issue')):
            # Anchor quotes use the raw text. Keep the paragraph table for host dispatch.
            compact = {**payload, 'm6': {key: value for key, value in dispatch.items() if key != 'a_paragraphs'}}
            packed, tokens, wire_schema, aliases = self._pack_payload(compact, schema)
        return packed, wire_schema, handles, rows, tokens, coverage, dispatch, aliases

    def _query_leaf_navigation_payload(self, state, context, full_tokens):
        """If a once-fitting region grows unfit, offer smaller source-bound reads."""
        tools = self.harness.m3
        if not isinstance(tools, MapFirstQueryTools):
            return None
        region = context.get('query_leaf_region') or tools.query_tree.root_ref
        epoch = sum(event['kind'] == 'action_started' for event in self.events())
        choices = tools.context_fallback_options(region, epoch)
        if not choices:
            return None
        feedback = self._feedback(context)
        payload = self._payload_base(state, [], [], feedback)
        backend = self.harness.hybrid_search
        dispatch = {**asdict(self.harness.adaptive_config), 'a_paragraphs': {},
            'hybrid_budget_remaining': backend.remaining() if backend is not None else None,
            'search_completed': bool(query_review.queries(self.events(), context)),
            'candidates': {}, 'expansions': {}, 'reloads': {}, 'review_candidates': {}, 'review_count': 0,
            'query_targets': choices, 'citation_search_pages': {},
            'cm_context': {key: context[key] for key in ('need_id', 'candidate_id', 'stage', 'mode')},
            'cm_page': {'total': 0, 'offset': 0, 'count': 0, 'candidates': []}}
        payload['m6'] = dispatch
        projected = {**context, 'pair_pins': {}, 'pair_targets': {}, 'pair_progress': {}}
        schema, handles = self._catalog(payload, state, projected, [])
        feedback['query_context_fallback'] = {'reason': 'full_region_payload_unfit',
            'full_region_input_tokens': full_tokens, 'max_payload_tokens': self.harness.budget.max_payload_tokens,
            'region_ref': region, 'raw_delivered_in_this_payload': False}
        feedback['guidance'] = ('The complete region no longer fits with current review state. '
            'Choose read_query_passages to open its subdivision or an ancestor map, then read a smaller region. '
            'No query raw or new source coverage is delivered by this navigation-only payload.')
        packed, tokens, wire_schema, aliases = self._pack_payload(payload, schema)
        return packed, wire_schema, handles, [], tokens, [], dispatch, aliases

    @timed('auto_survey_read')
    def _next_survey_read(self, state, context, progress_warning):
        """Choose the first remaining A region when navigation needs no model decision."""
        tools = self.harness.m3
        if not getattr(self, 'survey_first', False) or not isinstance(tools, MapFirstQueryTools):
            return None
        receipt = state.last_receipt or {}
        if (context['stage'] != 'ready' or context.get('active_anchor_draft')
                or receipt.get('cm_batch_length_recovery') or receipt.get('cm_tool_repair')):
            return None
        tree = tools.query_tree
        mode = context['mode']
        if mode == 'query_leaf':
            current = tree.region(context['query_leaf_region'])['span_bytes']
        elif mode == 'query_span':
            current = context['query_span_record']['span_bytes']
        elif mode == 'query' and not state.requests:
            current = None
        else:
            return None

        remaining = source_gate.unscreened_spans(
            context, self.harness.identity.query_source_hash, self.harness.query_paragraphs)
        if not remaining:
            return None
        if current:
            start, end = current
            unresolved = [row['visible_span_bytes'] for row in context.get('source_gate', {}).values()
                          if row['status'] == 'unresolved']
            if any(left < end and start < right for left, right in [*remaining, *unresolved]):
                return None

        next_byte = min(left for left, _ in remaining)
        region = tree.region(tree.root_ref)
        while True:
            ref = region['region_ref']
            left, right = region['span_bytes']
            overlaps_previous = current and left < current[1] and current[0] < right
            if not overlaps_previous and tools.can_read_region(ref):
                view = {'mode': 'query_leaf', 'query_leaf_region': ref, 'offset': 0, 'back': [],
                        'revision': context['revision'] + 1}
                projected = {**context, **view}
                payload, schema, handles, rows, tokens, coverage, dispatch, aliases = self._query_leaf_payload(
                    state, projected, progress_warning)
                if tokens <= self.harness.budget.max_payload_tokens:
                    return view, (payload, schema, handles, rows, coverage, tokens, dispatch, aliases)
            if region['is_leaf']:
                split = tools.split_option({
                    'binding': {'region_ref': ref, 'navigation_mode': 'raw'},
                    'description': {}})
                if not split:
                    return None
                ref = split[1]['binding']['region_ref']
            region = next(row for row in tree.children(ref) if row['span_bytes'][0] <= next_byte < row['span_bytes'][1])

    def prepare(self, *, admit=True, progress_warning=None):
        with self.harness.ledger.writer() as db:
            state = RunState(self.harness.ledger.read(db))
            require(state.final is None, 'Run already terminal')
            recovery = (state.last_receipt or {}).get('cm_batch_length_recovery')
            require(not state.last_receipt or state.last_receipt['status'] == 'success'
                    or state.last_receipt.get('cm_tool_repair', {}).get('retry_allowed') or recovery,
                    'Prior error/unknown receipt blocks a new request; no resend')
            if state.in_flight or state.active_action:
                self.harness._recover(db, state)
                if state.final is None:
                    self.harness._stop(db, state, 'failure', 'interrupted_request_unknown')
                return {'status': 'blocked_unknown', 'model_requests': 0}
            require(state.pending_action is None, 'Execute pending action before new request')
            context = self.context()
            if recovery:
                context['batch_item_limit'] = recovery['max_items']
            best, auto_query_view = None, None
            try:
                review = query_review.active(self.events(), context)
                if review is None and (automatic := self._next_survey_read(state, context, progress_warning)):
                    auto_query_view, best = automatic
                    context.update(auto_query_view)
                if passage_review.enabled(review):
                    for byte_limit in (5000, 3000, 1800, 900, 450, 180):
                        payload, schema, handles, rows = passage_review.compile_view(
                            self, state, context, review, byte_limit)
                        if progress_warning is not None:
                            payload['last_action_feedback']['progress_warning'] = deepcopy(progress_warning)
                        dispatch = payload['m6']
                        payload, tokens, schema, aliases = self._pack_payload(payload, schema)
                        if tokens <= self.harness.budget.max_payload_tokens:
                            best = payload, schema, handles, rows, [], tokens, dispatch, aliases
                            break
                leaf_read = context['mode'] in ('query_leaf', 'query_span')
                if best is None and leaf_read and not passage_review.enabled(review):
                    payload, schema, handles, rows, tokens, coverage, dispatch, aliases = self._query_leaf_payload(
                        state, context, progress_warning)
                    if tokens <= self.harness.budget.max_payload_tokens:
                        best = payload, schema, handles, rows, coverage, tokens, dispatch, aliases
                    else:
                        fallback = self._query_leaf_navigation_payload(state, context, tokens)
                        if fallback is not None and fallback[4] <= self.harness.budget.max_payload_tokens:
                            payload, schema, handles, rows, tokens, coverage, dispatch, aliases = fallback
                            best = payload, schema, handles, rows, coverage, tokens, dispatch, aliases
                # Try compact metadata at each raw size before clipping more raw.
                sizes = () if leaf_read or passage_review.enabled(review) else ((size, limit) for limit in (2048, 1024, 512, 256, 128, 64)
                                              for size in range(self.page_size, 0, -1))
                for size, byte_limit in sizes:
                    self.render_page_size = size
                    rows, coverage = self._rows(state, context, byte_limit)
                    payload = self._payload_base(state, rows, coverage, self._feedback(context))
                    if progress_warning is not None:
                        payload['last_action_feedback']['progress_warning'] = deepcopy(progress_warning)
                    payload['m6'] = self.harness._registry(state, payload)
                    schema, handles = self._catalog(payload, state, context, coverage)
                    dispatch_m6 = payload['m6']
                    payload, tokens, schema, aliases = self._pack_payload(payload, schema)
                    if tokens <= 8500:
                        if best is None:
                            best = payload, schema, handles, rows, coverage, tokens, dispatch_m6, aliases
                        if tokens <= 7900:
                            best = payload, schema, handles, rows, coverage, tokens, dispatch_m6, aliases
                            break
                    # A candidate at this raw size already meets the hard cap.
                    if size == 1 and best is not None:
                        break
                if best is None:
                    return {'status': 'unfit', 'reason': 'minimum_source_aware_window_or_catalog_unfit', 'model_requests': 0}
                payload, schema, handles, rows, coverage, tokens, dispatch_m6, aliases = best
                self.harness._verify(rows)
            except SourceDrift as exc:
                self.harness._record_drift(db, state, exc.case_id)
                return {'status': 'source_drift', 'model_requests': 0}
            except HarnessError as exc:
                if str(exc) != 'Query map with nonempty literal previews cannot fit its explicit token cap':
                    raise
                self.harness._stop(db, state, 'failure', 'query_navigation_map_unfit')
                return {'status': 'unfit', 'reason': 'query_navigation_map_unfit', 'model_requests': 0}
            finally:
                self._expansion_previews.clear()
                self._survey_previews.clear()
            request_id = fingerprint([self.harness.identity.run_id, 'request', state.usage()['requests'] + 1])
            body = encode(payload)
            manifest = {'version': VERSION, 'request_id': request_id, 'context': context,
                        'schema': schema, 'schema_sha256': fingerprint(schema), 'handles': handles,
                        'source_revision': fingerprint(self.events()), 'code_binding': code_binding(),
                        'counter_binding': self.counter_binding, 'payload_sha256': sha256(body).hexdigest(), 'coverage': coverage,
                        'dispatch_m6': dispatch_m6, 'wire_aliases': aliases,
                        'excerpts': rows, 'excerpts_sha256': fingerprint(rows)}
            relative = f'manifests/{request_id}.json'
            if not admit:
                return {'status': 'ready', 'input_tokens': tokens, 'soft_target_exceeded': tokens > 7900,
                        'payload': payload, 'manifest': manifest, 'admitted': False}
            with measure('write_request_manifest'):
                write_once(self.directory / relative, manifest)
            retry_of = state.last_receipt['request_id'] if recovery else None
            self.harness._write(db, state, 'request_admitted', request_id=request_id, retry_of=retry_of,
                payload=body.decode('utf-8'), admitted_input_tokens=tokens, output_token_cap=CONTROLLER_OUTPUT_TOKEN_CAP,
                consumed_refs=[], remaining_excerpts=[], excerpts=rows, current_payload_source_refs=[r['ref'] for r in rows],
                cm_query_navigation=dispatch_m6.get('query_navigation'),
                cm_search_query_id=dispatch_m6.get('query_review', {}).get('query_id'),
                cm_survey_candidates=[card['case_id'] for card in dispatch_m6.get('cm_page', {}).get('candidates', [])],
                cm_manifest_path=relative, cm_manifest_sha256=fingerprint(manifest),
                cm_scripted_offline=self.execution_mode == 'offline',
                **({'cm_auto_query_view': auto_query_view} if auto_query_view else {}))
            return {'status': 'ready', 'request_id': request_id, 'input_tokens': tokens, 'soft_target_exceeded': tokens > 7900,
                    'payload': payload, 'manifest': manifest, 'model_requests': 0}

    def _manifest(self, admission):
        relative = Path(admission['cm_manifest_path'])
        path = (self.directory / relative).resolve()
        require(path.is_relative_to(self.directory.resolve()), 'Manifest outside run')
        manifest = json.loads(path.read_bytes())
        require(fingerprint(manifest) == admission['cm_manifest_sha256'], 'Manifest changed')
        require(manifest['payload_sha256'] == sha256(admission['payload'].encode('utf-8')).hexdigest(), 'Payload changed')
        require(manifest['schema_sha256'] == fingerprint(manifest['schema']), 'Schema changed')
        require(manifest['excerpts_sha256'] == fingerprint(admission['excerpts']), 'Canonical excerpts changed')
        return manifest

    def _canonical_hybrid_need(self, action):
        """Keep the first committed binding to the same query and quote bytes."""
        args = action['args']
        if action['action'] != 'search_corpus' or args.get('channel') != 'hybrid':
            return action
        def binding(candidate):
            need = candidate['_m6_need']
            if need.get('a_anchor'):
                # A later payload can expose the same canonical quote in a
                # different excerpt and narrow the visible paragraph range.
                source = {key: need[key] for key in ('route', 'a_sources')}
            else:
                source = {key: value for key, value in need.items() if key != 'source_proposition'}
            return {**candidate, '_m6_need': source}

        proposed = binding(args)
        events = self.events()
        committed = {row['action_id'] for row in events if row['kind'] == 'action_result' and row['status'] == 'success'
                     and (row.get('result') or {}).get('observation', {}).get('m6_source_need')}
        for row in events:
            if (row['kind'] == 'action_started' and row['action_id'] in committed
                    and row['action']['action'] == 'search_corpus'
                    and binding(row['action']['args']) == proposed):
                return row['action']
        return action

    @staticmethod
    def _anchored_search(payload, args, paragraph_key, anchor):
        translated = {'action': 'search_cases_by_issue', 'args': {'issue': args['issue'],
                      'source_proposition': args['source_proposition'], 'a_paragraph_ref': paragraph_key}}
        internal = policy.translate(payload, translated)
        if anchor:
            need = internal['args']['_m6_need']
            need['a_anchor'] = anchor
            need['a_sources'][0]['span_bytes'] = anchor['span_bytes']
            need['source_need_id'] = 'need-' + fingerprint({
                key: value for key, value in need.items()
                if key not in ('source_need_id', 'source_proposition')})[:24]
        return internal

    def reply(self, request_id, action=None, status='success', *, telemetry=None, started=None,
              transport_metadata=None, error=None):
        with self.harness.ledger.writer() as db:
            state = RunState(self.harness.ledger.read(db))
            require(state.in_flight and state.in_flight['request_id'] == request_id, 'Stale or duplicate response')
            manifest = self._manifest(state.in_flight)
            require(status in ('success', 'unknown', 'error'), 'Invalid response status')
            raw_reply, raw_encoding = action, 'native'
            try:
                encode(raw_reply)
            except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
                # Preserve malformed Unicode without letting it break the receipt
                # transaction that records already incurred provider usage.
                try:
                    raw_reply = json.dumps(action, ensure_ascii=True)
                    raw_encoding = 'json_ascii_escaped'
                except (TypeError, ValueError, OverflowError, RecursionError):
                    raw_reply, raw_encoding = repr(action), 'repr'
            self._reply_metadata = {'cm_scripted_offline': self.execution_mode == 'offline',
                                    'transport_metadata': deepcopy(transport_metadata), 'raw_model_reply': raw_reply,
                                    'raw_model_reply_encoding': raw_encoding}
            if status != 'success':
                metadata = transport_metadata or {}
                max_items = manifest['context'].get('batch_item_limit', 3)
                admission = state.in_flight
                if (getattr(self, 'survey_first', False) and status == 'error'
                        and error == 'modal_incomplete_generation' and metadata.get('finish_reason') == 'length'
                        and metadata.get('submission_attempted') is True and metadata.get('call_id')
                        and getattr(telemetry, 'input_tokens', None) == admission['admitted_input_tokens']
                        and getattr(telemetry, 'output_tokens', None) == admission['output_token_cap']
                        and type(getattr(telemetry, 'latency_ms', None)) in (int, float)
                        and any(branch['properties']['action']['const'] == 'assess_source_needs'
                                for branch in manifest['schema']['anyOf'])
                        and max_items > 1):
                    self._reply_metadata['cm_batch_length_recovery'] = {'max_items': max_items - 1}
                self.harness._receipt(db, state, state.in_flight, status, telemetry=telemetry, started=started,
                                      error=error or ('scripted_' if self.execution_mode == 'offline' else 'transport_') + status)
                if state.last_receipt.get('cm_batch_length_recovery'):
                    return
                if (status == 'error' and error == 'operator_stop_before_submission'
                        and (transport_metadata or {}).get('submission_attempted') is False):
                    self.harness._stop(db, state, 'no_progress', 'operator_stop_file')
                else:
                    self.harness._stop(db, state, 'failure', ('scripted_' if self.execution_mode == 'offline' else 'transport_') + status)
                return
            try:
                action = parse_model_response(action)
                if (self.dual_search is not None and action.get('action') == 'assess_source_need'
                        and isinstance(action.get('args'), dict)):
                    submitted = action['args']
                    if (submitted.get('decision') in ('search_needed', 'no_search_needed')
                            and bool(submitted.get('proposition_ref')) == bool(submitted.get('proposition_quote'))):
                        # Repair this known schema error using a valid branch as
                        # the scaffold; unrelated schema errors remain terminal.
                        probe = deepcopy(action)
                        probe['args'].pop('proposition_quote', None)
                        ref = next((ref for ref,row in manifest['dispatch_m6'].get('source_gate_segments', {}).items()
                                    if row.get('proposition_selectable', True)), None)
                        if ref:
                            aliases = manifest.get('wire_aliases', {})
                            # Probe values must use the same wire ref encoding.
                            wire_ref = next((key for key,value in aliases.items() if value == ref), ref)
                            probe['args']['proposition_ref'] = wire_ref
                            if Draft202012Validator(manifest['schema']).is_valid(probe):
                                raise policy.ToolSemanticError('source_span_required')
                Draft202012Validator(manifest['schema']).validate(action)
                action = restore_action(action, manifest.get('wire_aliases', {}))
                payload = json.loads(state.in_flight['payload'])
                payload['m6'] = manifest['dispatch_m6']
                payload['excerpts'] = state.in_flight['excerpts']
                payload['current_payload_source_refs'] = state.in_flight['current_payload_source_refs']
                payload['query_source_hash'] = self.harness.identity.query_source_hash
                name = action['action']
                self._verify_gate_mutation(name, manifest['context'])
                if passage_review.enabled(query_review.active(self.events(), manifest['context'])):
                    internal = action
                elif name in CONTEXT_ACTIONS:
                    internal = action
                    if name == 'assess_source_needs':
                        require(getattr(self, 'survey_first', False), 'Batch survey disabled')
                        try:
                            assessments = source_gate.evaluate_batch(payload, action['args']['items'],
                                                                     self.harness.query_paragraphs)
                        except HarnessError as exc:
                            raise policy.ToolSemanticError('invalid_survey_batch') from exc
                        internal = {'action': name, 'args': {'assessments': assessments}}
                    elif name == 'group_source_needs':
                        try:
                            source_gate.group_needs(deepcopy(manifest['context']), action['args']['source_need_refs'],
                                                    action['args']['reason'], self.harness.query_paragraphs)
                        except HarnessError as exc:
                            raise policy.ToolSemanticError('invalid_source_group') from exc
                    elif name == 'assess_source_need':
                        require(self.gate_enabled, 'Source gate is disabled')
                        args = action['args']
                        evaluate = source_gate.evaluate_bound if self.dual_search is not None else source_gate.evaluate
                        internal = {'action': name, 'args': {'assessment': evaluate(
                            payload, args, self.harness.query_paragraphs)}}
                    elif name == 'choose_source_span':
                        target = manifest['handles'][action['args']['choice_ref']]
                        draft = manifest['context']['source_gate'][target['draft_ref']]
                        candidate = target['candidate']
                        args = {**draft['requested_args'], 'paragraph_ref': candidate['paragraph_ref'],
                                'proposition_quote': candidate['text']}
                        # Confirmation is positional, including when literal text
                        # occurs at several sites in the visible source.
                        segment_ref='confirmed-source-choice'
                        payload['m6']['source_gate_segments'][segment_ref]={
                            **candidate,'proposition_selectable':True}
                        args.pop('proposition_quote',None)
                        args['proposition_ref']=segment_ref
                        internal={'action':'assess_source_need','args':{'assessment':source_gate.evaluate_bound(
                            payload,args,self.harness.query_paragraphs)}}
                elif name == 'open_retrieved_passage':
                    if self.gate_enabled:
                        require(source_gate.authorized(manifest['context'], manifest['context']['need_id']), 'Candidate reading requires an approved retrieval need')
                    internal = retrieved_action(payload['m6'], action['args']['lead_ref'])
                elif name == 'open_candidate_header':
                    context = manifest['context']
                    need, case = context['need_id'], context['candidate_id']
                    require(self.gate_enabled and context['mode'] == 'assessment' and case in state.source_hashes
                            and source_gate.authorized(context, need), 'Candidate header is unavailable')
                    internal = {'action': 'open_source', 'args': {'cm4_candidate_header': {
                        'need_id': need, 'case_id': case, 'source_hash': state.source_hashes[case]}}}
                elif name == 'search_cases_by_issue':
                    args = action['args']
                    if self.gate_enabled:
                        permit = source_gate.visible_permits(payload, manifest['context'])[args['source_need_ref']]
                        decision = permit['decision']
                        anchor = {**decision['proposition'], 'source_ref': decision['source_ref']}
                        if self.dual_search is not None:
                            query_text = source_gate.query_text(decision)
                            if not self._embedding_query_budget(query_text)['accepted']:
                                raise policy.ToolSemanticError('source_query_embedding_cap')
                            need={'a_refs':[anchor['source_ref']],'intent':query_text,'route':'issue',
                                  'a_paragraph':{'handle':permit['paragraph_ref'], **deepcopy(decision['paragraph'])},
                                  'a_sources':[{'case_id':self.harness.identity.query_id,
                                                'source_hash':decision['source_hash'],'span_bytes':anchor['span_bytes']}],
                                  'a_anchor':anchor,'source_proposition':decision['proposition']['text']}
                            need.update(source_bound=True,a_supports=deepcopy(decision.get('a_supports',[])),
                                        source_query_text=query_text,source_query_sha256=sha256(query_text.encode('utf-8')).hexdigest())
                            if decision.get('group_members'):
                                need.update(group_members=deepcopy(decision['group_members']),
                                            group_kind=decision['group_kind'])
                            need['source_need_id']='need-'+fingerprint([source_gate.BOUND_VERSION,
                                decision['source_hash'],anchor['span_bytes'],
                                [(row['role'],row['source_hash'],row['span_bytes']) for row in need['a_supports']]])[:24]
                            internal={'action':'search_corpus','args':{'text':query_text,
                                'channel':self.harness.adaptive_config.channel,
                                'limit':self.harness.adaptive_config.search_limit,'_m6_need':need}}
                        else:
                            internal = self._anchored_search(payload, args, permit['paragraph_ref'], anchor)
                        internal['args']['_m6_need']['source_gate_ref'] = args['source_need_ref']
                    else:
                        resolved, _ = find_anchor(payload, args['anchor_quote'])
                    if not self.gate_enabled and resolved:
                        internal = self._anchored_search(payload, args, *resolved)
                    elif not self.gate_enabled:
                        # Validate the proposed issue before parking it. The temporary
                        # paragraph here is used for local policy validation only.
                        self._anchored_search(payload, args, next(iter(payload['m6']['a_paragraphs'])), None)
                        internal = {'action': 'stage_query_anchor', 'args': args}
                elif name == 'choose_query_anchor':
                    require(not self.gate_enabled, 'Source gate requires a new bound assessment before anchor retrieval')
                    target = manifest['handles'][action['args']['anchor_ref']]
                    context = manifest['context']
                    draft = context['anchor_drafts'][target['draft_id']]
                    require(target['draft_id'] == context.get('active_anchor_draft'), 'Anchor choice belongs to another draft')
                    internal = self._anchored_search(payload, draft['args'], target['paragraph_key'], target['anchor'])
                elif self.gate_enabled and name == 'finish_case_review' and action['args']['reason'] == 'complete_policy':
                    # The gate schema also permits a fully screened query with zero searches.
                    internal = {'action': 'stop', 'args': {'reason': 'complete'}}
                else:
                    translated = action
                    if name in ASSESSMENT_TOOLS:
                        args = dict(action['args'])
                        pair = payload['m6']['pair_refs'][args['pair_ref']]
                        for public, internal_field in EVIDENCE_CHOICES:
                            choice = args.pop(public, '')
                            if choice:
                                sides = choice.split('+')
                                args[internal_field] = [ref for side, key in (('A', 'a_context_refs'), ('B', 'b_passage_refs'))
                                                        if side in sides for ref in pair[key]]
                        translated = {'action': name, 'args': args}
                    internal = policy.translate(payload, translated)
                    if name == 'read_case_passages':
                        internal = focused_action(internal, payload['m6'])
                internal = self._canonical_hybrid_need(internal)
                if self.gate_enabled and internal['action'] in ('search_corpus', 'search_identity'):
                    self._verify_search_permit(internal, manifest['context'])
                encode(internal)
                if action['action'] in ('record_missing_evidence', 'defer_case_pair', 'report_review_blocker',
                                        'prioritize_query_results', 'conclude_search_query', 'revisit_source_need'):
                    if not action['args']['reason'].strip():
                        raise policy.ToolSemanticError('blank_reason')
                if (action['action'] == 'conclude_search_query'
                        and not passage_review.enabled(query_review.active(self.events(), manifest['context']))):
                    try:
                        query_review.conclude(query_review.active(self.events(), manifest['context']), state, action['args'])
                    except HarnessError as exc:
                        raise policy.ToolSemanticError('invalid_query_conclusion') from exc
                if action['action'] == 'prioritize_query_results' and len(action['args']['candidate_refs']) != len(set(action['args']['candidate_refs'])):
                    raise policy.ToolSemanticError('duplicate_evidence_refs')
                if action['action'] in ASSESSMENT_TOOLS:
                    notes = internal['args']['assessments'][0].get('missing_evidence', [])
                    if len(notes) != len(set(notes)):
                        raise policy.ToolSemanticError('duplicate_missing_evidence')
            except policy.ToolSemanticError as exc:
                feedback = repair_feedback(action, str(exc))
                repair = bind_repair(self.harness.ledger.read(db), feedback, manifest) if feedback else None
                missing_selector = str(exc) == 'source_span_required'
                if repair:
                    if self.loop_guard_mode == 'warn' and not missing_selector:
                        repair['warning_threshold_reached'] = not repair['retry_allowed']
                        repair['retry_allowed'] = True
                    self._reply_metadata['cm_tool_repair'] = repair
                self.harness._receipt(db, state, state.in_flight, 'malformed', received=True, telemetry=telemetry,
                                      started=started, error=str(exc),
                                      schema_validation='rejected' if missing_selector else 'passed')
                if state.last_receipt['telemetry_error']:
                    self.harness._stop(db, state, 'failure', state.last_receipt['telemetry_error'])
                elif repair and not repair['retry_allowed']:
                    self.harness._stop(db, state, 'no_progress', 'repeated_tool_input_rejection')
                elif not repair:
                    self.harness._stop(db, state, 'failure', 'scripted_response_rejected' if self.execution_mode == 'offline' else 'response_rejected')
                return
            except Exception as exc:
                self.harness._receipt(db, state, state.in_flight, 'malformed', received=True, telemetry=telemetry, started=started,
                                      error=('scripted_rejected:' if self.execution_mode == 'offline' else 'response_rejected:') + type(exc).__name__, schema_validation='rejected')
                self.harness._stop(db, state, 'failure', 'scripted_response_rejected' if self.execution_mode == 'offline' else 'response_rejected')
                return
            self.harness._receipt(db, state, state.in_flight, 'success', received=True, telemetry=telemetry, started=started,
                                  action=internal, schema_validation='passed')

    def execute_pending(self):
        with self.harness.ledger.writer() as db:
            state = RunState(self.harness.ledger.read(db))
            require(state.pending_action is not None, 'No pending model action')
            action = state.pending_action['action']
            context = self.context()
            self._verify_gate_mutation(action['action'], context)
            if (action['action'] not in CONTEXT_ACTIONS
                    and not passage_review.enabled(query_review.active(self.events(), context))):
                # Source verification and actual M4 assessment validator execute here.
                try:
                    for ref in state.current:
                        self.store.verify(state.current_records[ref])
                except SourceDrift as exc:
                    self.harness._record_drift(db, state, exc.case_id)
                    return state.snapshot()
                if context['candidate_id']:
                    pair = fingerprint([context['need_id'], context['candidate_id']])
                    admission = state.requests[state.pending_action['request_id']]
                    manifest = self._manifest(admission)
                    context['pair_pins'][pair] = list(dict.fromkeys([*context['pair_pins'].get(pair, []), *(c['canonical_ref'] for c in manifest['coverage'])]))
                    context['pair_targets'][pair] = {key: context[key] for key in ('need_id', 'candidate_id')}
                    self._commit_coverage(context, manifest['coverage'])
                # Persist parked refs at the same durable action boundary as its outcome.
                self._observed_excerpts = []
                original = self.harness._write
                receipt = state.pending_action
                def write(db_, state_, kind, **fields):
                    if kind == 'action_result' and 'cm_context' not in fields:
                        latest = deepcopy(context)
                        fields['cm_context'] = latest
                        name = action['action']
                        reason = fields.get('reason') or ''
                        if name == 'open_source' and 'cm4_candidate_header' in action['args']:
                            if fields['status'] == 'success':
                                target = action['args']['cm4_candidate_header']
                                span = fields['result']['observation']['cm4_candidate_header']
                                self._progress(latest)['candidate_header'] = {
                                    'span_bytes': span, 'source_hash': target['source_hash']}
                            latest['revision'] += 1
                            return original(db_, state_, kind, **fields)
                        if name == 'assess_links' and reason.startswith('assessment_state:'):
                            raw = receipt['raw_model_reply']
                            chosen = parse_model_response(raw)
                            feedback = repair_feedback(chosen, reason.split(':', 1)[1], provenance=True)
                            if feedback:
                                admission = state_.requests[receipt['request_id']]
                                repair = bind_repair(self.harness.ledger.read(db_), feedback, self._manifest(admission))
                                if self.loop_guard_mode == 'warn':
                                    repair['warning_threshold_reached'] = not repair['retry_allowed']
                                    repair['retry_allowed'] = True
                                fields['cm_tool_repair'] = repair
                                fields['final'] = None if repair['retry_allowed'] else self.harness._final(
                                    'no_progress', 'repeated_tool_input_rejection')
                                return original(db_, state_, kind, **fields)
                        raw_rows = (fields.get('result') or {}).get('excerpts', [])
                        fresh_refs = [r['ref'] for r in raw_rows if r['text'].strip()]
                        for value in self._observed_excerpts:
                            for ref, record in state_.catalog.items():
                                if (record['case_id'] == value.case_id and record['source_hash'] == value.source_hash
                                        and tuple(record['span_bytes']) == tuple(value.span_bytes)
                                        and record['text_sha256'] == value.text_sha256
                                        and record['provenance'] == value.provenance):
                                    if record['text'].strip():
                                        fresh_refs.append(ref)
                        known = {**state_.catalog, **{r['ref']: r for r in raw_rows}} if raw_rows else state_.catalog
                        reopen_stage = None
                        reopened_spans = {}
                        candidate = action['args'].get('m6_candidate') if name == 'open_source' else None
                        if candidate and fields['status'] == 'success':
                            case_id = candidate['case_id']
                            if not any(row['case_id'] == case_id and row['text'].strip() for row in raw_rows):
                                cached = sorted((item for item in state_.catalog.items() if item[1]['case_id'] == case_id),
                                                key=lambda item: item[1]['span_bytes'])
                                for value in self._observed_excerpts:
                                    if value.case_id != case_id or not value.text.strip():
                                        continue
                                    for ref, record in cached:
                                        if record['source_hash'] != value.source_hash:
                                            continue
                                        left, right = record['span_bytes']
                                        start, end = max(left, value.span_bytes[0]), min(right, value.span_bytes[1])
                                        if start < end and slice_record(record, start, end)['text'].strip():
                                            reopened_spans.setdefault(ref, [start, end])
                                if reopened_spans:
                                    fresh_refs = [*reopened_spans, *(ref for ref in fresh_refs
                                                  if known[ref]['case_id'] != case_id)]
                            pair = {'source_need_id': latest['need_id'], 'candidate_id': case_id, 'a_context_refs': [],
                                    'b_passage_refs': [ref for ref in fresh_refs if known[ref]['case_id'] == case_id]}
                            assessed_view = {**known, **{ref: slice_record(known[ref], *span)
                                                         for ref, span in reopened_spans.items()}}
                            if not self._has_new_assessment_raw(state_, pair, assessed_view):
                                fields['reason'] = 'reopened_without_new_raw'
                                pair_key = (latest['need_id'], case_id)
                                reopen_stage = 'missing_evidence' if pair_key in state_.pending_assessments else 'assessed'
                                if not reopened_spans:
                                    fresh_refs = []
                        self._transition_result(latest, action, fields, reopen_stage=reopen_stage)
                        if fresh_refs:
                            cm = fields['cm_context']
                            pair_key = fingerprint([cm['need_id'], cm['candidate_id']])
                            if cm['candidate_id'] or (cm['mode'] == 'query' and pair_key in cm['pair_pins']):
                                prior = cm['pair_pins'].get(pair_key, [])
                                fresh_sides = {known[r]['case_id'] for r in fresh_refs}
                                progress = self._progress(cm, pair_key)
                                if name == 'open_source':
                                    progress['reopened_spans'] = reopened_spans
                                    for ref, span in reopened_spans.items():
                                        progress['window_offsets'][ref] = span[0]
                                        progress['active_roots'].pop(known[ref]['case_id'], None)
                                        if ref in progress.get('lead_windows', {}):
                                            progress['lead_windows'].pop(ref)
                                continuing_lead = (name == 'expand_source'
                                                   and action['args'] == progress.get('lead_source_continuation'))
                                retained = [r for r in prior if known[r]['case_id'] not in fresh_sides
                                            or (continuing_lead and r in progress.get('lead_windows', {}))]
                                # Keep the exact active need's A anchor when only B is newly read.
                                if self.harness.identity.query_id not in fresh_sides and not any(known[r]['case_id'] == self.harness.identity.query_id for r in retained):
                                    need = next((n for e in reversed(self.events()) if e['kind'] == 'action_result' and e.get('result')
                                                 for n in [e['result']['observation'].get('m6_source_need')] if n and n['source_need_id'] == cm['need_id']), None)
                                    retained.extend(r for r in (need or {}).get('a_refs', []) if r in known)
                                cm['pair_pins'][pair_key] = list(dict.fromkeys([*retained, *fresh_refs]))
                                if cm['need_id'] and cm['candidate_id']:
                                    cm['pair_targets'][pair_key] = {k: cm[k] for k in ('need_id', 'candidate_id')}
                                # New source work changes the visible region, but does not erase
                                # delivered progress on roots that are already known to this pair.
                                for side in fresh_sides:
                                    active = progress['active_roots'].get(side)
                                    if active not in cm['pair_pins'][pair_key]:
                                        progress['active_roots'].pop(side, None)
                                self._prioritize_initial_hit(cm, action, fields, known, fresh_refs)
                            fields['reload_refs'] = list(dict.fromkeys([*fields.get('reload_refs', []), *(r for r in fresh_refs if r in state_.catalog)]))
                        self._sync_missing(fields['cm_context'])
                        fields['cm_context']['revision'] += 1
                    return original(db_, state_, kind, **fields)
                self.harness._write = write
                try:
                    self.harness._apply_action(db, state)
                except SourceDrift as exc:
                    self.harness._record_drift(db, state, exc.case_id)
                finally:
                    self.harness._write = original
                return state.snapshot()
            receipt = state.pending_action
            admission = state.requests[receipt['request_id']]
            manifest = self._manifest(admission)
            require(context == manifest['context'], 'Context changed since admission')
            self._commit_coverage(context, manifest['coverage'])
            action_id = fingerprint([receipt['request_id'], 'action'])
            self.harness._write(db, state, 'action_started', action_id=action_id, request_id=receipt['request_id'],
                                action=action, action_fingerprint=fingerprint(action), executes_tool=False)
            name, args = action['action'], action['args']
            reload_refs = []
            action_status, action_reason = 'success', None
            review = query_review.active(self.events(), context)
            if passage_review.enabled(review):
                try:
                    passage_review.execute(self, db, state, context, review, action, manifest, action_id)
                except SourceDrift as exc:
                    self.harness._record_drift(db, state, exc.case_id)
                except HarnessError as exc:
                    restored = self.context()
                    restored.setdefault('passage_session', {})['last_read_feedback'] = str(exc)[:240]
                    self.harness._write(db, state, 'action_result', action_id=action_id,
                        status='error', result=None, reason=str(exc), reload_refs=[],
                        invalidated_assessments=[], assessments=[], pending_assessments=[], final=None,
                        local_elapsed_ms=0, cm_context=restored)
                return state.snapshot()
            if name == 'read_source_context':
                target=manifest['handles'][args['context_ref']]
                raw=self.store.raw_reader(self.harness.identity.query_id)
                require(target['source_hash']==self.harness.identity.query_source_hash
                        and sha256(raw).hexdigest()==target['source_hash'],'Query context source changed')
                left,right=target['span_bytes']
                text=raw[left:right].decode('utf-8')
                record=source_record(SourceExcerpt(self.harness.identity.query_id,target['source_hash'],(left,right),text,
                    sha256(text.encode('utf-8')).hexdigest(),provenance={'extraction_method':source_gate.BOUND_VERSION}))
                context.update(mode='query_span',offset=0,back=[],query_span_record=record)
            elif name == 'revise_source_need':
                decision=context['source_gate'][args['source_need_ref']]
                require(decision['status']=='approved','Only an unconsumed permit can be revised')
                context.setdefault('source_gate_history',[]).append(deepcopy(decision))
                for member in decision.pop('group_members', []):
                    row = context['source_gate'].get(member)
                    if row and row.get('grouped_into') == args['source_need_ref']:
                        row.pop('grouped_into')
                        row['status'] = 'approved'
                decision.pop('group_kind', None)
                decision.pop('group_reason', None)
                decision['a_supports'] = decision.pop('ungrouped_a_supports', [
                    row for row in decision.get('a_supports', []) if row['role'] != 'group_member'])
                decision.update(status='unresolved',decision='need_more_context',resolution_choices=[],
                                validation_message='Approval withdrawn for a revised source-span selection.')
            elif name == 'read_query_span':
                target = manifest['handles'][args['span_ref']]
                try:
                    record = self._combined_query_record(state, target)
                except SourceDrift as exc:
                    self.harness._record_drift(db, state, exc.case_id)
                    return state.snapshot()
                context.update(mode='query_span', offset=0, back=[], query_span_record=record)
            elif name == 'prioritize_query_results':
                query = query_review.active(self.events(), context)
                require(query is not None, 'No active query')
                decisions = context.setdefault('query_priorities', {}).setdefault(query['query_id'], {})
                require(len(args['candidate_refs']) == len(set(args['candidate_refs'])), 'Duplicate priority refs')
                for ref in args['candidate_refs']:
                    case = manifest['handles'][ref]['case_id']
                    require(case in query['survey_exposed'], 'Priority requires a delivered survey card')
                    require(decisions.get(case, {}).get('priority') != args['priority'], 'Unchanged priority assignment')
                    decisions[case] = {'priority': args['priority'], 'reason': args['reason'].strip()}
            elif name == 'conclude_search_query':
                query = query_review.active(self.events(), context)
                require(query is not None, 'No active query')
                context.setdefault('query_conclusions', {})[query['query_id']] = query_review.conclude(query, state, args)
                context.update(candidate_id=None, stage='ready', mode='query', offset=0, back=[])
            elif name == 'report_review_blocker':
                require(self.gate_enabled, 'Review blocker is unavailable')
                reports = context.setdefault('review_blockers', {}).setdefault(self._blocker_scope(context), {})
                require(args['kind'] not in reports, 'Review blocker already reported in this scope')
                report = {'action_id': action_id, 'kind': args['kind'], 'reason': args['reason'].strip(),
                          'need_id': context['need_id'], 'candidate_id': context['candidate_id'],
                          'query_region': context.get('query_leaf_region') if context['mode'] == 'query_leaf'
                          else context.get('query_map_region') if context['mode'] == 'query' else None}
                if args['kind'] == 'tool_rejected':
                    repair = json.loads(admission['payload'])['last_action_feedback'].get('tool_repair')
                    if repair:
                        report['observed_repair'] = {key: repair[key] for key in ('tool', 'code', 'fields', 'hint')}
                reports[args['kind']] = report
            elif name == 'group_source_needs':
                require(getattr(self, 'survey_first', False), 'Survey grouping disabled')
                source_gate.group_needs(context, args['source_need_refs'], args['reason'],
                                        self.harness.query_paragraphs)
                main = context['source_gate'][args['source_need_refs'][0]]
                for support in main.pop('group_context', []):
                    support['case_id'] = self.harness.identity.query_id
                    if support not in main.setdefault('a_supports', []):
                        main['a_supports'].append(support)
            elif name == 'assess_source_needs':
                assessments = args['assessments']
                refs = set()
                for assessment in assessments:
                    refs.add(assessment['source_ref'])
                    refs.update(s['source_ref'] for s in assessment.get('a_supports', []))
                    if signal := assessment.get('signal'):
                        refs.add(signal['source_ref'])
                try:
                    for ref in sorted(refs):
                        self.store.verify(state.current_records[ref])
                except SourceDrift as exc:
                    self.harness._record_drift(db, state, exc.case_id)
                    return state.snapshot()
                updated = deepcopy(context)
                for assessment in assessments:
                    source_gate.commit_decision(updated, assessment)
                context.update(updated)
            elif name == 'assess_source_need':
                assessment = deepcopy(args['assessment'])
                try:
                    self.store.verify(state.current_records[assessment['source_ref']])
                    if signal := assessment['signal']:
                        if signal['source_ref'] != assessment['source_ref']:
                            self.store.verify(state.current_records[signal['source_ref']])
                    for support in assessment.get('a_supports',[]):
                        self.store.verify(state.current_records[support['source_ref']])
                except SourceDrift as exc:
                    self.harness._record_drift(db, state, exc.case_id)
                    return state.snapshot()
                if not source_gate.commit_decision(context, assessment):
                    action_status, action_reason = 'duplicate', 'partial_view_already_screened'
                elif self.dual_search is not None:
                    context['source_return_focus']={'source_hash':assessment['source_hash'],
                        'span_bytes':assessment['visible_span_bytes'],'paragraph_handle':assessment['paragraph_handle']}
            elif name == 'revisit_source_need':
                require(query_review.active(self.events(), context) is None, 'Conclude the current query first')
                decision = context['source_gate'][args['source_need_ref']]
                require(decision['status'] == 'searched', 'Only searched source needs may be revisited')
                decision.update(status='approved', revisit_reason=args['reason'].strip())
            elif name in ('defer_approved_source_need', 'resume_approved_source_need'):
                require(self.gate_enabled, 'Source gate is disabled')
                decision = context['source_gate'][args['source_need_ref']]
                if name == 'defer_approved_source_need':
                    require(decision['status'] == 'approved', 'Only an approved search can be postponed')
                    decision.update(status='search_deferred', search_defer_code=args['reason_code'],
                                    search_defer_reason=args['reason'].strip())
                else:
                    require(decision['status'] == 'search_deferred', 'Only a deferred search can be reopened')
                    decision.update(status='approved', search_resume_reason=args['reason'].strip())
            elif name == 'show_source_need_page':
                target = manifest['handles'][args['page_ref']]
                require(self.gate_enabled and target['kind'] == 'source_need_page', 'Invalid source-need page handle')
                require(target['start_ref'] in context.get('source_gate', {}), 'Unknown source-need page cursor')
                context['source_need_page_start'] = target['start_ref']
            elif name == 'defer_source_need':
                require(self.gate_enabled, 'Source gate is disabled')
                decision = context['source_gate'][args['source_need_ref']]
                require(decision['status'] == 'unresolved', 'Only an unresolved source question may be deferred')
                require(decision['context_complete'] or source_gate.query_fully_read(
                        state, self.harness.query_paragraphs, self.harness.identity.query_id,
                        self.harness.identity.query_source_hash), 'Read the source context before deferring this question')
                decision.update(status='deferred', defer_reason=args['reason'], context_complete=True)
            elif name == 'close_query_anchor':
                target = manifest['handles'][args['draft_ref']]
                draft_id = target['draft_id']
                draft = context['anchor_drafts'][draft_id]
                if args['resolution'] == 'superseded':
                    valid = manifest['dispatch_m6']['anchor_replacements']
                    require(args['replacement_ref'] in valid and args['replacement_ref'] != args['draft_ref'], 'A superseded draft requires another existing replacement')
                else:
                    require(not args['replacement_ref'], 'A discarded draft has no replacement')
                context.setdefault('closed_anchor_drafts', {})[draft_id] = {
                    **deepcopy(draft), 'resolution': args['resolution'], 'reason': args['reason'],
                    'replacement_ref': args['replacement_ref'] or None}
                del context['anchor_drafts'][draft_id]
                if context.get('active_anchor_draft') == draft_id:
                    context.pop('active_anchor_draft')
            elif name == 'stage_query_anchor':
                draft_id = fingerprint(['query_anchor', *(' '.join(args[key].split()) for key in ('issue', 'anchor_quote'))])
                drafts = context.setdefault('anchor_drafts', {})
                draft = drafts.setdefault(draft_id, {'args': args})
                draft['view'] = {key: deepcopy(context[key]) for key in ANCHOR_VIEW_KEYS if key in context}
                context['active_anchor_draft'] = draft_id
            elif name == 'defer_query_anchor':
                draft_id = context.pop('active_anchor_draft')
                draft = context['anchor_drafts'][draft_id]
                draft['view'] = {key: deepcopy(context[key]) for key in ANCHOR_VIEW_KEYS if key in context}
            elif name == 'resume_query_anchor':
                target = manifest['handles'][args['draft_ref']]
                draft_id = target['draft_id']
                context['active_anchor_draft'] = draft_id
                draft = context['anchor_drafts'][draft_id]
                for key in ANCHOR_VIEW_KEYS:
                    context.pop(key, None)
                context.update(deepcopy(draft['view']))
            elif name == 'record_missing_evidence':
                require(args['reason'].strip(), 'Missing evidence reason blank')
                progress = self._progress(context)
                progress['missing_reason'] = args['reason']
                progress['reported_missing_evidence'] = [args['reason']]
                progress['validation_missing_codes'] = []
                context.update(stage='missing_evidence')
            elif name == 'defer_case_pair':
                need, case = context['need_id'], context['candidate_id']
                require(need and case and context['stage'] == 'missing_evidence', 'Only a pair missing evidence may be deferred')
                pair = fingerprint([need, case])
                offered = self._progress(context, pair).get('offered_spans', {})
                context.setdefault('deferred_pairs', {})[pair] = {
                    'need_id': need, 'candidate_id': case, 'reason': args['reason'].strip(),
                    'known_spans': [span for ref, spans in offered.items()
                                    if state.catalog[ref]['case_id'] == case for span in spans]}
                context['pair_targets'][pair] = {'need_id': need, 'candidate_id': case}
                context['pair_pins'].setdefault(pair, [])
                context.update(candidate_id=None, stage='ready', mode='results', offset=0, back=[])
            elif name == 'show_context_page':
                target = manifest['handles'][args['page_ref']]
                context.update(mode=target['mode'], offset=target['offset'], back=target['back'])
            elif name == 'set_context_focus':
                require(self.gate_enabled or context['stage'] != 'reading', 'Pair still being read')
                target = manifest['handles'][args['need_ref']]
                context.update(need_id=target['need_id'], candidate_id=None, stage='ready', mode='results', offset=0, back=[])
            elif name in ('reload_pair_evidence', 'resume_pair_evidence'):
                target = manifest['handles'][args['evidence_ref']]
                reload_refs = context['pair_pins'][target['pair']]
                progress = self._progress(context, target['pair'])
                deferred = context.get('deferred_pairs', {})
                if name == 'resume_pair_evidence' and target['pair'] in deferred:
                    new_refs = self._new_deferred_refs(state, deferred[target['pair']])
                    require(new_refs, 'Deferred pair needs additional raw text')
                    reload_refs = list(dict.fromkeys([*new_refs, *reload_refs]))
                    context['pair_pins'][target['pair']] = reload_refs
                    progress['active_roots'].pop(target['candidate_id'], None)
                    del deferred[target['pair']]
                else:
                    new_refs = {}
                if name == 'reload_pair_evidence':
                    context['pair_progress'][target['pair']] = {
                        'window_offsets': {}, 'next_offsets': {}, 'active_roots': {}, 'completed_roots': [],
                        'offered_spans': progress.get('offered_spans', {})}
                    if 'candidate_header' in progress:
                        self._progress(context, target['pair'])['candidate_header'] = progress['candidate_header']
                    lead_windows = progress.get('lead_windows', {})
                    if lead_windows:
                        reset = self._progress(context, target['pair'])
                        reset['lead_windows'] = lead_windows
                        reset['lead_reviewed'] = progress.get('lead_reviewed', False)
                        reset['window_offsets'] = {ref: state.catalog[ref]['span_bytes'][0]
                                                   for ref in reload_refs if ref in lead_windows}
                    if progress.get('lead_source_continuation'):
                        self._progress(context, target['pair'])['lead_source_continuation'] = progress['lead_source_continuation']
                else:
                    # Resume at the next delivered boundary; completed active windows
                    # stay available as current raw for assessment, without a read loop.
                    for ref in reload_refs:
                        if ref in new_refs:
                            progress['window_offsets'][ref] = new_refs[ref][0]
                            progress.setdefault('reopened_spans', {})[ref] = new_refs[ref]
                            continue
                        end = progress.get('reopened_spans', {}).get(ref, state.catalog[ref]['span_bytes'])[1]
                        offset = progress['next_offsets'].get(ref)
                        lead = progress.get('lead_windows', {}).get(ref)
                        if lead:
                            gaps = unread_spans(lead['span'], lead['offered']) or unread_spans(
                                state.catalog[ref]['span_bytes'], lead['offered'])
                            offset = gaps[0][0] if gaps else None
                        if ref not in progress['completed_roots'] and offset is not None and offset < end:
                            progress['window_offsets'][ref] = offset
                context.update(mode='assessment', offset=0, back=[])
                if name == 'resume_pair_evidence':
                    require(self.gate_enabled or context['stage'] in ('ready', 'assessed', 'missing_evidence', 'error', 'no_hit'), 'Finish current pair before resuming another')
                    pair = target['need_id'], target['candidate_id']
                    stage = 'reading'
                    if pair in state.pending_assessments or progress.get('missing_reason'):
                        stage = 'missing_evidence'
                    elif pair in state.active_assessments:
                        stage = 'assessed'
                    context.update(need_id=pair[0], candidate_id=pair[1], stage=stage)
                try:
                    for ref in reload_refs:
                        self.store.verify(state.catalog[ref])
                except SourceDrift as exc:
                    self.harness._record_drift(db, state, exc.case_id)
                    return state.snapshot()
            elif name == 'continue_raw_evidence':
                target = manifest['handles'][args['context_ref']]
                require(target['pair'] == fingerprint([context['need_id'], context['candidate_id']]), 'Continuation belongs to another pair')
                pair = target['pair']
                context['pair_pins'][pair] = list(dict.fromkeys([*context['pair_pins'].get(pair, []),
                    *(c['canonical_ref'] for c in manifest['coverage']), target['ref']]))
                if context['need_id'] and context['candidate_id']:
                    context['pair_targets'][pair] = {key: context[key] for key in ('need_id', 'candidate_id')}
                progress = self._progress(context, pair)
                progress['window_offsets'][target['ref']] = target['offset']
                progress['active_roots'][state.catalog[target['ref']]['case_id']] = target['ref']
            if getattr(self, 'survey_first', False) and name in (
                    'assess_source_need', 'assess_source_needs', 'defer_source_need', 'resume_approved_source_need'):
                source_gate.group_exact_citations(context, self.harness.query_paragraphs,
                                                 self.harness.identity.query_id, self.store.raw_reader)
            if self.dual_search is not None and name in (
                    'assess_source_need', 'assess_source_needs', 'group_source_needs', 'defer_source_need',
                    'resume_approved_source_need', 'revisit_source_need', 'revise_source_need'):
                source_gate.fit_query_permits(context, self.harness.identity.query_id, self._embedding_query_budget)
            self._sync_missing(context)
            context['revision'] += 1
            self.harness._write(db, state, 'action_result', action_id=action_id, status=action_status, result=None,
                reason=action_reason, reload_refs=reload_refs, invalidated_assessments=[], assessments=[], pending_assessments=[],
                final=None, local_elapsed_ms=0, cm_context=context)
            return state.snapshot()

    def step(self, action):
        prepared = self.prepare()
        require(prepared['status'] == 'ready', 'Cannot script an unready context')
        reply = action(prepared) if callable(action) else action
        self.reply(prepared['request_id'], reply)
        if self.state().pending_action is not None:
            self.execute_pending()
        return prepared

    def stop(self, reason, *, status='no_progress'):
        with self.harness.ledger.writer() as db:
            state = RunState(self.harness.ledger.read(db))
            if state.final is None:
                self.harness._stop(db, state, status, reason)

    def inspect(self):
        result = {'context': self.context(), 'state': self.state().snapshot(),
                  'execution_mode': self.execution_mode}
        snapshot = result['state']
        if self.gate_enabled:
            result['search_queries'] = query_review.queries(self.events(), self.context())
            qs = list(result['search_queries'].values())
            result['query_review_totals'] = {
                'queries': len(qs), 'query_candidate_pairs': sum(len(q['candidate_ids']) for q in qs),
                'unique_candidates': len({case for q in qs for case in q['candidate_ids']}),
                'unique_survey_exposed': len({case for q in qs for case in q['survey_exposed']}),
                'unique_raw_exposed': len({case for q in qs for case in q['raw_exposed']})}
        matches = result['context'].get('host_citation_matches', {})
        if matches:
            result['host_citation_match_count'] = len(matches)
        if self.gate_enabled and snapshot['stop_reason'] not in (None, 'complete'):
            result['partial_supported_cases'] = sorted({
                case for case, row in snapshot['candidate_states'].items()
                if row['case_relation'] == 'supported' and row.get('selection_assessment_id')}
                | {match['b']['case_id'] for match in matches.values()})
        if self.execution_mode == 'offline':
            result.update(controller_inference_requests=0, embedding_requests=0, receipt_kind='scripted_offline_not_provider')
        else:
            receipts = [e for e in self.events() if e['kind'] == 'request_result']
            known = sum((e.get('transport_metadata') or {}).get('submission_attempted') is True for e in receipts)
            unknown = sum((e.get('transport_metadata') or {}).get('submission_attempted') not in (True, False) for e in receipts)
            unknown += len(self.state().requests) - len(receipts)
            result.update(controller_submission_attempts=None if unknown else known,
                          known_controller_submission_attempts=known, unknown_controller_submission_receipts=unknown,
                          receipt_kind='provider_actual_or_unknown',
                          embedding_usage=self.harness.hybrid_search.usage() if self.harness.hybrid_search else None)
        return result
