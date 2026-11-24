"""Pure, conservative next-page proposal; publication belongs to admission."""
from copy import deepcopy

from pipeline_v2.agent_harness.contracts import fingerprint

VERSION = 'cm4-auto-candidate-navigation-v1'


def propose(context, query, payload, schema, handles, *, blocked=False):
    if (blocked or context.get('mode') != 'results' or context.get('need_id') != query.get('need_id')
            or context.get('candidate_id') is not None or context.get('active_anchor_draft')):
        return None
    local = context.get('passage_session', {})
    if local.get('identity_packet') or context.get('stage') != 'ready':
        return None
    tools = payload.get('available_tools', [])
    if [tool['name'] for tool in tools] != ['show_context_page']:
        return None
    branches = schema.get('anyOf', [])
    if len(branches) != 1 or branches[0]['properties']['action'].get('const') != 'show_context_page':
        return None
    targets = branches[0]['properties']['args']['properties']['page_ref'].get('enum', [])
    if len(targets) != 1:
        return None
    m6 = payload['m6']
    cards = m6.get('cm_page', {}).get('candidates', [])
    if not cards or any(not card.get('review_complete') or card.get('conclusion_status') != 'final'
                        for card in cards):
        return None
    query_id = query['query_id']
    if m6.get('query_review', {}).get('query_id') != query_id:
        return None
    target = targets[0]
    if m6.get('candidate_navigation', {}).get('next_unseen_page') != target:
        return None
    handle = handles.get(target, {})
    offset = handle.get('offset')
    if handle.get('kind') != 'survey_page' or type(offset) is not int or offset <= local.get('survey_offset', 0):
        return None
    pool = fingerprint([query_id, query['candidate_ids'], query['hits']])
    key = fingerprint([query_id, pool, offset])
    visited = context.get('candidate_auto_visited', [])
    if key in visited:
        return None
    new_local = deepcopy(local)
    new_local['survey_offset'] = offset
    return {'passage_session': new_local, 'candidate_auto_visited': [*visited, key],
            'revision': context.get('revision', 0) + 1,
            'candidate_auto_transition': {'version': VERSION, 'query_id': query_id,
                'pool_fingerprint': pool, 'from_offset': local.get('survey_offset', 0),
                'to_offset': offset, 'target': target, 'reason': 'single_unseen_page_after_final_cards'}}
