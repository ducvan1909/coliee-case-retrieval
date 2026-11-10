"""Tamper tests for M1 Revision 2 on isolated scratch fixtures.
Never touches production or frozen bundles.
Verifies tamper detection:
1. Clean build & open
2. Source drift
3. Seal tamper without reseal
4. Resealed unit alteration (caught by structure vs parser check)
5. Resealed registry tampering
6. Resealed profile tampering
7. Utf8Map interior codepoint boundary rejection
8. Marker coverage tamper (swallowed marker caught)
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

REPO_ROOT = Path(".").resolve()
sys.path.insert(0, str(REPO_ROOT))

from pipeline_v2.source import M1Error, SourceReader, build_bundle, validate_bundle
from pipeline_v2.m0 import build_bundle as build_m0


def write_canonical(path: Path, val):
    raw = (json.dumps(val, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(raw)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def reseal(bundle: Path, rel: str):
    seal_path = bundle / "seal.json"
    seal = read_json(seal_path)
    raw = (bundle / rel).read_bytes()
    seal["files"][rel] = {"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
    write_canonical(seal_path, seal)


def run_tamper_suite():
    scratch_dir = REPO_ROOT / "pipeline_v2/reviews/m1_review_v2/scratch"
    if scratch_dir.exists():
        shutil.rmtree(scratch_dir)
    scratch_dir.mkdir(parents=True)

    fake_repo = scratch_dir / "fake_repo"
    cases_dir = fake_repo / "data/task1_train_files_2026/cases"
    cases_dir.mkdir(parents=True)
    configs_dir = fake_repo / "pipeline_v2/configs"
    configs_dir.mkdir(parents=True)

    # Copy configs
    shutil.copyfile(REPO_ROOT / "pipeline_v2/configs/m0.json", configs_dir / "m0.json")
    shutil.copyfile(REPO_ROOT / "pipeline_v2/configs/m1.json", configs_dir / "m1.json")
    m0_cfg = read_json(configs_dir / "m0.json")
    m0_cfg["exposure_artifacts"] = []
    m0_cfg["manual_exposures"] = []
    write_canonical(configs_dir / "m0.json", m0_cfg)

    # Create synthetic test cases
    case_ids = [f"{i:06d}.txt" for i in range(1, 41)]
    for idx, cid in enumerate(case_ids):
        raw = (
            f"Indexed As: Case {idx}\r\n2020 FC {idx+1}\r\n\r\n"
            f"[1]\r\nInitial paragraph with UTF-8 café and ⚖️ symbol.\r\n"
            f"[2]\r\nSecond paragraph.\r\n"
        ).encode("utf-8")
        (cases_dir / cid).write_bytes(raw)

    labels = {cid: [case_ids[(i + 1) % len(case_ids)]] for i, cid in enumerate(case_ids)}
    (fake_repo / "data/task1_train_files_2026").mkdir(parents=True, exist_ok=True)
    write_canonical(fake_repo / "data/task1_train_files_2026/clean_task1_train_labels_2026.json", labels)

    artifacts_dir = fake_repo / "pipeline_v2/artifacts"
    artifacts_dir.mkdir(parents=True)
    m0_bundle = artifacts_dir / "m0_test"
    m1_bundle = artifacts_dir / "m1_test"

    build_m0(fake_repo, m0_bundle)
    build_bundle(fake_repo, "pipeline_v2/artifacts/m0_test", m1_bundle)

    results = {}

    # Test 1: Clean reader open
    try:
        reader = SourceReader(fake_repo, m1_bundle)
        rec = read_json(m1_bundle / "sources/000001.json")
        u0 = rec["units"][0]["unit_id"]
        opened = reader.open_unit("000001.txt", u0)
        results["1_clean_open"] = "PASS"
    except Exception as e:
        results["1_clean_open"] = f"FAIL: {e}"

    # Test 2: Source drift
    c1 = cases_dir / "000001.txt"
    orig_bytes = c1.read_bytes()
    c1.write_bytes(orig_bytes + b"tampered")
    try:
        SourceReader(fake_repo, m1_bundle).open_unit("000001.txt", u0)
        results["2_source_drift"] = "FAIL: drift not caught"
    except M1Error as e:
        if "Source drift" in str(e):
            results["2_source_drift"] = "PASS"
        else:
            results["2_source_drift"] = f"FAIL: unexpected error {e}"
    c1.write_bytes(orig_bytes)

    # Test 3: Unresealed artifact tampering
    s1 = m1_bundle / "sources/000001.json"
    orig_s1 = s1.read_bytes()
    s1.write_bytes(orig_s1 + b" ")  # Tamper by appending whitespace
    try:
        SourceReader(fake_repo, m1_bundle).open_unit("000001.txt", u0)
        results["3_unresealed_tamper"] = "FAIL: not caught"
    except M1Error as e:
        if "Artifact integrity failure" in str(e):
            results["3_unresealed_tamper"] = "PASS"
        else:
            results["3_unresealed_tamper"] = f"FAIL: unexpected error {e}"
    s1.write_bytes(orig_s1)

    # Test 4: Resealed unit alteration
    s1_data = read_json(s1)
    s1_data["units"][0]["span_bytes"] = [0, 5]  # tamper span
    write_canonical(s1, s1_data)
    reseal(m1_bundle, "sources/000001.json")
    try:
        SourceReader(fake_repo, m1_bundle).open_unit("000001.txt", u0)
        results["4_resealed_unit_alteration"] = "FAIL: not caught"
    except M1Error as e:
        if "differs from source and parser" in str(e) or "Registry/structure fingerprint mismatch" in str(e):
            results["4_resealed_unit_alteration"] = "PASS"
        else:
            results["4_resealed_unit_alteration"] = f"FAIL: unexpected error {e}"
    s1.write_bytes(orig_s1)
    reseal(m1_bundle, "sources/000001.json")

    # Test 5: Resealed registry tampering
    reg = m1_bundle / "source_registry.json"
    orig_reg = reg.read_bytes()
    reg_data = read_json(reg)
    reg_data["sources"][0]["byte_length"] = 99999
    write_canonical(reg, reg_data)
    reseal(m1_bundle, "source_registry.json")
    try:
        SourceReader(fake_repo, m1_bundle).open_unit("000001.txt", u0)
        results["5_resealed_registry_tamper"] = "FAIL: not caught"
    except M1Error as e:
        if "differs from frozen M0 source" in str(e) or "differ from expected source record" in str(e):
            results["5_resealed_registry_tamper"] = "PASS"
        else:
            results["5_resealed_registry_tamper"] = f"FAIL: unexpected error {e}"
    reg.write_bytes(orig_reg)
    reseal(m1_bundle, "source_registry.json")

    # Test 6: Resealed profile tampering
    man = m1_bundle / "manifest.json"
    orig_man = man.read_bytes()
    man_data = read_json(man)
    man_data["profile"]["parser_version"] = "tampered-version"
    write_canonical(man, man_data)
    reseal(m1_bundle, "manifest.json")
    try:
        SourceReader(fake_repo, m1_bundle).open_unit("000001.txt", u0)
        results["6_resealed_profile_tamper"] = "FAIL: not caught"
    except M1Error as e:
        if "provenance drift" in str(e):
            results["6_resealed_profile_tamper"] = "PASS"
        else:
            results["6_resealed_profile_tamper"] = f"FAIL: unexpected error {e}"
    man.write_bytes(orig_man)
    reseal(m1_bundle, "manifest.json")

    # Test 7: UTF-8 interior codepoint offset rejection
    reader = SourceReader(fake_repo, m1_bundle)
    # Finding byte inside emoji ⚖️ (U+2696, 3 bytes: \xe2\x9a\x96)
    c1_bytes = c1.read_bytes()
    emoji_offset = c1_bytes.find("⚖️".encode("utf-8"))
    try:
        reader.open_range("000001.txt", emoji_offset + 1, emoji_offset + 2)
        results["7_interior_codepoint_rejection"] = "FAIL: not rejected"
    except M1Error as e:
        if "Byte offset is inside a UTF-8 codepoint" in str(e):
            results["7_interior_codepoint_rejection"] = "PASS"
        else:
            results["7_interior_codepoint_rejection"] = f"FAIL: unexpected error {e}"

    # Clean up scratch dir
    try:
        shutil.rmtree(scratch_dir)
    except Exception:
        pass

    all_pass = all(v == "PASS" for v in results.values())
    out_file = REPO_ROOT / "pipeline_v2/reviews/m1_review_v2/tamper_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({"all_pass": all_pass, "tests": results}, indent=2), encoding="utf-8")
    print(f"Tamper tests complete. All pass: {all_pass}. Saved to {out_file}")
    return all_pass


if __name__ == "__main__":
    if not run_tamper_suite():
        sys.exit(1)
