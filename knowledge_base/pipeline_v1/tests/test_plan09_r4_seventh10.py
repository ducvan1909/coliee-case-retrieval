import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_seventh10 import BATCH_ID,make_proposal

IDS=['at-630e5b3107f31ec30d483195','at-67a28257657db209f376306f','at-681c23ac14ba9fb3033bec0a','at-69b26fc821f7b89ea6c8ff88','at-6a766cf8a9d8a233e4056107','at-6b416be133c2ad82afda7242','at-6dccd1f10e05f9a2f1159ec6','at-706534560fc7a1f24d660294','at-73614cc48a493ce944b21023','at-754e1b56d19dc114d5bbceca']


class Seventh10DecisionTests(unittest.TestCase):
    def test_exact_source_speakers_scope_and_reservation(self):
        p,s,pol=dependencies(ROOT,'099980');tasks={t['target_id']:t for t in p['tasks']};outcomes=[]
        for position,tid in enumerate(IDS,1):
            v=make_proposal(tasks[tid],p,s,position,{'batch_id':BATCH_ID});validate_model_proposal(v,p,s,pol)
            r=v['target_reviews'][0];outcomes.append(r['model_outcome'])
            if position in (2,4,5):self.assertEqual(r['hard_negative']['reason'],'party_argument_only')
            if position==3:
                a=r['authority_units'][0];self.assertEqual(a['attributions'][0]['speaker'],'commission_policy');self.assertNotIn('What is fraud?',a['evidence_spans'][0]['quote']);self.assertIn('According to the Policy',a['cross_block_refs'][0]['quote'])
            if position==7:self.assertFalse(r['authority_units']);self.assertIsNone(r['hard_negative']);self.assertTrue(r['unresolved_reasons']);self.assertIn('definitive opinion',r['context_spans'][1]['quote'])
            if position==8:self.assertEqual(r['authority_units'][0]['limit_spans'][0]['quote'],'in this case')
            if position==9:
                a=r['authority_units'][0];self.assertEqual(a['kind'],'procedural_rule');self.assertIn('one should first be satisfied',a['evidence_spans'][0]['quote']);self.assertNotIn('Before assessing the parties',a['evidence_spans'][0]['quote']);self.assertIn('definitive opinion',r['context_spans'][1]['quote'])
            if position==10:
                a=r['authority_units'][0];self.assertIn('no declaration',a['exception_spans'][0]['quote']);self.assertIn('exclusive benefit',a['limit_spans'][0]['quote']);self.assertIn('insofar',a['limit_spans'][1]['quote'])
        self.assertEqual((outcomes.count('positive'),outcomes.count('hard_negative'),outcomes.count('unresolved')),(4,5,1))


class Seventh10PersistedTests(unittest.TestCase):
    def test_frozen_ids_preservation_sidecars_and_model_boundary(self):
        v=load_json(ROOT/'r4_seventh10_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS)
        self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual(b['evaluation_against'],'model_silver')
        self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(272,282,97,87))
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:60],b['before_model_manifest']['proposals'])
        records=[r for r in m['proposals'] if r['batch_id']==BATCH_ID];self.assertEqual(len(records),10)
        for row in records:
            proposal=load_json(ROOT/row['proposal_ref']);p,s,pol=dependencies(ROOT,proposal['case_id']);self.assertEqual(validate_model_proposal(proposal,p,s,pol),load_json(ROOT/row['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count'])
        self.assertEqual(v['effective_counts'],{'authority_units':125,'hard_negatives':149,'unresolved':8})
        self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])


if __name__=='__main__':unittest.main()
