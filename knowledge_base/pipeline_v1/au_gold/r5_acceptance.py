"""Hash-bound R5 acceptance and R6 development gate, separate from frozen progress.

Historical ``*.latest.json`` is already bound by R4 audit snapshots. Do not rewrite
it. Consumers of the current development gate must use validate_development_gate.
This does not implement the mixed-model silver lock or authorize Plan 10 execution.
"""
from pathlib import Path

from .core import AnnotationError, canonical_hash, load_json
from .remediation import ROOT, digest, effective_proposals

ACCEPTANCE = 'r5_acceptance.v1.json'
DECISION = 'r6_use_decision.v1.json'
PROGRESS = 'reports/plan09_model_silver_progress.r5_r6.v2.json'
TESTS = 'reports/plan09_r5_coordinator_tests.v1.json'
AUDIT = 'evaluation/reports/plan09_r5_final_independent_semantic_audit.json'
COUNTS = {'reviewed_target_count': 369, 'missing_target_count': 0,
          'authority_unit_count': 188, 'hard_negative_count': 186,
          'unresolved_target_count': 8, 'canonical_duplicate_target_count': 0}


def require(condition, message):
    if not condition:
        raise AnnotationError(message, code='r5_acceptance_stale')


def bind(path, pipeline):
    return {'ref': Path(path).relative_to(pipeline).as_posix(), 'sha256': digest(path)}


def verify_bindings(rows, pipeline):
    require(len({x['ref'] for x in rows}) == len(rows), 'duplicate artifact binding')
    for row in rows:
        path = (pipeline / row['ref']).resolve()
        require(path.is_relative_to(pipeline.resolve()), 'artifact outside pipeline')
        require(path.is_file() and digest(path) == row['sha256'], 'changed artifact: '+row['ref'])


def implementation_bindings(pipeline):
    paths = set((pipeline/'au_gold').glob('*.py'))
    paths.update((pipeline/'tests').glob('test_plan09*.py'))
    paths.update((pipeline/'evaluation').glob('test_plan09*.py'))
    paths.update([pipeline/'accept_plan09_r5.py', pipeline/'plan09_workflow.md'])
    return [bind(p, pipeline) for p in sorted(paths)]


