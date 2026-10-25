"""Optional unprobed SGLang jobs EBNF transport with compact repair wire."""
from __future__ import annotations

import json

from ..au_candidate_store.core import _hash
from ..au_compact.jobs_client import complete_job
from ..au_compact.jobs_client import JobTransportError
from .core import MODEL, POLICY
from .wire import payload, bound_messages
from .selection import VERSION, model_catalog


class JobsAdapter:
    is_mock = False

    def __init__(self, cfg):
        if cfg.get("model") != MODEL or cfg.get("enable_thinking", False):
            raise ValueError("locked_model_thinking_mismatch")
        if not cfg.get("jobs_url") or not cfg.get("token"):
            raise ValueError("jobs_configuration_required")
        self.cfg = dict(cfg)
        self.identity = {"kind": "jobs_ebnf_selection_host_v1", "wire_version": VERSION, "model": MODEL,
            "endpoint_sha256": _hash({k: cfg.get(k) for k in ("url", "jobs_url")}),
            "thinking": False, "decoder_status": "unverified"}

    def prepare_payload(self, messages, *, task, turn, arm, attempt_id):
        data = json.loads(messages[1]["content"])
        ids = [a["atom_id"] for a in data["supplied_atom_catalog"]]
        if data.get("selection_catalog") != model_catalog(task, ids):
            raise ValueError("selection_catalog_prompt_mismatch")
        return payload(messages, task, arm, turn, attempt_id, ids)

    def __call__(self, messages, *, task, turn, arm, attempt_id):
        # Unique persisted attempt ID binds tools to this arm/task, even when
        # R1/R2 otherwise share the same source. No warmup/probe or hidden retry.
        request = self.prepare_payload(messages, task=task, turn=turn, arm=arm, attempt_id=attempt_id)
        try:
            body, trace = complete_job(self.cfg, request)
        except JobTransportError as exc:
            raise RepairProviderError(safe_trace(exc.trace)) from None
        choice = body["choices"][0]
        if choice.get("finish_reason") != "stop":
            return {"output": None, "provider_usage": body.get("usage"), "finish_reason": choice.get("finish_reason"),
                    "job_id": trace["job_id"], "content_sha256": _hash(choice.get("message", {}).get("content")),
                    "raw_content": choice.get("message", {}).get("content"),
                    "parse_error": {"type": "FinishReason", "message": "non_stop_completion"}, "transport_trace": safe_trace(trace)}
        content = choice["message"]["content"]
        def strict(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError("duplicate_model_json_key")
                out[key] = value
            return out
        try:
            output = json.loads(content, object_pairs_hook=strict)
            parse_error = None
        except (ValueError, TypeError) as exc:
            output = None
            parse_error = {"type": type(exc).__name__, "message": str(exc)}
        return {"output": output, "provider_usage": body.get("usage"),
                "finish_reason": choice.get("finish_reason"), "job_id": trace["job_id"],
                "content_sha256": _hash(content), "transport_latency_ms": trace["latency_ms"],
                "parse_error": parse_error, "raw_content": content,
                "transport_trace": safe_trace(trace)}


def safe_trace(trace):
    keys = ("job_id", "payload_sha256", "polls", "submit_attempts", "job_status",
            "started_at_unix", "finished_at_unix", "latency_ms")
    result = {k: trace[k] for k in keys if k in trace and isinstance(trace[k], (int, float, str))}
    result["events"] = [{k: e[k] for k in ("method", "http_status", "error") if k in e}
                        for e in trace.get("events", [])]
    result["server_timing"] = {k: v for k, v in trace.get("server_timing", {}).items()
                               if k in {"created_at", "started_at", "finished_at", "inference_seconds"}}
    diagnostic = trace.get("failure_diagnostic", {})
    result["failure_diagnostic"] = {k: diagnostic[k] for k in ("kind", "http_status", "retryable", "outcome") if k in diagnostic}
    return result


class RepairProviderError(RuntimeError):
    def __init__(self, trace):
        self.safe_trace = trace
        super().__init__("repair_provider_error")
