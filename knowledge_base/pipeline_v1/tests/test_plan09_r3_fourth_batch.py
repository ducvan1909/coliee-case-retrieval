import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,digest,effective_proposals,registry,scan_attribution_risks,validate_amendment,validate_risk_review
from knowledge_base.pipeline_v1.au_gold.progress import build_progress
from knowledge_base.pipeline_v1.review_plan09_r3_fourth10 import DECISIONS

class FourthBatchTests(unittest.TestCase):
    def test_records_and_dependencies(self):
        queue=scan_attribution_risks();items=queue['items'][30:40]
        self.assertEqual([x['target_id'] for x in items],[x[0] for x in DECISIONS])
        for position,(item,(_,outcome,_)) in enumerate(zip(items,DECISIONS),31):
            self.assertEqual(item['status'],'model_reviewed_pending_independent_audit')
            review=load_json(ROOT/'risk_reviews'/f'p09-r3-fourth10-{position:02d}-gpt61sol-v1.json');self.assertEqual(review['outcome'],outcome)
            self.assertTrue(validate_risk_review(load_json(ROOT/item['review_ref']))['valid'])
            self.assertTrue(validate_risk_review(review)['valid'])
            self.assertEqual(digest(ROOT/'model_proposals'/item['case_id']/(item['proposal_id']+'.json')),review['proposal_sha256'])
            if review['amendment_id']:validate_amendment(load_json(ROOT/'model_amendments'/(review['amendment_id']+'.json')))

    def test_overlay_s01_lineage_and_snapshots(self):
        report=load_json(ROOT/'remediation_r3_fourth10_validation.json')
        self.assertEqual((report['pending_before'],report['pending_after']),(19,9))
        self.assertEqual(report['effective_counts'],{'authority_units':97,'hard_negatives':113,'unresolved':2})
        self.assertTrue(report['original_proposals_unchanged']);self.assertTrue(report['previous_heads_history_unchanged'])
        self.assertTrue(report['p09_s01_registry_unchanged']);self.assertFalse(report['independent_audit_complete'])
        amendment=load_json(ROOT/'model_amendments/p09-r3-fourth10-32-gpt61sol-v1.json')
        self.assertEqual(amendment['schema_version'],'au-model-amendment-v2')
        self.assertEqual(amendment['supersedes_amendment_id'],'p09-s01-gpt6-unresolved-v1')
        self.assertEqual(amendment['replacement_review']['model_outcome'],'unresolved')
        self.assertEqual(next(x for x in registry()['findings'] if x['finding_id']=='P09-S01')['status'],'closed')
        stored=load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
        reviews=[r for p in effective_proposals() for r in p['target_reviews']]
        self.assertEqual((len(reviews),sum(len(r['authority_units']) for r in reviews),sum(r['hard_negative'] is not None for r in reviews),sum(r['model_outcome']=='unresolved' for r in reviews)),(stored['reviewed_target_count'],stored['authority_unit_count'],stored['hard_negative_count'],stored['unresolved_target_count']))
        self.assertEqual(stored,build_progress(ROOT,stored['blocker']))
        appended=load_json(ROOT/'model_proposal_manifest.json')['reviewed_target_count'] if (ROOT/'model_proposal_manifest.json').exists() else 0
        self.assertEqual(stored['missing_target_count'],157-appended);self.assertFalse(stored['semantic_remediation']['plan10_allowed'])

if __name__=='__main__':unittest.main()
