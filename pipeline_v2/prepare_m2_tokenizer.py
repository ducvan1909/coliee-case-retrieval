"""Fetch only public tokenizer/config assets; never model weights or remote code."""
import hashlib
import json
from pathlib import Path
import time
import sys

import requests
import tokenizers

REVISION = "5cf2132abc99cad020ac570b19d031efec650f2b"
MODEL = "Qwen/Qwen3-Embedding-4B"
FILES = ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "config.json", "README.md")


def main():
    root = Path(__file__).resolve().parents[1]
    assets = root / "pipeline_v2/vendor/qwen3_embedding_4b_tokenizer" / REVISION
    lock_path = root / "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json"
    finalize = "--finalize-local" in sys.argv
    receipt_path = root / ("pipeline_v2/reviews/m2_tokenizer_acquisition_v2.json" if finalize else "pipeline_v2/reviews/m2_tokenizer_acquisition_v1.json")
    if lock_path.exists() or receipt_path.exists():
        raise RuntimeError("Write-once lock/receipt already exists")
    assets.mkdir(parents=True, exist_ok=True)
    entries, attempts = {}, []
    started = time.perf_counter()
    try:
        for name in FILES:
            url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}"
            attempt = {"file": name, "url": url}
            before = time.perf_counter()
            attempts.append(attempt)
            path = assets / name
            if finalize:
                prior = json.loads((root / "pipeline_v2/reviews/m2_tokenizer_acquisition_v1.json").read_text())
                saved = next(x for x in prior["attempts"] if x["file"] == name)
                raw = path.read_bytes()
                if len(raw) != saved["byte_length"] or hashlib.sha256(raw).hexdigest() != saved["sha256"]:
                    raise RuntimeError("Downloaded asset differs from successful HTTP receipt")
                attempt["mode"] = "local_hash_verified_from_prior_http_receipt"
            else:
                response = requests.get(url, timeout=120)
                attempt["status_code"] = response.status_code
                response.raise_for_status()
                raw = response.content
            if path.exists():
                if path.read_bytes() != raw:
                    raise RuntimeError("Existing asset mismatch")
            else:
                path.write_bytes(raw)
            entries[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
            attempt.update(entries[name], elapsed_seconds=round(time.perf_counter()-before, 6))
        backend = tokenizers.Tokenizer.from_file(str(assets / "tokenizer.json"))
        backend_state = json.loads(backend.to_str())
        cfg = json.loads((assets / "tokenizer_config.json").read_text(encoding="utf-8"))
        if cfg.get("add_bos_token", False) or cfg.get("add_eos_token", False):
            raise RuntimeError("AutoTokenizer special-token handling requires further implementation")
        processor = backend_state.get("post_processor")
        template = processor["processors"][1] if processor and processor.get("type") == "Sequence" else {}
        if (template.get("type") != "TemplateProcessing" or template.get("single") !=
                [{"Sequence": {"id": "A", "type_id": 0}}, {"SpecialToken": {"id": "<|endoftext|>", "type_id": 0}}]
                or backend.num_special_tokens_to_add(False) != 1):
            raise RuntimeError("Unexpected document special-token processor")
        backend.no_truncation()
        backend.no_padding()
        lock = {"schema_version": "pipeline-v2-tokenizer-lock-1", "model_id": MODEL,
                "tokenizer_id": MODEL, "revision": REVISION,
                "assets_dir": assets.relative_to(root).as_posix(), "files": entries,
                "package_versions": {"tokenizers": tokenizers.__version__},
                "encoding": {"add_special_tokens": True, "truncation": False, "padding": False,
                             "document_template": "{body}", "document_instruction": None,
                             "chat_template_applied": False},
                "backend_post_processor": backend_state.get("post_processor"),
                "special_tokens_added_per_document": backend.num_special_tokens_to_add(False),
                "tokenizer_class_observed": cfg.get("tokenizer_class"),
                "published_context_limit": 32768,
                "config_max_position_embeddings": json.loads((assets / "config.json").read_text())["max_position_embeddings"],
                "tokenizer_config_model_max_length": cfg.get("model_max_length"),
                "runtime_endpoint_limit": None,
                "weights_downloaded": False, "inference_executed": False}
        lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        status = "PASS"
    except Exception as exc:
        status = "FAIL"
        attempts[-1]["error_type"] = type(exc).__name__ if attempts else type(exc).__name__
        raise
    finally:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps({"status": status, "attempts": attempts,
            "elapsed_seconds": round(time.perf_counter()-started, 6), "model_requests": 0,
            "inference_tokens": 0, "weights_downloaded": False,
            "prior_metadata_attempts": [{"status":"FAIL","reason":"sandbox network proxy refused"},
                                        {"status":"PASS","mode":"approved public metadata read"}]}, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"status": status, "revision": REVISION, "files": entries,
                      "special_tokens_added": lock["special_tokens_added_per_document"]}))


if __name__ == "__main__":
    main()
