"""Source-bound decisions made before CM4 may issue a corpus search."""
from copy import deepcopy
import re

from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from .evidence import unread_spans

VERSION = 'cm4-source-gate-v5'
DECISIONS = ('search_needed', 'need_more_context', 'no_search_needed')
ATTRIBUTIONS = ('court', 'party', 'quoted_source', 'lower_tribunal', 'unknown')
REASONS = ('authority_reference', 'quoted_authority', 'masked_authority', 'facts',
           'procedural_history', 'relief_requested', 'truncated', 'attribution_unclear',
           'mixed_or_unclear', 'source_unresolved', 'legal_proposition', 'source_relationship')


def assessment_properties(paragraph_refs, segment_refs):
    fields = {
        'paragraph_ref': {'type': 'string', 'enum': list(paragraph_refs)},
        'decision': {'type': 'string', 'enum': list(DECISIONS)},
        'attribution': {'type': 'string', 'enum': list(ATTRIBUTIONS)},
        'reason_code': {'type': 'string', 'enum': list(REASONS)},
        'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240},
        'context_complete': {'type': 'boolean'},
        'sufficient_for_search': {'type': 'boolean'},
        'missing_context': {'type': 'string', 'maxLength': 240},
    }
    for name in ('proposition_ref', 'signal_ref'):
        if segment_refs:
            choices = ([ref for ref, row in segment_refs.items() if row.get('proposition_selectable', True)]
                       if name == 'proposition_ref' and isinstance(segment_refs, dict) else list(segment_refs))
            if choices:
                fields[name] = {'type': 'string', 'enum': choices}
    if isinstance(segment_refs, dict) and not any(row.get('proposition_selectable', True) for row in segment_refs.values()):
        fields['decision']['enum'] = [decision for decision in DECISIONS if decision != 'search_needed']
    return fields


def _query_rows(payload):
    current = set(payload['current_payload_source_refs'])
    return {row['ref']: row for row in payload['excerpts'] if row['ref'] in current
            and row['case_id'] == payload['query_id'] and row['source_hash'] == payload['query_source_hash']}


def _slice(row, span):
    origin, end = row['span_bytes']
    left, right = span
    if not origin <= left < right <= end:
        raise HarnessError('Source gate span is outside the current excerpt')
    return row['text'].encode('utf-8')[left-origin:right-origin].decode('utf-8')


_BOUNDARY = re.compile(r'(?<=[:;])\s+(?=\([a-z0-9]+\))|(?:\r?\n)+(?=\s*\([a-z0-9]+\))|(?<=[!?])\s+|(?<=\.)\s+(?=[A-Z\u00c0-\u00d6])')


def segments(payload, context=None):
    """Issue selectable sentence or list-item spans from current query excerpts."""
    rows = _query_rows(payload)
    result = {}
    for ref, paragraph in payload['m6']['a_paragraphs'].items():
        source = rows[paragraph['source_ref']]
        raw = _slice(source, paragraph['span_bytes'])
        origin = paragraph['span_bytes'][0]
        cuts = [0]
        for boundary in _BOUNDARY.finditer(raw):
            left = raw[:boundary.start()]
            # Keep reporter abbreviations and judicial titles with their sentence.
            if not re.search(r'(?:\b(?:No|J|JJ|para|Mr|Ms|Dr|v)|\b[A-Z])\.$', left):
                cuts.append(boundary.end())
        for i, (left, right) in enumerate(zip(cuts, [*cuts[1:], len(raw)]), 1):
            value = raw[left:right]
            if not value.strip():
                continue
            start = origin + len(raw[:left].encode('utf-8'))
            span = [start, start + len(value.encode('utf-8'))]
            result[f'{ref}.s{i}'] = {'paragraph_ref': ref, 'source_ref': source['ref'], 'span_bytes': span,
                                    'preview': ' '.join(value.split())[:56]}
    if context is not None:
        settled = _settled_spans(context)
        for ref, item in list(result.items()):
            paragraph = payload['m6']['a_paragraphs'][item['paragraph_ref']]
            gaps = unread_spans(item['span_bytes'], settled.get((payload['query_source_hash'], paragraph['paragraph_handle']), []))
            item['proposition_selectable'] = gaps == [item['span_bytes']]
            if gaps and not item['proposition_selectable']:
                for i, gap in enumerate(gaps):
                    result[f'{ref}.remaining{i}'] = {**item, 'span_bytes': gap,
                        'preview': ' '.join(_slice(rows[item['source_ref']], gap).split())[:56],
                        'proposition_selectable': True}
    return result


