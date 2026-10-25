import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_twelfth10 import BATCH_ID,make_proposal
IDS=['at-b414c5f923125d9ffbb13318','at-b4be11ef36bb42c7a0602c1c','at-b50c20d6fac5a5ff45581b48','at-b69ad45bcc2f35fe4e2f2a4a','at-bb0fadd7519f573da9eaaf9e','at-bcacdc4982d12ca435892d57','at-bed335129a82eef9211c598b','at-bee7bffa49507d9907ed2c9b','at-befd32410e3f601906b6e19a','at-c027337ac756114775dcabdb']

class Twelfth10DecisionTests(unittest.TestCase):
    def test_source_attribution_and_statutory_scope(self):
        p,s,pol=dependencies(ROOT,'099980');ts={t['target_id']:t for t in p['tasks']};counts=[]
        for n,tid in enumerate(IDS,1):
            q=make_proposal(ts[tid],p,s,n,{'batch_id':BATCH_ID});validate_model_proposal(q,p,s,pol);r=q['target_reviews'][0];aus=r['authority_units'];counts.append((len(aus),r['hard_negative'] is not None))
            if n==2:self.assertTrue(aus[0]['condition_spans']);self.assertIn('remedies and costs',aus[0]['limit_spans'][0]['quote'])
            if n==3:
                self.assertEqual(len(aus),2);self.assertTrue(all(a['attributions'][0]['speaker']=='cited_court' for a in aus));self.assertLessEqual(aus[0]['evidence_spans'][0]['end_char'],aus[1]['evidence_spans'][0]['start_char']);self.assertIn('procedural fairness',aus[1]['evidence_spans'][0]['quote']);self.assertIn('Justice Sopinka',aus[0]['attributions'][1]['evidence_span']['quote'])
            if n==5:
                self.assertEqual(len(aus),2);self.assertIn('section 9',aus[0]['evidence_spans'][0]['quote']);self.assertIn('section 12',aus[1]['evidence_spans'][0]['quote']);self.assertEqual(aus[0]['condition_spans'][0]['quote'],'if he or she commits a wrongdoing')
            if n==6:self.assertIn('in this case',aus[0]['limit_spans'][1]['quote']);self.assertIn('not saying',aus[0]['cross_block_refs'][0]['quote'])
            if n==7:self.assertIn('no persons',aus[0]['condition_spans'][0]['quote']);self.assertIn('subsection (3)',aus[0]['cross_block_refs'][0]['quote']);self.assertNotIn('FRAGMENT_SUPPRESSED',aus[0]['evidence_spans'][0]['quote'])
            if n==8:self.assertEqual(r['hard_negative']['reason'],'party_argument_only')
            if n==10:self.assertIn('section 69',aus[0]['limit_spans'][0]['quote']);self.assertIn('discrimination',aus[0]['limit_spans'][1]['quote'])
        self.assertEqual((sum(a for a,_ in counts),sum(n for _,n in counts)),(8,4))

class Twelfth10PersistedTests(unittest.TestCase):
    def test_frozen_preservation_and_sidecars(self):
        v=load_json(ROOT/'r4_twelfth10_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS);self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual(b['evaluation_against'],'model_silver');self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(322,332,47,37))
        self.assertEqual(len(b['preserved_artifacts']),459)
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:110],b['before_model_manifest']['proposals']);rows=[x for x in m['proposals'] if x['batch_id']==BATCH_ID];self.assertEqual(len(rows),10)
        for x in rows:
            q=load_json(ROOT/x['proposal_ref']);p,s,pol=dependencies(ROOT,q['case_id']);self.assertEqual(validate_model_proposal(q,p,s,pol),load_json(ROOT/x['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count']);self.assertEqual(v['effective_counts'],{'authority_units':157,'hard_negatives':169,'unresolved':10});self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])
