"""Host source navigation. Navigation exposure never counts as assessment."""
from __future__ import annotations

import copy
import re
from ..milestone1.core import digest
from ..au_compact import runner
from ..au_compact.core import build_evidence_catalog

POLICY = 'selective-exact30-first-last-salient-v1'
CUES = re.compile(r'\b(must|shall|unless|however|court|held|requires?|test|exception)\b', re.I)
FIND_TERMS = {
    'attribution': ('submits', 'argues', 'counsel', 'according'),
    'current_court_response': ('reject', 'accept', 'conclude', 'held'),
    'condition': ('only if', 'provided', 'where', 'if'),
    'exception': ('unless', 'except', 'however'),
    'limit': ('limited', 'only', 'does not'),
    'cross_block_context': ('however', 'submits', 'unless'),
}


def _ref(task, start, end, **extra):
    q = task['request']
    return {'case_id': q['case_id'], 'source_hash': q['source_hash'],
            'start_char': start, 'end_char': end, **extra}


def previews(task):
    """At most three disjoint/deduplicated raw excerpts of <=120 characters."""
    refs = [r for r in task['request']['source_refs'] if r['role'] == 'target']
    result = []
    for r in refs:
        a, b = r['start_char'], r['end_char']
        text = task['source'][a:b]
        matches = list(CUES.finditer(text))
        middle = a + (matches[len(matches)//2].start() if matches else len(text)//2)
        for selector, start in [('first', a), ('last', max(a, b-120)),
                                ('salient', max(a, min(middle-40, b-120)))]:
            end = min(b, start+120)
            if any(p['start_char'] == start and p['end_char'] == end for p in result):
                continue
            result.append(_ref(task, start, end, quote=task['source'][start:end],
                               selector=selector, selector_version=POLICY))
            if len(result) == 3:
                return result
    return result


def get_case_overview(prepared, case_id):
    items = [t for t in prepared if t['request']['case_id'] == case_id]
    if not items:
        raise ValueError('unknown_case')
    return {'case_id': case_id, 'source_hash': items[0]['request']['source_hash'],
            'source_char_length': len(items[0]['source']), 'universe_regions': len(items),
            'scope': 'six_workload_regions_not_whole_case_overview',
            'options': list_blocks(prepared, case_id)['items']}


def list_blocks(prepared, case_id, cursor=0, limit=6):
    if type(cursor) is not int or type(limit) is not int or cursor < 0 or not 1 <= limit <= 6:
        raise ValueError('navigation_page_cap')
    tasks = sorted([t for t in prepared if t['request']['case_id'] == case_id],
                   key=lambda t: t['navigation']['ordinal'])
    return {'items': [copy.deepcopy(t['navigation']) for t in tasks[cursor:cursor+limit]],
            'next_cursor': cursor+limit if cursor+limit < len(tasks) else None,
            'catalog_sha256': digest([t['navigation'] for t in tasks]),
            'source_assessed': False}


def find_source(task, obligations, max_chars=1200):
    """One local search over same-case atom addresses, never old predictions.

    Hits are navigation only. Whole atoms preserve the unchanged extraction
    renderer/catalog. Oversized atoms are skipped instead of hidden expansion.
    """
    if not 1 <= max_chars <= 1200:
        raise ValueError('context_character_cap')
    flags = [f for f in obligations if f in FIND_TERMS]
    existing = [(a['start_char'], a['end_char']) for a in task['catalog']['atoms'].values()]
    target = min(r['start_char'] for r in task['request']['source_refs'] if r['role'] == 'target')
    candidates = []
    for atom in task['catalog']['atom_map']['atoms']:
        a, b = atom['span']['start_char'], atom['span']['end_char']
        if any(a < y and x < b for x, y in existing):
            continue
        text = task['source'][a:b].lower()
        score = sum(any(term in text for term in FIND_TERMS[f]) for f in flags)
        if score:
            candidates.append((-score, abs(a-target), a, b))
    hits, chars = [], 0
    for _, _, a, b in sorted(candidates):
        if chars+b-a > max_chars:
            continue
        hits.append(_ref(task, a, b, role='context', target_ids=[],
                         navigation_id='find-'+digest([task['request']['case_id'], a, b])[:20]))
        chars += b-a
        if len(hits) == 3:
            break
    return {'hits': hits, 'chars': chars, 'source_assessed': False,
            'search_policy': 'same_case_whole_atom_terms_distance_v1', 'search_calls': 1}


def expand_context(task, hits):
    if len(hits) > 3 or sum(h['end_char']-h['start_char'] for h in hits) > 1200:
        raise ValueError('context_character_cap')
    expanded = copy.copy(task)
    q = copy.deepcopy(task['request'])
    for h in hits:
        if h['case_id'] != q['case_id'] or h['source_hash'] != q['source_hash'] or h['role'] != 'context':
            raise ValueError('context_identity_mismatch')
        q['source_refs'].append({k: h[k] for k in ('role', 'start_char', 'end_char', 'target_ids')})
    catalog = build_evidence_catalog(q, task['binding'], task['source'])
    old_ids = set(task['catalog']['atoms'])
    added = [a for aid, a in catalog['atoms'].items() if aid not in old_ids]
    if sum(a['end_char']-a['start_char'] for a in added) > 1200:
        raise ValueError('rendered_context_character_cap')
    expanded.update(request=q, catalog=catalog, rendered=runner._render(q, catalog))
    return expanded


def read_region(prepared, navigation_id):
    for task in prepared:
        if task['navigation']['navigation_id'] == navigation_id:
            return task
    raise ValueError('unknown_navigation_id')


def get_reading_state(state):
    return copy.deepcopy({k: state.get(k, []) for k in
                          ('exposure_intervals', 'delivery_intervals', 'assessment_intervals',
                           'unresolved_obligations')})
