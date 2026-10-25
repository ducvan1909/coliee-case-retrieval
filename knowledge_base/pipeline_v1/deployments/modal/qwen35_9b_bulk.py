"""Isolated bulk/corpus C4 deployment for Qwen/Qwen3.5-9B on one L40S.

This deployment is intentionally independent from Modal's generated Model
Library endpoint. It shares the baseline pinned model-cache Volume in the active
Modal workspace and downloads that revision when the cache is empty.

C4 is fixed in both gateway and server configuration.
This independent app has its own job Volume; only the pinned model cache and
unchanged EOS/runtime hook sources are shared with baseline. Protocol success
is not evidence of semantic AU quality.
"""

import os
from pathlib import Path

import modal


MINUTE = 60
PORT = 8000
MODEL_PORT = 8001
JOB_VOLUME_ROOT = Path("/job-store")
JOB_VOLUME_NAME = "coliee-qwen35-9b-bulk-jobs"
GATEWAY_MODULE_PATH = "/opt/coliee/job_gateway_bulk.py"
BACKEND_TIMEOUT = 1800

APP_NAME = "coliee-qwen35-9b-bulk"
MODEL_REPO = "Qwen/Qwen3.5-9B"
MODEL_REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
SERVED_MODEL_NAME = MODEL_REPO

MODEL_VOLUME_NAME = "coliee-qwen35-9b-model-cache"
MODEL_VOLUME_ROOT = Path("/model-cache")
MODEL_PATH = MODEL_VOLUME_ROOT / "Qwen3.5-9B" / MODEL_REVISION
MODEL_READY_MARKER = MODEL_PATH / ".coliee-download-complete"

SGLANG_IMAGE_TAG = "lmsysorg/sglang:v0.5.19-cu130"
AUTOINFERENCE_UTILS_VERSION = "0.2.6"

GPU = "L40S:1"
CPU = 4
MEMORY_MB = 16_384
ROUTING_REGION = "us-west"
STARTUP_TIMEOUT = 60 * MINUTE
SCALEDOWN_WINDOW = 2 * MINUTE


# Fixed C4 experiment; independent of concurrency deployment environment.
BENCH_CONCURRENCY = 4


model_volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=True)
job_volume = modal.Volume.from_name(JOB_VOLUME_NAME, create_if_missing=True)

serving_image = (
    modal.Image.from_registry(SGLANG_IMAGE_TAG)
    .uv_pip_install(
        f"autoinference-utils=={AUTOINFERENCE_UTILS_VERSION}",
        "fastapi>=0.115,<1", "uvicorn>=0.30,<1",
    )
    .env(
        {
            "HF_XET_HIGH_PERFORMANCE": "1",
            "SGLANG_ENABLE_JIT_DEEPGEMM": "0",
            "SGLANG_TIMEOUT_KEEP_ALIVE": "300",
            "TORCHINDUCTOR_COMPILE_THREADS": "1",
            "PLX_BULK_CONCURRENCY": str(BENCH_CONCURRENCY),
        }
    )
    .add_local_file(Path(__file__).with_name("job_gateway_bulk.py"), GATEWAY_MODULE_PATH)
    .add_local_file(Path(__file__).with_name("json_diagnostic.py"), "/opt/coliee/json_diagnostic.py")
    .add_local_file(Path(__file__).with_name("sitecustomize.py"), "/opt/coliee/diagnostics/sitecustomize.py")
    .add_local_file(Path(__file__).with_name("json_runtime_hook.py"), "/opt/coliee/diagnostics/json_runtime_hook.py")
)

# Modal mount targets are Linux paths even when its CLI runs on Windows.
VOLUME_MOUNTS = {MODEL_VOLUME_ROOT.as_posix(): model_volume}
SERVER_VOLUME_MOUNTS = {**VOLUME_MOUNTS, JOB_VOLUME_ROOT.as_posix(): job_volume}

SERVER_ARGS = {
    "--served-model-name": SERVED_MODEL_NAME,
    "--context-length": "12288",
    "--max-total-tokens": "12288",
    "--max-running-requests": str(BENCH_CONCURRENCY),
    "--chunked-prefill-size": "4096",
    "--max-prefill-tokens": "4096",
    "--cuda-graph-max-bs": str(BENCH_CONCURRENCY),
    "--disable-cuda-graph-padding": "",
    "--enable-memory-saver": "",
    "--enable-cache-report": "",
    "--enable-multimodal": "",
    "--mamba-scheduler-strategy": "extra_buffer",
    "--mamba-ssm-dtype": "float32",
    "--mem-fraction-static": "0.70",
    "--reasoning-parser": "qwen3",
    "--tool-call-parser": "qwen3_coder",
    "--trust-remote-code": "",
}

WARMUP_PAYLOAD = {
    "model": SERVED_MODEL_NAME,
    "messages": [
        {
            "role": "user",
            "content": "Return a JSON object describing Tokyo.",
        }
    ],
    "max_tokens": 64,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": False},
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "city_facts",
            "schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "country": {"type": "string"},
                },
                "required": ["city", "country"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
}


def _ensure_model_downloaded() -> str:
    """Download the pinned checkpoint once and persist it in the Modal Volume."""

    if MODEL_READY_MARKER.is_file():
        marker_revision = MODEL_READY_MARKER.read_text(encoding="utf-8").strip()
        if marker_revision == MODEL_REVISION:
            return str(MODEL_PATH)

    from huggingface_hub import snapshot_download

    MODEL_PATH.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_REPO,
        revision=MODEL_REVISION,
        local_dir=str(MODEL_PATH),
    )
    MODEL_READY_MARKER.write_text(MODEL_REVISION, encoding="utf-8")
    model_volume.commit()
    return str(MODEL_PATH)


