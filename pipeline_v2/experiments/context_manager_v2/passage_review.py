"""Bounded passage review for the dual-query CM4 experiment."""
from copy import deepcopy
from hashlib import sha256
import re

from pipeline_v2.agent_harness import SourceExcerpt, ToolResult
from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint, encode
from pipeline_v2.agent_harness.evidence import SourceDrift, normalize_result, source_record
from pipeline_v2.agent_harness.assessment import validate_assessment_state

VERSION = 'cm4-passage-review-v4'
IDENTITY_RELATIONS = {
    'same_decision': ('select', 'confirmed_identity'),
    'different_decision': ('not_select', 'different_decision'),
    'insufficient_evidence': ('not_select', 'insufficient_identity'),
}
ACTIONS = {'open_candidate_passages', 'conclude_candidate', 'request_identity_check', 'revisit_case_passage', 'read_candidate_identity',
           'read_passage_attribution', 'read_query_citation_context', 'return_to_candidates'}


def enabled(query):
    return query is not None and query.get('passage_review', False)


def hit_id(hit):
    return hit.get('hit_ref') or 'hit-' + fingerprint([
        hit['case_id'], hit['source_hash'], hit['span_bytes']])[:20]


def conclusions(context, query):
    return context.get('candidate_conclusions', {}).get(query['query_id'], {})


def case_done(context, query, case):
    return case in conclusions(context, query)


def _case_assessment(query, case, decision):
    return {'source_need_id': query['need_id'], 'candidate_id': case,
            'case_relation': 'supported' if decision['decision'] == 'select' else 'similarity_only',
            'passage_location': 'pinpoint', 'reason': decision['reason'],
            'a_context_refs': decision['a_refs'], 'b_passage_refs': decision['b_refs'],
            'identity_support_refs': decision.get('identity_refs', []),
            'speaker_evidence_refs': [], 'quote_chain_refs': [], 'container_refs': []}


def _raw(engine, case, digest):
    raw = engine.store.raw_reader(case)
    if sha256(raw).hexdigest() != digest:
        raise SourceDrift(case)
    return raw


def _span(raw, start, end):
    start, end = max(0, start), min(len(raw), end)
    while start > 0 and start < len(raw) and raw[start] & 0xc0 == 0x80:
        start -= 1
    while end > start and end < len(raw) and raw[end] & 0xc0 == 0x80:
        end -= 1
    return [start, end]


def _record(engine, case, digest, span, label):
    raw = _raw(engine, case, digest)
    left, right = _span(raw, *span)
    if left >= right:
        raise HarnessError('Reading target is empty')
    text = raw[left:right]
    value = SourceExcerpt(case, digest, (left, right), text.decode('utf-8'),
                          sha256(text).hexdigest(), provenance={
                              'extraction_method': VERSION, 'source_label': label,
                              'semantic_status': 'unverified'})
    record = source_record(value, overlay=True)
    return record


def _merge(spans):
    result = []
    for left, right in sorted(spans):
        if result and left < result[-1][1]:
            result[-1][1] = max(result[-1][1], right)
        else:
            result.append([left, right])
    return result


def _contains(span, ranges):
    at = span[0]
    for left, right in sorted(tuple(span) for span in ranges):
        if left > at:
            break
        at = max(at, right)
    return at >= span[1]


def _gaps(span, ranges):
    cursor, end = span
    result = []
    for left, right in sorted(tuple(value) for value in ranges):
        if right <= cursor or left >= end:
            continue
        if left > cursor:
            result.append([cursor,min(left,end)])
        cursor = max(cursor,right)
    if cursor < end:
        result.append([cursor,end])
    return result


def _unique_rows(engine, rows):
    result = []
    groups = {}
    for row in rows:
        groups.setdefault((row['case_id'],row['source_hash']),[]).append(row)
    for (case,digest), records in groups.items():
        for span in _merge([row['span_bytes'] for row in records]):
            labels = list(dict.fromkeys(row['provenance']['source_label'] for row in records
                         if max(span[0],row['span_bytes'][0]) < min(span[1],row['span_bytes'][1])))
            result.append(_record(engine,case,digest,span,'; '.join(labels)))
    return result


def delivered(engine, case, digest):
    ranges = []
    events = engine.events()
    requests = {row['request_id']: row for row in events if row['kind'] == 'request_admitted'}
    for event in events:
        if event['kind'] != 'request_result' or not event.get('received_response'):
            continue
        admission = requests[event['request_id']]
        ranges.extend(row['span_bytes'] for row in admission['excerpts']
                      if row['ref'] in admission['current_payload_source_refs']
                      and row['case_id'] == case and row['source_hash'] == digest)
    return ranges


