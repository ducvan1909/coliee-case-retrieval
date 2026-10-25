"""Executed cost counted once, shared controls never treated as paired samples."""
from .build import fingerprint, PairedError
from .preflight import validate_workload
from .review import _run_rows, review_packet, validate_decisions

def compare(workload, run, decisions=None):
    validate_workload(workload)
    if run.get('workload_sha256') != workload['workload_sha256']:
        raise PairedError('comparison run binding mismatch')
    rows = _run_rows(run)
    expected = {r['request_id'] for r in workload['manifest']['requests']}
    if not set(rows).issubset(expected):
        raise PairedError('run contains receipts outside workload')
    cost = {'unique_extraction_receipts': len(rows), 'known_input_tokens': 0, 'known_output_tokens': 0,
            'known_total_tokens': 0, 'unknown_usage_receipts': 0,
            'server_recovered_without_POST': sum(bool(r.get('receipt', {}).get('server_recovered_without_POST')) for r in rows.values()),
            'usage_attribution': 'observed provider usage; not verified new billing'}
    for row in rows.values():
        usage = row.get('receipt', {}).get('usage')
        if isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens', 'total_tokens')):
            for src, dest in (('input_tokens', 'known_input_tokens'), ('output_tokens', 'known_output_tokens'), ('total_tokens', 'known_total_tokens')):
                cost[dest] += usage[src]
        else:
            cost['unknown_usage_receipts'] += 1
    packet, mapping = review_packet(workload, run)
    decisions_by_id = {}
    if decisions is not None:
        validate_decisions(decisions, packet)
        decisions_by_id = {d['blind_id']: d for d in decisions['rows']}
    review_by_request = {m['physical_request_id']: decisions_by_id[m['blind_id']] for m in mapping['rows'] if m['blind_id'] in decisions_by_id}
    pairs = []
    for p in workload['pairs']:
        statuses = {a: rows.get(rid, {}).get('status', 'pending') for a, rid in p['request_ids'].items()}
        reviews = {a: review_by_request.get(rid) for a, rid in p['request_ids'].items()}
        comparison = 'not_assessed'
        if all(reviews.values()):
            if p['shared_identical_input']:
                comparison = 'shared_control_not_independent'
            elif any(d['verdict'] in ('unknown', 'disputed') for d in reviews.values()):
                comparison = 'unknown_or_disputed'
            else:
                score = lambda d: (d['severity'] == 'severe', d['severity'] == 'minor', len(d['errors']), d['verdict'] != 'supported')
                g, s = score(reviews['G']), score(reviews['S'])
                comparison = 'S_better' if s < g else 'G_better' if g < s else 'same_review_error_summary'
        pairs.append({'pair_id': p['pair_id'], 'case_id': p['case_id'], 'effective_delta': p['effective_delta'],
                      'known_gap': p['known_gap'], 'shared_identical_input': p['shared_identical_input'],
                      'execution_status': statuses, 'semantic_comparison': comparison, 'reviews': reviews})
    fully_reviewed = bool(decisions_by_id) and len(decisions_by_id) == len(packet['rows'])
    return {'artifact_type': 'AUContextPairedComparison', 'workload_sha256': workload['workload_sha256'],
            'run_sha256': fingerprint(run), 'execution_status': run.get('status'),
            'semantic_review_status': 'complete_model_assisted' if fully_reviewed else 'pending_or_partial',
            'semantic_gold': False, 'retrieval_quality_claim': False, 'evaluation_split': workload['evaluation_split'],
            'executed_extraction_cost': cost, 'overhead_ledger': run.get('execution_ledger', run.get('runtime_ledger', {})),
            'review_usage': 'unavailable_unless_separately_supplied', 'pairs': pairs,
            'changed_pair_count': sum(p['effective_delta'] for p in pairs),
            'shared_control_count': sum(p['shared_identical_input'] for p in pairs),
            'unknown_or_failed_requests': sorted(rid for rid in expected if rows.get(rid, {}).get('status') != 'protocol_verified')}
