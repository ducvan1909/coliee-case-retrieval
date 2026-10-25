import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_sixth10 import BATCH_ID,make_proposal

IDS=['at-4d1f2de7b9825c4769503ecd','at-53b9e5a98f7f48d4d0b6edeb','at-5504fe5bd31f8b96cf578894','at-5ae776a11ff4273a21d10c5e','at-5b314a4af85452a367b6930c','at-5d005ab7046f40f4effbf4c6','at-5e5b91a4b13687e831ba0418','at-5ec7836e659f3030d36f47ac','at-604adea56602fb87307c1f7d','at-61be17d6a14ab52741a7c2a4']


class Sixth10DecisionTests(unittest.TestCase):
    def test_exact_source_speakers_and_qualifications(self):
        p,s,pol=dependencies(ROOT,'099980');tasks={t['target_id']:t for t in p['tasks']};outcomes=[]
        for position,tid in enumerate(IDS,1):
            v=make_proposal(tasks[tid],p,s,position,{'batch_id':BATCH_ID});validate_model_proposal(v,p,s,pol)
            r=v['target_reviews'][0];outcomes.append(r['model_outcome'])
            if position==1:self.assertTrue(r['authority_units'][0]['evidence_spans'][0]['quote'].endswith('context'))
            if position==3:self.assertIn('consideration must first be given',r['authority_units'][0]['attributions'][0]['evidence_span']['quote'])
            if position==4:self.assertFalse(r['authority_units']);self.assertIsNone(r['hard_negative']);self.assertTrue(r['unresolved_reasons'])
            if position==5:
                a=r['authority_units'][0];self.assertNotIn('The only question',a['evidence_spans'][0]['quote']);self.assertEqual(a['condition_spans'][0]['quote'],'in cases of fraud');self.assertIn('definitive opinion',r['context_spans'][1]['quote'])
            if position==6:self.assertEqual(r['authority_units'][0]['kind'],'standard_of_review');self.assertIn('procedural fairness',r['authority_units'][0]['limit_spans'][0]['quote'])
            if position==8:self.assertIn('exceptional',r['authority_units'][0]['condition_spans'][0]['quote'])
            if position==9:
                a=r['authority_units'][0];self.assertEqual(a['attributions'][0]['speaker'],'statutory_text');self.assertEqual(len(a['condition_spans']),2);self.assertIn('may',a['evidence_spans'][0]['quote']);self.assertNotIn('69. La',a['evidence_spans'][0]['quote'])
        self.assertEqual((outcomes.count('positive'),outcomes.count('hard_negative'),outcomes.count('unresolved')),(7,2,1))


class Sixth10PersistedTests(unittest.TestCase):
    def test_frozen_ids_preservation_and_sidecars(self):
        v=load_json(ROOT/'r4_sixth10_validation.json');b=load_json(ROOT/v['batch_ref'])
        self.assertEqual(b['target_ids'],IDS)
        self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(262,272,107,97))
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:50],b['before_model_manifest']['proposals'])
        records=[r for r in m['proposals'] if r['batch_id']==BATCH_ID];self.assertEqual(len(records),10)
        for row in records:
            proposal=load_json(ROOT/row['proposal_ref']);p,s,pol=dependencies(ROOT,proposal['case_id']);self.assertEqual(validate_model_proposal(proposal,p,s,pol),load_json(ROOT/row['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count'])
        self.assertEqual(v['effective_counts'],{'authority_units':121,'hard_negatives':144,'unresolved':7})
        self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])


if __name__=='__main__':unittest.main()
