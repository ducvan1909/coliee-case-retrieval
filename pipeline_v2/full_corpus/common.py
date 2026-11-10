"""Frozen full-run contracts, shared with the accepted V2 encoder."""
from pathlib import Path
from ..optimization_v2.common import artifact, file_digest, read, write_json, M3Error
from ..optimization_v2.common import implementation as opt_implementation
from ..optimization_v2.common import load_profile as opt_profile
from ..optimization_v2.index import FastSession
from ..optimization_v2.runtime import require_compatibility
from ..retrieval.common import fingerprint
from ..source.core import canonical, digest

PROFILE='pipeline_v2/configs/m3_full.json'

def implementation():
    root=Path(__file__).resolve().parents[2]
    paths={'pipeline_v2/m3_full.py',*opt_implementation()}
    for package in ('full_corpus','retrieval','passages','source','navigation'):
        paths.update(p.relative_to(root).as_posix() for p in (root/'pipeline_v2'/package).glob('*.py'))
    paths.add('pipeline_v2/deploy_modal.py')
    return {p:file_digest(root/p) for p in sorted(paths)}

def load_profile(root):
    p=read(Path(root)/PROFILE);v2=opt_profile(root)
    if p.get('schema_version')!='pipeline-v2-m3-full-1' or p.get('mode')!='full_train':raise M3Error('Unsupported full profile')
    if p.get('embedding')!=v2['embedding'] or fingerprint(p)!=fingerprint(v2):raise M3Error('Full encoder differs from accepted V2 encoder')
    if p.get('batch_size')!=64 or p.get('expected_passages')!=415693 or p.get('expected_cases')!=7708:raise M3Error('Unsupported full scope or batching')
    if p.get('passages_bundle')!='pipeline_v2/artifacts/m2_passages_20261106_v1' or p.get('accepted_m2_seal_sha256')!='0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6':raise M3Error('Unaccepted M2 source')
    if p['qdrant'].get('on_disk') is not True or not p['qdrant']['collection_prefix'].startswith('coliee_m3_full_'):raise M3Error('Full collection must be isolated and on disk')
    return p

def compatibility(root,p):
    session=FastSession(root,p['compatibility_index'])
    try:
        receipt=require_compatibility(session,p['compatibility_receipt'])
        if receipt['embedding_fingerprint']!=fingerprint(p):raise M3Error('Full compatibility fingerprint mismatch')
        path=artifact(root,p['compatibility_receipt'])
        if path.is_dir():path=path/'compatibility.json'
        return {'receipt':path.relative_to(Path(root).resolve()).as_posix(),'sha256':file_digest(path),
                'embedding_fingerprint':receipt['embedding_fingerprint']}
    finally:session.close()

def seal(directory,names):
    return {name:{'sha256':file_digest(directory/name),'bytes':(directory/name).stat().st_size} for name in names}

def validate_seal(directory):
    expected=read(directory/'seal.json')
    if set(expected)!={'manifest.json','lexical.sqlite3'}:raise M3Error('Incomplete full plan seal')
    for name,entry in expected.items():
        path=directory/name
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or entry!={'sha256':file_digest(path),'bytes':path.stat().st_size}:raise M3Error('Full plan file drift: '+name)

