"""Issue CM4 open choices for exact, need-scoped retrieval leads."""
from copy import deepcopy
from hashlib import sha256

from pipeline_v2.agent_harness import SourceExcerpt, ToolResult
from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from pipeline_v2.agent_harness.evidence import SourceDrift, excerpt, normalize_result


def _opened_leads(events):
    actions = {event['action_id']: event['action'] for event in events if event['kind'] == 'action_started'}
    for outcome in reversed(events):
        if outcome['kind'] != 'action_result' or outcome['status'] != 'success':
            continue
        action = actions[outcome['action_id']]
        if action['action'] != 'open_source' or 'm6_candidate' not in action['args']:
            continue
        args = action['args']
        candidate = args['m6_candidate']
        observation = (outcome.get('result') or {}).get('observation', {})
        lead = args.get('cm4_retrieved_lead')
        if not lead and observation.get('route') == 'open_observed_lead':
            lead = candidate.get('open_ref')
        if not lead and observation.get('route') == 'within_case_then_open':
            hits = observation.get('local_search', {}).get('hits', [])
            lead = next((hit['open_ref'] for hit in hits if hit.get('open_ref')), None)
        if lead:
            need = args.get('cm4_need_id') or outcome.get('cm_context', {}).get('need_id')
            yield need, candidate['case_id'], lead, outcome


def opened_lead_keys(events):
    return {fingerprint([need, case, lead]) for need, case, lead, _ in _opened_leads(events)}


def retrieved_passages(opened, candidates, leading_hits, need_id):
    choices = {}
    for ref, candidate in candidates.items():
        case = candidate['case_id']
        lead = leading_hits.get(case)
        if not lead or not candidate['needs'] or candidate.get('read_status'):
            continue
        binding = {'need_id': need_id, 'candidate_id': case, 'open_ref': lead['open_ref']}
        key = fingerprint([need_id, case, lead['open_ref']])
        if key not in opened:
            description = {'candidate_ref': ref, 'case_id': case}
            if lead.get('span_bytes'):
                description['span_bytes'] = lead['span_bytes']
            choices[key] = {'description': description, 'binding': binding}
    return choices


def retrieved_action(m6, lead_ref):
    binding = m6['retrieved_passages'][lead_ref]['binding']
    lead = deepcopy(binding['open_ref'])
    return {'action': 'open_source', 'args': {
        'm6_candidate': {'case_id': binding['candidate_id'], 'open_ref': lead},
        'cm4_need_id': binding['need_id'], 'cm4_retrieved_lead': lead,
    }}


def focused_action(action, m6):
    args = action['args']
    # Deliberately exclude presentation-only fields from the operation fingerprint.
    return {'action': 'open_source', 'args': {
        'm6_candidate': {'case_id': args['m6_candidate']['case_id']},
        'focus': ' '.join(args['focus'].split()), 'cm4_need_id': m6['cm_context']['need_id'],
    }}


def focused_read_key(action):
    args = action['args']
    candidate = args.get('m6_candidate')
    if action['action'] != 'open_source' or 'focus' not in args or not candidate:
        return None
    return args.get('cm4_need_id'), candidate['case_id'], ' '.join(args['focus'].split())


def _covered(span, records):
    position, end = span
    for left, right in sorted(tuple(row['span_bytes']) for row in records):
        if left > position or position >= end:
            break
        position = max(position, right)
    return position >= end


def next_unread_expansion(read, state, binding, cache):
    """Find the first reader page that adds text to the run's source catalog."""
    seen = set()
    while binding:
        key = fingerprint(binding)
        if key in seen:
            return None
        seen.add(key)
        if key not in cache:
            page = read(binding)
            cache[key] = (page, any(row['text'].strip()
                                   for row in normalize_result(page, state)['excerpts']))
        page, has_new_raw = cache[key]
        if has_new_raw:
            return page
        binding = page.observation.get('continuation')
    return None


