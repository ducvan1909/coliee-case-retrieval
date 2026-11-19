"""Compact CM4 model input while retaining canonical dispatch data at the host."""
from copy import deepcopy
from hashlib import sha256
import re


_OPAQUE = re.compile(r'(?:[a-f0-9]{32,}|[a-z][a-f0-9]{16,}|need-[a-f0-9]+|qn-.+|\d{6}:[a-f0-9:.-]+)\Z')
_LITERAL_FIELDS = {'text', 'preview', 'reason', 'finding', 'issue', 'intent', 'focus', 'anchor_quote',
                   'source_proposition', 'guidance', 'message', 'hint', 'description',
                   'when', 'examples', 'result', 'heading', 'label', 'missing_reason',
                   'reported_missing_evidence', 'attribution_cues'}
_HOST_FIELDS = {'binding', 'open_ref', 'source_hash', 'query_source_hash', 'text_sha256',
                'schema_fingerprint', 'cm_schema_fingerprint', 'tree_binding', 'source_revision',
                'provenance_overlay', 'reading_expansion', 'paragraph_span_bytes', 'text_hash'}
_M6_HOST_FIELDS = {'channel', 'policy_version', 'audit_untriggered', 'max_reviews',
                   'no_progress_actions', 'hybrid_budget_remaining', 'schema_fingerprint'}
_SIDE_NAMES = {'A': 'query case', 'B': 'candidate case', 'A+B': 'both cases'}
_INTERNAL_SIDES = {name: side for side, name in _SIDE_NAMES.items()}
_SIDE_FIELDS = {'side', 'identity_support_choice', 'counterevidence_choice'}
_TOOL_TERMS = {
    'raw A/B excerpts': 'raw excerpts from the query case and candidate case',
    'a known A/B pair': 'a known pair of query and candidate cases',
    'chosen A/B pair only': 'selected query and candidate cases only',
    'raw query A': 'raw text of the query case',
    'query A': 'the query case',
    'raw A excerpts': 'raw excerpts from the query case',
    'raw A.': 'raw text from the query case.',
    'Raw A text': 'Raw text from the query case',
    'current A': 'the current query case excerpt',
    'map of A': 'map of the query case',
    'A context': 'query case context',
    'raw B passages': 'raw passages from the candidate case',
    'within B': 'within the candidate case',
    'whether A cites or relies on B': 'whether the query case cites or relies on the candidate case',
    'A-to-B use': 'use of the candidate case by the query case',
    'Do not infer A-to-B merely because both quote C.': 'A shared quotation from a third case is insufficient to infer reliance.',
}


