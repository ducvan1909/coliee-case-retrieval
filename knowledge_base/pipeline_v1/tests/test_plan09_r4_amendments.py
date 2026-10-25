import copy,unittest
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError,canonical_hash,load_json
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,digest,effective_proposals
from knowledge_base.pipeline_v1.au_gold.r4_amendments import validate,checkpoint,effective_count_delta
from knowledge_base.pipeline_v1.correct_plan09_r4_fourth10 import TARGETS,make,FROZEN

class R4AmendmentDecisionTests(unittest.TestCase):
    def test_exact_source_speaker_and_narrow_scope(self):
        a=make(1);validate(a);r=a['replacement_review'];au=r['authority_units'][0];self.assertEqual(au['kind'],'standard_of_review');self.assertEqual(au['attributions'][0]['speaker'],'current_court');self.assertTrue(au['evidence_spans'][0]['quote'].startswith('With respect, in my view'));self.assertIn('no declaration',au['cross_block_refs'][1]['quote']);self.assertFalse(r['unresolved_reasons'])
        b=make(2);validate(b);self.assertEqual(b['replacement_review']['hard_negative']['reason'],'party_argument_only');self.assertIn('the applicant argues',b['replacement_review']['reviewed_span']['quote'])
    def test_hash_kind_audit_and_gate_tampering_rejected(self):
        for field,val in [('audit_sha256','0'*64),('supersedes_proposal_sha256','0'*64),('target_id','wrong'),('r5_pass',True)]:
            bad=copy.deepcopy(make(1));bad[field]=val
            with self.assertRaises(AnnotationError):validate(bad)
        bad=copy.deepcopy(make(1));bad['replacement_review']['authority_units'][0]['kind']='holding'
        with self.assertRaises(AnnotationError):validate(bad)

class R4AmendmentPersistedTests(unittest.TestCase):
    def test_exact_two_immutable_overlays_and_only_two_effective_changes(self):
        f=load_json(ROOT/FROZEN);v=load_json(ROOT/'r4_fourth10_correction_validation.json');self.assertEqual(v['target_ids'],TARGETS);self.assertTrue(v['all_other_367_reviews_unchanged']);self.assertEqual(effective_count_delta(),{'authority_units':1,'hard_negatives':1,'unresolved':-2})
        for ref,sha in f['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        hashes={p['case_id']+':'+r['target_id']:canonical_hash(r) for p in effective_proposals() for r in p['target_reviews']};self.assertEqual({key for key in hashes if hashes[key]!=f['before_effective_review_hashes'][key]},{'099980:'+t for t in TARGETS})
        for n in (1,2):
            a=make(n);path=ROOT/'r4_model_amendments'/(a['amendment_id']+'.json');self.assertEqual(load_json(path),a);self.assertEqual(load_json(path.with_suffix('.validation.json')),validate(a));before=digest(path);checkpoint(a);self.assertEqual(digest(path),before)
    def test_revision_coverage_hashes_and_independent_gates(self):
        c=load_json(ROOT/'r4_coverage_completion.after_fourth10_corrections.json');self.assertEqual((c['reviewed_target_count'],c['missing_target_count']),(369,0));self.assertEqual(c['effective_counts'],{'authority_units':188,'hard_negatives':186,'unresolved':8});self.assertEqual(c['supersedes_sha256'],digest(ROOT/'r4_coverage_completion.json'));self.assertFalse(c['r5_pass']);self.assertFalse(c['plan10_allowed'])
        for r in c['bound_artifacts']:self.assertEqual(digest(ROOT.parents[1]/r['ref']),r['sha256'])
