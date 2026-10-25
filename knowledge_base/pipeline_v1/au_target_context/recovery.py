"""Offline, source-validated migration of stopped KOS calibration checkpoints.

Only EBNF may differ between a cached job and its new counterpart. Imported
responses are revalidated, never presented as generations under the new grammar.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile

from . import core, kos_aligned as kos
from .contracts import BUDGET
from ..au_context_paired.build import binding, fingerprint, write_new
from ..au_presentation_paired.core import profile


def _digest(value, key):
    core.require(value.get(key) == fingerprint({k: v for k, v in value.items() if k != key}),
                 'recovery input digest mismatch')


def _snapshot(root):
    core.require(not any(p.is_symlink() for p in root.rglob('*')), 'recovery input symlink prohibited')
    return [binding(p) for p in sorted(root.rglob('*')) if p.is_file()]


def _raw(receipt, job):
    body = receipt['raw_response']
    core.require(body.get('model') == job['payload']['model'], 'imported response model mismatch')
    choice = body['choices'][0]
    core.require(choice.get('finish_reason') == 'stop', 'cannot import incomplete generation')
    def pairs(items):
        core.require(len(dict(items)) == len(items), 'duplicate imported JSON keys')
        return dict(items)
    value = json.loads(choice['message']['content'], object_pairs_hook=pairs)
    core.require(value == receipt['model_output'], 'imported model output mismatch')
    return value


def _same_job(old, new):
    """Strict semantic identity: only decoding grammar and its digest may change."""
    for job in (old, new):
        core.require(job['payload_sha256'] == fingerprint(job['payload']), 'job payload digest mismatch')
    a, b = copy.deepcopy(old), copy.deepcopy(new)
    for job in (a, b):
        job.pop('payload_sha256')
        job['payload'].pop('ebnf')
    core.require(a == b, 'recovery changed source/prompt/model/job semantics')


def _cfg_from_binding(workload, bound):
    cfg = kos._cfg(workload['parent_workload'])
    runtime = bound['run_profile']
    cfg.update({k: runtime[k] for k in ('timeout', 'job_wait_seconds', 'job_poll_seconds')})
    if runtime['runtime_revision_setting_present']:
        cfg['expected_model_revision'] = runtime['expected_model_revision']
    else:
        cfg.pop('expected_model_revision', None)
    return cfg


def recover(old_root, output_root, *, cfg=None):
    """Create a new bound workload and seeded ledger without contacting a provider."""
    old_root, root = Path(old_root).resolve(), Path(output_root).resolve()
    old_input, old_live = old_root / 'input', old_root / 'live'
    core.require(old_root.is_dir() and not (old_live / '.runner.lock').exists(), 'old runner must be stopped')
    core.require(not root.exists(), 'recovery output must be new')
    old = core.load(old_input / 'workload.json')
    core.guard_output(root, [old_root, old['source_store'], old['atom_root'], old['kos_root'],
                             core.DEFAULT_PARENT.parent, core.DEFAULT_MANIFEST.parent])
    before = _snapshot(old_root)
    _digest(old, 'workload_sha256')
    core.require(old['artifact_type'] == kos.ARTIFACT, 'recovery supports only KOS-aligned calibration')
    reference = core.load(old['reference_checklist_path'])
    _digest(reference, 'reference_sha256')
    core.require(old['reference_checklist_sha256'] == reference['reference_sha256'], 'old reference binding mismatch')
    ledger = core.load(old_live / 'runtime_ledger.json')
    _digest(ledger, 'ledger_sha256')
    bound = ledger['binding']
    core.require(ledger['identity'] == fingerprint(bound), 'old runtime binding mismatch')
    core.require(bound['workload_sha256'] == old['workload_sha256'] and bound['code_sha256'] == old['code_sha256']
                 and bound['prompt_profile'] == old['prompt_profile'] and bound['prompt_sha'] == old['prompt_sha']
                 and bound['budget'] == old['budget'] == BUDGET, 'old workload/runtime mismatch')
    core.require(bound['mode'] in ('execute', 'mock') and type(bound['concurrency']) is int
                 and 1 <= bound['concurrency'] <= 4, 'invalid old mode/concurrency')
    core.require(not ledger.get('recovery_prior_accounting'), 'nested recovery requires explicit review')
    cfg = copy.deepcopy(cfg) if cfg is not None else _cfg_from_binding(old, bound)
    runtime = profile(old['parent_workload'], cfg)
    core.require(runtime == bound['run_profile'], 'recovery runtime settings changed')
    ids = bound['selected_target_ids']
    core.require(bool(ids) and len(ids) == len(set(ids)) and set(ids) <= {r['target_id'] for r in old['rows']},
                 'invalid old TARGET selection')
    core.require(ledger['provider_attempts'] == len(ledger['attempts']) <= BUDGET['max_provider_attempts'],
                 'old attempt counter mismatch')
    for field, cap in (('reserved_input_tokens', 'max_total_input_tokens'), ('reserved_output_tokens', 'max_total_output_tokens')):
        core.require(ledger[field] == sum(a[field] for a in ledger['attempts']) <= BUDGET[cap], 'old reservation mismatch')
    # Prepare in private temporary storage: a rejected import must not leave an
    # executable partial destination behind.
    with tempfile.TemporaryDirectory(prefix='au-kos-recovery-') as scratch:
        new = kos.prepare(Path(scratch) / 'input', kos_root=old['kos_root'],
                          selected_kos_manifest=old['selected_kos_manifest'], source_store=old['source_store'],
                          atom_root=old['atom_root'], parent=old['parent_workload'], cfg=cfg)
        ignored = {'workload_sha256', 'code_sha256', 'reference_checklist_path'}
        core.require({k:v for k,v in old.items() if k not in ignored} ==
                     {k:v for k,v in new.items() if k not in ignored}, 'recovery workload/source changed')
        core.require(core.load(new['reference_checklist_path']) == reference, 'rebuilt reference changed')
        new['reference_checklist_path'] = str(root / 'input/reference_checklist.json')
        new['workload_sha256'] = fingerprint({k:v for k,v in new.items() if k != 'workload_sha256'})
        allowed, verified_stage1, receipts, imported, retry, requeued = {}, {}, {}, {}, [], []
        # Validate all stage1 evidence first so stage2 is rebuilt from trusted refs.
        for row in new['rows']:
            if row['target_id'] not in ids:
                continue
            job = core.build_stage1(row, new['identity'])
            allowed[job['request_id']] = job
            entry = ledger['jobs'].get(job['request_id'])
            if entry and entry['status'] == 'verified':
                _same_job(entry['job'], job)
                receipt = core.load(old_live / 'receipts' / (job['request_id'] + '.json'))
                _digest(receipt, 'receipt_sha256')
                value = _raw(receipt, job)
                normalized = core.validate_stage1(value, job)
                core.require(normalized == receipt['normalized'], 'stage1 normalized evidence changed')
                verified_stage1[row['target_id']] = normalized
                for extra in core.build_stage2(row, normalized, new['identity']):
                    allowed[extra['request_id']] = extra
        core.require(set(ledger['jobs']) <= set(allowed), 'foreign old jobs')
        known = {e['job']['payload_sha256'] for e in ledger['jobs'].values()}
        for ordinal, attempt in enumerate(ledger['attempts'], 1):
            core.require(attempt['ordinal'] == ordinal and attempt['job_id'] == attempt['payload_sha256']
                         and attempt['job_id'] in known, 'foreign old attempt')
            path = old_live / 'attempt_receipts' / f'{ordinal:03d}.json'
            core.require(path.is_file() and core.load(path) == attempt, 'old attempt receipt mismatch')
            core.require(sum(a['job_id'] == attempt['job_id'] for a in ledger['attempts']) <= 2,
                         'old retry cap exceeded')
        for rid, entry in ledger['jobs'].items():
            job = allowed[rid]
            _same_job(entry['job'], job)
            old_jid = entry['job']['payload_sha256']
            attempts = [a for a in ledger['attempts'] if a['job_id'] == old_jid]
            receipt_path = old_live / 'receipts' / (rid + '.json')
            receipt = core.load(receipt_path) if receipt_path.is_file() else None
            if receipt is not None:
                _digest(receipt, 'receipt_sha256')
                core.require(entry.get('receipt_sha256') == receipt['receipt_sha256']
                             and receipt['request_id'] == rid and receipt['payload_sha256'] == old_jid
                             and receipt['status'] == entry['status'], 'old receipt/ledger binding mismatch')
                receipts[rid] = receipt
            if entry['status'] == 'verified':
                core.require(receipt is not None, 'verified receipt missing')
                value = _raw(receipt, job)
                validate = core.validate_stage1 if job['stage'] == 1 else core.validate_stage2
                normalized = validate(value, job)
                core.require(normalized == receipt['normalized'], 'imported normalized evidence changed')
                imported[rid] = (job, receipt, normalized, binding(receipt_path))
            elif entry['status'] in ('pending', 'reserved'):
                core.require(not attempts and old_jid not in ledger.get('observed_jobs', {}),
                             'pending job may have executed; retrieve before recovery')
                core.require(receipt is None or receipt.get('raw_response') is None, 'pending generation requires review')
                requeued.append({'request_id': rid, 'target_id': job['target_id'], 'reason': 'no_POST_attempt',
                                 'old_receipt': binding(receipt_path) if receipt is not None else None})
            elif entry['status'] == 'invalid':
                core.require(job['stage'] == 2 and receipt is not None and len(attempts) == 1
                             and old_jid != job['payload_sha256'], 'invalid retry requires changed stage2 grammar')
                value = _raw(receipt, job)
                try:
                    core.validate_stage2(value, job)
                except core.TargetContextError as exc:
                    core.require(str(exc) in ('complete with unresolved/no anchors', 'global unresolved must reflect anchor status'),
                                 'invalid output not covered by grammar fix')
                else:
                    raise core.TargetContextError('invalid output unexpectedly validates')
                retry.append({'request_id': rid, 'target_id': job['target_id'], 'old_payload_sha256': old_jid,
                              'new_payload_sha256': job['payload_sha256'], 'old_receipt': binding(receipt_path),
                              'reason': 'stage2_global_anchor_decision_grammar_fix'})
            else:
                raise core.TargetContextError('old failed/unknown job requires explicit recovery review')
        core.require(before == _snapshot(old_root) and not (old_live / '.runner.lock').exists(),
                     'old checkpoint changed during recovery')
        usage = [r['usage'] for r in receipts.values() if r.get('usage') is not None]
        prior = {'provider_attempts': ledger['provider_attempts'],
                 'reserved_input_tokens': ledger['reserved_input_tokens'],
                 'reserved_output_tokens': ledger['reserved_output_tokens'],
                 'known_provider_usage': {k: sum(u.get(k, 0) for u in usage) for k in ('input_tokens','output_tokens','total_tokens')},
                 'unknown_usage_jobs': sum(r.get('usage') is None for r in receipts.values()),
                 'GET_polls': ledger['get_polls'], 'usage_is_complete': False,
                 'note': 'Prior run includes invalid generation; current imported receipts are cache, not new generation.'}
        manifest = {'artifact_type': 'AUKOSSelectiveRecovery', 'version': 1, 'network_requests': 0,
                    'old_root': str(old_root), 'old_workload_sha256': old['workload_sha256'],
                    'new_workload_sha256': new['workload_sha256'], 'old_files': before,
                    'imported_verified_count': len(imported), 'requeued': requeued, 'retry_invalid': retry,
                    'prior_accounting': copy.deepcopy(prior), 'semantic_quality': 'not_assessed',
                    'import_policy': 'current host validation; exact job equality except EBNF; old generation provenance retained'}
        manifest['recovery_sha256'] = fingerprint(manifest)
        prior.update(manifest_path=str(root / 'recovery_manifest.json'), manifest_sha256=manifest['recovery_sha256'])
        new_bound = {'workload_sha256': new['workload_sha256'], 'code_sha256': core.code_hash(),
                     'prompt_profile': new['prompt_profile'], 'prompt_sha': new['prompt_sha'],
                     'selected_target_ids': ids, 'mode': bound['mode'], 'run_profile': runtime,
                     'budget': new['budget'], 'concurrency': bound['concurrency']}
        seeded = {'identity': fingerprint(new_bound), 'binding': new_bound, 'jobs': {}, 'attempts': [],
                  'provider_attempts': 0, 'get_polls': 0, 'reserved_input_tokens': 0, 'reserved_output_tokens': 0,
                  'recovery_prior_accounting': prior}
        for rid, (job, receipt, normalized, old_binding) in imported.items():
            migrated = copy.deepcopy(receipt)
            trace = migrated.pop('transport_trace', None)
            migrated.update(payload_sha256=job['payload_sha256'], normalized=normalized, latency_ms=0,
                            import_provenance={'old_receipt': old_binding,
                                               'old_payload_sha256': ledger['jobs'][rid]['job']['payload_sha256'],
                                               'generation_grammar': 'historical_not_current', 'transport_trace': trace})
            migrated.pop('receipt_sha256')
            migrated['receipt_sha256'] = fingerprint(migrated)
            seeded['jobs'][rid] = {'job': job, 'status': 'verified', 'receipt_sha256': migrated['receipt_sha256']}
            write_new(root / 'live/receipts' / (rid + '.json'), migrated)
        seeded['ledger_sha256'] = fingerprint(seeded)
        write_new(root / 'input/reference_checklist.json', reference)
        write_new(root / 'recovery_manifest.json', manifest)
        write_new(root / 'live/runtime_ledger.json', seeded)
        write_new(root / 'input/preflight.json', core.preflight(new, cfg=cfg))
        # The wrapper only recognizes an executable destination after this last
        # write. A crash earlier leaves no workload to dispatch accidentally.
        write_new(root / 'input/workload.json', new)
        return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-root', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        from ..au_context_paired.__main__ import study_config
        cfg, _, _ = study_config(args)
        result = recover(args.old_root, args.output_root, cfg=cfg)
        print(json.dumps({'status':'prepared','imported_verified':result['imported_verified_count'],
                          'pending_requeued':len(result['requeued']),'invalid_retry':len(result['retry_invalid']),
                          'report':str(args.output_root/'recovery_manifest.json'),'network_executed':False}))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'status':'blocked','error_type':type(exc).__name__,'network_executed':False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