def _tool_guidance(value, field=None):
    if isinstance(value, dict):
        return {key: _tool_guidance(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_tool_guidance(item, field) for item in value]
    if isinstance(value, str) and field in {'description', 'when', 'result', 'examples', 'choices_from'}:
        for old, new in _TOOL_TERMS.items():
            value = value.replace(old, new)
    return value


def _cue_text(cue, raw, start, end):
    span = cue.get('span_bytes')
    if not isinstance(span, (list, tuple)) or len(span) != 2 or not all(type(n) is int for n in span):
        return None
    left, right = span
    if start <= left < right <= end:
        return raw[left-start:right-start].decode('utf-8')
    return None


def _structure(record):
    """Keep paragraph identity, ownership and quotation cues visible to the model."""
    result = []
    raw = record['text'].encode('utf-8')
    start, end = record['span_bytes']
    for component in record.get('provenance', {}).get('components', []):
        kind = component.get('unit_kind')
        if kind == 'whitespace':
            continue
        row = {}
        if component.get('unit_id'):
            row['unit_ref'] = component['unit_id']
        if component.get('handle'):
            row['paragraph_ref'] = component['handle']
        if component.get('observed_marker') is not None:
            row['paragraph'] = component['observed_marker']
        if kind not in ('paragraph', None):
            row['kind'] = kind
        role = component.get('paragraph_role')
        if role not in (None, 'unknown'):
            row['role'] = role
        if component.get('attribution_unit_id'):
            row['attribution_source'] = component['attribution_unit_id']
        cues = []
        for cue in component.get('role_evidence_refs', []):
            text = _cue_text(cue, raw, start, end)
            if text is not None:
                cues.append(text)
            else:
                row['attribution_cue_outside_excerpt'] = True
        if cues:
            row['attribution_cues'] = list(dict.fromkeys(cues))
        ownership = []
        for cue in component.get('ownership_cue_observations', []):
            if not isinstance(cue, dict):
                continue
            observation = {key: cue[key] for key in ('kind', 'role', 'speaker_role', 'speaker',
                                                     'type', 'label', 'observed_text', 'text') if key in cue}
            text = _cue_text(cue, raw, start, end)
            if text is not None:
                observation['text'] = text
            elif cue.get('span_bytes'):
                observation['outside_excerpt'] = True
            if observation and observation not in ownership:
                ownership.append(observation)
        if ownership:
            row['ownership_cues'] = ownership
        uncertainties = component.get('uncertainties', [])
        if uncertainties:
            row['uncertainties'] = uncertainties
        if row and row not in result:
            result.append(row)
    return result


def _compact(payload):
    wire = deepcopy(payload)
    wire.pop('query_source_hash', None)
    wire.pop('cm_schema_fingerprint', None)
    wire.pop('observation_scope', None)
    wire['context_projection'] = 'compact_model_view'
    wire['excerpts'] = [
        {**{key: record[key] for key in ('case_id', 'ref', 'span_bytes', 'text')},
         'structure': _structure(record)}
        for record in payload['excerpts']
    ]
    m6 = wire['m6']
    if sides := m6.get('assessment_ref_sides'):
        m6['assessment_ref_sides'] = {'query case': sides['A'], 'candidate case': sides['B_by_candidate']}
    if 'available_tools' in wire:
        wire['available_tools'] = _tool_guidance(wire['available_tools'])
    for key in _M6_HOST_FIELDS:
        m6.pop(key, None)
    for row in m6.get('source_needs', {}).values():
        anchor = row.get('a_anchor')
        if anchor:
            row['anchor_quote'] = anchor['text']
        for key in list(row):
            if key not in ('source_need_id', 'intent', 'route', 'source_proposition', 'anchor_quote', 'a_refs'):
                row.pop(key)
    for row in m6.get('a_paragraphs', {}).values():
        for key in list(row):
            if key not in ('paragraph_handle', 'paragraph_coverage', 'span_bytes', 'source_ref'):
                row.pop(key)
    for segment in m6.get('source_gate_segments', {}).values():
        segment.pop('source_ref', None)
        segment.pop('span_bytes', None)
    for row in m6.get('candidates', {}).values():
        row.pop('open_ref', None)
        for lead in row.get('leads', []):
            lead.pop('channel_ranks', None)
            lead.pop('discovery_channel', None)
            lead.pop('score', None)
    return wire


def project(payload, schema):
    """Return a compact payload, equivalent wire schema, and short-to-canonical refs."""
    wire = _compact(payload)
    aliases, canonical_aliases = {}, {}

    def alias(value):
        if not _OPAQUE.fullmatch(value):
            return value
        if value in canonical_aliases:
            return canonical_aliases[value]
        digest = sha256(value.encode('utf-8')).hexdigest()
        length = 10
        key = 'r' + digest[:length]
        while key in aliases and aliases[key] != value:
            length += 2
            if length > len(digest):
                raise ValueError('Model reference alias collision')
            key = 'r' + digest[:length]
        aliases[key] = value
        canonical_aliases[value] = key
        return key

    def transform(value, field=None):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in _HOST_FIELDS:
                    continue
                # Text inside descriptions is literal, while a description object
                # still contains technical source refs and host binding fields.
                if key in _LITERAL_FIELDS and isinstance(item, str):
                    result[alias(key)] = item
                elif key == 'examples':
                    result[key] = deepcopy(item)
                else:
                    item_field = field if field in _SIDE_FIELDS and key in ('enum', 'const') else key
                    result[alias(key)] = transform(item, item_field)
            return result
        if isinstance(value, list):
            return [transform(item, field) for item in value]
        if isinstance(value, tuple):
            return [transform(item, field) for item in value]
        if isinstance(value, str):
            if field in _SIDE_FIELDS:
                return _SIDE_NAMES.get(value, value)
            return value if field in _LITERAL_FIELDS else alias(value)
        return value

    wire = transform(wire)
    wire_schema = transform(schema)
    # The tool description in the prompt may use lookup paths. Explicit enums
    # in its schema are projected by the same alias table as those lookup maps.
    return wire, wire_schema, aliases


def restore_action(action, aliases):
    """Resolve issued argument refs without changing free-form model text."""
    restored = deepcopy(action)
    args = restored.get('args')
    if not isinstance(args, dict):
        return restored

    def resolve(value):
        if isinstance(value, str):
            return aliases.get(value, value)
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value

    for field, value in args.items():
        if field.endswith(('_ref', '_refs')) or field == 'counterevidence':
            args[field] = resolve(value)
        elif field in _SIDE_FIELDS and isinstance(value, str):
            args[field] = _INTERNAL_SIDES.get(value, value)
        elif field == 'speaker' and isinstance(value, dict) and isinstance(side := value.get('side'), str):
            value['side'] = _INTERNAL_SIDES.get(side, side)
    return restored
