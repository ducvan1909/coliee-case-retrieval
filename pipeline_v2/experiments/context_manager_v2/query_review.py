"""Durable per-search review derived from receipts, never from compile previews."""
from copy import deepcopy
from pipeline_v2.agent_harness.contracts import fingerprint, HarnessError
from . import passage_review

VERSION = 'cm4-query-review-v1'


def queries(events, context):
    runtime = getattr(events, 'runtime', None)
    if runtime is not None:
        result = deepcopy(runtime.queries)
    else:
        starts, requests, result = {}, {}, {}
        for event in events:
            kind = event['kind']
            if kind == 'action_started':
                starts[event['action_id']] = event['action']
            elif kind == 'request_admitted':
                requests[event['request_id']] = event
            elif kind == 'action_result' and event.get('status') == 'success':
                action = starts.get(event.get('action_id'), {})
                observation = (event.get('result') or {}).get('observation', {})
                if action.get('action') == 'search_corpus' and 'hits' in observation:
                    need = action['args'].get('_m6_need', {})
                    if not need:
                        continue
                    key = event['action_id']
                    hits = list(dict.fromkeys(row['case_id'] for row in observation['hits']))
                    result[key] = {'query_id': key, 'need_id': need['source_need_id'],
                        'issue': action['args']['text'], 'candidate_ids': hits,
                        'action_id': key, 'source_need': deepcopy(need),
                        'retrieval_request_id': observation.get('request_id'),
                        'query_sha256': observation.get('query_sha256'),
                        'search_reuse': deepcopy(observation.get('search_reuse')),
                        'hits': deepcopy(observation['hits']), 'survey_exposed': [], 'raw_exposed': [],
                        'passage_review': bool(observation.get('cm4_passage_review'))}
            elif kind == 'request_result' and event.get('received_response'):
                admission = requests.get(event['request_id'], {})
                key = admission.get('cm_search_query_id')
                if key in result:
                    query = result[key]
                    query['survey_exposed'] = list(dict.fromkeys([*query['survey_exposed'],
                        *(case for case in admission.get('cm_survey_candidates', []) if case in query['candidate_ids'])]))
                    query['raw_exposed'] = list(dict.fromkeys([*query['raw_exposed'],
                        *(row['case_id'] for row in admission.get('excerpts', [])
                          if row['ref'] in admission.get('current_payload_source_refs', [])
                          and row['case_id'] in query['candidate_ids'] and row['text'].strip())]))
    for key, query in result.items():
        query['priorities'] = deepcopy(context.get('query_priorities', {}).get(key, {}))
        query['conclusion'] = deepcopy(context.get('query_conclusions', {}).get(key))
        query['phase'] = ('concluded' if query['conclusion'] else
                          'reviewing' if set(query['candidate_ids']) <= set(query['survey_exposed']) else 'surveying')
        if query['passage_review']:
            # Grouped passage reading has no mandatory survey phase. Cards and
            # raw exposure still come only from received model requests.
            query['phase'] = 'concluded' if query['conclusion'] else 'reviewing'
            query['completed_candidates'] = [case for case in query['candidate_ids']
                                             if passage_review.case_done(context, query, case)]
            query['candidate_conclusions'] = deepcopy(passage_review.conclusions(context, query))
    return result


def active(events, context):
    return next((row for row in queries(events, context).values() if not row['conclusion']), None)


def unresolved_candidates(query, state):
    if query.get('passage_review'):
        completed = set(query['completed_candidates'])
        return [case for case in query['candidate_ids'] if case not in completed]
    result = []
    for case in query['candidate_ids']:
        pair = query['need_id'], case
        assessment = state.assessments.get(state.active_assessments.get(pair), {})
        if (not assessment or pair in state.pending_assessments
                or assessment.get('case_relation') == 'unknown'
                or assessment.get('passage_location') == 'unresolved'
                or assessment.get('status') == 'pending_evidence'):
            result.append(case)
    return result


def pending_read_next(query):
    completed = set(query['completed_candidates'] if query.get('passage_review') else query['raw_exposed'])
    return [case for case in query['candidate_ids']
            if query['priorities'].get(case, {}).get('priority') == 'read_next' and case not in completed]


