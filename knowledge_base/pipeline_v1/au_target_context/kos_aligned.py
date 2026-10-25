"""Local reference-guided same-source KOS calibration; never semantic gold."""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

from . import core
from .contracts import BUDGET, OUTPUT_CAP, MAX_ANCHORS, VERSION
from .prompts import prompt_metadata, DEFAULT_PROMPT_PROFILE
from ..au_context_paired.build import (DEFAULT_SOURCE_STORE, DEFAULT_ATOM_ROOT,
    read_json, write_new, fingerprint, binding, verify_bindings, make_request)
from ..au_context_paired.preflight import validate_workload
from ..au_presentation_paired.core import DEFAULT_PARENT, profile
from ..au_compact.manifest import _binding_for, _binding_path
from ..kos_comparison.comparison import _load_kos, align_evidence, _overlap
from ..source_contract import open_source

BASE = Path(__file__).resolve().parents[1]
DEFAULT_KOS_MANIFEST = BASE / 'manifests/selected_kos_manifest.v1.json'
DEFAULT_KOS_ROOT = Path('G:/Legal-AI/kos_sample')
ARTIFACT = 'AUKOSAlignedWorkload'
SELECTOR = {'version': 'kos-full-blocks-v1', 'selection': 'reference_guided_calibration',
            'context_blocks_each_side': 1, 'merge': 'same_or_overlapping_blocks',
            'boundary_fallback': 'full_paragraphs_with_printed_markers'}
CASES = {'013009': 0, '013948': 0, '011904': 8, '045155': 5, '099980': 5}
LIMITS = ['Reference-guided selected regions only; not blind full-case coverage.',
          'KOS is a reference, not human gold; overlap does not establish correctness.',
          'Semantic review pending; no precision/recall/F1 or retrieval quality claim.',
          'At most three pipeline anchors per TARGET; dense regions can saturate this cap.']


def _cfg(parent):
    identity = parent['identity']
    return {**identity, 'jobs_url': identity['url'].removesuffix('/chat/completions') + '/jobs'}


def _blocks(atom_map, source, case_id, source_hash):
    """Use bound full parent spans if they partition source, else source-only paragraphs."""
    refs = atom_map.get('parent_block_refs', [])
    spans = [r.get('span', {}) for r in refs]
    cursor = 0
    valid = bool(spans)
    for span in spans:
        a, b = span.get('start_char'), span.get('end_char')
        valid = valid and (type(a) is int and type(b) is int and a == cursor and a < b <= len(source)
                          and span.get('case_id') == case_id and span.get('source_hash') == source_hash)
        if not valid:
            break
        cursor = b
    if valid and cursor == len(source):
        return [{'start_char': s['start_char'], 'end_char': s['end_char']} for s in spans], 'bound_atom_parent_blocks'
    # Keep printed markers and all intervening whitespace. Never use content_span/quote crops.
    cuts = {0, len(source)}
    cuts.update(m.end() for m in re.finditer(r'\n[ \t]*\n', source))
    cuts.update(m.start() for m in re.finditer(r'(?m)^[ \t]*\[\d+\][ \t]*', source))
    points = sorted(cuts)
    return [{'start_char': a, 'end_char': b} for a, b in zip(points, points[1:]) if a < b], 'deterministic_full_paragraphs'


