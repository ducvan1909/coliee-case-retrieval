"""Local-only comparison CLI."""
import argparse
import json

from .comparison import ComparisonError, DEFAULT_ATOM_ROOT, compare


def main():
    parser = argparse.ArgumentParser(description="Compare normalized AU output against KOS reference only")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("compare")
    for flag in ("run", "source-store", "kos-root", "kos-manifest", "output-root"):
        command.add_argument("--" + flag, required=True)
    command.add_argument("--workload-manifest")
    command.add_argument("--atom-root", default=str(DEFAULT_ATOM_ROOT))
    args = parser.parse_args()
    try:
        report = compare(args.run, source_store=args.source_store, kos_root=args.kos_root,
                         kos_manifest=args.kos_manifest, output_root=args.output_root,
                         workload_manifest=args.workload_manifest, atom_root=args.atom_root)
    except (ComparisonError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, "comparison failed: " + str(exc) + "\n")
    print(json.dumps({"status": report["status"], "counts": report["counts"], "expected_workload_complete": report["coverage"]["expected_workload_complete"], "output_root": args.output_root}, ensure_ascii=False))


if __name__ == "__main__":
    main()
