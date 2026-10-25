# Plan10 recovery epoch — implementation audit

Date: 2026-10-08  
Scope: local code and fixture-test audit of `paired-recovery-epoch`. No Modal request was made.  
Verdict: **FAIL — do not execute against v1.5.**

## What was checked

The implementation adds the CLI command in `au_baseline/__main__.py`, reads a source-free `Plan10WarmupLedger` through `_recovery_warmup_proof`, writes a proof registry/new directory under `output-root/recovery_epochs`, and passes `resume-root/remote_cache/<arm>` to the existing `execute_remote` function. The existing focused suite was run locally:

```
python -m unittest knowledge_base.pipeline_v1.tests.test_plan10 -v
Ran 33 tests ... OK
```

That is useful regression evidence for the old Plan10 recovery behavior, but it contains no test named for `paired-recovery-epoch`, proof claiming, epoch chaining, or its command path. It cannot establish the new feature's acceptance gate.

## P0 blockers

### 1. Cache selector retries budget-stopped rows that are not provider-unavailable

The requested selector is “retryable unresolved HTTP/transport **or** `budget_stopped/provider_unavailable` only.” The current cache branch does not enforce this.

`execute_remote` treats all `budget_stopped` rows as candidates to fall through: it calculates `cached_retryable` correctly, but then archives the row and continues execution even when it is false. With a fresh epoch budget, a prior `budget_reservation_exceeded` row can therefore reach `dispatch` and make a source/provider call. This is exactly the prohibited reclassification of a budget stop into recovery work. It also archives it with `resume_budget_stopped`, which confirms it did not fail closed.

Required repair: classify before archival/dispatch; append or reject every noneligible predecessor row without writing/dispatching. Make a deterministic selected-request manifest first, and invoke remote execution only on that manifest. Tests must include `budget_reservation_exceeded`, target/per-request caps, `length`, malformed/protocol failures, unknown values, 503, and `provider_unavailable`.

### 2. The “external proof” does not bind the epoch or establish required trust/freshness

`_recovery_warmup_proof` verifies only: local file beneath `pipeline_v1/outputs`, `Plan10WarmupLedger`, success, model, thinking flag, and age computed from `started_unix + started_elapsed_seconds`. It does **not** bind provider endpoint/identity, Plan07 build, paired manifests, request/spec hashes, recovery policy, epoch budget, proof ID, or a signature/issuer attestation. The warmup ledger has no such binding fields.

It also accepts a future-dated proof because a negative age is not rejected; malformed timestamp types can escape as a generic runtime error. Thus it is a locally readable warmup record, not a fresh external authorization for the precise epoch.

Required repair: define and validate a separately versioned proof receipt with canonical proof ID/hash, safe provider identity, endpoint/config hash, issuer verification, workload/spec/build hashes, budget and recovery policy hashes, issued timestamp with future-skew/rollback policy, and explicit trust label. Do not call it external proof without verifiable external attestation.

### 3. Proof use is neither atomic nor safely resumable

The command performs `exists()` then `write_text()` of the proof registry. Two processes can pass the existence check and both claim the proof. The registry is written **before** workload validation, `max-requests`, preflight, and epoch directory creation. A later validation failure irreversibly consumes the proof, and a crash after the write has no resumable `epoch_id` or idempotency record. A retry with the same proof simply fails “already used.”

Required repair: after deterministic validation/preflight, atomically create an immutable claim ledger keyed by proof ID/hash and epoch idempotency key. A claim must either be released only before work starts or become resumable only by the exact same epoch identity. Test concurrent claims and crash-after-claim recovery.

### 4. No immutable predecessor-to-epoch chain; predecessor can be written

The only predecessor record is the mutable string `previous_epoch` in `remote_comparison.json`. There is no epoch ledger, predecessor artifact hash, prior usage snapshot, selected-manifest hash, child/fork validation, or cumulative accounting.

Worse, `--output-root` is not checked against `--resume-root`. Setting them equal writes `recovery_epochs/proofs/...` into the v1.5 predecessor directory, violating the stated no-v1.5-write requirement. The source cache is normally read-only only when roots differ, but that input equality is currently accepted.

Required repair: reject equal/nested output and resume roots, hash and seal the predecessor artifacts before claim, and persist an append-only epoch ledger containing predecessor hashes, proof claim, selected cache identities, epoch/cumulative usage, state, and child identity. Validate the chain on resume.

### 5. Preflight/budget is for all 192 locked requests, not the eligible resume set

The command rebuilds both full arms, requires `--max-requests >= len(P2a)+len(P2b)`, and calls `_preflight((a,b), ...)` before cache selection. It therefore reserves the complete workload plus recovery slots, even though the stated purpose is to resume only eligible predecessor rows. This can reject a legitimate bounded partial epoch and does not produce evidence that exactly the selected set was reserved. The comparison exposes only new `runtime_reservation`; it neither snapshots predecessor usage nor computes cumulative usage, and it does not account for the external warmup proof attempt.

Required repair: derive and persist the eligible selection first, preflight exactly that set plus bounded retry/warmup reservations, retain all old usage as immutable predecessor data, and report epoch/cumulative/proof-attempt usage separately. Full-pair `COMPLETE` must be based on union coverage, not merely execution of the epoch.

## Secondary findings

* Epoch directory identity is proof-hash prefix plus `time.time()`, rather than an explicit stable epoch id/idempotency key; same-second collision can leave a consumed proof with no usable epoch.
* A registry scoped beneath a caller-selected output root is not a global one-use identity. The same proof can be reused by selecting another output root.
* There is no audit artifact listing selected request IDs, exact original cache identities, inclusion reasons, exclusions, counts by arm, or an empty-selection rejection. Existing `execute_remote` walks the entire workload.
* Existing completion computes status from the rows returned in the new root. It has no code proving union with predecessor verification; therefore it cannot safely make the requested whole-pair completion distinction.

## What did pass, with limits

The existing core retry predicate remains narrow for unresolved rows: retryable HTTP/transport requires both `retryable=True` and kind in `{http, transport}`; `length` is not classified retryable. The command passes predecessor caches via `resume_cache_dir` and normally writes new cache entries in the new root. These facts are insufficient because the `budget_stopped` fall-through and root-alias case defeat the principal safety boundary.

## Re-audit gate

Re-audit only after P0 repairs are implemented with new isolated tests for: binding/tampered/future/stale proof; atomic one-use and crash resume; output-root/predecessor separation; exact mixed-cache selection; preflight at selected-set capacity; prior/current/cumulative budget accounting; chain tamper/fork detection; and whole-pair union completion. The existing 33-test pass must remain green, but is not a substitute for these tests.
