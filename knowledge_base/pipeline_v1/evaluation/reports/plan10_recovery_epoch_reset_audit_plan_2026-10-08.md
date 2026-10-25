# Plan10 — audit criteria for an externally proven recovery epoch reset

Date: 2026-10-08  
Scope: design and future implementation audit only. No Modal request was made and this document does not assert that an epoch-reset implementation exists.

## Independent conclusion

The premise needs a constraint: a successful warmup must **not** reset, overwrite, or make invisible the previous recovery and budget history. A valid operation is a new, bounded **recovery epoch**, cryptographically/provenance-linked to the stopped epoch. Its counters may start at zero only as *epoch-local counters*; reports must still expose the predecessor counters and cumulative history.

This is especially important for the v1.5 incomplete pair. An epoch reset is not a generic way to retry every non-verified cache row. In particular, `length`, malformed/schema failures, and `budget_stopped` with `budget_reservation_exceeded` are not provider-unavailable rows and must remain ineligible unless a separately approved policy changes their classification.

## Required interface and non-destructive boundary

Prefer a separate explicit command, for example `paired-resume-epoch`, requiring all of:

* an immutable predecessor output root;
* a new output root and explicit `epoch_id`/idempotency key;
* `--external-warmup-proof PATH`;
* an explicit new epoch budget and recovery policy; and
* the existing explicit execution authorization.

It must not be an implicit branch of ordinary `paired-run`, and it must never mutate the predecessor cache, recovery ledger, remote comparison, or remote-run artifact. The new cache namespace should be under the new epoch; predecessor cache is read-only input. This permits a before/after hash audit of the original partial v1.5 result.

## External warmup proof contract

The existing local warmup-probe receipt is useful for ordinary preflight, but is not by itself sufficient as a reset authority: it has no one-use claim or epoch-chain binding. Require a distinct, canonicalized `Plan10ExternalWarmupProof` receipt with at least:

| Field | Required binding / validation |
|---|---|
| `proof_id`, `proof_sha256`, schema version | Globally unique identity; canonical hash verifies the immutable contents. |
| `status=success`, observed/issued time | Successful warmup only; reject stale proofs, timestamps too far in the future, and local-clock rollback according to documented tolerance and TTL. |
| provider/model identity | Exact endpoint/provider identity, model, and `enable_thinking` must equal the new epoch configuration. No credential is stored. |
| warmup request contract | Safe fixed warmup prompt, request/config hash, response-status/response hash, and issuer/verification method. It must contain no source case request. |
| workload binding | Frozen Plan07 manifest/build hash, paired input-manifest hash, paired request/spec hash, and accepted target/cap policy hash. |
| epoch-policy binding | New epoch budget hash and recovery-policy hash. Changing either requires a newly issued proof. |
| authenticity | A verifiable issuer signature or equivalent trusted attestation, if the claim is “external proof.” A plain local JSON file only proves consistency with the local machine, not external success. |

Freshness based solely on the host clock is a weaker claim: it can prove “fresh relative to this host's clock,” not independently prove current external availability. If no signed/provider-verifiable attestation and trusted timestamp exist, the implementation must label the proof as locally attested and must not present it as independent external evidence.

The proof's provider attempt is not free. Record it as `external_warmup_attempts=1` with its own receipt/accounting provenance. It may be outside the source-execution budget only if the report states that separation explicitly; it may never disappear from the cumulative provider-attempt report.

## One-use proof claim and epoch chain

Before any warmup or source request in the new epoch, atomically persist a proof claim. Reusing the same `proof_id` or `proof_sha256` for a different epoch must fail. A crash after the claim may resume only with the same `epoch_id`, predecessor, proof hash, and idempotency key; it must not permit a second epoch or silently release the proof.

Persist an append-only `Plan10RecoveryEpochLedger` (or equivalent immutable snapshots) with:

* `epoch_id`, idempotency key, state (`claimed`, `running`, `stopped`, `complete`), timestamps, and output-root hash;
* `prior_epoch_id`, predecessor recovery-ledger hash, predecessor runtime-usage hash, and predecessor output/cache manifest hashes;
* proof ID/hash/path, issuer, issued time, freshness verdict, and claim timestamp;
* exact Plan07/paired/spec/model/thinking/policy/budget hashes;
* selected request IDs and cache identities, selection reason for each, count per arm, and selection-manifest hash;
* epoch-local reservation, consumption, provider-attempt/recovery-cycle counters, plus immutable predecessor and cumulative summaries; and
* hashes of produced cache, recovery ledger, comparison, and final status artifacts.

