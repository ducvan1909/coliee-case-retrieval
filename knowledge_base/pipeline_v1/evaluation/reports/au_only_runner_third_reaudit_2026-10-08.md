# AU-only runner third re-audit

Date: 2026-10-08  
Scope: current source, focused tests, and local fake-provider probes. No Modal call and no runtime edit.  
Verdict: **FAIL — original P0s are repaired, but a newly introduced cache-key shadowing defect breaks cache/resume after any known-usage provider call.**

## Confirmed repairs

* No runtime imports from `au_baseline`, Plan07, `analysis_regions`, P2a/P2b, or ContextHint remain in `au_only`.
* `preflight` now rejects `len(requests) > max_provider_attempts` with `provider_attempt_cap`.
* `_validate_response` now iterates actual contract fields: `evidence_spans`, attribution `evidence_span`, and condition/exception/limit spans, checking offset and exact source quote.
* Manifest requires locked `spec.model` and `spec.enable_thinking`; `run` rejects model/thinking configuration mismatch before preflight/provider work. Cache identity includes canonical whole-manifest and full request.
* Runtime ledger is loaded by manifest hash, writes before provider dispatch and after receipt processing, and records actual known input/output/total tokens plus unavailable-usage count.
* A fake HTTP-200, schema-invalid response produced 10 `host_validation` rows with retained usage `{2,3,5}` and cumulative actual total 50, confirming the intended host-validation accounting path.

## New P0: known-usage rows write the wrong cache key

Inside `run`, `key` initially holds the request cache hash. Later, the known-usage aggregation uses:

```
for name, key in (..., ("actual_total_tokens", "total_tokens")):
    ledger[name] += receipt["usage"][key]
row = {"cache_key": key, ...}
```

The loop shadows the request cache hash. For every receipt with `usage_state="provider"` (including a normal HTTP-200 result, host-validation result, `length`, or content filter), the persisted row is written at the correct hashed path but contains `cache_key="total_tokens"`.

Direct fake-provider evidence:

| Path | Persisted row cache key | Expected |
|---|---|---|
| `length`, usage `{2,10,12}` | `total_tokens` | SHA-256 cache key |
| HTTP-200 invalid JSON/schema, usage `{2,3,5}` | `total_tokens` | SHA-256 cache key |

On the next run, cache validation compares the row value with the expected hash and raises `stale/corrupt AU-only cache`. Thus the supposedly write-ahead cumulative ledger cannot be resumed for the ordinary provider-success/known-usage paths. This is a remote-execution blocker.

Required repair: use a distinct variable such as `usage_field` in the accounting loop; keep `cache_key` immutable for the request scope. Add a regression test that runs twice against the same temporary `root/cache`: first call receives length/host-validation with usage, second call makes zero opener calls and returns the persisted row/ledger without error.

## Coverage and residual risks

The aggregate runtime cap predicate appears to prevent a call before dispatch, and preflight now gates provider attempts. But AU-only tests remain three manifest/preflight tests; they do not exercise run/cache/resume/cap-stop/HTTP/transport/length/host-validation/config mismatch. The fake probes above exercised length and HTTP-200 invalid paths only and found the cache defect.

The ledger is correctly write-ahead at the intended `output_root/runtime_ledger.json` location when CLI passes `output_root/cache`. Its path is `Path(cache_dir).parent`, so embedding the runner under an arbitrary cache hierarchy should be documented/validated to avoid unintentional ledger sharing.

As before, `complete` is protocol completion only. The runner flags `semantic_gold=false` and `semantic_quality_claim=false`; neither source-span validation nor test success demonstrates AU semantic correctness.

## Test result

```
python -m unittest knowledge_base.pipeline_v1.tests.test_au_only knowledge_base.pipeline_v1.tests.test_plan10 -v
Ran 36 tests ... OK
```

This test pass does not cover the discovered P0. Re-audit after the cache-key fix and dedicated run-path tests.
