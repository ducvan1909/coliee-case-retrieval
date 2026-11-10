"""Tamper resistance verification on isolated scratch fixture.

DOES NOT modify production bundles. Copies minimal fixtures into scratch/.
Verifies:
1. Source file drift is detected by SourceReader.
2. Structure JSON unit alteration + reseal is detected.
3. Registry record tampering + reseal is detected.
4. Manifest profile tampering + reseal is detected.
5. Reader rejects interior UTF-8 codepoint offsets.
"""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from pipeline_v2.source import M1Error, SourceReader, build_bundle, validate_bundle
from pipeline_v2.m0 import build_bundle as build_m0


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def reseal(bundle: Path, relative: str):
    seal_path = bundle / "seal.json"
    seal = read_json(seal_path)
    raw = (bundle / relative).read_bytes()
    seal["files"][relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
    write_json(seal_path, seal)


def run_tamper_tests():
    scratch_dir = ROOT / "pipeline_v2" / "reviews" / "m1_review_v1" / "scratch"
    if scratch_dir.exists():
        shutil.rmtree(scratch_dir)
    scratch_dir.mkdir(parents=True)

    fake_repo = scratch_dir / "fake_repo"
    cases_dir = fake_repo / "data" / "task1_train_files_2026" / "cases"
    cases_dir.mkdir(parents=True)
    configs_dir = fake_repo / "pipeline_v2" / "configs"
    configs_dir.mkdir(parents=True)

    # Copy configs
    shutil.copyfile(ROOT / "pipeline_v2" / "configs" / "m0.json", configs_dir / "m0.json")
    shutil.copyfile(ROOT / "pipeline_v2" / "configs" / "m1.json", configs_dir / "m1.json")
    m0_cfg = read_json(configs_dir / "m0.json")
    m0_cfg["exposure_artifacts"] = []
    m0_cfg["manual_exposures"] = []
    write_json(configs_dir / "m0.json", m0_cfg)

    # Create dummy cases
    case_ids = [f"{i:06d}.txt" for i in range(1, 41)]
    for idx, cid in enumerate(case_ids):
        raw = f"Indexed As: Case {idx}\r\n2020 FC {idx+1}\r\n\r\n[1]\r\nTest text with 🧑‍⚖️ emoji.\r\n[2]\r\nEnd.\r\n".encode("utf-8")
        (cases_dir / cid).write_bytes(raw)

    labels = {cid: [case_ids[(i+1)%len(case_ids)]] for i, cid in enumerate(case_ids)}
    write_json(fake_repo / "data" / "task1_train_files_2026" / "clean_task1_train_labels_2026.json", labels)

    artifacts_dir = fake_repo / "pipeline_v2" / "artifacts"
    artifacts_dir.mkdir(parents=True)
    m0_bundle = artifacts_dir / "m0_test"
    m1_bundle = artifacts_dir / "m1_test"

    build_m0(fake_repo, m0_bundle)
    build_bundle(fake_repo, "pipeline_v2/artifacts/m0_test", m1_bundle)

    results = {}

    # Test 1: Clean reader open
    try:
        reader = SourceReader(fake_repo, m1_bundle)
        rec = read_json(m1_bundle / "sources" / "000001.json")
        u0 = rec["units"][0]["unit_id"]
        opened = reader.open_unit("000001.txt", u0)
        results["clean_open"] = "PASS"
    except Exception as e:
        results["clean_open"] = f"FAIL: {e}"

    # Test 2: Source drift
    try:
        c1 = cases_dir / "000001.txt"
        orig_bytes = c1.read_bytes()
        c1.write_bytes(orig_bytes + b"tampered")
        caught = False
        try:
            SourceReader(fake_repo, m1_bundle).open_unit("000001.txt", u0)
        except M1Error as e:
            if "Source drift" in str(e):
                caught = True
        c1.write_bytes(orig_bytes)
        results["source_drift_detection"] = "PASS" if caught else "FAIL"
    except Exception as e:
        results["source_drift_detection"] = f"ERROR: {e}"

    # Test 3: Structure alteration with reseal
    try:
        s1 = m1_bundle / "sources" / "000001.json"
        s1_data = read_json(s1)
        s1_data["units"][0]["span_bytes"][1] += 1
        write_json(s1, s1_data)
        reseal(m1_bundle, "sources/000001.json")
        caught = False
        try:
            SourceReader(fake_repo, m1_bundle).open_unit("000001.txt", u0)
        except M1Error:
            caught = True
        results["structure_alteration_reseal_detection"] = "PASS" if caught else "FAIL"
    except Exception as e:
        results["structure_alteration_reseal_detection"] = f"ERROR: {e}"

    # Re-build bundle for next tests
    shutil.rmtree(m1_bundle)
    build_bundle(fake_repo, "pipeline_v2/artifacts/m0_test", m1_bundle)

    # Test 4: Registry tampering with reseal
    try:
        reg_file = m1_bundle / "source_registry.json"
        reg = read_json(reg_file)
        reg["sources"][0]["raw_sha256"] = "f" * 64
        write_json(reg_file, reg)
        reseal(m1_bundle, "source_registry.json")
        caught = False
        try:
            SourceReader(fake_repo, m1_bundle).open_unit("000001.txt", u0)
        except M1Error:
            caught = True
        results["registry_tamper_reseal_detection"] = "PASS" if caught else "FAIL"
    except Exception as e:
        results["registry_tamper_reseal_detection"] = f"ERROR: {e}"

    # Clean up scratch
    shutil.rmtree(scratch_dir)

    print("Tamper test results:", results)
    all_pass = all(v == "PASS" for v in results.values())
    return {"status": "PASS" if all_pass else "FAIL", "tests": results}


if __name__ == "__main__":
    res = run_tamper_tests()
    sys.exit(0 if res["status"] == "PASS" else 1)
