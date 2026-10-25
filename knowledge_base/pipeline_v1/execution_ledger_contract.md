# Plan 08 — Execution ledger contract

This is an offline operational test over the exact KOS-5 Plan 07 workload. It calls no model and infers no `AuthorityUnit`, no-AU result, `Issue`, `NoticeNeed`, or `ContextObligation`.

## Canonical state

`run_snapshot.json` is the sole source of truth. `attempt_log.jsonl` is a derived projection and must reconcile record-for-record with `snapshot.attempts`. Writes use a same-directory temporary file followed by atomic replacement.

Before replacing a current suite, the complete previous `scenarios/`, manifest, invalidation probe, and pointer are staged under `history/<manifest-sha256>/`. `archive_record.json` inventories every payload file with a safe relative path, SHA-256, byte length, and artifact type; the record itself is hashed by schema-validated `history/index.json`, avoiding a self-hash cycle. Publication order is stage, validate, atomic directory rename, then atomic index update. `current.json` selects only the non-history current manifest by verified relative reference and hash.

History validation compares the inventory with the complete actual file set, then validates size/hash/type, manifest identity and Plan 07/policy dependencies. Every archived snapshot is reopened with its archive-local cache and reconciled against its archived JSONL projection. Missing, modified, truncated, duplicate, unexpected, escaped, or current-substituted paths fail closed.

The former manifest-only archive is retained under `history/legacy_unsealed/` and migrated to record version v2. Its provenance explicitly says tamper detection begins at migration; no claim is made about changes before that point.

Each of the 369 Plan 07 primary targets has exactly one `CoverageLedgerEntry`. The only successful terminal state is `mock_protocol_verified`: the deterministic mock returned exactly the expected target and work-item identifiers. It is not semantic completion.

The fixed graph is `pending -> in_progress -> mock_protocol_verified|error|unresolved`, `in_progress -> pending` only for recovery, and `pending -> budget_exhausted`. Terminal states cannot transition.

## Request identity and cache

The fingerprint includes source hash, Plan 07 arm, exact region fingerprint, render items/order, scheduler and region policy versions, target/context spans, task, provider, response schema, dependencies, and settings. Wall-clock and host identity are excluded. Cache entries are immutable and fingerprint-addressed. A malformed, stale, or mismatched cache entry fails closed.

P2a and P2b never share fingerprints even when source spans match. A source mutation invalidates only requests for the changed case; provider, schema, policy, arm, render metadata, or settings mutations invalidate every affected request.

## Retry, resume, and partial responses

Only `transient_failure` is retried, at most twice after the initial attempt. Permanent failure, timeout, and protocol failure are not blindly retried. Attempt numbers and global order are append-only; resume continues numbering instead of rewriting crash history.

The partial-response policy is `atomic_batch_reject_all`. Missing, duplicate, foreign, malformed, or partial processed-ID responses commit no work item in that request. A budget stop remains `budget_exhausted`, never protocol-verified. Exact resume skips verified work and makes zero provider calls.
