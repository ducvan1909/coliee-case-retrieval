"""Read-only source-aligned comparison. Overlap proposes pairs, never correctness."""
from __future__ import annotations

import copy
import html
from pathlib import Path
import tempfile

from . import core
from .contracts import BUDGET
from .runner import _validate_cache, _receipt
from ..au_context_paired.build import binding, fingerprint, write_new
from ..au_presentation_paired.core import profile
from ..au_target_context import kos_aligned
from ..kos_comparison.comparison import _overlap

DEFAULT_BASELINE_RUN = (Path(__file__).resolve().parents[1] / 'outputs' /
                       'kos_same_source_20261018_recovered_v1/live/run.json')


def _checkpoint(workload, run_path):
    w = core.load(workload)
    core.preflight(w)
    path = Path(run_path).resolve()
    root = path.parent
    core.require(not (root / '.runner.lock').exists(), 'compare requires stopped runner')
    report, ledger = core.load(path), core.load(root / 'runtime_ledger.json')
    core.require(ledger['ledger_sha256'] == fingerprint({k:v for k,v in ledger.items() if k != 'ledger_sha256'}),
                 'ledger digest mismatch')
    bound = ledger['binding']
    core.require(bound['mode'] in ('mock','execute'), 'unknown run mode')
    cfg = core.runtime_config(w['identity'])
    cfg.update({k:bound['run_profile'][k] for k in ('timeout','job_wait_seconds','job_poll_seconds')})
    if not bound['run_profile']['runtime_revision_setting_present']:
        cfg.pop('expected_model_revision', None)
    expected = {'workload_sha256':w['workload_sha256'],'code_sha256':core.code_hash(),
                'selected_target_ids':bound['selected_target_ids'],'mode':bound['mode'],
                'run_profile':profile(w,cfg),'budget':w['budget'],'concurrency':bound['concurrency']}
    core.require(bound == expected and ledger['identity'] == fingerprint(bound) == report['identity']
                 and report['mode'] == bound['mode'] and report['workload_sha256'] == w['workload_sha256'],
                 'foreign run/workload binding')
    selected = bound['selected_target_ids']
    core.require(bool(selected) and len(selected) == len(set(selected))
                 and set(selected) <= {r['target_id'] for r in w['rows']}
                 and type(bound['concurrency']) is int and 1 <= bound['concurrency'] <= 4, 'invalid run selection')
    core.require(ledger['provider_attempts'] == len(ledger['attempts']) <= BUDGET['max_provider_attempts']
                 and len(ledger['jobs']) <= BUDGET['max_requests'], 'attempt/request counters changed')
    for field, cap in (('reserved_input_tokens','max_total_input_tokens'),('reserved_output_tokens','max_total_output_tokens')):
        core.require(ledger[field] == sum(a[field] for a in ledger['attempts']) <= BUDGET[cap], 'reservation changed')
    rows = [r for r in w['rows'] if r['target_id'] in selected]
    first_jobs = [core.build_job(r,w['identity']) for r in rows]
    _validate_cache(root,ledger,first_jobs,rows,w['identity'],cfg)
    targets, receipts = [], []
    def read(job):
        entry = ledger['jobs'].get(job['request_id'])
        if entry is None:
            return 'not_dispatched',None
        if entry.get('receipt_sha256'):
            value = _receipt(root,entry)
            receipts.append(value)
            return entry['status'],value['normalized'] if entry['status'] == 'verified' else None
        return entry['status'],None
    for row,job in zip(rows,first_jobs):
        status1, initial = read(job)
        status2, final = 'not_needed',initial
        if initial and initial['context_request'] is not None and row['context_refs']:
            status2,final = read(core.build_job(row,w['identity'],stage=2,draft=initial))
        status = ('provider_or_protocol_failure' if status1 in ('invalid','failed') or status2 in ('invalid','failed')
                  else 'pending' if final is None else 'needs_context' if final['context_request'] is not None else 'draft_ready')
        targets.append({'target_id':row['target_id'],'case_id':row['case_id'],'source_hash':row['source_hash'],
                        'target':row['target'],'status':status,'stage1_status':status1,'stage2_status':status2,
                        'initial_output':initial,'output':final,'semantic_quality':'not_assessed'})
    core.require(core.load(root/'runtime_ledger.json') == ledger and not (root/'.runner.lock').exists(),
                 'checkpoint changed during comparison')
    usage = [r['usage'] for r in receipts if r.get('usage') is not None]
    summary = {'mode':bound['mode'],'target_count':len(rows),'logical_requests':len(ledger['jobs']),
               'provider_POST_attempts':ledger['provider_attempts'] if bound['mode']=='execute' else 0,
               'transport_POST_attempts':ledger['provider_attempts'],
               'known_usage_observed_subtotal':{k:sum(u.get(k,0) for u in usage) for k in ('input_tokens','output_tokens','total_tokens')},
               'unknown_usage_jobs':sum(r.get('usage') is None for r in receipts),
               'usage_is_complete':False,'usage_note':'Receipt subtotal; retries may have unknown usage; mock is not provider usage.',
               'stage1_requests':len(rows),'stage2_requests':sum(t['stage2_status']!='not_needed' for t in targets),
               'needs_context_targets':sum(t['status']=='needs_context' for t in targets),
               'reported_elapsed_wall_ms':report.get('elapsed_wall_ms'),'semantic_quality':'not_assessed'}
    return w,targets,summary,ledger


