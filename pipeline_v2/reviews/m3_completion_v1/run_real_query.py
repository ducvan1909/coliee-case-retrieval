"""Preview or explicitly execute the single frozen user/AG M3 acceptance query."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_once(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write('\n')


def load_manifest():
    path = HERE / 'real_query_manifest.json'
    expected = (HERE / 'real_query_manifest.sha256').read_text(encoding='utf-8').strip()
    if sha(path) != expected:
        raise ValueError('Acceptance manifest hash differs')
    manifest = json.loads(path.read_bytes())
    if manifest['max_model_requests'] != 1 or manifest['automatic_retries'] != 0:
        raise ValueError('Unexpected request scope')
    for name, expected_hash in manifest['file_sha256'].items():
        target = (ROOT / name).resolve()
        if not target.is_relative_to(ROOT) or sha(target) != expected_hash:
            raise ValueError('Acceptance input/code drift: ' + name)
    source = manifest['source']
    if re.fullmatch(r'[0-9]{6}\.txt', source['case_id']) is None:
        raise ValueError('Invalid acceptance case ID')
    raw = (ROOT / 'data/task1_train_files_2026/cases' / source['case_id']).read_bytes()
    start, end = source['span_bytes']
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(raw)
            or hashlib.sha256(raw).hexdigest() != source['source_hash']
            or raw[start:end].decode('utf-8') != manifest['query']):
        raise ValueError('Acceptance query differs from raw source')
    cohort = json.loads((ROOT / manifest['cohort_path']).read_bytes())
    if source['case_id'] not in cohort['discovery_queries']:
        raise ValueError('Acceptance query must belong to frozen discovery cohort')
    return manifest, expected


def usage(directory):
    path = directory / 'ledger.sqlite3'
    if not path.exists():
        return {'ledger_exists': False, 'model_requests': None}
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        row = db.execute(
            'SELECT COUNT(*),COALESCE(SUM(requests),0),COALESCE(SUM(tokens),0),'
            'SUM(tokens IS NULL),COALESCE(SUM(elapsed),0),SUM(elapsed IS NULL) '
            'FROM attempts').fetchone()
        fields = ('attempts', 'model_requests', 'known_input_tokens',
                  'unknown_token_attempts', 'recorded_elapsed_seconds',
                  'unknown_elapsed_attempts')
        return {'ledger_exists': True, **dict(zip(fields, row)),
                'status_counts': dict(db.execute(
                    'SELECT status,COUNT(*) FROM attempts GROUP BY status'))}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true',
                        help='User/AG only. Admit one actual Modal query request.')
    args = parser.parse_args()
    manifest, manifest_hash = load_manifest()
    command = [sys.executable, '-m', 'pipeline_v2.m3_sparse', 'search-hybrid',
               '--query', manifest['query'], '--query-case', manifest['source']['case_id'],
               '--limit', '20']
    if not args.execute:
        print(json.dumps({'status': 'preview_only', 'model_requests': 0,
                          'manifest_sha256': manifest_hash, 'command': command}, indent=2))
        return 0
    output = HERE / 'real_query_execution'
    output.mkdir(exist_ok=True)
    runtime = ROOT / 'pipeline_v2/artifacts/m3_full_search_runtime_v1'
    before = {p.name for p in runtime.iterdir() if p.is_dir()} if runtime.exists() else set()
    # A previous admission requires explicit review even if its outcome is unknown.
    write_once(output / 'admission.json', {
        'started_utc': utc(), 'manifest_sha256': manifest_hash,
        'max_model_requests': 1, 'automatic_retries': 0, 'command': command})
    started = time.perf_counter()
    result = {'status': 'started', 'manifest_sha256': manifest_hash}
    exit_code = 1
    try:
        with (output / 'stdout.json').open('x', encoding='utf-8') as stdout:
            with (output / 'stderr.txt').open('x', encoding='utf-8') as stderr:
                completed = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        exit_code = completed.returncode
        result.update(status='returned' if exit_code == 0 else 'failed', exit_code=exit_code)
    except BaseException as exc:
        exit_code = 130 if isinstance(exc, KeyboardInterrupt) else 1
        result.update(status='interrupted_or_failed', error_type=type(exc).__name__)
        raise
    finally:
        after = {p.name for p in runtime.iterdir() if p.is_dir()} if runtime.exists() else set()
        result.update(finished_utc=utc(), elapsed_seconds=time.perf_counter() - started,
                      new_runtime_usage={name: usage(runtime / name)
                                         for name in sorted(after - before)})
        write_once(output / 'command_receipt.json', result)
        print(json.dumps(result, indent=2), flush=True)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
