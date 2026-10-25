"""Exact historical union; independently bound v2 prompt, grammar and sources."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from ..k0_authoring import core as old
from ..kos_authoring_controls_v2 import controls as controls
from ..au_context_paired.build import binding, verify_bindings, write_new
from ..au_compact.runner import _atomic

VERSION = 'k0-authoring-v2'
DEFAULT_PARENT = Path(old.__file__).resolve().parents[1] / 'outputs/k0_ready_20261023'
PARENT_SHA256 = '59a0821b1e4403ee94eb765f324b006d6be24113d2914e7c607dbacc521abfc6'
DEFAULT_CONTROLS = controls.DEFAULT_ROOT
DEFAULT_ROOT = DEFAULT_PARENT.parent / 'k0_authoring_v2_20261025'
INPUT_CAP, OUTPUT_CAP, TOTAL_CAP = 6000, 800, 30000
BUDGET = dict(old.BUDGET)
load, require, fingerprint = old.load, old.require, old.fingerprint
input_reservation, counter_identity = old.input_reservation, old.counter_identity
runtime_config, profile = old.runtime_config, old.profile
INSTRUCTIONS = controls.final_instructions() + controls.demonstrations()


def code_hash():
    # Narrow explicit production dependency closure. Other plans/tests/docs are not bindings.
    base = Path(__file__).resolve().parents[1]
    packages = ('k0_authoring_v2', 'k0_authoring', 'kos_authoring_controls_v2',
                'kos_authoring_controls', 'au_target_context', 'au_compact',
                'au_context_paired', 'au_presentation_paired', 'au_claim', 'source_contract')
    files = sorted(p for name in packages for p in (base / name).glob('*.py'))
    files += [base / 'experiments/k0_grammar_cpu_probe.py',
              base / 'experiments/recover_kos_contract_v2_report.py',
              base / 'experiments/run_k0_v2.ps1', base / 'au_runtime_config.py']
    return fingerprint({str(p.relative_to(base)): binding(p)['sha256'] for p in files})


def guard_output(root, protected=()):
    return old.guard_output(root, [DEFAULT_PARENT, DEFAULT_CONTROLS,
        controls.PARENT, controls.v1.BASELINE,
        Path(__file__).parent, Path(old.__file__).parent, *protected])


def _parent(parent_root):
    path = Path(parent_root).resolve()
    path = path if path.name == 'workload.json' else path / 'input/workload.json'
    require(path == DEFAULT_PARENT.resolve() / 'input/workload.json', 'exact frozen K0 parent required')
    require(binding(path)['sha256'] == PARENT_SHA256, 'frozen parent byte digest changed')
    w = load(path)
    require(w['workload_sha256'] == fingerprint({k: v for k, v in w.items()
                                              if k != 'workload_sha256'}), 'parent digest mismatch')
    verify_bindings(w['parent_bindings'])
    require((len(w['cases']), sum(len(c['scopes']) for c in w['cases']),
             sum(len(s['evidence_ids']) for c in w['cases'] for s in c['scopes'])) == (3, 16, 58),
            'requires exact 3-case/16-scope/58-part union')
    require({c['case_id'] for c in w['cases']} == {'011904', '045155', '099980'}, 'foreign cases')
    for case in w['cases']:
        source = old.open_source(w['source_store'], case['case_id'], case['source_hash'])
        require(len(source) == case['source_char_length'], 'source length mismatch')
        for ref in case['evidence_catalog'].values():
            require(ref['case_id'] == case['case_id'] and ref['source_hash'] == case['source_hash']
                    and source[ref['start_char']:ref['end_char']] == ref['quote'], 'source/offset mismatch')
    return path, w


def _material(parent_root):
    path, parent = _parent(parent_root)
    source_files = [Path(parent['source_store']) / 'cases' / case['case_id'] / 'versions'
                    / case['source_hash'] / name for case in parent['cases']
                    for name in ('case_source.json', 'source.txt')]
    return {'artifact_type': 'K0AuthoringWorkloadV2', 'version': VERSION,
        'parent_root': str(path.parent.parent),
        'parent_bindings': [binding(path), *copy.deepcopy(parent['parent_bindings'])],
        'source_bindings': [binding(p) for p in source_files],
        'source_store': parent['source_store'], 'cases': copy.deepcopy(parent['cases']),
        'identity': copy.deepcopy(parent['identity']), 'budget': BUDGET,
        'input_cap': INPUT_CAP, 'output_cap': OUTPUT_CAP, 'total_cap': TOTAL_CAP,
        'input_counter': counter_identity(), 'code_sha256': code_hash(),
        'prompt_sha256': fingerprint(INSTRUCTIONS), 'wire_version': controls.WIRE_VERSION,
        'schema_sha256': fingerprint(_grammar(['binding-e'], ['binding-r'], ['binding-draft'])),
        'scope_policy': parent['scope_policy'], 'baseline_accounting': parent['baseline_accounting'],
        'semantic_quality': 'not_assessed', 'case_source_status': 'partial'}


def prepare(output_root, parent_root=DEFAULT_PARENT):
    w = _material(parent_root)
    root = Path(output_root).resolve()
    guard_output(root, [w['source_store'], *[Path(b['path']).parent for b in w['parent_bindings']]])
    require(not root.exists(), 'prepare requires fresh root')
    w['workload_sha256'] = fingerprint(w)
    cfg = runtime_config(w['identity'])
    from .tools import initial_state
    jobs = [build_job(w, c, initial_state(c), cfg) for c in w['cases']]
    write_new(root / 'input/workload.json', w)
    write_new(root / 'input/cpu_authoring.json', cpu_bundle(jobs))
    return w


def preflight(workload, cfg=None):
    w = load(workload)
    if isinstance(workload, (str, Path)):
        guard_output(Path(workload).resolve().parent.parent, [w['source_store'],
            *[Path(b['path']).parent for b in w['parent_bindings']]])
    require(w['workload_sha256'] == fingerprint({k: v for k, v in w.items()
                                               if k != 'workload_sha256'}), 'workload digest mismatch')
    verify_bindings(w['parent_bindings'])
    verify_bindings(w['source_bindings'])
    require({k: v for k, v in w.items() if k != 'workload_sha256'} == _material(w['parent_root']),
            'frozen material/code changed')
    cfg = cfg or runtime_config(w['identity'])
    profile(w, cfg)
    from .tools import initial_state
    jobs = [build_job(w, c, initial_state(c), cfg) for c in w['cases']]
    if isinstance(workload, (str, Path)):
        require(load(Path(workload).parent / 'cpu_authoring.json') == cpu_bundle(jobs),
                'CPU bundle changed')
    return {'status': 'pass', 'case_count': 3, 'scope_count': 16, 'part_count': 58,
            'initial_packets': [{'case_id': j['case_id'], 'payload_sha256': j['payload_sha256'],
                                 'input_reservation': j['input_reservation']} for j in jobs],
            'network_executed': False, 'semantic_quality': 'not_assessed'}


def _grammar(eids, scope_ids, draft_ids):
    # Preserve real draft IDs in replacement production; controls grammar uses no drafts.
    root = controls.grammar(eids, scope_ids).splitlines()[0]
    lines = [root if line.startswith('root ::=') else line
             for line in old._grammar(eids, scope_ids, draft_ids).splitlines()
             if not line.startswith('scopes ::=')]
    lines.append('empty-reason ::= ' + ' | '.join(json.dumps(json.dumps(v))
                                              for v in (None, *controls.REASONS)))
    return '\n'.join(lines) + '\n'


def _job(w, case, state, cfg, active):
    job = old._job(w, case, state, cfg, active)
    payload = job['payload']
    text = payload['messages'][0]['content']
    require(text.startswith(old.INSTRUCTIONS + '\nINPUT:\n'), 'frozen renderer anchor changed')
    payload['messages'][0]['content'] = INSTRUCTIONS + text[len(old.INSTRUCTIONS):]
    payload['ebnf'] = _grammar(list(job['catalog']['evidence']), job['allowed_scope_ids'], job['draft_ids'])
    job['input_reservation'] = input_reservation(payload)
    job['payload_sha256'] = fingerprint(payload)
    job['request_id'] = 'k0v2-' + fingerprint([w['workload_sha256'], case['case_id'],
                                             job['state_sha256'], payload])[:24]
    return job


def build_job(w, case, state, cfg):
    require(not state['finished'], 'finished case')
    active = state.get('active_scope_ids')
    if active is None:
        active = []
        for scope in case['scopes']:
            trial = active + [scope['scope_id']]
            if _job(w, case, state, cfg, trial)['input_reservation'] > INPUT_CAP:
                break
            active = trial
    require(bool(active) and len(active) == len(set(active))
            and set(active) <= {s['scope_id'] for s in case['scopes']}, 'invalid source selection')
    job = _job(w, case, state, cfg, list(active))
    require(job['input_reservation'] <= INPUT_CAP, 'full v2 payload exceeds input cap')
    return job


validate_response = controls.validate


def mock_response(job):
    return {'aus': [], 'empty_reason': 'insufficient_context',
            'next_action': {'tool': 'finish_case', 'reason': 'needs_context'}}


def cpu_bundle(jobs):
    rows = []
    for job in jobs:
        positive = {'aus': [{'claim': 'Synthetic protocol witness.', 'kind': None,
            'evidence_ids': [next(iter(job['catalog']['evidence']))], 'limits': None}],
            'empty_reason': None, 'next_action': {'tool': 'finish_case', 'reason': 'work_scope_complete'}}
        empty = mock_response(job)
        negative = copy.deepcopy(positive)
        negative['aus'][0]['evidence_ids'] = ['not-in-catalog']
        bad_scope = {'aus': [], 'empty_reason': None,
                     'next_action': {'tool': 'open_region', 'scope_ids': ['not-in-catalog']}}
        rows.append({'name': job['case_id'], 'grammar': job['payload']['ebnf'],
            'positive_examples': [controls.encode(v) for v in (positive, empty)],
            'negative_examples': [controls.encode(v) for v in
                (negative, bad_scope, dict(positive, assessed_scope_ids=[]))]})
    # Exercise replacement with a real shaped ID in addition to actual initial payload grammars.
    job = jobs[0]
    draft_id = 'k0au-' + 'a' * 24
    revision = copy.deepcopy(positive)
    revision['aus'][0]['evidence_ids'] = [next(iter(job['catalog']['evidence']))]
    revision['aus'][0]['replace_id'] = draft_id
    bad = copy.deepcopy(revision)
    bad['aus'][0]['replace_id'] = 'not-in-drafts'
    rows.append({'name': 'draft-revision',
        'grammar': _grammar(list(job['catalog']['evidence']), job['allowed_scope_ids'], [draft_id]),
        'positive_examples': [controls.encode(revision)], 'negative_examples': [controls.encode(bad)]})
    return {'version': VERSION, 'jobs': rows, 'semantic_quality': 'not_assessed'}


def require_cpu(root):
    from ..kos_authoring_controls.__main__ import require_cpu as check
    check(root, 'authoring')


def require_controls(root, w):
    """Verify persisted recovery without writing controls or invoking transport."""
    from ..experiments import recover_kos_contract_v2_report as recovery
    # Private reporter namespace: suppress its derived-report writes, retain every check.
    import types
    module = types.ModuleType(__package__ + '._offline_gate')
    module.__file__, module.__package__ = recovery.__file__, recovery.__package__
    text = Path(recovery.__file__).read_text(encoding='utf-8')
    anchor = '    destination.mkdir(exist_ok=True)'
    require(text.count(anchor) == 1, 'frozen reporter anchor changed')
    text = text[:text.index(anchor)] + '    return report\n'
    exec(compile(text, recovery.__file__, 'exec'), module.__dict__)
    report = module.build_report(root)
    persisted = load(Path(root) / 'recovered_report/report.json')
    require(fingerprint(report) == fingerprint(persisted), 'persisted recovered report changed')
    require(report['status'] == 'semantic_review_pending'
            and report['protocol_valid_count'] == report['structural_control_pass_count'] == 9
            and not report['budget_violation'] and report['unknown_usage_count'] == 0,
            'nine valid completed persisted controls required')
    manifest = load(Path(root) / 'input/manifest.json')
    require(all(manifest['identity'][k] == w['identity'][k]
                for k in ('model', 'url', 'expected_model_revision')), 'controls model identity mismatch')
    return report['sha256']
