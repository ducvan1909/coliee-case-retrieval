from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from .core import build_pairs
from ..au_compact.manifest import write_json

def main():
    p=argparse.ArgumentParser(description='Build offline metadata-only Plan11 hint pairs')
    p.add_argument('command',choices=['build','review-packet','costs','bind-review'])
    p.add_argument('--readiness',default='knowledge_base/pipeline_v1/outputs/plan11_context_hint_readiness_20261011/readiness.json')
    p.add_argument('--source-store',default='knowledge_base/pipeline_v1/outputs/source_store_v1')
    p.add_argument('--atom-root',default='knowledge_base/pipeline_v1/outputs/plan04_sentence_atoms_v1')
    p.add_argument('--output-root',required=True)
    p.add_argument('--run')
    p.add_argument('--pairing')
    p.add_argument('--review')
    args=p.parse_args(); root=Path(args.output_root)
    if args.command!='build':
        from .review import masked_packet, costs, bind_reviews
        if not args.run: p.error('--run required')
        raw=Path(args.run).read_bytes(); report=json.loads(raw)
        if args.command=='review-packet':
            packet,bindings=masked_packet(report,args.source_store,args.atom_root)
            packet['run_sha256']=hashlib.sha256(raw).hexdigest()
            write_json(root/'review_packet.masked.json',packet)
            write_json(root/'review_bindings.private.json',{'run_sha256':packet['run_sha256'],'bindings':bindings})
            print(f'CONTEXT-HINT ARM-MASKED PACKET READY — output: {(root/"review_packet.masked.json").resolve()}')
        elif args.command=='bind-review':
            if not args.review: p.error('--review required')
            value=bind_reviews(args.run,root/'review_packet.masked.json',root/'review_bindings.private.json',args.review)
            write_json(root/'review.bound.json',value)
            print(f'CONTEXT-HINT REVIEW BOUND — output: {(root/"review.bound.json").resolve()}')
        else:
            if not args.pairing: p.error('--pairing required')
            paired=json.loads(Path(args.pairing).read_text(encoding='utf-8'))
            if paired['manifest_sha256'] != report['manifest_sha256']:
                p.error('pairing/run manifest mismatch')
            value=costs(report,paired)
            write_json(root/'costs.json',value)
            print(f'CONTEXT-HINT COSTS READY — known tokens={value["known_provider_total_tokens"]} output: {(root/"costs.json").resolve()}')
        return
    value=build_pairs(args.readiness,args.source_store,args.atom_root)
    for name,payload in value.items():
        dest=root/(name+'.json')
        if dest.exists():
            if json.loads(dest.read_text(encoding='utf-8')) != payload:
                p.error('refusing to replace a different locked experiment: '+str(dest))
        write_json(dest,payload)
    print(f'CONTEXT-HINT PAIRS READY — pairs={value["pairing"]["pair_count"]} output: {(root/"pairing.json").resolve()}')

if __name__=='__main__': main()
