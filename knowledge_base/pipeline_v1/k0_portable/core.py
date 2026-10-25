"""Portable derived manifests; historical records are copied, never re-sealed."""
from __future__ import annotations

import copy
import hashlib
import platform
import sys
from pathlib import Path

from .paths import repository, resolve, relative
from ..k0_authoring_v2 import core as frozen
from ..k0_authoring_v2 import runner as v2runner
from ..kos_authoring_controls_v2 import __main__ as controls_cli
from ..au_compact.runner import _atomic

VERSION = 'k0-portable-v1'
DEFAULT_BUNDLE = 'knowledge_base/pipeline_v1/research_snapshots/k0_portable_20261025'
DEFAULT_RUN = 'research_bundle/k0_portable_runs/current'
load, require, fingerprint = frozen.load, frozen.require, frozen.fingerprint


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sealed(value, key='sha256'):
    require(value[key] == fingerprint({k: v for k, v in value.items() if k != key}),
            'derived manifest digest mismatch')


def production_bindings(repo):
    base = Path(frozen.__file__).resolve().parents[1]
    packages = ('k0_portable', 'k0_authoring_v2', 'k0_authoring',
                'kos_authoring_controls_v2', 'kos_authoring_controls', 'au_target_context',
                'au_compact', 'au_context_paired', 'au_presentation_paired', 'au_claim',
                'source_contract', 'au_only', 'kos_comparison', 'region_priority_offline',
                'region_priority_variants', 'selective_context_offline', 'sentence_atoms',
                'structural_prepass')
    files = {p for name in packages for p in (base / name).glob('*.py')}
    files.update(base / p for p in ('experiments/k0_grammar_cpu_probe.py',
        'experiments/recover_kos_contract_v2_report.py', 'au_runtime_config.py',
        'experiments/run_k0_v2.ps1', 'experiments/run_k0_portable.ps1'))
    files.update(frozen.old.counter_identity.__globals__['ASSETS'] / n
                 for n in frozen.old.counter_identity.__globals__['EXPECTED'])
    files.update((base.parent / '__init__.py', base.parent / 'config.py', base / '__init__.py'))
    files.update((base / 'contracts').glob('*.json'))
    if (base / 'experiments/__init__.py').exists():
        files.add(base / 'experiments/__init__.py')
    return [{'path': relative(repo, p), 'sha256': sha(p)} for p in sorted(files)]


def _scope(w, source_store):
    cases = w['cases']
    require((len(cases), sum(len(c['scopes']) for c in cases),
        sum(len(s['evidence_ids']) for c in cases for s in c['scopes'])) == (3, 16, 58),
        'requires exact 3/16/58 union')
    require({c['case_id'] for c in cases} == {'011904', '045155', '099980'}, 'foreign cases')
    for case in cases:
        text = frozen.old.open_source(source_store, case['case_id'], case['source_hash'])
        require(len(text) == case['source_char_length'], 'source length changed')
        for ref in case['evidence_catalog'].values():
            require(ref['case_id'] == case['case_id'] and ref['source_hash'] == case['source_hash']
                and 0 <= ref['start_char'] <= ref['end_char'] <= len(text)
                and text[ref['start_char']:ref['end_char']] == ref['quote'], 'source span changed')


def _records(value):
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
            yield value
        for child in value.values():
            yield from _records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _records(child)


def _clean_tree(repo, root):
    for path in root.rglob('*'):
        resolve(repo, path.relative_to(repo).as_posix())


