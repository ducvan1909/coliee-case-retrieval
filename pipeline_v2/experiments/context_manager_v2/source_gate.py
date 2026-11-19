"""Source-bound decisions made before CM4 may issue a corpus search."""
from copy import deepcopy
import re

from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from .evidence import unread_spans

VERSION = 'cm4-source-gate-v2'
DECISIONS = ('has_source_signal', 'need_more_context', 'no_source_signal')
ATTRIBUTIONS = ('court', 'party', 'quoted_source', 'lower_tribunal', 'unknown')
REASONS = ('authority_reference', 'quoted_authority', 'masked_authority', 'facts',
           'procedural_history', 'relief_requested', 'truncated', 'attribution_unclear',
           'mixed_or_unclear', 'source_unresolved')


def assessment_properties(paragraph_refs, segment_refs):
    fields = {
        'paragraph_ref': {'type': 'string', 'enum': list(paragraph_refs)},
        'decision': {'type': 'string', 'enum': list(DECISIONS)},
        'attribution': {'type': 'string', 'enum': list(ATTRIBUTIONS)},
        'reason_code': {'type': 'string', 'enum': list(REASONS)},
        'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240},
        'context_complete': {'type': 'boolean'},
    }
    for name in ('proposition_ref', 'signal_ref'):
        if segment_refs:
            fields[name] = {'type': 'string', 'enum': list(segment_refs)}
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


_BOUNDARY = re.compile(r'(?<=[:;])\s+(?=\([a-z0-9]+\))|(?:\r?\n)+(?=\s*\([a-z0-9]+\))|(?<=[!?])\s+|(?<=\.)\s+(?=[A-ZÀ-Ö])')


def segments(payload):
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
    proposition = cue = None
    if decision == 'has_source_signal':
        issued = payload['m6']['source_gate_segments']
        p = issued.get(args.get('proposition_ref'))
        c = issued.get(args.get('signal_ref'))
        order = {item['handle']: i for i, item in enumerate(query_paragraphs)}
        cue_paragraph = payload['m6']['a_paragraphs'][c['paragraph_ref']] if c else None
        if not p or not c or p['paragraph_ref'] != args['paragraph_ref']:
            validation = 'Select a proposition in this paragraph and an issued source signal.'
        elif abs(order[paragraph['paragraph_handle']] - order[cue_paragraph['paragraph_handle']]) > 1:
            validation = 'Select a signal in the same paragraph or a visible neighboring paragraph.'
        else:
            proposition, cue = ({'span_bytes': item['span_bytes'], 'source_ref': item['source_ref'],
                                 'text': _slice(rows[item['source_ref']], item['span_bytes'])} for item in (p, c))
    if decision != 'need_more_context' and (not full or not args['context_complete']):
        validation = 'Read the complete paragraph context before a final screening decision.'
    if validation:
        decision = 'need_more_context'
    span = proposition['span_bytes'] if proposition else list(paragraph['paragraph_span_bytes'])
    key = 'gate-' + fingerprint([VERSION, payload['query_source_hash'], paragraph['paragraph_handle'], span])[:24]
    return {'source_need_ref': key, 'decision': decision, 'proposed_decision': args['decision'],
            'paragraph_handle': paragraph['paragraph_handle'],
            'paragraph_span_bytes': list(paragraph['paragraph_span_bytes']),
            'visible_span_bytes': [left, right], 'source_hash': payload['query_source_hash'],
            'source_ref': row['ref'], 'paragraph': deepcopy(paragraph),
            'proposition': proposition, 'signal': cue, 'attribution': args['attribution'],
            'reason_code': args['reason_code'], 'reason': args['reason'],
            'context_complete': full and args['context_complete'], 'validation_message': validation,
            'context_binding': fingerprint([row['source_hash'], [left, right], raw]),
            'status': 'approved' if decision == 'has_source_signal' else 'unresolved' if decision == 'need_more_context' else 'screened'}


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
            spans.setdefault(key, []).append(row['visible_span_bytes'])
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
                    and other['source_hash'] == assessment['source_hash'] and other['status'] == 'unresolved'):
                other.update(status='superseded', replacement_ref=key)
    decisions[key] = assessment
    return True


def screened_paragraphs(context):
    return {row['paragraph_handle'] for row in context.get('source_gate', {}).values()
            if (row['decision'] != 'need_more_context' or row['status'] == 'deferred')
            and row['context_complete']}


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
    spans = [row['span_bytes'] for request in state.requests.values()
             for row in request.get('excerpts', [])
             if row['case_id'] == query_id and row['source_hash'] == source_hash]
    return all(not unread_spans(row['span_bytes'], spans) for row in paragraphs)
