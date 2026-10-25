"""Durable intent/reservation/receipt/commit loop on the existing BULK app."""
from __future__ import annotations

import copy
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from ..milestone1.core import ROOT, load, digest
from ..bulk_execution.core import validate_progress, normalize_receipt
from ..bulk_execution.storage import write_json
from ..bulk_execution.transport import GroupTransport, GroupTransportError, group_id
from ..concurrency_benchmark import core as bench
from ..au_only.core import warmup
from .core import (VERSION, CAPS, prepare, fingerprints, host_selection, discovery,
                   planner_task, extraction_task, normalize_planner)
from .catalog import get_case_overview, read_region, find_source, expand_context


class Halt(ValueError):
    pass


GUARD_COMPAT_IMPLEMENTATION = '63c303b09454273b78488f552d8738ccf0cf4eb9ef33721a003eec302f4b1e68'


def _resume_guard(state, identity, requested_cap):
    """One explicit guard-only migration; reader/selector/source settings stay fixed."""
    if type(requested_cap) is not int or not CAPS['input_estimate_bytes']<requested_cap<=300000:
        raise ValueError('invalid_resume_estimate_guard')
    old=copy.deepcopy(state['identity']);new=copy.deepcopy(identity)
    old_hash=old.pop('implementation_sha256',None);new_hash=new.pop('implementation_sha256',None)
    cost=_budget(state)
    if (old!=new or (old_hash!=new_hash and old_hash!=GUARD_COMPAT_IMPLEMENTATION)
        or state.get('stop_reason')!='budget_exhausted' or state.get('finished')
        or cost['pending_or_unknown_requests'] or cost['usage_unavailable']
        or any(not g.get('finished') for g in state['groups'].values())):
        raise ValueError('guard_resume_identity_or_state_mismatch')
    state.setdefault('guard_override_history',[]).append({'from_estimate_bytes':CAPS['input_estimate_bytes'],
        'to_estimate_bytes':requested_cap,'old_implementation_sha256':old_hash,
        'new_implementation_sha256':new_hash,'reason':'conservative_estimate_guard_only',
        'source_model_prompt_schema_policy_unchanged':True,
        'actual_input_token_cap_unchanged':CAPS['actual_input_tokens']})
    state['effective_input_estimate_bytes']=requested_cap
    state['identity']=identity


def _usage_valid(value):
    return (isinstance(value, dict) and all(type(value.get(k)) is int and value[k] >= 0
            for k in ('input_tokens', 'output_tokens', 'total_tokens'))
            and value['total_tokens'] == value['input_tokens']+value['output_tokens'])


def _budget(state):
    reservations = [t for g in state['groups'].values() for t in g['reservations']]
    rows = state['rows']
    usage = [r['receipt'].get('usage') for r in rows.values()]
    return {'requests': len(reservations), 'provider_attempts_reserved': len(reservations),
            'input_estimate_bytes': sum(t['estimate'] for t in reservations),
            'reserved_output_tokens': len(reservations)*800,
            'tokens': {k: sum(u[k] for u in usage if _usage_valid(u))
                      for k in ('input_tokens', 'output_tokens', 'total_tokens')},
            'usage_unavailable': sum(not _usage_valid(u) for u in usage),
            'pending_or_unknown_requests': len(reservations)-len(rows),
            'estimate_method': 'utf8_prompt_bytes_plus128_not_provider_usage'}


def _flags(row):
    compact = row.get('compact_response')
    if not isinstance(compact, dict):
        return []
    aus = compact.get('aus')
    flags = sorted({f for au in (aus if isinstance(aus, list) else []) if isinstance(au, dict)
                    for f in (au.get('needs_context') if isinstance(au.get('needs_context'), list) else [])
                    if isinstance(f, str)})
    if compact.get('unresolved_reason') in ('needs_context', 'insufficient_context', 'ambiguous_speaker') and not flags:
        flags = ['cross_block_context']
    return flags


