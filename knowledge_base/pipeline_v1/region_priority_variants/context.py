"""Bounded input-owned reference hints. No semantic dependency or acceptance."""
from copy import deepcopy
import math
import re
from ..region_priority_offline import core as old
from ..region_priority_offline.features import PATTERNS

CONTEXT_POLICY = {
    'version': 'owned-reference-context-v1', 'max_context_chars': 6000,
    'max_context_intervals': 12, 'max_reference_hops': 1,
    'neighbor_expansion': 'complete containing blocks of baseline nearby atoms when qualification/reporting/open_quote',
    'reference_seed': 'target plus supplied baseline context and containing neighbor blocks; never fetched reference blocks',
    'ownership': 'unique same-case marker AND of/in these reasons; reject quotation/reporting windows unless unquoted explicit current narration',
    'admission': 'whole explicit owned blocks before complete neighbors before baseline hints; union within packet minus target; no truncation',
    'oversize': 'whole dependency unknown; no partial replacement',
    'semantics': 'local context hint only; outside TARGET cannot establish acceptance',
    'renderer': 'unchanged baseline canonical JSON and scaffold; host audit not transmitted',
}


def _union(text, candidates, target):
    pieces = []
    for c in candidates:
        a, b = c['start_char'], c['end_char']
        for lo, hi in ((a, min(b, target['start_char'])), (max(a, target['end_char']), b)):
            if lo < hi:
                pieces.append({'start_char': lo, 'end_char': hi,
                               'reasons': c.get('reasons', [c.get('reason', 'raw_context_hint')]),
                               'atom_ids': c.get('atom_ids', []),
                               'block_ids': c.get('block_ids', [])})
    merged = []
    for p in sorted(pieces, key=lambda p: (p['start_char'], p['end_char'])):
        if merged and p['start_char'] <= merged[-1]['end_char']:
            merged[-1]['end_char'] = max(p['end_char'], merged[-1]['end_char'])
            for k in ('reasons', 'atom_ids', 'block_ids'):
                merged[-1][k] = sorted(set(merged[-1][k] + p[k]))
        else:
            merged.append(deepcopy(p))
    return [old._span_packet(text, {**target, **p}, dependency_status='hint', role='CONTEXT') for p in merged]


def _ownership(text, match):
    """Conservative lexical ownership, never inferred from matching marker alone.

    Quote state and reporting are evaluated over the supplied segment, not a
    global graph. Explicit current narration can bypass reporting *outside*
    its sentence, but never quotation state or reporting in that sentence.
    """
    suffix = text[match.end():]
    if not re.match(r'\s+(?:of|in)\s+these\s+reasons\b', suffix, re.I):
        return False, 'unresolved_ownership'
    before = text[:match.start()]
    # A segment may start mid-quote; any quotation in the reference sentence
    # is conservatively unresolved, including balanced external quotations.
    sentence_start = max(before.rfind('\n'), before.rfind('. '), before.rfind('! '), before.rfind('? ')) + 1
    sentence_end = re.search(r'[.!?](?:\s|$)|\n', text[match.end():])
    end = match.end() + sentence_end.end() if sentence_end else len(text)
    sentence = text[sentence_start:end]
    quoted = ('"' in sentence or '“' in sentence or '”' in sentence
              or before.count('"') % 2 or before.count('“') > before.count('”')
              or bool(re.search(r"(?:^|\s)'[^\n]*paragraph[^\n]*'", sentence, re.I)))
    if quoted:
        return False, 'unresolved_external_or_quoted_ownership'
    # Ownership guarding is deliberately broader than the frozen ranking
    # features: present-tense reporting and parenthesized citation years are
    # external scope signals, not new scheduler features.
    reporting_pattern = PATTERNS['reporting'] + r'|\b(?:says|states|observes|writes|holds|reports|cites|explains)\b'
    reporting = re.search(reporting_pattern, sentence, re.I)
    external = re.search(r'\b(?:other (?:decision|reasons|case)|that (?:decision|case)|his reasons|her reasons|their reasons)\b', sentence, re.I)
    narration = re.search(r'\b(?:set out earlier|as (?:I|we) (?:noted|stated|explained)|(?:I|we) (?:set out|discussed)|earlier in|above in|below in)\b', sentence, re.I)
    if external or reporting:
        return False, 'unresolved_reported_or_external_ownership'
    if not narration and (re.search(reporting_pattern, text, re.I)
                          or re.search(PATTERNS['citation'], sentence, re.I)
                          or re.search(r'\(\d{4}\)', sentence)):
        return False, 'unresolved_reporting_window'
    return True, 'explicit_current_narration' if narration else 'explicit_local_ownership_no_external_cue'


