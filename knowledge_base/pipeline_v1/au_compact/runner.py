"""Remote-capable compact AU runner; no manifest construction or provider invocation at import time."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from jsonschema import Draft202012Validator

from ..au_only.core import warmup
from ..source_contract import open_source
from .core import COMPACT_SCHEMA, COMPACT_TRANSPORT_SCHEMA, FULL_SCHEMA, CompactAUError, build_evidence_catalog, build_needs_split_sidecar, normalize_positive, validate_compact
from .manifest import _binding_path, preflight as compact_preflight, write_json
from .decoding import build_decoding
from .core import deduplicate_lists
from .jobs_client import complete_job, JobTransportError
from .prompting import PROMPT_VERSION, build_prompt, prompt_identity


NORMALIZER_VERSION = "au-compact-normalizer-v1"
RESPONSE_FORMAT_VERSION = "au-compact-request-ebnf-v4"
RENDER_VERSION = "au-compact-target-body-v1"
_COMPACT_VALIDATOR = Draft202012Validator(json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8")))
_FULL_VALIDATOR = Draft202012Validator(json.loads(FULL_SCHEMA.read_text(encoding="utf-8")))


class CompactRunError(ValueError):
    pass


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _atomic(path, value):
    write_json(path, value)


def _cache_path(root, key):
    return Path(root) / key[:2] / key / "response.json"


def _binding_digest(binding):
    return _hash({key: binding[key] for key in ("atom_map_relative_path", "atom_map_sha256", "atom_map_cache_key", "case_id", "source_hash", "segmenter_version", "policy_sha256")})


def _key(request, manifest_hash, cfg=None):
    from . import decoding
    return _hash({"manifest_sha256": manifest_hash, "request": request, "endpoint_identity": {k: (cfg or {}).get(k) for k in ("url", "model", "enable_thinking", "transport", "jobs_url", "string_decoder")}, "compact_schema_sha256": hashlib.sha256(COMPACT_SCHEMA.read_bytes()).hexdigest(), "transport_schema_sha256": hashlib.sha256(COMPACT_TRANSPORT_SCHEMA.read_bytes()).hexdigest(), "decoder_sha256": hashlib.sha256(Path(decoding.__file__).read_bytes()).hexdigest(), "prompt_version": PROMPT_VERSION, "prompt_identity": prompt_identity(), "render_version": RENDER_VERSION, "normalizer_version": NORMALIZER_VERSION, "response_format_version": RESPONSE_FORMAT_VERSION, "atom_binding_sha256": _binding_digest(request["atom_binding"])})


def _usage(body):
    raw = body.get("usage")
    if isinstance(raw, dict) and all(isinstance(raw.get(key), int) for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
        return {"input_tokens": raw["prompt_tokens"], "output_tokens": raw["completion_tokens"], "total_tokens": raw["total_tokens"]}
    return None


def _cache_observation(body):
    """Observe only OpenAI cache counters; never adjust billable usage.

    Missing/null counters are unavailable, not zero. A zero prompt has no
    defined fraction. No arbitrary provider metadata is copied to receipts.
    """
    result = {"state": "unavailable", "cached_tokens": None,
              "prompt_tokens": None, "cached_fraction": None}
    if not isinstance(body, dict) or body.get("usage") is None:
        return result
    usage = body["usage"]
    if not isinstance(usage, dict):
        return {**result, "state": "invalid"}
    prompt = usage.get("prompt_tokens")
    if prompt is not None:
        if type(prompt) is not int or prompt < 0:
            return {**result, "state": "invalid"}
        result["prompt_tokens"] = prompt
    details = usage.get("prompt_tokens_details")
    if details is None:
        return result
    if not isinstance(details, dict):
        return {**result, "state": "invalid"}
    cached = details.get("cached_tokens")
    if cached is None:
        return result
    if (type(cached) is not int or cached < 0
            or (prompt is not None and cached > prompt)):
        return {**result, "state": "invalid"}
    result.update(state="provider", cached_tokens=cached)
    if prompt:
        # Divide integers directly rather than converting huge counters first.
        result["cached_fraction"] = cached / prompt
    return result


def _render(request, catalog):
    from html import escape
    from .hints import validate_payload
    validate_payload(request, catalog)
    # Only unbound, refs-absent synthetic mocks retain the legacy whole-atom view.
    legacy = "source_refs" not in request and not any(
        key in request for key in ("source_hash", "atom_binding", "context_hint_experiment")
    )
    target_spans = []
    if not legacy:
        refs = request.get("source_refs")
        expected = request.get("expected_target_ids", [])
        if not isinstance(refs, list) or not refs or len(expected) != 1:
            raise CompactRunError("render requires source refs and one locked target")
        for ref in refs:
            start, end = ref.get("start_char"), ref.get("end_char")
            if (ref.get("role") not in {"target", "context"}
                    or type(start) is not int or type(end) is not int or not 0 <= start < end):
                raise CompactRunError("invalid render source ref")
            if ref["role"] == "target":
                if expected[0] not in ref.get("target_ids", []):
                    raise CompactRunError("render source ref does not own locked target")
                target_spans.append((start, end))
        if not target_spans:
            raise CompactRunError("render requires target source refs")
    atoms = sorted(catalog["atoms"].values(), key=lambda atom: (atom["start_char"], atom["end_char"], atom["atom_id"]))
    lines = [f"<AU_COMPACT_REGION case={request['case_id']} request={request['request_id']}>\n"]
    owned = False
    for atom in atoms:
        role = "TARGET" if atom["target_intersecting"] else "CONTEXT"
        body = atom["quote"]
        if not legacy:
            start, end = atom["start_char"], atom["end_char"]
            if len(body) != end - start:
                raise CompactRunError("render atom quote/offset mismatch")
            intersections = sorted((max(start, a), min(end, b)) for a, b in target_spans
                                   if max(start, a) < min(end, b))
            if bool(intersections) != bool(atom["target_intersecting"]):
                raise CompactRunError("render target intersection mismatch")
            if intersections:
                owned = True
                merged = []
                for a, b in intersections:
                    if merged and a <= merged[-1][1]:
                        merged[-1][1] = max(b, merged[-1][1])
                    else:
                        merged.append([a, b])
                parts, cursor = [], start
                for a, b in merged:
                    if cursor < a:
                        parts.append(("CONTEXT_PADDING", cursor, a))
                    parts.append(("TARGET_BODY", a, b))
                    cursor = b
                if cursor < end:
                    parts.append(("CONTEXT_PADDING", cursor, end))
                body = "".join(
                    f"<{tag} span={a}:{b}>" + escape(atom["quote"][a-start:b-start], quote=False)
                    + f"</{tag}>" for tag, a, b in parts
                )
            else:
                body = escape(body, quote=False)
        lines.extend((f"<{role} atom_id={atom['atom_id']} span={atom['start_char']}:{atom['end_char']}>\n", body, f"\n</{role}>\n"))
    if not legacy and not owned:
        raise CompactRunError("render has no raw target intersection")
    return "".join(lines) + "</AU_COMPACT_REGION>\n"


def _compact_schema_probe(cfg, root, opener):
    minimal = {"request_id": "probe", "target_id": "probe", "decision": "hard_negative", "coverage_status": "complete", "aus": [], "hard_negative_reason": "other", "unresolved_reason": None}
    payload = {"model": cfg["model"], "messages": [{"role": "user", "content": "Return exactly this compact schema-valid JSON, with no prose:\n" + json.dumps(minimal, separators=(",", ":"))}], "max_tokens": 128, **build_decoding("probe", "probe", ["sa-target"], ["sa-target"]), "chat_template_kwargs": {"enable_thinking": cfg.get("enable_thinking", False)}}
    identity = {"model": cfg["model"], "enable_thinking": cfg.get("enable_thinking", False), "compact_schema_sha256": hashlib.sha256(COMPACT_SCHEMA.read_bytes()).hexdigest(), "transport_schema_sha256": hashlib.sha256(COMPACT_TRANSPORT_SCHEMA.read_bytes()).hexdigest(), "request_sha256": _hash(payload)}
    try:
        with opener(urlrequest.Request(cfg["url"], data=json.dumps(payload).encode(), headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"}, method="POST"), timeout=cfg.get("timeout", 60)) as response:
            body = json.loads(response.read().decode())
        choice = body["choices"][0]; content = choice["message"]["content"]; result = json.loads(content)
        errors = list(_COMPACT_VALIDATOR.iter_errors(result))
        if choice.get("finish_reason") != "stop" or result != minimal:
            errors.append("probe incomplete or ownership/control mismatch")
        out = {"artifact_type": "AUCompactSchemaProbe", "status": "supported" if not errors else "invalid_result", "config_identity": identity, "provider_usage": body.get("usage"), "finish_reason": choice.get("finish_reason"), "content_sha256": hashlib.sha256(content.encode()).hexdigest(), "content_length": len(content), "content_preview": content[:500] if errors else None}
    except HTTPError as exc:
        out = {"artifact_type": "AUCompactSchemaProbe", "status": "http_error", "config_identity": identity, "provider_usage": None, "http_status": exc.code}
    except Exception as exc:
        out = {"artifact_type": "AUCompactSchemaProbe", "status": "invalid_result", "config_identity": identity, "provider_usage": None, "error": type(exc).__name__}
    _atomic(Path(root) / "compact_schema_probe.json", out)
    return out


def _call(cfg, request, rendered, opener, catalog=None):
    prompt = build_prompt(request, rendered)
    if not catalog or not catalog.get("atoms"):
        raise CompactRunError("request-bound decoder requires evidence catalog")
    atoms = catalog["atoms"]
    constraint = build_decoding(request["request_id"], request["expected_target_ids"][0], list(atoms), [aid for aid, atom in atoms.items() if atom["target_intersecting"]], string_mode=cfg.get("string_decoder", "bounded"))
    payload = {"model": cfg["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": request["spec"]["caps"]["output_tokens"], **constraint, "chat_template_kwargs": {"enable_thinking": cfg.get("enable_thinking", False)}}
    started = time.monotonic()
    trace = {"transport": cfg.get("transport", "direct"), "request_id": request["request_id"], "started_at_unix": time.time()}
    try:
        if cfg.get("transport", "direct") == "jobs":
            body, job_trace = complete_job(cfg, payload, opener)
            trace.update(job_trace)
        else:
            with opener(urlrequest.Request(cfg["url"], data=json.dumps(payload).encode(), headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"}, method="POST"), timeout=cfg.get("timeout", 60)) as response:
                body = json.loads(response.read().decode())
    except JobTransportError as exc:
        raise CompactRunError(json.dumps({"usage": None, "usage_state": "unavailable", "cache_observation": _cache_observation(None), "finish_reason": "host_unresolved", "latency_ms": exc.trace["latency_ms"], "transport_trace": {**trace, **exc.trace}, "failure_diagnostic": exc.trace["failure_diagnostic"]})) from exc
    except HTTPError as exc:
        # An HTTP failure can still carry provider cost; decode bounded data
        # without persisting the error text or arbitrary envelope metadata.
        error_body = None
        try:
            raw = exc.read(1024 * 1024 + 1)
            if len(raw) <= 1024 * 1024:
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    error_body = decoded
        except Exception:
            pass  # Optional accounting must not replace the HTTP diagnostic.
        finally:
            exc.close()
        usage = _usage(error_body) if error_body is not None else None
        raise CompactRunError(json.dumps({"usage": usage, "usage_state": "provider" if usage else "unavailable", "cache_observation": _cache_observation(error_body), "finish_reason": "host_unresolved", "latency_ms": round((time.monotonic() - started) * 1000, 3), "transport_trace": trace, "failure_diagnostic": {"kind": "http", "http_status": exc.code, "retryable": exc.code == 429 or 500 <= exc.code <= 599}}))
    except (URLError, TimeoutError, OSError) as exc:
        raise CompactRunError(json.dumps({"usage": None, "usage_state": "unavailable", "cache_observation": _cache_observation(None), "finish_reason": "host_unresolved", "latency_ms": round((time.monotonic() - started) * 1000, 3), "transport_trace": trace, "failure_diagnostic": {"kind": "transport", "detail": type(exc).__name__, "retryable": True}}))
    except (ValueError, UnicodeError) as exc:
        raise CompactRunError(json.dumps({"usage": None, "usage_state": "unavailable", "cache_observation": _cache_observation(None), "finish_reason": "host_unresolved", "latency_ms": round((time.monotonic() - started) * 1000, 3), "transport_trace": trace, "failure_diagnostic": {"kind": "malformed_envelope", "detail": type(exc).__name__}})) from exc
    if not isinstance(body, dict):
        raise CompactRunError("provider envelope must be an object")
    trace["finished_at_unix"] = time.time()
    usage = _usage(body); receipt = {"usage": usage, "usage_state": "provider" if usage else "unavailable", "cache_observation": _cache_observation(body), "finish_reason": "unknown", "latency_ms": round((time.monotonic() - started) * 1000, 3), "transport_trace": trace}
    try:
        receipt["finish_reason"] = body["choices"][0].get("finish_reason", "unknown")
        content = body["choices"][0]["message"]["content"]
        receipt["raw_response"] = content
        if receipt["finish_reason"] != "stop":
            receipt["failure_diagnostic"] = {"kind": "output_truncated" if receipt["finish_reason"] == "length" else "incomplete_generation", "content_length": len(content) if isinstance(content, str) else 0}
            raise CompactRunError(json.dumps(receipt))
        return json.loads(content), receipt
    except CompactRunError:
        raise
    except Exception as exc:
        content = locals().get("content", "")
        raise CompactRunError(json.dumps({**receipt, "failure_diagnostic": {"kind": "malformed_response", "detail": type(exc).__name__, "content_sha256": hashlib.sha256(content.encode()).hexdigest() if isinstance(content, str) else None, "content_length": len(content) if isinstance(content, str) else 0, "content_preview": content[:2000] if isinstance(content, str) else None}}))


def _terminal_full(request, decision, reason):
    result = {"schema_version": "plan10-au-model-output-v1", "request_id": request["request_id"], "processed_target_ids": request["expected_target_ids"], "target_results": [{"target_id": request["expected_target_ids"][0], "decision": decision, "authority_units": [], "hard_negative_reason": reason if decision == "hard_negative" else None, "unresolved_reason": reason if decision == "unresolved" else None, "reason_detail": "output_truncated" if decision == "unresolved" and reason == "other" else None}], "context_requests": [], "warnings": []}
    errors = list(_FULL_VALIDATOR.iter_errors(result))
    if errors:
        raise CompactRunError("terminal full normalization invalid")
    return result


def _normalize(value, request, binding, source):
    validate_compact(value, request)
    if value["decision"] == "positive":
        return normalize_positive(value, request, binding, source)
    if value["decision"] == "hard_negative":
        return _terminal_full(request, "hard_negative", value["hard_negative_reason"])
    return _terminal_full(request, "unresolved", value["unresolved_reason"])


def _retryable(row):
    receipt = row.get("receipt", {}); diagnostic = receipt.get("failure_diagnostic", {})
    return row.get("status") == "unresolved" and receipt.get("usage_state") == "unavailable" and diagnostic.get("retryable") is True


def _blocks_dispatch(receipt):
    return receipt.get("failure_diagnostic", {}).get("kind") in {"job_wait_timeout", "job_interrupted", "transport"}


def _record_usage(ledger, receipt, job_key=None):
    fields = (("actual_input_tokens", "input_tokens"), ("actual_output_tokens", "output_tokens"), ("actual_total_tokens", "total_tokens"))
    if receipt.get("usage_state") == "not_called":
        return
    if job_key is not None:
        if job_key in ledger["job_receipts"]:
            prior = ledger["job_receipts"][job_key]
            if prior is None:
                ledger["usage_unavailable"] -= 1
            else:
                for name, field in fields:
                    ledger[name] -= prior[field]
        ledger["job_receipts"][job_key] = receipt.get("usage") if receipt.get("usage_state") == "provider" else None
    if receipt.get("usage_state") == "provider":
        for name, field in fields:
            ledger[name] += receipt["usage"][field]
    else:
        ledger["usage_unavailable"] += 1


def run(manifest, *, source_store, atom_root, cfg, budget, cache_dir, execute=False, opener=urlrequest.urlopen, warmup_policy=None, retry_provider_unavailable=False, request_ids=None):
    if not execute:
        raise CompactRunError("compact remote execution requires --execute")
    all_requests = manifest.get("requests", [])
    if any(request["spec"].get("model") != cfg.get("model") or request["spec"].get("enable_thinking") != cfg.get("enable_thinking", False) for request in all_requests):
        raise CompactRunError("runtime config does not match compact locked spec")
    preflight = compact_preflight(manifest, source_store, atom_root)
    if preflight["status"] != "pass":
        raise CompactRunError("compact preflight failed")
    known = [request.get("request_id") for request in all_requests]
    if len(known) != len(set(known)):
        raise CompactRunError("compact manifest has duplicate request IDs")
    if request_ids is None:
        selected_ids = known
    else:
        if not request_ids or len(request_ids) != len(set(request_ids)):
            raise CompactRunError("selection must be non-empty and unique")
        unknown = set(request_ids) - set(known)
        if unknown:
            raise CompactRunError("unknown selected request ID")
        selected_ids = [request_id for request_id in known if request_id in set(request_ids)]
    requests = [request for request in all_requests if request["request_id"] in set(selected_ids)]
    root = Path(cache_dir).parent
    resume_jobs = cfg.get("transport") == "jobs" and (root / "runtime_ledger.json").is_file()
    if resume_jobs:
        # A persisted job may be running: polling must not wait behind a fresh probe.
        warm = json.loads((root / "warmup/warmup.json").read_text(encoding="utf-8"))
        probe = json.loads((root / "compact_schema_probe.json").read_text(encoding="utf-8"))
    else:
        warm = warmup(cfg, warmup_policy or {"max_attempts": 10}, root / "warmup", opener)
    if warm["status"] != "success":
        raise CompactRunError("compact warmup failed before source dispatch")
    if not resume_jobs:
        probe = _compact_schema_probe(cfg, root, opener)
    if probe["status"] != "supported":
        raise CompactRunError("compact schema probe failed before source dispatch")
    manifest_hash = _hash(manifest)
    selection_identity = _hash({"manifest_sha256": manifest_hash, "request_ids": selected_ids, "decoder_version": RESPONSE_FORMAT_VERSION, "prompt_identity": prompt_identity(), "render_version": RENDER_VERSION, "endpoint": {k: cfg.get(k) for k in ("url", "model", "transport", "jobs_url", "string_decoder")}})
    rows = []
    ledger = {"manifest_sha256": manifest_hash, "selection_identity": selection_identity, "selection_request_ids": selected_ids, "requests": 0, "provider_attempts": 0, "reserved_input_tokens": 0, "reserved_output_tokens": 0, "actual_input_tokens": 0, "actual_output_tokens": 0, "actual_total_tokens": 0, "usage_unavailable": 0}
    ledger_path = root / "runtime_ledger.json"
    if ledger_path.is_file():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if ledger.get("manifest_sha256") != manifest_hash or ledger.get("selection_identity") != selection_identity:
            raise CompactRunError("compact runtime ledger identity mismatch")
    ledger.setdefault("job_reservations", [])
    ledger.setdefault("job_receipts", {})
    for request in requests:
        key = _key(request, manifest_hash, cfg); path = _cache_path(cache_dir, key)
        if path.is_file():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("cache_key") != key or row.get("request") != request:
                raise CompactRunError("stale compact cache")
            if retry_provider_unavailable and _retryable(row):
                archive = path.parent / "attempt_history"; archive.mkdir(exist_ok=True); _atomic(archive / (_hash(row)[:16] + ".json"), {"superseded_reason": "retry_provider_unavailable", "prior": row}); path.unlink()
            else:
                if cfg.get("transport") == "jobs":
                    # Recover the cache->ledger crash window without double accounting.
                    _record_usage(ledger, row["receipt"], key)
                    _atomic(ledger_path, ledger)
                rows.append(row)
                if _blocks_dispatch(row.get("receipt", {})):
                    break
                continue
        source = open_source(source_store, request["case_id"], request["source_hash"])
        binding = _binding_path(request["atom_binding"], atom_root)
        catalog = build_evidence_catalog(request, binding, source)
        rendered = _render(request, catalog)
        # Conservative reservation, not a tokenizer measurement: includes the
        # instructions/examples missing from the source-only catalog estimate.
        input_estimate = len(build_prompt(request, rendered).encode("utf-8"))
        prompt_meta = {"prompt_identity": prompt_identity(), "estimated_input_tokens": input_estimate, "input_estimate_method": "full_prompt_utf8_bytes"}
        output_reservation = request["spec"]["caps"]["output_tokens"]
        recovering_job = cfg.get("transport") == "jobs" and key in ledger["job_reservations"]
        if not recovering_job and (ledger["requests"] + 1 > budget["max_requests"] or ledger["provider_attempts"] + 1 > budget["max_provider_attempts"] or ledger["reserved_input_tokens"] + input_estimate > budget["max_total_input_tokens"] or ledger["reserved_output_tokens"] + output_reservation > budget["max_total_output_tokens"]):
            row = {"cache_key": key, "request": request, "status": "budget_stopped", "response": None, "receipt": {"usage": None, "usage_state": "not_called", "cache_observation": _cache_observation(None), "finish_reason": "host_unresolved", "stop_reason": "aggregate_budget", **prompt_meta}}; _atomic(path, row); rows.append(row); continue
        if not recovering_job:
            ledger["requests"] += 1; ledger["provider_attempts"] += 1
            ledger["reserved_input_tokens"] += input_estimate; ledger["reserved_output_tokens"] += output_reservation
            if cfg.get("transport") == "jobs":
                ledger["job_reservations"].append(key)
        # Persist reservation before submission, including when an acknowledgement is lost.
        _atomic(ledger_path, ledger)
        compact = None; normalized = None
        try:
            compact, receipt = _call(cfg, request, rendered, opener, catalog=catalog)
            if receipt["finish_reason"] in {"length", "content_filter"}:
                normalized = _terminal_full(request, "unresolved", "other"); receipt["failure_diagnostic"] = {"kind": "output_truncated"}; status = "unresolved"
            else:
                try:
                    cleaned, cleanup = deduplicate_lists(compact)
                    receipt["exact_duplicate_cleanup"] = cleanup
                    normalized = _normalize(cleaned, request, binding, source); status = "protocol_verified"
                except (CompactAUError, CompactRunError) as exc:
                    normalized = _terminal_full(request, "unresolved", "other"); receipt["failure_diagnostic"] = {"kind": "host_validation", "detail": str(exc)}; status = "unresolved"
        except CompactRunError as exc:
            try: receipt = json.loads(str(exc))
            except json.JSONDecodeError: receipt = {"usage": None, "usage_state": "unavailable", "finish_reason": "host_unresolved", "failure_diagnostic": {"kind": "adapter"}}
            normalized = _terminal_full(request, "unresolved", "other"); status = "unresolved"
        receipt.update(prompt_meta)
        receipt.setdefault("cache_observation", _cache_observation(None))
        _record_usage(ledger, receipt, key if cfg.get("transport") == "jobs" else None)
        row = {"cache_key": key, "request": request, "compact_response": compact, "response": normalized, "receipt": receipt, "status": status, "catalog_metrics": catalog["metrics"]}; _atomic(path, row)
        if isinstance(compact, dict) and compact.get("coverage_status") == "needs_split":
            _atomic(root / "needs_split" / (key + ".json"), build_needs_split_sidecar(compact, normalized if compact.get("decision") == "positive" else None))
        rows.append(row); _atomic(ledger_path, ledger)
        if _blocks_dispatch(receipt):
            # A request may still be running. Do not cascade new inference calls.
            break
    pending_ids = [rid for rid in selected_ids if rid not in {row["request"]["request_id"] for row in rows}]
    return {"artifact_type": "AUCompactRun", "schema_version": "au-compact-runtime-v1", "semantic_gold": False, "semantic_quality_claim": False, "pending_request_ids": pending_ids, "status": "complete" if not pending_ids and all(row["status"] == "protocol_verified" for row in rows) else "incomplete", "manifest_sha256": manifest_hash, "selection_request_ids": selected_ids, "selection_identity": selection_identity, "preflight": preflight, "warmup": warm, "compact_schema_probe": probe, "runtime_ledger": ledger, "request_ledger": rows}
