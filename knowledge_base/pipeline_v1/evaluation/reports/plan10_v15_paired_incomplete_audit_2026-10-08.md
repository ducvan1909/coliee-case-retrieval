# Plan 10 v15 paired-run incompleteness audit (2026-10-08)

## Result: FAIL

This is an independent local artifact/code audit of `outputs/plan10_warmup_probe_v15`.  No provider call or environment-secret access was performed.

The run is not complete despite the CLI message `PLAN10 PAIRED RUN COMPLETE`.

| arm | protocol verified | unresolved (length) | budget stopped | total ledger rows |
| --- | ---: | ---: | ---: | ---: |
| P2a | 1 | 1 | 94 | 96 |
| P2b | 1 | 1 | 94 | 96 |

Only four requests reached the provider path.  Every stopped row has `stop_reason: budget_reservation_exceeded`; 188 of 192 pair members were never dispatched.  The artifact makes no semantic, human-gold, or retrieval claim, but it must not be called a complete paired execution.

## Cause

Preflight correctly used the dedicated global fields:

- `PLX_MAX_TOTAL_INPUT_TOKENS = 490044`
- `PLX_MAX_TOTAL_OUTPUT_TOKENS = 230400`
- 192 total requests, with 488823 input and 230400 output tokens reserved for this v15 manifest.

However `plan10_budget()` stores `PLX_MAX_OUTPUT_TOKENS` (2400) in `budget["max_output_tokens"]`; this is explicitly the **per-request hard ceiling**.  `execute_remote()` then compares cumulative `used["output_tokens"] + reserve_output` to that same field.  It should instead use the required total field.  With a 1413-token response followed by a 1200-token reservation, the third request already exceeds 2400, explaining the 94 stopped rows in each arm.

There is a second independent accounting defect: the paired command calls `execute_remote()` separately for P2a and P2b, and each invocation initializes `used` to zero.  Even after correcting the total-output key, this does not enforce a shared 192-request/global-token/USD ceiling across the pair.

## Required execution contract

1. Retain distinct names and meanings for per-request ceilings and pair-global reservations.  Use the validated `max_total_input_tokens` / `max_total_output_tokens` for the execution pool; retain the per-request input/output checks separately.
2. Use one shared, persisted pair budget ledger across P2a then P2b (requests, input, output, USD).  The execution ledger must bind the two immutable input-manifest hashes and preflight hash.
3. `budget_stopped` means **not dispatched / resumable interruption**, never a processed model result.  A resume with an enlarged valid budget must retry it, preserving the original stop attempt in history rather than treating its cache row as terminal or overwriting audit evidence.
4. A remote pair may be `complete` only when all 192 locked requests are protocol-verified under the bound manifests.  Any `budget_stopped`, unresolved/truncated request, or unmatched arm member yields `incomplete` (or an explicit terminal failure), with non-success CLI exit/status.  The word `COMPLETE` must not be emitted unconditionally.

The current cache reader accepts `budget_stopped` as a normal cached terminal row, so a simple resume with larger limits would currently replay the 188 stopped outcomes rather than dispatching them.  This must change together with the shared-ledger fix.

## Evidence

- `remote_comparison.json` preflight reservation is `pass` for the global caps above.
- `remote_runs/P2a.json` and `remote_runs/P2b.json` each record `1 protocol_verified`, `1 unresolved`, `94 budget_stopped`.
- `au_baseline/core.py` compares cumulative usage against `budget["max_output_tokens"]`.
- `au_baseline/__main__.py` invokes that routine independently per arm and prints `COMPLETE` after serializing the comparison, regardless of request statuses.

## Scope limit

This identifies an execution/accounting and truthfulness failure.  It does not evaluate model output quality.

## Post-fix independent audit

**PARTIAL PASS / overall FAIL against the full required contract.**

The corrected implementation now uses `max_total_input_tokens` and `max_total_output_tokens` for runtime reservation, and threads one mutable `usage_state` through P2a and P2b.  A local three-request, two-arm fixture with a 2400 total-output cap yielded `protocol_verified`, `protocol_verified`, then `budget_stopped`, with exactly two provider-stub calls.  This demonstrates one shared pool rather than one pool per arm.  The focused Plan 10 suite passed 26 tests, including aggregate-cap, free-cache-hit, and budget-stopped/incomplete tests.

The historical `plan10_warmup_probe_v15` partial artifacts remain present and retain their prior incomplete accounting; no new remote execution was performed during this audit.

Two contract gaps remain:

1. A cached `budget_stopped` row falls through to a retry, which is correct for resumability, but its single `response.json` is then atomically replaced.  The stop attempt is not preserved in an immutable attempt history.  A local resume fixture confirmed the cache entry hash changes.  Therefore a same-root resume can overwrite evidence of the partial run, contrary to the no-overwrite/history-preservation requirement.
2. `_paired_completion()` defines `complete` solely as zero `budget_stopped` rows.  A pair containing unresolved/truncated rows but no stopped rows can still print `COMPLETE`.  If complete means every locked request is protocol-verified, completion must additionally require 192 protocol-verified rows (96 each), zero unresolved rows, and matched arm/request identities.

Until immutable attempt preservation and the stricter completion predicate are added and tested, a resumed production pair must be reported as incomplete/non-final even if all remaining budget-stopped requests dispatch.

## Final P0 re-audit

**PASS for the P0 fix.**

- Before a cached `budget_stopped` row is retried, the runtime now writes an immutable `attempt_history/<ordinal>-<hash>.json` sidecar containing the complete prior row, its canonical hash, request ID, and request hash.  The focused resume test verifies a later protocol-verified cache row while retaining exactly one archived stopped attempt.
- Completion now requires the exact locked request count (`pair_count * 2`, therefore 192 for KOS-5) and `protocol_verified` status for every ledger row.  A budget stop, truncation, provider failure, ordinary unresolved row, or count mismatch produces an explicit incomplete status/reason; the CLI selects `COMPLETE` only for the all-verified branch.
- The focused Plan 10 suite passed 27 tests.  No Modal call was made in this audit.  The historical `plan10_warmup_probe_v15` comparison and per-arm artifacts remain unchanged; its old partial outcome remains historical evidence rather than being relabeled as complete.
