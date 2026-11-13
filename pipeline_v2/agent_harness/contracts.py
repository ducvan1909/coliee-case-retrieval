"""Interfaces for the local M4 controller harness."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re


class HarnessError(RuntimeError):
    """The run configuration or a controller operation is invalid."""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def fingerprint(value):
    return sha256(encode(value)).hexdigest()


def source_hash(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    query_id: str
    query_source_hash: str
    candidate_fingerprint: str
    index_fingerprint: str
    profile_fingerprint: str
    model_fingerprint: str
    prompt_fingerprint: str
    tools_fingerprint: str
    tokenizer_fingerprint: str

    def __post_init__(self):
        if not all(isinstance(value, str) and value.strip() for value in vars(self).values()):
            raise HarnessError("Run identity fields must be nonempty strings")
        if not source_hash(self.query_source_hash):
            raise HarnessError("Invalid query source SHA-256")


@dataclass(frozen=True)
class Budget:
    max_requests: int
    max_actions: int
    max_input_tokens: int
    max_payload_tokens: int
    max_output_tokens: int
    max_total_tokens: int | None = None
    max_retries: int = 0

    def __post_init__(self):
        values = {key: value for key, value in vars(self).items() if key != "max_total_tokens"}
        if not all(integer(value) for value in values.values()) or not self.max_output_tokens:
            raise HarnessError("Budget limits must be nonnegative integers with a positive output cap")
        if self.max_total_tokens is not None and not integer(self.max_total_tokens):
            raise HarnessError("Invalid total token cap")


@dataclass(frozen=True)
class SourceExcerpt:
    case_id: str
    source_hash: str
    span_bytes: tuple[int, int]
    text: str
    text_sha256: str
    provenance: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.case_id, str) or not self.case_id.strip() or not source_hash(self.source_hash):
            raise HarnessError("Invalid excerpt source identity")
        if (not isinstance(self.span_bytes, (list, tuple)) or len(self.span_bytes) != 2
                or not all(integer(offset) for offset in self.span_bytes)
                or self.span_bytes[0] >= self.span_bytes[1]):
            raise HarnessError("Invalid UTF-8 byte span")
        if not isinstance(self.text, str) or not isinstance(self.provenance, dict):
            raise HarnessError("Invalid excerpt text or provenance")
        raw = self.text.encode("utf-8")
        if self.span_bytes[1] - self.span_bytes[0] != len(raw) or sha256(raw).hexdigest() != self.text_sha256:
            raise HarnessError("Excerpt bytes or SHA-256 do not match its span")
        object.__setattr__(self, "span_bytes", tuple(self.span_bytes))
        encode(self.provenance)

    @property
    def ref(self):
        return fingerprint([self.case_id, self.source_hash, self.span_bytes, self.text_sha256])

    def to_record(self):
        return {**vars(self), "ref": self.ref}

    def slice(self, start, end):
        if (start, end) == self.span_bytes:
            return self
        raw = self.text.encode("utf-8")
        base = self.span_bytes[0]
        piece = raw[start - base:end - base]
        provenance = self.provenance
        if isinstance(provenance.get("components"), list):
            provenance = {**provenance, "components": [
                row for row in provenance["components"]
                if not isinstance(row, dict) or not isinstance(row.get("span_bytes"), (tuple, list))
                or len(row["span_bytes"]) != 2 or not all(integer(offset) for offset in row["span_bytes"])
                or max(start, row["span_bytes"][0]) < min(end, row["span_bytes"][1])
            ]}
        if provenance.get("span_bytes") in (self.span_bytes, list(self.span_bytes)):
            provenance = {**provenance, "span_bytes": [start, end]}
        return SourceExcerpt(self.case_id, self.source_hash, (start, end), piece.decode("utf-8"),
                             sha256(piece).hexdigest(), provenance)


@dataclass(frozen=True)
class ToolResult:
    observation: dict
    excerpts: tuple[SourceExcerpt, ...] = ()
    candidates: tuple[str, ...] = ()
    source_requests: tuple[dict, ...] = ()


@dataclass(frozen=True)
class ModelReply:
    action: dict | str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None


class TransportError(Exception):
    """Known retryable rejection or uncertain receipt from the transport adapter."""

    def __init__(self, message, *, retryable=False, unknown=False, input_tokens=None,
                 output_tokens=None, latency_ms=None):
        super().__init__(message)
        self.retryable = retryable
        self.unknown = unknown
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms
