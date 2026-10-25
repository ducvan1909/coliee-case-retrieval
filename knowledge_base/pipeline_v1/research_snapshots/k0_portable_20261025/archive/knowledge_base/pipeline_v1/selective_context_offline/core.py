"""Frozen local selection, full-request costs and post-freeze diagnostics."""
from copy import deepcopy
import math
from pathlib import Path
import time

from ..region_priority_offline import core as old, scheduler as baseline
from ..region_priority_variants import core as prior
from ..region_priority_variants.context import expand_context as aggressive_context
from ..region_priority_variants.scheduler import priority_order, schedule_order
from .policy import POLICY, expand_context, request_cost, source_audit

BASE = old.BASE
DEFAULT_BASELINE = prior.DEFAULT_BASELINE
DEFAULT_ORDER_REPORT = prior.DEFAULT_ROOT / 'order/revision02/report.json'
DEFAULT_CONTEXT_REPORT = prior.DEFAULT_ROOT / 'context/revision02/report.json'
DEFAULT_ROOT = BASE / 'outputs/selective_context_offline_20261013/implementation'
FRACTIONS = prior.FRACTIONS
fingerprint = prior.fingerprint


def schedule_selective(baseline_inventory, expanded_inventory, ordered_ids, *, budget=None,
                       bytes_per_token=4, mode='preassembled', arm=None):
    """Reuse full-order scheduler with exact per-request rounded host costs.

    For two_step the temporary scheduler byte field is cost * divisor, so its
    ceil(bytes/divisor) equals ceil(first/divisor)+ceil(second/divisor).
    This host proxy is never transmitted or saved as a rendered packet.
    """
    before = {r['region_id']: r for r in baseline_inventory['regions']}
    proxy, costs = [], {}
    for row in expanded_inventory['regions']:
        cost = request_cost(before[row['region_id']], row, bytes_per_token, mode)
        costs[row['region_id']] = cost
        proxy.append({**row, 'serialized_utf8_bytes': cost['estimated_tokens'] * bytes_per_token})
    schedule = schedule_order(proxy, ordered_ids, budget=budget, bytes_per_token=bytes_per_token,
                              arm=arm or 'selective_' + mode)
    for read in schedule['reads']:
        read.update(costs[read['region_id']])
    schedule.update(mode=mode, hypothetical_input_lower_bound=True,
                    hypothetical_requests=sum(r['hypothetical_requests'] for r in schedule['reads']),
                    hypothetical_second_requests=sum(r['hypothetical_second_requests'] for r in schedule['reads']),
                    serialized_bytes=sum(r['serialized_bytes'] for r in schedule['reads']))
    return schedule


def _verify_context_report(path, inventory, aggressive, lock, order_path):
    path = Path(path).resolve()
    report = old._json(path)
    if report.get('stage') != 'context' or report.get('protocol_status') != 'pass':
        raise ValueError('completed passing context revision required')
    frozen = old._json(path.parent / 'frozen_snapshot.json')
    selection = old._json(path.parent / 'selection_snapshot.json')
    saved = old._json(path.parent / 'inventory.json')
    if frozen != lock or report['lock'] != lock or report['frozen_snapshot_sha256'] != fingerprint(lock):
        raise ValueError('context lock differs from current inputs/code/order')
    if report['selection_snapshot_sha256'] != fingerprint(selection):
        raise ValueError('context selection snapshot modified')
    if report['inventory_file_sha256'] != old._sha((path.parent / 'inventory.json').read_bytes()):
        raise ValueError('context inventory file modified')
    if saved != {k: v for k, v in aggressive.items() if k != 'sources'}:
        raise ValueError('context inventory differs from current implementation')
    binding = report['order_report_binding']
    if Path(binding['path']).resolve() != Path(order_path).resolve() or binding['sha256'] != old._sha(Path(order_path).read_bytes()):
        raise ValueError('context order report binding differs')
    if selection['schedules'] != report['schedules']:
        raise ValueError('context schedules differ from frozen selection')
    for entry in selection['selections']:
        sched = entry['schedule']
        arm, d, b = sched['arm'], entry['divisor'], entry['absolute_budget']
        if b != math.floor(247339 * entry['fraction']):
            raise ValueError('context absolute budget differs')
        rebuilt = (baseline.schedule(inventory, arm, budget=b, bytes_per_token=d) if arm in baseline.ARMS
                   else schedule_order(aggressive if arm == 'dependency_context' else inventory,
                                       lock['full_ordered_ids'], budget=b, bytes_per_token=d, arm=arm))
        if sched != rebuilt:
            raise ValueError('context budget selection differs from current helpers')
    return report


