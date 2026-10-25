"""Build blank KOS-5 human annotation packets and non-semantic readiness artifacts."""
from __future__ import annotations
import hashlib,html,json,time
from pathlib import Path
from ..execution_ledger.build import load_plan07_workloads
from ..sentence_atoms.segmenter import canonical_hash
from ..source_contract import open_source
from .core import AnnotationError,atomic_write,build_packet,load_json,new_submission,select_few_shot,select_silver_few_shot,validate_model_proposal,validate_packet

def _pilot_ids(registry,kind):
    rows=[]
    for corpus_split,bands in registry["pilot"].items():
        for band,groups in bands.items():
            for case_id in groups[kind]:rows.append((case_id,corpus_split,band))
    return sorted(rows)

def build_heldout_lock(registry_path,repo_root):
    registry=load_json(registry_path);repo_root=Path(repo_root);dev=_pilot_ids(registry,"development");held=_pilot_ids(registry,"holdout")
    if set(x[0] for x in dev)&set(x[0] for x in held):raise ValueError("development/held-out case overlap")
    def row(item,split):
        cid,corpus,band=item;path=repo_root/("data/task1_train_files_2026/cases" if corpus=="train" else "data/task1_test_files_2026")/(cid+".txt")
        if path.is_file():
            raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest();exists=True
        else:digest=None;exists=False
        return {"case_id":cid,"corpus_split":corpus,"length_band":band,"assignment":split,"source_path":path.relative_to(repo_root).as_posix(),"source_exists":exists,"source_sha256_raw":digest,"source_contract_ingested":False,"labels_materialized":False}
    development=[row(x,"development") for x in dev];holdout=[row(x,"heldout") for x in held]
    dev_hash={x["source_sha256_raw"] for x in development if x["source_sha256_raw"]};held_hash={x["source_sha256_raw"] for x in holdout if x["source_sha256_raw"]};duplicates=sorted(dev_hash&held_hash)
    if duplicates:raise ValueError("development/held-out duplicate source hash")
    value={"artifact_type":"HeldoutSourceLock","lock_version":"heldout-source-lock-v1","status":"dependency_missing_source_contract","reason":"pilot 60-case raw source has not been ingested through Plan 02 CaseSource contract","split_registry_sha256":canonical_hash(registry),"development":development,"heldout":holdout,"checks":{"case_id_disjoint":True,"source_hash_disjoint":True,"heldout_labels_materialized":False,"all_raw_sources_present":all(x["source_exists"] for x in development+holdout),"all_sources_contract_ingested":False}}
    value["lock_digest"]=canonical_hash(value);return value

def validate_heldout_lock(value,registry_path,repo_root):
    copy_value=dict(value);digest=copy_value.pop("lock_digest",None)
    if digest!=canonical_hash(copy_value):raise ValueError("held-out lock digest mismatch")
    expected=build_heldout_lock(registry_path,repo_root)
    if value!=expected:raise ValueError("held-out lock differs from current split/raw source dependencies")
    if value["checks"]["heldout_labels_materialized"] is not False:raise ValueError("held-out labels must not be materialized")
    return {"development_count":len(value["development"]),"heldout_count":len(value["heldout"]),"status":value["status"]}

def _render_review(packet,text,path):
    parts=["<!doctype html><meta charset='utf-8'><title>Plan 09 blank AU review</title>",f"<h1>Case {html.escape(packet['case_id'])}</h1>","<p><strong>Blank human-review view.</strong> Structural triggers are candidates only; no KOS/model/gold labels are present.</p>"]
    for task in packet["tasks"]:
        span=task["target_span"];quote=text[span["start_char"]:span["end_char"]];triggers=", ".join(x["trigger_id"] for x in task["structural_triggers"])
        parts.append(f"<section id='{task['target_id']}'><h2>{task['target_id']} / {task['owner_block_id']}</h2><p>span [{span['start_char']},{span['end_char']}); triggers: {html.escape(triggers or 'none')}</p><pre>{html.escape(quote)}</pre></section>")
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text("\n".join(parts),encoding="utf-8")

