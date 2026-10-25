"""Human-only AU annotation, adjudication, and locking contracts for Plan 09."""
from __future__ import annotations
import copy,hashlib,json
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator
from ..sentence_atoms.segmenter import canonical_hash
from ..source_contract import open_source

KINDS={"holding","standard_of_review","statutory_hook","procedural_rule","fact_pattern_rule","foreign_law","other","unresolved_kind"}
NEGATIVE_REASONS={"party_argument_only","fact_only","procedural_history_only","citation_without_proposition","editorial","insufficient_context","other"}
FORBIDDEN_PROVENANCE={"model","llm","codex","kos","old_pipeline","weak_label","self_training"}
ANNOTATION_TRANSITIONS={"unassigned":{"independently_annotated"},"independently_annotated":{"disagreement","pending_adjudication"},"disagreement":{"pending_adjudication"},"pending_adjudication":{"adjudicated"},"adjudicated":{"locked"},"locked":set()}

class AnnotationError(ValueError):
    def __init__(self,detail,*,code="annotation_contract",location="<root>"):
        self.code,self.location,self.detail=code,location,detail;super().__init__(f"[{code}] {location}: {detail}")

def transition_annotation_state(old,new):
    if new not in ANNOTATION_TRANSITIONS.get(old,set()):raise AnnotationError(f"illegal annotation transition {old}->{new}",code="illegal_annotation_transition")
    return new

def load_json(path):
    try:return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:raise AnnotationError("invalid JSON",code="malformed_artifact",location=str(path)) from exc

def atomic_write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");tmp.replace(path)

def schema_validator(name):
    path=Path(__file__).resolve().parents[1]/"contracts"/name;schema=load_json(path);Draft202012Validator.check_schema(schema);return Draft202012Validator(schema)

def validate_schema(value,name):
    errors=sorted(schema_validator(name).iter_errors(value),key=lambda e:list(e.path))
    if errors:raise AnnotationError(errors[0].message,code="schema_violation",location="/"+"/".join(map(str,errors[0].path)))

def exact_span(text,case_id,source_hash,start,end):
    quote=text[start:end]
    return {"case_id":case_id,"source_hash":source_hash,"start_char":start,"end_char":end,"quote":quote,"text_sha256":hashlib.sha256(quote.encode()).hexdigest()}

def verify_span(span,text,case_id,source_hash,*,allow_empty=False):
    if not isinstance(span,dict):raise AnnotationError("span object required",code="span_invalid")
    required={"case_id","source_hash","start_char","end_char","quote","text_sha256"}
    if set(span)!=required:raise AnnotationError("exact span fields mismatch",code="span_invalid")
    if span["case_id"]!=case_id or span["source_hash"]!=source_hash:raise AnnotationError("span source identity mismatch",code="source_mismatch")
    a,b=span["start_char"],span["end_char"]
    if not isinstance(a,int) or not isinstance(b,int) or a<0 or b<a or (a==b and not allow_empty) or b>len(text):raise AnnotationError("span offset outside source",code="offset_violation")
    quote=text[a:b]
    if span["quote"]!=quote or span["text_sha256"]!=hashlib.sha256(quote.encode()).hexdigest():raise AnnotationError("span quote/hash mismatch",code="quote_mismatch")
    return quote

def _packet_identity(case_id,source_hash,workload,policy):
    return canonical_hash({"case_id":case_id,"source_hash":source_hash,"workload_cache_key":workload["cache_key"],"policy_sha256":canonical_hash(policy),"guideline_version":policy["guideline_version"]})

def build_packet(workload,policy,hard_cases):
    case_id,source_hash=workload["case_id"],workload["source_hash"]
    work_by_target={t["target_id"]:[] for t in workload["targets"]}
    for batch in workload["batches"]:
        for item in batch["work_items"]:work_by_target[item["target_id"]].append({"work_item_id":item["work_item_id"],"slice_id":item["slice_id"],"span":item["span"]})
    regions_by_target={t["target_id"]:[] for t in workload["targets"]}
    for region in workload["regions"]:
        for target_id in region["target_ids"]:regions_by_target[target_id].append({"region_id":region["region_id"],"arm":region["arm"],"batch_id":region["batch_id"],"region_fingerprint":region["fingerprint"]})
    case_triggers=[s["situation_id"] for s in hard_cases["situations"] if case_id in s["candidate_cases"] and s["class"]!="operations"]
    tasks=[]
    for target in workload["targets"]:
        triggers=[{"trigger_id":x,"basis":"candidate_queue_only","semantic_label":False} for x in case_triggers]
        if target["mode"]=="sliced":triggers.append({"trigger_id":"structural-long-target-sliced","basis":"plan07_scheduler","semantic_label":False})
        if any(r["arm"]=="P2b" for r in regions_by_target[target["target_id"]]):triggers.append({"trigger_id":"context-review-available","basis":"plan07_region_ref","semantic_label":False})
        span=target["content_span"]
        tasks.append({"task_id":"aut-"+canonical_hash({"target":target["target_id"],"packet":_packet_identity(case_id,source_hash,workload,policy)})[:24],"target_id":target["target_id"],"owner_block_id":target["parent_block_id"],"target_span":span,"work_item_refs":sorted(work_by_target[target["target_id"]],key=lambda x:x["work_item_id"]),"region_refs":sorted(regions_by_target[target["target_id"]],key=lambda x:(x["arm"],x["region_id"])),"tool_refs":{"open_exact":{"tool":"open_span","span":span},"open_expanded":{"tool":"expand_context","target_id":target["target_id"],"max_neighbor_blocks":2}},"structural_triggers":triggers,"annotation_state":"unassigned"})
    packet_id="aup-"+_packet_identity(case_id,source_hash,workload,policy)[:24]
    return {"artifact_type":"AUAnnotationPacket","schema_version":policy["packet_schema_version"],"packet_id":packet_id,"case_id":case_id,"source_hash":source_hash,"split":"calibration","guideline_version":policy["guideline_version"],"policy_sha256":canonical_hash(policy),"dependencies":{"analysis_workload_cache_key":workload["cache_key"],"analysis_region_policy_sha256":workload["policy_sha256"],"sourceblock_cache_key":workload["dependencies"]["sourceblock_cache_key"],"sentence_atom_cache_key":workload["dependencies"]["sentence_atom_cache_key"],"sidecar_cache_key":workload["dependencies"]["sidecar_cache_key"],"context_hint_cache_key":workload["dependencies"]["context_hint_cache_key"]},"tasks":sorted(tasks,key=lambda x:x["target_id"]),"semantic_labels_present":False,"provenance":{"source_type":"raw_source_and_structural_refs","semantic_sources":[],"structural_triggers_semantic":False}}

