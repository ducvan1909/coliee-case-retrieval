"""Small, checkpointed concurrency experiment; the extraction contract is reused."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from ..milestone1.core import digest, load, preflight
from ..au_compact import runner
from ..au_compact.manifest import _binding_path, write_json
from ..au_compact.core import build_evidence_catalog, deduplicate_lists
from ..source_contract import open_source
from ..au_only.core import warmup

VERSION = "au-concurrency-v1"
MODEL = "Qwen/Qwen3.5-9B"
CASES = {"011904", "013009", "013948", "045155", "099980"}


def _save(path, value):
    write_json(Path(path), value)


def build_manifest(parent_manifest, *, source_store, atom_root, count=30, benchmark_id):
    if type(count) is not int or count < 10 or count > 32 or not benchmark_id:
        raise ValueError("invalid_benchmark_size_or_id")
    check = preflight(parent_manifest, source_store=source_store, atom_root=atom_root)
    if check["status"] != "pass":
        raise ValueError("parent_preflight_failed")
    # Choose source-length strata independently of model output or KOS labels.
    selected = set()
    for index, case in enumerate(sorted(CASES)):
        items = [q for q in parent_manifest["requests"] if q["case_id"] == case]
        n = count // 5 + (index < count % 5)
        items.sort(key=lambda q: (sum(r["end_char"]-r["start_char"] for r in q["source_refs"] if r["role"] == "target"), q["request_id"]))
        if len(items) < n:
            raise ValueError("insufficient_case_targets")
        for j in range(n):
            selected.add(items[round(j*(len(items)-1)/(n-1))]["request_id"])
    requests = [copy.deepcopy(q) for q in parent_manifest["requests"] if q["request_id"] in selected]
    value = {"version": VERSION, "benchmark_id": str(benchmark_id),
        "parent_manifest_sha256": digest(parent_manifest), "prompt_identity": runner.prompt_identity(),
        "decoder_version": runner.RESPONSE_FORMAT_VERSION, "model": MODEL,
        "requests": requests, "sampling": "per_case_source_length_quantiles",
        "semantic_quality_claim": False}
    prepare(value, source_store=source_store, atom_root=atom_root)
    return value


def prepare(manifest, *, source_store, atom_root):
    if manifest.get("version") != VERSION or manifest.get("model") != MODEL or not manifest.get("benchmark_id"):
        raise ValueError("invalid_benchmark_manifest")
    if manifest.get("prompt_identity") != runner.prompt_identity() or manifest.get("decoder_version") != runner.RESPONSE_FORMAT_VERSION:
        raise ValueError("stale_benchmark_prompt_or_decoder")
    rows = manifest.get("requests", [])
    if not 10 <= len(rows) <= 32 or {q["case_id"] for q in rows} != CASES:
        raise ValueError("benchmark_requires_small_kos5_sample")
    if len({q["request_id"] for q in rows}) != len(rows):
        raise ValueError("duplicate_benchmark_request")
    tasks = []
    for q in rows:
        if q["spec"]["model"] != MODEL or q["spec"]["enable_thinking"] is not False or q["spec"]["caps"]["output_tokens"] != 800:
            raise ValueError("benchmark_spec_changed")
        source = open_source(source_store, q["case_id"], q["source_hash"])
        binding = _binding_path(q["atom_binding"], atom_root)
        catalog = build_evidence_catalog(q, binding, source)
        rendered = runner._render(q, catalog)
        # The experimental request ID has two extra ASCII characters; include
        # this difference plus framing in the same conservative input ceiling.
        if len(runner.build_prompt(q,rendered).encode("utf-8"))+130 > 11488:
            raise ValueError("benchmark_input_ceiling_exceeded")
        tasks.append({"request": q, "source": source, "binding": binding,
            "catalog": catalog, "rendered": rendered})
    return tasks


def _effective(q, manifest, concurrency):
    q = copy.deepcopy(q)
    identity = {"benchmark": manifest["benchmark_id"], "manifest": digest(manifest),
                "arm": concurrency, "original_id": q["request_id"]}
    q["request_id"] = "bench-" + digest(identity)[:24]
    return q


def capability(cfg):
    base = cfg["url"].removesuffix("/v1/chat/completions")
    req = urlrequest.Request(base + "/v1/benchmark/info", headers={"Authorization": "Bearer " + cfg["token"]})
    with urlrequest.urlopen(req, timeout=min(cfg.get("timeout",60),60)) as response:
        return json.loads(response.read().decode())


def wait_capability(cfg, fetch, policy, root):
    """Bounded, source-free startup polling; never retry an unknown inference."""
    start=time.monotonic();events=[]
    limit=policy.get("max_attempts",50);deadline=policy.get("max_wait_seconds",1500)
    delay=policy.get("initial_backoff_seconds",1)
    for ordinal in range(1,limit+1):
        remaining=deadline-(time.monotonic()-start)
        if remaining<=0:break
        attempt_cfg={**cfg,"timeout":min(cfg.get("timeout",60),remaining)}
        try:
            info=fetch(attempt_cfg)
            events.append({"ordinal":ordinal,"status":"received"})
            _save(root/"capability_startup.json",{"attempts":events,"wall_seconds":time.monotonic()-start})
            return info
        except HTTPError as exc:
            code=exc.code;exc.close()
            events.append({"ordinal":ordinal,"http_status":code})
            if code not in (429,502,503,504):raise ValueError("capability_http_terminal") from None
        except (URLError,TimeoutError,OSError) as exc:
            events.append({"ordinal":ordinal,"error_type":type(exc).__name__})
        remaining=deadline-(time.monotonic()-start)
        if ordinal>=limit or remaining<=0:break
        time.sleep(min(delay,remaining));delay=min(delay*2,policy.get("max_backoff_seconds",30))
    _save(root/"capability_startup.json",{"attempts":events,"wall_seconds":time.monotonic()-start})
    raise ValueError("capability_startup_limit_reached")


def _percentile(values, fraction):
    if not values: return None
    return sorted(values)[round((len(values)-1)*fraction)]


def _default_call(cfg, request, rendered, *, catalog):
    """Adapt the production caller's required opener to the benchmark interface."""
    return runner._call(cfg, request, rendered, urlrequest.urlopen, catalog=catalog)


