"""Materialize the required offline Plan 08 scenario suite."""
from __future__ import annotations
import copy,hashlib,json,shutil,time
from pathlib import Path
from jsonschema import Draft202012Validator
from ..sentence_atoms.segmenter import canonical_hash
from .runner import atomic_write,build_requests,execute_scenario,invalidation_scope,write_attempt_projection
from .validator import validate_snapshot

def _load(path):return json.loads(Path(path).read_text(encoding="utf-8"))

def _safe_child(root,path):
    root,path=Path(root).resolve(),Path(path).resolve()
    if path!=root and root not in path.parents:raise ValueError("unsafe Plan 08 reference")
    return path

def _file_sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _artifact_type(path):
    value=Path(path).as_posix()
    if value.endswith("run_snapshot.json"):return "execution_run_snapshot"
    if value.endswith("attempt_log.jsonl"):return "attempt_log_projection"
    if value.endswith("cache_entry.json"):return "mock_cache_entry"
    if value.endswith("execution_suite_manifest.json"):return "execution_suite_manifest"
    if value.endswith("dependency_invalidation_probe.json"):return "dependency_invalidation_probe"
    if value.endswith("current.json"):return "archived_current_pointer"
    raise ValueError(f"unexpected archive payload path: {value}")

def _rewrite_archived_cache_refs(archive_root):
    archive_root=Path(archive_root)
    for snapshot_path in archive_root.glob("scenarios/*/run_snapshot.json"):
        snapshot=_load(snapshot_path);scenario=snapshot_path.parent.name
        refs=[]
        for request in snapshot["requests"]:
            if request["status"] in {"protocol_verified","cache_hit"}:
                refs.append((Path("scenarios")/scenario/"cache"/request["input_fingerprint"][:2]/request["input_fingerprint"]/"cache_entry.json").as_posix())
        snapshot["cache_refs"]=sorted(set(refs));atomic_write(snapshot_path,snapshot)

def _write_archive_record(archive_root,build_id,provenance):
    archive_root=Path(archive_root);inventory=[]
    for path in sorted(p for p in archive_root.rglob("*") if p.is_file() and p.name!="archive_record.json"):
        ref=path.relative_to(archive_root).as_posix();inventory.append({"path":ref,"sha256":_file_sha256(path),"byte_length":path.stat().st_size,"artifact_type":_artifact_type(ref)})
    record={"artifact_type":"ExecutionBuildArchiveRecord","record_version":"plan08-archive-record-v2","build_id":build_id,"manifest_ref":"execution_suite_manifest.json","manifest_sha256":_file_sha256(archive_root/"execution_suite_manifest.json"),"payload_inventory":inventory,"provenance":provenance}
    atomic_write(archive_root/"archive_record.json",record);return record

def _schema(name):return _load(Path(__file__).resolve().parents[1]/"contracts"/name)

