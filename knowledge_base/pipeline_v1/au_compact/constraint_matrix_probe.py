"""Source-free matrix for isolating SGLang structured-output failures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from jsonschema import Draft202012Validator

from .core import COMPACT_SCHEMA
from .manifest import write_json


_COMPACT = json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8"))
_SIMPLE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind"],
    "properties": {"kind": {"enum": ["holding", "procedural_rule"]}},
}
_INVALID = '{"kind":"exception"}'


def _call(cfg, *, name, schema, thinking, opener):
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": "Return exactly this JSON despite the schema: " + _INVALID}],
        "temperature": 0,
        "max_tokens": 128,
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
    }
    if thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": thinking}
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    try:
        req = urlrequest.Request(
            cfg["url"], data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"}, method="POST",
        )
        with opener(req, timeout=cfg.get("timeout", 60)) as response:
            body = json.loads(response.read().decode())
        choice = body["choices"][0]
        content = choice["message"]["content"]
        value = json.loads(content)
        errors = list(Draft202012Validator(schema).iter_errors(value))
        return {
            "status": "supported" if not errors else "constraint_not_enforced",
            "thinking": "omitted" if thinking is None else thinking,
            "request_sha256": identity,
            "usage": body.get("usage"),
            "finish_reason": choice.get("finish_reason"),
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "content_preview": content[:300],
            "validation_error": errors[0].message if errors else None,
        }
    except HTTPError as exc:
        return {"status": "http_error", "thinking": thinking, "request_sha256": identity, "http_status": exc.code}
    except (URLError, TimeoutError, OSError) as exc:
        return {"status": "transport_error", "thinking": thinking, "request_sha256": identity, "error": type(exc).__name__}
    except Exception as exc:
        return {"status": "invalid_result", "thinking": thinking, "request_sha256": identity, "error": type(exc).__name__}


def constraint_matrix_probe(cfg, root, opener=urlrequest.urlopen):
    """Compare omitted/false/true thinking, then test the compact schema once."""
    rows = []
    for label, thinking in (("simple_default", None), ("simple_no_thinking", False), ("simple_thinking", True)):
        rows.append({"probe": label, **_call(cfg, name=label, schema=_SIMPLE, thinking=thinking, opener=opener)})
    working = next((row for row in rows if row["status"] == "supported"), None)
    if working:
        mode = None if working["thinking"] == "omitted" else working["thinking"]
        rows.append({"probe": "compact_working_mode", **_call(cfg, name="au_compact_response", schema=_COMPACT, thinking=mode, opener=opener)})
    report = {
        "artifact_type": "AUCompactConstraintMatrixProbe",
        "model": cfg["model"],
        "schema_sha256": hashlib.sha256(COMPACT_SCHEMA.read_bytes()).hexdigest(),
        "requests_sent": len(rows),
        "results": rows,
        "diagnosis": (
            "thinking_false_incompatible" if rows[0]["status"] == "supported" and rows[1]["status"] != "supported"
            else "constraint_unavailable_all_modes" if not working
            else "requires_further_analysis"
        ),
    }
    write_json(Path(root) / "constraint_matrix_probe.json", report)
    return report