def audited_state(root=ROOT):
    """Revalidate provenance, exact coverage and all 417 historical bindings."""
    from .progress import build_progress
    root = Path(root); pipeline = root.parents[1]
    audit = load_json(pipeline/AUDIT)
    sample = load_json(pipeline/audit['frozen_sample']['manifest_ref'])
    require(audit['verdict'] == 'PASS' and audit['reviewer']['independent_of_producers'], 'R5 audit not accepted')
    require(audit['scope']['evaluation_against'] == 'model_silver', 'audit scope changed')
    require(digest(pipeline/audit['frozen_sample']['manifest_ref']) == audit['frozen_sample']['manifest_sha256'], 'sample changed')
    require(sample['frozen_before_raw_sample_review'] is True, 'sample not frozen')
    require((sample['positive_target_count'], sample['positive_au_count'], sample['hard_negative_target_count'], sample['unresolved_target_count']) == (38,38,30,8), 'sample counts changed')
    require(all(audit['independent_findings'][k] == 0 for k in ('severe','high','moderate','attribution_errors','wrong_kind_errors','lost_condition_exception_limit_errors','evidence_span_errors','omission_errors','duplicate_or_coverage_errors')), 'unhandled R5 finding')
    coverage = load_json(pipeline/audit['r4_chain_verification']['coverage_ref'])
    require(coverage['valid'] and coverage['exact_expected_case_target_set_verified'], 'coverage incomplete')
    require(len(coverage['bound_artifacts']) == 417, 'coverage binding count changed')
    verify_bindings(coverage['bound_artifacts'], pipeline)
    legacy = coverage['legacy_proposals_without_sidecar']
    require(len(legacy) == coverage['legacy_sidecar_absence_count'] == 17, 'legacy disclosure changed')
    require(coverage['legacy_sidecars_not_created_or_modified'], 'legacy sidecars changed')
    for row in legacy:
        path = root/row['proposal_ref']
        require(not path.with_suffix('.validation.json').exists(), 'legacy sidecar unexpectedly created')
        require(not row['existing_sidecar_present'] and row['original_unchanged'] and row['fresh_validation']['semantic_gold'] is False, 'legacy validation boundary changed')
    chain = audit['r3_attribution_and_amendment_chain']
    require(digest(pipeline/chain['r3_completion_ref']) == chain['r3_completion_sha256'], 'R3 audit binding changed')
    correction = load_json(pipeline/audit['r4_chain_verification']['fourth10_correction_reaudit_ref'])
    require(correction['verdict'] == 'pass_corrections_accepted' and correction['summary']['original_moderate_findings_closed'] == 2, 'fourth10 findings not closed')
    frozen_path = pipeline/correction['snapshot']['correction_frozen_ref']
    require(digest(frozen_path) == correction['snapshot']['correction_frozen_sha256'], 'correction freeze changed')
    frozen = load_json(frozen_path)
    preservation = [{'ref':ref,'sha256':sha} for ref,sha in frozen['preserved_artifacts'].items()]
    require(len(preservation) == 615, 'preservation inventory changed')
    verify_bindings(preservation, pipeline)
    batch_audits = sorted((pipeline/'evaluation/reports').glob('plan09_r4_*_independent_semantic_audit.json'))
    require(len(batch_audits) == 16 and sum(load_json(p)['scope']['target_count'] for p in batch_audits) == 157, 'R4 independent audit scope incomplete')
    require(all(p.relative_to(pipeline).as_posix() in frozen['preserved_artifacts'] for p in batch_audits), 'batch audit not frozen')
    progress = build_progress(root)
    require(all(progress[k] == v for k,v in COUNTS.items()), 'effective counts changed')
    require(all(row['coverage_complete'] and not row['missing_target_ids'] for row in progress['cases']), 'case coverage incomplete')
    require(progress['semantic_remediation']['open_severe_finding_count'] == 0 and progress['semantic_remediation']['risk_pending_count'] == 0 and progress['semantic_remediation']['risk_reviewed_count'] == 49, 'R1-R3 incomplete')
    require(len(list((root/'risk_reviews').glob('*.json'))) == 54 and len(list((root/'model_amendments').glob('*.json'))) == 42, 'R3 physical history changed')
    require(load_json(pipeline/chain['post_r4_verification_ref'])['valid'] is True, 'post-R4 R3 validation incomplete')
    values = effective_proposals(root)
    hashes = {p['case_id']+':'+r['target_id']: canonical_hash(r) for p in values for r in p['target_reviews']}
    require(len(hashes) == 369, 'duplicate target owner')
    unresolved = sorted(p['case_id']+':'+r['target_id'] for p in values for r in p['target_reviews'] if r['model_outcome'] == 'unresolved')
    require(unresolved == sorted(sample['unresolved_target_ids']), 'unresolved sample no longer exact')
    by_target = {p['case_id']+':'+r['target_id']:r for p in values for r in p['target_reviews']}
    for field, outcome in [('positive_target_ids','positive'),('hard_negative_target_ids','hard_negative')]:
        ids = sample[field]
        require(len(ids) == len(set(ids)), 'duplicate sample target')
        require(all(t in by_target and by_target[t]['model_outcome'] == outcome for t in ids), 'sample outcome drift')
    require(sum(len(by_target[t]['authority_units']) for t in sample['positive_target_ids']) == 38, 'positive sample AU count changed')
    paths = [pipeline/AUDIT, (pipeline/AUDIT).with_suffix('.md'), pipeline/audit['frozen_sample']['manifest_ref'], pipeline/audit['r4_chain_verification']['coverage_ref'], pipeline/audit['r4_chain_verification']['fourth10_correction_reaudit_ref'], pipeline/chain['post_r4_verification_ref'], pipeline/'evaluation/plan09_remediation_independent_summary.json', pipeline/'evaluation/plan09_independent_summary.json', frozen_path, pipeline/correction['snapshot']['completion_verification_ref']]
    bindings = {x['ref']:x for x in preservation+coverage['bound_artifacts']}
    for path in paths:
        row = bind(path,pipeline); bindings[row['ref']] = row
    return progress, hashes, unresolved, sorted(bindings.values(),key=lambda x:x['ref'])


