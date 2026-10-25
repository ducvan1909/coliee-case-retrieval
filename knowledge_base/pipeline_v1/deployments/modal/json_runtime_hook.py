"""Mandatory constructor EOS union, followed by optional scheduler diagnostics."""
import functools
import importlib.abc
import importlib.machinery
import inspect
import json
import os
from pathlib import Path
import sys
import threading

TARGET = "sglang.srt.constrained.xgrammar_backend"
SNAPSHOT = Path("/tmp/coliee-json-scheduler-info.json")
LOCK = threading.RLock()


def ids(value):
    if type(value) is int and 0 <= value < 10_000_000:
        return value
    if isinstance(value, (list, tuple, set)) and len(value) <= 128:
        values = sorted(value) if isinstance(value, set) else list(value)
        if all(type(x) is int and 0 <= x < 10_000_000 for x in values):
            return values
    return None


def write_snapshot(value):
    temporary = SNAPSHOT.with_name(SNAPSHOT.name + f".{os.getpid()}.tmp")
    encoded = json.dumps(value, allow_nan=False).encode()
    if len(encoded) > 16384:
        return
    with temporary.open("wb") as output:
        output.write(encoded)
    os.replace(temporary, SNAPSHOT)


class EOSSyncError(RuntimeError):
    """Cannot safely construct the grammar backend with synchronized EOS."""


def eos_union(model_ids, tokenizer, vocab_size):
    if type(vocab_size) is not int or not 0 < vocab_size < 10_000_000:
        raise EOSSyncError("Unsupported grammar vocabulary size")
    try:
        tokenizer_id = tokenizer.eos_token_id
        additional = getattr(tokenizer, "additional_stop_token_ids", None)
    except Exception:
        raise EOSSyncError("Unreadable tokenizer EOS state") from None
    union = set()
    for value in (model_ids, tokenizer_id, additional):
        if value is None:
            continue
        normalized = ids(value)
        if normalized is None:
            raise EOSSyncError("Invalid EOS token IDs")
        union.update([normalized] if type(normalized) is int else normalized)
    if not union or len(union) > 128 or any(x >= vocab_size for x in union):
        raise EOSSyncError("Empty or out-of-vocabulary EOS union")
    return sorted(union), tokenizer_id, additional


def validate_stop_ids(info, expected):
    try:
        actual = ids(info.stop_token_ids)
    except Exception:
        raise EOSSyncError("Unreadable actual grammar stop set") from None
    if not isinstance(actual, list) or set(actual) != set(expected):
        raise EOSSyncError("Actual grammar stop set differs from EOS union")
    return sorted(set(actual))


def install_module(module):
    cls = module.XGrammarGrammarBackend
    original = cls.__init__
    if getattr(original, "_coliee_eos_sync", False):
        return
    signature = inspect.signature(original)
    if not all(name in signature.parameters for name in
               ("tokenizer", "vocab_size", "model_eos_token_ids")):
        raise EOSSyncError("Unsupported XGrammar backend constructor")

    @functools.wraps(original)
    def observed(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        tokenizer = bound.arguments["tokenizer"]
        input_model_ids = bound.arguments["model_eos_token_ids"]
        expected, tokenizer_id, additional = eos_union(
            input_model_ids, tokenizer, bound.arguments["vocab_size"])
        bound.arguments["model_eos_token_ids"] = expected
        # Restore the module symbol even if the ORIGINAL constructor raises.
        # Any diagnostic failure after successful construction is swallowed.
        with LOCK:
            factory = module.TokenizerInfo
            captured = []
            class ObserveInfo:
                @staticmethod
                def from_huggingface(*a, **kw):
                    info = factory.from_huggingface(*a, **kw)
                    # Validate BEFORE the original backend constructs its compiler.
                    validate_stop_ids(info, expected)
                    captured.append(info)
                    return info
            module.TokenizerInfo = ObserveInfo
            try:
                original_result = original(*bound.args, **bound.kwargs)
            finally:
                module.TokenizerInfo = factory
            if not captured:
                raise EOSSyncError("Unsupported backend: no actual TokenizerInfo captured")
            stop_ids = validate_stop_ids(captured[0], expected)
            try:
                override = self.override_stop_tokens
            except Exception:
                raise EOSSyncError("Unreadable grammar stop override") from None
            if override is not None:
                normalized_override = ids(override)
                if (normalized_override is None or
                        set([normalized_override] if type(normalized_override) is int
                            else normalized_override) != set(expected)):
                    raise EOSSyncError("Grammar stop override differs from EOS union")
            try:
                value = {"available": stop_ids is not None, "pid": os.getpid(),
                    "evidence": "actual_scheduler_backend_constructor",
                    "model_eos_token_ids": ids(input_model_ids),
                    "input_model_eos_token_ids": ids(input_model_ids),
                    "effective_grammar_eos_token_ids": expected,
                    "expected_eos_union": expected,
                    "eos_sync_status": "validated",
                    "eos_sync_mode": "mandatory",
                    "tokenizer_eos_token_id": ids(tokenizer_id),
                    "additional_stop_token_ids": ids(additional),
                    "xgrammar_stop_token_ids": stop_ids,
                    "override_stop_tokens": ids(override)}
                eos = getattr(tokenizer, "eos_token", None)
                if eos in ("<|im_end|>", "<|endoftext|>", "</s>"):
                    value["tokenizer_eos_token"] = eos
                write_snapshot(value)
            except Exception:
                try:
                    write_snapshot({"available": False,
                        "evidence": "actual_scheduler_backend_constructor"})
                except Exception:
                    pass
            return original_result
    observed._coliee_eos_sync = True
    cls.__init__ = observed


class ObserverLoader(importlib.abc.Loader):
    def __init__(self, delegate):
        self.delegate = delegate

    def create_module(self, spec):
        creator = getattr(self.delegate, "create_module", None)
        return creator(spec) if creator else None

    def exec_module(self, module):
        self.delegate.exec_module(module)  # Import exceptions keep original semantics.
        install_module(module)


class ObserverFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != TARGET:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec and spec.loader:
            spec.loader = ObserverLoader(spec.loader)
        return spec


def install():
    if TARGET in sys.modules:
        install_module(sys.modules[TARGET])
    elif not any(isinstance(x, ObserverFinder) for x in sys.meta_path):
        sys.meta_path.insert(0, ObserverFinder())
