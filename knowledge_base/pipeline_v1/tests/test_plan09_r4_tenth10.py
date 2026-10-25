import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_tenth10 import BATCH_ID,make_proposal

IDS=['at-8f8857880ffb9989ff95d485','at-9169a7cb049cf248e5c2ce1a','at-9225bf8f48de08423b2764aa','at-950ed802967a5dd1e6352b4e','at-95364ee9fae807cd82176477','at-98814cc80cdfb175986f0de4','at-9a77548a0ed859334746f9be','at-9b01d3f90b10e934c376245e','at-9c36ec4f176e3085aed6e9c8','at-9d5ed1c1ad745b3679a3f919']


class Tenth10DecisionTests(unittest.TestCase):
    def test_exact_source_speakers_scoped_orders_and_thresholds(self):
        p,s,pol=dependencies(ROOT,'099980');tasks={t['target_id']:t for t in p['tasks']};outcomes=[];aus=0
        for position,tid in enumerate(IDS,1):
            v=make_proposal(tasks[tid],p,s,position,{'batch_id':BATCH_ID});validate_model_proposal(v,p,s,pol);r=v['target_reviews'][0];outcomes.append(r['model_outcome']);aus+=len(r['authority_units'])
            if position==1:self.assertTrue(r['authority_units'][0]['evidence_spans'][0]['quote'].startswith('On this point'));self.assertIn('Rule 400',r['authority_units'][0]['limit_spans'][0]['quote'])
            if position==3:self.assertEqual(r['authority_units'][0]['attributions'][0]['speaker'],'cited_court');self.assertIn('do not apply in this case',r['context_spans'][1]['quote'])
            if position==4:self.assertEqual(len(r['authority_units'][0]['condition_spans']),5)
            if position==6:
                self.assertEqual(len(r['authority_units']),3);relief,costs,finality=r['authority_units'];spans=[a['evidence_spans'][0] for a in r['authority_units']];self.assertTrue(all(x['end_char']<=y['start_char'] for x,y in zip(spans,spans[1:])));self.assertIn('insofar',relief['limit_spans'][0]['quote']);self.assertIn('not yet been paid',costs['condition_spans'][0]['quote']);self.assertEqual(finality['condition_spans'][0]['quote'],'upon the expiry of rights of appeal');self.assertNotIn('Editor:',finality['evidence_spans'][0]['quote'])
            if position==8:self.assertEqual(r['hard_negative']['reason'],'other')
            if position==10:self.assertEqual(len(r['authority_units'][0]['condition_spans']),2);self.assertIn('definitive opinion',r['context_spans'][1]['quote'])
        self.assertEqual((outcomes.count('positive'),outcomes.count('hard_negative'),outcomes.count('unresolved'),aus),(6,4,0,8))


class Tenth10PersistedTests(unittest.TestCase):
    def test_frozen_ids_preservation_sidecars_and_model_boundary(self):
        v=load_json(ROOT/'r4_tenth10_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS);self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual(b['evaluation_against'],'model_silver')
        self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(302,312,67,57))
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:90],b['before_model_manifest']['proposals'])
        records=[r for r in m['proposals'] if r['batch_id']==BATCH_ID];self.assertEqual(len(records),10)
        for row in records:
            proposal=load_json(ROOT/row['proposal_ref']);p,s,pol=dependencies(ROOT,proposal['case_id']);self.assertEqual(validate_model_proposal(proposal,p,s,pol),load_json(ROOT/row['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count']);self.assertEqual(v['effective_counts'],{'authority_units':146,'hard_negatives':159,'unresolved':9});self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])


if __name__=='__main__':unittest.main()
