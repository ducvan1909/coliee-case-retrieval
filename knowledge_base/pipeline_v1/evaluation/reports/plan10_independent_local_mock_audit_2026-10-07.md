# Plan 10 — independent local/mock audit (2026-10-07)

## Verdict

**FAIL for the Plan 10 remote runtime contract.** The offline/mock path and its five focused tests pass in a Python environment containing `jsonschema`, but the remote validator, cap/accounting, and paired-run evidence do not yet meet the locked Plan 10 contract. No Modal endpoint was contacted and no credentials were read or printed by the audit checks.

This is a protocol/runtime result only. It establishes neither semantic AU quality, human gold, nor retrieval quality.

## Evidence that passed

- `python -m unittest knowledge_base.pipeline_v1.tests.test_plan10 -v` passed **5/5** using the system Python (`jsonschema 4.26.0`). The project `.venv` failed before collection because it lacks `jsonschema`; that is an environment/dependency issue, not a Plan 10 semantic result.
- The checked mock tests exercised KOS-5 locked workloads (96 P2a and 96 P2b requests), a target mismatch rejection, atomic local cache hit/invalidation, bearer-header construction, and split-token combination.
- Direct local adapter check showed `PLX_PROXY_TOKEN` takes precedence (`wk.ws`) and split credentials form `k:s`. `probe --max-requests 1` without `--execute` stopped at the CLI gate before configuration or network use.
- `core.py:29` writes cache rows with write-then-`os.replace`; `core.py:102` keys cache on arm, source hash, region fingerprint, rendered hash, and spec. These are useful local crash-safety and invalidation properties.
- A fake malformed provider response became an `unresolved` receipt, and `length`/`content_filter` are explicitly treated as truncation by `core.py:115`.

## Blocking findings

### P0 — host accepts model output that violates the locked schema

The Plan requires the response schema plus host checks (`11_incremental_implementation_plans.md:283-615`). `validate_response` (`core.py:60`) hand-checks only a subset and never validates against `contracts/plan10_au_model_output.v1.json`.

Minimal reproduction, all **accepted** by `validate_response(q, response, "abc")`:

- omit required `reason_detail`;
- set `hard_negative_reason` to `NOT_IN_CONTRACT`;
- provide malformed `warnings` (`{"not": "schema-shaped"}`);
- add an undeclared target-result property;
- set a positive result's `hard_negative_reason` and `unresolved_reason` non-null.

The checked JSON Schema rejects the first three corresponding payloads. This permits invalid parsed provider output to receive `protocol_verified` in `execute_remote` (`core.py:115`).

**Remediation:** load the versioned schema once with `Draft202012Validator`, reject every validation error before semantic/host checks, and retain the existing exact target/span/local-AU/context-reference checks as a second layer. Add one test per reproduction above and an end-to-end `execute_remote` assertion that such responses have `status == "unresolved"`.

### P0 — remote budget and cap contract is incomplete

The CLI's `--max-requests` cap is a request-count gate (`__main__.py:12,19`) only. There is no Plan-10 token, cost/USD, or cumulative budget configuration/enforcement; `execute_remote` also does not enforce `spec.caps.targets` or `spec.caps.au_candidates` (`core.py:102`).

Minimal reproduction: build P2a with `caps.targets=1`; requests containing four expected targets are still produced (`target_cap_max=4`). A provider response can likewise contain more candidates than the spec's `au_candidates` because the host does not check that cap.

**Remediation:** introduce a dedicated Plan-10 budget config (request, input-token, output-token, and, when price is known, USD reserve/actual); preflight both arms; enforce target and AU-candidate caps per request/target; record stop reason and unresolved targets when any limit is reached. Do not reuse unrelated `KB_*` cost assumptions silently.

### P1 — paired remote run is not bound to the probe or paired-control artifact

`paired-run` only requires a JSON file with truthy `success` (`__main__.py:16-18`). It does not verify probe model/spec/schema hash, source/Plan-07 digest, request identity/cache key, receipt authenticity, or that it is the current P2a workload. It builds two arm manifests but never calls `paired_experiment` or persists a remote paired-control manifest/ledger/accounting report.

**Remediation:** validate a signed/hash-bound probe receipt against the current P2a manifest/spec/schema/model and require a persisted `paired_experiment` result before dispatch. Persist each remote arm's immutable input-manifest hash, receipt ledger, status totals, usage/latency, and pair comparison; reject changed work rather than accepting any `success: true` file.

### P1 — ContextHint accounting regressed and repeats can be overcounted

Plan 10 explicitly requires P2a/P2b token, repeated-context, and latency accounting (`11_incremental_implementation_plans.md:269`). The current request has `repeated_source_chars` but no `repeated_context_chars`; `run_mock` initializes that total but never increments it (`core.py:122-131`). `_repeat` sums intersections against every prior interval without merging them (`core.py:35`), so overlapping prior spans can double-count repeated characters.

**Remediation:** retain a separate, merged interval set for context spans and source spans; record both per request and per arm. Add overlapping-interval and P2a/P2b accounting tests. This is cost/protocol accounting, not proof that ContextHint helps semantically.

### P1 — unexpected adapter errors can terminate the run rather than yield an unresolved receipt

`call_modal` catches HTTP/URL/timeout and parse-shape errors (`core.py:90-101`), but an unexpected opener/runtime exception escapes `execute_remote`. Local fake-opener reproduction: `RuntimeError("boom")` produced `ESCAPED RuntimeError`; a deliberate `ProviderResponseError` correctly produced `unresolved`.

**Remediation:** catch and classify bounded unexpected adapter/transport exceptions at the per-request boundary, create a redacted unresolved receipt, then continue to later requests. Do not catch `KeyboardInterrupt`/`SystemExit`, and never serialize authentication headers/tokens.

## Non-blocking observations

- Combined and split Modal credential assembly are correct for the documented forms, and the model is caller-configurable via `PLX_MODEL`; the default is consistently `Qwen/Qwen3.5-9B` (`.env.example:33-40`, `core.py:89`). Add a test for combined-token precedence (not only split token) and reject blank/whitespace-only model identifiers.
- Secrets are not printed by the focused tests. Remote configuration is intentionally loaded only after `--execute`; keep tests injecting dictionaries/fake openers rather than calling `settings()` against a real `.env`.
- The checkout has `knowledge_base/` untracked and unrelated staged deletions under `legal_unit/`. This audit is reproducible from the working tree, not from a committed Git revision.

## Required re-test after remediation

1. Validate valid and invalid responses through the exact runtime path, including all schema-required fields, enums, extra properties, duplicate local IDs, missing/foreign target, invalid every span type, and bad context references.
2. Simulate `length`, content filter, malformed JSON, HTTP error, timeout, and unexpected adapter exception; each must produce a redacted unresolved receipt and preserve later requests.
3. Test combined/split auth, URL normalization, configurable model, `--execute`, exact probe binding, stale receipt rejection, request/token/cost cap stop semantics, and no secret in receipts/logs.
4. Test atomic cache recovery/corruption, source/spec/schema/model invalidation, and resume without replaying validated cache rows.
5. Assert P2a/P2b identical model/prompt/schema/examples/caps and exact target pairs; verify source/context-repeat, usage, and latency ledgers.

Only after this protocol/runtime audit passes may a provider run be called protocol-valid. It would still be evaluated against `model_silver`, not human gold, and would not establish semantic AU quality or retrieval quality.
