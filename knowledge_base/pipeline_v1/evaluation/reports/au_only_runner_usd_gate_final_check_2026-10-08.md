# AU-only USD gate — final narrow check

Date: 2026-10-08  
Scope: only the missing-price USD-cap gate. No Modal call and no runtime edit.

## PASS

`preflight` now derives `rates_known` from the configured input/output per-1K rates and appends `usd_rate_unknown` whenever `max_usd_micros` is non-null but both rates are zero/missing. It computes `usd_cap` only when rates are known.

The AU-only fixture sets `max_usd_micros=1` while retaining zero default rates and asserts `status=fail` plus `usd_rate_unknown`. The focused suite passed:

```
python -m unittest knowledge_base.pipeline_v1.tests.test_au_only -v
Ran 5 tests ... OK
```

## Remote-readiness conclusion

The previously identified P0 gates are now present: isolated AU-only import boundary, source-backed manifest preflight, global target/ref checks, provider-attempt cap, known/unavailable usage distinction, exact evidence-span validation, model/thinking binding, write-ahead cumulative ledger, cache-resume safety for length and host-validation, and fail-closed USD-rate handling.

No remaining P0 was observed in the audited local code paths. This is **local protocol/runtime readiness only**, not authorization to claim AU semantic quality: outputs remain explicitly `semantic_gold=false` and protocol completion is not adjudicated AU correctness. Before an actual run, the user must still choose/review the locked 10–20 request manifest, source hashes, concrete provider configuration, caps, and budget.
