"""Freeze source-only policies/selections before post-selection KOS auditing."""
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import time

from ..region_priority_offline import core as old
from ..region_priority_offline import features, scheduler as baseline
from ..kos_comparison.comparison import _load_kos, align_evidence
from .context import CONTEXT_POLICY, expand_context
from .scheduler import ORDER_POLICY, priority_order, rank_reason, schedule_order

BASE = old.BASE
DEFAULT_ROOT = BASE / 'outputs/region_priority_variants_20261013'
DEFAULT_BASELINE = BASE / 'outputs/region_priority_offline_20261013'
FRACTIONS = (.1, .25, .5, .75, 1.)


def fingerprint(value):
    return old._sha(old._canonical(value).encode('utf-8'))


def implementation_fingerprints():
    paths = sorted(set(Path(__file__).parent.glob('*.py')) |
                   {Path(old.__file__), Path(features.__file__), Path(baseline.__file__)})
    return [{'path': str(p.resolve()), 'sha256': old._sha(p.read_bytes())} for p in paths]


def identity(inventory):
    return {'input_bindings': inventory['input_bindings'], 'artifact_bindings': inventory['artifact_bindings'],
            'baseline_policy_sha256': inventory['policy_sha256'],
            'source_hashes': {c['case_id']: c['source_hash'] for c in inventory['cases']},
            'targets_sha256': fingerprint([{k: r[k] for k in ('region_id', 'case_id', 'source_hash', 'target', 'block_type')} for r in inventory['regions']]),
            'features_sha256': fingerprint([r['features'] for r in inventory['regions']]),
            'baseline_packets_sha256': fingerprint([r['packet'] for r in inventory['regions']]),
            'baseline_inventory_sha256': fingerprint({k: v for k, v in inventory.items() if k != 'sources'})}


def _write(root, name, value):
    with (root / name).open('x', encoding='utf-8') as handle:
        handle.write((value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)) + '\n')


def _prepare_root(root, stage, protected):
    root = Path(root).resolve()
    for p in protected:
        p = Path(p).resolve()
        if root == p or p in root.parents or root in p.parents:
            raise ValueError('output overlaps protected input: ' + str(p))
    if root.exists() and any(root.iterdir()):
        raise ValueError('nonempty stage output; overwrite refused: ' + str(root))
    if root == DEFAULT_ROOT.resolve():
        raise ValueError('use owned order/context child; Main owns root files')
    root.mkdir(parents=True, exist_ok=True)
    return root


def _freeze(inventory, ordered, prior_path):
    return {'version': 'priority-variants-lock-v1', 'full_ordered_ids': ordered,
            'order_sha256': fingerprint(ordered), 'identity': identity(inventory),
            'order_policy': ORDER_POLICY, 'context_policy': CONTEXT_POLICY,
            'order_policy_sha256': fingerprint(ORDER_POLICY), 'context_policy_sha256': fingerprint(CONTEXT_POLICY),
            'implementation_fingerprints': implementation_fingerprints(),
            'prior_report_sha256': old._sha(prior_path.read_bytes()),
            'rank_reasons': [{'region_id': rid, 'full_order_rank': i, **rank_reason({r['region_id']: r for r in inventory['regions']}[rid])}
                             for i, rid in enumerate(ordered)]}


def verify_order_report(path, inventory, expected_lock):
    """Reject altered snapshots, source, features, target, policy, code or order."""
    path = Path(path).resolve()
    report = old._json(path)
    if report.get('stage') != 'order' or report.get('protocol_status') != 'pass':
        raise ValueError('Stage 2 requires completed passing Stage 1 report')
    frozen = old._json(path.parent / 'frozen_snapshot.json')
    if report['frozen_snapshot_sha256'] != fingerprint(frozen) or frozen != expected_lock or report['lock'] != frozen:
        raise ValueError('order/input/target/features/policy/code identity lock differs')
    inv_path = path.parent / 'inventory.json'
    if report['inventory_file_sha256'] != old._sha(inv_path.read_bytes()):
        raise ValueError('Stage 1 inventory file modified')
    saved = old._json(inv_path)
    if identity({**saved, 'sources': inventory['sources']}) != frozen['identity']:
        raise ValueError('Stage 1 inventory identity differs')
    if saved != {k: v for k, v in inventory.items() if k != 'sources'}:
        raise ValueError('Stage 1 inventory must equal rebuilt baseline')
    if report['selection_snapshot_sha256'] != fingerprint(old._json(path.parent / 'selection_snapshot.json')):
        raise ValueError('Stage 1 selection snapshot modified')
    return report


