"""Build, validate, cache, and audit offline P2 AnalysisRegion workloads."""
from __future__ import annotations
import hashlib, html, json, time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from ..context_hints import load_and_validate_context_hint_map
from ..sentence_atoms import load_and_validate_sentence_atom_map
from ..sentence_atoms.segmenter import canonical_hash
from ..sidecars import load_and_validate_sidecar_map
from ..source_contract import open_source
from ..structural_prepass import load_and_validate_block_map
from .renderer import render_metrics, render_region
from .scheduler import build_case_workload

EXPECTED_CASES={"013009","013948","011904","045155","099980"}

class AnalysisRegionError(ValueError):
    def __init__(self,detail: str,*,code="analysis_region_contract",location="<root>"):
        self.code,self.location,self.detail=code,location,detail;super().__init__(f"[{code}] {location}: {detail}")

def _load(path: Path):
    try:value=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:raise AnalysisRegionError(str(exc),code="malformed_artifact",location=str(path)) from exc
    if not isinstance(value,dict):raise AnalysisRegionError("JSON object required",code="malformed_artifact",location=str(path))
    return value

@lru_cache(maxsize=1)
def _validator():
    schema=_load(Path(__file__).resolve().parents[1]/"contracts/analysis_region.v1.json");Draft202012Validator.check_schema(schema);return Draft202012Validator(schema)