def compare(workload, run_path, output_root, *, baseline_run=None):
    w,targets,summary,ledger = _checkpoint(workload,run_path)
    root = Path(output_root).resolve()
    baseline_path = Path(baseline_run or DEFAULT_BASELINE_RUN).resolve()
    protected = [Path(workload).resolve().parent,Path(run_path).resolve().parent,w['source_store'],w['atom_root'],
                 Path(w['reference_checklist_path']).parent,baseline_path.parent,
                 *[Path(b['path']).parent for b in w['parent_bindings']]]
    core.guard_output(root,protected)
    core.require(not root.exists(), 'comparison output must be new')
    reference = core.load(w['reference_checklist_path'])
    old_workload_path = w['parent_bindings'][0]['path']
    old_w = core.load(old_workload_path)
    core.require(w['rows'] == core._rows(old_w), 'baseline TARGET/context mismatch')
    # Existing verifier is read-only toward the old run; its generated comparison
    # goes to private temporary storage, never regenerating provider results.
    with tempfile.TemporaryDirectory(prefix='au-claim-baseline-') as temp:
        old = kos_aligned.compare(old_workload_path,baseline_path,old_w['reference_checklist_path'],Path(temp)/'compare')
    baseline_ledger = core.load(baseline_path.parent/'runtime_ledger.json')
    core.require(set(baseline_ledger['binding']['selected_target_ids']) == {r['target_id'] for r in w['rows']},
                 'baseline must cover same16 TARGETs')
    baseline_aus = [r['anchor'] for r in old['pipeline_anchors']]
    old_usage = []
    for entry in baseline_ledger['jobs'].values():
        if entry.get('receipt_sha256'):
            receipt = _receipt(baseline_path.parent,entry)
            if receipt.get('usage') is not None:
                old_usage.append(receipt['usage'])
    baseline = {'run_binding':binding(baseline_path),'target_count':16,'logical_requests':len(baseline_ledger['jobs']),
                'stage1_requests':16,'stage2_requests':sum(e['job']['stage']==2 for e in baseline_ledger['jobs'].values()),
                'anchor_count':len(baseline_aus),'provisional_au':sum(a['status']=='provisional_au' for a in baseline_aus),
                'unresolved':sum(a['status']=='unresolved' for a in baseline_aus),
                'completed_workload_usage':{k:sum(u.get(k,0) for u in old_usage) for k in ('input_tokens','output_tokens','total_tokens')},
                'usage_scope':'Includes imported verified generations once, excludes prior invalid generation; not new generation during comparison.',
                'semantic_quality':'source_based_agent_review_exists_not_human_gold'}
    new_aus,initial_aus = [],[]
    for target in targets:
        for key,out in (('initial',initial_aus),('final',new_aus)):
            value = target['initial_output'] if key=='initial' else target['output']
            out.extend({'target_id':target['target_id'],'case_id':target['case_id'],'source_hash':target['source_hash'],
                        'status':target['status'],**copy.deepcopy(a)} for a in (value or {}).get('aus',[]))
    comparisons = []
    states = {t['target_id']:t['status'] for t in targets}
    for ref in reference['references']:
        def matches(items):
            return [{'au':a,'evidence_overlap_characters':_overlap(ref['alignment']['spans'],a['evidence'])}
                    for a in items if a['case_id']==ref['case_id'] and a['source_hash']==ref['source_hash']
                    and _overlap(ref['alignment']['spans'],a['evidence'])]
        old_ref = next(r for r in old['references'] if r['reference']['kos_id']==ref['kos_id'])
        comparisons.append({'reference':ref,'target_status':states.get(ref['target_id'],'out_of_scope'),
                            'claim_first_candidates':matches(new_aus),'initial_candidates':matches(initial_aus),
                            'baseline_candidates':old_ref['candidates'],'semantic_review_status':'pending'})
    result = {'artifact_type':'AUClaimComparison','status':'semantic_review_pending',
              'workload_sha256':w['workload_sha256'],'run_binding':binding(run_path),
              'reference_count':len(comparisons),'cases':reference['cases'],'targets':targets,
              'references':comparisons,'claim_first_aus':new_aus,'initial_aus':initial_aus,
              'claim_first_summary':summary,'baseline_summary':baseline,
              'comparison_conditions':{'same_source_target_context':True,'same_model':True,'same_output_cap':True,
                                       'same_prompt_contract':False,'selection':'reference_guided_calibration'},
              'semantic_quality':'not_assessed','token_savings_claim':'not_established',
              'limitations':['KOS is not human gold.','Overlap proposes evidence pairs, not semantic equivalence.',
                             'Mock never measures extraction quality or provider token savings.',
                             'Claim-first vs baseline changes contract, prompt and context policy together.']}
    write_new(root/'comparison.json',result)
    def cell(text):
        return html.escape(str(text)).replace('|','\\|').replace('\n',' ').replace('\r',' ')
    lines = ['# So AU claim-first với KOS và baseline','',
             'Semantic review còn pending. Các cặp dưới đây chỉ ghép theo overlap evidence; không phải chấm đúng/sai.', '',
             '| KOS reference | Claim KOS | Claim mới có evidence overlap | Trạng thái TARGET |',
             '|---|---|---|---|']
    for item in comparisons:
        claims = ' / '.join(c['au']['claim'] for c in item['claim_first_candidates']) or '(không có cặp overlap)'
        lines.append('| '+ ' | '.join(cell(x) for x in (item['reference']['kos_id'],item['reference']['claim_text'],claims,item['target_status'])) +' |')
    (root/'REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result
