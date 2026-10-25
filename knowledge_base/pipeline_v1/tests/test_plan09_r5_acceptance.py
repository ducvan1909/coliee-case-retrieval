import copy
import tempfile
import unittest
from pathlib import Path
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, atomic_write, load_json
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT, digest
from knowledge_base.pipeline_v1.au_gold.r5_acceptance import audited_state, make_decision, verify_bindings

class R5AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state=audited_state(ROOT)

    def test_full_audit_binding_counts_and_frozen_gate(self):
        progress, hashes, unresolved, bindings=self.state
        self.assertEqual(len(hashes),369)
        self.assertEqual(len(unresolved),8)
        self.assertEqual((progress['authority_unit_count'],progress['hard_negative_count']),(188,186))
        self.assertFalse(progress['gates']['plan10_allowed'])
        self.assertFalse(progress['semantic_gold'])
        coverage=load_json(ROOT/'r4_coverage_completion.after_fourth10_corrections.json')
        self.assertEqual(len(coverage['bound_artifacts']),417)
        self.assertEqual(coverage['legacy_sidecar_absence_count'],17)
        verify_bindings(bindings,ROOT.parents[1])

    def test_scope_is_development_not_human_gold_or_execution(self):
        acceptance={'r5_status':'PASS','semantic_gold':False,'human_gold':False,'limitations':['model_silver only']}
        decision=make_decision(acceptance,'a'*64)
        self.assertTrue(decision['plan10_allowed'])
        self.assertEqual(decision['plan10_allowed_scope'],'baseline_development_only')
        self.assertEqual(decision['evaluation_against'],'model_silver')
        self.assertFalse(decision['plan10_execution_authorized'])
        self.assertFalse(decision['independent_retrieval_quality_estimate'])
        for key,value in [('r5_status','FAIL'),('semantic_gold',True),('human_gold',True)]:
            bad=copy.deepcopy(acceptance);bad[key]=value
            with self.assertRaises(AnnotationError):make_decision(bad,'a'*64)

    def test_stale_missing_duplicate_and_outside_bindings_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            atomic_write(root/'audit.json',{'verdict':'PASS'})
            row={'ref':'audit.json','sha256':digest(root/'audit.json')}
            verify_bindings([row],root)
            for rows in ([{**row,'sha256':'0'*64}], [{**row,'ref':'missing.json'}], [row,row], [{**row,'ref':'../outside.json'}]):
                with self.assertRaises(AnnotationError):verify_bindings(rows,root)