def execute_candidate_header(harness, state, binding):
    """Read a registered candidate's exact bounded prefix without a search."""
    case, digest = binding['case_id'], binding['source_hash']
    if case == harness.identity.query_id or case not in state.candidates:
        raise HarnessError('Header must belong to a registered candidate')
    if state.source_hashes.get(case) != digest:
        raise HarnessError('Candidate header hash differs from the run source')
    raw = harness.engine.store.raw_reader(case)
    if sha256(raw).hexdigest() != digest:
        raise SourceDrift(case)
    if not raw:
        raise HarnessError('Candidate source is empty')
    configured_budget = getattr(harness.m3, 'byte_budget', 1024)
    if type(configured_budget) is not int or configured_budget < 1:
        raise HarnessError('Candidate header needs a positive byte budget')
    end = min(len(raw), 1024, configured_budget)
    while end < len(raw) and end > 0 and raw[end] & 0xc0 == 0x80:
        end -= 1
    if not end:
        raise HarnessError('Candidate header byte budget cannot hold one UTF-8 codepoint')
    if hasattr(harness.m3, 'sources'):
        result = harness.m3.open_source({'case_id': case, 'source_hash': digest,
                                        'hit_spans': [[0, end]], 'byte_budget': end})
        if len(result.excerpts) != 1 or result.excerpts[0].span_bytes != (0, end):
            raise HarnessError('Candidate reader did not return the exact header span')
        record = result.excerpts[0]
        if record.case_id != case or record.source_hash != digest or record.text.encode('utf-8') != raw[:end]:
            raise SourceDrift(case)
        harness.engine.store.verify(record.to_record())
    else:
        prefix = raw[:end]
        record = SourceExcerpt(case, digest, (0, end), prefix.decode('utf-8'), sha256(prefix).hexdigest())
        result = ToolResult({}, (record,), (case,), ({
            'case_id': case, 'source_hash': digest,
            'requested_spans': [[0, end]], 'opened_spans': [[0, end]],
            'cumulative_opened_spans': [[0, end]], 'pending_spans': [], 'next_cursor': None,
        },))
    return ToolResult({**result.observation, 'route': 'open_candidate_header',
                       'm6_opened_candidate': case, 'cm4_candidate_header': [0, end],
                       'cm4_observed_spans': [[0, end]]},
                      result.excerpts, result.candidates, result.source_requests)


def execute_retrieved_passage(harness, state, args):
    case, lead = args['m6_candidate']['case_id'], args['cm4_retrieved_lead']
    for _, previous_case, previous_lead, outcome in _opened_leads(harness.events()):
        if previous_case != case or previous_lead != lead:
            continue
        result = outcome['result']
        refs = dict.fromkeys([*(row['ref'] for row in result['excerpts']), *outcome['reload_refs']])
        records = [state.catalog[ref] for ref in refs if ref in state.catalog
                   and state.catalog[ref]['case_id'] == case
                   and state.catalog[ref]['source_hash'] == lead['source_hash']]
        observation = result['observation']
        spans = observation.get('cm4_observed_spans') or [
            span for request in result['source_requests'] if request.get('case_id') == case
            and request.get('source_hash') == lead['source_hash'] for span in request.get('opened_spans', [])]
        if records and all(_covered(span, records) for span in spans):
            excerpts = tuple(excerpt(harness.engine.store.verify(record)) for record in records)
            cached = {key: value for key, value in observation.items()
                      if key not in ('reading_focus', 'local_search')}
            return ToolResult({**cached, 'route': 'reuse_observed_lead', 'm6_opened_candidate': case,
                               'cm4_source_read_action_id': outcome['action_id'],
                               'cm4_observed_spans': [list(row.span_bytes) for row in excerpts]},
                              excerpts, (case,))
    result = harness.m3.open_source(lead)
    return ToolResult({**result.observation, 'route': 'open_observed_lead', 'm6_opened_candidate': case,
                       'cm4_observed_spans': [list(row.span_bytes) for row in result.excerpts]},
                      result.excerpts, result.candidates, result.source_requests)
