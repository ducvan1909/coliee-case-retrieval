"""Source-free schema ablations for the compact AU response contract."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from urllib import request as urlrequest

from jsonschema import Draft202012Validator

from .core import COMPACT_SCHEMA
from .constraint_matrix_probe import _call
from .manifest import write_json


_BASE = json.loads(COMPACT_SCHEMA.read_text(encoding="utf-8"))


def _drop(value, keys):
    if isinstance(value, dict):
        return {key: _drop(item, keys) for key, item in value.items() if key not in keys}
    if isinstance(value, list):
        return [_drop(item, keys) for item in value]
    return value


def _inline_au(schema):
    value = copy.deepcopy(schema)
    au = value.get("$defs", {}).get("au")
    if au:
        value["properties"]["aus"]["items"] = copy.deepcopy(au)
    value.pop("$defs", None)
    return value


def schema_ablation_probe(cfg, root, opener=urlrequest.urlopen):
    variants = [
        ("drop_conditionals", _drop(_BASE, {"allOf"})),
        ("drop_conditionals_unique", _drop(_BASE, {"allOf", "uniqueItems"})),
        ("inline_refs", _inline_au(_drop(_BASE, {"allOf", "uniqueItems", "$schema", "$id", "title"}))),
        ("grammar_core", _inline_au(_drop(_BASE, {"allOf", "uniqueItems", "$schema", "$id", "title", "minLength", "maxLength", "minItems", "maxItems"}))),
    ]
    rows = []
    for label, schema in variants:
        row = {"probe": label, **_call(cfg, name=label, schema=schema, thinking=False, opener=opener)}
        rows.append(row)
        if row["status"] == "supported":
            break
    diagnosis = "no_supported_ablation"
    if rows[-1]["status"] == "supported":
        diagnosis = {
            "drop_conditionals": "conditional_schema_keywords_incompatible",
            "drop_conditionals_unique": "unique_items_also_incompatible",
            "inline_refs": "references_or_schema_metadata_also_incompatible",
            "grammar_core": "only_core_grammar_supported",
        }[rows[-1]["probe"]]
    report = {
        "artifact_type": "AUCompactSchemaAblationProbe",
        "model": cfg["model"],
        "base_schema_sha256": hashlib.sha256(COMPACT_SCHEMA.read_bytes()).hexdigest(),
        "requests_sent": len(rows),
        "results": rows,
        "diagnosis": diagnosis,
    }
    write_json(Path(root) / "schema_ablation_probe.json", report)
    return report
