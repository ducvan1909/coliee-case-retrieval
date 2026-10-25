"""Frozen global tiers, followed by the unchanged saturated cue-control tie."""
import math

ORDER_POLICY = {
    'version': 'global-tier-v1',
    'tier3': 'review>0 OR duty AND (rights OR standard OR qualification) OR fact AND consequence AND rationale',
    'tier2': 'doctrine>=2 OR application>=3 OR reported_authority>=2',
    'tier1': 'any remaining nonzero existing lane',
    'tier0': 'otherwise',
    'tie': 'descending saturated citation+standard+duty+reporting; case_id/start_char/end_char',
    'budget_selection': 'scan frozen order; defer above-remaining-budget target as not_assessed; no reorder',
}


def rank_reason(row):
    c, lanes = row['features']['counts'], row['features']['lane_scores']
    reasons = []
    if c['review']:
        reasons.append('review')
    if c['duty'] and any(c[k] for k in ('rights', 'standard', 'qualification')):
        reasons.append('duty_with_rights_standard_or_qualification')
    if c['fact'] and c['consequence'] and c['rationale']:
        reasons.append('fact_consequence_rationale')
    if reasons:
        tier = 3
    else:
        reasons = [k for k, threshold in (('doctrine', 2), ('application', 3), ('reported_authority', 2))
                   if lanes[k] >= threshold]
        tier = 2 if reasons else 1 if any(lanes.values()) else 0
        if not reasons:
            reasons = [k for k, value in lanes.items() if value] or ['no_lane_cue']
    return {'tier': tier, 'reasons': reasons,
            'cue_control_score': sum(c[k] for k in ('citation', 'standard', 'duty', 'reporting')),
            'tie': [row['case_id'], row['target']['start_char'], row['target']['end_char']]}


def priority_order(inventory):
    rows = inventory['regions'] if isinstance(inventory, dict) else inventory
    def key(r):
        reason = rank_reason(r)
        return (-reason['tier'], -reason['cue_control_score'], *reason['tie'])
    return [r['region_id'] for r in sorted(rows, key=key)]


def schedule_order(inventory, ordered_ids, *, budget=None, bytes_per_token=4, arm='global_priority'):
    if bytes_per_token <= 0 or (budget is not None and budget < 0):
        raise ValueError('invalid budget or divisor')
    rows = inventory['regions'] if isinstance(inventory, dict) else inventory
    by_id = {r['region_id']: r for r in rows}
    if len(by_id) != len(rows) or len(ordered_ids) != len(rows) or set(ordered_ids) != set(by_id):
        raise ValueError('order must contain each inventory ID exactly once')
    reads, residual, cumulative = [], [], 0
    for rank, rid in enumerate(ordered_ids):
        cost = math.ceil(by_id[rid]['serialized_utf8_bytes'] / bytes_per_token)
        if budget is not None and cumulative + cost > budget:
            residual.append({'region_id': rid, 'full_order_rank': rank,
                             'status': 'not_assessed', 'reason': 'above_remaining_budget'})
            continue
        cumulative += cost
        reads.append({'region_id': rid, 'full_order_rank': rank, 'read_order': len(reads),
                      'estimated_tokens': cost, 'cumulative_estimated_tokens': cumulative})
    return {'arm': arm, 'budget': budget, 'bytes_per_token': bytes_per_token,
            'reads': reads, 'unknown_residual': residual, 'estimated_tokens': cumulative,
            'semantic_stopping': False}
