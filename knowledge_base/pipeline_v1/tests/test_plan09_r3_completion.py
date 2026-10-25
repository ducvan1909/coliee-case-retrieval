import copy
import tempfile
import unittest
from pathlib import Path
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, atomic_write, load_json
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT, assert_lockable, digest, registry
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.au_gold.progress import build_progress


class R3CompletionTests(unittest.TestCase):
    def test_bound_completion_and_closed_findings(self):
        completion = validate_completion()
        self.assertEqual(completion['r3_status'], 'PASS')
        self.assertEqual({x['position'] for x in completion['accepted_items']}, set(range(1,50)))
        self.assertFalse(completion['semantic_gold'])
        assert_lockable(registry())
        event = load_json(ROOT/'registry_history/p09-r3-final-acceptance-v1.json')
        self.assertEqual(event['before_registry_sha256'], digest(ROOT/event['before_registry_ref']))
        self.assertEqual(event['after_registry'], registry())
        before = load_json(ROOT/event['before_registry_ref'])
        after = registry()
        for old,new in zip(before['findings'],after['findings']):
            if old['finding_id'] not in event['changed_findings']:
                self.assertEqual(old,new)
            else:
                self.assertEqual(old['status'],'pending_reaudit')
                self.assertEqual(new['status'],'closed')
                for key in old:
                    if key != 'status':
                        self.assertEqual(old[key],new[key])

    def test_closure_hash_and_effective_resolution_required(self):
        for key in ('independent_review_sha256','resolution_amendment_sha256'):
            bad = copy.deepcopy(registry())
            next(f for f in bad['findings'] if f['finding_id']=='P09-S01')[key]='0'*64
            with self.assertRaises(AnnotationError) as caught:
                assert_lockable(bad)
            self.assertEqual(caught.exception.code,'silver_semantic_closure_unverified')
        bad = copy.deepcopy(registry())
        next(f for f in bad['findings'] if f['finding_id']=='P09-S01')['resolution_amendment_id']='p09-s01-gpt6-unresolved-v1'
        with self.assertRaises(AnnotationError):
            assert_lockable(bad)

    def test_stale_acceptance_ref_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'outputs/sample'
            completion = copy.deepcopy(load_json(ROOT/'r3_completion.json'))
            completion['bound_artifacts']=[{'ref':'audit.json','sha256':'0'*64}]
            atomic_write(root/'r3_completion.json', completion)
            atomic_write(Path(folder)/'audit.json', {'changed':True})
            with self.assertRaises(AnnotationError) as caught:
                validate_completion(root)
            self.assertEqual(caught.exception.code,'r3_completion_stale')

    def test_r3_does_not_unlock_r4_r5_or_plan10(self):
        progress = build_progress(ROOT)
        manifest=load_json(ROOT/'model_proposal_manifest.json') if (ROOT/'model_proposal_manifest.json').exists() else {'reviewed_target_count':0,'authority_unit_count':0,'hard_negative_count':0,'unresolved_target_count':0}
        self.assertEqual(progress['missing_target_count'],157-manifest['reviewed_target_count'])
        self.assertEqual(progress['reviewed_target_count'],212+manifest['reviewed_target_count'])
        from knowledge_base.pipeline_v1.au_gold.r4_amendments import effective_count_delta
        delta=effective_count_delta(ROOT)
        self.assertEqual((progress['authority_unit_count'],progress['hard_negative_count'],progress['unresolved_target_count']),(98+manifest['authority_unit_count']+delta['authority_units'],113+manifest['hard_negative_count']+delta['hard_negatives'],1+manifest['unresolved_target_count']+delta['unresolved']))
        self.assertEqual(progress['gates'], {'r3_pass':True,'r4_coverage_complete':not progress['missing_target_count'],'r5_final_audit_pass':False,'plan10_allowed':False})
        self.assertFalse(progress['semantic_remediation']['semantic_pass'])


if __name__ == '__main__':
    unittest.main()
