"""Read-only M0 inventory/profile freeze. Standard library; never calls a model.

Builds deterministic, write-once bundles. Validation recomputes the complete bundle
from current corpus/config/history, detecting drift and inconsistent resealing.
History adapters deliberately never emit gold edges into generated manifests.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import time


class M0Error(ValueError):
    """Invalid input, drift or failed milestone invariant."""


CONFIG_PATH = "pipeline_v2/configs/m0.json"
CORPUS_PATH = "data/task1_train_files_2026/cases"
LABELS_PATH = "data/task1_train_files_2026/clean_task1_train_labels_2026.json"
ARTIFACT_NAMES = (
    "inventory.json", "candidate_manifest.json", "exposure_ledger.json",
    "cohort.json", "evaluator_metadata.json", "profiles.json", "readiness.json",
)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_path(root, relative, prefix=None):
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts:
        raise M0Error(f"Unsafe relative path: {relative}")
    resolved = (root / p).resolve()
    boundary = (root / prefix).resolve() if prefix else root
    if not resolved.is_relative_to(boundary):
        raise M0Error(f"Path escapes allowed scope: {relative}")
    return resolved


def read_json(path):
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M0Error(f"Cannot read JSON {path}: {exc}") from exc


def case_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}(?:\.txt)?", value):
        raise M0Error(f"Invalid case ID: {value!r}")
    return value if value.endswith(".txt") else value + ".txt"


def extract_history(data, adapter):
    """Yield (case ID, exposure kind). Adapters are structural, not semantic."""
    rows = []

    def add(values, kind):
        for value in values:
            rows.append((case_id(value), kind))

    if adapter == "rule_study":
        add(data["discovery_queries"], "query_gold_exposed")
        add(data["verification_queries"], "query_gold_exposed")
        add(data.get("sampling_protocol", {}).get("excluded_queries", []), "historical_excluded_query")
    elif adapter == "split_registry":
        add(data["calibration"], "calibration_read")
        for band in data["pilot"]["train"].values():
            add(band["development"], "historical_development")
            add(band["holdout"], "reserved_holdout")
        # The registry's test section is neither emitted nor used for sampling.
    elif adapter == "au_reference":
        for ident, record in data["cases"].items():
            kind = "query_gold_exposed" if record["role"] in ("query", "both") else "candidate_read_not_query_gold"
            add([ident], kind)
        # Some serialized gold edges mention query IDs absent from cases. They
        # are not proof that their full texts were read, but are not fresh gold.
        add([pair["query_id"] for pair in data["query_gold_pairs"]], "serialized_gold_reference")
    elif adapter == "gold_link":
        add(data["discovery_queries"], "query_gold_exposed")
        add(data["file_Registry"], "candidate_read_not_query_gold")
    elif adapter == "source_pilot":
        for context in data["contexts"]:
            add([context["query_id"]], "query_gold_exposed")
            add([context["seed_gold_candidate"]], "candidate_read_not_query_gold")
            add(context.get("competitor_candidates", []), "candidate_read_not_query_gold")
    elif adapter == "gold_passages":
        queries = data["queries"]
        if isinstance(queries, dict):
            add(queries, "query_gold_exposed")
        else:
            add([q["query_id"] if isinstance(q, dict) else q for q in queries], "query_gold_exposed")
        registry = data.get("case_files_registry", {})
        add(registry, "candidate_read_not_query_gold")
    elif adapter == "calibration":
        add([row["case_id"] for row in data["cases"]], "calibration_read")
    elif adapter == "reading_trial":
        add([data["case_id"]], "source_read_diagnostic")
    else:
        raise M0Error(f"Unknown exposure adapter: {adapter}")
    return sorted(set(rows))


def load_config(root):
    path = checked_path(root, CONFIG_PATH, "pipeline_v2")
    config = read_json(path)
    if config.get("schema_version") != "pipeline-v2-m0-config-1":
        raise M0Error("Unsupported M0 config version")
    if config.get("corpus_path") != CORPUS_PATH or config.get("labels_path") != LABELS_PATH:
        raise M0Error("M0 supports only the locked train source paths")
    sampling = config["sampling"]
    if sampling != {"seed": 20261105, "discovery_size": 10, "holdout_size": 10, "exclude_candidate_read": True}:
        raise M0Error("Sampling protocol differs from authorized M0 cohort")
    profiles = config["profiles"]
    if profiles["embedding"]["status"] != "not_ready" or profiles["runtime"]["status"] != "not_ready":
        raise M0Error("M0 has not selected model profiles")
    if any(v is not None for v in profiles["runtime"]["budgets"].values()):
        raise M0Error("Runtime budgets remain pending payload preflight")
    return config, sha(path.read_bytes())


def collect_bundle(root):
    config, config_hash = load_config(root)
    corpus = checked_path(root, CORPUS_PATH)
    if not corpus.is_dir():
        raise M0Error("Missing train corpus")
    sources = []
    hashes = defaultdict(list)
    newline_counts = Counter()
    for path in sorted(corpus.iterdir(), key=lambda p: p.name):
        if not path.is_file() or path.is_symlink() or not re.fullmatch(r"[0-9]{6}\.txt", path.name):
            raise M0Error(f"Unexpected corpus entry: {path.name}")
        raw = path.read_bytes()
        if not raw:
            raise M0Error(f"Empty source: {path.name}")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise M0Error(f"Not strict UTF-8: {path.name}") from exc
        crlf = raw.count(b"\r\n")
        lf = raw.count(b"\n") - crlf
        cr = raw.count(b"\r") - crlf
        style = "mixed" if sum(x > 0 for x in (crlf, lf, cr)) > 1 else "crlf" if crlf else "lf" if lf else "cr" if cr else "none"
        newline_counts[style] += 1
        digest = sha(raw)
        hashes[digest].append(path.name)
        sources.append({"case_id": path.name, "path": f"{CORPUS_PATH}/{path.name}", "sha256": digest,
                        "byte_length": len(raw), "encoding": "utf-8", "has_bom": raw.startswith(b"\xef\xbb\xbf"),
                        "newlines": {"style": style, "crlf": crlf, "bare_lf": lf, "bare_cr": cr}})
    if not sources:
        raise M0Error("Empty train corpus")
    source_ids = [r["case_id"] for r in sources]
    source_set = set(source_ids)
    duplicates = [ids for _, ids in sorted(hashes.items()) if len(ids) > 1]
    inventory = {"schema_version": "pipeline-v2-inventory-1", "split": "train", "sources": sources,
                 "summary": {"source_count": len(sources), "total_bytes": sum(s["byte_length"] for s in sources),
                             "bom_count": sum(s["has_bom"] for s in sources), "newline_styles": dict(newline_counts),
                             "exact_duplicate_groups": duplicates, "semantic_identity_deduplication": "not_verified"}}

    labels_path = checked_path(root, LABELS_PATH)
    labels = read_json(labels_path)
    if not isinstance(labels, dict) or not labels:
        raise M0Error("Train labels must be nonempty object")
    query_ids = sorted(case_id(q) for q in labels)
    if len(set(query_ids)) != len(query_ids):
        raise M0Error("Duplicate normalized query IDs")
    edges = 0
    self_edges = 0
    for query, candidates in labels.items():
        query = case_id(query)
        if query not in source_set or not isinstance(candidates, list):
            raise M0Error(f"Missing query source or invalid labels list: {query}")
        normalized = [case_id(c) for c in candidates]
        if len(set(normalized)) != len(normalized) or any(c not in source_set for c in normalized):
            raise M0Error(f"Duplicate/missing gold candidate: {query}")
        edges += len(normalized)
        self_edges += normalized.count(query)
    # Only IDs/counts and raw file provenance leave this preparation step. No edge list.
    evaluator = {"schema_version": "pipeline-v2-evaluator-metadata-1", "access_scope": "preparation_and_evaluator_only",
                 "labels": {"path": LABELS_PATH, "sha256": sha(labels_path.read_bytes()), "byte_length": labels_path.stat().st_size},
                 "query_ids": query_ids, "counts": {"queries": len(query_ids), "edges": edges, "self_edges": self_edges},
                 "selection_used": "query_key_eligibility_only_not_gold_count_or_retrieval_quality",
                 "test_labels_accessed": False, "holdout_gold_isolation": "not_enforced_by_filesystem"}

    reasons = defaultdict(list)
    artifacts = []
    for spec in config["exposure_artifacts"]:
        relative = spec["path"]
        path = checked_path(root, relative, "knowledge_base/pipeline_v1")
        data = read_json(path)
        try:
            extracted = extract_history(data, spec["adapter"])
        except (KeyError, TypeError) as exc:
            raise M0Error(f"Unexpected history schema {relative}: {exc}") from exc
        artifacts.append({"path": relative, "sha256": sha(path.read_bytes()), "adapter": spec["adapter"],
                          "extracted_records": len(extracted), "kind_counts": dict(Counter(k for _, k in extracted))})
        for ident, kind in extracted:
            reasons[ident].append({"kind": kind, "artifact_path": relative, "scope": "historical_train_exposure_or_reservation"})
    for ident in config["manual_exposures"]:
        reasons[case_id(ident)].append({"kind": "manual_query_exposed", "artifact_path": CONFIG_PATH,
                                       "scope": config["manual_provenance"]})
    ledger = {"schema_version": "pipeline-v2-exposure-ledger-1", "artifacts": artifacts,
              "entries": [{"case_id": ident, "reasons": sorted(rows, key=lambda r: (r["artifact_path"], r["kind"]))} for ident, rows in sorted(reasons.items())],
              "coverage": {"mode": "explicit_scoped_historical_manifests_plus_manual_session_history",
                           "history_complete": False, "test_registry_branch_used": False,
                           "candidate_read_is_query_gold": False,
                           "candidate_only_exclusion": "conservative_query_sampling_only_candidate_universe_unchanged",
                           "unscanned": ["arbitrary_nonmanifest_run_logs", "archived_snapshots", "external_workspaces_and_chat_history_not_listed"],
                           "freshness_claim": "fresh-by-ledger"}}
    excluded = {}
    for query in query_ids:
        if query in reasons:
            excluded[query] = sorted({r["kind"] for r in reasons[query]})
    # Exact identical query text is a verified identity group; never split or
    # sample another copy of an exposed source. Near/semantic identity is unknown.
    for group in duplicates:
        if any(ident in reasons for ident in group):
            for ident in group:
                if ident in query_ids:
                    excluded.setdefault(ident, []).append("exact_duplicate_of_historical_source")
        else:
            query_group = sorted(set(group) & set(query_ids))
            for ident in query_group[1:]:
                excluded.setdefault(ident, []).append("exact_duplicate_query_representative_used")
    eligible = sorted(set(query_ids) - excluded.keys())
    sampling = config["sampling"]
    total = sampling["discovery_size"] + sampling["holdout_size"]
    if len(eligible) < total:
        raise M0Error(f"Only {len(eligible)} eligible queries for {total}-query cohort")
    sampled = random.Random(sampling["seed"]).sample(eligible, total)
    cohort = {"schema_version": "pipeline-v2-cohort-1", "seed": sampling["seed"], "rng": "Python_random.Random.sample_on_sorted_eligible_ids",
              "freshness": "fresh-by-ledger", "eligible_query_ids": eligible,
              "excluded_queries": [{"case_id": ident, "reasons": sorted(set(kinds))} for ident, kinds in sorted(excluded.items())],
              "discovery_queries": sampled[:sampling["discovery_size"]], "holdout_queries": sampled[sampling["discovery_size"]:],
              "selection_uses": ["train_query_keys", "exposure_ledger", "exact_raw_hash_identity"],
              "selection_does_not_use": ["gold_count", "retrieval_quality", "hardness", "test_labels"],
              "semantic_query_identity": "not_verified_no_absolute_blindness_claim",
              "shared_candidate_policy": "allowed_report_dependencies_at_evaluation_do_not_remove_candidates",
              "holdout_policy": "one_frozen_evaluation_no_tuning"}
    candidate = {"schema_version": "pipeline-v2-candidates-1", "split": "train", "candidate_ids": source_ids,
                 "source_manifest_sha256": sha(canonical(inventory)), "per_query_exclude_self": True,
                 "eligibility_rule": "candidate_in_manifest_and_candidate_id_not_equal_active_query_id",
                 "contains_gold_edges": False, "test_sources_included": False}
    profiles = {"schema_version": "pipeline-v2-profiles-1", "config_path": CONFIG_PATH, "config_sha256": config_hash,
                "implementation": {"path": "pipeline_v2/m0.py", "sha256": sha(Path(__file__).read_bytes())},
                "profiles": config["profiles"]}
    readiness = {"schema_version": "pipeline-v2-readiness-1", "m0": "prepared_with_pending_model_profiles",
                 "source_m1": "ready", "dense": "not_ready", "runtime": "not_ready", "chunk_token_preflight": "not_ready",
                 "pending": ["embedding_model_and_tokenizer_selection", "runtime_models_prompts_and_budget_preflight", "semantic_query_identity_not_verified"],
                 "implemented_milestones": ["M0_local_preparation"], "m1_or_later_executed": False,
                 "usage": {"model_requests": 0, "model_retries": 0, "model_tokens": 0, "model_latency_seconds": None,
                           "development_chat_tokens": None, "scope": "M0_script_execution_only_not_development_chat"}}
    return dict(zip(ARTIFACT_NAMES, (inventory, candidate, ledger, cohort, evaluator, profiles, readiness)))


def output_path(root, output):
    path = Path(output).resolve()
    artifact_root = (root / "pipeline_v2" / "artifacts").resolve()
    if not artifact_root.is_relative_to(root) or not path.is_relative_to(artifact_root) or path == artifact_root:
        raise M0Error("M0 bundles must be under pipeline_v2/artifacts")
    return path


def build_bundle(repo_root, output):
    root = Path(repo_root).resolve()
    target = output_path(root, output)
    if target.exists():
        raise M0Error("Write-once output already exists; choose a new directory")
    records = collect_bundle(root)
    target.mkdir(parents=True, exist_ok=False)
    seal = {"schema_version": "pipeline-v2-m0-seal-1", "files": {}}
    for name, value in records.items():
        raw = canonical(value)
        with (target / name).open("xb") as stream:
            stream.write(raw)
        seal["files"][name] = {"sha256": sha(raw), "byte_length": len(raw)}
    with (target / "seal.json").open("xb") as stream:
        stream.write(canonical(seal))
    return {"bundle": str(target), "source_count": records["inventory.json"]["summary"]["source_count"],
            "excluded_queries": len(records["cohort.json"]["excluded_queries"]),
            "eligible_queries": len(records["cohort.json"]["eligible_query_ids"]), "readiness": records["readiness.json"]}


def validate_bundle(repo_root, bundle):
    root = Path(repo_root).resolve()
    target = output_path(root, bundle)
    seal = read_json(target / "seal.json")
    if seal.get("schema_version") != "pipeline-v2-m0-seal-1" or set(seal.get("files", {})) != set(ARTIFACT_NAMES):
        raise M0Error("Invalid seal artifact set")
    if {p.name for p in target.iterdir()} != set(ARTIFACT_NAMES) | {"seal.json"}:
        raise M0Error("Unexpected/missing bundle files")
    for name in ARTIFACT_NAMES:
        path = target / name
        if path.is_symlink():
            raise M0Error(f"Bundle artifact symlink: {name}")
        raw = path.read_bytes()
        if seal["files"][name] != {"sha256": sha(raw), "byte_length": len(raw)}:
            raise M0Error(f"Seal integrity failure: {name}")
    expected = collect_bundle(root)
    for name, record in expected.items():
        if (target / name).read_bytes() != canonical(record):
            raise M0Error(f"Source/config/history/profile/cohort drift: {name}")
    return {"valid": True, "bundle": str(target), "source_count": expected["inventory.json"]["summary"]["source_count"],
            "m0": expected["readiness.json"]["m0"], "source_m1": "ready", "dense": "not_ready", "runtime": "not_ready"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--repo-root", default=".")
    build.add_argument("--output", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--repo-root", default=".")
    validate.add_argument("--bundle", required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        result = build_bundle(args.repo_root, args.output) if args.command == "build" else validate_bundle(args.repo_root, args.bundle)
        result["local_elapsed_seconds"] = round(time.perf_counter() - started, 6)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (M0Error, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc), "local_elapsed_seconds": round(time.perf_counter() - started, 6)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
