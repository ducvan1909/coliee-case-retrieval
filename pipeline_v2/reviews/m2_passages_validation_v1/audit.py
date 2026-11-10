"""Independent raw/token/coverage audit: no passage builder or reader imports."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from tokenizers import Tokenizer


def read(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def audit(root, bundle):
    started = time.perf_counter()
    manifest = read(bundle / "manifest.json")
    profile = manifest["profile"]
    lock = read(root / profile["tokenizer_lock"])
    assert sha((root / profile["tokenizer_lock"]).read_bytes()) == manifest["tokenizer_lock_sha256"]
    for name, expected in lock["files"].items():
        asset = (root / lock["assets_dir"] / name).read_bytes()
        assert expected == {"sha256":sha(asset),"byte_length":len(asset)}
    backend = Tokenizer.from_file(str(root / lock["assets_dir"] / "tokenizer.json"))
    backend.no_truncation()
    backend.no_padding()
    assert backend.num_special_tokens_to_add(False) == 1
    seal = read(bundle / "seal.json")
    assert {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()} == set(seal["files"]) | {"seal.json"}
    for name, expected in seal["files"].items():
        value = (bundle / name).read_bytes()
        assert expected == {"sha256":sha(value),"byte_length":len(value)}
    for name, expected in manifest["implementation"].items():
        assert sha((root / name).read_bytes()) == expected
    assert sha((root / manifest["profile_path"]).read_bytes()) == manifest["profile_sha256"]
    nav_bundle = root / manifest["navigation"]["bundle"]
    for key, name in (("seal_sha256","seal.json"),("manifest_sha256","manifest.json"),("registry_sha256","source_registry.json")):
        assert sha((nav_bundle / name).read_bytes()) == manifest["navigation"][key]
    m1_bundle = root / manifest["m1"]["bundle"]
    registry = read(bundle / "source_registry.json")["sources"]
    nav_registry = read(nav_bundle / "source_registry.json")["sources"]
    assert {r["case_id"] for r in registry} == {r["case_id"] for r in nav_registry}
    counts, errors, all_ids = Counter(), [], set()
    for r in registry:
        case = r["case_id"]
        raw = (root / "data/task1_train_files_2026/cases" / case).read_bytes()
        raw_hash = sha(raw)
        text = raw.decode("utf-8")
        nav = read(nav_bundle / "sources" / (case[:-4]+".json"))
        record = read(bundle / r["passages_ref"])
        try:
            structure = read(m1_bundle / "sources" / (case[:-4]+".json"))
            for u in structure["units"]:
                if u["unit_kind"] in ("heading", "whitespace"):
                    counts["unindexed_"+u["unit_kind"]+"_units"] += 1
                    counts["unindexed_"+u["unit_kind"]+"_bytes"] += u["span_bytes"][1]-u["span_bytes"][0]
            assert record["source_hash"] == nav["source_hash"] == raw_hash
            assert record["case_id"] == case
            parents = {p["unit_id"]: p for p in record["parents"]}
            units = {u["unit_id"]: u for u in nav["navigation"]}
            assert len(parents) == len(record["parents"]) == len(units)
            assert parents.keys() == units.keys()
            pieces = {p["passage_id"]: p for p in record["passages"]}
            assert len(pieces) == len(record["passages"]) == r["passage_count"]
            used = []
            for uid, parent in parents.items():
                unit = units[uid]
                ua, ub = unit["span_bytes"]
                assert parent["span_bytes"] == [ua, ub]
                refs = parent["passage_refs"]
                assert refs
                end, previous_start = ua, -1
                for i, ref in enumerate(refs):
                    p = pieces[ref]
                    assert ref not in all_ids
                    all_ids.add(ref)
                    used.append(ref)
                    a, b = p["span_bytes"]
                    ca, cb = p["span_chars"]
                    assert ua <= a < b <= ub and a <= end and b > end
                    assert a > previous_start
                    assert raw[a:b].decode("utf-8") == p["text"] == text[ca:cb]
                    assert len(text[:ca].encode("utf-8")) == a
                    assert p["text_sha256"] == p["exact_input_sha256"] == sha(raw[a:b])
                    assert p["source_hash"] == raw_hash
                    assert p["parent_unit_ids"] == [uid]
                    assert p["parent_handle"] == unit["handle"]
                    assert p["parent_span_bytes"] == unit["span_bytes"]
                    assert p["reading_expansion"] == unit["reading_expansion"]
                    for key in ("paragraph_role", "language_region", "unit_kind", "observed_marker", "uncertainties", "section_refs", "role_evidence_refs"):
                        assert p[key] == unit[key]
                    n = len(backend.encode(p["text"], add_special_tokens=True).ids)
                    assert n == p["full_input_tokens"] <= profile["max_input_tokens"]
                    overlap = len(backend.encode(raw[a:end].decode("utf-8"), add_special_tokens=False).ids) if i and a < end else 0
                    assert overlap == p["overlap_tokens_with_previous"] <= profile["overlap_tokens"]
                    assert p["split_order"] == i and p["split_count"] == len(refs)
                    assert p["previous_sibling_ref"] == (refs[i-1] if i else None)
                    assert p["next_sibling_ref"] == (refs[i+1] if i+1 < len(refs) else None)
                    counts["passages"] += 1
                    counts["full_input_tokens"] += n
                    counts["overlap_tokens"] += overlap
                    counts["max_full_input_tokens"] = max(counts["max_full_input_tokens"], n)
                    end, previous_start = b, a
                assert end == ub
                if len(backend.encode(raw[ua:ub].decode("utf-8"), add_special_tokens=True).ids) <= profile["max_input_tokens"]:
                    assert len(refs) == 1
                counts["parents"] += 1
                counts["split_parents"] += len(refs) > 1
            assert len(used) == len(set(used)) == len(pieces) and set(used) == set(pieces)
            counts["sources"] += 1
        except (AssertionError, KeyError, ValueError) as exc:
            errors.append({"case_id":case,"error_type":type(exc).__name__,"message":str(exc)})
        if counts["sources"] and counts["sources"] % 1000 == 0:
            print(json.dumps({"progress_sources":counts["sources"]}), flush=True)
    return {"status":"PASS" if not errors else "FAIL","counts":dict(counts),"errors":errors,
            "elapsed_seconds":round(time.perf_counter()-started,6),"bundle":str(bundle),
            "scope":"all_navigation_units_raw_reencoding_coverage_metadata_mapping",
            "limits":["not_semantic_or_retrieval_quality","headings_whitespace_not_standalone_embeddings"],
            "model_requests":0,"inference_tokens":0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    result = audit(root, root / args.bundle)
    output = root / args.output
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
