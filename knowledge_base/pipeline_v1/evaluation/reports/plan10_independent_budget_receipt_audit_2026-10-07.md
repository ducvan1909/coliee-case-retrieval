# Plan 10 independent budget and receipt audit — 2026-10-07

## Verdict: FAIL for paired-run authorization

The new total-budget and truncation mechanics pass focused local/mock checks, but a successful warmup-probe ledger is not sufficiently bound to the particular verified P2a request/cache row that paired-run relies on. Do not authorize paired-run until this binding is fixed.

No Modal request was made and no real `.env` was read or printed.

## Evidence that passes

- `python -m unittest knowledge_base.pipeline_v1.tests.test_plan10 -v`: **22/22 passed**.
- Per-request limits (`max_input_tokens`, `max_output_tokens`) and aggregate paired limits (`max_total_input_tokens`, `max_total_output_tokens`) are distinct. Missing aggregate limits and too-small aggregate input limit produce preflight failures before dispatch.
- `_preflight` is pure/local: it only derives reservation data from locked request manifests. The CLI preflight command writes a local report but does not call a provider.
- `paired_experiment` freezes equal P2a/P2b spec and exact `(case_id, batch_id)` target sets. The input manifests preserve arm-specific rendering; ContextHint differences therefore do not change model/prompt/schema/examples/caps or targets.
- `length` is retained as `unresolved`, with `failure_diagnostic.kind=output_truncated`; paired accounting counts it separately as `output_truncated_unresolved`.
- Direct probe receipts validate their receipt hash plus P2a manifest, Plan 07 manifest, spec and first-request hashes.

## Blocking reproduction: warmup-probe verified status is not bound to its request/cache

`_has_probe_proof` validates warmup-probe ledger top-level hashes, model and thinking flag, then accepts if *any* `probe_attempts` entry has `status="protocol_verified"` (`au_baseline/__main__.py:37-39`). It does not require that entry to have:

- the current first P2a `request_id`;
- the corresponding recomputed `cache_key`;
- a receipt/request hash or cache-row validation.

Local reproduction constructed a temporary `warmup_probe/current.json` whose top-level identity matched the real locked P2a manifest/spec, but whose sole verified attempt used `request_id="WRONG"` and `cache_key="WRONG"`. `_has_probe_proof(...)` returned **True**. Thus a stale/tampered/misbound warmup-probe ledger can satisfy paired-run's gate without proving the current P2a source probe.

## Required remediation

1. Require exactly one matching verified probe entry (or a cryptographically/hash-bound receipt) with the current first P2a request ID and recomputed cache key.
2. Bind the entry to `request_sha256`, input-manifest/spec hash and a cache-row/receipt digest; validate the referenced row's status and response before accepting it.
3. Add stale/misbound tests for wrong request ID, wrong cache key, changed manifest/spec/model/thinking, and missing/corrupt referenced cache row. Each must reject before paired dispatch.

After this P0 authorization fix, rerun the focused tests and the fake-provider paired preflight path. Passing it would establish a local runtime/protocol gate only—not semantic AU quality, human gold, ContextHint value, or retrieval quality.