app = modal.App(APP_NAME)


@app.function(
    image=serving_image,
    cpu=CPU,
    memory=MEMORY_MB,
    timeout=STARTUP_TIMEOUT,
    volumes=VOLUME_MOUNTS,
)
def download_model() -> str:
    """Optional pre-deploy step that fills the workspace-local model cache."""

    return _ensure_model_downloaded()


@app.server(
    image=serving_image,
    gpu=GPU,
    cpu=CPU,
    memory=MEMORY_MB,
    min_containers=0,
    max_containers=1,
    buffer_containers=0,
    scaledown_window=SCALEDOWN_WINDOW,
    port=PORT,
    routing_region=ROUTING_REGION,
    unauthenticated=False,
    exit_grace_period=60,
    startup_timeout=STARTUP_TIMEOUT,
    # HTTP routing/admission capacity, independent of the N inference workers.
    # Polling/health routes must remain available while all workers are busy.
    target_concurrency=4,
    max_concurrency=8,
    volumes=SERVER_VOLUME_MOUNTS,
)
class Server:
    @modal.enter()
    def startup(self) -> None:
        import importlib.util
        import json
        import os
        import sys
        import threading
        import time
        import urllib.request

        import uvicorn
        from autoinference_utils.endpoint import SGLangEndpoint

        model_path = _ensure_model_downloaded()
        # Child interpreters use sitecustomize; current interpreter may already
        # be running before Modal injects PYTHONPATH, so install here as well.
        self.diagnostic_setup_available = True
        # EOS sync is mandatory. Preserve Modal's dependency paths and fail
        # startup if installation fails, rather than serving the old EOS state.
        inherited_path = os.environ.get("PYTHONPATH", "")
        diagnostic_path = "/opt/coliee/diagnostics"
        if diagnostic_path not in inherited_path.split(os.pathsep):
            os.environ["PYTHONPATH"] = diagnostic_path + (os.pathsep + inherited_path if inherited_path else "")
        sys.path.insert(0, diagnostic_path)
        from json_runtime_hook import install
        install()
        try:
            # A new backend must not inherit evidence from a prior PID.
            Path("/tmp/coliee-json-scheduler-info.json").unlink(missing_ok=True)
        except Exception:
            # Optional diagnostic I/O must not block successful EOS sync.
            # Refuse to read a potentially stale snapshot even if cleanup failed.
            self.diagnostic_setup_available = False
        self.endpoint = SGLangEndpoint(
            model_path=model_path,
            worker_port=MODEL_PORT,
            tp=1,
            extra_server_args=SERVER_ARGS,
            health_timeout=STARTUP_TIMEOUT,
            health_poll_interval=5.0,
        )
        self.endpoint.start()
        # SGLang reads enable_thinking from chat_template_kwargs. Send exactly
        # this payload directly, once; never retry an unknown inference outcome.
        request = urllib.request.Request(
            f"http://127.0.0.1:{MODEL_PORT}/v1/chat/completions",
            data=json.dumps(WARMUP_PAYLOAD).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        warmup_started = time.monotonic()
        warmup_accounting = {"requests": 1, "usage": None, "latency_seconds": None,
                             "outcome": "unknown", "included_in_diagnostic_budget": False}
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                warmup_body = response.read()
            warmup_accounting.update(outcome="completed", latency_seconds=time.monotonic() - warmup_started)
            try:
                usage = json.loads(warmup_body).get("usage") or {}
                warmup_accounting["usage"] = {key: usage[key] for key in
                    ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens")
                    if type(usage.get(key)) is int and usage[key] >= 0}
            except Exception:
                pass  # Observational decoding must not affect successful warmup.
        except Exception:
            self.endpoint.stop()
            raise RuntimeError("Internal warmup failed") from None

        spec = importlib.util.spec_from_file_location("coliee_job_gateway_bulk", GATEWAY_MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Both standalone files are installed in this fixed, image-owned path.
        sys.path.insert(0, "/opt/coliee")
        from json_diagnostic import RuntimeInspector
        self.gateway_app = module.create_app(
            JOB_VOLUME_ROOT / "bulk-v1", job_volume.commit, backend_timeout=BACKEND_TIMEOUT,
            concurrency=BENCH_CONCURRENCY, server_concurrency=BENCH_CONCURRENCY,
            diagnostic_inspector=RuntimeInspector(model_path, startup_warmup=warmup_accounting,
                diagnostic_setup_available=self.diagnostic_setup_available),
        )
        self.gateway_server = uvicorn.Server(uvicorn.Config(
            self.gateway_app, host="0.0.0.0", port=PORT, access_log=False,
            log_level="warning", timeout_graceful_shutdown=50,
        ))
        self.gateway_thread = threading.Thread(target=self.gateway_server.run, daemon=True)
        self.gateway_thread.start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and self.gateway_thread.is_alive():
            if self.gateway_server.started:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as response:
                    if response.status == 200:
                        print(f"{SERVED_MODEL_NAME} ({GPU}) durable gateway is ready.")
                        return
            time.sleep(0.1)
        self.gateway_server.should_exit = True
        self.endpoint.stop()
        raise RuntimeError("Durable gateway startup failed")

    @modal.exit()
    def stop(self) -> None:
        if hasattr(self, "gateway_app"):
            self.gateway_app.state.gateway.stop(grace_seconds=50)
        if hasattr(self, "gateway_server"):
            self.gateway_server.should_exit = True
            self.gateway_thread.join(timeout=5)
        if hasattr(self, "endpoint"):
            self.endpoint.stop()
