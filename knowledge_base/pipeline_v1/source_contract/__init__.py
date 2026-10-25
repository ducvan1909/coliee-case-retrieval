"""Immutable CaseSource/SpanRef implementation for Pipeline V1."""

from .models import CaseSource, ManifestCase, SourceManifest, SpanRef
from .store import (
    ImmutableSourceError,
    SourceContractError,
    build_source_store,
    load_source_manifest,
    open_source,
    open_span,
)

__all__ = [
    "CaseSource",
    "ImmutableSourceError",
    "ManifestCase",
    "SourceContractError",
    "SourceManifest",
    "SpanRef",
    "build_source_store",
    "load_source_manifest",
    "open_source",
    "open_span",
]