def _materialize(*, kos_root, selected_kos_manifest, source_store, atom_root):
    manifest = read_json(selected_kos_manifest)
    core.require({c['case_id'] for c in manifest['cases']} == set(CASES), 'requires all five selected KOS trees')
    inventory, units, errors = _load_kos(kos_root, manifest)
    core.require(not errors, 'KOS parsing failed')
    core.require({c: sum(u['case_id'] == c for u in units) for c in CASES} == CASES,
                 'requires exact 18 candidate references and zero query references')
    atom_manifest_path = Path(atom_root) / 'sentence_atom_build_manifest.json'
    atom_manifest = read_json(atom_manifest_path)
    core.require(atom_manifest.get('status') == 'pass', 'atom manifest is not pass')
    bindings = [binding(selected_kos_manifest), binding(atom_manifest_path)]
    # Include imported source/alignment/catalog implementations beyond core.code_hash.
    from ..kos_comparison import comparison
    from ..source_contract import store
    from ..au_compact import core as compact_core, manifest as compact_manifest
    bindings.extend(binding(m.__file__) for m in (comparison, store, compact_core, compact_manifest))
    rows, references, sources, selections, case_reports = [], [], [], [], []
    for case_id, count in CASES.items():
        matches = [r for r in atom_manifest['cases'] if r['case_id'] == case_id]
        core.require(len(matches) == 1, 'atom manifest requires unique case selection')
        source_hash = matches[0]['source_hash']
        source = open_source(source_store, case_id, source_hash)
        atom_binding = _binding_for({'case_id': case_id, 'source_hash': source_hash}, atom_root, atom_manifest)
        atom_path = Path(_binding_path(atom_binding, atom_root)['atom_map_path'])
        bindings.append(binding(atom_path))
        atom_map = read_json(atom_path)
        blocks, method = _blocks(atom_map, source, case_id, source_hash)
        sources.append({'case_id': case_id, 'source_hash': source_hash, 'atom_binding': atom_binding,
                        'blocks_sha256': fingerprint(blocks), 'boundary_method': method})
        case_reports.append({'case_id': case_id, 'reference_count': count,
                             'status': 'no_reference' if not count else 'reference_guided_calibration',
                             'is_negative': False})
        intervals, local_refs = [], []
        for unit in [u for u in units if u['case_id'] == case_id]:
            alignment = align_evidence(unit['evidence_text'], source)
            core.require(alignment['status'] in ('exact', 'whitespace_normalized') and len(alignment['spans']) == 1,
                         'reference evidence must align unambiguously')
            span = alignment['spans'][0]
            indices = [i for i, block in enumerate(blocks) if _overlap([span], [block])]
            core.require(bool(indices), 'reference evidence outside source blocks')
            first, last = min(indices), max(indices)
            core.require(blocks[first]['start_char'] <= span['start_char'] < span['end_char'] <= blocks[last]['end_char'],
                         'incomplete evidence block coverage')
            intervals.append((first, last))
            local_refs.append({**unit, 'source_hash': source_hash, 'alignment': alignment})
        # Merge shared or overlapping block ranges only; adjacent disjoint TARGETs stay separate.
        merged = []
        for first, last in sorted(intervals):
            if merged and first <= merged[-1][1]:
                merged[-1][1] = max(last, merged[-1][1])
            else:
                merged.append([first, last])
        for first, last in merged:
            target = {'case_id': case_id, 'source_hash': source_hash,
                      'start_char': blocks[first]['start_char'], 'end_char': blocks[last]['end_char']}
            context = [blocks[i] for i in (first - 1, last + 1) if 0 <= i < len(blocks)]
            region_id = 'kos-region-' + fingerprint([target, SELECTOR])[:24]
            request = make_request({'region_id': region_id, 'case_id': case_id, 'source_hash': source_hash,
                                    'target': target, 'packet': {'context': context}}, atom_root)
            row = core.clipped_row(request, source_store, atom_root)
            # Atom expansion must not extend the fixed full-block context policy,
            # including when fallback paragraph seams lie inside an atom.
            bounded_context = {}
            for ref in row['context_refs'].values():
                for block in context:
                    start = max(ref['start_char'], block['start_char'])
                    end = min(ref['end_char'], block['end_char'])
                    if start < end:
                        rid = 'c-' + fingerprint([case_id, source_hash, ref['source_atom_id'], start, end, 'context'])[:24]
                        bounded_context[rid] = {**ref, 'ref_id': rid, 'start_char': start,
                                                'end_char': end, 'quote': source[start:end]}
            row['context_refs'] = bounded_context
            row['pair_id'] = region_id
            row.update(prompt_metadata('primary_support_v1'))
            rows.append(row)
            selections.append({'case_id': case_id, 'target_id': row['target_id'], 'target': target,
                               'context': context, 'block_indices': [first, last]})
            associated = [r for r in local_refs if _overlap(r['alignment']['spans'], [target])]
            for ref in associated:
                ref['target_id'] = row['target_id']
        references.extend(local_refs)
    core.require(bool(rows) and len(rows) * 2 <= BUDGET['max_requests'], 'TARGET request bound exceeded')
    density = [{'target_id': row['target_id'], 'kos_reference_count': sum(r['target_id'] == row['target_id'] for r in references),
                'max_pipeline_anchors': MAX_ANCHORS} for row in rows]
    for item in density:
        item['saturation_risk'] = item['kos_reference_count'] > MAX_ANCHORS
    reference = {'artifact_type': 'AUKOSAlignedReferenceChecklist', 'version': 1,
                 'selector': SELECTOR, 'cases': case_reports, 'kos_inventory': inventory,
                 'references': references, 'target_reference_density': density,
                 'semantic_review_status': 'semantic_review_pending', 'limitations': LIMITS}
    reference['reference_sha256'] = fingerprint(reference)
    return rows, reference, {'input_bindings': bindings, 'sources': sources,
                             'selector': SELECTOR, 'selected_regions': selections}


