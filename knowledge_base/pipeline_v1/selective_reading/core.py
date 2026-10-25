"""Manifest, finite planner and extraction identities for the EXACT30 pilot."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from ..bulk_execution import core as bulk
from ..concurrency_benchmark import core as bench
from ..milestone1.core import digest
from ..au_compact import runner, decoding
from ..au_compact.core import COMPACT_SCHEMA, COMPACT_TRANSPORT_SCHEMA
from ..au_compact.jobs_client import payload_digest
from .catalog import POLICY, CUES, previews

VERSION = 'selective-reading-exact30-v1'
CAPS = {'prompt_utf8_bytes': 11488, 'output_tokens': 800,
        'input_estimate_bytes': 200000, 'actual_input_tokens': 100000,
        'actual_output_tokens': 30000, 'requests_H': 30, 'requests_P': 35,
        'initial_targets_per_case': 3, 'replans_per_case': 1,
        'context_expansions_per_case': 1, 'context_chars': 1200}
PLANNER_PROMPT = ('Select source regions to read for legal AuthorityUnit extraction. '
    'These are navigation previews, not assessed evidence or legal conclusions. '
    'Consider all offered finite IDs, including regions without citations/headings. '
    'Return exactly the constrained JSON with distinct selected navigation IDs. '
    'Do not produce AU evidence, summaries or invented IDs. ')


def build_manifest(parent_bulk, workload_id, seed=20261013):
    if not isinstance(workload_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', workload_id):
        raise ValueError('invalid_workload_id')
    if type(seed) is not int:
        raise ValueError('invalid_seed')
    if parent_bulk.get('version') != bulk.VERSION:
        raise ValueError('full_bulk_manifest_required')
    universe = parent_bulk.get('parent', {}).get('requests', [])
    if len(universe) != 30 or Counter(q['case_id'] for q in universe) != Counter({c: 6 for c in bench.CASES}):
        raise ValueError('exact30_five_cases_six_targets_required')
    if len({q['request_id'] for q in universe}) != 30 or len({q['expected_target_ids'][0] for q in universe}) != 30:
        raise ValueError('duplicate_universe_identity')
    if parent_bulk != bulk.build_manifest(parent_bulk['parent'], workload_id=parent_bulk.get('workload_id')):
        raise ValueError('invalid_parent_bulk_identity')
    return {'version': VERSION, 'workload_id': workload_id, 'seed': seed,
            'parent': copy.deepcopy(parent_bulk), 'parent_sha256': digest(parent_bulk),
            'universe_sha256': digest(universe), 'model': bench.MODEL, 'policy': POLICY,
            'caps': copy.deepcopy(CAPS), 'semantic_quality_claim': False}


def prepare(manifest, source_store, atom_root):
    if manifest != build_manifest(manifest['parent'], manifest['workload_id'], manifest['seed']):
        raise ValueError('selective_manifest_identity_mismatch')
    tasks = bench.prepare(manifest['parent']['parent'], source_store=source_store, atom_root=atom_root)
    for case in sorted(bench.CASES):
        items = sorted([t for t in tasks if t['request']['case_id'] == case],
                       key=lambda t: min(r['start_char'] for r in t['request']['source_refs'] if r['role'] == 'target'))
        for ordinal, task in enumerate(items):
            q = task['request']
            task['navigation'] = {
                'navigation_id': 'nav-'+digest([manifest['universe_sha256'], q['request_id']])[:24],
                'original_request_id': q['request_id'], 'case_id': case, 'source_hash': q['source_hash'],
                'ordinal': ordinal, 'region_id': q['region_id'],
                'parent_block_id': q.get('provenance', {}).get('parent_block_id'),
                'target_spans': [copy.deepcopy(r) for r in q['source_refs'] if r['role'] == 'target'],
                'real_heading_ref': None, 'previews': previews(task), 'source_assessed': False}
            # Validate both arms' initial extraction payloads locally.
            for arm in ('H', 'P'):
                extraction_task(task, manifest, arm, 'initial')
    return tasks


def host_selection(tasks, seed, case_id):
    items = [t for t in tasks if t['request']['case_id'] == case_id]
    def rank(t):
        text = ' '.join(p['quote'] for p in t['navigation']['previews'])
        return (-len(CUES.findall(text)), t['navigation']['ordinal'])
    priority = [t['navigation']['navigation_id'] for t in sorted(items, key=rank)[:2]]
    return priority + [discovery(items, priority, seed, case_id)]


def discovery(tasks, selected, seed, case_id):
    available = [t['navigation']['navigation_id'] for t in tasks
                 if t['request']['case_id'] == case_id and t['navigation']['navigation_id'] not in selected]
    if not available:
        raise ValueError('discovery_has_no_unselected_option')
    return min(available, key=lambda nav: digest([POLICY, seed, case_id, nav]))


def _payload(prompt, grammar):
    # Account complete message framing and EBNF in the conservative byte cap.
    value = {'model': bench.MODEL, 'messages': [{'role': 'user', 'content': prompt}],
             'temperature': 0, 'max_tokens': 800, **grammar,
             'chat_template_kwargs': {'enable_thinking': False}}
    # Existing AU cap measures full prompt + conservative chat framing; grammar
    # is separately recorded as transport bytes (it is not model prompt text).
    size = len(prompt.encode('utf-8')) + 128
    if size > CAPS['prompt_utf8_bytes']:
        raise ValueError('selective_prompt_ceiling_exceeded')
    return value, size


def extraction_task(task, manifest, arm, phase):
    q = copy.deepcopy(task['request'])
    original = next(r for r in manifest['parent']['parent']['requests'] if r['request_id'] == q['request_id'])
    q['request_id'] = 'sel-'+digest({'manifest': digest(manifest), 'arm': arm, 'phase': phase,
                                    'request': q, 'catalog': task['catalog']['atoms']})[:24]
    atoms = task['catalog']['atoms']
    rendered = runner._render(q, task['catalog'])
    payload, estimate = _payload(runner.build_prompt(q, rendered),
        decoding.build_decoding(q['request_id'], q['expected_target_ids'][0], atoms,
            [a for a, item in atoms.items() if item['target_intersecting']], string_mode='host_validated'))
    return {**task, 'rendered': rendered, 'effective': q, 'original_request': original, 'kind': 'extraction',
            'phase': phase, 'estimate': estimate,
            'capsule': {'job_id': payload_digest(payload), 'payload': payload}}


def planner_task(manifest, case_id, overview, *, phase='plan', excluded=(), trigger=None):
    options = [o for o in overview['options'] if o['navigation_id'] not in excluded]
    count = 2 if phase == 'plan' else 1
    ids = sorted(o['navigation_id'] for o in options)
    if len(ids) < count:
        raise ValueError('planner_options_exhausted')
    rid = 'sel-plan-'+digest([digest(manifest), case_id, phase, overview, list(excluded), trigger])[:24]
    prefix = '{"request_id":'+json.dumps(rid)+',"case_id":'+json.dumps(case_id)+',"selected_ids":['
    # Six finite options: enumerate closed ordered pairs, never free JSON.
    outputs = []
    for i, nav in enumerate(ids):
        for nav2 in ids[i+1:] if count == 2 else [None]:
            outputs.append(prefix+','.join(json.dumps(v) for v in ([nav, nav2] if nav2 else [nav]))+']}')
    grammar = {'ebnf': 'root ::= '+' | '.join(json.dumps(o) for o in outputs)+'\n'}
    prompt = PLANNER_PROMPT+f'Choose exactly {count} IDs. REQUEST_ID={rid}\n'+json.dumps(
        {**overview, 'options': options, 'phase': phase, 'trigger': trigger}, ensure_ascii=False, separators=(',', ':'))
    payload, estimate = _payload(prompt, grammar)
    return {'kind': 'planner', 'phase': phase, 'case_id': case_id, 'effective': {'request_id': rid},
            'allowed_outputs': outputs, 'options': ids, 'estimate': estimate,
            'capsule': {'job_id': payload_digest(payload), 'payload': payload}}


def normalize_planner(job, task):
    receipt = {'usage': runner._usage(job.get('response') or {}), 'job_id': job['job_id'],
               'usage_state': 'unavailable', 'server_status': job['status'],
               'server_timing': {k: job.get(k) for k in ('created_at', 'started_at', 'finished_at', 'inference_seconds')}}
    if receipt['usage'] is None and isinstance(job.get('usage'), dict):
        receipt['usage'] = runner._usage({'usage': job['usage']})
    receipt['usage_state'] = 'provider' if receipt['usage'] is not None else 'unavailable'
    row = {'request': task['effective'], 'original_request': None, 'kind': 'planner',
           'case_id': task['case_id'], 'phase': task['phase'], 'status': 'unresolved',
           'compact_response': None, 'response': None, 'receipt': receipt}
    try:
        if job['status'] != 'completed':
            raise ValueError('planner_provider_failure')
        choice = job['response']['choices'][0]
        raw = choice['message']['content']; receipt['raw_response'] = raw
        receipt['finish_reason'] = choice.get('finish_reason')
        if choice.get('finish_reason') != 'stop' or raw not in task['allowed_outputs']:
            raise ValueError('planner_closed_id_validation_failed')
        row.update(status='protocol_verified', response=json.loads(raw))
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        receipt['failure_diagnostic'] = {'kind': 'planner_validation_or_provider', 'error_type': type(exc).__name__,
                                         'outcome_unknown': job['status'] == 'interrupted'}
    return row


def fingerprints(manifest, tasks, arm, cfg):
    return {'version': VERSION, 'manifest_sha256': digest(manifest), 'universe_sha256': manifest['universe_sha256'],
            'arm': arm, 'model': bench.MODEL, 'policy': POLICY, 'seed': manifest['seed'],
            'endpoint_sha256': digest(cfg['url']), 'generation': {'thinking': False, 'temperature': 0, 'output': 800},
            'prompt': runner.prompt_identity(), 'planner_prompt_sha256': digest(PLANNER_PROMPT),
            'schema_sha256': hashlib.sha256(COMPACT_SCHEMA.read_bytes()).hexdigest(),
            'transport_schema_sha256': hashlib.sha256(COMPACT_TRANSPORT_SCHEMA.read_bytes()).hexdigest(),
            'decoder_sha256': hashlib.sha256(Path(decoding.__file__).read_bytes()).hexdigest(),
            'implementation_sha256': digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in Path(__file__).parent.glob('*.py')}),
            'render_version': runner.RENDER_VERSION, 'normalizer_version': runner.NORMALIZER_VERSION,
            'acceptance_policy': 'host_valid_semantic_review_pending_v1', 'ledger_revision': 1,
            'catalog_sha256': digest([{'navigation': t['navigation'], 'atoms': t['catalog']['atoms'],
                                       'binding': t['request']['atom_binding'], 'render_sha256': digest(t['rendered'])}
                                      for t in tasks])}


def run(manifest, cfg, arm, output_root, execute=False, **kwargs):
    from .runtime import run as execute_run
    return execute_run(manifest, cfg, arm, output_root, execute=execute, **kwargs)
