import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_fifteenth10 import BATCH_ID,make_proposal
IDS=['at-de62131bac8ca4625cb79fa8','at-df0473b2880f2404b1ca88a9','at-df4dc4c2e982e08f238790d3','at-e1f04c1bf82c16c2655d1a17','at-e214e0f6df0f336908001e71','at-e297aa3d761f69aa6a477a62','at-e37c726311667f70ed6bc96a','at-e72eaee9971b824c3f1eeb46','at-ea2ca4b59d16cea823f1ead2','at-eab531eaedf6a1d8fdd7899c']

class Fifteenth10DecisionTests(unittest.TestCase):
    def test_deference_appeal_and_costs_scope(self):
        p,s,pol=dependencies(ROOT,'099980');ts={t['target_id']:t for t in p['tasks']};counts=[]
        for n,tid in enumerate(IDS,1):
            q=make_proposal(ts[tid],p,s,n,{'batch_id':BATCH_ID});validate_model_proposal(q,p,s,pol);r=q['target_reviews'][0];aus=r['authority_units'];counts.append((len(aus),r['hard_negative'] is not None))
            if n==3:self.assertEqual(aus[0]['kind'],'standard_of_review');self.assertIn('trial judge',aus[0]['limit_spans'][1]['quote']);self.assertIn('no declaration',aus[0]['cross_block_refs'][0]['quote'])
            if n==4:self.assertNotIn('Choice of procedures',aus[0]['evidence_spans'][0]['quote']);self.assertIn('section 67',aus[0]['condition_spans'][0]['quote']);self.assertIn('judicial review',aus[0]['cross_block_refs'][0]['quote'])
            if n==5:self.assertEqual(aus[0]['limit_spans'][0]['quote'],'Under the circumstances');self.assertIn('not directly contradicted',aus[0]['condition_spans'][1]['quote'])
            if n in (2,7,8):self.assertEqual(r['hard_negative']['reason'],'fact_only')
            if n in (9,10):self.assertEqual(len(aus),2);self.assertLessEqual(aus[0]['evidence_spans'][0]['end_char'],aus[1]['evidence_spans'][0]['start_char'])
            if n==9:self.assertEqual(aus[0]['limit_spans'][0]['quote'],'In principle');self.assertNotIn('50 years',aus[0]['evidence_spans'][0]['quote'])
            if n==10:self.assertIn('not incurred on this application',aus[0]['limit_spans'][0]['quote']);self.assertIn('not yet been paid',aus[1]['condition_spans'][0]['quote']);self.assertIn('$12,000',aus[1]['evidence_spans'][0]['quote'])
        self.assertEqual((sum(a for a,_ in counts),sum(n for _,n in counts)),(7,5))

class Fifteenth10PersistedTests(unittest.TestCase):
    def test_frozen_preservation_and_sidecars(self):
        v=load_json(ROOT/'r4_fifteenth10_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS);self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual(b['evaluation_against'],'model_silver');self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(352,362,17,7));self.assertEqual(len(b['preserved_artifacts']),531)
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:140],b['before_model_manifest']['proposals']);rows=[x for x in m['proposals'] if x['batch_id']==BATCH_ID];self.assertEqual(len(rows),10)
        for x in rows:
            q=load_json(ROOT/x['proposal_ref']);p,s,pol=dependencies(ROOT,q['case_id']);self.assertEqual(validate_model_proposal(q,p,s,pol),load_json(ROOT/x['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count']);self.assertEqual(v['effective_counts'],{'authority_units':182,'hard_negatives':181,'unresolved':10});self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])