def _metrics(units, schedule, inventory):
    by_id = {r['region_id']: r for r in inventory['regions']}
    exposure = [{'case_id': u['case_id'], 'kos_id': u['kos_id'], **old._exposure(u, schedule, by_id)} for u in units]
    eligible = [e for e in exposure if e['eligible_denominator']]
    def counts(group):
        return {'denominator': len(group), 'full_target_count': sum(e['target_fullspan'] for e in group),
                'full_context_count': sum(e['context_fullspan'] for e in group),
                'full_target_fraction': sum(e['target_fullspan'] for e in group) / len(group) if group else None,
                'zero_denominator_status': 'NA' if not group else None}
    groups = {}
    for key in ('source_no_marker', 'containing_block_no_marker', 'containing_block_no_citation_or_marker_cue', 'application_cue', 'exception_cue'):
        groups[key] = counts([e for e, u in zip(exposure, units) if e['eligible_denominator'] and u['categories'][key]])
    for kind in sorted({str(u['kind']) for u in units}):
        groups['kos_kind:' + kind] = counts([e for e, u in zip(exposure, units) if e['eligible_denominator'] and str(u['kind']) == kind])
    cases = []
    for case in inventory['cases']:
        cid = case['case_id']
        rows = [by_id[r['region_id']] for r in schedule['reads'] if by_id[r['region_id']]['case_id'] == cid]
        targets = old._length([r['target'] for r in rows])
        cases.append({'case_id': cid, **counts([e for e in eligible if e['case_id'] == cid]),
                      'source_chars': case['source_chars'], 'covered_target_source_chars': targets,
                      'unknown_target_source_chars': case['source_chars'] - targets,
                      'covered_context_source_chars': old._length([c for r in rows for c in r['packet']['context']]),
                      'delivered_serialized_bytes': sum(r['serialized_utf8_bytes'] for r in rows),
                      'selected_region_count': len(rows), 'unknown_region_count': case['block_count'] - len(rows)})
    return {**counts(eligible), 'partial_target_count': sum(0 < e['covered_target_chars'] < e['evidence_chars'] for e in eligible),
            'diagnostic_categories': groups, 'cases': cases, 'per_au': exposure}


def _audit_kos(inventory, kos_root, manifest):
    ki, units, errors = _load_kos(kos_root, manifest)
    result = []
    for unit in units:
        source = inventory['sources'][unit['case_id']]
        aligned = align_evidence(unit['evidence_text'], source)
        valid = aligned['status'] in ('exact', 'whitespace_normalized')
        evidence = ''.join(source[s['start_char']:s['end_char']] for s in aligned['spans']) if valid else ''
        f = features.extract_features(evidence)
        containing = ''.join(r['packet']['target']['text'] for r in inventory['regions']
                             if valid and r['case_id'] == unit['case_id'] and old._overlap(aligned['spans'], [r['target']]))
        categories = {'source_no_marker': not bool(f['counts']['citation']) if valid else None,
                      'containing_block_no_marker': not any('<' + k + '>' in containing for k in ('FRAGMENT_SUPPRESSED', 'REFERENCE_SUPPRESSED', 'CITATION_SUPPRESSED')) if valid else None,
                      'containing_block_no_citation_or_marker_cue': not bool(features.extract_features(containing)['counts']['citation']) if valid else None,
                      'application_cue': bool(f['lane_scores']['application']) if valid else None,
                      'exception_cue': bool(f['counts']['qualification'] or f['counts']['rebuttal']) if valid else None,
                      'category_role': 'overlapping diagnostics, not semantic labels'}
        result.append({**unit, 'alignment': aligned, 'categories': categories,
                       'aligned_source_evidence': evidence if valid else None})
    return ki, result, errors


