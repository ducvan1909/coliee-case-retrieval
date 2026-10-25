import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_third10 import BATCH_ID,make_proposal

IDS=['at-1f8713f545365df1f151daa4','at-23e0d9d111911c28fba85628','at-246ff349485b66f67fe5c39d','at-25a47b63b5767f7bc735f6be','at-27935875158c3bd52e6220aa','at-27d52ebdf0fe44b1ec832078','at-2830ad7af31dc36e2dfd45a2','at-298921465b894cd1e165f1c2','at-2ad9077730065065ecf5523f','at-2be613d920e6ea831c8e3022']


class Third10DecisionTests(unittest.TestCase):
    def test_exact_source_and_speaker_qualifications(self):
        p,source,policy=dependencies(ROOT,'099980');tasks={t['target_id']:t for t in p['tasks']};outcomes=[]
        for position,tid in enumerate(IDS,1):
            value=make_proposal(tasks[tid],p,source,position,{'batch_id':BATCH_ID})
            validate_model_proposal(value,p,source,policy)
            r=value['target_reviews'][0];outcomes.append(r['model_outcome'])
            if position in (1,3):self.assertEqual(r['hard_negative']['reason'],'editorial')
            if position==2:
                a=r['authority_units'][0];self.assertTrue(a['condition_spans']);self.assertTrue(a['limit_spans']);self.assertIn('To ask the question',a['cross_block_refs'][0]['quote'])
            if position==4:
                a=r['authority_units'][0];self.assertIn('March 31, 2010',a['limit_spans'][0]['quote']);self.assertIn('no way mentions',a['condition_spans'][0]['quote'])
            if position==6:self.assertEqual(r['authority_units'],[]);self.assertIsNone(r['hard_negative']);self.assertTrue(r['unresolved_reasons'])
            if position==7:
                a=r['authority_units'][0];self.assertEqual(a['kind'],'statutory_hook');self.assertNotIn('Review Team',a['evidence_spans'][0]['quote']);self.assertIn('five years',a['limit_spans'][0]['quote'])
            if position==9:self.assertFalse(r['authority_units'])
            if position==10:
                a=r['authority_units'][0];self.assertIn('this impugned decision',a['claim_text']);self.assertEqual(a['uncertainty'],'medium')
        self.assertEqual((outcomes.count('positive'),outcomes.count('hard_negative'),outcomes.count('unresolved')),(4,5,1))


class Third10PersistedTests(unittest.TestCase):
    def test_frozen_batch_preservation_sidecars_and_overlay(self):
        report=load_json(ROOT/'r4_third10_validation.json');batch=load_json(ROOT/report['batch_ref'])
        self.assertEqual(batch['target_ids'],IDS)
        self.assertEqual((report['reviewed_before'],report['reviewed_after'],report['missing_before'],report['missing_after']),(232,242,137,127))
        for ref,sha in batch['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion()
        manifest=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(manifest['proposals'][:20],batch['before_model_manifest']['proposals'])
        records=[r for r in manifest['proposals'] if r['batch_id']==BATCH_ID];self.assertEqual(len(records),10)
        for row in records:
            v=load_json(ROOT/row['proposal_ref']);p,s,pol=dependencies(ROOT,v['case_id'])
            self.assertEqual(validate_model_proposal(v,p,s,pol),load_json(ROOT/row['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+manifest['reviewed_target_count'])
        self.assertEqual(report['effective_counts'],{'authority_units':108,'hard_negatives':131,'unresolved':3})
        self.assertFalse(report['independent_acceptance']);self.assertFalse(report['plan10_allowed'])


if __name__=='__main__':unittest.main()
