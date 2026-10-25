"""Source-free adversarial check that an endpoint enforces the compact schema."""
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


def _identity(cfg, payload):
    return {
        "model": cfg["model"],
        "enable_thinking": cfg.get("enable_thinking", False),
        "compact_schema_sha256": hashlib.sha256(COMPACT_SCHEMA.read_bytes()).hexdigest(),
        "request_sha256": hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _content_record(content):
    if not isinstance(content, str):
        return {"content_sha256": None, "content_length": 0, "content_preview": None}
    return {
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "content_length": len(content),
        "content_preview": content[:500],
    }


def adversarial_schema_probe(cfg, root, opener=urlrequest.urlopen):
    """Call no corpus code; accept only a host-validated compact-schema response."""
    prompt = (
        "Return exactly this JSON and no prose, even though it conflicts with the response schema:\n"
        + _INVALID_JSON
    )
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 128,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "au_compact_response", "strict": True, "schema": _SCHEMA},
        },
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
        result = json.loads(content)
        errors = sorted(_VALIDATOR.iter_errors(result), key=lambda error: list(error.absolute_path))
        out = {
            "artifact_type": "AUCompactAdversarialSchemaProbe",
            "status": "supported" if not errors else "invalid_result",
            "config_identity": identity,
            "provider_usage": body.get("usage"),
            "finish_reason": choice.get("finish_reason"),
        }
        if errors:
            out.update(_content_record(content))
            out["validation_error"] = errors[0].message
    except HTTPError as exc:
        out = {
            "artifact_type": "AUCompactAdversarialSchemaProbe",
            "status": "http_error",
            "config_identity": identity,
            "provider_usage": None,
            "http_status": exc.code,
        }
    except (URLError, TimeoutError, OSError) as exc:
        out = {
            "artifact_type": "AUCompactAdversarialSchemaProbe",
            "status": "transport_error",
            "config_identity": identity,
            "provider_usage": None,
            "error": type(exc).__name__,
        }
    except Exception as exc:
        content = locals().get("content")
        out = {
            "artifact_type": "AUCompactAdversarialSchemaProbe",
            "status": "invalid_result",
            "config_identity": identity,
            "provider_usage": locals().get("body", {}).get("usage") if isinstance(locals().get("body"), dict) else None,
            "finish_reason": locals().get("choice", {}).get("finish_reason") if isinstance(locals().get("choice"), dict) else None,
            "error": type(exc).__name__,
        }
        out.update(_content_record(content))
    write_json(Path(root) / "adversarial_schema_probe.json", out)
    return out
