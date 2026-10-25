"""Deterministic offline P2 target, batching, and region construction."""
from __future__ import annotations
from collections import defaultdict
import copy
from typing import Any
from ..sentence_atoms.segmenter import canonical_hash, span
from .renderer import render_metrics


def _id(prefix: str, payload: Any) -> str: return f"{prefix}-{canonical_hash(payload)[:24]}"


def _slice_target(block, atoms, policy):
    ref=block["content_span"]; chunks=[]
    for atom in atoms:
        a=max(ref["start_char"],atom["span"]["start_char"]); b=min(ref["end_char"],atom["span"]["end_char"])
        if a<b: chunks.append((a,b,atom["atom_id"]))
    if not chunks and ref["start_char"]<ref["end_char"]: chunks=[(ref["start_char"],ref["end_char"],None)]
    maximum=policy["slice"]["max_chars"]
    groups=[]; current=[]; start=None
    for a,b,atom_id in chunks:
        if current and b-start>maximum:
            groups.append(current); current=[]; start=None
        if not current: start=a
        current.append((a,b,atom_id))
    if current: groups.append(current)
    output=[]
    for order,group in enumerate(groups):
        a,b=group[0][0],group[-1][1]; oversized=(b-a)>maximum and len(group)==1
        payload={"parent_block_id":block["block_id"],"span":[a,b],"slice_order":order,"policy_version":policy["policy_version"]}
        output.append({"record_type":"AnalysisTargetSlice","slice_id":_id("ats",payload),"parent_block_id":block["block_id"],"slice_order":order,"span":span(block["case_id"],block["source_hash"],a,b),"atom_ids":[x[2] for x in group if x[2]],"policy_version":policy["policy_version"],"oversized_atom":oversized,"stop_reasons":["oversized_atom_preserved"] if oversized else []})
    return output


def _union_len(refs):
    merged=[]
    for a,b in sorted(set((r["start_char"],r["end_char"]) for r in refs)):
        if not merged or a>merged[-1][1]: merged.append([a,b])
        else: merged[-1][1]=max(merged[-1][1],b)
    return sum(b-a for a,b in merged)


def _subtract(ref, targets, case_id, source_hash):
    parts=[(ref["start_char"],ref["end_char"])]
    for target in targets:
        next_parts=[]
        for a,b in parts:
            x,y=target["start_char"],target["end_char"]
            if y<=a or x>=b: next_parts.append((a,b)); continue
            if a<x: next_parts.append((a,x))
            if y<b: next_parts.append((y,b))
        parts=next_parts
    return [span(case_id,source_hash,a,b) for a,b in parts if a<b]


