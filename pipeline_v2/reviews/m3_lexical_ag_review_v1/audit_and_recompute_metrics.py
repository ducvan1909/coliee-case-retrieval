"""Independent audit and recomputation of all M3 lexical reader metrics, hashes, and benchmark results."""
import json
import math
from pathlib import Path
import statistics
import time

from pipeline_v2.full_corpus.common import implementation as full_implementation
from pipeline_v2.full_corpus.common import load_profile as load_full_profile
from pipeline_v2.full_corpus.common import validate_seal as validate_full_seal
from pipeline_v2.full_search.lexical import implementation as lexical_implementation
from pipeline_v2.full_search.lexical import load_profile as load_lexical_profile
from pipeline_v2.optimization_v2.common import file_digest, read
from pipeline_v2.source.core import canonical, digest

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def audit_fingerprints_and_immutability() -> dict:
    prior_state = read(ROOT / "pipeline_v2/reviews/m3_lexical_validation_v1/prior_state.json")
    current_full_impl = full_implementation()
    current_full_agg = digest(canonical(current_full_impl))
    assert current_full_impl == prior_state["full_implementation"], "Full implementation drifted from prior_state.json"
    assert current_full_agg == prior_state["aggregate"], "Full aggregate hash drifted"

    lex_impl = lexical_implementation()
    lex_agg = digest(canonical(lex_impl))
    assert lex_agg == "3633aa881ef8ff7f739a87c5c174b00faff82f59f656466a70d3804f7c0856bf", (
        f"Unexpected lexical implementation hash: {lex_agg}"
    )

    lex_profile = load_lexical_profile(ROOT)
    lex_profile_sha256 = file_digest(ROOT / "pipeline_v2/configs/m3_lexical.json")
    full_profile = load_full_profile(ROOT)
    full_profile_sha256 = file_digest(ROOT / "pipeline_v2/configs/m3_full.json")

    full_run_dir = ROOT / lex_profile["full_run"]
    full_seal = read(full_run_dir / "seal.json")
    full_manifest_sha256 = file_digest(full_run_dir / "manifest.json")
    full_seal_sha256 = file_digest(full_run_dir / "seal.json")
    sqlite_stat = (full_run_dir / "lexical.sqlite3").stat()
    assert full_seal["manifest.json"] == {
        "sha256": full_manifest_sha256,
        "bytes": (full_run_dir / "manifest.json").stat().st_size,
    }
    assert full_seal["lexical.sqlite3"]["bytes"] == sqlite_stat.st_size

    # Also check pilot artifacts remain untouched
    pilot_v2_dir = ROOT / "pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1"
    pilot_v2_seal = read(pilot_v2_dir / "seal.json")["files"]
    for fname, entry in pilot_v2_seal.items():
        p = pilot_v2_dir / fname
        assert p.stat().st_size == entry["byte_length"], f"Pilot V2 size drift on {fname}"
        assert file_digest(p) == entry["sha256"], f"Pilot V2 hash drift on {fname}"

    return {
        "prior_state_full_implementation_matches": True,
        "full_implementation_aggregate_sha256": current_full_agg,
        "lexical_implementation_files": lex_impl,
        "lexical_implementation_aggregate_sha256": lex_agg,
        "lexical_profile": lex_profile,
        "lexical_profile_sha256": lex_profile_sha256,
        "full_profile_sha256": full_profile_sha256,
        "full_run_manifest_sha256": full_manifest_sha256,
        "full_run_seal_sha256": full_seal_sha256,
        "full_run_lexical_sqlite_seal_entry": full_seal["lexical.sqlite3"],
        "pilot_v2_seal_intact": True,
    }


