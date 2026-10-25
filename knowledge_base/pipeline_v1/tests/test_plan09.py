from __future__ import annotations
import copy,json,unittest
from unittest.mock import patch
from pathlib import Path
from jsonschema import Draft202012Validator
from knowledge_base.pipeline_v1.au_gold import AnnotationError,compare_submissions,create_adjudication_template,create_terra_unresolved_proposal,exact_span,lock_gold,lock_silver,model_review_trace,new_submission,score_predictions,select_few_shot,select_silver_few_shot,transition_annotation_state,validate_adjudication,validate_locked_gold,validate_locked_silver,validate_model_proposal,validate_packet,validate_submission
from knowledge_base.pipeline_v1.au_gold.core import atomic_write,load_json
from knowledge_base.pipeline_v1.au_gold.build import _terra_batches,checkpoint_model_proposal,validate_heldout_lock
from knowledge_base.pipeline_v1.execution_ledger.build import load_plan07_workloads
from knowledge_base.pipeline_v1.source_contract import open_source

P=Path(__file__).resolve().parents[1]
POLICY=load_json(P/"policies/au_annotation_policy.v1.json")

class Plan09Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=load_json(P/"reports/plan09_au_gold_readiness.latest.json");cls.root=Path(cls.report["outputs"]["output_root"]);cls.manifest=load_json(cls.report["outputs"]["build_manifest"]);cls.workloads,_,_=load_plan07_workloads(P/"reports/plan07_analysis_region_validation.latest.json");cls.workload=cls.workloads[0];row=next(x for x in cls.manifest["cases"] if x["case_id"]==cls.workload["case_id"]);cls.packet=load_json(cls.root/row["packet_ref"]);cls.text=open_source(cls.manifest["source_store"],cls.packet["case_id"],cls.packet["source_hash"])

    def submission(self,annotator="human-a",positive=True):
        value=new_submission(self.packet,annotator,annotator);value["submission_status"]="independently_annotated"
        for task,review in zip(self.packet["tasks"],value["target_reviews"]):
            span=task["target_span"];reviewed=exact_span(self.text,self.packet["case_id"],self.packet["source_hash"],span["start_char"],span["end_char"]);review["review_complete"]=True;review["reviewed_span"]=reviewed;review["hard_negative"]={"reason":"fact_only","reviewed_span":reviewed,"provenance":{"source_type":"human","annotator_id":annotator,"guideline_version":self.packet["guideline_version"],"derived_from":[]},"notes":[]}
        if positive:
            task=self.packet["tasks"][0];review=value["target_reviews"][0];a=task["target_span"]["start_char"];b=min(a+20,task["target_span"]["end_char"]);span=exact_span(self.text,self.packet["case_id"],self.packet["source_hash"],a,b);review["hard_negative"]=None;review["authority_units"]=[{"au_id":"au-"+annotator,"owner_target_id":task["target_id"],"owner_block_id":task["owner_block_id"],"claim_text":"Human-entered synthetic fixture claim","kind":"holding","other_kind":None,"evidence_spans":[span],"attributions":[{"role":"proposition","speaker":"current_court","evidence_span":span}],"condition_spans":[],"exception_spans":[],"limit_spans":[],"cross_block_refs":[],"overlap_disposition":"none","duplicate_of":None,"status":"independently_annotated","provenance":{"source_type":"human","annotator_id":annotator,"guideline_version":self.packet["guideline_version"],"derived_from":[]},"notes":[]}]
        return value

    def test_schemas_and_checked_in_readiness_are_honest(self):
        names=("annotation_task.v1.json","annotator_submission.v1.json","authority_unit_human.v1.json","au_disagreement.v1.json","au_adjudication.v1.json","locked_au_gold.v1.json","few_shot_selection.v1.json","terra_au_proposal.v1.json","locked_au_silver.v1.json")
        for name in names:Draft202012Validator.check_schema(load_json(P/"contracts"/name))
        self.assertEqual((self.manifest["packet_count"],self.manifest["target_count"],self.manifest["semantic_label_count"]),(5,369,0));self.assertEqual(self.report["overall_status"],"gold_awaiting_independent_adjudication");self.assertTrue(self.report["gates"]["structural_ready"]);self.assertFalse(self.report["gates"]["silver_ready"]);self.assertFalse(self.report["gates"]["plan10_allowed"])
        terra=load_json(self.root/"terra_annotation_batches.json");self.assertGreaterEqual(terra["batch_count"],96);self.assertEqual(terra["batch_count"],len(terra["batches"]));self.assertEqual(terra["provider_calls"],0)
        proposals=load_json(self.root/"terra_proposal_manifest.json");self.assertEqual(proposals["proposal_count"],len(proposals["proposals"]));self.assertEqual(proposals["reviewed_target_count"],sum(x["reviewed_target_count"] for x in proposals["proposals"]));self.assertEqual(proposals["authority_unit_count"],sum(x["authority_unit_count"] for x in proposals["proposals"]));self.assertFalse(proposals["provider_or_endpoint_usage_claimed"])
        self.assertEqual(transition_annotation_state("unassigned","independently_annotated"),"independently_annotated")
        with self.assertRaises(AnnotationError):transition_annotation_state("unassigned","locked")
        with self.assertRaises(AnnotationError):create_terra_unresolved_proposal(self.packet,self.text,POLICY)

    def test_blank_packet_exact_coverage_and_no_semantic_or_text_leak(self):
        total=0
        for workload in self.workloads:
            row=next(x for x in self.manifest["cases"] if x["case_id"]==workload["case_id"]);packet=load_json(self.root/row["packet_ref"]);text=open_source(self.manifest["source_store"],packet["case_id"],packet["source_hash"]);checks=validate_packet(packet,workload,text,POLICY);total+=checks["task_count"]
            serialized=json.dumps(packet).lower();self.assertNotIn("authority_units",serialized);self.assertNotIn("gold_noticed",serialized);self.assertNotIn("source_text",serialized)
        self.assertEqual(total,369)
        with self.assertRaises(AnnotationError):validate_packet(self.packet,self.workload,self.text+"x",POLICY)
        partial=copy.deepcopy(self.packet);partial["tasks"].pop()
        with self.assertRaises(AnnotationError):validate_packet(partial,self.workload,self.text,POLICY)

    def test_exact_span_source_hash_quote_offset_and_wrong_owner_fail(self):
        good=self.submission();validate_submission(good,self.packet,self.text,POLICY)
        mutations=[]
        for field,value in (("quote","tamper"),("source_hash","0"*64),("start_char",good["target_reviews"][0]["authority_units"][0]["evidence_spans"][0]["start_char"]+1)):
            bad=copy.deepcopy(good);bad["target_reviews"][0]["authority_units"][0]["evidence_spans"][0][field]=value;mutations.append(bad)
        bad=copy.deepcopy(good);bad["target_reviews"][0]["authority_units"][0]["owner_target_id"]=self.packet["tasks"][1]["target_id"];mutations.append(bad)
        for bad in mutations:
            with self.assertRaises(AnnotationError):validate_submission(bad,self.packet,self.text,POLICY)

    def test_model_or_kos_provenance_cannot_masquerade_as_human_gold(self):
        for source in ("model","kos","codex","old_pipeline"):
            bad=self.submission();bad["target_reviews"][0]["authority_units"][0]["provenance"]["source_type"]=source
            with self.subTest(source=source),self.assertRaises(AnnotationError):validate_submission(bad,self.packet,self.text,POLICY)
        a,b=self.submission("a"),self.submission("b");d=compare_submissions(a,b,self.packet,self.text,POLICY);adj=create_adjudication_template(self.packet,a,b,d,"judge","Human judge");adj["source_review_confirmed"]=True;adj["status"]="adjudicated";adj["decisions"]=copy.deepcopy(a["target_reviews"]);adj["decisions"][0]["authority_units"][0]["provenance"]["source_type"]="model"
        with self.assertRaises(AnnotationError):lock_gold([self.packet],[a,b],[adj],POLICY)

    def test_blind_two_annotator_and_adjudication_source_gates(self):
        a=self.submission("same");b=self.submission("same")
        with self.assertRaises(AnnotationError):compare_submissions(a,b,self.packet,self.text,POLICY)
        leaked=self.submission("b");leaked["blindness"]={"peer_submissions_visible":True,"visible_peer_submission_ids":[a["submission_id"]]}
        with self.assertRaises(AnnotationError):validate_submission(leaked,self.packet,self.text,POLICY)
        b=self.submission("b");d=compare_submissions(a,b,self.packet,self.text,POLICY);adj=create_adjudication_template(self.packet,a,b,d,"judge","Human judge")
        with self.assertRaises(AnnotationError):validate_adjudication(adj,self.packet,a,b,d,self.text,POLICY)
        single=copy.deepcopy(adj);single["submission_ids"]=[a["submission_id"]];single["source_review_confirmed"]=True;single["status"]="adjudicated";single["decisions"]=copy.deepcopy(a["target_reviews"])
        with self.assertRaises(AnnotationError):lock_gold([self.packet],[a],[single],POLICY,{self.packet["case_id"]:self.text})
        single["override"]={"reason":"Documented emergency second-annotator exception","authorized_by":"judge","single_annotator_exception":True}
        for review in single["decisions"]:
            if review["hard_negative"] is not None:review["hard_negative"]["provenance"]["annotator_id"]="judge"
            for au in review["authority_units"]:au["provenance"]["annotator_id"]="judge"
        validate_locked_gold(lock_gold([self.packet],[a],[single],POLICY,{self.packet["case_id"]:self.text}))

    def test_duplicate_overlap_negative_partial_and_cross_block_contracts(self):
        good=self.submission();au=good["target_reviews"][0]["authority_units"][0]
        duplicate=copy.deepcopy(good);other=copy.deepcopy(au);other["au_id"]="au-duplicate";duplicate["target_reviews"][0]["authority_units"].append(other)
        with self.assertRaises(AnnotationError):validate_submission(duplicate,self.packet,self.text,POLICY)
        overlap=copy.deepcopy(good);other=copy.deepcopy(au);other["au_id"]="au-overlap";other["evidence_spans"][0]["start_char"]+=1;other["evidence_spans"][0]["quote"]=self.text[other["evidence_spans"][0]["start_char"]:other["evidence_spans"][0]["end_char"]];import hashlib;other["evidence_spans"][0]["text_sha256"]=hashlib.sha256(other["evidence_spans"][0]["quote"].encode()).hexdigest();overlap["target_reviews"][0]["authority_units"].append(other)
        with self.assertRaises(AnnotationError):validate_submission(overlap,self.packet,self.text,POLICY)
        negative=self.submission(positive=False);negative["target_reviews"][0]["review_complete"]=False
        with self.assertRaises(AnnotationError):validate_submission(negative,self.packet,self.text,POLICY)
        cross=copy.deepcopy(good);task=self.packet["tasks"][1];s=task["target_span"];cross["target_reviews"][0]["authority_units"][0]["cross_block_refs"]=[exact_span(self.text,self.packet["case_id"],self.packet["source_hash"],s["start_char"],min(s["start_char"]+10,s["end_char"]))];validate_submission(cross,self.packet,self.text,POLICY)
        partial=copy.deepcopy(good);partial["target_reviews"].pop()
        with self.assertRaises(AnnotationError):validate_submission(partial,self.packet,self.text,POLICY)

    def test_disagreement_dimensions_and_human_lock_digest(self):
        a,b=self.submission("a"),self.submission("b",positive=False);d=compare_submissions(a,b,self.packet,self.text,POLICY);self.assertIn("negative_vs_positive",d["items"][0]["dimensions"])
        adj=create_adjudication_template(self.packet,a,b,d,"judge","Human judge");adj["source_review_confirmed"]=True;adj["status"]="adjudicated";adj["decisions"]=copy.deepcopy(a["target_reviews"]);validate_adjudication(adj,self.packet,a,b,d,self.text,POLICY);gold=lock_gold([self.packet],[a,b],[adj],POLICY,{self.packet["case_id"]:self.text});validate_locked_gold(gold);bad=copy.deepcopy(gold);bad["authority_units"][0]["claim_text"]="tampered"
        with self.assertRaises(AnnotationError):validate_locked_gold(bad)

    def test_fewshot_heldout_and_empty_blocked(self):
        blocked=select_few_shot(None);self.assertEqual(blocked["status"],"blocked_no_locked_gold");self.assertEqual(blocked["records"],[])
        silver_blocked=select_silver_few_shot(None);self.assertEqual(silver_blocked["evaluation_against"],"model_silver");self.assertEqual(silver_blocked["heldout_case_ids"],[])
        fake={"artifact_type":"LockedAUGoldSnapshot","schema_version":"locked-au-gold-v1","snapshot_id":"x","status":"locked","split":"heldout"}
        with self.assertRaises(AnnotationError):select_few_shot(fake)
        lock=load_json(self.root/"heldout_source_lock.json");self.assertEqual((len(lock["development"]),len(lock["heldout"])),(20,40));self.assertFalse(lock["checks"]["all_sources_contract_ingested"]);self.assertFalse(lock["checks"]["heldout_labels_materialized"])
        validate_heldout_lock(lock,P/"manifests/split_registry.v1.json",P.parents[1]);bad=copy.deepcopy(lock);bad["heldout"][0]["source_sha256_raw"]="0"*64
        with self.assertRaises(ValueError):validate_heldout_lock(bad,P/"manifests/split_registry.v1.json",P.parents[1])

    @patch('knowledge_base.pipeline_v1.au_gold.remediation.registry', return_value={'artifact_type':'Plan09SemanticDefectRegistry','findings':[]})
    def test_model_silver_is_explicit_and_never_human_gold(self, fixture_registry):
        human=self.submission("terra-adapter");reviews=copy.deepcopy(human["target_reviews"])
        for review in reviews:
            if review["hard_negative"] is not None:review["hard_negative"]["provenance"]={"source_type":"model","producer_id":"model:gpt-5.6-terra","prompt_version":POLICY["terra_prompt_version"]};review["model_outcome"]="hard_negative";review["unresolved_reasons"]=[]
            for au in review["authority_units"]:au["status"]="model_proposed";au["provenance"]={"source_type":"model","producer_id":"model:gpt-5.6-terra","prompt_version":POLICY["terra_prompt_version"]};au["uncertainty"]="low";au["unresolved_reasons"]=[];review["model_outcome"]="positive";review["unresolved_reasons"]=[]
        for task,review in zip(self.packet["tasks"],reviews):review["review_trace"]=model_review_trace(task,self.text,self.packet["source_hash"],review)
        proposal={"artifact_type":"TerraAUProposal","schema_version":"terra-au-proposal-v1","proposal_id":"proposal-1","packet_id":self.packet["packet_id"],"case_id":self.packet["case_id"],"source_hash":self.packet["source_hash"],"producer":{"source_type":"model","producer_id":"model:gpt-5.6-terra","model":"gpt-5.6-terra","reasoning_effort":"low"},"prompt_version":POLICY["terra_prompt_version"],"batch_id":"synthetic-test","status":"model_proposed","target_reviews":reviews};validate_model_proposal(proposal,self.packet,self.text,POLICY);silver=lock_silver([self.packet],[proposal],POLICY,{self.packet["case_id"]:self.text});validate_locked_silver(silver);self.assertEqual(silver["evaluation_against"],"model_silver")
        bad=copy.deepcopy(silver);bad["authority_units"][0]["claim_text"]="tampered"
        with self.assertRaises(AnnotationError):validate_locked_silver(bad)
        silver_fewshot=select_silver_few_shot(silver);self.assertEqual(silver_fewshot["evaluation_against"],"model_silver");self.assertEqual(silver_fewshot["heldout_case_ids"],[])
        for mutation in ("human","missing"):
            altered=copy.deepcopy(proposal)
            if mutation=="human":altered["producer"]["source_type"]="human"
            else:altered.pop("producer")
            with self.subTest(mutation=mutation),self.assertRaises(AnnotationError):validate_model_proposal(altered,self.packet,self.text,POLICY)
        traced=copy.deepcopy(proposal);traced["target_reviews"][0]["review_trace"]["decision_checksum"]="0"*64
        with self.assertRaises(AnnotationError):validate_model_proposal(traced,self.packet,self.text,POLICY)
        with self.assertRaises(AnnotationError):lock_gold([self.packet],[proposal,proposal],[proposal],POLICY,{self.packet["case_id"]:self.text})

    def test_model_checkpoint_requires_one_matching_batch_and_never_overwrites(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp); root=temp/"outputs"/"plan09_au_gold_v1"; root.mkdir(parents=True)
            # Copy the minimal immutable build artifacts; checkpoint writes only beneath this temp root.
            import shutil
            for name in ("au_annotation_build_manifest.json","terra_proposal_manifest.json","terra_annotation_batches.json"):
                shutil.copy2(self.root/name,root/name)
            # The checked-in output may contain prior checkpoints.  This fixture
            # exercises an isolated first checkpoint, so retain the batch list
            # but remove proposal ownership from its copied manifest.
            isolated=load_json(root/"terra_proposal_manifest.json")
            isolated.update({"status":"not_run_no_review_trace","proposal_count":0,"reviewed_target_count":0,"target_count":0,"authority_unit_count":0,"hard_negative_count":0,"unresolved_target_count":0,"proposals":[]})
            atomic_write(root/"terra_proposal_manifest.json",isolated)
            row=next(x for x in self.manifest["cases"] if x["case_id"]==self.packet["case_id"]);(root/row["packet_ref"]).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(self.root/row["packet_ref"],root/row["packet_ref"])
            batch=next(x for x in load_json(root/"terra_annotation_batches.json")["batches"] if x["case_id"]==self.packet["case_id"])
            task=next(x for x in self.packet["tasks"] if x["target_id"]==batch["target_ids"][0]); span=task["target_span"]; reviewed=exact_span(self.text,self.packet["case_id"],self.packet["source_hash"],span["start_char"],span["end_char"])
            review={"target_id":task["target_id"],"review_complete":True,"reviewed_span":reviewed,"authority_units":[],"hard_negative":None,"notes":[],"model_outcome":"unresolved","unresolved_reasons":["requires a separately recorded human legal interpretation"]};review["review_trace"]=model_review_trace(task,self.text,self.packet["source_hash"],review)
            proposal={"artifact_type":"TerraAUProposal","schema_version":"terra-au-proposal-v1","proposal_id":"checkpoint-fixture","packet_id":self.packet["packet_id"],"case_id":self.packet["case_id"],"source_hash":self.packet["source_hash"],"producer":{"source_type":"model","producer_id":"model:gpt-5.6-terra","model":"gpt-5.6-terra","reasoning_effort":"low"},"prompt_version":POLICY["terra_prompt_version"],"batch_id":batch["batch_id"],"status":"model_proposed","target_reviews":[review]}
            result=checkpoint_model_proposal(proposal=proposal,output_root=root,source_store=self.manifest["source_store"],policy=POLICY);self.assertEqual(result["reviewed_target_count"],1)
            with self.assertRaises(AnnotationError):checkpoint_model_proposal(proposal=proposal,output_root=root,source_store=self.manifest["source_store"],policy=POLICY)

    def test_terra_batch_builder_assigns_overlapping_target_once(self):
        task=self.packet["tasks"][0];target_id=task["target_id"]
        base={"arm":"P2a","target_ids":[target_id]}
        workload={"case_id":self.packet["case_id"],"source_hash":self.packet["source_hash"],"regions":[
            {**base,"region_id":"region-b","fingerprint":"b"*64},
            {**base,"region_id":"region-a","fingerprint":"a"*64},
        ]}
        result=_terra_batches([workload],[self.packet],POLICY)
        self.assertEqual(sum(target_id in b["target_ids"] for b in result["batches"]),1)
        self.assertEqual(result["batches"][0]["region_id"],"region-a")
        self.assertEqual(result["excluded_duplicate_assignments"],[{"case_id":self.packet["case_id"],"target_id":target_id,"owner_region_id":"region-a","excluded_region_id":"region-b"}])

    def test_scoring_exact_overlap_and_severe_fields(self):
        au=self.submission()["target_reviews"][0]["authority_units"][0];gold={**copy.deepcopy(au),"case_id":self.packet["case_id"]};exact=copy.deepcopy(gold);exact["au_id"]="pred-exact";score=score_predictions([gold],[exact]);self.assertEqual(score["micro"]["exact"]["f1"],1.0);self.assertEqual(score["severe_error_count"],0)
        partial=copy.deepcopy(exact);partial["au_id"]="pred-partial";partial["evidence_spans"][0]["end_char"]-=1;partial["attributions"]=[];score=score_predictions([gold],[partial]);self.assertEqual(score["micro"]["exact"]["tp"],0);self.assertEqual(score["micro"]["overlap"]["tp"],1);self.assertEqual(score["severe_error_count"],1)

if __name__=="__main__":unittest.main()
