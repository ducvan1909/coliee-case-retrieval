"""Deterministic lane round robin; budget exhaustion is not a negative."""
from collections import deque
import math

ARMS = ('multi_queue', 'source_order', 'cue_control')


def schedule(inventory, arm='round_robin', budget=None, bytes_per_token=4):
    arm = {'round_robin': 'multi_queue', 'old_cue': 'cue_control'}.get(arm, arm)
    if arm not in ARMS:
        raise ValueError('unknown arm: ' + arm)
    if bytes_per_token <= 0 or (budget is not None and budget < 0):
        raise ValueError('invalid budget or token divisor')
    rows = inventory['regions'] if isinstance(inventory, dict) else inventory
    source = sorted(rows, key=lambda r: (r['case_id'], r['target']['start_char']))
    if arm == 'source_order':
        ordered = source
    elif arm == 'cue_control':
        ordered = sorted(source, key=lambda r: (-sum(r['features']['counts'][k] for k in ('citation', 'standard', 'duty', 'reporting')), r['case_id'], r['target']['start_char']))
    else:
        lanes = []
        for lane in ('doctrine', 'application', 'reported_authority', 'context_need'):
            lanes.append(deque(sorted((r for r in source if r['features']['lane_scores'][lane]),
                                     key=lambda r: (-r['features']['lane_scores'][lane], r['case_id'], r['target']['start_char']))))
        # All blocks remain eligible. Alternate position quintiles and cases.
        strata = {}
        for r in source:
            strata.setdefault((r['position_stratum'], r['case_id']), deque()).append(r)
        discovery = []
        while any(strata.values()):
            for key in sorted(strata):
                if strata[key]:
                    discovery.append(strata[key].popleft())
        lanes.append(deque(discovery))
        ordered, seen = [], set()
        while any(lanes):
            for lane in lanes:
                while lane and lane[0]['region_id'] in seen:
                    lane.popleft()
                if lane:
                    row = lane.popleft()
                    ordered.append(row); seen.add(row['region_id'])
    read, residual, seen, cumulative = [], [], set(), 0
    for row in ordered:
        span = row['target']
        key = (row['case_id'], row['source_hash'], span['start_char'], span['end_char'])
        if key in seen:
            continue
        seen.add(key)
        cost = math.ceil(row['serialized_utf8_bytes'] / bytes_per_token)
        if budget is not None and cumulative + cost > budget:
            residual.append({'region_id': row['region_id'], 'status': 'not_assessed', 'reason': 'above_remaining_budget'})
            continue
        cumulative += cost
        read.append({'region_id': row['region_id'], 'read_order': len(read), 'estimated_tokens': cost,
                     'cumulative_estimated_tokens': cumulative})
    return {'arm': arm, 'budget': budget, 'bytes_per_token': bytes_per_token, 'reads': read,
            'unknown_residual': residual, 'estimated_tokens': cumulative, 'semantic_stopping': False}
