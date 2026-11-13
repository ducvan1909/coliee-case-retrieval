"""Private, text-only Qwen generation for a bounded Modal canary."""

import json
from pathlib import Path
from time import perf_counter

import modal


APP_NAME = "coliee-qwen36-27b-fp8-l40s"
MODEL = "Qwen/Qwen3.6-27B-FP8"
MODEL_REVISION = "a56219b8202864dc6d3e565be5ff1eea01f54cb4"
VLLM_VERSION = "0.19.1"
VLLM_IMAGE = (
    "vllm/vllm-openai@sha256:89c1d0629d377daa3f7f369cbea6167a7b48ea89aaacd12555e2b0b2f7f740d3"
)
MAX_CONTEXT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 512
HF_HOME = "/models/huggingface"

app = modal.App(APP_NAME)
cache = modal.Volume.from_name("coliee-qwen36-27b-fp8-hf-v1", create_if_missing=True)
image = modal.Image.from_registry(
    VLLM_IMAGE,
    setup_dockerfile_commands=[
        "ENTRYPOINT []",
        "RUN command -v python >/dev/null || ln -s /usr/bin/python3 /usr/local/bin/python",
    ],
).env({
    "HF_HOME": HF_HOME,
    "HF_HUB_ETAG_TIMEOUT": "30",
    "HF_HUB_DOWNLOAD_TIMEOUT": "120",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "VLLM_NO_USAGE_STATS": "1",
    "VLLM_ENABLE_V1_MULTIPROCESSING": "0",
}).workdir("/root").add_local_file(
    __file__, "/root/pipeline_v2/deployments/modal_qwen36_27b/app.py",
)


@app.cls(
    image=image,
    gpu="L40S",
    volumes={HF_HOME: cache},
    min_containers=0,
    max_containers=1,
    scaledown_window=60,
    startup_timeout=900,
    timeout=120,
    retries=0,
    include_source=False,
)
class Qwen:
    @modal.enter()
    def load(self):
        started = perf_counter()
        print(f"Loading {MODEL}@{MODEL_REVISION} with vLLM {VLLM_VERSION}", flush=True)

        from huggingface_hub import snapshot_download
        import torch
        from vllm import LLM, __version__

        if __version__ != VLLM_VERSION:
            raise RuntimeError("Unexpected vLLM version")
        self.vllm_version = __version__
        self.gpu = torch.cuda.get_device_name(0)
        if torch.cuda.device_count() != 1 or "L40S" not in self.gpu.upper():
            raise RuntimeError("Expected one NVIDIA L40S")

        print("Resolving pinned Hugging Face weights in the Modal Volume", flush=True)
        snapshot = snapshot_download(
            MODEL,
            revision=MODEL_REVISION,
            allow_patterns=["*.safetensors", "*.json", "*.jinja", "*.model", "merges.txt", "vocab.*"],
        )
        if Path(snapshot).name != MODEL_REVISION:
            raise RuntimeError("Unexpected Hugging Face snapshot revision")
        cache.commit()

        print("Initializing the text-only vLLM engine", flush=True)
        self.engine = LLM(
            model=snapshot,
            trust_remote_code=False,
            tensor_parallel_size=1,
            language_model_only=True,
            max_model_len=MAX_CONTEXT_TOKENS,
            max_num_seqs=1,
            gpu_memory_utilization=0.90,
            enforce_eager=True,
            structured_outputs_config={"backend": "xgrammar"},
        )
        self.startup_seconds = perf_counter() - started
        print(f"Engine ready on {self.gpu} in {self.startup_seconds:.2f} seconds", flush=True)

    @modal.method()
    def generate(self, prompt: str, schema: dict, max_tokens: int) -> dict:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Expected a nonempty text prompt")
        if not isinstance(schema, dict) or not schema:
            raise ValueError("Expected a nonempty JSON schema object")
        if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError(f"max_tokens must be between 1 and {MAX_OUTPUT_TOKENS}")

        started = perf_counter()
        from vllm import SamplingParams
        from vllm.sampling_params import StructuredOutputsParams

        params = SamplingParams(
            temperature=0.0,
            max_tokens=max_tokens,
            structured_outputs=StructuredOutputsParams(json=json.dumps(schema, allow_nan=False)),
        )
        request, = self.engine.chat(
            [{"role": "user", "content": prompt}],
            sampling_params=params,
            chat_template_kwargs={"enable_thinking": False},
            use_tqdm=False,
        )
        output, = request.outputs
        if request.prompt_token_ids is None or not request.finished or output.finish_reason is None:
            raise RuntimeError("vLLM did not return final output and token usage")
        return {
            "text": output.text,
            "input_tokens": len(request.prompt_token_ids),
            "output_tokens": len(output.token_ids),
            "finish_reason": output.finish_reason,
            "model": MODEL,
            "revision": MODEL_REVISION,
            "vllm_version": self.vllm_version,
            "gpu": self.gpu,
            "latency_seconds": perf_counter() - started,
            "startup_seconds": self.startup_seconds,
        }
