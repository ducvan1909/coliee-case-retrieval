import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,digest,effective_proposals,registry,risk_review_heads,scan_attribution_risks,validate_amendment,validate_risk_review
from knowledge_base.pipeline_v1.au_gold.progress import build_progress
from knowledge_base.pipeline_v1.review_plan09_r3_final9 import DECISIONS

class FinalBatchTests(unittest.TestCase):
    def test_exact_nine_records_and_dependencies(self):
        queue=scan_attribution_risks();items=queue['items'][40:49]
        self.assertEqual(len(items),9)
        self.assertEqual([x['target_id'] for x in items],[x[0] for x in DECISIONS])
        for item in items:
            review=load_json(ROOT/item['review_ref'])
            self.assertEqual(review['outcome'],'amendment')
            self.assertEqual(review['reviewer']['model'],'gpt-6.1-sol')
            self.assertTrue(validate_risk_review(review)['valid'])
            self.assertEqual(digest(ROOT/'model_proposals'/item['case_id']/(item['proposal_id']+'.json')),review['proposal_sha256'])
            validate_amendment(load_json(ROOT/'model_amendments'/(review['amendment_id']+'.json')))

    def test_final_queue_overlay_and_locked_gates(self):
        queue=scan_attribution_risks()
        self.assertEqual(queue['pending_model_review_count'],0)
        self.assertEqual(len(risk_review_heads()),49)
        self.assertTrue(all(x['status']=='model_reviewed_pending_independent_audit' for x in queue['items']))
        report=load_json(ROOT/'remediation_r3_final9_validation.json')
        self.assertEqual((report['pending_before'],report['pending_after']),(9,0))
        self.assertTrue(report['original_proposals_unchanged']);self.assertTrue(report['previous_history_unchanged']);self.assertTrue(report['missing_ids_unchanged'])
        self.assertFalse(report['independent_acceptance']);self.assertFalse(report['plan10_allowed'])
        reviews=[r for p in effective_proposals() for r in p['target_reviews']]
        stored=load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
        self.assertEqual(report['effective_counts'],{'authority_units':97,'hard_negatives':113,'unresolved':2})
        self.assertEqual((len(reviews),sum(len(r['authority_units']) for r in reviews),sum(r['hard_negative'] is not None for r in reviews),sum(r['model_outcome']=='unresolved' for r in reviews)),(stored['reviewed_target_count'],stored['authority_unit_count'],stored['hard_negative_count'],stored['unresolved_target_count']))
        self.assertEqual(stored,build_progress(ROOT,stored['blocker']))
        missing=next(x['missing_target_ids'] for x in stored['cases'] if x['case_id']=='099980')
        appended=load_json(ROOT/'model_proposal_manifest.json')['reviewed_target_count'] if (ROOT/'model_proposal_manifest.json').exists() else 0
        self.assertEqual(len(missing),157-appended);self.assertNotIn('at-dc762fc78fb3970f9e23f864',missing)
        self.assertEqual(next(x for x in registry()['findings'] if x['finding_id']=='P09-S01')['status'],'closed')

if __name__=='__main__':unittest.main()
