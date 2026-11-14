"""Purpose-oriented M6 tool catalog and structured transport bridge."""
from dataclasses import replace
import re
from jsonschema import Draft202012Validator, ValidationError
from .contracts import HarnessError, ModelReply, TransportError, encode, fingerprint
from .schema import ResponseSchemaError, parse_model_response, CASE_RELATIONS, PASSAGE_LOCATIONS, assessment_schema
from .evidence import slice_record

VERSION = 'm6-adaptive-purpose-v8'
ISSUE_SCHEMA = {'type': 'string', 'minLength': 4, 'maxLength': 160}
# Conservative observations only: this is neither citation resolution nor semantic extraction.
CITATION_PATTERN = re.compile(r'\b\d{4}\s+(?:SCC|FCA|FC|CanLII)\s+\d+\b|\[\d{4}\]\s+\d+\s+S\.?C\.?R\.?\s+\d+', re.IGNORECASE)


class ToolSemanticError(HarnessError):
    """An explicit M6 rule rejected otherwise schema-valid model arguments."""


class ModelToolReplyRejected(TransportError):
    """The provider returned a reply, but the M6 host rejected it."""


def obj(fields):
    return {'type': 'object', 'additionalProperties': False, 'properties': fields, 'required': list(fields)}


def choice(values):
    return {'type': 'string', 'enum': sorted(values)}


def text(limit=160, *, minimum=1):
    # XGrammar's pattern conversion can replace length constraints and force
    # single-character output for a bare non-whitespace pattern.
    return {'type': 'string', 'minLength': minimum, 'maxLength': limit}


def nonblank(value, field):
    stripped = value.strip()
    if not stripped:
        raise ToolSemanticError(f'blank_{field}')
    return stripped


def citations(body):
    result = {}
    current = set(body['current_payload_source_refs'])
    for row in body['excerpts']:
        if row['ref'] not in current or row['case_id'] != body['query_id']:
            continue
        for match in CITATION_PATTERN.finditer(row['text']):
            start = row['span_bytes'][0] + len(row['text'][:match.start()].encode('utf-8'))
            end = start + len(match[0].encode('utf-8'))
            record = {'source_ref': row['ref'], 'case_id': row['case_id'], 'source_hash': row['source_hash'],
                      'span_bytes': [start, end], 'text': match[0], 'method_version': 'm6-citation-regex-v1',
                      'identity_status': 'observed_not_identity_verified'}
            result[fingerprint(record)] = record
    return result


