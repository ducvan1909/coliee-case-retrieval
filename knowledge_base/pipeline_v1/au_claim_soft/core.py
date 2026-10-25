"""Offline soft-length policy; all other original hard gates stay intact."""
from pathlib import Path
import hashlib
from ..au_claim import core as original
from ..au_claim.contracts import MAX_AUS, KINDS
from ..au_claim.compare import _checkpoint
from ..au_claim_recovery.core import parse_body
from ..au_context_paired.build import binding, verify_bindings, write_new
from ..au_target_context.runner import _receipt

require, fingerprint = original.require, original.fingerprint
VERSION = 'au-claim-soft-v1'


def validate_response(value, job):
    require(isinstance(value, dict) and set(value) == {'aus', 'context_request'}, 'exact response keys required')
    require(isinstance(value['aus'], list) and len(value['aus']) <= MAX_AUS, 'AU cap exceeded')
    warnings = []
    def text(v, cap, path):
        require(isinstance(v, str) and 1 <= len(v) and bool(v.strip())
                and not any(0xD800 <= ord(c) <= 0xDFFF for c in v), 'invalid text')
        if len(v) > cap:
            warnings.append({'code': 'length_threshold_exceeded', 'severity': 'warning',
                             'path': path, 'threshold': cap, 'actual_length': len(v)})
        return ' '.join(v.split())
    context_request = value['context_request']
    if context_request is not None:
        require(isinstance(context_request, dict) and set(context_request) == {'question'}, 'invalid context request')
        context_request = {'question': text(context_request['question'], 200, ['context_request', 'question'])}
    target = job['catalog']['target_refs']
    allowed = {**target, **job['catalog']['context_refs']}
    aus, seen, removed = [], set(), 0
    for i, item in enumerate(value['aus']):
        require(isinstance(item, dict) and set(item) == {'claim', 'kind', 'evidence_ids', 'limits'}, 'exact AU keys required')
        claim, kind = text(item['claim'], 500, ['aus', i, 'claim']), item['kind']
        require(kind is None or (isinstance(kind, str) and kind in KINDS), 'unknown kind')
        refs = item['evidence_ids']
        require(isinstance(refs, list) and bool(refs) and all(isinstance(r, str) and r in allowed for r in refs), 'invalid evidence IDs')
        require(bool(set(refs) & set(target)), 'AU needs TARGET evidence')
        refs = sorted(set(refs), key=lambda r: (allowed[r]['start_char'], allowed[r]['end_char'], r))
        limits = None if item['limits'] is None else text(item['limits'], 250, ['aus', i, 'limits'])
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
    return {'warnings': warnings, 'aus': aus, 'context_request': context_request, 'needs_context': context_request is not None,
            'exact_duplicates_removed': removed, 'shared_evidence_pairs': shared,
            'semantic_quality': 'not_assessed', 'semantic_status': 'unknown'}


