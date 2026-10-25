# AU-only bounded remote-pilot readiness audit

Date: 2026-10-08  
Scope: AU-only runtime correctness with USD explicitly out of scope by user direction. Local code/tests only; no Modal call and no runtime edit.  
Verdict: **PASS for a bounded AU-only remote pilot at the audited protocol/runtime boundary. No remaining P0 was observed in scope.**

## Requested hardening branches — regression evidence

| Branch | Test evidence | Result |
|---|---|---|
| Transport failure with unavailable usage and cache resume | `test_transport_unavailable_cache_and_config_mismatch` | PASS |
| HTTP 503 failure with unavailable usage and cache resume | `test_httperror_unavailable_cache_resume` | PASS |
| HTTP-200 invalid output keeps usage and resumes from cache | `test_http200_invalid_keeps_usage_and_caches` | PASS |
| `length` keeps usage, correct cache key, and no replay | `test_length_usage_cache_key_and_resume_cache_hit` | PASS |
| Schema-valid incorrect AU evidence quote | `test_bad_au_and_attribution_quotes_are_rejected` | PASS |
| Schema-valid incorrect attribution evidence quote | Same test | PASS |
| Config mismatch before dispatch | `test_transport_unavailable_cache_and_config_mismatch` | PASS |
| Corrupt cached unresolved receipt fails before opener | `test_corrupt_cached_unresolved_fails_before_opener` | PASS |
| Persisted exhausted ledger stops a newly uncached row before opener | `test_persisted_exhausted_ledger_stops_uncached_without_opener` | PASS |

The runner remains independent of Plan07/P2a/P2b/analysis-regions/ContextHint runtime imports. Manifest/source preflight, duplicate target and ref checks, provider-attempt and aggregate token caps, locked model/thinking binding, safe receipt taxonomy, cache identity, and write-ahead ledger behavior are covered by the cumulative AU-only suite.

## Test command

```
python -m unittest knowledge_base.pipeline_v1.tests.test_au_only knowledge_base.pipeline_v1.tests.test_plan10 -v
Ran 43 tests ... OK
```

## Explicit boundary and residual operational risks

* USD accounting is deliberately not enforced (`usd_limit_enforced=false`) under the stated user direction. Do not attach a USD ceiling or cost-bounded claim to this pilot. If a cost ceiling is later required, restore a fail-closed rate/cap gate before execution.
* This is fake-provider/local protocol evidence, not a live provider availability, endpoint-authentication, latency, or cost result.
* `protocol_verified` means schema, target coverage, and exact source-span/quote constraints passed. It does not establish that extracted Authority Units are legally/semantically correct. Artifacts remain `semantic_gold=false` and `semantic_quality_claim=false`; semantic claims need adjudicated review/gold.
* The pilot remains bounded by the locked 10–20 manifest and configured request/provider/input/output caps. Review those concrete manifest, source hashes, model/thinking config, and caps immediately before any live run.
