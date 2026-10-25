from __future__ import annotations
import copy
from pathlib import Path
from ..milestone1.core import digest
from ..bulk_execution.storage import write_json


def _aus(row):
    result=row.get('response')
    if not isinstance(result,dict):return []
    return [au for target in result.get('target_results',[]) for au in target.get('authority_units',[])]


def _evidence(au):
    return tuple(sorted((x['start_char'],x['end_char']) for x in au.get('evidence_spans',[])))


def _content(au):
    v=copy.deepcopy(au);v.pop('local_au_id',None)
    return digest(v)


def _complete_assessment(row):
    v=row.get('compact_response')
    return (row.get('status')=='protocol_verified' and isinstance(v,dict)
            and v.get('coverage_status')=='complete' and v.get('decision') in ('positive','hard_negative')
            and not any(au.get('needs_context') for au in v.get('aus',[])))


def _warmup_tokens(report):
    warm=report.get('warmup') or report.get('setup',{}).get('warmup',{})
    attempts=warm.get('attempts',[]) if isinstance(warm,dict) else []
    return sum(a.get('usage',{}).get('total_tokens',0) for a in attempts if isinstance(a.get('usage'),dict))


def compare(manifest,baseline,arms,output_root):
    """Compare selected assessments with a frozen complete same-target reference.

    Reference positives and AU signatures are model outputs, not gold labels.
    Never use this module during selection; it consumes completed run artifacts.
    """
    parent=manifest.get('parent',{})
    requests=parent.get('parent',{}).get('requests',[])
    if not requests or manifest.get('parent_sha256')!=digest(parent):
        raise ValueError('comparison_manifest_invalid')
    original={q['request_id']:q for q in requests}
    if len(original)!=len(requests):raise ValueError('comparison_duplicate_universe')
    expected=set(original);universe_hash=digest(requests)
    if baseline.get('identity',{}).get('manifest_sha256')!=digest(parent):
        raise ValueError('comparison_reference_manifest_mismatch')
    def indexed(report):
        rows=report.get('request_ledger',[]);out={}
        for row in rows:
            q=row.get('original_request',{})
            rid=q.get('request_id')
            if rid not in expected or q!=original[rid]:raise ValueError('comparison_source_request_mismatch')
            if rid in out:raise ValueError('comparison_duplicate_assessment')
            out[rid]=row
        return out
    old=indexed(baseline)
    if set(old)!=expected or baseline.get('status')!='complete' or any(r.get('status')!='protocol_verified' for r in old.values()):
        raise ValueError('comparison_reference_incomplete')
    old_positive={rid for rid,row in old.items() if row.get('compact_response',{}).get('decision')=='positive'}
    old_au_count=sum(len(_aus(r)) for r in old.values())
    summaries={};pairs={}
    for arm,report in arms.items():
        if arm not in ('H','P'):raise ValueError('comparison_unknown_arm')
        if report.get('arm')!=arm or report.get('universe_sha256')!=universe_hash:
            raise ValueError('comparison_universe_mismatch')
        if report.get('manifest_sha256')!=digest(manifest) or report.get('model')!=manifest.get('model'):
            raise ValueError('comparison_run_identity_mismatch')
        listed=report.get('original_request_ids',[])
        if len(listed)!=len(expected) or set(listed)!=expected:raise ValueError('comparison_universe_mismatch')
        def idset(key):
            value=report.get(key,[])
            if not isinstance(value,list) or any(not isinstance(x,str) for x in value) or len(value)!=len(set(value)) or not set(value)<=expected:
                raise ValueError('comparison_selection_invalid')
            return set(value)
        selected=idset('selected_request_ids');assessed=idset('assessed_request_ids');unselected=idset('unselected_request_ids')
        if selected&unselected or selected|unselected!=expected or not assessed<=selected:
            raise ValueError('comparison_selection_invalid')
        new=indexed(report)
        if not set(new)<=selected:raise ValueError('comparison_selection_invalid')
        verified={rid for rid,row in new.items() if _complete_assessment(row)}
        if assessed!=verified:raise ValueError('comparison_assessment_ledger_mismatch')
        details=[];exact=0;evidence=0;new_count=0
        for rid in original:
            before=old[rid];after=new.get(rid)
            initial=before.get('compact_response',{});v=(after or {}).get('compact_response') or {}
            original_aus=_aus(before);current_aus=_aus(after or {}) if rid in assessed else []
            # Match one-to-one so duplicates cannot inflate retention.
            counts={}
            for au in current_aus:counts[_content(au)]=counts.get(_content(au),0)+1
            exact_for_row=0
            for au in original_aus:
                signature=_content(au)
                if counts.get(signature,0):exact_for_row+=1;counts[signature]-=1
            counts={}
            for au in current_aus:counts[_evidence(au)]=counts.get(_evidence(au),0)+1
            evidence_for_row=0
            for au in original_aus:
                signature=_evidence(au)
                if signature and counts.get(signature,0):evidence_for_row+=1;counts[signature]-=1
            exact+=exact_for_row;evidence+=evidence_for_row;new_count+=len(current_aus)
            details.append({'original_request_id':rid,'case_id':original[rid]['case_id'],
                'target_ids':original[rid]['expected_target_ids'],'selected':rid in selected,'assessed':rid in assessed,
                'state':'not_assessed' if rid not in selected else 'assessed' if rid in assessed else 'unresolved',
                'reference_decision':initial.get('decision'),'new_decision':v.get('decision') if rid in assessed else None,
                'reference_au_count':len(original_aus),'new_au_count':len(current_aus),
                'exact_content_matches':exact_for_row,'exact_evidence_matches':evidence_for_row,
                'review_required':rid in old_positive and (rid not in assessed or exact_for_row<len(original_aus))})
        tokens=report.get('tokens',{})
        if any(type(tokens.get(k)) is not int or tokens[k]<0 for k in ('input_tokens','output_tokens','total_tokens')):
            raise ValueError('comparison_usage_invalid')
        eligible=(report.get('status')=='complete' and report.get('performance_eligible') is True and
                  baseline.get('performance_eligible') is True and report.get('usage_unavailable')==0 and
                  baseline.get('usage_unavailable')==0 and selected==assessed and not report.get('stop_dispatch',False))
        retained=sum((new[rid].get('compact_response') or {}).get('decision')=='positive' for rid in old_positive&assessed)
        reported_total=tokens['total_tokens']+_warmup_tokens(report)
        old_total=baseline['tokens']['total_tokens']+_warmup_tokens(baseline)
        summaries[arm]={'status':report.get('status'),'targets_selected':len(selected),'targets_assessed':len(assessed),
            'targets_not_assessed':len(expected-assessed),'reference_positive_targets':len(old_positive),
            'reference_positive_targets_unselected':len(old_positive-selected),
            'reference_positive_targets_selected_but_unresolved':len((old_positive&selected)-assessed),
            'reference_positive_targets_still_positive':retained,
            'reference_positive_targets_now_negative':sum((new[rid].get('compact_response') or {}).get('decision')=='hard_negative' for rid in old_positive&assessed),
            'reference_au_count':old_au_count,'new_au_count':new_count,
            'exact_content_matches':exact,'exact_evidence_matches':evidence,
            'reference_positive_target_retention':retained/len(old_positive) if old_positive else None,
            'retention_note':'relative to model reference, NOT true AU recall or semantic equivalence',
            'tokens_including_planner':tokens,'reported_tokens_including_client_warmup':reported_total,
            'cumulative_token_spend_change_percent':100*(reported_total/old_total-1) if old_total and report.get('usage_unavailable')==0 else None,
            'spend_note':'cumulative recorded provider usage incl cached checkpoint receipts once; not latency speedup or quality-equivalent saving',
            'wall_seconds':report.get('wall_seconds'),'total_client_seconds':report.get('total_client_seconds'),
            'fresh_operational_comparison_eligible':eligible,
            'observed_token_reduction_percent':100*(1-reported_total/old_total) if eligible and old_total else None,
            'quality_equivalence_claim':False,'semantic_quality_claim':False,
            'needs_source_review':sum(d['review_required'] for d in details),
            'recommendation':('requires_retention_and_semantic_review_before_adoption' if eligible else
                              'resumed_cost_comparison_only_not_fresh_speedup' if report.get('status')=='complete' else
                              'incomplete_not_speedup_evidence')}
        pairs[arm]=details
    result={'version':'selective-reading-comparison-v1','universe_sha256':universe_hash,'targets':len(expected),
        'cases':len({q['case_id'] for q in requests}),'reference_scope':'complete only for locked30-target pilot; NOT complete five cases',
        'reference_is_gold':False,'semantic_quality_claim':False,'baseline':{k:baseline.get(k) for k in ('tokens','wall_seconds','total_client_seconds')},
        'arms':summaries,'pairs':pairs}
    write_json(Path(output_root)/'comparison.json',result)
    lines=['# So sánh đọc chọn lọc với bản cũ','',
           'Reference là output model trên cùng 30 target, không phải gold hoặc toàn năm án.','',
           '| Arm | Target đã đánh giá | Positive reference chưa chọn | Positive reference giữ lại | Tổng token model | Giảm token quan sát |',
           '|---|---:|---:|---:|---:|---:|']
    for arm,v in summaries.items():
        reduction=v['observed_token_reduction_percent']
        lines.append(f"| {arm} | {v['targets_assessed']} | {v['reference_positive_targets_unselected']} | {v['reference_positive_targets_still_positive']}/{v['reference_positive_targets']} | {v['tokens_including_planner']['total_tokens']} | {reduction:.1f}% |" if reduction is not None else f"| {arm} | {v['targets_assessed']} | {v['reference_positive_targets_unselected']} | {v['reference_positive_targets_still_positive']}/{v['reference_positive_targets']} | {v['tokens_including_planner']['total_tokens']} | chưa đủ điều kiện |")
    lines+=['','Giảm token không chứng minh chất lượng tương đương. Xem pairs trong JSON để review omission, claim và evidence.','GPU/billing chưa đo; wall chạy khác thời điểm chỉ là quan sát, không chứng minh riêng tác dụng selection.']
    (Path(output_root)/'COMPARISON.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result
