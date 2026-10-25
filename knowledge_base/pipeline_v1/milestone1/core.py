"""Source-complete manifest and cost preflight, independent of KOS annotations."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from ..source_contract import open_source
from ..structural_prepass import load_and_validate_block_map
from ..sentence_atoms import load_and_validate_sentence_atom_map
from ..au_compact.manifest import _binding_for, _binding_path, preflight as compact_preflight
from ..au_compact.core import build_evidence_catalog
from ..au_compact.runner import _render, RESPONSE_FORMAT_VERSION
from ..au_compact.prompting import build_prompt, prompt_identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = "m1-sourceblock-all-v1"
CASES = {"013009", "013948", "011904", "045155", "099980"}
DEFAULT_BLOCK_ROOT = ROOT / "outputs/plan03_source_blocks_v1"
DEFAULT_SOURCE_MANIFEST = ROOT / "manifests/calibration_manifest.v1.json"


def load(path):
    def unique(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate_json_key")
            out[key] = value
        return out
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("dependency_path_escape")
    return path


def _span(ref):
    a, b = ref["start_char"], ref["end_char"]
    if type(a) is not int or type(b) is not int or not 0 <= a < b:
        raise ValueError("invalid_span")
    return a, b


def _neighbors(atoms, a, b, cap):
    before = [x for x in atoms if x["span"]["end_char"] <= a]
    after = [x for x in atoms if x["span"]["start_char"] >= b]
    candidates = ([before[-1]] if before else []) + ([after[0]] if after else [])
    refs, omitted, used = [], [], 0
    for atom in candidates:
        lo, hi = _span(atom["span"])
        if used + hi - lo > cap:
            omitted.append(atom["atom_id"])
        else:
            refs.append({"role": "context", "start_char": lo, "end_char": hi, "target_ids": []})
            used += hi - lo
    return refs, omitted


def build_manifest(*, source_manifest=DEFAULT_SOURCE_MANIFEST, source_store,
                   atom_root, model="Qwen/Qwen3.5-9B", context_chars=800,
                   output_tokens=800, block_root=DEFAULT_BLOCK_ROOT):
    if model != "Qwen/Qwen3.5-9B":
        raise ValueError("milestone1_model_not_locked_qwen9b")
    if type(context_chars) is not int or context_chars < 0 or type(output_tokens) is not int or output_tokens != 800:
        raise ValueError("invalid_locked_policy")
    source_manifest = Path(source_manifest).resolve()
    sm = load(source_manifest)
    rows = sm.get("cases", [])
    if len(rows) != 5 or {r["case_id"] for r in rows} != CASES:
        raise ValueError("source_manifest_must_be_exact_kos5")
    atom_root, block_root = Path(atom_root).resolve(), Path(block_root).resolve()
    ap = atom_root / "sentence_atom_build_manifest.json"
    bp = block_root / "sourceblock_build_manifest.json"
    am, bm = load(ap), load(bp)
    if am.get("status") != "pass" or bm.get("status") != "pass":
        raise ValueError("dependency_build_not_pass")
    policy = load(ROOT / "policies/sentence_atom_policy.v1.json")
    requests, case_coverage = [], []
    for row in sorted(rows, key=lambda x: x["case_id"]):
        cid, sh = row["case_id"], row["sha256"]
        source = open_source(source_store, cid, sh)
        if row.get("char_length") != len(source):
            raise ValueError("source_manifest_length_mismatch")
        ar = [r for r in am["cases"] if r["case_id"] == cid and r["source_hash"] == sh]
        br = [r for r in bm["cases"] if r["case_id"] == cid and r["source_hash"] == sh]
        if len(ar) != 1 or len(br) != 1:
            raise ValueError("dependency_case_source_not_unique")
        blocks, _ = load_and_validate_block_map(safe_path(block_root, br[0]["artifact_ref"]), source)
        atoms, _ = load_and_validate_sentence_atom_map(
            safe_path(atom_root, ar[0]["artifact_ref"]), source, blocks, policy)
        plans = {p["parent_block_id"]: p for p in atoms["slice_plans"]}
        dispositions, source_cursor, target_chars = [], 0, 0
        for block in atoms["parent_block_refs"]:
            a, b = _span(block["span"])
            if a != source_cursor or b > len(source):
                raise ValueError("source_partition_gap_or_overlap")
            source_cursor = b
            if not source[a:b].strip():
                dispositions.append(dict(block_id=block["block_id"], start_char=a,
                    end_char=b, status="host_skip_whitespace"))
                continue
            spans = [s["span"] for s in plans.get(block["block_id"], {}).get("slices", [])] or [block["span"]]
            cursor = a
            for span in spans:
                lo, hi = _span(span)
                if lo != cursor or hi > b:
                    raise ValueError("derived_slice_gap_or_overlap")
                cursor = hi
                if not source[lo:hi].strip():
                    dispositions.append(dict(block_id=block["block_id"], start_char=lo,
                        end_char=hi, status="host_skip_whitespace"))
                    continue
                target = "m1t-" + digest([VERSION, cid, sh, block["block_id"], lo, hi])[:24]
                context, omitted = _neighbors(atoms["atoms"], lo, hi, context_chars)
                refs = [{"role": "target", "start_char": lo, "end_char": hi,
                         "target_ids": [target]}, *context]
                refs.sort(key=lambda x: (x["start_char"], x["end_char"]))
                spec = dict(model=model, enable_thinking=False,
                    caps=dict(targets=1, output_tokens=output_tokens, au_candidates=3))
                request = dict(case_id=cid, source_hash=sh, arm="AU-only",
                    region_id="m1r-" + digest([target, refs])[:24], expected_target_ids=[target],
                    source_refs=refs, spec=spec,
                    hint_payload={"version": "context-hint-payload-v1", "hint_ids": []},
                    provenance=dict(builder=VERSION, parent_block_id=block["block_id"],
                        selection="all_non_whitespace_sourceblocks_no_kos_labels",
                        derived_slice=block["block_id"] in plans,
                        context_omitted_atom_ids=omitted))
                request["request_id"] = "m1q-" + digest(request)[:24]
                request["atom_binding"] = _binding_for(request, atom_root, am)
                catalog = build_evidence_catalog(request, _binding_path(request["atom_binding"], atom_root), source)
                request["input_tokens"] = len(build_prompt(request, _render(request, catalog)).encode("utf-8"))
                requests.append(request)
                target_chars += hi - lo
                dispositions.append(dict(block_id=block["block_id"], target_id=target,
                    request_id=request["request_id"], start_char=lo, end_char=hi, status="planned"))
            if cursor != b:
                raise ValueError("derived_slice_missing_tail")
        if source_cursor != len(source):
            raise ValueError("source_partition_missing_tail")
        case_coverage.append(dict(case_id=cid, source_hash=sh, source_chars=len(source),
            target_chars=target_chars, source_addressable_rate=1.0,
            non_whitespace_target_coverage=1.0, dispositions=dispositions))
    return dict(artifact_type="AUCompactLockedManifest", schema_version="au-compact-manifest-v1",
        base_manifest_sha256=file_hash(source_manifest), plan04_build_manifest_sha256=file_hash(ap),
        requests=requests, milestone1=dict(version=VERSION, source_manifest=str(source_manifest),
            block_root=str(block_root), model=model, context_chars=context_chars,
            output_tokens=output_tokens, prompt_identity=prompt_identity(),
            decoder_version=RESPONSE_FORMAT_VERSION, block_build_sha256=file_hash(bp),
            cases=case_coverage, semantic_quality_claim=False, kos_annotations_used=False))


def preflight(manifest, *, source_store, atom_root, budget=None, max_input_tokens=11488):
    if type(max_input_tokens) is not int or not 1 <= max_input_tokens <= 11488:
        raise ValueError("invalid_input_ceiling")
    failures = []
    meta = manifest.get("milestone1", {})
    try:
        if meta.get("version") != VERSION:
            raise ValueError("not_milestone1_full_manifest")
        rebuilt = build_manifest(source_manifest=meta["source_manifest"], source_store=source_store,
            atom_root=atom_root, model=meta["model"], context_chars=meta["context_chars"],
            output_tokens=meta["output_tokens"], block_root=meta["block_root"])
        if manifest != rebuilt:
            raise ValueError("manifest_not_current_canonical_full_workload")
    except Exception as exc:
        failures.append({"stage": "source_coverage_identity", "error": str(exc)})
    base = compact_preflight(manifest, source_store, atom_root)
    failures.extend(base["failures"])
    costs = []
    if not failures:
        for q in manifest["requests"]:
            source = open_source(source_store, q["case_id"], q["source_hash"])
            catalog = build_evidence_catalog(q, _binding_path(q["atom_binding"], atom_root), source)
            prompt_bytes = len(build_prompt(q, _render(q, catalog)).encode("utf-8"))
            estimate = prompt_bytes + 128  # Reserve chat framing as well as the complete prompt.
            costs.append(dict(request_id=q["request_id"], case_id=q["case_id"],
                full_prompt_bytes=prompt_bytes, framing_reserve=128,
                estimated_input_tokens=estimate, output_reserve=q["spec"]["caps"]["output_tokens"]))
            if estimate > max_input_tokens:
                failures.append(dict(stage="per_request_input", request_id=q["request_id"],
                    estimate=estimate, ceiling=max_input_tokens))
    planned = dict(max_requests=len(costs), max_provider_attempts=len(costs),
        max_total_input_tokens=sum(r["estimated_input_tokens"] for r in costs),
        max_total_output_tokens=sum(r["output_reserve"] for r in costs))
    effective = copy.deepcopy(planned if budget is None else budget)
    for key in planned:
        if type(effective.get(key)) is not int or effective[key] < planned[key]:
            failures.append(dict(stage="aggregate_budget", field=key,
                required=planned[key], configured=effective.get(key)))
    return dict(artifact_type="Milestone1Preflight", version=VERSION,
        status="pass" if not failures else "fail", manifest_sha256=digest(manifest),
        prompt_identity=prompt_identity(), decoder_version=RESPONSE_FORMAT_VERSION,
        input_estimate_method="full_prompt_utf8_bytes_plus128_framing_not_provider_usage",
        request_count=len(manifest.get("requests", [])), cases=meta.get("cases", []),
        per_request_input_ceiling=max_input_tokens, planned_budget=planned, approved_budget=effective,
        budget_mode="explicit_planned_budget" if budget is None else "configured_budget",
        costs=costs, compact_preflight=base, failures=failures,
        warmup_and_probe_budget="separate; recorded by runner, not included in source requests",
        semantic_quality="not_evaluated")