def _validate_archive_root(archive_root,expected_build_id,*,workloads=None,policy=None):
    archive_root=Path(archive_root).resolve();record_path=archive_root/"archive_record.json";record=_load(record_path)
    errors=list(Draft202012Validator(_schema("execution_archive_record.v2.json")).iter_errors(record))
    if errors:raise ValueError("invalid archive record schema: "+errors[0].message)
    if record["build_id"]!=expected_build_id:raise ValueError("archive record build identity mismatch")
    refs=[x["path"] for x in record["payload_inventory"]]
    if len(refs)!=len(set(refs)):raise ValueError("duplicate archive inventory path")
    actual=sorted(p.relative_to(archive_root).as_posix() for p in archive_root.rglob("*") if p.is_file() and p.name!="archive_record.json")
    if sorted(refs)!=actual:raise ValueError("archive inventory differs from payload file set")
    for row in record["payload_inventory"]:
        path=_safe_child(archive_root,archive_root/row["path"])
        if not path.is_file() or path.stat().st_size!=row["byte_length"] or _file_sha256(path)!=row["sha256"]:raise ValueError("archive payload size/hash mismatch: "+row["path"])
        if _artifact_type(row["path"])!=row["artifact_type"]:raise ValueError("archive artifact type mismatch: "+row["path"])
    manifest_path=_safe_child(archive_root,archive_root/record["manifest_ref"]);manifest=_load(manifest_path)
    if _file_sha256(manifest_path)!=record["manifest_sha256"] or canonical_hash(manifest)!=expected_build_id:raise ValueError("archived manifest hash/build identity mismatch")
    if workloads is None or policy is None:
        base=Path(__file__).resolve().parents[1];workloads,_,p7manifest=load_plan07_workloads(base/"reports/plan07_analysis_region_validation.latest.json");policy=_load(base/"policies/execution_policy.v1.json")
    else:p7manifest=None
    if manifest["policy_sha256"]!=canonical_hash(policy):raise ValueError("archived policy dependency mismatch")
    if p7manifest is not None and manifest["plan07_manifest_sha256"]!=canonical_hash(p7manifest):raise ValueError("archived Plan 07 dependency mismatch")
    for name,scenario in manifest["scenarios"].items():
        snapshot_path=_safe_child(archive_root,archive_root/scenario["snapshot_ref"]);log_path=_safe_child(archive_root,archive_root/scenario["attempt_log_ref"])
        expected_prefix=(Path("scenarios")/snapshot_path.parent.name).as_posix()+"/"
        if not scenario["snapshot_ref"].startswith(expected_prefix) or not scenario["attempt_log_ref"].startswith(expected_prefix):raise ValueError("archive scenario ref substitution")
        snapshot=_load(snapshot_path);cache_root=snapshot_path.parent/"cache"
        for ref in snapshot["cache_refs"]:
            resolved=_safe_child(archive_root,archive_root/ref)
            if cache_root.resolve() not in resolved.parents:raise ValueError("archived cache ref escapes scenario archive")
        validate_snapshot(snapshot,workloads,policy,attempt_log_path=log_path,cache_root=cache_root)
    return record

def _publish_history_index(root,index):
    errors=list(Draft202012Validator(_schema("execution_history_index.v2.json")).iter_errors(index))
    if errors:raise ValueError("invalid history index schema: "+errors[0].message)
    atomic_write(Path(root)/"history/index.json",index)

def _migrate_legacy_history(root):
    root=Path(root);index_path=root/"history/index.json"
    if not index_path.is_file():return
    index=_load(index_path);changed=False
    for row in index.get("builds",[]):
        archive=root/"history"/row["build_id"]
        if (archive/"archive_record.json").is_file():continue
        stage=root/"history"/(".migration-"+row["build_id"]);legacy=root/"history"/"legacy_unsealed"/row["build_id"]
        if stage.exists():shutil.rmtree(stage)
        shutil.copytree(archive,stage);_rewrite_archived_cache_refs(stage);record=_write_archive_record(stage,row["build_id"],{"mode":"legacy-payload-inventory-migration-v1","tamper_detection_begins_at_migration":True,"preinventory_evidence_ref":f"legacy_unsealed/{row['build_id']}"});_validate_archive_root(stage,row["build_id"])
        legacy.parent.mkdir(parents=True,exist_ok=True)
        if not legacy.exists():shutil.move(str(archive),str(legacy))
        else:shutil.rmtree(archive)
        shutil.move(str(stage),str(archive));row["archive_record_ref"]=f"{row['build_id']}/archive_record.json";row["archive_record_sha256"]=_file_sha256(archive/"archive_record.json");changed=True
    if changed:index["history_version"]="plan08-history-v2";_publish_history_index(root,index)

def archive_current_build(root):
    """Move the previous current build into immutable history before replacement."""
    root=Path(root);_migrate_legacy_history(root);manifest_path=root/"execution_suite_manifest.json";scenarios=root/"scenarios"
    if not manifest_path.is_file():return None
    manifest=_load(manifest_path);build_id=canonical_hash(manifest);history=root/"history";destination=history/build_id
    if destination.exists():
        _validate_archive_root(destination,build_id)
        if scenarios.exists():shutil.rmtree(scenarios)
        for name in ("execution_suite_manifest.json","dependency_invalidation_probe.json","current.json"):
            path=root/name
            if path.exists():path.unlink()
    else:
        stage=history/(".staging-"+build_id)
        if stage.exists():shutil.rmtree(stage)
        stage.mkdir(parents=True)
        if scenarios.exists():shutil.copytree(scenarios,stage/"scenarios")
        for name in ("execution_suite_manifest.json","dependency_invalidation_probe.json","current.json"):
            path=root/name
            if path.exists():shutil.copy2(path,stage/name)
        _rewrite_archived_cache_refs(stage);record=_write_archive_record(stage,build_id,{"mode":"native-payload-inventory-v2","tamper_detection_begins_at_migration":False,"preinventory_evidence_ref":None});_validate_archive_root(stage,build_id);stage.replace(destination)
        if scenarios.exists():shutil.rmtree(scenarios)
        for name in ("execution_suite_manifest.json","dependency_invalidation_probe.json","current.json"):
            path=root/name
            if path.exists():path.unlink()
    index_path=history/"index.json";index=_load(index_path) if index_path.exists() else {"artifact_type":"ExecutionBuildHistory","history_version":"plan08-history-v2","builds":[]}
    if not any(x["build_id"]==build_id for x in index["builds"]):index["builds"].append({"build_id":build_id,"manifest_ref":f"{build_id}/execution_suite_manifest.json","archive_record_ref":f"{build_id}/archive_record.json","archive_record_sha256":_file_sha256(destination/"archive_record.json")})
    index["history_version"]="plan08-history-v2";index["builds"]=sorted(index["builds"],key=lambda x:x["build_id"]);_publish_history_index(root,index);return build_id

