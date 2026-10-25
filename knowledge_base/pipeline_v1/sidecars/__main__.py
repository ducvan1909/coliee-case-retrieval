"""CLI for Plan 05 sidecar build."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import build_sidecars

PIPELINE_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic KOS-5 sidecars.")
    parser.add_argument("--source-store", type=Path, default=PIPELINE_DIR / "outputs/source_store_v1")
    parser.add_argument("--plan03-report", type=Path, default=PIPELINE_DIR / "reports/plan03_structural_validation.latest.json")
    parser.add_argument("--plan04-report", type=Path, default=PIPELINE_DIR / "reports/plan04_sentence_atom_validation.latest.json")
    parser.add_argument("--plan04-independent-report", type=Path, default=PIPELINE_DIR / "evaluation/plan04_independent_evaluation.md")
    parser.add_argument("--sourceblock-policy", type=Path, default=PIPELINE_DIR / "policies/sourceblock_policy.v1.json")
    parser.add_argument("--sentence-policy", type=Path, default=PIPELINE_DIR / "policies/sentence_atom_policy.v1.json")
    parser.add_argument("--policy", type=Path, default=PIPELINE_DIR / "policies/sidecar_policy.v1.json")
    parser.add_argument("--output", type=Path, default=PIPELINE_DIR / "outputs/plan05_sidecars_v1")
    parser.add_argument("--report", type=Path, default=PIPELINE_DIR / "reports/plan05_sidecar_validation.latest.json")
    parser.add_argument("--audit", type=Path, default=PIPELINE_DIR / "reports/plan05_sidecar_audit.html")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_sidecars(source_store=args.source_store, plan03_report=args.plan03_report, plan04_report=args.plan04_report, plan04_independent_report=args.plan04_independent_report, sourceblock_policy=args.sourceblock_policy, sentence_policy=args.sentence_policy, policy_path=args.policy, output_root=args.output, audit_path=args.audit)
    args.report.parent.mkdir(parents=True, exist_ok=True); temporary = args.report.with_suffix(args.report.suffix + ".tmp"); temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); temporary.replace(args.report)
    print(f"PLAN05 {report['status'].upper()} - report: {args.report.resolve()}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__": sys.exit(main())
