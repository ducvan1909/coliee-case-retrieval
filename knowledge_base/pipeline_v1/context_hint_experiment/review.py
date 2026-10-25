"""Arm-masked source packets and receipts; no automatic semantic verdicts."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from ..au_compact.review_packet import build_packet
from ..au_compact.hints import digest

def masked_packet(report, source_store, atom_root):
    packet=build_packet(report,source_store,atom_root)
    bindings=[]
    for row in packet['rows']:
        request_id=row.pop('request_id')
        review_id='blind-'+digest({'request':request_id})[:20]
        bindings.append({'review_id':review_id,'request_id':request_id})
        row['review_id']=review_id
    packet['rows'].sort(key=lambda r:r['review_id'])
    packet['artifact_type']='ContextHintArmMaskedReviewPacket'
    packet['masking']='No arm label, hint payload, pairing or receipts shown. Development agent review, not human gold.'
    return packet,bindings

def costs(report, pairing):
    arm_by_request={rid:arm for pair in pairing['pairs'] for arm,rid in pair['request_ids'].items()}
    totals={arm:{'requests':0,'input_tokens':0,'output_tokens':0,'total_tokens':0,
                  'client_latency_ms':0,'inference_seconds':0,'usage_unavailable':0,
                  'protocol_verified':0,'failed_requests':[]} for arm in ('P2a','P2b')}
    for row in report['request_ledger']:
        rid=row['request']['request_id']; arm=arm_by_request[rid]; total=totals[arm]
        receipt=row.get('receipt',{}); usage=receipt.get('usage')
        total['requests']+=1; total['protocol_verified']+=row['status']=='protocol_verified'
        if usage:
            for key in ('input_tokens','output_tokens','total_tokens'): total[key]+=usage[key]
        else: total['usage_unavailable']+=1
        total['client_latency_ms']+=receipt.get('latency_ms',0)
        total['inference_seconds']+=receipt.get('transport_trace',{}).get('server_timing',{}).get('inference_seconds',0)
        if row['status']!='protocol_verified': total['failed_requests'].append({'request_id':rid,'diagnostic':receipt.get('failure_diagnostic')})
    overhead=sum(a.get('usage',{}).get('total_tokens',0) for a in report.get('warmup',{}).get('attempts',[]))
    overhead+=report.get('compact_schema_probe',{}).get('provider_usage',{}).get('total_tokens',0)
    return {'artifact_type':'ContextHintExperimentCost','semantic_gold':False,
            'arms':totals,'shared_known_overhead_tokens':overhead,
            'known_provider_total_tokens':sum(x['total_tokens'] for x in totals.values())+overhead,
            'runtime_ledger':copy.deepcopy(report['runtime_ledger']),
            'warmup_attempts':copy.deepcopy(report.get('warmup',{}).get('attempts',[])),
            'money':'not measured','failed_provider_usage':'include known receipts; unreported usage remains unknown',
            'review_agent_cost':'not included in endpoint usage; not measured',
            'quality_claim':False,'run_status':report['status']}

def bind_reviews(run_path, packet_path, bindings_path, reviewed_path):
    """Resolve hidden request IDs only after the arm-masked verdict is frozen."""
    raw=Path(run_path).read_bytes(); report=json.loads(raw); run_sha=hashlib.sha256(raw).hexdigest()
    packet_raw=Path(packet_path).read_bytes(); packet=json.loads(packet_raw)
    mapping=json.loads(Path(bindings_path).read_text(encoding='utf-8'))
    reviewed=json.loads(Path(reviewed_path).read_text(encoding='utf-8'))
    if packet['run_sha256']!=run_sha or mapping['run_sha256']!=run_sha:
        raise ValueError('stale masked packet or private mapping')
    if reviewed['packet_sha256']!=hashlib.sha256(packet_raw).hexdigest():
        raise ValueError('review does not bind exact masked packet')
    requests={r['request']['request_id']:r for r in report['request_ledger']}
    ids={x['review_id']:x['request_id'] for x in mapping['bindings']}
    packet_rows={r['review_id']:r for r in packet['rows']}
    if len(ids)!=len(mapping['bindings']) or set(ids)!=set(packet_rows):
        raise ValueError('invalid private review mapping')
    if any(rid not in requests or bid!='blind-'+digest({'request':rid})[:20] for bid,rid in ids.items()):
        raise ValueError('private mapping locator mismatch')
    entries=[]; locators=set()
    for proposed in reviewed['reviews']:
        entry=copy.deepcopy(proposed); review_id=entry.pop('review_id'); rid=ids[review_id]
        row=requests[rid]; compact=row['compact_response']; index=entry.get('au_index')
        locator=(review_id,entry['review_type'],index)
        if locator in locators: raise ValueError('duplicate review locator')
        locators.add(locator)
        if entry['review_type']=='au':
            if type(index)!=int or not 0<=index<len(compact['aus']): raise ValueError('review AU index mismatch')
            recorded=next(p['proposal'] for p in packet_rows[review_id]['proposals'] if p['au_index']==index)
            if recorded!=compact['aus'][index]: raise ValueError('packet proposal mismatch')
            proposal_sha=digest(compact['aus'][index])
        else:
            if entry['review_type']!='target_omission': raise ValueError('invalid review type')
            proposal_sha=digest(compact)
        entry.update(run_sha256=run_sha,request_id=rid,proposal_sha256=proposal_sha)
        entries.append(entry)
    expected={(bid,'target_omission',None) for bid in ids}
    expected|={(bid,'au',p['au_index']) for bid,r in packet_rows.items() for p in r['proposals']}
    if locators!=expected: raise ValueError('incomplete masked review coverage')
    value={'artifact_type':'AUCandidateReview','schema_version':'au-candidate-review-v1',
           'reviewer':{'reviewer_id':'plan11-arm-masked-tester','reviewer_type':'agent',
                       'producer':'Codex tester','version':'development-masked-review-v1',
                       'provenance':{'method':'Arm-masked source review; deterministic ID binding after verdicts; not gold.',
                                     'input_artifacts':[str(packet_path),str(reviewed_path)]}},
           'reviews':entries}
    from jsonschema import Draft202012Validator
    schema=json.loads((Path(__file__).resolve().parents[1]/'contracts/au_candidate_review.v1.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate(value)
    return value