def _intro(engine, case, digest, *, identity_first=False):
    raw = _raw(engine, case, digest)
    text = raw.decode('utf-8')
    boundary = re.search(r'(?m)^\s*\[(?!\d{4}\])\d+\]', text)
    header_end = boundary.start() if boundary else min(len(text), 4000)
    sections = []
    if identity_first:
        sections.append(_record(engine, case, digest, _opening_context(raw),
                                'Literal candidate opening for checking B identity; match unverified'))
    if text[:header_end].strip():
        end = len(text[:header_end].encode('utf-8'))
        sections.append(_record(engine, case, digest, [0, min(end, 1024)],
                                'Literal candidate opening; observed identity fields require semantic checking'))
    summary = re.search(r'(?im)^\s*Summary\s*:\s*', text[:header_end])
    if summary:
        value = text[summary.end():header_end]
        stop = re.search(
            r'(?im)^[ \t]*(?:Counsel|Solicitors of Record|Cases Cited)[ \t]*:'
            r'|^[ \t]*[^\r\n.!?]{1,100} [–-] Topic \d+(?:\.\d+)?[ \t]*\r?$'
            r'|[ \t]+[–-] Topic \d+(?:\.\d+)?[ \t]*\r?$', value)
        value = (value[:stop.start()] if stop else value).rstrip()
        if (value.strip().replace('<FRAGMENT_SUPPRESSED>', '').strip()
                and not re.search(r'(?i)contains? no summary|no summary (?:is )?(?:available|provided)', value)):
            left = len(text[:summary.end()].encode('utf-8'))
            right = left + len(value.encode('utf-8'))
            sections.append(_record(engine, case, digest, [left, min(right, left + 1400)],
                                    'Literal Summary before Topic; section origin verified, meaning unverified'))
            return sections
    start = header_end
    background = re.search(r'(?im)^\s*(?:Background|Facts|Contexte|Les faits)\s*:?\s*$', text[start:start + 6000])
    if background:
        start += background.end()
        label = 'Literal Background excerpt, automatically selected; meaning unverified'
    else:
        label = 'Literal opening paragraph excerpt, automatically selected; meaning unverified'
    left = len(text[:start].encode('utf-8'))
    if left < len(raw):
        sections.append(_record(engine, case, digest, [left, min(len(raw), left + 900)], label))
    return sections


def identity_regions(raw):
    """Find literal identity lines in the preamble, before quoted/body material."""
    limit = _span(raw, 0, min(len(raw), 8192))[1]
    text = raw[:limit].decode('utf-8')
    boundary = re.search(
        r'(?im)^[ \t]*(?:\[(?!\d{4}\])\d+\]|'
        r'(?:summary|sommaire|résumé|counsel|avocats?|solicitors of record|'
        r'cases cited|authorities cited|jurisprudence citée|statutes cited)'
        r'(?:[ \t]*:|[ \t]*\r?$))', text)
    header = text[:boundary.start()] if boundary else text
    court = re.compile(
        r'(?:Federal Court(?: of Appeal)?|Supreme Court of Canada|'
        r'Cour fédérale|Cour d[’\x27]appel fédérale|Cour suprême du Canada)', re.I)
    citation = re.compile(
        r'(?:(?:\[)?(?:19|20)\d{2}(?:\])?\s+(?:FC|FCA|CF|CAF|SCC|CSC)\s+\d+|'
        r'\[(?:19|20)\d{2}\]\s*F\.?\s*C\.?\s*J\.?\s*No\.?\s*\d+|'
        r'\d+\s+(?:N\.?\s*R\.?|F\.?\s*T\.?\s*R\.?)\s+\d+)[.]?', re.I)
    labelled = re.compile(
        r'(?:Indexed As|Intitulé|Docket(?: No\.?)?|Dossier|Court File(?: No\.?)?|'
        r'Citation|Référence|Date(?: of (?:Judgment|Decision))?|Date du jugement)\s*:\s*\S.+', re.I)
    date = re.compile(
        r'(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+\d{1,2},\s+(?:19|20)\d{2}|'
        r'\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)'
        r'\s+(?:19|20)\d{2})[.]?', re.I)
    result = []
    char_offset = 0
    for line in header.splitlines(keepends=True):
        value = line.strip()
        if '<FRAGMENT_SUPPRESSED>' not in value and any(
                pattern.fullmatch(value) for pattern in (court, citation, labelled, date)):
            start = char_offset + len(line) - len(line.lstrip())
            end = start + len(value)
            result.append([len(text[:start].encode('utf-8')), len(text[:end].encode('utf-8'))])
        char_offset += len(line)
    return result


def targets(engine, query, case):
    hits = [hit for hit in query['hits'] if hit['case_id'] == case]
    digest = hits[0]['source_hash']
    raw = _raw(engine, case, digest)
    for hit in hits:
        left, right = hit['span_bytes']
        if hit['source_hash'] != digest or not 0 <= left < right <= len(raw):
            raise HarnessError('Retrieved passage is outside its canonical candidate source')
        raw[left:right].decode('utf-8')
    spans = _merge([_span(raw, hit['span_bytes'][0] - 180, hit['span_bytes'][1] + 180) for hit in hits])
    return [_record(engine, case, digest, span, 'Retrieved passage and adjacent source context') for span in spans]


def _opening_context(raw):
    return _span(raw, 0, min(len(raw), 900))


def _self_identity_spans(raw):
    # The opening is context to inspect even when no metadata line was recognized.
    return [_opening_context(raw), *identity_regions(raw)]


