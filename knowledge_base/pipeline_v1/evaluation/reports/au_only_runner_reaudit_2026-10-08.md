# AU-only runner re-audit after P0/P1 repair

Date: 2026-10-08  
Scope: current `au_only` source, schema, focused tests, and local fake/in-memory checks. No Modal call and no runtime edit.  
Verdict: **FAIL — several original boundary defects are repaired, but remaining runtime/validation blockers make remote execution premature.**

## Repaired and verified

* `au_only.core` no longer imports `au_baseline`, Plan07, `analysis_regions`, P2a/P2b, or ContextHint modules. Its runtime imports are source-contract, JSON/schema, and standard-library provider code. This satisfies the requested P2/ContextHint import boundary.
* Manifest validation now rejects non-AU-only arm/non-empty hint payload, duplicate request ID or case/region identity, global duplicate target IDs, empty source refs, and zero/negative refs.
* `preflight(..., source_store=...)` opens each immutable source and checks hash-backed source availability plus ordered, in-bounds refs before a run. It carries explicit `semantic_gold=false` and `semantic_quality_claim=false` fields.
* CLI preflight returns zero only for a pass and prints the actual pass/fail state; it has no credential/token read. Remote run separately requires explicit execution and AU-only URL/token/model configuration.
* HTTP/transport receipts now use `usage=None` with `usage_state=unavailable`; fake length execution retained provider usage. A local fake run of 10 length responses produced 10 `output_truncated` rows, receipt usage `{2,10,12}`, and a 10-attempt ledger.

## P0 blockers

### 1. Preflight does not enforce `max_provider_attempts`

`preflight` exposes `max_provider_attempts` in `limits` but has no corresponding failure condition. Reproduction with 10 valid locked requests, `max_requests=10`, and `max_provider_attempts=9` returned `preflight_attempt_cap=pass` (with source opening stubbed locally). `run` later stops the tenth request at the aggregate budget check instead.

This defeats the purpose of preflight as an all-cap pre-dispatch authorization. Add `provider_attempt_cap` to preflight (for this no-retry runner, request count is the bound), and test that failure prevents any opener call.

### 2. AU evidence source validation checks the wrong field

The official output contract names AU evidence `evidence_spans` and attribution evidence `attributions[*].evidence_span`. `_validate_response` instead iterates `au.get("evidence", [])`. Consequently it validates neither required `evidence_spans` nor attribution/condition/exception/limit spans against source offsets and exact quotes.

Schema validity alone confirms field shape, not that a quote equals the locked source at those coordinates. This is a structural/protocol failure, not merely a semantic limitation. Port the exact-source-span validation to the actual schema fields, including attribution/condition/exception/limit spans, and add a fake HTTP-200 schema-valid response with a deliberately wrong quote that must become `host_validation` while preserving provider usage.

### 3. Provider configuration is not bound to locked request spec

`_call` sends `cfg["model"]`, while cache/request identity derives from manifest `q["spec"]`; `run` never checks that configured model and thinking mode equal the locked manifest spec. A caller can execute model B under a manifest/cache identity claiming model A.

Before opening any source/provider, validate model, thinking mode, output cap/schema/prompt identity as applicable against every locked request. Include the effective provider configuration fingerprint in the receipt/cache provenance.

## Residual P1 risks

* `runtime_ledger` is only returned at the end; it is not write-ahead/persisted during dispatch. A crash leaves cache rows but loses aggregate historical known usage/attempt accounting. Resume treats cache hits as free and emits a fresh ledger, so the final report is not cumulative across interrupted runs.
* The ledger tracks reservation and unavailable-usage attempt count, but not sum of known provider input/output/total usage. Receipts retain the data but audit/cost reporting requires a recomputation rather than an explicit bounded ledger field.
* Cache validates a cached `protocol_verified` response structurally, which is good, but accepts unresolved/budget-stopped rows without validating receipt shape/provenance. There is no immutable attempt-history record or declared resume policy.
* Manifest list order is included in its canonical hash/cache key, so it is locked once supplied, but no canonical ordering rule or explicit order-check test exists. Output target checks use sets, so response order is not enforced.

## Tests

```
python -m unittest knowledge_base.pipeline_v1.tests.test_au_only knowledge_base.pipeline_v1.tests.test_plan10 -v
Ran 36 tests ... OK
```

The AU-only suite now has three manifest/preflight tests. It still has no test for `run`, cache/resume, HTTP/transport receipt, length/content filter, host validation, config-to-spec binding, CLI exit code, or runtime cap prevention. Plan10 tests are regression evidence only; they do not establish AU-only behavior.

## Semantic boundary

The explicit semantic flags are an improvement. Nevertheless, `status=complete` currently means only every request passed the runner's structural/protocol validator; it does not establish AU correctness, legal proposition quality, or retrieval quality. That distinction must remain in reports and requires adjudicated gold/review for any semantic claim.

## Re-audit gate before remote

Require all three P0 repairs plus tests for provider-attempt preflight rejection, quote/span validation in every AU evidence field, model/thinking/spec binding, write-ahead cumulative ledger/resume, cache receipt validation, and safe receipt taxonomy. Until then, retain the status **local prototype; remote execution not authorized by this audit**.