def evaluate(payload, args, query_paragraphs):
    """Bind the model decision to issued source spans without judging its meaning."""
    paragraph = payload['m6']['a_paragraphs'][args['paragraph_ref']]
    rows = _query_rows(payload)
    row = rows.get(paragraph['source_ref'])
    if row is None:
        raise HarnessError('Source gate requires current query evidence')
    left, right = paragraph['span_bytes']
    raw = _slice(row, [left, right])
    full = paragraph['paragraph_coverage'] == 'full'
    decision, validation = args['decision'], None
    if decision not in DECISIONS:
        raise HarnessError('Unsupported source-need decision')
    proposition = cue = None
    if decision == 'search_needed':
        issued = payload['m6']['source_gate_segments']
        p = issued.get(args.get('proposition_ref'))
        c = issued.get(args.get('signal_ref'))
        order = {item['handle']: i for i, item in enumerate(query_paragraphs)}
        cue_paragraph = payload['m6']['a_paragraphs'][c['paragraph_ref']] if c else None
        if not p or not p.get('proposition_selectable', True) or p['paragraph_ref'] != args['paragraph_ref']:
            validation = 'Select an issued proposition in this visible paragraph span.'
        elif c and abs(order[paragraph['paragraph_handle']] - order[cue_paragraph['paragraph_handle']]) > 1:
            validation = 'Select an optional source signal in this or a visible neighboring paragraph.'
        else:
            proposition = {'span_bytes': p['span_bytes'], 'source_ref': p['source_ref'],
                           'text': _slice(rows[p['source_ref']], p['span_bytes'])}
            if c:
                cue = {'span_bytes': c['span_bytes'], 'source_ref': c['source_ref'],
                       'text': _slice(rows[c['source_ref']], c['span_bytes'])}
        if not args.get('sufficient_for_search', args['context_complete']):
            validation = 'Read more context or declare the selected proposition sufficient for search.'
    elif decision == 'no_search_needed' and not args['context_complete']:
        validation = 'Read enough context to decide whether this visible span needs a source.'
    if validation:
        decision = 'need_more_context'
    span = proposition['span_bytes'] if proposition else [left, right]
    key = 'gate-' + fingerprint([VERSION, payload['query_source_hash'], paragraph['paragraph_handle'], span])[:24]
    return {'source_need_ref': key, 'decision': decision, 'proposed_decision': args['decision'],
            'paragraph_handle': paragraph['paragraph_handle'],
            'paragraph_span_bytes': list(paragraph['paragraph_span_bytes']),
            'visible_span_bytes': [left, right], 'source_hash': payload['query_source_hash'],
            'source_ref': row['ref'], 'paragraph': deepcopy(paragraph),
            'proposition': proposition, 'signal': cue, 'attribution': args['attribution'],
            'reason_code': args['reason_code'], 'reason': args['reason'],
            'context_complete': full and args['context_complete'],
            'paragraph_complete': full,
            'sufficient_for_search': args.get('sufficient_for_search', args['context_complete']),
            'missing_context': args.get('missing_context', ''), 'validation_message': validation,
            'context_binding': fingerprint([row['source_hash'], [left, right], raw]),
            'status': 'approved' if decision == 'search_needed' else 'unresolved' if decision == 'need_more_context' else 'screened'}


def visible_permits(payload, context, *, status='approved'):
    """Only approved, unconsumed decisions whose exact query anchor is visible."""
    permits = {}
    for key, decision in context.get('source_gate', {}).items():
        if decision['status'] != status or decision['source_hash'] != payload['query_source_hash']:
            continue
        paragraph = decision['paragraph']
        matching = next((ref for ref, row in payload['m6']['a_paragraphs'].items()
                         if row['source_ref'] == decision['source_ref']
                         and row['paragraph_handle'] == decision['paragraph_handle']
                         and tuple(row['span_bytes']) == tuple(paragraph['span_bytes'])), None)
        if matching:
            permits[key] = {'decision': decision, 'paragraph_ref': matching}
    return permits


def authorized(context, need_id):
    return bool(need_id) and need_id in context.get('source_gate_searches', {})


def _settled_spans(context):
    spans = {}
    for row in context.get('source_gate', {}).values():
        if row['status'] in ('screened', 'approved', 'searched', 'deferred', 'search_deferred'):
            key = row['source_hash'], row['paragraph_handle']
            spans.setdefault(key, []).append(row['proposition']['span_bytes'] if row.get('proposition') else row['visible_span_bytes'])
    return spans


def screening_choices(payload, context):
    """A narrower view of a settled paragraph adds no screening work."""
    evaluated = _settled_spans(context)
    return [ref for ref, row in payload['m6']['a_paragraphs'].items()
            if not any(start <= row['span_bytes'][0] < row['span_bytes'][1] <= end
                       for start, end in evaluated.get((row['source_hash'], row['paragraph_handle']), []))]


