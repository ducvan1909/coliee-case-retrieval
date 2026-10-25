import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_fourteenth10 import BATCH_ID,make_proposal
IDS=['at-cf6fca31c74537f0ecac83c6','at-cfec9b9748dc2d026558f94e','at-d13565be34b60a161deff6f7','at-d3a8f76f09003c1f2e1b21e0','at-d539ff9328a73bb8ffbb82cd','at-da684466af6b7841e1098b51','at-dc72e90c34d89d936cac1c43','at-dc744de9dbcd9a3cc38eb32e','at-dd5c27c6731b40e09175035c','at-ddda333f10704998d2b8ac59']

class Fourteenth10DecisionTests(unittest.TestCase):
    def test_threshold_speakers_and_procedure_qualifiers(self):
        p,s,pol=dependencies(ROOT,'099980');ts={t['target_id']:t for t in p['tasks']};counts=[]
        for n,tid in enumerate(IDS,1):
            q=make_proposal(ts[tid],p,s,n,{'batch_id':BATCH_ID});validate_model_proposal(q,p,s,pol);r=q['target_reviews'][0];aus=r['authority_units'];counts.append((len(aus),r['hard_negative'] is not None))
            if n==2:self.assertEqual([a['attributions'][0]['speaker'] for a in aus],['current_court','cited_court']);self.assertIn('following an investigation',aus[0]['condition_spans'][0]['quote']);self.assertIn('by a candidate',aus[1]['limit_spans'][0]['quote'])
            if n==4:self.assertEqual(len(aus[0]['condition_spans']),2);self.assertIn('unable or unwilling',aus[0]['condition_spans'][1]['quote']);self.assertNotIn('no such motion',aus[0]['evidence_spans'][0]['quote'])
            if n==5:self.assertEqual(len(aus),2);self.assertEqual(aus[1]['condition_spans'][0]['quote'],'if applicable');self.assertIn('seems really necessary',aus[1]['limit_spans'][0]['quote']);self.assertNotIn('Distinguishing',aus[1]['evidence_spans'][0]['quote'])
            if n in (2,5):self.assertLessEqual(aus[0]['evidence_spans'][0]['end_char'],aus[1]['evidence_spans'][0]['start_char'])
            if n==6:self.assertIn('no need to express a definitive opinion',aus[0]['evidence_spans'][0]['quote']);self.assertIn('no declaration',aus[0]['cross_block_refs'][0]['quote'])
            if n==8:self.assertIn('be able to comment on a draft',aus[0]['cross_block_refs'][0]['quote'])
            if n==9:self.assertTrue(aus[0]['evidence_spans'][0]['quote'].startswith('Furthermore'));self.assertEqual(aus[0]['limit_spans'][0]['quote'],'section 72')
            if n==10:self.assertEqual(r['hard_negative']['reason'],'procedural_history_only')
        self.assertEqual((sum(a for a,_ in counts),sum(n for _,n in counts)),(9,3))

class Fourteenth10PersistedTests(unittest.TestCase):
    def test_frozen_preservation_and_sidecars(self):
        v=load_json(ROOT/'r4_fourteenth10_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS);self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual(b['evaluation_against'],'model_silver');self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(342,352,27,17));self.assertEqual(len(b['preserved_artifacts']),507)
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:130],b['before_model_manifest']['proposals']);rows=[x for x in m['proposals'] if x['batch_id']==BATCH_ID];self.assertEqual(len(rows),10)
        for x in rows:
            q=load_json(ROOT/x['proposal_ref']);p,s,pol=dependencies(ROOT,q['case_id']);self.assertEqual(validate_model_proposal(q,p,s,pol),load_json(ROOT/x['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+m['reviewed_target_count']);self.assertEqual(v['effective_counts'],{'authority_units':175,'hard_negatives':176,'unresolved':10});self.assertFalse(v['independent_acceptance']);self.assertFalse(v['plan10_allowed'])
