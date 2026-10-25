# Plan 09 P09-R1–R3 independent evaluation

Date: 2026-10-05

## Verdict

| Gate | Verdict | Evidence |
|---|---|---|
| P09-R1 — quarantine known finding | **PASS after gate fix** | P09-S01 is a severe open finding with exact evidence and canonical proposal digest; the original proposal is unchanged; progress exposes one quarantined target; silver lock returns `silver_semantic_quarantine`. |
| P09-R2 — offline attribution-risk queue | **PASS** | The scanner deterministically reproduces the checked-in 49-item queue, including P09-S01; all cue spans verify against raw source; all 49 items remain `pending_model_review`; proposal hashes are unchanged and `labels_changed=false`. |
| P09-R3 — review and amendment closure | **FAIL / incomplete** | The amendment is structurally valid and the effective view conservatively changes P09-S01 from a positive AU to label-free `unresolved`, preserving its model-review provenance boundary. However, P09-S01 remains `quarantined_pending_review`, the severe finding remains open, and the other 48 risk items have not been reviewed. The R3 completion criterion—P09-S01 closed and no open severe findings—is not met. |

The implementation therefore supports safe quarantine and resumable remediation, but the statement that P09-R1 through P09-R3 are all complete is not supported by the artifacts.

## Independent checks

### Original proposal and effective overlay

- Canonical proposal `terra-013948-aafb64c3e03c512941a071a8` still has its original byte digest `dac1d941aa08722a8c9875bef1c1bba8d54c43e8c21c06d5ab80308bd7a0c666` and original P09-S01 outcome `positive`.
- Amendment `p09-s01-gpt6-unresolved-v1` references that digest, validates against the packet/raw source, and does not overwrite the proposal.
- The effective overlay has `model_outcome=unresolved`, no AU, and no hard negative. Thus unresolved is not counted as a hard negative.
- Effective progress is reproducible: 212 reviewed, 157 missing, 98 AUs, 112 hard negatives, 2 unresolved, one open severe finding, one amendment, and `plan10_allowed=false`.

### Scanner

- Generated queue equals `attribution_risk_queue.json` exactly.
- 49 queue items correspond to 49 unique case/target pairs; 27 carry `holding_current_court_reporting_risk`.
- Every queue item is still `pending_model_review`. Cue matching only routes review and makes no label mutation.

### Silver lock defect found and fixed

Before this audit, a severe finding could be changed to `closed` and supplied with any non-empty `independent_review_ref`; `assert_lockable` accepted it without proving that the review or resolving amendment existed. This could bypass quarantine through a fabricated registry edit.

The gate now requires, for each closed severe finding:

1. a named resolution amendment and independent-review reference;
2. both referenced files to exist;
3. the amendment to pass validation and match the finding/proposal/target;
4. the replacement outcome to be final rather than `unresolved`.

No semantic label or model proposal was changed by this fix.

## Tests

- New independent remediation tests: **4/4 PASS** in 2.508 s.
- Plan 09 and remediation unit tests: **18/18 PASS** in 5.766 s.
- Full pipeline regression suite: **111/111 PASS** in 90.555 s.

## Remaining gates

1. Review all 49 attribution-risk targets from raw source and neighboring context; currently none is marked reviewed in the queue.
2. Obtain an independent disposition for P09-S01. If disagreement remains, keep it unresolved and severe/open; do not close it merely because the erroneous AU is absent from the effective view.
3. Record a verifiable final amendment plus independent-review record before changing the finding to `closed`.
4. Complete the 157 missing targets in `099980`; incomplete coverage must continue to block silver lock.
5. Continue to treat the result as model silver, not human gold. Plan 10 remains locked.

