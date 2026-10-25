"""Ephemeral CPU-only XGrammar replay; no server, weights or inference.

Uploads only the isolated probe package, never knowledge_base/.env or outputs.
Reads tokenizer files from the existing model cache without downloading them.
"""
from pathlib import Path
import json

import modal

APP_NAME = "coliee-length-constraints-cpu"
BASE_IMAGE = "lmsysorg/sglang:v0.5.19-cu130"
CANDIDATE_VERSION = "0.2.8"  # Candidate to measure, not a production upgrade.
MODEL_REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
TOKENIZER_PATH = "/model-cache/Qwen3.5-9B/" + MODEL_REVISION
PROBE_PATH = (Path(__file__).resolve().parents[2] / "au_length_probe"
              if modal.is_local() else Path("/opt/probe/au_length_probe"))

app = modal.App(APP_NAME)
cache = modal.Volume.from_name("coliee-qwen35-9b-model-cache", create_if_missing=False)


def image(candidate=False):
    value = modal.Image.from_registry(BASE_IMAGE)
    if candidate:
        value = value.uv_pip_install(f"xgrammar=={CANDIDATE_VERSION}")
    return value.env({"PYTHONPATH": "/opt/probe", "HF_HUB_OFFLINE": "1",
                      "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"}).add_local_dir(
        PROBE_PATH, "/opt/probe/au_length_probe", ignore=["**/__pycache__/**", "**/*.pyc"])


def _benchmark(repeats, variant="all"):
    import hashlib
    import os
    import subprocess
    import sys
    import tempfile
    from importlib.metadata import version, PackageNotFoundError

    versions = {}
    for name in ("xgrammar", "sglang", "torch", "transformers", "tokenizers"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    metadata = {"image": BASE_IMAGE, "versions": versions, "gpu_requested": False,
                "inference_requests": 0, "weights_loaded": False,
                "tokenizer_download_permitted": False, "model_revision": MODEL_REVISION,
                "live_scheduler_version_confirmed": False}
    metadata["selected_variant"] = variant
    metadata["probe_source_sha256"] = {
        name: hashlib.sha256(Path("/opt/probe/au_length_probe", name).read_bytes()).hexdigest()
        for name in ("__init__.py", "core.py", "__main__.py")
        if Path("/opt/probe/au_length_probe", name).is_file()
    }
    if not Path(TOKENIZER_PATH, "tokenizer_config.json").is_file():
        return {**metadata, "status": "unavailable", "reason": "cached_tokenizer_missing"}
    with tempfile.TemporaryDirectory(prefix="length-probe-") as tmp:
        target = Path(tmp, "probe", "report.json")
        try:
            # CLI has a child watchdog, so even native compilation is bounded.
            command = [sys.executable, "-m", "au_length_probe", "offline",
                 "--tokenizer-path", TOKENIZER_PATH, "--output-root", str(target.parent),
                 "--repeats", str(repeats), "--max-seconds", "120"]
            if variant != "all":
                command.extend(["--variants", variant])
            process = subprocess.run(command,
                capture_output=True, timeout=150,
                env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
            )
        except subprocess.TimeoutExpired:
            return {**metadata, "status": "incomplete", "reason": "cpu_replay_deadline"}
        if not target.is_file():
            # Raw exceptions/stdout could contain arbitrary paths; keep diagnostics finite.
            return {**metadata, "status": "unavailable", "reason": "probe_process_failed",
                    "exit_code": process.returncode}
        if target.stat().st_size > 8 * 1024 * 1024:
            return {**metadata, "status": "incomplete", "reason": "report_size_ceiling"}
        return {**metadata, "probe_exit_code": process.returncode,
                "report": json.loads(target.read_text(encoding="utf-8"))}


@app.function(image=image(), cpu=4, memory=16384, timeout=720,
              volumes={"/model-cache": cache}, max_containers=1)
def inherited(repeats: int = 1, variant: str = "all"):
    return _benchmark(repeats, variant)


@app.function(image=image(candidate=True), cpu=4, memory=16384, timeout=720,
              volumes={"/model-cache": cache}, max_containers=1)
def candidate(repeats: int = 1, variant: str = "all"):
    return _benchmark(repeats, variant)


@app.local_entrypoint()
def main(output_root: str, arm: str = "inherited", repeats: int = 1, variant: str = "all"):
    if (arm not in ("inherited", "candidate", "both") or not 1 <= repeats <= 3
            or variant not in ("all", "host_validated", "bounded", "max_chars", "json_schema")):
        raise ValueError("arm inherited/candidate/both; repeats 1..3")
    root = Path(output_root).resolve()
    if root.exists():
        raise ValueError("Use a fresh output root; existing reports are never overwritten")
    root.mkdir(parents=True)
    arms = ("inherited", "candidate") if arm == "both" else (arm,)
    for name in arms:
        function = inherited if name == "inherited" else candidate
        result = function.remote(repeats, variant)
        path = root / f"{name}.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        status = result.get("report", {}).get("status", result.get("status", "unknown"))
        print(f"LENGTH CPU {name}: {status} — {path}; inference=0, not endpoint acceptance")
