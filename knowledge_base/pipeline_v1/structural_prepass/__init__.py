"""Deterministic structural pre-pass for Pipeline V1."""

from .build import (
    StructuralPrepassError,
    build_source_blocks,
    load_and_validate_block_map,
    validate_block_map,
)
from .parser import EVENT_SPECS, block_id_for, cache_key_for, parse_source, parser_event_for

__all__ = [
    "StructuralPrepassError",
    "EVENT_SPECS",
    "build_source_blocks",
    "block_id_for",
    "cache_key_for",
    "load_and_validate_block_map",
    "parse_source",
    "parser_event_for",
    "validate_block_map",
]
