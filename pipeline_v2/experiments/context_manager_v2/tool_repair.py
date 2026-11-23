"""Known model-input errors CM4 can return to the controller for correction."""
from pipeline_v2.agent_harness.contracts import fingerprint


TRANSLATION_FIELDS = {
    'invalid_survey_batch': ('items', 'Use one to three distinct nonoverlapping offered spans. You can assess a single span first.'),
    'invalid_source_group': ('source_need_refs', 'Choose distinct queued needs for the same decision. Keep distinct cited decisions separate.'),
    'source_span_required': ('proposition_ref', 'Choose exactly one offered remaining source ref, or copy a literal proposition_quote. no_search_needed also requires a selected span.'),
    'issue_requires_legal_phrase': ('issue', 'Use at least two words for the search.'),
    'issue_contains_case_id': ('issue', 'Use a search phrase without a corpus case ID.'),
    'focus_requires_legal_phrase': ('focus', 'Give a legal focus of at least two words.'),
    'source_proposition_requires_short_nonblank_line': ('source_proposition', 'Write one nonblank line of at least four characters.'),
    'anchor_quote_not_found': ('anchor_quote', 'Copy at least 12 characters from one visible query paragraph and keep its wording and punctuation.'),
    'anchor_quote_ambiguous': ('anchor_quote', 'Copy a longer distinctive phrase from the same paragraph, including words next to the repeated quote.'),
    'anchor_quote_outside_paragraph': ('anchor_quote', 'Copy a continuous phrase that stays inside one visible query paragraph.'),
    'invalid_query_conclusion': ('unresolved_reason', 'Keep unknown or unread candidates unresolved, explain the gap, and use a partial conclusion where required.'),
    'blank_reason': ('reason', 'State a concrete reason.'),
    'blank_finding': ('finding', 'State a concrete review finding.'),
    'blank_missing_evidence': ('missing_evidence', 'Describe the missing evidence or omit the optional note.'),
    'duplicate_missing_evidence': ('missing_evidence', 'Describe each missing item once.'),
    'reserved_review_marker': ('reason', 'State the reason without the reserved targeted review prefix.'),
    'counterevidence_not_in_assessment_dependencies': ('counterevidence', 'Choose evidence already bound to this assessment.'),
}
PROVENANCE_FIELDS = {
    'speaker_ref_lacks_matching_provenance': ('speaker_evidence_refs', 'Choose a ref that supports this speaker role.'),
    'container_ref_lacks_matching_provenance': ('container_refs', 'Choose a ref that contains the relevant quotation.'),
    'quote_chain_ref_lacks_matching_provenance': ('quote_chain_refs', 'Choose raw refs with recorded attribution provenance.'),
    'quote_chain_ref_lacks_a_delivered_attribution_cue': ('quote_chain_refs', 'Choose the cue attached to this quotation, or read it first.'),
}


def repair_feedback(action, code, *, provenance=False):
    """Identify actionable fields without treating state or source faults as model mistakes."""
    args = action['args']
    table = PROVENANCE_FIELDS if provenance else TRANSLATION_FIELDS
    if code in table:
        field, hint = table[code]
        fields = [field]
    elif not provenance and code == 'duplicate_evidence_refs':
        fields = [key for key, values in args.items() if key.endswith('_refs') or key == 'counterevidence'
                  if len(set(values)) < len(values)]
        hint = 'Use each selected ref only once per field.'
    else:
        return None
    refs = {field: list(dict.fromkeys(args[field])) for field in fields
            if field.endswith('_refs') or field == 'counterevidence'}
    return {'tool': action['action'], 'code': code, 'fields': fields, 'refs': refs, 'hint': hint}


def bind_repair(events, feedback, manifest):
    # Repacking the same raw windows to fit feedback does not earn another retry.
    context = manifest['context']
    pair = fingerprint([context['need_id'], context['candidate_id']])
    offsets = context['pair_progress'].get(pair, {}).get('window_offsets', {})
    evidence = sorted((row['canonical_ref'], offsets.get(row['canonical_ref'], -1))
                      for row in manifest['coverage'])
    scope = fingerprint([pair, feedback['tool'], evidence])
    if feedback['code'] == 'source_span_required':
        scope = fingerprint([feedback['tool'], feedback['code'],
                             manifest.get('dispatch_m6', {}).get('a_paragraphs', {})])
    already_offered = any(row.get('cm_tool_repair', {}).get('scope') == scope for row in events)
    return {**feedback, 'scope': scope, 'retry_allowed': not already_offered}


def visible_repair(events):
    """Project the latest repair that the model can still act on."""
    boundary = next((row for row in reversed(events) if row['kind'] in ('request_result', 'action_result')), {})
    repair = boundary.get('cm_tool_repair', {})
    if not repair.get('retry_allowed'):
        return None
    return {**{key: repair[key] for key in ('tool', 'code', 'fields', 'refs', 'hint')},
            'guidance': 'Correct the rejected fields using current options or report the evidence gap.'}