def validate_packet(packet,workload,text,policy):
    validate_schema(packet,"annotation_task.v1.json")
    if packet["case_id"]!=workload["case_id"] or packet["source_hash"]!=workload["source_hash"] or hashlib.sha256(text.encode()).hexdigest()!=packet["source_hash"]:raise AnnotationError("packet source identity mismatch",code="source_mismatch")
    expected=build_packet(workload,policy,load_json(Path(__file__).resolve().parents[1]/"hard_cases.v1.json"))
    if packet!=expected:raise AnnotationError("packet differs from deterministic blank build",code="packet_mismatch")
    forbidden={"authority_units","gold","gold_noticed","issue","model_output","no_au"}
    def keys(node):
        if isinstance(node,dict):return set(map(str.lower,node))|set().union(*(keys(v) for v in node.values()),set())
        if isinstance(node,list):return set().union(*(keys(v) for v in node),set())
        return set()
    if forbidden&keys(packet):raise AnnotationError("semantic or KOS/model label leaked into blank packet",code="gold_leakage")
    if len(packet["tasks"])!=len({t["target_id"] for t in packet["tasks"]}):raise AnnotationError("target task coverage is not exactly once",code="task_coverage")
    return {"task_count":len(packet["tasks"]),"semantic_labels_present":False}

def new_submission(packet,annotator_id,display_name):
    return {"artifact_type":"AUAnnotatorSubmission","schema_version":"au-annotator-submission-v1","submission_id":"sub-"+canonical_hash({"packet":packet["packet_id"],"annotator":annotator_id})[:24],"packet_id":packet["packet_id"],"case_id":packet["case_id"],"source_hash":packet["source_hash"],"annotator":{"annotator_id":annotator_id,"display_name":display_name,"role":"annotator","source_type":"human"},"blindness":{"peer_submissions_visible":False,"visible_peer_submission_ids":[]},"guideline_version":packet["guideline_version"],"submission_status":"draft","target_reviews":[{"target_id":t["target_id"],"review_complete":False,"reviewed_span":None,"authority_units":[],"hard_negative":None,"notes":[]} for t in packet["tasks"]]}

def _verify_human_provenance(prov,annotator_id,guideline_version):
    if not isinstance(prov,dict) or prov.get("source_type")!="human" or prov.get("annotator_id")!=annotator_id or prov.get("guideline_version")!=guideline_version or prov.get("derived_from")!=[]:raise AnnotationError("human-only provenance required",code="forbidden_provenance")
    if any(str(v).lower() in FORBIDDEN_PROVENANCE for v in prov.values() if isinstance(v,str)):raise AnnotationError("model/KOS provenance forbidden",code="forbidden_provenance")

def _span_overlap(a,b):return max(a["start_char"],b["start_char"])<min(a["end_char"],b["end_char"])

