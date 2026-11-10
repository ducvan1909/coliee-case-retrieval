"""Independent tamper, reseal, drift-after-init, tokenizer edge-case, CLI, and middle-child context tests."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tokenizers import Tokenizer
from pipeline_v2.passages import PassageError, PinnedTokenizer, PassageReader, split_text, validate_bundle
from pipeline_v2.passages.store import registry_row
from pipeline_v2.navigation import M2Error
from pipeline_v2.source import M1Error
from pipeline_v2.source.core import canonical, digest


def read_json(path: Path):
    return json.loads(path.read_bytes())


def write_json_canonical(path: Path, payload):
    raw = canonical(payload)
    path.write_bytes(raw)
    return {"sha256": digest(raw), "byte_length": len(raw)}


def reseal_bundle(bundle_dir: Path, updated_rel_path: str):
    seal_path = bundle_dir / "seal.json"
    seal = read_json(seal_path)
    raw = (bundle_dir / updated_rel_path).read_bytes()
    seal["files"][updated_rel_path] = {"sha256": digest(raw), "byte_length": len(raw)}
    seal_path.write_bytes(canonical(seal))


def test_1_bundle_seal_and_file_universe():
    t0 = time.perf_counter()
    bundle_dir = ROOT / "pipeline_v2/artifacts/m2_passages_20261106_v1"
    seal = read_json(bundle_dir / "seal.json")
    assert seal["schema_version"] == "pipeline-v2-m2-passages-seal-1"
    actual_files = sorted(p.relative_to(bundle_dir).as_posix() for p in bundle_dir.rglob("*") if p.is_file())
    expected_files = sorted(set(seal["files"].keys()) | {"seal.json"})
    assert actual_files == expected_files, "File universe mismatch"
    assert len(seal["files"]) == 7711, f"Expected 7711 sealed entries, got {len(seal['files'])}"
    assert len(actual_files) == 7712, f"Expected 7712 total files, got {len(actual_files)}"
    total_bytes = sum((bundle_dir / f).stat().st_size for f in actual_files)
    manifest = read_json(bundle_dir / "manifest.json")
    summary = read_json(bundle_dir / "summary.json")
    build_receipt = read_json(ROOT / "pipeline_v2/artifacts/m2_passages_20261106_v1.build-receipt.json")
    validator_receipt = read_json(ROOT / "pipeline_v2/reviews/m2_passages_validation_v1/validator_receipt.json")
    assert build_receipt["exit_code"] == 0
    assert validator_receipt["exit_code"] == 0
    assert json.loads(build_receipt["stdout"])["summary"] == summary
    assert json.loads(validator_receipt["stdout"])["summary"] == summary
    return {
        "status": "PASS",
        "sealed_entries": len(seal["files"]),
        "total_files_including_seal": len(actual_files),
        "total_bundle_bytes": total_bytes,
        "seal_sha256": digest((bundle_dir / "seal.json").read_bytes()),
        "manifest_sha256": digest((bundle_dir / "manifest.json").read_bytes()),
        "summary_sha256": digest((bundle_dir / "summary.json").read_bytes()),
        "registry_sha256": digest((bundle_dir / "source_registry.json").read_bytes()),
        "elapsed_seconds": round(time.perf_counter() - t0, 6),
    }


def test_2_tamper_reseal_and_drift_after_reader_init():
    t0 = time.perf_counter()
    from pipeline_v2.tests import test_m2_navigation_store as nav_tests

    nav_tests.M2NavigationStoreTests.setUpClass()
    try:
        temp_root = nav_tests.M2NavigationStoreTests.root
        configs = temp_root / "pipeline_v2/configs"
        for name in ("m2_passages.json", "qwen3_embedding_4b_tokenizer.lock.json"):
            shutil.copyfile(ROOT / "pipeline_v2/configs" / name, configs / name)
        lock = read_json(configs / "qwen3_embedding_4b_tokenizer.lock.json")
        shutil.copytree(ROOT / lock["assets_dir"], temp_root / lock["assets_dir"])
        from pipeline_v2.passages import build_bundle

        bundle_rel = "pipeline_v2/artifacts/passages-review-fixture"
        build_bundle(temp_root, "pipeline_v2/artifacts/m2-fixture", bundle_rel)
        fixture_dir = temp_root / bundle_rel

        subchecks = {}

        # 2a. Unsealed tamper on sources/000001.json
        t_unsealed = temp_root / "pipeline_v2/artifacts/tamper-unsealed"
        shutil.copytree(fixture_dir, t_unsealed)
        p_000001 = t_unsealed / "sources/000001.json"
        rec = read_json(p_000001)
        rec["passages"][0]["full_input_tokens"] += 1
        write_json_canonical(p_000001, rec)
        try:
            PassageReader(temp_root, t_unsealed).inspect("000001.txt")
            raise AssertionError("Unsealed tamper was not rejected")
        except PassageError as exc:
            subchecks["unsealed_source_tamper"] = {"rejected": True, "error": str(exc)}

        # 2b. Resealed tamper on full_input_tokens (also updating source_registry.json and resealing both)
        t_resealed_tok = temp_root / "pipeline_v2/artifacts/tamper-resealed-tokens"
        shutil.copytree(fixture_dir, t_resealed_tok)
        p_000001 = t_resealed_tok / "sources/000001.json"
        rec = read_json(p_000001)
        rec["passages"][0]["full_input_tokens"] += 1
        write_json_canonical(p_000001, rec)
        reg_path = t_resealed_tok / "source_registry.json"
        reg = read_json(reg_path)
        reg["sources"] = [registry_row("000001.txt", rec) if r["case_id"] == "000001.txt" else r for r in reg["sources"]]
        write_json_canonical(reg_path, reg)
        reseal_bundle(t_resealed_tok, "sources/000001.json")
        reseal_bundle(t_resealed_tok, "source_registry.json")
        try:
            PassageReader(temp_root, t_resealed_tok).inspect("000001.txt")
            raise AssertionError("Resealed token count tamper was not rejected")
        except PassageError as exc:
            subchecks["resealed_token_count_and_registry_tamper"] = {"rejected": True, "error": str(exc)}

        # 2c. Resealed tamper on passage span_bytes/text
        t_resealed_span = temp_root / "pipeline_v2/artifacts/tamper-resealed-span"
        shutil.copytree(fixture_dir, t_resealed_span)
        p_000001 = t_resealed_span / "sources/000001.json"
        rec = read_json(p_000001)
        rec["passages"][0]["text"] = rec["passages"][0]["text"][:-1]
        write_json_canonical(p_000001, rec)
        reg_path = t_resealed_span / "source_registry.json"
        reg = read_json(reg_path)
        reg["sources"] = [registry_row("000001.txt", rec) if r["case_id"] == "000001.txt" else r for r in reg["sources"]]
        write_json_canonical(reg_path, reg)
        reseal_bundle(t_resealed_span, "sources/000001.json")
        reseal_bundle(t_resealed_span, "source_registry.json")
        try:
            PassageReader(temp_root, t_resealed_span).inspect("000001.txt")
            raise AssertionError("Resealed text tamper was not rejected")
        except PassageError as exc:
            subchecks["resealed_text_and_registry_tamper"] = {"rejected": True, "error": str(exc)}

        # 2d. Extra unsealed file in bundle rejected by validate_bundle
        t_extra = temp_root / "pipeline_v2/artifacts/tamper-extra-file"
        shutil.copytree(fixture_dir, t_extra)
        (t_extra / "sources/extra.json").write_bytes(b"{}\n")
        try:
            validate_bundle(temp_root, t_extra)
            raise AssertionError("Extra unsealed file was not rejected")
        except PassageError as exc:
            subchecks["extra_unsealed_file_in_bundle"] = {"rejected": True, "error": str(exc)}

        # 2e. Upstream mutations AFTER PassageReader initialization (same reader instance!)
        reader = PassageReader(temp_root, bundle_rel)
        drift_targets = [
            ("raw_case_after_init", temp_root / "data/task1_train_files_2026/cases/000001.txt"),
            ("m2_passages_profile_after_init", temp_root / "pipeline_v2/configs/m2_passages.json"),
            ("m2_navigation_profile_after_init", temp_root / "pipeline_v2/configs/m2.json"),
            ("m1_profile_after_init", temp_root / "pipeline_v2/configs/m1.json"),
            ("tokenizer_lock_after_init", temp_root / "pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json"),
            ("tokenizer_asset_after_init", temp_root / lock["assets_dir"] / "tokenizer_config.json"),
            ("m1_artifact_after_init", temp_root / "pipeline_v2/artifacts/m1-fixture/sources/000001.json"),
            ("m2_nav_artifact_after_init", temp_root / "pipeline_v2/artifacts/m2-fixture/sources/000001.json"),
        ]
        for label, target_path in drift_targets:
            original = target_path.read_bytes()
            try:
                target_path.write_bytes(original + b" ")
                try:
                    reader.inspect("000001.txt")
                    raise AssertionError(f"Drift not rejected for {label}")
                except (PassageError, M1Error, M2Error) as exc:
                    subchecks[label] = {"rejected": True, "error_type": type(exc).__name__, "error": str(exc)}
            finally:
                target_path.write_bytes(original)

        # Confirm reader recovers cleanly once original bytes are restored
        clean_page = reader.inspect("000001.txt", 0, 5)
        assert clean_page["total"] >= 1

        return {
            "status": "PASS",
            "subchecks": subchecks,
            "elapsed_seconds": round(time.perf_counter() - t0, 6),
        }
    finally:
        nav_tests.M2NavigationStoreTests.tearDownClass()


def test_3_tokenizer_lock_postprocessor_and_edge_cases():
    t0 = time.perf_counter()
    profile = read_json(ROOT / "pipeline_v2/configs/m2_passages.json")
    lock = read_json(ROOT / profile["tokenizer_lock"])
    tok = PinnedTokenizer(ROOT, profile["tokenizer_lock"])

    assert lock["model_id"] == "Qwen/Qwen3-Embedding-4B"
    assert lock["revision"] == "5cf2132abc99cad020ac570b19d031efec650f2b"
    assert importlib.metadata.version("tokenizers") == "0.22.2" == lock["package_versions"]["tokenizers"]
    assert tok.backend.truncation is None
    assert tok.backend.padding is None
    assert tok.backend.num_special_tokens_to_add(False) == 1

    # Verify postprocessor adds exactly one <|endoftext|> (151643) for full input and 0 for content
    samples = [
        "Simple ASCII sentence.",
        "\ufeff[1] Line one\r\nLine two\r\n",
        "Énoncé français avec accents: é, è, ê, ç, œ, « citation ».",
        "漢字テスト and emoji \U0001f9d1\u200d\u2696\ufe0f multi-codepoint.",
        "<|endoftext|> literal <|im_start|> user <|im_end|> tokens in raw text.",
    ]
    sample_checks = []
    for s in samples:
        enc_full = tok.backend.encode(s, add_special_tokens=True)
        enc_content = tok.backend.encode(s, add_special_tokens=False)
        assert len(enc_full.ids) == len(enc_content.ids) + 1
        assert enc_full.ids[-1] == 151643
        assert enc_full.ids[:-1] == enc_content.ids
        assert tok.count(s) == len(enc_full.ids)
        assert tok.count_content(s) == len(enc_content.ids)
        sample_checks.append({
            "sample_prefix": s[:32],
            "full_tokens": len(enc_full.ids),
            "content_tokens": len(enc_content.ids),
            "trailing_id": enc_full.ids[-1],
        })

    # Verify split_text edge cases
    edge_inputs = {
        "fitting_above_target_320_le_448": "word " * 400,
        "crlf_and_bom_long": "\ufeff" + "  clause\r\n" * 1000,
        "unicode_cjk_emoji_zwj_long": "\u00e9\u6cd5\U0001f9d1\u200d\u2696\ufe0f " * 400,
        "unbroken_no_whitespace_9000_chars": "A" * 9000,
        "whitespace_only_long": "\r\n\t " * 3000,
        "special_token_literals_long": "<|endoftext|> literal <|im_start|> " * 500,
    }
    edge_results = {}
    for name, text in edge_inputs.items():
        parts = split_text(text, tok, profile)
        assert parts[0]["start"] == 0
        assert parts[-1]["end"] == len(text)
        covered = 0
        prev_start = -1
        for i, p in enumerate(parts):
            s, e = p["start"], p["end"]
            assert 0 <= s < e <= len(text)
            assert s <= covered and e > covered, f"Gap or non-advancing end in {name} at {i}"
            assert s > prev_start, f"Non-advancing start in {name} at {i}"
            slice_text = text[s:e]
            assert p["token_count"] == tok.count(slice_text) <= profile["max_input_tokens"]
            expected_ov = tok.count_content(text[s:covered]) if i > 0 and s < covered else 0
            assert p["overlap_tokens"] == expected_ov <= profile["overlap_tokens"]
            expected_wb = e < len(text) and not text[e - 1].isspace() and not text[e].isspace()
            assert p["word_boundary_split"] == expected_wb
            covered = e
            prev_start = s
        edge_results[name] = {
            "num_slices": len(parts),
            "max_full_tokens": max(p["token_count"] for p in parts),
            "max_overlap_tokens": max(p["overlap_tokens"] for p in parts),
            "word_boundary_splits": sum(p["word_boundary_split"] for p in parts),
        }

    assert edge_results["fitting_above_target_320_le_448"]["num_slices"] == 1
    assert edge_results["unbroken_no_whitespace_9000_chars"]["word_boundary_splits"] > 0

    # Verify impossible cap and invalid profile rejections
    impossible_checks = {}
    for bad_label, bad_text, bad_prof in [
        ("overlap_ge_target", "hello", {**profile, "overlap_tokens": 320}),
        ("target_gt_max", "hello", {**profile, "target_tokens": 449}),
        ("empty_parent", "", profile),
        ("single_codepoint_exceeds_cap_1", "\U0001f9d1" * 10, {**profile, "target_tokens": 1, "overlap_tokens": 0, "max_input_tokens": 1}),
    ]:
        try:
            split_text(bad_text, tok, bad_prof)
            raise AssertionError(f"Failed to reject {bad_label}")
        except PassageError as exc:
            impossible_checks[bad_label] = {"rejected": True, "error": str(exc)}

    return {
        "status": "PASS",
        "sample_checks": sample_checks,
        "edge_results": edge_results,
        "impossible_checks": impossible_checks,
        "elapsed_seconds": round(time.perf_counter() - t0, 6),
    }


def test_4_cli_subcommands():
    t0 = time.perf_counter()
    bundle = "pipeline_v2/artifacts/m2_passages_20261106_v1"
    python_exe = str(ROOT / ".venv/Scripts/python.exe")

    # 4a. inspect CLI
    cmd_inspect = [python_exe, "-m", "pipeline_v2.m2_passages", "inspect", "--repo-root", str(ROOT), "--bundle", bundle, "--case", "041666.txt", "--offset", "0", "--limit", "3"]
    proc_inspect = subprocess.run(cmd_inspect, capture_output=True, text=True, check=False)
    assert proc_inspect.returncode == 0, proc_inspect.stderr
    out_inspect = json.loads(proc_inspect.stdout)
    assert out_inspect["case_id"] == "041666.txt"
    assert len(out_inspect["items"]) == 3
    assert out_inspect["total"] > 100

    # 4b. open CLI on middle child
    pid = "041666:6aa38298330c0005b7207373"
    cmd_open = [python_exe, "-m", "pipeline_v2.m2_passages", "open", "--repo-root", str(ROOT), "--bundle", bundle, "--case", "041666.txt", "--passage-id", pid]
    proc_open = subprocess.run(cmd_open, capture_output=True, text=True, check=False)
    assert proc_open.returncode == 0, proc_open.stderr
    out_open = json.loads(proc_open.stdout)
    assert out_open["hit_passage_id"] == pid
    assert out_open["requested_handle"] == "p000417"
    assert out_open["diagnostic_only"] is True
    assert out_open["M4_delivery_recorded"] is False

    # 4c. error exit code 2 on unknown passage ID
    cmd_err = [python_exe, "-m", "pipeline_v2.m2_passages", "open", "--repo-root", str(ROOT), "--bundle", bundle, "--case", "041666.txt", "--passage-id", "nonexistent"]
    proc_err = subprocess.run(cmd_err, capture_output=True, text=True, check=False)
    assert proc_err.returncode == 2
    err_payload = json.loads(proc_err.stderr)
    assert err_payload["valid"] is False

    return {
        "status": "PASS",
        "inspect_total_passages_041666": out_inspect["total"],
        "open_hit_passage_id": out_open["hit_passage_id"],
        "open_span_bytes": out_open["span_bytes"],
        "error_exit_code_verified": proc_err.returncode,
        "elapsed_seconds": round(time.perf_counter() - t0, 6),
    }


def test_5_real_middle_child_open_context_scenarios():
    """Verify PassageReader.open_context on middle children across 5 structural scenarios."""
    t0 = time.perf_counter()
    bundle_rel = "pipeline_v2/artifacts/m2_passages_20261106_v1"
    reader = PassageReader(ROOT, bundle_rel)
    bundle_dir = ROOT / bundle_rel
    nav_dir = ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v3"

    # Scan corpus JSONs to pick deterministic examples of the 5 middle-child scenarios:
    # 1. End-of-source largest split parent: 041666.txt / p000417 (110 children, middle child index 55)
    # 2. Interior split parent skipping unnumbered unit in paragraph_order: 041666.txt / p000153 (3 children, middle child index 1)
    # 3. Start-of-source split parent (previous_ref is None, split_count >= 3, middle child)
    # 4. Split parent with repeated/jumping markers or quoted role (split_count >= 3, middle child)
    # 5. Split parent with intervening heading(s) in opened context envelope (split_count >= 3, middle child)
    start_of_source_candidate = None
    jumping_or_quoted_candidate = None
    intervening_heading_candidate = None

    registry = read_json(bundle_dir / "source_registry.json")["sources"]
    for row in registry:
        case_id = row["case_id"]
        if row["passage_count"] == row["parent_count"]:
            continue
        rec = read_json(bundle_dir / row["passages_ref"])
        nav = read_json(nav_dir / "sources" / f"{case_id[:-4]}.json")
        nav_by_handle = {u["handle"]: u for u in nav["navigation"]}
        passages_by_id = {p["passage_id"]: p for p in rec["passages"]}

        for parent in rec["parents"]:
            refs = parent["passage_refs"]
            if len(refs) < 3:
                continue
            mid_id = refs[len(refs) // 2]
            mid_p = passages_by_id[mid_id]
            exp = mid_p["reading_expansion"]

            if start_of_source_candidate is None and exp["previous_ref"] is None and exp["next_ref"] is not None:
                start_of_source_candidate = (case_id, parent["handle"], mid_id)

            if jumping_or_quoted_candidate is None and exp["previous_ref"] and exp["next_ref"]:
                u_prev = nav_by_handle[exp["previous_ref"]]
                u_curr = nav_by_handle[parent["handle"]]
                u_next = nav_by_handle[exp["next_ref"]]
                if (u_curr["observed_marker"] is not None and u_prev["observed_marker"] is not None and u_next["observed_marker"] is not None):
                    if (u_curr["observed_marker"] - u_prev["observed_marker"] != 1 or
                        u_next["observed_marker"] - u_curr["observed_marker"] != 1 or
                        u_curr["paragraph_role"] == "quoted"):
                        jumping_or_quoted_candidate = (case_id, parent["handle"], mid_id)

            if intervening_heading_candidate is None and exp["previous_ref"] and exp["next_ref"] and nav["headings"]:
                u_prev = nav_by_handle[exp["previous_ref"]]
                u_next = nav_by_handle[exp["next_ref"]]
                env_start, env_end = u_prev["span_bytes"][0], u_next["span_bytes"][1]
                headings_in_env = [h for h in nav["headings"] if env_start <= h["span_bytes"][0] and h["span_bytes"][1] <= env_end]
                if headings_in_env:
                    intervening_heading_candidate = (case_id, parent["handle"], mid_id)

        if start_of_source_candidate and jumping_or_quoted_candidate and intervening_heading_candidate:
            break

    scenarios = [
        ("end_of_source_largest_parent", "041666.txt", "p000417", "041666:6aa38298330c0005b7207373"),
        ("interior_skipping_unnumbered_neighbors", "041666.txt", "p000153", "041666:3f296642490ce0314e005143"),
    ]
    if start_of_source_candidate:
        scenarios.append(("start_of_source_split_parent", *start_of_source_candidate))
    if jumping_or_quoted_candidate:
        scenarios.append(("jumping_or_quoted_marker_split_parent", *jumping_or_quoted_candidate))
    if intervening_heading_candidate:
        scenarios.append(("intervening_heading_split_parent", *intervening_heading_candidate))

    results = {}
    for label, case_id, handle, pid in scenarios:
        raw = (ROOT / "data/task1_train_files_2026/cases" / case_id).read_bytes()
        rec = read_json(bundle_dir / "sources" / f"{case_id[:-4]}.json")
        nav = read_json(nav_dir / "sources" / f"{case_id[:-4]}.json")
        nav_by_handle = {u["handle"]: u for u in nav["navigation"]}
        hit = next(p for p in rec["passages"] if p["passage_id"] == pid)
        assert 0 < hit["split_order"] < hit["split_count"] - 1, f"Not a middle child: {pid}"
        assert hit["previous_sibling_ref"] is not None and hit["next_sibling_ref"] is not None

        opened = reader.open_context(case_id, pid)
        env_a, env_b = opened["span_bytes"]
        assert opened["text"] == raw[env_a:env_b].decode("utf-8")
        assert opened["hit_passage_id"] == pid
        assert opened["hit_span_bytes"] == hit["span_bytes"]
        assert opened["hit_text"] == raw[slice(*hit["span_bytes"])].decode("utf-8") == hit["text"]
        assert opened["hit_is_distinct_from_context"] is True
        assert opened["diagnostic_only"] is True
        assert opened["M4_delivery_recorded"] is False
        assert hit["span_bytes"][0] >= hit["parent_span_bytes"][0] and hit["span_bytes"][1] <= hit["parent_span_bytes"][1]
        assert hit["span_bytes"] != hit["parent_span_bytes"]

        comps = {c["kind"]: c for c in opened["components"]}
        assert comps["parent"]["handle"] == handle
        assert comps["parent"]["span_bytes"] == hit["parent_span_bytes"]
        exp = hit["reading_expansion"]
        if exp["previous_ref"] is None:
            assert "previous_context" not in comps
            assert exp["previous_absence_reason"] == "source_boundary"
        else:
            assert comps["previous_context"]["handle"] == exp["previous_ref"]
        if exp["next_ref"] is None:
            assert "next_context" not in comps
            assert exp["next_absence_reason"] == "source_boundary"
        else:
            assert comps["next_context"]["handle"] == exp["next_ref"]

        assert env_a == min(c["span_bytes"][0] for c in opened["components"])
        assert env_b == max(c["span_bytes"][1] for c in opened["components"])

        results[label] = {
            "case_id": case_id,
            "parent_handle": handle,
            "passage_id": pid,
            "split_order": hit["split_order"],
            "split_count": hit["split_count"],
            "hit_span_bytes": hit["span_bytes"],
            "parent_span_bytes": hit["parent_span_bytes"],
            "opened_span_bytes": opened["span_bytes"],
            "components": [
                {
                    "kind": c["kind"],
                    "handle": c["handle"],
                    "observed_marker": nav_by_handle[c["handle"]]["observed_marker"],
                    "unit_kind": nav_by_handle[c["handle"]]["unit_kind"],
                    "paragraph_role": nav_by_handle[c["handle"]]["paragraph_role"],
                    "span_bytes": c["span_bytes"],
                }
                for c in opened["components"]
            ],
            "intervening_headings_count": len(opened["intervening_headings"]),
            "intervening_headings": opened["intervening_headings"],
            "neighbor_policy": opened["neighbor_policy"],
        }

    return {
        "status": "PASS",
        "scenarios_verified": len(results),
        "scenarios": results,
        "elapsed_seconds": round(time.perf_counter() - t0, 6),
    }


def main():
    started = time.perf_counter()
    report = {
        "test_1_bundle_seal_and_file_universe": test_1_bundle_seal_and_file_universe(),
        "test_2_tamper_reseal_and_drift_after_reader_init": test_2_tamper_reseal_and_drift_after_reader_init(),
        "test_3_tokenizer_lock_postprocessor_and_edge_cases": test_3_tokenizer_lock_postprocessor_and_edge_cases(),
        "test_4_cli_subcommands": test_4_cli_subcommands(),
        "test_5_real_middle_child_open_context_scenarios": test_5_real_middle_child_open_context_scenarios(),
    }
    report["overall_status"] = "PASS" if all(v["status"] == "PASS" for v in report.values()) else "FAIL"
    report["total_elapsed_seconds"] = round(time.perf_counter() - started, 6)

    out_path = ROOT / "pipeline_v2/reviews/m2_passages_ag_review_v1/tamper_tokenizer_and_cli_results.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall_status": report["overall_status"], "total_elapsed_seconds": report["total_elapsed_seconds"]}))


if __name__ == "__main__":
    main()
