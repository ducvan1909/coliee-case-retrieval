# AU-only runner implementation audit

Date: 2026-10-08  
Scope: local source, schema, focused tests, and in-memory negative fixtures. No Modal call; no runtime edit.  
Verdict: **FAIL — do not treat this as an independent AU-only runner or run it remotely yet.**

## Tests run

```
python -m unittest knowledge_base.pipeline_v1.tests.test_au_only knowledge_base.pipeline_v1.tests.test_plan10 -v
Ran 35 tests ... OK
```

The pass is limited: `test_au_only.py` has two tests and only exercises `validate_manifest`/`preflight`. It does not execute `run`, fake provider receipts, cache/resume, source validation, aggregate runtime caps, or CLI behavior.

## P0 findings

### 1. Runtime still depends on the P2/Plan07 runner

`au_only.core` imports `BaselineError`, provider adapter, cache helpers, prompt/spec helpers, budget parser, and `validate_response` directly from `au_baseline.core`; `au_only.__main__` also imports its modal config/budget helpers from that module. Importing `au_baseline.core` imports `analysis_regions.renderer` and other Plan07-derived runtime dependencies.

This fails the requested boundary even if no P2 manifest is passed: the AU-only process cannot load independently of the P2/Plan07 runtime graph. Move genuinely shared generic provider/receipt/schema primitives into a P2-neutral module, or provide AU-only-local equivalents. AU-only must not import `au_baseline` at runtime.

### 2. Manifest validation does not enforce global target uniqueness or valid source refs

`validate_manifest` checks uniqueness only of `(case_id, region_id)`. It verifies target ownership within each request, but does not reject a target ID assigned to more than one request, does not enforce a frozen global request/target order, and does not validate source-reference bounds/non-empty spans.

Two direct in-memory negative fixtures were accepted:

* ten requests all owning the same `at-same` target ID; and
* a target source ref with `start_char == end_char == 0`.

The second fails only later in `_render`, after remote run setup and with no normalized fail-closed manifest report. Source bytes/hash are checked by `open_source` during `run`, but preflight has no source-store parameter and cannot verify source hash, offsets, or target ref validity before a cache hit/dispatch decision.

Required repair: manifest must include and validate canonical target identity/order and source refs against a supplied, read-only source store in offline preflight. Reject duplicate target IDs globally and invalid/empty/overlapping (unless explicitly allowed) refs before any provider configuration/call.

### 3. Receipt and budget semantics are incomplete for runtime safety

The HTTP-200 host-validation path correctly preserves safe provider usage and assigns `host_validation`; `length`/`content_filter` also preserve usage. However, HTTP/transport paths default to `{0,0,0}` rather than an explicit `usage_unavailable` state. Zero known usage is not the same claim as unavailable provider usage.

Runtime only checks request count after preflight. It does not maintain/enforce aggregate input/output/USD/provider-attempt caps during dispatch, does not reserve retry/recovery slots, and reports no provider-attempt or unavailable-usage counters. Preflight catches the nominal fixed manifest totals, but this is not a persisted runtime budget ledger or a proof against changed/corrupt/cache/resume behavior.

## P1 findings

* The cache key omits `request_id`, `input_tokens`, and manifest identity. Full request equality protects a cache hit afterward, but a changed value can collide at the path and produce a stale-cache error rather than a clean versioned identity; no manifest hash/output provenance is persisted.
* Cache hits are returned without re-validating cached response/receipt status or structural output. A corrupt but request-matching `protocol_verified` cache row can be trusted.
* CLI `preflight` calls no credential-required modal configuration, which is good, but always prints `AU-ONLY PREFLIGHT PASS` even if `preflight(...)["status"] == "fail"`. It also requires `--source-store` but does not use it in preflight, so the required source proof is absent.
* The result is structurally labeled only by `protocol_verified`/`unresolved`; it contains no explicit `semantic_gold=false`, semantic-evaluation boundary, or test preventing a caller from reading `status=complete` as AU semantic correctness.

## What is correct so far

The schema and implementation enforce 10–20 requests, `arm="AU-only"`, and an empty ContextHint payload. The source renderer uses only manifest `source_refs`; it does not itself insert P2 spans. The safe HTTP-200 host-validation and length usage preservation follows the repaired Plan10 pattern. These are partial building blocks, not enough to satisfy the independent-runner requirement.

## Required re-audit tests

1. Dependency isolation test that imports/runs AU-only with `au_baseline`, `analysis_regions`, and ContextHint imports blocked; source scan alone is not sufficient.
2. Source-backed offline preflight tests for hash mismatch, stale source, zero/out-of-bounds refs, target quote/span mismatch, global duplicate target, duplicate request ID, and altered order; each must prove opener was never invoked.
3. Fake-provider tests for protocol-valid, HTTP-200 host-validation, HTTP/transport `usage_unavailable`, length/content-filter, and no-call budget stop.
4. Cache tests for identity mutation, malformed/stale cached row, structurally invalid cached response, no-cost valid hit, immutable prior attempt/archive, and resumed budget state.
5. Aggregate input/output/USD/provider-attempt boundary tests, including one-over-cap prevention before opener.
6. A semantic-boundary test proving structurally valid output cannot produce a semantic-quality/gold claim without an adjudicated fixture.

Until these P0 repairs and tests land, the correct report is: **AU-only manifest prototype with some safe receipt handling, not an independently executable or semantically validated AU-only runner.**