def catalog(body):
    """Build only tools whose bound references exist in this exact admitted payload."""
    state = body['m6']
    current = {row['ref']: row for row in body['excerpts'] if row['ref'] in body['current_payload_source_refs']}
    a_refs = [ref for ref, row in current.items() if row['case_id'] == body['query_id']]
    candidates = state['candidates']
    tools, branches = [], []

    def add(name, fields, description, when, result, examples):
        required = list(fields)
        if name in ('assess_case_link', 'review_conflicting_link'):
            optional = {'speaker': assessment_schema()['properties']['speaker'],
                        # vLLM's XGrammar backend rejects uniqueItems. Check
                        # distinct refs in translate before dispatch instead.
                        **{key: {'type': 'array', 'items': choice(current)} for key in ('identity_support_refs', 'speaker_evidence_refs', 'quote_chain_refs', 'container_refs')},
                        'counterevidence': {'type': 'array', 'items': choice(current)},
                        'missing_evidence': {'type': 'array', 'items': text(240)}}
            fields = {**fields, **optional}
        parameters = obj(fields)
        parameters['required'] = required
        tools.append({'name': name, 'description': description, 'when': when, 'result': result,
                      'examples': examples, 'parameters': parameters})
        branches.append(obj({'action': {'const': name}, 'args': parameters}))

    hybrid_remaining = state.get('hybrid_budget_remaining')
    paragraphs = state.get('a_paragraphs', {})
    if paragraphs and (hybrid_remaining is None or all(hybrid_remaining.values())):
        add('search_cases_by_issue', {'issue': dict(ISSUE_SCHEMA),
                                      'a_paragraph_ref': choice(paragraphs)},
            'Find candidate cases for a legal issue grounded in the current raw A excerpts.',
            'Use a full or partial paragraph currently shown as raw A. Partial coverage is enough to search; read more context when needed. Use find_citation_matches for an observed citation.',
            'Ranked leads and previews, not evidence. Host fixes channels and limits.',
            ['Choose an a_paragraph_ref from m6.a_paragraphs and ground the issue in its visible raw span. A partial ref does not mean the whole paragraph was read.',
             'Wrong: t, a single word, or an invented case ID.'])
    citation_rows = citations(body)
    if citation_rows:
        add('find_citation_matches', {'citation_ref': choice(citation_rows)},
            'Find textual matches for one exact citation observed in current A.',
            'Choose a host-issued citation ref; never supply citation text or source offsets.',
            'Observed matches with spans and coverage; identity remains unverified.',
            ['Good: choose the ref for 2012 SCC 12.', 'Wrong: use a whole paragraph ref as a citation ref.'])
    if state.get('citation_search_pages'):
        add('continue_citation_search', {'search_ref': choice(state['citation_search_pages'])},
            'Continue an incomplete textual citation search using its host-bound cursor.',
            'Use when coverage reports unscanned cases; this does not verify source identity.',
            'The next bounded search page, with observation method and coverage.',
            ['Choose a search_ref for the observed citation; do not supply cursor or scan limits.'])
    fresh_case = state.get('fresh_evidence_candidate')
    readable = {ref: candidate for ref, candidate in candidates.items()
                if not candidate.get('read_status') and candidate['case_id'] != fresh_case}
    if readable:
        add('read_case_passages', {'candidate_ref': choice(readable), 'focus': text(minimum=4)},
            'Read raw B passages about the chosen legal issue.',
            'Choose a known candidate and a short legal phrase of at least two words. Host opens a passage lead directly when available; otherwise searches within B.',
            'Full parent and source-order neighbors under the M3 page cap, with provenance and pending coverage.',
            ['Good: choose a candidate ref and focus on whether the court adopted the quoted test.',
             'Wrong: supply a case ID, retrieval channel, top_k or arbitrary open handle.'])
    if state.get('query_maps'):
        add('expand_query_map', {'map_ref': choice(state['query_maps'])},
            'Expand a structural map of A, or return to its parent/root.',
            'Choose a current map option to inspect smaller regions or navigate back. Map snippets are previews only.',
            'A bounded structural map; no raw evidence is delivered by this action.',
            ['Read raw at any level with read_query_passages; reaching a leaf is not required.'])
    if state['query_targets']:
        hierarchical = 'query_navigation' in state
        add('read_query_passages', {'query_ref': choice(state['query_targets'])},
            'Read raw query A at the current region or a child, at any tree level.' if hierarchical else
            'Read another observed region of query A or another map page.',
            'Use when A context is missing; query previews are navigation only.',
            'Raw A text with bounded continuation; use expand_query_map for maps.' if hierarchical else
            'Raw A text or the next bounded navigation page.', ['Choose a ref listed in query_targets.'])
    if state['expansions']:
        add('read_more_context', {'context_ref': choice(state['expansions'])},
            'Continue a pending page or open an observed neighboring/attribution region.',
            'Use when current evidence is truncated or speaker/quote context is missing.',
            'Additional raw source text and requested/delivered/pending coverage.', ['Choose an issued context_ref; do not calculate paragraph numbers.'])
    reloads = state['reloads']
    if reloads:
        add('reload_evidence', {'evidence_ref': choice(reloads)},
            'Bring previously delivered raw A/B excerpts back into the next payload.',
            'Use before assessing when relevant raw text is absent now. Reloading still costs tokens.',
            'Queued raw excerpts, not an assessment.', ['Choose one evidence_ref for a known A/B pair.'])
    pairs = {}
    for candidate_ref, candidate in candidates.items():
        b_refs = [ref for ref, row in current.items() if row['case_id'] == candidate['case_id']]
        for need_row in candidate.get('needs', []):
            present = [ref for ref in a_refs if any(
                current[ref]['case_id'] == source['case_id'] and current[ref]['source_hash'] == source['source_hash']
                and max(current[ref]['span_bytes'][0], source['span_bytes'][0]) < min(current[ref]['span_bytes'][1], source['span_bytes'][1])
                for source in need_row.get('a_sources', [])) or
                (not need_row.get('a_sources') and ref in need_row['a_refs'])]
            if present and b_refs:
                need = need_row['source_need_id']
                key = fingerprint([need, candidate['case_id'], present, b_refs])
                pairs[key] = {'source_need_id': need, 'candidate_id': candidate['case_id'],
                              'a_context_refs': present, 'b_passage_refs': b_refs,
                              'context_coverage': 'partial' if set(present) != set(need_row['a_refs']) else 'original_search_context'}
    if pairs:
        fields = {'pair_ref': choice(pairs), 'case_relation': choice(CASE_RELATIONS),
                  'passage_location': choice(PASSAGE_LOCATIONS), 'reason': text(240)}
        add('assess_case_link', fields,
            'Assess whether A cites or relies on B using the current raw excerpts.',
            'Both sides must be in this payload. Similarity alone does not establish A-to-B use.',
            'M4-validated assessment. Optional speaker uses the discriminated role/type schema; known attribution needs current speaker/quote/container refs. Counterevidence cites current refs; missing_evidence lists concrete context to read next. Unknown remains valid.',
            ['Judge relation separately from pinpoint location.', 'Do not infer A-to-B merely because both quote C.'])
        review_pairs = {key: row for key, row in pairs.items() if row['candidate_id'] in state['review_candidates']}
        if review_pairs and state['review_count'] < state['max_reviews']:
            add('review_conflicting_link', {**fields, 'pair_ref': choice(review_pairs), 'finding': text(240)},
                'Review a host-triggered attribution or relation conflict and provide a concrete finding.',
                'Only triggered candidates, bounded by the shared request budget and reviewer cap.',
                'A new evidence-bound assessment revision with the review finding; not human gold.',
                ['State which current passage resolves or preserves the conflict; agreement alone is insufficient.'])
    stop_reasons = ['no_progress', 'failure']
    if state.get('search_completed'):
        stop_reasons.append('complete_policy')
    add('finish_case_review', {'reason': choice(stop_reasons)},
        'End adaptive evidence acquisition; host selector owns final predictions.',
        'Use complete_policy only after a search has executed and the bounded review is done.',
        'A stop record and shared-selector prediction or pending_selection.', ['No model-supplied predictions or cutoff.'])
    return tools, {'type': 'object', 'anyOf': branches}, citation_rows, pairs