def make_acceptance(root=ROOT):
    root=Path(root); pipeline=root.parents[1]
    tests=load_json(pipeline/TESTS)
    require(tests['status'] == 'PASS' and all(tests[k]['failures'] == tests[k]['errors'] == 0 and tests[k]['passed'] == tests[k]['run'] for k in ('focused','full_plan09')), 'tests not PASS')
    require(tests['focused']['run'] >= 12 and tests['full_plan09']['run'] >= 78, 'test scope incomplete')
    from ..accept_plan09_r5 import FOCUSED
    require(tests['focused_modules'] == FOCUSED and tests['full_plan09_modules'] == ['knowledge_base.pipeline_v1.tests.'+p.stem for p in sorted((pipeline/'tests').glob('test_plan09*.py'))], 'test modules changed')
    require(tests['full_plan09_scope'] == 'tests/test_plan09*.py plus both evaluation/test_plan09*.py', 'evaluation tests omitted')
    require(tests['implementation_bindings'] == implementation_bindings(pipeline), 'tested implementation changed')
    verify_bindings(tests['implementation_bindings'],pipeline)
    progress, hashes, unresolved, bindings=audited_state(root)
    bindings = {x['ref']:x for x in bindings+[bind(pipeline/TESTS,pipeline), *tests['implementation_bindings']]}
    bindings = sorted(bindings.values(),key=lambda x:x['ref'])
    return {'artifact_type':'Plan09R5Acceptance','revision':1,'date':'2026-10-06','r5_status':'PASS',
            'evaluation_against':'model_silver','semantic_gold':False,'human_gold':False,
            'counts':COUNTS,'audit_sample_counts':{'positive_targets':38,'positive_AUs':38,'hard_negatives':30,'unresolved':8,'attribution_risks':49},
            'coverage_bound_artifact_count':417,'legacy_missing_sidecar_count':17,
            'unresolved_target_ids':unresolved,'effective_review_hashes':hashes,
            'bound_artifacts':bindings,'tests_ref':TESTS,
            'limitations':['Model-silver development only; not human gold.', 'Frozen error-finding sample is not precision/recall or independent retrieval-quality evidence.', '17 historical Terra sidecars remain absent; fresh structural validation is not semantic proof.', '8 unresolved records remain unresolved.', 'Mixed-model silver lock/export is not implemented by this gate.']}


def make_decision(acceptance, acceptance_sha256):
    require(acceptance['r5_status']=='PASS' and acceptance['semantic_gold'] is False and acceptance['human_gold'] is False, 'invalid acceptance scope')
    return {'artifact_type':'Plan09R6UseDecision','revision':1,'date':'2026-10-06',
            'acceptance_ref':'outputs/plan09_au_gold_v1/'+ACCEPTANCE,'acceptance_sha256':acceptance_sha256,
            'decision':'allow_baseline_development_only','evaluation_against':'model_silver',
            'semantic_gold':False,'human_gold':False,'independent_retrieval_quality_estimate':False,
            'plan10_allowed':True,'plan10_allowed_scope':'baseline_development_only',
            'plan10_execution_authorized':False,'plan10_executed':False,
            'required_reporting_label':'evaluation_against=model_silver',
            'unresolved_policy':'retain_all_8; do_not_force_labels', 'limitations':acceptance['limitations']}


def validate_development_gate(root=ROOT):
    """Fail closed on any audit/data/test drift, including a fabricated use decision."""
    root=Path(root); pipeline=root.parents[1]
    acceptance=load_json(root/ACCEPTANCE)
    require(acceptance == make_acceptance(root), 'acceptance no longer reproducible')
    decision=load_json(root/DECISION)
    require(decision == make_decision(acceptance,digest(root/ACCEPTANCE)), 'R6 decision binding/scope changed')
    return decision


def build_development_progress(root=ROOT):
    from .progress import build_progress
    root=Path(root)
    decision=validate_development_gate(root)
    result=build_progress(root, 'Model-silver baseline development allowed; no Plan10 execution authorized. No human gold or independent retrieval-quality estimate.')
    result['progress_version']='plan09-model-silver-progress-v2-r5-r6'
    result['supersedes_ref']='reports/plan09_model_silver_progress.latest.json'
    result['supersedes_sha256']=digest(root.parents[1]/result['supersedes_ref'])
    result['gates'].update(r5_final_audit_pass=True,plan10_allowed=True)
    result['semantic_remediation']['plan10_allowed']=True
    result['use_decision_binding']=bind(root/DECISION,root.parents[1])
    result['plan10_allowed_scope']=decision['plan10_allowed_scope']
    result['plan10_execution_authorized']=False
    result['human_gold']=False
    return result