def _render_audit(report,path):
    body="<!doctype html><meta charset='utf-8'><title>Plan 09 readiness audit</title><h1>Plan 09 AU annotation readiness</h1><p>This audit contains readiness metadata only, not AU labels.</p><pre>"+html.escape(json.dumps(report,ensure_ascii=False,indent=2))+"</pre>";path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body,encoding="utf-8")

def _terra_batches(workloads,packets,policy):
    packet_by={p["case_id"]:p for p in packets};rows=[];excluded=[]
    for workload in workloads:
        task_by={t["target_id"]:t for t in packet_by[workload["case_id"]]["tasks"]}
        owned={}
        # Analysis regions may overlap for context, but semantic annotation has
        # exactly one canonical owner per target.  Assign ownership in stable
        # region order so overlapping context never creates duplicate reviews.
        for region in sorted(workload["regions"],key=lambda x:x["region_id"]):
            if region["arm"]!="P2a":continue
            target_ids=[]
            for target_id in region["target_ids"]:
                if target_id in owned:
                    excluded.append({"case_id":workload["case_id"],"target_id":target_id,"owner_region_id":owned[target_id],"excluded_region_id":region["region_id"]})
                else:
                    owned[target_id]=region["region_id"];target_ids.append(target_id)
            if not target_ids:continue
            rows.append({"batch_id":"terra-"+region["fingerprint"][:24],"case_id":workload["case_id"],"source_hash":workload["source_hash"],"packet_id":packet_by[workload["case_id"]]["packet_id"],"region_id":region["region_id"],"region_fingerprint":region["fingerprint"],"target_ids":target_ids,"task_ids":[task_by[x]["task_id"] for x in target_ids],"prompt_version":policy["terra_prompt_version"],"producer":{"source_type":"model","producer_id":"model:gpt-5.6-terra","model":"gpt-5.6-terra","reasoning_effort":"low"},"execution_status":"not_run_no_endpoint_or_budget","semantic_output_present":False})
    assigned=[(b["case_id"],target_id) for b in rows for target_id in b["target_ids"]]
    if len(assigned)!=len(set(assigned)):
        raise AnnotationError("Terra batch ownership is not unique",code="duplicate_batch_target")
    return {"artifact_type":"TerraAnnotationBatchManifest","manifest_version":"terra-au-batches-v1","status":"ready_not_executed","batch_count":len(rows),"prompt_version":policy["terra_prompt_version"],"input_contract":"raw source rendered from packet/region refs only","output_schema_version":policy["model_proposal_schema_version"],"batches":sorted(rows,key=lambda x:(x["case_id"],x["region_id"])),"excluded_duplicate_assignments":excluded,"provider_calls":0}

