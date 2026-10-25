"""CLI for Plan 04 SentenceAtom build."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import build_sentence_atoms

PIPELINE_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic KOS-5 SentenceAtom maps.")
    parser.add_argument("--source-store", type=Path, default=PIPELINE_DIR / "outputs/source_store_v1")
    parser.add_argument("--plan03-report", type=Path, default=PIPELINE_DIR / "reports/plan03_structural_validation.latest.json")
    parser.add_argument("--plan03-independent-report", type=Path, default=PIPELINE_DIR / "evaluation/plan03_independent_evaluation.md")
    parser.add_argument("--policy", type=Path, default=PIPELINE_DIR / "policies/sentence_atom_policy.v1.json")
    parser.add_argument("--output", type=Path, default=PIPELINE_DIR / "outputs/plan04_sentence_atoms_v1")
    parser.add_argument("--report", type=Path, default=PIPELINE_DIR / "reports/plan04_sentence_atom_validation.latest.json")
    parser.add_argument("--audit", type=Path, default=PIPELINE_DIR / "reports/plan04_sentence_atom_audit.html")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_sentence_atoms(source_store=args.source_store, plan03_report=args.plan03_report, plan03_independent_report=args.plan03_independent_report, policy_path=args.policy, output_root=args.output, audit_path=args.audit)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.report)
    print(f"PLAN04 {report['status'].upper()} - report: {args.report.resolve()}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