def _delivery(rows):
    """Input-only quality proxies; no KOS requirement enters this function."""
    reference_counts = Counter()
    refs = []
    cues = Counter()
    sent, unique = 0, 0
    by_case = {}
    for row in rows:
        contexts = row['packet']['context']
        sent += sum(c['end_char'] - c['start_char'] for c in contexts)
        by_case.setdefault(row['case_id'], []).extend(contexts)
        for ref in row.get('context_audit', {}).get('input_reference_hints', []):
            reference_counts[ref['resolution']] += 1
            refs.append({'region_id': row['region_id'], **ref})
        for cue in ('qualification', 'reporting', 'quote'):
            # Source cue presence is delivery only, not resolved interpretation.
            cues[cue + '_target_packets'] += bool(row['features']['counts'][cue])
            cues[cue + '_context_packets'] += any(features.extract_features(c['text'])['counts'][cue] for c in contexts)
    unique = sum(old._length(spans) for spans in by_case.values())
    return {'input_owned_reference_hints': {k: reference_counts[k] for k in ('resolved', 'open', 'unresolved')},
            'references': refs, 'cue_delivery_proxy': dict(cues),
            'delivered_context_chars_with_repetitions': sent, 'unique_context_source_chars': unique,
            'repeated_context_chars': sent - unique,
            'semantic_dependency_quality': 'not_assessed', 'independent_reviewer_probe': 'tester_owned_pending'}


def _matched(original, changed, selected_ids, divisor):
    before = {r['region_id']: r for r in original['regions']}
    after = {r['region_id']: r for r in changed['regions']}
    a, b = [before[rid] for rid in selected_ids], [after[rid] for rid in selected_ids]
    def cost(rows):
        return {'serialized_bytes': sum(r['serialized_utf8_bytes'] for r in rows),
                'estimated_tokens': sum(math.ceil(r['serialized_utf8_bytes'] / divisor) for r in rows)}
    ca, cb = cost(a), cost(b)
    dependencies = []
    for ra, rb in zip(a, b):
        for ref in rb['context_audit']['input_reference_hints']:
            if not ref['ownership_confirmed_local']:
                continue
            span = ref['required_span']
            size = span['end_char'] - span['start_char']
            dependencies.append({'region_id': rb['region_id'], 'reference_start_char': ref['start_char'],
                                 'required_span': span, 'dependency_status': 'hint',
                                 'original_whole_delivery': old._overlap([span], [ra['target']] + ra['packet']['context']) == size,
                                 'new_whole_delivery': old._overlap([span], [rb['target']] + rb['packet']['context']) == size})
    return {'selected_target_ids': selected_ids, 'selected_set_sha256': fingerprint(selected_ids),
            'original': {**ca, **_delivery(a)}, 'new_context': {**cb, **_delivery(b)},
            'serialized_byte_delta': cb['serialized_bytes'] - ca['serialized_bytes'],
            'estimated_token_delta': cb['estimated_tokens'] - ca['estimated_tokens'],
            'required_owned_dependency_delivery': dependencies}


