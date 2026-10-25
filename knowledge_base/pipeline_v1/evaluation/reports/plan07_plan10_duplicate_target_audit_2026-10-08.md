# Plan 07 / Plan 10 duplicate AnalysisTarget audit (2026-10-08)

## Scope

Independent local audit only. No Modal invocation, credentials, or production-code edits.

## Finding

The assertion that the problem is only a Plan 10 counting defect is not supported.  The checked-in Plan 07 artifact currently selected by `plan07_analysis_region_validation.latest.json` contains one `AnalysisTarget` in two batches:

| case | target | first work item / span | second work item / span |
| --- | --- | --- | --- |
| `045155` | `at-5929ffb989b919cd1334a0d2` | `ats-9908a121eed93bc7d613f2ec`, `9032:10955`, batch `ab-0dd72abcfe013a27683d9393` | `ats-9804b3e6b29fa3df91247c80`, `10955:11684`, batch `ab-536b2e16ecf6102e2a8b2019` |

Thus P2a places that target in regions `ar-b846fc3b45a358f148ce5aa0` and `ar-b5ef25e0b24d91b48de584b1`; P2b likewise places it in two regions.  The old Plan 07 artifact has 54 target occurrences but only 53 unique target IDs for case `045155`.

The artifact also has four other sliced targets in case `099980` with multiple work items.  They remained in one batch each, so the prior per-region `set(target_id)` hid them at region level.  This is why the old Plan 07 report can simultaneously state 374 work items and 369 primary targets while its case-045155 artifact duplicates one target across two regions.

## Required invariant

The correct identity unit is `(case_id, target_id)`, not `work_item_id` (a sliced target can legitimately have several work items).  It must occur in exactly one batch and exactly one region per arm.  A duplicate must fail closed; it must not be silently deduplicated because that would discard a slice from the model obligation.

## Implementation observed

Current scheduler code groups all work items of a sliced target atomically before batching.  Current Plan 07 validation rejects a target appearing in multiple batches or regions per arm.  Current `build_locked_requests` independently tracks assigned `(case_id, target_id)` and raises `BaselineError` before a request is returned.

The current persisted artifact is stale relative to that code.  Running the focused integration tests against it produced the expected fail-closed evidence:

- Plan 07 build-reader test: `canonical_mismatch` on `batches`.
- Plan 10 setup: `duplicate AnalysisTarget across Plan 10 requests: [('045155', 'at-5929ffb989b919cd1334a0d2')]`.

## Regeneration check

I rebuilt Plan 07 in a temporary directory from the locked KOS-5 inputs, then built both Plan 10 input manifests from that temporary report.  Result:

| check | result |
| --- | --- |
| Plan 07 build | PASS |
| primary targets | 369 |
| work items | 374 |
| batches / requests per arm | 96 |
| P2a target occurrences / unique targets | 369 / 369 |
| P2b target occurrences / unique targets | 369 / 369 |
| paired regions | 96 |

This establishes the new code produces the intended unique target inventory locally, but does not replace the official artifact.  The official Plan 07 output/report must be regenerated and then the focused `test_plan07` and `test_plan10` suite rerun before claiming the persisted pipeline is green.

## Limits

This is a structural/protocol audit only.  It validates neither Authority Unit semantics nor human-gold or retrieval quality.

## Final persisted re-audit (after implementation and regeneration)

**PASS.**  The current `plan07_analysis_region_validation.latest.json` points to the regenerated `analysis-region-policy-v1.5` / `p2-offline-scheduler-v1.5` artifact, whose build manifest carries the same scheduler version and policy hash.

Direct recount of the persisted artifacts and Plan 10 locked input manifests produced:

| arm | target occurrences | unique `(case_id, target_id)` | requests |
| --- | ---: | ---: | ---: |
| P2a | 369 | 369 | 96 |
| P2b | 369 | 369 | 96 |

There are no duplicate target IDs in any case/arm.  Case `045155` now has 53 occurrences and 53 unique targets for each arm; the prior duplicated target is absent.  The paired manifest contains 96 matched regions.

`python -m unittest knowledge_base.pipeline_v1.tests.test_plan07 knowledge_base.pipeline_v1.tests.test_plan10 -v` passed all 38 tests.  This includes the crafted duplicate checks: Plan 07 rejects a sliced target split across a batch/region boundary, and Plan 10 raises before any provider dispatch when one target would occur in two locked requests.

The prior stale-artifact finding remains historical evidence only; it is not a current persisted-artifact failure.
