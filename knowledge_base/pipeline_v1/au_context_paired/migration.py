"""Explicit, source/payload-preserving adoption into a new recovery checkpoint."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import shutil

from .build import (PairedError, read_json, binding, fingerprint, write_new,
                    code_bindings, nonsecret_config, render_request)
from .preflight import validate_workload
from .review import validate_checklist
from ..au_compact import runner as compact

ARCHIVE = Path(__file__).resolve().parents[1] / 'outputs/au_context_paired/recovery_20261014/original_runtime'
ALLOWED_CHANGED = {'runner.py', '__main__.py'}

def _config_keys(path):
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CONFIG_KEYS' for t in node.targets):
            return ast.literal_eval(node.value)
    raise PairedError('archived CONFIG_KEYS missing')

def migrate(old_workload_path, old_live, old_reference_path, output_root, *, cfg, archive_root=ARCHIVE):
    """Never update old files or reset requests, usage, attempts or reservations."""
    old_live, root, archive = Path(old_live).resolve(), Path(output_root).resolve(), Path(archive_root).resolve()
    repo = Path(__file__).resolve().parents[3]
    if not root.is_relative_to(repo):
        raise PairedError('migration output must stay inside repository')
    if root == old_live or root.is_relative_to(old_live) or old_live.is_relative_to(root):
        raise PairedError('migration output overlaps old checkpoint')
    if (old_live / '.runner.lock').exists():
        raise PairedError('old runner lock exists; migration refused while run may be active')
    if root.exists() and any(root.iterdir()):
        raise PairedError('nonempty migration output; overwrite refused')
    old = read_json(old_workload_path)
    payload = deepcopy(old); claimed = payload.pop('workload_sha256', None)
    if claimed != fingerprint(payload):
        raise PairedError('old workload digest mismatch')
    if nonsecret_config(cfg) != {k: old['identity'].get(k) for k in nonsecret_config(cfg)}:
        raise PairedError('runtime model/endpoint identity changed')
    module = Path(__file__).resolve().parent
    for b in old['bindings']:
        path = Path(b['path'])
        if binding(path) == b:
            continue
        if path.parent.resolve() != module or path.name not in ALLOWED_CHANGED:
            raise PairedError('migration refuses non-transport binding change: ' + str(path))
        archived = archive / path.name
        if not archived.is_file() or hashlib.sha256(archived.read_bytes()).hexdigest() != b['sha256']:
            raise PairedError('archived runtime does not prove original code identity')
    for request in old['manifest']['requests']:
        rendered = render_request(request, old['source_store'], old['atom_root'])
        if old['rendered_fingerprints'][request['request_id']] != {
                'prompt_sha256': rendered['prompt_sha256'], 'decoding_sha256': rendered['decoding_sha256']}:
            raise PairedError('migration changed extraction prompt/catalog/grammar')
    ledger = read_json(old_live / 'runtime_ledger.json')
    old_runner = archive / 'runner.py'
    historical_identity = compact._hash({'workload': old, 'config': {k: cfg.get(k) for k in _config_keys(old_runner)},
                                        'runner_sha256': hashlib.sha256(old_runner.read_bytes()).hexdigest()})
    if ledger.get('identity') != historical_identity or ledger.get('workload_sha256') != claimed:
        raise PairedError('old runtime/config identity mismatch')
    old_reference = read_json(old_reference_path)
    validate_checklist(old_reference, old, require_locked=True)
    snapshots = {str(p.relative_to(old_live)): binding(p) for p in old_live.rglob('*') if p.is_file()}
    new = deepcopy(old)
    new_bindings = {b['path']: binding(b['path']) for b in old['bindings']}
    new_bindings.update({b['path']: b for b in code_bindings()})
    new['bindings'] = [new_bindings[k] for k in sorted(new_bindings)]
    new['migration'] = {'version': 'paired-transport-recovery-v1', 'parent_workload_sha256': claimed,
                        'parent_workload_path': str(Path(old_workload_path).resolve()),
                        'parent_live': str(old_live), 'manifest_and_rendered_inputs_unchanged': True}
    new.pop('workload_sha256', None)
    new['workload_sha256'] = fingerprint(new)
    validate_workload(new, cfg=cfg)
    from .runner import runtime_identity
    identity = runtime_identity(new, cfg)
    requests = {r['request_id']: r for r in old['manifest']['requests']}
    migrated_rows = {}
    for rid, key in ledger['terminal'].items():
        if rid not in requests or key != compact._key(requests[rid], historical_identity, cfg):
            raise PairedError('old terminal receipt key mismatch')
        path = old_live / 'receipts' / (key + '.json')
        row = read_json(path)
        expected_hash = compact._hash({k: v for k, v in row.items() if k != 'row_sha256'})
        if row.get('row_sha256') != expected_hash or row.get('request') != requests[rid] or row.get('status') != 'protocol_verified':
            raise PairedError('old terminal receipt content/status mismatch')
        adopted = deepcopy(row)
        adopted['cache_key'] = compact._key(requests[rid], identity, cfg)
        adopted['migration_provenance'] = {'original_receipt': binding(path), 'original_row_sha256': expected_hash,
                                         'parent_workload_sha256': claimed}
        adopted.pop('row_sha256', None)
        adopted['row_sha256'] = compact._hash(adopted)
        migrated_rows[rid] = adopted
    for rid, reservation in ledger['reservations'].items():
        if rid not in requests or reservation.get('cache_key') != compact._key(requests[rid], historical_identity, cfg):
            raise PairedError('old reservation identity mismatch')
    if ledger['requests'] != len(ledger['reservations']) or ledger['provider_attempts'] != len(ledger['attempts']):
        raise PairedError('old persistent accounting inconsistent')
    for attempt in ledger['attempts']:
        path = old_live / 'attempt_receipts' / (f"{attempt['ordinal']:03d}.json")
        if path.exists() and read_json(path) != attempt:
            raise PairedError('old attempt receipt and ledger disagree')
    gate = read_json(old_live / 'smoke_gate.json')
    if gate != {'identity': historical_identity, 'request_ids': old['smoke_request_ids'], 'status': 'pass',
                'receipt_sha256': [read_json(old_live / 'receipts' / (ledger['terminal'][rid] + '.json'))['row_sha256'] for rid in old['smoke_request_ids']]}:
        raise PairedError('old smoke gate did not verify matching receipts')
    # A separate destination preserves the historical snapshot byte-for-byte.
    live = root / 'live'
    root.mkdir(parents=True, exist_ok=True)
    live.mkdir()
    for name in ('attempt_receipts', 'pending_receipts', 'probe_receipts', 'warmup'):
        if (old_live / name).exists():
            shutil.copytree(old_live / name, live / name)
    new_ledger = deepcopy(ledger)
    new_ledger.update(identity=identity, workload_sha256=new['workload_sha256'])
    new_ledger['migration'] = {'source_ledger': binding(old_live / 'runtime_ledger.json'), 'parent_identity': historical_identity}
    for rid, row in migrated_rows.items():
        new_ledger['terminal'][rid] = row['cache_key']
        write_new(live / 'receipts' / (row['cache_key'] + '.json'), row)
    for rid, reservation in new_ledger['reservations'].items():
        reservation['cache_key'] = compact._key(requests[rid], identity, cfg)
    write_new(live / 'runtime_ledger.json', new_ledger)
    write_new(live / 'smoke_gate.json', {'identity': identity, 'request_ids': new['smoke_request_ids'], 'status': 'pass',
                                      'receipt_sha256': [migrated_rows[rid]['row_sha256'] for rid in new['smoke_request_ids']]})
    reference = deepcopy(old_reference)
    reference['workload_sha256'] = new['workload_sha256']
    reference['migration_reference_parent'] = binding(old_reference_path)
    reference.pop('reference_checklist_sha256', None)
    reference['reference_checklist_sha256'] = fingerprint(reference)
    validate_checklist(reference, new, require_locked=True)
    write_new(root / 'workload.json', new)
    write_new(root / 'reference_checklist.json', reference)
    preserved = {name: binding(old_live / name) == before for name, before in snapshots.items()}
    if not all(preserved.values()):
        raise PairedError('old checkpoint changed during migration')
    report = {'status': 'complete', 'old_workload_sha256': claimed, 'new_workload_sha256': new['workload_sha256'],
              'old_identity': historical_identity, 'new_identity': identity, 'copied_receipts': len(migrated_rows),
              'counters_preserved': {k: ledger[k] for k in ('requests', 'provider_attempts', 'warmup_attempts', 'probe_attempts', 'reserved_input_tokens', 'reserved_output_tokens')},
              'old_checkpoint_preservation': preserved, 'payloads_unchanged': old['manifest'] == new['manifest'],
              'rendered_inputs_unchanged': old['rendered_fingerprints'] == new['rendered_fingerprints'],
              'network_requests': 0, 'semantic_quality': 'not_assessed'}
    write_new(root / 'migration_manifest.json', report)
    return report
