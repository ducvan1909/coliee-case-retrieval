"""Independent readonly full-plan audit against sealed M2 and raw sources."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time


def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_bytes())
def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[3];run=root/args.run_dir;started=time.perf_counter()
    m=read(run/'manifest.json');seal=read(run/'seal.json')
    assert set(seal)=={'manifest.json','lexical.sqlite3'}
    for name,entry in seal.items():assert entry=={'sha256':file_sha(run/name),'bytes':(run/name).stat().st_size}
    assert m['passages']==415693 and m['cases']==7708 and m['profile']['batch_size']==64
    bundle=root/m['profile']['passages_bundle'];m2seal=read(bundle/'seal.json')['files']
    assert file_sha(bundle/'seal.json')==m['profile']['accepted_m2_seal_sha256']
    registry_bytes=(bundle/'source_registry.json').read_bytes()
    assert m2seal['source_registry.json']=={'sha256':sha(registry_bytes),'byte_length':len(registry_bytes)}
    registry=json.loads(registry_bytes)['sources'];assert len(registry)==7708
    db=sqlite3.connect((run/'lexical.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    counts=dict(db.execute('SELECT kind,COUNT(*) FROM documents GROUP BY kind'))
    assert counts=={'case':7708,'passage':415693}
    assert db.execute("SELECT COUNT(*) FROM documents WHERE json_type(metadata,'$.text') IS NOT NULL").fetchone()[0]==0
    source_count=passage_count=0
    for row in registry:
        case=row['case_id'];raw=(root/'data/task1_train_files_2026/cases'/case).read_bytes()
        assert sha(raw)==row['source_hash']==m['source_hashes'][case]
        body=(bundle/row['passages_ref']).read_bytes()
        assert m2seal[row['passages_ref']]=={'sha256':sha(body),'byte_length':len(body)}
        record=json.loads(body);passages=record['passages']
        assert len(passages)==row['passage_count']
        case_meta=json.loads(db.execute("SELECT metadata FROM documents WHERE kind='case' AND id=?",(case,)).fetchone()[0])
        assert case_meta=={'case_id':case,'source_hash':row['source_hash']}
        for offset in range(0,len(passages),256):
            block=passages[offset:offset+256];ids=[p['passage_id'] for p in block]
            rows=db.execute("SELECT id,metadata FROM documents WHERE kind='passage' AND id IN ("+','.join('?' for _ in ids)+')',ids)
            found={i:json.loads(meta) for i,meta in rows};assert set(found)==set(ids)
            for p in block:
                actual=found[p['passage_id']]
                assert all(actual[k]==v for k,v in p.items() if k!='text')
                assert set(actual)==(set(p)-{'text'})|{'navigation_preview_count'}
                span=raw[slice(*p['span_bytes'])]
                assert span.decode('utf-8')==p['text'] and sha(span)==p['exact_input_sha256']
                passage_count+=1
        source_count+=1
    assert (source_count,passage_count)==(7708,415693)
    previous=None;input_tokens=padded_tokens=0;current=[];batch_count=0
    sql="SELECT s.ordinal,s.batch,s.passage_id,json_extract(d.metadata,'$.full_input_tokens') FROM schedule s JOIN documents d ON d.kind='passage' AND d.id=s.passage_id ORDER BY s.ordinal"
    for expected,(ordinal,batch,ident,tokens) in enumerate(db.execute(sql)):
        assert ordinal==expected and batch==ordinal//64 and type(tokens) is int and 1<=tokens<=448
        key=(tokens,ident);assert previous is None or previous<key;previous=key
        current.append(tokens);input_tokens+=tokens
        if len(current)==64:
            padded_tokens+=max(current)*len(current);current=[];batch_count+=1
    assert expected+1==415693
    if current:padded_tokens+=max(current)*len(current);batch_count+=1
    assert batch_count==m['batches']==6496
    assert db.execute('SELECT COUNT(*),COUNT(DISTINCT passage_id) FROM schedule').fetchone()==(415693,415693)
    db.close()
    result={'status':'PASS_local_plan_only','raw_cases_verified':source_count,'passages_verified':passage_count,'batches':batch_count,
            'last_batch_size':len(current),'input_tokens':input_tokens,'padded_tokens':padded_tokens,'padding_ratio':padded_tokens/input_tokens,
            'sqlite_bytes':(run/'lexical.sqlite3').stat().st_size,'elapsed_seconds':time.perf_counter()-started,
            'model_requests':0,'DB_accessed':False,'labels_accessed':False,'vectors_ingested':False}
    with (root/args.output).open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result))


if __name__=='__main__':main()
