"""Source-bound workload, compact grammar, rendering and soft-length validation."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .contracts import *
from .token_budget import counter_identity, input_reservation
from ..au_claim import core as original
from ..au_claim.compare import _checkpoint
from ..au_context_paired.build import binding, verify_bindings, write_new
from ..au_presentation_paired.core import profile
from ..source_contract import open_source

load, require, fingerprint, guard_output = original.load, original.require, original.fingerprint, original.guard_output
DEFAULT_PARENT = Path(__file__).resolve().parents[1] / 'outputs/au_claim_a_local_ready_20261020'


def code_hash():
    return fingerprint({'legacy_dependency': original.code_hash(), **{
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))}})


def runtime_config(identity):
    return original.runtime_config(identity)


def _material(parent_root):
    root = Path(parent_root).resolve()
    old, _, history, ledger = _checkpoint(root / 'input/workload.json', root / 'live/run.json')
    require(len(ledger['jobs']) == 16 and all(e['job']['stage'] == 1 and
            e['status'] in ('verified', 'invalid') for e in ledger['jobs'].values()), 'requires original terminal same16 stage1')
    cases, paths = {}, [root / 'input/workload.json', root / 'live/run.json', root / 'live/runtime_ledger.json']
    for rid, entry in ledger['jobs'].items():
        job = entry['job']
        require(not job['catalog']['context_refs'], 'K0 excludes context never sent in stage1')
        supplied = json.loads(job['payload']['messages'][0]['content'].split('\nINPUT:\n', 1)[1])
        refs = job['catalog']['target_refs']
        require(set(supplied) == {'TARGET'} and supplied['TARGET'] == [
            {'id': k, 'text': v['quote']} for k, v in refs.items()], 'historical payload/catalog mismatch')
        case = cases.setdefault(job['case_id'], {'case_id': job['case_id'], 'source_hash': job['source_hash'], 'scopes': []})
        require(case['source_hash'] == job['source_hash'], 'mixed source versions')
        source = open_source(old['source_store'], job['case_id'], job['source_hash'])
        case['source_char_length'] = len(source)
        spans = []
        for ref in refs.values():
            require(ref['case_id'] == case['case_id'] and ref['source_hash'] == case['source_hash'] and
                    source[ref['start_char']:ref['end_char']] == ref['quote'], 'invalid historical evidence')
            spans.append({k: ref[k] for k in ('case_id', 'source_hash', 'start_char', 'end_char', 'quote')})
        case['scopes'].append({'historical_request_id': rid, 'spans': sorted(spans, key=lambda r: (r['start_char'], r['end_char']))})
        paths.append(root / 'live/receipts' / (rid + '.json'))
    for case in cases.values():
        case['scopes'].sort(key=lambda s: s['spans'][0]['start_char'])
        catalog = {}
        for i, scope in enumerate(case['scopes'], 1):
            scope['scope_id'] = 'r' + str(i)
            scope['evidence_ids'] = []
            for span in scope.pop('spans'):
                found = next((k for k, v in catalog.items() if v == span), None)
                eid = found or 'e' + str(len(catalog) + 1)
                catalog[eid] = span
                scope['evidence_ids'].append(eid)
        case['evidence_catalog'] = catalog
    require(set(cases) == {'011904', '045155', '099980'}, 'unexpected calibration cases')
    paths += sorted((root / 'live/attempt_receipts').glob('*.json'))
    return {'artifact_type': 'K0AuthoringWorkload', 'version': VERSION, 'parent_root': str(root),
            'parent_bindings': [binding(p) for p in paths], 'identity': old['identity'],
            'source_store': old['source_store'], 'cases': [cases[k] for k in sorted(cases)],
            'budget': dict(BUDGET), 'input_cap': INPUT_CAP, 'output_cap': OUTPUT_CAP, 'total_cap': TOTAL_CAP,
            'code_sha256': code_hash(), 'input_counter': counter_identity(), 'baseline_accounting': history,
            'scope_policy': 'actual_delivered_stage1_catalog_only', 'semantic_quality': 'not_assessed'}


def prepare(output_root, parent_root=DEFAULT_PARENT):
    w = _material(parent_root)
    root = Path(output_root).resolve()
    guard_output(root, [w['parent_root'], w['source_store'], Path(__file__).parent])
    require(not root.exists(), 'prepare requires fresh output root')
    w['workload_sha256'] = fingerprint(w)
    write_new(root / 'input/workload.json', w)
    return w


def preflight(workload, cfg=None):
    w = load(workload)
    require(w['workload_sha256'] == fingerprint({k: v for k, v in w.items() if k != 'workload_sha256'}), 'workload digest mismatch')
    verify_bindings(w['parent_bindings'])
    require({k: v for k, v in w.items() if k != 'workload_sha256'} == _material(w['parent_root']), 'stale workload/source/code')
    cfg = cfg or runtime_config(w['identity'])
    profile(w, cfg)
    packets = []
    from .tools import initial_state
    for case in w['cases']:
        job = build_job(w, case, initial_state(case), cfg)
        packets.append({'case_id': case['case_id'], 'initial_scope_ids': job['active_scope_ids'],
                        'input_reservation': job['input_reservation'], 'payload_sha256': job['payload_sha256']})
    return {'status': 'pass', 'case_count': len(w['cases']), 'scope_count': sum(len(c['scopes']) for c in w['cases']),
            'initial_packets': packets, 'input_count_method': counter_identity()['method'],
            'input_counter': counter_identity(), 'native_grammar_compile': 'not_checked',
            'max_model_POST_attempts': BUDGET['max_provider_attempts'], 'total_cap': TOTAL_CAP,
            'network_executed': False, 'semantic_quality': 'not_assessed'}


def _grammar(eids, scope_ids, draft_ids):
    lit = lambda v: json.dumps(v, ensure_ascii=True)
    val = lambda v: lit(json.dumps(v, ensure_ascii=True))
    rules = []
    def rule(k, v): rules.append(k + ' ::= ' + v)
    def obj(parts): return lit('{') + ' ' + (' ' + lit(',') + ' ').join(parts) + ' ' + lit('}')
    def field(k, v): return lit(json.dumps(k) + ':') + ' ' + v
    rule('root', obj([field('aus', 'aus'), field('assessed_scope_ids', 'scopes'), field('next_action', 'action')]))
    rule('aus', lit('[') + ' (au (' + lit(',') + ' au){0,7})? ' + lit(']'))
    au = obj([field('claim', 'text'), field('kind', 'kind'), field('evidence_ids', 'refs'), field('limits', 'nullable')])
    # Optional replace_id keeps the four-field add wire small.
    au = au.rsplit(' ' + lit('}'), 1)[0] + ' (' + lit(',"replace_id":') + ' replacement)? ' + lit('}')
    rule('au', au)
    rule('replacement', ' | '.join(val(v) for v in [None, *draft_ids]))
    rule('kind', ' | '.join(val(v) for v in [None, *KINDS]))
    rule('nullable', val(None) + ' | text')
    rule('refs', lit('[') + ' ref (' + lit(',') + ' ref)* ' + lit(']'))
    rule('ref', ' | '.join(val(v) for v in eids))
    rule('scopes', lit('[') + ' (scope (' + lit(',') + ' scope)*)? ' + lit(']'))
    rule('scope', ' | '.join(val(v) for v in scope_ids))
    rule('action', ' | '.join([
        obj([field('tool', val('open_region')), field('scope_ids', 'open-scopes')]),
        obj([field('tool', val('search_source')), field('query', 'text')]),
        obj([field('tool', val('get_drafts'))]),
        obj([field('tool', val('finish_case')), field('reason', 'finish-reason')])]))
    rule('finish-reason', val('work_scope_complete') + ' | ' + val('needs_context'))
    rule('open-scopes', lit('[') + ' scope (' + lit(',') + ' scope)* ' + lit(']'))
    rule('text', r'"\"" json-char* "\""')
    rule('json-char', r'[\x20-\x21\x23-\x5b\x5d-\uD7FF\uE000-\U0010FFFF] | "\\" (["\\/bfnrt] | "u" scalar-hex) | "\\u" [dD] [89aAbB] hex hex "\\u" [dD] [c-fC-F] hex hex')
    rule('scalar-hex', '[0-9a-cA-Ce-fE-F] hex hex hex | [dD] [0-7] hex hex')
    rule('hex', '[0-9a-fA-F]')
    return '\n'.join(rules) + '\n'


def _job(w, case, state, cfg, active):
    byid = {s['scope_id']: s for s in case['scopes']}
    evidence = {e: case['evidence_catalog'][e] for sid in active for e in byid[sid]['evidence_ids']}
    drafts = [{'id': k, 'claim_preview': a['claim'][:100], 'preview_only': len(a['claim']) > 100}
              for k, a in state['drafts'].items()]
    data = {'CASE': case['case_id'], 'turn': state['turn'],
            'NAVIGATION': [{'scope_id': s['scope_id'], 'state': state['read_ledger'][s['scope_id']]['state'],
                            'start': min(case['evidence_catalog'][e]['start_char'] for e in s['evidence_ids'])}
                           for s in case['scopes']],
            'SOURCE': [{'scope_id': sid, 'parts': [{'id': e, 'text': case['evidence_catalog'][e]['quote']}
                        for e in byid[sid]['evidence_ids']]} for sid in active],
            'CURRENT_DRAFTS': drafts, 'TOOL_RESULT': state.get('tool_result')}
    payload = {'model': cfg['model'], 'messages': [{'role': 'user', 'content': INSTRUCTIONS + '\nINPUT:\n' +
               json.dumps(data, ensure_ascii=False, separators=(',', ':'))}], 'temperature': 0,
               'max_tokens': OUTPUT_CAP, 'chat_template_kwargs': {'enable_thinking': False},
               'ebnf': _grammar(list(evidence), list(byid), list(state['drafts']))}
    reserve = input_reservation(payload)
    material = {'workload': w['workload_sha256'], 'case': case['case_id'], 'state': fingerprint(state), 'payload': payload}
    return {'request_id': 'k0-' + fingerprint(material)[:24], 'payload_sha256': fingerprint(payload), 'payload': payload,
            'case_id': case['case_id'], 'target_id': case['case_id'], 'source_hash': case['source_hash'],
            'turn': state['turn'], 'state_sha256': fingerprint(state), 'active_scope_ids': active,
            'catalog': {'evidence': evidence}, 'allowed_scope_ids': list(byid),
            'draft_ids': list(state['drafts']), 'input_reservation': reserve}


def build_job(w, case, state, cfg):
    require(not state['finished'], 'case task already finished')
    requested = state.get('active_scope_ids')
    if requested is None:
        active = []
        for scope in case['scopes']:
            trial = active + [scope['scope_id']]
            if _job(w, case, state, cfg, trial)['input_reservation'] <= INPUT_CAP:
                active = trial
            else:
                break
        require(bool(active), 'initial source scope exceeds conservative input cap')
    else:
        active = list(requested)
    require(bool(active) and len(active) == len(set(active)) and
            set(active) <= {s['scope_id'] for s in case['scopes']}, 'invalid source selection')
    job = _job(w, case, state, cfg, active)
    require(job['input_reservation'] <= INPUT_CAP, 'full payload exceeds conservative input cap')
    return job


def validate_response(value, job):
    require(isinstance(value, dict) and set(value) == {'aus', 'assessed_scope_ids', 'next_action'}, 'exact turn keys required')
    require(isinstance(value['aus'], list) and len(value['aus']) <= MAX_AUS, 'invalid AU transport list')
    assessed = value['assessed_scope_ids']
    require(isinstance(assessed, list) and all(isinstance(s, str) and s in job['active_scope_ids'] for s in assessed), 'cannot assess unopened scope')
    action = value['next_action']
    require(isinstance(action, dict), 'invalid next action')
    tool = action.get('tool')
    if tool == 'open_region':
        require(set(action) == {'tool', 'scope_ids'} and isinstance(action['scope_ids'], list) and
                bool(action['scope_ids']) and all(isinstance(s, str) and s in job['allowed_scope_ids'] for s in action['scope_ids']), 'scope outside K0 union')
    elif tool == 'search_source':
        require(set(action) == {'tool', 'query'} and isinstance(action['query'], str) and bool(action['query'].strip())
                and not any(0xD800 <= ord(c) <= 0xDFFF for c in action['query']), 'invalid search query')
    elif tool == 'get_drafts':
        require(set(action) == {'tool'}, 'invalid draft action')
    else:
        require(tool == 'finish_case' and set(action) == {'tool', 'reason'} and
                action['reason'] in ('work_scope_complete', 'needs_context'), 'invalid finish action')
    warnings, aus, errors, replacing = [], [], [], set()
    def text(v, threshold, path):
        require(isinstance(v, str) and bool(v.strip()) and not any(0xD800 <= ord(c) <= 0xDFFF for c in v), 'invalid text')
        if len(v) > threshold:
            warnings.append({'code': 'length_threshold_exceeded', 'path': path, 'actual_length': len(v), 'threshold': threshold})
        return ' '.join(v.split())
    for i, item in enumerate(value['aus']):
        try:
            require(isinstance(item, dict) and set(item) in ({'claim', 'kind', 'evidence_ids', 'limits'},
                    {'claim', 'kind', 'evidence_ids', 'limits', 'replace_id'}), 'invalid AU keys')
            claim = text(item['claim'], 500, ['aus', i, 'claim'])
            limits = None if item['limits'] is None else text(item['limits'], 250, ['aus', i, 'limits'])
            kind, refs, replace = item['kind'], item['evidence_ids'], item.get('replace_id')
            require(kind is None or isinstance(kind, str) and kind in KINDS, 'invalid kind')
            require(replace is None or isinstance(replace, str) and replace in job['draft_ids'] and replace not in replacing, 'invalid replacement')
            require(isinstance(refs, list) and refs and all(isinstance(e, str) and e in job['catalog']['evidence'] for e in refs), 'invalid or unopened evidence')
            refs = sorted(set(refs), key=lambda e: job['catalog']['evidence'][e]['start_char'])
            spans = [copy.deepcopy(job['catalog']['evidence'][e]) for e in refs]
            require(all(s['case_id'] == job['case_id'] and s['source_hash'] == job['source_hash'] for s in spans), 'foreign evidence')
            aid = 'k0au-' + fingerprint([job['case_id'], job['source_hash'], claim, kind, spans, limits])[:24]
            aus.append({'au_id': aid, 'case_id': job['case_id'], 'source_hash': job['source_hash'],
                        'claim': claim, 'kind': kind, 'evidence_ids': refs, 'evidence': spans, 'limits': limits,
                        'replace_id': replace, 'quality_status': 'grounded_draft', 'semantic_quality': 'not_assessed'})
            if replace: replacing.add(replace)
        except (ValueError, TypeError, KeyError, IndexError):
            errors.append({'index': i, 'code': 'invalid_AU'})
    return {'aus': aus, 'au_errors': errors, 'warnings': warnings,
            'assessed_scope_ids': list(dict.fromkeys(assessed)),
            'delivered_scope_ids': list(job['active_scope_ids']), 'next_action': copy.deepcopy(action)}


def mock_response(job):
    all_scopes = job['allowed_scope_ids']
    # Synthetic controls do not infer semantic content or read KOS outputs.
    supplied = json.loads(job['payload']['messages'][0]['content'].split('\nINPUT:\n')[1])
    done = {x['scope_id'] for x in supplied['NAVIGATION'] if x['state'] == 'assessed'} | set(job['active_scope_ids'])
    remaining = [s for s in all_scopes if s not in done]
    return {'aus': [{'claim': 'Synthetic legal point; mock is not semantic assessment.', 'kind': None,
                     'evidence_ids': [next(iter(job['catalog']['evidence']))], 'limits': None}],
            'assessed_scope_ids': job['active_scope_ids'],
            'next_action': {'tool': 'open_region', 'scope_ids': [remaining[0]]} if remaining else
                           {'tool': 'finish_case', 'reason': 'work_scope_complete'}}
