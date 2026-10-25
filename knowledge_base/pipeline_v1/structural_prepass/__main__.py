"""CLI for Plan 03 structural pre-pass."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import build_source_blocks

PIPELINE_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build exact KOS-5 SourceBlock maps.")
    parser.add_argument("--source-store", type=Path, default=PIPELINE_DIR / "outputs/source_store_v1")
    parser.add_argument("--source-store-manifest", type=Path, default=PIPELINE_DIR / "outputs/source_store_v1/source_store_manifest.json")
    parser.add_argument("--plan02-report", type=Path, default=PIPELINE_DIR / "reports/plan02_source_validation.latest.json")
    parser.add_argument("--policy", type=Path, default=PIPELINE_DIR / "policies/sourceblock_policy.v1.json")
    parser.add_argument("--output", type=Path, default=PIPELINE_DIR / "outputs/plan03_source_blocks_v1")
    parser.add_argument("--report", type=Path, default=PIPELINE_DIR / "reports/plan03_structural_validation.latest.json")
    parser.add_argument("--audit", type=Path, default=PIPELINE_DIR / "reports/plan03_block_audit.html")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_source_blocks(
        store_root=args.source_store,
        store_manifest_path=args.source_store_manifest,
        plan02_report_path=args.plan02_report,
        policy_path=args.policy,
        output_root=args.output,
        audit_path=args.audit,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.report)
    print(f"PLAN03 {report['status'].upper()} - report: {args.report.resolve()}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
