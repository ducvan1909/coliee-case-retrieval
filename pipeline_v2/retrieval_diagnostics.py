"""Write-once raw hybrid captures and read-only verification, without model calls."""

import argparse
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from time import perf_counter

from .agent_harness.contracts import HarnessError, encode, fingerprint, source_hash

VERSION = 'm6-retrieval-diagnostic-v1'
BINDING_FIELDS = ('policy', 'execution_mode', 'full_manifest_sha256', 'sparse_manifest_sha256',
                  'full_verification_receipt_sha256', 'embedding_fingerprint', 'collection',
                  'implementation_sha256')


def _require(condition, message):
    if not condition:
        raise HarnessError(message)


def _relative_path(operation):
    _require(source_hash(operation), 'Invalid diagnostic operation ID')
    return f'retrieval_diagnostics/{operation}.json'


def _resolve(run_dir, relative):
    root = Path(run_dir).resolve()
    path = (root / relative).resolve()
    _require(path.is_relative_to(root), 'Diagnostic artifact escapes run directory')
    return path


def bindings(result):
    """Record exactly what the runtime supplied; absent bindings remain unknown."""
    return {key: result.get(key) for key in BINDING_FIELDS}


def capture(run_dir, *, operation, action_id, query, query_case, limit, result):
    """Persist one existing result. Never run retrieval, replace or reuse a file."""
    started = perf_counter()
    _require(operation == fingerprint([action_id, query, query_case, limit]), 'Diagnostic operation mismatch')
    query_hash = sha256(query.encode('utf-8')).hexdigest()
    _require(result.get('query_case') == query_case and result.get('query_sha256') == query_hash,
             'Diagnostic query mismatch')
    relative = _relative_path(operation)
    path = _resolve(run_dir, relative)
    envelope = {'version': VERSION, 'operation': operation, 'action_id': action_id,
                'query': query, 'query_sha256': query_hash, 'query_case': query_case, 'limit': limit,
                'm3_request_id': result.get('request_id'), 'bindings': bindings(result), 'result': result}
    content = encode(envelope)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return {'diagnostic_status': 'saved', 'diagnostic_path': relative,
            'diagnostic_sha256': sha256(content).hexdigest(), 'diagnostic_bindings': envelope['bindings'],
            'diagnostic_save_seconds': perf_counter() - started}


def verify_capture(run_dir, receipt, admission):
    """Hash and cross-check a saved capture against its two journal links.

    This verifies the linked bytes and identifiers, not historical seal correctness,
    channel completeness beyond the returned caps, or semantic retrieval quality.
    """
    _require(receipt.get('kind') == 'search_returned' and receipt.get('status') == 'success'
             and receipt.get('diagnostic_status') == 'saved', 'Search has no saved diagnostic')
    _require(admission.get('kind') == 'search_admitted', 'Missing search admission')
    operation = admission.get('operation')
    relative = _relative_path(operation)
    _require(receipt.get('operation') == operation and receipt.get('diagnostic_path') == relative,
             'Diagnostic link/path mismatch')
    path = _resolve(run_dir, relative)
    content = path.read_bytes()
    _require(source_hash(receipt.get('diagnostic_sha256')) and
             sha256(content).hexdigest() == receipt['diagnostic_sha256'], 'Diagnostic artifact hash mismatch')
    body = json.loads(content)
    _require(isinstance(body, dict) and body.get('version') == VERSION, 'Unknown diagnostic envelope')
    for key in ('operation', 'action_id', 'query_sha256', 'query_case', 'limit'):
        _require(body.get(key) == admission.get(key) == receipt.get(key), f'Diagnostic {key} link mismatch')
    query = body.get('query')
    _require(isinstance(query, str) and sha256(query.encode('utf-8')).hexdigest() == body['query_sha256'],
             'Diagnostic query text/hash mismatch')
    _require(operation == fingerprint([body['action_id'], query, body['query_case'], body['limit']]),
             'Diagnostic operation fingerprint mismatch')
    result = body.get('result')
    _require(isinstance(result, dict), 'Diagnostic raw result missing')
    _require(body.get('m3_request_id') == receipt.get('m3_request_id') == result.get('request_id')
             and isinstance(body.get('m3_request_id'), str) and bool(body['m3_request_id']),
             'Diagnostic M3 request link mismatch')
    _require(result.get('query_sha256') == body['query_sha256'] and result.get('query_case') == body['query_case'],
             'Diagnostic raw response query mismatch')
    _require(body.get('bindings') == receipt.get('diagnostic_bindings') == bindings(result),
             'Diagnostic result binding mismatch')
    return body


def inspect_run(run_dir):
    """Inspect an existing journal read-only; unavailable or interrupted stays explicit."""
    run_dir = Path(run_dir).resolve()
    journal = run_dir / 'embedding_events.sqlite3'
    with closing(sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True)) as db:
        events = [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]
    admissions = {row['operation']: row for row in events if row['kind'] == 'search_admitted'}
    returned = {}
    for row in events:
        if row['kind'] != 'search_returned':
            continue
        operation = row.get('operation')
        _require(operation in admissions and operation not in returned, 'Unmatched/duplicate search receipt')
        returned[operation] = row
    searches = []
    for operation, admission in admissions.items():
        receipt = returned.get(operation)
        summary = {'operation': operation, 'action_id': admission.get('action_id'),
                   'query_sha256': admission.get('query_sha256')}
        if receipt is None:
            summary.update(status='unknown', diagnostic_status='unlinked_or_unavailable',
                           reason='No terminal receipt; any orphan artifact is not certified or replayed.')
        elif receipt.get('diagnostic_status') == 'saved':
            body = verify_capture(run_dir, receipt, admission)
            result = body['result']
            summary.update(status=receipt['status'], diagnostic_status='verified',
                           diagnostic_path=receipt['diagnostic_path'], m3_request_id=body['m3_request_id'],
                           channel_counts={key: len(value) for key, value in result.get('channels', {}).items()},
                           delivered_hits=len(result.get('hits', [])), bindings=body['bindings'])
        else:
            summary.update(status=receipt.get('status'), diagnostic_status=receipt.get('diagnostic_status', 'legacy_unavailable'),
                           diagnostic_error_type=receipt.get('diagnostic_error_type'),
                           channel_results='unknown_no_verified_raw_response')
        searches.append(summary)
    return {'version': VERSION, 'model_calls_this_tool': 0, 'searches': searches}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True, help='Existing M6 run to inspect read-only')
    args = parser.parse_args()
    try:
        report = inspect_run(args.run_dir)
    except (OSError, ValueError, HarnessError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
