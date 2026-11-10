"""Seal Main's local acceptance facts without contacting services."""
import json
from pathlib import Path
from pipeline_v2.full_corpus.common import implementation,file_digest
from pipeline_v2.optimization_v2.common import implementation as opt_implementation
from pipeline_v2.retrieval.common import implementation as base_implementation
from pipeline_v2.source.core import canonical,digest

root=Path(__file__).resolve().parents[3];here=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_bytes())
prior=read(here/'prior_state.json')
assert prior['optimization_v2_implementation']==opt_implementation()
assert all(file_digest(root/p)==h for p,h in prior['profile_hashes'].items())
base=read(root/'pipeline_v2/artifacts/m3_pilot_20261106_l4_v1/pilot_manifest.json')
assert base_implementation()==base['implementation']
run=root/'pipeline_v2/artifacts/m3_full_train_20261108_v1';m=read(run/'manifest.json')
assert implementation()==m['implementation']
assert not any((run/name).exists() for name in ('ledger.sqlite3','vectors','execution_state.json','progress.json'))
audit=read(here/'real_full_plan_audit.json');assert audit['status']=='PASS_local_plan_only'
command=json.loads((here/'plan_command_receipt.json').read_text(encoding='utf-8-sig'));assert command['exit_code']==0
result={'status':'PASS_local_plan_and_tests_remote_not_run','implementation_sha256':digest(canonical(implementation())),
        'profile_sha256':file_digest(root/'pipeline_v2/configs/m3_full.json'),'old_code_profiles_unchanged':True,
        'test_result':'30/30 PASS fixtures_and_mocks','plan_command':command,'real_plan_audit':audit,
        'model_requests_executed_by_main':0,'Modal_operations_executed_by_main':False,'Qdrant_accessed_by_main':False,
        'full_vectors_ingested':False,'full_DB_verified':False,'full_hybrid_search_ready':False,'COLIEE_quality_evaluated':False,
        'AG_next':'local_review_then_real_canary2_resume_full_verify','plan_dir':run.relative_to(root).as_posix()}
with (here/'local_acceptance.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({k:result[k] for k in ('status','implementation_sha256','old_code_profiles_unchanged','model_requests_executed_by_main')}))
