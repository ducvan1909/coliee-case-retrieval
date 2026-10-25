"""Plan22 paired execution adapter; imports and dry runs never contact a provider."""
from __future__ import annotations

import hashlib
import io
import json
import os
import time
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError

from ..au_compact import runner as compact
from ..au_compact.core import build_evidence_catalog, deduplicate_lists
from ..au_compact.decoding import build_decoding
from ..au_compact.jobs_client import payload_digest
from ..au_compact.manifest import _binding_path
from ..au_compact.prompting import build_prompt
from ..au_only.core import warmup
from ..source_contract import open_source
from .transport import PairedTransport

CONFIG_KEYS = ("url", "jobs_url", "model", "enable_thinking", "transport",
               "string_decoder", "expected_model_revision", "timeout",
               "job_wait_seconds", "job_poll_seconds")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def runtime_identity(workload, cfg):
    return compact._hash({"workload": workload, "config": {k: cfg.get(k) for k in CONFIG_KEYS},
                          "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          "transport_sha256": hashlib.sha256(Path(__file__).with_name("transport.py").read_bytes()).hexdigest()})


def receipt_key(request, identity, cfg):
    return compact._key(request, identity, cfg)


def _immutable(path, value):
    if path.exists():
        if _read(path) != value:
            raise PairedRunError("immutable receipt conflict")
        return
    compact._atomic(path, value)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _Accounting:
    """Checkpoint before dispatch; duplicate jobs need a durable recovery permit."""

    def __init__(self, root, ledger, budget, opener):
        self.root, self.ledger, self.budget, self.opener = root, ledger, budget, opener
        self.phase = "extraction"
        self.block_reason = None
        self.recovery_proof = None

    def block(self, reason):
        self.block_reason = reason
        raise PairedRunError(reason)

    def save(self):
        compact._atomic(self.root / "runtime_ledger.json", self.ledger)

    def __call__(self, req, **kwargs):
        ledger = self.ledger
        method = req.get_method()
        if method == "GET":
            ledger["get_polls"] += 1
            self.save()
            outcome = {"url": req.full_url, "http_status": None, "mode": "unknown"}
            try:
                with self.opener(req, **kwargs) as response:
                    raw = response.read()
                    outcome["http_status"] = getattr(response, "status", 200)
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeError):
                    body = None
                outcome["mode"] = "health" if req.full_url.endswith("/health") else "job"
                if isinstance(body, dict) and body.get("job_id"):
                    ledger.setdefault("observed_jobs", {})[body["job_id"]] = body.get("status")
                return _Response(raw)
            except HTTPError as exc:
                raw = exc.read()
                outcome["http_status"] = exc.code
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeError):
                    body = None
                outcome["mode"] = "authoritative_unknown" if exc.code == 404 and body == {"detail": "Unknown job"} else "http_error"
                raise HTTPError(exc.url, exc.code, exc.reason, exc.headers, io.BytesIO(raw)) from exc
            except Exception as exc:
                outcome.update(mode="transport_error", error=type(exc).__name__)
                raise
            finally:
                ledger["last_get"] = outcome
                ledger.setdefault("last_get_outcomes", {})[req.full_url] = outcome
                self.save()
        if method != "POST":
            raise PairedRunError("unsupported transport method")
        wire = json.loads(req.data)
        payload = wire.get("payload", wire)
        job = wire.get("job_id")
        if job is not None and job != payload_digest(payload):
            raise PairedRunError("job payload identity mismatch")
        prior = [a for a in ledger["attempts"] if job and a.get("job_id") == job]
        proof = self.recovery_proof
        self.recovery_proof = None
        recovery = ledger.setdefault("job_recovery", {}).get(job, {}) if job else {}
        if prior:
            observations = (proof or {}).get("observations", [])
            if (len(prior) >= 2 or recovery.get("retry_used") or not proof or proof.get("job_id") != job
                    or proof.get("gateway_url") != req.full_url.rstrip("/")
                    or len(observations) != 2
                    or any(o.get("http_status") != 404 or o.get("detail") != "Unknown job"
                           or o.get("job_url") != req.full_url.rstrip("/") + "/" + job
                           or o.get("health", {}).get("ready") is not True for o in observations)
                    or observations[1]["observed_monotonic"] - observations[0]["observed_monotonic"] < proof["backoff_seconds"]
                    or job in ledger.get("observed_jobs", {})
                    or any(a.get("acknowledgement") == "received" for a in prior)):
                self.block("acknowledgement uncertain: fresh bounded recovery proof required")
        inp = sum(len(m.get("content", "").encode("utf-8")) for m in payload["messages"])
        out = payload["max_tokens"]
        if (ledger["provider_attempts"] >= min(100, self.budget["max_provider_attempts"])
                or ledger["reserved_input_tokens"] + inp > self.budget["max_total_input_tokens"]
                or ledger["reserved_output_tokens"] + out > self.budget["max_total_output_tokens"]):
            self.block("aggregate POST/reservation budget exhausted")
        if self.phase == "warmup" and ledger["warmup_attempts"] >= 50:
            self.block("persistent warmup attempt cap exhausted")
        if self.phase == "probe" and ledger["probe_attempts"] >= 2:
            self.block("persistent decoder probe cap exhausted")
        if job and proof:
            recovery = ledger.setdefault("job_recovery", {}).setdefault(job, {})
            recovery.update(last_absence_proof=proof)
            if prior:
                recovery.update(retry_used=True, retry_ordinal=ledger["provider_attempts"] + 1)
            self.save()  # Proof/one-shot permit is durable BEFORE dispatch, even if ACK is lost.
        ordinal = ledger["provider_attempts"] + 1
        attempt = {"ordinal": ordinal, "phase": self.phase, "job_id": job,
                   "payload_sha256": payload_digest(payload), "http_bytes": len(req.data),
                   "reserved_input_tokens": inp, "reserved_output_tokens": out,
                   "input_estimate_method": "full_prompt_utf8_bytes", "usage": None,
                   "usage_state": "unknown", "started_at_unix": time.time()}
        ledger["attempts"].append(attempt)
        ledger["provider_attempts"] = ordinal
        ledger["reserved_input_tokens"] += inp
        ledger["reserved_output_tokens"] += out
        if self.phase in {"warmup", "probe"}:
            ledger[self.phase + "_attempts"] += 1
        self.save()
        started = time.monotonic()
        try:
            with self.opener(req, **kwargs) as response:
                raw = response.read()
            body = json.loads(raw)
            if job and isinstance(body, dict) and body.get("status"):
                ledger.setdefault("observed_jobs", {})[job] = body["status"]
            usage = compact._usage(body) if isinstance(body, dict) else None
            attempt.update(usage=usage, usage_state="provider" if usage else "unknown",
                           acknowledgement="received")
            return _Response(raw)
        except HTTPError as exc:
            attempt["http_status"] = exc.code
            # A generic 503 is not evidence of nonacceptance. Require explicit
            # source-free gateway fields; preserve the body for jobs_client.
            raw = exc.read()
            try:
                diagnostic = json.loads(raw)
            except (ValueError, UnicodeError):
                diagnostic = None
            attempt["provably_not_accepted"] = bool(
                job and exc.code == 503 and isinstance(diagnostic, dict)
                and diagnostic.get("accepted") is False
                and diagnostic.get("error") == "provider_unavailable")
            raise HTTPError(exc.url, exc.code, exc.reason, exc.headers, io.BytesIO(raw)) from exc
        finally:
            attempt["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
            _immutable(self.root / "attempt_receipts" / f"{ordinal:03d}.json", dict(attempt))
            self.save()


def _probe(cfg, root, counted):
    """Source-free probe using the extraction generator and string mode."""
    minimal = {"request_id": "probe", "target_id": "probe", "decision": "hard_negative",
               "coverage_status": "complete", "aus": [], "hard_negative_reason": "other",
               "unresolved_reason": None}
    payload = {"model": cfg["model"], "temperature": 0, "max_tokens": 128,
               "messages": [{"role": "user", "content": "Return exactly this JSON:\n" + json.dumps(minimal)}],
               "chat_template_kwargs": {"enable_thinking": False},
               **build_decoding("probe", "probe", ["sa-target"], ["sa-target"],
                                string_mode=cfg["string_decoder"])}
    counted.phase = "probe"
    try:
        req = urlrequest.Request(cfg["url"], data=json.dumps(payload).encode(),
                                 headers={"Authorization": "Bearer " + cfg["token"],
                                          "Content-Type": "application/json"}, method="POST")
        with counted(req, timeout=cfg.get("timeout", 60)) as response:
            body = json.loads(response.read())
        choice = body["choices"][0]
        value = json.loads(choice["message"]["content"])
        ok = choice.get("finish_reason") == "stop" and value == minimal
        result = {"status": "supported" if ok else "invalid_result",
                  "usage": compact._usage(body), "usage_state": "provider" if compact._usage(body) else "unknown"}
    except PairedRunError:
        raise
    except Exception as exc:
        result = {"status": "failed", "usage": None, "usage_state": "unknown",
                  "error": type(exc).__name__}
    path = root / "probe_receipts" / f"{counted.ledger['probe_attempts']:02d}.json"
    _immutable(path, result)
    counted.ledger["probe"] = result
    counted.save()
    return result


class PairedRunError(ValueError):
    """A locked identity, execution gate, or persistent budget was violated."""


def run(workload, *, source_store, atom_root, cfg, budget, output_root,
        execute=False, smoke=False, opener=urlrequest.urlopen, warmup_policy=None,
        clock=time.monotonic, sleep=time.sleep):
    """Validate the immutable workload before any execution."""
    from .preflight import validate_workload, preflight
    validate_workload(workload, source_store, atom_root, cfg=cfg)
    if not execute:
        return {"artifact_type": "AUContextPairedRun", "status": "not_executed",
                "workload_sha256": workload["workload_sha256"],
                "semantic_gold": False, "semantic_quality_claim": False,
                "request_ledger": [], "runtime_ledger": {}, "execution_ledger": {}}
    if (cfg.get("model") != "Qwen/Qwen3.5-9B" or cfg.get("enable_thinking") is not False
            or cfg.get("transport") != "jobs" or cfg.get("string_decoder") != "host_validated"
            or not cfg.get("jobs_url")):
        raise PairedRunError("paired runtime requires locked 9B, thinking=false, jobs, host_validated")
    for name in ("max_requests", "max_provider_attempts", "max_total_input_tokens", "max_total_output_tokens"):
        if type(budget.get(name)) is not int or budget[name] <= 0:
            raise PairedRunError("invalid operator budget")
    checked = preflight(workload, source_store=source_store, atom_root=atom_root,
                        cfg=cfg, budget=budget)
    if checked["status"] != "pass":
        raise PairedRunError("paired preflight budget gate: " + "; ".join(checked["failures"]))
    requests = workload["manifest"]["requests"]
    ids = [r["request_id"] for r in requests]
    smoke_ids = workload["smoke_request_ids"]
    if (len(ids) != len(set(ids)) or len(ids) > 34 or not smoke_ids
            or len(smoke_ids) != len(set(smoke_ids)) or not set(smoke_ids) <= set(ids)):
        raise PairedRunError("invalid locked physical/smoke workload")
    if any(r["spec"]["caps"]["output_tokens"] != 800 for r in requests):
        raise PairedRunError("extraction cap must remain 800")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    # Exclusive writer: another process cannot race the pre-dispatch reservation.
    lock = root / ".runner.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise PairedRunError("runner lock exists; confirm stopped process before removing lock") from None
    os.close(fd)
    try:
        return _execute(workload, requests, source_store, atom_root, cfg, budget,
                        root, smoke, opener, warmup_policy, clock=clock, sleep=sleep)
    finally:
        lock.unlink()


def _execute(workload, requests, source_store, atom_root, cfg, budget, root, smoke, opener, warmup_policy,
             *, clock=time.monotonic, sleep=time.sleep):
    identity = runtime_identity(workload, cfg)
    path = root / "runtime_ledger.json"
    ledger = _read(path) if path.exists() else {
        "identity": identity, "workload_sha256": workload["workload_sha256"],
        "provider_attempts": 0, "get_polls": 0, "warmup_attempts": 0, "probe_attempts": 0,
        "requests": 0, "reserved_input_tokens": 0, "reserved_output_tokens": 0,
        "attempts": [], "reservations": {}, "terminal": {}, "smoke_gate": "pending"}
    if ledger.get("identity") != identity:
        raise PairedRunError("stale workload/runtime ledger identity")
    # Recover an attempt-receipt -> ledger crash window without changing the
    # pre-dispatch counters or inventing usage for a lost acknowledgement.
    for attempt in ledger["attempts"]:
        receipt_path = root / "attempt_receipts" / f"{attempt['ordinal']:03d}.json"
        if receipt_path.exists():
            prior = _read(receipt_path)
            if any(prior.get(k) != attempt.get(k) for k in
                   ("ordinal", "phase", "payload_sha256", "job_id")):
                raise PairedRunError("attempt receipt identity mismatch")
            attempt.update(prior)
    if ledger.get("probe") is None:
        probe_path = root / "probe_receipts" / f"{ledger['probe_attempts']:02d}.json"
        if probe_path.exists():
            ledger["probe"] = _read(probe_path)
    counted = _Accounting(root, ledger, budget, opener)
    counted.save()
    selected = workload["smoke_request_ids"] if smoke else [r["request_id"] for r in requests]

    def report(reason=None):
        rows = [_read(root / "receipts" / (ledger["terminal"][rid] + ".json"))
                for rid in selected if rid in ledger["terminal"]]
        pending = [rid for rid in selected if rid not in ledger["terminal"]]
        all_rows = [_read(root / "receipts" / (key + ".json")) for key in ledger["terminal"].values()]
        jobs = {}
        for row in all_rows:
            job = row["receipt"].get("transport_trace", {}).get("job_id")
            if job:
                jobs[job] = row["receipt"].get("usage")
        usage = []
        seen = set()
        for attempt in ledger["attempts"]:
            job = attempt.get("job_id")
            if attempt.get("provably_not_accepted"):
                usage.append(attempt.get("usage"))
            elif job and job in jobs and job not in seen:
                usage.append(jobs[job]); seen.add(job)
            elif not job or job not in jobs:
                usage.append(attempt.get("usage"))
        recovered_usage = [u for job, u in jobs.items() if job not in seen]
        # Previously completed server jobs are observations, not new billing.
        usage += recovered_usage
        result = {"artifact_type": "AUContextPairedRun", "schema_version": "au-context-paired-runtime-v1",
                  "workload_sha256": workload["workload_sha256"], "identity": identity,
                  "semantic_gold": False, "semantic_quality_claim": False,
                  "status": "complete" if not reason and not pending and all(r["status"] == "protocol_verified" for r in rows) else "incomplete",
                  "stop_reason": reason, "pending_request_ids": pending, "request_ledger": rows,
                  "runtime_ledger": ledger, "smoke_gate": ledger["smoke_gate"],
                  "execution_ledger": ledger,
                  "usage_state": "unknown" if any(u is None for u in usage) else "provider",
                  "known_total_tokens": sum(u["total_tokens"] for u in usage if u is not None),
                  "unknown_usage_count": sum(u is None for u in usage),
                  "usage_attribution": "observed_provider_usage; not verified new billing",
                  "server_recovered_jobs_without_POST": len(recovered_usage),
                  "current_run_provider_POST_attempts": ledger["provider_attempts"],
                  "actual_total_tokens": None if any(u is None for u in usage) else sum(u["total_tokens"] for u in usage)}
        compact._atomic(root / ("smoke_report.json" if smoke else "run_report.json"), result)
        compact._atomic(root / "run.json", result)
        return result

    if (ledger["provider_attempts"] > min(100, budget["max_provider_attempts"])
            or ledger["requests"] > min(34, budget["max_requests"])
            or ledger["reserved_input_tokens"] > budget["max_total_input_tokens"]
            or ledger["reserved_output_tokens"] > budget["max_total_output_tokens"]):
        return report("persisted spending exceeds operator caps")

    if not smoke and ledger["smoke_gate"] != "pass":
        return report("persisted successful smoke required")
    if not smoke:
        gate_path = root / "smoke_gate.json"
        if not gate_path.exists():
            return report("smoke gate receipt missing")
        gate = _read(gate_path)
        smoke_rows = []
        for rid in workload["smoke_request_ids"]:
            key = ledger["terminal"].get(rid)
            if not key or not (root / "receipts" / (key + ".json")).exists():
                return report("smoke physical receipt missing")
            row = _read(root / "receipts" / (key + ".json"))
            digest = compact._hash({k: v for k, v in row.items() if k != "row_sha256"})
            if row.get("row_sha256") != digest or row.get("status") != "protocol_verified":
                return report("smoke physical receipt invalid")
            smoke_rows.append(digest)
        if gate != {"identity": identity, "request_ids": workload["smoke_request_ids"],
                    "status": "pass", "receipt_sha256": smoke_rows}:
            return report("smoke gate identity mismatch")
    try:
        # Recover local receipts before any readiness, warmup or decoder network work.
        for request in requests:
            rid = request["request_id"]
            if rid not in selected:
                continue
            key = receipt_key(request, identity, cfg)
            receipt_path = root / "receipts" / (key + ".json")
            if receipt_path.exists():
                row = _read(receipt_path)
                if (row.get("cache_key") != key or row.get("request") != request
                        or row.get("row_sha256") != compact._hash({k: v for k, v in row.items() if k != "row_sha256"})):
                    raise PairedRunError("corrupt or stale physical receipt")
                ledger["terminal"][rid] = key
        counted.save()
        pending_network = any(rid not in ledger["terminal"] for rid in selected)
        transport = PairedTransport(cfg, counted, clock=clock, sleep=sleep)
        if pending_network:
            transport.ensure_ready(timeout=cfg.get("timeout", 60))
        if pending_network and ledger.get("warmup", {}).get("status") != "success":
            policy = dict(warmup_policy or {"max_attempts": 10, "max_wait_seconds": 600})
            policy["max_attempts"] = min(50, policy["max_attempts"]) - ledger["warmup_attempts"]
            ledger.setdefault("warmup_started_at_unix", time.time())
            policy["max_wait_seconds"] = min(policy.get("max_wait_seconds", 600),
                                              600 - (time.time() - ledger["warmup_started_at_unix"]))
            if policy["max_attempts"] <= 0 or policy["max_wait_seconds"] <= 0:
                return report("persistent warmup cap exhausted")
            counted.phase = "warmup"
            ledger["warmup"] = warmup(cfg, policy, root / "warmup" / str(ledger["warmup_attempts"]), counted)
            counted.save()
            if ledger["warmup"]["status"] != "success":
                return report("warmup failed")
        if pending_network and ledger.get("probe", {}).get("status") != "supported":
            if _probe(cfg, root, counted)["status"] != "supported":
                return report("decoder probe failed")
        counted.phase = "extraction"
        for request in requests:
            rid = request["request_id"]
            if rid not in selected:
                continue
            key = compact._key(request, identity, cfg)
            receipt_path = root / "receipts" / (key + ".json")
            if receipt_path.exists():
                row = _read(receipt_path)
                if row.get("cache_key") != key or row.get("request") != request:
                    raise PairedRunError("stale physical receipt")
                if row.get("row_sha256") != compact._hash({k: v for k, v in row.items() if k != "row_sha256"}):
                    raise PairedRunError("corrupt immutable receipt")
                ledger["terminal"][rid] = key
                counted.save()
                continue
            source = open_source(source_store, request["case_id"], request["source_hash"])
            binding = _binding_path(request["atom_binding"], atom_root)
            catalog = build_evidence_catalog(request, binding, source)
            rendered = compact._render(request, catalog)
            inp = len(build_prompt(request, rendered).encode("utf-8"))
            if rid not in ledger["reservations"]:
                if ledger["requests"] >= min(34, budget["max_requests"]):
                    return report("unique extraction budget exhausted")
                ledger["requests"] += 1
                ledger["reservations"][rid] = {"cache_key": key, "prompt_bytes": inp,
                                                 "output_tokens": 800}
                counted.save()
            compact_value = None
            receipt = None
            try:
                compact_value, receipt = compact._call(cfg, request, rendered, transport, catalog=catalog)
                if receipt.get("finish_reason") != "stop":
                    receipt["failure_diagnostic"] = {"kind": "output_truncated" if receipt.get("finish_reason") == "length" else "incomplete_generation"}
                    raise compact.CompactRunError(json.dumps(receipt))
                cleaned, cleanup = deduplicate_lists(compact_value)
                normalized = compact._normalize(cleaned, request, binding, source)
                receipt["exact_duplicate_cleanup"] = cleanup
                status = "protocol_verified"
            except compact.CompactRunError as exc:
                if counted.block_reason:
                    return report(counted.block_reason)
                prior_receipt = receipt
                try:
                    receipt = json.loads(str(exc))
                except ValueError:
                    receipt = {**(prior_receipt or {"usage": None, "usage_state": "unknown"}),
                               "failure_diagnostic": {"kind": "host_validation"}}
                if receipt.get("failure_diagnostic", {}).get("kind") in {"job_wait_timeout", "job_interrupted", "transport"}:
                    _immutable(root / "pending_receipts" / (key + f"-{ledger['get_polls']}.json"), receipt)
                    return report("job pending; resume polls same payload")
                normalized = compact._terminal_full(request, "unresolved", "other")
                status = "unresolved"
            except ValueError as exc:
                if counted.block_reason:
                    return report(counted.block_reason)
                receipt = {**(receipt or {"usage": None, "usage_state": "unknown"}),
                           "failure_diagnostic": {"kind": "host_validation", "error": type(exc).__name__}}
                normalized = compact._terminal_full(request, "unresolved", "other")
                status = "unresolved"
            receipt.update(estimated_input_tokens=inp, input_estimate_method="full_prompt_utf8_bytes")
            # jobs_client may expose arbitrary gateway error text; keep only
            # bounded operational diagnostics, never copy that text to reports.
            for diagnostic in (receipt.get("failure_diagnostic", {}),
                               receipt.get("transport_trace", {}).get("failure_diagnostic", {})):
                if isinstance(diagnostic, dict):
                    diagnostic.pop("server_error", None)
            job = receipt.get("transport_trace", {}).get("job_id")
            receipt["provider_POST_attempts_for_job"] = sum(a.get("job_id") == job for a in ledger["attempts"]) if job else None
            receipt["usage_attribution"] = "observed_provider_usage; new billing unverified"
            receipt["server_recovered_without_POST"] = bool(job and receipt["provider_POST_attempts_for_job"] == 0)
            if receipt.get("usage_state") == "unavailable":
                receipt["usage_state"] = "unknown"
            row = {"cache_key": key, "request": request, "status": status,
                   "compact_response": compact_value, "response": normalized, "receipt": receipt,
                   "catalog_metrics": catalog["metrics"]}
            row["row_sha256"] = compact._hash(row)
            _immutable(receipt_path, row)
            ledger["terminal"][rid] = key
            counted.save()
        if smoke:
            rows = [_read(root / "receipts" / (ledger["terminal"][rid] + ".json")) for rid in selected]
            ledger["smoke_gate"] = "pass" if all(row["status"] == "protocol_verified" for row in rows) else "fail"
            _immutable(root / "smoke_gate.json", {"identity": identity, "request_ids": selected,
                                                  "status": ledger["smoke_gate"],
                                                  "receipt_sha256": [r["row_sha256"] for r in rows]})
            counted.save()
        return report()
    except PairedRunError as exc:
        return report(str(exc))