def run(*, stage, output_root=None, order_report=None, kos_root=Path('G:/Legal-AI/kos_sample'),
        baseline_root=DEFAULT_BASELINE, **inventory_kwargs):
    started = time.perf_counter()
    if stage not in ('order', 'context'):
        raise ValueError('stage must be order or context')
    if (stage == 'context') != bool(order_report):
        raise ValueError('only context stage requires --order-report')
    baseline_root = Path(baseline_root).resolve()
    prior_path = baseline_root / 'report.json'
    prior, prior_inventory = old._json(prior_path), old._json(baseline_root / 'inventory.json')
    inventory = old.build_inventory(**inventory_kwargs)
    bare = {k: v for k, v in inventory.items() if k != 'sources'}
    if bare != prior_inventory or len(inventory['regions']) != 431:
        raise ValueError('rebuilt exact5 inventory differs from validated original 431 blocks')
    controls = {a: baseline.schedule(inventory, a) for a in baseline.ARMS}
    if controls != prior['schedules'] or controls['source_order']['estimated_tokens'] != 247339:
        raise ValueError('original control packets/cost/order differ from prior report')
    ordered = priority_order(inventory)
    lock = _freeze(inventory, ordered, prior_path)
    stage1 = verify_order_report(order_report, inventory, lock) if stage == 'context' else None
    current = expand_context(inventory) if stage == 'context' else inventory
    variant = 'dependency_context' if stage == 'context' else 'global_priority'
    current_rows = {r['region_id']: r for r in current['regions']}
    global_full = schedule_order(inventory, ordered)
    schedules = {**controls, 'global_priority': global_full}
    if stage == 'context':
        schedules[variant] = schedule_order(current, ordered, arm=variant)
    selections = []
    # All arms/divisors use exactly the SAME baseline-defined absolute units.
    # Divisors 3/5 change incurred cost, never the budget denominator.
    for divisor in (3, 4, 5):
        for fraction in FRACTIONS:
            budget = math.floor(247339 * fraction)
            for arm in schedules:
                if arm in baseline.ARMS:
                    sched = baseline.schedule(inventory, arm, budget=budget, bytes_per_token=divisor)
                else:
                    sched = schedule_order(current if arm == 'dependency_context' else inventory, ordered,
                                           budget=budget, bytes_per_token=divisor, arm=arm)
                selections.append({'fraction': fraction, 'divisor': divisor, 'absolute_budget': budget,
                                   'baseline_budget_denominator': 247339, 'schedule': sched})
    protected = [kos_root, baseline_root, BASE / 'outputs/source_store_v1', BASE / 'outputs/plan03_source_blocks_v1', BASE / 'outputs/plan04_sentence_atoms_v1']
    protected += [v if 'store' in k else Path(v).parent for k, v in inventory_kwargs.items()]
    if order_report:
        protected.append(Path(order_report).parent)
    root = _prepare_root(output_root or DEFAULT_ROOT / stage, stage, protected)
    _write(root, 'frozen_snapshot.json', lock)
    _write(root, 'selection_snapshot.json', {'schedules': schedules, 'selections': selections})
    _write(root, 'inventory.json', {k: v for k, v in current.items() if k != 'sources'})
    frozen_selection_sha = fingerprint({'schedules': schedules, 'selections': selections})
    # KOS loading/alignment happens ONLY after materializing policy, full order,
    # packet inventory, and every budget selection. No callbacks to selector.
    manifest = old._json(inventory_kwargs.get('kos_manifest', BASE / 'manifests/selected_kos_manifest.v1.json'))
    ki, units, errors = _audit_kos(inventory, kos_root, manifest)
    curves = []
    for selection in selections:
        inv = current if selection['schedule']['arm'] == 'dependency_context' else inventory
        metrics = _metrics(units, selection['schedule'], inv)
        curves.append({**selection, **metrics})
    audits = []
    for unit in units:
        arms = {}
        for arm, sched in schedules.items():
            inv = current if arm == 'dependency_context' else inventory
            arms[arm] = old._exposure(unit, sched, {r['region_id']: r for r in inv['regions']}, packets=True)
        audits.append({**unit, 'arms': arms})
    matched, selected_differences = [], []
    if stage == 'context':
        for divisor in (3, 4, 5):
            for fraction in FRACTIONS:
                pair = {c['schedule']['arm']: c for c in selections if c['divisor'] == divisor and c['fraction'] == fraction}
                a = [r['region_id'] for r in pair['global_priority']['schedule']['reads']]
                b = [r['region_id'] for r in pair['dependency_context']['schedule']['reads']]
                prefix = 0
                for x, y in zip(a, b):
                    if x != y:
                        break
                    prefix += 1
                selected_differences.append({'fraction': fraction, 'divisor': divisor,
                                             'order_sha256': lock['order_sha256'], 'shared_full_order': True,
                                             'selected_sequence_shared_prefix_length': prefix,
                                             'original_selected_ids': a, 'context_selected_ids': b,
                                             'only_original_ids': sorted(set(a) - set(b)), 'only_context_ids': sorted(set(b) - set(a)),
                                             'cause': 'cost-only skip under identical absolute budget; full order unchanged'})
                for selector, ids in [('original_budget_selected', a), ('new_context_budget_selected', b)]:
                    matched.append({'fraction': fraction, 'divisor': divisor, 'target_set_basis': selector,
                                    **_matched(inventory, current, ids, divisor)})
    target_identity = all(r['target'] == o['target'] and r['features'] == o['features'] and
                          r['packet']['target'] == o['packet']['target'] for r, o in zip(current['regions'], inventory['regions']))
    checks = {'exact5_full431_original_inventory': bare == prior_inventory,
              'baseline_controls_identical_prior_report': controls == prior['schedules'],
              'baseline_cost_247339': controls['source_order']['estimated_tokens'] == 247339,
              'full_order_all431_unique': len(ordered) == 431 and len(set(ordered)) == 431,
              'targets_features_unchanged': target_identity,
              'order_stage_packets_cost_unchanged': stage != 'order' or current is inventory,
              'context_full_order_locked': stage != 'context' or stage1['lock']['full_ordered_ids'] == ordered,
              'context_target_subtraction_union': all(old._overlap([r['target']], r['packet']['context']) == 0 and
                                                       old._length(r['packet']['context']) == sum(c['end_char'] - c['start_char'] for c in r['packet']['context']) for r in current['regions']),
              'context_caps': all(sum(c['end_char'] - c['start_char'] for c in r['packet']['context']) <= 6000 and len(r['packet']['context']) <= 12 for r in current['regions']),
              'same_baseline_absolute_budgets': all(c['absolute_budget'] == math.floor(247339 * c['fraction']) for c in selections),
              'frozen_before_kos_unchanged': frozen_selection_sha == fingerprint({'schedules': schedules, 'selections': selections}),
              'kos18_unique_alignment': not errors and len(units) == 18 and all(u['alignment']['status'] in ('exact', 'whitespace_normalized') for u in units)}
    report = {'version': 'region-priority-variants-v1', 'stage': stage, 'lock': lock,
              'frozen_snapshot_sha256': fingerprint(lock), 'selection_snapshot_sha256': frozen_selection_sha,
              'inventory_file_sha256': old._sha((root / 'inventory.json').read_bytes()),
              'order_report_binding': {'path': str(Path(order_report).resolve()), 'sha256': old._sha(Path(order_report).read_bytes())} if order_report else None,
              'protocol_checks': checks, 'protocol_status': 'pass' if all(checks.values()) else 'fail',
              'semantic_quality': 'not_assessed', 'qualified_evidence_quality': 'not_assessed',
              'schedules': schedules, 'budget_curves': curves, 'au_audit': audits,
              'kos_inventory': ki, 'kos_parse_errors': errors,
              'alignment_counts': dict(Counter(u['alignment']['status'] for u in units)),
              'matched_order_context_comparisons': matched, 'selected_set_cost_consequences': selected_differences,
              'input_owned_reference_quality_proxy': _delivery(current['regions']) if stage == 'context' else None,
              'inventory_summary': {'case_count': 5, 'block_count': 431, 'atom_count': sum(c['atom_count'] for c in inventory['cases']),
                                    'source_chars': sum(c['source_chars'] for c in inventory['cases']),
                                    'long_blocks': [{'region_id': r['region_id'], 'target_chars': r['target_chars']} for r in inventory['regions'] if r['target_chars'] > 6000],
                                    'tier_counts': dict(Counter(rank_reason(r)['tier'] for r in inventory['regions']))},
              'cost': {'method': 'ceil(serialized UTF-8 bytes / divisor) per independent request',
                       'baseline_absolute_budget_denominator': 247339, 'baseline_serialized_bytes': 988706,
                       'divisors': [3, 4, 5], 'sensitivity_budget': 'same absolute units at all divisors',
                       'packet_scaffold': old.SCAFFOLD, 'packet_top_level_fields': sorted(current['regions'][0]['packet']),
                       'transmitted_context_extra_fields': ['reasons', 'atom_ids', 'block_ids', 'dependency_status', 'role'],
                       'new_context_packet_field_names': [],
                       'host_only': ['context_audit', 'context_obligations', 'rank_reasons', 'policy and code fingerprints', 'KOS comparison', 'metrics'],
                       'actual_tokenizer': False, 'network_requests': 0, 'inference_requests': 0,
                       'latency_seconds': time.perf_counter() - started},
              'unknowns': 'budget residuals, cap residuals, unresolved ownership, unannotated source, semantic completeness remain unknown',
              'independent_reviewer_probe': 'tester owned; pending independent report'}
    _write(root, 'report.json', report)
    lines = ['# Offline sequential variant: ' + stage, '', 'Protocol: ' + report['protocol_status'] + '; semantic/qualified evidence: not assessed.',
             '', '431 original blocks; global order SHA: `' + lock['order_sha256'] + '`.',
             'Absolute budgets = floor(247339 × fraction), identical across all arms and divisors; no arm-specific normalization.',
             '', '| Fraction | Arm | Full TARGET / aligned | Full CONTEXT | Incurred estimated tokens /4 |', '|---|---|---|---|---|']
    for c in curves:
        if c['divisor'] == 4:
            lines.append(f"| {c['fraction']} | {c['schedule']['arm']} | {c['full_target_count']}/{c['denominator']} | {c['full_context_count']} | {c['schedule']['estimated_tokens']} |")
    lines += ['', 'Context outside TARGET is exposure only, never acceptance. KOS is incomplete reference, not gold.',
              'Reference ownership and whole-block delivery are lexical input-only proxies; independent tester probe pending.',
              'JSON contains full ordered IDs/rank reasons, per-case/category/AU costs and coverage, residuals and matched target sets.',
              'No model calls. Cost includes unchanged scaffold, IDs, escaping and repeated context; no actual tokenizer.',
              'Elapsed local seconds: ' + str(round(report['cost']['latency_seconds'], 3))]
    _write(root, 'summary.md', '\n'.join(lines))
    return report
