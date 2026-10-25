"""Validated whole-source inventory and post-schedule KOS exposure audit."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import time

from ..source_contract import open_source
from ..structural_prepass import load_and_validate_block_map
from ..structural_prepass.parser import parse_source
from ..sentence_atoms.build import load_and_validate_sentence_atom_map
from ..kos_comparison.comparison import _load_kos, align_evidence, _overlap, _length
from .features import extract_features, PATTERNS
from .scheduler import schedule, ARMS

BASE = Path(__file__).resolve().parents[1]
EXACT5 = {'013009', '013948', '011904', '045155', '099980'}
SCAFFOLD = 'OFFLINE estimated-only region packet. Inspect target with raw context hints. No semantic dependency is asserted.'
POLICY = {'version': 'region-priority-rule-v1', 'occurrence_saturation': 3,
          'neighbor_atoms_normal': 1, 'neighbor_atoms_context_cue': 3,
          'explicit_reference_max_blocks': 3, 'discovery_position_strata': 5,
          'max_context_chars': 6000, 'max_context_intervals': 12,
          'reference_ownership': 'only paragraph N of/in these reasons attaches local context; all others unresolved',
          'scaffold': SCAFFOLD, 'patterns': PATTERNS,
          'priority': 'doctrine cue combination; fact AND consequence; citation AND quote/report; context cue combination',
          'learned_features': 'missing', 'dedup': 'identical case/hash/target offsets only'}


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _bound_path(root, ref):
    path = (root / ref).resolve()
    if root.resolve() not in path.parents:
        raise ValueError('artifact reference escapes input root')
    return path


def _span_packet(text, span, **extra):
    return {**span, **extra, 'text': text[span['start_char']:span['end_char']]}


def _merge_context(text, contexts, target):
    """Union raw context, subtract target, retain all provenance on merges."""
    pieces = []
    for ctx in contexts:
        a, b = ctx['start_char'], ctx['end_char']
        intervals = [(a, min(b, target['start_char'])), (max(a, target['end_char']), b)]
        for lo, hi in intervals:
            if lo < hi:
                pieces.append({'start_char': lo, 'end_char': hi, 'reasons': [ctx['reason']],
                               'atom_ids': [ctx['atom_id']] if 'atom_id' in ctx else [],
                               'block_ids': [ctx['block_id']] if 'block_id' in ctx else []})
    merged = []
    for part in sorted(pieces, key=lambda c: (c['start_char'], c['end_char'])):
        if merged and part['start_char'] <= merged[-1]['end_char']:
            merged[-1]['end_char'] = max(merged[-1]['end_char'], part['end_char'])
            for key in ('reasons', 'atom_ids', 'block_ids'):
                merged[-1][key] = sorted(set(merged[-1][key] + part[key]))
        else:
            merged.append(part)
    included, unknown, chars = [], [], 0
    # Nearest context first under the hard context cap; no truncation of atoms.
    for part in sorted(merged, key=lambda p: min(abs(p['end_char'] - target['start_char']), abs(p['start_char'] - target['end_char']))):
        n = part['end_char'] - part['start_char']
        if chars + n > POLICY['max_context_chars'] or len(included) >= POLICY['max_context_intervals']:
            unknown.append({**part, 'status': 'not_assessed', 'dependency_status': 'hint', 'reason': 'context_cap'})
            continue
        chars += n
        included.append(_span_packet(text, {**target, **part}, dependency_status='hint'))
    return sorted(included, key=lambda p: p['start_char']), unknown


def build_inventory(*, kos_manifest=BASE / 'manifests/selected_kos_manifest.v1.json',
                    source_store=BASE / 'outputs/source_store_v1',
                    block_manifest=BASE / 'outputs/plan03_source_blocks_v1/sourceblock_build_manifest.json',
                    atom_manifest=BASE / 'outputs/plan04_sentence_atoms_v1/sentence_atom_build_manifest.json',
                    block_policy=BASE / 'policies/sourceblock_policy.v1.json',
                    atom_policy=BASE / 'policies/sentence_atom_policy.v1.json'):
    """Read full exact5 source, validate deterministic maps, render all blocks."""
    paths = {key: Path(value).resolve() for key, value in locals().copy().items()}
    km, bm, am = (_json(paths[k]) for k in ('kos_manifest', 'block_manifest', 'atom_manifest'))
    sm = _json(paths['source_store'] / 'source_store_manifest.json')
    for label, manifest in (('KOS', km), ('blocks', bm), ('atoms', am), ('source', sm)):
        ids = [c['case_id'] for c in manifest['cases']]
        if len(ids) != 5 or set(ids) != EXACT5:
            raise ValueError(label + ' manifest must select exact5')
        if label != 'KOS' and manifest.get('status') != 'pass':
            raise ValueError(label + ' input manifest is not validated')
    bp, ap = _json(paths['block_policy']), _json(paths['atom_policy'])
    # Existing producers use ASCII canonical JSON for policy hashing.
    canonical_hash = lambda v: _sha(json.dumps(v, sort_keys=True, separators=(',', ':')).encode())
    for manifest, policy in ((bm, bp), (am, ap)):
        if manifest['policy_sha256'] != canonical_hash(policy):
            raise ValueError('policy hash differs from manifest')
    atoms_by_case = {c['case_id']: c for c in am['cases']}
    sources_by_case = {c['case_id']: c for c in sm['cases']}
    regions, cases, sources, artifacts = [], [], {}, []
    for case in bm['cases']:
        cid, digest = case['case_id'], case['source_hash']
        ac = atoms_by_case[cid]
        if digest != ac['source_hash'] or digest != sources_by_case[cid]['source_hash']:
            raise ValueError('source binding mismatch: ' + cid)
        text = open_source(paths['source_store'], cid, digest)
        sources[cid] = text
        bpath = _bound_path(paths['block_manifest'].parent, case['artifact_ref'])
        apath = _bound_path(paths['atom_manifest'].parent, ac['artifact_ref'])
        blocks, bchecks = load_and_validate_block_map(bpath, text, paths['source_store'])
        if blocks != parse_source(text=text, case_id=cid, source_hash=digest, policy=bp, policy_sha256=bm['policy_sha256']):
            raise ValueError('block map differs from existing policy producer')
        atoms, achecks = load_and_validate_sentence_atom_map(apath, text, blocks, ap)
        if blocks['cache_key'] != case['cache_key'] or atoms['cache_key'] != ac['cache_key'] or atoms['sourceblock_map_cache_key'] != blocks['cache_key']:
            raise ValueError('manifest cache binding mismatch')
        artifacts.extend([{'path': str(p), 'sha256': _sha(p.read_bytes())} for p in (bpath, apath)])
        aa = atoms['atoms']
        paragraph_map = {}
        for block in blocks['blocks']:
            marker = block.get('marker_span')
            if marker:
                m = re.search(r'\[(\d+)\]', text[marker['start_char']:marker['end_char']])
                if m:
                    paragraph_map.setdefault(m[1], []).append(block)
        for block in blocks['blocks']:
            span = block['span']
            target_text = text[span['start_char']:span['end_char']]
            features = extract_features(target_text)
            for cue, anchors in features['anchors'].items():
                for anchor in anchors:
                    anchor['start_char'] += span['start_char']; anchor['end_char'] += span['start_char']
                    anchor['atom_ids'] = [a['atom_id'] for a in aa if a['span']['start_char'] < anchor['end_char'] and a['span']['end_char'] > anchor['start_char']]
            width = 3 if features['open_quote'] or any(features['counts'][k] for k in ('qualification', 'reporting', 'paragraph_reference', 'speaker_voice')) else 1
            before = [a for a in aa if a['span']['end_char'] <= span['start_char']][-width:]
            after = [a for a in aa if a['span']['start_char'] >= span['end_char']][:width]
            contexts = [_span_packet(text, a['span'], atom_id=a['atom_id'], reason='adjacent_atom', dependency_status='hint') for a in before + after]
            refs = []
            referenced = set()
            for m in re.finditer(PATTERNS['paragraph_reference'], target_text, re.I):
                hits = paragraph_map.get(m[1], [])
                local = bool(re.match(r'\s+(?:of|in)\s+these\s+reasons\b', target_text[m.end():], re.I))
                refs.append({'reference': m.group(), 'paragraph_number': m[1], 'dependency_status': 'hint',
                             'resolution': 'same_case_raw_marker_hint' if local and hits else 'unresolved_ownership_or_missing',
                             'matching_block_ids': [b['block_id'] for b in hits] if local else [],
                             'unverified_local_candidate_ids': [b['block_id'] for b in hits] if not local else []})
                for other in hits if local else []:
                    if other['block_id'] != block['block_id'] and other['block_id'] not in referenced and len(referenced) < POLICY['explicit_reference_max_blocks']:
                        referenced.add(other['block_id'])
                        contexts.append(_span_packet(text, other['span'], block_id=other['block_id'], reason='explicit_paragraph_reference', dependency_status='hint'))
                    elif other['block_id'] != block['block_id'] and other['block_id'] not in referenced:
                        refs.append({'block_id': other['block_id'], 'dependency_status': 'hint', 'status': 'not_assessed', 'reason': 'reference_block_cap'})
            # Dedup identical context spans only, retaining reasons; overlaps stay raw.
            contexts, capped = _merge_context(text, contexts, span)
            refs.extend(capped)
            if features['open_quote'] or features['counts']['qualification'] or features['counts']['reporting']:
                refs.append({'dependency_status': 'hint', 'status': 'unknown', 'reason': 'bounded_neighbors_do_not_prove_condition_quote_or_voice_completion'})
            packet = {'scaffold': SCAFFOLD, 'region_id': block['block_id'], 'case_id': cid, 'source_hash': digest,
                      'target': _span_packet(text, span, block_id=block['block_id'], role='TARGET'),
                      'context': [{**c, 'role': 'CONTEXT'} for c in contexts]}
            serialized = _canonical(packet)
            raw_bytes = len(serialized.encode('utf-8'))
            regions.append({'region_id': block['block_id'], 'case_id': cid, 'source_hash': digest,
                            'order': block['order'], 'block_type': block['block_type'], 'target': span,
                            'target_atom_ids': [a['atom_id'] for a in aa if a['parent_block_id'] == block['block_id']],
                            'features': features, 'position_stratum': min(4, span['start_char'] * 5 // max(1, len(text))),
                            'context_obligations': refs, 'adjacent_atoms_per_side_limit': width,
                            'packet': packet, 'serialized_payload': serialized, 'serialized_utf8_bytes': raw_bytes,
                            'serialized_chars': len(serialized), 'target_utf8_bytes': len(target_text.encode('utf-8')),
                            'target_chars': len(target_text), 'context_utf8_bytes': sum(len(c['text'].encode('utf-8')) for c in contexts),
                            'estimated_tokens': {str(d): math.ceil(raw_bytes / d) for d in (3, 4, 5)}})
        cases.append({'case_id': cid, 'source_hash': digest, 'source_chars': len(text),
                      'source_utf8_bytes': len(text.encode('utf-8')), 'block_count': len(blocks['blocks']), 'atom_count': len(aa),
                      'block_checks': bchecks, 'atom_checks': achecks, 'coverage_fraction': 1.0,
                      'atom_span_inventory': [{'atom_id': a['atom_id'], 'parent_block_id': a['parent_block_id'], 'span': a['span']} for a in aa]})
    bindings = [{'path': str(p), 'sha256': _sha(p.read_bytes())} for k, p in paths.items() if k != 'source_store']
    bindings.append({'path': str(paths['source_store'] / 'source_store_manifest.json'), 'sha256': _sha((paths['source_store'] / 'source_store_manifest.json').read_bytes())})
    return {'version': 'region-priority-inventory-v1', 'regions': regions, 'cases': cases,
            'input_bindings': bindings, 'artifact_bindings': artifacts, 'policy': POLICY,
            'policy_sha256': _sha(_canonical(POLICY).encode()), 'sources': sources}


def _exposure(unit, scheduled, region_by_id, packets=False):
    aligned = unit['alignment']['status'] in ('exact', 'whitespace_normalized')
    spans = unit['alignment']['spans'] if aligned else []
    total = _length(spans)
    targets, contexts, history, first_target, first_context, full_target, full_context = [], [], [], None, None, None, None
    raw = []
    for read in scheduled['reads']:
        r = region_by_id[read['region_id']]
        if r['case_id'] != unit['case_id']:
            continue
        ts = [r['target']]; cs = r['packet']['context']
        targets.extend(ts); contexts.extend(cs)
        hit_t, hit_c = _overlap(spans, ts), _overlap(spans, cs)
        covered_t, covered_c = _overlap(spans, targets), _overlap(spans, contexts)
        event = {**read, 'target_intersection_chars': hit_t, 'context_intersection_chars': hit_c,
                 'covered_target_chars': covered_t, 'covered_context_chars': covered_c,
                 'target_fullspan': bool(total and covered_t == total), 'context_fullspan': bool(total and covered_c == total)}
        if hit_t and first_target is None:
            first_target = event
        if hit_c and first_context is None:
            first_context = event
        if total and covered_t == total and full_target is None:
            full_target = event
        if total and covered_c == total and full_context is None:
            full_context = event
        if hit_t or hit_c:
            history.append(event)
            if packets:
                raw.append(r['packet'])
    return {'eligible_denominator': aligned, 'evidence_chars': total, 'first_target': first_target,
            'first_context': first_context, 'first_full_target': full_target, 'first_full_context': full_context,
            'covered_target_chars': _overlap(spans, targets), 'covered_context_chars': _overlap(spans, contexts),
            'target_fullspan': bool(total and _overlap(spans, targets) == total),
            'context_fullspan': bool(total and _overlap(spans, contexts) == total),
            'status': 'excluded_alignment' if not aligned else 'exposed_full_target' if full_target else 'not_assessed',
            'exposure_history': history, **({'raw_context_packets': raw} if packets else {})}


def _transformation_audit(inventory):
    swaps = {'Nancy Chow': 'Mandy Snow', 'Gauthier': 'Zauthier', 'Tabib': 'Zabib', 'Challal': 'Zhallal'}
    transformed = deepcopy(inventory['regions'])
    audited, changed, failures = 0, 0, []
    for r, copied in zip(inventory['regions'], transformed):
        original = r['packet']['target']['text']
        modified = original
        for a, b in swaps.items():
            modified = re.sub(r'\b' + a + r'\b', b, modified)
        audited += 1; changed += int(original != modified)
        if extract_features(original) != extract_features(modified):
            failures.append(r['region_id'])
        copied['features'] = extract_features(modified)
    ranks = {}
    ordinals = {r['region_id']: (r['case_id'], r['order']) for r in inventory['regions']}
    for arm in ARMS:
        original_order = [ordinals[r['region_id']] for r in schedule(inventory, arm)['reads']]
        swapped_order = [ordinals[r['region_id']] for r in schedule(transformed, arm)['reads']]
        ranks[arm] = {'ordinal_ranks_equal': original_order == swapped_order,
                      'compared_region_count': len(original_order)}
    # Deliberately recreate the former preview-count failure on a real-case block.
    exemplar = next((r for r in inventory['regions'] if any(r['features']['counts'].values())), inventory['regions'][0])
    text = exemplar['packet']['target']['text']
    preview = text[:180]
    legacy = lambda previews: sum(len(list(re.finditer(p, v, re.I))) for v in previews for p in PATTERNS.values())
    return {'name_swap': {'scope': 'real-case copies only; immutable sources untouched', 'swaps': swaps,
                          'audited_blocks': audited, 'changed_blocks': changed, 'feature_mismatch_ids': failures,
                          'equal_length_replacement': True, 'scope_limit': 'selected substitutions only, not arbitrary NER invariance'},
            'ordinal_rank_comparison': ranks,
            'old_preview_court_reproduction': {'fixture': 'the court stated', 'single_preview_occurrences': 1,
                                               'three_overlapping_previews_occurrences': sum(len(re.findall(r'\bcourt\b', p)) for p in ['the court stated', 'court stated', 'the court']),
                                               'source_unique_occurrences': len(set((m.start(), m.end()) for m in re.finditer(r'\bcourt\b', 'the court stated')))},
            'duplicate_preview': {'region_id': exemplar['region_id'], 'preview_chars': len(preview),
                                  'legacy_single_count': legacy([preview]), 'legacy_duplicate_count': legacy([preview, preview]),
                                  'new_features_equal': extract_features(text) == extract_features(text),
                                  'reason': 'canonical extractor accepts complete source text only; no preview input exists'}}


def run(*, output_root, kos_root=Path('G:/Legal-AI/kos_sample'), **inventory_kwargs):
    started = time.perf_counter()
    root = Path(output_root).resolve()
    owned_outputs = ('inventory.json', 'report.json', 'summary.json', 'summary.md')
    if any((root / name).exists() for name in owned_outputs):
        raise ValueError('report files already exist; historical overwrite refused')
    if root.exists() and any(p.name not in ('main_preservation_snapshot.json', 'tester') for p in root.iterdir()):
        raise ValueError('output-root contains unexpected existing artifacts')
    protected = [Path(kos_root).resolve(), BASE / 'outputs/source_store_v1', BASE / 'outputs/plan03_source_blocks_v1', BASE / 'outputs/plan04_sentence_atoms_v1']
    protected += [Path(v).resolve() if 'store' in k else Path(v).resolve().parent for k, v in inventory_kwargs.items()]
    for path in protected:
        if root == path or path in root.parents or root in path.parents:
            raise ValueError('output overlaps an input directory')
    inventory = build_inventory(**inventory_kwargs)
    # Schedules and audit are frozen before loading any KOS evidence.
    schedules = {arm: schedule(inventory, arm) for arm in ARMS}
    audit = _transformation_audit(inventory)
    schedule_sha = _sha(_canonical(schedules).encode())
    manifest = _json(inventory_kwargs.get('kos_manifest', BASE / 'manifests/selected_kos_manifest.v1.json'))
    kos_inventory, units, parse_errors = _load_kos(kos_root, manifest)
    region_by_id = {r['region_id']: r for r in inventory['regions']}
    au_audit = []
    for unit in units:
        source = inventory['sources'][unit['case_id']]
        alignment = align_evidence(unit['evidence_text'], source)
        aligned = alignment['status'] in ('exact', 'whitespace_normalized')
        source_evidence = ''.join(source[s['start_char']:s['end_char']] for s in alignment['spans']) if aligned else ''
        f = extract_features(source_evidence) if aligned else None
        containing = [r for r in inventory['regions'] if r['case_id'] == unit['case_id'] and aligned and _overlap(alignment['spans'], [r['target']])]
        block_text = ''.join(r['packet']['target']['text'] for r in containing)
        def marker_status(t):
            return {'literal_markers': {k: bool(re.search(r'<'+k+r'>', t)) for k in ('FRAGMENT_SUPPRESSED', 'REFERENCE_SUPPRESSED', 'CITATION_SUPPRESSED')},
                    'visible_citation_cue': bool(re.search(r'\[\d{4}\]|\b\d{4}\s+(?:SCC|FCA|FC|CanLII)\b|\b\d+\s+(?:S\.C\.R\.|D\.L\.R\.)', t, re.I)),
                    'any_citation_or_marker_cue': bool(extract_features(t)['counts']['citation'])}
        evidence_markers = marker_status(source_evidence) if aligned else None
        block_markers = marker_status(block_text) if aligned else None
        categories = {'kos_kind': unit['kind'], 'source_no_marker': not bool(f['counts']['citation']) if f else None,
                      'containing_block_no_marker': not any(block_markers['literal_markers'].values()) if block_markers else None,
                      'containing_block_no_citation_or_marker_cue': not block_markers['any_citation_or_marker_cue'] if block_markers else None,
                      'evidence_marker_status': evidence_markers, 'containing_targetblock_marker_status': block_markers,
                      'no_marker_scope_note': 'source_no_marker means no combined citation/marker cue in aligned excerpt; literal markers and full containing blocks reported separately',
                      'application_cue': bool(f['lane_scores']['application']) if f else None,
                      'exception_cue': bool(f['counts']['qualification'] or f['counts']['rebuttal']) if f else None,
                      'category_role': 'overlapping source-cue diagnostics; not semantic gold'}
        row = {**unit, 'alignment': alignment, 'categories': categories,
               'aligned_source_evidence': source_evidence if aligned else None}
        row['arms'] = {arm: _exposure(row, sched, region_by_id, packets=True) for arm, sched in schedules.items()}
        au_audit.append(row)
    curves = []
    fractions = sorted(set([i / 10 for i in range(1, 11)] + [.25, .75]))
    for divisor in (3, 4, 5):
        exhaustive = schedule(inventory, 'source_order', bytes_per_token=divisor)['estimated_tokens']
        for fraction in fractions:
            budget = math.floor(exhaustive * fraction)
            for arm in ARMS:
                sched = schedule(inventory, arm, budget=budget, bytes_per_token=divisor)
                exposure = [{'case_id': u['case_id'], 'kos_id': u['kos_id'], **_exposure(u, sched, region_by_id)} for u in au_audit]
                eligible = [e for e in exposure if e['eligible_denominator']]
                grouped = {}
                for category in ('source_no_marker', 'containing_block_no_marker', 'containing_block_no_citation_or_marker_cue', 'application_cue', 'exception_cue'):
                    group = [e for e, u in zip(exposure, au_audit) if e['eligible_denominator'] and u['categories'][category]]
                    grouped[category] = {'denominator': len(group), 'full_target_count': sum(e['target_fullspan'] for e in group)}
                kinds = sorted({str(u['kind']) for u in au_audit})
                for kind in kinds:
                    group = [e for e, u in zip(exposure, au_audit) if e['eligible_denominator'] and str(u['kind']) == kind]
                    grouped['kos_kind:' + kind] = {'denominator': len(group), 'full_target_count': sum(e['target_fullspan'] for e in group)}
                case_rows = []
                for case in inventory['cases']:
                    cid = case['case_id']
                    selected = [region_by_id[r['region_id']] for r in sched['reads'] if region_by_id[r['region_id']]['case_id'] == cid]
                    group = [e for e in eligible if e['case_id'] == cid]
                    delivered = _length([r['target'] for r in selected])
                    full = sum(e['target_fullspan'] for e in group)
                    case_rows.append({'case_id': cid, 'aligned_denominator': len(group), 'full_target_count': full,
                                      'target_reference_fraction': full / len(group) if group else None, 'zero_denominator_status': 'NA' if not group else None,
                                      'full_context_count': sum(e['context_fullspan'] for e in group),
                                      'source_chars': case['source_chars'], 'covered_target_source_chars': delivered,
                                      'unknown_target_source_chars': case['source_chars'] - delivered,
                                      'covered_context_source_chars': _length([s for r in selected for s in r['packet']['context']]),
                                      'delivered_serialized_bytes': sum(r['serialized_utf8_bytes'] for r in selected),
                                      'delivered_serialized_chars': sum(r['serialized_chars'] for r in selected)})
                curves.append({'fraction': fraction, 'divisor': divisor, 'exhaustive_same_renderer_tokens': exhaustive,
                               'schedule': sched, 'aligned_denominator': len(eligible),
                               'full_target_count': sum(e['target_fullspan'] for e in eligible),
                               'full_context_count': sum(e['context_fullspan'] for e in eligible),
                               'partial_target_count': sum(0 < e['covered_target_chars'] < e['evidence_chars'] for e in eligible),
                               'diagnostic_categories': grouped, 'cases': case_rows, 'per_au': exposure})
    sources = inventory.pop('sources')
    checks = {'exact5': len(inventory['cases']) == 5,
              'kos_parse_errors_absent': not parse_errors,
              'whole_source_partition': all(sum(r['target_chars'] for r in inventory['regions'] if r['case_id'] == c['case_id']) == c['source_chars'] for c in inventory['cases']),
              'all_arms_exhaustive': all(len(s['reads']) == len(inventory['regions']) for s in schedules.values()),
              'same_renderer_cost_all_arms': len({s['estimated_tokens'] for s in schedules.values()}) == 1,
              'schedules_unchanged_after_kos': schedule_sha == _sha(_canonical(schedules).encode()),
              'name_swap_invariance': not audit['name_swap']['feature_mismatch_ids'],
              'name_swap_ordinal_ranks': all(v['ordinal_ranks_equal'] for v in audit['ordinal_rank_comparison'].values()),
              'context_cap': all(sum(c['end_char'] - c['start_char'] for c in r['packet']['context']) <= POLICY['max_context_chars'] for r in inventory['regions']),
              'context_union_no_target_overlap': all(_length(r['packet']['context']) == sum(c['end_char'] - c['start_char'] for c in r['packet']['context']) and _overlap([r['target']], r['packet']['context']) == 0 for r in inventory['regions']),
              'full_target_aligned_at_exhaustive': all(u['arms'][a]['target_fullspan'] for u in au_audit if u['alignment']['status'] in ('exact', 'whitespace_normalized') for a in ARMS)}
    summary = {'case_count': len(inventory['cases']), 'region_count': len(inventory['regions']),
               'source_chars': sum(len(t) for t in sources.values()), 'kos_file_count': sum(c['file_count'] for c in kos_inventory),
               'kos_au_count': len(au_audit), 'alignment_counts': dict(Counter(u['alignment']['status'] for u in au_audit)),
               'aligned_denominator': sum(u['alignment']['status'] in ('exact', 'whitespace_normalized') for u in au_audit),
               'excluded_alignment_count': sum(u['alignment']['status'] not in ('exact', 'whitespace_normalized') for u in au_audit),
               'kos_parse_error_count': len(parse_errors), 'exhaustive_estimated_tokens_divisor4': schedules['source_order']['estimated_tokens'],
               'serialized_bytes': sum(r['serialized_utf8_bytes'] for r in inventory['regions']),
               'serialized_chars': sum(r['serialized_chars'] for r in inventory['regions'])}
    report = {'version': 'region-priority-offline-report-v1', 'status': 'materialized',
              'protocol_checks': checks, 'protocol_status': 'pass' if all(checks.values()) else 'fail',
              'semantic_quality': 'not_assessed', 'qualified_evidence_quality': 'not_assessed',
              'summary': summary, 'schedules': schedules, 'schedules_sha256_before_kos': schedule_sha,
              'implementation_fingerprints': [{'path': str(p), 'sha256': _sha(p.read_bytes())} for p in sorted(Path(__file__).parent.glob('*.py'))],
              'transformation_audit': audit, 'kos_inventory': kos_inventory, 'kos_parse_errors': parse_errors,
              'au_audit': au_audit, 'budget_curves': curves, 'unknown_residual': 'budget-skipped regions and unknown unannotated source remain not_assessed',
              'cost': {'method': 'ceil(serialized UTF-8 bytes / divisor) per packet', 'divisors': [3, 4, 5],
                       'includes': 'constant scaffold + exact IDs + exact target/context source text + JSON overhead',
                       'billing': 'estimated only; not Qwen tokenizer, not full real extraction prompt, not actual model billing',
                       'network_requests': 0, 'inference_requests': 0, 'latency_seconds': time.perf_counter() - started},
              'limitations': ['Rule cues do not establish doctrine/application/authority correctness.',
                              'KOS is incomplete reference, not semantic gold; no tuning against KOS.',
                              'Neighbor and explicit-reference contexts are uncertain raw hints, not semantic dependencies.',
                              'Open-quote/condition context expansion is bounded and may miss distant obligations.',
                              'Old-cue control is an explicit lexical full-block control, not a claim of exact historic production equivalence.',
                              'No semantic stopping; exhaustive TARGET reading only proves source exposure.']}
    root.mkdir(parents=True, exist_ok=True)
    for name, value in [('inventory.json', inventory), ('report.json', report), ('summary.json', summary)]:
        (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# Offline region priority pilot', '', 'Semantic quality and qualified evidence: not assessed. KOS reference only.', '',
             'Protocol: ' + report['protocol_status'], '', '```json', json.dumps(summary, indent=2), '```', '',
             '| Fraction | Arm | Full TARGET / aligned | Full CONTEXT | Estimated tokens (divisor 4) |', '|---|---|---|---|---|']
    for c in curves:
        if c['divisor'] == 4 and c['fraction'] in (.1, .25, .5, .75, 1.):
            lines.append(f"| {c['fraction']} | {c['schedule']['arm']} | {c['full_target_count']}/{c['aligned_denominator']} | {c['full_context_count']} | {c['schedule']['estimated_tokens']} |")
    lines += ['', 'Costs include shared offline scaffold and serialization overhead; estimated only, not full extraction prompt or billing.', '', *report['limitations']]
    (root / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report
