"""Independent full-corpus raw/token/provenance/mapping audit for M2 passages.

Does NOT import pipeline_v2.passages builder or reader. Reads raw bytes, M0/M1/M2
JSON artifacts, and the pinned Qwen3-Embedding-4B tokenizers backend directly.
"""
from bisect import bisect_left
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[4]


def read_json(path: Path):
    return json.loads(path.read_bytes())


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class IndependentUtf8Map:
    def __init__(self, raw: bytes):
        self.text = raw.decode("utf-8", errors="strict")
        self.byte_length = len(raw)
        self._positions = []
        self._extras = [0]
        for idx, ch in enumerate(self.text):
            w = len(ch.encode("utf-8"))
            if w != 1:
                self._positions.append(idx)
                self._extras.append(self._extras[-1] + w - 1)

    def char_to_byte(self, index: int) -> int:
        assert 0 <= index <= len(self.text)
        return index + self._extras[bisect_left(self._positions, index)]

    def byte_to_char(self, offset: int) -> int:
        assert 0 <= offset <= self.byte_length
        lo, hi = 0, len(self.text)
        while lo <= hi:
            mid = (lo + hi) // 2
            val = self.char_to_byte(mid)
            if val == offset:
                return mid
            if val < offset:
                lo = mid + 1
            else:
                hi = mid - 1
        raise ValueError(f"Byte offset {offset} is inside a UTF-8 codepoint")


