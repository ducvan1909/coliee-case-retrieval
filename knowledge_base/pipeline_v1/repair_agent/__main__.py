from __future__ import annotations

import argparse
from pathlib import Path

from .core import atomic, build_tasks, load, safe_error, guard_output
from .runtime import MockAdapter, preflight, run_arm


def main():
    parser = argparse.ArgumentParser(description="Plan12 bounded repair; offline by default")
    parser.add_argument("command", choices=["build", "preflight", "offline-run", "run", "decoder-probe", "formal-suite-probe", "formal-suite-aggregate"])
    parser.add_argument("--run")
    parser.add_argument("--review")
    parser.add_argument("--source-store")
    parser.add_argument("--atom-root")
    parser.add_argument("--manifest")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--arm", choices=["R0", "R1", "R2", "all"])
    parser.add_argument("--script", help="JSON task_id -> list of mock turn outcomes")
    parser.add_argument("--task-id", action="append", help="Explicit subset of verified frozen tasks; repeat to select more")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--case-id", action="append", help="FORMAL challenge ID; repeat to select more")
    parser.add_argument("--max-requests", type=int, default=8, help="FORMAL remote cap, at most 8")
    parser.add_argument("--report", action="append", help="FORMAL batch report path; repeat to aggregate")
    args = parser.parse_args()
    root = Path(args.output_root)
    try:
        if args.command == "formal-suite-aggregate":
            from .formal_probe import aggregate_reports
            if not args.report or args.execute:
                parser.error("formal-suite-aggregate requires --report; no --execute")
            report = aggregate_reports([load(path) for path in args.report])
            atomic(root / "formal-suite-aggregate.json", report, immutable=True)
            print("REPAIR FORMAL AGGREGATE " + report["status"].upper() + " - " + str(root / "formal-suite-aggregate.json"))
            return 0 if report["status"] == "complete" else 3
        if args.command == "formal-suite-probe":
            from .formal_probe import run_formal_probe
            cfg = None
            if args.execute:
                from knowledge_base.config import settings
                from ..au_runtime_config import load_au_runtime_config
                cfg, _, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
                if not cfg.get("jobs_url"):
                    url = cfg.get("url", "")
                    if not url.endswith("/v1/chat/completions"):
                        parser.error("jobs URL required")
                    cfg["jobs_url"] = url[:-len("/chat/completions")] + "/jobs"
            report = run_formal_probe(root, cfg, args.case_id, args.max_requests)
            print("REPAIR FORMAL SUITE " + report["status"].upper() + " host=" + report["host_check_status"] + " selection=" + report["selection_check_status"] + " - " + str(root / "formal-suite-probe.json"))
            return 0 if report["status"] in {"prepared", "complete"} and report["host_check_status"] == "pass" and report["selection_check_status"] == "pass" else 3
        if args.command == "decoder-probe":
            from .probe import run_probe
            cfg = None
            if args.execute:
                from knowledge_base.config import settings
                from ..au_runtime_config import load_au_runtime_config
                cfg, _, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
                if not cfg.get("jobs_url"):
                    url = cfg.get("url", "")
                    if not url.endswith("/v1/chat/completions"):
                        parser.error("jobs URL required")
                    cfg["jobs_url"] = url[:-len("/chat/completions")] + "/jobs"
            report = run_probe(root, cfg)
            print("REPAIR DECODER PROBE " + report["status"].upper() + " - " + str(root / "decoder-probe.json"))
            return 0 if report["status"] in {"prepared", "complete"} else 3
        if args.command == "build":
            if not all((args.run, args.review, args.source_store, args.atom_root)):
                parser.error("build requires --run --review --source-store --atom-root")
            manifest = build_tasks(args.run, args.review, args.source_store, args.atom_root, root)
            print(f"REPAIR BUILD COMPLETE tasks={manifest['task_count']} - {root / 'manifest.json'}")
            return 0
        if not args.manifest or not args.arm:
            parser.error("command requires --manifest and --arm")
        manifest = load(args.manifest)
        guard_output(root, manifest.get("source_store"), manifest.get("atom_root"))
        if args.command == "preflight":
            if args.arm == "all":
                parser.error("preflight requires one arm; caps apply to each CLI arm run")
            report = preflight(manifest, args.arm, args.task_id)
            atomic(root / ("preflight-" + args.arm + ".json"), report)
            print(f"REPAIR PREFLIGHT {report['status'].upper()} - {root}")
            return 0 if report["status"] == "pass" else 3
        if args.command == "run":
            if not args.execute or args.arm not in {"R1", "R2"} or args.script:
                parser.error("live run requires --execute and one R1/R2 arm; no mock script")
            from knowledge_base.config import settings
            from ..au_runtime_config import load_au_runtime_config
            from .adapter import JobsAdapter
            cfg, _, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
            if not cfg.get("jobs_url"):
                url = cfg.get("url", "")
                if not url.endswith("/v1/chat/completions"):
                    parser.error("jobs URL required")
                cfg["jobs_url"] = url[:-len("/chat/completions")] + "/jobs"
            reports = [run_arm(manifest, args.arm, root, JobsAdapter(cfg), args.task_id)]
        else:
            if args.execute:
                parser.error("offline-run cannot --execute")
            arms = ["R0", "R1", "R2"] if args.arm == "all" else [args.arm]
            reports = [run_arm(manifest, arm, root, MockAdapter(load(args.script) if args.script else None), args.task_id) for arm in arms]
        summary = {"artifact_type": "RepairComparison", "reports": [{"arm": r["arm"], "status": r["status"],
            "cost_summary": r["cost_summary"], "output_root": r["output_root"]} for r in reports],
            "semantic_metrics": None, "semantic_status": "independent_review_required",
            "budget_scope": "each arm has its own 8-attempt/20000-token cap",
            "aggregate_attempts": sum(r["cost_summary"]["source_model_attempts"] for r in reports),
            "aggregate_charged_or_reserved_tokens": sum(r["cost_summary"]["charged_or_reserved_tokens"] for r in reports),
            "mock_usage_is_provider_usage": False}
        atomic(root / ("comparison.json" if args.arm == "all" else "summary-" + args.arm + ".json"), summary)
        print("REPAIR " + ", ".join(r["arm"] + "=" + r["status"] for r in reports) + " - " + str(root))
        return 0 if all(r["status"] == "complete" for r in reports) else 3
    except Exception as exc:
        # Summaries intentionally omit arbitrary exception contents / config.
        error = safe_error(exc)
        if error["code"] == "output_root_overlaps_source":
            print("REPAIR ERROR " + error["code"])
        else:
            atomic(root / "error.json", error)
            print("REPAIR ERROR " + error["code"] + " - " + str(root / "error.json"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