def checkpoint_model_proposal(*, proposal, output_root, source_store, policy):
    """Atomically record one already-executed, traced Terra batch; never invent decisions."""
    root=Path(output_root)
    manifest_path=root/"au_annotation_build_manifest.json"
    terra_path=root/"terra_proposal_manifest.json"
    batches_path=root/"terra_annotation_batches.json"
    if not (manifest_path.is_file() and terra_path.is_file() and batches_path.is_file()):
        raise AnnotationError("Plan 09 build artifacts are required before a model checkpoint",code="checkpoint_dependency_missing")
    manifest=load_json(manifest_path); terra=load_json(terra_path); batches=load_json(batches_path)
    row=next((x for x in manifest["cases"] if x["case_id"]==proposal.get("case_id")),None)
    if row is None: raise AnnotationError("proposal case is outside the Plan 09 workload",code="checkpoint_case_unknown")
    packet=load_json(root/row["packet_ref"]); text=open_source(source_store,packet["case_id"],packet["source_hash"])
    batch=next((x for x in batches["batches"] if x["batch_id"]==proposal.get("batch_id")),None)
    if batch is None or (batch["case_id"],batch["packet_id"],batch["source_hash"]) != (packet["case_id"],packet["packet_id"],packet["source_hash"]):
        raise AnnotationError("proposal batch does not match the packet/source",code="checkpoint_batch_mismatch")
    reviewed={x.get("target_id") for x in proposal.get("target_reviews",[])}
    if not reviewed or not reviewed <= set(batch["target_ids"]):
        raise AnnotationError("checkpoint may contain only targets assigned to its batch",code="checkpoint_batch_mismatch")
    for review in proposal["target_reviews"]:
        trace=review.get("review_trace",{})
        if trace.get("region_id")!=batch["region_id"] or trace.get("region_fingerprint")!=batch["region_fingerprint"]:
            raise AnnotationError("review trace must identify the checkpoint batch region",code="checkpoint_batch_mismatch")
    validate_model_proposal(proposal,packet,text,policy)
    previous=set()
    for record in terra.get("proposals",[]):
        existing=load_json(root/record["proposal_ref"])
        previous.update(x["target_id"] for x in existing["target_reviews"])
    duplicate=sorted(previous & reviewed)
    if duplicate: raise AnnotationError("target was already checkpointed: "+", ".join(duplicate),code="checkpoint_duplicate_target")
    relative=Path("model_proposals")/packet["case_id"]/(proposal["proposal_id"]+".json")
    destination=root/relative
    if destination.exists(): raise AnnotationError("proposal id already exists",code="checkpoint_duplicate_proposal")
    atomic_write(destination,proposal)
    record={"proposal_id":proposal["proposal_id"],"case_id":packet["case_id"],"batch_id":batch["batch_id"],"proposal_ref":relative.as_posix(),"reviewed_target_count":len(reviewed),"authority_unit_count":sum(len(x.get("authority_units",[])) for x in proposal["target_reviews"]),"hard_negative_count":sum(x.get("hard_negative") is not None for x in proposal["target_reviews"]),"unresolved_target_count":sum(x.get("model_outcome")=="unresolved" for x in proposal["target_reviews"])}
    records=terra["proposals"]+[record]
    terra.update({"status":"partially_checkpointed","proposal_count":len(records),"reviewed_target_count":sum(x["reviewed_target_count"] for x in records),"target_count":sum(x["reviewed_target_count"] for x in records),"authority_unit_count":sum(x["authority_unit_count"] for x in records),"hard_negative_count":sum(x["hard_negative_count"] for x in records),"unresolved_target_count":sum(x["unresolved_target_count"] for x in records),"semantic_silver_ready":False,"proposals":records})
    atomic_write(terra_path,terra)
    manifest["silver_status"]="partially_checkpointed_model_review";manifest["provenance"]["terra_proposals_materialized"]=True;atomic_write(manifest_path,manifest)
    report_path=root.parents[1]/"reports"/"plan09_au_gold_readiness.latest.json"
    if report_path.is_file():
        report=load_json(report_path); silver=report["silver_readiness"]
        for key in ("proposal_count","reviewed_target_count","authority_unit_count","hard_negative_count","unresolved_target_count"):silver[key]=terra[key]
        silver["status"]="partially_checkpointed_model_review";atomic_write(report_path,report)
    return record