def validate_au(au,task,text,submission,policy,all_tasks):
    validate_schema(au,"authority_unit_human.v1.json");annotator_id=submission["annotator"]["annotator_id"]
    _verify_human_provenance(au["provenance"],annotator_id,submission["guideline_version"])
    if au["owner_target_id"]!=task["target_id"] or au["owner_block_id"]!=task["owner_block_id"]:raise AnnotationError("AU owner id mismatch",code="wrong_owner",location=au["au_id"])
    if au["kind"] not in KINDS or (au["kind"]=="other" and not au["other_kind"]) or (au["kind"]!="other" and au["other_kind"] is not None):raise AnnotationError("kind/other_kind contract violated",code="kind_invalid",location=au["au_id"])
    evidence=au["evidence_spans"]
    for field in ("evidence_spans","condition_spans","exception_spans","limit_spans","cross_block_refs"):
        for span in au[field]:verify_span(span,text,submission["case_id"],submission["source_hash"])
    for attr in au["attributions"]:
        if set(attr)!={"role","speaker","evidence_span"}:raise AnnotationError("attribution requires field-level witness",code="field_witness_missing")
        verify_span(attr["evidence_span"],text,submission["case_id"],submission["source_hash"])
    start=min(x["start_char"] for x in evidence);target_span=task["target_span"]
    if not (target_span["start_char"]<=start<target_span["end_char"]):raise AnnotationError("owner must contain evidence start",code="wrong_owner",location=au["au_id"])
    task_by_id={x["target_id"]:x for x in all_tasks};owner=next((x for x in all_tasks if x["target_span"]["start_char"]<=start<x["target_span"]["end_char"]),None)
    if owner is None or owner["target_id"]!=task["target_id"]:raise AnnotationError("owner target is not canonical evidence-start owner",code="wrong_owner")
    for cross in au["cross_block_refs"]:
        if cross["start_char"]==start and cross["end_char"]==evidence[0]["end_char"]:raise AnnotationError("cross-block refs must identify additional evidence",code="cross_block_invalid")
    if au["status"]!="independently_annotated":raise AnnotationError("submission AU must be independently_annotated",code="state_invalid")

def validate_submission(submission,packet,text,policy):
    validate_schema(submission,"annotator_submission.v1.json")
    if (submission["packet_id"],submission["case_id"],submission["source_hash"],submission["guideline_version"])!=(packet["packet_id"],packet["case_id"],packet["source_hash"],packet["guideline_version"]):raise AnnotationError("submission dependency mismatch",code="dependency_mismatch")
    annotator=submission["annotator"]
    if annotator["source_type"]!="human" or annotator["role"]!="annotator":raise AnnotationError("human annotator required",code="forbidden_provenance")
    if submission["blindness"]!={"peer_submissions_visible":False,"visible_peer_submission_ids":[]}:raise AnnotationError("independent annotator leakage",code="annotator_leakage")
    tasks={t["target_id"]:t for t in packet["tasks"]};reviews=submission["target_reviews"]
    ids=[r.get("target_id") for r in reviews]
    if len(ids)!=len(set(ids)):raise AnnotationError("duplicate target review",code="duplicate_review")
    if submission["submission_status"]=="independently_annotated" and set(ids)!=set(tasks):raise AnnotationError("independent submission must cover every packet target",code="incomplete_submission")
    au_ids=set()
    for review in reviews:
        task=tasks.get(review.get("target_id"))
        if task is None:raise AnnotationError("review target not in packet",code="heldout_or_foreign_target")
        if submission["submission_status"]=="independently_annotated" and review.get("review_complete") is not True:raise AnnotationError("target review incomplete",code="incomplete_submission")
        if review.get("reviewed_span") is not None:
            verify_span(review["reviewed_span"],text,packet["case_id"],packet["source_hash"])
            expected=task["target_span"]
            if (review["reviewed_span"]["start_char"],review["reviewed_span"]["end_char"])!=(expected["start_char"],expected["end_char"]):raise AnnotationError("reviewed span must cover whole target",code="partial_target_review")
        elif submission["submission_status"]=="independently_annotated":raise AnnotationError("full target reviewed_span required",code="partial_target_review")
        aus=review.get("authority_units",[]);negative=review.get("hard_negative")
        if aus and negative is not None:raise AnnotationError("target cannot be positive and hard negative",code="positive_negative_conflict")
        if not aus and negative is None and submission["submission_status"]=="independently_annotated":raise AnnotationError("review needs AU or explicit hard negative",code="missing_review_outcome")
        if negative is not None:
            if not review.get("review_complete") or negative.get("reason") not in NEGATIVE_REASONS or negative.get("provenance",{}).get("source_type")!="human":raise AnnotationError("hard negative requires full human target review and allowed reason",code="invalid_hard_negative")
            verify_span(negative.get("reviewed_span"),text,packet["case_id"],packet["source_hash"])
            if negative["reviewed_span"]!=review["reviewed_span"]:raise AnnotationError("hard negative span must equal full reviewed target",code="invalid_hard_negative")
        for au in aus:
            if au["au_id"] in au_ids:raise AnnotationError("duplicate AU id",code="duplicate_au")
            au_ids.add(au["au_id"]);validate_au(au,task,text,submission,policy,packet["tasks"])
        for i,left in enumerate(aus):
            for right in aus[i+1:]:
                if left["evidence_spans"][0]==right["evidence_spans"][0]:raise AnnotationError("exact duplicate AU span forbidden",code="duplicate_au")
                if _span_overlap(left["evidence_spans"][0],right["evidence_spans"][0]) and (left["overlap_disposition"]!="distinct_supported" or right["overlap_disposition"]!="distinct_supported" or not left["notes"] or not right["notes"]):raise AnnotationError("overlap requires distinct_supported and notes",code="overlap_unresolved")
    return {"target_review_count":len(reviews),"au_count":len(au_ids),"hard_negative_count":sum(r.get("hard_negative") is not None for r in reviews),"status":submission["submission_status"]}