def _matched_cost(inventory, expanded, aggressive, ids, divisor):
    original = {r['region_id']: r for r in inventory['regions']}
    totals = {}
    for name, current in [('baseline', inventory), ('aggressive', aggressive), ('selective', expanded)]:
        by_id = {r['region_id']: r for r in current['regions']}
        totals[name] = {}
        for mode in ('preassembled', 'two_step'):
            costs = [request_cost(original[rid], by_id[rid], divisor, mode) for rid in ids]
            totals[name][mode] = {k: sum(c[k] for c in costs) for k in
                                 ('serialized_bytes', 'estimated_tokens', 'hypothetical_requests', 'hypothetical_second_requests')}
    dependencies = []
    by_id = {r['region_id']: r for r in expanded['regions']}
    seen = set()
    for rid in ids:
        for ref in by_id[rid]['context_audit']['input_reference_hints']:
            if not ref['ownership_confirmed_local']:
                continue
            key = (rid, ref['start_char'], ref['bridge_block_id'])
            if key in seen:
                continue
            seen.add(key)
            spans = [ref['required_span']] + ([ref['bridge_span']] if ref['bridge_span'] else [])
            delivered = {}
            for name, current in [('baseline', inventory), ('aggressive', aggressive), ('selective', expanded)]:
                row = next(r for r in current['regions'] if r['region_id'] == rid)
                delivered[name] = all(old._overlap([s], [row['target']] + row['packet']['context']) == s['end_char'] - s['start_char'] for s in spans)
            dependencies.append({'region_id': rid, 'reference_start_char': ref['start_char'],
                                 'required_span': ref['required_span'], 'bridge_span': ref['bridge_span'],
                                 'whole_owned_dependency_delivery': delivered})
    return {'selected_target_ids': ids, 'selected_set_sha256': fingerprint(ids), 'costs': totals,
            'whole_owned_dependency_delivery': dependencies}


