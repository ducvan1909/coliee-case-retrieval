import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from knowledge_base.pipeline_v1.au_gold.core import AnnotationError, atomic_write, load_json, model_review_trace, validate_model_proposal
from knowledge_base.pipeline_v1.au_gold.remediation import ROOT, dependencies, digest, effective_proposals, proposal_records
from knowledge_base.pipeline_v1.au_gold.r4 import checkpoint, rebuild_manifest, MANIFEST
from knowledge_base.pipeline_v1.au_gold.r3_completion import validate_completion
from knowledge_base.pipeline_v1.review_plan09_r4_first10 import BATCH_ID, make_proposal

IDS=['at-002724763909ed3cbd562979','at-04bf386d8c5d925091d491c6','at-054dfde5d03691a3ecdf1850','at-057d175123c3feeaa748a894','at-05b0930b0c23a8bd764d4430','at-05ddb4f2a8aa0a4312eef8e3','at-0875297b672250b6552a1a4c','at-09d62c9c1e03e472ef963e5c','at-0b86a942dd15b6bbbe7e3baa','at-0be8a81021550bf6fad9cdb2']


class R4CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.packet,self.source,self.policy=dependencies(ROOT,'099980')
        self.tasks={t['target_id']:t for t in self.packet['tasks']}
        self.batch={'batch_id':BATCH_ID,'case_id':'099980','source_hash':self.packet['source_hash'],'target_ids':IDS}

    def temporary_root(self,folder):
        root=Path(folder)/'outputs/plan09'
        root.mkdir(parents=True)
        # Only dependency manifests and their actual immutable proposals/packet.
        for name in ('au_annotation_build_manifest.json','terra_proposal_manifest.json'):
            shutil.copyfile(ROOT/name,root/name)
        for row in load_json(ROOT/'terra_proposal_manifest.json')['proposals']:
            path=root/row['proposal_ref'];path.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/row['proposal_ref'],path)
        row=next(c for c in load_json(ROOT/'au_annotation_build_manifest.json')['cases'] if c['case_id']=='099980')
        path=root/row['packet_ref'];path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/row['packet_ref'],path)
        atomic_write(root/'r4_batches'/(BATCH_ID+'.json'),self.batch)
        return root

    def test_atomic_idempotent_resume_and_duplicate_guard(self):
        proposal=make_proposal(self.tasks[IDS[1]],self.packet,self.source,2,self.batch)
        with tempfile.TemporaryDirectory() as folder:
            root=self.temporary_root(folder)
            checkpoint(proposal,self.batch,root,refresh_progress=False)
            before={str(p):digest(p) for p in root.rglob('*.json')}
            self.assertTrue(checkpoint(proposal,self.batch,root,refresh_progress=False)['resumed'])
            self.assertEqual(before,{str(p):digest(p) for p in root.rglob('*.json')})
            other=copy.deepcopy(proposal);other['proposal_id']+='-different'
            with self.assertRaises(AnnotationError) as caught:checkpoint(other,self.batch,root,refresh_progress=False)
            self.assertEqual(caught.exception.code,'checkpoint_duplicate_target')
            # Simulate crash after immutable proposal/sidecar, before manifest commit.
            manifest=load_json(root/MANIFEST);manifest['proposals']=[];atomic_write(root/MANIFEST,manifest)
            self.assertTrue(checkpoint(proposal,self.batch,root,refresh_progress=False)['resumed'])
            self.assertEqual(len(load_json(root/MANIFEST)['proposals']),1)
            manifest=load_json(root/MANIFEST);manifest['reviewed_target_count']=0;atomic_write(root/MANIFEST,manifest)
            self.assertTrue(rebuild_manifest(root)['manifest_rebuild_changed'])
            self.assertEqual(load_json(root/MANIFEST)['reviewed_target_count'],1)

    def test_exact_context_trace_and_nonterra_provenance(self):
        proposal=make_proposal(self.tasks[IDS[0]],self.packet,self.source,1,self.batch)
        self.assertEqual(proposal['artifact_type'],'ModelAUProposal')
        validate_model_proposal(proposal,self.packet,self.source,self.policy)
        for change in ('quote','producer','trace','context'):
            bad=copy.deepcopy(proposal)
            if change=='quote':bad['target_reviews'][0]['authority_units'][0]['evidence_spans'][0]['quote']='not raw'
            if change=='producer':bad['target_reviews'][0]['authority_units'][0]['provenance']['producer_id']='model:gpt-5.6-terra'
            if change=='trace':bad['target_reviews'][0]['review_trace']['target_span_checksum']='0'*64
            if change=='context':bad['target_reviews'][0]['context_spans']=[]
            if change in ('quote','producer'):
                bad['target_reviews'][0]['review_trace']=model_review_trace(self.tasks[IDS[0]],self.source,self.packet['source_hash'],bad['target_reviews'][0])
            with self.assertRaises(AnnotationError):validate_model_proposal(bad,self.packet,self.source,self.policy)

    def test_ten_per_target_decisions_and_speaker_boundaries(self):
        outcomes=[]
        for position,tid in enumerate(IDS,1):
            proposal=make_proposal(self.tasks[tid],self.packet,self.source,position,self.batch)
            validate_model_proposal(proposal,self.packet,self.source,self.policy)
            review=proposal['target_reviews'][0];outcomes.append(review['model_outcome'])
            self.assertEqual(review['reviewed_span']['quote'],self.source[self.tasks[tid]['target_span']['start_char']:self.tasks[tid]['target_span']['end_char']])
            if position==4:self.assertFalse(review['authority_units']);self.assertIn('Directorate',review['notes'][0])
            if position==8:self.assertEqual(review['hard_negative']['reason'],'party_argument_only')
            if position==9:self.assertEqual(review['authority_units'][0]['evidence_spans'][0]['quote'],"The breach of procedural fairness is flagrant in the applicant's case.")
            if position==7:self.assertTrue(review['authority_units'][0]['limit_spans']);self.assertTrue(review['authority_units'][0]['cross_block_refs'])
        self.assertEqual(outcomes.count('positive'),4);self.assertEqual(outcomes.count('hard_negative'),6)


class R4PersistedTests(unittest.TestCase):
    def test_exact_batch_overlay_and_r3_preserved(self):
        report=load_json(ROOT/'r4_first10_validation.json')
        batch=load_json(ROOT/report['batch_ref'])
        self.assertEqual(batch['target_ids'],IDS)
        self.assertEqual((report['missing_before'],report['missing_after']),(157,147))
        for ref,sha in batch['preserved_artifacts'].items():self.assertEqual(digest(ROOT.parents[1]/ref),sha)
        validate_completion()
        manifest=load_json(ROOT/MANIFEST)
        self.assertEqual(len([r for p in effective_proposals() for r in p['target_reviews']]),212+manifest['reviewed_target_count'])
        records=[r for r in manifest['proposals'] if r['batch_id']==BATCH_ID];self.assertEqual(len(records),10)
        for row in records:
            proposal=load_json(ROOT/row['proposal_ref'])
            p,s,pol=dependencies(ROOT,proposal['case_id']);validate_model_proposal(proposal,p,s,pol)
            self.assertEqual(proposal['producer']['model'],'gpt-6.1-sol')
        self.assertFalse(report['independent_acceptance']);self.assertFalse(report['plan10_allowed'])


if __name__=='__main__':unittest.main()
