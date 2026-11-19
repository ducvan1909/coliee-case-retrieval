"""Compile CM4 attribution choices from the evidence in the admitted view."""

from itertools import combinations

from pipeline_v2.agent_harness.assessment import (
    AssessmentStateError, _anchor, _component_rows, _overlaps, _span, _speaker_evidence,
)


def _check(speaker, side, support=(), containers=(), chain=()):
    """Use the M4 provenance and cue checks used when the assessment is saved."""
    try:
        missing, _ = _speaker_evidence(speaker, {
            'speaker_evidence_refs': support, 'container_refs': containers,
            'quote_chain_refs': chain,
        }, side, side)
    except AssessmentStateError:
        return None
    return missing


def speaker_refs(rows, role):
    return [row['ref'] for row in rows if _check({'role': role}, row['case_id'], [row]) is not None]


def _chains(rows, container):
    """Preselect current raw refs that overlap cues on the selected quote."""
    candidates = {}
    sources = [(row, {_anchor(component) for _, component in _component_rows([row])})
               for row in rows if row.get('provenance', {}).get('components')]
    for _, component in _component_rows([container]):
        if component.get('paragraph_role') != 'quoted':
            continue
        attribution = component.get('attribution_unit_id')
        cues = component.get('role_evidence_refs', [])
        if not isinstance(cues, list):
            continue
        for cue in cues:
            if not isinstance(cue, dict):
                continue
            try:
                span = _span(cue.get('span_bytes'))
            except AssessmentStateError:
                continue
            for row, anchors in sources:
                if (not attribution or attribution in anchors) and _overlaps(row['span_bytes'], span):
                    candidates[row['ref']] = row
    # A cue can span several current raw excerpts. M4 checks byte coverage and
    # rejects subsets that do not cover a cue or contain unmatched refs.
    for count in range(1, len(candidates) + 1):
        yield from combinations(candidates.values(), count)


def attribution_options(rows, side):
    """Return options shared by the prompt and decoder for one speaker side."""
    case = rows[0]['case_id']
    by_ref = {row['ref']: row for row in rows}
    own = speaker_refs(rows, 'court')
    quoted = speaker_refs(rows, 'quoted_source')
    direct_containers = [row['ref'] for row in rows if _check({'role': 'unknown'}, case, containers=[row]) is not None]
    candidates = {row['ref']: list(_chains(rows, row)) for row in rows}
    direct_chains = [(ref, [row['ref'] for row in chain]) for ref in direct_containers
                     for chain in candidates[ref]
                     if _check({'role': 'unknown'}, case, containers=[by_ref[ref]], chain=chain) == []]

    def direct_options(speaker):
        yield {**speaker, 'container_refs': direct_containers}
        # An ordinary speaker can annotate an observed quotation without
        # claiming to be its quoted source or to adopt its reasoning.
        for ref, chain in direct_chains:
            yield {**speaker, 'container_refs': [ref], 'quote_chain_refs': chain}

    if side == 'B':
        yield from direct_options({'role': 'unknown', 'side': side, 'speaker_refs': speaker_refs(rows, 'unknown')})
    if own:
        for role, kind in (('court', 'own_reasoning'), ('party', 'submission')):
            yield from direct_options({'role': role, 'type': kind, 'side': side, 'speaker_refs': own})
    for role, kind, support in (('court', 'adopted_reasoning', own), ('quoted_source', 'quotation', quoted)):
        speaker = {'role': role, 'type': kind, 'side': side}
        for ref in support:
            speaker_row = by_ref[ref]
            containers = [row for row in rows if _check(speaker, case, [speaker_row], [row]) is not None]
            matching = []
            for container in containers:
                for chain in candidates[container['ref']]:
                    if _check(speaker, case, [speaker_row], [container], chain) == []:
                        matching.append((container['ref'], [row['ref'] for row in chain]))
            base = {'role': role, 'type': kind, 'side': side, 'speaker_refs': [ref]}
            if matching:
                for container, chain in matching:
                    yield {**base, 'container_refs': [container], 'quote_chain_refs': chain}
            elif role == 'quoted_source' or containers:
                # With an observed quotation, M4 may record a pending attribution.
                # Its schema cannot claim a chain until the matching cue is present.
                yield {**base, 'container_refs': [row['ref'] for row in containers], 'pending_only': True}
