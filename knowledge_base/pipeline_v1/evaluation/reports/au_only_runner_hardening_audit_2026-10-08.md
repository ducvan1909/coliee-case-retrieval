# AU-only runner hardening audit

Date: 2026-10-08  
Scope: current AU-only revision and requested fake-provider/cache/config branches. No Modal call and no runtime edit.  
Verdict: **FAIL for a USD-capped remote run; otherwise the newly added transport/config/cache hardening is partially verified.**

## Regression coverage actually present

| Requested branch | Evidence | Status |
|---|---|---|
| Transport unavailable + cache/resume | `test_transport_unavailable_cache_and_config_mismatch` raises `URLError`; first run records `usage_state=unavailable` and 10 unavailable attempts, second run makes no extra opener calls. | Covered / PASS |
| Config mismatch before dispatch | Same test supplies another model and expects `AUOnlyError`. | Covered / PASS |
| HTTP-200 invalid + usage/cache | Existing test uses HTTP-200 `stop` with `{}` and checks `host_validation`, usage retention, cache resume. | Covered / PASS |
| Length + usage/cache | Existing test checks `output_truncated`, known usage, correct cache key, and no second-run calls. | Covered / PASS |
| HTTP error (not transport) | `_call` has an `HTTPError` branch with `usage_state=unavailable`, but no AU-only regression test exercises it. | Code-only / unverified |
| Schema-valid bad `evidence_spans` quote | Code iterates `evidence_spans`; no regression fixture sends a schema-valid bad quote through `run`. | Code-only / unverified |
| Bad attribution `evidence_span` | Code iterates attribution evidence spans; no regression fixture exists. | Code-only / unverified |
| Cached unresolved validation | Current cache branch calls `_validate_response` for all non-budget rows, including unresolved; no mutation/resume regression exists. | Code-only / unverified |
| Persisted partial-ledger aggregate stop | Runtime predicate uses persisted counters; no test constructs a partial ledger and proves no opener call for the next row. | Code-only / unverified |

Focused command result:

```
python -m unittest knowledge_base.pipeline_v1.tests.test_au_only knowledge_base.pipeline_v1.tests.test_plan10 -v
Ran 39 tests ... OK
```

## P0 regression: USD cap has been removed rather than fail-closed

This revision removes USD price/rate fields from the AU-only budget and runtime ledger. `preflight` unconditionally emits `usd_limit_enforced=false`; its test sets a USD cap and explicitly asserts that `usd_cap` is absent. Runtime has no USD reservation predicate.

That is a valid explicit statement only if the run has **no USD budget requirement**. It is not safe for a USD-capped run: a configured USD limit is ignored rather than rejected as unknown/unavailable. This regresses the prior fail-closed `usd_rate_unknown` gate.

Required disposition before remote:

* either restore known-rate USD reservation and reject missing rates when a USD cap is configured; or
* remove USD-cap configuration entirely and make the run authorization/report explicitly state `USD budget not enforced`.

Until one of those choices is made, remote execution cannot claim a bounded USD budget. Treat this as P0 whenever a cost ceiling is part of authorization.

## P1 test gaps

Add separate regression tests for HTTP error cache/resume, schema-valid bad AU evidence quote, bad attribution evidence quote, malformed cached unresolved receipt/response, and a persisted partial runtime ledger where the next request stops before opener. These are all required to turn the present code-only paths into evidence-backed behavior.

## Semantic boundary

The runner continues to state `semantic_gold=false` and `semantic_quality_claim=false`; protocol/structure success is not AU semantic correctness. No semantic-quality claim is supported by the local tests.