def _identity_role_refs(rows, query, qcase, case, identities):
    anchor = query['source_need'].get('a_anchor') or query['source_need']['a_sources'][0]
    a_windows = [anchor['span_bytes'], *(s['span_bytes'] for s in query['source_need'].get('a_supports', []))]
    hits = [hit['span_bytes'] for hit in query['hits'] if hit['case_id'] == case]

    def overlaps(span, windows):
        return any(max(span[0], left) < min(span[1], right) for left, right in windows)

    return {
        'a_refs': [r['ref'] for r in rows if r['case_id'] == qcase
                   and (overlaps(r['span_bytes'], a_windows)
                        or ('read_query_citation_context' in r['provenance'].get('source_label', '')
                            and overlaps(r['span_bytes'], [[anchor['span_bytes'][0] - 1200,
                                                            anchor['span_bytes'][1] + 1200]])))],
        'b_identity_refs': [r['ref'] for r in rows if r['case_id'] == case
                            and any(_contains(r['span_bytes'], [span]) for span in identities)],
        'b_rule_refs': [r['ref'] for r in rows if r['case_id'] == case and overlaps(r['span_bytes'], hits)],
    }


def _target(engine, query, case, kind, span):
    digest = (engine.harness.identity.query_source_hash if case == engine.harness.identity.query_id
              else next(hit['source_hash'] for hit in query['hits'] if hit['case_id'] == case))
    return {'case_id': case, 'source_hash': digest, 'span_bytes': span, 'kind': kind,
            'query_id': query['query_id']}


def _identity_view(engine, state, context, query, packet):
    if packet['query_id'] != query['query_id'] or packet['case_id'] != context['passage_session']['candidate_id']:
        raise HarnessError('Identity packet belongs to a different query or candidate')
    rows = deepcopy(packet['rows'])
    for row in rows:
        engine.store.verify(row)
    def refs(values):
        return {'type': 'array', 'items': {'type': 'string', 'enum': values}, 'maxItems': len(values)}
    fields = {'decision': {'type': 'string', 'enum': ['select', 'not_select']},
              'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240},
              'disposition': {'type': 'string', 'enum': ['confirmed_identity', 'different_decision', 'insufficient_identity']},
              'bridge': {'type': 'string', 'maxLength': 240},
              'a_refs': refs(packet['a_refs']), 'b_refs': refs(packet['b_rule_refs']),
              'identity_refs': refs(packet['b_identity_refs'])}
    if getattr(engine, 'survey_first', False):
        fields.pop('decision')
        fields.pop('disposition')
        fields['identity_relation'] = {'type': 'string', 'enum': list(IDENTITY_RELATIONS)}
        fields['a_refs']['minItems'] = 1
        fields['identity_refs']['minItems'] = 1
    tools = [{'name': 'conclude_candidate', 'description':
              'Decide only whether the authority cited by A is this decision B. Identify an independent identity bridge. '
              'A shared legal rule or B quoting another case is insufficient. Return not_select if this packet is insufficient.',
              'parameters': {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}}]
    if getattr(engine, 'survey_first', False):
        tools[0]['description'] = (
            'Compare A authority with B itself. Return same_decision only with a specific identity bridge, '
            'after checking visible court, date, docket and outcome contradictions. Return different_decision '
            'for evidence of another decision, or insufficient_evidence when the bridge is missing. '
            'Use refs on both sides and explain the match, contradiction or missing fact briefly. '
            'A shared rule or B quoting another case does not establish identity. The host maps your label to a conclusion.')
    feedback = {'guidance': tools[0]['description'], 'next_options': ['conclude_candidate']}
    payload = engine._payload_base(state, rows, [], feedback)
    payload['available_tools'] = tools
    payload['m6'] = {'cm_context': {'need_id': query['need_id'], 'candidate_id': packet['case_id'], 'mode': 'identity_check'},
                     'query_review': {'query_id': query['query_id']},
                     'identity_check': {'packet_id': packet['packet_id'], 'roles': {
                         key: packet[key] for key in ('a_refs', 'b_identity_refs', 'b_rule_refs')}}}
    return payload, {'type': 'object', 'anyOf': [engine._branch('conclude_candidate', fields)]}, {}, rows