def import_run(parent_root, output_root):
    """Verify original A checkpoint and revalidate all 16 raw stage-1 bodies.

    Nothing is generated or repaired. Raw text is retained alongside the original
    whitespace normalization; AU identities use that entire normalized text.
    Context continuation is pending and deliberately outside this offline import.
    """
    parent, root = Path(parent_root).resolve(), Path(output_root).resolve()
    base = Path(__file__).resolve().parents[1]
    original.guard_output(root, [parent, *[base / name for name in
        ('au_claim_soft', 'au_claim', 'au_claim_recovery')]])
    require(not root.exists(), 'import output must be a new directory')
    workload_path, run_path = parent / 'input/workload.json', parent / 'live/run.json'
    # Snapshot every file read by the checkpoint, not only its ledger/report.
    paths = [workload_path, run_path, run_path.parent / 'runtime_ledger.json']
    paths += sorted((run_path.parent / 'receipts').glob('*.json'))
    paths += sorted((run_path.parent / 'attempt_receipts').glob('*.json'))
    bindings = [binding(p) for p in paths]
    w, _, history, ledger = _checkpoint(workload_path, run_path)
    original.guard_output(root, [w['source_store'], w['atom_root'],
        Path(w['reference_checklist_path']).parent,
        *[Path(b['path']).parent for b in w['parent_bindings']]])
    ids = {r['target_id'] for r in w['rows']}
    require(len(ids) == len(w['rows']) == len(ledger['jobs']) == 16
            and set(ledger['binding']['selected_target_ids']) == ids,
            'requires full original same16 checkpoint')
    entries = {e['job']['target_id']: e for e in ledger['jobs'].values()}
    require(set(entries) == ids and all(e['job']['stage'] == 1 and
            e['status'] in ('verified', 'invalid') for e in entries.values()),
            'requires one terminal original stage1 receipt per TARGET')
    results, warnings = [], []
    for row in w['rows']:
        entry = entries[row['target_id']]
        job, receipt = entry['job'], _receipt(run_path.parent, entry)
        require(receipt['status'] == entry['status'], 'parent receipt status mismatch')
        result = {k: row[k] for k in ('target_id', 'case_id', 'source_hash', 'target')}
        result.update(original_request_id=job['request_id'], original_status=entry['status'],
                      original_receipt_sha256=receipt['receipt_sha256'],
                      raw_response=receipt['raw_response'], output=None, warnings=[],
                      needs_context=False, semantic_quality='not_assessed')
        try:
            value = parse_body(receipt['raw_response'], job, {'model': w['identity']['model']})
            result['model_output'] = value
            normalized = validate_response(value, job)
        except (ValueError, TypeError, KeyError, IndexError):
            result.update(status='invalid', protocol_status='invalid',
                          error='output_protocol_validation', context_status='not_assessed')
        else:
            needs = normalized['needs_context']
            result.update(output=normalized, warnings=normalized['warnings'],
                          status='needs_context' if needs else 'draft_ready',
                          protocol_status='verified', needs_context=needs,
                          context_status='pending' if needs else 'not_needed')
            warnings.extend({'target_id': row['target_id'], 'request_id': job['request_id'], **warning}
                            for warning in normalized['warnings'])
        results.append(result)
    verified = sum(r['protocol_status'] == 'verified' for r in results)
    # Include historical costs even for invalid generations; import costs zero.
    history.update(GET_polls=ledger['get_polls'], attempts=ledger['attempts'],
                   reserved_input_utf8_bytes=ledger['reserved_input_tokens'],
                   reserved_output_tokens=ledger['reserved_output_tokens'],
                   client_latency_ms=sum(_receipt(run_path.parent, e).get('latency_ms', 0)
                                         for e in ledger['jobs'].values()))
    report = {'artifact_type': 'AUClaimSoftImport', 'version': VERSION,
              'status': 'complete' if verified == 16 else 'incomplete',
              'parent_root': str(parent), 'parent_bindings': bindings,
              'parent_workload_sha256': w['workload_sha256'],
              'historical_code_sha256': w['code_sha256'],
              'code_sha256': fingerprint({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(Path(__file__).parent.glob('*.py'))}),
              'policy': {'claim': 500, 'limits': 250, 'question': 200,
                         'length_enforcement': 'warning_only', 'length_repair': False},
              'target_count': len(results), 'receipt_count': len(results),
              'protocol_complete': verified == 16, 'protocol_verified': verified,
              'protocol_invalid': 16 - verified, 'results': results,
              'warnings': warnings, 'warning_count': len(warnings),
              'needs_context': sum(r['needs_context'] for r in results),
              'context_continuation': 'separate_workflow_pending',
              'inherited_accounting': history,
              'new_accounting': {'logical_requests': 0, 'provider_POST_attempts': 0,
                                 'transport_POST_attempts': 0, 'GET_polls': 0,
                                 'input_tokens': 0, 'output_tokens': 0},
              'network_requests': 0, 'network_executed': False,
              'semantic_quality': 'not_assessed'}
    verify_bindings(bindings)
    require(not (run_path.parent / '.runner.lock').exists(), 'parent runner restarted')
    report['report_sha256'] = fingerprint(report)
    write_new(root / 'report.json', report)
    return report
