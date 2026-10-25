"""Frozen source-only routing policy; no semantic inference."""
from collections import Counter
from copy import deepcopy
import math
import re

from ..region_priority_offline import core as old
from ..region_priority_offline.features import PATTERNS
from ..region_priority_variants import context

QUALIFICATION_DEPENDENCY_RE = r'\b(subject\s+(?:only\s+)?to|provided\s+that|unless|except(?:ion)?|conditional\s+(?:on|upon))\b'
POLICY = {
    'version': 'selective-context-v1',
    'qualification_dependency_regex': QUALIFICATION_DEPENDENCY_RE,
    'seed': 'TARGET and baseline context; cue in TARGET scans one immediate block each side in same case',
    'ownership': 'unchanged context._ownership; unique opening numbered_paragraph marker',
    'admission': 'baseline first; whole missing bridge plus required block as atomic bundle; union minus TARGET',
    'max_context_chars': 6000, 'max_context_intervals': 12, 'max_reference_hops': 1,
    'recursive_fetched_reference': False, 'audit': 'host only',
    'unchanged_packet': 'byte-identical baseline when no new source span is admitted',
    'quality': 'lexical dependency delivery only; development/calibration, not heldout',
}
CONTEXT_POLICY = POLICY


def _whole(span, row):
    return old._overlap([span], [row['target']] + row['packet']['context']) == span['end_char'] - span['start_char']


def expand_context(inventory):
    """Copy inventory, preserve packets on no-op. No KOS, recursive scan or calls."""
    result = deepcopy(inventory)
    cases, markers = {}, {}
    for row in inventory['regions']:
        cases.setdefault(row['case_id'], []).append(row)
        m = re.match(r'\s*\[(\d+)\]', row['packet']['target']['text'])
        if row.get('block_type') == 'numbered_paragraph' and m:
            markers.setdefault((row['case_id'], m[1]), []).append(row)
    for rows in cases.values():
        rows.sort(key=lambda r: (r['target']['start_char'], r['target']['end_char']))
    for row in result['regions']:
        cid, target = row['case_id'], row['target']
        text, original = inventory['sources'][cid], row['packet']['context']
        cue = bool(re.search(QUALIFICATION_DEPENDENCY_RE, row['packet']['target']['text'], re.I))
        seeds = [(row['packet']['target'], None)] + [(c, None) for c in original]
        scanned = []
        if cue:
            rows = cases[cid]
            idx = next(i for i, r in enumerate(rows) if r['region_id'] == row['region_id'])
            for i in (idx - 1, idx + 1):
                if 0 <= i < len(rows):
                    neighbor = rows[i]
                    seeds.append((neighbor['packet']['target'], neighbor))
                    scanned.append(neighbor['region_id'])
        refs, additions, caps, candidates = [], [], [], []
        seen = set()
        for seed, bridge in seeds:
            for match in re.finditer(PATTERNS['paragraph_reference'], seed['text'], re.I):
                offset = seed['start_char'] + match.start()
                key = (offset, bridge['region_id'] if bridge else None)
                if key in seen:
                    continue
                seen.add(key)
                owned, reason = context._ownership(seed['text'], match)
                hits = markers.get((cid, match[1]), [])
                if owned and len(hits) != 1:
                    owned, reason = False, 'missing_or_ambiguous_local_marker'
                ref = {'reference': match.group(), 'paragraph_number': match[1],
                       'start_char': offset, 'end_char': seed['start_char'] + match.end(),
                       'seed_role': 'BRIDGE_SCAN' if bridge else seed['role'], 'reference_hop': 1,
                       'ownership_confirmed_local': owned, 'ownership_reason': reason,
                       'dependency_status': 'hint', 'resolution': 'unresolved',
                       'matching_block_ids': [h['region_id'] for h in hits] if owned else []}
                if owned:
                    hit = hits[0]
                    ref.update(required_span=deepcopy(hit['target']),
                               bridge_span=deepcopy(bridge['target']) if bridge else None,
                               bridge_block_id=bridge['region_id'] if bridge else None)
                    bundle = []
                    for r, why in ((bridge, 'qualification_reference_bridge'), (hit, 'explicit_owned_reference_hint')):
                        if r and not _whole(r['target'], row):
                            bundle.append({**r['target'], 'block_ids': [r['region_id']],
                                           'atom_ids': [], 'reasons': [why]})
                    candidates.append((ref, bundle))
                refs.append(ref)
        # Process source seed order; baseline is never removed. Each bridge and
        # referenced block is admitted together or the entire addition is unknown.
        for ref, bundle in candidates:
            if not bundle:
                ref['admission'] = 'already_delivered'
                continue
            current = context._union(text, original + additions, target)
            missing = [b for b in bundle if old._overlap([b], [target] + current) < b['end_char'] - b['start_char']]
            if not missing:
                ref['admission'] = 'already_delivered'
                continue
            proposed = context._union(text, original + additions + missing, target)
            if old._length(proposed) > POLICY['max_context_chars'] or len(proposed) > POLICY['max_context_intervals']:
                cap = {'status': 'unknown', 'reason': 'whole_context_cap_no_truncation',
                       'reference_start_char': ref['start_char'], 'bundle': missing}
                caps.append(cap)
                ref['admission'] = 'capped_unknown'
            else:
                additions.extend(missing)
                ref['admission'] = 'added_whole_bundle'
        if additions:
            row['packet']['context'] = context._union(text, original + additions, target)
            rendered = old._canonical(row['packet'])
            size = len(rendered.encode('utf-8'))
            row.update(serialized_payload=rendered, serialized_utf8_bytes=size,
                       serialized_chars=len(rendered),
                       context_utf8_bytes=sum(len(c['text'].encode('utf-8')) for c in row['packet']['context']),
                       estimated_tokens={str(d): math.ceil(size / d) for d in (3, 4, 5)})
        for ref in refs:
            if ref['ownership_confirmed_local']:
                required = _whole(ref['required_span'], row)
                bridge = not ref['bridge_span'] or _whole(ref['bridge_span'], row)
                ref.update(resolution='resolved' if required and bridge else 'open',
                           required_whole_delivery=required, bridge_whole_delivery=bridge,
                           delivery='whole_raw_block' if required and bridge else 'unknown_context_cap')
        row['context_audit'] = {
            'host_only': True, 'qualification_dependency_cue': cue,
            'neighbor_block_ids_scanned': scanned, 'input_reference_hints': refs,
            'context_cap_residual': caps, 'reference_hops': 1,
            'trigger_candidate': cue or any(r['ownership_confirmed_local'] for r in refs),
            'owned_reference_candidate_count': sum(r['ownership_confirmed_local'] for r in refs),
            'opened_additional_context': bool(additions), 'packet_changed': bool(additions),
            'semantic_dependency': 'not_confirmed', 'acceptance_scope': 'TARGET only',
        }
    return result