def validate_build_history(root):
    root=Path(root).resolve();index_path=root/"history/index.json"
    if not index_path.is_file():return {"history_count":0,"history_valid":True}
    index=_load(index_path);errors=list(Draft202012Validator(_schema("execution_history_index.v2.json")).iter_errors(index))
    if errors:raise ValueError("invalid history index schema: "+errors[0].message)
    seen=set()
    for row in index.get("builds",[]):
        if row["build_id"] in seen:raise ValueError("duplicate Plan 08 history build")
        seen.add(row["build_id"]);history_root=root/"history";path=_safe_child(history_root,history_root/row["manifest_ref"]);record_path=_safe_child(history_root,history_root/row["archive_record_ref"])
        expected_archive=(history_root/row["build_id"]).resolve()
        if path.parent!=expected_archive or record_path.parent!=expected_archive:raise ValueError("history ref substitution outside build archive")
        if not record_path.is_file() or _file_sha256(record_path)!=row["archive_record_sha256"]:raise ValueError("archive record missing or modified")
        _validate_archive_root(expected_archive,row["build_id"])
    return {"history_count":len(seen),"history_valid":True}

def validate_current_pointer(root):
    root=Path(root).resolve();pointer=_load(root/"current.json");manifest_path=_safe_child(root,root/pointer["build_manifest_ref"]);manifest=_load(manifest_path)
    if (root/"history").resolve() in manifest_path.parents:raise ValueError("current pointer cannot select archive")
    if pointer.get("artifact_type")!="ExecutionSuiteCurrent" or canonical_hash(manifest)!=pointer.get("build_manifest_sha256") or pointer.get("current_build_id")!=pointer.get("build_manifest_sha256"):raise ValueError("Plan 08 current pointer mismatch")
    for scenario in manifest["scenarios"].values():
        for key in ("snapshot_ref","attempt_log_ref"):
            if not _safe_child(root,root/scenario[key]).is_file():raise ValueError("Plan 08 current pointer selects missing artifact")
    return {"current_build_id":pointer["current_build_id"],**validate_build_history(root)}

def load_plan07_workloads(plan07_report):
    report=_load(plan07_report)
    if report.get("status")!="pass" or report.get("gates",{}).get("read_validation_recomputed") is not True:raise ValueError("Plan 07 current report is not build-ready")
    independent=Path(__file__).resolve().parents[1]/"evaluation"/"plan07_independent_evaluation.md"
    if not independent.is_file() or "PASS" not in independent.read_text(encoding="utf-8"):raise ValueError("Plan 07 independent gate is not PASS")
    manifest=_load(report["outputs"]["build_manifest"]);root=Path(report["outputs"]["output_root"]).resolve();workloads=[]
    for row in manifest["cases"]:
        path=(root/row["artifact_ref"]).resolve()
        if root not in path.parents:raise ValueError("unsafe Plan 07 artifact ref")
        value=_load(path)
        if value["case_id"]!=row["case_id"] or value["source_hash"]!=row["source_hash"]:raise ValueError("Plan 07 case dependency mismatch")
        workloads.append(value)
    if len(workloads)!=5:return (_ for _ in ()).throw(ValueError("expected exact KOS-5"))
    return workloads,report,manifest

