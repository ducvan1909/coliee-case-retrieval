"""Source-bound decisions made before CM4 may issue a corpus search."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re

from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from .evidence import unread_spans
from .anchor_quote import _matches, _visible_paragraphs, _normalized_text, _typographic_text, _nearby_anchors

VERSION = 'cm4-source-gate-v6'
BOUND_VERSION = 'cm4-source-bound-v2'
DECISIONS = ('search_needed', 'need_more_context', 'no_search_needed')
ATTRIBUTIONS = ('court', 'party', 'quoted_source', 'lower_tribunal', 'unknown')
REASONS = ('authority_reference', 'quoted_authority', 'masked_authority', 'facts',
           'procedural_history', 'relief_requested', 'truncated', 'attribution_unclear',
           'mixed_or_unclear', 'source_unresolved', 'legal_proposition', 'source_relationship')


@lru_cache(maxsize=1)
def _embedding_tokenizer():
    from pipeline_v2.passages import PinnedTokenizer
    return PinnedTokenizer(Path(__file__).resolve().parents[3],
                           'pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json')


def embedding_query_budget(text, profile=None):
    """Count precisely the input accepted by AccountedSparseHybridSession."""
    from pipeline_v2.retrieval.runtime import render_query
    if profile is None:
        profile = json.loads((Path(__file__).resolve().parents[3] /
                              'pipeline_v2/configs/m3_full.json').read_bytes())
    ids = _embedding_tokenizer().backend.encode(render_query(text, profile), add_special_tokens=True).ids
    cap = profile['embedding']['max_tokens']
    return {'input_tokens': len(ids), 'max_tokens': cap,
            'accepted': bool(ids) and ids[-1] == 151643 and len(ids) <= cap}


def query_text(decision):
    text = decision['proposition']['text']
    additions = [row['text'] for row in decision.get('a_supports', [])
                 if row['role'] in ('citation', 'group_member') and row['text'] not in text]
    return '\n'.join([text, *dict.fromkeys(additions)])


def _set_group(context, refs, kind, reason, query_case):
    main = context['source_gate'][refs[0]]
    main.update(group_members=list(refs), group_kind=kind, group_reason=reason)
    for ref in refs[1:]:
        row = context['source_gate'][ref]
        row.update(status='grouped', grouped_into=refs[0])
        main.setdefault('a_supports', []).append({
            'role': 'group_member', 'case_id': query_case,
            'source_hash': row['source_hash'], 'source_ref': row['source_ref'],
            'span_bytes': deepcopy(row['proposition']['span_bytes']), 'text': row['proposition']['text']})
        # Each member's citation remains bound even when different source refs
        # carry the same literal citation; query_text alone deduplicates text.
        for support in row.get('a_supports', []):
            if support not in main['a_supports']:
                main['a_supports'].append(deepcopy(support))


def fit_query_permits(context, query_case, budget=embedding_query_budget):
    """Partition oversized groups before persisting approval, never cut source text."""
    decisions = context.get('source_gate', {})
    for ref, main in list(decisions.items()):
        if main['status'] != 'approved':
            continue
        members = main.get('group_members', [ref])
        if len(members) > 1:
            kind, reason = main['group_kind'], main['group_reason']
            # Rebuild from original member records. Group-only supports must not
            # leak into a later split query or survive revising the main span.
            for member in members:
                row = decisions[member]
                originals = row.pop('ungrouped_a_supports', None)
                row['a_supports'] = originals if originals is not None else [
                    s for s in row.get('a_supports', []) if s['role'] != 'group_member']
                row['status'] = 'approved'
                for key in ('group_members', 'group_kind', 'group_reason', 'grouped_into', 'group_context'):
                    row.pop(key, None)
            partitions = []
            for member in members:
                row = decisions[member]
                if partitions:
                    trial = deepcopy(context)
                    _set_group(trial, [*partitions[-1], member], kind, reason, query_case)
                    if budget(query_text(trial['source_gate'][partitions[-1][0]]))['accepted']:
                        partitions[-1].append(member)
                        continue
                partitions.append([member])
            for part in partitions:
                row = decisions[part[0]]
                row['ungrouped_a_supports'] = deepcopy(row.get('a_supports', []))
                if len(part) > 1:
                    _set_group(context, part, kind, reason, query_case)
                if len(partitions) > 1:
                    row['embedding_split_from'] = list(members)
        # Check every approved partition, including a single oversized span.
    for row in decisions.values():
        if row['status'] != 'approved':
            continue
        row['embedding_query_budget'] = budget(query_text(row))
        if not row['embedding_query_budget']['accepted']:
            row.update(status='unresolved', decision='need_more_context', resolution_choices=[],
                       validation_message='The full rendered embedding query exceeds its token cap. '
                       'Select a smaller complete source proposition or revise citation supports; no text was truncated.')


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


def bound_assessment_properties(paragraph_refs, segment_refs):
    fields = assessment_properties(paragraph_refs, segment_refs)
    fields['proposition_quote'] = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
    if segment_refs:
        fields['a_supports'] = {'type': 'array', 'maxItems': 4, 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'role': {'type': 'string', 'enum': ['attribution', 'citation']},
                           'span_ref': {'type': 'string', 'enum': [ref for ref,row in segment_refs.items() if not row.get('negative_only')]}},
            'required': ['role', 'span_ref']}}
    return fields


def bound_assessment_variants(paragraph_refs, segment_refs):
    """Use flat, mutually exclusive branches supported by structured decoders."""
    common = bound_assessment_properties(paragraph_refs, segment_refs)
    variants = []
    for decision in DECISIONS:
        for selector in ('proposition_ref', 'proposition_quote', None):
            if selector is None and decision != 'need_more_context':
                continue
            fields = {key: deepcopy(value) for key,value in common.items()
                      if key not in ('proposition_ref','proposition_quote') or key == selector}
            fields['decision'] = {'type':'string','enum':[decision]}
            if selector == 'proposition_ref':
                choices = [ref for ref,row in segment_refs.items()
                           if row.get('proposition_selectable',True)
                           or (decision == 'no_search_needed' and row.get('negative_only'))]
                if not choices:
                    continue
                fields['proposition_ref'] = {'type':'string','enum':choices}
            required = [key for key in fields if key not in ('signal_ref','sufficient_for_search','missing_context','a_supports')]
            variants.append((fields, required))
    return variants


def evaluate_bound(payload, args, query_paragraphs):
    """Resolve a source span; approximate matches never authorize retrieval."""
    rows = _query_rows(payload)
    paragraph = payload['m6']['a_paragraphs'][args['paragraph_ref']]
    issued = payload['m6']['source_gate_segments']
    has_ref = bool(args.get('proposition_ref'))
    has_quote = bool(args.get('proposition_quote'))
    if has_ref and has_quote:
        raise HarnessError('Choose exactly one proposition_ref or proposition_quote.')
    if args['decision'] != 'need_more_context' and not (has_ref or has_quote):
        raise HarnessError('Choose one offered proposition_ref or provide a literal proposition_quote for this decision.')
    chosen = issued.get(args.get('proposition_ref'))
    resolved = None
    suggestions = []
    if args.get('proposition_quote'):
        # Reuse exact/whitespace/paired-quote normalization and exact-source
        # suggestions. The resolver never accepts a fuzzy suggestion itself.
        visible=list(_visible_paragraphs(payload))
        unique={}
        quote=args['proposition_quote'].strip()
        for normalizer in (None,_normalized_text,_typographic_text):
            for ref,anchor in _matches(visible,quote,normalize=normalizer):
                unique.setdefault(tuple(anchor['span_bytes']),(ref,anchor))
        resolved=next(iter(unique.values())) if len(unique)==1 else None
        suggestions=list(unique.values())[:3] if len(unique)>1 else ([] if resolved else _nearby_anchors(visible,quote))
        if not resolved and not unique and len(quote) > 240:
            # A full visible paragraph is a confirmation choice for a long
            # imperfect copy, never an automatically accepted match.
            words = set(re.findall(r'\w+', quote.casefold()))
            for ref, source_ref, left, text in visible:
                candidate_words = set(re.findall(r'\w+', text.casefold()))
                if (ref == args['paragraph_ref'] and len(text) <= 4096 and words
                        and len(words & candidate_words) / len(words) >= 0.65):
                    suggestions.insert(0, (ref, {'source_ref': source_ref,
                        'span_bytes': [left,left+len(text.encode('utf-8'))], 'text': text}))
                    suggestions = suggestions[:3]
                    break
    elif chosen and chosen.get('negative_only'):
        if (args['decision'] != 'no_search_needed' or not args['context_complete']
                or chosen['paragraph_ref'] != args['paragraph_ref']):
            raise HarnessError('The remaining-visible reference only supports no_search_needed for its shown paragraph.')
        spans = chosen['selected_spans']
        for span in spans:
            _slice(rows[chosen['source_ref']], span)
        scaffold = {**args, 'decision': 'need_more_context'}
        result = evaluate(payload, scaffold, query_paragraphs)
        result.update(bound_mode=True, proposed_decision='no_search_needed', requested_args=deepcopy(args),
                      a_supports=[], resolution_choices=[], settled_spans=deepcopy(spans),
                      decision='no_search_needed', status='screened', validation_message=None,
                      visible_span_bytes=[spans[0][0], spans[-1][1]],
                      source_need_ref='gate-'+fingerprint([BOUND_VERSION,payload['query_source_hash'],paragraph['paragraph_handle'],spans])[:24])
        return result
    elif chosen and chosen.get('proposition_selectable', True):
        resolved = (chosen['paragraph_ref'], {key: deepcopy(chosen[key]) for key in ('source_ref', 'span_bytes')})
        resolved[1]['text'] = _slice(rows[chosen['source_ref']], chosen['span_bytes'])
    # Use legacy metadata validation only as a scaffold, then bind every
    # positive/negative decision to exactly the resolved primary span.
    scaffold = {**args, 'decision': 'need_more_context'}
    result = evaluate(payload, scaffold, query_paragraphs)
    result.update(bound_mode=True, proposed_decision=args['decision'], requested_args=deepcopy(args),
                  a_supports=[], resolution_choices=[])
    if resolved:
        ref, anchor = resolved
        selected = payload['m6']['a_paragraphs'][ref]
        if selected['paragraph_handle'] != paragraph['paragraph_handle']:
            result['validation_message'] = 'Choose the paragraph containing the selected literal span.'
            return result
        left, right = anchor['span_bytes']
        heading_only = any(start <= left < right <= end for start,end in payload['m6'].get('known_heading_spans', []))
        settled = payload['m6'].get('settled_source_spans', [])
        blocked_heading = heading_only and args['decision'] == 'search_needed'
        if blocked_heading or not unread_spans([left,right], settled):
            result['validation_message'] = ('A heading alone cannot authorize a source search.' if blocked_heading else
                                            'This exact source span has already been processed; select another span.')
            return result
        order = {row['handle']: i for i,row in enumerate(query_paragraphs)}
        supports = []
        for item in args.get('a_supports', []):
            support = issued.get(item['span_ref'])
            if item['role'] not in ('attribution', 'citation') or support is None or support.get('negative_only'):
                raise HarnessError('Unknown typed A support')
            support_p = payload['m6']['a_paragraphs'][support['paragraph_ref']]
            if abs(order[support_p['paragraph_handle']]-order[paragraph['paragraph_handle']]) > 1:
                raise HarnessError('Typed A support is outside the selected source region')
            supports.append({'role': item['role'], 'case_id': payload['query_id'],
                             'source_hash': payload['query_source_hash'], 'source_ref': support['source_ref'],
                             'span_bytes': list(support['span_bytes']),
                             'text': _slice(rows[support['source_ref']], support['span_bytes'])})
        decision = args['decision']
        if decision == 'search_needed' and not args.get('sufficient_for_search', args['context_complete']):
            decision = 'need_more_context'
        if decision == 'no_search_needed' and not args['context_complete']:
            decision = 'need_more_context'
        result.update(proposition=anchor, source_ref=anchor['source_ref'], visible_span_bytes=[left,right],
                      a_supports=supports, decision=decision,
                      status='approved' if decision=='search_needed' else 'screened' if decision=='no_search_needed' else 'unresolved',
                      validation_message=None if decision != 'need_more_context' else 'Read more context while retaining this source span.',
                      source_need_ref='gate-'+fingerprint([BOUND_VERSION,payload['query_source_hash'],paragraph['paragraph_handle'],[left,right]])[:24])
    else:
        if not suggestions:
            for ref,item in issued.items():
                if item['paragraph_ref'] == args['paragraph_ref'] and item.get('proposition_selectable',True) and not item.get('negative_only'):
                    suggestions.append((item['paragraph_ref'], {'source_ref':item['source_ref'],
                        'span_bytes':item['span_bytes'],'text':_slice(rows[item['source_ref']],item['span_bytes'])}))
                    if len(suggestions) == 3:
                        break
        result['validation_message'] = 'The quote does not identify a unique source span. Choose a literal source suggestion or an offered remaining span.'
        result['resolution_choices'] = [{'paragraph_ref': ref, **anchor} for ref,anchor in suggestions]
    return result


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
_LETTERED_ITEM = re.compile(r'(?im)^[ \t]*\([a-z]\)[ \t]+\S')


def heading_spans(raw):
    """Recognize a standalone title between prose and the next numbered paragraph."""
    matches = re.finditer(
        rb'[.!?]["\x27]?[ \t]*[\r\n]+(?P<title>[A-Z][A-Za-z ]{3,79})[ \t]*[\r\n]+\[\d{1,3}\]',
        raw,
    )
    spans = []
    for match in matches:
        title = match['title'].rstrip()
        words = title.split()
        if len(words) >= 2 and sum(word[:1].isupper() for word in words) >= 2 and all(
                word[:1].isupper() or word in (b'a', b'an', b'and', b'for', b'in', b'of', b'on', b'or', b'the', b'to')
                for word in words):
            spans.append((match.start('title'), match.start('title') + len(title)))
    return spans


def segments(payload, context=None, *, bound=False):
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
        if bound:
            for ref,paragraph in payload['m6']['a_paragraphs'].items():
                visible_text = _slice(rows[paragraph['source_ref']], paragraph['span_bytes'])
                if _LETTERED_ITEM.search(visible_text):
                    continue
                gaps = unread_spans(paragraph['span_bytes'],settled.get((payload['query_source_hash'],paragraph['paragraph_handle']),[]))
                if gaps:
                    result[f'{ref}.remaining_visible'] = {'paragraph_ref':ref,'source_ref':paragraph['source_ref'],
                        'span_bytes':list(paragraph['span_bytes']),'selected_spans':gaps,'negative_only':True,
                        'proposition_selectable':False,'preview':'All remaining shown text of this paragraph',
                        'byte_count':sum(right-left for left,right in gaps)}
    if bound and 'source_survey' in payload['m6']:
        from .citation_lookup import literal_citations
        for ref, paragraph in payload['m6']['a_paragraphs'].items():
            source = rows[paragraph['source_ref']]
            text = _slice(source, paragraph['span_bytes'])
            origin = paragraph['span_bytes'][0]
            for index, (left, right) in enumerate(literal_citations(text), 1):
                span = [origin + left, origin + right]
                result[f'{ref}.citation{index}'] = {
                    'paragraph_ref': ref, 'source_ref': source['ref'], 'span_bytes': span,
                    'preview': _slice(source, span), 'proposition_selectable': False, 'citation_cue': True}
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
        elif payload.get('m6', {}).get('source_survey', {}).get('phase') == 'retrieval':
            permits[key] = {'decision': decision, 'paragraph_ref': decision['paragraph_handle']}
    if payload.get('m6', {}).get('source_survey', {}).get('phase') == 'retrieval':
        return dict(list(permits.items())[:5])
    return permits


def survey_ready(context, paragraphs):
    progress_state = progress(context, paragraphs)
    return (progress_state['paragraphs_screened'] == progress_state['paragraphs_total']
            and progress_state['unresolved_count'] == 0)


def group_needs(context, refs, reason, paragraphs):
    if not survey_ready(context, paragraphs) or not 2 <= len(refs) <= 3 or len(set(refs)) != len(refs):
        raise HarnessError('Grouping needs two or three distinct queued needs after survey')
    decisions = context.get('source_gate', {})
    rows = [decisions.get(ref) for ref in refs]
    if any(row is None or row['status'] != 'approved' for row in rows) or not reason.strip():
        raise HarnessError('Grouping requires approved needs and source-based confirmation')
    if len({row['source_hash'] for row in rows}) != 1:
        raise HarnessError('Grouped needs must have the same canonical source')
    from .citation_lookup import explicit_citation_key
    identifiers = {key for row in rows for support in row.get('a_supports', [])
                   if support['role'] == 'citation' and (key := explicit_citation_key(support['text']))}
    if len(identifiers) > 1:
        raise HarnessError('Keep approved needs with distinct scoped citations separate')
    main = rows[0]
    main.setdefault('ungrouped_a_supports', deepcopy(main.get('a_supports', [])))
    members = [member for row, ref in zip(rows, refs) for member in row.get('group_members', [ref])]
    main['group_members'] = list(dict.fromkeys(members))
    main['group_reason'] = reason.strip()
    main['group_kind'] = 'model_confirmed'
    for ref in main['group_members']:
        if ref == refs[0]:
            continue
        row = decisions[ref]
        row.update(status='grouped', grouped_into=refs[0])
        for field in ('group_members', 'group_kind', 'group_reason'):
            row.pop(field, None)
        row['a_supports'] = [support for support in row.get('a_supports', []) if support['role'] != 'group_member']
        support = {'role': 'group_member',
                   'source_hash': row['source_hash'], 'source_ref': row['source_ref'],
                   'span_bytes': row['proposition']['span_bytes'], 'text': row['proposition']['text']}
        main.setdefault('group_context', []).append(support)


def evaluate_batch(payload, items, paragraphs):
    if not 1 <= len(items) <= 3:
        raise HarnessError('Survey accepts one to three decisions')
    assessments = [evaluate_bound(payload, item, paragraphs) for item in items]
    for index, current in enumerate(assessments):
        a, b = current['visible_span_bytes']
        for previous in assessments[:index]:
            c, d = previous['visible_span_bytes']
            if max(a, c) < min(b, d):
                raise HarnessError('Batch decisions must address distinct nonoverlapping spans')
    return assessments


def group_exact_citations(context, paragraphs, query_case, raw_reader):
    if not survey_ready(context, paragraphs):
        return
    from .citation_lookup import approved_citation
    groups = {}
    for ref, row in context.get('source_gate', {}).items():
        if row['status'] != 'approved':
            continue
        need = {'source_bound': True, 'a_anchor': row['proposition'],
                'a_supports': row.get('a_supports', []),
                'a_sources': [{'case_id': query_case, 'source_hash': row['source_hash']}]}
        match = approved_citation(need, raw_reader)
        if match is None:
            continue
        key, citation = match
        # Shared scoped citation ref is required, so adjacent quotation blocks
        # carrying separate authorities cannot collapse through topic overlap.
        identity = key, tuple(citation['span_bytes']), row['source_hash']
        if identity not in groups:
            groups[identity] = ref
            continue
        main_ref = groups[identity]
        main = context['source_gate'][main_ref]
        main.setdefault('ungrouped_a_supports', deepcopy(main.get('a_supports', [])))
        main['group_members'] = list(dict.fromkeys([*main.get('group_members', [main_ref]), ref]))
        main['group_reason'] = 'The approved spans share one exact scoped citation.'
        main.setdefault('group_kind', 'exact_citation')
        row.update(status='grouped', grouped_into=main_ref)


def authorized(context, need_id):
    return bool(need_id) and need_id in context.get('source_gate_searches', {})


def _settled_spans(context):
    spans = {}
    for row in context.get('source_gate', {}).values():
        if row['status'] in ('screened', 'approved', 'searched', 'deferred', 'search_deferred', 'grouped'):
            key = row['source_hash'], row['paragraph_handle']
            spans.setdefault(key, []).extend(row.get('settled_spans') or [row['proposition']['span_bytes'] if row.get('proposition') else row['visible_span_bytes']])
    return spans


def screening_choices(payload, context):
    """A narrower view of a settled paragraph adds no screening work."""
    evaluated = _settled_spans(context)
    return [ref for ref, row in payload['m6']['a_paragraphs'].items()
            if unread_spans(row['span_bytes'], evaluated.get((row['source_hash'], row['paragraph_handle']), []))]


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


def unscreened_spans(context, source_hash, paragraphs):
    settled = _settled_spans(context)
    return [gap for paragraph in paragraphs
            for gap in unread_spans(paragraph['span_bytes'],
                                    settled.get((source_hash, paragraph['handle']), []))]


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
