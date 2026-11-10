"""M2 navigation-only stage: build, validate, map, anchors and inspect context."""
import argparse
import json
import sys
import time

from .navigation import M2Error, NavigationReader, build_bundle, validate_bundle
from .source import M1Error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    for name in ("build","validate","map","anchors","source-anchors","open"):
        command = sub.add_parser(name)
        command.add_argument("--repo-root",default=".")
        if name == "build":
            command.add_argument("--m1-bundle",required=True)
            command.add_argument("--output",required=True)
        else:
            command.add_argument("--bundle",required=True)
        if name in ("map","anchors","source-anchors","open"):
            command.add_argument("--case",required=True)
        if name in ("anchors","open"):
            command.add_argument("--handle",required=True)
        if name in ("map","anchors","source-anchors"):
            command.add_argument("--offset",type=int,default=0)
            command.add_argument("--limit",type=int,default=20)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        if args.command == "build":
            result = build_bundle(args.repo_root,args.m1_bundle,args.output)
        elif args.command == "validate":
            result = validate_bundle(args.repo_root,args.bundle)
        else:
            reader = NavigationReader(args.repo_root,args.bundle)
            if args.command == "map":
                result = reader.map(args.case,args.offset,args.limit)
            elif args.command == "anchors":
                result = reader.anchors(args.case,args.handle,args.offset,args.limit)
            elif args.command == "source-anchors":
                result = reader.source_anchors(args.case,args.offset,args.limit)
            else:
                result = reader.open_context(args.case,args.handle)
        result["local_elapsed_seconds"] = round(time.perf_counter()-started,6)
        print(json.dumps(result,ensure_ascii=True,sort_keys=True))
        return 0
    except (M1Error,M2Error,OSError,KeyError,TypeError,ValueError) as exc:
        print(json.dumps({"valid":False,"error":str(exc),"local_elapsed_seconds":round(time.perf_counter()-started,6)},ensure_ascii=True),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
