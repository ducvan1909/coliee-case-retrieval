"""Immutable compact-manifest construction and offline preflight."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

from ..source_contract import open_source
from .core import CompactAUError, build_evidence_catalog


class CompactManifestError(ValueError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _safe_relative(root, relative):
    path = (Path(root) / relative).resolve()
    try:
        path.relative_to(Path(root).resolve())
    except ValueError as exc:
        raise CompactManifestError("atom map path escapes atom root") from exc
    return path


def _binding_for(request, atom_root, plan04_manifest):
    matches = [row for row in plan04_manifest.get("cases", []) if row.get("case_id") == request["case_id"] and row.get("source_hash") == request["source_hash"]]
    if len(matches) != 1:
        raise CompactManifestError("Plan04 atom map must have exactly one case/source match")
    row = matches[0]
    relative = row.get("artifact_ref")
    if not isinstance(relative, str) or not relative:
        raise CompactManifestError("Plan04 atom map artifact_ref missing")
    path = _safe_relative(atom_root, relative)
    if not path.is_file():
        raise CompactManifestError("Plan04 atom map missing")
    raw = path.read_bytes()
    atom_map = json.loads(raw)
    if atom_map.get("case_id") != request["case_id"] or atom_map.get("source_hash") != request["source_hash"]:
        raise CompactManifestError("Plan04 atom map case/source mismatch")
    if atom_map.get("cache_key") != row.get("cache_key"):
        raise CompactManifestError("Plan04 atom map cache key mismatch")
    return {
        "atom_map_relative_path": Path(relative).as_posix(),
        "atom_map_sha256": _sha(raw),
        "atom_map_cache_key": atom_map["cache_key"],
        "case_id": atom_map["case_id"],
        "source_hash": atom_map["source_hash"],
        "segmenter_version": atom_map["segmenter_version"],
        "policy_sha256": atom_map["policy_sha256"],
    }


def build_manifest(base_manifest_path, atom_root):
    """Create a new compact manifest without mutating the locked AU-only source manifest."""
    base_path = Path(base_manifest_path)
    base_raw = base_path.read_bytes()
    base = json.loads(base_raw)
    if base.get("artifact_type") != "AUOnlyLockedManifest" or base.get("schema_version") != "au-only-manifest-v1":
        raise CompactManifestError("base must be the locked AU-only v1 manifest")
    plan04_path = Path(atom_root) / "sentence_atom_build_manifest.json"
    plan04 = _read_json(plan04_path)
    if plan04.get("status") != "pass":
        raise CompactManifestError("Plan04 atom build manifest is not pass")
    requests = []
    for original in base.get("requests", []):
        request = copy.deepcopy(original)
        request["spec"]["caps"]["output_tokens"] = 800
        request["atom_binding"] = _binding_for(request, atom_root, plan04)
        requests.append(request)
    if not requests:
        raise CompactManifestError("base manifest has no requests")
    return {
        "artifact_type": "AUCompactLockedManifest",
        "schema_version": "au-compact-manifest-v1",
        "base_manifest_sha256": _sha(base_raw),
        "plan04_build_manifest_sha256": _sha(plan04_path.read_bytes()),
        "requests": requests,
    }


def _binding_path(binding, atom_root):
    path = _safe_relative(atom_root, binding["atom_map_relative_path"])
    return {**binding, "atom_map_path": str(path)}


def preflight(manifest, source_store, atom_root):
    """Open every locked source and atom map, then report catalog and exact reservations."""
    failures, rows = [], []
    if manifest.get("artifact_type") != "AUCompactLockedManifest" or manifest.get("schema_version") != "au-compact-manifest-v1":
        failures.append("invalid_compact_manifest_identity")
    requests = manifest.get("requests", [])
    for request in requests:
        try:
            source = open_source(source_store, request["case_id"], request["source_hash"])
            binding = request["atom_binding"]
            catalog = build_evidence_catalog(request, _binding_path(binding, atom_root), source)
            from .hints import validate_payload
            validate_payload(request, catalog)
            atom_map = catalog["atom_map"]
            if atom_map.get("cache_key") != binding.get("atom_map_cache_key"):
                raise CompactManifestError("atom map cache key mismatch")
            target_atoms = sum(row["target_intersecting"] for row in catalog["atoms"].values())
            if not target_atoms:
                raise CompactManifestError("no target-intersecting atom after expansion")
            rows.append({"request_id": request["request_id"], "case_id": request["case_id"], "target_id": request["expected_target_ids"][0], "atom_count": len(catalog["atoms"]), "target_atom_count": target_atoms, **catalog["metrics"], "atom_binding": {key: binding[key] for key in ("atom_map_relative_path", "atom_map_sha256", "atom_map_cache_key", "segmenter_version", "policy_sha256")}})
        except Exception as exc:
            failures.append({"request_id": request.get("request_id"), "error": str(exc)})
    reserved_input = sum(row["estimated_input_tokens"] for row in rows)
    reserved_output = sum(request.get("spec", {}).get("caps", {}).get("output_tokens", 0) for request in requests)
    return {"artifact_type": "AUCompactPreflight", "schema_version": "au-compact-preflight-v1", "base_manifest_sha256": manifest.get("base_manifest_sha256"), "input_estimate_policy": "utf8_rendered_atom_union_bytes_plus_512", "request_count": len(requests), "reserved_input_tokens": reserved_input, "reserved_output_tokens": reserved_output, "requests": rows, "status": "pass" if not failures else "fail", "failures": failures}


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
