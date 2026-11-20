"""Inspect host bindings separately from the compact model-facing view."""
from copy import deepcopy


def canonical_ref(prepared, ref):
    return prepared['manifest'].get('wire_aliases', {}).get(ref, ref)


def wire_ref(prepared, ref):
    return next((key for key, value in prepared['manifest'].get('wire_aliases', {}).items() if value == ref), ref)


def host_payload(prepared):
    payload = deepcopy(prepared['payload'])
    manifest = prepared['manifest']
    payload['m6'] = deepcopy(manifest['dispatch_m6'])
    payload['excerpts'] = deepcopy(manifest['excerpts'])
    payload['current_payload_source_refs'] = [row['ref'] for row in payload['excerpts']]
    query = next((row for row in payload['excerpts'] if row['case_id'] == payload['query_id']), None)
    if query:
        payload['query_source_hash'] = query['source_hash']
    return payload


def survey_results(engine):
    """Exercise actual delivered survey turns for gated fixture engines."""
    if not engine.gate_enabled:
        return
    from pipeline_v2.experiments.context_manager_v2 import query_review
    from pipeline_v2.experiments.context_manager_v2.cli import choose
    while (query := query_review.active(engine.events(), engine.context())) and query['phase'] == 'surveying':
        def action(p):
            controls = p['payload']['m6']['cm_page']['controls']
            if 'next_unseen' in controls or 'next' in controls:
                return choose(p, 'show_context_page', page_ref=controls.get('next_unseen', controls.get('next')))
            return choose(p, 'prioritize_query_results',
                          candidate_refs=list(p['payload']['m6']['query_result_choices']),
                          priority='read_next', reason='The fixture selects the surveyed leads.')
        engine.step(action)


def conclude_query(engine):
    if not engine.gate_enabled:
        return
    from pipeline_v2.experiments.context_manager_v2.cli import choose
    engine.step(lambda p: choose(p, 'conclude_search_query', outcome='partially_resolved',
                                reason='The retrieved candidates have been assessed.',
                                unresolved_reason='The assessment may retain unknown evidence.', remaining_source_need=''))
