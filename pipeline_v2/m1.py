"""M1 source store: build, validate and open exact raw evidence."""
import argparse
import json
import sys
import time
from .source import M1Error, SourceReader, build_bundle, validate_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--repo-root", default=".")
    build.add_argument("--m0-bundle", required=True)
    build.add_argument("--output", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--repo-root", default=".")
    validate.add_argument("--bundle", required=True)
    open_cmd = sub.add_parser("open")
    open_cmd.add_argument("--repo-root", default=".")
    open_cmd.add_argument("--bundle", required=True)
    open_cmd.add_argument("--case", required=True)
    open_cmd.add_argument("--unit")
    open_cmd.add_argument("--start", type=int)
    open_cmd.add_argument("--end", type=int)
    open_cmd.add_argument("--before", type=int, default=0)
    open_cmd.add_argument("--after", type=int, default=0)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        if args.command == "build":
            result = build_bundle(args.repo_root, args.m0_bundle, args.output)
        elif args.command == "validate":
            result = validate_bundle(args.repo_root, args.bundle)
        else:
            reader = SourceReader(args.repo_root, args.bundle)
            if args.unit is not None and args.start is None and args.end is None:
                result = reader.open_unit(args.case, args.unit, args.before, args.after)
            elif args.unit is None and args.start is not None and args.end is not None:
                result = reader.open_range(args.case, args.start, args.end)
            else:
                raise M1Error("Choose --unit OR both --start and --end")
        result["local_elapsed_seconds"] = round(time.perf_counter()-started, 6)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except (M1Error, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"valid": False,"error": str(exc),"local_elapsed_seconds": round(time.perf_counter()-started,6)},ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
