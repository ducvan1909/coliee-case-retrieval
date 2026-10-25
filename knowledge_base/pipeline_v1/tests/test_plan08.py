from __future__ import annotations
import copy,hashlib,json,shutil,tempfile,unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from knowledge_base.pipeline_v1.execution_ledger import ExecutionError,build_requests,execute_scenario,invalidation_scope,request_fingerprint,validate_snapshot,write_attempt_projection
from knowledge_base.pipeline_v1.execution_ledger.build import load_plan07_workloads,validate_build_history,validate_current_pointer

P=Path(__file__).resolve().parents[1]
POLICY=json.loads((P/"policies/execution_policy.v1.json").read_text(encoding="utf-8"))

class Plan08Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workloads,_,_=load_plan07_workloads(P/"reports/plan07_analysis_region_validation.latest.json")

    def test_schema_and_checked_in_gate(self):
        Draft202012Validator.check_schema(json.loads((P/"contracts/execution_ledger.v1.json").read_text(encoding="utf-8")))
        Draft202012Validator.check_schema(json.loads((P/"contracts/mock_cache_entry.v1.json").read_text(encoding="utf-8")))
        Draft202012Validator.check_schema(json.loads((P/"contracts/execution_archive_record.v2.json").read_text(encoding="utf-8")))
        Draft202012Validator.check_schema(json.loads((P/"contracts/execution_history_index.v2.json").read_text(encoding="utf-8")))
        report=json.loads((P/"reports/plan08_execution_validation.latest.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"],"pass");self.assertTrue(all(report["gates"].values()));self.assertEqual(report["summary"]["primary_target_count"],369)
        checks=validate_current_pointer(Path(report["outputs"]["output_root"]));self.assertTrue(checks["history_valid"]);self.assertGreaterEqual(checks["history_count"],1)

    def test_current_pointer_and_history_tampering_fail_closed(self):
        report=json.loads((P/"reports/plan08_execution_validation.latest.json").read_text(encoding="utf-8"));source=Path(report["outputs"]["output_root"])
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"history").mkdir();pointer=json.loads((source/"current.json").read_text());manifest=json.loads((source/"execution_suite_manifest.json").read_text());(root/"execution_suite_manifest.json").write_text(json.dumps(manifest),encoding="utf-8");pointer["build_manifest_sha256"]="0"*64;(root/"current.json").write_text(json.dumps(pointer),encoding="utf-8")
            with self.assertRaises(ValueError):validate_current_pointer(root)
        history=json.loads((source/"history/index.json").read_text());bad=copy.deepcopy(history);bad["builds"][0]["build_id"]="0"*64
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"history").mkdir();(root/"history/index.json").write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ValueError):validate_build_history(root)

    def test_archive_payload_inventory_mutations_fail_closed(self):
        report=json.loads((P/"reports/plan08_execution_validation.latest.json").read_text(encoding="utf-8"));source=Path(report["outputs"]["output_root"]);source_index=json.loads((source/"history/index.json").read_text());build=source_index["builds"][0];bid=build["build_id"]
        def fixture():
            temp=tempfile.TemporaryDirectory();root=Path(temp.name);shutil.copytree(source/"history",root/"history");return temp,root
        for mutation in ("snapshot_byte","snapshot_missing","log_byte","log_missing","unexpected_payload","duplicate_inventory","record_path_escape","record_ref_current"):
            temp,root=fixture()
            try:
                archive=root/"history"/bid;record_path=archive/"archive_record.json";record=json.loads(record_path.read_text());index_path=root/"history/index.json";index=json.loads(index_path.read_text())
                if mutation.startswith("snapshot"):
                    target=next(archive/x["path"] for x in record["payload_inventory"] if x["artifact_type"]=="execution_run_snapshot")
                    if mutation.endswith("missing"):target.unlink()
                    else:target.write_bytes(target.read_bytes()+b" ")
                elif mutation.startswith("log"):
                    target=next(archive/x["path"] for x in record["payload_inventory"] if x["artifact_type"]=="attempt_log_projection")
                    if mutation.endswith("missing"):target.unlink()
                    else:target.write_bytes(target.read_bytes()[:-1])
                elif mutation=="unexpected_payload":(archive/"unexpected.json").write_text("{}",encoding="utf-8")
                else:
                    if mutation=="duplicate_inventory":record["payload_inventory"].append(copy.deepcopy(record["payload_inventory"][0]))
                    elif mutation=="record_path_escape":record["payload_inventory"][0]["path"]="../escape.json"
                    else:record["manifest_ref"]="../../execution_suite_manifest.json"
                    record_path.write_text(json.dumps(record),encoding="utf-8");index["builds"][0]["archive_record_sha256"]=hashlib.sha256(record_path.read_bytes()).hexdigest();index_path.write_text(json.dumps(index),encoding="utf-8")
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_build_history(root)
            finally:temp.cleanup()

    def test_exact_resume_zero_calls_and_snapshot_projection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);snap=execute_scenario(workloads=self.workloads,policy=POLICY,cache_root=root/"cache",snapshot_path=root/"run.json")
            snap=execute_scenario(workloads=self.workloads,policy=POLICY,cache_root=root/"cache",snapshot_path=root/"run.json",resume=True);write_attempt_projection(snap,root/"attempts.jsonl")
            self.assertEqual(snap["invocations"][-1]["provider_calls"],0);self.assertEqual(snap["invocations"][-1]["skipped_verified_requests"],96);self.assertEqual(len(snap["coverage_entries"]),369)
            validate_snapshot(snap,self.workloads,POLICY,attempt_log_path=root/"attempts.jsonl",cache_root=root/"cache")

    def test_crash_after_attempt_resume_appends_unique_attempt(self):
        workloads=self.workloads[:1]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);first=execute_scenario(workloads=workloads,policy=POLICY,cache_root=root/"cache",snapshot_path=root/"run.json",crash_point="after_attempt_before_commit")
            self.assertEqual(first["run_status"],"interrupted");resumed=execute_scenario(workloads=workloads,policy=POLICY,cache_root=root/"cache",snapshot_path=root/"run.json",resume=True)
            ids=[a["attempt_id"] for a in resumed["attempts"]];self.assertEqual(len(ids),len(set(ids)));numbers=[a["attempt_number"] for a in resumed["attempts"] if a["request_id"]==resumed["attempts"][0]["request_id"]];self.assertEqual(numbers,[1,2]);self.assertEqual(resumed["run_status"],"protocol_complete")

    def test_protocol_faults_are_atomic_and_not_retried(self):
        for scenario in ("protocol_malformed","protocol_missing","protocol_duplicate","protocol_foreign","partial_batch"):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as d:
                root=Path(d);snap=execute_scenario(workloads=self.workloads[:1],policy=POLICY,cache_root=root/"cache",snapshot_path=root/"run.json",scenario=scenario,fault_request_ordinal=0)
                failed=snap["requests"][0];self.assertEqual(failed["status"],"error");self.assertEqual(len(failed["attempt_ids"]),1)
                for tid in failed["expected_target_ids"]:self.assertEqual(next(e for e in snap["coverage_entries"] if e["target_id"]==tid)["verified_work_item_ids"],[])

    def test_only_transient_is_retried_and_budget_never_completes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);retry=execute_scenario(workloads=self.workloads[:1],policy=POLICY,cache_root=root/"r-cache",snapshot_path=root/"r.json",scenario="transient_retry",fault_request_ordinal=0);self.assertEqual(retry["summary"]["retry_count"],1);self.assertEqual(retry["run_status"],"protocol_complete")
            permanent=execute_scenario(workloads=self.workloads[:1],policy=POLICY,cache_root=root/"p-cache",snapshot_path=root/"p.json",scenario="permanent_failure",fault_request_ordinal=0);self.assertEqual(len(permanent["requests"][0]["attempt_ids"]),1)
            budget=execute_scenario(workloads=self.workloads[:1],policy=POLICY,cache_root=root/"b-cache",snapshot_path=root/"b.json",scenario="budget_stop",budget_request_limit=1);self.assertEqual(budget["run_status"],"budget_exhausted");self.assertIn("budget_exhausted",budget["summary"]["status_counts"])

    def test_corruption_false_completion_projection_and_order_fail_closed(self):
        root=P/"outputs/plan08_execution_v1/scenarios/cold_success";snap=json.loads((root/"run_snapshot.json").read_text(encoding="utf-8"))
        mutations=[]
        bad=copy.deepcopy(snap);bad["coverage_entries"][0]["verified_work_item_ids"]=[];mutations.append(bad)
        bad=copy.deepcopy(snap);bad["attempts"][1]["attempt_order"]=0;mutations.append(bad)
        bad=copy.deepcopy(snap);bad["summary"]["provider_calls"]+=1;mutations.append(bad)
        for bad in mutations:
            with self.assertRaises(ExecutionError):validate_snapshot(bad,self.workloads,POLICY)
        with tempfile.TemporaryDirectory() as d:
            log=Path(d)/"attempts.jsonl";write_attempt_projection(snap,log);log.write_text(log.read_text(encoding="utf-8").splitlines()[0]+"\n",encoding="utf-8")
            with self.assertRaises(ExecutionError):validate_snapshot(snap,self.workloads,POLICY,attempt_log_path=log)

    def test_cache_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);snap=execute_scenario(workloads=self.workloads[:1],policy=POLICY,cache_root=root/"cache",snapshot_path=root/"run.json");cache=Path(snap["cache_refs"][0]);value=json.loads(cache.read_text());value["fingerprint"]="0"*64;cache.write_text(json.dumps(value),encoding="utf-8")
            with self.assertRaises(ExecutionError):execute_scenario(workloads=self.workloads[:1],policy=POLICY,cache_root=root/"cache",snapshot_path=root/"fresh.json")

    def test_dependency_locality_restore_and_arm_isolation(self):
        settings={"mode":"probe"};base=build_requests(self.workloads,POLICY,settings);mutated=copy.deepcopy(self.workloads);case=mutated[0]["case_id"];mutated[0]["source_hash"]="0"*64
        for region in mutated[0]["regions"]:region["source_hash"]="0"*64
        scope=invalidation_scope(base,build_requests(mutated,POLICY,settings));self.assertTrue(scope["invalidated"]);self.assertTrue(all(x[0]==case for x in scope["invalidated"]));self.assertEqual(invalidation_scope(base,build_requests(self.workloads,POLICY,settings))["invalidated_count"],0)
        p2b=copy.deepcopy(POLICY);p2b["region_arm"]="P2b";left=next(r for r in self.workloads[0]["regions"] if r["arm"]=="P2a");right=next(r for r in self.workloads[0]["regions"] if r["arm"]=="P2b" and r["batch_id"]==left["batch_id"])
        self.assertNotEqual(request_fingerprint(left,self.workloads[0],POLICY,settings),request_fingerprint(right,self.workloads[0],p2b,settings))

if __name__=="__main__":unittest.main()
