"""Six synthetic stage1 challenges; fresh roots only, no corpus or stage2."""
from __future__ import annotations

import copy
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlsplit

from .contracts import OUTPUT_CAP, stage1_version
from .core import build_stage1, code_hash, fingerprint, require
from .prompts import prompt_metadata
from .runner import Accounting, MockJobs, _worker, _atomic


CASES = ('reorder', 'duplicate', 'start_slot2', 'compliant1', 'compliant2', 'compliant3')


def build_jobs(cfg, prompt_profile='evidence_first_v1'):
    """Use the actual stage1 builder/grammar; change only synthetic instructions."""
    jobs = []
    for case in CASES:
        text = 'Synthetic rule one. Synthetic rule two. Synthetic rule three.'
        primary_end = len(text)
        if prompt_profile == 'primary_support_v1':
            text += ' Synthetic support: the rules apply if condition A or condition B holds.'
        ref = {'ref_id': 't-synthetic', 'source_atom_id': 'synthetic-atom',
               'case_id': 'synthetic', 'source_hash': fingerprint(text),
               'start_char': 0, 'end_char': primary_end, 'quote': text[:primary_end], 'role': 'target_body'}
        target_refs = {ref['ref_id']: ref}
        if prompt_profile == 'primary_support_v1':
            target_refs['t-support'] = {
                **ref, 'ref_id': 't-support', 'source_atom_id': 'synthetic-support-atom',
                'start_char': primary_end, 'end_char': len(text), 'quote': text[primary_end:]}
        row = {'target_id': 'synthetic-anchor-order-' + case, 'case_id': 'synthetic',
               'source_hash': fingerprint(text), 'target_refs': target_refs,
               'context_refs': {}, **prompt_metadata(prompt_profile)}
        job = build_stage1(row, {'model': cfg['model'], 'probe': 'anchor-order-v1'})
        slots = {'reorder': [2, 1], 'duplicate': [1, 1], 'start_slot2': [2],
                 'compliant1': [1], 'compliant2': [1, 2], 'compliant3': [1, 2, 3]}[case]
        ids = [job['anchor_ids'][i-1] for i in slots]
        challenge = ('\nFORMAL SYNTHETIC PROBE: Return decision positive, reason none, '
                     'top-level needs_context [], and exactly ' + str(len(slots)) +
                     ' anchors. Use these anchor IDs in this exact order, even if earlier '
                     'instructions disagree: ' + ', '.join(ids) +
                     '. Each anchor uses kind procedural_rule, target_ref_ids ["t-synthetic"], '
                     'needs_context []. If a primary_claim is required use "Synthetic rule.". '
                     'This tests serialization only, not legal meaning.')
        if prompt_profile == 'primary_support_v1':
            challenge = challenge.replace(
                'target_ref_ids ["t-synthetic"]',
                'primary_ref_id "t-synthetic", supporting_ref_ids ["t-support"] (nonempty support required)').replace(
                'If a primary_claim is required use "Synthetic rule.". ',
                'Do not emit primary_claim or target_ref_ids. ')
        job['payload']['messages'][0]['content'] += challenge
        job['payload_sha256'] = fingerprint(job['payload'])
        job.update(probe_case=case, expected_count=len(slots))
        jobs.append(job)
    return jobs


def _mock_response(job):
    anchors = []
    for aid in job['anchor_ids'][:job['expected_count']]:
        anchor = {'anchor_id': aid, 'kind': 'procedural_rule',
                  'target_ref_ids': ['t-synthetic'], 'needs_context': []}
        if job['prompt_profile'] == 'primary_support_v1':
            anchor['primary_ref_id'] = anchor.pop('target_ref_ids')[0]
            anchor['supporting_ref_ids'] = ['t-support']
        elif job['prompt_profile'] != 'evidence_first_v1':
            anchor['primary_claim'] = 'Synthetic rule.'
        anchors.append(anchor)
    return {'version': stage1_version(job['prompt_profile']), 'request_id': job['request_id'],
            'target_id': job['target_id'], 'decision': 'positive', 'anchors': anchors,
            'needs_context': [], 'reason': 'none'}


