import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json, validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_second10 import BATCH_ID,make_proposal

IDS=['at-0c041e93ec332ab4eaa1354a','at-10bb35c0b238a53d984dfdf8','at-143c4e018a2c0568cdf11a72','at-14a2c80dde4ce6c302eded10','at-14ff8ed5bd6fc2b9d2b9cff5','at-169450a12e07bd505d8d2dab','at-174a2f0bbfd0b2d0d0ee2608','at-188b314c4f3fc2293a2a3f9e','at-19699b1ac79c9676fcc00a6d','at-1f0c7e3838ca599ebd75ae72']


class Second10DecisionTests(unittest.TestCase):
    def test_source_and_qualified_decisions(self):
        packet,source,policy=dependencies(ROOT,'099980')
        tasks={t['target_id']:t for t in packet['tasks']}
        outcomes=[]
        for position,tid in enumerate(IDS,1):
            value=make_proposal(tasks[tid],packet,source,position,{'batch_id':BATCH_ID})
            validate_model_proposal(value,packet,source,policy)
            review=value['target_reviews'][0];outcomes.append(review['model_outcome'])
            self.assertEqual(review['reviewed_span']['quote'],source[tasks[tid]['target_span']['start_char']:tasks[tid]['target_span']['end_char']])
            if position==1:
                self.assertEqual(review['authority_units'],[]);self.assertIsNone(review['hard_negative']);self.assertTrue(review['unresolved_reasons'])
                self.assertIn('definitive opinion',review['context_spans'][0]['quote'])
            if position in (2,5,7):self.assertEqual(review['hard_negative']['reason'],'party_argument_only')
            if position==8:
                au=review['authority_units'][0]
                self.assertEqual(au['attributions'][0]['speaker'],'current_court')
                self.assertNotIn('Commission noted',au['evidence_spans'][0]['quote'])
                self.assertIn('good faith',au['exception_spans'][0]['quote'])
            if position==9:
                au=review['authority_units'][0]
                self.assertIn('assuming',au['claim_text'].lower())
                self.assertIn('assumption',au['condition_spans'][0]['quote'])
                self.assertIn('no need to express a definitive opinion',au['limit_spans'][0]['quote'])
                self.assertEqual(au['kind'],'procedural_rule')
        self.assertEqual((outcomes.count('positive'),outcomes.count('hard_negative'),outcomes.count('unresolved')),(2,7,1))


class Second10PersistedTests(unittest.TestCase):
    def test_batch_overlay_exact_ids_and_preservation(self):
        report=load_json(ROOT/'r4_second10_validation.json')
        batch=load_json(ROOT/report['batch_ref'])
        self.assertEqual(batch['target_ids'],IDS)
        self.assertEqual((report['missing_before'],report['missing_after']),(147,137))
        for ref,sha in batch['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion()
        manifest=load_json(ROOT/'model_proposal_manifest.json')
        self.assertEqual(manifest['proposals'][:10],batch['before_model_manifest']['proposals'])
        records=[r for r in manifest['proposals'] if r['batch_id']==BATCH_ID]
        self.assertEqual(len(records),10)
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+manifest['reviewed_target_count'])
        for row in records:
            proposal=load_json(ROOT/row['proposal_ref'])
            p,s,pol=dependencies(ROOT,proposal['case_id'])
            self.assertEqual(validate_model_proposal(proposal,p,s,pol),load_json(ROOT/row['validation_ref']))
            self.assertEqual(proposal['producer']['model'],'gpt-6.1-sol')
        self.assertEqual(report['effective_counts'],{'authority_units':104,'hard_negatives':126,'unresolved':2})
        self.assertFalse(report['independent_acceptance']);self.assertFalse(report['plan10_allowed'])


if __name__=='__main__':unittest.main()
