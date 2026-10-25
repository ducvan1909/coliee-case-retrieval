import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_fourth10 import BATCH_ID,make_proposal

IDS=['at-2c1bd134149633afd4376e74','at-2ee52523f9ffaed8ef6d78a9','at-30fcb7387e01828cdc463add','at-31fb5ee31ba428e383f369cf','at-322488d8d16a073136576e8a','at-34095952cc8f4531057b05a3','at-36d2799e80bf0e3f5421c6cf','at-397a79d4d287d795fed0e818','at-3b322354b56dc150db0ef7af','at-3bf2d5382a3dbb34d161b87b']


class Fourth10DecisionTests(unittest.TestCase):
    def test_source_attribution_and_conditional_rules(self):
        p,source,pol=dependencies(ROOT,'099980');tasks={t['target_id']:t for t in p['tasks']};outcomes=[]
        for position,tid in enumerate(IDS,1):
            v=make_proposal(tasks[tid],p,source,position,{'batch_id':BATCH_ID});validate_model_proposal(v,p,source,pol)
            r=v['target_reviews'][0];outcomes.append(r['model_outcome'])
            if position==2:self.assertFalse(r['authority_units']);self.assertIn('agency notification',r['notes'][0])
            if position in (7,10):self.assertFalse(r['authority_units']);self.assertIsNone(r['hard_negative']);self.assertTrue(r['unresolved_reasons']);self.assertIn('definitive opinion',r['context_spans'][1]['quote'])
            if position==3:self.assertEqual(r['authority_units'][0]['limit_spans'][0]['quote'],'not determinative')
            if position==6:
                a=r['authority_units'][0];self.assertIn('in the absence',a['condition_spans'][0]['quote']);self.assertIn('May 17, 2010',a['limit_spans'][0]['quote']);self.assertNotIn('Prejudice',a['evidence_spans'][0]['quote'])
            if position==9:
                a=r['authority_units'][0];self.assertEqual(a['limit_spans'][0]['quote'],'In this case');self.assertIn('does not define',a['condition_spans'][0]['quote']);self.assertEqual(a['attributions'][0]['speaker'],'current_court')
        self.assertEqual((outcomes.count('positive'),outcomes.count('hard_negative'),outcomes.count('unresolved')),(3,5,2))


class Fourth10PersistedTests(unittest.TestCase):
    def test_checkpoint_sidecars_preservation_and_exact_overlay(self):
        report=load_json(ROOT/'r4_fourth10_validation.json');batch=load_json(ROOT/report['batch_ref'])
        self.assertEqual(batch['target_ids'],IDS)
        self.assertEqual((report['reviewed_before'],report['reviewed_after'],report['missing_before'],report['missing_after']),(242,252,127,117))
        for ref,sha in batch['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();manifest=load_json(ROOT/'model_proposal_manifest.json')
        self.assertEqual(manifest['proposals'][:30],batch['before_model_manifest']['proposals'])
        records=[r for r in manifest['proposals'] if r['batch_id']==BATCH_ID];self.assertEqual(len(records),10)
        for row in records:
            v=load_json(ROOT/row['proposal_ref']);p,s,pol=dependencies(ROOT,v['case_id'])
            self.assertEqual(validate_model_proposal(v,p,s,pol),load_json(ROOT/row['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+manifest['reviewed_target_count'])
        self.assertEqual(report['effective_counts'],{'authority_units':111,'hard_negatives':136,'unresolved':5})
        self.assertFalse(report['independent_acceptance']);self.assertFalse(report['plan10_allowed'])


if __name__=='__main__':unittest.main()
