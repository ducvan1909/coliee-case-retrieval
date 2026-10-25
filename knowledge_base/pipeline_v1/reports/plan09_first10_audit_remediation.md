# First-ten audit remediation: items 02, 06 and 10 only

Model lane: `gpt-6.1-sol`, model-silver, not human gold. No pending item or missing target was processed. Independent acceptance is not asserted and P09-S01 is not closed.

## Audit binding and corrections

Input audit: [independent semantic audit](../evaluation/reports/plan09_r3_first10_independent_semantic_audit.json). Its audited-record SHA-256 values match the actual historical first-ten review files for all three items. The audit file itself is preserved; its hash and all correction refs are recorded in [validation artifact](../outputs/plan09_au_gold_v1/remediation_first10_audit_validation.json).

| Finding | Correction | Persisted review head / amendment |
|---|---|---|
| 02: missing developed-democracy and danger qualifications; target `at-2f7477cfb9547856d31ae73a` | Paragraph 16 claim now explicitly scopes the high burden to claimants from developed democratic states and treats required danger as an exceptional circumstance. Exact condition, exception and limit witnesses are recorded. Historical decision was `keep`, not an existing amendment. | `risk_reviews/p09-r3-first10-audit-02-gpt61sol-v2.json`; `model_amendments/p09-r3-first10-audit-02-gpt61sol-v2.json` (new primary v1 amendment against original proposal). |
| 06: alleged quote normalization; target `at-c6800dac79406967a0f487af` | Rebuilt target `[15576,16864)` and context `[15076,17364)` exclusively from `open_source`. **The alleged mismatch does not reproduce at the audited hashes.** Both original record and raw source contain U+00E9, and original quotes already pass exact-span validation. No replacement character was inserted to satisfy a console rendering. Semantic `keep` is preserved; independent audit reconciliation is still needed. | `risk_reviews/p09-r3-first10-audit-06-gpt61sol-v2.json`; no label amendment. |
| 10: over-conservative unresolved; target `at-8269eb428258043e32dca5a8` | Restore narrow `holding/current_court`: the court found the Board faced abundant evidence indicating protective measures for this principal applicant were ineffective. Evidence is the final sentence of paragraph 27, not the preceding Board conclusion. Paragraph 34 is reopened as contextual support. No universal claim about Mexican protection is made. | `risk_reviews/p09-r3-first10-audit-10-gpt61sol-v2.json`; `model_amendments/p09-r3-first10-audit-10-gpt61sol-v2.json` explicitly supersedes the old unresolved amendment. |

All refs above are relative to `outputs/plan09_au_gold_v1/`. Registry entries `P09-R3-AUDIT-02` and `P09-R3-AUDIT-10` remain `amended_pending_independent_audit`. Item 06's structural finding is marked **not reproduced**, not independently accepted or closed.

## Item 06 code-point evidence

At immutable source hash `c2bc7c0944a5ee103368055f7d2f0e3c260d4bb8336d406c3d01733304c96b12`, `open_source` yields `M\u00e9xico` with code points `[77,233,120,105,99,111]`. The audited record hash `570d9ea4bfc62d4f45b69ee0af17ad335bb1b82c7527c3a3a0c607cedb47c795` yields the same string. Target/context quote strings, lengths and text SHA-256 values match raw source exactly. U+FFFD is not present in that word. This evidence contradicts the audit prose; a display/transport encoding issue is a possible explanation, not a proven cause. Source bytes were not normalized or modified.

## Immutable history contract

Amendment v2 requires `supersedes_amendment_id` and predecessor byte SHA-256, in addition to the original proposal SHA-256. Review revisions similarly require `supersedes_review_id` and byte SHA-256. Target/source/proposal identities must match, and checkpointing must supersede the current head. Forks, duplicate roots, missing parents, parent hash changes and cycles are rejected. Effective overlays select validated lineage heads, not whichever filename sorts last. Historical files remain unchanged and remain addressable.

The new `checkpoint-risk-review-revision` CLI corrects an already-reviewed item; it does not consume the next pending queue entry. Only active review heads contribute to reviewed counts. Superseded review files are retained but are not silently treated as independent valid/accepted evidence.

## Revalidation and state

Three new review heads and the effective first-ten snapshot pass exact source/proposal validation. Queue and progress reproduce from the immutable histories. Queue stays **30 reviewed / 19 pending**, 49 total. Effective counts become **98 AU / 112 hard negatives / 2 unresolved**, reflecting restoration of item 10. Coverage stays **212/369**, with the same **157 missing IDs**. All pre-existing proposal, amendment and review bytes pass preservation checks. P09-S01 remains open; Plan 10 stays locked.

The original first-ten validation report and earlier batch reports are historical snapshots, not overwritten current acceptance claims. Current first-ten evidence and validation are in `remediation_first10_audit_validation.json`. Independent reviewers must re-audit these heads and reconcile item 06 before whole-batch acceptance.

Verification: **33/33 related tests PASS** in 131.354 seconds: revision-history, risk-review, remediation, second/third batch, Plan 09 and existing independent infrastructure tests. Tests exercise exact-quote normalization rejection, predecessor hash/identity binding, fork rejection, immutable retry, active-head selection and queue/progress reproducibility. CLI validation of the revised item 10 passes and is recorded in `remediation_first10_audit_cli_validation.json`. The preflight self-parent fixture initially exposed a missing guard; the guard was repaired and the final suite passes. No unrelated full pipeline suite was rerun.
