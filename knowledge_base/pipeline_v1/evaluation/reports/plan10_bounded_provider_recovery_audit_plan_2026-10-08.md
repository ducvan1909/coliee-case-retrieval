# Plan 10 paired-run bounded provider-recovery: independent audit plan

## Decision

Do **not** add an independent retry loop to every one of the 192 paired requests.  The v15 evidence (188 requests not dispatched after provider trouble) makes an outage-level controller necessary.  Retrying every request on HTTP 503 would turn a provider outage into source-bearing fanout.

Recommended default is one recovery cycle per paired run.  A cycle is:

1. A locked source request receives a retryable provider failure.
2. Persist its failed attempt without source/provider body.
3. Send one bounded source-free warmup.
4. Only if warmup succeeds, issue one retry of that exact frozen source request.
5. If the warmup or this one retry fails retryably, open the circuit.  No remaining locked source request may be dispatched in that run.

This is conservative deliberately.  It permits recovery from a transient event but stops after two outage signals (the original failure and failed recovery), rather than multiplying failures across the corpus.

## Contract to implement

### Error classification

Only HTTP `408`, `429`, `500`, `502`, `503`, `504`, and transport timeout/URL failures are retryable.  HTTP 4xx outside that set, malformed responses, schema failures, and `length`/`content_filter` are terminal for recovery.

In particular, `length` must never enter provider recovery or consume a warmup/retry cycle.  It remains an explicit incomplete outcome (a separately authorized structural-repair protocol is not a provider-outage retry).

### Two distinct budgets

The implementation must persist and report both ledgers, never conflate them:

| ledger | counts | purpose |
| --- | --- | --- |
| provider-attempt budget | every HTTP attempt, including source-free warmup and source retry | bounds outage fanout and latency |
| source/request reservation budget | every source-bearing dispatch, with its exact input/output/USD reservation | enforces the pair's cost ceiling |

Cache hits consume neither ledger.  A source retry consumes one provider attempt and a second source reservation.  Source-free warmup consumes only a provider attempt.

Use explicit policy fields, hash them into a `ProviderRecoveryLedger`, and preflight the worst case: 192 baseline source requests plus at most one recovery source retry and one warmup.  If configured provider/source/global token or USD limits cannot reserve this maximum, paired-run must refuse before dispatch.

### Circuit and completion

The circuit begins closed.  A failed recovery opens it with a machine-readable reason such as `provider_outage_circuit_open`; all undispatched rows are resumable interruption rows, not model outputs.  `COMPLETE` still requires all 192 frozen requests to be `protocol_verified`; circuit-open, retryable failure, length, or unresolved states are `INCOMPLETE`.

### Resume and provenance

Before retrying, append an immutable attempt-history record that binds cache key, request hash, attempt ordinal, failure classification, source-dispatched boolean, provider-attempt ordinal, and recovery-cycle identity.  Resume must require identical Plan 07 build hash, both input-manifest hashes, model/spec, and recovery-policy hash.  It skips protocol-verified cache entries, preserves historic failed/stopped entries, and begins with a fresh source-free warmup before any newly resumed source retry.

## Required test matrix

All tests use a fake opener; no real provider or `.env` access.

| scenario | required assertion |
| --- | --- |
| `503 → warmup success → source retry success` | exactly three provider attempts; two source dispatches for that one locked request; next request proceeds; immutable attempt record exists |
| `503 → warmup 503` | exactly two provider attempts; circuit opens; no second source retry and no remaining source request dispatch |
| `503 → warmup success → source retry 503` | exactly three provider attempts; circuit opens; no additional request fanout |
| `429`, `504`, transport timeout | classified retryable and follow the same single-cycle bound |
| HTTP `400`, malformed body/schema error | one source attempt only; no warmup and no retry |
| `length` or `content_filter` | one source attempt only; no recovery/warmup/retry; incomplete reason preserves truncation |
| circuit-open tail | all remaining logical requests have a resumable interruption status, zero source bytes/provider calls, and exact IDs remain in ledger |
| provider/source budget exhaustion | stops before dispatch; provider-attempt and source-reservation counters remain truthful and separate |
| cache hit | makes zero provider/source reservations and cannot advance/close the circuit |
| resume after circuit open | validates identity; retains archived attempts; starts with warmup; retries only permitted pending request(s), never already verified IDs |
| tampered history/policy/manifest identity | fails closed before any provider call |
| complete predicate | only 192 `protocol_verified` rows yields `COMPLETE`; every other status/count yields `INCOMPLETE` |

## Acceptance evidence after implementation

1. Focused Plan 10 tests cover every matrix row above and pass.
2. A deterministic all-success fake paired fixture reaches 192 verified rows with exact shared provider/source ledger reconciliation.
3. A deterministic 503-outage fixture proves bounded calls (at most three under the recommended policy), zero tail-source fanout, circuit-open state, and a resumable immutable history.
4. Existing `plan10_warmup_probe_v15` remains untouched and continues to describe the historical incomplete attempt.

## Scope limit

This plan governs provider recovery and execution truthfulness only.  It neither validates Authority Unit semantics nor authorizes a new Modal run.
