"""Record local acceptance; never invokes services or model inference."""
import hashlib
import json
from pathlib import Path
import sqlite3
from pipeline_v2.optimization_v2.benchmark import stratified_windows
from pipeline_v2.optimization_v2.common import implementation

root=Path(__file__).resolve().parents[3]
here=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_bytes())
hashfile=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
prior=read(here/'prior_state.json')
for group in ('baseline_code','optimization_v1_code'):
    assert all(hashfile(root/p)==expected for p,expected in prior[group].items())
for name,key in [('m3.json','baseline_profile_sha256'),('m3_opt.json','optimization_v1_profile_sha256')]:
    assert hashfile(root/'pipeline_v2/configs'/name)==prior[key]
directory=root/'pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1'
manifest=read(directory/'manifest.json')
assert implementation()==manifest['optimization_implementation']
db=sqlite3.connect((directory/'lexical.sqlite3').as_uri()+'?mode=ro',uri=True)
metadata=[json.loads(row[0]) for row in db.execute("SELECT metadata FROM documents WHERE kind='passage'")]
db.close()
strata=stratified_windows(metadata)
byid={p['passage_id']:p for p in metadata}
padding={}
for size in (16,32,64):
    actual=padded=0
    for s in strata:
        tokens=[byid[i]['full_input_tokens'] for i in s['passage_ids']]
        actual+=sum(tokens)
        padded+=sum(max(tokens[i:i+size])*len(tokens[i:i+size]) for i in range(0,len(tokens),size))
    padding[str(size)]={'input_tokens':actual,'padded_tokens':padded,'ratio':padded/actual}
old=root/'pipeline_v2/artifacts/m3_opt_index_20261107_v2/lexical.sqlite3'
oldbytes=old.stat().st_size
newbytes=(directory/'lexical.sqlite3').stat().st_size
result={'status':'PASS_local_index_and_tests_remote_pending','synthetic_tests':18,
        'real_index_audit':read(here/'real_index_audit.json'),'old_code_profiles_unchanged':True,
        'old_sqlite_bytes':oldbytes,'new_sqlite_bytes':newbytes,'sqlite_reduction_fraction':1-newbytes/oldbytes,
        'strata':strata,'padding_by_batch':padding,'index_build':read(directory/'cli_receipt.json'),
        'modal_operations_executed':False,'full_corpus_executed':False,'COLIEE_quality_evaluated':False,
        'full_db_verification':{'status':'not_verified_connection_error','attempted':True,
            'cli_exit_code':1,'internal_cli_seconds':4.445671899999979,'error':'ConnectionError',
            'action':'AG must ensure existing Docker Qdrant ready then run verify --full-db; do not reset collection'},
        'compatibility':'not_run','gpu_benchmark':'not_run','real_search':'not_run',
        'implementation':implementation()}
with (here/'local_acceptance.json').open('x',encoding='utf-8') as f:
    json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({k:result[k] for k in ('status','old_sqlite_bytes','new_sqlite_bytes','sqlite_reduction_fraction','padding_by_batch','old_code_profiles_unchanged')}))
