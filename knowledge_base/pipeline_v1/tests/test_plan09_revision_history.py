import copy
import tempfile
import unittest
from pathlib import Path
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError,atomic_write,load_json
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT,digest,lineage_heads,validate_risk_review,risk_review_heads,amendment_heads,validate_amendment,checkpoint_amendment,checkpoint_risk_review_revision,effective_proposals

class HistoryTests(unittest.TestCase):
    def test_head_hash_fork_and_cycle_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            old={'id':'old','owner':'target'};atomic_write(root/'old.json',old)
            new={'id':'new','owner':'target','parent':'old','parent_hash':digest(root/'old.json')};atomic_write(root/'new.json',new)
            def heads(values):return lineage_heads(values,root,'id','parent','parent_hash',('owner',))
            self.assertEqual(heads([new,old]),[new]) # not filename-order dependent
            for patch in ({'parent_hash':'0'*64},{'owner':'different'},{'parent':'missing'}):
                bad=copy.deepcopy(new);bad.update(patch)
                with self.assertRaises(AnnotationError):heads([old,bad])
            branch={**new,'id':'fork'}
            with self.assertRaises(AnnotationError):heads([old,new,branch])
            with self.assertRaises(AnnotationError):heads([old,{'id':'other-root','owner':'target'}])
            with self.assertRaises(AnnotationError):heads([{'id':'self','owner':'target','parent':'self','parent_hash':'x'}])

    def test_quote_normalization_is_rejected(self):
        review=load_json(ROOT/'risk_reviews/p09-r3-first10-06-gpt61sol-v1.json')
        self.assertIn('M\u00e9xico',review['target_span']['quote'])
        bad=copy.deepcopy(review)
        bad['target_span']['quote']=bad['target_span']['quote'].replace('M\u00e9xico','M\ufffdxico')
        with self.assertRaises(AnnotationError) as caught:validate_risk_review(bad)
        self.assertEqual(caught.exception.code,'quote_mismatch')

    def test_persisted_audit_revisions(self):
        heads={x['target_id']:x for x in risk_review_heads()}
        for position in (2,6,10):
            value=load_json(ROOT/'risk_reviews'/f'p09-r3-first10-audit-{position:02d}-gpt61sol-v2.json')
            self.assertEqual(heads[value['target_id']]['review_id'],value['review_id'])
            self.assertTrue(validate_risk_review(value)['valid'])
            self.assertEqual(value['supersedes_review_sha256'],digest(ROOT/'risk_reviews'/(value['supersedes_review_id']+'.json')))
            with self.assertRaises(AnnotationError):checkpoint_risk_review_revision(value)
        amendment=load_json(ROOT/'model_amendments/p09-r3-first10-audit-10-gpt61sol-v2.json')
        validate_amendment(amendment)
        self.assertIn(amendment['amendment_id'],[x['amendment_id'] for x in amendment_heads()])
        old=load_json(ROOT/'model_amendments'/(amendment['supersedes_amendment_id']+'.json'))
        self.assertEqual(old['replacement_review']['model_outcome'],'unresolved')
        self.assertEqual(amendment['replacement_review']['model_outcome'],'positive')
        bad=copy.deepcopy(amendment);bad['supersedes_amendment_sha256']='0'*64
        with self.assertRaises(AnnotationError):validate_amendment(bad)
        fork=copy.deepcopy(amendment);fork['amendment_id']='forbidden-fork'
        with self.assertRaises(AnnotationError):checkpoint_amendment(fork)
        counts=[r for p in effective_proposals() for r in p['target_reviews']]
        stored=load_json(ROOT.parents[1]/'reports/plan09_model_silver_progress.latest.json')
        self.assertEqual(sum(r['model_outcome']=='unresolved' for r in counts),stored['unresolved_target_count'])

    def test_audit02_qualifications_and_first10_active_validation(self):
        value=load_json(ROOT/'model_amendments/p09-r3-first10-audit-02-gpt61sol-v2.json')
        validate_amendment(value)
        au=value['replacement_review']['authority_units'][0]
        self.assertIn('developed democratic states',au['claim_text'])
        self.assertTrue(au['condition_spans']);self.assertTrue(au['exception_spans']);self.assertTrue(au['limit_spans'])
        from knowledge_base.pipeline_v1.au_gold.remediation import scan_attribution_risks
        queue=scan_attribution_risks()
        self.assertEqual(queue['pending_model_review_count'],49-len(risk_review_heads()))
        for item in queue['items'][:10]:
            self.assertTrue(validate_risk_review(load_json(ROOT/item['review_ref']))['valid'])

if __name__=='__main__':unittest.main()
