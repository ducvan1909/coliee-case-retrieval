"""Isolated K0 diagnosis: preparation and at most three explicitly authorized jobs.

Never writes the frozen K0 workload, package or live checkpoint. No deployment.
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from urllib import request

from ..k0_authoring import core
from ..k0_authoring.tools import initial_state
from ..k0_authoring.runner import _usage
from ..au_compact.jobs_client import complete_job, payload_digest, JobTransportError
from ..au_compact.runner import _atomic
from ..au_context_paired.__main__ import study_config
from ..au_target_context.readiness import ReadinessGate

DEFAULT_K0 = Path('knowledge_base/pipeline_v1/outputs/k0_ready_20261023')


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def prepare(root, k0_root=DEFAULT_K0):
    root, parent = Path(root).resolve(), Path(k0_root).resolve()
    core.guard_output(root, [parent, Path(core.__file__).parent])
    if root.exists():
        raise ValueError('fresh diagnostic root required')
    cfg, _, _ = study_config(argparse.Namespace())
    w = core.load(parent / 'input/workload.json')
    core.preflight(w, cfg=cfg)
    real = core.build_job(w, w['cases'][0], initial_state(w['cases'][0]), cfg)
    synthetic = copy.deepcopy(real)
    source = 'Under this fictional test rule, an applicant must receive notice and an opportunity to respond before an adverse decision. This requirement does not apply in an emergency.'
    synthetic.update(case_id='synthetic', source_hash='synthetic', active_scope_ids=['r1'], allowed_scope_ids=['r1'], draft_ids=[],
        catalog={'evidence': {'e1': {'case_id': 'synthetic', 'source_hash': 'synthetic',
        'start_char': 0, 'end_char': len(source), 'quote': source}}})
    prompt = ('This is a synthetic protocol test, not real law. Author exactly one AU from the explicit fictional rule below, preserving its emergency exception. '
        'Return the K0 envelope aus, assessed_scope_ids, next_action. AU keys claim, kind, evidence_ids, limits. '
        'Use kind procedural_rule, evidence_ids ["e1"], assessed_scope_ids ["r1"], and next_action {"tool":"finish_case","reason":"work_scope_complete"}. '
        'Only JSON, no markdown.\nSOURCE r1/e1:\n' + source)
    synthetic['payload']['messages'] = [{'role': 'user', 'content': prompt}]
    synthetic['payload']['ebnf'] = core._grammar(['e1'], ['r1'], [])
    plain = copy.deepcopy(synthetic)
    plain['payload'].pop('ebnf')
    one = copy.deepcopy(real)
    one['payload']['messages'][0]['content'] += ('\nDIAGNOSTIC SINGLE-TURN MODE: All available source for this experiment is already supplied above. '
        'Author the supported legal points now in this response. Do not search, open regions, or request drafts. '
        'Finish this single turn using finish_case with reason work_scope_complete. An empty AU list remains allowed if no supported legal point exists; do not invent one.')
    # Same finite evidence/claim rules; the only available action is finish_case.
    lines = one['payload']['ebnf'].splitlines()
    lines = [line if not line.startswith('action ::=') else
        'action ::= "{" "\\\"tool\\\":" "\\\"finish_case\\\"" "," "\\\"reason\\\":" finish-reason "}"' for line in lines]
    one['payload']['ebnf'] = '\n'.join(lines) + '\n'
    jobs = []
    for name, job in [('synthetic_grammar', synthetic), ('synthetic_plain', plain), ('real_one_turn', one)]:
        job = copy.deepcopy(job)
        job['payload_sha256'] = payload_digest(job['payload'])
        job['input_reservation'] = core.input_reservation(job['payload'])
        if job['input_reservation'] > 6000 or job['payload']['max_tokens'] != 800:
            raise ValueError('diagnostic cap exceeded')
        jobs.append({'name': name, 'job': job})
    positive = {'aus': [{'claim': 'An applicant must receive notice and an opportunity to respond before an adverse decision.',
        'kind': 'procedural_rule', 'evidence_ids': ['e1'], 'limits': 'Except in an emergency.'}],
        'assessed_scope_ids': ['r1'], 'next_action': {'tool': 'finish_case', 'reason': 'work_scope_complete'}}
    bundles = []
    for row in (jobs[0], jobs[2]):
        j = row['job']; p = copy.deepcopy(positive)
        p['aus'][0]['evidence_ids'] = [next(iter(j['catalog']['evidence']))]
        p['assessed_scope_ids'] = j['active_scope_ids']
        multiple = copy.deepcopy(p); multiple['aus'].append({**p['aus'][0], 'claim': 'A separate test point.'})
        null = copy.deepcopy(p); null['aus'][0].update(kind=None, limits=None)
        empty = copy.deepcopy(p); empty['aus'] = []
        bad = copy.deepcopy(p); bad['aus'][0]['evidence_ids'] = ['NOT_SUPPLIED']
        bundles.append({'name': row['name'], 'grammar': j['payload']['ebnf'],
            'positive_examples': [encode(x) for x in (p, multiple, null, empty)],
            'negative_examples': [encode(bad), encode(p).replace('"claim":', '"WRONG_KEY":'), encode(p) + 'prose']})
    bindings = [{'path': str(p.resolve()), 'sha256': __import__('hashlib').sha256(p.read_bytes()).hexdigest()}
        for p in sorted(parent.rglob('*')) if p.is_file()]
    _atomic(root/'input/manifest.json', {'jobs': jobs, 'parent_bindings': bindings,
        'runtime_code_sha256': core.code_hash(), 'diagnostic_code_sha256': __import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest(),
        'max_POST_attempts': 3, 'max_reserved_tokens': 30000,
        'same_source_case': real['case_id'], 'semantic_quality': 'not_assessed'})
    _atomic(root/'input/cpu_bundle.json', {'jobs': bundles})
    return {'status': 'prepared', 'jobs': len(jobs), 'inference': 0}


def run(root):
    root = Path(root).resolve(); manifest = core.load(root/'input/manifest.json')
    from ..au_context_paired.build import verify_bindings
    verify_bindings(manifest['parent_bindings'])
    if core.code_hash() != manifest['runtime_code_sha256']:
        raise ValueError('K0 code changed')
    if __import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest() != manifest['diagnostic_code_sha256']:
        raise ValueError('diagnostic code changed')
    cpu = core.load(root/'cpu.json')
    bundle_sha = __import__('hashlib').sha256((root/'input/cpu_bundle.json').read_bytes()).hexdigest()
    if cpu.get('status') != 'pass' or cpu.get('bundle_sha256') != bundle_sha:
        raise ValueError('CPU replay must pass before live diagnostic')
    cfg, _, _ = study_config(argparse.Namespace())
    cfg['job_wait_seconds'] = min(float(cfg.get('job_wait_seconds', 600)), 600)
    ledger_path = root/'ledger.json'
    ledger = core.load(ledger_path) if ledger_path.exists() else {'attempts': [], 'receipts': {}}
    reserved = sum(core.input_reservation(r['job']['payload']) + 800 for r in manifest['jobs'])
    if reserved > 30000:
        raise ValueError('reservation ceiling')

    def audit(req, **kwargs):
        if req.get_method() == 'POST':
            wire = json.loads(req.data); jid = wire['job_id']
            if any(a['job_id'] == jid for a in ledger['attempts']):
                raise ValueError('prior POST exists; retrieve only, no duplicate dispatch')
            if len(ledger['attempts']) >= 3:
                raise ValueError('three POST ceiling')
            for a in ledger['attempts']:
                receipt = ledger['receipts'].get(a['job_id'], {})
                if not receipt.get('usage'):
                    raise ValueError('unknown prior usage blocks POST')
                if receipt['usage']['input_tokens'] > 6000 or receipt['usage']['output_tokens'] > 800:
                    raise ValueError('measured per-request cap')
            if sum(x['usage']['total_tokens'] for x in ledger['receipts'].values() if x.get('usage')) >= 30000:
                raise ValueError('actual usage ceiling')
            if not any(payload_digest(j['job']['payload']) == jid and j['job']['payload'] == wire['payload'] for j in manifest['jobs']):
                raise ValueError('unlisted payload')
            ledger['attempts'].append({'job_id': jid, 'started_at_unix': time.time()})
            _atomic(ledger_path, ledger)
        return request.urlopen(req, **kwargs)

    gate = ReadinessGate(cfg, audit, time.monotonic, time.sleep, lambda x: _atomic(root/'readiness.json', x))
    gate.warmup(any(j['job']['payload_sha256'] not in ledger['receipts'] for j in manifest['jobs']))
    if gate.snapshot()['status'] not in ('ready', 'not_needed'):
        return {'status': 'incomplete', 'reason': 'readiness'}
    rows = []
    for row in manifest['jobs']:
        job, name = row['job'], row['name']; jid = payload_digest(job['payload'])
        if jid not in ledger['receipts'] or 'raw_response' not in ledger['receipts'][jid]:
            _atomic(root/'payloads'/f'{name}.json', job['payload'])
            try:
                body, trace = complete_job(cfg, job['payload'], opener=audit)
                receipt = {'raw_response': body, 'trace': trace, 'usage': _usage(body)}
            except Exception as exc:
                receipt = {'error_type': type(exc).__name__, 'trace': exc.trace if isinstance(exc, JobTransportError) else None, 'usage': None}
            receipt_path = root/'receipts'/f'{name}.json'
            if receipt_path.exists():
                previous = core.load(receipt_path)
                _atomic(root/'receipt_history'/f'{name}_{time.time_ns()}.json', previous)
            _atomic(receipt_path, receipt)
            ledger['receipts'][jid] = receipt; _atomic(ledger_path, ledger)
        receipt = ledger['receipts'][jid]
        result = {'name': name, 'usage': receipt.get('usage'), 'status': 'invalid'}
        try:
            body = receipt['raw_response']; choice = body['choices'][0]
            result['finish_reason'] = choice['finish_reason']
            value = json.loads(choice['message']['content'])
            normalized = core.validate_response(value, job)
            result.update(status='valid' if choice['finish_reason']=='stop' and not normalized['au_errors'] else 'invalid',
                model_output=value, normalized=normalized)
            result['AU_count'] = len(normalized['aus'])
            if name.startswith('synthetic'):
                result['one_AU_control_pass'] = result['status']=='valid' and len(normalized['aus'])==1
        except Exception as exc:
            result['error_type'] = type(exc).__name__
        rows.append(result)
        _atomic(root/'report.json', {'status': 'complete' if len(rows)==3 else 'incomplete', 'rows': rows,
            'POST_attempts': len(ledger['attempts']), 'semantic_quality': 'not_assessed', 'reservation': reserved})
        if not receipt.get('usage'):
            break
    verify_bindings(manifest['parent_bindings'])
    return {'status': 'complete' if len(rows)==3 else 'incomplete', 'rows': len(rows), 'POST_attempts': len(ledger['attempts'])}


def main():
    p=argparse.ArgumentParser(); p.add_argument('command', choices=['prepare','run']); p.add_argument('--output-root',type=Path,required=True); p.add_argument('--execute',action='store_true'); args=p.parse_args()
    if args.command=='run' and not args.execute: p.error('run requires --execute')
    try:
        result=prepare(args.output_root) if args.command=='prepare' else run(args.output_root)
        print(json.dumps(result)); return 0 if result['status'] in ('prepared','complete') else 1
    except Exception as exc:
        print(json.dumps({'status':'blocked','error_type':type(exc).__name__}));return 1


if __name__=='__main__':
    raise SystemExit(main())
