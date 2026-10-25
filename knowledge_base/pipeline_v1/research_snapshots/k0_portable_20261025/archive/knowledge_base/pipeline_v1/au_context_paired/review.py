"""Source-backed review packets, with no inferred semantic verdict."""
from copy import deepcopy
from pathlib import Path
from .build import fingerprint, render_request, write_new, PairedError
from .preflight import validate_workload
from ..source_contract import open_source

CHECKS = ['authority_qualification', 'target_ownership', 'claim_support', 'attribution',
          'condition', 'exception', 'limit', 'omission', 'duplicate', 'coverage']

def reference_checklist(workload):
    validate_workload(workload)
    requests = {r['request_id']: r for r in workload['manifest']['requests']}
    rows = []
    for p in workload['pairs']:
        # Review can see the union of both packets; no extraction output enters it.
        atoms = {}
        for rid in set(p['request_ids'].values()):
            catalog = render_request(requests[rid], workload['source_store'], workload['atom_root'])['catalog']
            atoms.update(catalog['atoms'])
        rows.append({'pair_id': p['pair_id'], 'case_id': p['case_id'], 'source_hash': p['source_hash'],
                     'target_id': p['target_id'], 'target': p['target'],
                     'source_atoms': sorted(atoms.values(), key=lambda a: a['start_char']),
                     'checks': CHECKS, 'status': 'pending', 'propositions': [],
                     'required_qualifications': [], 'speaker_evidence': [], 'distractors': [],
                     'unresolved_dependencies': [], 'reviewer': None})
    return {'artifact_type': 'AUContextReferenceChecklist', 'version': 'au-context-reference-v1',
            'workload_sha256': workload['workload_sha256'], 'status': 'pending',
            'reference_kind': 'model_assisted_reference', 'semantic_gold': False,
            'source_only': True, 'rows': rows}

def validate_checklist(value, workload, require_locked=False):
    if value.get('workload_sha256') != workload['workload_sha256'] or value.get('reference_kind') != 'model_assisted_reference' or value.get('semantic_gold') is not False:
        raise PairedError('reference checklist identity mismatch')
    pairs = {p['pair_id']: p for p in workload['pairs']}
    rows = value.get('rows', [])
    if len(rows) != len(pairs) or {r['pair_id'] for r in rows} != set(pairs):
        raise PairedError('reference checklist must cover every distinct target')
    for row in rows:
        p = pairs[row['pair_id']]
        if any(row.get(k) != p[k] for k in ('case_id', 'source_hash', 'target_id', 'target')):
            raise PairedError('reference checklist source ownership mismatch')
        if row.get('status') not in ('pending', 'reviewed', 'unknown'):
            raise PairedError('invalid reference status')
        if require_locked and (row['status'] == 'pending' or not row.get('reviewer')):
            raise PairedError('reference checklist not reviewed/locked before inference')
    if require_locked and value.get('status') != 'locked':
        raise PairedError('reference checklist is not locked')
    return value

def _run_rows(run):
    rows = run.get('request_ledger', [])
    if not isinstance(rows, list):
        raise PairedError('invalid run request ledger')
    result = {}
    for row in rows:
        rid = row.get('request', {}).get('request_id')
        if not isinstance(rid, str) or rid in result:
            raise PairedError('duplicate or missing physical receipt identity')
        result[rid] = row
    return result