def prepare(output_root, *, kos_root=DEFAULT_KOS_ROOT, selected_kos_manifest=DEFAULT_KOS_MANIFEST,
            source_store=DEFAULT_SOURCE_STORE, atom_root=DEFAULT_ATOM_ROOT, parent=DEFAULT_PARENT, cfg=None):
    root = Path(output_root).resolve()
    inputs = {'kos_root': str(Path(kos_root).resolve()),
              'selected_kos_manifest': str(Path(selected_kos_manifest).resolve()),
              'source_store': str(Path(source_store).resolve()), 'atom_root': str(Path(atom_root).resolve())}
    core.guard_output(root, [*inputs.values(), DEFAULT_PARENT.parent, core.DEFAULT_MANIFEST.parent,
                             *([parent] if isinstance(parent, (str, Path)) else [])])
    core.require(not root.exists(), 'prepare output must be a new directory')
    p = core.load(parent)
    validate_workload(p, cfg=cfg)
    profile(p, cfg if cfg is not None else _cfg(p))
    rows, reference, selection = _materialize(**inputs)
    w = {'artifact_type': ARTIFACT, 'version': VERSION, **prompt_metadata('primary_support_v1'),
         **inputs, **selection, 'parent_workload': p, 'parent_workload_sha256': p['workload_sha256'],
         'identity': copy.deepcopy(p['identity']), 'rows': rows, 'budget': dict(BUDGET),
         'output_cap': OUTPUT_CAP, 'code_sha256': core.code_hash(), 'semantic_gold': False,
         'reference_checklist_path': str(root / 'reference_checklist.json'),
         'reference_checklist_sha256': reference['reference_sha256'],
         'context_policy': 'one_adjacent_full_source_block_each_side', 'limitations': LIMITS}
    w['workload_sha256'] = fingerprint(w)
    # Both files exist before preflight; preflight re-reads the reference independently.
    write_new(root / 'reference_checklist.json', reference)
    write_new(root / 'workload.json', w)
    checked = preflight(w, cfg=cfg)
    write_new(root / 'preflight.json', checked)
    return w


def preflight(workload, *, cfg=None):
    w = core.load(workload)
    digest = w.pop('workload_sha256', None)
    core.require(digest == fingerprint(w), 'workload digest mismatch')
    core.require(w['artifact_type'] == ARTIFACT and w['version'] == VERSION, 'unknown KOS workload')
    core.require(w['code_sha256'] == core.code_hash(), 'code binding changed')
    p = w['parent_workload']
    validate_workload(p, cfg=cfg)
    profile(p, cfg if cfg is not None else _cfg(p))
    core.require(w['parent_workload_sha256'] == p['workload_sha256'] and w['identity'] == p['identity'], 'parent/runtime binding mismatch')
    core.require(w['budget'] == BUDGET and w['output_cap'] == OUTPUT_CAP and w['semantic_gold'] is False,
                 'budget/cap/reference role changed')
    verify_bindings(w['input_bindings'])
    rows, reference, selection = _materialize(**{k: w[k] for k in ('kos_root', 'selected_kos_manifest', 'source_store', 'atom_root')})
    core.require(all(w[k] == v for k, v in selection.items()) and w['rows'] == rows, 'source-only selector/rows mismatch')
    prompts = prompt_metadata('primary_support_v1')
    core.require(all(w[k] == v for k, v in prompts.items()), 'primary_support profile changed')
    core.require(w['context_policy'] == 'one_adjacent_full_source_block_each_side' and w['limitations'] == LIMITS, 'policy changed')
    actual = read_json(w['reference_checklist_path'])
    core.require(actual == reference and w['reference_checklist_sha256'] == reference['reference_sha256'], 'reference checklist mismatch')
    jobs = [core.build_stage1(row, w['identity']) for row in rows]
    sizes = [len(j['payload']['messages'][0]['content'].encode('utf-8')) for j in jobs]
    baseline = [len(core.build_stage1({**row, **prompt_metadata(DEFAULT_PROMPT_PROFILE)}, w['identity'])['payload']['messages'][0]['content'].encode('utf-8')) for row in rows]
    core.require(len({j['request_id'] for j in jobs}) == len(rows) and sum(sizes) <= BUDGET['max_total_input_tokens'], 'stage1 job/budget overflow')
    return {'artifact_type': 'AUKOSAlignedPreflight', 'status': 'pass', 'workload_sha256': digest,
            **prompts, 'target_count': len(rows), 'stage1_requests': len(rows), 'max_logical_requests': 2 * len(rows),
            'stage1_input_reservation_utf8_bytes': sum(sizes),
            'stage1_baseline_input_reservation_utf8_bytes': sum(baseline),
            'stage1_added_input_utf8_bytes': sum(sizes) - sum(baseline),
            'stage1_max_added_input_utf8_bytes_per_target': max([0] + [s-b for s,b in zip(sizes,baseline)]),
            'reference_count': len(reference['references']), 'cases': reference['cases'],
            'target_reference_density': reference['target_reference_density'],
            'budget': dict(BUDGET), 'network_requests': 0, 'semantic_quality': 'not_assessed',
            'semantic_review_status': 'semantic_review_pending', 'limitations': LIMITS}


