"""Prepare a fixed M5 evidence basket and assess it through the M4 harness."""

import argparse
from contextlib import closing
import json
from pathlib import Path
from time import time_ns

from .agent_harness import Budget, HarnessError
from .agent_harness.contracts import encode, fingerprint
from .agent_harness.modal_qwen import (
    APP_NAME, MODAL_FUNCTION_ID, MODEL, MODEL_REVISION, VLLM_VERSION, ModalQwenTransport,
)
from .full_search.source_tools import SourceToolsSession
from .m4 import M3Tools
from .m5 import run_fixed_baseline
from .sparse_bm25.index import SparseSession


ASSESSMENT_BUDGET = Budget(
    max_requests=5, max_actions=5, max_input_tokens=20000, max_payload_tokens=4096,
    max_output_tokens=256, max_total_tokens=21280, max_retries=0,
)


def prepare(root, run_dir, query_id):
    run_dir.mkdir(parents=True, exist_ok=False)
    with closing(SparseSession(root)) as lexical:
        with closing(SourceToolsSession(root, snapshot=lexical)) as sources:
            tools = M3Tools(sources, lexical, query_id, byte_budget=2048, map_limit=5)
            evidence = run_fixed_baseline(tools)
            binding = {
                "evidence": evidence,
                "evidence_fingerprint": fingerprint(evidence),
                "index_binding": lexical.index_binding, "corpus_binding": lexical.binding,
                "tool_settings": {"byte_budget": 2048, "map_limit": 5},
            }
    path = run_dir / "evidence.json"
    with path.open("xb") as handle:
        handle.write(encode(binding) + b"\n")
    print(json.dumps({
        "status": "evidence_prepared", "path": str(path.resolve()), "model_requests": 0,
        "query_id": query_id, "candidates": len(evidence["pairs"]),
        "coverage": evidence["coverage"],
    }, ensure_ascii=False, indent=2))
    return binding


def assess(root, run_dir, tokenizer_dir):
    from .m5_assessment import M5_ASSESSMENT_INSTRUCTIONS, assess_fixed_baseline

    binding = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    evidence = binding["evidence"]
    if fingerprint(evidence) != binding["evidence_fingerprint"]:
        raise HarnessError("Frozen M5 evidence fingerprint differs")
    transport = ModalQwenTransport(tokenizer_dir, instructions=M5_ASSESSMENT_INSTRUCTIONS)
    model_binding = fingerprint([APP_NAME, MODAL_FUNCTION_ID, MODEL, MODEL_REVISION, VLLM_VERSION])
    with closing(SparseSession(root)) as lexical:
        with closing(SourceToolsSession(root, snapshot=lexical)) as sources:
            if lexical.binding != binding["corpus_binding"] or lexical.index_binding != binding["index_binding"]:
                raise HarnessError("M5 source or index snapshot differs from prepared evidence")
            tools = M3Tools(sources, lexical, evidence["query_id"], **binding["tool_settings"])
            if tools.fingerprint != evidence["tools_fingerprint"]:
                raise HarnessError("M5 tool profile differs from prepared evidence")
            result = assess_fixed_baseline(
                evidence, run_dir / "assessment", budget=ASSESSMENT_BUDGET, transport=transport,
                count_tokens=transport.count_tokens, verify_source=tools.verify_source,
                model_fingerprint=model_binding, tokenizer_fingerprint=transport.tokenizer_fingerprint,
                prompt_fingerprint=transport.prompt_fingerprint,
            )
    report = {
        "result": result, "app": APP_NAME, "model": MODEL, "model_revision": MODEL_REVISION,
        "modal_function_id": MODAL_FUNCTION_ID, "modal_receipts": transport.receipts,
    }
    path = run_dir / f"assessment_report_{time_ns()}.json"
    with path.open("xb") as handle:
        handle.write(encode(report) + b"\n")
    print(json.dumps({
        "report_path": str(path.resolve()), "status": result["status"],
        "accepted_assessments": len(result["assessments"]),
        "context_statuses": {
            status: sum(row["status"] == status for row in result["assessment_contexts"])
            for status in sorted({row["status"] for row in result["assessment_contexts"]})
        },
        "usage": result["usage"], "selection_status": result["selection_status"],
    }, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare", help="collect and freeze evidence using local tools")
    prepare_cmd.add_argument("--query-id", default="017984.txt")
    assess_cmd = commands.add_parser("assess", help="assess the saved basket on the configured Modal app")
    assess_cmd.add_argument("--tokenizer-dir", type=Path, required=True)
    for command in (prepare_cmd, assess_cmd):
        command.add_argument("--root", type=Path, default=Path.cwd())
        command.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.root, args.run_dir, args.query_id)
        return 0
    result = assess(args.root, args.run_dir, args.tokenizer_dir)
    return 0 if result["status"] == "assessment_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
