# Plan10 v16 actual-result accounting and paired-comparison audit

Date: 2026-10-08  
Artifact audited: `outputs/plan10_pair_20261008_142127`  
Scope: local, read-only artifact/code audit. No Modal call and no production-code edit.

## Verdict

**The run is a real 192-attempt incomplete execution, but its reported provider-token accounting is incomplete and its paired-control claim is mislabeled. It is not evidence for a completed P2a/P2b quality comparison.**

The initial concern about protocol failures is confirmed: 25 provider-returned, post-call validation failures are persisted as zero usage. The exact missing provider token total cannot be reconstructed from this artifact because the original successful response receipt/usage was discarded when validation failed.

## Direct artifact facts

| Measure | P2a | P2b | Total |
|---|---:|---:|---:|
| Cached rows / source attempts | 96 | 96 | 192 |
| `protocol_verified` | 8 | 8 | 16 |
| `unresolved` | 88 | 88 | 176 |
| `finish_reason=length` | 76 | 75 | 151 |
| protocol failure with `host_unresolved` | 12 | 13 | 25 |
| persisted provider input tokens | 202,815 | 199,784 | 402,599 |
| persisted provider output tokens | 95,576 | 94,079 | 189,655 |
| persisted provider total tokens | 298,391 | 293,863 | 592,254 |

`recovery_ledger.json` reports 192 provider/source attempts, zero recovery cycles, and no warmup attempts. The preflight reserved 492,493 input and 231,600 output tokens (including bounded retry reservation); runtime reservation records 488,823 input and 230,400 output. Those are reservation envelopes, not a substitute for actual provider usage.

The terminal comparison correctly says `incomplete_output_truncated`, but it understates the distinct protocol-failure population: there are 151 truncations and 25 non-truncation protocol failures.

## Confirmed under-accounting path

In `execute_remote.dispatch`, the provider call succeeds first:

1. `call_modal(...)` returns both parsed result and provider receipt/usage.
2. `validate_response(...)` then raises `BaselineError` for invalid semantic/protocol output.
3. The `BaselineError` handler replaces the receipt with a synthetic `host_unresolved` receipt and defaults usage to zero when the exception has no diagnostic.

All 25 protocol rows in this artifact have exactly that synthetic shape: `failure_class=BaselineError`, diagnostic kind `protocol`, `finish_reason=host_unresolved`, and usage `{0,0,0}`. They are not transport failures: a provider response was obtained before local validation. The 151 `length` rows, in contrast, retain `provider_usage` via their diagnostic and are counted.

Therefore 592,254 is a known lower bound, not actual total provider consumption. The missing amount is not safely inferable from prompt estimates or output caps; those are reservations, not provider-reported usage. Do not retrofit v16 with invented token values or call it a precise cost/token measurement.

## Paired-comparison validity

The paired workload is structurally aligned by `(case_id, batch_id)` and target IDs: 96 target-batch pairs exist in each arm and no target mismatch was found. Outcome coverage by that intended pairing is:

| Pair outcome | Count |
|---|---:|
| verified / verified | 7 |
| verified P2a / unresolved P2b | 1 |
| unresolved P2a / verified P2b | 1 |
| unresolved / unresolved | 87 |

However, **zero of 96 pairs share `region_id` or `render_sha256`**. The code pairs by case/batch, while the artifact declares `same_case_region_pairs=true`. That declaration is false. The arms deliberately/actually receive different rendered regions; the comparison is not a same-input A/B control.

This does not automatically make the study meaningless if the intended independent variable is the region/context selection policy: same case, target batch, model/schema/caps, and target IDs provide a legitimate *paired target-batch* design. But it must be reported as a comparison of two different context regions, not “same case-region pairs.” Any causal claim beyond that needs the treatment definition and substantially more than seven jointly verified pairs.

With only 7/96 jointly protocol-verified pairs and 87/96 jointly unresolved, no meaningful P2a-versus-P2b semantic, retrieval, or cost-quality conclusion is supported. Even a simple success-rate comparison is constrained by non-random failures dominated by output truncation.

## Required accounting repair and re-audit criteria

For a future execution, retain the safe provider receipt fields (`usage`, finish reason, latency, safe response hash/length) when `validate_response` fails after `call_modal`. Label it `provider_call_succeeded_protocol_invalid` (or equivalent), rather than `host_unresolved`. Keep raw content excluded. A true transport/HTTP failure with no provider usage remains `usage_unavailable`, not zero actual usage.

Tests must prove:

1. a provider response that fails `validate_response` preserves its provider usage and non-transport finish reason;
2. HTTP/transport failures remain explicitly usage-unavailable without inventing zero consumption;
3. `_account` reports known usage separately from unavailable usage/attempt counts; and
4. `remote_comparison` labels pairing as same case/batch/targets with different region inputs, or validates same regions if that stronger design is actually intended.

The accounting fix cannot repair v16's unknown 25 receipts retroactively. A re-audit can verify the code/test contract and future artifacts; it cannot turn this artifact into exact provider-usage evidence.