def _au_signature(au):return (tuple((x["start_char"],x["end_char"]) for x in au["evidence_spans"]),au["kind"],bool(au["attributions"]),bool(au["condition_spans"]),bool(au["exception_spans"]),bool(au["limit_spans"]))

def compare_submissions(a,b,packet,text,policy):
    validate_submission(a,packet,text,policy);validate_submission(b,packet,text,policy)
    if a["annotator"]["annotator_id"]==b["annotator"]["annotator_id"] or a["submission_id"]==b["submission_id"]:raise AnnotationError("two distinct annotators required",code="missing_second_annotator")
    by_a={x["target_id"]:x for x in a["target_reviews"]};by_b={x["target_id"]:x for x in b["target_reviews"]};items=[]
    for target_id in sorted(by_a):
        ra,rb=by_a[target_id],by_b[target_id];dims=[];aa,bb=ra["authority_units"],rb["authority_units"]
        if bool(aa)!=bool(bb):dims.append("negative_vs_positive")
        elif not aa and ra["hard_negative"]["reason"]!=rb["hard_negative"]["reason"]:dims.append("negative_reason")
        elif aa:
            sa,sb=sorted(_au_signature(x) for x in aa),sorted(_au_signature(x) for x in bb)
            if [x[0] for x in sa]!=[x[0] for x in sb]:dims.append("span")
            if [x[1] for x in sa]!=[x[1] for x in sb]:dims.append("kind")
            for idx,name in ((2,"attribution_presence"),(3,"condition_presence"),(4,"exception_presence"),(5,"limit_presence")):
                if [x[idx] for x in sa]!=[x[idx] for x in sb]:dims.append(name)
        if dims:items.append({"target_id":target_id,"dimensions":dims,"submission_a_refs":[x["au_id"] for x in aa],"submission_b_refs":[x["au_id"] for x in bb]})
    value={"artifact_type":"AUDisagreementLog","schema_version":"au-disagreement-v1","comparison_id":"cmp-"+canonical_hash({"a":a["submission_id"],"b":b["submission_id"]})[:24],"packet_id":packet["packet_id"],"submission_ids":[a["submission_id"],b["submission_id"]],"case_id":packet["case_id"],"status":"pending_adjudication" if items else "agreement","items":items};validate_schema(value,"au_disagreement.v1.json");return value

def create_adjudication_template(packet,a,b,disagreement,adjudicator_id,display_name):
    if disagreement["submission_ids"]!=[a["submission_id"],b["submission_id"]]:raise AnnotationError("disagreement/submission mismatch",code="dependency_mismatch")
    return {"artifact_type":"AUAdjudicationDecision","schema_version":"au-adjudication-v1","adjudication_id":"adj-"+canonical_hash({"packet":packet["packet_id"],"submissions":disagreement["submission_ids"],"adjudicator":adjudicator_id})[:24],"packet_id":packet["packet_id"],"case_id":packet["case_id"],"source_hash":packet["source_hash"],"submission_ids":disagreement["submission_ids"],"disagreement_id":disagreement["comparison_id"],"adjudicator":{"adjudicator_id":adjudicator_id,"display_name":display_name,"role":"adjudicator","source_type":"human"},"source_review_confirmed":False,"override":None,"decisions":[],"status":"pending_adjudication"}

def validate_adjudication(value,packet,a,b,disagreement,text,policy):
    if value.get("status")!="adjudicated" or value.get("source_review_confirmed") is not True:raise AnnotationError("named human adjudicator must confirm exact source",code="adjudication_without_source")
    validate_schema(value,"au_adjudication.v1.json")
    if value["submission_ids"]!=[a["submission_id"],b["submission_id"]] or value["disagreement_id"]!=disagreement["comparison_id"]:raise AnnotationError("adjudication dependency mismatch",code="dependency_mismatch")
    if value["adjudicator"]["source_type"]!="human" or value["adjudicator"]["role"]!="adjudicator" or not value["adjudicator"]["adjudicator_id"]:raise AnnotationError("named human adjudicator required",code="forbidden_provenance")
    if len({a["annotator"]["annotator_id"],b["annotator"]["annotator_id"]})<2:raise AnnotationError("two independent submissions required",code="missing_second_annotator")
    decisions={d.get("target_id"):d for d in value["decisions"]}
    if set(decisions)!={t["target_id"] for t in packet["tasks"]}:raise AnnotationError("adjudication must decide every target",code="incomplete_adjudication")
    synthetic={**a,"submission_id":"adjudicated-"+value["adjudication_id"],"annotator":{"annotator_id":value["adjudicator"]["adjudicator_id"],"display_name":value["adjudicator"]["display_name"],"role":"annotator","source_type":"human"},"target_reviews":copy.deepcopy(value["decisions"]),"submission_status":"independently_annotated"}
    for review in synthetic["target_reviews"]:
        for au in review.get("authority_units",[]):au["status"]="independently_annotated";au["provenance"]={"source_type":"human","annotator_id":value["adjudicator"]["adjudicator_id"],"guideline_version":value.get("guideline_version",packet["guideline_version"]),"derived_from":[]}
    validate_submission(synthetic,packet,text,policy);return {"decision_count":len(decisions),"status":"adjudicated"}