def compare(workload, run, reference_checklist, output_root):
    """Read validated partial checkpoints; never dispatch or mutate the run."""
    from .runner import _receipt
    w = core.load(workload)
    preflight(w)
    root, run_path, ref_path = Path(output_root).resolve(), Path(run).resolve(), Path(reference_checklist).resolve()
    core.guard_output(root, [Path(workload).resolve().parent, run_path.parent, ref_path.parent,
                             w['source_store'], w['atom_root'], w['kos_root'], DEFAULT_PARENT.parent, core.DEFAULT_MANIFEST.parent])
    core.require(not root.exists(), 'comparison output must be a new directory')
    reference = read_json(ref_path)
    core.require(reference == read_json(w['reference_checklist_path']), 'comparison reference differs from workload')
    report = read_json(run_path)
    ledger_path = run_path.parent / 'runtime_ledger.json'
    core.require(ledger_path.is_file() and not (run_path.parent / '.runner.lock').exists(),
                 'comparison requires stopped runner checkpoint')
    ledger = read_json(ledger_path)
    bound = ledger['binding']
    core.require(ledger.get('ledger_sha256') == fingerprint({k:v for k,v in ledger.items() if k != 'ledger_sha256'}), 'ledger digest mismatch')
    core.require(bound['mode'] in ('mock', 'execute'), 'unknown run mode')
    expected_profile = profile(w['parent_workload'], _cfg(w['parent_workload']))
    for key in ('timeout', 'job_wait_seconds', 'job_poll_seconds', 'runtime_revision_setting_present'):
        expected_profile[key] = bound['run_profile'][key]
    expected_bound = {'workload_sha256': w['workload_sha256'], 'code_sha256': core.code_hash(),
                      'prompt_profile': w['prompt_profile'], 'prompt_sha': w['prompt_sha'],
                      'selected_target_ids': bound['selected_target_ids'], 'mode': bound['mode'],
                      'run_profile': expected_profile, 'budget': w['budget'], 'concurrency': bound['concurrency']}
    core.require(bound == expected_bound and ledger['identity'] == fingerprint(bound) == report['identity']
                 and report['mode'] == bound['mode'], 'run binding mismatch')
    selected = bound['selected_target_ids']
    core.require(bool(selected) and len(selected) == len(set(selected))
                 and set(selected) <= {r['target_id'] for r in w['rows']}, 'unknown selected targets')
    core.require(type(bound['concurrency']) is int and 1 <= bound['concurrency'] <= 4, 'invalid concurrency')
    core.require(ledger['provider_attempts'] == len(ledger['attempts']) <= BUDGET['max_provider_attempts']
                 and len(ledger['jobs']) <= BUDGET['max_requests'], 'run request counters mismatch')
    for field, cap in (('reserved_input_tokens', 'max_total_input_tokens'), ('reserved_output_tokens', 'max_total_output_tokens')):
        core.require(ledger[field] == sum(a[field] for a in ledger['attempts']) <= BUDGET[cap], 'reservation counters mismatch')
    allowed_jobs, anchors, stage1_candidates, targets, receipts = {}, [], [], [], []

    def checkpoint(job):
        allowed_jobs[job['request_id']] = job
        entry = ledger['jobs'].get(job['request_id'])
        if entry is None:
            return 'not_dispatched', None
        core.require(entry['job'] == job and entry['status'] in ('reserved', 'pending', 'verified', 'invalid', 'failed'), 'run job mismatch')
        if entry['status'] == 'reserved':
            core.require(not entry.get('receipt_sha256'), 'reserved job has receipt')
            return 'not_dispatched', None
        receipt = _receipt(run_path.parent, entry)
        receipts.append(receipt)
        core.require(receipt['status'] == entry['status'], 'receipt status mismatch')
        if entry['status'] != 'verified':
            return 'provider_or_protocol_failure' if entry['status'] in ('invalid', 'failed') else 'pending', None
        # Revalidate the provider envelope as well as normalized host evidence.
        body = receipt['raw_response']
        choice = body['choices'][0]
        core.require(body.get('model') == w['identity']['model'] and choice.get('finish_reason') == 'stop', 'receipt envelope mismatch')
        def unique(items):
            core.require(len({k for k, _ in items}) == len(items), 'duplicate receipt JSON keys')
            return dict(items)
        raw = json.loads(choice['message']['content'], object_pairs_hook=unique)
        core.require(raw == receipt['model_output'], 'receipt model output changed')
        normalized = (core.validate_stage1 if job['stage'] == 1 else core.validate_stage2)(raw, job)
        core.require(normalized == receipt['normalized'], 'normalized receipt mismatch')
        return 'verified', normalized

    def candidates(output, row, layer):
        return [{'target_id': row['target_id'], 'case_id': row['case_id'], 'source_hash': row['source_hash'],
                 **a, 'candidate_layer': layer, 'semantic_review_status': 'semantic_review_pending'}
                for a in output['anchors']]

    for row in w['rows']:
        tid = row['target_id']
        if tid not in selected:
            targets.append({'target_id': tid, 'case_id': row['case_id'], 'status': 'out_of_scope'})
            continue
        one_status, one = checkpoint(core.build_stage1(row, w['identity']))
        final, two_status = one, 'not_needed'
        if one is not None:
            stage1_candidates.extend(candidates(one, row, 'stage1_candidate'))
            jobs = core.build_stage2(row, one, w['identity'])
            if jobs:
                two_status, final = checkpoint(jobs[0])
        status = (one_status if one is None else two_status if final is None else
                  'unresolved' if final['decision'] in ('unresolved', 'revisit_target', 'needs_context')
                  or any(a['status'] in ('unresolved', 'needs_context') for a in final['anchors']) else
                  'rejected' if final['anchors'] and all(a['status'] == 'reject' for a in final['anchors']) else 'resolved')
        if final is not None:
            anchors.extend(candidates(final, row, 'final'))
        targets.append({'target_id': tid, 'case_id': row['case_id'], 'status': status,
                        'stage1_status': one_status, 'stage2_status': two_status,
                        'stage1_output': one, 'final_output': final,
                        'stage1_anchor_count': len(one['anchors']) if one else 0,
                        'final_anchor_count': len(final['anchors']) if final else 0,
                        'anchor_cap_reached': bool(one and len(one['anchors']) == MAX_ANCHORS)})
    core.require(set(ledger['jobs']) <= set(allowed_jobs), 'foreign run jobs')
    # Report status/output is a convenience snapshot only. All comparisons below
    # use the validated receipts, including partial and failed stage2 checkpoints.
    states = {t['target_id']: t['status'] for t in targets}
    comparisons = []
    def matches(ref, items):
        found = []
        for anchor in items:
            if anchor['case_id'] != ref['case_id'] or anchor['source_hash'] != ref['source_hash']:
                continue
            evidence = anchor['primary_evidence'] + anchor.get('supporting_evidence', [])
            overlap = _overlap(ref['alignment']['spans'], evidence)
            if overlap:
                found.append({'anchor': anchor, 'evidence_overlap_characters': overlap,
                              'primary_overlap_characters': _overlap(ref['alignment']['spans'], anchor['primary_evidence']),
                              'semantic_review_status': 'semantic_review_pending'})
        return found
    for ref in reference['references']:
        found = matches(ref, anchors)
        status = states[ref['target_id']]
        if status == 'resolved':
            status = 'overlap_candidates' if found else 'no_overlap'
        comparisons.append({'reference': ref, 'status': status, 'candidates': found,
                            'kept_overlap_candidates': [c for c in found if c['anchor']['status'] == 'provisional_au'],
                            'unresolved_overlap_candidates': [c for c in found if c['anchor']['status'] in ('unresolved', 'needs_context')],
                            'rejected_overlap_candidates': [c for c in found if c['anchor']['status'] == 'reject'],
                            'stage1_overlap_candidates': matches(ref, stage1_candidates),
                            'semantic_review_status': 'semantic_review_pending'})
    def reverse(items, key):
        result = []
        for anchor in items:
            kos_ids = [r['reference']['kos_id'] for r in comparisons for c in r[key]
                       if c['anchor']['anchor_id'] == anchor['anchor_id'] and c['anchor']['target_id'] == anchor['target_id']]
            result.append({'anchor': anchor, 'kos_overlap_candidates': kos_ids,
                           'status': 'unresolved' if anchor['status'] in ('unresolved', 'needs_context') else 'rejected' if anchor['status'] == 'reject' else 'overlap_candidates' if kos_ids else 'no_overlap',
                           'semantic_review_status': 'semantic_review_pending'})
        return result
    usage = [r['usage'] for r in receipts if r.get('usage') is not None]
    prior = ledger.get('recovery_prior_accounting', {})
    if prior:
        migration = read_json(prior['manifest_path'])
        core.require(migration['recovery_sha256'] == prior['manifest_sha256'] == fingerprint(
            {k:v for k,v in migration.items() if k != 'recovery_sha256'}), 'recovery manifest mismatch')
        core.require(migration['prior_accounting'] == {k:v for k,v in prior.items()
                     if k not in ('manifest_path', 'manifest_sha256')}, 'recovery counters changed')
    new_usage = [r['usage'] for r in receipts if r.get('usage') is not None and not r.get('import_provenance')]
    new_subtotal = {k:sum(u.get(k, 0) for u in new_usage) for k in ('input_tokens','output_tokens','total_tokens')}
    previous_usage = prior.get('known_provider_usage', prior.get('known_provider_usage_observed_subtotal', {}))
    summary = {'logical_requests': len(ledger['jobs']), 'transport_POST_attempts': len(ledger['attempts']),
               'provider_POST_attempts': len(ledger['attempts']) if bound['mode'] == 'execute' else 0,
               'GET_polls': ledger['get_polls'], 'reserved_input_utf8_bytes': ledger['reserved_input_tokens'],
               'reserved_output_tokens': ledger['reserved_output_tokens'],
               'known_provider_usage_observed_subtotal': {k: sum(u.get(k, 0) for u in usage) for k in ('input_tokens', 'output_tokens', 'total_tokens')},
               'unknown_usage_jobs': sum(r.get('usage') is None for r in receipts),
               'usage_is_complete': False, 'usage_note': 'Observed terminal receipt subtotal only; retries or pending attempts may be unknown; mock is not provider usage.',
               'new_generation_usage_observed_subtotal': new_subtotal,
               'previous_run_usage_observed_subtotal': previous_usage,
               'cumulative_usage_observed_subtotal': {k: previous_usage.get(k,0) + new_subtotal[k] for k in new_subtotal},
               'imported_verified_jobs': sum(bool(r.get('import_provenance')) for r in receipts),
               'aggregate_provider_POST_attempts': prior.get('provider_attempts',0) + len(ledger['attempts'])
                   if bound['mode'] == 'execute' else 0,
               'POST_ack_latency_ms': sum(a.get('latency_ms', 0) for a in ledger['attempts']),
               'receipt_client_latency_ms': sum(r.get('latency_ms', 0) for r in receipts),
               'status_counts': {s: sum(t['status'] == s for t in targets) for s in sorted(set(states.values()))}}
    result = {'artifact_type': 'AUKOSAlignedComparison', 'workload_sha256': w['workload_sha256'],
              'mode': bound['mode'], 'status': 'semantic_review_pending', 'semantic_review_status': 'semantic_review_pending',
              'cases': reference['cases'], 'references': comparisons, 'pipeline_anchors': reverse(anchors, 'candidates'),
              'stage1_candidates': reverse(stage1_candidates, 'stage1_overlap_candidates'), 'targets': targets,
              'target_reference_density': reference['target_reference_density'],
              'reference_count': len(comparisons), 'pipeline_anchor_count': len(anchors),
              'execution_summary': summary, 'limitations': LIMITS,
              'run_binding': binding(run_path), 'ledger_binding': binding(ledger_path),
              'report_status_policy': 'derived_from_validated_receipts; report status/output not trusted'}
    # Reject a concurrent checkpoint change rather than combine different snapshots.
    core.require(read_json(ledger_path) == ledger and not (run_path.parent / '.runner.lock').exists(), 'run checkpoint changed during comparison')
    write_new(root / 'comparison.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'preflight', 'run', 'compare'))
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--workload', type=Path)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--reference-checklist', type=Path)
    parser.add_argument('--kos-root', type=Path, default=DEFAULT_KOS_ROOT)
    parser.add_argument('--selected-kos-manifest', type=Path, default=DEFAULT_KOS_MANIFEST)
    parser.add_argument('--source-store', type=Path, default=DEFAULT_SOURCE_STORE)
    parser.add_argument('--atom-root', type=Path, default=DEFAULT_ATOM_ROOT)
    parser.add_argument('--parent-workload', type=Path, default=DEFAULT_PARENT)
    parser.add_argument('--concurrency', type=int, choices=range(1, 5), default=2)
    parser.add_argument('--target-id', action='append', dest='target_ids')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--mock', action='store_true')
    modes.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    if args.command != 'run' and (args.mock or args.execute or args.target_ids):
        parser.error('--mock/--execute/--target-id require run')
    if args.command != 'prepare' and args.workload is None:
        parser.error('--workload required')
    if args.command == 'compare' and (args.run is None or args.reference_checklist is None):
        parser.error('compare requires --run and --reference-checklist')
    try:
        if args.command == 'compare':
            value = compare(args.workload, args.run, args.reference_checklist, args.output_root)
            path = args.output_root / 'comparison.json'
        else:
            from ..au_context_paired.__main__ import study_config
            cfg, _, _ = study_config(args)
            if args.command == 'prepare':
                w = prepare(args.output_root, kos_root=args.kos_root, selected_kos_manifest=args.selected_kos_manifest,
                            source_store=args.source_store, atom_root=args.atom_root, parent=args.parent_workload, cfg=cfg)
                value, path = {'status': 'prepared', 'target_count': len(w['rows'])}, args.output_root / 'workload.json'
            elif args.command == 'preflight':
                w = core.load(args.workload)
                value = preflight(w, cfg=cfg)
                core.guard_output(args.output_root, [args.workload.parent, w['source_store'], w['atom_root'], w['kos_root'], DEFAULT_PARENT.parent, core.DEFAULT_MANIFEST.parent])
                core.require(not args.output_root.exists(), 'preflight output must be a new directory')
                path = args.output_root / 'preflight.json'
                write_new(path, value)
            else:
                from .runner import run
                w = core.load(args.workload)
                core.guard_output(args.output_root, [w['kos_root'], w['selected_kos_manifest'], Path(w['reference_checklist_path']).parent])
                value = run(args.workload, output_root=args.output_root, cfg=cfg, execute=args.execute, mock=args.mock,
                            concurrency=args.concurrency, target_ids=args.target_ids)
                path = args.output_root / 'run.json'
                if not args.mock and not args.execute:
                    core.guard_output(args.output_root, [args.workload.parent, w['source_store'], w['atom_root'], DEFAULT_PARENT.parent, core.DEFAULT_MANIFEST.parent])
                    core.require(not args.output_root.exists(), 'dryrun output must be a new directory')
                    write_new(path, value)
        print(json.dumps({'status': value['status'], 'report': str(path), 'network_executed': bool(args.execute),
                          'semantic_quality': 'not_assessed'}))
        return 0 if value['status'] in ('prepared', 'pass', 'complete', 'not_executed', 'semantic_review_pending') else 1
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__, 'network_executed': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
