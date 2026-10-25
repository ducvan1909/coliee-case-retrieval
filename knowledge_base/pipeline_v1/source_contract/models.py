"""Data contracts for immutable source records and exact spans."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ManifestCase:
    case_id: str
    kos_role: str
    corpus_split: str
    source_path: str
    sha256: str
    byte_length: int
    char_length: int


@dataclass(frozen=True)
class SourceManifest:
    manifest_version: str
    workload: str
    source_contract: dict[str, Any]
    cases: tuple[ManifestCase, ...]
    audit_kos_manifest: str


@dataclass(frozen=True)
class SpanRef:
    case_id: str
    source_hash: str
    start_char: int
    end_char: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CaseSource:
    case_id: str
    source_version: str
    source_hash: str
    text_ref: str
    byte_length: int
    char_length: int
    metadata: dict[str, Any]
    record_type: str = "CaseSource"
    contract_version: str = "case-source-v1"
    encoding: str = "utf-8-sig"
    offset_unit: str = "unicode_codepoint"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "contract_version": self.contract_version,
            "case_id": self.case_id,
            "source_version": self.source_version,
            "source_hash": self.source_hash,
            "text_ref": self.text_ref,
            "byte_length": self.byte_length,
            "char_length": self.char_length,
            "encoding": self.encoding,
            "offset_unit": self.offset_unit,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CaseSource":
        return cls(
            case_id=value["case_id"],
            source_version=value["source_version"],
            source_hash=value["source_hash"],
            text_ref=value["text_ref"],
            byte_length=value["byte_length"],
            char_length=value["char_length"],
            metadata=value["metadata"],
            record_type=value["record_type"],
            contract_version=value["contract_version"],
            encoding=value["encoding"],
            offset_unit=value["offset_unit"],
        )

    def resolve_text(self, store_root: Path) -> Path:
        path = (store_root / self.text_ref).resolve()
        root = store_root.resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"text_ref escapes source store: {self.text_ref}")
        return path