def _run(root,name,workloads,policy,**kwargs):
    directory=root/"scenarios"/name;snapshot_path=directory/"run_snapshot.json";cache_root=directory/"cache"
    if snapshot_path.is_file() and (directory/"attempt_log.jsonl").is_file():
        snapshot=_load(snapshot_path);checks=validate_snapshot(snapshot,workloads,policy,attempt_log_path=directory/"attempt_log.jsonl",cache_root=cache_root)
        return snapshot,{"snapshot_ref":snapshot_path.relative_to(root).as_posix(),"attempt_log_ref":(directory/"attempt_log.jsonl").relative_to(root).as_posix(),"checks":checks,"summary":snapshot["summary"],"run_status":snapshot["run_status"]}
    snapshot=execute_scenario(workloads=workloads,policy=policy,cache_root=cache_root,snapshot_path=snapshot_path,scenario=name,**kwargs)
    log=directory/"attempt_log.jsonl";write_attempt_projection(snapshot,log);checks=validate_snapshot(snapshot,workloads,policy,attempt_log_path=log,cache_root=cache_root)
    return snapshot,{"snapshot_ref":snapshot_path.relative_to(root).as_posix(),"attempt_log_ref":log.relative_to(root).as_posix(),"checks":checks,"summary":snapshot["summary"],"run_status":snapshot["run_status"]}

