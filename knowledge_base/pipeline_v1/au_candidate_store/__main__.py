"""Build offline Plan 11 candidates.json and audit.json from compact run reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import build_store
from .reviews import build_review_template


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="validate source evidence and optional agent review sidecars")
    build.add_argument("--run", action="append", required=True, help="compact run JSON path; repeatable")
    build.add_argument("--review", action="append", help="strict review sidecar JSON path; repeatable")
    build.add_argument("--source-store", required=True)
    build.add_argument("--atom-root", required=True)
    build.add_argument("--output-root", required=True)
    template = commands.add_parser("template", help="emit pending strict review and verified atom quote choices")
    template.add_argument("--run", action="append", required=True)
    template.add_argument("--source-store", required=True)
    template.add_argument("--atom-root", required=True)
    template.add_argument("--output-root", required=True)
    template.set_defaults(review=None)
    args = parser.parse_args(argv)
    output = Path(args.output_root).resolve()
    try:
        for protected in (args.source_store, args.atom_root):
            if output.is_relative_to(Path(protected).resolve()):
                raise ValueError("output root must be outside source/atom stores")
        if args.command == "template":
            payload = build_review_template(args.run, args.source_store, args.atom_root)
            template_paths = [output / "review.pending.json", output / "review.quote_choices.json"]
            if any(path.exists() for path in template_paths):
                raise ValueError("refusing to overwrite existing review template/choices")
            if any(path.resolve() in {Path(run).resolve() for run in args.run} for path in template_paths):
                raise ValueError("output would overwrite an input run")
            output.mkdir(parents=True, exist_ok=True)
            for path, value in zip(template_paths, (payload["review"], payload["quote_choices"])):
                path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            print("AU-CANDIDATE-REVIEW TEMPLATE: pending=" + str(template_paths[0]))
            return 0
        destinations = [output / "candidates.json", output / "audit.json"]
        if any(path.resolve() in {Path(run).resolve() for run in args.run + (args.review or [])} for path in destinations):
            raise ValueError("output would overwrite an input run/review")
        for path, kind in zip(destinations, ("AUCandidateStore", "AUCandidateStoreAudit")):
            if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("artifact_type") != kind:
                raise ValueError("refusing to overwrite unrelated artifact: " + str(path))
        store = build_store(args.run, args.source_store, args.atom_root, reviews=args.review)
        output.mkdir(parents=True, exist_ok=True)
        candidate_payload = {key: value for key, value in store.items() if key != "audit"}
        for path, payload in zip(destinations, (candidate_payload, store["audit"])):
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "AU-CANDIDATE-STORE ERROR: " + str(exc) + "\n")
    audit = store["audit"]
    print("AU-CANDIDATE-STORE: " + " ".join(f"{key}={audit[key]}" for key in
          ("candidate_count", "rejected_count", "unresolved_count", "superseded_count", "accepted_count")) +
          f" semantic={audit['semantic_status']} audit={destinations[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