def lock_gold(packets,submissions,adjudications,policy,source_text_by_case=None):
    if source_text_by_case is None:raise AnnotationError("gold lock requires exact source validation",code="adjudication_without_source")
    if any(s.get("artifact_type")!="AUAnnotatorSubmission" or "submission_id" not in s for s in submissions) or any(a.get("artifact_type")!="AUAdjudicationDecision" for a in adjudications):raise AnnotationError("human submission/adjudication artifacts required for gold",code="forbidden_provenance")
    packet_by={p["packet_id"]:p for p in packets};sub_by={s["submission_id"]:s for s in submissions};units=[];negatives=[];case_rows=[]
    if not packets:raise AnnotationError("no packets",code="no_gold")
    for adjudication in adjudications:
        validate_schema(adjudication,"au_adjudication.v1.json")
        packet=packet_by.get(adjudication["packet_id"])
        if packet is None:raise AnnotationError("foreign adjudication packet",code="dependency_mismatch")
        if any(x not in sub_by for x in adjudication["submission_ids"]):raise AnnotationError("gold requires two recorded submissions",code="missing_second_annotator")
        selected=[sub_by[x] for x in adjudication["submission_ids"]]
        override=adjudication.get("override")
        if len(adjudication["submission_ids"])<2:
            expected_override={"reason":override.get("reason") if isinstance(override,dict) else None,"authorized_by":adjudication.get("adjudicator",{}).get("adjudicator_id"),"single_annotator_exception":True}
            if not isinstance(override,dict) or override!=expected_override or not override["reason"]:raise AnnotationError("gold requires two submissions or documented named-human override",code="missing_second_annotator")
        elif len({x.get("annotator",{}).get("annotator_id") for x in selected})<2:raise AnnotationError("gold requires two distinct human annotators",code="missing_second_annotator")
        if any(x.get("annotator",{}).get("source_type")!="human" for x in selected):raise AnnotationError("gold submissions must be human",code="forbidden_provenance")
        if adjudication.get("status")!="adjudicated" or adjudication.get("source_review_confirmed") is not True or adjudication.get("adjudicator",{}).get("source_type")!="human" or not adjudication.get("adjudicator",{}).get("adjudicator_id"):raise AnnotationError("gold requires named human source-confirmed adjudication",code="adjudication_without_source")
        text=source_text_by_case.get(packet["case_id"])
        if text is None:raise AnnotationError("gold source text unavailable",code="adjudication_without_source")
        for submission in selected:validate_submission(submission,packet,text,policy)
        if len(selected)>=2:
            disagreement=compare_submissions(selected[0],selected[1],packet,text,policy);validate_adjudication(adjudication,packet,selected[0],selected[1],disagreement,text,policy)
        else:
            judge=adjudication["adjudicator"];synthetic=copy.deepcopy(selected[0]);synthetic["submission_id"]="override-"+adjudication["adjudication_id"];synthetic["annotator"]={"annotator_id":judge["adjudicator_id"],"display_name":judge["display_name"],"role":"annotator","source_type":"human"};synthetic["target_reviews"]=copy.deepcopy(adjudication["decisions"])
            validate_submission(synthetic,packet,text,policy)
        if {d.get("target_id") for d in adjudication["decisions"]}!={t["target_id"] for t in packet["tasks"]}:raise AnnotationError("gold adjudication does not cover every target",code="incomplete_adjudication")
        for decision in adjudication["decisions"]:
            for au in decision.get("authority_units",[]):
                if au.get("provenance",{}).get("source_type")!="human" or any(str(v).lower() in FORBIDDEN_PROVENANCE for v in au.get("provenance",{}).values() if isinstance(v,str)):raise AnnotationError("model/KOS AU cannot enter human gold",code="forbidden_provenance")
                locked=copy.deepcopy(au);locked["status"]="locked";units.append(locked)
            if decision.get("hard_negative") is not None:
                if decision["hard_negative"].get("provenance",{}).get("source_type")!="human":raise AnnotationError("model/KOS negative cannot enter human gold",code="forbidden_provenance")
                negatives.append(copy.deepcopy(decision["hard_negative"]))
        case_rows.append({"case_id":packet["case_id"],"source_hash":packet["source_hash"],"packet_id":packet["packet_id"],"adjudication_id":adjudication["adjudication_id"]})
    if len(case_rows)!=len(packets):raise AnnotationError("every packet requires adjudication before lock",code="incomplete_adjudication")
    deps={"source_snapshot_digest":canonical_hash(sorted((p["case_id"],p["source_hash"]) for p in packets)),"task_digest":canonical_hash(packets),"submission_digest":canonical_hash(submissions),"adjudication_digest":canonical_hash(adjudications),"guideline_version":policy["guideline_version"],"schema_versions":{"packet":policy["packet_schema_version"],"submission":policy["submission_schema_version"],"au":policy["au_schema_version"],"adjudication":policy["adjudication_schema_version"]},"scoring_version":policy["scoring_version"]}
    body={"artifact_type":"LockedAUGoldSnapshot","schema_version":policy["gold_schema_version"],"snapshot_id":"gold-"+canonical_hash(deps)[:24],"status":"locked","split":"calibration","cases":sorted(case_rows,key=lambda x:x["case_id"]),"authority_units":units,"hard_negatives":negatives,"provenance":{"source_type":"human_adjudication","model_or_kos_used":False},**deps};body["lock_digest"]=canonical_hash(body);validate_schema(body,"locked_au_gold.v1.json");return body

