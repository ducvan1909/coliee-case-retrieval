"""Independent tamper, drift, pagination, CLI, and boundary-fallback tests for M2 Preview Revision 2.

All tamper/drift tests run strictly on a temporary fixture copy in tempfile.TemporaryDirectory().
Uses only the real public API (`NavigationReader`, `build_bundle`, `validate_bundle`, `build_case_navigation`)
and real CLI subcommands (`map`, `anchors`, `source-anchors`, `open`, `validate`).
"""
from __future__ import annotations

import hashlib
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

from pipeline_v2.m0 import build_bundle as build_m0
from pipeline_v2.navigation import M2Error, NavigationReader, build_bundle as build_m2, validate_bundle as validate_m2
from pipeline_v2.navigation.core import build_case_navigation
from pipeline_v2.source import M1Error, build_bundle as build_m1
from pipeline_v2.source.core import parse_source


def write_canonical_json(path: Path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def reseal_file(bundle: Path, rel_path: str):
    seal_path = bundle / "seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    raw = (bundle / rel_path).read_bytes()
    seal["files"][rel_path] = {"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
    write_canonical_json(seal_path, seal)


def run_tests() -> dict:
    started = time.perf_counter()
    results = []
    profile = json.loads((ROOT / "pipeline_v2/configs/m2.json").read_text(encoding="utf-8"))

    # Test 1: Reader on current profile rejects old v1 bundle due to profile/implementation drift
    t0 = time.perf_counter()
    try:
        NavigationReader(ROOT, "pipeline_v2/artifacts/m2_navigation_20261105_v1")
        results.append({"test": "reject_v1_bundle_under_v2_profile", "passed": False, "error": "Did not raise M2Error"})
    except M2Error as exc:
        results.append({
            "test": "reject_v1_bundle_under_v2_profile",
            "passed": True,
            "expected_error": str(exc),
            "elapsed_seconds": round(time.perf_counter() - t0, 4),
        })

    # Test 2: Pagination & open_context on real v3 bundle via NavigationReader and CLI
    t0 = time.perf_counter()
    reader_v3 = NavigationReader(ROOT, "pipeline_v2/artifacts/m2_navigation_20261106_v3")
    rec_014101 = json.loads((ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v3/sources/014101.json").read_text(encoding="utf-8"))
    rec_048208 = json.loads((ROOT / "pipeline_v2/artifacts/m2_navigation_20261106_v3/sources/048208.json").read_text(encoding="utf-8"))
    # Paginate all units of 014101.txt
    paged_items = []
    offset = 0
    while True:
        page = reader_v3.map("014101.txt", offset=offset, limit=5)
        paged_items.extend(page["items"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    # Paginate all anchors of 014101.txt p000008
    anchor_items = []
    offset = 0
    while True:
        apage = reader_v3.anchors("014101.txt", "p000008", offset=offset, limit=2)
        anchor_items.extend(apage["items"])
        if apage["next_offset"] is None:
            break
        offset = apage["next_offset"]
    # Paginate source-anchors of 048208.txt
    sa_items = []
    offset = 0
    while True:
        sapage = reader_v3.source_anchors("048208.txt", offset=offset, limit=1)
        sa_items.extend(sapage["items"])
        if sapage["next_offset"] is None:
            break
        offset = sapage["next_offset"]
    # Open context on 014101.txt p000008
    opened = reader_v3.open_context("014101.txt", "p000008")
    raw_014101 = (ROOT / "data/task1_train_files_2026/cases/014101.txt").read_bytes()
    s_byte, e_byte = opened["span_bytes"]
    exact_match = opened["text"] == raw_014101[s_byte:e_byte].decode("utf-8")

    # Pagination bounds rejection
    bounds_rejected = False
    try:
        reader_v3.map("014101.txt", offset=0, limit=101)
    except M2Error:
        bounds_rejected = True

    expected_p000008_anchors = next(r for r in rec_014101["navigation"] if r["handle"] == "p000008")["anchor_refs"]
    results.append({
        "test": "real_v3_reader_pagination_and_open_context",
        "passed": (
            [x["unit_id"] for x in paged_items] == [r["unit_id"] for r in rec_014101["navigation"]]
            and [a["anchor_id"] for a in anchor_items] == expected_p000008_anchors
            and [sa["source_anchor_id"] for sa in sa_items] == [sa["source_anchor_id"] for sa in rec_048208["source_anchors"]]
            and exact_match
            and bounds_rejected
        ),
        "details": {
            "014101_total_units_paginated": len(paged_items),
            "014101_expected_units": len(rec_014101["navigation"]),
            "014101_p000008_anchors_paginated": len(anchor_items),
            "048208_source_anchors_paginated": len(sa_items),
            "open_context_exact_raw_slice": exact_match,
            "open_context_components": [c["kind"] for c in opened["components"]],
            "invalid_limit_101_rejected": bounds_rejected,
        },
        "elapsed_seconds": round(time.perf_counter() - t0, 4),
    })

    # Test 3: Overlong single word (>240 chars) and overlong protected tag (>240 chars) honest fallback
    t0 = time.perf_counter()
    overlong_word = "A" * 280
    raw_word = f"[1] {overlong_word} tail words.\n".encode("utf-8")
    rec_word = build_case_navigation("123456.txt", raw_word, parse_source("123456.txt", raw_word), profile)
    op_word = rec_word["previews"][0]

    overlong_tag = "<" + ("TAG_" * 65) + "END>"
    raw_tag = f"[1] {overlong_tag} tail words.\n".encode("utf-8")
    rec_tag = build_case_navigation("123456.txt", raw_tag, parse_source("123456.txt", raw_tag), profile)
    op_tag = rec_tag["previews"][0]

    results.append({
        "test": "overlong_word_and_tag_honest_clipping_fallback",
        "passed": (
            len(op_word["text"]) == 240
            and op_word["word_boundary_clipped"] is True
            and op_word["tag_boundary_clipped"] is False
            and op_word["end_clipped"] is True
            and op_word["truncated"] is True
            and op_word["partial_sentence"] is None
            and op_word["text"] == raw_word[slice(*op_word["span_bytes"])].decode("utf-8")
            and len(op_tag["text"]) == 240
            and op_tag["tag_boundary_clipped"] is True
            and op_tag["end_clipped"] is True
            and op_tag["truncated"] is True
            and op_tag["partial_sentence"] is None
            and op_tag["text"] == raw_tag[slice(*op_tag["span_bytes"])].decode("utf-8")
        ),
        "details": {
            "overlong_word_len": len(op_word["text"]),
            "overlong_word_flag": op_word["word_boundary_clipped"],
            "overlong_tag_len": len(op_tag["text"]),
            "overlong_tag_flag": op_tag["tag_boundary_clipped"],
        },
        "elapsed_seconds": round(time.perf_counter() - t0, 4),
    })

    # Test 4..8: Isolated temporary fixture tamper & drift tests
    with tempfile.TemporaryDirectory() as tmpdir:
        t0 = time.perf_counter()
        repo = Path(tmpdir) / "repo"
        cfg_dir = repo / "pipeline_v2/configs"
        cases_dir = repo / "data/task1_train_files_2026/cases"
        cfg_dir.mkdir(parents=True)
        cases_dir.mkdir(parents=True)
        for name in ("m0.json", "m1.json", "m2.json"):
            shutil.copyfile(ROOT / "pipeline_v2/configs" / name, cfg_dir / name)
        m0_cfg = json.loads((cfg_dir / "m0.json").read_text(encoding="utf-8"))
        m0_cfg["exposure_artifacts"] = []
        m0_cfg["manual_exposures"] = []
        write_canonical_json(cfg_dir / "m0.json", m0_cfg)

        ids = [f"{n:06d}.txt" for n in range(1, 31)]
        for i, ident in enumerate(ids):
            raw = (
                f"Indexed As: Fixture {i}\r\n[1]\r\nPinard, J.\r\n: Application for review <FRAGMENT_SUPPRESSED> "
                + ("substantive text " * 20)
                + "<REFERENCE_SUPPRESSED> conclusion.\r\n[2]\r\n<FRAGMENT_SUPPRESSED> )\r\nReal second paragraph.\r\n"
            ).encode("utf-8")
            (cases_dir / ident).write_bytes(raw)
        labels = {ident: [ids[(i + 1) % len(ids)]] for i, ident in enumerate(ids)}
        write_canonical_json(repo / "data/task1_train_files_2026/clean_task1_train_labels_2026.json", labels)

        (repo / "pipeline_v2/artifacts").mkdir(parents=True)
        build_m0(repo, repo / "pipeline_v2/artifacts/m0_fix")
        build_m1(repo, "pipeline_v2/artifacts/m0_fix", repo / "pipeline_v2/artifacts/m1_fix")
        build_m2(repo, "pipeline_v2/artifacts/m1_fix", "pipeline_v2/artifacts/m2_fix")
        m2_fix = repo / "pipeline_v2/artifacts/m2_fix"

        # 4a: Unresealed byte tamper in sources/000001.json
        t_unresealed = repo / "pipeline_v2/artifacts/m2_unresealed"
        shutil.copytree(m2_fix, t_unresealed)
        rec = json.loads((t_unresealed / "sources/000001.json").read_text(encoding="utf-8"))
        rec["previews"][0]["text"] = "Tampered text"
        write_canonical_json(t_unresealed / "sources/000001.json", rec)
        unresealed_rejected = False
        try:
            validate_m2(repo, "pipeline_v2/artifacts/m2_unresealed")
        except M2Error as exc:
            unresealed_rejected = "seal integrity failure" in str(exc)

        # 4b: Resealed tamper setting partial_sentence = False
        t_resealed_ps = repo / "pipeline_v2/artifacts/m2_resealed_ps"
        shutil.copytree(m2_fix, t_resealed_ps)
        rec = json.loads((t_resealed_ps / "sources/000001.json").read_text(encoding="utf-8"))
        rec["previews"][0]["partial_sentence"] = False
        write_canonical_json(t_resealed_ps / "sources/000001.json", rec)
        reseal_file(t_resealed_ps, "sources/000001.json")
        resealed_ps_rejected = False
        try:
            validate_m2(repo, "pipeline_v2/artifacts/m2_resealed_ps")
        except M2Error:
            resealed_ps_rejected = True

        # 4c: Resealed tamper injecting contained duplicate preview
        t_resealed_cont = repo / "pipeline_v2/artifacts/m2_resealed_cont"
        shutil.copytree(m2_fix, t_resealed_cont)
        rec = json.loads((t_resealed_cont / "sources/000001.json").read_text(encoding="utf-8"))
        p0 = dict(rec["previews"][0])
        p_dup = dict(p0)
        p_dup["preview_id"] = "p000001:v02"
        p_dup["preview_kind"] = "anchor"
        rec["previews"].append(p_dup)
        rec["navigation"][0]["preview_refs"].append("p000001:v02")
        write_canonical_json(t_resealed_cont / "sources/000001.json", rec)
        reseal_file(t_resealed_cont, "sources/000001.json")
        resealed_cont_rejected = False
        try:
            validate_m2(repo, "pipeline_v2/artifacts/m2_resealed_cont")
        except M2Error:
            resealed_cont_rejected = True

        # 4d: Raw source drift rejected
        case1 = cases_dir / "000001.txt"
        orig_raw = case1.read_bytes()
        case1.write_bytes(orig_raw + b" ")
        raw_drift_rejected = False
        try:
            NavigationReader(repo, "pipeline_v2/artifacts/m2_fix").map("000001.txt")
        except (M1Error, M2Error):
            raw_drift_rejected = True
        finally:
            case1.write_bytes(orig_raw)

        # 4e: Profile drift rejected
        prof_file = cfg_dir / "m2.json"
        orig_prof = prof_file.read_bytes()
        p_mod = json.loads(orig_prof.decode("utf-8"))
        p_mod["preview"]["max_chars"] = 200
        write_canonical_json(prof_file, p_mod)
        prof_drift_rejected = False
        try:
            NavigationReader(repo, "pipeline_v2/artifacts/m2_fix")
        except M2Error:
            prof_drift_rejected = True
        finally:
            prof_file.write_bytes(orig_prof)

        # 4f: M1 seal drift rejected
        m1_seal = repo / "pipeline_v2/artifacts/m1_fix/seal.json"
        orig_m1_seal = m1_seal.read_bytes()
        m1_seal.write_bytes(orig_m1_seal + b"\n")
        m1_drift_rejected = False
        try:
            NavigationReader(repo, "pipeline_v2/artifacts/m2_fix")
        except (M1Error, M2Error):
            m1_drift_rejected = True
        finally:
            m1_seal.write_bytes(orig_m1_seal)

        results.append({
            "test": "isolated_fixture_tamper_reseal_and_drift_suite",
            "passed": all([
                unresealed_rejected,
                resealed_ps_rejected,
                resealed_cont_rejected,
                raw_drift_rejected,
                prof_drift_rejected,
                m1_drift_rejected,
            ]),
            "details": {
                "unresealed_tamper_rejected": unresealed_rejected,
                "resealed_partial_sentence_tamper_rejected": resealed_ps_rejected,
                "resealed_contained_preview_tamper_rejected": resealed_cont_rejected,
                "raw_source_drift_rejected": raw_drift_rejected,
                "profile_drift_rejected": prof_drift_rejected,
                "m1_seal_drift_rejected": m1_drift_rejected,
            },
            "elapsed_seconds": round(time.perf_counter() - t0, 4),
        })

    # Test 5: CLI subcommands (`map`, `anchors`, `source-anchors`, `open`) on real v3 bundle
    t0 = time.perf_counter()
    py = str(ROOT / ".venv/Scripts/python.exe")
    cli_cmds = [
        [py, "-m", "pipeline_v2.m2", "map", "--repo-root", str(ROOT), "--bundle", "pipeline_v2/artifacts/m2_navigation_20261106_v3", "--case", "011922.txt", "--offset", "0", "--limit", "6"],
        [py, "-m", "pipeline_v2.m2", "anchors", "--repo-root", str(ROOT), "--bundle", "pipeline_v2/artifacts/m2_navigation_20261106_v3", "--case", "014101.txt", "--handle", "p000008", "--offset", "0", "--limit", "10"],
        [py, "-m", "pipeline_v2.m2", "source-anchors", "--repo-root", str(ROOT), "--bundle", "pipeline_v2/artifacts/m2_navigation_20261106_v3", "--case", "048208.txt", "--offset", "0", "--limit", "10"],
        [py, "-m", "pipeline_v2.m2", "open", "--repo-root", str(ROOT), "--bundle", "pipeline_v2/artifacts/m2_navigation_20261106_v3", "--case", "051807.txt", "--handle", "u000030"],
    ]
    cli_passed = True
    cli_outputs = []
    for cmd in cli_cmds:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            cli_passed = False
        parsed = json.loads(proc.stdout) if proc.returncode == 0 else {"stderr": proc.stderr}
        cli_outputs.append({
            "command": " ".join(cmd[3:]),
            "exit_code": proc.returncode,
            "local_elapsed_seconds": parsed.get("local_elapsed_seconds"),
        })
    results.append({
        "test": "cli_subcommands_map_anchors_source_anchors_open",
        "passed": cli_passed,
        "details": cli_outputs,
        "elapsed_seconds": round(time.perf_counter() - t0, 4),
    })

    summary = {
        "schema_version": "m2-preview-revision2-tamper-boundary-v1",
        "status": "PASS" if all(r["passed"] for r in results) else "FAIL",
        "total_tests": len(results),
        "passed_tests": sum(1 for r in results if r["passed"]),
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "results": results,
    }
    out_path = Path(__file__).resolve().parents[1] / "tamper_and_boundary_results.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run_tests()