def run(manifest, *, source_store, atom_root, cfg, concurrency, output_root,
        execute=False, capability_fetch=None, caller=None, warmup_fn=None,
        warmup_policy=None):
    if not execute:
        raise ValueError("benchmark_requires_execute")
    if type(concurrency) is not int or concurrency not in (1,2,4):
        raise ValueError("benchmark_concurrency_must_be_1_2_4")
    if cfg.get("model") != MODEL or cfg.get("enable_thinking") is not False:
        raise ValueError("benchmark_model_or_thinking_changed")
    parsed=urlsplit(cfg.get("url",""))
    host=parsed.hostname or ""
    if (parsed.scheme!="https" or parsed.path!="/v1/chat/completions" or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port or
        not re.fullmatch(r"[a-z0-9-]+--coliee-qwen35-9b-concurrency-server\.(?:[a-z0-9.-]+\.modal\.direct|modal\.run)",host)):
        raise ValueError("experimental_endpoint_required_not_baseline")
    tasks = prepare(manifest, source_store=source_store, atom_root=atom_root)
    root = Path(output_root).resolve()
    for dep in (source_store, atom_root):
        if root.is_relative_to(Path(dep).resolve()):
            raise ValueError("output_overlaps_source")
    root.mkdir(parents=True, exist_ok=True)
    if (root/"runtime_ledger.json").exists() or (root/"milestone1_run.lock").exists():
        raise ValueError("baseline_output_root_forbidden")
    if (root/"run.json").exists() and load(root/"run.json").get("version") != VERSION:
        raise ValueError("historical_output_root_forbidden")
    lock = root / "benchmark.lock"
    try: handle = lock.open("x")
    except FileExistsError: raise ValueError("benchmark_locked_manual_recovery_required") from None
    try:
        handle.close()
        cfg = copy.deepcopy(cfg)
        cfg.update(transport="jobs", string_decoder="host_validated",
            jobs_url=cfg["url"].removesuffix("/chat/completions")+"/jobs")
        identity = {"manifest_sha256": digest(manifest), "concurrency": concurrency,
            "endpoint_sha256": hashlib.sha256(cfg["url"].encode()).hexdigest(),
            "prompt_identity": runner.prompt_identity(), "decoder_version": runner.RESPONSE_FORMAT_VERSION}
        identity_path = root / "identity.json"
        if identity_path.exists() and load(identity_path) != identity:
            raise ValueError("benchmark_resume_identity_mismatch")
        _save(identity_path, identity)
        policy=warmup_policy or {"max_attempts":50,"max_wait_seconds":1500}
        # Source-free capability polling activates the container, without sending
        # a client inference to a mismatched/unsafe deployment.
        info = wait_capability(cfg,capability_fetch or capability,policy,root)
        _save(root/"capability.json", info)
        expected = {"experiment": VERSION, "gateway_concurrency": concurrency,
            "server_concurrency": concurrency, "max_containers":1, "model":MODEL,
            "context_length":12288, "max_total_tokens":12288,
            "app":"coliee-qwen35-9b-concurrency","cuda_graph_max_bs":concurrency,
            "gpu":"L40S:1","backend_retry":False,"exclusive_probes":True,
            "model_revision":"c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "job_volume":"coliee-qwen35-9b-concurrency-jobs","job_store_subdir":f"c{concurrency}",
            "cpu":4,"memory_mb":16384}
        if not isinstance(info,dict) or any(info.get(k) != v for k,v in expected.items()) or info.get("backend_outcome_unknown") or info.get("ready") is not True or info.get("poisoned") or info.get("stopping"):
            raise ValueError("endpoint_concurrency_or_resource_mismatch")
        # Warmup is outside the timed source workload. Never dispatch if it fails.
        warm = (warmup_fn or warmup)(cfg,policy,root/"warmup")
        if warm.get("status") != "success":
            raise ValueError("benchmark_warmup_failed")
        cached, pending = [], []
        for task in tasks:
            q = _effective(task["request"], manifest, concurrency)
            task = {**task, "effective":q}
            path = root/"cache"/(q["request_id"]+".json")
            if path.exists():
                row = load(path)
                if row.get("original_request") != task["request"] or row.get("request") != q or row.get("identity") != identity:
                    raise ValueError("benchmark_cache_identity_mismatch")
                cached.append(row)
            else: pending.append(task)
        had_reservations=any((root/"reservations"/(t["effective"]["request_id"]+".json")).exists() for t in pending)
        rows = list(cached)
        caller = caller or _default_call
        began = time.monotonic()
        def perform(task):
            q = task["effective"]
            _save(root/"reservations"/(q["request_id"]+".json"), {"request":q,"identity":identity})
            compact, normalized = None, None
            try:
                compact, receipt = caller(cfg,q,task["rendered"],catalog=task["catalog"])
                if receipt.get("finish_reason") != "stop":
                    raise runner.CompactRunError(json.dumps(receipt))
                try:
                    cleaned, cleanup = deduplicate_lists(compact)
                    normalized = runner._normalize(cleaned,q,task["binding"],task["source"])
                    receipt["exact_duplicate_cleanup"] = cleanup
                    status = "protocol_verified"
                except Exception as exc:
                    status="unresolved"
                    receipt["failure_diagnostic"]={"kind":"host_validation","error_type":type(exc).__name__}
            except runner.CompactRunError as exc:
                try: receipt=json.loads(str(exc))
                except (ValueError,TypeError): receipt={"usage":None,"failure_diagnostic":{"kind":"adapter"}}
                status="unresolved"
            except Exception as exc:
                receipt={"usage":None,"failure_diagnostic":{"kind":"unexpected_client_failure","error_type":type(exc).__name__,"outcome_unknown":True}}
                status="unresolved"
            row={"identity":identity,"request":q,"original_request":task["request"],"status":status,
                "compact_response":compact,"response":normalized,"receipt":receipt}
            _save(root/"cache"/(q["request_id"]+".json"),row)
            return row
        stop_dispatch=False
        iterator=iter(pending)
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            active={}
            def admit():
                while not stop_dispatch and len(active)<concurrency:
                    task=next(iterator,None)
                    if task is None:break
                    active[pool.submit(perform,task)]=task
            admit()
            while active:
                done,_=wait(active,return_when=FIRST_COMPLETED)
                for future in done:
                    active.pop(future)
                    row=future.result();rows.append(row)
                    rec=row["receipt"];diag=rec.get("failure_diagnostic",{})
                    if runner._blocks_dispatch(rec) or diag.get("outcome_unknown") or diag.get("kind")=="unexpected_client_failure":
                        stop_dispatch=True
                admit()
        wall=time.monotonic()-began
        order={q["request_id"]:i for i,q in enumerate(manifest["requests"])}
        rows.sort(key=lambda r:order[r["original_request"]["request_id"]])
        valid=sum(r["status"]=="protocol_verified" for r in rows)
        needs_split=sum(isinstance(r.get("compact_response"),dict) and r["compact_response"].get("coverage_status")=="needs_split" for r in rows)
        lat=[r["receipt"]["latency_ms"] for r in rows if isinstance(r["receipt"].get("latency_ms"),(int,float))]
        usages=[r["receipt"].get("usage") for r in rows]
        tokens={k:sum(u.get(k,0) for u in usages if isinstance(u,dict)) for k in ("input_tokens","output_tokens","total_tokens")}
        resumed=bool(cached) or had_reservations
        # Only a fresh uninterrupted workload is admissible as throughput evidence.
        complete=len(rows)==len(tasks)
        result={"version":VERSION,"identity":identity,"concurrency":concurrency,
            "status":"complete" if complete else "incomplete", "protocol_pass":valid==len(tasks),
            "semantic_quality_claim":False,"request_ledger":rows,"expected_count":len(tasks),
            "completed_count":len(rows),"protocol_verified":valid,"needs_split":needs_split,
            "cache_hits":len(cached),"performance_eligible":complete and not resumed,
            "measured_fresh_count":len(rows)-len(cached),"wall_seconds":wall,
            "targets_per_second":len(pending)/wall if wall and complete and not resumed else None,
            "latency_ms":{"p50":_percentile(lat,.5),"p95":_percentile(lat,.95)},
            "tokens":tokens,"usage_unavailable":sum(not isinstance(u,dict) for u in usages),
            "setup":{"warmup":warm,"included_in_workload_wall":False,
                "server_startup_warmup_usage":None,"server_startup_warmup_usage_state":"not_collected"},
            "hardware_measurement":{"gpu_hours":None,"vram_peak":None,"cpu_hours":None,"billing":None},
            "stop_dispatch":stop_dispatch}
        _save(root/"run.json",result)
        return result
    finally: lock.unlink(missing_ok=True)