def review_packet(workload, run):
    validate_workload(workload)
    if run.get('workload_sha256') != workload['workload_sha256']:
        raise PairedError('run/workload binding mismatch')
    receipts = _run_rows(run)
    requests = {r['request_id']: r for r in workload['manifest']['requests']}
    for rid, row in receipts.items():
        if rid not in requests or row['request'] != requests[rid]:
            raise PairedError('review receipt request does not match locked workload')
    packet, mapping = [], []
    for p in workload['pairs']:
        arms = ['G', 'S'] if int(fingerprint(['blind', p['pair_id']])[:2], 16) % 2 == 0 else ['S', 'G']
        if p['shared_identical_input']:
            arms = ['G']
        for ordinal, arm in enumerate(arms):
            rid = p['request_ids'][arm]
            blind_id = 'blind-' + fingerprint([p['pair_id'], ordinal])[:24]
            row = receipts.get(rid)
            compact = deepcopy(row.get('compact_response')) if row else None
            if isinstance(compact, dict):
                compact.pop('request_id', None)
            catalog = render_request(requests[rid], workload['source_store'], workload['atom_root'])['catalog']
            packet.append({'blind_id': blind_id, 'pair_id': p['pair_id'], 'case_id': p['case_id'],
                           'source_hash': p['source_hash'], 'target_id': p['target_id'], 'target': p['target'],
                           'source_atoms': sorted(catalog['atoms'].values(), key=lambda a: a['start_char']),
                           'proposal': compact, 'execution_status': row.get('status') if row else 'pending',
                           'checks': CHECKS, 'semantic_verdict': None, 'target_omission_review': 'pending'})
            mapping.append({'blind_id': blind_id, 'pair_id': p['pair_id'], 'arm': arm,
                            'physical_request_id': rid, 'shared_identical_input': p['shared_identical_input']})
    result = {'artifact_type': 'AUContextBlindReviewPacket', 'version': 'au-context-blind-v1',
              'workload_sha256': workload['workload_sha256'], 'run_sha256': fingerprint(run),
              'source_store': workload['source_store'],
              'semantic_gold': False, 'reference_kind': 'model_assisted_reference', 'status': 'pending', 'rows': packet}
    result['packet_sha256'] = fingerprint(result)
    return result, {'packet_sha256': result['packet_sha256'], 'workload_sha256': workload['workload_sha256'], 'rows': mapping}

def write_review(workload, run, output_root):
    packet, mapping = review_packet(workload, run)
    root = Path(output_root)
    write_new(root / 'blind_review_packet.json', packet)
    write_new(root / 'blind_mapping_host_only.json', mapping)
    return packet

def validate_decisions(value, packet):
    if value.get('packet_sha256') != packet['packet_sha256'] or value.get('semantic_gold') is not False:
        raise PairedError('review decisions binding mismatch')
    allowed = {row['blind_id']: row for row in packet['rows']}
    rows = value.get('rows')
    if not isinstance(rows, list):
        raise PairedError('review decisions rows must be a list')
    seen = set()
    for row in rows:
        bid = row.get('blind_id')
        if bid not in allowed or bid in seen:
            raise PairedError('unknown/duplicate blind review ID')
        seen.add(bid)
        if row.get('verdict') not in ('supported', 'unsupported', 'incomplete', 'unknown', 'disputed') or row.get('severity') not in ('none', 'minor', 'severe', 'unknown'):
            raise PairedError('invalid semantic verdict/severity')
        if not isinstance(row.get('reviewer'), str) or not row['reviewer']:
            raise PairedError('reviewer identity required')
        if not isinstance(row.get('errors'), list) or not all(e in CHECKS for e in row['errors']):
            raise PairedError('invalid review error tags')
        if not isinstance(row.get('evidence_spans'), list) or not isinstance(row.get('explanation'), str) or not row['explanation']:
            raise PairedError('review requires explanation and exact source evidence')
        for span in row['evidence_spans']:
            a, b = span.get('start_char'), span.get('end_char')
            source = open_source(packet['source_store'], allowed[bid]['case_id'], allowed[bid]['source_hash'])
            if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(source):
                raise PairedError('invalid review evidence span')
            if 'quote' in span and span['quote'] != source[a:b]:
                raise PairedError('review quote differs from immutable source')
        if row['verdict'] in ('supported', 'unsupported', 'incomplete') and not row['evidence_spans']:
            raise PairedError('non-unknown review needs source evidence')
    return value
