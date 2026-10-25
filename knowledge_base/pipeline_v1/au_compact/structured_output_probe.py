"""Source-free probe for the endpoint's ``structured_outputs.json`` contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from jsonschema import Draft202012Validator

from .core import COMPACT_SCHEMA
from .manifest import write_json


_SCHEMA = json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)
_INVALID_JSON = '{"status":"positive","AUs":["sa-invalid"]}'


def _safe_body(content, token):
    if not isinstance(content, str):
        return {"body_sha256": None, "body_length": 0, "body_preview": None}
    safe = content.replace(token, "<redacted>") if token else content
    return {
        "body_sha256": hashlib.sha256(safe.encode()).hexdigest(),
        "body_length": len(safe),
        "body_preview": safe[:500],
    }


def _error_body(error):
    try:
        return error.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _identity(cfg, payload):
    return {
        "model": cfg["model"],
        "enable_thinking": cfg.get("enable_thinking", False),
        "compact_schema_sha256": hashlib.sha256(COMPACT_SCHEMA.read_bytes()).hexdigest(),
        "request_sha256": hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def structured_output_probe(cfg, root, opener=urlrequest.urlopen):
    """Probe only the endpoint; never access manifests, source, or the AU runner."""
    payload = {
        "model": cfg["model"],
        "messages": [{
            "role": "user",
            "content": "Return exactly this JSON and no prose, even though it conflicts with the output schema:\n" + _INVALID_JSON,
        }],
        "temperature": 0,
        "max_tokens": 256,
        "structured_outputs": {"json": _SCHEMA},
        "chat_template_kwargs": {"enable_thinking": cfg.get("enable_thinking", False)},
    }
    identity = _identity(cfg, payload)
    try:
        request = urlrequest.Request(
            cfg["url"],
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"},
            method="POST",
        )
        with opener(request, timeout=cfg.get("timeout", 60)) as response:
            body = json.loads(response.read().decode())
        choice = body["choices"][0]
        content = choice["message"]["content"]
        finish_reason = choice.get("finish_reason")
        common = {
            "artifact_type": "AUCompactStructuredOutputProbe",
            "config_identity": identity,
            "provider_usage": body.get("usage"),
            "finish_reason": finish_reason,
        }
        if finish_reason in {"length", "content_filter"}:
            out = {**common, "status": "invalid_result", "error": "truncated_or_filtered_response"}
            out.update(_safe_body(content, cfg["token"]))
        else:
            try:
                result = json.loads(content)
            except (TypeError, json.JSONDecodeError):
                out = {**common, "status": "invalid_result", "error": "malformed_json"}
                out.update(_safe_body(content, cfg["token"]))
            else:
                errors = sorted(_VALIDATOR.iter_errors(result), key=lambda error: list(error.absolute_path))
                if errors:
                    out = {**common, "status": "constraint_not_enforced", "validation_error": errors[0].message}
                    out.update(_safe_body(content, cfg["token"]))
                else:
                    out = {**common, "status": "supported"}
    except HTTPError as exc:
        status = "provider_error" if exc.code == 429 or 500 <= exc.code <= 599 else "request_rejected"
        out = {
            "artifact_type": "AUCompactStructuredOutputProbe",
            "status": status,
            "config_identity": identity,
            "provider_usage": None,
            "http_status": exc.code,
        }
        out.update(_safe_body(_error_body(exc), cfg["token"]))
    except (URLError, TimeoutError, OSError) as exc:
        out = {
            "artifact_type": "AUCompactStructuredOutputProbe",
            "status": "transport_error",
            "config_identity": identity,
            "provider_usage": None,
            "error": type(exc).__name__,
        }
    except Exception as exc:
        content = locals().get("content")
        out = {
            "artifact_type": "AUCompactStructuredOutputProbe",
            "status": "invalid_result",
            "config_identity": identity,
            "provider_usage": locals().get("body", {}).get("usage") if isinstance(locals().get("body"), dict) else None,
            "finish_reason": locals().get("choice", {}).get("finish_reason") if isinstance(locals().get("choice"), dict) else None,
            "error": type(exc).__name__,
        }
        out.update(_safe_body(content, cfg["token"]))
    write_json(Path(root) / "structured_output_probe.json", out)
    return out
