import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_eighth10 import BATCH_ID,make_proposal

IDS=['at-77795080c5c4a12d616c23fb','at-7ae2ae96e98fe1711c0bb0c8','at-7c2438bcce27682cdd68ac16','at-7ca139c74013a440ec1f9b58','at-7d8a081b1e141c63b05c04f0','at-7e7fcd55dcd3ac2c48651d45','at-80dd855d64256453a585304d','at-82b9a66eda69a6ecd5efa988','at-848aa7019c8e57579343e4c6','at-84d29312a5bc05be38261afa']


class Eighth10DecisionTests(unittest.TestCase):
    def test_exact_source_conditional_rules_and_reported_voice(self):
        p,s,pol=dependencies(ROOT,'099980');tasks={t['target_id']:t for t in p['tasks']};outcomes=[]
        for position,tid in enumerate(IDS,1):
            v=make_proposal(tasks[tid],p,s,position,{'batch_id':BATCH_ID});validate_model_proposal(v,p,s,pol)
            r=v['target_reviews'][0];outcomes.append(r['model_outcome'])
            if position==1:
                a=r['authority_units'][0];self.assertEqual(len(a['condition_spans']),2);self.assertIn('can be found guilty',a['evidence_spans'][0]['quote']);self.assertIn('section 5',a['cross_block_refs'][1]['quote'])
            if position==3:self.assertTrue(r['authority_units'][0]['evidence_spans'][0]['quote'].startswith('However, regardless'))
            if position==4:self.assertFalse(r['authority_units']);self.assertIsNone(r['hard_negative']);self.assertTrue(r['unresolved_reasons']);self.assertIn('draft of the final',r['context_spans'][1]['quote'])
            if position==5:
                a=r['authority_units'][0];self.assertNotIn('requires',a['evidence_spans'][0]['quote']);self.assertEqual(len(a['condition_spans']),2);self.assertIn('may investigate',r['context_spans'][1]['quote'])
            if position==6:self.assertTrue(r['authority_units'][0]['condition_spans'][0]['quote'].startswith('as long as'));self.assertIn('nothing authorizes',r['authority_units'][0]['cross_block_refs'][1]['quote'])
            if position==7:
                a=r['authority_units'][0];self.assertEqual(a['attributions'][0]['speaker'],'commission_policy');self.assertEqual(len(a['exception_spans']),2);self.assertNotIn('The notice',a['evidence_spans'][0]['quote'])
            if position==8:
                a=r['authority_units'][0];self.assertEqual(a['kind'],'standard_of_review');self.assertIn('actually has jurisdiction',a['condition_spans'][0]['quote']);self.assertIn('definitive opinion',r['context_spans'][1]['quote'])
        self.assertEqual((outcomes.count('positive'),outcomes.count('hard_negative'),outcomes.count('unresolved')),(6,3,1))


class Eighth10PersistedTests(unittest.TestCase):
    def test_frozen_ids_preservation_sidecars_and_model_boundary(self):
        v=load_json(ROOT/'r4_eighth10_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS)
        self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual(b['evaluation_against'],'model_silver')
        self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(282,292,87,77))
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:70],b['before_model_manifest']['proposals'])
        records=[r for r in m['proposals'] if r['batch_id']==BATCH_ID];self.assertEqual(len(records),10)
        for row in records:
            proposal=load_json(ROOT/row['proposal_ref']);p,s,pol=dependencies(ROOT,proposal['case_id']);self.assertEqual(validate_model_proposal(proposal,p,s,pol),load_json(ROOT/row['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count'])
        self.assertEqual(v['effective_counts'],{'authority_units':131,'hard_negatives':152,'unresolved':9})
        self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])


if __name__=='__main__':unittest.main()
