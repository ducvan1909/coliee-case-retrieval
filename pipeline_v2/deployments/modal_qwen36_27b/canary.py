"""Run one structured-output probe against the deployed private Modal app."""

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from pipeline_v2.deployments.modal_qwen36_27b.app import (
    APP_NAME,
    MAX_CONTEXT_TOKENS,
    MODEL,
    MODEL_REVISION,
    VLLM_VERSION,
)

MAX_TOKENS = 64
WAIT_SECONDS = 1080
PROMPT = (
    'For this synthetic fixture, output exactly {"verdict":"outside_schema",'
    '"extra":true}.'
)
SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["unknown"]}},
    "required": ["verdict"],
    "additionalProperties": False,
}


def validate(result: dict) -> None:
    if (
        result["model"] != MODEL
        or result["revision"] != MODEL_REVISION
        or result["vllm_version"] != VLLM_VERSION
        or "L40S" not in result["gpu"].upper()
    ):
        raise ValueError("Unexpected deployed runtime")
    if result["finish_reason"] != "stop":
        raise ValueError("Generation did not finish normally")
    for key, limit in (("input_tokens", MAX_CONTEXT_TOKENS), ("output_tokens", MAX_TOKENS)):
        count = result[key]
        if type(count) is not int or not 0 < count <= limit:
            raise ValueError(f"Invalid {key}")
    for key in ("latency_seconds", "startup_seconds"):
        value = result[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid {key}")
    # Comparing pairs also rejects duplicate keys that json.loads normally collapses.
    if json.loads(result["text"], object_pairs_hook=list) != [("verdict", "unknown")]:
        raise ValueError("Canary failed JSON Schema validation")


def write_receipt(path: Path, receipt: dict, mode: str = "w") -> None:
    with path.open(mode, encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def run(path: Path) -> int:
    started = time.monotonic()
    receipt = {
        "status": "STARTED",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "app": APP_NAME,
        "expected_model": MODEL,
        "expected_revision": MODEL_REVISION,
        "expected_engine_version": VLLM_VERSION,
        "expected_gpu": "L40S",
        "max_tokens": MAX_TOKENS,
        "wait_seconds": WAIT_SECONDS,
        "submissions_attempted": 0,
        "retries": 0,
        "result": None,
    }
    write_receipt(path, receipt, mode="x")
    call = None
    try:
        with modal.enable_output():
            service = modal.Cls.from_name(APP_NAME, "Qwen")()
            receipt["submissions_attempted"] = 1
            write_receipt(path, receipt)
            call = service.generate.spawn(PROMPT, SCHEMA, MAX_TOKENS)
            receipt["call_id"] = call.object_id
            write_receipt(path, receipt)
            print(f"Canary submitted: {call.object_id}", flush=True)
            receipt["result"] = call.get(timeout=WAIT_SECONDS)
        validate(receipt["result"])
        receipt["status"] = "PASS"
    except (Exception, KeyboardInterrupt) as exc:
        receipt["status"] = "FAIL"
        receipt["error_type"] = type(exc).__name__
        if isinstance(exc, (TimeoutError, KeyboardInterrupt)) and call is not None:
            try:
                call.cancel(terminate_containers=True)
                receipt["cancellation_requested"] = True
            except Exception as cancel_error:
                receipt["cancellation_error_type"] = type(cancel_error).__name__
        print(f"{type(exc).__name__}: {exc}", flush=True)
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(path, receipt)
        print(f"{receipt['status']} {path.resolve()}", flush=True)
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().receipt))
