"""Validate immutable paired source/render bindings without network access."""
from copy import deepcopy
from pathlib import Path
from .build import (PairedError, MODEL, fingerprint, verify_bindings, read_json,
                    render_request, target_identity, effective_identity, nonsecret_config, DEFAULT_ORDER, DEFAULT_SELECTIVE)

def validate_workload(workload, source_store=None, atom_root=None, cfg=None):
    value = deepcopy(workload)
    digest = value.pop('workload_sha256', None)
    if digest != fingerprint(value):
        raise PairedError('workload identity hash mismatch')
    if value.get('artifact_type') != 'AUContextPairedWorkload' or value.get('version') != 'au-context-paired-v1':
        raise PairedError('unknown paired workload version')
    verify_bindings(value['bindings'])
    if cfg is not None and nonsecret_config(cfg) != {key: value['identity'].get(key) for key in nonsecret_config(cfg)}:
        raise PairedError('model/endpoint/decoder identity mismatch')
    store = Path(source_store or value['source_store']).resolve()
    atoms = Path(atom_root or value['atom_root']).resolve()
    if str(store) != value['source_store'] or str(atoms) != value['atom_root']:
        raise PairedError('source or atom root mismatch')
    requests = value['manifest']['requests']
    if len(requests) > 34 or len({r['request_id'] for r in requests}) != len(requests):
        raise PairedError('physical request cap/identity invalid')
    if value['manifest']['artifact_type'] != 'AUCompactLockedManifest' or value['manifest']['schema_version'] != 'au-compact-manifest-v1':
        raise PairedError('compact manifest identity invalid')
    catalogs, rendered = {}, {}
    inventory_paths = value['inventory_paths']
    for path in inventory_paths.values():
        if str(Path(path).resolve()) not in {b['path'] for b in value['bindings']}:
            raise PairedError('inventory path is not source-bound')
    baseline = {r['region_id']: r for r in read_json(inventory_paths['G'])['regions']}
    selective = {r['region_id']: r for r in read_json(inventory_paths['S'])['regions']}
    for r in requests:
        if r['spec']['model'] != MODEL or r['spec']['enable_thinking'] is not False or r['spec']['caps']['output_tokens'] != 800:
            raise PairedError('fixed model/thinking/output cap changed')
        v = render_request(r, store, atoms)
        if r['input_tokens'] != v['prompt_utf8_bytes']:
            raise PairedError('prompt reservation mismatch')
        f = value['rendered_fingerprints'].get(r['request_id'])
        if f != {'prompt_sha256': v['prompt_sha256'], 'decoding_sha256': v['decoding_sha256']}:
            raise PairedError('render/catalog/decoding fingerprint mismatch')
        catalogs[r['request_id']], rendered[r['request_id']] = v['catalog'], v
    by_id = {r['request_id']: r for r in requests}
    represented, pair_ids, target_ids = set(), set(), set()
    controls = {}
    changed = 0
    for p in value['pairs']:
        if p['pair_id'] in pair_ids or p['target_id'] in target_ids:
            raise PairedError('duplicate pair/target')
        pair_ids.add(p['pair_id']); target_ids.add(p['target_id'])
        if set(p['request_ids']) != {'G', 'S'}:
            raise PairedError('pair requires exactly G and S')
        g, s = (by_id[p['request_ids'][arm]] for arm in ('G', 'S'))
        represented.update(p['request_ids'].values())
        for arm, r in (('G', g), ('S', s)):
            if r['case_id'] != p['case_id'] or r['source_hash'] != p['source_hash'] or r['expected_target_ids'] != [p['target_id']]:
                raise PairedError('physical/logical target ownership mismatch')
            reference = baseline[p['region_id']] if arm == 'G' or not p['effective_delta'] else selective[p['region_id']]
            allowed_target = [x for x in r['source_refs'] if x['role'] == 'target']
            if len(allowed_target) != 1 or any(allowed_target[0].get(k) != p['target'].get(k) for k in ('start_char', 'end_char', 'case_id', 'source_hash')) or p['target'] != reference['target']:
                raise PairedError('TARGET source spans changed')
            actual = [(x['start_char'], x['end_char']) for x in r['source_refs'] if x['role'] == 'context']
            expected = sorted((x['start_char'], x['end_char']) for x in reference['packet']['context'])
            if actual != expected:
                raise PairedError('context refs differ from frozen policy')
        if target_identity(g, catalogs[g['request_id']]) != target_identity(s, catalogs[s['request_id']]):
            raise PairedError('pair TARGET atom/text mismatch')
        delta = effective_identity(g, rendered[g['request_id']]) != effective_identity(s, rendered[s['request_id']])
        if delta != p['effective_delta'] or p['shared_identical_input'] == delta:
            raise PairedError('effective input/shared mapping mismatch')
        if not delta and g['request_id'] != s['request_id']:
            raise PairedError('no-op control must share one physical request')
        if delta and g['request_id'] == s['request_id']:
            raise PairedError('changed pair cannot share response')
        if delta:
            changed += 1
        else:
            controls[p['case_id']] = controls.get(p['case_id'], 0) + 1
    if represented != set(by_id):
        raise PairedError('orphan physical request')
    if value['status'] == 'ready' and (changed not in (1, 2) or controls != {cid: 6 for cid in ('013009', '013948', '011904', '045155', '099980')}):
        raise PairedError('pilot composition changed')
    if not set(value['smoke_request_ids']).issubset(by_id):
        raise PairedError('smoke request not in locked workload')
    return workload

def preflight(workload, *, cfg=None, budget=None, source_store=None, atom_root=None):
    failures = []
    try:
        validate_workload(workload, source_store, atom_root, cfg)
    except (ValueError, KeyError, OSError) as exc:
        failures.append(str(exc))
    requests = workload.get('manifest', {}).get('requests', [])
    required = {'max_requests': len(requests), 'max_provider_attempts': 100,
                'max_total_input_tokens': sum(r.get('input_tokens', 0) for r in requests),
                'max_total_output_tokens': sum(r.get('spec', {}).get('caps', {}).get('output_tokens', 0) for r in requests)}
    if workload.get('status') != 'ready':
        failures.append('no_effective_intervention')
    if budget:
        for k in required:
            if type(budget.get(k)) is not int or budget[k] < required[k]:
                failures.append(k + '_below_required')
    return {'artifact_type': 'AUContextPairedPreflight', 'status': 'pass' if not failures else 'fail',
            'workload_sha256': workload.get('workload_sha256'), 'physical_request_count': len(requests),
            'required_caps': required, 'configured_caps': budget,
            'input_reservation_method': 'full_prompt_utf8_bytes; conservative reservation, NOT provider tokens',
            'source_only_http_grammar_bytes_are_not_model_tokens': True,
            'endpoint_revision_verification': 'pending_remote_or_operator_evidence',
            'failures': failures, 'network_requests': 0, 'semantic_quality': 'not_assessed'}
