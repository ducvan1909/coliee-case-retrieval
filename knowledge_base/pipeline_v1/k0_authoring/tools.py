"""Local, case-bound source navigation and deterministic draft/read state."""
from __future__ import annotations

import copy

from .core import require


def initial_state(case):
    return {'case_id': case['case_id'], 'source_hash': case['source_hash'], 'turn': 0,
            'active_scope_ids': None, 'drafts': {}, 'revisions': [], 'warnings': [], 'au_errors': [],
            'read_ledger': {s['scope_id']: {'state': 'available', 'delivered_count': 0, 'assessed': False}
                            for s in case['scopes']},
            'finished': False, 'stop_reason': None, 'work_scope_complete': False,
            'case_source_assessment_complete': False, 'case_status': 'partial', 'tool_result': None}


def get_case(case, state):
    require(case['case_id'] == state['case_id'] and case['source_hash'] == state['source_hash'], 'foreign case work')
    return {'case_id': case['case_id'], 'source_hash': case['source_hash'],
            'source_char_length': case['source_char_length'], 'scopes': copy.deepcopy(state['read_ledger']),
            'work_scope_complete': state['work_scope_complete'], 'case_status': 'partial',
            'draft_ids': list(state['drafts'])}


def open_region(case, scope_ids):
    require(isinstance(scope_ids, list) and scope_ids, 'empty region request')
    scopes = {s['scope_id']: s for s in case['scopes']}
    require(all(isinstance(s, str) and s in scopes for s in scope_ids), 'scope outside K0 source union')
    ids = list(dict.fromkeys(scope_ids))
    evidence = {e: copy.deepcopy(case['evidence_catalog'][e]) for sid in ids for e in scopes[sid]['evidence_ids']}
    return {'case_id': case['case_id'], 'source_hash': case['source_hash'], 'scope_ids': ids, 'evidence': evidence}


def search_source(case, query):
    require(isinstance(query, str) and bool(query.strip()), 'empty lexical query')
    terms = query.casefold().split()
    hits = []
    for scope in case['scopes']:
        text = ' '.join(case['evidence_catalog'][e]['quote'] for e in scope['evidence_ids'])
        if all(t in text.casefold() for t in terms):
            hits.append({'scope_id': scope['scope_id'], 'preview': ' '.join(text.split())[:160],
                         'preview_only': True, 'must_open_before_citing': True})
    return {'query': query, 'hits': hits[:5], 'scope': 'K0_union_only', 'preview_is_evidence': False}


def get_drafts(case, state):
    get_case(case, state)
    return {'drafts': [{'id': aid, 'claim': a['claim'], 'kind': a['kind'], 'limits': a['limits']}
                       for aid, a in state['drafts'].items()],
            'note': 'Drafts are not evidence. Reopen source before proposing a revision.'}


def submit_aus(case, state, aus):
    result = copy.deepcopy(state)
    for au in aus:
        require(au['case_id'] == case['case_id'] and au['source_hash'] == case['source_hash'], 'foreign AU owner')
        for ref in au['evidence']:
            require(ref in case['evidence_catalog'].values(), 'evidence outside case union')
        value = copy.deepcopy(au)
        replace = value.pop('replace_id', None)
        aid = value['au_id']
        if replace:
            require(replace in result['drafts'], 'unknown revision owner')
            if replace != aid:
                previous = result['drafts'].pop(replace)
                result['revisions'].append({'superseded_id': replace, 'replacement_id': aid,
                                            'previous': previous, 'turn': state['turn']})
        result['drafts'][aid] = value  # Exact duplicates are idempotent; no semantic dedup.
    return result


def finish_case(case, state, reason):
    require(reason in ('work_scope_complete', 'needs_context'), 'invalid finish reason')
    result = copy.deepcopy(state)
    result.update(finished=True, stop_reason=reason,
                  work_scope_complete=all(r['assessed'] for r in result['read_ledger'].values()),
                  case_source_assessment_complete=False, case_status='partial')
    if reason == 'needs_context':
        for sid in result['active_scope_ids'] or []:
            result['read_ledger'][sid]['state'] = 'unresolved'
    return result


def apply_turn(case, state, normalized):
    get_case(case, state)
    require(not state['finished'], 'finished work cannot receive another turn')
    result = submit_aus(case, state, normalized['aus'])
    delivered = normalized['delivered_scope_ids']
    open_region(case, delivered)
    result['active_scope_ids'] = delivered
    for sid in delivered:
        entry = result['read_ledger'][sid]
        entry['delivered_count'] += 1
        if not entry['assessed']:
            entry['state'] = 'delivered'
    require(set(normalized['assessed_scope_ids']) <= set(delivered), 'cannot assess a navigation preview')
    # A bad candidate does not erase good drafts, but must not certify assessment.
    if not normalized['au_errors']:
        for sid in normalized['assessed_scope_ids']:
            result['read_ledger'][sid].update(state='assessed', assessed=True)
    result['warnings'].extend(copy.deepcopy(normalized['warnings']))
    result['au_errors'].extend(copy.deepcopy(normalized['au_errors']))
    result['turn'] += 1
    if normalized['au_errors']:
        result.update(finished=True, stop_reason='invalid_AU', work_scope_complete=False)
        return result
    action = normalized['next_action']
    if action['tool'] == 'finish_case':
        return finish_case(case, result, action['reason'])
    if action['tool'] == 'open_region':
        opened = open_region(case, action['scope_ids'])
        result['active_scope_ids'] = opened['scope_ids']
        # Do not mark delivered until the next response confirms actual delivery.
        result['tool_result'] = {'tool': 'open_region', 'scope_ids': opened['scope_ids']}
    elif action['tool'] == 'search_source':
        result['tool_result'] = search_source(case, action['query'])
    elif action['tool'] == 'get_drafts':
        result['tool_result'] = get_drafts(case, result)
    else:
        require(False, 'unsupported tool')
    return result