def progress(query, state):
    ids, need = query['candidate_ids'], query['need_id']
    assessed = {case: state.active_assessments[(need, case)] for case in ids
                if (need, case) in state.active_assessments and (need, case) not in state.pending_assessments}
    relations = {}
    for assessment_id in assessed.values():
        relation = state.assessments.get(assessment_id, {}).get('case_relation', 'unknown')
        relations[relation] = relations.get(relation, 0) + 1
    result = {'query_id': query['query_id'], 'phase': query['phase'], 'issue': query['issue'],
        'retrieved': len(ids), 'survey_exposed': len(query['survey_exposed']),
        'not_exposed': len(set(ids) - set(query['survey_exposed'])),
        'selected_for_read': sum(row['priority'] == 'read_next' for row in query['priorities'].values()),
        'pending_read_next': len(pending_read_next(query)),
        'pending_read_next_examples': pending_read_next(query)[:5],
        'raw_exposed': len(query['raw_exposed']), 'assessed': len(assessed), 'assessed_by_relation': relations,
        'not_read': len(set(ids) - set(query['raw_exposed'])), 'unresolved': len(unresolved_candidates(query, state)),
        'conclusion': query['conclusion']}
    if query.get('passage_review'):
        final = query['candidate_conclusions']
        selected = {case for case, row in final.items() if row['decision'] == 'select'}
        negative = {case for case, row in final.items() if row['decision'] == 'not_select'}
        final_relations = {}
        for case, row in final.items():
            assessment = state.assessments.get(fingerprint([row['action_id'], need, case]))
            if assessment is not None:
                relation = assessment['case_relation']
                final_relations[relation] = final_relations.get(relation, 0) + 1
        result.update(completed_candidates=len(final), passage_hits=len(query['hits']),
                      assessed=len(final),
                      assessed_by_relation=final_relations,
                      conclusions_by_decision={'select': len(selected), 'not_select': len(negative)},
                      candidates_final=len(final), candidates_pending=len(set(ids)-set(final)),
                      selected_candidates=len(selected), final_not_select_candidates=len(negative),
                      candidate_states={case: {'status': 'final' if case in final else 'pending',
                                              'decision': final.get(case, {}).get('decision', 'not_select')}
                                        for case in ids})
    return result


def conclude(query, state, args):
    if not args.get('reason', '').strip():
        raise HarnessError('Query conclusion needs a nonblank reason')
    if query['phase'] != 'reviewing':
        raise HarnessError('Survey all results before concluding this query')
    if pending_read_next(query):
        raise HarnessError('Read or explicitly downgrade outstanding read_next candidates before concluding')
    if args['outcome'] == 'no_supported_source_found' and query['candidate_ids'] and not query['raw_exposed']:
        raise HarnessError('Use a partial conclusion when no candidate raw has been received')
    if args['outcome'] not in ('resolved', 'partially_resolved', 'no_supported_source_found'):
        raise HarnessError('Invalid query outcome')
    if args['outcome'] == 'no_supported_source_found' and any(
            state.assessments.get(state.active_assessments.get((query['need_id'], case)), {}).get('case_relation') == 'supported'
            and (query['need_id'], case) not in state.pending_assessments
            for case in query['candidate_ids']):
        raise HarnessError('Supported assessments contradict a no-supported-source conclusion')
    unresolved = unresolved_candidates(query, state)
    if unresolved and not args['unresolved_reason'].strip():
        raise HarnessError('A query with unresolved candidates needs an explicit disposition reason')
    if args['outcome'] == 'resolved' and unresolved:
        raise HarnessError('Use partially_resolved or no_supported_source_found while candidates remain unresolved')
    return {**deepcopy(args), 'candidate_ids': list(query['candidate_ids']),
        'unresolved_candidate_ids': unresolved,
        'not_read_candidate_ids': [case for case in query['candidate_ids'] if case not in query['raw_exposed']],
        'counters': progress(query, state)}


def first_unseen_offset(query, extra_seen=()):
    seen = set(query['survey_exposed']) | set(extra_seen)
    return next((i for i, case in enumerate(query['candidate_ids']) if case not in seen), None)


def page_status(query, cards, offset):
    seen = set(query['survey_exposed'])
    ids = [card['case_id'] for card in cards]
    return {'offset': offset, 'first_result': offset + 1 if ids else None,
            'last_result': offset + len(ids) if ids else None, 'total_results': len(query['candidate_ids']),
            'shown_cards_received_before': sum(case in seen for case in ids),
            'shown_cards_new_on_reply': sum(case not in seen for case in ids),
            'first_unseen_offset': first_unseen_offset(query),
            'unseen_after_current_page': len(set(query['candidate_ids']) - seen - set(ids))}
