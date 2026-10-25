import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_eleventh10 import BATCH_ID,make_proposal
IDS=['at-9da27af39832dc60e64122b4','at-a41b1c3147bae9ad5c1f0e11','at-a7039ffbcf81acfdf39a03bc','at-a717d9e338c80464e87d585c','at-a8d96590034d4f26937d6ac4','at-aa407c31bddfef792959ec7e','at-aad011c3eeb3d5201e016a63','at-affded0df7852c0f341cd3b6','at-b0d26b01c226af7bf286f860','at-b16418abd94e0e3822932535']

class Eleventh10DecisionTests(unittest.TestCase):
    def test_source_speaker_and_tentative_bias_boundary(self):
        p,s,pol=dependencies(ROOT,'099980');ts={t['target_id']:t for t in p['tasks']};os=[]
        for n,tid in enumerate(IDS,1):
            v=make_proposal(ts[tid],p,s,n,{'batch_id':BATCH_ID});validate_model_proposal(v,p,s,pol);r=v['target_reviews'][0];os.append(r['model_outcome'])
            if n==2:self.assertTrue(r['authority_units'][0]['evidence_spans'][0]['quote'].startswith('I have decided'));self.assertIn('no declaration',r['authority_units'][0]['cross_block_refs'][0]['quote'])
            if n==5:self.assertNotIn('private sector',r['authority_units'][0]['evidence_spans'][0]['quote']);self.assertNotIn('Martineau',r['authority_units'][0]['evidence_spans'][0]['quote'])
            if n==7:self.assertEqual(r['hard_negative']['reason'],'party_argument_only')
            if n==8:self.assertFalse(r['authority_units']);self.assertIsNone(r['hard_negative']);self.assertTrue(r['unresolved_reasons']);self.assertIn('apprehensions one may have',r['context_spans'][1]['quote'])
            if n==10:self.assertTrue(r['authority_units'][0]['evidence_spans'][0]['quote'].startswith('The Public Sector Integrity'));self.assertIn('protected disclosure',r['authority_units'][0]['limit_spans'][0]['quote'])
        self.assertEqual((os.count('positive'),os.count('hard_negative'),os.count('unresolved')),(3,6,1))

class Eleventh10PersistedTests(unittest.TestCase):
    def test_frozen_preservation_and_sidecars(self):
        v=load_json(ROOT/'r4_eleventh10_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS);self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual(b['evaluation_against'],'model_silver');self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(312,322,57,47))
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:100],b['before_model_manifest']['proposals']);rows=[x for x in m['proposals'] if x['batch_id']==BATCH_ID];self.assertEqual(len(rows),10)
        for x in rows:
            q=load_json(ROOT/x['proposal_ref']);p,s,pol=dependencies(ROOT,q['case_id']);self.assertEqual(validate_model_proposal(q,p,s,pol),load_json(ROOT/x['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count']);self.assertEqual(v['effective_counts'],{'authority_units':149,'hard_negatives':165,'unresolved':10});self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])