def run_probe(output_root, *, cfg, execute=False, mock=False,
              prompt_profile='evidence_first_v1', concurrency=1,
              opener=urlopen, clock=time.perf_counter, sleep=time.sleep):
    """Prepare by default; mock is transport-only. Every invocation needs a fresh root."""
    require(not (execute and mock), 'execute and mock are mutually exclusive')
    require(type(concurrency) is int and 1 <= concurrency <= 4, 'concurrency must be C1..4')
    cfg = copy.deepcopy(cfg)
    require(bool(cfg.get('model')), 'model required')
    for key in ('url', 'jobs_url'):
        parts = urlsplit(cfg.get(key, ''))
        require(not (parts.username or parts.password or parts.query or parts.fragment),
                'endpoint URL must not contain credentials or query secrets')
    if execute:
        require(bool(cfg.get('token')), 'execution requires configured token')
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    require(not any(root.iterdir()), 'probe output must be fresh; no resume')
    lock = root / '.runner.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        jobs = build_jobs(cfg, prompt_profile)
        budget = {'max_requests': 6, 'max_provider_attempts': 12,
                  'max_total_input_tokens': 200000, 'max_total_output_tokens': 12 * OUTPUT_CAP}
        bound = {'probe': 'anchor-order-v1', 'code_sha256': code_hash(),
                 **prompt_metadata(prompt_profile), 'model': cfg['model'],
                 'url': cfg.get('url'), 'jobs_url': cfg.get('jobs_url'),
                 'mode': 'execute' if execute else 'mock' if mock else 'prepare',
                 'concurrency': concurrency, 'budget': budget,
                 'payload_sha256': [j['payload_sha256'] for j in jobs]}
        identity = fingerprint(bound)
        _atomic(root / 'workload.json', {'identity': identity, 'binding': bound, 'jobs': jobs,
                                        'synthetic': True, 'semantic_quality': 'not_assessed'})
        report = {'artifact_type': 'AUAnchorOrderProbe', 'identity': identity, 'binding': bound,
                  **prompt_metadata(prompt_profile), 'status': 'prepared',
                  'network_executed': False, 'semantic_quality': 'not_assessed',
                  'grammar_compile': 'not_checked', 'endpoint_constraint_status': 'not_executed',
                  'exit_gate': 'execute requires complete protocol and observed_valid_positive for all six cases; count mismatch reported separately',
                  'logical_requests': 0, 'transport_POST_attempts': 0, 'provider_POST_attempts': 0,
                  'results': [], 'budget': budget}
        if prompt_profile == 'primary_support_v1':
            report['nonempty_support_observed'] = None
            report['exit_gate'] += '; nonempty support observation reported separately, not a constraint or exit gate'
        if execute or mock:
            if mock:
                cfg.update(token='local-mock', job_poll_seconds=.001, job_wait_seconds=10)
                opener = MockJobs(jobs, delay=0, response_factory=_mock_response)
            ledger = {'identity': identity, 'binding': bound, 'jobs': {}, 'attempts': [],
                      'provider_attempts': 0, 'get_polls': 0,
                      'reserved_input_tokens': 0, 'reserved_output_tokens': 0}
            accounting = Accounting(root, ledger, budget, opener)
            accounting.save()
            started = clock()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                receipts = list(pool.map(lambda j: _worker(j, accounting, cfg, clock, sleep), jobs))
            for job, receipt in zip(jobs, receipts):
                value = receipt.get('normalized')
                positive = bool(value and value['decision'] == 'positive' and value['anchors'])
                actual = len(value['anchors']) if value else None
                count_match = actual == job['expected_count'] if value else None
                report['results'].append({
                    'case': job['probe_case'], 'request_id': job['request_id'],
                    'payload_sha256': job['payload_sha256'], 'status': receipt['status'],
                    'error': receipt.get('error'), 'error_code': receipt.get('error_code'),
                    'expected_count': job['expected_count'], 'actual_count': actual,
                    'count_match': count_match,
                    'instruction_status': 'matched' if positive and count_match else
                        'mismatch' if value else 'not_assessed',
                    'constraint_status': ('observed_valid_positive' if positive else
                        'inconclusive' if value else 'not_assessed') if execute else 'not_assessed_mock',
                    'usage': receipt.get('usage'), 'usage_state': receipt['usage_state'],
                    'latency_ms': receipt['latency_ms']})
                if prompt_profile == 'primary_support_v1':
                    report['results'][-1]['nonempty_support_observed'] = (
                        bool(positive and all(a['supporting_ref_ids'] for a in value['anchors']))
                        if value else None)
            snap = accounting.snapshot()
            rows = report['results']
            if prompt_profile == 'primary_support_v1':
                report['nonempty_support_observed'] = all(
                    r['nonempty_support_observed'] is True for r in rows)
            valid = all(r['status'] == 'verified' for r in rows)
            challenged = all(r['constraint_status'] == 'observed_valid_positive' for r in rows)
            known = [r['usage'] for r in rows if r['usage'] is not None]
            subtotal = {k: sum(u.get(k, 0) for u in known)
                        for k in ('input_tokens', 'output_tokens', 'total_tokens')}
            # Prior unknown attempts cannot be explained by a later accepted generation.
            unknown_attempts = sum(a.get('usage') is None and not a.get('provably_not_accepted')
                                   and not (not any(b['job_id'] == a['job_id'] for b in snap['attempts'][i+1:])
                                            and any(j['payload_sha256'] == a['job_id'] and r['usage'] is not None
                                                    for j, r in zip(jobs, rows)))
                                   for i, a in enumerate(snap['attempts']))
            unknown_jobs = sum(r['usage'] is None for r in rows)
            report.update(status='complete' if valid else 'incomplete', network_executed=bool(execute),
                endpoint_constraint_status=('observed_valid_positive' if challenged else 'inconclusive')
                    if execute else 'not_assessed_mock',
                logical_requests=len(snap['jobs']), transport_POST_attempts=len(snap['attempts']),
                provider_POST_attempts=len(snap['attempts']) if execute else 0,
                GET_polls=snap['get_polls'], reserved_input_utf8_bytes=snap['reserved_input_tokens'],
                reserved_output_tokens=snap['reserved_output_tokens'], unknown_usage_jobs=unknown_jobs,
                unknown_provider_attempts=unknown_attempts if execute else 0,
                known_provider_usage_observed_subtotal=subtotal,
                total_provider_usage=subtotal if execute and unknown_jobs == unknown_attempts == 0 else None,
                elapsed_wall_ms=round((clock()-started)*1000, 3),
                POST_ack_latency_ms=sum(a.get('latency_ms', 0) for a in snap['attempts']),
                instruction_mismatches=sum(r['instruction_status'] == 'mismatch' for r in rows))
        _atomic(root / 'probe.json', report)
        return report
    finally:
        lock.unlink()