def compare(output_root):
    root=Path(output_root)
    arms={str(n):load(root/f"c{n}"/"run.json") for n in (1,2,4) if (root/f"c{n}"/"run.json").exists()}
    manifests={r["identity"]["manifest_sha256"] for r in arms.values()}
    target_sets=[{row["original_request"]["request_id"] for row in r["request_ledger"]} for r in arms.values()]
    comparable=(len(arms)==3 and len(manifests)==1 and all(r["performance_eligible"] and r["status"]=="complete" and r["protocol_pass"] and r["needs_split"]==0 and
        r["completed_count"]==r["expected_count"]==len(r["request_ledger"]) and len(s)==r["expected_count"]
        for r,s in zip(arms.values(),target_sets)) and all(s==target_sets[0] for s in target_sets))
    baseline=arms.get("1")
    differences={}
    if baseline:
        base_rows={r["original_request"]["request_id"]:r for r in baseline["request_ledger"]}
        for n, arm in arms.items():
            changed=[]
            for row in arm["request_ledger"]:
                old=base_rows.get(row["original_request"]["request_id"])
                def content(r):
                    v=copy.deepcopy(r.get("compact_response")) if r else None
                    if isinstance(v,dict):v.pop("request_id",None)
                    return v
                if content(old)!=content(row):changed.append(row["original_request"]["request_id"])
            differences[n]=changed
    summary={"version":VERSION,"comparable_fresh":comparable,"semantic_review_required":True,
        "arms":{n:{k:r[k] for k in ("status","protocol_pass","concurrency","wall_seconds","targets_per_second","latency_ms","tokens","cache_hits","needs_split")} for n,r in arms.items()},
        "speedup_vs_c1":{n:baseline["wall_seconds"]/r["wall_seconds"] for n,r in arms.items() if baseline and comparable and r["wall_seconds"]>0},
        "changed_output_request_ids":differences,
        "recommendation":"needs_semantic_difference_review" if comparable else "insufficient_fresh_complete_runs"}
    _save(root/"comparison.json",summary)
    return summary
