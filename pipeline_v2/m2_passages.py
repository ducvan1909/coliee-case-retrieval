"""M2 offline tokenizer passages. Does not build indexes or call inference."""
import argparse
import json
import sys
import time

from .passages import PassageError, PassageReader, build_bundle, validate_bundle
from .navigation import M2Error
from .source import M1Error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    for name in ("build","validate","inspect","open"):
        command = sub.add_parser(name)
        command.add_argument("--repo-root",default=".")
        if name=="build":
            command.add_argument("--navigation-bundle",required=True)
            command.add_argument("--output",required=True)
        else:
            command.add_argument("--bundle",required=True)
        if name in ("inspect","open"):
            command.add_argument("--case",required=True)
        if name=="inspect":
            command.add_argument("--offset",type=int,default=0)
            command.add_argument("--limit",type=int,default=20)
        if name=="open":
            command.add_argument("--passage-id",required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        if args.command=="build":
            result = build_bundle(args.repo_root,args.navigation_bundle,args.output)
        elif args.command=="validate":
            result = validate_bundle(args.repo_root,args.bundle)
        else:
            reader = PassageReader(args.repo_root,args.bundle)
            result = reader.inspect(args.case,args.offset,args.limit) if args.command=="inspect" else reader.open_context(args.case,args.passage_id)
        result["local_elapsed_seconds"] = round(time.perf_counter()-started,6)
        print(json.dumps(result,ensure_ascii=True,sort_keys=True))
        return 0
    except (PassageError,M1Error,M2Error,OSError,KeyError,TypeError,ValueError) as exc:
        print(json.dumps({"valid":False,"error":str(exc),"local_elapsed_seconds":round(time.perf_counter()-started,6)}),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