The validator must reject a missing predecessor, hash mismatch, cycle, duplicate child/proof claim, or an unapproved fork. The old ledger remains sealed; “reset” is a report view of a new epoch, never a rewrite of history.

## Exact cache-selection rule

For each frozen request identity/cache key, select it only when all identity checks pass and its predecessor row is one of:

1. unresolved with a retryable provider HTTP/transport condition; or
2. `budget_stopped` whose recorded `stop_reason` is exactly `provider_unavailable`.

Do not select `protocol_verified`; non-provider unresolved rows (including `length`, malformed output, schema/protocol failure, content filtering); or any budget stop such as reservation exhausted, target cap, or per-request limit. The selector must fail closed on unknown status/reason.

Selection must preserve the frozen P2a/P2b request identities, have no duplicate identity across or within arms, and produce an auditable sorted manifest. If selection is empty, reject the epoch rather than issue a cosmetically successful reset. This rule intentionally rejects historical v1.5 rows stopped for reservation exhaustion; reclassifying those rows as provider failures would be a material new policy decision, not recovery.

## Bounded budget and completion semantics

Preflight must use only the selected logical requests, but reserve the full worst case before dispatch: each selected baseline source request plus permitted global recovery source retries and warmup attempts. Input, output, USD, logical source attempts, provider attempts, and recovery cycles all have explicit caps. One additional attempt of any kind must fail before calling a provider.

The epoch ledger reports both `epoch_usage` and `cumulative_usage = predecessor_usage + epoch_usage` (with the external proof attempt separately identified). A fresh local counter must never be reported as if the full historical run consumed only that amount.

An epoch can be `complete` when its own selected set is terminally processed. The whole paired experiment can be `COMPLETE` only if the union of predecessor verified rows and this epoch's verified rows covers the exact frozen 192-request workload under the same protocol. A remaining `length` or other terminal non-verified row prevents that stronger claim.

## Mandatory automated tests and independent audit checks

| Case | Required evidence / expected result |
|---|---|
| Valid recovery | Fake successful external proof, stopped predecessor, and mixed cache: only exactly eligible rows dispatch; predecessor hashes unchanged; proof claimed before first dispatch. |
| Binding tamper | Change any proof hash/signature, endpoint/model/thinking, manifest/spec/Plan07 hash, policy hash, or budget hash: reject before warmup/source call. |
| Freshness | Stale, future-dated, and clock-rollback proofs reject before calls; boundary TTL behavior is deterministic. |
| One-use and crash | Sequential/concurrent second claim fails. Crash just after claim resumes only the same epoch and cannot duplicate proof use or source dispatch. |
| Cache selector | Fixtures containing verified, `length`, malformed, ordinary budget stop, `budget_reservation_exceeded`, `provider_unavailable`, retryable 503, and unknown values select exactly the latter two eligible classes. |
| Identity safety | A cache row with mismatched request/cache identity is rejected, not reused; duplicates across P2a/P2b fail. |
| Epoch-chain tamper | Missing/wrong predecessor hash, cycle, proof reused in another child, and altered snapshot all fail validation. |
| Budget boundary | Preflight reservation equals selected workload plus permitted retry slots; exhaust each cap and show the next provider/source attempt is prevented. |
| New-epoch recovery | A retryable failure inside the new epoch consumes persisted global cycle/attempt counters write-ahead; resume observes the spent counter. |
| Completion claim | Subset completion stays epoch-only; whole-pair `COMPLETE` is granted only when union coverage is exact and protocol-verified. |
| Provenance report | Final report lists predecessor, proof, selection, old/epoch/cumulative budget, all stop reasons, and explicitly labels trust level of the proof. |

All tests use fake providers/openers and fixture receipts. The independent audit should run the narrow Plan10 test module plus these new tests, inspect ledger/cache hashes before and after, and make no Modal call.

## Acceptance gate

Accept only if the implementation demonstrates: (1) an externally verifiable, fresh, one-use proof bound to the precise workload and configuration; (2) an immutable predecessor-to-epoch chain; (3) fail-closed selection limited to retryable/provider-unavailable rows; (4) independent epoch and cumulative budget accounting with a pre-dispatch hard cap; and (5) no overclaim of full-pair completion. Any implementation that merely clears `cycles_used`, rewrites the old recovery ledger, or treats all stopped v1.5 rows as eligible fails this audit.
