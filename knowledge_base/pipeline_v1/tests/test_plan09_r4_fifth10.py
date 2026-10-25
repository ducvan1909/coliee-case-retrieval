import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_fifth10 import BATCH_ID,make_proposal

IDS=['at-3c30af827186591d2bf66be2','at-3e39044f97b84404b520022e','at-3e97359dc0a6d7669025040b','at-41ba0116a63ebb7c839e9149','at-422fbd7f49cb2cff502c7399','at-4751d840ca72860653e65cd8','at-47a655a27ed5534b3a17e956','at-49def3d233262fffd76bbd5a','at-49ed1261d578f869e56746d2','at-4b1f384513ca1b440639bff3']


class Fifth10DecisionTests(unittest.TestCase):
    def test_exact_source_and_reporting_vs_court_response(self):
        p,source,pol=dependencies(ROOT,'099980');tasks={t['target_id']:t for t in p['tasks']};outcomes=[]
        for position,tid in enumerate(IDS,1):
            v=make_proposal(tasks[tid],p,source,position,{'batch_id':BATCH_ID});validate_model_proposal(v,p,source,pol)
            r=v['target_reviews'][0];outcomes.append(r['model_outcome'])
            if position in (2,4):self.assertEqual(r['hard_negative']['reason'],'party_argument_only')
            if position==1:
                a=r['authority_units'][0];self.assertEqual(a['limit_spans'][0]['quote'],'in this case');self.assertIn('did not object',a['cross_block_refs'][0]['quote'])
            if position==5:self.assertTrue(r['authority_units'][0]['evidence_spans'][0]['quote'].startswith('At the outset'))
            if position==7:
                a=r['authority_units'][0];self.assertTrue(a['evidence_spans'][0]['quote'].startswith('Once again'));self.assertNotIn('respondent maintains',a['evidence_spans'][0]['quote']);self.assertEqual(a['uncertainty'],'medium')
            if position==10:self.assertFalse(r['authority_units']);self.assertIsNone(r['hard_negative']);self.assertTrue(r['unresolved_reasons']);self.assertIn('definitive opinion',r['context_spans'][1]['quote'])
        self.assertEqual((outcomes.count('positive'),outcomes.count('hard_negative'),outcomes.count('unresolved')),(3,6,1))


class Fifth10PersistedTests(unittest.TestCase):
    def test_frozen_ids_preservation_and_sidecars(self):
        report=load_json(ROOT/'r4_fifth10_validation.json');batch=load_json(ROOT/report['batch_ref'])
        self.assertEqual(batch['target_ids'],IDS)
        self.assertEqual((report['reviewed_before'],report['reviewed_after'],report['missing_before'],report['missing_after']),(252,262,117,107))
        for ref,sha in batch['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();manifest=load_json(ROOT/'model_proposal_manifest.json')
        self.assertEqual(manifest['proposals'][:40],batch['before_model_manifest']['proposals'])
        records=[r for r in manifest['proposals'] if r['batch_id']==BATCH_ID];self.assertEqual(len(records),10)
        for row in records:
            v=load_json(ROOT/row['proposal_ref']);p,s,pol=dependencies(ROOT,v['case_id'])
            self.assertEqual(validate_model_proposal(v,p,s,pol),load_json(ROOT/row['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+manifest['reviewed_target_count'])
        self.assertEqual(report['effective_counts'],{'authority_units':114,'hard_negatives':142,'unresolved':6})
        self.assertFalse(report['independent_acceptance']);self.assertFalse(report['plan10_allowed'])


if __name__=='__main__':unittest.main()
