from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_base.config import settings
from ..au_runtime_config import load_au_runtime_config
from .adversarial_probe import adversarial_schema_probe
from .manifest import build_manifest, preflight, write_json
from .runner import run
from .structured_output_probe import structured_output_probe
from .constraint_matrix_probe import constraint_matrix_probe
from .schema_ablation_probe import schema_ablation_probe
from .constraint_suite_probe import constraint_suite_probe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build", "preflight", "run", "adversarial-schema-probe", "structured-output-probe", "constraint-matrix-probe", "schema-ablation-probe", "constraint-suite-probe"])
    parser.add_argument("--manifest")
    parser.add_argument("--source-store")
    parser.add_argument("--atom-root", default="knowledge_base/pipeline_v1/outputs/plan04_sentence_atoms_v1")
    parser.add_argument("--output")
    parser.add_argument("--output-root", default="knowledge_base/pipeline_v1/outputs/au_compact_v1")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--retry-provider-unavailable", action="store_true")
    parser.add_argument("--request-id", action="append")
    parser.add_argument("--transport", choices=["direct", "jobs"], help="Override AU_TRANSPORT for extraction")
    parser.add_argument("--string-decoder", choices=["bounded", "host_validated"], help="Ablate string length grammar; host schema remains unchanged")
    parser.add_argument("--max-requests", type=int, help="Request cap for constraint-suite-probe; omitted runs the complete catalog")
    parser.add_argument("--decoder", choices=["json_schema", "ebnf"], default="json_schema", help="Constraint-suite diagnostic mode; extraction uses request-bound EBNF")
    args = parser.parse_args()
    if args.command == "constraint-suite-probe":
        if args.max_requests is not None and args.max_requests < 1:
            parser.error("--max-requests must be positive")
        cfg, _, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
        if args.execute and not all(cfg[key] for key in ("url", "token", "model")):
            parser.error("constraint-suite-probe requires AU_URL, AU_TOKEN, and AU_MODEL")
        root = Path(args.output_root)
        report = constraint_suite_probe(cfg, root, execute=args.execute, max_requests=args.max_requests, decoder=args.decoder)
        print(f"AU-COMPACT CONSTRAINT-SUITE-PROBE {report['status'].upper()} — output: {(root / 'constraint_suite_probe.json').resolve()}")
        return 0 if report["status"] in {"pass", "planned"} else 3
    if args.command == "schema-ablation-probe":
        if not args.execute:
            parser.error("schema-ablation-probe requires --execute")
        cfg, _, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
        if not all(cfg[key] for key in ("url", "token", "model")):
            parser.error("schema-ablation-probe requires AU_URL, AU_TOKEN, and AU_MODEL")
        root = Path(args.output_root)
        report = schema_ablation_probe(cfg, root)
        print(f"AU-COMPACT SCHEMA-ABLATION-PROBE {report['diagnosis'].upper()} — output: {(root / 'schema_ablation_probe.json').resolve()}")
        return 0 if any(row["status"] == "supported" for row in report["results"]) else 3
    if args.command == "constraint-matrix-probe":
        if not args.execute:
            parser.error("constraint-matrix-probe requires --execute")
        cfg, _, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
        if not all(cfg[key] for key in ("url", "token", "model")):
            parser.error("constraint-matrix-probe requires AU_URL, AU_TOKEN, and AU_MODEL")
        root = Path(args.output_root)
        report = constraint_matrix_probe(cfg, root)
        print(f"AU-COMPACT CONSTRAINT-MATRIX-PROBE {report['diagnosis'].upper()} — output: {(root / 'constraint_matrix_probe.json').resolve()}")
        return 0 if any(row["status"] == "supported" for row in report["results"]) else 3
    if args.command == "adversarial-schema-probe":
        if not args.execute:
            parser.error("adversarial-schema-probe requires --execute")
        cfg, _, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
        if not all(cfg[key] for key in ("url", "token", "model")):
            parser.error("adversarial-schema-probe requires AU_URL, AU_TOKEN, and AU_MODEL (AU_COMPACT_* fallback is deprecated)")
        root = Path(args.output_root)
        report = adversarial_schema_probe(cfg, root)
        print(f"AU-COMPACT ADVERSARIAL-SCHEMA-PROBE {report['status'].upper()} — output: {(root / 'adversarial_schema_probe.json').resolve()}")
        return 0 if report["status"] == "supported" else 3
    if args.command == "structured-output-probe":
        if not args.execute:
            parser.error("structured-output-probe requires --execute")
        cfg, _, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
        if not all(cfg[key] for key in ("url", "token", "model")):
            parser.error("structured-output-probe requires AU_URL, AU_TOKEN, and AU_MODEL (AU_COMPACT_* fallback is deprecated)")
        root = Path(args.output_root)
        report = structured_output_probe(cfg, root)
        print(f"AU-COMPACT STRUCTURED-OUTPUT-PROBE {report['status'].upper()} — output: {(root / 'structured_output_probe.json').resolve()}")
        return 0 if report["status"] == "supported" else 3
    if args.command == "build":
        if not args.manifest:
            parser.error("build requires --manifest")
        output = Path(args.output or "knowledge_base/pipeline_v1/manifests/au_compact_pilot_r5_model_silver.v1.json")
        value = build_manifest(args.manifest, args.atom_root)
        write_json(output, value)
        print(f"AU-COMPACT BUILD PASS — output: {output.resolve()}")
        return 0
    if not args.manifest or not args.source_store:
        parser.error("preflight/run require --source-store")
    value = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.command == "run":
        if not args.execute:
            parser.error("run requires --execute")
        env = settings(); cfg, budget, policy = load_au_runtime_config(env, "AU_COMPACT_")
        if args.transport:
            cfg["transport"] = args.transport
            if args.transport == "jobs" and not cfg.get("jobs_url"):
                if not cfg["url"].endswith("/v1/chat/completions"):
                    parser.error("jobs requires AU_JOBS_URL or AU_URL ending /v1/chat/completions")
                cfg["jobs_url"] = cfg["url"][:-len("/chat/completions")] + "/jobs"
        if args.string_decoder:
            cfg["string_decoder"] = args.string_decoder
        if not all(cfg[key] for key in ("url", "token", "model")):
            parser.error("run requires AU_URL, AU_TOKEN, and AU_MODEL (AU_COMPACT_* fallback is deprecated)")
        root = Path(args.output_root); report = run(value, source_store=args.source_store, atom_root=args.atom_root, cfg=cfg, budget=budget, cache_dir=root / "cache", execute=True, warmup_policy=policy, retry_provider_unavailable=args.retry_provider_unavailable, request_ids=args.request_id); output = root / "run.json"; write_json(output, report); print(f"AU-COMPACT RUN {report['status'].upper()} — output: {output.resolve()}"); return 0 if report["status"] == "complete" else 3
    report = preflight(value, args.source_store, args.atom_root)
    output = Path(args.output or Path(args.manifest).with_name("preflight.json"))
    write_json(output, report)
    print(f"AU-COMPACT PREFLIGHT {report['status'].upper()} — output: {output.resolve()}")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