def translate(body, action):
    _, schema, citation_rows, pairs = catalog(body)
    if isinstance(action, dict) and isinstance(action.get('action'), str):
        # Validate against the same disjoint branch sent to the decoder, so
        # a rejected argument identifies its own path instead of the root anyOf.
        branch = next((candidate for candidate in schema['anyOf']
                       if candidate['properties']['action']['const'] == action['action']), None)
        if branch is None:
            raise ValidationError('Action is not available for this payload', path=('action',), validator='enum')
        Draft202012Validator(branch).validate(action)
    else:
        Draft202012Validator(schema).validate(action)
    name, args = action['action'], action['args']
    state = body['m6']
    if name == 'search_cases_by_issue':
        issue = args['issue'].strip()
        if len(issue) < 4 or len(re.findall(r'[^\W_]+', issue)) < 2:
            raise ToolSemanticError('issue_requires_legal_phrase')
        if re.search(r'\b\d+\.txt\b', issue, re.IGNORECASE):
            raise ToolSemanticError('issue_contains_case_id')
        handle = args['a_paragraph_ref']
        paragraph = state['a_paragraphs'][handle]
        start, end = paragraph['span_bytes']
        original = paragraph.get('paragraph_span_bytes')
        paragraph_handle = paragraph.get('paragraph_handle')
        if (not isinstance(original, (tuple, list)) or len(original) != 2
                or any(type(offset) is not int or offset < 0 for offset in original)
                or not original[0] <= start < end <= original[1]
                or not isinstance(paragraph_handle, str) or not paragraph_handle):
            raise ToolSemanticError('paragraph_coverage_metadata_mismatch')
        full = (start, end) == tuple(original)
        expected_handle = paragraph_handle if full else f'{paragraph_handle}@{start}:{end}'
        if paragraph.get('paragraph_coverage') != ('full' if full else 'partial') or handle != expected_handle:
            raise ToolSemanticError('paragraph_coverage_metadata_mismatch')
        source = next((row for row in body['excerpts'] if row['ref'] == paragraph['source_ref']
                       and row['ref'] in body['current_payload_source_refs']
                       and row['case_id'] == paragraph['case_id'] == body['query_id']
                       and row['source_hash'] == paragraph['source_hash'] == body['query_source_hash']
                       and row['span_bytes'][0] <= start < end <= row['span_bytes'][1]), None)
        if source is None or slice_record(source, start, end)['text_sha256'] != paragraph['text_sha256']:
            raise ToolSemanticError('paragraph_not_in_current_query_evidence')
        need = {'a_refs': [paragraph['source_ref']], 'intent': issue, 'route': 'issue',
                'a_paragraph': {'handle': handle, **paragraph},
                'a_sources': [{key: paragraph[key] for key in ('case_id', 'source_hash', 'span_bytes')}]}
        need['source_need_id'] = 'need-' + fingerprint(need)[:24]
        return {'action': 'search_corpus', 'args': {'text': issue, 'channel': state['channel'], 'limit': state['search_limit'], '_m6_need': need}}
    if name == 'find_citation_matches':
        row = citation_rows[args['citation_ref']]
        need = {'a_refs': [row['source_ref']], 'intent': row['text'], 'citation': row, 'route': 'citation'}
        need['a_sources'] = [{key: row[key] for key in ('case_id', 'source_hash', 'span_bytes')} for row in body['excerpts'] if row['ref'] in need['a_refs']]
        need['source_need_id'] = 'need-' + fingerprint(need)[:24]
        return {'action': 'search_identity', 'args': {'text': row['text'], 'limit': state['search_limit'], '_m6_need': need}}
    if name == 'continue_citation_search':
        return {'action': 'search_identity', 'args': state['citation_search_pages'][args['search_ref']]['binding']}
    if name == 'read_case_passages':
        row = state['candidates'][args['candidate_ref']]
        focus = args['focus'].strip()
        if len(focus) < 4 or len(re.findall(r'[^\W_]+', focus)) < 2:
            raise ToolSemanticError('focus_requires_legal_phrase')
        return {'action': 'open_source', 'args': {'m6_candidate': row, 'focus': focus}}
    if name == 'expand_query_map':
        return {'action': 'open_query', 'args': state['query_maps'][args['map_ref']]['binding']}
    if name == 'read_query_passages':
        return {'action': 'open_query', 'args': state['query_targets'][args['query_ref']]['binding']}
    if name == 'read_more_context':
        return {'action': 'expand_source', 'args': state['expansions'][args['context_ref']]['binding']}
    if name == 'reload_evidence':
        return {'action': 'reload_source', 'args': {'refs': state['reloads'][args['evidence_ref']]}}
    if name in ('assess_case_link', 'review_conflicting_link'):
        row = {key: value for key, value in pairs[args['pair_ref']].items() if key != 'context_coverage'}
        row.update({key: args[key].strip() for key in ('case_relation', 'passage_location', 'reason')})
        row['reason'] = nonblank(args['reason'], 'reason')
        row['speaker'] = args.get('speaker', {'role': 'unknown'})
        for key in ('identity_support_refs', 'speaker_evidence_refs', 'quote_chain_refs', 'container_refs', 'counterevidence', 'missing_evidence'):
            if key in args:
                if key != 'missing_evidence' and len(set(args[key])) != len(args[key]):
                    raise ToolSemanticError('duplicate_evidence_refs')
                if key != 'missing_evidence' and any(ref not in body['current_payload_source_refs'] or
                    next(source['case_id'] for source in body['excerpts'] if source['ref'] == ref) not in (body['query_id'], row['candidate_id']) for ref in args[key]):
                    raise ToolSemanticError('evidence_ref_belongs_to_another_pair')
                row[key] = ([nonblank(value, key) for value in args[key]]
                            if key == 'missing_evidence' else args[key])
        if row.get('counterevidence'):
            dependencies = set().union(*(set(row.get(key, [])) for key in ('a_context_refs', 'b_passage_refs', 'identity_support_refs', 'speaker_evidence_refs', 'quote_chain_refs', 'container_refs')))
            if not set(row['counterevidence']) <= dependencies:
                raise ToolSemanticError('counterevidence_not_in_assessment_dependencies')
            # M4 treats counterevidence as a note, not REF_FIELDS: host materializes verified raw records.
            row['counterevidence'] = encode([source for source in body['excerpts'] if source['ref'] in row['counterevidence']]).decode('utf-8')
        if name == 'assess_case_link' and row['reason'].startswith('Targeted review: '):
            raise ToolSemanticError('reserved_review_marker')
        if name == 'review_conflicting_link':
            row['reason'] = 'Targeted review: ' + nonblank(args['finding'], 'finding') + ' | ' + row['reason']
        return {'action': 'assess_links', 'args': {'assessments': [row]}}
    return {'action': 'stop', 'args': {'reason': 'complete', 'prediction': []} if args['reason'] == 'complete_policy'
            else {'reason': args['reason']}}


