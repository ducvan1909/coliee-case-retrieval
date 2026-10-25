import copy
import tempfile
import shutil
import unittest
from pathlib import Path
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError,load_json,lock_silver,model_review_trace
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,registry,assert_lockable,digest,validate_amendment,checkpoint_amendment,scan_attribution_risks,effective_proposals,dependencies
from knowledge_base.pipeline_v1.au_gold.progress import build_progress

class RemediationTests(unittest.TestCase):
    def setUp(self):
        self.amendment=load_json(ROOT/'model_amendments/p09-s01-gpt6-unresolved-v1.json')
    def test_severe_quarantine_precedes_lock_and_cannot_be_unresolved_closed(self):
        historical=load_json(ROOT/'registry_history/p09-r3-before-final-acceptance-v1.json')
        with self.assertRaises(AnnotationError) as caught:lock_silver([],[],{}, {},semantic_registry=historical)
        self.assertEqual(caught.exception.code,'silver_semantic_quarantine')
        value=registry();value['findings'][0]['status']='amended_pending_review'
        with self.assertRaises(AnnotationError):assert_lockable(value)
        fabricated=registry();fabricated['findings'][0].update(status='closed',resolution_amendment_id='does-not-exist',independent_review_ref='reports/does-not-exist.md')
        with self.assertRaises(AnnotationError) as caught:assert_lockable(fabricated)
        self.assertEqual(caught.exception.code,'silver_semantic_closure_unverified')
    def test_original_and_historical_unresolved_preserved_effective_head_applied(self):
        original=ROOT/'model_proposals/013948/terra-013948-aafb64c3e03c512941a071a8.json'
        self.assertEqual(digest(original),self.amendment['supersedes_proposal_sha256'])
        raw=load_json(original);self.assertEqual(raw['target_reviews'][0]['model_outcome'],'positive')
        effective=next(x for x in effective_proposals() if x['proposal_id']==self.amendment['supersedes_proposal_id'])
        self.assertEqual(self.amendment['replacement_review']['model_outcome'],'unresolved')
        self.assertEqual(self.amendment['replacement_review']['authority_units'],[])
        from knowledge_base.pipeline_v1.au_gold.remediation import amendment_heads
        head=next(x for x in amendment_heads() if x['target_id']==self.amendment['target_id'])
        self.assertEqual(effective['target_reviews'][0],head['replacement_review'])
    def test_amendment_tamper_and_retry(self):
        checks=validate_amendment(self.amendment)
        self.assertFalse(checks['semantic_gold']);self.assertEqual(checks['hard_negative_count'],0)
        for field in ('source_hash','supersedes_proposal_sha256','target_id'):
            bad=copy.deepcopy(self.amendment);bad[field]='tampered'
            with self.assertRaises(AnnotationError):validate_amendment(bad)
        bad=copy.deepcopy(self.amendment);bad['replacement_review']['review_trace']['target_span_checksum']='0'*64
        with self.assertRaises(AnnotationError):validate_amendment(bad)
        with self.assertRaises(AnnotationError):checkpoint_amendment(self.amendment)
    def test_outcome_provenance_and_incomplete_lock_regressions(self):
        packet,source,policy=dependencies(ROOT,'013948')
        task=next(x for x in packet['tasks'] if x['target_id']==self.amendment['target_id'])
        bad=copy.deepcopy(self.amendment);review=bad['replacement_review'];review.update(model_outcome='positive',unresolved_reasons=[])
        review['review_trace']=model_review_trace(task,source,bad['source_hash'],review)
        with self.assertRaises(AnnotationError):validate_amendment(bad)
        bad=copy.deepcopy(self.amendment);review=bad['replacement_review'];review.update(model_outcome='hard_negative',unresolved_reasons=[],hard_negative={'reason':'party_argument_only','reviewed_span':review['reviewed_span'],'provenance':{'source_type':'human'},'notes':[]})
        review['review_trace']=model_review_trace(task,source,bad['source_hash'],review)
        with self.assertRaises(AnnotationError) as caught:validate_amendment(bad)
        self.assertEqual(caught.exception.code,'amendment_provenance_invalid')
        original=load_json(ROOT/'model_proposals/013948/terra-013948-aafb64c3e03c512941a071a8.json')
        with self.assertRaises(AnnotationError) as caught:lock_silver([packet],[original],policy,{'013948':source},semantic_registry={'findings':[]})
        self.assertEqual(caught.exception.code,'incomplete_silver')
    def test_scanner_reproducible_and_does_not_write_labels(self):
        paths=list((ROOT/'model_proposals').rglob('*.json'));before={str(p):digest(p) for p in paths}
        first=scan_attribution_risks();self.assertEqual(first,scan_attribution_risks())
        self.assertFalse(first['labels_changed'])
        self.assertTrue(any(x['target_id']==self.amendment['target_id'] for x in first['items']))
        self.assertEqual(before,{str(p):digest(p) for p in paths})
    def test_progress_retains_missing_and_quarantine(self):
        progress=build_progress(ROOT)
        appended=load_json(ROOT/'model_proposal_manifest.json')['reviewed_target_count'] if (ROOT/'model_proposal_manifest.json').exists() else 0
        self.assertEqual(progress['missing_target_count'],157-appended)
        self.assertEqual(progress['reviewed_target_count'],212+appended)
        self.assertEqual(progress['semantic_remediation']['open_severe_finding_count'],0)
        self.assertTrue(progress['gates']['r3_pass'])
        self.assertEqual(progress['gates']['r4_coverage_complete'],not progress['missing_target_count'])
        self.assertFalse(progress['gates']['r5_final_audit_pass'])
        self.assertFalse(progress['gates']['plan10_allowed'])
        self.assertEqual(progress['semantic_remediation']['amendment_count'],len(list((ROOT/'model_amendments').glob('*.json'))))
        self.assertEqual(progress['semantic_remediation']['risk_item_count'],49)
        from knowledge_base.pipeline_v1.au_gold.remediation import risk_review_heads
        self.assertEqual(progress['semantic_remediation']['risk_reviewed_count'],len(risk_review_heads()))

if __name__=='__main__':unittest.main()