def compile_view(engine, state, context, query, byte_limit):
    """Build only source text and valid choices; retrieval scores stay outside."""
    from . import query_review
    local = context.get('passage_session', {})
    if local.get('identity_packet') and not case_done(context, query, local.get('candidate_id')):
        return _identity_view(engine, state, context, query, local['identity_packet'])
    active_case = local.get('candidate_id')
    rows, handles, tools, branches = [], {}, [], []
    def add(name, fields, description):
        tools.append({'name': name, 'description': description,
                      'parameters': {'type': 'object', 'properties': fields,
                                     'required': list(fields), 'additionalProperties': False}})
        branches.append(engine._branch(name, fields))
    def choice(values):
        return {'type': 'string', 'enum': list(values)}
    def references(values):
        values = list(dict.fromkeys(values))
        return {'type': 'array', 'items': choice(values), 'maxItems': len(values)}
    cases = sorted(query['candidate_ids'])
    seen = set(query['survey_exposed'])
    offset = local.get('survey_offset', 0)
    cards = []
    next_unseen_page = None
    unseen_after_page = set(cases) - seen
    if not active_case:
        for case in cases[offset:offset + engine.page_size]:
            hits = [hit for hit in query['hits'] if hit['case_id'] == case]
            first = min(hits, key=lambda hit: hit['span_bytes'][0])
            received = delivered(engine, case, first['source_hash'])
            values = conclusions(context, query)
            cards.append({'case_id': case, 'passage_count': len(hits),
                          'preview': engine._survey_preview(first),
                          'review_complete': case_done(context, query, case),
                          'passages_received': sum(_contains(hit['span_bytes'], received) for hit in hits),
                          'conclusion_status': 'final' if case in values else 'pending',
                          'decision': values.get(case, {}).get('decision', 'not_select'),
                          'selected': values.get(case, {}).get('decision') == 'select'})
        unseen_after_page.difference_update(card['case_id'] for card in cards)
        unseen = next((i for i, case in enumerate(cases) if case in unseen_after_page), None)
        pages = {}
        page_offsets = []
        if offset > 0:
            page_offsets.append(max(0,offset-engine.page_size))
        if offset+engine.page_size < len(cases):
            page_offsets.append(offset+engine.page_size)
        if unseen is not None:
            page_offsets.append((unseen//engine.page_size)*engine.page_size)
        for index in sorted(set(page_offsets)):
            if index != offset:
                ref = 'page-' + fingerprint([query['query_id'], index])[:16]
                handles[ref] = {'kind': 'survey_page', 'offset': index}
                pages[ref] = index
                if unseen is not None and index == (unseen // engine.page_size) * engine.page_size:
                    next_unseen_page = ref
        if pages:
            add('show_context_page', {'page_ref': choice(pages)},
                'View another candidate page. Use next_unseen_page to reach candidate cards not yet shown.')
        options = {}
        for card in cards:
            if getattr(engine, 'survey_first', False) and card['review_complete']:
                continue
            ref = 'case-' + fingerprint([query['query_id'], card['case_id']])[:16]
            handles[ref] = {'kind': 'candidate', 'case_id': card['case_id']}
            options[ref] = card['case_id']
            card['candidate_ref'] = ref
        if options:
            add('open_candidate_passages', {'candidate_ref': choice(options)},
                'Open or resume a candidate and its grouped passages from this search. Choose how much to read; completed candidates may be revisited.')
        if not unseen_after_page:
            add('conclude_search_query', {'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}},
                'Conclude after seeing the shortlist. Unread or unfinished cases stay pending.')
    hit_view = []
    if active_case:
        case = active_case
        qcase, qdigest = engine.harness.identity.query_id, engine.harness.identity.query_source_hash
        anchor = query['source_need'].get('a_anchor') or query['source_need'].get('a_sources', [{}])[0]
        if not anchor.get('span_bytes'):
            raise HarnessError('Passage review requires the canonical query anchor span')
        arow = _record(engine, qcase, qdigest, anchor['span_bytes'], 'Literal query proposition')
        rows.append(arow)
        for support in query['source_need'].get('a_supports', []):
            row = _record(engine, qcase, qdigest, support['span_bytes'],
                          'Literal query support: ' + support['role'])
            if (support['case_id'] != qcase or support['source_hash'] != qdigest
                    or support['text'] != row['text']):
                raise HarnessError('Query support differs from the approved source')
            rows.append(row)
        primary_row = len(rows)
        identity_enabled = getattr(engine, 'identity_check_enabled', False)
        all_regions = targets(engine, query, case)
        extra = local.get('extra_target')
        if extra:
            regions = [_record(engine, extra['case_id'], extra['source_hash'], extra['span_bytes'], extra['kind'])]
        else:
            regions = all_regions
        region_index = local.get('region_index', 0) if not extra else 0
        region_index = min(region_index, len(regions) - 1)
        record = regions[region_index]
        left, right = record['span_bytes']
        cursor = local.get('extra_cursor',left) if extra else local.get('cursor', left)
        cursor = min(max(cursor, left), right)
        end = min(right, cursor + byte_limit)
        rows.append(_record(engine, record['case_id'], record['source_hash'], [cursor, end],
                            record['provenance']['source_label']))
        if extra:
            primary = all_regions[min(local.get('region_index',0),len(all_regions)-1)]
            at = local.get('cursor',primary['span_bytes'][0])
            rows.append(_record(engine,case,primary['source_hash'],
                                [at,min(primary['span_bytes'][1],at+byte_limit)],
                                'Retrieved passage for comparison with additional evidence'))
        for ref in local.get('support_refs',[]):
            if ref in state.catalog:
                rows.append(deepcopy(state.catalog[ref]))
        if not extra:
            digest = next(h['source_hash'] for h in query['hits'] if h['case_id']==case)
            rows.extend(_intro(engine, case, digest, identity_first=identity_enabled))
        # A compact single window is the minimum payload. Larger budgets include all merged regions.
        if not extra and cursor == left and sum(r['span_bytes'][1]-r['span_bytes'][0] for r in all_regions) <= byte_limit:
            rows[primary_row:primary_row + 1] = all_regions
        rows = _unique_rows(engine,rows)
        digest = next(h['source_hash'] for h in query['hits'] if h['case_id']==case)
        raw = _raw(engine, case, digest)
        identity_spans = _self_identity_spans(raw) if identity_enabled else []
        if identity_enabled:
            visible_b = [r['span_bytes'] for r in rows if r['case_id'] == case]
            existing_spans = {tuple(span) for span in visible_b}
            for span in identity_spans[:6]:
                key = tuple(span)
                if key not in existing_spans and _contains(span, visible_b):
                    rows.append(_record(engine, case, digest, span,
                                        'Literal candidate self-identity context; match unverified'))
                    existing_spans.add(key)
        rows = [deepcopy(state.catalog.get(row['ref'], row)) for row in rows]
        ranges = delivered(engine, case, digest)
        ranges += [r['span_bytes'] for r in rows if r['case_id'] == case]
        b_refs = [r['ref'] for r in rows if r['case_id'] == case]
        conclusion = conclusions(context, query).get(case)
        for hit in sorted(query['hits'], key=lambda row: (row['case_id'], row['span_bytes'], hit_id(row))):
            if hit['case_id'] == case:
                hit_view.append({'hit_ref': hit_id(hit), 'source_span': hit['span_bytes'],
                                 'read_complete': _contains(hit['span_bytes'], ranges)})
        if conclusion is None:
            # xgrammar rejects uniqueItems; execute() validates duplicate refs.
            add('conclude_candidate', {
                'decision': choice(('not_select',) if identity_enabled else ('select', 'not_select')),
                'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240},
                'a_refs': references(r['ref'] for r in rows if r['case_id'] == qcase),
                'b_refs': references(b_refs),
                'identity_refs': references(r['ref'] for r in rows)},
                'Finalize not_select once for this search after your identity review. If evidence is still missing and you want to keep checking, read more or leave temporarily.'
                if identity_enabled else 'Finalize this candidate once for this search with current evidence.')
            role_refs = _identity_role_refs(rows, query, qcase, case, identity_spans)
            if identity_enabled and all(role_refs.values()):
                add('request_identity_check', {role: {**references(refs), 'minItems': 1}
                                               for role, refs in role_refs.items()},
                    'After reading, request one identity-only decision using A authority context, B self-identity and B rule context. '
                    'Choose received evidence for all three roles. No proposed select reason is supplied.')
        reading = {}
        if extra and end < right:
            ref = 'continue-' + fingerprint([query['query_id'],extra,end])[:16]
            handles[ref] = {'kind':'extra_continuation','cursor':end}
            reading[ref] = record['span_bytes']
        for i, region in enumerate(all_regions):
            visible = _contains(region['span_bytes'], [r['span_bytes'] for r in rows if r['case_id'] == case])
            reload_region = not visible and (extra or i != region_index)
            if reload_region or not _contains(region['span_bytes'], ranges):
                at = region['span_bytes'][0]
                if not extra and i == region_index and not reload_region:
                    at = end
                if at >= region['span_bytes'][1]:
                    continue
                ref = 'continue-' + fingerprint([query['query_id'],case,i,at])[:16]
                handles[ref] = {'kind':'continuation','region_index':i,'cursor':at}
                reading[ref] = region['span_bytes']
        if reading:
            add('continue_raw_evidence', {'context_ref': choice(reading)}, 'Continue or revisit another source region in this candidate group.')
        add('return_to_candidates', {'reason': {'type': 'string', 'minLength': 4, 'maxLength': 240}},
            'Leave this candidate at any time. Reading position is saved; leaving does not finalize a pending candidate.')
        add('read_case_passages', {'focus':{'type':'string','minLength':4,'maxLength':160}},
            'Search for a different legal phrase inside the current candidate case.')
        revisit = {}
        for target in local.get('search_revisit_targets', []):
            if target['query_id'] != query['query_id'] or target['case_id'] != case or target['source_hash'] != digest:
                raise HarnessError('Within-case revisit target belongs to a different source')
            ref = 'revisit-' + fingerprint(target)[:16]
            handles[ref] = target
            revisit[ref] = target['span_bytes']
        if revisit:
            add('revisit_case_passage', {'target_ref': choice(revisit)},
                'Intentionally reopen a previously received within-case search hit. This is not new source coverage.')
        primary = all_regions[min(local.get('region_index',0),len(all_regions)-1)]
        primary_left, primary_right = primary['span_bytes']
        purpose = {
            'read_passage_attribution': (case, _span(raw, primary_left-1200,primary_right+1200)),
            'read_query_citation_context': (qcase, _span(_raw(engine,qcase,qdigest),anchor['span_bytes'][0]-1200,anchor['span_bytes'][1]+1200)),
        }
        for kind,(target_case,span) in purpose.items():
            target = _target(engine,query,target_case,
                             'Literal context before/after passage (within approximately 1200 bytes); speaker and quote source unverified'
                             if kind == 'read_passage_attribution' else kind,span)
            current = [r['span_bytes'] for r in rows if r['case_id']==target_case]
            prior = delivered(engine,target_case,target['source_hash']) + current
            gaps = _gaps(span,prior)
            if not gaps and kind == 'read_query_citation_context' and identity_enabled:
                gaps = _gaps(span, current)
            if not gaps:
                continue
            target['span_bytes'] = gaps[0]
            ref = 'target-' + fingerprint(target)[:16]
            handles[ref] = target
            add(kind, {'target_ref':choice([ref])},
                'Read before/after passage context so you can check speaker and quotation source; the host expands approximately 1200 bytes and does not identify attribution semantically.'
                if kind == 'read_passage_attribution' else 'Read literal context around the query citation; meaning remains to be checked.')
        identity_options = []
        prior_identity = [row['span_bytes'] for row in rows if row['case_id'] == case]
        if not identity_enabled:
            prior_identity += delivered(engine, case, digest)
        for span in identity_spans if identity_enabled else identity_regions(raw):
            if _contains(span, prior_identity):
                continue
            target = _target(engine, query, case,
                             'Literal candidate opening or preamble line; self-identity match unverified', span)
            ref = 'identity-' + fingerprint(target)[:16]
            handles[ref] = target
            identity_options.append(ref)
        if identity_options:
            add('read_candidate_identity', {'target_ref': choice(identity_options)},
                'Read or reopen the candidate opening or a preamble line to check which decision B itself is.')
    feedback = {'guidance': ('Choose a candidate to open directly, view another candidate page, or conclude this search.' if not active_case else
                             'Read this candidate group and decide when to finalize once, or return temporarily at any time. Reading depth is your decision. A final conclusion is locked even if you read more.'),
                'last_action':engine._feedback(context)['last_action'],
                'next_options':[tool['name'] for tool in tools]}
    if active_case and identity_enabled and conclusion is None:
        feedback['guidance'] = (
            'Check identity first: compare the authority cited by A with the opening and other evidence identifying B itself. '
            'Opening and preamble excerpts are clues. If the bridge is unclear, read more or leave this candidate pending. '
            'When ready to select, request the final identity check.')
    if not active_case and next_unseen_page:
        feedback['guidance'] = (
            f'{len(unseen_after_page)} candidate cards remain on unseen pages. '
            'Open a displayed candidate or use show_context_page with next_unseen_page before concluding.')
    if local.get('last_read_feedback'):
        feedback['last_read_feedback'] = local['last_read_feedback']
    payload = engine._payload_base(state, rows, [], feedback)
    payload['m6'] = {'cm_context':{'need_id':query['need_id'],'candidate_id':active_case,'mode':'assessment' if active_case else 'results'},
                     'query_review':{'query_id':query['query_id']},
                     'cm_page':{'candidates':cards}, 'passages':hit_view,
                     'reading_options':{ref:value for ref,value in handles.items() if value.get('kind')!='candidate'}}
    payload['m6']['candidate_navigation'] = {'total': len(cases), 'offset': offset,
                                            'cards_received': len(seen), 'cards_unseen': len(set(cases)-seen)}
    if not active_case:
        payload['m6']['candidate_navigation'].update(
            unseen_after_this_page=len(unseen_after_page), next_unseen_page=next_unseen_page,
            cases_pending=sum(not case_done(context, query, case) for case in cases))
    if active_case:
        conclusion = conclusions(context, query).get(active_case)
        payload['m6']['candidate_progress'] = {
            'case_id': active_case, 'passage_count': len(hit_view),
            'passages_read_complete': sum(hit['read_complete'] for hit in hit_view),
            'conclusion_status': 'final' if conclusion else 'pending',
            'decision': conclusion['decision'] if conclusion else 'not_select',
            'conclusion': deepcopy(conclusion)}
    if local.get('search_feedback'):
        payload['m6']['within_case_search'] = deepcopy(local['search_feedback'])
    payload['available_tools'] = tools
    return payload, {'type':'object','anyOf':branches}, handles, rows


def execute(engine, db, state, context, query, action, manifest, action_id):
    name, args = action['action'], action['args']
    local = context.setdefault('passage_session', {})
    local.pop('last_read_feedback', None)
    accepted, invalidated = [], []
    if name == 'show_context_page':
        local['survey_offset'] = manifest['handles'][args['page_ref']]['offset']
    elif name == 'open_candidate_passages':
        case = manifest['handles'][args['candidate_ref']]['case_id']
        if getattr(engine, 'survey_first', False) and case_done(context, query, case):
            raise HarnessError('Candidate conclusion is already final and locked')
        offset = local.get('survey_offset', 0)
        saved = context.get('passage_positions', {}).get(query['query_id'], {}).get(case, {})
        local.clear()
        local.update(deepcopy(saved))
        local.update(candidate_id=case, survey_offset=offset)
        local.setdefault('region_index', 0)
        local.pop('leave_reason', None)
        context.update(candidate_id=case,mode='assessment',stage='reading')
    elif name == 'return_to_candidates':
        if not args['reason'].strip():
            raise HarnessError('Leaving a candidate needs a nonblank reason')
        case = local['candidate_id']
        saved = deepcopy(local)
        saved['leave_reason'] = args['reason']
        context.setdefault('passage_positions', {}).setdefault(query['query_id'], {})[case] = saved
        offset = local.get('survey_offset', 0)
        local.clear()
        local['survey_offset'] = offset
        context.update(candidate_id=None, mode='results', stage='ready')
    elif name == 'continue_raw_evidence':
        target=manifest['handles'][args['context_ref']]
        if target['kind']=='extra_continuation':
            local['extra_cursor']=target['cursor']
        else:
            if local.get('extra_target'):
                extra=local['extra_target']
                supporting=[row['ref'] for row in manifest['excerpts']
                            if row['case_id']==extra['case_id']
                            and max(row['span_bytes'][0],extra['span_bytes'][0]) < min(row['span_bytes'][1],extra['span_bytes'][1])]
                local['support_refs']=list(dict.fromkeys([*local.get('support_refs',[]),*supporting]))[-3:]
            local.pop('extra_target',None)
            local.pop('extra_cursor',None)
            local.update(region_index=target['region_index'],cursor=target['cursor'])
    elif name in ('read_candidate_identity','read_passage_attribution','read_query_citation_context'):
        local['extra_target']=deepcopy(manifest['handles'][args['target_ref']])
        local.pop('extra_cursor',None)
    elif name == 'revisit_case_passage':
        target = manifest['handles'].get(args['target_ref'], {})
        case = local['candidate_id']
        digest = next(h['source_hash'] for h in query['hits'] if h['case_id'] == case)
        if (target not in local.get('search_revisit_targets', []) or target.get('case_id') != case
                or target.get('source_hash') != digest or target.get('query_id') != query['query_id']):
            raise HarnessError('Revisit target outside current candidate search')
        _raw(engine, case, digest)
        if not _contains(target['span_bytes'], delivered(engine, case, digest)):
            raise HarnessError('Revisit target has not been received')
        local['extra_target'] = deepcopy(target)
        local.pop('extra_cursor', None)
    elif name == 'read_case_passages':
        case = local['candidate_id']
        if len(args['focus'].split()) < 2:
            raise HarnessError('Within-case reading needs at least two words')
        digest = next(row['source_hash'] for row in query['hits'] if row['case_id'] == case)
        raw = _raw(engine, case, digest)
        result = engine.harness.m3.search_case({'case_id': case, 'text': args['focus'], 'limit': 3})
        prior = delivered(engine, case, digest)
        old, fresh = [], []
        for hit in result.observation.get('hits', [])[:3]:
            span = hit.get('span_bytes')
            if not span:
                continue
            if (hit.get('case_id', case) != case or hit.get('source_hash', digest) != digest
                    or len(span) != 2 or any(type(at) is not int for at in span)
                    or not 0 <= span[0] < span[1] <= len(raw)):
                raise HarnessError('Within-case search returned a different candidate source or invalid span')
            raw[span[0]:span[1]].decode('utf-8')
            target = _target(engine, query, case, 'Literal within-candidate search hit; meaning unverified', list(span))
            gaps = _gaps(span, prior)
            if gaps:
                fresh.append((target, gaps))
            else:
                old.append(target)
        local['search_revisit_targets'] = old
        if fresh:
            target, gaps = fresh[0]
            local['extra_target'] = target
            local['extra_cursor'] = gaps[0][0]
            local['search_feedback'] = {'status': 'new_content', 'span_bytes': target['span_bytes'],
                                        'new_spans': gaps, 'new_bytes': sum(r-l for l,r in gaps),
                                        'note': 'Located source bytes not yet received at search time. Delivery is counted only after the next payload receipt; legal relevance remains unverified.'}
        else:
            local['search_feedback'] = {'status': 'already_read' if old else 'no_hits',
                                        'new_spans': [], 'new_bytes': 0,
                                        'note': 'Use an explicit revisit target to reopen an old hit.' if old else 'No matching passage found inside the current candidate.'}
    elif name == 'request_identity_check':
        case = local.get('candidate_id')
        if not getattr(engine, 'identity_check_enabled', False) or case_done(context, query, case):
            raise HarnessError('Identity check unavailable for this candidate')
        if local.get('identity_packet'):
            raise HarnessError('Identity packet is already frozen')
        roles = {'a_refs': engine.harness.identity.query_id, 'b_identity_refs': case, 'b_rule_refs': case}
        for key, side in roles.items():
            if not args[key] or len(args[key]) != len(set(args[key])):
                raise HarnessError('Identity check needs nonempty distinct references for all three roles; read missing evidence first')
            for ref in args[key]:
                row = state.current_records.get(ref)
                if row is None or row['case_id'] != side or ref not in state.delivered:
                    raise HarnessError('Identity check evidence must be received in the current pair')
                engine.store.verify(row)
        digest = next(h['source_hash'] for h in query['hits'] if h['case_id'] == case)
        role_refs = _identity_role_refs(state.current_records.values(), query, engine.harness.identity.query_id,
                                        case, _self_identity_spans(_raw(engine, case, digest)))
        for role, allowed in role_refs.items():
            if not set(args[role]) <= set(allowed):
                raise HarnessError(f'Invalid identity packet role {role}; read the corresponding source context first')
        packet = {**deepcopy(args), 'query_id': query['query_id'], 'case_id': case,
                  'rows': [deepcopy(state.current_records[ref]) for ref in dict.fromkeys(
                      args['a_refs'] + args['b_identity_refs'] + args['b_rule_refs'])]}
        packet['packet_id'] = fingerprint(packet)
        payload, _, _, _ = _identity_view(engine, state, context, query, packet)
        if engine.harness._count(encode(payload)) > engine.harness.budget.max_payload_tokens:
            raise HarnessError('Identity packet exceeds payload budget; choose shorter source evidence before entering the check')
        local['identity_packet'] = packet
    elif name == 'conclude_candidate':
        case = local.get('candidate_id')
        if case not in query['candidate_ids']:
            raise HarnessError('No active candidate from this search')
        if case_done(context, query, case):
            raise HarnessError('Candidate conclusion is already final and locked')
        packet = local.get('identity_packet')
        if getattr(engine, 'survey_first', False) and packet:
            relation = args.get('identity_relation')
            if relation not in IDENTITY_RELATIONS or 'decision' in args or 'disposition' in args:
                raise HarnessError('Identity conclusion requires a valid relation label')
            if not args.get('a_refs') or not args.get('identity_refs') or not args.get('bridge', '').strip():
                raise HarnessError('Identity relation requires both evidence sides and a comparison')
            decision, disposition = IDENTITY_RELATIONS[relation]
            args = {**args, 'decision': decision, 'disposition': disposition}
        if args['decision'] not in ('select', 'not_select') or not args['reason'].strip():
            raise HarnessError('Candidate conclusion needs a valid decision and reason')
        packet = local.get('identity_packet')
        if getattr(engine, 'identity_check_enabled', False):
            if args['decision'] == 'select' and packet is None:
                raise HarnessError('Select requires the identity-only check first')
            if packet:
                if packet['query_id'] != query['query_id'] or packet['case_id'] != case:
                    raise HarnessError('Identity packet belongs to a different query or candidate')
                for key, role in (('a_refs', 'a_refs'), ('b_refs', 'b_rule_refs'), ('identity_refs', 'b_identity_refs')):
                    if not set(args[key]) <= set(packet[role]):
                        raise HarnessError('Conclusion evidence is outside the frozen identity role')
                if args.get('disposition') not in ('confirmed_identity', 'different_decision', 'insufficient_identity'):
                    raise HarnessError('Identity check requires a disposition')
                if args['decision'] == 'select' and (args['disposition'] != 'confirmed_identity' or not args.get('bridge', '').strip()):
                    raise HarnessError('Select requires an explicit identity bridge')
                if args['decision'] == 'not_select' and args['disposition'] == 'confirmed_identity':
                    raise HarnessError('Negative identity conclusion requires its negative disposition')
        for side, refs in ((engine.harness.identity.query_id, args['a_refs']), (case, args['b_refs'])):
            if len(refs) != len(set(refs)):
                raise HarnessError('Duplicate evidence refs')
            for ref in refs:
                record = state.current_records.get(ref)
                if record is None or record['case_id'] != side:
                    raise HarnessError('Conclusion ref outside the current pair')
                engine.store.verify(record)
        if len(args['identity_refs']) != len(set(args['identity_refs'])):
            raise HarnessError('Duplicate identity refs')
        for ref in args['identity_refs']:
            record = state.current_records.get(ref)
            if record is None or record['case_id'] not in (engine.harness.identity.query_id, case):
                raise HarnessError('Identity evidence outside the current pair')
            engine.store.verify(record)
        if args['decision'] == 'select':
            if not args['a_refs'] or not args['b_refs']:
                raise HarnessError('Select requires current A and B evidence')
            if not any(state.current_records[ref]['case_id'] == case for ref in args['identity_refs']):
                raise HarnessError('Select requires explicit candidate identity evidence refs')
        prior_selected = any(
            final.get(case, {}).get('decision') == 'select'
            and final[case].get('need_id') == query['need_id']
            for final in context.get('candidate_conclusions', {}).values())
        if args['a_refs'] and args['b_refs'] and not (args['decision'] == 'not_select' and prior_selected):
            accepted, pending, invalidated = validate_assessment_state({'assessments': [
                _case_assessment(query, case, args)]}, state, action_id)
            invalidated = [key for key in invalidated
                           if (state.assessments[key]['source_need_id'], state.assessments[key]['candidate_id'])
                           == (query['need_id'], case)]
            if pending:
                raise HarnessError('Candidate conclusion did not satisfy evidence validation')
        context.setdefault('candidate_conclusions', {}).setdefault(query['query_id'], {})[case] = {
            **deepcopy(args), 'status': 'final', 'action_id': action_id,
            'need_id': query['need_id'], 'query_id': query['query_id']}
        if packet:
            context['candidate_conclusions'][query['query_id']][case]['identity_packet_id'] = packet['packet_id']
            local.pop('identity_packet')
        if getattr(engine, 'survey_first', False):
            offset = local.get('survey_offset', 0)
            local.clear()
            local['survey_offset'] = offset
            context.update(candidate_id=None, mode='results', stage='ready')
    elif name == 'assess_passages':
        raise HarnessError('Per-passage assessment is unavailable; candidates have one final conclusion')
    elif name == 'conclude_search_query':
        if not args['reason'].strip():
            raise HarnessError('Query conclusion needs a nonblank reason')
        if set(query['candidate_ids']) - set(query['survey_exposed']):
            raise HarnessError('Show the remaining shortlist pages before concluding this search')
        unfinished=[case for case in query['candidate_ids'] if not case_done(context,query,case)]
        selected=any(r['decision']=='select' for r in conclusions(context,query).values())
        context.setdefault('query_conclusions',{})[query['query_id']]={
            'outcome':'partially_resolved' if unfinished else 'resolved' if selected else 'no_supported_source_found',
            'reason':args['reason'],'unresolved_reason':args['reason'] if unfinished else '',
            'remaining_source_need':'','unresolved_candidate_ids':unfinished,
            'not_read_candidate_ids':[c for c in query['candidate_ids'] if c not in query['raw_exposed']]}
        context.pop('passage_session',None)
        context.update(candidate_id=None,mode='query',stage='ready',offset=0,back=[])
    else:
        raise HarnessError('Unsupported passage-review action')
    context['revision']+=1
    registrations = tuple({'case_id':hit['case_id'],'source_hash':hit['source_hash']}
                          for hit in query['hits'])
    result = normalize_result(ToolResult({},source_requests=registrations),state)
    engine.harness._write(db,state,'action_result',action_id=action_id,status='success',result=result,
        reason=None,reload_refs=[],invalidated_assessments=invalidated,assessments=accepted,
        pending_assessments=[],final=None,local_elapsed_ms=0,cm_context=context)