def _region(text, arm, batch, blocks, sidecars, hints, policy, deps):
    case_id,source_hash=blocks[0]["case_id"],blocks[0]["source_hash"]; by_id={b["block_id"]:b for b in blocks}; order={b["block_id"]:b["order"] for b in blocks}
    target_refs=[x["span"] for x in batch["work_items"]]; target_blocks=set(x["parent_block_id"] for x in batch["work_items"]); candidates=[]
    for rel in sidecars["relations"]:
        if rel["relation_type"] not in policy["region"]["allowed_structural_relation_types"] or rel["status"] not in policy["region"]["allowed_structural_relation_statuses"]: continue
        if rel["source_ref"] in target_blocks and rel["target_ref"] in by_id and rel["target_ref"] not in target_blocks:
            b=by_id[rel["target_ref"]]; candidates.append((0,b["content_span"],b["block_id"],"accepted_structural_relation",None,rel["relation_id"],rel["status"]))
    if arm=="P2b":
        for hint in hints["hints"]:
            if hint["target_block_id"] not in target_blocks or hint["status"] not in policy["region"]["allowed_hint_statuses"]: continue
            for bid,ref in zip(hint["related_block_ids"],hint["related_spans"]):
                normalized=by_id[bid]["content_span"] if bid in by_id else ref
                candidates.append((1,normalized,bid,"context_hint",hint["hint_id"],None,hint["status"]))
    n=policy["region"]["local_neighbor_blocks_each_side"]
    for bid in target_blocks:
        idx=order[bid]
        for j in range(max(0,idx-n),min(len(blocks),idx+n+1)):
            b=blocks[j]
            if b["block_id"] not in target_blocks: candidates.append((2,b["content_span"],b["block_id"],"local_neighbor",None,None,"derived"))
    grouped={}; events=[]
    for priority,ref,bid,reason,hid,rid,status in sorted(candidates,key=lambda x:(x[0],x[1]["start_char"],x[2],x[4] or "",x[5] or "")):
        parts=_subtract(ref,target_refs,case_id,source_hash)
        if not parts:
            events.append({"candidate_key":f"{bid}:{ref['start_char']}:{ref['end_char']}:{reason}","action":"dropped","reason":"overlaps_primary_target","source_hint_ids":[hid] if hid else []}); continue
        for part in parts:
            key=(part["start_char"],part["end_char"]); item=grouped.get(key)
            if item is None:
                item={"span":part,"block_ids":[],"reasons":[],"source_hint_ids":[],"source_relation_ids":[],"source_statuses":[],"priority":priority}; grouped[key]=item
            item["block_ids"].append(bid); item["reasons"].append(reason)
            if hid: item["source_hint_ids"].append(hid)
            if rid: item["source_relation_ids"].append(rid)
            item["source_statuses"].append(status); item["priority"]=min(item["priority"],priority)
    kept=[]; context_chars=0; stops=[]; caps=policy["region"]
    target_unique=_union_len(target_refs)
    for key,item in sorted(grouped.items(),key=lambda x:(x[1]["priority"],x[0][0],x[0][1])):
        item={**item,"block_ids":sorted(set(item["block_ids"])),"reasons":sorted(set(item["reasons"])),"source_hint_ids":sorted(set(item["source_hint_ids"])),"source_relation_ids":sorted(set(item["source_relation_ids"])),"source_statuses":sorted(set(item["source_statuses"]))}
        length=item["span"]["end_char"]-item["span"]["start_char"]
        reason=None
        if len(kept)>=caps["max_context_spans"]: reason="max_context_spans"
        elif context_chars+length>caps["max_context_chars"]: reason="max_context_chars"
        elif target_unique+context_chars+length>caps["max_unique_source_chars"]: reason="max_unique_source_chars"
        if reason:
            events.append({"candidate_key":f"{key[0]}:{key[1]}","action":"dropped","reason":reason,"source_hint_ids":item["source_hint_ids"]}); stops.append("context_cap_exhausted"); continue
        kept.append(item); context_chars+=length; events.append({"candidate_key":f"{key[0]}:{key[1]}","action":"kept","reason":"within_caps","source_hint_ids":item["source_hint_ids"]})
    target_items=[]
    for work in batch["work_items"]: target_items.append({"render_key":f"target:{work['work_item_id']}","role":"target","span":work["span"],"ref_ids":[work["work_item_id"]],"reasons":["primary_target"]})
    context_items=[]
    for item in kept: context_items.append({"render_key":f"context:{item['span']['start_char']}:{item['span']['end_char']}","role":"context","span":item["span"],"ref_ids":item["block_ids"],"reasons":item["reasons"]})
    render_items=sorted(target_items+context_items,key=lambda x:(x["span"]["start_char"],0 if x["role"]=="context" else 1,x["span"]["end_char"],x["render_key"]))
    source_refs=[x["span"] for x in render_items]; unique=_union_len(source_refs); proposed=sum(r["end_char"]-r["start_char"] for r in source_refs); repeated=proposed-unique
    payload={"arm":arm,"batch_id":batch["batch_id"],"targets":[x["work_item_id"] for x in batch["work_items"]],"context":[(x["span"]["start_char"],x["span"]["end_char"],x["reasons"]) for x in kept],"policy":policy["policy_version"],"dependencies":deps}
    region={"record_type":"AnalysisRegionManifest","region_id":_id("ar",payload),"case_id":case_id,"source_hash":source_hash,"arm":arm,"batch_id":batch["batch_id"],"target_ids":sorted(set(x["target_id"] for x in batch["work_items"])),"target_block_ids":sorted(target_blocks,key=lambda x:order[x]),"target_slice_refs":[x["slice_id"] for x in batch["work_items"] if x["slice_id"]],"primary_spans":target_refs,"context_refs":kept,"included_hint_ids":sorted(set(h for x in kept for h in x["source_hint_ids"])),"render_items":render_items,"render_order":[x["render_key"] for x in render_items],"metrics":{"unique_source_chars":unique,"proposed_source_chars":proposed,"repeated_source_chars":repeated,"rendered_chars":0,"overlap_ratio":round(repeated/proposed,8) if proposed else 0.0,"estimated_input_tokens":0},"caps":{"max_unique_source_chars":caps["max_unique_source_chars"],**policy["request_caps"]},"token_estimator":policy["token_estimator"],"context_events":events,"stop_reasons":sorted(set(batch["stop_reasons"]+stops)),"policy_version":policy["policy_version"],"dependencies":deps,"fingerprint":""}
    measured=render_metrics(text,region,policy["token_estimator"]["chars_per_token"]);region["metrics"].update(measured)
    if measured["estimated_input_tokens"]>policy["request_caps"]["max_input_tokens"]:
        region["stop_reasons"]=sorted(set(region["stop_reasons"]+["estimated_input_token_cap_exceeded_preserved"]))
    region["fingerprint"]=canonical_hash({k:v for k,v in region.items() if k!="fingerprint"})
    return region


