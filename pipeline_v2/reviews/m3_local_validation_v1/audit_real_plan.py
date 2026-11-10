"""Independent local audit of one M3 plan; does not import M3 builders/readers."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_SEAL = "0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6"
EXPECTED_MODEL_REVISION = "5cf2132abc99cad020ac570b19d031efec650f2b"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def audit(run_relative):
    run = (ROOT / run_relative).resolve()
    require(run.is_relative_to(ROOT / "pipeline_v2/artifacts"), "Run path escaped M3 artifact directory")
    manifest_path = run / "pilot_manifest.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    require(json.loads((run / "manifest.sha256.json").read_bytes()) == {"sha256": sha(manifest_raw)}, "Pilot manifest seal mismatch")

    profile_path = ROOT / "pipeline_v2/configs/m3.json"
    profile = json.loads(profile_path.read_bytes())
    require(manifest["profile"] == profile, "Planned profile differs from current frozen profile")
    require(profile["passages_bundle"] == "pipeline_v2/artifacts/m2_passages_20261106_v1", "Unexpected accepted M2 bundle")
    require(profile["accepted_m2_seal_sha256"] == EXPECTED_SEAL, "Accepted source seal changed")
    require(profile["embedding"]["revision"] == EXPECTED_MODEL_REVISION, "Unexpected model revision")
    require(manifest["embedding_fingerprint"] == sha(json_bytes(profile["embedding"])), "Embedding fingerprint mismatch")

    code_root = ROOT
    current_code = {}
    paths = [code_root / "pipeline_v2/m3.py"]
    paths += sorted((code_root / "pipeline_v2/retrieval").glob("*.py"))
    paths += sorted((code_root / "pipeline_v2/deployments/modal").glob("*.py"))
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        current_code[rel] = sha(path.read_bytes())
    require(manifest["implementation"] == current_code, "Production code hash mismatch")

    bundle = ROOT / profile["passages_bundle"]
    seal_raw = (bundle / "seal.json").read_bytes()
    require(sha(seal_raw) == EXPECTED_SEAL == manifest["m2_seal_sha256"], "Accepted M2 seal mismatch")
    seal = json.loads(seal_raw)
    file_index = seal["files"]
    m2_manifest_raw = (bundle / "manifest.json").read_bytes()
    m2_manifest = json.loads(m2_manifest_raw)
    require(seal["files"].get("manifest.json") == {"sha256": sha(m2_manifest_raw), "byte_length": len(m2_manifest_raw)}, "M2 manifest is not sealed")

    user_selection = json.loads((ROOT / "pipeline_v2/configs/m3_user_selection.json").read_bytes())
    nav_bundle = ROOT / user_selection["navigation_bundle"]
    nav_seal_raw = (nav_bundle / "seal.json").read_bytes()
    require(sha(nav_seal_raw) == m2_manifest["navigation"]["seal_sha256"], "Navigation seal differs from accepted M2 manifest")
    nav_manifest_raw = (nav_bundle / "manifest.json").read_bytes()
    require(sha(nav_manifest_raw) == m2_manifest["navigation"]["manifest_sha256"], "Navigation manifest differs from accepted M2 manifest")
    nav_seal = json.loads(nav_seal_raw)
    nav_files = nav_seal["files"]

    ids = manifest["passage_ids"]
    require(len(ids) == profile["pilot_size"] == 1024, "Pilot manifest size is not 1,024")
    require(len(set(ids)) == len(ids), "Duplicate passage IDs")
    require(manifest["selection"]["seed"] == profile["seed"], "Selection seed differs from profile")
    require(manifest["selection"]["method"] == "hash_priority_plus_risk_v1", "Unexpected selection algorithm marker")
    require(len(manifest["input_hashes"]) == len(ids), "Input hash array length mismatch")

    cases = sorted(manifest["source_hashes"])
    require(set(cases) == {x.split(":", 1)[0] + ".txt" for x in ids}, "Source case map does not match selected passage IDs")
    passage_by_id = {}
    nav_preview_count = {}
    token_counts = []
    split_children = unicode_count = no_preview_count = 0
    source_cases = Counter()
    tokenizer_lock = json.loads((ROOT / "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json").read_bytes())
    tokenizer_dir = ROOT / tokenizer_lock["assets_dir"]
    tokenizer_raw = (tokenizer_dir / "tokenizer.json").read_bytes()
    require(sha(tokenizer_raw) == tokenizer_lock["files"]["tokenizer.json"]["sha256"], "Pinned tokenizer asset hash mismatch")
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(tokenizer_dir / "tokenizer.json"))

    for case_id in cases:
        stem = case_id[:-4]
        rel = f"sources/{stem}.json"
        passage_path = bundle / rel
        raw_record = passage_path.read_bytes()
        expected_record = file_index.get(rel)
        require(expected_record == {"sha256": sha(raw_record), "byte_length": len(raw_record)}, f"M2 passage record not sealed: {case_id}")
        record = json.loads(raw_record)

        nav_path = nav_bundle / rel
        nav_raw = nav_path.read_bytes()
        nav_expected = nav_files.get(rel)
        require(nav_expected == {"sha256": sha(nav_raw), "byte_length": len(nav_raw)}, f"Navigation record not sealed: {case_id}")
        nav_record = json.loads(nav_raw)
        nav_preview_count.update({x["unit_id"]: len(x["preview_refs"]) for x in nav_record["navigation"]})

        raw_source = (ROOT / "data/task1_train_files_2026/cases" / case_id).read_bytes()
        source_hash = sha(raw_source)
        require(record["case_id"] == case_id and record["source_hash"] == source_hash, f"Raw source/M2 record mismatch: {case_id}")
        require(manifest["source_hashes"][case_id] == source_hash, f"Manifest source hash mismatch: {case_id}")
        for passage in record["passages"]:
            passage_by_id[passage["passage_id"]] = passage

    for i, passage_id in enumerate(ids):
        passage = passage_by_id.get(passage_id)
        require(passage is not None, f"Selected ID absent from sealed source records: {passage_id}")
        require(passage["case_id"] == passage_id.split(":", 1)[0] + ".txt", f"Passage case mapping mismatch: {passage_id}")
        raw_source = (ROOT / "data/task1_train_files_2026/cases" / passage["case_id"]).read_bytes()
        a, b = passage["span_bytes"]
        exact = raw_source[a:b]
        require(exact.decode("utf-8") == passage["text"], f"Passage span differs from raw source: {passage_id}")
        require(sha(exact) == passage["exact_input_sha256"] == passage["text_sha256"], f"Passage input hash mismatch: {passage_id}")
        require(manifest["input_hashes"][i] == passage["exact_input_sha256"], f"Manifest input hash/order mismatch: {passage_id}")
        token_ids = tokenizer.encode(passage["text"], add_special_tokens=True).ids
        require(len(token_ids) == passage["full_input_tokens"] <= profile["embedding"]["max_tokens"], f"Pinned token count/cap mismatch: {passage_id}")
        require(token_ids[-1] == 151643, f"Expected official EOS token missing: {passage_id}")
        token_counts.append(len(token_ids))
        split_children += int(passage["split_count"] > 1)
        unicode_count += int(any(ord(c) > 127 for c in passage["text"]))
        preview_count = nav_preview_count.get(passage["parent_unit_ids"][0])
        require(preview_count is not None, f"Missing sealed navigation unit: {passage_id}")
        no_preview_count += int(preview_count == 0)
        source_cases[passage["case_id"]] += 1

    recorded_strata = manifest["selection"]["strata_actual"]
    recomputed_strata = {"split_children": split_children, "unicode": unicode_count, "no_preview": no_preview_count}
    require(recorded_strata == recomputed_strata, f"Recorded/recomputed strata mismatch: {recorded_strata} != {recomputed_strata}")
    require(manifest.get("labels_accessed") is False and manifest.get("test_sources_accessed") is False, "Manifest reports labels/test source access")
    require(manifest.get("model_requests") == 0 and manifest.get("pilot_executed") is False, "Plan unexpectedly records inference/execution")

    return {
        "status": "PASS",
        "audit_method": "independent selected-record/source/hash/tokenizer verification; no M3 builder/reader imports",
        "run_dir": str(run.relative_to(ROOT).as_posix()),
        "manifest_sha256": sha(manifest_raw),
        "m2_seal_sha256": sha(seal_raw),
        "navigation_seal_sha256": sha(nav_seal_raw),
        "implementation_sha256_map_match": True,
        "embedding_fingerprint": manifest["embedding_fingerprint"],
        "selected_passages": len(ids),
        "unique_passage_ids": len(set(ids)),
        "selected_cases": len(cases),
        "raw_source_hashes_verified": len(cases),
        "selected_m2_record_files_verified": len(cases),
        "selected_navigation_record_files_verified": len(cases),
        "input_hashes_and_order_verified": len(ids),
        "pinned_tokenizer_ids_verified": len(ids),
        "token_count_stats": {"min": min(token_counts), "max": max(token_counts), "mean": statistics.mean(token_counts),
                              "median": statistics.median(token_counts),
                              "bins_64": dict(sorted(Counter(str((n // 64) * 64) for n in token_counts).items()))},
        "recomputed_strata": recomputed_strata,
        "case_passage_count_stats": {"min": min(source_cases.values()), "max": max(source_cases.values()),
                                     "mean": statistics.mean(source_cases.values())},
        "labels_accessed": False,
        "test_sources_accessed": False,
        "model_requests": 0,
        "pilot_executed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default="pipeline_v2/artifacts/m3_pilot_20261106_v1")
    args = parser.parse_args()
    result = audit(args.run_dir)
    out = ROOT / "pipeline_v2/reviews/m3_local_validation_v1/real_m2_plan_audit.json"
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