def validate_locked_gold(value):
    validate_schema(value,"locked_au_gold.v1.json");copy_value=copy.deepcopy(value);digest=copy_value.pop("lock_digest")
    if canonical_hash(copy_value)!=digest:raise AnnotationError("locked gold digest mismatch",code="digest_tamper")
    if value["provenance"]!={"source_type":"human_adjudication","model_or_kos_used":False}:raise AnnotationError("locked gold provenance invalid",code="forbidden_provenance")
    return True

def select_few_shot(gold,max_records=12):
    if gold is None:
        value={"artifact_type":"AUFewShotSelectionManifest","schema_version":"au-few-shot-selection-v1","selection_id":"fewshot-blocked-no-gold","status":"blocked_no_locked_gold","reason":"no human-adjudicated locked calibration/development gold","allowed_splits":["calibration","development"],"heldout_excluded":True,"heldout_case_ids":[],"evaluation_against":"human_gold","gold_snapshot_id":None,"records":[],"diversity":{"kind_counts":{},"hard_case_count":0},"provenance":{"source_type":"locked_human_gold_only","kos_or_model_used":False}}
    else:
        validate_locked_gold(gold)
        if gold["split"] not in {"calibration","development"}:raise AnnotationError("held-out gold forbidden for few-shot",code="heldout_leakage")
        selected=[];seen=set()
        for au in sorted(gold["authority_units"],key=lambda x:(x["kind"],x["au_id"])):
            if len(selected)>=max_records:break
            if au["kind"] not in seen or len(selected)<max_records:selected.append({"au_id":au["au_id"],"kind":au["kind"],"source_snapshot_id":gold["snapshot_id"],"provenance":"locked_human_gold"});seen.add(au["kind"])
        counts={k:sum(x["kind"]==k for x in selected) for k in sorted(seen)};value={"artifact_type":"AUFewShotSelectionManifest","schema_version":"au-few-shot-selection-v1","selection_id":"fewshot-"+canonical_hash(selected)[:24],"status":"ready","reason":None,"allowed_splits":["calibration","development"],"heldout_excluded":True,"heldout_case_ids":[],"evaluation_against":"human_gold","gold_snapshot_id":gold["snapshot_id"],"records":selected,"diversity":{"kind_counts":counts,"hard_case_count":0},"provenance":{"source_type":"locked_human_gold_only","kos_or_model_used":False}}
    validate_schema(value,"few_shot_selection.v1.json");return value

def select_silver_few_shot(silver,max_records=12):
    if silver is None:
        value={"artifact_type":"AUFewShotSelectionManifest","schema_version":"au-few-shot-selection-v1","selection_id":"fewshot-blocked-no-silver","status":"blocked_no_locked_silver","reason":"no host-validated locked model silver snapshot","allowed_splits":["calibration","development"],"heldout_excluded":True,"heldout_case_ids":[],"evaluation_against":"model_silver","gold_snapshot_id":None,"records":[],"diversity":{"kind_counts":{},"hard_case_count":0},"provenance":{"source_type":"locked_model_silver_only","producer_id":"model:gpt-5.6-terra"}}
    else:
        validate_locked_silver(silver)
        selected=[{"au_id":x["au_id"],"kind":x["kind"],"source_snapshot_id":silver["snapshot_id"],"provenance":"model_silver"} for x in silver["authority_units"][:max_records]];kinds=sorted({x["kind"] for x in selected});value={"artifact_type":"AUFewShotSelectionManifest","schema_version":"au-few-shot-selection-v1","selection_id":"silver-fewshot-"+canonical_hash(selected)[:24],"status":"ready","reason":None,"allowed_splits":["calibration","development"],"heldout_excluded":True,"heldout_case_ids":[],"evaluation_against":"model_silver","gold_snapshot_id":silver["snapshot_id"],"records":selected,"diversity":{"kind_counts":{k:sum(x["kind"]==k for x in selected) for k in kinds},"hard_case_count":0},"provenance":{"source_type":"locked_model_silver_only","producer_id":"model:gpt-5.6-terra"}}
    validate_schema(value,"few_shot_selection.v1.json");return value

