"""Read-only canonical verification; writes only a separate verification report."""
import copy
import hashlib
import json
import os
from .au_gold.core import atomic_write, load_json
from .au_gold.progress import build_progress
from .au_gold.remediation import ROOT, amendment_heads, digest, effective_proposals, registry, risk_review_heads, scan_attribution_risks, validate_amendment, validate_risk_review


def main():
    pipeline = ROOT.parents[1]
    saved = {str(p): digest(p) for folder in ('model_proposals','model_amendments','risk_reviews') for p in (ROOT/folder).rglob('*.json')}
    prior_report = load_json(ROOT/'remediation_audit_positions11_32_validation.json')
    audit_path = pipeline/prior_report['audit_ref']
    assert digest(audit_path) == prior_report['audit_sha256']
    queue = scan_attribution_risks()
    assert queue == load_json(ROOT/'attribution_risk_queue.json')
    raw = scan_attribution_risks(include_reviews=False)['items']
    heads = risk_review_heads()
    checks = [validate_risk_review(h, items=raw) for h in heads]
    assert len(checks) == 49 and queue['pending_model_review_count'] == 0
    physical_amendments = list((ROOT/'model_amendments').glob('*.json'))
    for path in physical_amendments:
        validate_amendment(load_json(path))
    amendment_heads()  # validates all immutable parent hashes and unique ancestry
    reconstructed = copy.deepcopy(queue)
    for position in (11,32):
        item = reconstructed['items'][position-1]
        head = load_json(ROOT/item['review_ref'])
        expected = f'p09-r3-audit-11-32-{position:02d}-gpt61sol-v2'
        assert head['review_id'] == expected
        parent_path = ROOT/'risk_reviews'/(head['supersedes_review_id']+'.json')
        assert digest(parent_path) == head['supersedes_review_sha256']
        parent = load_json(parent_path)
        item.update(review_ref=parent_path.relative_to(ROOT).as_posix(), outcome=parent['outcome'])
    # Match atomic_write's native text newline conversion, including Windows CRLF.
    serialized = (json.dumps(reconstructed,ensure_ascii=False,indent=2)+'\n').replace('\n', os.linesep)
    old_hash = hashlib.sha256(serialized.encode()).hexdigest()
    assert old_hash == prior_report['audit_queue_sha256'], 'original audit snapshot no longer reproducible'
    stored = load_json(pipeline/'reports/plan09_model_silver_progress.latest.json')
    assert build_progress(ROOT,stored['blocker']) == stored
    # R3 verification remains scoped to its immutable Terra cohort. Appended R4
    # targets are not retroactively covered by the R3 independent acceptance.
    reviews = [r for p in effective_proposals() if p['artifact_type']=='TerraAUProposal' for r in p['target_reviews']]
    counts = {'authority_units':sum(len(r['authority_units']) for r in reviews),'hard_negatives':sum(r['hard_negative'] is not None for r in reviews),'unresolved':sum(r['model_outcome']=='unresolved' for r in reviews)}
    assert counts == {'authority_units':98,'hard_negatives':113,'unresolved':1}
    missing = sum(len(c['missing_target_ids']) for c in stored['cases'])
    appended = load_json(ROOT/'model_proposal_manifest.json')['reviewed_target_count'] if (ROOT/'model_proposal_manifest.json').exists() else 0
    assert missing == 157-appended
    status = next(f for f in registry()['findings'] if f['finding_id']=='P09-S01')['status']
    assert status in ('pending_reaudit','closed')
    if status == 'closed':
        from .au_gold.r3_completion import validate_completion
        validate_completion()
    assert prior_report['originals_and_history_unchanged'] and prior_report['missing_ids_unchanged']
    assert all(digest(path)==sha for path,sha in saved.items())
    result = {'artifact_type':'Plan09ResumedRevisionVerification','valid':True,'verification_scope':'R3 frozen Terra cohort; R4 additions excluded from R3 acceptance','all_head_validation':checks,'physical_amendment_count':len(physical_amendments),'immutable_file_count':len(saved),'immutable_files_unchanged_during_verification':True,'pre_revision_queue_sha256_reproduced':old_hash,'earlier_preservation_report_sha256':digest(ROOT/'remediation_audit_positions11_32_validation.json'),'queue_sha256':digest(ROOT/'attribution_risk_queue.json'),'progress_sha256':digest(pipeline/'reports/plan09_model_silver_progress.latest.json'),'effective_counts':counts,'missing_count':missing,'r4_appended_target_count':appended,'snapshot_rebuild_needed':False,'p09_s01_status':status,'independent_acceptance':status=='closed','plan10_allowed':False}
    filename = 'r3_post_r4_verification.json' if appended else ('remediation_audit_positions11_32_postclosure_verification.json' if status=='closed' else 'remediation_audit_positions11_32_resumed_verification.json')
    atomic_write(ROOT/filename,result)
    print(f'PASS heads=49 amendments={len(physical_amendments)} history=unchanged R3_counts=98/113/1 missing={missing} R4_appended={appended} snapshot=consistent S01={status} Plan10=false')


if __name__ == '__main__':
    main()
