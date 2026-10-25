"""Build, validate, cache, and report deterministic KOS-5 ContextHints."""

from __future__ import annotations
import hashlib, html, json, time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from ..sentence_atoms import load_and_validate_sentence_atom_map
from ..sentence_atoms.segmenter import canonical_hash
from ..sidecars import load_and_validate_sidecar_map
from ..source_contract import open_source
from ..structural_prepass import load_and_validate_block_map
from .rules import run_context_hint_rules

EXPECTED_CASES = {"013009", "013948", "011904", "045155", "099980"}


class ContextHintError(ValueError):
    def __init__(self, detail: str, *, code: str = "context_hint_contract", location: str = "<root>"):
        self.code, self.location, self.detail = code, location, detail
        super().__init__(f"[{code}] {location}: {detail}")


def _load(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise ContextHintError(str(exc), code="malformed_artifact", location=str(path)) from exc
    if not isinstance(value, dict): raise ContextHintError("JSON object required", code="malformed_artifact", location=str(path))
    return value


@lru_cache(maxsize=1)
def _validator():
    schema = _load(Path(__file__).resolve().parents[1] / "contracts/context_hint.v1.json")
    Draft202012Validator.check_schema(schema); return Draft202012Validator(schema)


@lru_cache(maxsize=1)
def _manifest_validator():
    schema = _load(Path(__file__).resolve().parents[1] / "contracts/context_hint_build_manifest.v1.json")
    Draft202012Validator.check_schema(schema); return Draft202012Validator(schema)


@lru_cache(maxsize=1)
def _ledger_validator():
    schema = _load(Path(__file__).resolve().parents[1] / "contracts/context_hint_ledger_event.v1.json")
    Draft202012Validator.check_schema(schema); return Draft202012Validator(schema)


def _write(path: Path, value: Any, immutable=False):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if path.exists() and immutable:
        if path.read_bytes() != data: raise ContextHintError("refusing to overwrite dependency-addressed artifact", code="immutable_conflict", location=str(path))
        return "reused"
    path.parent.mkdir(parents=True, exist_ok=True); temp = path.with_suffix(path.suffix + ".tmp"); temp.write_bytes(data); temp.replace(path); return "created"


def validate_context_hint_map(value: dict[str, Any], text: str, blocks: dict[str, Any], atoms: dict[str, Any], sidecars: dict[str, Any], policy: dict[str, Any], *, artifact_path: str | Path | None = None, allow_partial: bool = False):
    try: _validator().validate(value)
    except ValidationError as exc: raise ContextHintError(exc.message, code="schema_violation", location=".".join(map(str, exc.absolute_path)) or "<root>") from exc
    if value["run_status"] == "partial" and not allow_partial: raise ContextHintError("partial ContextHint map is not readable as complete", code="partial_artifact", location="run_status")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != value["source_hash"]: raise ContextHintError("source bytes do not match source_hash", code="source_hash_mismatch", location="source_hash")
    parent_identity = (blocks.get("case_id"), blocks.get("source_hash"), blocks.get("cache_key"), atoms.get("cache_key"), sidecars.get("cache_key"))
    own_identity = (value["case_id"], value["source_hash"], value["sourceblock_cache_key"], value["sentence_atom_cache_key"], value["sidecar_cache_key"])
    if parent_identity != own_identity: raise ContextHintError("parent artifact identity mismatch", code="dependency_mismatch", location="dependencies")
    expected = run_context_hint_rules(text, blocks, atoms, sidecars, policy, canonical_hash(policy), set(value["failed_rules"]))
    if value != expected:
        field = next((k for k in expected if value.get(k) != expected[k]), "<root>")
        raise ContextHintError("value differs from deterministic producer", code="canonical_mismatch", location=field)
    if artifact_path is not None:
        dep = f"{value['rule_bundle_version']}-{value['policy_sha256'][:16]}" + (f"-partial-{canonical_hash(value['failed_rules'])[:12]}" if value["failed_rules"] else "")
        expected_suffix = (value["case_id"], value["source_hash"], value["sourceblock_cache_key"], value["sentence_atom_cache_key"], value["sidecar_cache_key"], dep, "context_hint_map.json")
        if tuple(Path(artifact_path).parts[-7:]) != expected_suffix: raise ContextHintError("artifact path does not match dependencies", code="identity_mismatch", location="artifact_path")
    block_by_id = {b["block_id"]: b for b in blocks["blocks"]}
    if value["target_block_ids"] != [b["block_id"] for b in blocks["blocks"]]: raise ContextHintError("primary targets changed", code="target_coverage", location="target_block_ids")
    for hint in value["hints"]:
        if hint["target_block_id"] not in block_by_id or hint["target_span"] != block_by_id[hint["target_block_id"]]["span"]: raise ContextHintError("invalid target", code="identity_mismatch", location=hint["hint_id"])
        if len(hint["related_block_ids"]) != len(hint["related_spans"]): raise ContextHintError("related ids/spans length mismatch", code="identity_mismatch", location=hint["hint_id"])
        if hint["target_block_id"] in hint["related_block_ids"]: raise ContextHintError("self relation forbidden", code="direction_violation", location=hint["hint_id"])
        target_order = block_by_id[hint["target_block_id"]]["order"]
        for bid, ref in zip(hint["related_block_ids"], hint["related_spans"]):
            if bid not in block_by_id or ref != block_by_id[bid]["span"]: raise ContextHintError("invalid related block/span", code="identity_mismatch", location=hint["hint_id"])
            order = block_by_id[bid]["order"]
            if hint["direction"] == "previous" and order >= target_order: raise ContextHintError("previous direction/order mismatch", code="direction_violation", location=hint["hint_id"])
            if hint["direction"] == "next" and order <= target_order: raise ContextHintError("next direction/order mismatch", code="direction_violation", location=hint["hint_id"])
        for ref in [hint["target_span"], *hint["related_spans"], *hint["evidence_spans"]]:
            if ref["case_id"] != value["case_id"] or ref["source_hash"] != value["source_hash"] or not (0 <= ref["start_char"] <= ref["end_char"] <= len(text)): raise ContextHintError("cross-source or out-of-bounds span", code="offset_violation", location=hint["hint_id"])
    serialized = json.dumps(value["hints"], sort_keys=True)
    for forbidden in policy["forbidden_semantic_fields"]:
        if f'"{forbidden}"' in serialized: raise ContextHintError("forbidden semantic field", code="semantic_scope", location=forbidden)
    return {"schema_valid": True, "canonical_ids": True, "same_source_exact_spans": True, "direction_order_valid": True, "no_self_or_duplicates": True, "no_semantic_facts": True, "all_targets_preserved": True, "caps_and_dedup_reproducible": True}


def load_and_validate_context_hint_map(path, text, blocks, atoms, sidecars, policy, *, allow_partial=False):
    value = _load(Path(path)); return value, validate_context_hint_map(value, text, blocks, atoms, sidecars, policy, artifact_path=path, allow_partial=allow_partial)


def _metrics(hints):
    refs = [(r["case_id"],r["start_char"],r["end_char"]) for h in hints for r in h["related_spans"]]; unique = set(refs)
    merged=[]
    for cid,a,b in sorted(unique):
        if not merged or cid != merged[-1][0] or a > merged[-1][2]: merged.append([cid,a,b])
        else: merged[-1][2]=max(merged[-1][2],b)
    proposed = sum(b-a for _,a,b in refs); unique_chars = sum(b-a for _,a,b in merged)
    return {"targets_with_hints": len({h["target_block_id"] for h in hints}), "unique_related_span_count": len(unique), "unique_related_chars": unique_chars, "proposed_related_chars": proposed, "repeated_proposed_chars": proposed-unique_chars}


def _addition_distributions(hints):
    targets={}
    for hint in hints:
        key=(hint["case_id"],hint["target_block_id"]); row=targets.setdefault(key,{"hints":0,"refs":set()}); row["hints"]+=1
        row["refs"].update((r["start_char"],r["end_char"]) for r in hint["related_spans"])
    hint_hist=Counter(); char_hist=Counter()
    for row in targets.values():
        hint_hist[str(row["hints"])]+=1; char_hist[str(sum(b-a for a,b in row["refs"]))]+=1
    by_type={}
    for kind in sorted({h["hint_type"] for h in hints}):
        selected=[h for h in hints if h["hint_type"]==kind]; by_type[kind]={"hint_count":len(selected),**_metrics(selected)}
    return {"per_target_hint_count_histogram":dict(sorted(hint_hist.items(),key=lambda x:int(x[0]))),"per_target_added_chars_histogram":dict(sorted(char_hist.items(),key=lambda x:int(x[0]))),"by_hint_type":by_type}


def _case_summary(value: dict[str, Any], artifact_ref: str, artifact_action: str, checks: dict[str, bool]) -> dict[str, Any]:
    ledger = value["policy_ledger"]
    return {
        "case_id": value["case_id"], "source_hash": value["source_hash"],
        "artifact_ref": artifact_ref, "artifact_action": artifact_action,
        "target_count": len(value["target_block_ids"]), "hint_count": len(value["hints"]),
        "pre_policy_count": value["pre_policy_count"], "post_policy_count": value["post_policy_count"],
        "hint_type_counts": dict(sorted(Counter(h["hint_type"] for h in value["hints"]).items())),
        "hint_status_counts": dict(sorted(Counter(h["status"] for h in value["hints"]).items())),
        "hint_direction_counts": dict(sorted(Counter(h["direction"] for h in value["hints"]).items())),
        "dropped_reason_counts": dict(sorted(Counter(x["reason"] for x in ledger if x["action"] == "dropped").items())),
        "policy_ledger_count": len(ledger), "kept_count": sum(x["action"] == "kept" for x in ledger),
        "dropped_count": sum(x["action"] == "dropped" for x in ledger),
        "error_event_count": len(value["rule_events"]), "rule_runs": value["rule_runs"],
        "metrics": _metrics(value["hints"]), "checks": checks,
    }


def _cap_ledger_record(value: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "event_type": "cap_dedup_decision", "case_id": value["case_id"], "source_hash": value["source_hash"],
        **item, "severity": "audit", "message_code": item["reason"],
        "message": f"ContextHint proposal {item['action']}: {item['reason']}",
        "rule_bundle_version": value["rule_bundle_version"], "policy_sha256": value["policy_sha256"],
    }
    return {"ledger_event_id": f"cl-{canonical_hash(payload)[:20]}", **payload}


def _global_summary(maps: list[dict[str, Any]]) -> dict[str, Any]:
    hints=[h for value in maps for h in value["hints"]]
    return {"case_count":len(maps),"target_count":sum(len(v["target_block_ids"]) for v in maps),"hint_count":len(hints),"pre_policy_count":sum(v["pre_policy_count"] for v in maps),"post_policy_count":sum(v["post_policy_count"] for v in maps),"hint_type_counts":dict(sorted(Counter(h["hint_type"] for h in hints).items())),"hint_status_counts":dict(sorted(Counter(h["status"] for h in hints).items())),"hint_direction_counts":dict(sorted(Counter(h["direction"] for h in hints).items())),"dropped_reason_counts":dict(sorted(Counter(x["reason"] for v in maps for x in v["policy_ledger"] if x["action"]=="dropped").items())),"policy_ledger_count":sum(len(v["policy_ledger"]) for v in maps),"rule_event_count":sum(len(v["rule_events"]) for v in maps),**_metrics(hints)}


def _read_jsonl(path: Path, *, expected_event_type: str) -> list[dict[str, Any]]:
    try: raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc: raise ContextHintError(str(exc), code="malformed_ledger", location=str(path)) from exc
    rows = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip(): raise ContextHintError("blank/truncated JSONL line", code="malformed_ledger", location=f"{path}:{number}")
        try: value = json.loads(line)
        except json.JSONDecodeError as exc: raise ContextHintError(str(exc), code="malformed_ledger", location=f"{path}:{number}") from exc
        try: _ledger_validator().validate(value)
        except ValidationError as exc: raise ContextHintError(exc.message, code="ledger_schema_violation", location=f"{path}:{number}") from exc
        if value.get("event_type") != expected_event_type: raise ContextHintError("wrong ledger event type", code="ledger_reconciliation", location=f"{path}:{number}")
        rows.append(value)
    return rows


def _safe_artifact(output: Path, artifact_ref: str) -> Path:
    relative = Path(artifact_ref)
    if relative.is_absolute() or "\\" in artifact_ref or any(part in {"", ".", ".."} for part in relative.parts):
        raise ContextHintError("unsafe or non-canonical artifact_ref", code="unsafe_artifact_ref", location=artifact_ref)
    resolved = (output / relative).resolve()
    try: resolved.relative_to(output.resolve())
    except ValueError as exc: raise ContextHintError("artifact_ref escapes output root", code="unsafe_artifact_ref", location=artifact_ref) from exc
    if not resolved.is_file(): raise ContextHintError("referenced ContextHint map does not exist", code="missing_artifact", location=artifact_ref)
    if resolved.relative_to(output.resolve()).as_posix() != artifact_ref: raise ContextHintError("artifact_ref is not canonical", code="unsafe_artifact_ref", location=artifact_ref)
    return resolved


def load_and_validate_context_hint_build(*, manifest_path, cap_ledger_path, rule_event_ledger_path, source_store, plan03_report, plan04_report, plan05_report, sourceblock_policy, sentence_policy, sidecar_policy, policy_path):
    manifest_file = Path(manifest_path).resolve(); output = manifest_file.parent; manifest = _load(manifest_file)
    try: _manifest_validator().validate(manifest)
    except ValidationError as exc: raise ContextHintError(exc.message, code="manifest_schema_violation", location=".".join(map(str, exc.absolute_path)) or "<root>") from exc
    policy, sbp, sap, scp = _load(Path(policy_path)), _load(Path(sourceblock_policy)), _load(Path(sentence_policy)), _load(Path(sidecar_policy))
    policy_hash = canonical_hash(policy)
    if manifest["policy_sha256"] != policy_hash or manifest["rule_bundle_version"] != policy["rule_bundle_version"]: raise ContextHintError("manifest policy identity mismatch", code="dependency_mismatch", location="manifest")
    if manifest["status"] != "pass": raise ContextHintError("partial manifest is not readable as complete", code="partial_artifact", location="status")
    rows = manifest["cases"]
    case_ids = [r["case_id"] for r in rows]
    if set(case_ids) != EXPECTED_CASES or len(case_ids) != len(set(case_ids)): raise ContextHintError("manifest must contain five unique KOS-5 cases", code="manifest_completeness", location="cases")
    r3, r4, r5 = _load(Path(plan03_report)), _load(Path(plan04_report)), _load(Path(plan05_report)); c3={c["case_id"]:c for c in r3["cases"]}; c4={c["case_id"]:c for c in r4["cases"]}; c5={c["case_id"]:c for c in r5["cases"]}
    maps=[]; referenced=set(); store=Path(source_store).resolve()
    for row in rows:
        cid, sh = row["case_id"], row["source_hash"]
        if cid not in c3 or cid not in c4 or cid not in c5 or c5[cid]["source_hash"] != sh: raise ContextHintError("case/source identity differs from parent reports", code="dependency_mismatch", location=cid)
        artifact = _safe_artifact(output, row["artifact_ref"]); referenced.add(artifact)
        text=open_source(store,cid,sh); bp=Path(r3["outputs"]["output_root"])/c3[cid]["artifact_ref"]; blocks,_=load_and_validate_block_map(bp,text,store)
        if canonical_hash(sbp)!=blocks["policy_sha256"]: raise ContextHintError("SourceBlock policy mismatch",code="dependency_mismatch",location=cid)
        ap=Path(r4["outputs"]["output_root"])/c4[cid]["artifact_ref"]; atoms,_=load_and_validate_sentence_atom_map(ap,text,blocks,sap)
        sp=Path(r5["outputs"]["output_root"])/c5[cid]["artifact_ref"]; sidecars,_=load_and_validate_sidecar_map(sp,text,blocks,atoms,scp,sap)
        value, checks=load_and_validate_context_hint_map(artifact,text,blocks,atoms,sidecars,policy)
        expected=_case_summary(value,row["artifact_ref"],row["artifact_action"],checks)
        if row != expected:
            field=next((k for k in expected if row.get(k)!=expected[k]),"<root>")
            raise ContextHintError("stored case summary differs from actual ContextHint map",code="manifest_metric_mismatch",location=f"{cid}.{field}")
        maps.append(value)
    current=set()
    for candidate in output.glob("cases/**/context_hint_map.json"):
        try: probe=_load(candidate)
        except ContextHintError: continue
        if probe.get("policy_sha256")==policy_hash and probe.get("rule_bundle_version")==policy["rule_bundle_version"] and probe.get("run_status")=="complete": current.add(candidate.resolve())
    if current != referenced: raise ContextHintError("current complete artifact namespace is missing, duplicated, or unreferenced",code="manifest_completeness",location="artifact_ref")
    expected_cap=[_cap_ledger_record(value,item) for value in maps for item in value["policy_ledger"]]
    actual_cap=_read_jsonl(Path(cap_ledger_path),expected_event_type="cap_dedup_decision")
    if actual_cap != expected_cap: raise ContextHintError("cap/dedup ledger differs from ContextHint maps",code="ledger_reconciliation",location=str(cap_ledger_path))
    actual_events=_read_jsonl(Path(rule_event_ledger_path),expected_event_type="rule_failure")
    expected_events=[event for value in maps for event in value["rule_events"]]
    if actual_events != expected_events: raise ContextHintError("rule event ledger differs from ContextHint maps",code="ledger_reconciliation",location=str(rule_event_ledger_path))
    totals=_global_summary(maps)
    if manifest["summary"] != totals: raise ContextHintError("stored global summary differs from actual ContextHint maps",code="manifest_metric_mismatch",location="summary")
    return manifest, {"manifest_schema_valid":True,"safe_existing_artifact_refs":True,"five_complete_current_artifacts":True,"case_metrics_recomputed":True,"global_metrics_recomputed":True,"ledgers_schema_and_identity_valid":True,"ledgers_reconciled":True,"totals":totals}


def build_context_hints(*, source_store, source_manifest, plan03_report, plan04_report, plan05_report, plan05_independent_report, sourceblock_policy, sentence_policy, sidecar_policy, policy_path, output_root, audit_path=None, fault_rules=None):
    started=time.perf_counter(); store=Path(source_store).resolve(); output=Path(output_root).resolve(); manifest=_load(Path(source_manifest)); r3,r4,r5=_load(Path(plan03_report)),_load(Path(plan04_report)),_load(Path(plan05_report)); sbp,sap,scp,policy=_load(Path(sourceblock_policy)),_load(Path(sentence_policy)),_load(Path(sidecar_policy)),_load(Path(policy_path))
    existing_manifest=output/"context_hint_build_manifest.json"
    if existing_manifest.exists():
        existing=_load(existing_manifest)
        if existing.get("policy_sha256")==canonical_hash(policy) and existing.get("rule_bundle_version")==policy["rule_bundle_version"]:
            try:
                load_and_validate_context_hint_build(manifest_path=existing_manifest,cap_ledger_path=output/"cap_dedup_ledger.jsonl",rule_event_ledger_path=output/"rule_event_ledger.jsonl",source_store=store,plan03_report=plan03_report,plan04_report=plan04_report,plan05_report=plan05_report,sourceblock_policy=sourceblock_policy,sentence_policy=sentence_policy,sidecar_policy=sidecar_policy,policy_path=policy_path)
            except ContextHintError as exc:
                raise ContextHintError("existing current cache manifest/artifact/ledger failed validation; refusing cache reuse",code="cache_validation_failed",location=str(existing_manifest)) from exc
    independent=Path(plan05_independent_report).read_text(encoding="utf-8")
    if r5.get("status") != "pass" or "**PASS" not in independent: raise ContextHintError("Plan 05 dependency and independent verdict must PASS", code="dependency_gate")
    if manifest.get("workload") != "KOS-5" or {c["case_id"] for c in manifest.get("cases",[])} != EXPECTED_CASES: raise ContextHintError("source manifest is not exact KOS-5", code="dependency_gate")
    locked_hashes={c["case_id"]:c["sha256"] for c in manifest["cases"]}
    if {c["case_id"] for c in r5["cases"]} != EXPECTED_CASES or any(locked_hashes.get(c["case_id"])!=c["source_hash"] for c in r5["cases"]): raise ContextHintError("Plan 05 identities differ from locked KOS-5 manifest", code="dependency_gate")
    c3={c["case_id"]:c for c in r3["cases"]}; c4={c["case_id"]:c for c in r4["cases"]}; rows=[]; ph=canonical_hash(policy)
    for c5 in r5["cases"]:
        cid,sh=c5["case_id"],c5["source_hash"]; text=open_source(store,cid,sh)
        bp=Path(r3["outputs"]["output_root"])/c3[cid]["artifact_ref"]; blocks,_=load_and_validate_block_map(bp,text,store)
        if canonical_hash(sbp)!=blocks["policy_sha256"]: raise ContextHintError("SourceBlock policy dependency mismatch",code="dependency_gate",location=cid)
        ap=Path(r4["outputs"]["output_root"])/c4[cid]["artifact_ref"]; atoms,_=load_and_validate_sentence_atom_map(ap,text,blocks,sap)
        sp=Path(r5["outputs"]["output_root"])/c5["artifact_ref"]; sidecars,_=load_and_validate_sidecar_map(sp,text,blocks,atoms,scp,sap)
        value=run_context_hint_rules(text,blocks,atoms,sidecars,policy,ph,fault_rules)
        dep=f"{policy['rule_bundle_version']}-{ph[:16]}"+(f"-partial-{canonical_hash(value['failed_rules'])[:12]}" if value["failed_rules"] else "")
        artifact=output/"cases"/cid/sh/blocks["cache_key"]/atoms["cache_key"]/sidecars["cache_key"]/dep/"context_hint_map.json"
        checks=validate_context_hint_map(value,text,blocks,atoms,sidecars,policy,artifact_path=artifact,allow_partial=bool(value["failed_rules"])); action=_write(artifact,value,True)
        rows.append({**_case_summary(value,artifact.relative_to(output).as_posix(),action,checks),"map":value})
    ledger=output/"cap_dedup_ledger.jsonl"; ledger.parent.mkdir(parents=True,exist_ok=True); ledger.write_text("".join(json.dumps(_cap_ledger_record(r["map"],x),sort_keys=True)+"\n" for r in rows for x in r["map"]["policy_ledger"]),encoding="utf-8")
    events=output/"rule_event_ledger.jsonl"; events.write_text("".join(json.dumps(x,sort_keys=True)+"\n" for r in rows for x in r["map"]["rule_events"]),encoding="utf-8")
    clean=[{k:v for k,v in r.items() if k!="map"} for r in rows]; manifest={"build_manifest_version":"context-hint-build-v1","status":"partial" if any(r["error_event_count"] for r in rows) else "pass","workload":"KOS-5","rule_bundle_version":policy["rule_bundle_version"],"policy_sha256":ph,"summary":_global_summary([r["map"] for r in rows]),"cases":clean}; _manifest_validator().validate(manifest); manifest_path=output/"context_hint_build_manifest.json"; _write(manifest_path,manifest)
    build_checks=None
    if manifest["status"]=="pass":
        _,build_checks=load_and_validate_context_hint_build(manifest_path=manifest_path,cap_ledger_path=ledger,rule_event_ledger_path=events,source_store=store,plan03_report=plan03_report,plan04_report=plan04_report,plan05_report=plan05_report,sourceblock_policy=sourceblock_policy,sentence_policy=sentence_policy,sidecar_policy=sidecar_policy,policy_path=policy_path)
    if audit_path:
        p=Path(audit_path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text("<!doctype html><meta charset='utf-8'><title>Plan 06 ContextHint audit</title><h1>Plan 06 ContextHint audit</h1><p>Hints are context proposals, not semantic facts. No source text is materialized.</p><pre>"+html.escape(json.dumps(clean,ensure_ascii=False,indent=2))+"</pre>",encoding="utf-8")
    allh=[h for r in rows for h in r["map"]["hints"]]; agg=_metrics(allh); distributions=_addition_distributions(allh); elapsed=max(time.perf_counter()-started,1e-9); types=Counter(h["hint_type"] for h in allh); statuses=Counter(h["status"] for h in allh); directions=Counter(h["direction"] for h in allh); dropped=Counter(x["reason"] for r in rows for x in r["map"]["policy_ledger"] if x["action"]=="dropped")
    type_counts={name:types[name] for name in policy["allowed_hint_types"]}; status_counts={name:statuses[name] for name in policy["statuses"]}
    gates={"plan05_independent_pass":True,"exact_kos5":True,"dependency_hash_paths_validated":True,"same_source_exact_spans":True,"canonical_ids":True,"direction_order_consistent":True,"no_semantic_facts":True,"all_primary_targets_preserved":True,"context_additions_measurable":True,"zero_rule_errors":all(r["error_event_count"]==0 for r in rows),"dependency_addressed_cache":True,"stored_manifest_recomputed":bool(build_checks),"ledgers_reconciled":bool(build_checks)}
    return {"report_version":"plan06-context-hint-validation-v1","status":"pass" if all(gates.values()) else "fail","scope":"KOS-5 deterministic local ContextHint rules; no model/LLM; KOS artifacts audit-only","inputs":{"source_store":str(store),"source_manifest":str(Path(source_manifest).resolve()),"plan03_report":str(Path(plan03_report).resolve()),"plan04_report":str(Path(plan04_report).resolve()),"plan05_report":str(Path(plan05_report).resolve()),"plan05_independent_report":str(Path(plan05_independent_report).resolve()),"policy":str(Path(policy_path).resolve())},"outputs":{"output_root":str(output),"build_manifest":str((output/"context_hint_build_manifest.json").resolve()),"cap_dedup_ledger":str(ledger.resolve()),"rule_event_ledger":str(events.resolve()),"audit_html":str(Path(audit_path).resolve()) if audit_path else None},"summary":{"case_count":len(rows),"target_count":sum(r["target_count"] for r in rows),"hint_count":len(allh),"pre_policy_count":sum(r["pre_policy_count"] for r in rows),"post_policy_count":sum(r["post_policy_count"] for r in rows),"hint_type_counts":type_counts,"hint_status_counts":status_counts,"hint_direction_counts":dict(sorted(directions.items())),"dropped_reason_counts":dict(sorted(dropped.items())),"policy_ledger_count":sum(r["policy_ledger_count"] for r in rows),**agg,"addition_distributions":distributions,"error_event_count":sum(r["error_event_count"] for r in rows),"elapsed_seconds":elapsed,"characters_per_second":sum(len(open_source(store,r["case_id"],r["source_hash"])) for r in rows)/elapsed},"p2_counterfactual":{"P2a":{"context_hint_count":0,"added_related_chars":0},"P2b":{"context_hint_count":len(allh),**agg,"addition_distributions":distributions}},"stored_build_validation":build_checks,"gates":gates,"cases":clean,"metrics_not_reported":["precision","recall","F1"],"metrics_reason":"No adjudicated ContextHint gold exists.","limitations":["ContextHint is only a context proposal and does not prove semantic continuity.","accepted_by_contract means an evidence-backed structural continuation contract, not semantic correctness.","Speaker continuity candidates compare adjacent lexical cue classes and never assign identity.","No topic/coreference/condition inference, ContextObligation, AnalysisRegion, LegalUnit, AU, Issue, NN, retrieval, model, or LLM is implemented."]}
