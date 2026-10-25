import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, atomic_write, exact_span, load_json
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT, dependencies, scan_attribution_risks, validate_risk_review, checkpoint_risk_review


class RiskReviewTests(unittest.TestCase):
    def setUp(self):
        self.items = scan_attribution_risks(include_reviews=False)['items']
        item = self.items[0]
        packet, source, _ = dependencies(ROOT,item['case_id'])
        task = next(x for x in packet['tasks'] if x['target_id']==item['target_id'])
        a,b = task['target_span']['start_char'],task['target_span']['end_char']
        self.review = {k:item[k] for k in ('proposal_id','proposal_sha256','case_id','source_hash','target_id','au_id')}
        self.review.update(artifact_type='Plan09AttributionRiskReview',review_id='test-review',reviewer={'source_type':'model','reviewer_id':'test','model':'gpt-6.1-sol'},outcome='keep',reason='Current court expressly adopts this standard.',target_span=exact_span(source,item['case_id'],item['source_hash'],a,b),context_spans=[exact_span(source,item['case_id'],item['source_hash'],a-100,b+100)],amendment_id=None,semantic_gold=False)

    def test_valid_and_tamper(self):
        self.assertTrue(validate_risk_review(self.review,items=self.items)['valid'])
        for field in ('source_hash','proposal_sha256','target_id','au_id'):
            bad=copy.deepcopy(self.review);bad[field]='changed'
            with self.assertRaises(AnnotationError):validate_risk_review(bad,items=self.items)
        bad=copy.deepcopy(self.review);bad['context_spans']=[bad['target_span']]
        with self.assertRaises(AnnotationError):validate_risk_review(bad,items=self.items)
        bad=copy.deepcopy(self.review);bad['target_span']['quote']='wrong'
        with self.assertRaises(AnnotationError):validate_risk_review(bad,items=self.items)
        bad=copy.deepcopy(self.review);bad['outcome']='amendment'
        with self.assertRaises(AnnotationError):validate_risk_review(bad,items=self.items)

    def test_atomic_checkpoint_order_and_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            queue={'items':self.items}
            with patch('knowledge_base.pipeline_v1.au_gold.remediation.validate_risk_review',return_value={'valid':True}), patch('knowledge_base.pipeline_v1.au_gold.remediation.scan_attribution_risks',return_value=queue):
                wrong=copy.deepcopy(self.review);wrong['target_id']=self.items[1]['target_id']
                with self.assertRaises(AnnotationError):checkpoint_risk_review(wrong,root)
                checkpoint_risk_review(self.review,root)
                self.assertEqual(load_json(root/'risk_reviews/test-review.json'),self.review)
                with self.assertRaises(AnnotationError):checkpoint_risk_review(self.review,root)

    def test_persisted_records_rebuild_queue_without_label_writes(self):
        from knowledge_base.pipeline_v1.au_gold.remediation import digest
        paths=list((ROOT/'model_proposals').rglob('*.json'))
        before={str(p):digest(p) for p in paths}
        queue=scan_attribution_risks()
        from knowledge_base.pipeline_v1.au_gold.remediation import risk_review_heads
        records=[ROOT/'risk_reviews'/(x['review_id']+'.json') for x in risk_review_heads()]
        self.assertEqual(queue['pending_model_review_count'],49-len(records))
        self.assertEqual(queue,scan_attribution_risks())
        for path in records:
            review=load_json(path)
            self.assertTrue(validate_risk_review(review,items=self.items)['valid'])
            if review['outcome']!='keep':
                bad=copy.deepcopy(review);bad['reviewer']['model']='another-model'
                with self.assertRaises(AnnotationError):validate_risk_review(bad,items=self.items)
        self.assertEqual(before,{str(p):digest(p) for p in paths})


if __name__=='__main__':unittest.main()
