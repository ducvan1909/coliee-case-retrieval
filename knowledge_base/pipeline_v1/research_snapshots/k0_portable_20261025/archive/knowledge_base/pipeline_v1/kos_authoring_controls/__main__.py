"""Local preparation, CPU-gated positive control, then reviewed balanced controls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from . import controls as c
from ..au_context_paired.__main__ import study_config
from ..au_compact.runner import _atomic


def require_cpu(root, stage):
    path=Path(root)/f'cpu_{stage}.json';bundle=Path(root)/'input'/f'cpu_{stage}.json'
    report=c.old.load(path)
    from ..k0_authoring.token_budget import EXPECTED
    if not (report.get('status')=='pass' and report.get('protocol_pass') is True
            and report.get('bundle_sha256')==hashlib.sha256(bundle.read_bytes()).hexdigest()
            and report.get('tokenizer_sha256')==EXPECTED['tokenizer.json']
            and report.get('xgrammar_version')=='0.2.1'
            and sorted(report.get('actual_stop_token_ids',[]))==[248044,248046]):
        raise ValueError('native CPU report binding or status failed')


def evaluate_row(row,receipt):
    result={'name':row['name'],'expected':row['expected'],'usage':receipt.get('usage'),
        'status':'invalid','semantic_quality':'not_assessed'}
    try:
        body=receipt['raw_response'];choices=body['choices']
        if body.get('model')!=row['payload']['model'] or len(choices)!=1:raise ValueError('model/choice mismatch')
        choice=choices[0]
        if choice['finish_reason']!='stop':raise ValueError('incomplete generation')
        def pairs(items):
            if len({k for k,v in items})!=len(items):raise ValueError('duplicate JSON keys')
            return dict(items)
        def constant(_):raise ValueError('nonfinite JSON')
        content=choice['message']['content']
        out=json.loads(content,object_pairs_hook=pairs,parse_constant=constant)
        normalized=c.validate(out,row['validation_job'],row['name']!='positive_only')
        count=len(normalized['aus']);group=row['expected']['group']
        observed_text=' '.join((a['claim']+' '+(a['limits'] or '')) for a in normalized['aus']).lower()
        concepts={word:word in observed_text for word in row['expected']['concepts']}
        structural=(count==row['expected']['AU_count'])
        if group=='uncertain':
            structural=structural and normalized['empty_reason'] in c.REASONS[3:] and out['next_action']=={'tool':'finish_case','reason':'needs_context'}
        if group=='negative':
            structural=structural and normalized['empty_reason'] in c.NEGATIVE and out['assessed_scope_ids']==row['validation_job']['active_scope_ids']
        result.update(status='structural_control_pass' if structural else 'control_failed',
            model_output=out,normalized=normalized,AU_count=count,lexical_concept_hints=concepts,
            semantic_quality='agent_review_pending',note='Concept keywords are hints, never entailment or gold.')
    except Exception as exc:
        result['error_type']=type(exc).__name__
    return result


def evaluate(root,stage):
    root=Path(root);m=c.old.load(root/'input/manifest.json');ledger=c.old.load(root/'live/ledger.json')
    rows=m['jobs'] if stage=='positive' else m['balanced_jobs']
    results=[]
    for row in rows:
        key=c.old.fingerprint(row['payload'])
        receipt=ledger.get('receipts',{}).get(key)
        if receipt is None:
            # New transport stores immutable per-job receipts; support its map of pointers.
            receipt_path=root/'live/receipts'/f'{key}.json'
            receipt=c.old.load(receipt_path) if receipt_path.exists() else {}
        if isinstance(receipt,str):receipt=c.old.load(Path(receipt))
        results.append(evaluate_row(row,receipt))
    report={'stage':stage,'status':'agent_review_pending' if all(r['status']=='structural_control_pass' for r in results) else 'control_failed',
        'rows':results,'code_sha256':c.code_hash(),'manifest_sha256':m['sha256'],
        'K1_allowed':False,'corpus_dispatch_allowed':False,'semantic_quality':'not_gold'}
    report['sha256']=c.old.fingerprint(report)
    _atomic(root/f'{stage}_evaluation.json',report)
    return report


def positive_gate(root):
    root=Path(root);evaluation=c.old.load(root/'positive_evaluation.json');review=c.old.load(root/'positive_agent_review.json')
    if evaluation['sha256']!=c.old.fingerprint({k:v for k,v in evaluation.items() if k!='sha256'}):raise ValueError('evaluation digest')
    if (evaluation['status']!='agent_review_pending' or evaluation['code_sha256']!=c.code_hash()
        or review.get('evaluation_sha256')!=evaluation['sha256'] or review.get('decision')!='supported'
        or review.get('basis')!='main_agent_source_review' or not review.get('reason')):
        raise ValueError('positive control has not passed source review')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','preflight','run-positive','run-balanced','evaluate'])
    p.add_argument('--output-root',type=Path,required=True);p.add_argument('--execute',action='store_true')
    p.add_argument('--stage',choices=['positive','balanced'],default='positive');args=p.parse_args();root=args.output_root
    try:
        if args.command=='prepare':
            c.prepare(root);result={'status':'prepared','inference':0}
        elif args.command=='preflight':
            result=c.preflight(root);_atomic(root/'preflight.json',result)
        elif args.command=='evaluate':result=evaluate(root,args.stage)
        else:
            if not args.execute:raise ValueError('live control requires explicit --execute')
            c.preflight(root);stage='positive' if args.command=='run-positive' else 'balanced'
            require_cpu(root,stage)
            if stage=='balanced':positive_gate(root)
            m=c.old.load(root/'input/manifest.json');cfg,_,_=study_config(args)
            from .execution import run_jobs
            selected=[r['name'] for r in (m['jobs'] if stage=='positive' else m['balanced_jobs'])]
            result=run_jobs(root/'live',cfg,m['jobs']+m['balanced_jobs'],execute=True,selected_names=selected)
            if result.get('status')=='complete':result=evaluate(root,stage)
        print(json.dumps({k:v for k,v in result.items() if k not in ('rows','jobs','receipts')},ensure_ascii=False))
        return 0 if result['status'] in ('prepared','pass','complete','agent_review_pending') else 1
    except Exception as exc:
        print(json.dumps({'status':'blocked','error_type':type(exc).__name__}));return 1


if __name__=='__main__':raise SystemExit(main())