def run(*, output_root, baseline_root=DEFAULT_BASELINE, order_report=DEFAULT_ORDER_REPORT,
        context_report=DEFAULT_CONTEXT_REPORT, kos_root=Path('G:/Legal-AI/kos_sample'), **inventory_kwargs):
    """Validate existing locks, freeze packets/selections, then load KOS once."""
    started = time.perf_counter()
    output = Path(output_root).resolve()
    protected = [baseline_root, prior.DEFAULT_ROOT, kos_root, BASE / 'outputs/source_store_v1',
                 BASE / 'outputs/plan03_source_blocks_v1', BASE / 'outputs/plan04_sentence_atoms_v1',
                 Path(order_report).parent, Path(context_report).parent]
    protected += [v if 'store' in k else Path(v).parent for k, v in inventory_kwargs.items()]
    for path in protected:
        p = Path(path).resolve()
        if output == p or output in p.parents or p in output.parents:
            raise ValueError('output overlaps protected input: ' + str(p))
    if output.exists() and any(output.iterdir()):
        raise ValueError('nonempty output; overwrite refused: ' + str(output))
    if output == DEFAULT_ROOT.parent.resolve():
        raise ValueError('Main owns output root; use implementation child')
    inventory = old.build_inventory(**inventory_kwargs)
    baseline_path = Path(baseline_root) / 'report.json'
    original_report = old._json(baseline_path)
    if {k: v for k, v in inventory.items() if k != 'sources'} != old._json(Path(baseline_root) / 'inventory.json'):
        raise ValueError('current source inventory differs from baseline')
    controls = {a: baseline.schedule(inventory, a) for a in baseline.ARMS}
    if controls != original_report['schedules'] or controls['source_order']['estimated_tokens'] != 247339:
        raise ValueError('baseline schedules/cost differ')
    ordered = priority_order(inventory)
    lock = prior._freeze(inventory, ordered, baseline_path)
    prior.verify_order_report(order_report, inventory, lock)
    aggressive = aggressive_context(inventory)
    _verify_context_report(context_report, inventory, aggressive, lock, order_report)
    expanded = expand_context(inventory)
    inventories = {'global_priority': inventory, 'aggressive_preassembled': aggressive,
                   'aggressive_two_step': aggressive, 'selective_preassembled': expanded,
                   'selective_two_step': expanded}
    def schedule(arm, budget=None, divisor=4):
        if arm in baseline.ARMS:
            return baseline.schedule(inventory, arm, budget=budget, bytes_per_token=divisor)
        if arm == 'global_priority':
            return schedule_order(inventory, ordered, budget=budget, bytes_per_token=divisor)
        mode = 'two_step' if arm.endswith('two_step') else 'preassembled'
        return schedule_selective(inventory, inventories[arm], ordered, budget=budget,
                                  bytes_per_token=divisor, mode=mode, arm=arm)
    arms = list(baseline.ARMS) + list(inventories)
    schedules = {a: schedule(a) for a in arms}
    selections = [{'fraction': f, 'divisor': d, 'absolute_budget': math.floor(247339 * f),
                   'baseline_budget_denominator': 247339, 'schedule': schedule(a, math.floor(247339 * f), d)}
                  for d in (3, 4, 5) for f in FRACTIONS for a in arms]
    frozen_selection = {'schedules': schedules, 'selections': selections}
    frozen_inventory = {k: v for k, v in expanded.items() if k != 'sources'}
    bindings = [{'path': str(Path(p).resolve()), 'sha256': old._sha(Path(p).read_bytes())}
                for p in (baseline_path, order_report, context_report)]
    code = prior.implementation_fingerprints() + [
        {'path': str(p.resolve()), 'sha256': old._sha(p.read_bytes())} for p in sorted(Path(__file__).parent.glob('*.py'))]
    frozen = {'version': 'selective-context-lock-v1', 'prior_lock': lock, 'report_bindings': bindings,
              'policy': POLICY, 'policy_sha256': fingerprint(POLICY), 'implementation_fingerprints': code,
              'inventory_sha256': fingerprint(frozen_inventory), 'selection_sha256': fingerprint(frozen_selection)}
    output.mkdir(parents=True, exist_ok=True)
    prior._write(output, 'frozen_snapshot.json', frozen)
    prior._write(output, 'inventory.json', frozen_inventory)
    prior._write(output, 'selection_snapshot.json', frozen_selection)
    audit = source_audit(expanded)
    prior._write(output, 'source_audit.json', audit)
    # All selection-affecting decisions are now persisted. No changes after KOS.
    manifest = old._json(inventory_kwargs.get('kos_manifest', BASE / 'manifests/selected_kos_manifest.v1.json'))
    ki, units, errors = prior._audit_kos(inventory, kos_root, manifest)
    curves = []
    for entry in selections:
        inv = inventories.get(entry['schedule']['arm'], inventory)
        metrics = prior._metrics(units, entry['schedule'], inv)
        curves.append({**entry, **metrics})
    matched = []
    for d in (3, 4, 5):
        for f in FRACTIONS:
            for arm in inventories:
                entry = next(e for e in selections if e['divisor'] == d and e['fraction'] == f and e['schedule']['arm'] == arm)
                ids = [r['region_id'] for r in entry['schedule']['reads']]
                matched.append({'fraction': f, 'divisor': d, 'target_set_basis': arm,
                                **_matched_cost(inventory, expanded, aggressive, ids, d)})
    # Diagnostic known-gap probe chosen after freeze, never a selector input.
    probes = []
    import re
    targets = {r['region_id']: r for r in inventory['regions']}
    required = [r['target'] for r in inventory['regions'] if r['case_id'] == '045155'
                and r['block_type'] == 'numbered_paragraph' and re.match(r'\s*\[5\]', r['packet']['target']['text'])]
    for row in expanded['regions']:
        if row['case_id'] == '045155' and re.match(r'\s*\[21\]', row['packet']['target']['text']):
            probes.append({'region_id': row['region_id'], 'diagnostic_only_selected_after_freeze': True,
                           'scope': 'known development/calibration gap; not heldout',
                           'required_paragraph_5_unique': len(required) == 1,
                           'baseline_packet': targets[row['region_id']]['packet'], 'selective_packet': row['packet'],
                           'required_paragraph_5_whole_delivery': len(required) == 1 and old._overlap(required, [row['target']] + row['packet']['context']) == old._length(required),
                           'audit': row['context_audit']})
    checks = {
        'baseline_and_revision02_locks_verified': True,
        'full431_order_unique': len(ordered) == 431 and len(set(ordered)) == 431,
        'targets_features_unchanged': all(r['target'] == b['target'] and r['features'] == b['features'] and r['packet']['target'] == b['packet']['target'] for r, b in zip(expanded['regions'], inventory['regions'])),
        'baseline_context_preserved': all(old._overlap(b['packet']['context'], r['packet']['context']) == old._length(b['packet']['context']) for r, b in zip(expanded['regions'], inventory['regions'])),
        'noop_packets_byte_identical': all(r['serialized_payload'] == b['serialized_payload'] and r['packet'] == b['packet'] for r, b in zip(expanded['regions'], inventory['regions']) if not r['context_audit']['packet_changed']),
        'context_union_target_subtraction_caps': all(old._overlap([r['target']], r['packet']['context']) == 0 and old._length(r['packet']['context']) == sum(c['end_char'] - c['start_char'] for c in r['packet']['context']) and old._length(r['packet']['context']) <= 6000 and len(r['packet']['context']) <= 12 for r in expanded['regions']),
        'frozen_unchanged_after_kos': fingerprint(frozen_inventory) == frozen['inventory_sha256'] and fingerprint(frozen_selection) == frozen['selection_sha256'] and fingerprint(POLICY) == frozen['policy_sha256'],
        'current_inputs_and_code_unchanged': all(old._sha(Path(b['path']).read_bytes()) == b['sha256'] for b in bindings + code + inventory['input_bindings'] + inventory['artifact_bindings']),
        'kos18_unique_alignment': not errors and len(units) == 18 and all(u['alignment']['status'] in ('exact', 'whitespace_normalized') for u in units),
    }
    report = {'version': 'selective-context-offline-v1', 'protocol_status': 'pass' if all(checks.values()) else 'fail',
              'protocol_checks': checks, 'semantic_quality': 'not_assessed', 'evaluation_split': 'development/calibration; not heldout',
              'frozen_snapshot_sha256': fingerprint(frozen), 'selection_snapshot_sha256': frozen['selection_sha256'],
              'inventory_file_sha256': old._sha((output / 'inventory.json').read_bytes()),
              'bindings': bindings, 'schedules': schedules, 'budget_curves': curves,
              'target_matched_cost': matched, 'source_audit': audit['counts'], 'source_audit_path': 'source_audit.json',
              'packet_probes': probes, 'kos_inventory': ki, 'kos_parse_errors': errors,
              'cost': {'method': 'per full request ceil(serialized UTF-8 bytes / divisor)', 'divisors': [3, 4, 5],
                       'baseline_absolute_budget_denominator': 247339, 'network_requests': 0, 'inference_requests': 0,
                       'actual_requests': 0, 'actual_provider_tokens': 0,
                       'two_step': 'hypothetical input LOWER BOUND; baseline request plus full expanded request on changed rows; separately rounded',
                       'excluded_costs': ['output', 'planner', 'tool', 'retry'], 'real_agent_decision': False,
                       'host_metadata_transmitted': False, 'actual_tokenizer': False,
                       'latency_seconds': time.perf_counter() - started},
              'unknowns': ['unread targets', 'ownership unresolved', 'whole bundle caps', 'semantic completeness', 'agent decision quality'],
              'independent_testing': 'tester owned; not asserted by implementation run'}
    prior._write(output, 'report.json', report)
    lines = ['# Local selective context', '', 'Protocol: ' + report['protocol_status'] + '; semantic quality: not assessed.',
             'KOS-5 is development/calibration, not heldout. Actual requests: 0.',
             'Two-step cost is a hypothetical input lower bound, excluding output/planner/tool/retry.', '',
             '| Fraction | Arm | TARGET /18 | CONTEXT /18 | Input estimate /4 |', '|---|---|---|---|---|']
    lines += [f"| {e['fraction']} | {e['schedule']['arm']} | {e['full_target_count']} | {e['full_context_count']} | {e['schedule']['estimated_tokens']} |" for e in curves if e['divisor'] == 4]
    prior._write(output, 'summary.md', '\n'.join(lines))
    return report
