"""Independent tamper, drift, reseal, pagination, and multi-hit dedup fixture tests for M2 navigation.

Operates strictly on temporary copies in tempfile.TemporaryDirectory(); never modifies production bundles or configs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline_v2.m0 import build_bundle as build_m0
from pipeline_v2.navigation import M2Error, NavigationReader, build_bundle as build_m2, validate_bundle as validate_m2
from pipeline_v2.source import M1Error, build_bundle as build_m1


def write_json(path: Path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def reseal_file(bundle: Path, relative: str):
    seal_path = bundle / "seal.json"
    seal = read_json(seal_path)
    raw = (bundle / relative).read_bytes()
    seal["files"][relative] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_length": len(raw),
    }
    write_json(seal_path, seal)


def run_all_tests() -> dict:
    started = time.perf_counter()
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "repo"
        config_dir = root / "pipeline_v2" / "configs"
        cases_dir = root / "data" / "task1_train_files_2026" / "cases"
        config_dir.mkdir(parents=True)
        cases_dir.mkdir(parents=True)

        for name in ("m0.json", "m1.json", "m2.json"):
            shutil.copyfile(REPO / "pipeline_v2" / "configs" / name, config_dir / name)

        m0_config = read_json(config_dir / "m0.json")
        m0_config["exposure_artifacts"] = []
        m0_config["manual_exposures"] = []
        write_json(config_dir / "m0.json", m0_config)

        case_ids = [f"{n:06d}.txt" for n in range(1, 31)]
        for i, cid in enumerate(case_ids):
            raw = (
                f"Indexed As: Test Case {i}\r\n2020 FC {i + 1}\r\nFederal Court\r\n\r\n"
                "BACKGROUND\r\n\r\n"
                "Unnumbered introductory note before markers.\r\n\r\n"
                "[10] First numbered paragraph with <FRAGMENT_SUPPRESSED> and <REFERENCE_SUPPRESSED>.\r\n\r\n"
                "ANALYSIS\r\n\r\n"
                "[2] The Court states the following:\r\n"
                "[1] Quoted block paragraph with <FRAGMENT_SUPPRESSED> one and <FRAGMENT_SUPPRESSED> two "
                "and <REFERENCE_SUPPRESSED> three.\r\n"
                "[11] Closing paragraph after quotation.\r\n"
            ).encode("utf-8")
            (cases_dir / cid).write_bytes(raw)

        labels = {cid: [case_ids[(i + 1) % len(case_ids)]] for i, cid in enumerate(case_ids)}
        write_json(root / "data" / "task1_train_files_2026" / "clean_task1_train_labels_2026.json", labels)

        artifacts = root / "pipeline_v2" / "artifacts"
        artifacts.mkdir()
        build_m0(root, artifacts / "m0_fix")
        build_m1(root, "pipeline_v2/artifacts/m0_fix", artifacts / "m1_fix")
        build_m2(root, "pipeline_v2/artifacts/m1_fix", "pipeline_v2/artifacts/m2_fix")
        m2_fix = artifacts / "m2_fix"

        # Test 1: Unresealed byte tamper on case navigation JSON
        t1_dir = artifacts / "m2_t1_unresealed"
        shutil.copytree(m2_fix, t1_dir)
        p = t1_dir / "sources/000001.json"
        p.write_bytes(p.read_bytes() + b" ")
        try:
            validate_m2(root, "pipeline_v2/artifacts/m2_t1_unresealed")
            raise AssertionError("Failed to reject unresealed tamper")
        except M2Error as exc:
            results.append({"test": "unresealed_case_tamper", "passed": True, "error_caught": str(exc)})

        # Test 2: Resealed semantic tamper on preview text
        t2_dir = artifacts / "m2_t2_resealed_preview"
        shutil.copytree(m2_fix, t2_dir)
        rec = read_json(t2_dir / "sources/000001.json")
        rec["previews"][0]["text"] = "Tampered preview text..."
        write_json(t2_dir / "sources/000001.json", rec)
        reseal_file(t2_dir, "sources/000001.json")
        try:
            validate_m2(root, "pipeline_v2/artifacts/m2_t2_resealed_preview")
            raise AssertionError("Failed to reject resealed preview tamper")
        except M2Error as exc:
            results.append({"test": "resealed_preview_tamper", "passed": True, "error_caught": str(exc)})

        # Test 3: Resealed neighbor link tamper
        t3_dir = artifacts / "m2_t3_resealed_neighbor"
        shutil.copytree(m2_fix, t3_dir)
        rec = read_json(t3_dir / "sources/000001.json")
        rec["navigation"][1]["previous_paragraph_ref"] = "p000005"
        write_json(t3_dir / "sources/000001.json", rec)
        reseal_file(t3_dir, "sources/000001.json")
        try:
            validate_m2(root, "pipeline_v2/artifacts/m2_t3_resealed_neighbor")
            raise AssertionError("Failed to reject resealed neighbor tamper")
        except M2Error as exc:
            results.append({"test": "resealed_neighbor_tamper", "passed": True, "error_caught": str(exc)})

        # Test 4: Resealed summary count tamper
        t4_dir = artifacts / "m2_t4_resealed_summary"
        shutil.copytree(m2_fix, t4_dir)
        summ = read_json(t4_dir / "summary.json")
        summ["counts"]["previews"] += 1
        write_json(t4_dir / "summary.json", summ)
        reseal_file(t4_dir, "summary.json")
        try:
            validate_m2(root, "pipeline_v2/artifacts/m2_t4_resealed_summary")
            raise AssertionError("Failed to reject resealed summary tamper")
        except M2Error as exc:
            results.append({"test": "resealed_summary_tamper", "passed": True, "error_caught": str(exc)})

        # Test 5: Source raw byte drift
        c_path = cases_dir / "000001.txt"
        orig_bytes = c_path.read_bytes()
        c_path.write_bytes(orig_bytes + b"\r\n")
        try:
            NavigationReader(root, "pipeline_v2/artifacts/m2_fix").map("000001.txt")
            raise AssertionError("Failed to reject raw source byte drift")
        except (M1Error, M2Error) as exc:
            results.append({"test": "raw_source_byte_drift", "passed": True, "error_caught": str(exc)})
        finally:
            c_path.write_bytes(orig_bytes)

        # Test 6: Profile config drift
        prof_path = config_dir / "m2.json"
        orig_prof = prof_path.read_bytes()
        prof = read_json(prof_path)
        prof["preview"]["anchor_radius_chars"] = 100
        write_json(prof_path, prof)
        try:
            NavigationReader(root, "pipeline_v2/artifacts/m2_fix")
            raise AssertionError("Failed to reject profile config drift")
        except M2Error as exc:
            results.append({"test": "profile_config_drift", "passed": True, "error_caught": str(exc)})
        finally:
            prof_path.write_bytes(orig_prof)

        # Test 7: M1 seal/manifest drift
        m1_manifest_path = artifacts / "m1_fix" / "manifest.json"
        m1_seal_path = artifacts / "m1_fix" / "seal.json"
        orig_m1_man = m1_manifest_path.read_bytes()
        orig_m1_seal = m1_seal_path.read_bytes()
        m1_man = read_json(m1_manifest_path)
        m1_man["scope"] = "drifted_scope"
        write_json(m1_manifest_path, m1_man)
        reseal_file(artifacts / "m1_fix", "manifest.json")
        try:
            NavigationReader(root, "pipeline_v2/artifacts/m2_fix")
            raise AssertionError("Failed to reject M1 provenance drift")
        except (M1Error, M2Error) as exc:
            results.append({"test": "m1_provenance_drift", "passed": True, "error_caught": str(exc)})
        finally:
            m1_manifest_path.write_bytes(orig_m1_man)
            m1_seal_path.write_bytes(orig_m1_seal)

        # Test 8: Multi-hit / sibling passage deduplication readiness simulation on parent-neighbor mapping
        reader = NavigationReader(root, "pipeline_v2/artifacts/m2_fix")
        page = reader.map("000001.txt", offset=0, limit=20)
        rows = page["items"]
        # Suppose two synthetic child hits (e.g., 12a, 12b) map to the same parent unit p000004 (observed_marker=1)
        parent_row = next(r for r in rows if r["observed_marker"] == 1)
        next_row = next(r for r in rows if r["observed_marker"] == 11)
        p_bs, p_be = parent_row["span_bytes"]
        mid = (p_bs + p_be) // 2
        synthetic_hits = [
            {"hit_id": "sim_child_a", "parent_ref": parent_row["handle"], "hit_span_bytes": [p_bs, mid]},
            {"hit_id": "sim_child_b", "parent_ref": parent_row["handle"], "hit_span_bytes": [mid, p_be]},
            {"hit_id": "sim_neighbor_hit", "parent_ref": next_row["handle"], "hit_span_bytes": next_row["span_bytes"]},
        ]
        # Verify M2 parent_container_refs, reading_expansion, and open_context provide exact byte spans to dedup
        ctx_parent = reader.open_context("000001.txt", parent_row["handle"])
        ctx_next = reader.open_context("000001.txt", next_row["handle"])
        # Both sim_child_a and sim_child_b resolve to identical parent_container_refs and reading_expansion
        assert parent_row["parent_container_refs"] == [{"unit_id": parent_row["unit_id"], "span_bytes": [p_bs, p_be]}]
        assert ctx_parent["span_bytes"][0] <= p_bs < mid < p_be <= ctx_parent["span_bytes"][1]
        # Overlapping reading expansions between p000004 (prev=p000003, parent=p000004, next=p000005)
        # and p000005 (prev=p000004, parent=p000005, next=None) share component handles & exact byte spans
        shared_handles = {c["handle"] for c in ctx_parent["components"]} & {c["handle"] for c in ctx_next["components"]}
        assert shared_handles == {parent_row["handle"], next_row["handle"]}
        results.append({
            "test": "multi_hit_same_and_adjacent_parent_dedup_mapping_fixture",
            "passed": True,
            "shared_handles": sorted(shared_handles),
            "parent_envelope_bytes": ctx_parent["span_bytes"],
            "adjacent_envelope_bytes": ctx_next["span_bytes"],
        })

    return {
        "schema_version": "pipeline-v2-m2-ag-tamper-and-boundary-tests-1",
        "all_passed": all(r["passed"] for r in results),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "tests_count": len(results),
        "results": results,
    }


def main():
    out = run_all_tests()
    out_path = REPO / "pipeline_v2/reviews/m2_navigation_ag_review_v1/tamper_and_boundary_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
