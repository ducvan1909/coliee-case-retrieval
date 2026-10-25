"""Bounded, case-specific diagnostics. No inference in runtime inspection."""

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

CASE_ID = "invalid_reason_int"
PAYLOAD_SHA256 = "62245e6597435a6d9012b558f45ace72bb0064abc2ee1529c41480cd090893ee"
ATTEMPT_BINDING = "coliee-plan12-json-diagnostic-20261012-attempt-1"
MAX_RESPONSE_BYTES = 1024 * 1024
READ_TIMEOUT = 3
SCHEDULER_SNAPSHOT = Path("/tmp/coliee-json-scheduler-info.json")
BASE = Path(__file__).resolve().parents[2]
PAYLOAD_PATH = BASE / "outputs/plan12_formal_20261012_003243/batch_5/invalid_reason_int.payload.json"
RESULT_PATH = PAYLOAD_PATH.with_name("invalid_reason_int.result.json")


def token_ids(value):
    if type(value) is int and 0 <= value < 10_000_000:
        return value
    if isinstance(value, list) and len(value) <= 128 and all(
        type(x) is int and 0 <= x < 10_000_000 for x in value
    ):
        return value
    return None


def filtered_info(value, depth=0):
    """Allow typed fields only; never echo arbitrary backend strings or keys."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("eos_token_id", "eos_token_ids", "model_eos_token_ids",
                "additional_stop_token_ids", "bos_token_id", "pad_token_id"):
        if key in value and token_ids(value[key]) is not None:
            result[key] = token_ids(value[key])
    for key in ("context_length", "max_total_tokens", "max_running_requests",
                "vocab_size", "max_new_tokens", "page_size"):
        if type(value.get(key)) is int and 0 <= value[key] < 100_000_000:
            result[key] = value[key]
    for key in ("is_generation", "ignore_eos", "skip_tokenizer_init",
                "disable_radix_cache", "enable_cache_report", "enable_metrics"):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    for key, allowed in {
        "grammar_backend": {"xgrammar", "outlines", "llguidance", "none"},
        "reasoning_parser": {"qwen3", "none"},
        "tool_call_parser": {"qwen3_coder", "none"},
        "eos_token": {"<|im_end|>", "<|endoftext|>", "</s>"},
        # SGLang v0.5.19: scheduler is the legacy radix-cache alias.
        "mamba_scheduler_strategy": {"auto", "no_buffer", "extra_buffer", "extra_buffer_lazy"},
        "mamba_radix_cache_strategy": {"auto", "no_buffer", "extra_buffer", "extra_buffer_lazy"},
    }.items():
        if isinstance(value.get(key), str) and value[key] in allowed:
            result[key] = value[key]
    if depth == 0 and isinstance(value.get("server_args"), dict):
        result["server_args"] = filtered_info(value["server_args"], depth=1)
    if depth == 0 and isinstance(value.get("text_config"), dict):
        result["text_config"] = filtered_info(value["text_config"], depth=1)
    return result


def bounded_json(response):
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Response budget exceeded")
    return json.loads(raw)


class RuntimeInspector:
    """Only fixed backend GETs and fixed model metadata files are inspected.

    This process is the gateway, not the scheduler process. File EOS metadata
    must never be labelled the scheduler's active EOS or grammar stop set.
    """

    def __init__(self, model_path, backend_origin="http://127.0.0.1:8001", startup_warmup=None,
                 diagnostic_setup_available=True):
        self.model_path = Path(model_path)
        self.origin = backend_origin
        self.diagnostic_setup_available = diagnostic_setup_available
        self.startup_warmup = startup_warmup or {"requests": None, "usage": None,
            "latency_seconds": None, "outcome": "not_observed", "included_in_diagnostic_budget": False}

    def __call__(self):
        result = {"versions": {}, "backend": {}, "model_files": {},
                  "startup_warmup": self.startup_warmup,
                  "active_grammar_stop_set": "unavailable",
                  "grammar_mask": {"available": False,
                      "reason": "Live scheduler TokenizerInfo is not exposed to gateway"},
                  "token_trace": {"available": False,
                      "reason": "Chat completions do not establish raw generate metadata or token IDs"}}
        for package in ("sglang", "xgrammar", "transformers"):
            try:
                result["versions"][package] = version(package)
            except PackageNotFoundError:
                result["versions"][package] = None
        for route in ("get_server_info", "get_model_info"):
            try:
                request = urllib.request.Request(self.origin + "/" + route, method="GET")
                with urllib.request.urlopen(request, timeout=READ_TIMEOUT) as response:
                    result["backend"][route] = {"available": True,
                        "fields": filtered_info(bounded_json(response))}
            except Exception:
                result["backend"][route] = {"available": False}
        for name in ("config.json", "generation_config.json", "tokenizer_config.json"):
            try:
                with (self.model_path / name).open("rb") as source:
                    result["model_files"][name] = {"available": True,
                        "fields": filtered_info(bounded_json(source)),
                        "evidence": "checkpoint_metadata_not_active_scheduler"}
            except Exception:
                result["model_files"][name] = {"available": False}
        try:
            if not self.diagnostic_setup_available:
                raise ValueError("Diagnostic setup unavailable")
            with SCHEDULER_SNAPSHOT.open("rb") as source:
                snapshot = bounded_json(source)
            scheduler = filtered_info(snapshot)
            for key in ("xgrammar_stop_token_ids", "tokenizer_eos_token_id", "override_stop_tokens",
                        "input_model_eos_token_ids", "effective_grammar_eos_token_ids",
                        "expected_eos_union"):
                if token_ids(snapshot.get(key)) is not None:
                    scheduler[key] = token_ids(snapshot[key])
            if snapshot.get("eos_sync_status") == "validated":
                scheduler["eos_sync_status"] = "validated"
            if snapshot.get("eos_sync_mode") == "mandatory":
                scheduler["eos_sync_mode"] = "mandatory"
            scheduler["available"] = (snapshot.get("available") is True and
                                       "xgrammar_stop_token_ids" in scheduler)
            scheduler["evidence"] = "actual_scheduler_backend_constructor"
            if snapshot.get("tokenizer_eos_token") in ("<|im_end|>", "<|endoftext|>", "</s>"):
                scheduler["tokenizer_eos_token"] = snapshot["tokenizer_eos_token"]
            result["scheduler"] = scheduler
            if scheduler["available"]:
                result["active_grammar_stop_set"] = scheduler["xgrammar_stop_token_ids"]
        except Exception:
            result["scheduler"] = {"available": False,
                                   "setup_available": self.diagnostic_setup_available}
        return result

def diagnostic_job(record):
    """No prompt, model output, raw error message or arbitrary provider metadata."""
    result = {key: record[key] for key in ("job_id", "status", "payload_sha256",
              "provider_http_status", "inference_seconds", "response_sha256") if key in record}
    usage = record.get("usage") or {}
    result["usage"] = {key: usage[key] for key in
        ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens")
        if type(usage.get(key)) is int and usage[key] >= 0}
    choices = (record.get("response") or {}).get("choices") or record.get("choices") or []
    result["finish_reasons"] = [c.get("finish_reason") for c in choices[:1]
        if isinstance(c, dict) and c.get("finish_reason") in
        ("stop", "length", "tool_calls", "content_filter", None)]
    if not choices and isinstance(record.get("finish_reasons"), list):
        result["finish_reasons"] = [x for x in record["finish_reasons"][:1]
            if x in ("stop", "length", "tool_calls", "content_filter", None)]
    result["matched_stop"] = [token_ids(c["matched_stop"]) for c in choices[:1]
        if isinstance(c, dict) and "matched_stop" in c and token_ids(c["matched_stop"]) is not None]
    if not choices and token_ids(record.get("matched_stop")) is not None:
        result["matched_stop"] = token_ids(record["matched_stop"])
    result["choices"] = [{key: c[key] for key in ("finish_reason", "matched_stop")
        if (key == "finish_reason" and c.get(key) in ("stop", "length", "tool_calls", "content_filter", None))
        or (key == "matched_stop" and token_ids(c.get(key)) is not None)}
        for c in choices[:1] if isinstance(c, dict)]
    result["raw_backend_finish_reason_available"] = False
    result["generated_token_ids_available"] = False
    # Only actual raw metadata carried by the saved provider response counts.
    # Never manufacture a raw reason from choices[].finish_reason == 'stop'.
    response = record.get("response") or {}
    meta = response.get("meta_info")
    if not meta and record.get("raw_backend_finish_reason_available") is True:
        meta = {"finish_reason": record.get("raw_backend_finish_reason")}
    if isinstance(meta, dict) and isinstance(meta.get("finish_reason"), dict):
        raw = meta["finish_reason"]
        if raw.get("type") in ("stop", "length", "abort"):
            result["raw_backend_finish_reason"] = {"type": raw["type"]}
            matched = token_ids(raw.get("matched"))
            if matched is not None:
                result["raw_backend_finish_reason"]["matched"] = matched
            result["raw_backend_finish_reason_available"] = True
    ids = response.get("output_ids")
    if ids is None and record.get("generated_token_ids_available") is True:
        ids = record.get("generated_token_ids")
    if (isinstance(ids, list) and len(ids) <= 1200 and
            all(type(x) is int and 0 <= x < 10_000_000 for x in ids)):
        result["generated_token_ids"] = ids
        result["generated_token_ids_available"] = True
    return result


def replay_payload(payload, hash_function):
    if not isinstance(payload, dict) or hash_function(payload) != PAYLOAD_SHA256:
        raise ValueError("Only the pinned failing payload is allowed")
    # OpenAI user is an audit binding. It changes request identity; report it.
    return {**payload, "user": ATTEMPT_BINDING}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Admit at most one fixed replay job")
    parser.add_argument("--replay-status", action="store_true", help="GET the fixed replay job; no inference")
    parser.add_argument("--output", type=Path, required=True, help="New report file; never overwrite")
    args = parser.parse_args(argv)
    if args.execute and args.replay_status:
        parser.error("Choose --execute or --replay-status")
    if args.output.exists():
        parser.error("Output already exists")
    from .job_gateway import payload_job_id
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    saved = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    if (payload_job_id(payload) != PAYLOAD_SHA256 or saved.get("case_id") != CASE_ID
            or saved.get("payload_sha256") != PAYLOAD_SHA256
            or saved.get("receipt", {}).get("job_id") != PAYLOAD_SHA256):
        parser.error("Saved case identity mismatch")
    from knowledge_base.config import settings
    from knowledge_base.pipeline_v1.au_runtime_config import load_au_runtime_config
    try:
        cfg, _, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
    except ValueError:
        parser.error("Invalid AU runtime configuration")
    url, token = cfg["url"], cfg["token"]
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path != "/v1/chat/completions"
            or not token):
        parser.error("Require HTTPS AU_URL ending /v1/chat/completions and AU_TOKEN")
    origin = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    def request(route, body=None):
        req = urllib.request.Request(origin + route,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method="GET" if body is None else "POST")
        # No redirects with credentials and no automatic retries.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *unused, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as response:
            return bounded_json(response)

    report = {"case_id": CASE_ID, "original_payload_sha256": PAYLOAD_SHA256,
              "execute": args.execute, "max_diagnostic_inferences": 1 if args.execute else 0,
              "startup_warmup": {"requests": None, "usage": None, "latency_seconds": None,
                  "outcome": "not_observed", "included_in_diagnostic_budget": False}}
    try:
        report["runtime"] = request("/v1/diagnostics/json/info")
        if isinstance(report["runtime"].get("startup_warmup"), dict):
            report["startup_warmup"] = report["runtime"]["startup_warmup"]
    except Exception as error:
        report["runtime"] = {"available": False}
        if isinstance(error, urllib.error.HTTPError):
            report["runtime"]["http_status"] = error.code
            error.close()
    try:
        old = request("/v1/jobs/" + PAYLOAD_SHA256)
        if old.get("job_id") != PAYLOAD_SHA256 or old.get("payload_sha256") != PAYLOAD_SHA256:
            raise ValueError("Remote job identity mismatch")
        report["original_job"] = diagnostic_job(old)
        if args.replay_status:
            replay = replay_payload(payload, payload_job_id)
            report["replay_payload_sha256"] = payload_job_id(replay)
            replay_result = request("/v1/jobs/" + payload_job_id(replay))
            if replay_result.get("job_id") != payload_job_id(replay):
                raise ValueError("Replay identity mismatch")
            report["replay_job"] = diagnostic_job(replay_result)
        if args.execute:
            replay = replay_payload(payload, payload_job_id)
            report["replay_payload_sha256"] = payload_job_id(replay)
            report["payload_difference"] = {"added_user": ATTEMPT_BINDING}
            replay_result = request("/v1/diagnostics/json/replay",
                {"case_id": CASE_ID, "payload_sha256": PAYLOAD_SHA256, "payload": payload})
            if replay_result.get("job_id") != payload_job_id(replay):
                raise ValueError("Replay identity mismatch")
            report["replay_job"] = diagnostic_job(replay_result)
    except Exception as error:
        report["error"] = "Diagnostic request failed; no retry. Inspect job by ID before any action."
        if isinstance(error, urllib.error.HTTPError):
            report["http_status"] = error.code
            error.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False, allow_nan=False)
    return 1 if "error" in report or report["runtime"].get("available") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
