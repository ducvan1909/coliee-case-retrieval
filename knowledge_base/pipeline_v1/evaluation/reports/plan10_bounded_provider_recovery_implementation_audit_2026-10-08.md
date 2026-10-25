# Plan 10 bounded provider-recovery implementation audit (2026-10-08)

## Verdict: FAIL

The implementation improves error classification, one-request recovery, attempt history, and completion reporting, but it does not satisfy the bounded paired-run contract.  No Modal call or real environment access was used.

## What passes

- Retryable classification is correct for HTTP `408`, `429`, `500`, `502`, `503`, `504` and transport failures; malformed responses and `length` are non-retryable.
- For one retryable source failure, the tested sequence is exactly source request -> source-free warmup -> one source retry.
- `length` remains terminal in paired recovery and produces no warmup/retry.
- A repeated consecutive outage fixture opens the circuit and prevents tail source fanout.
- Retryable and budget-stopped cache rows are archived before retry; completion requires every locked row to be protocol-verified.
- The focused Plan 10 suite passed 31 tests.

## Failing contract properties

### 1. `max_source_retries` is per failure, not a global paired-run bound

The implementation tests `recovery["max_source_retries"]` as a truthy switch after each new retryable source failure.  It never decrements or records a global retry allowance.  A successful retry resets `consecutive_retryable_source_failures` to zero, permitting recovery again for the next request.

Independent three-request fake-provider fixture, with `max_source_retries=1`, generated:

```
source, warmup, source, source, warmup, source, source, warmup, source
```

That is 9 provider attempts and 6 source-bearing attempts: three recovery cycles despite the configured value of one.  This recreates fanout under intermittent rather than consecutive outages.

### 2. Preflight under-reserves provider attempts

For the same three logical requests with `max_consecutive_retryable_failures=2`, preflight calculates an upper bound of 7 and accepts a provider-attempt cap of 7.  The valid runtime sequence above needs 9 attempts.  Therefore preflight cannot prove the runtime policy is budget-safe.

### 3. Source retry does not consume a second source reservation

The retry dispatch uses `logical=False`; it increments provider/source-attempt counters but does not increment `reserved_input_tokens`, `reserved_output_tokens`, or USD.  A source retry is a second paid/source-bearing dispatch and must reserve its own exact input/output/USD cost.  The current global cost ledger consequently understates worst-case spend.

### 4. Resume recovery provenance is incomplete

Attempt history is preserved, but there is no persistent, identity-bound `ProviderRecoveryLedger` controlling recovery state across a resumed pair.  A resumed `provider_unavailable` budget-stopped row does not require a fresh recovery warmup before a new source dispatch.  The configured recovery policy is recorded in the final comparison but is not used to fail closed on a changed-policy resume.

## Required correction

Use a global `remaining_source_retries`/recovery-cycle budget, decrement it atomically before the warmup, and open the circuit when exhausted.  Preflight must reserve:

- all 192 baseline source dispatches;
- at most the configured global retry count of extra source reservations; and
- at most that many source-free warmup provider attempts.

Each retry must reserve input/output/USD independently.  Persist a recovery ledger bound to both input manifests, Plan 07 build, model/spec, and recovery-policy hash; a resumed pending outage path must warm up before any source retry.

## Limits

This audit concerns provider recovery, budgeting, and execution truthfulness only.  It makes no semantic Authority Unit, human-gold, or retrieval claim.

## Global-recovery P0 re-audit

**FAIL.**  The global-cycle and retry-reservation corrections work for the in-process intermittent-503 regression: with one allowed recovery cycle, the fixture performs only `source, warmup, source, source`, consumes one cycle, reserves the retry, then stops the remaining tail.  Preflight now includes one worst-case retry's input/output reservation and provider-attempt bound.  The focused Plan 10 suite passed 32 tests.

However, the persisted-ledger requirement fails on a resume-specific fail path:

1. Create a cached retryable HTTP 503 row.
2. Resume it with a valid policy-bound recovery ledger.
3. Make the required fresh source-free warmup fail with HTTP 503.

Observed state after the call:

| field | in memory | persisted `recovery_ledger.json` |
| --- | ---: | ---: |
| `cycles_used` | 1 | 0 |
| `provider_attempts` | 1 | 0 |

The cached-retryable/warmup-failed branch returns before flushing `recovery_ledger_path`.  A later process resume can reload `0/0` and repeat the supposedly globally bounded warmup cycle.  This defeats the provider-attempt circuit bound across resume, exactly when outage recovery needs durable control.

Required P0 repair: atomically persist the recovery ledger before **every** early `continue`/return after any state mutation or provider attempt, especially warmup failure and provider-attempt-budget exhaustion.  Add a regression test that performs two process-style resume calls against the same failing warmup and proves the second call sees the consumed cycle, opens/stays open, and makes no additional provider request.  Until that test passes, this is not safe against cross-resume outage fanout.

## Durability P0 re-audit

**PASS.**  The runtime now checkpoints the policy-bound recovery ledger before every provider attempt and immediately after consuming a recovery cycle.  The focused process-style regression performs cached 503 -> fresh warmup 503 -> process restart and verifies the persisted ledger retains `cycles_used=1`, `provider_attempts=1`, and `warmup_attempts=1`; the restart receives `provider_unavailable` without another provider call.

The global intermittent-outage regression remains bounded at one recovery cycle, and source retry now increments the source reservation.  Preflight reserves the worst-case global retry input/output amount and provider-attempt upper bound.  Terminal length remains outside recovery.  Focused Plan 10 tests passed 33/33; no Modal request or real environment access occurred.
