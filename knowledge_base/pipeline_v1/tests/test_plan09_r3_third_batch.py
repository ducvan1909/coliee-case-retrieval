import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT, digest, effective_proposals, scan_attribution_risks, validate_amendment, validate_risk_review
from knowledge_base.pipeline_v1.au_gold.progress import build_progress
from knowledge_base.pipeline_v1.review_plan09_r3_third10 import DECISIONS


class ThirdBatchTests(unittest.TestCase):
    def test_records_and_exact_dependencies(self):
        queue=scan_attribution_risks()
        items=queue['items'][20:30]
        self.assertEqual([x['target_id'] for x in items],[x[0] for x in DECISIONS])
        for item,(_,outcome,_) in zip(items,DECISIONS):
            self.assertEqual(item['status'],'model_reviewed_pending_independent_audit')
            review=load_json(ROOT/item['review_ref'])
            self.assertEqual(review['outcome'],outcome)
            self.assertEqual(review['reviewer']['model'],'gpt-6.1-sol')
            self.assertTrue(validate_risk_review(review)['valid'])
            self.assertEqual(digest(ROOT/'model_proposals'/item['case_id']/(item['proposal_id']+'.json')),review['proposal_sha256'])
            if review['amendment_id']:
                validate_amendment(load_json(ROOT/'model_amendments'/(review['amendment_id']+'.json')))

    def test_overlay_and_snapshot(self):
        report=load_json(ROOT/'remediation_r3_third10_validation.json')
        self.assertEqual((report['pending_before'],report['pending_after']),(29,19))
        self.assertEqual(report['effective_counts'],{'authority_units':97,'hard_negatives':112,'unresolved':3})
        self.assertTrue(report['original_proposals_unchanged'])
        self.assertTrue(report['previous_reviews_unchanged'])
        self.assertTrue(report['missing_targets_unchanged'])
        self.assertFalse(report['independent_audit_complete'])
        stored=load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
        reviews=[r for p in effective_proposals() for r in p['target_reviews']]
        self.assertEqual((len(reviews),sum(len(r['authority_units']) for r in reviews),sum(r['hard_negative'] is not None for r in reviews),sum(r['model_outcome']=='unresolved' for r in reviews)),(stored['reviewed_target_count'],stored['authority_unit_count'],stored['hard_negative_count'],stored['unresolved_target_count']))
        self.assertEqual(stored,build_progress(ROOT,stored['blocker']))
        self.assertFalse(stored['semantic_remediation']['plan10_allowed'])


if __name__=='__main__':unittest.main()
