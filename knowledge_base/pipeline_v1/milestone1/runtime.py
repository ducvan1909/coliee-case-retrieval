"""Explicit approved-workload execution through the existing compact runner."""
from __future__ import annotations

import copy
from pathlib import Path

from .core import digest, preflight
from ..au_compact import runner


def run(manifest, *, preflight_report, source_store, atom_root, cfg, output_root,
        warmup_policy, execute=False, retry_provider_unavailable=False):
    if not execute:
        raise ValueError("milestone1_execution_requires_execute")
    if preflight_report.get("status") != "pass" or preflight_report.get("manifest_sha256") != digest(manifest):
        raise ValueError("approved_preflight_missing_or_stale")
    model = manifest["milestone1"]["model"]
    if cfg.get("model") != model or cfg.get("enable_thinking") is not False:
        raise ValueError("runtime_model_or_thinking_differs_from_manifest")
    check = preflight(manifest, source_store=source_store, atom_root=atom_root,
        budget=preflight_report["approved_budget"],
        max_input_tokens=preflight_report["per_request_input_ceiling"])
    if check["status"] != "pass" or check["prompt_identity"] != preflight_report["prompt_identity"] or check["decoder_version"] != preflight_report["decoder_version"]:
        raise ValueError("current_preflight_failed_or_decoder_changed")
    for field in ("version", "request_count", "cases", "costs", "planned_budget", "compact_preflight"):
        if check.get(field) != preflight_report.get(field):
            raise ValueError("preflight_content_differs_from_current_workload")
    cfg = copy.deepcopy(cfg)
    # Frozen M1 transport policy, never a model/provider fallback.
    cfg.update(transport="jobs", string_decoder="host_validated")
    if not cfg.get("jobs_url"):
        if not cfg.get("url", "").endswith("/v1/chat/completions"):
            raise ValueError("jobs_url_required")
        cfg["jobs_url"] = cfg["url"][:-len("/chat/completions")] + "/jobs"
    root = Path(output_root).resolve()
    for dependency in (source_store, atom_root, manifest["milestone1"]["block_root"]):
        if root.is_relative_to(Path(dependency).resolve()):
            raise ValueError("output_overlaps_source_dependency")
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "milestone1_run.lock"
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise ValueError("milestone1_run_locked_manual_recovery_required") from None
    try:
        handle.close()
        result = runner.run(manifest, source_store=source_store, atom_root=atom_root,
            cfg=cfg, budget=check["approved_budget"], cache_dir=root / "cache",
            execute=True, warmup_policy=warmup_policy,
            retry_provider_unavailable=retry_provider_unavailable)
    finally:
        lock.unlink(missing_ok=True)
    rows = result["request_ledger"]
    expected = {q["request_id"]: q for q in manifest["requests"]}
    actual_ids = [r["request"]["request_id"] for r in rows]
    missing = sorted(set(expected) - set(actual_ids))
    unexpected = sorted(set(actual_ids) - set(expected))
    identity_invalid = len(actual_ids) != len(set(actual_ids)) or bool(unexpected) or any(
        r["request"] != expected.get(r["request"]["request_id"]) for r in rows)
    needs_split = [r["request"]["request_id"] for r in rows
        if isinstance(r.get("compact_response"), dict) and r["compact_response"].get("coverage_status") == "needs_split"]
    unresolved = [r["request"]["request_id"] for r in rows if r["status"] != "protocol_verified" or
        any(t["decision"] == "unresolved" for t in (r.get("response") or {}).get("target_results", []))]
    result["milestone1"] = dict(version=manifest["milestone1"]["version"],
        preflight_sha256=digest(preflight_report), protocol_status=result["status"],
        expected_requests=len(manifest["requests"]), needs_split_request_ids=needs_split,
        unrun_request_ids=missing, unexpected_request_ids=unexpected,
        runner_request_identity_invalid=identity_invalid,
        unresolved_request_ids=unresolved, semantic_accepted=False,
        kos_annotations_used_for_extraction=False,
        transport="jobs", string_decoder="host_validated")
    if needs_split or unresolved or missing or identity_invalid:
        result["status"] = "incomplete"
    return result
