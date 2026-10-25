"""OpenAI-compatible transport with a persistent, shared budget ledger."""

from __future__ import annotations

from copy import deepcopy
import json
import hashlib
import time
from pathlib import Path
from urllib import error, request

from .source import save


class BudgetStop(RuntimeError):
    pass


class UncertainRequest(RuntimeError):
    pass


class ProviderUnavailable(RuntimeError):
    pass


class HttpRejected(RuntimeError):
    pass


class ModelProtocolError(RuntimeError):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("Endpoint redirect refused")


def decode_model_json(content: str) -> tuple[dict, dict | None]:
    """Strictly parse a JSON object; semantic-looking text repair is forbidden."""
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ModelProtocolError("Model returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise ModelProtocolError("Model output must be a JSON object")
    return result, None


def _hash_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cache_identity(request_id: str, model: str, system: str, payload: dict,
                    metadata: dict, response_format: dict | None = None) -> dict:
    return {"request_id": request_id, "model": model,
            "system_hash": hashlib.sha256(system.encode("utf-8")).hexdigest(),
            "payload_hash": _hash_json(payload), "metadata": deepcopy(metadata),
            **({"response_format_hash": _hash_json(response_format)}
               if response_format is not None else {})}


def _cache_envelope(identity: dict, response: dict) -> dict:
    return {"cache_schema_version": 1, "identity": identity,
            "response": response, "response_checksum": _hash_json(response)}


def _read_cache(path: Path, expected_identity: dict) -> dict:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(envelope, dict) or envelope.get("cache_schema_version") != 1 or
            envelope.get("identity") != expected_identity or
            not isinstance(envelope.get("response"), dict) or
            envelope.get("response_checksum") != _hash_json(envelope["response"])):
        raise UncertainRequest("Response cache identity or checksum mismatch")
    return envelope["response"]


def reconcile_known_noninference(ledger: dict) -> int:
    """Release reserves only for persisted attempts proven not to reach inference."""
    changed = 0
    for call in ledger.get("calls", []):
        is_old_503 = (call.get("status") == "failed_or_uncertain" and
                      call.get("http_status") == 503)
        is_local_block = call.get("status") == "local_environment_blocked"
        if is_old_503:
            call["status"] = "provider_unavailable"
        if (is_old_503 or is_local_block) and not call.get("reserve_released_usd"):
            amount = call.get("reserve_usd", 0)
            ledger["reserved_usd"] = max(0, round(ledger.get("reserved_usd", 0) - amount, 10))
            call["reserve_released_usd"] = amount
            call["reserve_release_reason"] = (
                "Historical HTTP 503 occurred before a Modal replica was ready"
                if is_old_503 else "Sandbox proxy blocked dispatch before the endpoint"
            )
            changed += 1
    return changed


def confirm_local_environment_block(ledger_path: Path, request_id: str,
                                    evidence: str) -> dict:
    """Release one attempt only after an operator confirms local pre-dispatch blocking."""
    path = Path(ledger_path)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    matches = [call for call in ledger.get("calls", [])
               if call.get("request_id") == request_id or
               call.get("logical_request_id") == request_id]
    if not matches:
        raise ValueError("Unknown request ID")
    call = matches[-1]
    if (call.get("status") != "failed_or_uncertain" or
            call.get("error_type") != "URLError" or call.get("transport_attempts")):
        raise ValueError("Only an unattempted URLError can be confirmed as a local block")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("Confirmation evidence is required")
    call["status"] = "local_environment_blocked"
    call["local_block_confirmation"] = evidence.strip()
    if not call.get("reserve_released_usd"):
        amount = call.get("reserve_usd", 0)
        ledger["reserved_usd"] = max(0, round(ledger.get("reserved_usd", 0) - amount, 10))
        call["reserve_released_usd"] = amount
        call["reserve_release_reason"] = "Confirmed local network sandbox blocked dispatch"
    save(path, ledger)
    return deepcopy(call)


