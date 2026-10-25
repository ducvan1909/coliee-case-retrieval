# P09-R3 model review: queue positions 11–20

Model: `gpt-6.1-sol`. Scope: the next ten `pending_model_review` items in existing stable order. Positions 1–10 are not re-reviewed. No missing target in `099980` is annotated.

Evidence method: each complete target is reopened through `open_source`, preserving CRLF and the locked source hash, together with 850 characters of neighboring source on each side. Queue cues are routing signals, not labels. Exact quotes, offsets, source SHA-256, original proposal byte SHA-256 and reasons are persisted in individual review records.

| Position / case | Target ID | Decision | Evidence and reason |
|---|---|---|---|
| 11 / 011904 | at-a5b5b0fdf3bab9574aa4429e | keep | Paragraph 26: court contrast between state efforts and effective protection; paragraphs 25–27 confirm the applied reasoning. |
| 12 / 013009 | at-08bf65c4ca25403730d5353c | amendment | Paragraph 4 first sentence is the court finding. Narrow evidence/attribution to it, excluding the ensuing officer quotation; paragraphs 3 and 5 confirm the omission. |
| 13 / 013009 | at-fad288640dd0c7aa6b551320 | keep | Paragraph 6 explicitly calls the officer finding unreasonable and wrong; paragraph 5 provides the letter. |
| 14 / 013009 | at-5522df4fca96eee9c7176c4c | amendment | Paragraph 17 supports this case-specific holding, not a universal disposition rule. Make that scope explicit. |
| 15 / 013009 | at-6fd1350b5e4ed36850040c15 | amendment | Paragraph 3 begins “In this case”; scope claim to this H&C application and its identified errors. |
| 16 / 013009 | at-79ddc136c68ac1dccc949df4 | amendment | Paragraph 12 says withdrawn/dismissed charges, not pending charges. Correct claim scope, preserve the criminality-alone restriction and separate appellate quotation from court adoption. Paragraph 14 confirms fair consideration of pending charges is permitted. |
| 17 / 013009 | at-81ed7da8dd8cb3dab2bdd33e | amendment | Paragraph 15 applies authority to this officer and applicant. Set holding rather than generalized fact-pattern rule, preserve “does not appear”, and narrow attribution to the court comparison. |
| 18 / 013009 | at-d1a9498ecd408d28317aa793 | amendment | Paragraph 16 expressly says “In my view”. Scope claim/evidence to this court inference and avoid merging the ensuing cited quotation into the speaker witness. |
| 19 / 013009 | at-f4a073144323210976dace57 | amendment | Paragraph 14 rejects a blanket prohibition. Preserve permitted consideration, procedural fairness limit and separate adopted/quoted proposition witnesses. |
| 20 / 013948 | at-085b9017aac39b55a1c66d99 | amendment | Paragraph 14 interprets section 163. Preserve statutory_hook; add exact late-application condition and no decision-time restriction witnesses. |

Record/ref convention: `outputs/plan09_au_gold_v1/risk_reviews/p09-r3-second10-{position}-gpt61sol-v1.json`; changed items additionally have the matching `model_amendments/` file. All ten concrete refs and their hashes/offsets are listed in `outputs/plan09_au_gold_v1/remediation_r3_second10_validation.json`. Eight new moderate findings remain pending independent audit.

Checkpointing uses existing `checkpoint_risk_review` and `checkpoint_amendment`: immutable individual records are atomically written in queue order; queue and progress snapshots are derived and rebuildable. Original proposals and prior review records are preserved. This is not an atomic multi-file database transaction.

Batch result: 2 keep, 8 amendments, 0 newly unresolved. Queue remains 49 total; 20 model-reviewed pending independent audit, 29 pending model review. Effective overlay remains 97 AUs, 112 hard negatives, 3 unresolved; coverage remains 212/369, with all 157 missing IDs unchanged. Plan 10 stays locked. No human gold, semantic PASS or independent-audit completion is claimed.

Verification: 27/27 tests PASS in 62.520 seconds across second-batch, risk-review, remediation, Plan 09 and existing independent infrastructure tests. All ten persisted reviews and eight new amendments were validated; queue and progress rebuilt exactly; original proposal bytes and previous review records were checked unchanged. CLI `validate-risk-review` also passes for position 20, recorded in `remediation_r3_second10_cli_validation.json`. These are contract/infrastructure checks, not a new independent semantic audit. The full unrelated pipeline suite was not rerun.