def export(bundle=DEFAULT_BUNDLE, repo_root=None, history_root=None, controls_root=None, refresh_derived=False):
    """Origin-only verification, then immutable raw-byte archive plus derived manifest."""
    repo = repository(repo_root)
    target = resolve(repo, bundle)
    previous = None
    if (target / 'manifest.json').exists():
        require(refresh_derived, 'export refuses completed bundle; explicit refresh-derived preserves old manifest')
        inspect(bundle, repo)
        previous = (target / 'manifest.json').read_bytes()
    _clean_tree(repo, target)
    require('outputs' not in Path(bundle).parts, 'handoff must be outside outputs')
    history = resolve(repo, history_root) if history_root else frozen.DEFAULT_ROOT
    controls = resolve(repo, controls_root) if controls_root else frozen.DEFAULT_CONTROLS
    wpath = history / 'input/workload.json'
    frozen.preflight(wpath)
    w = load(wpath)
    frozen.require_cpu(history)
    controls_sha = frozen.require_controls(controls, w)
    report = load(history / 'live/run.json')
    ledger = load(history / 'live/runtime_ledger.json')
    sealed(ledger, 'ledger_sha256')
    sealed_w = w['workload_sha256']
    require(ledger['binding']['workload_sha256'] == sealed_w
            and ledger['identity'] == fingerprint(ledger['binding']), 'historical ledger binding changed')
    adapter = v2runner._adapter()
    cfg = v2runner._config(frozen.runtime_config(w['identity']))
    adapter._reconcile(history / 'live', copy.deepcopy(ledger), cfg)
    states, pauses = adapter._replay(w, {**ledger, '_root': str(history / 'live')}, cfg)
    require(not pauses and all(s['finished'] for s in states.values())
        and report['status'] == 'complete' and report['workload_sha256'] == sealed_w,
        'requires completed historical basis')
    require(all(row['state'] == states[row['case_id']] for row in report['results']),
            'historical report state changed')
    pending = set()
    for root in (history, controls):
        _clean_tree(repo, root)
        pending.update(p for p in root.rglob('*') if p.is_file()
                       and p.suffix in ('.json', '.txt', '.md') and '__pycache__' not in p.parts)
    pending.update(Path(b['path']) for b in w['source_bindings'])
    archived = {}
    while pending:
        path = pending.pop()
        rel = relative(repo, path)
        if rel in archived:
            continue
        require(path.suffix in ('.json', '.txt', '.py', '.ps1', '.md') or path.name == 'lock',
                'unexpected archive file type')
        raw = path.read_bytes()
        dest = resolve(repo, bundle + '/archive/' + rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            require(dest.read_bytes() == raw, 'partial export bytes differ; preserve for inspection')
        else:
            with dest.open('xb') as handle:
                handle.write(raw)
        archived[rel] = {'path': relative(repo, dest), 'sha256': hashlib.sha256(raw).hexdigest()}
        if path.suffix == '.json':
            for b in _records(load(path)):
                dependency = Path(b['path'])
                # CaseSource logical text references (e.g. CASE.md) are not
                # repository file bindings. Their stored raw bytes are included
                # explicitly by the frozen source_bindings above.
                if not dependency.is_absolute():
                    continue
                require(sha(dependency) == b['sha256'], 'historical dependency digest changed')
                pending.add(dependency)
    manifest = {'version': VERSION, 'kind': 'derived_portable_basis',
        'archive': dict(sorted(archived.items())), 'code_bindings': production_bindings(repo),
        'history_root': bundle + '/archive/' + relative(repo, history),
        'controls_root': bundle + '/archive/' + relative(repo, controls),
        'source_store': bundle + '/archive/' + relative(repo, w['source_store']),
        'original_workload': bundle + '/archive/' + relative(repo, wpath),
        'cases_sha256': fingerprint(w['cases']), 'controls_report_sha256': controls_sha,
        'input_counter': frozen.counter_identity(),
        'origin_verification': {'platform': platform.platform(), 'python': sys.version,
            'executable': sys.executable, 'repository': str(repo), 'controls': 'verified_on_origin',
            'historical_run': 'completed_verified_on_origin'},
        'history_policy': 'archive_only_not_resumable_as_new_run', 'semantic_quality': 'not_assessed'}
    manifest['sha256'] = fingerprint(manifest)
    if previous is not None:
        saved = target / 'derived_history' / (hashlib.sha256(previous).hexdigest() + '.json')
        saved.parent.mkdir(exist_ok=True)
        if saved.exists():
            require(saved.read_bytes() == previous, 'derived history changed')
        else:
            with saved.open('xb') as handle:
                handle.write(previous)
    _atomic(target / 'manifest.json', manifest)
    return inspect(bundle, repo)


def _controls(repo, m, check_counter=True):
    """Offline stored-source/schema/receipt gate; never run old platform-bound preflight."""
    from ..kos_authoring_controls_v2 import controls as c
    root = resolve(repo, m['controls_root'])
    manifest = load(root / 'input/manifest.json')
    sealed(manifest)
    binding = load(root / 'live/binding.json')
    digest = fingerprint(binding)
    rows = manifest['jobs']
    require(len(rows) == 9 and fingerprint(rows) == manifest['workload_sha256'], 'controls workload changed')
    require(manifest['wire_version'] == c.WIRE_VERSION, 'controls wire changed')
    require(load(root / 'input/cpu_balanced.json') == c.cpu_bundle(rows), 'controls schema changed')
    controls_cli.require_cpu(root, 'balanced')
    require(binding['jobs'] == [dict(r, job_id=fingerprint(r['payload']),
        input_reservation=(c.token_budget.input_reservation(r['payload']) if check_counter
                           else r['validation_job']['input_reservation'])) for r in rows], 'controls jobs changed')
    results = []
    for row in binding['jobs']:
        jid = fingerprint(row['payload'])
        require(row['validation_job']['payload'] == row['payload'], 'controls validation payload changed')
        intent = load(root / 'live/intents' / (jid + '.json'))
        c.execution._verify_record(intent)
        require(intent['job_id'] == jid and intent['binding_sha256'] == digest,
                'controls intent binding changed')
        paths = sorted((root / 'live/receipts' / jid).glob('*.json'), key=lambda p: int(p.stem))
        require(bool(paths), 'controls receipt missing')
        for path in paths:
            receipt = load(path)
            c.execution._verify_record(receipt)
            require(receipt['job_id'] == jid and receipt['binding_sha256'] == digest
                and receipt['usage'] == c.execution._usage(receipt.get('raw_response')), 'controls receipt changed')
        result = controls_cli.evaluate_row(row, receipt)
        require(result['status'] == 'structural_control_pass' and result['protocol_valid'], 'controls row failed')
        results.append(result)
    persisted = load(root / 'recovered_report/report.json')
    sealed(persisted)
    require(persisted['sha256'] == m['controls_report_sha256'] and persisted['rows'] == results
        and persisted['unknown_usage_count'] == 0 and not persisted['budget_violation'], 'controls report changed')
    return manifest


def inspect(bundle=DEFAULT_BUNDLE, repo_root=None, check_runtime=False):
    repo = repository(repo_root)
    m = load(resolve(repo, bundle + '/manifest.json'))
    sealed(m)
    require(m['version'] == VERSION, 'unsupported portable version')
    for b in m['archive'].values():
        require(sha(resolve(repo, b['path'])) == b['sha256'], 'archive byte digest changed')
    w = load(resolve(repo, m['original_workload']))
    sealed(w, 'workload_sha256')
    require(fingerprint(w['cases']) == m['cases_sha256'], 'case union changed')
    _scope(w, resolve(repo, m['source_store']))
    controls = _controls(repo, m, check_counter=check_runtime)
    require(all(controls['identity'][k] == w['identity'][k]
        for k in ('model', 'url', 'expected_model_revision')), 'controls identity changed')
    if check_runtime:
        require(m['code_bindings'] == production_bindings(repo), 'production code/tokenizer assets changed')
        require(m['input_counter'] == frozen.counter_identity(), 'tokenizer/counter version changed')
    history = load(resolve(repo, m['history_root'] + '/live/run.json'))
    return {'status': 'pass', 'offline': True, 'network_requests': 0,
        'case_count': 3, 'scope_count': 16, 'part_count': 58,
        'history': history, 'history_policy': m['history_policy'],
        'runtime_gates_checked': check_runtime, 'semantic_quality': 'not_assessed'}


def _material(repo, bundle):
    inspect(bundle, repo, check_runtime=True)
    m = load(resolve(repo, bundle + '/manifest.json'))
    old = load(resolve(repo, m['original_workload']))
    w = {k: copy.deepcopy(v) for k, v in old.items() if k not in (
        'parent_root', 'parent_bindings', 'source_bindings', 'source_store', 'code_sha256', 'workload_sha256')}
    w.update(artifact_type='K0PortableWorkload', portable_version=VERSION,
        bundle=bundle, basis_sha256=m['sha256'], source_store=m['source_store'],
        parent_bindings=[{'path': bundle + '/manifest.json', 'sha256': sha(resolve(repo, bundle + '/manifest.json'))}],
        source_bindings=[b for b in m['archive'].values() if '/cases/' in b['path']],
        code_bindings=m['code_bindings'], code_sha256=fingerprint(m['code_bindings']),
        history_policy=m['history_policy'])
    w['workload_sha256'] = fingerprint(w)
    return w


def prepare(output_root=DEFAULT_RUN, bundle=DEFAULT_BUNDLE, repo_root=None):
    repo = repository(repo_root)
    root = resolve(repo, output_root)
    require(not root.exists(), 'prepare requires fresh run root')
    require('outputs' not in Path(output_root).parts, 'portable runs must be outside outputs')
    w = _material(repo, bundle)
    require(not root.is_relative_to(resolve(repo, bundle)) and not resolve(repo, bundle).is_relative_to(root),
            'run overlaps immutable bundle')
    cfg = v2runner._config(frozen.runtime_config(w['identity']))
    from ..k0_authoring_v2.tools import initial_state
    jobs = [frozen.build_job(w, c, initial_state(c), cfg) for c in w['cases']]
    _atomic(root / 'input/workload.json', w)
    _atomic(root / 'input/cpu_authoring.json', frozen.cpu_bundle(jobs))
    m = load(resolve(repo, bundle + '/manifest.json'))
    historical_cpu = resolve(repo, m['history_root'] + '/cpu_authoring.json')
    report = load(historical_cpu)
    if sha(root / 'input/cpu_authoring.json') == report['bundle_sha256']:
        # An identical grammar/example bundle can reuse the exact old CPU
        # evidence. Never claim this file is a newly executed diagnostic.
        with (root / 'cpu_authoring.json').open('xb') as handle:
            handle.write(historical_cpu.read_bytes())
        _atomic(root / 'input/cpu_provenance.json', {
            'kind': 'reused_byte_identical_historical_cpu_evidence',
            'new_cpu_execution': False, 'origin_report': relative(repo, historical_cpu),
            'origin_report_sha256': sha(historical_cpu),
            'bundle_sha256': report['bundle_sha256']})
    return {'status': 'prepared', 'network_requests': 0}


def preflight(output_root=DEFAULT_RUN, repo_root=None, cfg=None):
    repo = repository(repo_root)
    root = resolve(repo, output_root)
    _clean_tree(repo, root)
    w = load(root / 'input/workload.json')
    sealed(w, 'workload_sha256')
    require(w == _material(repo, w['bundle']), 'portable workload changed')
    frozen.profile(w, cfg or frozen.runtime_config(w['identity']))
    from ..k0_authoring_v2.tools import initial_state
    jobs = [frozen.build_job(w, c, initial_state(c), cfg or frozen.runtime_config(w['identity'])) for c in w['cases']]
    require(load(root / 'input/cpu_authoring.json') == frozen.cpu_bundle(jobs), 'CPU bundle changed')
    return {'status': 'pass', 'case_count': 3, 'scope_count': 16, 'part_count': 58,
            'network_executed': False, 'semantic_quality': 'not_assessed'}