def recompute_main_actual_benchmark() -> dict:
    bench = read(ROOT / "pipeline_v2/reviews/m3_lexical_validation_v1/actual_benchmark.json")
    rows = bench["rows"]
    assert len(rows) == 16

    recomputed = {}
    for kind in ("case", "passage"):
        krows = [r for r in rows if r["kind"] == kind]
        assert len(krows) == 8
        assert all(r["ranked_ids_exact"] is True for r in krows)
        assert all(r["hits"] == 4096 for r in krows)
        max_diff = max(r["max_abs_score_diff"] for r in krows)
        assert max_diff == 0.0

        scal_all = [r["seconds"]["scalar"] for r in krows]
        vec_all = [r["seconds"]["vectorized"] for r in krows]
        rep_all = [r["vectorized_repeat_seconds"] for r in krows]

        # Separate by execution order (which ran 1st vs 2nd in the pair)
        vec_first_rows = [r for r in krows if r["execution_order"][0] == "vectorized"]
        scal_first_rows = [r for r in krows if r["execution_order"][0] == "scalar"]

        first_call_regardless_of_method = [
            r["seconds"][r["execution_order"][0]] for r in krows
        ]
        second_call_regardless_of_method = [
            r["seconds"][r["execution_order"][1]] for r in krows
        ]

        recomputed[kind] = {
            "queries_count": len(krows),
            "all_ranked_ids_exact": True,
            "max_abs_score_diff": max_diff,
            "scalar_median_seconds": statistics.median(scal_all),
            "scalar_min_seconds": min(scal_all),
            "scalar_max_seconds": max(scal_all),
            "vectorized_median_seconds": statistics.median(vec_all),
            "vectorized_min_seconds": min(vec_all),
            "vectorized_max_seconds": max(vec_all),
            "vectorized_repeat_median_seconds": statistics.median(rep_all),
            "vectorized_repeat_min_seconds": min(rep_all),
            "vectorized_repeat_max_seconds": max(rep_all),
            "matches_reported_summary": (
                math.isclose(statistics.median(scal_all), bench["summary"][kind]["scalar_median_seconds"], rel_tol=0, abs_tol=1e-15)
                and math.isclose(statistics.median(vec_all), bench["summary"][kind]["vectorized_median_seconds"], rel_tol=0, abs_tol=1e-15)
                and math.isclose(statistics.median(rep_all), bench["summary"][kind]["vectorized_repeat_median_seconds"], rel_tol=0, abs_tol=1e-15)
            ),
            "execution_order_analysis": {
                "vectorized_ran_first_count": len(vec_first_rows),
                "vectorized_ran_first_queries": [r["query_id"] for r in vec_first_rows],
                "scalar_ran_first_count": len(scal_first_rows),
                "scalar_ran_first_queries": [r["query_id"] for r in scal_first_rows],
                "when_vectorized_ran_first_cold": {
                    "vectorized_1st_median_s": statistics.median(r["seconds"]["vectorized"] for r in vec_first_rows),
                    "scalar_2nd_warm_median_s": statistics.median(r["seconds"]["scalar"] for r in vec_first_rows),
                    "vectorized_3rd_repeat_median_s": statistics.median(r["vectorized_repeat_seconds"] for r in vec_first_rows),
                },
                "when_scalar_ran_first_cold": {
                    "scalar_1st_median_s": statistics.median(r["seconds"]["scalar"] for r in scal_first_rows),
                    "vectorized_2nd_warm_median_s": statistics.median(r["seconds"]["vectorized"] for r in scal_first_rows),
                    "vectorized_3rd_repeat_median_s": statistics.median(r["vectorized_repeat_seconds"] for r in scal_first_rows),
                },
                "position_1st_any_method_median_s": statistics.median(first_call_regardless_of_method),
                "position_2nd_any_method_median_s": statistics.median(second_call_regardless_of_method),
            },
        }

    return {
        "status": bench["status"],
        "startup_seconds": bench["startup_seconds"],
        "scalar_preload_seconds": bench["scalar_preload_seconds"],
        "elapsed_seconds": bench["elapsed_seconds"],
        "implementation_sha256": bench["implementation_sha256"],
        "channels": recomputed,
    }


def main():
    fingerprints = audit_fingerprints_and_immutability()
    main_bench = recompute_main_actual_benchmark()
    ind_tests = read(HERE / "independent_test_results.json")
    bounded_bench = read(HERE / "bounded_benchmark_results.json")

    out = {
        "schema_version": "ag-m3-lexical-recomputed-metrics-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fingerprints_and_immutability": fingerprints,
        "main_actual_benchmark_recomputed": main_bench,
        "independent_unit_tests_summary": ind_tests,
        "ag_bounded_benchmark_summary": {
            "total_elapsed_seconds": bounded_bench["total_elapsed_seconds"],
            "memory_and_pragma_audit": bounded_bench["part_a_memory_and_pragma_audit"],
            "standalone_cli_verification": bounded_bench["part_b_standalone_cli_verification"],
            "stage_decomposed_8_query_summary": {
                "session_open_seconds": bounded_bench["part_c_stage_decomposed_8_query_benchmark"]["session_open_seconds"],
                "session_initialization_seconds": bounded_bench["part_c_stage_decomposed_8_query_benchmark"]["session_initialization_seconds"],
                "reader_preload_seconds": bounded_bench["part_c_stage_decomposed_8_query_benchmark"]["reader_preload_seconds"],
                "single_guard_seconds": bounded_bench["part_c_stage_decomposed_8_query_benchmark"]["single_guard_seconds"],
                "explicit_revalidate_seconds": bounded_bench["part_c_stage_decomposed_8_query_benchmark"]["explicit_revalidate_seconds"],
                "summary_by_channel": bounded_bench["part_c_stage_decomposed_8_query_benchmark"]["summary_by_channel"],
            },
        },
    }
    out_path = HERE / "recomputed_metrics.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Saved recomputed metrics to {out_path}")


if __name__ == "__main__":
    main()
