from __future__ import annotations

import argparse
import re
from pathlib import Path

from knowledge_base.config import settings
from ..au_runtime_config import load_au_runtime_config
from ..au_compact.manifest import write_json
from .core import ROOT, DEFAULT_SOURCE_MANIFEST, DEFAULT_BLOCK_ROOT, load, build_manifest, preflight


def _guard(path, args):
    path = Path(path).resolve()
    for root in (args.source_store, args.atom_root, args.block_root):
        if path.is_relative_to(Path(root).resolve()):
            raise ValueError("output_overlaps_source_dependency")
    if path == Path(args.source_manifest).resolve():
        raise ValueError("output_overwrites_source_manifest")


def _locked_write(path, value):
    path = Path(path)
    if path.exists():
        if load(path) != value:
            raise ValueError("immutable_artifact_conflict_use_new_output")
        return
    write_json(path, value)


def main():
    p = argparse.ArgumentParser(description="Mốc1 full KOS-5 baseline; local unless run --execute")
    p.add_argument("command", choices=["build", "preflight", "run"])
    p.add_argument("--source-manifest", default=str(DEFAULT_SOURCE_MANIFEST))
    p.add_argument("--source-store", default=str(ROOT / "outputs/source_store_v1"))
    p.add_argument("--atom-root", default=str(ROOT / "outputs/plan04_sentence_atoms_v1"))
    p.add_argument("--block-root", default=str(DEFAULT_BLOCK_ROOT))
    p.add_argument("--manifest", default=str(ROOT / "manifests/au_compact_kos5_full_m1.v1.json"))
    p.add_argument("--output", help="Build manifest or preflight report output")
    p.add_argument("--output-root", default=str(ROOT / "outputs/milestone1_kos5"))
    p.add_argument("--preflight", help="Approved PASS report; required for live run")
    p.add_argument("--planned-budget", action="store_true", help="Explicitly use workload-derived reservations instead of old pilot env caps")
    p.add_argument("--max-input-tokens", type=int, default=11488,
        help="Conservative input ceiling, 12288 deployment context minus 800 output")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--retry-provider-unavailable", action="store_true")
    a = p.parse_args()
    try:
        if a.command != "run" and a.execute:
            p.error("Only run accepts --execute")
        if a.max_input_tokens <= 0 or a.max_input_tokens > 11488:
            p.error("input ceiling must be 1..11488")
        if a.command == "build":
            value = build_manifest(source_manifest=a.source_manifest, source_store=a.source_store,
                atom_root=a.atom_root, block_root=a.block_root)
            output = Path(a.output or a.manifest)
            _guard(output, a); _locked_write(output, value)
            print(f"MILESTONE1 BUILD PASS requests={len(value['requests'])} — {output.resolve()}")
            return 0
        value = load(a.manifest)
        if a.command == "preflight":
            budget = None
            if not a.planned_budget:
                _, budget, _ = load_au_runtime_config(settings(), "AU_COMPACT_")
            report = preflight(value, source_store=a.source_store, atom_root=a.atom_root,
                budget=budget, max_input_tokens=a.max_input_tokens)
            output = Path(a.output or Path(a.output_root) / "preflight_ready.json")
            _guard(output, a); _locked_write(output, report)
            print(f"MILESTONE1 PREFLIGHT {report['status'].upper()} requests={report['request_count']} — {output.resolve()}")
            return 0 if report["status"] == "pass" else 3
        if not a.execute or not a.preflight:
            p.error("run requires --execute and --preflight PASS report")
        cfg, _, warm = load_au_runtime_config(settings(), "AU_COMPACT_")
        if not all(isinstance(cfg.get(k), str) and cfg[k] for k in ("url", "token", "model")):
            raise ValueError("runtime_endpoint_credentials_missing")
        from .runtime import run
        _guard(a.output_root, a)
        result = run(value, preflight_report=load(a.preflight), source_store=a.source_store,
            atom_root=a.atom_root, cfg=cfg, output_root=a.output_root, warmup_policy=warm,
            execute=True, retry_provider_unavailable=a.retry_provider_unavailable)
        output = Path(a.output_root) / "run.json"
        write_json(output, result)
        print(f"MILESTONE1 RUN {result['status'].upper()} — {output.resolve()}")
        return 0 if result["status"] == "complete" else 3
    except Exception as exc:
        safe_runner_codes = {
            "compact warmup failed before source dispatch": "warmup_failed_before_source_dispatch",
            "compact schema probe failed before source dispatch": "schema_probe_failed_before_source_dispatch",
        }
        code = safe_runner_codes.get(str(exc))
        if code is None:
            code = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,95}", str(exc)) else type(exc).__name__
        print(f"MILESTONE1 ERROR {code}")
        if code == "warmup_failed_before_source_dispatch":
            print(f"Warmup report: {(Path(a.output_root) / 'warmup/warmup.json').resolve()}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
