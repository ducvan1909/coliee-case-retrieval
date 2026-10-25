"""Rooted JSON EBNF; finite identities and enums, host-bounded strings."""
import json
from itertools import combinations, product
from .contracts import *
from ..au_compact.decoding import _literal as lit, _json_literal as jlit


def build_grammar(job):
    rules = []
    def rule(name, body):
        rules.append(name + ' ::= ' + body)
    def enum(name, values):
        rule(name, ' | '.join(jlit(v) for v in values))
    def field(key, body):
        return lit(json.dumps(key) + ':') + ' ' + body
    def obj(parts):
        return lit('{') + ' ' + (' ' + lit(',') + ' ').join(parts) + ' ' + lit('}')
    def arr(body):
        return lit('[') + ' ' + body + ' ' + lit(']')
    def refs(name, values, allow_empty=False, cap=MAX_REFS):
        if not values:
            rule(name, lit('[]'))
            return
        enum(name + '-id', values)
        inner = name + '-id (' + lit(',') + ' ' + name + '-id){0,' + str(cap-1) + '}'
        rule(name, arr('(' + inner + ')?' if allow_empty else inner))
    version = stage1_version(job.get('prompt_profile')) if job['stage'] == 1 else STAGE2
    prefix = [field('version', jlit(version)), field('request_id', jlit(job['request_id'])),
              field('target_id', jlit(job['target_id']))]
    # Positive character ranges avoid the old XGrammar negated-class narrowing bug.
    rule('text', r'"\"" json-char* "\""')
    rule('json-char', r'[\x20-\x21\x23-\x5b\x5d-\uD7FF\uE000-\U0010FFFF] | "\\" (["\\/bfnrt] | "u" scalar-hex) | "\\u" [dD] [89aAbB] hex hex "\\u" [dD] [c-fC-F] hex hex')
    rule('scalar-hex', '[0-9a-cA-Ce-fE-F] hex hex hex | [dD] [0-7] hex hex')
    rule('hex', '[0-9a-fA-F]')
    refs('needs', NEEDS, True, len(NEEDS))
    if job['stage'] == 1:
        enum('kind', KINDS)
        primary_support = job.get('prompt_profile') == 'primary_support_v1'
        if not primary_support:
            refs('target-refs', job['catalog']['target_refs'])
        else:
            # One finite primary branch fixes which ID is excluded from support.
            branches = []
            for index, primary in enumerate(job['catalog']['target_refs']):
                name = 'supporting-refs-' + str(index)
                refs(name, [r for r in job['catalog']['target_refs'] if r != primary],
                     allow_empty=True, cap=MAX_REFS - 1)
                branches.append((primary, name))
            if branches:
                rule('primary-support-selection', ' | '.join(
                    field('primary_ref_id', jlit(primary)) + ' ' + lit(',') + ' ' +
                    field('supporting_ref_ids', support) for primary, support in branches))
        # IDs are output slots, not a freely permutable set. Match the host
        # contract at decode time: only contiguous prefixes of slots 1..3.
        slots = []
        available_slots = [] if primary_support and not branches else job['anchor_ids'][:MAX_ANCHORS]
        for index, anchor_id in enumerate(available_slots, 1):
            name = 'anchor-slot-' + str(index)
            anchor_fields = [field('anchor_id', jlit(anchor_id)), field('kind', 'kind')]
            if primary_support:
                rule(name, obj(anchor_fields + ['primary-support-selection',
                                               field('needs_context', 'needs')]))
                slots.append(name)
                continue
            if stage1_version(job.get('prompt_profile')) == STAGE1:
                anchor_fields.append(field('primary_claim', 'text'))
            rule(name, obj(anchor_fields + [field('target_ref_ids', 'target-refs'),
                                           field('needs_context', 'needs')]))
            slots.append(name)
        prefixes = [arr((' ' + lit(',') + ' ').join(slots[:size]))
                    for size in range(1, len(slots) + 1)]
        rule('anchors', ' | '.join([lit('[]')] + prefixes))
        if prefixes or not primary_support:
            rule('positive-anchors', ' | '.join(prefixes))
        outcomes = []
        for i, (decision, reasons) in enumerate(STAGE1_REASON_BY_DECISION.items()):
            if primary_support and not prefixes and decision == 'positive':
                continue
            name = 'stage1-reason-' + str(i)
            enum(name, reasons)
            anchor_body = ('positive-anchors' if decision == 'positive' else
                           lit('[]') if decision == 'negative' else 'anchors')
            needs_body = lit('[]') if decision == 'negative' else 'needs'
            outcomes.append(obj(prefix + [field('decision', jlit(decision)),
                field('anchors', anchor_body), field('needs_context', needs_body), field('reason', name)]))
        rule('root', ' | '.join(outcomes))
    else:
        refs('context-refs', job['catalog']['context_refs'])
        if job['catalog']['context_refs']:
            # Four slots => only 16 ordered subsets. No repetition operator can
            # produce a second occurrence of the same slot. Multiple references
            # belong in the existing context_ref_ids list of a single item.
            for slot in SLOTS:
                rule('supplement-' + slot, obj([field('slot', jlit(slot)),
                    field('text', 'text'), field('context_ref_ids', 'context-refs')]))
            subsets = [lit('[]')]
            for size in range(1, len(SLOTS) + 1):
                for slots in combinations(SLOTS, size):
                    subsets.append(arr((' ' + lit(',') + ' ').join(
                        'supplement-' + slot for slot in slots)))
            rule('supplements', ' | '.join(subsets))
        else:
            rule('supplements', lit('[]'))
        # Exact anchor order/count, per-anchor finite IDs. Context never creates anchors.
        parts = []
        if len(job['locked_anchors']) > MAX_ANCHORS:
            raise ValueError('locked anchor count exceeds finite grammar bound')
        for decision, reasons in STAGE2_ANCHOR_REASON_BY_DECISION.items():
            enum('anchor-reason-' + decision, reasons)
        for i, anchor in enumerate(job['locked_anchors']):
            name = 'locked-' + str(i)
            branches = []
            for decision in STAGE2_ANCHOR_REASON_BY_DECISION:
                branch = obj([field('anchor_id', jlit(anchor['anchor_id'])),
                    field('decision', jlit(decision)),
                    field('supplements', 'supplements' if decision == 'keep' else lit('[]')),
                    field('reason', 'anchor-reason-' + decision)])
                rule(name + '-' + decision, branch)
                branches.append(branch)
            rule(name, ' | '.join(branches))
            parts.append(name)
        rule('anchors', arr((' ' + lit(',') + ' ').join(parts)) if parts else lit('[]'))
        outcomes = []
        for decision, reasons in STAGE2_REASON_BY_DECISION.items():
            if decision == 'complete' and not parts:
                continue
            name = 'stage2-reason-' + decision
            enum(name, reasons)
            # At most 3**3 combinations. Bind global and anchor decisions
            # together, exactly as validate_stage2 does (including zero anchors).
            choices = []
            for decisions in product(STAGE2_ANCHOR_REASON_BY_DECISION, repeat=len(parts)):
                if decision == 'complete' and 'unresolved' in decisions:
                    continue
                if decision == 'unresolved' and decisions and 'unresolved' not in decisions:
                    continue
                choices.append(arr((' ' + lit(',') + ' ').join(
                    part + '-' + choice for part, choice in zip(parts, decisions)))
                    if decisions else lit('[]'))
            anchor_rule = 'anchors-' + decision
            rule(anchor_rule, ' | '.join(choices))
            outcomes.append(obj(prefix + [field('decision', jlit(decision)),
                field('anchors', anchor_rule), field('reason', name)]))
        rule('root', ' | '.join(outcomes))
    # XGrammar expects root first; rule order otherwise has no meaning.
    rules.sort(key=lambda s: not s.startswith('root ::='))
    return '\n'.join(rules) + '\n'