def build_plan09(*,plan07_report,plan08_independent_report,source_store,policy_path,split_registry,hard_cases_path,output_root,report_path,repo_root):
    started=time.perf_counter();p8=Path(plan08_independent_report).read_text(encoding="utf-8")
    if "**PASS" not in p8 or "fixed_verified" not in p8:raise ValueError("Plan 08 independent gate must PASS")
    policy=load_json(policy_path);hard_cases=load_json(hard_cases_path);workloads,p7,p7manifest=load_plan07_workloads(plan07_report);root=Path(output_root);rows=[];packets=[]
    for workload in workloads:
        text=open_source(source_store,workload["case_id"],workload["source_hash"]);packet=build_packet(workload,policy,hard_cases);checks=validate_packet(packet,workload,text,policy);case_root=root/"packets"/workload["case_id"]/workload["source_hash"];packet_path=case_root/"annotation_packet.json";atomic_write(packet_path,packet)
        atomic_write(case_root/"annotator_a.template.json",new_submission(packet,"ANNOTATOR_A","Human annotator A"));atomic_write(case_root/"annotator_b.template.json",new_submission(packet,"ANNOTATOR_B","Human annotator B"));_render_review(packet,text,case_root/"review.html");packets.append(packet);rows.append({"case_id":workload["case_id"],"source_hash":workload["source_hash"],"packet_id":packet["packet_id"],"packet_ref":packet_path.relative_to(root).as_posix(),"review_ref":(case_root/"review.html").relative_to(root).as_posix(),"annotator_a_template_ref":(case_root/"annotator_a.template.json").relative_to(root).as_posix(),"annotator_b_template_ref":(case_root/"annotator_b.template.json").relative_to(root).as_posix(),**checks})
    rejected_ref="rejected_noncanonical/blanket_abstentions" if (root/"rejected_noncanonical/blanket_abstentions").is_dir() else None
    proposal_manifest={"artifact_type":"TerraProposalManifest","manifest_version":"terra-proposal-manifest-v2","status":"not_run_no_review_trace","producer":{"source_type":"model","producer_id":"model:gpt-5.6-terra","model":"gpt-5.6-terra","reasoning_effort":"low"},"provider_or_endpoint_usage_claimed":False,"proposal_count":0,"reviewed_target_count":0,"target_count":0,"authority_unit_count":0,"hard_negative_count":0,"unresolved_target_count":0,"semantic_silver_ready":False,"rejected_noncanonical_ref":rejected_ref,"required_before_materialization":["per-target review trace", "exact target/source checksum", "region reference/fingerprint", "specific decision or unresolved reason", "checkpointed batch identity"],"proposals":[]};atomic_write(root/"terra_proposal_manifest.json",proposal_manifest)
    heldout=build_heldout_lock(split_registry,repo_root);validate_heldout_lock(heldout,split_registry,repo_root);atomic_write(root/"heldout_source_lock.json",heldout);fewshot=select_few_shot(None);atomic_write(root/"few_shot_selection_manifest.json",fewshot);silver_fewshot=select_silver_few_shot(None);atomic_write(root/"silver_few_shot_selection_manifest.json",silver_fewshot);terra=_terra_batches(workloads,packets,policy);atomic_write(root/"terra_annotation_batches.json",terra)
    progress={"artifact_type":"HumanAnnotationProgress","progress_version":"plan09-human-progress-v1","status":"awaiting_human_adjudication","packet_count":len(packets),"target_count":sum(len(x["tasks"]) for x in packets),"independent_submission_count":0,"adjudication_count":0,"locked_gold_snapshot_count":0,"semantic_gold_available":False};atomic_write(root/"human_annotation_progress.json",progress)
    disagreement_queue={"artifact_type":"AUDisagreementQueue","queue_version":"au-disagreement-queue-v1","status":"awaiting_two_independent_submissions","items":[],"semantic_gold":False};atomic_write(root/"disagreement_queue.json",disagreement_queue)
    adjudication_queue={"artifact_type":"AUAdjudicationQueue","queue_version":"au-adjudication-queue-v1","status":"awaiting_disagreements","items":[],"named_human_adjudicator_required":True};atomic_write(root/"adjudication_queue.json",adjudication_queue)
    manifest={"artifact_type":"AUAnnotationWorkloadManifest","manifest_version":"plan09-au-workload-v1","status":"structural_ready","overall_status":"gold_awaiting_independent_adjudication","silver_status":"awaiting_traced_model_review","workload":"KOS-5","policy_sha256":canonical_hash(policy),"plan07_manifest_sha256":canonical_hash(p7manifest),"source_store":str(Path(source_store).resolve()),"packet_count":len(packets),"target_count":sum(x["task_count"] for x in rows),"semantic_label_count":0,"cases":sorted(rows,key=lambda x:x["case_id"]),"heldout_lock_ref":"heldout_source_lock.json","few_shot_manifest_ref":"few_shot_selection_manifest.json","silver_few_shot_manifest_ref":"silver_few_shot_selection_manifest.json","human_progress_ref":"human_annotation_progress.json","disagreement_queue_ref":"disagreement_queue.json","adjudication_queue_ref":"adjudication_queue.json","terra_batch_manifest_ref":"terra_annotation_batches.json","terra_proposal_manifest_ref":"terra_proposal_manifest.json","gold_snapshot_ref":None,"silver_snapshot_ref":None,"provenance":{"raw_source":True,"structural_refs_only":True,"kos_used_as_gold":False,"model_semantic_labels":False,"terra_proposals_materialized":False}};atomic_write(root/"au_annotation_build_manifest.json",manifest)
    report={"report_version":"plan09-au-gold-readiness-v1","overall_status":"gold_awaiting_independent_adjudication","structural_tool_readiness":{"status":"structural_ready","packet_count":len(packets),"target_count":manifest["target_count"],"exact_kos5":len(packets)==5,"raw_source_hash_verified":True,"blank_packets_no_semantic_labels":True},"silver_readiness":{"status":"awaiting_traced_model_review","batch_contract_ready":terra["batch_count"]==96,"batch_count":terra["batch_count"],"proposal_count":0,"reviewed_target_count":0,"unresolved_target_count":0,"authority_unit_count":0,"hard_negative_count":0,"provider_calls":0,"provider_or_endpoint_usage_claimed":False,"locked_silver_snapshot":None,"evaluation_boundary":"any future score must declare evaluation_against=model_silver"},"human_annotation_progress":progress,"gold_lock_status":{"status":"gold_awaiting_independent_adjudication","locked_gold_snapshot":None,"semantic_pass":False},"split_leakage_status":{"status":"dependency_missing","case_id_disjoint":heldout["checks"]["case_id_disjoint"],"source_hash_disjoint":heldout["checks"]["source_hash_disjoint"],"heldout_labels_materialized":False,"source_contract_dependency":heldout["status"]},"few_shot_readiness":{"status":fewshot["status"],"record_count":0,"heldout_excluded":True,"silver_manifest_status":silver_fewshot["status"],"silver_evaluation_against":silver_fewshot["evaluation_against"]},"inputs":{"plan07_report":str(Path(plan07_report).resolve()),"plan08_independent_report":str(Path(plan08_independent_report).resolve()),"source_store":str(Path(source_store).resolve()),"policy":str(Path(policy_path).resolve()),"split_registry":str(Path(split_registry).resolve())},"outputs":{"output_root":str(root.resolve()),"build_manifest":str((root/'au_annotation_build_manifest.json').resolve()),"heldout_lock":str((root/'heldout_source_lock.json').resolve()),"few_shot_manifest":str((root/'few_shot_selection_manifest.json').resolve()),"silver_few_shot_manifest":str((root/'silver_few_shot_selection_manifest.json').resolve()),"terra_proposal_manifest":str((root/'terra_proposal_manifest.json').resolve()),"human_progress":str((root/'human_annotation_progress.json').resolve()),"terra_batches":str((root/'terra_annotation_batches.json').resolve()),"audit_html":str(Path(report_path).with_name('plan09_au_annotation_audit.html').resolve())},"gates":{"structural_ready":manifest["target_count"]==369,"silver_ready":False,"two_independent_human_submissions":False,"human_adjudication_complete":False,"locked_gold_valid":False,"heldout_source_contract_valid":False,"few_shot_ready":False,"plan10_allowed":False},"elapsed_seconds":max(time.perf_counter()-started,1e-9),"limitations":["Agent cannot create independent human gold.","KOS-5 calibration is not held-out semantic evidence.","Structural readiness does not establish annotation quality.","No Terra proposal is materialized without a per-target review trace/checksum and specific decision or unresolved reason.","No provider endpoint or budget was supplied and no provider/endpoint usage is claimed.","Future accepted Terra labels remain model silver and cannot unlock held-out quality claims."]};atomic_write(report_path,report);_render_audit(report,report["outputs"]["audit_html"]);return report
