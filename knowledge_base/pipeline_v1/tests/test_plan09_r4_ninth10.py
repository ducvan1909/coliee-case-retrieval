import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_ninth10 import BATCH_ID,make_proposal

IDS=['at-85da5a3bc284d68445e19c26','at-85f5879a84c34e2201fc207f','at-867e2531fb535451e4d16e4d','at-86db1baf17aae56596742d23','at-8733e4b4d14fe59b3f2f3eec','at-889ec63c9b2044652d7bc22f','at-89b21721fd80d67c69db253b','at-8e0a98db1c36c55a5caa9a12','at-8edbbc3df5180b14d919415d','at-8f23d518e0197e14ac57c53f']


class Ninth10DecisionTests(unittest.TestCase):
    def test_exact_source_speakers_conditions_and_scope(self):
        p,s,pol=dependencies(ROOT,'099980');tasks={t['target_id']:t for t in p['tasks']};outcomes=[]
        for position,tid in enumerate(IDS,1):
            v=make_proposal(tasks[tid],p,s,position,{'batch_id':BATCH_ID});validate_model_proposal(v,p,s,pol);r=v['target_reviews'][0];outcomes.append(r['model_outcome'])
            if position==1:self.assertIn('no jurisdiction issue',r['authority_units'][0]['condition_spans'][1]['quote']);self.assertIn('definitive opinion',r['context_spans'][1]['quote'])
            if position==3:
                a=r['authority_units'][0];self.assertEqual(len(a['condition_spans']),2);self.assertIn('more latitude',a['exception_spans'][0]['quote']);self.assertIn('without seeking justification',a['limit_spans'][0]['quote'])
            if position==5:self.assertNotIn('This is obvious',r['authority_units'][0]['evidence_spans'][0]['quote'])
            if position==6:self.assertEqual(r['hard_negative']['reason'],'other')
            if position==7:
                a=r['authority_units'][0];self.assertNotIn('Regarding other candidates',a['evidence_spans'][0]['quote']);self.assertEqual(a['limit_spans'][0]['quote'],'any applicable collective agreement');self.assertIn('could be referred',a['limit_spans'][1]['quote'])
            if position==8:self.assertEqual(r['authority_units'][0]['limit_spans'][1]['quote'],'under the circumstances')
            if position==9:self.assertEqual(r['authority_units'][0]['attributions'][0]['speaker'],'cited_court');self.assertEqual(r['authority_units'][0]['condition_spans'][0]['quote'],'where the first inquiry proves unfruitful')
            if position==10:self.assertTrue(r['authority_units'][0]['evidence_spans'][0]['quote'].startswith('Even if'));self.assertNotIn('respondent would like',r['authority_units'][0]['evidence_spans'][0]['quote'])
        self.assertEqual((outcomes.count('positive'),outcomes.count('hard_negative'),outcomes.count('unresolved')),(7,3,0))


class Ninth10PersistedTests(unittest.TestCase):
    def test_frozen_ids_preservation_sidecars_and_model_boundary(self):
        v=load_json(ROOT/'r4_ninth10_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS);self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual(b['evaluation_against'],'model_silver')
        self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(292,302,77,67))
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:80],b['before_model_manifest']['proposals'])
        records=[r for r in m['proposals'] if r['batch_id']==BATCH_ID];self.assertEqual(len(records),10)
        for row in records:
            proposal=load_json(ROOT/row['proposal_ref']);p,s,pol=dependencies(ROOT,proposal['case_id']);self.assertEqual(validate_model_proposal(proposal,p,s,pol),load_json(ROOT/row['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count']);self.assertEqual(v['effective_counts'],{'authority_units':138,'hard_negatives':155,'unresolved':9});self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])


if __name__=='__main__':unittest.main()
