"""Frozen same-source workload, short evidence aliases, and host validation."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from .contracts import (VERSION, PROMPT_PROFILE, KINDS, MAX_AUS, OUTPUT_CAP, BUDGET,
                        DEFAULT_PARENT_WORKLOAD, DEFAULT_PARENT, INSTRUCTIONS)
from ..au_target_context import core as old_core
from ..au_context_paired.build import fingerprint, binding, verify_bindings, write_new
from ..au_presentation_paired.core import profile
from ..source_contract import open_source

load = old_core.load
require = old_core.require
guard_output = old_core.guard_output
ROW_KEYS = ('target_id', 'case_id', 'source_hash', 'target', 'target_refs', 'context_refs')


def prompt_metadata():
    return {'prompt_profile': PROMPT_PROFILE, 'prompt_sha': fingerprint([VERSION, INSTRUCTIONS])}


def code_hash():
    # Include the entire isolated package (also Main-owned CLI/comparison) and
    # local pipeline dependencies, including the unchanged transport runtime.
    base = Path(__file__).resolve().parents[1]
    paths = set(Path(__file__).parent.glob('*.py'))
    for package in ('au_target_context', 'au_compact', 'au_only', 'au_context_paired',
                    'au_presentation_paired', 'source_contract', 'kos_comparison',
                    'sentence_atoms', 'contracts'):
        paths.update((base / package).rglob('*.py'))
    paths.add(base / 'au_runtime_config.py')
    return fingerprint({str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(paths)})


def runtime_config(identity):
    return {**identity, 'jobs_url': identity['url'].removesuffix('/chat/completions') + '/jobs',
            'timeout': 60, 'job_wait_seconds': 1800, 'job_poll_seconds': 2}


def _rows(parent):
    return [{k: copy.deepcopy(row[k]) for k in ROW_KEYS} for row in parent['rows']]


def prepare(output_root, parent_workload=DEFAULT_PARENT_WORKLOAD, cfg=None):
    parent_path = Path(parent_workload).resolve()
    p = load(parent_path)
    old_core.preflight(p, cfg=cfg)
    require(p['artifact_type'] == 'AUKOSAlignedWorkload' and len(p['rows']) == 16,
            'requires verified same16 KOS-aligned parent')
    profile(p, cfg if cfg is not None else runtime_config(p['identity']))
    reference = load(p['reference_checklist_path'])
    require(len(reference['references']) == 18, 'requires same18 reference checklist')
    root = Path(output_root).resolve()
    guard_output(root, [parent_path.parent, p['source_store'], p['atom_root'], p['kos_root'],
                        Path(p['reference_checklist_path']).parent, Path(__file__).parent])
    require(not root.exists(), 'prepare output must be a new directory')
    w = {'artifact_type': 'AUClaimWorkload', 'version': VERSION, **prompt_metadata(), 'identity': copy.deepcopy(p['identity']),
         'source_store': p['source_store'], 'atom_root': p['atom_root'], 'rows': _rows(p),
         'parent_workload_sha256': p['workload_sha256'], 'parent_code_sha256': p['code_sha256'],
         'parent_bindings': [binding(parent_path), binding(p['reference_checklist_path'])],
         'source_bindings': copy.deepcopy(p['input_bindings']),
         'reference_checklist_path': str(root / 'reference_checklist.json'),
         'reference_checklist_sha256': reference['reference_sha256'],
         'context_policy': p['context_policy'], 'budget': dict(BUDGET), 'output_cap': OUTPUT_CAP,
         'semantic_gold': False, 'code_sha256': code_hash()}
    w['workload_sha256'] = fingerprint(w)
    write_new(root / 'reference_checklist.json', reference)
    write_new(root / 'workload.json', w)
    write_new(root / 'preflight.json', preflight(w, cfg))
    return w


def preflight(workload, cfg=None):
    w = load(workload)
    require(w.get('workload_sha256') == fingerprint({k: v for k, v in w.items() if k != 'workload_sha256'}),
            'workload digest mismatch')
    require(w['artifact_type'] == 'AUClaimWorkload' and w['version'] == VERSION, 'unknown claim workload')
    require(all(w.get(k) == v for k, v in prompt_metadata().items()), 'claim prompt metadata changed')
    require(w['code_sha256'] == code_hash() and w['budget'] == BUDGET and w['output_cap'] == OUTPUT_CAP
            and w['semantic_gold'] is False, 'code/budget/cap changed')
    verify_bindings(w['parent_bindings'])
    verify_bindings(w['source_bindings'])
    # Parent bindings are separate, not embedded historical ledgers/semantic answers.
    p = load(w['parent_bindings'][0]['path'])
    require(p['workload_sha256'] == w['parent_workload_sha256']
            and p['code_sha256'] == w['parent_code_sha256'] == old_core.code_hash(), 'parent binding changed')
    require(p['artifact_type'] == 'AUKOSAlignedWorkload' and w['identity'] == p['identity']
            and w['rows'] == _rows(p) and w['source_store'] == p['source_store']
            and w['atom_root'] == p['atom_root'] and w['source_bindings'] == p['input_bindings']
            and w['context_policy'] == p['context_policy'], 'parent source/runtime mismatch')
    profile(w, cfg if cfg is not None else runtime_config(w['identity']))
    reference = load(w['reference_checklist_path'])
    require(reference == load(w['parent_bindings'][1]['path'])
            and reference['reference_sha256'] == w['reference_checklist_sha256']
            == fingerprint({k: v for k, v in reference.items() if k != 'reference_sha256'})
            and len(reference['references']) == 18, 'reference checklist changed')
    require(len(w['rows']) == len({r['target_id'] for r in w['rows']}) == 16, 'requires same16 TARGETs')
    jobs = []
    for row in w['rows']:
        source = open_source(w['source_store'], row['case_id'], row['source_hash'])
        for role, refs in (('target_body', row['target_refs']), ('context', row['context_refs'])):
            for rid, ref in refs.items():
                a, b = ref['start_char'], ref['end_char']
                require(ref['ref_id'] == rid and ref['case_id'] == row['case_id']
                        and ref['source_hash'] == row['source_hash'] and ref['role'] == role
                        and type(a) is int and type(b) is int and 0 <= a < b <= len(source)
                        and ref['quote'] == source[a:b], 'source reference mismatch')
        jobs.append(build_job(row, w['identity']))
    sizes = [sum(len(m['content'].encode('utf-8')) for m in j['payload']['messages']) for j in jobs]
    require(sum(sizes) <= BUDGET['max_total_input_tokens'], 'stage1 input budget exceeded')
    return {'artifact_type': 'AUClaimPreflight', 'status': 'pass', 'workload_sha256': w['workload_sha256'],
            'target_count': 16, 'reference_count': 18, 'stage1_requests': 16, 'max_logical_requests': 32,
            'stage1_input_reservation_utf8_bytes': sum(sizes), 'budget': dict(BUDGET),
            'network_requests': 0, 'grammar_compile': 'not_checked', 'semantic_quality': 'not_assessed'}


def _grammar(ids):
    from ..au_compact.decoding import _literal as lit, _json_literal as jlit
    rules = []
    def rule(name, value): rules.append(name + ' ::= ' + value)
    def obj(parts): return lit('{') + ' ' + (' ' + lit(',') + ' ').join(parts) + ' ' + lit('}')
    def field(key, body): return lit(json.dumps(key) + ':') + ' ' + body
    rule('root', obj([field('aus', 'aus'), field('context_request', 'context')]))
    rule('aus', lit('[') + ' (au (' + lit(',') + ' au){0,2})? ' + lit(']'))
    rule('au', obj([field('claim', 'text'), field('kind', 'kind'), field('evidence_ids', 'refs'), field('limits', 'nullable-text')]))
    rule('context', jlit(None) + ' | ' + obj([field('question', 'text')]))
    rule('kind', ' | '.join(jlit(k) for k in (*KINDS, None)))
    rule('refs', lit('[') + ' ref (' + lit(',') + ' ref)* ' + lit(']'))
    rule('ref', ' | '.join(jlit(k) for k in ids))
    rule('nullable-text', jlit(None) + ' | text')
    rule('text', r'"\"" json-char* "\""')
    rule('json-char', r'[\x20-\x21\x23-\x5b\x5d-\uD7FF\uE000-\U0010FFFF] | "\\" (["\\/bfnrt] | "u" scalar-hex) | "\\u" [dD] [89aAbB] hex hex "\\u" [dD] [c-fC-F] hex hex')
    rule('scalar-hex', '[0-9a-cA-Ce-fE-F] hex hex hex | [dD] [0-7] hex hex')
    rule('hex', '[0-9a-fA-F]')
    return '\n'.join(rules) + '\n'


def _wire(normalized):
    return {'aus': [{k: copy.deepcopy(a[k]) for k in ('claim', 'kind', 'evidence_ids', 'limits')}
                    for a in normalized['aus']], 'context_request': copy.deepcopy(normalized['context_request'])}


def build_job(row, identity, stage=1, draft=None):
    require(type(stage) is int and stage in (1, 2), 'stage must be 1 or 2')
    require(stage == 2 or draft is None, 'stage1 cannot have a draft')
    target = {'s' + str(i): copy.deepcopy(v) for i, v in enumerate(row['target_refs'].values(), 1)}
    context = {'c' + str(i): copy.deepcopy(v) for i, v in enumerate(row['context_refs'].values(), 1)} if stage == 2 else {}
    require(bool(target), 'empty TARGET catalog')
    if stage == 2:
        require(isinstance(draft, dict), 'stage2 requires draft')
        draft = _wire(draft)
        validate_response(draft, build_job(row, identity))
        require(draft['context_request'] is not None, 'stage2 requires context request')
    data = {'TARGET': [{'id': k, 'text': v['quote']} for k, v in target.items()]}
    if stage == 2:
        data.update(CONTEXT=[{'id': k, 'text': v['quote']} for k, v in context.items()], draft=draft)
    instruction = ('Use only TARGET. No surrounding CONTEXT is supplied.' if stage == 1 else
        'Reconsider the entire draft using all original TARGET and the bounded frozen CONTEXT. '
        'You may rewrite, add or remove AUs and change every field. Context c-IDs may support AUs, '
        'but every AU still needs a TARGET s-ID. A further context_request remains unresolved; no further call will occur.')
    payload = {'model': identity['model'], 'messages': [{'role': 'user', 'content':
        INSTRUCTIONS + '\n' + instruction + '\nINPUT:\n' + json.dumps(data, ensure_ascii=False)}],
        'temperature': 0, 'max_tokens': OUTPUT_CAP, 'chat_template_kwargs': {'enable_thinking': False},
        'ebnf': _grammar([*target, *context])}
    material = {'version': VERSION, 'identity': identity, 'row': row, 'stage': stage, 'draft': draft, 'payload': payload}
    return {'request_id': 'auc-' + fingerprint(material)[:24], 'stage': stage, **prompt_metadata(), 'target_id': row['target_id'],
            'case_id': row['case_id'], 'source_hash': row['source_hash'], 'catalog':
            {'target_refs': target, 'context_refs': context}, 'draft': draft,
            'payload': payload, 'payload_sha256': fingerprint(payload)}


def validate_response(value, job):
    require(isinstance(value, dict) and set(value) == {'aus', 'context_request'}, 'exact response keys required')
    require(isinstance(value['aus'], list) and len(value['aus']) <= MAX_AUS, 'AU cap exceeded')
    def text(v, cap):
        require(isinstance(v, str) and 1 <= len(v) <= cap and bool(v.strip())
                and not any(0xD800 <= ord(c) <= 0xDFFF for c in v), 'invalid bounded text')
        return ' '.join(v.split())
    context_request = value['context_request']
    if context_request is not None:
        require(isinstance(context_request, dict) and set(context_request) == {'question'}, 'invalid context request')
        context_request = {'question': text(context_request['question'], 200)}
    target = job['catalog']['target_refs']
    allowed = {**target, **job['catalog']['context_refs']}
    aus, seen, removed = [], set(), 0
    for item in value['aus']:
        require(isinstance(item, dict) and set(item) == {'claim', 'kind', 'evidence_ids', 'limits'}, 'exact AU keys required')
        claim, kind = text(item['claim'], 500), item['kind']
        require(kind is None or (isinstance(kind, str) and kind in KINDS), 'unknown kind')
        refs = item['evidence_ids']
        require(isinstance(refs, list) and bool(refs) and all(isinstance(r, str) and r in allowed for r in refs), 'invalid evidence IDs')
        require(bool(set(refs) & set(target)), 'AU needs TARGET evidence')
        refs = sorted(set(refs), key=lambda r: (allowed[r]['start_char'], allowed[r]['end_char'], r))
        limits = None if item['limits'] is None else text(item['limits'], 250)
        signature = fingerprint([claim, kind, refs, limits])
        if signature in seen:
            removed += 1
            continue
        seen.add(signature)
        evidence = [{k: allowed[r][k] for k in ('ref_id', 'case_id', 'source_hash', 'start_char', 'end_char', 'quote', 'role')} for r in refs]
        aus.append({'au_id': 'au-' + fingerprint([job['target_id'], signature])[:24], 'claim': claim,
                    'kind': kind, 'evidence_ids': refs, 'limits': limits, 'evidence': evidence})
    shared = [{'au_ids': [a['au_id'], b['au_id']], 'evidence_ids': sorted(set(a['evidence_ids']) & set(b['evidence_ids'])),
               'semantic_merge': False} for i, a in enumerate(aus) for b in aus[i+1:]
              if set(a['evidence_ids']) & set(b['evidence_ids'])]
    return {'aus': aus, 'context_request': context_request, 'needs_context': context_request is not None,
            'exact_duplicates_removed': removed, 'shared_evidence_pairs': shared,
            'semantic_quality': 'not_assessed', 'semantic_status': 'unknown'}
