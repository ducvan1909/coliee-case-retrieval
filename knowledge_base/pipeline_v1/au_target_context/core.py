"""Host clipping, frozen input validation, and two independent model contracts."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from .contracts import *
from .grammar import build_grammar
from ..au_context_paired.build import fingerprint, read_json, render_request, write_new
from ..au_presentation_paired.core import (DEFAULT_MANIFEST, DEFAULT_PARENT,
                                         validate_manifest, profile)
from ..source_contract import open_source

from .prompts import (INSTRUCTIONS, TARGET_INSTRUCTIONS, CONTEXT_INSTRUCTIONS,
                      DEFAULT_PROMPT_PROFILE, prompt_metadata, instructions_for)



class TargetContextError(ValueError):
    def __init__(self, message):
        super().__init__(message)
        # Only host-owned constants may enter machine diagnostics.
        self.error_code = {
            'anchor IDs must use host slot order': 'anchor_slot_order',
            'foreign/duplicate anchor': 'anchor_slot_order',
            'incomplete generation': 'incomplete_generation',
        }.get(message, 'output_protocol_validation')


def require(condition, message):
    if not condition:
        raise TargetContextError(message)


def load(value):
    return read_json(value) if isinstance(value, (str, Path)) else copy.deepcopy(value)


def code_hash():
    # Bind both this implementation and the helpers used at execution time.
    from ..au_compact import jobs_client, runner as compact_runner, decoding
    from ..au_context_paired import transport, build
    from ..au_presentation_paired import core as presentation
    paths = set(Path(__file__).parent.glob('*.py'))
    paths.update(Path(m.__file__) for m in (jobs_client, compact_runner, decoding, transport, build, presentation))
    return fingerprint({str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})


def overlap(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def guard_output(root, protected):
    require(not any(overlap(root, p) for p in protected), 'output overlaps protected input/source in either direction')


def clipped_row(request, source_store, atom_root):
    rendered = render_request(request, source_store, atom_root)
    source = open_source(source_store, request['case_id'], request['source_hash'])
    target_spans = [(r['start_char'], r['end_char']) for r in request['source_refs'] if r['role'] == 'target']
    require(len(target_spans) == 1, 'one locked TARGET span required')
    lo, hi = target_spans[0]
    target, context = {}, {}
    for atom in sorted(rendered['catalog']['atoms'].values(), key=lambda a: (a['start_char'], a['end_char'])):
        a, b = atom['start_char'], atom['end_char']
        pieces = []
        if a < hi and lo < b:
            pieces.append(('target', max(a, lo), min(b, hi)))
            if a < lo: pieces.append(('context', a, lo))
            if b > hi: pieces.append(('context', hi, b))
        else:
            pieces.append(('context', a, b))
        for role, start, end in pieces:
            ref_id = ('t-' if role == 'target' else 'c-') + fingerprint(
                [request['case_id'], request['source_hash'], atom['atom_id'], start, end, role])[:24]
            ref = {'ref_id': ref_id, 'source_atom_id': atom['atom_id'], 'case_id': request['case_id'],
                   'source_hash': request['source_hash'], 'start_char': start, 'end_char': end,
                   'quote': source[start:end], 'role': 'target_body' if role == 'target' else 'context'}
            (target if role == 'target' else context)[ref_id] = ref
    require(bool(target), 'TARGET has no clipped atoms')
    return {'target_id': request['expected_target_ids'][0], 'case_id': request['case_id'],
            'source_hash': request['source_hash'], 'target': {'start_char': lo, 'end_char': hi},
            'request': copy.deepcopy(request), 'target_refs': target, 'context_refs': context}


def prepare(output_root, *, manifest=DEFAULT_MANIFEST, parent=DEFAULT_PARENT, cfg=None,
            prompt_profile=DEFAULT_PROMPT_PROFILE):
    """Build a new immutable workload from the same32 frozen G targets."""
    prompts = prompt_metadata(prompt_profile)
    m, p = load(manifest), load(parent)
    validate_manifest(m, p, cfg)
    identity = copy.deepcopy(p['identity'])
    if cfg is not None: profile(p, cfg)
    originals = {q['request_id']: q for q in p['manifest']['requests']}
    pairs = {pair['pair_id']: pair for pair in p['pairs']}
    rows = []
    for mr in m['rows']:
        pair = pairs[mr['pair_id']]
        row = clipped_row(originals[pair['request_ids']['G']], p['source_store'], p['atom_root'])
        row['pair_id'] = pair['pair_id']
        row.update(prompts)
        rows.append(row)
    workload = {'artifact_type': 'AUTargetContextWorkload', 'version': VERSION,
                **prompts,
                'presentation_manifest_sha256': m['manifest_sha256'], 'parent_workload_sha256': p['workload_sha256'],
                'presentation_manifest': m, 'parent_workload': p, 'identity': identity,
                'source_store': p['source_store'], 'atom_root': p['atom_root'], 'rows': rows,
                'budget': dict(BUDGET), 'code_sha256': code_hash(), 'semantic_gold': False,
                'context_policy': 'frozen_G_catalog_only; no far-context search', 'output_cap': OUTPUT_CAP}
    workload['workload_sha256'] = fingerprint(workload)
    root = Path(output_root).resolve()
    protected = [p['source_store'], p['atom_root'], DEFAULT_MANIFEST.parent, DEFAULT_PARENT.parent]
    protected += [v for v in (manifest, parent) if isinstance(v, (str, Path))]
    guard_output(root, protected)
    require(not root.exists() or not any(root.iterdir()), 'prepare output must be fresh')
    write_new(root / 'workload.json', workload)
    checked = preflight(workload, cfg=cfg)
    write_new(root / 'preflight.json', checked)
    return workload


def preflight(workload, *, cfg=None):
    """Verify source/store, input bindings and finite payloads without network."""
    w = load(workload)
    if w.get('artifact_type') == 'AUKOSAlignedWorkload':
        from .kos_aligned import preflight as kos_preflight
        return kos_preflight(w, cfg=cfg)
    digest = w.pop('workload_sha256', None)
    require(digest == fingerprint(w), 'workload digest mismatch')
    require(w['artifact_type'] == 'AUTargetContextWorkload' and w['version'] == VERSION, 'unknown workload contract')
    m, p = w['presentation_manifest'], w['parent_workload']
    validate_manifest(m, p, cfg)
    require(w['presentation_manifest_sha256'] == m['manifest_sha256'] and w['parent_workload_sha256'] == p['workload_sha256'], 'parent binding mismatch')
    require(w['identity'] == p['identity'] and w['source_store'] == p['source_store'] and w['atom_root'] == p['atom_root'], 'source/runtime changed')
    require(w['budget'] == BUDGET and w['output_cap'] == OUTPUT_CAP and w['code_sha256'] == code_hash(), 'budget/cap/code changed')
    prompts = prompt_metadata(w['prompt_profile'])
    require(w['prompt_sha'] == prompts['prompt_sha'], 'declared prompt hash mismatch')
    if cfg is not None: profile(p, cfg)
    originals = {q['request_id']: q for q in p['manifest']['requests']}
    pairs = {pair['pair_id']: pair for pair in p['pairs']}
    require(len(w['rows']) == 32 and len({r['pair_id'] for r in w['rows']}) == 32, 'requires exact same32 TARGETs')
    prompt_bytes, baseline_bytes, max_added_bytes, jobs = 0, 0, 0, []
    for row, mr in zip(w['rows'], m['rows']):
        pair = pairs[mr['pair_id']]
        expected = clipped_row(originals[pair['request_ids']['G']], w['source_store'], w['atom_root'])
        expected['pair_id'] = pair['pair_id']
        expected.update(prompts)
        require(row == expected, 'clipped source/store/target catalog mismatch')
        job = build_stage1(row, w['identity'])
        jobs.append(job['request_id'])
        size = len(job['payload']['messages'][0]['content'].encode('utf-8'))
        baseline_row = {**row, **prompt_metadata(DEFAULT_PROMPT_PROFILE)}
        baseline_size = len(build_stage1(baseline_row, w['identity'])['payload']['messages'][0]['content'].encode('utf-8'))
        prompt_bytes += size
        baseline_bytes += baseline_size
        max_added_bytes = max(max_added_bytes, size - baseline_size)
    require(len(set(jobs)) == 32 and prompt_bytes <= BUDGET['max_total_input_tokens'], 'stage1 identity/budget overflow')
    return {'artifact_type': 'AUTargetContextPreflight', 'status': 'pass', 'workload_sha256': digest,
            **prompts,
            'target_count': 32, 'stage1_requests': 32, 'max_logical_requests': 64,
            'stage1_input_reservation_utf8_bytes': prompt_bytes, 'budget': dict(BUDGET),
            'stage1_baseline_input_reservation_utf8_bytes': baseline_bytes,
            'stage1_added_input_utf8_bytes': prompt_bytes - baseline_bytes,
            'stage1_max_added_input_utf8_bytes_per_target': max_added_bytes,
            'network_requests': 0, 'grammar_compile': 'not_checked', 'semantic_quality': 'not_assessed',
            'revision_evidence': 'historical parent binding; no live revision verification'}


def _make_job(row, identity, stage, locked_anchors=(), stage1=None):
    prompts = prompt_metadata(row.get('prompt_profile', DEFAULT_PROMPT_PROFILE))
    require('prompt_sha' not in row or row['prompt_sha'] == prompts['prompt_sha'], 'row prompt hash mismatch')
    common, target_instructions, context_instructions = instructions_for(prompts['prompt_profile'])
    target_refs, context_refs = copy.deepcopy(row['target_refs']), copy.deepcopy(row['context_refs']) if stage == 2 else {}
    anchor_ids = ['a-' + fingerprint([row['target_id'], i])[:24] for i in range(MAX_ANCHORS)]
    identity_material = {'version': VERSION, 'stage': stage, 'target_id': row['target_id'],
                         **prompts,
                         'target_refs': target_refs, 'context_refs': context_refs,
                         'locked_anchors': list(locked_anchors), 'stage1': stage1, 'identity': identity}
    if prompts['prompt_profile'] == 'evidence_first_v1':
        identity_material['stage1_wire_version'] = STAGE1_EVIDENCE_FIRST
    if prompts['prompt_profile'] == 'primary_support_v1':
        identity_material['stage1_wire_version'] = STAGE1_PRIMARY_SUPPORT
    rid = 'atc-' + fingerprint(identity_material)[:24]
    job = {'stage': stage, 'request_id': rid, 'target_id': row['target_id'],
           **prompts,
           'catalog': {'target_refs': target_refs, 'context_refs': context_refs},
           'anchor_ids': anchor_ids, 'locked_anchors': copy.deepcopy(list(locked_anchors)),
           'stage1': copy.deepcopy(stage1), 'case_id': row['case_id'], 'source_hash': row['source_hash']}
    # Source fragments are JSON encoded. No offsets appear in the model output contract.
    data = {'request_id': rid, 'target_id': row['target_id'], 'version': stage1_version(prompts['prompt_profile']) if stage == 1 else STAGE2,
            'kind_enum': KINDS, 'needs_context_enum': NEEDS}
    if stage == 1:
        data['TARGET_BODY'] = [{'ref_id': k, 'text': v['quote']} for k, v in target_refs.items()]
        data['allowed_anchor_ids'] = anchor_ids
        data['output_keys'] = STAGE1_KEYS
        data['anchor_keys'] = stage1_anchor_keys(prompts['prompt_profile'])
        data['reason_by_decision'] = STAGE1_REASON_BY_DECISION
    else:
        data['locked_anchors'] = [{'anchor_id': a['anchor_id'], 'kind': a['kind'],
            'primary_claim': a['primary_claim'], 'target_ref_ids': a['target_ref_ids'],
            'primary_evidence': [{'ref_id': r, 'text': target_refs[r]['quote']} for r in a['target_ref_ids']],
            'needs_context': a['needs_context']} for a in locked_anchors]
        if prompts['prompt_profile'] == 'evidence_first_v1':
            for item, anchor in zip(data['locked_anchors'], locked_anchors):
                # Send source once: compatibility text stays in host results only.
                del item['primary_claim']
                item['primary_representation'] = anchor['primary_representation']
                item['primary_gaps'] = copy.deepcopy(anchor['primary_gaps'])
        if prompts['prompt_profile'] == 'primary_support_v1':
            # One shared source catalog also avoids duplication across AUs.
            selected_refs = {r for a in locked_anchors for r in a['target_ref_ids']}
            data['SELECTED_TARGET_EVIDENCE'] = [
                {'ref_id': r, 'text': target_refs[r]['quote']}
                for r in sorted(selected_refs, key=lambda r: (
                    target_refs[r]['start_char'], target_refs[r]['end_char'], r))]
            data['locked_anchors'] = [
                {key: copy.deepcopy(a[key]) for key in (
                    'anchor_id', 'kind', 'primary_ref_id', 'supporting_ref_ids',
                    'target_ref_ids', 'primary_representation', 'needs_context')}
                for a in locked_anchors]
        data['stage1_decision'] = stage1['decision']
        data['stage1_reason'] = stage1['reason']
        data['remaining_needs_context'] = stage1['needs_context']
        data['CONTEXT'] = [{'ref_id': k, 'text': v['quote']} for k, v in context_refs.items()]
        data['output_keys'] = STAGE2_KEYS
        data['anchor_keys'] = STAGE2_ANCHOR_KEYS
        data['supplement_keys'] = SUPPLEMENT_KEYS
        data['reason_by_decision'] = STAGE2_REASON_BY_DECISION
        data['anchor_reason_by_decision'] = STAGE2_ANCHOR_REASON_BY_DECISION
    prompt = common + '\n' + (target_instructions if stage == 1 else context_instructions) + '\nINPUT:\n' + json.dumps(data, ensure_ascii=False)
    job['payload'] = {'model': identity['model'], 'messages': [{'role': 'user', 'content': prompt}],
                      'temperature': 0, 'max_tokens': OUTPUT_CAP,
                      'chat_template_kwargs': {'enable_thinking': False}, 'ebnf': build_grammar(job)}
    job['payload_sha256'] = fingerprint(job['payload'])
    return job


def build_stage1(row, identity):
    """row has target_refs/context_refs; returns request_id,payload,catalog job."""
    return _make_job(row, identity, 1)


def _keys(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys), 'exact contract keys required')


def _text(value, maximum=300, empty=False):
    require(isinstance(value, str) and len(value) <= maximum and (empty or bool(value.strip())), 'invalid bounded text')
    require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value), 'invalid Unicode scalar')


def _refs(values, allowed, cap=MAX_REFS, empty=False):
    require(isinstance(values, list) and len(values) <= cap and (empty or bool(values)), 'invalid ref list')
    require(all(isinstance(v, str) and v in allowed for v in values) and len(values) == len(set(values)), 'foreign/duplicate ref or enum')


def _base(value, job, keys, version):
    _keys(value, keys)
    require(value['version'] == version and value['request_id'] == job['request_id'] and value['target_id'] == job['target_id'], 'response identity mismatch')


def _reason(value, mapping):
    require(isinstance(value['decision'], str) and value['decision'] in mapping, 'unknown decision')
    require(isinstance(value['reason'], str) and value['reason'] in mapping[value['decision']],
            'reason code incompatible with decision')


def validate_stage1(value, job):
    """Validate exact model keys/IDs; attach host primary_evidence to anchors."""
    require(job['stage'] == 1, 'not a stage1 job')
    evidence_first = job.get('prompt_profile') == 'evidence_first_v1'
    primary_support = job.get('prompt_profile') == 'primary_support_v1'
    _base(value, job, STAGE1_KEYS, stage1_version(job.get('prompt_profile')))
    require(value['decision'] in STAGE1_DECISIONS, 'unknown stage1 decision')
    _reason(value, STAGE1_REASON_BY_DECISION)
    _refs(value['needs_context'], NEEDS, len(NEEDS), True)
    require(isinstance(value['anchors'], list) and len(value['anchors']) <= MAX_ANCHORS, 'anchor cap')
    seen, normalized = set(), []
    for index, anchor in enumerate(value['anchors']):
        _keys(anchor, stage1_anchor_keys(job.get('prompt_profile')))
        require(anchor['anchor_id'] in job['anchor_ids'] and anchor['anchor_id'] not in seen, 'foreign/duplicate anchor')
        require(anchor['anchor_id'] == job['anchor_ids'][index], 'anchor IDs must use host slot order')
        seen.add(anchor['anchor_id'])
        require(anchor['kind'] in KINDS, 'unknown kind')
        if primary_support:
            primary = anchor['primary_ref_id']
            catalog = job['catalog']['target_refs']
            require(isinstance(primary, str) and primary in catalog, 'foreign primary ref')
            _refs(anchor['supporting_ref_ids'], catalog, MAX_REFS - 1, True)
            require(primary not in anchor['supporting_ref_ids'], 'primary repeated in support')
        elif not evidence_first:
            _text(anchor['primary_claim'])
        if not primary_support:
            _refs(anchor['target_ref_ids'], job['catalog']['target_refs'])
        _refs(anchor['needs_context'], NEEDS, len(NEEDS), True)
        selected = copy.deepcopy(anchor)
        if evidence_first:
            refs = sorted(anchor['target_ref_ids'], key=lambda r: (
                job['catalog']['target_refs'][r]['start_char'], job['catalog']['target_refs'][r]['end_char'], r))
            selected['target_ref_ids'] = refs
            spans = [job['catalog']['target_refs'][r] for r in refs]
            gaps, pieces = [], []
            for i, span in enumerate(spans):
                if i:
                    end, start = spans[i-1]['end_char'], span['start_char']
                    require(end <= start, 'overlapping selected evidence')
                    if end < start:
                        gaps.append({'start_char': end, 'end_char': start})
                        pieces.append(f'\n[GAP {end}:{start}]\n')
                pieces.append(span['quote'])
            selected.update(primary_claim=''.join(pieces), primary_gaps=gaps,
                            claim_origin='host_extracted',
                            primary_representation='extractive_source_spans_with_explicit_gaps')
        if primary_support:
            source_key = lambda r: (catalog[r]['start_char'], catalog[r]['end_char'], r)
            support = sorted(anchor['supporting_ref_ids'], key=source_key)
            selected.update(supporting_ref_ids=support,
                            target_ref_ids=sorted([primary] + support, key=source_key),
                            supporting_evidence=[copy.deepcopy(catalog[r]) for r in support],
                            primary_claim=catalog[primary]['quote'], claim_origin='host_extracted',
                            primary_representation='extractive_primary_ref_with_separate_support')
        primary_refs = [primary] if primary_support else selected['target_ref_ids']
        normalized.append({**selected, 'primary_evidence': [copy.deepcopy(job['catalog']['target_refs'][r]) for r in primary_refs],
                           'context_evidence': [], 'supplements': [],
                           'status': 'needs_context' if anchor['needs_context'] else 'provisional_au'})
    decision = value['decision']
    require((decision == 'positive') == bool(normalized) or decision in ('needs_context', 'unresolved'), 'decision/anchor inconsistency')
    require(decision != 'negative' or (not normalized and not value['needs_context']), 'negative cannot have dependencies')
    if decision == 'needs_context':
        require(bool(value['needs_context']) or any(a['needs_context'] for a in normalized), 'needs_context requires dependency')
    if decision == 'unresolved':
        for anchor in normalized: anchor['status'] = 'unresolved'
    return {**copy.deepcopy(value), 'anchors': normalized, 'protocol_status': 'verified',
            'reason_text': REASON_TEXT_VI[value['reason']], 'semantic_quality': 'not_assessed',
            'revisit_required': decision in ('needs_context', 'unresolved') and not normalized}


def build_stage2(row, stage1, identity):
    """Return [] or [one job]; all <=3 locked anchors share ONE TARGET request."""
    # Revalidate a normalized stage1; no caller-supplied primary_evidence is trusted.
    selection_only = row.get('prompt_profile') in ('evidence_first_v1', 'primary_support_v1')
    if selection_only and 'protocol_status' not in stage1:
        # A raw selection must obey the exact wire keys, including no claim.
        raw = copy.deepcopy(stage1)
    else:
        raw = {k: copy.deepcopy(stage1[k]) for k in STAGE1_KEYS}
        raw['anchors'] = [{k: a[k] for k in stage1_anchor_keys(row.get('prompt_profile'))} for a in raw['anchors']]
    checked = validate_stage1(raw, build_stage1(row, identity))
    if selection_only and 'protocol_status' in stage1:
        require(stage1 == checked, 'normalized selection/evidence changed')
    if not checked['anchors']: return []
    needs = bool(checked['needs_context']) or any(a['needs_context'] for a in checked['anchors'])
    if not needs: return []
    return [_make_job(row, identity, 2, checked['anchors'], checked)]


def validate_stage2(value, job):
    """Keep exact primary_claim; return supplements separately, never new AU."""
    require(job['stage'] == 2, 'not a stage2 job')
    _base(value, job, STAGE2_KEYS, STAGE2)
    require(value['decision'] in ('complete', 'unresolved', 'revisit_target'), 'unknown global decision')
    _reason(value, STAGE2_REASON_BY_DECISION)
    require(isinstance(value['anchors'], list) and len(value['anchors']) == len(job['locked_anchors']), 'locked anchor count changed')
    normalized = []
    for answer, locked in zip(value['anchors'], job['locked_anchors']):
        _keys(answer, STAGE2_ANCHOR_KEYS)
        require(answer['anchor_id'] == locked['anchor_id'], 'anchor changed/reordered')
        require(answer['decision'] in ('keep', 'reject', 'unresolved'), 'unknown anchor decision')
        _reason(answer, STAGE2_ANCHOR_REASON_BY_DECISION)
        require(isinstance(answer['supplements'], list) and len(answer['supplements']) <= len(SLOTS), 'supplement cap')
        require(answer['decision'] == 'keep' or not answer['supplements'], 'rejected/unresolved anchor cannot receive supplements')
        slots, evidence, supplements = set(), {}, []
        for addition in answer['supplements']:
            _keys(addition, SUPPLEMENT_KEYS)
            require(addition['slot'] in SLOTS and addition['slot'] not in slots, 'foreign/duplicate slot')
            slots.add(addition['slot']); _text(addition['text'])
            _refs(addition['context_ref_ids'], job['catalog']['context_refs'])
            refs = [copy.deepcopy(job['catalog']['context_refs'][r]) for r in addition['context_ref_ids']]
            evidence.update({r['ref_id']: r for r in refs})
            supplements.append({**copy.deepcopy(addition), 'context_evidence': refs})
        normalized.append({**copy.deepcopy(locked), 'decision': answer['decision'],
                           'status': 'provisional_au' if answer['decision'] == 'keep' else answer['decision'],
                           'supplements': supplements, 'context_evidence': list(evidence.values()),
                           'reason': answer['reason'], 'reason_text': REASON_TEXT_VI[answer['reason']]})
    if value['decision'] == 'complete':
        require(bool(normalized) and all(a['decision'] != 'unresolved' for a in normalized), 'complete with unresolved/no anchors')
    else:
        require(not normalized or any(a['decision'] == 'unresolved' for a in normalized) or value['decision'] == 'revisit_target', 'global unresolved must reflect anchor status')
    if not normalized: require(value['decision'] in ('unresolved', 'revisit_target'), 'context-only AU creation prohibited')
    return {**copy.deepcopy(value), 'anchors': normalized, 'protocol_status': 'verified',
            'reason_text': REASON_TEXT_VI[value['reason']],
            'semantic_quality': 'not_assessed', 'revisit_required': value['decision'] == 'revisit_target'}