def validate_model_proposal(proposal,packet,text,policy):
    """Validate Terra structural fidelity without promoting the proposal to gold."""
    generic = proposal.get('artifact_type') == 'ModelAUProposal'
    validate_schema(proposal,"model_au_proposal.v1.json" if generic else "terra_au_proposal.v1.json")
    if (proposal["packet_id"],proposal["case_id"],proposal["source_hash"])!=(packet["packet_id"],packet["case_id"],packet["source_hash"]):raise AnnotationError("model proposal dependency mismatch",code="dependency_mismatch")
    producer=proposal["producer"]
    model = 'gpt-6.1-sol' if generic else 'gpt-5.6-terra'
    prompt = 'r4-au-annotation-prompt-v1' if generic else policy['terra_prompt_version']
    if producer!={"source_type":"model","producer_id":"model:"+model,"model":model,"reasoning_effort":"low"}:raise AnnotationError("exact model producer identity required",code="forbidden_provenance")
    task_by={t["target_id"]:t for t in packet["tasks"]};review_ids=[r.get("target_id") for r in proposal["target_reviews"]]
    if not review_ids or len(review_ids)!=len(set(review_ids)) or not set(review_ids)<=set(task_by):raise AnnotationError("model proposal reviews must be unique packet targets",code="incomplete_submission")
    # A Terra checkpoint may deliberately cover one scheduled region, unlike a
    # human independent submission which must cover the entire packet.
    pseudo=new_submission(packet,"MODEL_STRUCTURAL_VALIDATOR","Terra structural adapter");pseudo["submission_status"]="draft";pseudo["target_reviews"]=copy.deepcopy(proposal["target_reviews"]);unresolved_count=0
    for review in pseudo["target_reviews"]:
        task=task_by[review["target_id"]];trace=review.pop("review_trace",None)
        if generic:
            contexts=review.pop('context_spans',None)
            target=task['target_span']
            if not contexts or not any(s['start_char']<=target['start_char'] and s['end_char']>=target['end_char'] and (s['start_char']<target['start_char'] or s['end_char']>target['end_char']) for s in contexts):
                raise AnnotationError('R4 full target plus neighboring context required',code='model_context_missing')
            for span in contexts:verify_span(span,text,packet['case_id'],packet['source_hash'])
        if not isinstance(trace,dict) or set(trace)!={"task_id","target_id","source_hash","target_span_checksum","region_id","region_fingerprint","decision_checksum"}:raise AnnotationError("per-target Terra review trace required",code="missing_review_trace")
        if trace["task_id"]!=task["task_id"] or trace["target_id"]!=task["target_id"] or trace["source_hash"]!=packet["source_hash"] or trace["target_span_checksum"]!=hashlib.sha256(text[task["target_span"]["start_char"]:task["target_span"]["end_char"]].encode()).hexdigest():raise AnnotationError("review trace target/source checksum mismatch",code="missing_review_trace")
        if not any(x["region_id"]==trace["region_id"] and x["region_fingerprint"]==trace["region_fingerprint"] for x in task["region_refs"]):raise AnnotationError("review trace region ref mismatch",code="missing_review_trace")
        expected_decision=canonical_hash({"target_id":review["target_id"],"model_outcome":review.get("model_outcome"),"authority_units":review.get("authority_units",[]),"hard_negative":review.get("hard_negative"),"unresolved_reasons":review.get("unresolved_reasons",[])})
        if trace["decision_checksum"]!=expected_decision or review.get("review_complete") is not True:raise AnnotationError("review trace decision/checkpoint invalid",code="missing_review_trace")
        outcome=review.pop("model_outcome",None);reasons=review.pop("unresolved_reasons",[])
        if outcome not in {"positive","hard_negative","unresolved"}:raise AnnotationError("model_outcome required",code="model_uncertainty_missing")
        if outcome=='positive' and (not review.get('authority_units') or review.get('hard_negative') is not None):raise AnnotationError('positive requires AU and no negative',code='model_outcome_mismatch')
        if outcome=='hard_negative' and (review.get('authority_units') or review.get('hard_negative') is None):raise AnnotationError('negative requires negative and no AU',code='model_outcome_mismatch')
        if outcome=="unresolved":
            unresolved_count+=1
            if not reasons or review.get("authority_units") or review.get("hard_negative") is not None:raise AnnotationError("unresolved model outcome must be explicit and label-free",code="model_uncertainty_missing")
            reviewed=review.get("reviewed_span")
            review["review_complete"]=True;review["hard_negative"]={"reason":"insufficient_context","reviewed_span":reviewed,"provenance":{"source_type":"model","producer_id":"model:"+model,"prompt_version":prompt},"notes":["synthetic structural adapter only; original outcome remains unresolved"]}
        if review.get("hard_negative") is not None:
            source=review["hard_negative"].get("provenance",{})
            if source.get("source_type")!="model" or source.get("producer_id")!="model:"+model or (generic and source.get('prompt_version')!=prompt):raise AnnotationError("model hard-negative provenance required",code="forbidden_provenance")
            review["hard_negative"]["provenance"]={"source_type":"human","annotator_id":"MODEL_STRUCTURAL_VALIDATOR","guideline_version":packet["guideline_version"],"derived_from":[]}
        for au in review.get("authority_units",[]):
            if au.get("status")!="model_proposed" or au.get("provenance")!={"source_type":"model","producer_id":"model:"+model,"prompt_version":prompt}:raise AnnotationError("AU must remain explicit model proposal",code="forbidden_provenance")
            if "uncertainty" not in au or "unresolved_reasons" not in au:raise AnnotationError("model proposal must expose uncertainty/unresolved",code="model_uncertainty_missing")
            au.pop("uncertainty");au.pop("unresolved_reasons");au["status"]="independently_annotated";au["provenance"]={"source_type":"human","annotator_id":"MODEL_STRUCTURAL_VALIDATOR","guideline_version":packet["guideline_version"],"derived_from":[]}
    result=validate_submission(pseudo,packet,text,policy);result['hard_negative_count']=sum(x.get('hard_negative') is not None for x in proposal['target_reviews']);return {**result,"status":"model_proposed","unresolved_target_count":unresolved_count,"semantic_gold":False}

