from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path

from .config import ROOT, api_config, number, settings
from .endpoint import Endpoint, confirm_local_environment_block
from .pipeline_v10 import build_case
from .pipeline_v9 import _has_unresolved_protocol, output_status_for_checkpoint
from .schema_v10 import PROMPT_VERSION as VERSION, SCHEMA_VERSION
from .source import digest, prepare, save

CONTROL_EXPERIMENT = ROOT / "outputs/pilot_v11_reading_control"
GUIDED_EXPERIMENT = ROOT / "outputs/pilot_v11_reading_guided"
CANDIDATE_EXPERIMENT = ROOT / "outputs/pilot_v12_candidate_selection"
SEPARATED_EXPERIMENT = ROOT / "outputs/pilot_v13_extract_before_navigate_local_scan"
AUDITED_EXPERIMENT = ROOT / "outputs/pilot_v14_direct_choices_scan_fix"
TWO_STAGE_EXPERIMENT = ROOT / "outputs/pilot_v15_two_stage_triage"
CHOICE_DIAGNOSTIC_EXPERIMENT = ROOT / "outputs/pilot_v14_choice_diagnostic"
SELECTION_DIAGNOSTIC_EXPERIMENT = ROOT / "outputs/pilot_v14_selection_diagnostic_contract_fix"
SELECTION_DIAGNOSTIC_LARGE_EXPERIMENT = ROOT / "outputs/pilot_v14_selection_diagnostic_large_only"
DEFAULT_EXPERIMENT = TWO_STAGE_EXPERIMENT
SHARED_LEDGER = ROOT / "outputs/pilot_budget.json"
SHARED_LEDGER_LOCK = ROOT / "outputs/pilot_budget.lock"
LEGACY_LEDGER = ROOT / "outputs/pilot_v1/budget.json"


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(f"Run lock exists: {path}; inspect it before removing a stale lock") from None
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def _fingerprint(manifest_bytes: bytes, config: dict, size: int, steps: int,
                 reading_policy: str = "v10") -> dict:
    guided = reading_policy in {"guided", "candidate", "candidate-separated",
                                "audited-candidates", "two-stage-candidates"}
    if reading_policy == "two-stage-candidates":
        from .schema_v15 import (PROMPT_VERSION as prompt_version,
                                 REFINEMENT_BATCH_SIZE, SCHEMA_VERSION as schema_version,
                                 TRIAGE_BATCH_SIZE)
        from .schema_v12 import SOURCE_BATCH_SIZE
    elif reading_policy == "audited-candidates":
        from .schema_v14 import PROMPT_VERSION as prompt_version
        from .schema_v14 import SCHEMA_VERSION as schema_version
        from .schema_v12 import SOURCE_BATCH_SIZE
    elif reading_policy == "candidate-separated":
        from .schema_v13 import PROMPT_VERSION as prompt_version
        from .schema_v13 import SCHEMA_VERSION as schema_version
        from .schema_v12 import SOURCE_BATCH_SIZE
    elif reading_policy == "candidate":
        from .schema_v12 import PROMPT_VERSION as prompt_version
        from .schema_v12 import SCHEMA_VERSION as schema_version
        from .schema_v12 import SOURCE_BATCH_SIZE
    elif guided:
        from .schema_v11 import PROMPT_VERSION as prompt_version
        from .schema_v11 import SCHEMA_VERSION as schema_version
    else:
        prompt_version, schema_version = VERSION, SCHEMA_VERSION
    return {"schema_version": schema_version, "manifest_hash": digest(manifest_bytes),
        "prompt_version": prompt_version, "reader": config["reader"],
        "repair": config.get("repair", config["reader"]),
        "reading_policy": reading_policy,
        "endpoint_hash": digest(config["url"].encode()),
        "window_chars": size, "read_steps": steps, "max_tokens": config["tokens"],
        "workflow": "constrained_reader_selection_classification_treatment_finalizer",
        "selection_extra_windows": 2, "protocol_repair_requests": 0,
        **({"shared_read_actions": 7,
            "reread_enabled": reading_policy != "two-stage-candidates",
            "guided_catalogue": "heading_marker_v1"} if guided else {}),
        **({"candidate_batch_size": SOURCE_BATCH_SIZE,
            "candidate_source_choice": "include_exclude_by_host_key",
            "new_item_anchor": "single_source",
            "max_source_scan_requests": config["max_source_scan_requests"]}
           if reading_policy in {"candidate", "candidate-separated",
                                 "audited-candidates", "two-stage-candidates"} else {}),
        **({"separate_extraction_navigation": True,
            "source_group_assessment": "required",
            "selection_empty_source_fallback": "last_processed_group"}
           if reading_policy in {"candidate-separated", "audited-candidates"} else {}),
        **({"candidate_triage": "direct_paragraph_and_sentence_keys",
            "source_payload": "single_text_with_sentence_offsets",
            "scan_modes": ["scan_extend", "scan_reconsider"],
            "shared_source_attribution": True,
            "authority_response_witnesses": True}
           if reading_policy == "audited-candidates" else {}),
        **({"candidate_triage": "paragraph_then_optional_sentence",
            "triage_batch_size": TRIAGE_BATCH_SIZE,
            "refinement_batch_size": REFINEMENT_BATCH_SIZE,
            "source_payload": "paragraph_text_once_with_sentence_offsets_on_refine",
            "scan_modes": ["scan_extend", "scan_reconsider"],
            "automatic_scan_for_new_items": False}
           if reading_policy == "two-stage-candidates" else {}),
        "temperature": config["temperature"], "top_p": config["top_p"],
        "reasoning_effort": config["reasoning_effort"],
        "reserve_usd": config["reserve"], "budget_usd": config["budget"],
        "timeout_seconds": config["timeout"],
        "startup_wait_seconds": config["startup_wait"],
        "implementation_hashes": {path.name: digest(path.read_bytes())
                                  for path in sorted(ROOT.glob("*.py"))}}


