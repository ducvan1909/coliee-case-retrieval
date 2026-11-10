"""Offline, hash-pinned tokenizer only. Never downloads model weights."""
import importlib.metadata
from pathlib import Path

from ..source.core import canonical, digest
from ..source.store import contained, read_json


class PassageError(ValueError):
    pass


class PinnedTokenizer:
    def __init__(self, repo_root, lock_path):
        self.root = Path(repo_root).resolve()
        path = contained(self.root, lock_path, "pipeline_v2")
        self.lock = read_json(path)
        self.lock_path = path
        self.lock_sha256 = digest(path.read_bytes())
        if (self.lock.get("schema_version") != "pipeline-v2-tokenizer-lock-1" or
                self.lock.get("model_id") != "Qwen/Qwen3-Embedding-4B" or not self.lock.get("revision")):
            raise PassageError("Expected pinned Qwen3-Embedding-4B tokenizer")
        directory = contained(self.root, self.lock["assets_dir"], "pipeline_v2/vendor")
        files = self.lock["files"]
        if "tokenizer.json" not in files:
            raise PassageError("Missing pinned tokenizer.json")
        for name, expected in files.items():
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise PassageError("Unsafe tokenizer asset path")
            asset = directory / name
            if asset.is_symlink() or not asset.resolve().is_relative_to(directory):
                raise PassageError("Tokenizer asset escapes pinned directory")
            raw = asset.read_bytes()
            if expected != {"sha256": digest(raw), "byte_length": len(raw)}:
                raise PassageError("Tokenizer asset hash drift: " + name)
        version = importlib.metadata.version("tokenizers")
        if self.lock.get("package_versions", {}).get("tokenizers") != version:
            raise PassageError("Pinned tokenizers package version drift")
        from tokenizers import Tokenizer
        self.backend = Tokenizer.from_file(str(directory / "tokenizer.json"))
        backend_json = read_json(directory / "tokenizer.json")
        if backend_json.get("post_processor") != self.lock.get("backend_post_processor"):
            raise PassageError("Tokenizer special-token postprocessor differs from lock")
        if self.backend.num_special_tokens_to_add(False) != self.lock.get("special_tokens_added_per_document"):
            raise PassageError("Tokenizer special-token overhead differs from lock")
        self.backend.no_truncation()
        self.backend.no_padding()
        encoded = self.lock.get("encoding", {})
        if encoded != {"add_special_tokens": True, "truncation": False, "padding": False,
                       "document_template": "{body}", "document_instruction": None, "chat_template_applied": False}:
            raise PassageError("Unsupported document rendering in tokenizer lock")
        config = read_json(directory / "tokenizer_config.json")
        if config.get("add_bos_token", False) or config.get("add_eos_token", False):
            raise PassageError("Tokenizer configuration requires unsupported added BOS/EOS")
        self.directory = directory
        self.fingerprint = digest(canonical({"lock_sha256": self.lock_sha256, "tokenizers": version,
                                             "add_special_tokens": True, "truncation": False,
                                             "document_template": "{body}"}))

    def verify(self):
        if digest(self.lock_path.read_bytes()) != self.lock_sha256:
            raise PassageError("Tokenizer lock drift")
        for name, expected in self.lock["files"].items():
            asset = self.directory/name
            raw = asset.read_bytes()
            if asset.is_symlink() or not asset.resolve().is_relative_to(self.directory) or expected != {"sha256":digest(raw),"byte_length":len(raw)}:
                raise PassageError("Tokenizer asset drift: " + name)

    def count(self, text):
        return len(self.backend.encode(text, add_special_tokens=True).ids)

    def offsets(self, text):
        return self.backend.encode(text, add_special_tokens=False).offsets

    def count_content(self, text):
        return len(self.backend.encode(text, add_special_tokens=False).ids)