class AdaptiveTransport:
    """The durable M4 admission contains the exact catalog/schema sent to the engine."""
    def __init__(self, underlying, count_tokens):
        self.underlying, self.counter = underlying, count_tokens
        self._reply_diagnostic = None

    def count_tokens(self, payload):
        return self.counter(payload)

    def take_reply_diagnostic(self, request_id):
        diagnostic, self._reply_diagnostic = self._reply_diagnostic, None
        if diagnostic is not None and diagnostic['request_id'] == request_id:
            return diagnostic
        return None

    def _reject(self, reply, stage, code, *, path=None, validator=None):
        self._reply_diagnostic['rejection'] = {
            'stage': stage, 'code': code, 'path': path, 'validator': validator,
        }
        return ModelToolReplyRejected(f'm6_tool_reply_rejected:{stage}:{code}',
                                      input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                                      latency_ms=reply.latency_ms)

    def send_structured(self, payload, request_id, schema):
        self._reply_diagnostic = None
        body = parse_model_response(payload.decode('utf-8'))
        _, narrowed, _, _ = catalog(body)
        if fingerprint(narrowed) != body['m6']['schema_fingerprint']:
            raise TransportError('m6_schema_binding_mismatch')
        reply = self.underlying.send_structured(payload, request_id, narrowed)
        if not isinstance(reply, ModelReply):
            raise TransportError('m6_invalid_reply')
        # Live replies are text. Local transports may return a JSON object.
        # Keep malformed text verbatim and avoid an unserializable object
        # obscuring the original failure when appending the receipt.
        raw = reply.action
        raw_format = 'text' if isinstance(raw, str) else 'json'
        try:
            encode(raw)
        except UnicodeEncodeError:
            if isinstance(raw, str):
                raw = raw.encode('unicode_escape').decode('ascii')
                raw_format = 'unicode_escape'
            else:
                raw, raw_format = None, 'unserializable'
        except (TypeError, ValueError, OverflowError, RecursionError):
            raw, raw_format = None, 'unserializable'
        self._reply_diagnostic = {
            'request_id': request_id, 'raw_action': raw, 'raw_format': raw_format, 'rejection': None,
        }
        try:
            parsed = parse_model_response(reply.action)
        except ResponseSchemaError as exc:
            raise self._reject(reply, 'parse', str(exc)) from exc
        try:
            internal = translate(body, parsed)
        except ValidationError as exc:
            raise self._reject(reply, 'schema', 'schema_validation_failed',
                               path=list(exc.absolute_path), validator=exc.validator) from exc
        except ToolSemanticError as exc:
            raise self._reject(reply, 'semantics', str(exc)) from exc
        except Exception as exc:
            raise self._reject(reply, 'adapter', 'internal_translation_error') from exc
        return replace(reply, action=internal)