def model_review_trace(task,text,source_hash,review):
    region=next((x for x in task["region_refs"] if x["arm"]=="P2a"),task["region_refs"][0])
    span=task["target_span"]
    return {"task_id":task["task_id"],"target_id":task["target_id"],"source_hash":source_hash,"target_span_checksum":hashlib.sha256(text[span["start_char"]:span["end_char"]].encode()).hexdigest(),"region_id":region["region_id"],"region_fingerprint":region["region_fingerprint"],"decision_checksum":canonical_hash({"target_id":review["target_id"],"model_outcome":review.get("model_outcome"),"authority_units":review.get("authority_units",[]),"hard_negative":review.get("hard_negative"),"unresolved_reasons":review.get("unresolved_reasons",[])})}

def create_terra_unresolved_proposal(packet,text,policy):
    raise AnnotationError("blanket unresolved proposals are forbidden; emit only traced per-target decisions from an executed batch checkpoint",code="blanket_abstention_forbidden")

def lock_silver(packets,proposals,policy,source_text_by_case=None,semantic_registry=None):
    from .remediation import registry, assert_lockable
    assert_lockable(registry() if semantic_registry is None else semantic_registry)
    if any(p.get('artifact_type')=='ModelAUProposal' for p in proposals):
        raise AnnotationError('R4 proposals require independent audit and a mixed-model lock contract; no Terra lock',code='mixed_model_silver_lock_unsupported')
    if source_text_by_case is None:raise AnnotationError("silver lock requires exact source validation",code="source_validation_required")
    by_packet={}
    for proposal in proposals:
        if proposal['packet_id'] not in by_packet:by_packet[proposal['packet_id']]=copy.deepcopy(proposal)
        else:by_packet[proposal['packet_id']]['target_reviews'].extend(copy.deepcopy(proposal['target_reviews']))
    if set(by_packet)!={x["packet_id"] for x in packets}:raise AnnotationError("silver lock requires one validated proposal per packet",code="incomplete_silver")
    units=[];negatives=[];unresolved=[]
    for packet in packets:
        proposal=by_packet[packet["packet_id"]]
        text=source_text_by_case.get(packet["case_id"])
        if text is None:raise AnnotationError("silver source text unavailable",code="source_validation_required")
        validate_model_proposal(proposal,packet,text,policy)
        if {x['target_id'] for x in proposal['target_reviews']} != {x['target_id'] for x in packet['tasks']}:raise AnnotationError('silver lock requires complete target coverage',code='incomplete_silver')
        for review in proposal["target_reviews"]:
            if review.get("model_outcome")=="unresolved":unresolved.append({"target_id":review["target_id"],"uncertainty":"high","reasons":review.get("unresolved_reasons",[])})
            if review.get("hard_negative") is not None:negatives.append(review["hard_negative"])
            for au in review.get("authority_units",[]):
                item=copy.deepcopy(au);item["status"]="model_adjudicated_silver";units.append(item)
                if item.get("uncertainty") or item.get("unresolved_reasons"):unresolved.append({"au_id":item["au_id"],"uncertainty":item.get("uncertainty"),"reasons":item.get("unresolved_reasons",[])})
    deps={"source_snapshot_digest":canonical_hash(sorted((p["case_id"],p["source_hash"]) for p in packets)),"packet_digest":canonical_hash(packets),"proposal_digest":canonical_hash(proposals)}
    value={"artifact_type":"LockedAUSilverSnapshot","schema_version":policy["silver_schema_version"],"snapshot_id":"silver-"+canonical_hash(deps)[:24],"status":"model_adjudicated_silver","evaluation_against":"model_silver","split":"calibration","producer":{"source_type":"model","producer_id":"model:gpt-5.6-terra","model":"gpt-5.6-terra","reasoning_effort":"low"},**deps,"prompt_version":policy["terra_prompt_version"],"authority_units":units,"hard_negatives":negatives,"unresolved":unresolved,"limitations":["Model silver is not independent human gold.","Model silver cannot unlock held-out quality claims.","Any downstream score must declare evaluation_against=model_silver."]};value["lock_digest"]=canonical_hash(value);validate_schema(value,"locked_au_silver.v1.json");return value

def validate_locked_silver(value):
    validate_schema(value,"locked_au_silver.v1.json");copy_value=copy.deepcopy(value);digest=copy_value.pop("lock_digest")
    if canonical_hash(copy_value)!=digest:raise AnnotationError("locked silver digest mismatch",code="digest_tamper")
    if value["evaluation_against"]!="model_silver" or value["producer"].get("source_type")!="model":raise AnnotationError("silver provenance/evaluation boundary violated",code="forbidden_provenance")
    return True
