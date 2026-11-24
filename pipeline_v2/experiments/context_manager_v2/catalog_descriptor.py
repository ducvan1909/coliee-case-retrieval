"""Prompt-only source-assessment descriptors; decoder contracts stay unchanged."""
from copy import deepcopy

from pipeline_v2.agent_harness.contracts import fingerprint

VERSION = 'cm4-catalog-descriptor-v1'
PROFILES = ('full', 'compact_catalog_v1')


def _merge_specs(specs):
    unique = {fingerprint(spec): spec for spec in specs}
    values = list(unique.values())
    if len(values) == 1:
        return deepcopy(values[0])
    stripped = [{key: value for key, value in spec.items() if key != 'enum'} for spec in values]
    if all(spec == stripped[0] for spec in stripped) and all('enum' in spec for spec in values):
        return {**deepcopy(stripped[0]), 'enum': list(dict.fromkeys(
            item for spec in values for item in spec['enum']))}
    # Other conditional differences must remain visible, rather than being lost
    # in a union of field names. These are descriptor fields, not decoder edits.
    return {'anyOf': deepcopy(values)}


def compact(payload, profile='full'):
    if profile not in PROFILES:
        raise ValueError('Unknown CM4 catalog profile')
    if profile == 'full':
        return payload
    result = deepcopy(payload)
    tools = result.get('available_tools', [])
    batch = next((tool for tool in tools if tool['name'] == 'assess_source_needs'), None)
    if batch is None:
        return result
    item = batch['parameters']['properties']['items']['items']
    variants = item.get('anyOf')
    if not variants:
        return result
    fields, required, rules = {}, None, {}
    for variant in variants:
        props = variant['properties']
        decisions = props['decision']['enum']
        if len(decisions) != 1:
            # A future contract with a different shape needs an explicit emitter.
            return deepcopy(payload)
        decision = decisions[0]
        selectors = [key for key in ('proposition_ref', 'proposition_quote') if key in props]
        if len(selectors) > 1:
            return deepcopy(payload)
        rule = rules.setdefault(decision, {'selector_options': []})
        if selectors not in rule['selector_options']:
            rule['selector_options'].append(selectors)
        if 'proposition_ref' in props:
            rule['proposition_ref_choices'] = deepcopy(props['proposition_ref'].get('enum', []))
        requirements = [key for key in variant['required'] if key not in ('proposition_ref', 'proposition_quote')]
        rule.setdefault('required_fields', requirements)
        if rule['required_fields'] != requirements:
            return deepcopy(payload)
        required = set(requirements) if required is None else required.intersection(requirements)
        for name, spec in props.items():
            fields.setdefault(name, []).append(spec)
    ordered = {name: _merge_specs(specs) for name, specs in fields.items()}
    batch['parameters']['properties']['items']['items'] = {
        'type': 'object', 'properties': ordered,
        'required': [name for name in ordered if name in required],
        'additionalProperties': False, 'decision_rules': rules,
        'selector_guidance': (
            'Each selector_options entry is one allowed set of supplied selector fields; '
            '[] permits no selector. Never send both proposition_ref and proposition_quote. '
            'Use only the proposition_ref_choices for the chosen decision. A quote is literal source text. '
            'remaining_visible and negative-only refs settle only their listed ranges with no_search_needed. '
            'Typed attribution/citation supports do not settle their own text. '
            'Keep independent items separate and do not submit conflicting overlapping decisions. '
            'decision_rules and this guidance describe the API; do not send them in args.'),
    }
    # Keep the single-item tool and all its eligibility/repair behavior in v1.
    return result