def run_independent_audit():
    started = time.perf_counter()
    bundle_dir = ROOT / "pipeline_v2/artifacts/m2_passages_20261106_v1"
    nav_dir = ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v3"
    m1_dir = ROOT / "pipeline_v2/artifacts/m1_20261105_v2"
    m0_dir = ROOT / "pipeline_v2/artifacts/m0_20261105_v2"
    raw_dir = ROOT / "data/task1_train_files_2026/cases"

    # 1. Verify seal and file universe
    seal = read_json(bundle_dir / "seal.json")
    assert seal["schema_version"] == "pipeline-v2-m2-passages-seal-1"
    actual_files = {p.relative_to(bundle_dir).as_posix() for p in bundle_dir.rglob("*") if p.is_file()}
    assert actual_files == set(seal["files"].keys()) | {"seal.json"}
    assert len(seal["files"]) == 7711
    for rel_name, expected_meta in seal["files"].items():
        b = (bundle_dir / rel_name).read_bytes()
        assert expected_meta == {"sha256": sha256_hex(b), "byte_length": len(b)}, f"Seal mismatch on {rel_name}"

    # 2. Verify manifest, profile, implementation, upstream hashes, and tokenizer lock
    manifest = read_json(bundle_dir / "manifest.json")
    summary = read_json(bundle_dir / "summary.json")
    profile_path = ROOT / manifest["profile_path"]
    assert sha256_hex(profile_path.read_bytes()) == manifest["profile_sha256"]
    profile = read_json(profile_path)
    assert profile == manifest["profile"]
    assert profile["target_tokens"] == 320
    assert profile["overlap_tokens"] == 128
    assert profile["max_input_tokens"] == 448
    assert profile["variant"] == "within_parent_overlap_128_not_nonoverlap_baseline"
    assert profile["document_template"] == "{body}"
    assert profile["add_special_tokens"] is True
    assert profile["truncation"] is False
    assert profile["merge_parents"] is False
    assert profile["semantic_inference"] is False
    policy_hash = sha256_hex(canonical_bytes(profile))

    for impl_rel, expected_sha in manifest["implementation"].items():
        assert sha256_hex((ROOT / impl_rel).read_bytes()) == expected_sha, f"Code drift on {impl_rel}"

    for key, fname in (("seal_sha256", "seal.json"), ("manifest_sha256", "manifest.json"), ("registry_sha256", "source_registry.json")):
        assert sha256_hex((nav_dir / fname).read_bytes()) == manifest["navigation"][key]
        assert sha256_hex((m1_dir / fname).read_bytes()) == manifest["m1"][key]
    assert sha256_hex((m0_dir / "candidate_manifest.json").read_bytes()) == manifest["m0"]["candidate_manifest_sha256"]
    assert sha256_hex((m0_dir / "inventory.json").read_bytes()) == manifest["m0"]["inventory_sha256"]

    lock_path = ROOT / profile["tokenizer_lock"]
    lock_sha = sha256_hex(lock_path.read_bytes())
    assert lock_sha == manifest["tokenizer_lock_sha256"]
    lock = read_json(lock_path)
    assert lock["model_id"] == "Qwen/Qwen3-Embedding-4B"
    assert lock["revision"] == "5cf2132abc99cad020ac570b19d031efec650f2b"
    tok_ver = importlib.metadata.version("tokenizers")
    assert tok_ver == "0.22.2" == lock["package_versions"]["tokenizers"]
    assets_dir = ROOT / lock["assets_dir"]
    for asset_name, expected_meta in lock["files"].items():
        asset_bytes = (assets_dir / asset_name).read_bytes()
        assert expected_meta == {"sha256": sha256_hex(asset_bytes), "byte_length": len(asset_bytes)}

    tok_json = read_json(assets_dir / "tokenizer.json")
    assert tok_json["post_processor"] == lock["backend_post_processor"]
    tok_cfg = read_json(assets_dir / "tokenizer_config.json")
    assert not tok_cfg.get("add_bos_token", False) and not tok_cfg.get("add_eos_token", False)

    expected_tok_fp = sha256_hex(canonical_bytes({
        "lock_sha256": lock_sha,
        "tokenizers": tok_ver,
        "add_special_tokens": True,
        "truncation": False,
        "document_template": "{body}",
    }))
    assert expected_tok_fp == manifest["tokenizer_fingerprint"]

    backend = Tokenizer.from_file(str(assets_dir / "tokenizer.json"))
    backend.no_truncation()
    backend.no_padding()
    assert backend.num_special_tokens_to_add(False) == 1

    # 3. Verify universe across raw, M0, M1, M2-nav, M2-passages
    registry = read_json(bundle_dir / "source_registry.json")["sources"]
    nav_registry = read_json(nav_dir / "source_registry.json")["sources"]
    m1_registry = read_json(m1_dir / "source_registry.json")["sources"]
    m0_inventory = read_json(m0_dir / "inventory.json")["sources"]
    raw_cases = sorted(p.name for p in raw_dir.glob("*.txt"))
    assert len(registry) == 7708
    assert [r["case_id"] for r in registry] == [r["case_id"] for r in nav_registry] == [r["case_id"] for r in m1_registry] == [r["case_id"] for r in m0_inventory] == raw_cases

    counts = Counter()
    errors = []
    all_passage_ids = set()
    token_bins = Counter()
    overlap_values = []
    full_token_values = []
    passages_at_448 = []

    for idx, reg_row in enumerate(registry, 1):
        case_id = reg_row["case_id"]
        raw = (raw_dir / case_id).read_bytes()
        raw_sha = sha256_hex(raw)
        utf8_map = IndependentUtf8Map(raw)
        text = utf8_map.text

        m1_rec = read_json(m1_dir / "sources" / f"{case_id[:-4]}.json")
        nav_rec = read_json(nav_dir / "sources" / f"{case_id[:-4]}.json")
        pas_rec = read_json(bundle_dir / reg_row["passages_ref"])

        try:
            assert reg_row == {
                "case_id": case_id,
                "source_hash": raw_sha,
                "passages_ref": f"sources/{case_id[:-4]}.json",
                "passages_sha256": sha256_hex(canonical_bytes(pas_rec)),
                "passage_count": len(pas_rec["passages"]),
                "parent_count": len(pas_rec["parents"]),
            }
            assert pas_rec["schema_version"] == "pipeline-v2-m2-passages-case-1"
            assert pas_rec["case_id"] == case_id
            assert pas_rec["source_hash"] == nav_rec["source_hash"] == m1_rec["raw_sha256"] == raw_sha
            assert pas_rec["policy_hash"] == policy_hash
            assert pas_rec["tokenizer_fingerprint"] == expected_tok_fp
            assert pas_rec["navigation_sha256"] == sha256_hex(canonical_bytes(nav_rec))
            assert pas_rec["scope"] == "all_navigation_units_no_role_or_language_filter"
            assert pas_rec["excluded_structural_views"] == "heading_and_whitespace_remain_source_addressable_not_standalone_embeddings"

            counts["total_raw_bytes"] += len(raw)
            case_unindexed_bytes = 0
            for u in m1_rec["units"]:
                uk = u["unit_kind"]
                ulen = u["span_bytes"][1] - u["span_bytes"][0]
                if uk in ("heading", "whitespace"):
                    counts[f"unindexed_{uk}_units"] += 1
                    counts[f"unindexed_{uk}_bytes"] += ulen
                    case_unindexed_bytes += ulen

            nav_units = nav_rec["navigation"]
            parents = pas_rec["parents"]
            assert len(parents) == len(nav_units)
            assert [p["unit_id"] for p in parents] == [u["unit_id"] for u in nav_units]
            assert [p["handle"] for p in parents] == [u["handle"] for u in nav_units]

            passages_by_id = {p["passage_id"]: p for p in pas_rec["passages"]}
            assert len(passages_by_id) == len(pas_rec["passages"])

            case_parent_bytes = 0
            ordered_refs = []
            for parent, unit in zip(parents, nav_units):
                uid = unit["unit_id"]
                ua, ub = unit["span_bytes"]
                uca, ucb = utf8_map.byte_to_char(ua), utf8_map.byte_to_char(ub)
                assert parent["span_bytes"] == [ua, ub]
                case_parent_bytes += (ub - ua)
                refs = parent["passage_refs"]
                assert len(refs) >= 1

                if not unit["preview_refs"]:
                    counts["parents_without_preview_covered"] += 1
                if str(unit["language_region"]).startswith("fr:"):
                    counts["french_parents_covered"] += 1

                # Check whole-parent token count only when len(refs) == 1 or to verify split threshold
                if len(refs) == 1:
                    single_p = passages_by_id[refs[0]]
                    parent_full_tokens = single_p["full_input_tokens"]
                    assert parent_full_tokens <= 448
                    if parent_full_tokens > 320:
                        counts["intact_parents_gt_320_le_448"] += 1
                    counts["unsplit_parent_full_tokens"] += parent_full_tokens
                    counts["unsplit_parent_content_tokens"] += (parent_full_tokens - 1)
                else:
                    parent_enc = backend.encode(text[uca:ucb], add_special_tokens=True)
                    assert parent_enc.ids[-1] == 151643
                    parent_full_tokens = len(parent_enc.ids)
                    assert parent_full_tokens > 448, f"Split parent <= 448 tokens in {case_id} {unit['handle']}"
                    counts["split_parents"] += 1
                    counts["unsplit_parent_full_tokens"] += parent_full_tokens
                    counts["unsplit_parent_content_tokens"] += (parent_full_tokens - 1)

                prev_end = ua
                prev_start = -1
                for i, ref in enumerate(refs):
                    assert ref not in all_passage_ids, f"Duplicate passage_id {ref}"
                    all_passage_ids.add(ref)
                    ordered_refs.append(ref)
                    p = passages_by_id[ref]
                    assert p["passage_id"] == p["chunk_id"] == ref
                    assert p["case_id"] == case_id
                    assert p["source_hash"] == raw_sha
                    assert p["parent_unit_ids"] == [uid]
                    assert p["parent_handle"] == unit["handle"]
                    assert p["parent_span_bytes"] == [ua, ub]

                    a, b = p["span_bytes"]
                    ca, cb = p["span_chars"]
                    if i == 0:
                        assert a == ua, f"First child does not start at parent start in {ref}"
                    if i == len(refs) - 1:
                        assert b == ub, f"Last child does not end at parent end in {ref}"
                    assert ua <= a < b <= ub
                    assert a <= prev_end, f"Gap between children in {ref}"
                    assert b > prev_end, f"Non-advancing child end in {ref}"
                    assert a > prev_start, f"Non-advancing child start in {ref}"

                    assert utf8_map.byte_to_char(a) == ca
                    assert utf8_map.byte_to_char(b) == cb
                    assert utf8_map.char_to_byte(ca) == a
                    assert utf8_map.char_to_byte(cb) == b

                    rel_start, rel_end = ca - uca, cb - uca
                    expected_id = f"{case_id[:-4]}:{sha256_hex(canonical_bytes([uid, policy_hash, expected_tok_fp, rel_start, rel_end]))[:24]}"
                    assert ref == expected_id, f"Deterministic ID mismatch on {ref} vs {expected_id}"

                    raw_slice = raw[a:b]
                    assert raw_slice.decode("utf-8") == p["text"] == text[ca:cb]
                    slice_sha = sha256_hex(raw_slice)
                    assert p["text_sha256"] == p["exact_input_sha256"] == slice_sha

                    enc_full = backend.encode(p["text"], add_special_tokens=True)
                    enc_content = backend.encode(p["text"], add_special_tokens=False)
                    assert enc_full.ids[-1] == 151643
                    assert len(enc_full.ids) == len(enc_content.ids) + 1
                    n_tok = len(enc_full.ids)
                    assert p["full_input_tokens"] == n_tok <= 448

                    if i > 0 and a < prev_end:
                        ov_text = raw[a:prev_end].decode("utf-8")
                        ov_tok = len(backend.encode(ov_text, add_special_tokens=False).ids)
                        assert ov_tok > 0
                    else:
                        ov_tok = 0
                    assert p["overlap_tokens_with_previous"] == ov_tok <= 128
                    if i > 0:
                        overlap_values.append(ov_tok)
                        if ov_tok == 128:
                            counts["overlap_children_eq_128"] += 1
                        else:
                            counts["overlap_children_lt_128"] += 1

                    assert p["split_order"] == i
                    assert p["split_count"] == len(refs)
                    assert p["previous_sibling_ref"] == (refs[i - 1] if i > 0 else None)
                    assert p["next_sibling_ref"] == (refs[i + 1] if i + 1 < len(refs) else None)

                    expected_bm = "whole_parent" if len(refs) == 1 else "whitespace_or_codepoint_fallback_not_sentence_verified"
                    assert p["boundary_method"] == expected_bm
                    expected_wb = (cb < ucb) and (not text[cb - 1].isspace()) and (not text[cb].isspace())
                    assert p["word_boundary_split"] is expected_wb

                    for mkey in ("section_refs", "paragraph_role", "observed_marker", "unit_kind", "language_region", "uncertainties", "role_evidence_refs", "reading_expansion"):
                        assert p[mkey] == unit[mkey], f"Metadata mismatch on {mkey} in {ref}"

                    assert p["policy_hash"] == policy_hash
                    assert p["tokenizer_fingerprint"] == expected_tok_fp
                    assert p["embedding_view"] == {
                        "template": "{body}",
                        "prefix": "",
                        "add_special_tokens": True,
                        "truncation": False,
                        "runtime_compatibility": "pending_endpoint_preflight",
                    }

                    counts["passages"] += 1
                    counts["full_input_tokens"] += n_tok
                    counts["passage_content_tokens"] += len(enc_content.ids)
                    counts["passage_special_tokens"] += 1
                    counts["overlap_tokens"] += ov_tok
                    counts["max_full_input_tokens"] = max(counts["max_full_input_tokens"], n_tok)
                    counts["word_boundary_splits"] += int(expected_wb)
                    counts[f"role_{p['paragraph_role']}"] += 1
                    counts[f"kind_{p['unit_kind']}"] += 1
                    if str(p["language_region"]).startswith("fr:"):
                        counts["french_passages"] += 1
                    token_bins[f"token_bin_{(n_tok // 64) * 64}"] += 1
                    full_token_values.append(n_tok)
                    if n_tok == 448:
                        passages_at_448.append({"case_id": case_id, "passage_id": ref, "parent_handle": unit["handle"], "split_order": i, "split_count": len(refs)})

                    prev_end = b
                    prev_start = a

                counts["parents"] += 1
                counts["indexed_parent_bytes"] += (ub - ua)

            assert ordered_refs == [p["passage_id"] for p in pas_rec["passages"]]
            assert case_parent_bytes + case_unindexed_bytes == len(raw)
            counts["sources"] += 1
        except Exception as exc:
            errors.append({"case_id": case_id, "error_type": type(exc).__name__, "message": str(exc)})

        if idx % 1000 == 0:
            print(json.dumps({"progress_cases": idx, "elapsed_seconds": round(time.perf_counter() - started, 2)}), flush=True)

    full_token_values.sort()
    overlap_values.sort()

    def pct(arr, q):
        if not arr:
            return 0
        pos = min(len(arr) - 1, int(round((len(arr) - 1) * q)))
        return arr[pos]

    summary_counts_expected = {
        "sources": counts["sources"],
        "parent_units": counts["parents"],
        "passages": counts["passages"],
        "split_parents": counts["split_parents"],
        "full_input_tokens": counts["full_input_tokens"],
        "max_full_input_tokens": counts["max_full_input_tokens"],
        "overlap_tokens": counts["overlap_tokens"],
        "word_boundary_splits": counts["word_boundary_splits"],
        "role_None": counts["role_None"],
        "role_quoted": counts["role_quoted"],
        "role_unknown": counts["role_unknown"],
        "kind_paragraph": counts["kind_paragraph"],
        "kind_unnumbered": counts["kind_unnumbered"],
        **dict(token_bins),
    }
    assert summary["counts"] == summary_counts_expected, "Summary counts mismatch against independent audit"

    result = {
        "status": "PASS" if not errors else "FAIL",
        "bundle": str(bundle_dir),
        "errors_count": len(errors),
        "errors": errors,
        "counts": dict(counts),
        "token_histogram_bins_64": dict(sorted(token_bins.items())),
        "full_input_token_distribution": {
            "count": len(full_token_values),
            "min": full_token_values[0] if full_token_values else 0,
            "p25": pct(full_token_values, 0.25),
            "median": pct(full_token_values, 0.50),
            "mean": round(sum(full_token_values) / len(full_token_values), 4) if full_token_values else 0,
            "p75": pct(full_token_values, 0.75),
            "p95": pct(full_token_values, 0.95),
            "p99": pct(full_token_values, 0.99),
            "max": full_token_values[-1] if full_token_values else 0,
            "passages_at_exact_448_cap": len(passages_at_448),
            "passages_at_448_examples": passages_at_448[:10],
        },
        "overlap_content_token_distribution_non_first_children": {
            "non_first_children_count": len(overlap_values),
            "min": overlap_values[0] if overlap_values else 0,
            "p25": pct(overlap_values, 0.25),
            "median": pct(overlap_values, 0.50),
            "mean": round(sum(overlap_values) / len(overlap_values), 4) if overlap_values else 0,
            "p75": pct(overlap_values, 0.75),
            "p95": pct(overlap_values, 0.95),
            "max": overlap_values[-1] if overlap_values else 0,
            "children_at_exact_128": counts["overlap_children_eq_128"],
            "children_below_128": counts["overlap_children_lt_128"],
        },
        "overhead_accounting": {
            "unsplit_parent_content_tokens": counts["unsplit_parent_content_tokens"],
            "unsplit_parent_full_tokens": counts["unsplit_parent_full_tokens"],
            "passage_content_tokens": counts["passage_content_tokens"],
            "passage_special_tokens_151643": counts["passage_special_tokens"],
            "overlap_content_tokens": counts["overlap_tokens"],
            "net_content_token_identities_ verified": counts["passage_content_tokens"] - counts["overlap_tokens"] == counts["unsplit_parent_content_tokens"],
            "token_expansion_ratio_full_vs_unsplit_full": round(counts["full_input_tokens"] / counts["unsplit_parent_full_tokens"], 6),
            "overlap_share_of_full_input_tokens": round(counts["overlap_tokens"] / counts["full_input_tokens"], 6),
        },
        "byte_partition_reconciliation": {
            "total_raw_corpus_bytes": counts["total_raw_bytes"],
            "indexed_parent_bytes": counts["indexed_parent_bytes"],
            "unindexed_heading_units": counts["unindexed_heading_units"],
            "unindexed_heading_bytes": counts["unindexed_heading_bytes"],
            "unindexed_whitespace_units": counts["unindexed_whitespace_units"],
            "unindexed_whitespace_bytes": counts["unindexed_whitespace_bytes"],
            "exact_byte_sum_matches_raw": (
                counts["indexed_parent_bytes"] + counts["unindexed_heading_bytes"] + counts["unindexed_whitespace_bytes"]
                == counts["total_raw_bytes"]
            ),
        },
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "model_requests": 0,
        "inference_tokens": 0,
    }

    out_path = ROOT / "pipeline_v2/reviews/m2_passages_ag_review_v1/independent_corpus_audit.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "sources": counts["sources"],
        "parents": counts["parents"],
        "passages": counts["passages"],
        "split_parents": counts["split_parents"],
        "full_input_tokens": counts["full_input_tokens"],
        "overlap_tokens": counts["overlap_tokens"],
        "elapsed_seconds": result["elapsed_seconds"],
    }))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run_independent_audit())
