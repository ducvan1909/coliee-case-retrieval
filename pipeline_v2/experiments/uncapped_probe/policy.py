"""RT4 policy in private module instances; production globals/files stay intact.

Load the accepted implementation in a separate Python namespace so its internal
catalog calls use this experiment's schema consistently, including payload fitting.
No production caller imports this file. Removing this directory removes the variant.
"""
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
from pipeline_v2.agent_harness.contracts import fingerprint
from pipeline_v2.m6_live import INSTRUCTIONS as BASE_INSTRUCTIONS

VERSION = 'experimental-rt4-proposition-compact-prompt-v4'
PROPOSITION_MAX_CHARS = 240
QUERY_GUIDANCE = (
    'Ground each issue query in one specific proposition in the visible raw A. '
    'Retain distinctive legal terms or wording that help identify the source. '
    'Avoid broad topic-only queries and combining independent source needs. '
    'Omit facts that do not help identify the source, but retain distinctive useful facts. '
    'Write source_proposition as one short sentence (at most 240 characters) stating '
    'what needs a source; issue alone is the actual retrieval query. '
    'The proposition is diagnostic model annotation, not verified evidence. '
    'Produce both in the same action; do not request a separate reasoning turn.'
)
INSTRUCTIONS = BASE_INSTRUCTIONS + '\n' + QUERY_GUIDANCE


def _private_module(name, path):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    sys.modules[name] = module  # dataclasses and relative imports need a module entry
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


_root = Path(__file__).resolve().parents[2]
_base = _private_module('pipeline_v2.agent_harness._probe_base_policy',
                        _root / 'agent_harness/adaptive_policy.py')
_policy = _private_module('pipeline_v2.agent_harness._probe_rt4_policy',
                          _root / 'agent_harness/adaptive_policy.py')
ToolSemanticError = _base.ToolSemanticError


def hydrate_body(body):
    """Resolve visible shared needs for host validation/dispatch, without mutation."""
    table = body['m6'].get('source_needs')
    if table is None:
        return body
    hydrated = deepcopy(body)
    for key, need in table.items():
        if key != 'n' + fingerprint(need)[:16]:
            raise ToolSemanticError('source_need_table_binding_mismatch')
    for candidate in hydrated['m6']['candidates'].values():
        needs = []
        for key in candidate['needs']:
            if not isinstance(key, str) or key not in table:
                raise ToolSemanticError('source_need_table_ref_missing')
            needs.append(deepcopy(table[key]))
        candidate['needs'] = needs
    return hydrated


def catalog(body, *, compact_prompt=True):
    tools, schema, citations, pairs = _base.catalog(hydrate_body(body))
    for tool in tools:
        if tool['name'] == 'search_cases_by_issue':
            parameters = tool['parameters']
            parameters['properties']['source_proposition'] = {
                'type': 'string', 'minLength': 4, 'maxLength': PROPOSITION_MAX_CHARS}
            parameters['required'].append('source_proposition')
            tool['when'] += ' ' + QUERY_GUIDANCE
    if not compact_prompt:
        return tools, schema, citations, pairs
    # Tool parameters are repeated in the text prompt and the decoder schema.
    # Registry choices already appear once in m6; describe their lookup location
    # in the prompt copy while keeping the full enum in the actual schema.
    prompt_tools = deepcopy(tools)
    choice_paths = {'a_paragraph_ref': 'm6.a_paragraphs keys',
                    'citation_ref': 'm6.citation_refs keys',
                    'search_ref': 'm6.citation_search_pages keys',
                    'candidate_ref': 'm6.candidates keys',
                    'map_ref': 'm6.query_maps keys', 'query_ref': 'm6.query_targets keys',
                    'context_ref': 'm6.expansions keys', 'evidence_ref': 'm6.reloads keys',
                    'pair_ref': 'm6.pair_refs keys'}
    current = set(body['current_payload_source_refs'])
    for tool in prompt_tools:
        for name, field in tool['parameters']['properties'].items():
            if name in choice_paths and 'enum' in field:
                field.pop('enum')
                field['choices_from'] = choice_paths[name]
            items = field.get('items', {})
            if 'enum' in items and set(items['enum']) <= current:
                items.pop('enum')
                items['choices_from'] = 'current_payload_source_refs; chosen A/B pair only'
    return prompt_tools, schema, citations, pairs


def translate(body, action):
    _, schema, _, _ = catalog(body)
    branch = next((item for item in schema['anyOf'] if isinstance(action, dict)
                   and item['properties']['action']['const'] == action.get('action')), schema)
    Draft202012Validator(branch).validate(action)
    adapted = deepcopy(action)
    proposition = None
    if action['action'] == 'search_cases_by_issue':
        proposition = adapted['args'].pop('source_proposition').strip()
        if len(proposition) < 4 or '\n' in proposition or '\r' in proposition:
            raise ToolSemanticError('source_proposition_requires_short_nonblank_line')
    internal = _base.translate(hydrate_body(body), adapted)
    if proposition is not None:
        # Debug stays on the source need, never the retrieval query text/score.
        internal['args']['_m6_need']['source_proposition'] = proposition
    return internal


_policy.VERSION = VERSION
_policy.catalog = catalog
_policy.translate = translate
# Ensure semantic rejections retain the bridge's normal error/usage treatment.
_policy.ToolSemanticError = ToolSemanticError

_m6 = _private_module('pipeline_v2._probe_rt4_m6', _root / 'm6.py')
_m6.catalog = catalog
_m6.AdaptiveTransport = _policy.AdaptiveTransport
_m6.ModelToolReplyRejected = _policy.ModelToolReplyRejected
_m6.VERSION = VERSION
_m6.M6_INSTRUCTIONS += '\n' + QUERY_GUIDANCE
_original_fingerprint = _m6.implementation_fingerprint


def _implementation_fingerprint():
    return fingerprint([_original_fingerprint(), VERSION,
                        __import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest()])


_m6.implementation_fingerprint = _implementation_fingerprint
OriginalAdaptiveHarness = _m6.AdaptiveHarness


class AdaptiveHarness(OriginalAdaptiveHarness):
    """Short payload-local tool choices, without shortening source identities.

    The original registry first resolves consumed routes and deduplicates using
    canonical bindings. Only the displayed choice keys are renamed afterwards.
    Translation reads this same payload table and dispatches its original values.
    """
    OPTION_PREFIXES = {'candidates': 'c', 'query_maps': 'm', 'query_targets': 'q',
                       'expansions': 'x', 'reloads': 'r', 'citation_search_pages': 's'}

    def _registry(self, state, payload):
        registry = super()._registry(state, payload)
        needs = {}
        for candidate in registry['candidates'].values():
            refs = []
            for need in candidate['needs']:
                key = 'n' + fingerprint(need)[:16]
                if key in needs and needs[key] != need:
                    raise ToolSemanticError('source_need_table_collision')
                needs[key] = need
                refs.append(key)
            candidate['needs'] = refs
        if needs:
            registry['source_needs'] = needs
        for field, prefix in self.OPTION_PREFIXES.items():
            options = registry.get(field)
            if options:
                renamed = {}
                for key, value in sorted(options.items()):
                    alias = prefix + fingerprint([field, key])[:12]
                    if alias in renamed:
                        raise ToolSemanticError('payload_option_alias_collision')
                    renamed[alias] = value
                registry[field] = renamed
        return registry


AdaptiveTransport = _policy.AdaptiveTransport
