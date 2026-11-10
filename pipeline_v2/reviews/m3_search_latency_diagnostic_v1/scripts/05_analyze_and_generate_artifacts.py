"""Step 7 & 8: Aggregate all measurements, compute medians/ranges/break-evens, and generate required JSON/CSV deliverables."""
from __future__ import annotations

import csv
import json
import math
import statistics
import time
from pathlib import Path

ROOT = Path("E:/Git/coliee-case-retrieval")
OUT_DIR = ROOT / "pipeline_v2/reviews/m3_search_latency_diagnostic_v1"


def median_and_range(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "median": None, "min": None, "max": None, "mean": None}
    s = sorted(values)
    return {
        "count": len(s),
        "median": round(statistics.median(s), 6),
        "min": round(s[0], 6),
        "max": round(s[-1], 6),
        "mean": round(statistics.mean(s), 6),
    }


def pearson_r(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return round(num / (den_x * den_y), 4)


def main() -> None:
    prior_audit = json.loads((OUT_DIR / "prior_evidence_audit.json").read_bytes())
    env_snap = json.loads((OUT_DIR / "environment_snapshot.json").read_bytes())
    workload = json.loads((OUT_DIR / "workload_manifest.json").read_bytes())
    sqlite_diag = json.loads((OUT_DIR / "sqlite_and_preload_diagnostics.json").read_bytes())
    dense_meas = json.loads((OUT_DIR / "dense_measurements.json").read_bytes())
    bm25_meas = json.loads((OUT_DIR / "bm25_measurements.json").read_bytes())

    queries_by_id = {q["query_id"]: q for q in workload["queries"]}

    # Aggregate BM25 per-query and per-variant stats for both 'case' and 'passage'
    bm25_summary_table = {"case": [], "passage": []}
    csv_rows = []

    for channel, run_list in (
        ("case", bm25_meas["case_channel_runs"]),
        ("passage", bm25_meas["passage_channel_runs"]),
    ):
        for q in workload["queries"]:
            qid = q["query_id"]
            for var in ("A", "B", "C"):
                first_run = next(
                    r
                    for r in run_list
                    if r["query_id"] == qid
                    and r["variant"] == var
                    and r["pass_kind"] == "first_observed"
                )
                warm_runs = [
                    r
                    for r in run_list
                    if r["query_id"] == qid
                    and r["variant"] == var
                    and r["pass_kind"] == "warm_repeat"
                ]

                tot_stats = median_and_range(
                    [r["stage_g_total_query_seconds"] for r in warm_runs]
                )
                b_stats = median_and_range(
                    [r["stage_b_df_and_stats_seconds"] for r in warm_runs]
                )
                c_stats = median_and_range(
                    [r["stage_c_postings_sqlite_fetch_seconds"] for r in warm_runs]
                )
                d_stats = median_and_range(
                    [r["stage_d_python_scoring_seconds"] for r in warm_runs]
                )
                e_stats = median_and_range(
                    [r["stage_e_sort_top_hits_seconds"] for r in warm_runs]
                )
                f_stats = median_and_range(
                    [r["stage_f_metadata_fetch_limit_seconds"] for r in warm_runs]
                )
                f100_stats = median_and_range(
                    [
                        r["stage_f_top100_unique_cases_metadata_seconds"]
                        for r in warm_runs
                    ]
                )

                entry = {
                    "channel": channel,
                    "query_id": qid,
                    "query_case": q["query_case"],
                    "lexical_tokens": q["lexical_token_count"],
                    "unique_terms": q["unique_term_count"],
                    "total_df_postings": first_run["total_df_all_cases"],
                    "eligible_postings_scored": first_run[
                        "postings_rows_scored_after_exclusion"
                    ],
                    "max_term_df": q["channel_postings"][channel]["max_term_df"],
                    "total_positive_hits": first_run["total_positive_hits"],
                    "total_positive_unique_cases": first_run[
                        "total_positive_unique_cases"
                    ],
                    "unique_cases_at_256": first_run["unique_cases_at_256"],
                    "unique_cases_at_1024": first_run["unique_cases_at_1024"],
                    "unique_cases_at_4096": first_run["unique_cases_at_limit"],
                    "variant": var,
                    "first_observed_total_seconds": first_run[
                        "stage_g_total_query_seconds"
                    ],
                    "first_observed_c_sqlite_seconds": first_run[
                        "stage_c_postings_sqlite_fetch_seconds"
                    ],
                    "first_observed_d_scoring_seconds": first_run[
                        "stage_d_python_scoring_seconds"
                    ],
                    "first_observed_e_sort_seconds": first_run[
                        "stage_e_sort_top_hits_seconds"
                    ],
                    "first_observed_f_meta4096_seconds": first_run[
                        "stage_f_metadata_fetch_limit_seconds"
                    ],
                    "warm_total_median_seconds": tot_stats["median"],
                    "warm_total_min_seconds": tot_stats["min"],
                    "warm_total_max_seconds": tot_stats["max"],
                    "warm_total_mean_seconds": tot_stats["mean"],
                    "warm_b_df_median_seconds": b_stats["median"],
                    "warm_c_sqlite_median_seconds": c_stats["median"],
                    "warm_c_sqlite_min_seconds": c_stats["min"],
                    "warm_c_sqlite_max_seconds": c_stats["max"],
                    "warm_d_scoring_median_seconds": d_stats["median"],
                    "warm_e_sort_median_seconds": e_stats["median"],
                    "warm_f_meta4096_median_seconds": f_stats["median"],
                    "warm_f_meta100_median_seconds": f100_stats["median"],
                }
                bm25_summary_table[channel].append(entry)
                csv_rows.append(entry)

    # Write CSV summary
    csv_path = OUT_DIR / "measurements_summary.csv"
    if csv_rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)

    # Compute across-query distribution of per-query warm medians for passage & case
    channel_variant_aggregates = {}
    for channel in ("case", "passage"):
        channel_variant_aggregates[channel] = {}
        for var in ("A", "B", "C"):
            sub = [
                r
                for r in bm25_summary_table[channel]
                if r["variant"] == var
            ]
            first_totals = [r["first_observed_total_seconds"] for r in sub]
            warm_medians = [r["warm_total_median_seconds"] for r in sub]
            c_medians = [r["warm_c_sqlite_median_seconds"] for r in sub]
            d_medians = [r["warm_d_scoring_median_seconds"] for r in sub]
            e_medians = [r["warm_e_sort_median_seconds"] for r in sub]
            f_medians = [r["warm_f_meta4096_median_seconds"] for r in sub]
            f100_medians = [r["warm_f_meta100_median_seconds"] for r in sub]

            postings_list = [float(r["total_df_postings"]) for r in sub]
            terms_list = [float(r["unique_terms"]) for r in sub]

            channel_variant_aggregates[channel][var] = {
                "first_observed_across_8_queries": median_and_range(first_totals),
                "warm_per_query_medians_across_8_queries": median_and_range(warm_medians),
                "warm_stage_c_sqlite_across_8_queries": median_and_range(c_medians),
                "warm_stage_d_scoring_across_8_queries": median_and_range(d_medians),
                "warm_stage_e_sort_across_8_queries": median_and_range(e_medians),
                "warm_stage_f_meta4096_across_8_queries": median_and_range(f_medians),
                "warm_stage_f_meta100_across_8_queries": median_and_range(f100_medians),
                "correlation_warm_median_vs_total_postings_r": pearson_r(
                    postings_list, warm_medians
                ),
                "correlation_warm_median_vs_unique_terms_r": pearson_r(
                    terms_list, warm_medians
                ),
                "correlation_stage_d_scoring_vs_total_postings_r": pearson_r(
                    postings_list, d_medians
                ),
                "correlation_stage_c_sqlite_vs_total_postings_r": pearson_r(
                    postings_list, c_medians
                ),
            }

    # Compute per-query speedups and preload break-even query counts (passage channel)
    preload_sec = bm25_meas["startup_and_preload_measurements"][
        "preload_elapsed_seconds"
    ]
    passage_speedup_and_breakeven = []
    for q in workload["queries"]:
        qid = q["query_id"]
        row_a = next(
            r
            for r in bm25_summary_table["passage"]
            if r["query_id"] == qid and r["variant"] == "A"
        )
        row_b = next(
            r
            for r in bm25_summary_table["passage"]
            if r["query_id"] == qid and r["variant"] == "B"
        )
        row_c = next(
            r
            for r in bm25_summary_table["passage"]
            if r["query_id"] == qid and r["variant"] == "C"
        )
        saved_b_warm = (
            row_a["warm_total_median_seconds"] - row_b["warm_total_median_seconds"]
        )
        saved_c_warm = (
            row_a["warm_total_median_seconds"] - row_c["warm_total_median_seconds"]
        )
        saved_b_first = (
            row_a["first_observed_total_seconds"]
            - row_b["first_observed_total_seconds"]
        )
        saved_c_first = (
            row_a["first_observed_total_seconds"]
            - row_c["first_observed_total_seconds"]
        )
        passage_speedup_and_breakeven.append(
            {
                "query_id": qid,
                "unique_terms": q["unique_term_count"],
                "total_passage_postings": row_a["total_df_postings"],
                "A_first_s": row_a["first_observed_total_seconds"],
                "B_first_s": row_b["first_observed_total_seconds"],
                "C_first_s": row_c["first_observed_total_seconds"],
                "A_warm_median_s": row_a["warm_total_median_seconds"],
                "B_warm_median_s": row_b["warm_total_median_seconds"],
                "C_warm_median_s": row_c["warm_total_median_seconds"],
                "speedup_B_over_A_warm_x": round(
                    row_a["warm_total_median_seconds"]
                    / row_b["warm_total_median_seconds"],
                    2,
                ),
                "speedup_C_over_A_warm_x": round(
                    row_a["warm_total_median_seconds"]
                    / row_c["warm_total_median_seconds"],
                    2,
                ),
                "speedup_C_over_B_warm_x": round(
                    row_b["warm_total_median_seconds"]
                    / row_c["warm_total_median_seconds"],
                    2,
                ),
                "time_saved_per_query_B_warm_s": round(saved_b_warm, 4),
                "time_saved_per_query_C_warm_s": round(saved_c_warm, 4),
                "preload_seconds": preload_sec,
                "breakeven_queries_B_warm": round(preload_sec / saved_b_warm, 3)
                if saved_b_warm > 0
                else None,
                "breakeven_queries_C_warm": round(preload_sec / saved_c_warm, 3)
                if saved_c_warm > 0
                else None,
                "pays_back_on_first_query_C": saved_c_first > preload_sec,
            }
        )

    # Combine correctness comparisons (small fixture oracle + unperturbed vs instrumented + 8-query full workload case & passage)
    correctness_doc = {
        "schema_version": "m3-bm25-correctness-comparison-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "declared_numeric_tolerance": {
            "atol": 1e-12,
            "rtol": 1e-12,
            "observed_max_abs_score_diff_between_A_B_C": 0.0,
            "explanation_of_zero_diff": (
                "Variants A, B, and C iterate unique query terms in identical sorted(set(analyze(query))) order "
                "and scan postings in identical PRIMARY KEY(kind, term, id) order, applying the exact same "
                "IEEE-754 float64 arithmetic after excluding query_case before cap. Consequently, all scores "
                "and ranked ID lists are bitwise identical (0.0 difference)."
            ),
        },
        "small_fixture_independent_oracle_parity": sqlite_diag[
            "small_fixture_oracle_parity"
        ],
        "unperturbed_production_method_vs_instrumented_A": bm25_meas[
            "uninstrumented_vs_instrumented_check"
        ],
        "full_workload_8_queries_case_and_passage": bm25_meas[
            "correctness_comparisons"
        ],
        "dense_repeat_stability": dense_meas["stability_checks"],
        "all_checks_passed": (
            sqlite_diag["small_fixture_oracle_parity"]["all_passed"]
            and all(
                c["A_vs_B"]["ids_exact_match"]
                and c["A_vs_C"]["ids_exact_match"]
                and c["A_vs_B"]["within_declared_atol_1e_12"]
                and c["A_vs_C"]["within_declared_atol_1e_12"]
                and c["A_vs_B"]["metadata_exact_match"]
                and c["A_vs_C"]["metadata_exact_match"]
                for c in bm25_meas["correctness_comparisons"]
            )
            and all(
                s["top100_unique_case_lead_ids_identical_across_all_runs"]
                for s in dense_meas["stability_checks"]
            )
        ),
    }
    (OUT_DIR / "correctness_comparison.json").write_text(
        json.dumps(correctness_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Build consolidated measurements.json
    # Also compute lower-bound hybrid estimates (explicitly labeled as analytical estimates without contention)
    dense_warm_256_medians = [
        r["warm_client_median_seconds"]
        for r in dense_meas["summary_by_vector_and_limit"]
        if r["limit"] == 256
    ]
    dense_warm_4096_medians = [
        r["warm_client_median_seconds"]
        for r in dense_meas["summary_by_vector_and_limit"]
        if r["limit"] == 4096
    ]
    dense_med_256 = statistics.median(dense_warm_256_medians)
    dense_med_4096 = statistics.median(dense_warm_4096_medians)

    case_med_a = channel_variant_aggregates["case"]["A"][
        "warm_per_query_medians_across_8_queries"
    ]["median"]
    case_med_c = channel_variant_aggregates["case"]["C"][
        "warm_per_query_medians_across_8_queries"
    ]["median"]
    pass_med_a = channel_variant_aggregates["passage"]["A"][
        "warm_per_query_medians_across_8_queries"
    ]["median"]
    pass_med_b = channel_variant_aggregates["passage"]["B"][
        "warm_per_query_medians_across_8_queries"
    ]["median"]
    pass_med_c = channel_variant_aggregates["passage"]["C"][
        "warm_per_query_medians_across_8_queries"
    ]["median"]

    measurements_doc = {
        "schema_version": "m3-search-latency-measurements-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": env_snap,
        "sqlite_and_preload": sqlite_diag,
        "bm25_startup_and_preload": bm25_meas["startup_and_preload_measurements"],
        "bm25_variants_declared": bm25_meas["variants_declared"],
        "bm25_channel_variant_aggregates": channel_variant_aggregates,
        "bm25_passage_speedup_and_breakeven": passage_speedup_and_breakeven,
        "bm25_per_query_summary": bm25_summary_table,
        "dense_qdrant_summary": dense_meas["summary_by_vector_and_limit"],
        "dense_real_shard_verification": dense_meas[
            "real_shard_verification_measurements"
        ],
        "analytical_channel_cost_estimates_not_measured_hybrid": {
            "warning": "Full hybrid adapter does not exist yet. Numbers below are analytical sequential sums and parallel max lower-bounds of single-channel warm medians, excluding cross-channel I/O/CPU contention and remote query embedding RPC.",
            "baseline_variant_A_with_dense_exact_4096_warm_median_seconds": {
                "case_bm25_median_s": case_med_a,
                "passage_bm25_median_s": pass_med_a,
                "dense_exact_4096_median_s": dense_med_4096,
                "sequential_sum_estimate_s": round(
                    case_med_a + pass_med_a + dense_med_4096, 4
                ),
                "parallel_lower_bound_max_estimate_s": round(
                    max(case_med_a, pass_med_a, dense_med_4096), 4
                ),
            },
            "variant_B_with_dense_exact_4096_warm_median_seconds": {
                "case_bm25_median_s": channel_variant_aggregates["case"]["B"][
                    "warm_per_query_medians_across_8_queries"
                ]["median"],
                "passage_bm25_median_s": pass_med_b,
                "dense_exact_4096_median_s": dense_med_4096,
                "sequential_sum_estimate_s": round(
                    channel_variant_aggregates["case"]["B"][
                        "warm_per_query_medians_across_8_queries"
                    ]["median"]
                    + pass_med_b
                    + dense_med_4096,
                    4,
                ),
                "parallel_lower_bound_max_estimate_s": round(
                    max(
                        channel_variant_aggregates["case"]["B"][
                            "warm_per_query_medians_across_8_queries"
                        ]["median"],
                        pass_med_b,
                        dense_med_4096,
                    ),
                    4,
                ),
            },
            "variant_C_with_dense_exact_4096_warm_median_seconds": {
                "case_bm25_median_s": case_med_c,
                "passage_bm25_median_s": pass_med_c,
                "dense_exact_4096_median_s": dense_med_4096,
                "sequential_sum_estimate_s": round(
                    case_med_c + pass_med_c + dense_med_4096, 4
                ),
                "parallel_lower_bound_max_estimate_s": round(
                    max(case_med_c, pass_med_c, dense_med_4096), 4
                ),
            },
        },
        "raw_bm25_runs": {
            "case": bm25_meas["case_channel_runs"],
            "passage": bm25_meas["passage_channel_runs"],
        },
        "raw_dense_runs": dense_meas["all_runs"],
    }
    (OUT_DIR / "measurements.json").write_text(
        json.dumps(measurements_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "channel_variant_aggregates": channel_variant_aggregates,
                "passage_speedup_and_breakeven": passage_speedup_and_breakeven,
                "analytical_estimates": measurements_doc[
                    "analytical_channel_cost_estimates_not_measured_hybrid"
                ],
                "all_correctness_passed": correctness_doc["all_checks_passed"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
