import unittest
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, load_json
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT, amendment_heads, assert_lockable, dependencies, digest, registry, risk_review_heads, validate_amendment, validate_risk_review


class AuditCorrectionTests(unittest.TestCase):
    def test_revision_heads_and_immutable_parent_hashes(self):
        heads = {v['review_id'] for v in risk_review_heads()}
        amendments = {v['amendment_id'] for v in amendment_heads()}
        for position in (11, 32):
            ident = f'p09-r3-audit-11-32-{position:02d}-gpt61sol-v2'
            review = load_json(ROOT/'risk_reviews'/(ident+'.json'))
            amendment = load_json(ROOT/'model_amendments'/(ident+'.json'))
            self.assertIn(ident, heads)
            self.assertIn(ident, amendments)
            self.assertTrue(validate_risk_review(review)['valid'])
            validate_amendment(amendment)
            self.assertEqual(review['supersedes_review_sha256'], digest(ROOT/'risk_reviews'/(review['supersedes_review_id']+'.json')))
            if position == 32:
                self.assertEqual(amendment['supersedes_amendment_sha256'], digest(ROOT/'model_amendments'/(amendment['supersedes_amendment_id']+'.json')))

    def test_position11_only_kind_and_provenance_changes(self):
        amendment = load_json(ROOT/'model_amendments/p09-r3-audit-11-32-11-gpt61sol-v2.json')
        original = load_json(ROOT/'model_proposals'/amendment['case_id']/(amendment['supersedes_proposal_id']+'.json'))
        before = next(r for r in original['target_reviews'] if r['target_id'] == amendment['target_id'])['authority_units'][0]
        after = amendment['replacement_review']['authority_units'][0]
        self.assertEqual(after['kind'], 'procedural_rule')
        for key in ('claim_text', 'attributions', 'evidence_spans', 'condition_spans', 'exception_spans', 'limit_spans'):
            self.assertEqual(after[key], before[key], key)

    def test_position32_heading_only_witness_and_exact_support(self):
        amendment = load_json(ROOT/'model_amendments/p09-r3-audit-11-32-32-gpt61sol-v2.json')
        review = amendment['replacement_review']
        self.assertEqual(review['model_outcome'], 'positive')
        self.assertEqual(len(review['authority_units']), 1)
        au = review['authority_units'][0]
        _, source, _ = dependencies(ROOT, amendment['case_id'])
        heading = au['evidence_spans'][0]
        self.assertEqual(len(au['evidence_spans']), 1)
        self.assertEqual((heading['start_char'], heading['end_char']), (11890, 11945))
        self.assertEqual(heading['quote'], source[11890:11945])
        self.assertEqual(au['claim_text'], "The Board never ruled on Mr. Bayavuge's risks of return")
        self.assertEqual(au['attributions'], [{'role':'proposition', 'speaker':'current_court', 'evidence_span':heading}])
        self.assertEqual(au['kind'], 'holding')
        expected = [(11953,12084),(12092,12474),(12482,12755),(12763,13024),(13032,13231)]
        self.assertEqual([(s['start_char'],s['end_char']) for s in au['cross_block_refs']], expected)
        for span in au['cross_block_refs']:
            self.assertEqual(span['quote'], source[span['start_char']:span['end_char']])
        finding = next(f for f in registry()['findings'] if f['finding_id']=='P09-S01')
        self.assertEqual(finding['status'], 'closed')
        assert_lockable(registry())


if __name__ == '__main__':
    unittest.main()