def _commit(state, job, task):
    key = task['capsule']['job_id']
    if key in state['rows']:
        if state['rows'][key].get('job_receipt') != job:
            raise ValueError('committed_receipt_changed')
        return  # Idempotent assessment/cost commit, including interval axes.
    if task['kind'] == 'planner':
        row = normalize_planner(job, task)
    else:
        row = normalize_receipt(job, task)
        row['original_request'] = task['original_request']
        row.update(kind='extraction', phase=task['phase'], publication_status='semantic_review_pending',
                   host_valid=row['status'] == 'protocol_verified',
                   catalog_sha256=digest(task['catalog']['atoms']),
                   source_provenance={'source_hash': task['effective']['source_hash'],
                                      'atom_binding': task['effective']['atom_binding'],
                                      'source_refs': task['effective']['source_refs']})
        q = task['effective']
        # Renderer sends whole atoms; canonical assessment remains raw TARGET.
        for atom in task['catalog']['atoms'].values():
            state['delivery_intervals'].append({'request_id': q['request_id'],
                'case_id': q['case_id'], 'source_hash': q['source_hash'],
                'start_char': atom['start_char'], 'end_char': atom['end_char'],
                'role': 'target_with_padding' if atom['target_intersecting'] else 'context',
                'delivery_state': 'completed' if job['status'] == 'completed' else 'unconfirmed',
                'assessment_implied': False})
        compact = row.get('compact_response')
        compact = compact if isinstance(compact, dict) else {}
        assessed = (row['status'] == 'protocol_verified' and compact.get('coverage_status') == 'complete'
                    and compact.get('decision') in ('positive', 'hard_negative') and not _flags(row))
        for ref in q['source_refs']:
            if ref['role'] != 'target':
                continue
            state['assessment_intervals'].append({**ref, 'case_id': q['case_id'],
                'source_hash': q['source_hash'], 'request_id': q['request_id'],
                'original_request_id': task['original_request']['request_id'],
                'state': ('assessed_with_AU' if compact.get('decision') == 'positive' else 'assessed_without_AU')
                         if assessed else 'unresolved',
                'publication_status': 'semantic_review_pending'})
        original = task['original_request']['request_id']
        state['unresolved_obligations'] = [o for o in state['unresolved_obligations']
                                          if o['original_request_id'] != original]
        if not assessed:
            state['unresolved_obligations'].append({'original_request_id': original,
                'case_id': q['case_id'], 'flags': _flags(row), 'status': 'unresolved',
                'reason': row.get('receipt',{}).get('failure_diagnostic',{}).get('kind')
                          or compact.get('unresolved_reason') or compact.get('coverage_status') or 'provider_or_host_failure'})
    row['provider_response'] = job.get('response')
    row['job_receipt'] = job
    row['estimate_bytes'] = task['estimate']
    state['rows'][key] = row


def _endpoint(cfg):
    parsed = urlsplit(cfg.get('url', ''))
    if (parsed.scheme != 'https' or parsed.path != '/v1/chat/completions' or parsed.username
        or parsed.password or parsed.port or parsed.query or parsed.fragment or not re.fullmatch(
            r'[a-z0-9-]+--coliee-qwen35-9b-bulk-server\.(?:[a-z0-9.-]+\.modal\.direct|modal\.run)', parsed.hostname or '')):
        raise ValueError('isolated_bulk_endpoint_required')
    if cfg.get('model') != bench.MODEL or cfg.get('enable_thinking') is not False:
        raise ValueError('selective_model_or_thinking_changed')


def _output_root(root, source_store, atom_root, manifest):
    root = Path(root).resolve()
    forbidden = [Path(source_store).resolve(), Path(atom_root).resolve(),
                 ROOT/'outputs/bulk_trial30_20261013']
    if any(root == p or root.is_relative_to(p) for p in forbidden):
        raise ValueError('historical_or_source_output_root_forbidden')
    if any((root/f).exists() for f in ('runtime_ledger.json', 'identity.json', 'probe_identity.json', 'execution_identity.json')):
        raise ValueError('historical_output_root_forbidden')
    if (root/'run.json').exists() and load(root/'run.json').get('version') != VERSION:
        raise ValueError('historical_output_root_forbidden')
    if (root/'manifest.json').exists() and load(root/'manifest.json') != manifest:
        raise ValueError('output_manifest_conflict')
    return root


