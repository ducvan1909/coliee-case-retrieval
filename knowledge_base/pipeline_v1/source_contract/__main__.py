"""CLI for building the immutable Pipeline V1 source store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .store import build_source_store

PIPELINE_DIR = Path(__file__).resolve().parents[1]


def _write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build immutable KOS-5 raw source store.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PIPELINE_DIR / "manifests/calibration_manifest.v1.json",
    )
    parser.add_argument(
        "--plan01-report",
        type=Path,
        default=PIPELINE_DIR / "reports/plan01_validation.latest.json",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=PIPELINE_DIR / "outputs/source_store_v1",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PIPELINE_DIR / "reports/plan02_source_validation.latest.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_source_store(
        repo_root=args.repo_root,
        manifest_path=args.manifest,
        plan01_report_path=args.plan01_report,
        store_root=args.store,
    )
    _write_report(args.report, report)
    print(f"PLAN02 {report['status'].upper()} - report: {args.report.resolve()}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

