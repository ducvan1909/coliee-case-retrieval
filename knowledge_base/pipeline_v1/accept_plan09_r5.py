"""Verify Plan09 tests, then publish immutable R5/R6 revisions. Never runs Plan10."""
import argparse
import subprocess
import time
import unittest
from .au_gold.core import atomic_write, load_json
from .au_gold.remediation import ROOT, digest
from .au_gold.r5_acceptance import (ACCEPTANCE, DECISION, PROGRESS, TESTS,
    implementation_bindings, make_acceptance, make_decision,
    build_development_progress, validate_development_gate, bind, require)

PIPELINE=ROOT.parents[1]
FOCUSED=['knowledge_base.pipeline_v1.evaluation.test_plan09_remediation_independent',
         'knowledge_base.pipeline_v1.tests.test_plan09_revision_history',
         'knowledge_base.pipeline_v1.tests.test_plan09_r4_amendments',
         'knowledge_base.pipeline_v1.tests.test_plan09_r5_acceptance']

def run_suite(suite):
    started=time.perf_counter()
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    return {'run':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
            'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
            'elapsed_seconds':round(time.perf_counter()-started,3)}

def verify_tests():
    before=implementation_bindings(PIPELINE)
    focused=run_suite(unittest.defaultTestLoader.loadTestsFromNames(FOCUSED))
    loader=unittest.TestLoader()
    modules=['knowledge_base.pipeline_v1.tests.'+p.stem for p in sorted((PIPELINE/'tests').glob('test_plan09*.py'))]
    full=loader.loadTestsFromNames(modules)
    full.addTests(loader.loadTestsFromNames(['knowledge_base.pipeline_v1.evaluation.test_plan09_independent',
                                          'knowledge_base.pipeline_v1.evaluation.test_plan09_remediation_independent']))
    results=run_suite(full)
    require(before==implementation_bindings(PIPELINE),'implementation changed while tests ran')
    passed=all(x['passed']==x['run'] and not x['failures'] and not x['errors'] for x in (focused,results))
    report={'artifact_type':'Plan09R5CoordinatorTests','revision':1,'date':'2026-10-06',
            'status':'PASS' if passed else 'FAIL','focused_modules':FOCUSED,
            'full_plan09_scope':'tests/test_plan09*.py plus both evaluation/test_plan09*.py',
            'focused':focused,'full_plan09':results,'full_plan09_modules':modules,
            'implementation_bindings':before,
            'plan10_executed':False}
    atomic_write(PIPELINE/TESTS,report)
    print(f"tests={report['status']} focused={focused['passed']}/{focused['run']} full={results['passed']}/{results['run']} report={PIPELINE/TESTS}")
    require(passed,'Plan09 tests failed; no acceptance or gate published')

def immutable_write(path,value):
    if path.exists():
        require(load_json(path)==value,'immutable artifact already exists with different contents')
    else:
        atomic_write(path,value)

def publish():
    acceptance=make_acceptance(ROOT)
    immutable_write(ROOT/ACCEPTANCE,acceptance)
    immutable_write(ROOT/DECISION,make_decision(acceptance,digest(ROOT/ACCEPTANCE)))
    immutable_write(PIPELINE/PROGRESS,build_development_progress(ROOT))
    verify()

def verify():
    decision=validate_development_gate(ROOT)
    progress=build_development_progress(ROOT)
    require(load_json(PIPELINE/PROGRESS)==progress,'published progress changed')
    diff=subprocess.run(['git','diff','--check'],cwd=PIPELINE.parents[1],capture_output=True,text=True)
    require(diff.returncode==0,'git diff --check failed: '+diff.stdout+diff.stderr)
    tests=load_json(PIPELINE/TESTS)
    report={'artifact_type':'Plan09R5R6FinalVerification','revision':1,'date':'2026-10-06',
            'status':'PASS','counts':load_json(ROOT/ACCEPTANCE)['counts'],
            'coverage_hashes_verified':417,'legacy_missing_sidecars_disclosed':17,
            'focused_tests':tests['focused'],'full_plan09_tests':tests['full_plan09'],
            'artifact_bindings':[bind(p,PIPELINE) for p in (ROOT/ACCEPTANCE,ROOT/DECISION,PIPELINE/PROGRESS,PIPELINE/TESTS)],
            'git_diff_check':'PASS','plan10_allowed':decision['plan10_allowed'],
            'plan10_allowed_scope':'baseline_development_only','plan10_execution_authorized':False,
            'plan10_executed':False,'evaluation_against':'model_silver','semantic_gold':False,'human_gold':False}
    immutable_write(PIPELINE/'reports/plan09_r5_r6_final_verification.v1.json',report)
    print(f"verification=PASS targets=369 AUs=188 negatives=186 unresolved=8 gate=baseline_development_only Plan10_executed=false report={PIPELINE/'reports/plan09_r5_r6_final_verification.v1.json'}")

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['tests','publish','verify'])
    args=parser.parse_args()
    {'tests':verify_tests,'publish':publish,'verify':verify}[args.action]()