def expand_context(inventory):
    """Return a copy; target/features/order never mutated. One reference hop."""
    result = deepcopy(inventory)
    source_rows = inventory['regions']
    by_case, markers = {}, {}
    atoms = {c['case_id']: {a['atom_id']: a for a in c['atom_span_inventory']} for c in inventory['cases']}
    for row in source_rows:
        by_case.setdefault(row['case_id'], {})[row['region_id']] = row
        # Only source paragraph blocks' opening marker is an address; citation
        # years or bracketed numbers occurring inside their body are not.
        m = re.match(r'\s*\[(\d+)\]', row['packet']['target']['text'])
        if m and row.get('block_type') == 'numbered_paragraph':
            markers.setdefault((row['case_id'], m[1]), []).append(row)
    for row in result['regions']:
        cid, target = row['case_id'], row['target']
        text = inventory['sources'][cid]
        original = row['packet']['context']
        candidates = [deepcopy(c) for c in original]
        f = row['features']
        expand = f['open_quote'] or f['counts']['qualification'] or f['counts']['reporting']
        neighbor_ids = set()
        if expand:
            for ctx in original:
                if 'adjacent_atom' in ctx.get('reasons', []):
                    for aid in ctx.get('atom_ids', []):
                        neighbor_ids.add(atoms[cid][aid]['parent_block_id'])
        neighbors = [{**by_case[cid][bid]['target'], 'block_ids': [bid], 'atom_ids': [],
                      'reasons': ['complete_neighbor_block_hint']} for bid in sorted(neighbor_ids)
                     if bid != row['region_id']]
        # Scan seed once. Fetched dependencies are never used as scan seeds.
        seeds = _union(text, candidates + neighbors, target)
        seeds = [row['packet']['target']] + seeds
        refs, deps, seen = [], [], set()
        for seed in seeds:
            for m in re.finditer(PATTERNS['paragraph_reference'], seed['text'], re.I):
                offset = seed['start_char'] + m.start()
                if offset in seen:
                    continue
                seen.add(offset)
                owned, reason = _ownership(seed['text'], m)
                hits = markers.get((cid, m[1]), [])
                if owned and len(hits) != 1:
                    owned, reason = False, 'missing_or_ambiguous_local_marker'
                ref = {'reference': m.group(), 'paragraph_number': m[1],
                       'start_char': offset, 'end_char': seed['start_char'] + m.end(),
                       'seed_role': seed['role'], 'reference_hop': 1,
                       'ownership_confirmed_local': owned, 'ownership_reason': reason,
                       'dependency_status': 'hint', 'resolution': 'open' if owned else 'unresolved',
                       'matching_block_ids': [r['region_id'] for r in hits] if owned else []}
                if owned:
                    hit = hits[0]
                    ref['required_span'] = hit['target']
                    if hit['region_id'] != row['region_id']:
                        deps.append({**hit['target'], 'block_ids': [hit['region_id']],
                                     'atom_ids': [], 'reasons': ['explicit_owned_reference_hint']})
                refs.append(ref)
        accepted, capped = [], []
        distance = lambda c: (min(abs(c['end_char'] - target['start_char']), abs(c['start_char'] - target['end_char'])), c['start_char'], c['end_char'])
        # Whole-block dependency admission precedes generic neighbors.
        for kind, group in [('explicit_owned_reference', deps), ('neighbor', neighbors), ('baseline', candidates)]:
            for c in sorted(group, key=distance):
                proposed = _union(text, accepted + [c], target)
                if sum(p['end_char'] - p['start_char'] for p in proposed) > 6000 or len(proposed) > 12:
                    capped.append({'start_char': c['start_char'], 'end_char': c['end_char'],
                                   'block_ids': c.get('block_ids', []), 'kind': kind,
                                   'status': 'unknown', 'reason': 'whole_context_cap_no_truncation',
                                   'dependency_status': 'hint'})
                else:
                    accepted.append(c)
        contexts = _union(text, accepted, target)
        for ref in refs:
            if ref['ownership_confirmed_local']:
                span = ref['required_span']
                ref['resolution'] = ('resolved' if old._overlap([span], [target] + contexts) == span['end_char'] - span['start_char'] else 'open')
                ref['delivery'] = 'whole_raw_block' if ref['resolution'] == 'resolved' else 'unknown_context_cap'
        row['context_obligations'] = refs + capped + [{'status': 'unknown', 'dependency_status': 'hint',
                                                     'reason': 'lexical_hints_do_not_prove_complete_legal_dependency'}]
        row['context_audit'] = {'input_reference_hints': refs, 'context_cap_residual': capped,
                                'neighbor_block_ids': sorted(neighbor_ids), 'reference_hops': 1,
                                'semantic_dependency': 'not_confirmed', 'acceptance_scope': 'TARGET only',
                                'host_only': True}
        row['packet']['context'] = contexts
        rendered = old._canonical(row['packet'])
        row.update(serialized_payload=rendered, serialized_utf8_bytes=len(rendered.encode('utf-8')),
                   serialized_chars=len(rendered), context_utf8_bytes=sum(len(c['text'].encode('utf-8')) for c in contexts),
                   estimated_tokens={str(d): math.ceil(len(rendered.encode('utf-8')) / d) for d in (3, 4, 5)})
    return result