def run(manifest, cfg, arm, output_root, execute=False, *,
        source_store=ROOT/'outputs/source_store_v1', atom_root=ROOT/'outputs/plan04_sentence_atoms_v1',
        transport=None, capability_fetch=None, warmup_fn=None, policy=None,
        clock=time.monotonic, sleep=time.sleep, resume_input_estimate_bytes=None):
    if not execute:
        raise ValueError('selective_requires_execute')
    if arm not in ('H', 'P'):
        raise ValueError('invalid_selective_arm')
    _endpoint(cfg)
    start = clock()
    injected = any(v is not None for v in (transport, capability_fetch, warmup_fn))
    tasks = prepare(manifest, source_store, atom_root)
    root = _output_root(output_root, source_store, atom_root, manifest)
    root.mkdir(parents=True, exist_ok=True)
    lock = root/'selective.lock'
    try:
        handle = lock.open('x'); handle.close()
    except FileExistsError:
        raise ValueError('selective_locked_manual_recovery_required') from None
    try:
        identity = fingerprints(manifest, tasks, arm, cfg)
        identity['execution_evidence'] = 'mock/injected' if injected else 'real_provider'
        path = root/'state.json'
        resumed = path.exists()
        if resumed:
            state = load(path)
            if resume_input_estimate_bytes is not None:
                if arm!='P':raise ValueError('guard_resume_requires_P')
                _resume_guard(state,identity,resume_input_estimate_bytes)
                write_json(path,state)
            elif state.get('identity') != identity:
                raise ValueError('selective_resume_identity_mismatch')
        else:
            if resume_input_estimate_bytes is not None:raise ValueError('guard_resume_requires_existing_checkpoint')
            state = {'identity': identity, 'groups': {}, 'rows': {}, 'selections': {},
                'exposure_intervals': [{**p, 'navigation_id': t['navigation']['navigation_id'],
                                        'exposure_kind': 'host_local_preview', 'source_assessed': False}
                                       for t in tasks for p in t['navigation']['previews']],
                'delivery_intervals': [], 'assessment_intervals': [],
                'unresolved_obligations': [], 'context_searches': {}, 'stop_reason': None,
                'warmup': None, 'transport_history': []}
            write_json(path, state)
        transport = transport or GroupTransport(cfg)
        policy = policy or {'max_attempts': 10, 'max_wait_seconds': 600}
        setup_end = clock(); began = setup_end
        allow_new_admission = True

        def save():
            state['cost_ledger'] = _budget(state)
            write_json(path, state)

        def dispatch(batch):
            nonlocal resumed
            if not batch:
                return []
            jobs = [t['capsule'] for t in batch]
            gid = group_id('bulk', jobs)
            existing = gid in state['groups']
            by_job = {t['capsule']['job_id']: t for t in batch}
            if not existing:
                if not allow_new_admission:
                    raise Halt('backend_unavailable_new_admission_forbidden')
                cost = _budget(state)
                if cost['usage_unavailable'] or cost['pending_or_unknown_requests']:
                    raise Halt('unknown_usage_or_pending_fail_closed')
                estimate = sum(t['estimate'] for t in batch)
                if (cost['requests']+len(batch) > CAPS['requests_'+arm]
                    or cost['input_estimate_bytes']+estimate > state.get('effective_input_estimate_bytes',CAPS['input_estimate_bytes'])
                    or cost['tokens']['input_tokens']+estimate > CAPS['actual_input_tokens']
                    or cost['tokens']['output_tokens']+800*len(batch) > CAPS['actual_output_tokens']):
                    raise Halt('budget_exhausted')
                state['groups'][gid] = {'group_id': gid, 'cursor': 0, 'finished': False,
                    'reservations': [{'job_id': t['capsule']['job_id'], 'estimate': t['estimate'],
                        'kind': t['kind'], 'request_id': t['effective']['request_id']} for t in batch],
                    'jobs': jobs, 'remote_job_state': 'reserved'}
                save()  # Reservation is durable before POST; never roll it back.
            group = state['groups'][gid]
            if group['jobs'] != jobs:
                raise ValueError('reservation_payload_changed')
            if group['finished']:
                return [state['rows'][j['job_id']] for j in jobs]
            deadline = clock()+cfg.get('job_wait_seconds', 1800)
            if existing:
                # GET only, including 404: unknown admission is never redispatched.
                ack = transport.progress('bulk', gid, group['cursor'], remaining=max(.001, deadline-clock()))
                resumed = True
            else:
                ack, recovered = transport.admit('bulk', jobs, resume=False)
                resumed |= recovered
            if ack.get('group_id') != gid or ack.get('mode') != 'bulk':
                raise Halt('group_ack_identity_mismatch')
            group['remote_job_state'] = 'acknowledged'; save()
            while not group['finished']:
                if clock() >= deadline:
                    raise Halt('group_wait_timeout_unknown')
                progress = (ack if 'results' in ack and ack.get('cursor') == group['cursor'] else
                            transport.progress('bulk', gid, group['cursor'], remaining=deadline-clock()))
                ack = {}
                rows = validate_progress(progress, gid=gid, mode='bulk', after=group['cursor'], expected_ids=set(by_job))
                for job in rows:
                    jid = job['job_id']
                    if jid in state['rows']:
                        raise Halt('duplicate_terminal_event')
                    # Raw receipt precedes atomic assessment/ledger/cost commit.
                    write_json(root/'receipts'/(jid+'.json'), job)
                    _commit(state, job, by_job[jid])
                group['cursor'] = progress['next_cursor']
                group['finished'] = all(j['job_id'] in state['rows'] for j in jobs)
                group['server_counts'] = progress['counts']
                save()
                if progress.get('status') in ('paused', 'blocked', 'interrupted') and not group['finished']:
                    raise Halt('backend_unknown_fail_closed')
                if not rows and not group['finished']:
                    sleep(min(cfg.get('job_poll_seconds', 2), max(0, deadline-clock())))
            return [state['rows'][j['job_id']] for j in jobs]

        def ensure_rows(rows):
            # A known local schema error stays unresolved for that target only.
            # Unknown backend outcome/usage still blocks ALL new admission.
            if any(r.get('receipt',{}).get('failure_diagnostic',{}).get('outcome_unknown')
                   or r.get('receipt',{}).get('failure_diagnostic',{}).get('kind')=='job_interrupted'
                   for r in rows):
                raise Halt('provider_outcome_unknown')
            if _budget(state)['usage_unavailable']:
                raise Halt('unknown_usage_fail_closed')
            cost = _budget(state)
            if (cost['tokens']['input_tokens'] > CAPS['actual_input_tokens']
                or cost['tokens']['output_tokens'] > CAPS['actual_output_tokens']):
                raise Halt('actual_budget_exceeded')

        def dispatch_many(batch):
            rows = []
            # Each logical batch remains independent; server schedules C4.
            # Commit actual usage before reserving the next bounded subgroup.
            for index in range(0, len(batch), 4):
                part = dispatch(batch[index:index+4])
                ensure_rows(part)
                rows.extend(part)
            return rows

        try:
            pending = any(not g['finished'] for g in state['groups'].values())
            if not state.get('finished') or pending:
                info = bench.wait_capability(cfg, capability_fetch or bench.capability, policy, root)
                write_json(root/'capability.json', info)
                required = {'experiment': 'au-bulk-v1', 'app': 'coliee-qwen35-9b-bulk',
                    'gateway_concurrency': 4, 'server_concurrency': 4, 'model': bench.MODEL,
                    'context_length': 12288, 'max_total_tokens': 12288, 'backend_retry': False,
                    'exclusive_probes': True, 'max_containers': 1}
                if any(info.get(k) != v for k, v in required.items()) or not info.get('capabilities', {}).get('bulk_submit'):
                    raise Halt('bulk_endpoint_capability_mismatch')
                allow_new_admission = (info.get('ready') is True and not any(
                    info.get(k) for k in ('poisoned', 'stopping', 'backend_outcome_unknown')))
                if not allow_new_admission and not pending:
                    raise Halt('backend_unavailable_new_admission_forbidden')
                if state['warmup'] is None:
                    state['warmup'] = {'status': 'reserved_unknown', 'usage': None}; save()
                    state['warmup'] = (warmup_fn or warmup)(cfg, policy, root/'warmup'); save()
                if state['warmup'].get('status') != 'success':
                    raise Halt('warmup_failed_or_unknown')
            setup_end = clock(); began = setup_end
            if arm == 'H':
                for case in sorted(bench.CASES):
                    state['selections'].setdefault(case, {'initial': host_selection(tasks, manifest['seed'], case),
                                                          'replanned': [], 'discovery': None})
                save()
            else:
                plans = [planner_task(manifest, case, get_case_overview(tasks, case)) for case in sorted(bench.CASES)]
                plan_rows = dispatch_many(plans)
                for case, row in zip(sorted(bench.CASES), plan_rows):
                    if row['status'] != 'protocol_verified':
                        state['selections'].setdefault(case, {'initial': [], 'discovery': None,
                            'replanned': [], 'planning_status': 'unresolved'})
                        continue
                    chosen = row['response']['selected_ids']
                    disc = discovery(tasks, chosen, manifest['seed'], case)
                    state['selections'].setdefault(case, {'initial': chosen+[disc], 'discovery': disc, 'replanned': []})
                save()
            initial = [extraction_task(read_region(tasks, nav), manifest, arm, 'initial')
                       for case in sorted(bench.CASES) for nav in state['selections'][case]['initial']]
            initial_rows = dispatch_many(initial)
            # Only committed assessments can trigger a next planning intent.
            replans = []
            if arm == 'P':
                for case in sorted(bench.CASES):
                    selected = state['selections'][case]
                    if not selected['initial'] or not selected.get('discovery'):
                        continue
                    case_rows = [r for r in initial_rows if r['original_request']['case_id'] == case]
                    disc_row = next(r for r in case_rows if r['original_request']['request_id'] ==
                                    read_region(tasks, selected['discovery'])['request']['request_id'])
                    discovery_value=disc_row.get('compact_response')
                    trigger = {'needs_context': any(_flags(r) for r in case_rows),
                               'discovery_positive': (disc_row['status']=='protocol_verified' and isinstance(discovery_value,dict)
                                                      and discovery_value.get('decision')=='positive')}
                    if any(trigger.values()):
                        replans.append(planner_task(manifest, case, get_case_overview(tasks, case),
                            phase='replan', excluded=selected['initial'], trigger=trigger))
                if replans:
                    rows = dispatch_many(replans)
                    for task, row in zip(replans, rows):
                        if row['status'] != 'protocol_verified':
                            state['selections'][task['case_id']]['replan_status']='unresolved'
                            continue
                        state['selections'][task['case_id']]['replanned'] = row['response']['selected_ids']
                    save()
                    rows = dispatch_many([extraction_task(read_region(tasks, nav), manifest, arm, 'replanned')
                                     for case in sorted(bench.CASES) for nav in state['selections'][case]['replanned']])
                    ensure_rows(rows)
            expansions = []
            for case in sorted(bench.CASES):
                obligations = [o for o in state['unresolved_obligations'] if o['case_id'] == case and o['flags']]
                # Reuse durable search selection even after expansion clears flags.
                search = state['context_searches'].get(case)
                if search is None and obligations:
                    obligation = sorted(obligations, key=lambda o: o['original_request_id'])[0]
                    task = next(t for t in tasks if t['request']['request_id'] == obligation['original_request_id'])
                    search = {**find_source(task, obligation['flags']),
                              'original_request_id': task['request']['request_id'], 'flags': obligation['flags']}
                    state['context_searches'][case] = search; save()
                if search and search['hits']:
                    task = next(t for t in tasks if t['request']['request_id'] == search['original_request_id'])
                    expansions.append(extraction_task(expand_context(task, search['hits']), manifest, arm, 'context'))
            if expansions:
                dispatch_many(expansions)
            state['finished'] = True; state['stop_reason'] = None; save()
        except (Halt, GroupTransportError, ValueError, OSError) as exc:
            state['stop_reason'] = exc.kind if isinstance(exc, GroupTransportError) else str(exc)
            if len(state['stop_reason']) > 100 or not re.fullmatch(r'[A-Za-z0-9_]+', state['stop_reason']):
                state['stop_reason'] = type(exc).__name__
            state['finished'] = False; save()
        state['transport_history'].append(copy.deepcopy(getattr(transport, 'stats', {}))); save()
        report = _report(manifest, arm, state, resumed, clock()-began, setup_end-start, clock()-start)
        report['execution_evidence'] = 'mock/injected' if injected else 'real_provider'
        report['performance_eligible'] = report['performance_eligible'] and not injected
        write_json(root/'run.json', report)
        return report
    finally:
        lock.unlink(missing_ok=True)