def request_cost(baseline_row, expanded_row, divisor=4, mode='preassembled'):
    """Full serialized inputs; two-step adds separately rounded full request."""
    if divisor <= 0 or mode not in ('preassembled', 'two_step'):
        raise ValueError('invalid cost mode or divisor')
    changed = baseline_row['serialized_payload'] != expanded_row['serialized_payload']
    first, expanded = baseline_row['serialized_utf8_bytes'], expanded_row['serialized_utf8_bytes']
    two = mode == 'two_step' and changed
    size = first + expanded if two else expanded
    tokens = math.ceil(first / divisor) + math.ceil(expanded / divisor) if two else math.ceil(expanded / divisor)
    return {'serialized_bytes': size, 'estimated_tokens': tokens,
            'hypothetical_requests': 2 if two else 1, 'hypothetical_second_requests': int(two),
            'packet_changed': changed, 'mode': mode}


def source_audit(inventory):
    rows = inventory['regions']
    counts = Counter()
    for row in rows:
        a = row['context_audit']
        for k in ('trigger_candidate', 'qualification_dependency_cue', 'opened_additional_context', 'packet_changed'):
            counts[k] += bool(a[k])
        counts['owned_reference_candidates'] += a['owned_reference_candidate_count']
        counts['cap_bundles'] += len(a['context_cap_residual'])
        for r in a['input_reference_hints']:
            counts['reference_' + r['resolution']] += 1
    return {'counts': dict(counts), 'rows': [{'region_id': r['region_id'], **r['context_audit']} for r in rows],
            'semantic_dependency_quality': 'not_assessed'}
