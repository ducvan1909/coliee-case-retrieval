from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from pathlib import Path
from urllib import request as urlrequest
from urllib.parse import urlsplit

from ..concurrency_benchmark import core as bench
from ..au_compact import runner
from ..au_compact.core import deduplicate_lists
from ..au_compact.manifest import write_json
from ..milestone1.core import digest, load
from ..au_only.core import warmup

VERSION = "prefix-cache-observation-v1"


def _selected(parent):
    selected=[]
    for case in sorted(bench.CASES):
        rows=[q for q in parent["requests"] if q["case_id"]==case]
        rows.sort(key=lambda q:(sum(r["end_char"]-r["start_char"] for r in q["source_refs"] if r["role"]=="target"),q["request_id"]))
        selected.append(rows[len(rows)//2]["request_id"])
    return selected


def build_manifest(parent, *, probe_id):
    if not isinstance(probe_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",probe_id):
        raise ValueError("invalid_probe_id")
    return {"version":VERSION,"probe_id":probe_id,"parent":copy.deepcopy(parent),
        "parent_sha256":digest(parent),"selected_request_ids":_selected(parent),
        "phases":["initial","reuse"],"source_request_count":10,
        "concurrency_configuration":4,"client_inflight":1,
        "cold_cache_claim":False,"semantic_quality_claim":False}


def prepare(manifest, *, source_store, atom_root):
    parent=manifest.get("parent",{})
    if manifest.get("version")!=VERSION or manifest.get("parent_sha256")!=digest(parent):
        raise ValueError("invalid_prefix_probe_manifest")
    if manifest!=build_manifest(parent,probe_id=manifest.get("probe_id")):
        raise ValueError("prefix_probe_manifest_changed")
    tasks=bench.prepare(parent,source_store=source_store,atom_root=atom_root)
    by_id={t["request"]["request_id"]:t for t in tasks}
    result=[]
    for qid in manifest["selected_request_ids"]:
        task=by_id[qid]
        for phase in manifest["phases"]:
            q=copy.deepcopy(task["request"])
            q["request_id"]="prefix-"+digest({"manifest":digest(manifest),"source_request":qid,"phase":phase})[:24]
            if len(runner.build_prompt(q,task["rendered"]).encode())+128>11488:
                raise ValueError("prefix_probe_input_ceiling_exceeded")
            result.append({**task,"effective":q,"phase":phase})
    return result


def diagnostic(cfg):
    base=cfg["url"].removesuffix("/v1/chat/completions")
    req=urlrequest.Request(base+"/v1/diagnostics/json/info",headers={"Authorization":"Bearer "+cfg["token"]})
    with urlrequest.urlopen(req,timeout=min(cfg.get("timeout",60),60)) as response:
        raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError("diagnostic_response_too_large")
        return json.loads(raw)


def summarize(rows, *, expected_count=10, resumed=False, wall_seconds=None):
    cache_rows=[]
    for row in rows:
        obs=row["receipt"].get("cache_observation",{})
        trace=row["receipt"].get("transport_trace",{})
        fresh=(trace.get("submit_attempts")==1 and any(e.get("method")=="GET" and e.get("http_status")==404 for e in trace.get("events",[])))
        valid=(obs.get("state")=="provider" and type(obs.get("cached_tokens")) is int and
            type(obs.get("prompt_tokens")) is int and 0<=obs["cached_tokens"]<=obs["prompt_tokens"])
        cache_rows.append({"request_id":row["request"]["request_id"],"phase":row["phase"],
            "fresh_server_job":fresh,"state":obs.get("state","unavailable"),
            "cached_tokens":obs.get("cached_tokens") if valid and fresh else None,
            "prompt_tokens":obs.get("prompt_tokens") if valid and fresh else None,
            "provider_cache_report_valid":valid,
            "backend_seconds":trace.get("server_timing",{}).get("inference_seconds"),
            "client_latency_ms":row["receipt"].get("latency_ms")})
    eligible=[x for x in cache_rows if x["provider_cache_report_valid"] and x["fresh_server_job"]]
    counted=sum(x["cached_tokens"] for x in eligible)
    prompt=sum(x["prompt_tokens"] for x in eligible)
    complete=len(rows)==expected_count
    usage=[r["receipt"].get("usage") for r in rows]
    return {"status":"complete" if complete else "incomplete","completed_count":len(rows),
        "protocol_verified":sum(r["status"]=="protocol_verified" for r in rows),
        "provider_report_count":len(eligible),"cache_hit_observed":(counted>0 if eligible else None),
        "cached_tokens":counted if eligible else None,"reported_prompt_tokens":prompt if eligible else None,
        "cached_fraction":counted/prompt if prompt else None,
        "resume_or_client_cache":resumed,"fresh_measurement_eligible":complete and not resumed and len(eligible)==expected_count,
        "cache_observations":cache_rows,"wall_seconds":wall_seconds,
        "tokens":{k:sum(u.get(k,0) for u in usage if isinstance(u,dict)) for k in ("input_tokens","output_tokens","total_tokens")},
        "usage_unavailable":sum(not isinstance(u,dict) for u in usage),
        "cold_cache_claim":False,"prefill_time_available":False,"causal_speedup_claim":False,
        "billing_discount_claim":False,"semantic_quality_claim":False}


def run(manifest, *, cfg, source_store, atom_root, output_root, execute=False,
        capability_fetch=None, diagnostic_fetch=None, caller=None, warmup_fn=None, policy=None):
    if not execute:raise ValueError("prefix_probe_requires_execute")
    parsed=urlsplit(cfg.get("url",""))
    if (parsed.scheme!="https" or parsed.path!="/v1/chat/completions" or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment or
        not re.fullmatch(r"[a-z0-9-]+--coliee-qwen35-9b-concurrency-server\.(?:[a-z0-9.-]+\.modal\.direct|modal\.run)",parsed.hostname or "")):
        raise ValueError("experimental_endpoint_required")
    if cfg.get("model")!=bench.MODEL or cfg.get("enable_thinking") is not False:
        raise ValueError("prefix_probe_model_changed")
    tasks=prepare(manifest,source_store=source_store,atom_root=atom_root)
    root=Path(output_root).resolve()
    if any(root.is_relative_to(Path(d).resolve()) for d in (source_store,atom_root)):
        raise ValueError("output_overlaps_source")
    if (root/"runtime_ledger.json").exists() or (root/"identity.json").exists():
        raise ValueError("historical_output_root_forbidden")
    if (root/"run.json").exists() and load(root/"run.json").get("version")!=VERSION:
        raise ValueError("historical_output_root_forbidden")
    root.mkdir(parents=True,exist_ok=True)
    lock=root/"prefix_probe.lock"
    try: handle=lock.open("x")
    except FileExistsError:raise ValueError("prefix_probe_locked_manual_recovery_required") from None
    try:
        handle.close()
        cfg={**cfg,"transport":"jobs","string_decoder":"host_validated",
             "jobs_url":cfg["url"].removesuffix("/chat/completions")+"/jobs"}
        identity={"version":VERSION,"manifest_sha256":digest(manifest),
            "endpoint_sha256":hashlib.sha256(cfg["url"].encode()).hexdigest(),
            "prompt_identity":runner.prompt_identity(),"decoder_version":runner.RESPONSE_FORMAT_VERSION}
        ip=root/"probe_identity.json"
        if ip.exists() and load(ip)!=identity:raise ValueError("prefix_probe_identity_mismatch")
        write_json(ip,identity)
        policy=policy or {"max_attempts":50,"max_wait_seconds":1500}
        info=bench.wait_capability(cfg,capability_fetch or bench.capability,policy,root)
        write_json(root/"capability.json",info)
        expected={"experiment":bench.VERSION,"gateway_concurrency":4,"server_concurrency":4,
            "model":bench.MODEL,"max_containers":1,"gpu":"L40S:1",
            "context_length":12288,"max_total_tokens":12288,"cuda_graph_max_bs":4,
            "exclusive_probes":True,"backend_retry":False,
            "model_revision":"c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "job_volume":"coliee-qwen35-9b-concurrency-jobs","job_store_subdir":"c4"}
        if any(info.get(k)!=v for k,v in expected.items()) or info.get("ready") is not True or any(info.get(k) for k in ("poisoned","stopping","backend_outcome_unknown")):
            raise ValueError("prefix_probe_endpoint_mismatch")
        warm=(warmup_fn or warmup)(cfg,policy,root/"warmup")
        if warm.get("status")!="success":raise ValueError("prefix_probe_warmup_failed")
        live=(diagnostic_fetch or diagnostic)(cfg)
        write_json(root/"runtime_cache.json",live)
        fields=live.get("backend",{}).get("get_server_info",{}).get("fields",{})
        args=fields.get("server_args",fields)
        if args.get("enable_cache_report") is not True:
            raise ValueError("runtime_cache_report_not_enabled_or_unavailable")
        rows=[];resumed=False;stop=False;started=time.monotonic()
        for task in tasks:
            q=task["effective"];path=root/"cache"/(q["request_id"]+".json")
            reservation=root/"reservations"/(q["request_id"]+".json")
            if path.exists():
                row=load(path)
                if row.get("identity")!=identity or row.get("request")!=q or row.get("phase")!=task["phase"]:
                    raise ValueError("prefix_probe_cache_mismatch")
                resumed=True;rows.append(row)
                if runner._blocks_dispatch(row["receipt"]) or row["receipt"].get("failure_diagnostic",{}).get("outcome_unknown"):
                    stop=True;break
                continue
            if reservation.exists():resumed=True
            write_json(reservation,{"request":q,"identity":identity})
            compact=None;normalized=None
            try:
                compact,receipt=(caller or bench._default_call)(cfg,q,task["rendered"],catalog=task["catalog"])
                if receipt.get("finish_reason")!="stop":raise runner.CompactRunError(json.dumps(receipt))
                try:
                    cleaned,cleanup=deduplicate_lists(compact)
                    normalized=runner._normalize(cleaned,q,task["binding"],task["source"])
                    receipt["exact_duplicate_cleanup"]=cleanup;status="protocol_verified"
                except Exception as exc:
                    status="unresolved";receipt["failure_diagnostic"]={"kind":"host_validation","error_type":type(exc).__name__}
            except runner.CompactRunError as exc:
                try:receipt=json.loads(str(exc))
                except (ValueError,TypeError):receipt={"usage":None,"failure_diagnostic":{"kind":"adapter","outcome_unknown":True}}
                status="unresolved"
            except Exception as exc:
                status="unresolved";receipt={"usage":None,"failure_diagnostic":{"kind":"unexpected_client_failure","error_type":type(exc).__name__,"outcome_unknown":True}}
            row={"identity":identity,"request":q,"original_request":task["request"],"phase":task["phase"],
                 "status":status,"compact_response":compact,"response":normalized,"receipt":receipt}
            write_json(path,row);rows.append(row)
            write_json(root/"checkpoint.json",{"saved_count":len(rows),"expected_count":len(tasks),"last_request_id":q["request_id"]})
            if runner._blocks_dispatch(receipt) or receipt.get("failure_diagnostic",{}).get("outcome_unknown"):
                stop=True;break
        result={"version":VERSION,"identity":identity,"request_ledger":rows,
            **summarize(rows,expected_count=len(tasks),resumed=resumed,wall_seconds=time.monotonic()-started),
            "stop_dispatch":stop,"setup":{"warmup":warm,"outside_workload_wall":True,
                "server_startup_warmup":live.get("startup_warmup")}}
        write_json(root/"run.json",result)
        return result
    finally:lock.unlink(missing_ok=True)
