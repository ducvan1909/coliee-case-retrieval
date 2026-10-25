import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_thirteenth10 import BATCH_ID,make_proposal
IDS=['at-c1baab4b25dbdf81279b1402','at-c1cc43ba1d61581499bf96ef','at-c346a3add188a66127ed9fb5','at-c41bd6c6fd1528e62af858c6','at-c45b12bb6a6e0ed072ba48ac','at-c4bae0c79c06c92fb4b2d5a9','at-c60115e01538c3e186265929','at-c9c5a308ac656af5df34017b','at-cc3ed060180327fc9de7fa85','at-cdff3df736823759bcfd28d9']

class Thirteenth10DecisionTests(unittest.TestCase):
    def test_source_attribution_inference_and_remittal(self):
        p,s,pol=dependencies(ROOT,'099980');ts={t['target_id']:t for t in p['tasks']};counts=[]
        for n,tid in enumerate(IDS,1):
            q=make_proposal(ts[tid],p,s,n,{'batch_id':BATCH_ID});validate_model_proposal(q,p,s,pol);r=q['target_reviews'][0];aus=r['authority_units'];counts.append((len(aus),r['hard_negative'] is not None))
            if n==1:self.assertNotIn('Legitimate hopes of the person',aus[0]['evidence_spans'][0]['quote']);self.assertIn('not a legal holding',r['notes'][0].lower())
            if n==3:self.assertTrue(aus[0]['evidence_spans'][0]['quote'].startswith('First, fraud'));self.assertEqual(aus[0]['limit_spans'][0]['quote'],'supports the inference');self.assertEqual(aus[0]['condition_spans'][0]['quote'],'If it was in good faith')
            if n==4:
                self.assertEqual(len(aus),2);self.assertTrue(all(a['attributions'][0]['speaker']=='cited_commission_decision' for a in aus));self.assertIn('absence of evidence of bad faith',aus[0]['condition_spans'][0]['quote']);self.assertIn('link the misconduct',aus[1]['condition_spans'][0]['quote']);self.assertIn('Personnel Psychology Centre',aus[0]['attributions'][1]['evidence_span']['quote'])
            if n==6:
                self.assertEqual(len(aus),2);self.assertTrue(all(a['attributions'][0]['speaker']=='cited_court' for a in aus));self.assertIn('Justice Stratas',aus[0]['attributions'][1]['evidence_span']['quote']);self.assertEqual(aus[1]['limit_spans'][0]['quote'],'may disable the tribunal')
            if n in (4,6,9):self.assertLessEqual(aus[0]['evidence_spans'][0]['end_char'],aus[1]['evidence_spans'][0]['start_char'])
            if n==8:self.assertEqual(r['hard_negative']['reason'],'fact_only');self.assertIn('In my view',r['context_spans'][1]['quote'])
            if n==9:self.assertEqual(len(aus),2);self.assertNotIn('always involved candidates',aus[1]['evidence_spans'][0]['quote']);self.assertIn('balance of probabilities',aus[1]['evidence_spans'][0]['quote'])
            if n==10:self.assertEqual(aus[0]['limit_spans'][0]['quote'],'It seems to me');self.assertIn('not saying',aus[0]['cross_block_refs'][0]['quote'])
        self.assertEqual((sum(a for a,_ in counts),sum(n for _,n in counts)),(9,4))

class Thirteenth10PersistedTests(unittest.TestCase):
    def test_frozen_preservation_and_sidecars(self):
        v=load_json(ROOT/'r4_thirteenth10_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS);self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual(b['evaluation_against'],'model_silver');self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(332,342,37,27));self.assertEqual(len(b['preserved_artifacts']),483)
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:120],b['before_model_manifest']['proposals']);rows=[x for x in m['proposals'] if x['batch_id']==BATCH_ID];self.assertEqual(len(rows),10)
        for x in rows:
            q=load_json(ROOT/x['proposal_ref']);p,s,pol=dependencies(ROOT,q['case_id']);self.assertEqual(validate_model_proposal(q,p,s,pol),load_json(ROOT/x['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count']);self.assertEqual(v['effective_counts'],{'authority_units':166,'hard_negatives':173,'unresolved':10});self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])