def _report(experiment: Path) -> dict:
    groups = {"extractive_v15": [], "extractive_v14": [], "extractive_v13": [], "extractive_v12": [], "extractive_v11": [], "extractive_v10": [], "extractive_v9": [], "extractive_v8": [], "extractive_v7": [], "extractive_v6": [], "extractive_v5": [], "extractive_v4": [], "extractive_v3": [], "extractive_v2": [],
              "legacy_v1": []}
    failures, incomplete_without_case = [], []
    calls = []
    if SHARED_LEDGER.exists():
        ledger = json.loads(SHARED_LEDGER.read_text(encoding="utf-8"))
        calls = [call for call in ledger.get("calls", [])
                 if call.get("experiment", "").split(":", 1)[0] == experiment.name]

    def usage_for(case_id: str) -> dict:
        matching = [call for call in calls if call.get("case_id") == case_id]
        return {"requests": len(matching),
                "prompt_tokens": sum(call.get("usage", {}).get("prompt_tokens", 0)
                                     for call in matching),
                "completion_tokens": sum(call.get("usage", {}).get("completion_tokens", 0)
                                         for call in matching),
                "elapsed_seconds": round(sum(call.get("elapsed_seconds", 0)
                                             for call in matching), 3),
                "internal_reserve_usd": round(sum(call.get("reserve_usd", 0) -
                    call.get("reserve_released_usd", 0) for call in matching), 3)}
    for path in sorted(experiment.glob("*/*/case.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        if case.get("schema_version") in {6, 7, 8, 9, 10, 11, 12, 13, 14, 15}:
            checkpoint_path = path.parent / "checkpoint.json"
            checkpoint = (json.loads(checkpoint_path.read_text(encoding="utf-8"))
                          if checkpoint_path.exists() else {})
            missing_final = (case.get("schema_version") in {8, 9, 10, 11, 12, 13, 14, 15} and
                (not checkpoint or checkpoint.get("stage") != "complete" or
                 (checkpoint.get("request_journal", {}).get("finalizer:0", {}).get(
                     "status") != "applied" and not (case.get("schema_version") in {14, 15}
                     and checkpoint.get("stop_reason") == "host_finalized_empty")
                  if case.get("schema_version") in {10, 11, 12, 13, 14, 15} else
                  "finalizer:0" not in checkpoint.get("processed_responses", {}))))
            if case.get("schema_version") in {13, 14}:
                missing_final = missing_final or bool(
                    checkpoint.get("source_scan_queue") or
                    checkpoint.get("pending_source_ids") or
                    checkpoint.get("pending_window_ids") or
                    sum(not entry.get("reused_last_group", False) for entry in
                        checkpoint.get("batch_assessments", [])) !=
                    1 + checkpoint.get("read_actions", 0))
            if case.get("schema_version") == 15:
                missing_final = missing_final or bool(
                    checkpoint.get("source_scan_queue") or
                    checkpoint.get("triage_queue") or
                    checkpoint.get("refinement_queue") or
                    checkpoint.get("pending_source_ids") or
                    checkpoint.get("pending_window_ids"))
            protocol_status = ("failure" if (bool(checkpoint.get("protocol_errors"))
                               if case.get("schema_version") in {10, 11, 12, 13, 14, 15} else
                               _has_unresolved_protocol(checkpoint))
                               or missing_final
                               else case["protocol_status"])
            execution_status = ("incomplete" if protocol_status == "failure" and
                                case["execution_status"] == "completed" else
                                case["execution_status"])
            output_status = (output_status_for_checkpoint(checkpoint, execution_status)
                if case.get("schema_version") == 9 else
                ("incomplete" if execution_status != "completed" else
                 case["output_status"]))
            row = {"case_id": case["case_id"],
                "split": path.parent.parent.name,
                "execution_status": execution_status,
                "protocol_status": protocol_status,
                "output_status": output_status,
                "empty_reason": case.get("empty_reason") if output_status == "empty_output" else None,
                "quality_status": case["quality_status"], "counts": case["counts"],
                "source_coverage": case["source_coverage"],
                "coverage_by_phase": case.get("coverage_by_phase", {}),
                "model_usage": usage_for(case["case_id"]),
                **({"reading_history": case.get("reading_history", []),
                    "unread_window_ids": case.get("unread_window_ids", [])}
                   if case.get("schema_version") in {11, 12, 13, 14, 15} else {}),
                **({"batch_assessments": case.get("batch_assessments", []),
                    "source_groups_provided": case["counts"].get("source_groups_provided"),
                    "source_groups_processed": case["counts"].get("source_groups_processed")}
                   if case.get("schema_version") in {13, 14} else {}),
                **({"candidate_uncertain_count": case.get("candidate_uncertain_count", 0),
                    "empty_with_unread": case.get("empty_with_unread", False)}
                   if case.get("schema_version") == 14 else {})}
            if case.get("schema_version") == 15:
                row.update({"candidate_uncertain_count": case.get(
                    "candidate_uncertain_count", 0),
                    "omission_review_required": case.get(
                        "omission_review_required", False),
                    "paragraphs_triaged": case.get("paragraphs_triaged", 0),
                    "refined_paragraphs": case.get("refined_paragraphs", 0)})
            if output_status != case["output_status"]:
                row["original_output_status"] = case["output_status"]
            if execution_status != case["execution_status"]:
                row["original_execution_status"] = case["execution_status"]
            if protocol_status != case["protocol_status"]:
                row["original_protocol_status"] = case["protocol_status"]
            groups[f"extractive_v{case['schema_version']}"].append(row)
        elif case.get("schema_version") in {3, 4, 5}:
            group = {3: "extractive_v3", 4: "extractive_v4",
                     5: "extractive_v5"}[case.get("schema_version")]
            groups[group].append({"case_id": case["case_id"],
                "split": path.parent.parent.name, "execution_status": case["execution_status"],
                "protocol_status": case["protocol_status"],
                "verification_status": case["verification_status"],
                "semantic_status": case["semantic_status"], "counts": case["counts"],
                "reader_coverage": case["reader_coverage"],
                "verifier_coverage": case["verifier_coverage"],
                "acceptance_basis": case.get("acceptance_basis"),
                "au_search_outcome": case.get("au_search_outcome")})
        elif case.get("schema_version") == 2:
            groups["extractive_v2"].append({"case_id": case["case_id"],
                "split": path.parent.parent.name, "execution_status": case["execution_status"],
                "semantic_status": case["semantic_status"], "counts": case["counts"],
                "coverage": case["coverage"]})
        else:
            groups["legacy_v1"].append({"case_id": case["case_id"],
                "split": path.parent.parent.name, "status": case.get("processing_status"),
                "accepted_aus": len(case.get("au_ids", [])), "coverage": case.get("coverage")})
    for failure in experiment.glob("*/*/failure.json"):
        result = failure.parent / "case.json"
        resolved = result.exists() and json.loads(result.read_text(encoding="utf-8")).get("execution_status") == "completed"
        if not resolved:
            failures.append(str(failure.relative_to(experiment)))
    for checkpoint_path in sorted(experiment.glob("*/*/checkpoint.json")):
        if (checkpoint_path.parent / "case.json").exists():
            continue
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        incomplete_without_case.append({"case_id": checkpoint_path.parent.name,
            "split": checkpoint_path.parent.parent.name,
            "schema_version": checkpoint.get("schema_version"),
            "execution_status": "incomplete", "output_status": "incomplete",
            "protocol_status": "failure" if (bool(checkpoint.get("protocol_errors"))
                                if checkpoint.get("schema_version") in {10, 11, 12, 13, 14, 15} else
                               _has_unresolved_protocol(checkpoint))
                               else "unknown",
            "checkpoint_stage": checkpoint.get("stage"),
            "failure_path": (str((checkpoint_path.parent / "failure.json").relative_to(
                experiment)) if (checkpoint_path.parent / "failure.json").exists() else None)})
    for failure in experiment.glob("*/*/failure.json"):
        if ((failure.parent / "case.json").exists() or
                (failure.parent / "checkpoint.json").exists()):
            continue
        incomplete_without_case.append({"case_id": failure.parent.name,
            "split": failure.parent.parent.name, "schema_version": None,
            "execution_status": "incomplete", "output_status": "incomplete",
            "protocol_status": "unknown", "checkpoint_stage": None,
            "failure_path": str(failure.relative_to(experiment))})
    return {"groups": groups, "failures": failures,
            "incomplete_without_case": incomplete_without_case,
            "capability_usage": {"requests": sum(call.get("stage") == "capability_probe"
                                                    for call in calls),
                                 "prompt_tokens": sum(call.get("usage", {}).get(
                                     "prompt_tokens", 0) for call in calls
                                     if call.get("stage") == "capability_probe"),
                                 "completion_tokens": sum(call.get("usage", {}).get(
                                     "completion_tokens", 0) for call in calls
                                     if call.get("stage") == "capability_probe")},
            "quality_note": "V1 abstractive and V2-V15 extractive results are reported separately. V10-V15 quality remains not_evaluated until external review. Schema validity and coverage are not semantic quality."}


def main():
    parser = argparse.ArgumentParser(description="Case/AU knowledge-base pilot")
    parser.add_argument("--env-file", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    sub.add_parser("preflight")
    probe_parser = sub.add_parser("probe-v10")
    probe_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    probe_parser.add_argument("--experiment", type=Path, default=CONTROL_EXPERIMENT)
    probe_parser.add_argument("--execute", action="store_true")
    probe_parser.add_argument("--retry-provider-unavailable", action="store_true")
    probe_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    guided_probe_parser = sub.add_parser("probe-v11")
    guided_probe_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    guided_probe_parser.add_argument("--experiment", type=Path, default=GUIDED_EXPERIMENT)
    guided_probe_parser.add_argument("--execute", action="store_true")
    guided_probe_parser.add_argument("--retry-provider-unavailable", action="store_true")
    guided_probe_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    candidate_probe_parser = sub.add_parser("probe-v12")
    candidate_probe_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    candidate_probe_parser.add_argument("--experiment", type=Path, default=CANDIDATE_EXPERIMENT)
    candidate_probe_parser.add_argument("--execute", action="store_true")
    candidate_probe_parser.add_argument("--retry-provider-unavailable", action="store_true")
    candidate_probe_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    separated_probe_parser = sub.add_parser("probe-v13")
    separated_probe_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    separated_probe_parser.add_argument("--experiment", type=Path, default=SEPARATED_EXPERIMENT)
    separated_probe_parser.add_argument("--execute", action="store_true")
    separated_probe_parser.add_argument("--retry-provider-unavailable", action="store_true")
    separated_probe_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    audited_probe_parser = sub.add_parser("probe-v14")
    audited_probe_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    audited_probe_parser.add_argument("--experiment", type=Path, default=AUDITED_EXPERIMENT)
    audited_probe_parser.add_argument("--execute", action="store_true")
    audited_probe_parser.add_argument("--retry-provider-unavailable", action="store_true")
    audited_probe_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    two_stage_probe_parser = sub.add_parser("probe-v15")
    two_stage_probe_parser.add_argument("--manifest", type=Path,
                                         default=ROOT / "outputs/manifest.json")
    two_stage_probe_parser.add_argument("--experiment", type=Path,
                                         default=TWO_STAGE_EXPERIMENT)
    two_stage_probe_parser.add_argument("--execute", action="store_true")
    two_stage_probe_parser.add_argument("--retry-provider-unavailable", action="store_true")
    two_stage_probe_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    sentence_probe_parser = sub.add_parser("probe-v14-sentences")
    sentence_probe_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    sentence_probe_parser.add_argument("--experiment", type=Path, default=AUDITED_EXPERIMENT)
    sentence_probe_parser.add_argument("--execute", action="store_true")
    sentence_probe_parser.add_argument("--retry-provider-unavailable", action="store_true")
    sentence_probe_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    choice_diagnostic_parser = sub.add_parser("diagnose-v14-choices")
    choice_diagnostic_parser.add_argument("--manifest", type=Path,
                                           default=ROOT / "outputs/manifest.json")
    choice_diagnostic_parser.add_argument("--experiment", type=Path,
                                           default=CHOICE_DIAGNOSTIC_EXPERIMENT)
    choice_diagnostic_parser.add_argument("--execute", action="store_true")
    choice_diagnostic_parser.add_argument("--retry-provider-unavailable", action="store_true")
    choice_diagnostic_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    selection_diagnostic_parser = sub.add_parser("diagnose-v14-selection")
    selection_diagnostic_parser.add_argument("--manifest", type=Path,
                                              default=ROOT / "outputs/manifest.json")
    selection_diagnostic_parser.add_argument("--experiment", type=Path)
    selection_diagnostic_parser.add_argument("--large-only", action="store_true")
    selection_diagnostic_parser.add_argument("--execute", action="store_true")
    selection_diagnostic_parser.add_argument("--retry-provider-unavailable", action="store_true")
    selection_diagnostic_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    run_parser.add_argument("--split", choices=["calibration", "evaluation"], required=True)
    run_parser.add_argument("--experiment", type=Path)
    run_parser.add_argument("--reading-policy", choices=["v10", "guided", "candidate",
                                                         "candidate-separated", "audited-candidates",
                                                         "two-stage-candidates"],
                            default="two-stage-candidates")
    run_parser.add_argument("--execute", action="store_true")
    run_parser.add_argument("--resume", action="store_true")
    run_parser.add_argument("--retry-provider-unavailable", action="store_true")
    run_parser.add_argument("--retry-confirmed-local-block", action="store_true")
    run_parser.add_argument("--recheck-verifier-errors", action="store_true")
    run_parser.add_argument("--case-id", action="append", default=[],
                            help="Run only this case from the selected split; repeat to preserve an explicit order")
    recover_parser = sub.add_parser("recover-v6")
    recover_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    recover_parser.add_argument("--source-experiment", type=Path,
                                default=ROOT / "outputs/pilot_v6")
    recover_parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    recover_parser.add_argument("--execute", action="store_true",
                                help="Apply the validated offline inheritance; default is preview only")
    revision_parser = sub.add_parser("recover-v6-revision")
    revision_parser.add_argument("--manifest", type=Path, default=ROOT / "outputs/manifest.json")
    revision_parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    revision_parser.add_argument("--execute", action="store_true",
                                 help="Apply the cached revision correction; default is preview only")
    report_parser = sub.add_parser("report")
    report_parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    pair_parser = sub.add_parser("compare-reading")
    pair_parser.add_argument("--control", type=Path, default=CONTROL_EXPERIMENT)
    pair_parser.add_argument("--guided", type=Path, default=GUIDED_EXPERIMENT)
    pair_parser.add_argument("--inventory", type=Path,
                             default=ROOT / "V11_SOURCE_INVENTORY.md")
    pair_parser.add_argument("--output", type=Path,
                             default=GUIDED_EXPERIMENT / "paired_comparison.json")
    adjudication_parser = sub.add_parser("adjudication")
    adjudication_parser.add_argument("--source-experiment", type=Path,
                                     default=DEFAULT_EXPERIMENT)
    adjudication_parser.add_argument("--destination", type=Path,
                                     default=DEFAULT_EXPERIMENT / "adjudication_template.json")
    reconcile_parser = sub.add_parser("reconcile-local-block")
    reconcile_parser.add_argument("--request-id", required=True)
    reconcile_parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    if args.command == "run" and args.experiment is None:
        args.experiment = ({"v10": CONTROL_EXPERIMENT,
                            "guided": GUIDED_EXPERIMENT,
                            "candidate": CANDIDATE_EXPERIMENT,
                            "candidate-separated": SEPARATED_EXPERIMENT,
                            "audited-candidates": AUDITED_EXPERIMENT,
                            "two-stage-candidates": TWO_STAGE_EXPERIMENT}[args.reading_policy])
    env = settings(args.env_file)

    if args.command == "reconcile-local-block":
        result = confirm_local_environment_block(SHARED_LEDGER, args.request_id, args.evidence)
        print(json.dumps({"request_id": result["request_id"], "status": result["status"],
                          "reserve_released_usd": result.get("reserve_released_usd", 0)},
                         indent=2))
        return

    if args.command == "compare":
        from .comparison import export_review
        print(export_review(args.experiment, env.get("KB_KOS_DIR", "G:/Legal-AI/kos_sample")))
        return
    if args.command == "compare-reading":
        from .reading_comparison_v11 import export_pair
        print(export_pair(args.control, args.guided, args.inventory,
                          SHARED_LEDGER, args.output))
        return
    if args.command == "adjudication":
        from .adjudication import create_adjudication
        print(create_adjudication(args.source_experiment, args.destination))
        return
    if args.command == "prepare":
        manifest = prepare(env.get("KB_KOS_DIR", "G:/Legal-AI/kos_sample"),
                           env.get("KB_SOURCE_DIR", str(ROOT.parent / "data/task1_train_files_2026/cases")),
                           args.manifest)
        print(json.dumps({"cohort": len(manifest["cases"]), "splits": manifest["splits"]}, indent=2))
        return
    if args.command == "report":
        result = _report(args.experiment)
        save(args.experiment / "report.json", result)
        print(json.dumps(result, indent=2))
        return

    config = api_config(env)
    config["max_source_scan_requests"] = number(
        env, "KB_MAX_SOURCE_SCAN_REQUESTS", 24, True)
    if getattr(args, "recheck_verifier_errors", False):
        raise ValueError("--recheck-verifier-errors is not available for schema V10; V10 has no model verifier")
    size = number(env, "KB_WINDOW_CHARS", 10000, True)
    steps = number(env, "KB_MAX_READ_STEPS", 6, True)
    inherited = 0
    if SHARED_LEDGER.exists():
        inherited = json.loads(SHARED_LEDGER.read_text(encoding="utf-8")).get("reserved_usd", 0)
    elif LEGACY_LEDGER.exists():
        inherited = json.loads(LEGACY_LEDGER.read_text(encoding="utf-8")).get("reserved_usd", 0)
    if args.command == "preflight":
        print("Configuration valid. No network request made.")
        if config["budget"] is None:
            print(f"Shared reserved USD: {inherited:.2f}; internal budget limit: unlimited")
        else:
            available = max(0, config["budget"] - inherited)
            print(f"Shared reserved USD: {inherited:.2f}; available reserve: {available:.2f}; "
                  f"additional requests: {int(available / config['reserve'])}")
        return

    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    if args.command == "diagnose-v14-selection":
        from .selection_diagnostic_v14 import CASE_ID, VERSION as diagnostic_version
        from .selection_diagnostic_v14 import cases, probe
        if args.experiment is None:
            args.experiment = (SELECTION_DIAGNOSTIC_LARGE_EXPERIMENT if
                args.large_only else SELECTION_DIAGNOSTIC_EXPERIMENT)
        if CASE_ID not in manifest["splits"]["calibration"]:
            raise ValueError("Selection diagnostic case is not in calibration")
        row = next(row for row in manifest["cases"] if row["case_id"] == CASE_ID)
        _, arms = cases(row)
        count = sum(not args.large_only or arm["size"] == "large" for arm in arms)
        print(f"Selection diagnostic: {count} structured-output requests on "
              f"case {CASE_ID}; internal reserve ceiling "
              f"{count * config['reserve']:.2f} USD, not measured Modal charges.")
        if not args.execute:
            return
        fingerprint = {**_fingerprint(manifest_bytes, config, size, steps,
                                      "audited-candidates"),
                       "diagnostic_version": diagnostic_version,
                       "diagnostic_scope": "large_only" if args.large_only else "all"}
        with exclusive_lock(SHARED_LEDGER_LOCK):
            with exclusive_lock(args.experiment / ".run.lock"):
                config_path = args.experiment / "config.json"
                if (config_path.exists() and
                        json.loads(config_path.read_text(encoding="utf-8")) != fingerprint):
                    raise ValueError("Selection diagnostic configuration changed")
                save(config_path, fingerprint)
                client = Endpoint(config, SHARED_LEDGER, LEGACY_LEDGER,
                    allow_provider_retry=args.retry_provider_unavailable,
                    allow_confirmed_local_retry=args.retry_confirmed_local_block)
                result = probe(client, config, args.experiment, fingerprint, row,
                               large_only=args.large_only)
                print("V14 selection diagnostic: " + result["status"])
                if result["status"] != "complete":
                    raise SystemExit(1)
        return
    if args.command == "diagnose-v14-choices":
        print("Choice diagnostic: 2 structured-output requests on identical source; "
              f"internal reserve ceiling {2 * config['reserve']:.2f} USD, "
              "not measured Modal charges.")
        if not args.execute:
            return
        from .choice_diagnostic_v14 import VERSION as diagnostic_version, probe
        fingerprint = {**_fingerprint(manifest_bytes, config, size, steps,
                                      "audited-candidates"),
                       "diagnostic_version": diagnostic_version}
        with exclusive_lock(SHARED_LEDGER_LOCK):
            with exclusive_lock(args.experiment / ".run.lock"):
                config_path = args.experiment / "config.json"
                if (config_path.exists() and
                        json.loads(config_path.read_text(encoding="utf-8")) != fingerprint):
                    raise ValueError("Choice diagnostic configuration changed")
                save(config_path, fingerprint)
                client = Endpoint(config, SHARED_LEDGER, LEGACY_LEDGER,
                    allow_provider_retry=args.retry_provider_unavailable,
                    allow_confirmed_local_retry=args.retry_confirmed_local_block)
                result = probe(client, config, args.experiment, fingerprint)
                print("V14 choice diagnostic: " + result["status"])
                if result["status"] != "passed":
                    raise SystemExit(1)
        return
    if args.command == "recover-v6":
        from .recovery_v6 import inherit_case
        fingerprint = _fingerprint(manifest_bytes, config, size, steps)
        with exclusive_lock(SHARED_LEDGER_LOCK):
            with exclusive_lock(args.experiment.parent / f"{args.experiment.name}.recovery.lock"):
                result = inherit_case(args.source_experiment, args.experiment,
                                      manifest, fingerprint, SHARED_LEDGER,
                                      execute=args.execute)
        print(json.dumps(result, indent=2))
        return
    if args.command == "recover-v6-revision":
        from .recovery_v6 import recover_revision_repair
        fingerprint = _fingerprint(manifest_bytes, config, size, steps)
        with exclusive_lock(SHARED_LEDGER_LOCK):
            with exclusive_lock(args.experiment.parent / f"{args.experiment.name}.recovery.lock"):
                result = recover_revision_repair(args.experiment, manifest, fingerprint,
                                                 SHARED_LEDGER, execute=args.execute)
        print(json.dumps(result, indent=2))
        return
    if args.command in {"probe-v10", "probe-v11", "probe-v12", "probe-v13",
                        "probe-v14", "probe-v14-sentences", "probe-v15"}:
        policy = {"probe-v10": "v10", "probe-v11": "guided",
                  "probe-v12": "candidate", "probe-v13": "candidate-separated",
                  "probe-v14": "audited-candidates",
                  "probe-v14-sentences": "audited-candidates",
                  "probe-v15": "two-stage-candidates"}[args.command]
        sentence_only = args.command == "probe-v14-sentences"
        count = (1 if sentence_only else {"v10": 3, "guided": 5, "candidate": 7,
                 "candidate-separated": 9, "audited-candidates": 11,
                 "two-stage-candidates": 11}[policy])
        print(f"Capability gate: {count} structured-output requests, internal reserve ceiling "
              f"{count * config['reserve']:.2f} USD; not measured Modal charges.")
        if not args.execute:
            return
        fingerprint = _fingerprint(manifest_bytes, config, size, steps, policy)
        with exclusive_lock(SHARED_LEDGER_LOCK):
            with exclusive_lock(args.experiment / ".run.lock"):
                config_path = args.experiment / "config.json"
                if (config_path.exists() and
                        json.loads(config_path.read_text(encoding="utf-8")) != fingerprint):
                    raise ValueError("Experiment configuration changed")
                save(config_path, fingerprint)
                client = Endpoint(config, SHARED_LEDGER, LEGACY_LEDGER,
                                  allow_provider_retry=args.retry_provider_unavailable,
                                  allow_confirmed_local_retry=args.retry_confirmed_local_block)
                if policy == "two-stage-candidates":
                    from .capability_v15 import probe
                elif policy == "audited-candidates":
                    from .capability_v14 import probe
                elif policy == "candidate-separated":
                    from .capability_v13 import probe
                elif policy == "candidate":
                    from .capability_v12 import probe
                elif policy == "guided":
                    from .capability_v11 import probe
                else:
                    from .capability_v10 import probe
                result = (probe(client, config, args.experiment, fingerprint,
                                sentence_only=True) if sentence_only else
                          probe(client, config, args.experiment, fingerprint))
                probe_version = {"v10": 10, "guided": 11, "candidate": 12,
                                 "candidate-separated": 13, "audited-candidates": 14,
                                 "two-stage-candidates": 15}[policy]
                probe_status = ("passed; full gate pending" if sentence_only and
                    result["results"] and not result["results"][0]["errors"] else
                    result["status"])
                print(f"V{probe_version} {'sentence' if sentence_only else 'full'} "
                      f"capability: {probe_status}")
        return
    selected = manifest["splits"][args.split]
    if args.case_id:
        if len(args.case_id) != len(set(args.case_id)):
            raise ValueError("Duplicate --case-id values are not allowed")
        outside = [case_id for case_id in args.case_id if case_id not in selected]
        if outside:
            raise ValueError(f"Case IDs not in {args.split}: {', '.join(outside)}")
        selected = args.case_id
    if args.split == "evaluation" and args.execute:
        raise ValueError("The pilot is calibration-only until the external five-case quality gate is passed")
    version = {"v10": 10, "guided": 11, "candidate": 12,
               "candidate-separated": 13, "audited-candidates": 14,
               "two-stage-candidates": 15}[args.reading_policy]
    print(f"Selected {len(selected)} cases; schema={version}; execute={args.execute}")
    probes = {"v10": 3, "guided": 5, "candidate": 7,
              "candidate-separated": 9, "audited-candidates": 11,
              "two-stage-candidates": 11}[args.reading_policy]
    rows = {row["case_id"]: row for row in manifest["cases"]}
    if args.reading_policy == "two-stage-candidates":
        from .source import load_source, source_structure
        ceilings = []
        queue_minimums = []
        for case_id in selected:
            source_text, source_hash = load_source(rows[case_id]["source"])
            if source_hash != rows[case_id]["source_hash"]:
                raise ValueError(f"Source changed since manifest: {case_id}")
            paragraph_count = len(source_structure(source_text, source_hash)[0])
            triage = math.ceil(paragraph_count / 4)
            refinement = math.ceil(paragraph_count / 4)
            ceilings.append(triage + refinement + steps + 3 + 3 +
                            config["max_source_scan_requests"])
            checkpoint_path = args.experiment / args.split / case_id / "checkpoint.json"
            if checkpoint_path.exists():
                saved_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                queue_minimums.append(math.ceil(len(saved_checkpoint.get(
                    "triage_queue", [])) / 4) + math.ceil(len(saved_checkpoint.get(
                    "refinement_queue", [])) / 4) + len(saved_checkpoint.get(
                    "source_scan_queue", [])))
        ceiling = sum(ceilings)
        print(f"Projected ceiling: {ceiling} case requests from actual paragraph counts, "
              f"including up to {config['max_source_scan_requests']} source-scan "
              f"batches/case, plus {probes} capability probes. Reserve exposure at "
              f"{config['reserve']:.2f} USD/request: "
              f"{(ceiling + probes) * config['reserve']:.2f} USD worst-case internal "
              "reserve, not measured Modal charges.")
        if queue_minimums:
            print("Currently queued minimum requests before later navigation/phases: "
                  f"{sum(queue_minimums)}.")
    elif args.reading_policy in {"candidate", "candidate-separated", "audited-candidates"}:
        per_case = (2 * (steps + 3) + 3 + config["max_source_scan_requests"]
                    if args.reading_policy in {"candidate-separated", "audited-candidates"} else
                    steps + 6 + config["max_source_scan_requests"])
        ceiling = len(selected) * per_case
        print(f"Projected ceiling: {ceiling} case requests including up to "
              f"{config['max_source_scan_requests']} source-scan batches/case, plus "
              f"{probes} capability probes. Reserve exposure at "
              f"{config['reserve']:.2f} USD/request: "
              f"{(ceiling + probes) * config['reserve']:.2f} USD worst-case "
              "internal reserve, not measured Modal charges. A scan limit "
              "leaves the case incomplete; it does not truncate selections.")
    else:
        primary_requests = len(selected) * (steps + 6)
        print(f"Projected ceiling: {primary_requests} case requests plus {probes} capability probes. "
              f"Reserve exposure at {config['reserve']:.2f} USD/request: "
              f"{(primary_requests + probes) * config['reserve']:.2f} USD worst-case "
              "internal reserve, not measured Modal charges.")
    if not args.execute:
        return
    fingerprint = _fingerprint(manifest_bytes, config, size, steps,
                               args.reading_policy)
    lock_path = args.experiment / "config.json"
    with exclusive_lock(SHARED_LEDGER_LOCK):
        with exclusive_lock(args.experiment / ".run.lock"):
            if (lock_path.exists() and
                    json.loads(lock_path.read_text(encoding="utf-8")) != fingerprint):
                raise ValueError("Experiment configuration changed; use a new experiment directory")
            save(lock_path, fingerprint)
            if args.reading_policy == "two-stage-candidates":
                from .selection_diagnostic_v14 import CASE_ID, source_groups
                calibration_row = rows.get(CASE_ID)
                if calibration_row is None:
                    raise ValueError("Locked V15 opportunity case is absent from manifest")
                locked, _ = source_groups(calibration_row)
                locked_path = args.experiment / "locked_opportunities.json"
                if (locked_path.exists() and json.loads(locked_path.read_text(
                        encoding="utf-8")) != locked):
                    raise ValueError("Locked V15 opportunities changed")
                save(locked_path, locked)
            client = Endpoint(config, SHARED_LEDGER, LEGACY_LEDGER,
                              allow_provider_retry=args.retry_provider_unavailable,
                              allow_confirmed_local_retry=args.retry_confirmed_local_block)
            if args.reading_policy == "two-stage-candidates":
                from .capability_v15 import probe
            elif args.reading_policy == "audited-candidates":
                from .capability_v14 import probe
            elif args.reading_policy == "candidate-separated":
                from .capability_v13 import probe
            elif args.reading_policy == "candidate":
                from .capability_v12 import probe
            elif args.reading_policy == "guided":
                from .capability_v11 import probe
            else:
                from .capability_v10 import probe
            probe(client, config, args.experiment, fingerprint)
            for case_id in selected:
                output = args.experiment / args.split / case_id
                result_path = output / "case.json"
                if result_path.exists():
                    existing = json.loads(result_path.read_text(encoding="utf-8"))
                    if existing.get("execution_status") == "completed":
                        continue
                    if not args.resume:
                        raise ValueError(f"Incomplete case {case_id}; pass --resume after inspection")
                elif output.exists() and not args.resume:
                    raise ValueError(f"Checkpoint exists for {case_id}; pass --resume after inspection")
                output.mkdir(parents=True, exist_ok=True)
                try:
                    result = build_case(rows[case_id], client, config, size, steps,
                                        output, args.reading_policy)
                    print(f"{case_id}: {result['execution_status']} / "
                          f"{result.get('output_status', result.get('semantic_status', 'unknown'))} / "
                          f"quality={result.get('quality_status', 'not_evaluated')}")
                    if result["execution_status"] != "completed":
                        raise SystemExit(2)
                except Exception as exc:
                    save(output / "failure.json", {"type": type(exc).__name__, "message": str(exc)})
                    print(f"{case_id}: stopped ({type(exc).__name__}); see failure.json")
                    raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc))