def commit_decision(context, assessment):
    """Apply a screening decision without letting a partial view downgrade it."""
    start, end = assessment['visible_span_bytes']
    identity = assessment['source_hash'], assessment['paragraph_handle']
    if assessment.get('proposition') and assessment['decision'] == 'search_needed':
        span = assessment['proposition']['span_bytes']
        if not unread_spans(span, _settled_spans(context).get(identity, [])):
            return False
    if (assessment['paragraph']['paragraph_coverage'] == 'partial'
            and any(left <= start < end <= right for left, right in _settled_spans(context).get(identity, []))):
        return False
    decisions = context.setdefault('source_gate', {})
    key = assessment['source_need_ref']
    previous = decisions.get(key)
    if previous and (previous['context_binding'], previous['decision']) == (
            assessment['context_binding'], assessment['decision']):
        return True
    if previous:
        context.setdefault('source_gate_history', []).append(deepcopy(previous))
    if assessment['decision'] != 'need_more_context':
        for other_key, other in decisions.items():
            if (other_key != key and other['paragraph_handle'] == assessment['paragraph_handle']
                    and other['source_hash'] == assessment['source_hash'] and other['status'] == 'unresolved'
                    and start <= other['visible_span_bytes'][0] < other['visible_span_bytes'][1] <= end):
                other.update(status='superseded', replacement_ref=key)
    decisions[key] = assessment
    return True


def screened_paragraphs(context):
    return {row['paragraph_handle'] for row in context.get('source_gate', {}).values()
            if (row['decision'] != 'need_more_context' or row['status'] == 'deferred')
            and not unread_spans(row['paragraph_span_bytes'], _settled_spans(context).get(
                (row['source_hash'], row['paragraph_handle']), []))}


def progress(context, paragraphs):
    rows = list(context.get('source_gate', {}).values())
    screened = screened_paragraphs(context)
    targets = {row['handle'] for row in paragraphs}
    unresolved = [key for key, row in context.get('source_gate', {}).items()
                  if row['status'] == 'unresolved']
    unsearched = [key for key, row in context.get('source_gate', {}).items()
                  if row['status'] == 'approved']
    return {'paragraphs_total': len(targets), 'paragraphs_screened': len(targets & screened),
            'unscreened_examples': sorted(targets - screened)[:5],
            'unresolved_count': len(unresolved), 'unsearched_count': len(unsearched),
            'deferred_count': sum(row['status'] == 'deferred' for row in rows),
            'deferred_search_count': sum(row['status'] == 'search_deferred' for row in rows),
            'complete': bool(targets) and targets <= screened and not unresolved and not unsearched}


def query_fully_read(state, paragraphs, query_id, source_hash):
    spans = [row['span_bytes'] for request_id, request in state.requests.items()
             if state.receipts.get(request_id, {}).get('received_response')
             for row in request.get('excerpts', [])
             if row['ref'] in request.get('current_payload_source_refs', [])
             and row['case_id'] == query_id and row['source_hash'] == source_hash]
    return all(not unread_spans(row['span_bytes'], spans) for row in paragraphs)


def delivered_query_rows(state, query_id, source_hash):
    return [row for request_id, request in state.requests.items()
            if state.receipts.get(request_id, {}).get('received_response')
            for row in request.get('excerpts', [])
            if row['ref'] in request.get('current_payload_source_refs', [])
            and row['case_id'] == query_id and row['source_hash'] == source_hash]


def span_options(state, payload):
    """Offer bounded, contiguous adjacent evidence across received windows."""
    delivered = delivered_query_rows(state, payload['query_id'], payload['query_source_hash'])
    options = {}
    for paragraph in payload['m6']['a_paragraphs'].values():
        start, end = paragraph['span_bytes']
        outer_start, outer_end = paragraph['paragraph_span_bytes']
        for previous in reversed(delivered):
            left, right = previous['span_bytes']
            left, right = max(left, outer_start), min(right, outer_end)
            if left >= right or right < start or left > end:
                continue
            combined = [min(left, start), max(right, end)]
            if combined == [start, end] or combined[1] - combined[0] > 8192:
                continue
            if unread_spans(combined, [row['span_bytes'] for row in delivered]):
                continue
            key = 'query-span-' + fingerprint([payload['query_source_hash'], combined])[:16]
            options[key] = {'source_hash': payload['query_source_hash'], 'span_bytes': combined,
                            'paragraph_handle': paragraph['paragraph_handle']}
            if len(options) >= 4:
                return options
    return options