class Endpoint:
    def __init__(self, config: dict, ledger_path: Path, inherited_path: Path | None = None,
                 *, allow_provider_retry: bool = False,
                 allow_confirmed_local_retry: bool = False,
                 sleep_fn=None, clock_fn=None):
        self.config, self.path = config, Path(ledger_path)
        self.allow_provider_retry = allow_provider_retry
        self.allow_confirmed_local_retry = allow_confirmed_local_retry
        self.sleep = sleep_fn or time.sleep
        self.clock = clock_fn or time.monotonic
        if self.path.exists():
            self.ledger = json.loads(self.path.read_text(encoding="utf-8"))
        elif inherited_path and Path(inherited_path).exists():
            legacy = json.loads(Path(inherited_path).read_text(encoding="utf-8"))
            self.ledger = {"schema_version": 2,
                           "budget_usd": config["budget"],
                           "reserved_usd": legacy.get("reserved_usd", 0),
                           "inherited_from": str(Path(inherited_path).resolve()),
                           "calls": deepcopy(legacy.get("calls", []))}
            save(self.path, self.ledger)
        else:
            self.ledger = {"schema_version": 2, "budget_usd": config["budget"],
                           "reserved_usd": 0, "calls": []}
            save(self.path, self.ledger)
        if config["budget"] is None:
            previous = self.ledger.get("budget_usd")
            if previous is not None:
                self.ledger["budget_limit_removed_from_usd"] = previous
                self.ledger["budget_usd"] = None
                save(self.path, self.ledger)
        elif self.ledger.get("budget_usd", config["budget"]) != config["budget"]:
            raise ValueError("Shared ledger budget differs from configuration")
        if reconcile_known_noninference(self.ledger):
            save(self.path, self.ledger)
        self.opener = request.build_opener(NoRedirect)

    def _related(self, request_id: str) -> list[dict]:
        return [call for call in self.ledger["calls"]
                if call.get("request_id") == request_id or call.get("logical_request_id") == request_id]

    def _release_reserve(self, call: dict, reason: str) -> None:
        if call.get("reserve_released_usd"):
            return
        amount = call.get("reserve_usd", 0)
        self.ledger["reserved_usd"] = max(0, self.ledger["reserved_usd"] - amount)
        call["reserve_released_usd"] = amount
        call["reserve_release_reason"] = reason

    def _next_attempt_id(self, request_id: str, related: list[dict]) -> str:
        return f"{request_id}:retry:{len(related)}"

    def complete(self, model: str, system: str, payload: dict, *, request_id: str,
                 metadata: dict, cache_path: Path,
                 response_format: dict | None = None) -> dict:
        cache_path = Path(cache_path)
        identity = _cache_identity(request_id, model, system, payload, metadata,
                                   response_format)
        related = self._related(request_id)
        if cache_path.exists():
            if not related:
                raise UncertainRequest("Response cache exists without a budget record")
            cached = _read_cache(cache_path, identity)
            latest = related[-1]
            if latest.get("cache_identity") != identity:
                raise UncertainRequest("Budget record identity does not match response cache")
            if latest.get("status") not in {"completed", "completed_recovered_from_cache"}:
                latest["status"] = "completed_recovered_from_cache"
                save(self.path, self.ledger)
            return cached
        raw_path = cache_path.with_suffix(".raw.json")
        if (raw_path.exists() and related and
                related[-1].get("error_type") in {"JSONDecodeError", "ModelProtocolError"}):
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            if raw.get("identity") != identity:
                raise UncertainRequest("Raw response identity mismatch")
            if raw.get("finish_reason") not in (None, "stop"):
                raise ModelProtocolError("Model response was truncated")
            result, parse_repair = decode_model_json(raw["model_content"])
            save(cache_path, _cache_envelope(identity, result))
            latest = related[-1]
            latest["status"] = "completed_recovered_from_raw_response"
            latest["usage"] = raw.get("provider_response", {}).get("usage", {})
            if parse_repair:
                latest["protocol_parse_repair"] = parse_repair
            save(self.path, self.ledger)
            return result
        retry_of = None
        if related:
            latest = related[-1]
            provider_retry = (latest.get("status") == "provider_unavailable" and
                              self.allow_provider_retry)
            local_retry = (latest.get("status") == "local_environment_blocked" and
                           self.allow_confirmed_local_retry)
            if not (provider_retry or local_retry):
                raise UncertainRequest(f"Request {request_id} has no reusable response and must not be retried")
            retry_of = latest["request_id"]

        config = self.config
        if (config["budget"] is not None and
                self.ledger["reserved_usd"] + config["reserve"] > config["budget"] + 1e-9):
            raise BudgetStop("Request reserve would exceed the shared experiment budget")
        actual_request_id = self._next_attempt_id(request_id, related) if related else request_id
        call = {"request_id": actual_request_id, "logical_request_id": request_id,
                "model": model, "status": "reserved", "reserve_usd": config["reserve"],
                "transport_attempts": [], "cache_identity": identity, **metadata}
        if retry_of:
            call["retry_of"] = retry_of
        self.ledger["reserved_usd"] += config["reserve"]
        self.ledger["calls"].append(call)
        save(self.path, self.ledger)

        headers = {"Content-Type": "application/json", **config["headers"]}
        if config["key"]:
            headers["Authorization"] = "Bearer " + config["key"]
        body = {"model": model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                "temperature": config["temperature"], "max_tokens": config["tokens"],
                "top_p": config["top_p"], "stream": False,
                "reasoning_effort": config["reasoning_effort"]}
        if response_format is not None:
            body["response_format"] = response_format
        req = request.Request(config["url"], data=json.dumps(body).encode("utf-8"),
                              headers=headers, method="POST")
        started = self.clock()
        delay = 2.0
        try:
            while True:
                attempt_started = self.clock()
                try:
                    with self.opener.open(req, timeout=config["timeout"]) as response:
                        data = json.load(response)
                    call["transport_attempts"].append({
                        "attempt": len(call["transport_attempts"]) + 1,
                        "status": "completed", "http_status": 200,
                        "elapsed_seconds": self.clock() - attempt_started,
                    })
                    save(self.path, self.ledger)
                    break
                except error.HTTPError as exc:
                    call["transport_attempts"].append({
                        "attempt": len(call["transport_attempts"]) + 1,
                        "status": "http_error", "http_status": exc.code,
                        "elapsed_seconds": self.clock() - attempt_started,
                    })
                    if exc.code != 503:
                        call.update(status="http_rejected", error_type="HTTPError",
                                    http_status=exc.code)
                        save(self.path, self.ledger)
                        raise HttpRejected(
                            f"Endpoint rejected request with HTTP {exc.code}; request will not be retried"
                        ) from None
                    elapsed = self.clock() - started
                    remaining = config["startup_wait"] - elapsed
                    if remaining <= 0:
                        call.update(status="provider_unavailable", error_type="HTTPError",
                                    http_status=503)
                        self._release_reserve(call, "Modal returned only HTTP 503 before startup deadline")
                        save(self.path, self.ledger)
                        raise ProviderUnavailable(
                            "Modal had no ready replica before the startup deadline; reserve released"
                        ) from None
                    call.update(status="waiting_for_provider", http_status=503)
                    save(self.path, self.ledger)
                    self.sleep(min(delay, remaining))
                    delay = min(15.0, delay * 2)
            choice = data["choices"][0]
            content = choice["message"]["content"]
            save(raw_path, {
                "identity": identity,
                "provider_response": data,
                "model_content": content,
                "finish_reason": choice.get("finish_reason"),
            })
            if choice.get("finish_reason") not in (None, "stop"):
                raise ModelProtocolError("Model response was truncated")
            result, parse_repair = decode_model_json(content)
            save(cache_path, _cache_envelope(identity, result))
            call.update(status="completed", usage=data.get("usage", {}))
            if parse_repair:
                call["protocol_parse_repair"] = parse_repair
            return result
        except (ProviderUnavailable, HttpRejected):
            raise
        except ModelProtocolError as exc:
            call["status"] = "completed_invalid_protocol"
            call["error_type"] = type(exc).__name__
            call["usage"] = data.get("usage", {}) if "data" in locals() else {}
            raise
        except Exception as exc:
            call["status"] = "failed_or_uncertain"
            call["error_type"] = type(exc).__name__
            if isinstance(exc, error.HTTPError):
                call["http_status"] = exc.code
            raise RuntimeError(
                f"Endpoint call failed ({type(exc).__name__}); reservation retained and request will not be retried"
            ) from None
        finally:
            call["elapsed_seconds"] = self.clock() - started
            save(self.path, self.ledger)