def build_case_workload(text, sourceblocks, atoms, sidecars, hints, policy, policy_hash=None):
    policy_hash=policy_hash or canonical_hash(policy); case_id,source_hash=sourceblocks["case_id"],sourceblocks["source_hash"]
    eligible=set(policy["content_eligibility"]["eligible_block_types"]); excluded=policy["content_eligibility"]["excluded_roles"]; atoms_by=defaultdict(list)
    for atom in atoms["atoms"]: atoms_by[atom["parent_block_id"]].append(atom)
    roles=[];targets=[];slices=[];work=[]
    for block in sourceblocks["blocks"]:
        ok=block["block_type"] in eligible and block["content_span"]["start_char"]<block["content_span"]["end_char"]
        role="primary_target" if ok else excluded.get(block["block_type"],"structural_only_not_content")
        roles.append({"block_id":block["block_id"],"block_type":block["block_type"],"span":block["span"],"content_span":block["content_span"],"eligible":ok,"role":role,"reason":"eligible_content_block" if ok else role})
        if not ok: continue
        target_payload={"parent_block_id":block["block_id"],"content_span":block["content_span"],"policy_version":policy["policy_version"]}; target_id=_id("at",target_payload)
        block_slices=_slice_target(block,atoms_by[block["block_id"]],policy) if block["content_span"]["end_char"]-block["content_span"]["start_char"]>policy["slice"]["max_chars"] else []
        for item in block_slices: item["target_id"]=target_id
        targets.append({"record_type":"AnalysisTarget","target_id":target_id,"parent_block_id":block["block_id"],"block_order":block["order"],"content_span":block["content_span"],"mode":"sliced" if block_slices else "block","slice_ids":[x["slice_id"] for x in block_slices],"policy_version":policy["policy_version"]})
        slices.extend(block_slices)
        units=block_slices or [{"slice_id":None,"span":block["content_span"],"stop_reasons":[]}]
        for unit in units:
            wid=unit["slice_id"] or target_id; work.append({"work_item_id":wid,"target_id":target_id,"parent_block_id":block["block_id"],"slice_id":unit["slice_id"],"span":unit["span"],"block_order":block["order"],"stop_reasons":unit["stop_reasons"]})
    # A sliced AnalysisTarget may have several work items.  Keep that group
    # atomic: otherwise a batch boundary makes the same target appear in two
    # regions and a downstream model receives two incompatible obligations.
    groups=[]
    for item in work:
        if not groups or groups[-1][0]!=item["target_id"]: groups.append((item["target_id"],[item]))
        else: groups[-1][1].append(item)
    batches=[];current=[];chars=0
    for _,items in groups:
        length=sum(x["span"]["end_char"]-x["span"]["start_char"] for x in items);cap=policy["batch"]
        if current and (len(current)+len(items)>cap["max_target_items"] or chars+length>cap["max_target_chars"]):
            payload={"case_id":case_id,"items":[x["work_item_id"] for x in current],"policy":policy["policy_version"]}; batches.append({"record_type":"AnalysisBatch","batch_id":_id("ab",payload),"case_id":case_id,"source_hash":source_hash,"ordinal":len(batches),"work_items":current,"target_chars":chars,"stop_reasons":[]}) ; current=[];chars=0
        current.extend(items);chars+=length
    if current:
        payload={"case_id":case_id,"items":[x["work_item_id"] for x in current],"policy":policy["policy_version"]}; batches.append({"record_type":"AnalysisBatch","batch_id":_id("ab",payload),"case_id":case_id,"source_hash":source_hash,"ordinal":len(batches),"work_items":current,"target_chars":chars,"stop_reasons":[]})
    for batch in batches:
        if batch["target_chars"]>policy["batch"]["max_target_chars"]: batch["stop_reasons"].append("target_char_cap_exceeded_preserved")
        if len(batch["work_items"])>policy["batch"]["max_target_items"]: batch["stop_reasons"].append("target_item_cap_exceeded_preserved")
    deps={"sourceblock_cache_key":sourceblocks["cache_key"],"sentence_atom_cache_key":atoms["cache_key"],"sidecar_cache_key":sidecars["cache_key"],"context_hint_cache_key":hints["cache_key"],"analysis_region_policy_sha256":policy_hash}
    p2a=[_region(text,"P2a",batch,sourceblocks["blocks"],sidecars,hints,policy,deps) for batch in batches]
    regions=list(p2a)
    for base in p2a:
        region=copy.deepcopy(base);region["arm"]="P2b";region["included_hint_ids"]=sorted(h["hint_id"] for h in hints["hints"] if h["target_block_id"] in region["target_block_ids"] and h["status"] in policy["region"]["allowed_hint_statuses"]);region["region_id"]=_id("ar",{"base_region_id":base["region_id"],"arm":"P2b","policy":policy["policy_version"]});region["fingerprint"]="";region["fingerprint"]=canonical_hash({k:v for k,v in region.items() if k!="fingerprint"});regions.append(region)
    eligible_blocks={t["parent_block_id"] for t in targets};a_by={r["batch_id"]:{(x["span"]["start_char"],x["span"]["end_char"]) for x in r["context_refs"]} for r in regions if r["arm"]=="P2a"};dispositions=[]
    for hint in hints["hints"]:
        target_eligibility="eligible_primary_target" if hint["target_block_id"] in eligible_blocks else "target_ineligible_structural_only"
        included=[];events=[]
        for region in regions:
            if region["arm"]!="P2b":continue
            included.extend((region["batch_id"],(x["span"]["start_char"],x["span"]["end_char"])) for x in region["context_refs"] if hint["hint_id"] in x["source_hint_ids"])
            events.extend(x for x in region["context_events"] if hint["hint_id"] in x["source_hint_ids"])
        if target_eligibility!="eligible_primary_target":disposition="target_ineligible_structural_only"
        elif hint["status"]=="unresolved" or not hint["related_spans"]:disposition="invalid_or_unresolved"
        elif any(ref not in a_by.get(batch,set()) for batch,ref in included):disposition="included_new_span"
        elif included:disposition="included_provenance_only_already_baseline_context"
        elif any(x["reason"]=="overlaps_primary_target" for x in events):disposition="related_is_primary"
        elif any(x["reason"] in {"max_context_spans","max_context_chars","max_unique_source_chars"} for x in events):disposition="cap_dropped"
        else:disposition="no_eligible_related_context"
        dispositions.append({"hint_id":hint["hint_id"],"target_block_id":hint["target_block_id"],"hint_status":hint["status"],"target_eligibility":target_eligibility,"disposition":disposition})
    cache=canonical_hash({"case_id":case_id,"source_hash":source_hash,"dependencies":deps,"scheduler_version":policy["scheduler_version"]})
    return {"artifact_type":"AnalysisWorkloadMap","schema_version":policy["schema_version"],"case_id":case_id,"source_hash":source_hash,"scheduler_version":policy["scheduler_version"],"policy_sha256":policy_hash,"cache_key":cache,"dependencies":deps,"block_roles":roles,"targets":targets,"slices":slices,"batches":batches,"regions":regions,"hint_dispositions":dispositions}