def _report(manifest, arm, state, resumed, wall, setup, total):
    universe = manifest['parent']['parent']['requests']
    original_ids = [q['request_id'] for q in universe]
    nav_ids = {nav for s in state['selections'].values() for nav in s['initial']+s['replanned']}
    selected = [q['request_id'] for q in universe if 'nav-'+digest([manifest['universe_sha256'], q['request_id']])[:24] in nav_ids]
    latest = {}
    for r in state['rows'].values():
        if r['kind'] == 'extraction':
            latest[r['original_request']['request_id']] = r
    def compact(rid):
        value = latest[rid].get('compact_response')
        return value if isinstance(value, dict) else {}
    assessed = [rid for rid in selected if rid in latest and latest[rid]['status'] == 'protocol_verified'
                and compact(rid).get('coverage_status') == 'complete'
                and compact(rid).get('decision') in ('positive', 'hard_negative')
                and not _flags(latest[rid])]
    cost = _budget(state)
    selective = bool(state.get('finished') and all(len(s['initial'])==3 and s.get('replan_status')!='unresolved'
                                                 for s in state['selections'].values())
                     and len(state['selections'])==5 and not state['unresolved_obligations'] and set(assessed) == set(selected)
                     and len(selected) >= 15 and not cost['usage_unavailable'])
    projections = []
    for q in universe:
        rid = q['request_id']
        projections.append({'original_request_id': rid, 'target_ids': q['expected_target_ids'],
            'parent_block_id': q.get('provenance', {}).get('parent_block_id'),
            'target_spans': [r for r in q['source_refs'] if r['role'] == 'target'],
            'state': 'assessed' if rid in assessed else ('unresolved' if rid in selected else 'not_assessed'),
            'block_state': 'partial_or_mixed' if rid in selected else 'not_assessed',
            'projection_only': True})
    return {'version': VERSION, 'identity': state['identity'], 'manifest_sha256': digest(manifest),
        'universe_sha256': manifest['universe_sha256'], 'arm': arm, 'model': bench.MODEL,
        'policy': manifest['policy'], 'caps': manifest['caps'],
        'status': 'complete' if state.get('finished') else 'incomplete',
        'execution_status': 'complete' if state.get('finished') else 'incomplete',
        'selective_pass': selective, 'semantic_quality_claim': False,
        'publication_status': 'semantic_review_pending',
        'original_request_ids': original_ids, 'selected_request_ids': selected,
        'protocol_verified_request_ids': [rid for rid in selected if rid in latest and latest[rid]['status'] == 'protocol_verified'],
        'assessed_request_ids': assessed, 'unselected_request_ids': [r for r in original_ids if r not in selected],
        'selected_targets': [p for p in projections if p['original_request_id'] in selected],
        'unselected_targets': [p for p in projections if p['original_request_id'] not in selected],
        'block_state_projection': projections, 'selections': state['selections'],
        'request_ledger': [latest[rid] for rid in selected if rid in latest],
        'extraction_history': [r for r in state['rows'].values() if r['kind'] == 'extraction'],
        'request_history': list(state['rows'].values()),
        'planner_receipts': [r for r in state['rows'].values() if r['kind'] == 'planner'],
        'cost_ledger': cost, 'tokens': cost['tokens'], 'usage_unavailable': cost['usage_unavailable'],
        'effective_input_estimate_bytes':state.get('effective_input_estimate_bytes',CAPS['input_estimate_bytes']),
        'guard_override_history':state.get('guard_override_history',[]),
        'exposure_intervals': state['exposure_intervals'], 'delivery_intervals': state['delivery_intervals'],
        'assessment_intervals': state['assessment_intervals'], 'unresolved_obligations': state['unresolved_obligations'],
        'context_searches': state['context_searches'], 'groups': list(state['groups'].values()),
        'stop_reason': state['stop_reason'], 'transport_stats': state['transport_history'],
        'resume_or_recovered_receipt': resumed, 'freshness': 'resumed' if resumed else 'fresh',
        'performance_eligible': selective and not resumed,
        'wall_seconds': wall, 'setup': {'seconds': setup, 'warmup': state['warmup'],
            'warmup_accounting': 'separate_all_attempts', 'server_startup_warmup_usage_state': 'not_collected'},
        'total_client_seconds': total, 'source_completeness_claim': False}
