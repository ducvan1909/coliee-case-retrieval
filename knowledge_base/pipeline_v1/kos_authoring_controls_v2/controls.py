"""Contract-only revision of the nine frozen fictional v1 controls."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import argparse
from pathlib import Path

from ..kos_authoring_controls import controls as v1
from ..kos_authoring_controls import execution
from ..k0_authoring import token_budget

old, encode = v1.old, v1.encode
REASONS, NEGATIVE = v1.REASONS, v1.NEGATIVE
VERSION = 'kos-authoring-controls-v2'
WIRE_VERSION = 'kos-authoring-wire-v2-host-assessment'
WORKLOAD_VERSION = 'kos-contract-v2-nine-frozen-controls-20261024'
PARENT = Path(v1.__file__).resolve().parents[1] / 'outputs/kos_authoring_controls_20261024'
PARENT_MANIFEST_SHA256 = '5b482208bf5ecfc77cf6a176fbdd8a7f2dcb94493fa7caa83d8efbbf23f2b090'
DEFAULT_ROOT = PARENT.parent / 'kos_contract_v2_20261024_ready'


def code_hash():
    return old.fingerprint({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(Path(__file__).parent.glob('*.py'))})


def frozen_manifest():
    path = PARENT / 'input/manifest.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != PARENT_MANIFEST_SHA256:
        raise ValueError('frozen v1 manifest changed')
    m = old.load(path)
    if (m['sha256'] != old.fingerprint({k: v for k, v in m.items() if k != 'sha256'})
            or m['code_sha256'] != v1.code_hash() or m['K0_code_sha256'] != old.code_hash()):
        raise ValueError('frozen v1 code/manifest mismatch')
    return m


def grammar(eids, sids):
    # Keep all AU/action productions, including nullable kinds and replacement.
    root = r'root ::= "{" "\"aus\":" aus "," "\"empty_reason\":" empty-reason "," "\"next_action\":" action "}"'
    return '\n'.join(root if line.startswith('root ::=') else line
                     for line in v1.grammar(eids, sids, True).splitlines()
                     if not line.startswith('scopes ::=')) + '\n'


def demonstrations():
    # Exact v1 texts and AU contents; remove only the obsolete envelope field.
    lines = []
    for line in v1.demonstrations(True, True).splitlines():
        if line.startswith('JSON: '):
            value = json.loads(line[6:])
            del value['assessed_scope_ids']
            line = 'JSON: ' + encode(value)
        lines.append(line)
    return '\n'.join(lines) + '\n'


def final_instructions():
    text = v1.final_instructions()
    replacements = {
        'aus (possibly empty), assessed_scope_ids, next_action':
            'aus (possibly empty), empty_reason, next_action',
        'Mark only fully assessed supplied scope IDs. ': '',
        'or uncertain, assessed_scope_ids empty, and finish_case needs_context.':
            'or uncertain, and finish_case needs_context.',
    }
    for before, after in replacements.items():
        if text.count(before) != 1:
            raise ValueError('frozen instruction anchor changed')
        text = text.replace(before, after)
    return text + ('Host records delivered/read scopes and assessment from the supplied catalog and your action. '
        'Return only the three envelope fields shown. Navigation makes no assessment. '
        'If some supplied scopes are facts but another lacks required context, treat the whole active '
        'set as uncertain, not as a negative assessment. insufficient_context and uncertain never '
        'complete work. finish_case needs_context leaves all active scopes unresolved, even with AUs.\n')


def balanced_jobs(cfg=None):
    """Copy the frozen workload, changing only instructions/examples/wire."""
    rows = copy.deepcopy(frozen_manifest()['balanced_jobs'])
    prefix = v1.final_instructions() + v1.demonstrations(True, True)
    for row in rows:
        payload, job = row['payload'], row['validation_job']
        if cfg is not None and payload['model'] != cfg['model']:
            raise ValueError('frozen model mismatch')
        text = payload['messages'][0]['content']
        if not text.startswith(prefix):
            raise ValueError('frozen prompt prefix mismatch')
        payload['messages'][0]['content'] = final_instructions() + demonstrations() + text[len(prefix):]
        payload['ebnf'] = grammar(list(job['catalog']['evidence']), job['allowed_scope_ids'])
        job.update(payload=copy.deepcopy(payload), payload_sha256=old.fingerprint(payload),
                   input_reservation=old.input_reservation(payload))
    if len(rows) != 9:
        raise ValueError('exactly nine frozen jobs required')
    return rows


def validate(value, job):
    """Translate exact v2 wire to K0 validation; retain per-AU errors/warnings.

    active_scope_ids is the host's delivered catalog selection, never model input.
    Completion is an author self-report, not semantic coverage or correctness.
    """
    if not isinstance(value, dict) or set(value) != {'aus', 'empty_reason', 'next_action'}:
        raise ValueError('exact v2 turn keys required')
    reason, action, aus = value['empty_reason'], value['next_action'], value['aus']
    if reason is not None and (not isinstance(reason, str) or reason not in REASONS):
        raise ValueError('invalid empty reason')
    if not isinstance(aus, list) or not isinstance(action, dict):
        raise ValueError('invalid AU list/action')
    if aus and reason is not None:
        raise ValueError('positive with empty reason')
    active = list(dict.fromkeys(job['active_scope_ids']))
    if (not job['catalog']['evidence'] or not active
            or not set(active) <= set(job['allowed_scope_ids'])):
        raise ValueError('invalid delivered catalog selection')
    terminal = action.get('tool') == 'finish_case'
    complete = terminal and action.get('reason') == 'work_scope_complete'
    if complete and reason in REASONS[3:]:
        raise ValueError('uncertain cannot complete work')
    if terminal and not aus and reason is None:
        raise ValueError('empty terminal assessment requires reason')
    assessed = active if complete and (aus or reason in NEGATIVE) else []
    normalized = old.validate_response({'aus': aus, 'assessed_scope_ids': assessed,
                                        'next_action': action}, job)
    # Invalid proposals retain K0's partial AU/error behavior, but cannot certify work.
    if normalized['au_errors']:
        assessed = []
    normalized.update(assessed_scope_ids=assessed, delivered_scope_ids=active,
        read_scope_ids=active, unresolved_scope_ids=[] if assessed else active,
        empty_reason=reason, work_scope_complete=bool(assessed),
        assessment_basis='author_self_report' if terminal else None,
        assessment_result=('has_au' if aus else 'no_au_candidate') if assessed
                          else ('uncertain' if terminal else None),
        semantic_quality='not_assessed')
    return normalized


def cpu_bundle(jobs):
    bundle = v1.cpu_bundle(jobs, True)
    for row in bundle['jobs']:
        positives = []
        for text in row['positive_examples']:
            value = json.loads(text)
            del value['assessed_scope_ids']
            positives.append(value)
        bad_id = copy.deepcopy(positives[0])
        bad_id['aus'][0]['evidence_ids'] = ['not-in-catalog']
        bad_field = dict(positives[0], assessed_scope_ids=[])
        bad_scope = {'aus': [], 'empty_reason': None,
                     'next_action': {'tool': 'open_region', 'scope_ids': ['not-in-catalog']}}
        row.update(positive_examples=[encode(v) for v in positives],
                   negative_examples=[encode(v) for v in (bad_id, bad_field, bad_scope)])
    return bundle


def dependency_bindings():
    files = [*Path(v1.__file__).parent.glob('*.py'), Path(old.__file__),
             Path(token_budget.__file__), Path(execution.complete_job.__code__.co_filename),
             Path(sys.modules[execution.ReadinessGate.__module__].__file__)]
    files += [Path(v1.binding.__code__.co_filename),
              Path(v1._atomic.__code__.co_filename),
              Path(__file__).resolve().parents[1] / 'experiments/k0_grammar_cpu_probe.py']
    return [v1.binding(p) for p in sorted(set(files))]


def parent_bindings():
    return [v1.binding(p) for p in sorted(PARENT.rglob('*')) if p.is_file()]


def runtime_identity(cfg=None):
    """Local K0 profile gate; never serialize the runtime config or credential."""
    if cfg is None:
        cfg, _, _ = v1.study_config(argparse.Namespace())
    workload = v1.PARENT / 'input/workload.json'
    old.preflight(workload, cfg=cfg)
    profile = old.profile(old.load(workload), cfg)
    return {key: profile[key] for key in ('model', 'url', 'jobs_url', 'enable_thinking',
                                         'transport', 'string_decoder', 'expected_model_revision')}


def _manifest():
    identity = runtime_identity()
    frozen = frozen_manifest()
    jobs = balanced_jobs()
    reserve = sum(old.input_reservation(r['payload']) + 800 for r in jobs)
    if reserve > 30000 or any(old.input_reservation(r['payload']) > 6000 for r in jobs):
        raise ValueError('frozen workload exceeds reserve')
    bundle = cpu_bundle(jobs)
    m = {'version': VERSION, 'wire_version': WIRE_VERSION, 'workload_version': WORKLOAD_VERSION,
         'code_sha256': code_hash(), 'v1_code_sha256': v1.code_hash(),
         'K0_code_sha256': old.code_hash(), 'dependency_bindings': dependency_bindings(),
         'identity': identity,
         'parent_manifest_sha256': frozen['sha256'], 'parent_bindings': parent_bindings(),
         'jobs': jobs, 'workload_sha256': old.fingerprint(jobs),
         'wire_sha256': old.fingerprint([r['payload']['ebnf'] for r in jobs]),
         'cpu_bundle_sha256': old.fingerprint(bundle), 'counter': token_budget.counter_identity(),
         'max_POST_attempts': 12, 'max_total_tokens': 30000,
         'reserved_input_and_output_tokens': reserve, 'semantic_quality': 'semantic_review_pending',
         'corpus_dispatch_allowed': False}
    m['sha256'] = old.fingerprint(m)
    return m


def guard_root(root):
    root = Path(root).resolve()
    old.guard_output(root, [PARENT, v1.PARENT, v1.BASELINE,
                           Path(old.__file__).parent, Path(v1.__file__).parent,
                           Path(__file__).parent])
    return root


def prepare(root):
    root = guard_root(root)
    if root.exists():
        raise ValueError('fresh root required')
    m = _manifest()
    v1._atomic(root / 'input/manifest.json', m)
    v1._atomic(root / 'input/cpu_balanced.json', cpu_bundle(m['jobs']))
    return m


def preflight(root):
    root = guard_root(root)
    m = old.load(root / 'input/manifest.json')
    if m != _manifest():
        raise ValueError('exact manifest/code/parent/workload binding changed')
    if old.load(root / 'input/cpu_balanced.json') != cpu_bundle(m['jobs']):
        raise ValueError('CPU bundle binding changed')
    return {'status': 'pass', 'model_requests_planned': 9, 'max_POST_attempts': 12,
            'max_total_tokens': 30000,
            'reserved_input_and_output_tokens': m['reserved_input_and_output_tokens'],
            'inference': 0, 'semantic_quality': 'semantic_review_pending'}
