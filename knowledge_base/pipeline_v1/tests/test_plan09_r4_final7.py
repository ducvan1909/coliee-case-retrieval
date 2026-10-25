import unittest
from knowledge_base.pipeline_v1.au_gold.core import load_json,validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,dependencies,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_final7 import BATCH_ID,make_proposal
IDS=['at-ee2e12aeef17269d91410e7e','at-f71923e1a0ac847eaf65fdcc','at-f84bcbf2e61c72f291935ac4','at-f9b94a5e5fb3e05554f4c167','at-f9be712086516d8fe612b889','at-fefd2e4233313a501663cb35','at-ffb5c4acb13eda43b742abd3']

class Final7DecisionTests(unittest.TestCase):
    def test_nested_letter_statutory_speakers_and_scope(self):
        p,s,pol=dependencies(ROOT,'099980');ts={t['target_id']:t for t in p['tasks']};counts=[]
        for n,tid in enumerate(IDS,1):
            q=make_proposal(ts[tid],p,s,n,{'batch_id':BATCH_ID});validate_model_proposal(q,p,s,pol);r=q['target_reviews'][0];aus=r['authority_units'];counts.append((len(aus),r['hard_negative'] is not None))
            if n==1:self.assertEqual(aus[0]['attributions'][0]['speaker'],'cited_court');self.assertIn('former',aus[0]['limit_spans'][0]['quote'])
            if n==4:self.assertEqual(r['hard_negative']['reason'],'party_argument_only')
            if n==5:self.assertEqual(aus[0]['attributions'][0]['speaker'],'commission_correspondence');self.assertIn('outweighs privacy',aus[0]['condition_spans'][0]['quote']);self.assertTrue(aus[0]['condition_spans'][1]['quote'].startswith('Should the PSC'));self.assertNotIn('matter is founded',aus[0]['evidence_spans'][0]['quote'])
            if n==7:self.assertEqual(len(aus),3);self.assertTrue(aus[0]['evidence_spans'][0]['quote'].startswith('In accordance'));self.assertIn('consistent',aus[2]['limit_spans'][1]['quote']);self.assertTrue(all(aus[i]['evidence_spans'][0]['end_char']<=aus[i+1]['evidence_spans'][0]['start_char'] for i in (0,1)))
        self.assertEqual((sum(a for a,_ in counts),sum(n for _,n in counts)),(5,4))

class Final7PersistedTests(unittest.TestCase):
    def test_final_exact_coverage_and_locked_independent_gate(self):
        v=load_json(ROOT/'r4_final7_validation.json');b=load_json(ROOT/v['batch_ref']);self.assertEqual(b['target_ids'],IDS);self.assertTrue(b['frozen_before_raw_source_review']);self.assertEqual((v['reviewed_before'],v['reviewed_after'],v['missing_before'],v['missing_after']),(362,369,7,0));self.assertEqual(len(b['preserved_artifacts']),555)
        for ref,sha in b['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion();m=load_json(ROOT/'model_proposal_manifest.json');self.assertEqual(m['proposals'][:150],b['before_model_manifest']['proposals']);rows=[x for x in m['proposals'] if x['batch_id']==BATCH_ID];self.assertEqual(len(rows),7)
        for x in rows:
            q=load_json(ROOT/x['proposal_ref']);p,s,pol=dependencies(ROOT,q['case_id']);self.assertEqual(validate_model_proposal(q,p,s,pol),load_json(ROOT/x['validation_ref']))
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),369);self.assertEqual(v['effective_counts'],{'authority_units':187,'hard_negatives':185,'unresolved':10})
        c=load_json(ROOT/'r4_coverage_completion.json');self.assertTrue(c['exact_expected_case_target_set_verified']);self.assertEqual(c['gates'],{'r3_pass':True,'r4_coverage_complete':True,'r5_final_audit_pass':False,'plan10_allowed':False});self.assertEqual(c['missing_target_count'],0);self.assertTrue(all(r['coverage_complete'] and not r['missing_target_ids'] for r in c['cases']))
        self.assertTrue(c['r4_all_sidecars_hash_bound']);self.assertEqual(c['legacy_sidecar_absence_count'],17);self.assertTrue(c['legacy_sidecars_not_created_or_modified']);self.assertTrue(all(not r['existing_sidecar_present'] and r['fresh_validation']['semantic_gold']==False for r in c['legacy_proposals_without_sidecar']))
        for r in c['bound_artifacts']:
            if r['ref']=='reports/plan09_model_silver_progress.latest.json' and (ROOT/'r4_fourth10_correction_frozen.json').exists():
                frozen=load_json(ROOT/'r4_fourth10_correction_frozen.json');self.assertEqual(frozen['before_progress_sha256'],r['sha256']);self.assertEqual(digest(ROOT.parents[1]/frozen['before_progress_snapshot_ref']),r['sha256'])
            else:self.assertEqual(digest(ROOT.parents[1]/r['ref']),r['sha256'])