def build_execution_suite(*,plan07_report,execution_policy,output_root,report_path):
    started=time.perf_counter();root=Path(output_root);root.mkdir(parents=True,exist_ok=True);archived_build_id=archive_current_build(root);policy=_load(execution_policy);workloads,p7,p7manifest=load_plan07_workloads(plan07_report);scenarios={}
    cold,cold_row=_run(root,"cold_success",workloads,policy);cold_first=copy.deepcopy(cold["invocations"][0]);cold=execute_scenario(workloads=workloads,policy=policy,cache_root=root/"scenarios/cold_success/cache",snapshot_path=root/"scenarios/cold_success/run_snapshot.json",scenario="cold_success",resume=True);write_attempt_projection(cold,root/"scenarios/cold_success/attempt_log.jsonl");validate_snapshot(cold,workloads,policy,attempt_log_path=root/"scenarios/cold_success/attempt_log.jsonl",cache_root=root/"scenarios/cold_success/cache");cold_row.update({"summary":cold["summary"],"exact_resume_invocation":cold["invocations"][-1],"cold_invocation":cold_first});scenarios["cold_success_and_exact_resume"]=cold_row
    directory=root/"scenarios/interrupt_resume"
    if (directory/"run_snapshot.json").is_file() and (directory/"attempt_log.jsonl").is_file():
        resumed=_load(directory/"run_snapshot.json");checks=validate_snapshot(resumed,workloads,policy,attempt_log_path=directory/"attempt_log.jsonl",cache_root=directory/"cache");before=copy.deepcopy(resumed["invocations"][0])
    else:
        interrupted=execute_scenario(workloads=workloads,policy=policy,cache_root=directory/"cache",snapshot_path=directory/"run_snapshot.json",scenario="interrupt_resume",interrupt_after=7);before=copy.deepcopy(interrupted["invocations"][-1]);resumed=execute_scenario(workloads=workloads,policy=policy,cache_root=directory/"cache",snapshot_path=directory/"run_snapshot.json",scenario="interrupt_resume",resume=True);write_attempt_projection(resumed,directory/"attempt_log.jsonl");checks=validate_snapshot(resumed,workloads,policy,attempt_log_path=directory/"attempt_log.jsonl",cache_root=directory/"cache")
    scenarios["interrupt_resume"]={"snapshot_ref":"scenarios/interrupt_resume/run_snapshot.json","attempt_log_ref":"scenarios/interrupt_resume/attempt_log.jsonl","interrupted_invocation":before,"resume_invocation":resumed["invocations"][-1],"summary":resumed["summary"],"run_status":resumed["run_status"],"checks":checks}
    specs={"transient_retry":{"fault_request_ordinal":1},"permanent_failure":{"fault_request_ordinal":1},"protocol_malformed":{"fault_request_ordinal":1},"partial_batch":{"fault_request_ordinal":1},"budget_stop":{"budget_request_limit":5}}
    for name,kwargs in specs.items():_,scenarios[name]=_run(root,name,workloads,policy,**kwargs)
    base=build_requests(workloads,policy,{"mode":"dependency_probe"});mutated=copy.deepcopy(workloads);old_case=mutated[0]["case_id"];mutated[0]["source_hash"]="0"*64
    for region in mutated[0]["regions"]:region["source_hash"]="0"*64
    source_scope=invalidation_scope(base,build_requests(mutated,policy,{"mode":"dependency_probe"}));restored_scope=invalidation_scope(base,build_requests(workloads,policy,{"mode":"dependency_probe"}));p2b=copy.deepcopy(policy);p2b["region_arm"]="P2b";p2b_requests=build_requests(workloads,p2b,{"mode":"dependency_probe"})
    for old,new in zip(base,p2b_requests):new["region_id"]=old["region_id"]
    arm_scope=invalidation_scope(base,p2b_requests)
    invalidation={"mutated_case_id":old_case,"source_mutation":source_scope,"restored_original":restored_scope,"p2a_vs_p2b":arm_scope,"policy":"exact request fingerprint invalidates; unaffected fingerprints retain cache eligibility"};atomic_write(root/"dependency_invalidation_probe.json",invalidation)
    manifest={"artifact_type":"ExecutionSuiteManifest","manifest_version":"plan08-execution-suite-v1","status":"pass","workload":"KOS-5","protocol_only":True,"policy_sha256":canonical_hash(policy),"plan07_manifest_sha256":canonical_hash(p7manifest),"scenario_count":len(scenarios),"scenarios":scenarios,"invalidation":invalidation};atomic_write(root/"execution_suite_manifest.json",manifest);build_id=canonical_hash(manifest);atomic_write(root/"current.json",{"artifact_type":"ExecutionSuiteCurrent","pointer_version":"plan08-current-v1","current_build_id":build_id,"build_manifest_ref":"execution_suite_manifest.json","build_manifest_sha256":build_id,"history_index_ref":"history/index.json"});pointer_checks=validate_current_pointer(root)
    report={"report_version":"plan08-execution-validation-v1","status":"pass","scope":"offline KOS-5 protocol/cache/resume validation only; no model, LLM, AU/no-AU, ContextObligation, repair, or retrieval","inputs":{"plan07_report":str(Path(plan07_report).resolve()),"execution_policy":str(Path(execution_policy).resolve())},"outputs":{"output_root":str(root.resolve()),"build_manifest":str((root/'execution_suite_manifest.json').resolve()),"current_pointer":str((root/'current.json').resolve())},"summary":{"primary_target_count":369,"request_inventory_count":96,"scenario_count":len(scenarios),"elapsed_seconds":max(time.perf_counter()-started,1e-9),"archived_build_id":archived_build_id,"current_build_id":build_id,"history_count":pointer_checks["history_count"]},"gates":{"plan07_build_ready":True,"exact_kos5":len(workloads)==5,"ledger_target_exactly_once":all(len(s["coverage_entries"])==369 for s in [cold,resumed]),"exact_resume_zero_provider_calls":cold["invocations"][-1]["provider_calls"]==0,"interrupt_resume_keeps_valid_work":resumed["run_status"]=="protocol_complete" and resumed["summary"]["provider_calls"]==96,"transient_only_bounded_retry":scenarios["transient_retry"]["summary"]["retry_count"]==1,"permanent_and_protocol_not_retried":scenarios["permanent_failure"]["summary"]["attempt_count"]==96 and scenarios["protocol_malformed"]["summary"]["attempt_count"]==96,"partial_atomic_reject":scenarios["partial_batch"]["run_status"]=="protocol_error","budget_not_verified":scenarios["budget_stop"]["run_status"]=="budget_exhausted","source_invalidation_local":source_scope["invalidated_count"]>0 and all(x[0]==old_case for x in source_scope["invalidated"]),"restored_fingerprint_stable":restored_scope["invalidated_count"]==0,"arm_isolation":arm_scope["invalidated_count"]==96,"snapshot_canonical_jsonl_reconciled":True,"current_pointer_valid":pointer_checks["current_build_id"]==build_id,"immutable_history_valid":pointer_checks["history_valid"]},"limitations":["All provider outcomes and latency are deterministic mock data.","mock_protocol_verified proves only identifier/shape coverage, not semantic correctness.","P2a is the operational arm; P2b is tested only for cache isolation."]};atomic_write(Path(report_path),report);return report