def _write(path: Path,value,immutable=False):
    data=(json.dumps(value,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    if path.exists() and immutable:
        if path.read_bytes()!=data:raise AnalysisRegionError("refusing to overwrite dependency-addressed artifact",code="immutable_conflict",location=str(path))
        return "reused"
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp");tmp.write_bytes(data);tmp.replace(path);return "created"

def _union_len(refs):
    merged=[]
    for cid,a,b in sorted(set((r["case_id"],r["start_char"],r["end_char"]) for r in refs)):
        if not merged or cid!=merged[-1][0] or a>merged[-1][2]:merged.append([cid,a,b])
        else:merged[-1][2]=max(merged[-1][2],b)
    return sum(b-a for _,a,b in merged)

def validate_analysis_workload(value,text,blocks,atoms,sidecars,hints,policy,*,artifact_path=None):
    try:_validator().validate(value)
    except ValidationError as exc:raise AnalysisRegionError(exc.message,code="schema_violation",location=".".join(map(str,exc.absolute_path)) or "<root>") from exc
    if hashlib.sha256(text.encode()).hexdigest()!=value["source_hash"]:raise AnalysisRegionError("source hash mismatch",code="source_hash_mismatch",location="source_hash")
    def keys(node):
        if isinstance(node,dict):return set(node)|set().union(*(keys(x) for x in node.values()),set())
        if isinstance(node,list):return set().union(*(keys(x) for x in node),set())
        return set()
    if {"text","source_text","rendered_text","target_text","context_text"}&keys(value):raise AnalysisRegionError("canonical workload must not materialize source text",code="materialized_text_forbidden",location="<root>")
    identity=(blocks["case_id"],blocks["source_hash"],blocks["cache_key"],atoms["cache_key"],sidecars["cache_key"],hints["cache_key"],canonical_hash(policy))
    own=(value["case_id"],value["source_hash"],value["dependencies"]["sourceblock_cache_key"],value["dependencies"]["sentence_atom_cache_key"],value["dependencies"]["sidecar_cache_key"],value["dependencies"]["context_hint_cache_key"],value["policy_sha256"])
    if identity!=own:raise AnalysisRegionError("parent dependency identity mismatch",code="dependency_mismatch",location="dependencies")
    parent_blocks={b["block_id"]:b for b in blocks["blocks"]}
    for hint in hints["hints"]:
        target=parent_blocks.get(hint["target_block_id"])
        if target is None or hint["target_span"]!=target["span"] or len(hint["related_block_ids"])!=len(hint["related_spans"]):raise AnalysisRegionError("invalid ContextHint target/ref contract",code="hint_reference_violation",location=hint["hint_id"])
        for bid,ref in zip(hint["related_block_ids"],hint["related_spans"]):
            if bid not in parent_blocks or ref!=parent_blocks[bid]["span"]:raise AnalysisRegionError("invalid ContextHint related ref",code="hint_reference_violation",location=hint["hint_id"])
    expected=build_case_workload(text,blocks,atoms,sidecars,hints,policy,value["policy_sha256"])
    if value!=expected:
        field=next((k for k in expected if value.get(k)!=expected[k]),"<root>");raise AnalysisRegionError("artifact differs from deterministic scheduler",code="canonical_mismatch",location=field)
    disposition_ids=[x["hint_id"] for x in value["hint_dispositions"]];hint_ids=[x["hint_id"] for x in hints["hints"]]
    if len(disposition_ids)!=len(set(disposition_ids)) or set(disposition_ids)!=set(hint_ids):raise AnalysisRegionError("ContextHint disposition ledger must reconcile every hint exactly once",code="hint_reconciliation",location="hint_dispositions")
    if artifact_path is not None:
        dep=f"{value['scheduler_version']}-{value['policy_sha256'][:16]}";suffix=(value["case_id"],value["source_hash"],value["dependencies"]["sourceblock_cache_key"],value["dependencies"]["sentence_atom_cache_key"],value["dependencies"]["sidecar_cache_key"],value["dependencies"]["context_hint_cache_key"],dep,"analysis_workload_map.json")
        if tuple(Path(artifact_path).parts[-8:])!=suffix:raise AnalysisRegionError("artifact path/dependency mismatch",code="identity_mismatch",location="artifact_path")
    eligible={r["block_id"] for r in value["block_roles"] if r["eligible"]};targets=value["targets"]
    if len(targets)!=len(eligible) or {t["parent_block_id"] for t in targets}!=eligible:raise AnalysisRegionError("eligible content block target coverage mismatch",code="target_coverage",location="targets")
    slice_by={s["slice_id"]:s for s in value["slices"]}
    for target in targets:
        if target["mode"]=="sliced":
            cursor=target["content_span"]["start_char"]
            for order,sid in enumerate(target["slice_ids"]):
                s=slice_by[sid]
                if s["slice_order"]!=order or s["span"]["start_char"]!=cursor:raise AnalysisRegionError("slice gap/overlap/order",code="slice_coverage",location=sid)
                cursor=s["span"]["end_char"]
            if cursor!=target["content_span"]["end_char"]:raise AnalysisRegionError("slices do not cover content span",code="slice_coverage",location=target["target_id"])
    expected_work={s["slice_id"] for s in value["slices"]}|{t["target_id"] for t in targets if t["mode"]=="block"}
    actual_work=[w["work_item_id"] for b in value["batches"] for w in b["work_items"]]
    if set(actual_work)!=expected_work or len(actual_work)!=len(set(actual_work)):raise AnalysisRegionError("duplicate/missing workload target",code="target_coverage",location="batches")
    expected_target_ids={t["target_id"] for t in targets}; batch_target_ids=[target_id for b in value["batches"] for target_id in {w["target_id"] for w in b["work_items"]}]
    if set(batch_target_ids)!=expected_target_ids or len(batch_target_ids)!=len(set(batch_target_ids)):raise AnalysisRegionError("AnalysisTarget must appear in exactly one batch",code="target_coverage",location="batches.target_id")
    if len(value["batches"])>policy["batch"]["max_requests_per_case"]:raise AnalysisRegionError("request cap exceeded",code="cap_violation",location="batches")
    for batch in value["batches"]:
        over=len(batch["work_items"])>policy["batch"]["max_target_items"] or batch["target_chars"]>policy["batch"]["max_target_chars"]
        if over and not batch["stop_reasons"]:raise AnalysisRegionError("batch cap violation lacks stop reason",code="cap_violation",location=batch["batch_id"])
    region_by_arm={arm:[r for r in value["regions"] if r["arm"]==arm] for arm in policy["arms"]}
    for arm,regions in region_by_arm.items():
        covered=[key.removeprefix("target:") for r in regions for key in r["render_order"] if key.startswith("target:")]
        if set(covered)!=expected_work or len(covered)!=len(set(covered)):raise AnalysisRegionError("arm target coverage mismatch",code="target_coverage",location=arm)
        covered_targets=[target_id for r in regions for target_id in r["target_ids"]]
        if set(covered_targets)!=expected_target_ids or len(covered_targets)!=len(set(covered_targets)):raise AnalysisRegionError("AnalysisTarget must appear in exactly one region per arm",code="target_coverage",location=f"{arm}.target_id")
        for region in regions:
            target_refs=region["primary_spans"]
            for context in region["context_refs"]:
                ref=context["span"]
                if any(ref["start_char"]<t["end_char"] and ref["end_char"]>t["start_char"] for t in target_refs):raise AnalysisRegionError("context overlaps primary target",code="context_target_overlap",location=region["region_id"])
                for rid in context["source_relation_ids"]:
                    relation=next((x for x in sidecars["relations"] if x["relation_id"]==rid),None)
                    if relation is None or relation["status"] not in policy["region"]["allowed_structural_relation_statuses"]:raise AnalysisRegionError("unaccepted structural relation used as context",code="relation_status_violation",location=rid)
                for hid in context["source_hint_ids"]:
                    hint=next((x for x in hints["hints"] if x["hint_id"]==hid),None)
                    if hint is None or hint["target_block_id"] not in region["target_block_ids"] or hint["status"] not in policy["region"]["allowed_hint_statuses"]:raise AnalysisRegionError("missing or ineligible ContextHint reference",code="hint_reference_violation",location=hid)
            if region["arm"]=="P2a" and region["included_hint_ids"]:raise AnalysisRegionError("P2a cannot carry ContextHint payload identifiers",code="hint_reference_violation",location=region["region_id"])
            for hid in region["included_hint_ids"]:
                hint=next((x for x in hints["hints"] if x["hint_id"]==hid),None)
                if hint is None or region["arm"]!="P2b" or hint["target_block_id"] not in region["target_block_ids"] or hint["status"] not in policy["region"]["allowed_hint_statuses"]:raise AnalysisRegionError("missing or ineligible ContextHint payload identifier",code="hint_reference_violation",location=hid)
            measured=render_metrics(text,region,policy["token_estimator"]["chars_per_token"])
            if measured["rendered_chars"]!=region["metrics"]["rendered_chars"] or measured["estimated_input_tokens"]!=region["metrics"]["estimated_input_tokens"]:raise AnalysisRegionError("stored render metrics drift",code="metric_mismatch",location=region["region_id"])
            fp=canonical_hash({k:v for k,v in region.items() if k!="fingerprint"})
            if fp!=region["fingerprint"]:raise AnalysisRegionError("region fingerprint mismatch",code="fingerprint_mismatch",location=region["region_id"])
            over=region["metrics"]["unique_source_chars"]>region["caps"]["max_unique_source_chars"] or region["metrics"]["estimated_input_tokens"]>region["caps"]["max_input_tokens"]
            if over and not region["stop_reasons"]:raise AnalysisRegionError("cap violation lacks stop reason",code="cap_violation",location=region["region_id"])
            context_chars=sum(x["span"]["end_char"]-x["span"]["start_char"] for x in region["context_refs"])
            if len(region["context_refs"])>policy["region"]["max_context_spans"] or context_chars>policy["region"]["max_context_chars"]:raise AnalysisRegionError("selected context exceeds cap",code="cap_violation",location=region["region_id"])
    return {"schema_valid":True,"dependency_identity_valid":True,"content_target_coverage_100pct":True,"slice_coverage_exact":True,"arm_target_coverage_100pct":True,"fixed_cap_arm_selection_auditable":True,"hint_dispositions_reconciled":True,"context_not_target":True,"render_metrics_recomputed":True,"fingerprints_recomputed":True,"caps_or_stop_reason":True}

def load_and_validate_analysis_workload(path,text,blocks,atoms,sidecars,hints,policy):
    value=_load(Path(path));return value,validate_analysis_workload(value,text,blocks,atoms,sidecars,hints,policy,artifact_path=path)

def _arm_metrics(regions):
    refs=[x["span"] for r in regions for x in r["render_items"]];proposed=sum(x["end_char"]-x["start_char"] for x in refs);unique=_union_len(refs)
    return {"region_count":len(regions),"unique_source_chars":unique,"proposed_source_chars":proposed,"repeated_source_chars":proposed-unique,"rendered_chars":sum(r["metrics"]["rendered_chars"] for r in regions),"estimated_input_tokens":sum(r["metrics"]["estimated_input_tokens"] for r in regions),"overlap_ratio":round((proposed-unique)/proposed,8) if proposed else 0.0,"regions_with_stop_reason":sum(bool(r["stop_reasons"]) for r in regions),"stop_reason_counts":dict(sorted(Counter(x for r in regions for x in r["stop_reasons"]).items())),"context_drop_reason_counts":dict(sorted(Counter(x["reason"] for r in regions for x in r["context_events"] if x["action"]=="dropped").items())),"context_spans":sum(len(r["context_refs"]) for r in regions),"included_hints":len({h for r in regions for h in r["included_hint_ids"]}),"max_region_unique_chars":max((r["metrics"]["unique_source_chars"] for r in regions),default=0),"max_region_estimated_input_tokens":max((r["metrics"]["estimated_input_tokens"] for r in regions),default=0),"regions_at_or_above_80pct_char_cap":sum(r["metrics"]["unique_source_chars"]>=0.8*r["caps"]["max_unique_source_chars"] for r in regions),"regions_at_or_above_80pct_token_cap":sum(r["metrics"]["estimated_input_tokens"]>=0.8*r["caps"]["max_input_tokens"] for r in regions)}

def _arm_context_comparison(regions):
    by={arm:{r["batch_id"]:r for r in regions if r["arm"]==arm} for arm in ("P2a","P2b")};retained=dropped=added=retained_chars=dropped_chars=added_chars=0
    for batch,a in by["P2a"].items():
        b=by["P2b"][batch];aa={(x["span"]["start_char"],x["span"]["end_char"]) for x in a["context_refs"]};bb={(x["span"]["start_char"],x["span"]["end_char"]) for x in b["context_refs"]};same=aa&bb;lost=aa-bb;new=bb-aa
        retained+=len(same);dropped+=len(lost);added+=len(new);retained_chars+=sum(y-x for x,y in same);dropped_chars+=sum(y-x for x,y in lost);added_chars+=sum(y-x for x,y in new)
    return {"selection_contract":"P2a and P2b share identical base source contexts; P2b ContextHints are a separate payload and cannot add, remove, or substitute source spans","retained_p2a_context_spans":retained,"retained_p2a_context_chars":retained_chars,"displaced_p2a_context_spans":dropped,"displaced_p2a_context_chars":dropped_chars,"new_p2b_context_spans":added,"new_p2b_context_chars":added_chars}

def _case_row(value,ref,action,checks):
    arms={arm:_arm_metrics([r for r in value["regions"] if r["arm"]==arm]) for arm in ("P2a","P2b")}
    return {"case_id":value["case_id"],"source_hash":value["source_hash"],"artifact_ref":ref,"artifact_action":action,"block_count":len(value["block_roles"]),"content_block_count":sum(r["eligible"] for r in value["block_roles"]),"empty_content_structural_only_count":sum((not r["eligible"]) and r["content_span"]["start_char"]==r["content_span"]["end_char"] for r in value["block_roles"]),"excluded_role_counts":dict(sorted(Counter(r["role"] for r in value["block_roles"] if not r["eligible"]).items())),"primary_target_count":len(value["targets"]),"slice_count":len(value["slices"]),"work_item_count":sum(len(b["work_items"]) for b in value["batches"]),"batch_count":len(value["batches"]),"oversized_atom_count":sum(s["oversized_atom"] for s in value["slices"]),"batch_stop_reason_counts":dict(sorted(Counter(x for b in value["batches"] for x in b["stop_reasons"]).items())),"hint_disposition_count":len(value["hint_dispositions"]),"hint_target_eligibility_counts":dict(sorted(Counter(x["target_eligibility"] for x in value["hint_dispositions"]).items())),"hint_disposition_counts":dict(sorted(Counter(x["disposition"] for x in value["hint_dispositions"]).items())),"arm_metrics":arms,"p2_context_comparison":_arm_context_comparison(value["regions"]),"checks":checks}

def _safe(output,ref):
    if not isinstance(ref,str):raise AnalysisRegionError("artifact_ref must be a string",code="manifest_schema_violation",location="artifact_ref")
    p=Path(ref)
    if p.is_absolute() or "\\" in ref or any(x in {"",".",".."} for x in p.parts):raise AnalysisRegionError("unsafe artifact_ref",code="unsafe_artifact_ref",location=ref)
    resolved=(output/p).resolve()
    try:resolved.relative_to(output.resolve())
    except ValueError as exc:raise AnalysisRegionError("artifact_ref escapes output",code="unsafe_artifact_ref",location=ref) from exc
    if not resolved.is_file():raise AnalysisRegionError("missing workload artifact",code="missing_artifact",location=ref)
    return resolved

def _parents(cid,reports,policies,store):
    r3,r4,r5,r6=reports;sbp,sap,scp,chp,arp=policies;c3={x["case_id"]:x for x in r3["cases"]}[cid];c4={x["case_id"]:x for x in r4["cases"]}[cid];c5={x["case_id"]:x for x in r5["cases"]}[cid];c6={x["case_id"]:x for x in r6["cases"]}[cid];sh=c6["source_hash"];text=open_source(store,cid,sh)
    bp=Path(r3["outputs"]["output_root"])/c3["artifact_ref"];blocks,_=load_and_validate_block_map(bp,text,store)
    ap=Path(r4["outputs"]["output_root"])/c4["artifact_ref"];atoms,_=load_and_validate_sentence_atom_map(ap,text,blocks,sap)
    sp=Path(r5["outputs"]["output_root"])/c5["artifact_ref"];sidecars,_=load_and_validate_sidecar_map(sp,text,blocks,atoms,scp,sap)
    hp=Path(r6["outputs"]["output_root"])/c6["artifact_ref"];hints,_=load_and_validate_context_hint_map(hp,text,blocks,atoms,sidecars,chp)
    return sh,text,blocks,atoms,sidecars,hints

def load_and_validate_region_build(*,manifest_path,source_store,plan03_report,plan04_report,plan05_report,plan06_report,sourceblock_policy,sentence_policy,sidecar_policy,context_hint_policy,region_policy):
    path=Path(manifest_path).resolve();output=path.parent;manifest=_load(path);policy=_load(Path(region_policy));ph=canonical_hash(policy)
    required={"build_manifest_version","status","workload","scheduler_version","policy_sha256","summary","cases"}
    if set(manifest)!=required or manifest.get("build_manifest_version")!="analysis-region-build-v1" or manifest.get("status")!="pass" or manifest.get("workload")!="KOS-5" or manifest.get("scheduler_version")!=policy["scheduler_version"] or manifest.get("policy_sha256")!=ph:raise AnalysisRegionError("invalid build manifest envelope",code="manifest_schema_violation",location="manifest")
    rows=manifest["cases"]
    if not isinstance(rows,list) or len(rows)!=5 or {r.get("case_id") for r in rows}!=EXPECTED_CASES:raise AnalysisRegionError("manifest must contain exact KOS-5",code="manifest_completeness",location="cases")
    required_row={"case_id","source_hash","artifact_ref","artifact_action","block_count","content_block_count","empty_content_structural_only_count","excluded_role_counts","primary_target_count","slice_count","work_item_count","batch_count","oversized_atom_count","batch_stop_reason_counts","hint_disposition_count","hint_target_eligibility_counts","hint_disposition_counts","arm_metrics","p2_context_comparison","checks"}
    for index,row in enumerate(rows):
        if not isinstance(row,dict) or set(row)!=required_row or row.get("artifact_action") not in {"created","reused"}:raise AnalysisRegionError("invalid case row shape",code="manifest_schema_violation",location=f"cases.{index}")
    reports=[_load(Path(x)) for x in (plan03_report,plan04_report,plan05_report,plan06_report)];policies=[_load(Path(x)) for x in (sourceblock_policy,sentence_policy,sidecar_policy,context_hint_policy,region_policy)];store=Path(source_store).resolve();maps=[]
    for row in rows:
        artifact=_safe(output,row["artifact_ref"]);sh,text,blocks,atoms,sidecars,hints=_parents(row["case_id"],reports,policies,store)
        if row.get("source_hash")!=sh:raise AnalysisRegionError("manifest source identity mismatch",code="dependency_mismatch",location=row["case_id"])
        value,checks=load_and_validate_analysis_workload(artifact,text,blocks,atoms,sidecars,hints,policy);expected=_case_row(value,row["artifact_ref"],row["artifact_action"],checks)
        if row!=expected:
            field=next((k for k in expected if row.get(k)!=expected[k]),"<root>");raise AnalysisRegionError("stored case summary drift",code="manifest_metric_mismatch",location=f"{row['case_id']}.{field}")
        maps.append(value)
    summary=_global_summary(maps)
    if manifest["summary"]!=summary:raise AnalysisRegionError("stored global summary drift",code="manifest_metric_mismatch",location="summary")
    current=set()
    for p in output.glob("cases/**/analysis_workload_map.json"):
        try:v=_load(p)
        except AnalysisRegionError:continue
        if v.get("policy_sha256")==ph and v.get("scheduler_version")==policy["scheduler_version"]:current.add(p.resolve())
    refs={_safe(output,r["artifact_ref"]) for r in rows}
    if current!=refs:raise AnalysisRegionError("current artifact namespace mismatch",code="manifest_completeness",location="artifact_ref")
    return manifest,{"safe_refs":True,"five_current_artifacts":True,"artifacts_recomputed":True,"coverage_recomputed":True,"metrics_recomputed":True,"fingerprints_recomputed":True,"summary":summary}

def _global_summary(maps):
    rows=[]
    for v in maps:rows.append(_case_row(v,"x","reused",{}))
    arm={name:_arm_metrics([r for v in maps for r in v["regions"] if r["arm"]==name]) for name in ("P2a","P2b")}
    return {"case_count":len(maps),"block_count":sum(len(v["block_roles"]) for v in maps),"content_block_count":sum(sum(x["eligible"] for x in v["block_roles"]) for v in maps),"empty_content_structural_only_count":sum(sum((not x["eligible"]) and x["content_span"]["start_char"]==x["content_span"]["end_char"] for x in v["block_roles"]) for v in maps),"primary_target_count":sum(len(v["targets"]) for v in maps),"slice_count":sum(len(v["slices"]) for v in maps),"work_item_count":sum(sum(len(b["work_items"]) for b in v["batches"]) for v in maps),"batch_count":sum(len(v["batches"]) for v in maps),"oversized_atom_count":sum(sum(s["oversized_atom"] for s in v["slices"]) for v in maps),"excluded_role_counts":dict(sorted(Counter(x["role"] for v in maps for x in v["block_roles"] if not x["eligible"]).items())),"hint_disposition_count":sum(len(v["hint_dispositions"]) for v in maps),"hint_target_eligibility_counts":dict(sorted(Counter(x["target_eligibility"] for v in maps for x in v["hint_dispositions"]).items())),"hint_disposition_counts":dict(sorted(Counter(x["disposition"] for v in maps for x in v["hint_dispositions"]).items())),"arm_metrics":arm,"p2_context_comparison":_arm_context_comparison([r for v in maps for r in v["regions"]])}

def build_analysis_regions(*,source_store,source_manifest,plan03_report,plan04_report,plan05_report,plan06_report,plan06_independent_report,sourceblock_policy,sentence_policy,sidecar_policy,context_hint_policy,region_policy,output_root,audit_path=None):
    started=time.perf_counter();output=Path(output_root).resolve();store=Path(source_store).resolve();manifest_source=_load(Path(source_manifest));reports=[_load(Path(x)) for x in (plan03_report,plan04_report,plan05_report,plan06_report)];policies=[_load(Path(x)) for x in (sourceblock_policy,sentence_policy,sidecar_policy,context_hint_policy,region_policy)];policy=policies[-1];ph=canonical_hash(policy)
    if "**PASS" not in Path(plan06_independent_report).read_text(encoding="utf-8"):raise AnalysisRegionError("Plan 06 independent gate must PASS",code="dependency_gate")
    locked={x["case_id"]:x["sha256"] for x in manifest_source.get("cases",[])}
    if set(locked)!=EXPECTED_CASES:raise AnalysisRegionError("source manifest is not exact KOS-5",code="dependency_gate")
    old=output/"analysis_region_build_manifest.json"
    if old.exists():
        try:existing=_load(old)
        except AnalysisRegionError as exc:raise AnalysisRegionError("current cache manifest is malformed; refusing reuse",code="cache_validation_failed",location=str(old)) from exc
        if existing.get("policy_sha256")==ph and existing.get("scheduler_version")==policy["scheduler_version"]:
            try:load_and_validate_region_build(manifest_path=old,source_store=store,plan03_report=plan03_report,plan04_report=plan04_report,plan05_report=plan05_report,plan06_report=plan06_report,sourceblock_policy=sourceblock_policy,sentence_policy=sentence_policy,sidecar_policy=sidecar_policy,context_hint_policy=context_hint_policy,region_policy=region_policy)
            except AnalysisRegionError as exc:raise AnalysisRegionError("current cache failed validation; refusing reuse",code="cache_validation_failed",location=str(old)) from exc
    rows=[];maps=[]
    for cid in [x["case_id"] for x in manifest_source["cases"]]:
        sh,text,blocks,atoms,sidecars,hints=_parents(cid,reports,policies,store)
        if locked[cid]!=sh:raise AnalysisRegionError("source hash differs from calibration manifest",code="dependency_gate",location=cid)
        value=build_case_workload(text,blocks,atoms,sidecars,hints,policy,ph);dep=f"{policy['scheduler_version']}-{ph[:16]}";artifact=output/"cases"/cid/sh/blocks["cache_key"]/atoms["cache_key"]/sidecars["cache_key"]/hints["cache_key"]/dep/"analysis_workload_map.json"
        checks=validate_analysis_workload(value,text,blocks,atoms,sidecars,hints,policy,artifact_path=artifact);action=_write(artifact,value,True);ref=artifact.relative_to(output).as_posix();rows.append(_case_row(value,ref,action,checks));maps.append(value)
    manifest={"build_manifest_version":"analysis-region-build-v1","status":"pass","workload":"KOS-5","scheduler_version":policy["scheduler_version"],"policy_sha256":ph,"summary":_global_summary(maps),"cases":rows};manifest_path=output/"analysis_region_build_manifest.json";_write(manifest_path,manifest)
    _,read_checks=load_and_validate_region_build(manifest_path=manifest_path,source_store=store,plan03_report=plan03_report,plan04_report=plan04_report,plan05_report=plan05_report,plan06_report=plan06_report,sourceblock_policy=sourceblock_policy,sentence_policy=sentence_policy,sidecar_policy=sidecar_policy,context_hint_policy=context_hint_policy,region_policy=region_policy)
    if audit_path:
        p=Path(audit_path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text("<!doctype html><meta charset='utf-8'><title>Plan 07 region audit</title><h1>Plan 07 offline P2 audit</h1><p>No region source text is persisted. Caps are pilot assumptions, not optimized values.</p><pre>"+html.escape(json.dumps(manifest,ensure_ascii=False,indent=2))+"</pre>",encoding="utf-8")
    elapsed=max(time.perf_counter()-started,1e-9);summary=manifest["summary"];all_artifacts=list(output.glob("cases/**/analysis_workload_map.json"))
    return {"report_version":"plan07-analysis-region-validation-v1","status":"pass","scope":"offline KOS-5 P2a/P2b workload only; no model/LLM; KOS artifacts audit-only","inputs":{"source_store":str(store),"source_manifest":str(Path(source_manifest).resolve()),"plan03_report":str(Path(plan03_report).resolve()),"plan04_report":str(Path(plan04_report).resolve()),"plan05_report":str(Path(plan05_report).resolve()),"plan06_report":str(Path(plan06_report).resolve()),"plan06_independent_report":str(Path(plan06_independent_report).resolve()),"policy":str(Path(region_policy).resolve())},"outputs":{"output_root":str(output),"build_manifest":str(manifest_path.resolve()),"audit_html":str(Path(audit_path).resolve()) if audit_path else None},"summary":{**summary,"elapsed_seconds":elapsed,"characters_per_second":sum(len(open_source(store,r["case_id"],r["source_hash"])) for r in rows)/elapsed},"immutable_history":{"total_workload_artifacts":len(all_artifacts),"current_artifacts":5,"historical_artifacts_preserved":len(all_artifacts)-5},"stored_build_validation":read_checks,"gates":{"plan06_independent_pass":True,"exact_kos5_hashes":True,"content_target_coverage_100pct":True,"slice_coverage_exact":True,"p2a_p2b_same_target_workload":True,"context_not_counted_as_target":True,"all_28_hints_reconciled_exactly_once":summary["hint_disposition_count"]==28,"caps_or_stop_reasons":True,"render_on_demand_no_canonical_text":True,"read_validation_recomputed":True,"dependency_addressed_cache":True},"cases":rows,"metrics_not_reported":["precision","recall","F1","token_saving","semantic_quality"],"limitations":[policy["pilot_assumption"],"Token counts use a character-based estimator, not provider tokenization.","P2a/P2b manifests measure context construction only and do not show that hints improve omission or semantic quality.","P0 and P1 are intentionally not implemented in Plan 07.","No ContextObligation, CoverageLedger, AU, Issue, NN, retrieval, model, or LLM is implemented."]}
