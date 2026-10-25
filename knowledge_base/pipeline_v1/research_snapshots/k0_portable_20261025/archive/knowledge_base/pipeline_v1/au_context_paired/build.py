"""Source-only sampling and immutable compact-AU paired inputs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ..region_priority_offline import core as source_core
from ..region_priority_variants import core as variants
from ..selective_context_offline.policy import expand_context, POLICY
from ..au_compact import core as compact, manifest as compact_manifest, runner as runtime, prompting, decoding
from ..source_contract import open_source

BASE = source_core.BASE
DEFAULT_SOURCE_STORE = BASE / 'outputs/source_store_v1'
DEFAULT_ATOM_ROOT = BASE / 'outputs/plan04_sentence_atoms_v1'
DEFAULT_ORDER = variants.DEFAULT_ROOT / 'order/revision02/report.json'
DEFAULT_SELECTIVE = BASE / 'outputs/selective_context_offline_20261013/main/revision01/report.json'
MODEL = 'Qwen/Qwen3.5-9B'
REVISION = 'c202236235762e1c871ad0ccb60c8ee5ba337b9a'
SEED = 'au-context-pilot-v1'
STRATA = ('legal_rule', 'application', 'reporting', 'qualification', 'no_citation', 'middle_tail_long')

class PairedError(ValueError):
    pass

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def binding(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

def verify_bindings(bindings):
    for item in bindings:
        if binding(item['path']) != item:
            raise PairedError('changed input/code binding: ' + item['path'])

def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')

def nonsecret_config(cfg):
    return {key: cfg.get(key) for key in ('model', 'url', 'enable_thinking', 'transport', 'string_decoder')}

def target_identity(request, catalog):
    return {'case_id': request['case_id'], 'source_hash': request['source_hash'],
            'target_id': request['expected_target_ids'][0],
            'target_refs': [r for r in request['source_refs'] if r['role'] == 'target'],
            'target_atoms': {aid: atom for aid, atom in catalog['atoms'].items() if atom['target_intersecting']}}

def make_request(row, atom_root=DEFAULT_ATOM_ROOT):
    rid = row['region_id']
    target_id = 'act-' + fingerprint([row['case_id'], row['source_hash'], row['target']])[:24]
    refs = [{'role': 'target', **row['target'], 'target_ids': [target_id]}]
    refs += [{'role': 'context', 'start_char': c['start_char'], 'end_char': c['end_char'], 'target_ids': []}
             for c in row['packet']['context']]
    request = {'case_id': row['case_id'], 'source_hash': row['source_hash'], 'region_id': rid,
               'arm': 'AU-only', 'expected_target_ids': [target_id],
               'source_refs': sorted(refs, key=lambda r: (r['start_char'], r['end_char'])),
               'spec': {'model': MODEL, 'enable_thinking': False, 'caps': {'targets': 1, 'output_tokens': 800, 'au_candidates': 3}},
               'request_id': 'acp-' + fingerprint([rid, refs, MODEL, prompting.prompt_identity()])[:24],
               'hint_payload': {'version': 'context-hint-payload-v1', 'hint_ids': []}}
    request['atom_binding'] = compact_manifest._binding_for(request, atom_root, read_json(Path(atom_root) / 'sentence_atom_build_manifest.json'))
    return request

def render_request(request, source_store=DEFAULT_SOURCE_STORE, atom_root=DEFAULT_ATOM_ROOT):
    source = open_source(source_store, request['case_id'], request['source_hash'])
    catalog = compact.build_evidence_catalog(request, compact_manifest._binding_path(request['atom_binding'], atom_root), source)
    rendered = runtime._render(request, catalog)
    prompt = prompting.build_prompt(request, rendered)
    constraint = decoding.build_decoding(request['request_id'], request['expected_target_ids'][0], list(catalog['atoms']),
                                        [aid for aid, atom in catalog['atoms'].items() if atom['target_intersecting']], string_mode='host_validated')
    return {'catalog': catalog, 'rendered': rendered, 'prompt': prompt, 'decoding': constraint,
            'prompt_sha256': fingerprint(prompt), 'decoding_sha256': fingerprint(constraint),
            'prompt_utf8_bytes': len(prompt.encode()), 'grammar_http_bytes': len(json.dumps(constraint).encode())}

def effective_identity(request, rendered):
    canonical = deepcopy(request)
    canonical['request_id'] = 'paired-canonical-request'
    return {'atoms': rendered['catalog']['atoms'], 'target': target_identity(canonical, rendered['catalog']),
            'prompt': prompting.build_prompt(canonical, runtime._render(canonical, rendered['catalog']))}

def strata_match(row, stratum):
    f, counts = row['features'], row['features']['counts']
    if stratum == 'legal_rule':
        return bool(f['lane_scores']['doctrine'])
    if stratum == 'application':
        return bool(f['lane_scores']['application'])
    if stratum == 'reporting':
        return bool(counts['reporting'] or counts['quote'] or counts['speaker_voice'])
    if stratum == 'qualification':
        return bool(counts['qualification'] or counts['rebuttal'])
    if stratum == 'no_citation':
        return not counts['citation']
    return row['position_stratum'] >= 2 or row['target_chars'] > 1500

def select_controls(rows, changed_ids, seed=SEED):
    selected = []
    for cid in sorted({r['case_id'] for r in rows}):
        candidates = sorted((r for r in rows if r['case_id'] == cid and r['region_id'] not in changed_ids),
                            key=lambda r: hashlib.sha256((seed + '|' + cid + '|' + r['region_id']).encode()).hexdigest())
        used = set()
        for stratum in STRATA:
            available = [r for r in candidates if r['region_id'] not in used]
            if not available:
                raise PairedError('insufficient distinct controls for case ' + cid)
            matched = [r for r in available if strata_match(r, stratum)]
            chosen = (matched or available)[0]
            selected.append((chosen['region_id'], stratum, not bool(matched)))
            used.add(chosen['region_id'])
    return selected

def code_bindings():
    paths = set(Path(__file__).parent.glob('*.py'))
    paths.update(Path(m.__file__) for m in (source_core, variants, compact, compact_manifest, runtime, prompting, decoding))
    paths.update([compact.COMPACT_SCHEMA, compact.FULL_SCHEMA])
    return [binding(p) for p in sorted(paths)]

def build(output_root, *, cfg, source_store=DEFAULT_SOURCE_STORE, atom_root=DEFAULT_ATOM_ROOT,
          order_report=DEFAULT_ORDER, selective_report=DEFAULT_SELECTIVE, seed=SEED):
    if cfg['model'] != MODEL or cfg.get('enable_thinking') is not False:
        raise PairedError('study requires pinned Qwen3.5-9B, non-thinking')
    if cfg.get('transport') != 'jobs' or cfg.get('string_decoder') != 'host_validated':
        raise PairedError('study requires jobs and host_validated EBNF')
    root = Path(output_root).resolve()
    protected = [Path(order_report).parent, Path(selective_report).parent, Path(source_store), Path(atom_root), Path(__file__).parent]
    if any(root == p.resolve() or root in p.resolve().parents or p.resolve() in root.parents for p in protected):
        raise PairedError('output overlaps protected inputs')
    if root.exists() and any(root.iterdir()):
        raise PairedError('nonempty build output; overwrite refused')
    inventory = source_core.build_inventory(source_store=source_store, atom_manifest=Path(atom_root) / 'sentence_atom_build_manifest.json')
    order = read_json(order_report)
    lock = variants._freeze(inventory, order['lock']['full_ordered_ids'], variants.DEFAULT_BASELINE / 'report.json')
    variants.verify_order_report(order_report, inventory, lock)
    selective = expand_context(inventory)
    sr, sf = read_json(selective_report), read_json(Path(selective_report).parent / 'frozen_snapshot.json')
    if sr['protocol_status'] != 'pass' or sr['frozen_snapshot_sha256'] != fingerprint(sf):
        raise PairedError('selective snapshot mismatch')
    verify_bindings(sf['implementation_fingerprints'] + sf['report_bindings'])
    if read_json(Path(selective_report).parent / 'inventory.json') != {k: v for k, v in selective.items() if k != 'sources'}:
        raise PairedError('selective source/policy inventory mismatch')
    audit, prepared = [], {}
    for g, s in zip(inventory['regions'], selective['regions']):
        pair = {}
        for arm, row in (('G', g), ('S', s)):
            req = make_request(row, atom_root)
            rendered = render_request(req, source_store, atom_root)
            req['input_tokens'] = rendered['prompt_utf8_bytes']
            pair[arm] = (req, rendered)
        if target_identity(pair['G'][0], pair['G'][1]['catalog']) != target_identity(pair['S'][0], pair['S'][1]['catalog']):
            raise PairedError('context changed TARGET ownership')
        raw_delta = g['packet'] != s['packet']
        effective_delta = effective_identity(*pair['G']) != effective_identity(*pair['S'])
        audit.append({'region_id': g['region_id'], 'case_id': g['case_id'], 'raw_delta': raw_delta,
                      'catalog_delta': pair['G'][1]['catalog']['atoms'] != pair['S'][1]['catalog']['atoms'],
                      'effective_delta': effective_delta, 'effective_context_noop': raw_delta and not effective_delta,
                      'target_identity_sha256': fingerprint(target_identity(pair['G'][0], pair['G'][1]['catalog']))})
        prepared[g['region_id']] = pair
    changed_ids = {a['region_id'] for a in audit if a['effective_delta']}
    if len(changed_ids) > 2:
        raise PairedError('effective intervention count exceeds locked pilot; investigate without truncation')
    controls = select_controls(inventory['regions'], changed_ids, seed) if changed_ids else []
    selected = [(rid, 'changed_context', False) for rid in sorted(changed_ids)] + controls
    by_id = {r['region_id']: r for r in inventory['regions']}
    requests, pairs, rendered_inputs = {}, [], {}
    for rid, stratum, fallback in selected:
        row, p = by_id[rid], prepared[rid]
        effective = rid in changed_ids
        pair_id = 'acpair-' + fingerprint([seed, rid])[:24]
        request_ids = {}
        for arm in ('G', 'S'):
            req, rendered = p[arm] if effective else p['G']
            request_ids[arm] = req['request_id']
            requests[req['request_id']] = req
            rendered_inputs[req['request_id']] = {k: rendered[k] for k in ('rendered', 'prompt', 'decoding', 'prompt_sha256', 'decoding_sha256', 'prompt_utf8_bytes', 'grammar_http_bytes')}
        pairs.append({'pair_id': pair_id, 'region_id': rid, 'case_id': row['case_id'], 'source_hash': row['source_hash'],
                      'target_id': p['G'][0]['expected_target_ids'][0], 'target': row['target'],
                      'request_ids': request_ids, 'effective_delta': effective, 'shared_identical_input': not effective,
                      'known_gap': effective, 'control_stratum': stratum, 'stratum_fallback': fallback})
    # Alternate first arm across the changed pairs; hashing assigns the first.
    changed_order = sorted((p for p in pairs if p['effective_delta']), key=lambda p: fingerprint([seed, p['pair_id']]))
    changed_rank = {p['pair_id']: i for i, p in enumerate(changed_order)}
    execution = []
    for p in sorted(pairs, key=lambda p: fingerprint([seed, 'execution', p['pair_id']])):
        arms = ('G', 'S') if changed_rank.get(p['pair_id'], 0) % 2 == 0 else ('S', 'G')
        for arm in arms:
            if p['request_ids'][arm] not in execution:
                execution.append(p['request_ids'][arm])
    first_changed = changed_order[0] if changed_order else None
    smoke = list(dict.fromkeys(first_changed['request_ids'].values())) if first_changed else []
    smoke += [p['request_ids']['G'] for p in pairs if not p['effective_delta']][:2]
    paths = [order_report, selective_report, Path(order_report).parent / 'inventory.json', Path(selective_report).parent / 'inventory.json']
    bindings = ([binding(p) for p in paths] + inventory['input_bindings'] + inventory['artifact_bindings']
                + sf['implementation_fingerprints'] + code_bindings())
    workload = {'artifact_type': 'AUContextPairedWorkload', 'version': 'au-context-paired-v1',
                'evaluation_split': 'development/calibration; not heldout', 'semantic_gold': False,
                'seed': seed, 'identity': {**nonsecret_config(cfg), 'expected_model_revision': REVISION,
                                         'prompt_identity': prompting.prompt_identity(), 'selective_policy_sha256': fingerprint(POLICY)},
                'bindings': bindings, 'source_store': str(Path(source_store).resolve()), 'atom_root': str(Path(atom_root).resolve()),
                'inventory_paths': {'G': str((Path(order_report).parent / 'inventory.json').resolve()),
                                    'S': str((Path(selective_report).parent / 'inventory.json').resolve())},
                'inventory_audit_sha256': fingerprint(audit), 'pairs': pairs, 'smoke_request_ids': smoke,
                'manifest': {'artifact_type': 'AUCompactLockedManifest', 'schema_version': 'au-compact-manifest-v1',
                             'requests': [requests[rid] for rid in execution]},
                'rendered_fingerprints': {rid: {'prompt_sha256': v['prompt_sha256'], 'decoding_sha256': v['decoding_sha256']} for rid, v in rendered_inputs.items()},
                'status': 'ready' if changed_ids else 'no_effective_intervention'}
    workload['workload_sha256'] = fingerprint(workload)
    write_new(root / 'workload.json', workload)
    write_new(root / 'inventory_audit.json', audit)
    write_new(root / 'config_nonsecret.json', workload['identity'])
    for rid, value in rendered_inputs.items():
        write_new(root / 'rendered_inputs' / (rid + '.json'), value)
    write_new(root / 'execution_plan.json', {'workload_sha256': workload['workload_sha256'],
               'physical_request_count': len(requests), 'logical_count': len(pairs)*2,
               'smoke_request_ids': smoke, 'order': execution, 'expected_model_revision': REVISION,
               'endpoint_revision_verification': 'pending_remote_or_operator_evidence',
               'actual_network_requests': 0, 'max_provider_post_attempts': 100})
    return workload
